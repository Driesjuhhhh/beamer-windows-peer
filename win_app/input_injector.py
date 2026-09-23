"""Win32 SendInput keyboard and mouse injection."""

import ctypes
import functools
import logging
import sys
import threading
from typing import Callable, Dict, List, Optional, Set, Tuple


LOGGER = logging.getLogger(__name__)

_IS_WINDOWS = sys.platform == "win32"

user32 = ctypes.WinDLL("user32", use_last_error=True) if _IS_WINDOWS else None

if _IS_WINDOWS:
    user32.VkKeyScanW.restype = ctypes.c_short
    user32.VkKeyScanW.argtypes = [ctypes.c_wchar]
    user32.MapVirtualKeyW.restype = ctypes.c_uint
    user32.MapVirtualKeyW.argtypes = [ctypes.c_uint, ctypes.c_uint]

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

# Stamped into the dwExtraInfo of every INPUT this module sends, and the same
# value the Mac stamps into kCGEventSourceUserData. Raw Input has no injected
# flag: a SendInput move reaches a WM_INPUT sink exactly as the hand's does,
# hDevice NULL, and this value coming back in RAWMOUSE.ulExtraInformation is
# the only thing that tells the two apart (proved on the rig, 19-09-2026).
INJECTED_MARK = 0xBEA3

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

MAPVK_VK_TO_VSC = 0

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000
MOUSEEVENTF_VIRTUALDESK = 0x4000
MOUSEEVENTF_ABSOLUTE = 0x8000

ULONG_PTR = ctypes.c_size_t


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ULONG_PTR),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("union", _INPUTUNION)]


def _send_input(*inputs: INPUT) -> None:
    if user32 is None:
        raise RuntimeError("Win32 SendInput is only available on Windows")
    count = len(inputs)
    array = (INPUT * count)(*inputs)
    sent = user32.SendInput(count, array, ctypes.sizeof(INPUT))
    if sent != count:
        raise ctypes.WinError(ctypes.get_last_error())


def _vk_key_scan(ch: str) -> int:
    """Look up the VK + shift-state byte for a character via VkKeyScanW.

    Returns the raw 16-bit result (low byte VK, high byte shift state) or
    -1 if the character can't be produced by the current keyboard layout.
    """
    if user32 is None:
        raise RuntimeError("VkKeyScanW is only available on Windows")
    return user32.VkKeyScanW(ch)


def _map_virtual_key(vk: int) -> int:
    """Look up the hardware scan code for a virtual-key code."""
    if user32 is None:
        raise RuntimeError("MapVirtualKeyW is only available on Windows")
    return user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)


VK_MAP = {
    "enter": 0x0D,
    "return": 0x0D,
    "esc": 0x1B,
    "escape": 0x1B,
    "tab": 0x09,
    "space": 0x20,
    "backspace": 0x08,
    "delete": 0x2E,
    "home": 0x24,
    "end": 0x23,
    "page_up": 0x21,
    "page_down": 0x22,
    "up": 0x26,
    "down": 0x28,
    "left": 0x25,
    "right": 0x27,
    "shift": 0xA0,
    "shift_r": 0xA1,
    "ctrl": 0xA2,
    "ctrl_r": 0xA3,
    "alt": 0xA4,
    "alt_r": 0xA5,
    "cmd": 0x5B,
    "cmd_r": 0x5C,
    "caps_lock": 0x14,
    "insert": 0x2D,
    "menu": 0x5D,
    "num_lock": 0x90,
    "scroll_lock": 0x91,
    "print_screen": 0x2C,
    "pause": 0x13,
    "media_play_pause": 0xB3,
    "media_next": 0xB0,
    "media_prev": 0xB1,
    "media_stop": 0xB2,
    "volume_mute": 0xAD,
    "volume_down": 0xAE,
    "volume_up": 0xAF,
    "browser_back": 0xA6,
    "browser_forward": 0xA7,
}

for _index in range(1, 13):
    VK_MAP[f"f{_index}"] = 0x70 + (_index - 1)
for _index in range(13, 21):
    VK_MAP[f"f{_index}"] = 0x7C + (_index - 13)

