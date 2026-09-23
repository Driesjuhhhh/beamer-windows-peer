"""The control window's pages, which one opens first, and which carry a dot in the sidebar.

Pure, so the rules are tested without AppKit.
"""

from __future__ import annotations

# (key, name, SF Symbol, what the page is for), in sidebar order; Cmd+1 is the first.
PAGES = (
    ("overview", "Overview", "gauge.with.needle",
     "Where input is, whether the link is up, and the two controls you reach for every day."),
    ("crossing", "Crossing", "cursorarrow.motionlines",
     "How the pointer passes from this Mac to Windows, and how hard the edge pushes back first."),
    ("design", "Design", "paintpalette",
     "How crossing looks and feels on this Mac: the notch, the edge and the trackpad. Every change applies as you make it."),
    ("keyboard", "Keyboard", "keyboard",
     "The key that switches input, and how the Mac's modifier keys arrive on Windows."),
    ("pairing", "Pairing", "link",
     "Connect this Mac to a PC by typing the code the PC shows. Once per Mac."),
    ("connection", "Connection", "network",
     "Where the PC is and the token this Mac proves itself with. Pairing fills these in."),
    ("permissions", "Permissions", "lock.shield",
     "macOS must allow Beamer to read this keyboard and trackpad before it can send them anywhere."),
)
KEYS = tuple(page[0] for page in PAGES)


def opening_page(last, accessibility, input_monitoring):
    """The last page viewed in this run; on the first open, Permissions while either is still
    required, otherwise Overview."""
    if last in KEYS:
        return last
    return "overview" if accessibility and input_monitoring else "permissions"


def dots(accessibility, input_monitoring, link_key):
    """Page key to the tone of its sidebar dot, for the pages that need one."""
    marks = {}
    if not (accessibility and input_monitoring):
        marks["permissions"] = "amber"
    if link_key == "token":
        marks["pairing"] = "fault"
    return marks


def step(current, direction):
    """The page an arrow key moves to, stopping at either end of the list."""
    index = KEYS.index(current) if current in KEYS else 0
    return KEYS[min(max(index + direction, 0), len(KEYS) - 1)]
