"""Win32 pointer and monitor geometry, imported lazily by the receiver so the
crossing logic stays testable without ctypes.windll. GetCursorPos, SetCursorPos
and GetSystemMetrics share one coordinate space — virtual-desktop pixels,
DPI-virtualised identically for this process — so values from one feed the
others unconverted."""

import ctypes
import logging
import sys
from typing import List, Tuple

from return_edge import Rect

_IS_WINDOWS = sys.platform == "win32"
user32 = ctypes.WinDLL("user32", use_last_error=True) if _IS_WINDOWS else None
LOGGER = logging.getLogger(__name__)

class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


if _IS_WINDOWS:
    MONITORENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(RECT), ctypes.c_ssize_t)
    user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
    user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
    user32.EnumDisplayMonitors.argtypes = [ctypes.c_void_p, ctypes.c_void_p, MONITORENUMPROC, ctypes.c_ssize_t]


def _require() -> None:
    if user32 is None:
        raise RuntimeError("Win32 desktop geometry is only available on Windows")


def monitors() -> List[Rect]:
    _require()
    found: List[Rect] = []

    def collect(_monitor, _dc, rect, _lparam):
        r = rect.contents
        found.append(Rect(r.left, r.top, r.right - r.left, r.bottom - r.top))
        return 1

    if not user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(collect), 0):
        raise ctypes.WinError(ctypes.get_last_error())
    return found


def cursor_position() -> Tuple[int, int]:
    _require()
    point = POINT()
    if not user32.GetCursorPos(ctypes.byref(point)):
        raise ctypes.WinError(ctypes.get_last_error())
    return point.x, point.y


class CURSORINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_ulong), ("flags", ctypes.c_ulong), ("hCursor", ctypes.c_void_p), ("ptScreenPos", POINT)]


SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN, SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 76, 77, 78, 79


def _cursor_flags() -> int:
    info = CURSORINFO(cbSize=ctypes.sizeof(CURSORINFO))
    return info.flags if user32.GetCursorInfo(ctypes.byref(info)) else -1


def set_cursor_position(x: int, y: int) -> None:
    """SetCursorPos failed with no error code for every arrival after the rig
    rebooted on 21-09-2026, while the Mac's relative moves drew nothing either,
    until the physical mouse was touched. An absolute SendInput move takes the
    path real hardware does, so it is the fallback rather than giving up."""
    _require()
    if user32.SetCursorPos(int(x), int(y)):
        return
    error = ctypes.get_last_error()
    import input_injector

    left, top = user32.GetSystemMetrics(SM_XVIRTUALSCREEN), user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    width, height = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN), user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
    input_injector.inject_mouse_absolute(
        round((x - left) * 65535 / max(width - 1, 1)),
        round((y - top) * 65535 / max(height - 1, 1)),
    )
    LOGGER.warning(
        "SetCursorPos refused (error %s, cursor flags %s); moved to %s,%s with SendInput instead",
        error, _cursor_flags(), x, y,
    )