# Named keys that require the extended-key flag (E0 scan prefix) so games,
# RDP sessions and low-level keyboard hooks read them correctly.
EXTENDED_KEYS = {
    "up",
    "down",
    "left",
    "right",
    "insert",
    "delete",
    "home",
    "end",
    "page_up",
    "page_down",
    "ctrl_r",
    "alt_r",
    "cmd",
    "cmd_r",
    "num_lock",
    "print_screen",
    "media_play_pause",
    "media_next",
    "media_prev",
    "media_stop",
    "volume_mute",
    "volume_down",
    "volume_up",
    "browser_back",
    "browser_forward",
}

# Modifier key names that participate in chording with character keys.
MODIFIER_KEYS = {"ctrl", "ctrl_r", "alt", "alt_r", "cmd", "cmd_r", "shift", "shift_r"}

# Either shift key satisfies a VkKeyScanW "shift required" result: the Mac
# forwards shift physically as its own keydown/keyup, so if one is currently
# held, the keyboard state agrees with what VkKeyScanW resolved the
# character from.
SHIFT_KEYS = {"shift", "shift_r"}

VkLookup = Callable[[str], int]
ScanLookup = Callable[[int], int]

# Characters we've already logged an unsupported-combo warning for, so we
# don't spam the log for every repeat keypress.
_warned_chars: Set[str] = set()


def _keybd_input(vk: int, scan: int, flags: int) -> INPUT:
    key_input = KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=flags, time=0, dwExtraInfo=INJECTED_MARK)
    return INPUT(type=INPUT_KEYBOARD, union=_INPUTUNION(ki=key_input))


def plan_key_inputs(
    name: str,
    down: bool,
    mods_down: Set[str],
    char_vk_down: Dict[str, int],
    vk_lookup: VkLookup,
    scan_lookup: ScanLookup,
) -> List[Tuple[int, int, int]]:
    """Pure planning logic: decide which (wVk, wScan, flags) tuples to send.

    Mutates mods_down / char_vk_down to track state across calls, exactly
    like inject_key does, so callers (tests) can inspect the bookkeeping.
    Returns an empty list if the key should be dropped.
    """
    keyup_flag = 0 if down else KEYEVENTF_KEYUP
    lowered = name.lower()

    if lowered in MODIFIER_KEYS:
        if down:
            mods_down.add(lowered)
        else:
            mods_down.discard(lowered)

    # Named key (arrows, modifiers, function keys, etc.)
    if lowered in VK_MAP:
        vk = VK_MAP[lowered]
        scan = scan_lookup(vk)
        flags = keyup_flag
        if lowered in EXTENDED_KEYS:
            flags |= KEYEVENTF_EXTENDEDKEY
        return [(vk, scan, flags)]

    # Single character. Prefer the real VK+scan keystroke path whenever the
    # current keyboard layout can produce it plainly, or with only the shift
    # state the Mac is already physically forwarding -- not just when a
    # chord modifier (ctrl/alt/win) happens to be held. A bare character
    # sent purely as KEYEVENTF_UNICODE produces WM_CHAR-style text but no
    # usable keyCode, so anything listening for a real keydown (games, media
    # shortcuts like YouTube's "k" to pause) never sees it, even though a
    # text field happily receives the character. Unicode remains the
    # fallback for whatever the VK path can't safely cover.
    if len(name) == 1:
        ch = name
        if not down:
            if ch in char_vk_down:
                vk = char_vk_down.pop(ch)
                scan = scan_lookup(vk)
                return [(vk, scan, KEYEVENTF_KEYUP)]
            return [(0, ord(ch), KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)]

        result = vk_lookup(ch)
        if result == -1:
            if ch not in _warned_chars:
                LOGGER.warning("Unsupported character for this keyboard layout: %r", ch)
                _warned_chars.add(ch)
            return [(0, ord(ch), KEYEVENTF_UNICODE | keyup_flag)]

        vk = result & 0xFF
        shift_state = (result >> 8) & 0xFF
        shift_only = shift_state == 0x01
        if shift_state == 0 or (shift_only and mods_down & SHIFT_KEYS):
            scan = scan_lookup(vk)
            char_vk_down[ch] = vk
            return [(vk, scan, keyup_flag)]
        if shift_state & 0xFE:
            # Needs ctrl/alt (AltGr) or some other combo bit we can't
            # fabricate without also toggling a modifier the user isn't
            # actually holding.
            if ch not in _warned_chars:
                LOGGER.warning("Combo not possible for this character on this layout: %r", ch)
                _warned_chars.add(ch)
        # else: shift is required but not currently held -- e.g. a capital
        # produced by caps-lock rather than a physical shift press. Trusting
        # the VK here would desync from the real keyboard state, so this
        # falls back to Unicode silently (it's not a broken layout, just a
        # state VkKeyScanW can't be told about); typing stays correct.
        return [(0, ord(ch), KEYEVENTF_UNICODE | keyup_flag)]

    LOGGER.warning("Unknown key name ignored: %r", name)
    return []


