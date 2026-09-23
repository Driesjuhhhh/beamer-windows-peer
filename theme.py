"""Vernier theming for the macOS sender.

Wraps tokens.py, the one home for every colour, size and face both apps draw with, so no hex value
is written twice. Dark only, by design: the window pins to the palette and does not follow the
system appearance.
"""

from __future__ import annotations

from pathlib import Path

import AppKit

import tokens

T: dict[str, str] = tokens.tokens()
PALETTE = tokens.PALETTE
PALETTES = tokens.PALETTES
TYPE = tokens.TYPE
RADIUS = tokens.RADIUS
TRACKING = tokens.TRACKING
MODULE_PADDING = tokens.MODULE_PADDING
RACK_GAP = tokens.RACK_GAP
MIN_WINDOW = tokens.MIN_WINDOW["mac"]

# Derived here rather than added to the shared tokens: the mock's negative tracking on the large
# display figures, the looser tracking on the mono permission state, and the peer name, which has
# to fit a third of the status module at 640.
TIGHT = {"status_word": -0.03, "readout": -0.04, "numeral": -0.05}
STATE_TRACKING = 0.06
PEER_SIZE = 17.0
PEER_SIZE_NARROW = 14.0
# The lit edge of the resistance preview's little screen at rest, so it reads as a screen and
# not as an empty field.
PREVIEW_REST = 0.18
# The sidebar and its pages. The sidebar gives up to 30pt toward the minimum window so the page
# keeps its width; the page title is the one large Hanken Grotesk line on each page. Padding is
# top, leading, bottom, trailing.
SIDEBAR_WIDTH = (150.0, 180.0)
SIDEBAR_WORD = 15.0
PAGE_TITLE = 26.0
PAGE_TITLE_NARROW = 22.0
PAGE_PADDING = (28.0, 32.0, 36.0, 32.0)
PAGE_PADDING_NARROW = (22.0, 22.0, 28.0, 22.0)
MODULE_GAP = 20.0

_sans = "SF Pro Text"
_mono = "SF Mono"

# NSFontManager's 0-15 weight scale, against the numeric weights the tokens name.
_MANAGER_WEIGHTS = {400: 5, 500: 6, 600: 8, 700: 9}
_SYSTEM_WEIGHTS = {
    400: AppKit.NSFontWeightRegular,
    500: AppKit.NSFontWeightMedium,
    600: AppKit.NSFontWeightSemibold,
    700: AppKit.NSFontWeightBold,
}

_FONT_SOURCE = Path(__file__).resolve().parent / "win_app" / "assets"


def _register_source_fonts() -> None:
    """The bundle carries the faces under ATSApplicationFontsPath, which macOS registers before the
    app runs. From source nothing does, so the same files the Windows receiver ships are
    registered for this process only."""
    try:
        import CoreText
        import Foundation
    except ImportError:
        return
    for name in tokens.FONT_FILES:
        path = _FONT_SOURCE / name
        if path.exists():
            CoreText.CTFontManagerRegisterFontsForURL(
                Foundation.NSURL.fileURLWithPath_(str(path)), CoreText.kCTFontManagerScopeProcess, None
            )


def init_fonts() -> None:
    global _sans, _mono
    # Before the first family query: NSFontManager caches the family list on that call, so a face
    # registered after it never appears. In the bundle the source folder is absent and this does
    # nothing.
    _register_source_fonts()
    families = set(AppKit.NSFontManager.sharedFontManager().availableFontFamilies())
    _sans = tokens.UI_FAMILY if tokens.UI_FAMILY in families else "SF Pro Text"
    _mono = tokens.MONO_FAMILY if tokens.MONO_FAMILY in families else "Menlo"


def sans() -> str:
    return _sans


def mono() -> str:
    return _mono


def _named(family: str, size: float, weight: int):
    return AppKit.NSFontManager.sharedFontManager().fontWithFamily_traits_weight_size_(
        family, 0, _MANAGER_WEIGHTS.get(weight, 5), size
    )


def font(size: float, weight: int = 400):
    return _named(_sans, size, weight) or AppKit.NSFont.systemFontOfSize_weight_(size, _SYSTEM_WEIGHTS[weight])


def mono_font(size: float | None = None, weight: int = 400):
    size = size if size is not None else TYPE["field_mono"]
    return _named(_mono, size, weight) or AppKit.NSFont.monospacedSystemFontOfSize_weight_(
        size, _SYSTEM_WEIGHTS[weight]
    )


def rgb(value: str) -> tuple[float, float, float]:
    value = value.lstrip("#")
    return tuple(int(value[index:index + 2], 16) / 255 for index in range(0, 6, 2))


def colour(name: str):
    return AppKit.NSColor.colorWithSRGBRed_green_blue_alpha_(*rgb(T[name]), 1.0)

# The longest a line of running text may get before it wraps, whatever the window width.
READING_WIDTH = 560.0
