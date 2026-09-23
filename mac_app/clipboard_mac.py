"""macOS clipboard access via AppKit's NSPasteboard.

`get_contents`/`set_contents` are called from background threads: the
outbound worker (when switching redirect to Windows, to grab the outgoing
clipboard) and the ack-receiver thread (when a clipboard message arrives from
Windows). Apple doesn't document NSPasteboard as thread-safe, but
reading/writing the general pasteboard from a background thread is widely
relied upon in practice and has not shown problems in manual testing. Flagging
here as the one part of this feature that still wants confirmation on a real
machine under load (see the runtime-verification notes in the task writeup).

AppKit is imported at module level (pyobjc is already a hard dependency of
this app -- bridge.py imports Quartz/objc the same way) but guarded so the
module stays importable, and its behaviour fakeable, on a machine without
it: tests replace the module-level `AppKit` attribute with a fake object
rather than mocking imports.
"""

import logging

try:
    import AppKit
except ImportError:  # pragma: no cover - exercised only off macOS
    AppKit = None

LOGGER = logging.getLogger("Beamer")


def _text_from_pasteboard(pasteboard):
    text = pasteboard.stringForType_(AppKit.NSPasteboardTypeString)
    return text if isinstance(text, str) and text else None


def _png_from_pasteboard(pasteboard):
    """PNG bytes for the image on the pasteboard, or None. PNG is taken as
    is; TIFF (what most apps put up, and what a Retina grab carries
    uncompressed at 25MB+) is re-encoded through NSBitmapImageRep, which
    also handles the odd TIFF a Windows consumer would never open."""
    png = pasteboard.dataForType_(AppKit.NSPasteboardTypePNG)
    if png is not None and len(png):
        return bytes(png)
    tiff = pasteboard.dataForType_(AppKit.NSPasteboardTypeTIFF)
    if tiff is None or not len(tiff):
        return None
    rep = AppKit.NSBitmapImageRep.imageRepWithData_(tiff)
    if rep is None:
        return None
    png = rep.representationUsingType_properties_(AppKit.NSBitmapImageFileTypePNG, None)
    return bytes(png) if png is not None and len(png) else None


def get_contents():
    """(text, png) from the general pasteboard, either None when absent.
    Both are read independently and both are sent: an image copied from
    Finder or a browser usually carries a filename or URL as its text, and
    the pasting app on the other side picks the representation it wants,
    exactly as it would from the source clipboard. Never raises."""
    if AppKit is None:
        return None, None
    try:
        pasteboard = AppKit.NSPasteboard.generalPasteboard()
        return _text_from_pasteboard(pasteboard), _png_from_pasteboard(pasteboard)
    except Exception:
        LOGGER.exception("failed to read the macOS clipboard")
        return None, None


def set_contents(text, png):
    """Replace the general pasteboard with `text` and/or `png`. Returns True
    when at least one of them was set, False otherwise. Only the PNG
    representation is written for the image; every current app pastes it,
    and a TIFF alongside would double the memory for nothing. Never raises."""
    if AppKit is None or (text is None and png is None):
        return False
    try:
        pasteboard = AppKit.NSPasteboard.generalPasteboard()
        pasteboard.clearContents()
        wrote = False
        if text is not None:
            wrote |= bool(pasteboard.setString_forType_(text, AppKit.NSPasteboardTypeString))
        if png is not None:
            data = AppKit.NSData.dataWithBytes_length_(png, len(png))
            wrote |= bool(pasteboard.setData_forType_(data, AppKit.NSPasteboardTypePNG))
        return wrote
    except Exception:
        LOGGER.exception("failed to set the macOS clipboard")
        return False