_mods_down: Set[str] = set()
_char_vk_down: Dict[str, int] = {}
# One lock over the held-key bookkeeping and the send it describes: a session
# thread injecting while a reconnect's release_all snapshots and clears would
# otherwise press a key that nothing then remembers to release.
_state_lock = threading.RLock()


def _locked(function):
    @functools.wraps(function)
    def wrapper(*args, **kwargs):
        with _state_lock:
            return function(*args, **kwargs)

    return wrapper


@_locked
def inject_key(name: str, down: bool) -> None:
    LOGGER.debug("key %s %s (mods held: %s)", name, "down" if down else "up", sorted(_mods_down))
    plan = plan_key_inputs(name, down, _mods_down, _char_vk_down, _vk_key_scan, _map_virtual_key)
    if not plan:
        return
    _send_input(*(_keybd_input(vk, scan, flags) for vk, scan, flags in plan))


def _mouse_input(dx: int, dy: int, data: int, flags: int) -> INPUT:
    mouse_input = MOUSEINPUT(dx=dx, dy=dy, mouseData=data, dwFlags=flags, time=0, dwExtraInfo=INJECTED_MARK)
    return INPUT(type=INPUT_MOUSE, union=_INPUTUNION(mi=mouse_input))


def inject_mouse_move(dx: int, dy: int) -> None:
    _send_input(_mouse_input(dx, dy, 0, MOUSEEVENTF_MOVE))


def inject_mouse_absolute(nx: int, ny: int) -> None:
    """nx, ny normalised 0-65535 across the whole virtual desktop."""
    _send_input(_mouse_input(nx, ny, 0, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK))


BUTTON_DOWN_FLAGS = {
    "left": MOUSEEVENTF_LEFTDOWN,
    "right": MOUSEEVENTF_RIGHTDOWN,
    "middle": MOUSEEVENTF_MIDDLEDOWN,
}

BUTTON_UP_FLAGS = {
    "left": MOUSEEVENTF_LEFTUP,
    "right": MOUSEEVENTF_RIGHTUP,
    "middle": MOUSEEVENTF_MIDDLEUP,
}


_buttons_down: Set[str] = set()


@_locked
def inject_mouse_button(button: str, down: bool) -> None:
    flags = (BUTTON_DOWN_FLAGS if down else BUTTON_UP_FLAGS).get(button)
    if flags is None:
        LOGGER.warning("Unknown mouse button ignored: %r", button)
        return
    if down:
        _buttons_down.add(button)
    else:
        _buttons_down.discard(button)
    _send_input(_mouse_input(0, 0, 0, flags))


@_locked
def release_all() -> None:
    """Let go of every key and button this module is holding, the twin of
    input_injector_mac.release_all: the receiver calls it when the peer's
    input goes home or its link dies, so a modifier held through a switch
    does not stay down on this PC."""
    for name in sorted(_mods_down):
        try:
            inject_key(name, down=False)
        except Exception:
            LOGGER.exception("Could not release %r", name)
    for ch in sorted(_char_vk_down):
        try:
            inject_key(ch, down=False)
        except Exception:
            LOGGER.exception("Could not release %r", ch)
    for button in sorted(_buttons_down):
        try:
            inject_mouse_button(button, down=False)
        except Exception:
            LOGGER.exception("Could not release the %s mouse button", button)
    _mods_down.clear()
    _char_vk_down.clear()
    _buttons_down.clear()


# Continuous (trackpad) scroll deltas arrive in points, not wheel "clicks".
# This converts px -> the same 120-per-notch wheel-unit scale a discrete
# click uses, so pixel-mode motion feels proportionate to line-mode motion.
# Tunable: raise it to make trackpad scrolling slower, lower it for faster.
WHEEL_UNITS_PER_PIXEL = 120 / 40  # 3.0

