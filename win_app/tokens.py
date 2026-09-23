"""Beamer's design tokens: the Vernier direction, chosen 10-09-2026.

The mock is docs/designs/claude-2-vernier.html and its reasoning docs/designs/claude-2-vernier-notes.md.
This file is the one home for every colour, size, face and spring both apps draw with. The Mac app
reads it through the root theme.py; win_app/tokens.py is a byte-identical copy because PyInstaller
only bundles what sits under the app, and win_app's tests fail if the two drift. Edit this one, then
copy it across.

Dark only. `signal` is the one colour that means something is happening: the link is up, input is on
Windows, pressure is building, a permission is granted. The mock used lime; it was swapped for
cockpit cyan at build time because lime on near-black is the stock developer-tool look, and B612
Mono is a cockpit face. Reverting is this one value and `signal_dim`.
"""

PALETTE = {
    "ground": "#0e0f0d",
    "panel": "#161714",
    "well": "#1f201c",
    "rule": "#2a2b26",
    "edge": "#6e6f66",
    "ink": "#efeee6",
    "ink_2": "#b3b2a7",
    "ink_3": "#8f8e84",
    "signal": "#5fd4f4",
    "signal_dim": "#1f4a55",
    "amber": "#f2b544",
    "fault": "#ff7a66",
    "off": "#4a4b44",
}

# Measured WCAG ratios, for whoever changes a value: ink on panel 15.5, ink_2 on panel 8.4, ink_3 on
# panel 5.5, edge on panel 3.5 (control boundaries), signal on panel 10.4, ground on signal 11.1,
# amber on panel 9.8, fault on panel 7.1.

UI_FAMILY = "Hanken Grotesk"
MONO_FAMILY = "B612 Mono"
FONT_FILES = (
    "HankenGrotesk-Variable.ttf",
    "B612Mono-Regular.ttf",
    "B612Mono-Bold.ttf",
)

# Points on the Mac, logical pixels on Windows. The `_narrow` sizes apply at the 640 minimum width.
TYPE = {
    "eyebrow": 10.5,
    "readout_key": 9.5,
    "small": 11.5,
    "note": 12.5,
    "body": 13.0,
    "button": 13.0,
    "status_word": 38.0,
    "status_word_narrow": 30.0,
    "readout": 34.0,
    "readout_narrow": 26.0,
    "numeral": 52.0,
    "numeral_narrow": 42.0,
    "keycap": 20.0,
    "field_mono": 13.0,
    "code": 92.0,
}

# Colour choices for the crossing feedback on both machines: `crossing.glow_colour` on the Mac and
# `glow_colour` on Windows. `signal` is the Vernier colour; the rest are Border Beam's palettes
# (libraries.dev/beam), each in the order its colours sit round a border.
PALETTES = {
    "signal": (PALETTE["signal"],),
    "colourful": ("#ff3264", "#ff7828", "#f032b4", "#b428f0", "#6446ff", "#288cff", "#1eb9aa", "#32c850"),
    "ocean": ("#288cff", "#6446ff", "#1eb9aa", "#3c6eff"),
    "sunset": ("#ff7828", "#ff3264", "#ffb43c", "#f03278"),
    "mono": ("#ebebeb", "#969696", "#ebebeb"),
}

# Letter spacing as a fraction of the font size, for the uppercase tracked labels.
TRACKING = {
    "eyebrow": 0.14,
    "readout_key": 0.14,
    "selector": 0.12,
}

RADIUS = {
    "field": 4.0,
    "button": 5.0,
    "segment": 5.0,
    "keycap": 6.0,
}

MODULE_PADDING = (14.0, 16.0)
RACK_GAP = 1.0
MIN_WINDOW = {"mac": (640, 540), "windows": (640, 600)}

# Mass-spring parameters (mass 1) for everything that moves. The notch island integrates two of
# these, width and depth; a trackpad tick adds `tick_velocity` points per second to the width.
SPRING = {
    "island": {"stiffness": 300.0, "damping": 20.0},
    "breakthrough": {"stiffness": 600.0, "damping": 28.0, "seconds": 0.32},
    "tick_velocity": 260.0,
    "flash_seconds": 0.14,
}

ISLAND = {
    "grow_width": 40.0,
    "grow_depth": 26.0,
    "meter_segments": 4,
    "meter_after_depth": 14.0,
}


def tokens() -> dict:
    return dict(PALETTE)
