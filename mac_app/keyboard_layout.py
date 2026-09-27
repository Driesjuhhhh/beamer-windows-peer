"""What each key types on this Mac's current keyboard layout.

The wire carries characters, and two places must turn a key into a character, or a character into
a key, the way the layout printed on the keys does: a shortcut sent to Windows (Cmd+Z has to arrive
as Ctrl+Z on a German Mac, whose Z sits where a US keyboard has Y) and a letter typed from the PC
onto this Mac (posting the US Z key code types "y" on that same Mac). A US table got both wrong for
every layout that moves letters, while US and UK, which share letter positions, never showed it.

The table is read with UCKeyTranslate from the layout's own `uchr` data, with no modifiers, so it
holds the key's unshifted character. Dead keys are left out: posting one starts an accent instead
of typing, so a dead key has no character here and no US one either: a "=" from the PC must not
land on German's accent key, which is where US keeps "=", but be typed as text.

⚠ The Text Input Sources calls must run on the main thread (macOS asserts on it), while the event
tap and the injector read the table from their own threads. So `refresh()` runs on the main thread,
at start and whenever the selected input source changes, and swaps in a new pair of dicts that the
readers only ever look up.
"""

import ctypes
import ctypes.util
import logging
from typing import Dict, Optional

from key_codes import PRINTABLE_KEY_FALLBACKS

LOGGER = logging.getLogger("Beamer")

# The keys worth reading: every key the US table covers, plus the ISO key beside Z (0x0A), which
# the US table has no character for.
LAYOUT_KEY_CODES = tuple(sorted(set(PRINTABLE_KEY_FALLBACKS) | {0x0A}))

INPUT_SOURCE_CHANGED = "com.apple.Carbon.TISNotifySelectedKeyboardInputSourceChanged"

_K_UC_KEY_ACTION_DOWN = 0
_K_UC_KEY_TRANSLATE_NO_DEAD_KEYS = 1

_chars: Dict[int, Optional[str]] = dict(PRINTABLE_KEY_FALLBACKS)
_codes: Dict[str, int] = {}
for _code, _char in sorted(PRINTABLE_KEY_FALLBACKS.items()):
    _codes.setdefault(_char, _code)


def char_for(keycode) -> Optional[str]:
    """The unshifted character `keycode` types on the current layout, or None."""
    return _chars.get(keycode)


def code_for(character) -> Optional[int]:
    """The key that types `character` unshifted on the current layout, or None."""
    return _codes.get(character)


def install(chars: Dict[int, Optional[str]]) -> None:
    """Swaps in a table read from a layout, where a dead key maps to None. Keys the layout leaves
    out keep the US answer, so a shortcut on an unreadable key still goes somewhere sensible."""
    global _chars, _codes
    merged: Dict[int, Optional[str]] = dict(PRINTABLE_KEY_FALLBACKS)
    merged.update(chars)
    codes: Dict[str, int] = {}
    for code, char in sorted(chars.items()):
        if char is not None:
            codes.setdefault(char, code)
    # A US character this layout does not type at all still has somewhere to go; one it types on
    # another key does not keep its US key.
    for code, char in sorted(PRINTABLE_KEY_FALLBACKS.items()):
        if code not in chars and char not in codes:
            codes[char] = code
    _chars, _codes = merged, codes


class _Carbon:
    def __init__(self):
        carbon = ctypes.CDLL("/System/Library/Frameworks/Carbon.framework/Carbon")
        core = ctypes.CDLL(ctypes.util.find_library("CoreFoundation"))
        self.carbon = carbon
        self.core = core
        carbon.TISCopyCurrentKeyboardLayoutInputSource.restype = ctypes.c_void_p
        carbon.TISGetInputSourceProperty.restype = ctypes.c_void_p
        carbon.TISGetInputSourceProperty.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        carbon.LMGetKbdType.restype = ctypes.c_uint8
        carbon.UCKeyTranslate.restype = ctypes.c_int32
        carbon.UCKeyTranslate.argtypes = [
            ctypes.c_void_p, ctypes.c_uint16, ctypes.c_uint16, ctypes.c_uint32, ctypes.c_uint32,
            ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32), ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_uint16),
        ]
        core.CFDataGetBytePtr.restype = ctypes.c_void_p
        core.CFDataGetBytePtr.argtypes = [ctypes.c_void_p]
        core.CFRelease.argtypes = [ctypes.c_void_p]
        self.layout_data_key = ctypes.c_void_p.in_dll(carbon, "kTISPropertyUnicodeKeyLayoutData").value

    def translate(self, layout, keycode, kbd_type, options):
        dead = ctypes.c_uint32(0)
        length = ctypes.c_ulong(0)
        buffer = (ctypes.c_uint16 * 8)()
        status = self.carbon.UCKeyTranslate(
            layout, keycode, _K_UC_KEY_ACTION_DOWN, 0, kbd_type, options,
            ctypes.byref(dead), len(buffer), ctypes.byref(length), buffer,
        )
        if status != 0:
            return None, 0
        text = bytes(bytearray(ctypes.string_at(buffer, 2 * length.value))).decode("utf-16-le", "ignore")
        return text, dead.value

    def layout_chars(self, source) -> Dict[int, Optional[str]]:
        """The table for one input source (a TISInputSourceRef), None for a dead key, and empty
        when it has no `uchr` data."""
        data = self.carbon.TISGetInputSourceProperty(source, self.layout_data_key)
        if not data:
            return {}
        layout = self.core.CFDataGetBytePtr(data)
        kbd_type = self.carbon.LMGetKbdType()
        chars = {}
        for code in LAYOUT_KEY_CODES:
            text, dead = self.translate(layout, code, kbd_type, 0)
            if dead:
                chars[code] = None
                continue
            if text and len(text) == 1 and text.isprintable() and not text.isspace():
                chars[code] = text
        return chars

    def current_chars(self) -> Dict[int, Optional[str]]:
        source = self.carbon.TISCopyCurrentKeyboardLayoutInputSource()
        if not source:
            return {}
        try:
            return self.layout_chars(source)
        finally:
            self.core.CFRelease(source)


_carbon = None


def refresh() -> bool:
    """Main thread only. Re-reads the current layout into the table; on any failure the table
    keeps what it had, and the US answers stay underneath."""
    global _carbon
    try:
        if _carbon is None:
            _carbon = _Carbon()
        chars = _carbon.current_chars()
    except Exception:
        LOGGER.exception("could not read the keyboard layout; keys follow US positions")
        return False
    if not chars:
        LOGGER.info("the keyboard layout has no key table; keys follow US positions")
        return False
    install(chars)
    return True


try:
    import Foundation
except ImportError:  # pragma: no cover - off macOS
    Foundation = None
else:
    class _LayoutObserver(Foundation.NSObject):
        def layoutChanged_(self, _note):
            refresh()


def watch():
    """Main thread. Refreshes now and on every change of input source, which macOS announces on the
    distributed centre and delivers on this thread's run loop. Returns the observer, which the
    caller keeps alive."""
    refresh()
    if Foundation is None:  # pragma: no cover - off macOS
        return None
    observer = _LayoutObserver.alloc().init()
    Foundation.NSDistributedNotificationCenter.defaultCenter().addObserver_selector_name_object_(
        observer, "layoutChanged:", INPUT_SOURCE_CHANGED, None
    )
    return observer
