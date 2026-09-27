"""Win32 pointer and monitor geometry, imported lazily by the receiver so the
crossing logic stays testable without ctypes.windll. GetCursorPos, SetCursorPos
and EnumDisplayMonitors share one coordinate space — virtual-desktop pixels,
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


_refused_under = [None]


def set_cursor_position(x: int, y: int) -> None:
    """SetCursorPos returns FALSE with no error code, and SendInput is dropped
    in silence, whenever Windows' UIPI puts the foreground window above
    Beamer's integrity level, so a SendInput move is no fallback. The one such
    window seen so far is GameInput's (see input_injector); for it the
    placement runs again once the service has been restarted, and anything
    else in front is named in the log."""
    _require()
    x, y = int(x), int(y)
    if user32.SetCursorPos(x, y):
        _refused_under[0] = None
        return
    error = ctypes.get_last_error()
    import input_injector

    # Placed through this function again, so a refusal after the restart is logged too.
    if input_injector.release_gameinput_foreground(after=lambda: set_cursor_position(x, y)):
        return
    blocker = input_injector.foreground_class()
    # A hold at the return edge lands here on every move, so once per blocker.
    if blocker != _refused_under[0]:
        _refused_under[0] = blocker
        LOGGER.warning(
            "SetCursorPos refused (error %s) with %r in the foreground; Windows refuses Beamer's input "
            "while a window above its integrity level is in front, until a click on this PC",
            error, blocker,
        )