# Fractional wheel units carried across calls, per axis, for pixel-mode
# scroll (see plan_scroll_units). Module state, like _mods_down/_char_vk_down
# above: there is one physical scroll wheel to drive, regardless of how many
# scroll messages arrive.
_scroll_accum = [0.0, 0.0]  # [y, x]


def plan_scroll_units(dy, dx, mode: str, accum: List[float]) -> Tuple[int, int]:
    """Pure planning logic: decide the whole wheel-unit deltas to send for one
    scroll event, given accumulator state `accum` (a mutable [y, x] pair,
    mutated in place so callers/tests can inspect the carried residue exactly
    like inject_scroll does). Returns (whole_y, whole_x); either may be 0,
    meaning nothing to send on that axis for this event.

    mode "line": dy/dx are whole wheel clicks (as sent by a discrete mouse
    wheel); each maps to +/-120 wheel units -- unchanged from before dx/mode
    existed.

    mode "pixel": dy/dx are continuous trackpad point deltas; converted to
    wheel units via WHEEL_UNITS_PER_PIXEL and accumulated across calls so
    slow, precise motion isn't lost to integer truncation.

    Sign convention: the vertical mapping below (dy -> +120 per unit) is
    intentionally unchanged from today's dy*120 behaviour, whatever that
    already works out to with Mac natural scrolling. MOUSEEVENTF_HWHEEL's
    positive mouseData means "scroll right" (the mirror of
    MOUSEEVENTF_WHEEL, where positive means "scroll up/away"); dx is
    forwarded without an extra sign flip, on the assumption that a rightward
    two-finger swipe on the Mac should scroll content right on Windows, the
    same direction it would on the Mac itself. That assumption -- and the
    WHEEL_UNITS_PER_PIXEL constant above -- still needs confirming on real
    trackpad/mouse hardware; both are easy to retune if the felt direction or
    speed is wrong.
    """
    if mode == "pixel":
        accum[0] += dy * WHEEL_UNITS_PER_PIXEL
        accum[1] += dx * WHEEL_UNITS_PER_PIXEL
    else:
        accum[0] += int(dy) * 120
        accum[1] += int(dx) * 120
    whole_y = int(accum[0])
    whole_x = int(accum[1])
    accum[0] -= whole_y
    accum[1] -= whole_x
    return whole_y, whole_x


def inject_scroll(dy, dx=0.0, mode: str = "line") -> None:
    whole_y, whole_x = plan_scroll_units(dy, dx, mode, _scroll_accum)
    if whole_y:
        _send_input(_mouse_input(0, 0, whole_y, MOUSEEVENTF_WHEEL))
    if whole_x:
        _send_input(_mouse_input(0, 0, whole_x, MOUSEEVENTF_HWHEEL))


# What each Mac gesture becomes here: first a real touchpad swipe, replayed
# through a synthetic Precision Touchpad so this PC's own Settings > Touchpad
# choices apply and Task View animates as it would under fingers; if that
# device cannot be made, the shortcut that means the same thing by default.
# Finger direction maps 1:1 because content follows the fingers on both
# systems: fingers moving left reveal the desktop on the right, which is
# Win+Ctrl+Right. Launchpad has no touchpad gesture on Windows, so it opens
# Start. "cmd" is the Windows key in VK_MAP.
GESTURE_PLAN: Dict[str, Tuple[Optional[Tuple[int, str]], Tuple[str, ...]]] = {
    "swipe_up": ((3, "up"), ("cmd", "tab")),
    "swipe_down": ((3, "down"), ("cmd", "d")),
    "spread": ((3, "down"), ("cmd", "d")),
    "swipe_left": ((4, "left"), ("cmd", "ctrl", "right")),
    "swipe_right": ((4, "right"), ("cmd", "ctrl", "left")),
    "pinch": (None, ("cmd",)),
}


def inject_gesture(name: str, swipe=None) -> None:
    """`swipe` is touchpad_injector.swipe unless a test passes its own; it
    returns False when Windows refuses, and the chord is pressed instead."""
    plan = GESTURE_PLAN.get(name)
    if plan is None:
        LOGGER.warning("Unknown gesture ignored: %r", name)
        return
    touchpad, chord = plan
    if touchpad is not None:
        if swipe is None:
            import touchpad_injector

            swipe = touchpad_injector.swipe
        if swipe(*touchpad):
            return
    for key in chord:
        inject_key(key, down=True)
    for key in reversed(chord):
        inject_key(key, down=False)
