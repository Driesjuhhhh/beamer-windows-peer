"""Quartz pointer and display geometry, the Mac twin of win_app/desktop_win.py.

`receiver.py` is handed this module and calls the same three functions on
either machine. Coordinates are Quartz global points -- top-left origin, the
space CGDisplayBounds, CGEventGetLocation and CGWarpMouseCursorPosition all
share -- so values from one feed the others unconverted, exactly as the
Win32 twin's do.

Quartz is imported at module level and guarded the same way clipboard_mac
guards AppKit, so this module stays importable, and its behaviour fakeable,
on a machine without it.
"""

from typing import List, Tuple

from return_edge import Rect

try:
    import Quartz
except ImportError:  # pragma: no cover - exercised only off macOS
    Quartz = None

MAX_DISPLAYS = 16


def _require():
    if Quartz is None:
        raise RuntimeError("Quartz display geometry is only available on macOS")
    return Quartz


def monitors() -> List[Rect]:
    quartz = _require()
    error, display_ids, _count = quartz.CGGetActiveDisplayList(MAX_DISPLAYS, None, None)
    if error:
        raise RuntimeError(f"CGGetActiveDisplayList failed with error {error}")
    found: List[Rect] = []
    for display_id in display_ids:
        bounds = quartz.CGDisplayBounds(display_id)
        found.append(
            Rect(
                int(round(bounds.origin.x)),
                int(round(bounds.origin.y)),
                int(round(bounds.size.width)),
                int(round(bounds.size.height)),
            )
        )
    return found


def cursor_position() -> Tuple[int, int]:
    quartz = _require()
    location = quartz.CGEventGetLocation(quartz.CGEventCreate(None))
    return int(round(location.x)), int(round(location.y))


def set_cursor_position(x: int, y: int) -> None:
    quartz = _require()
    status = quartz.CGWarpMouseCursorPosition(quartz.CGPointMake(float(x), float(y)))
    if status:
        raise RuntimeError(f"CGWarpMouseCursorPosition failed with error {status}")
    # A warp normally suppresses hardware mouse input for a quarter of a
    # second so the pointer does not fight the warp. Beamer warps on every
    # held move at the return edge, so leaving that in place would make the
    # Mac's own trackpad feel dead while the PC is driving it.
    quartz.CGAssociateMouseAndMouseCursorPosition(True)
