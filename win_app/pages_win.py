"""The control window's pages, and which carry a dot in the sidebar.

Pure, so the rules are tested without Qt.
"""

from __future__ import annotations

# (key, name, what the page is for), in sidebar order; Ctrl+1 is the first.
PAGES = (
    ("overview", "Overview",
     "Where input is right now, and the two switches you reach for every day."),
    ("crossing", "Crossing",
     "How input leaves this PC: ways in, the arrangement with your Mac, resistance, and the "
     "shortcut key."),
    ("pairing", "Pairing",
     "Connect a Mac to this PC by typing the code it shows here. Once per Mac."),
    ("connection", "Connection",
     "This PC's address, listen port and shared token, and the Mac address pairing learned."),
    ("firewall", "Firewall",
     "Windows Firewall must let Beamer through before a Mac can connect."),
)
KEYS = tuple(page[0] for page in PAGES)


def dots(config_error: bool, firewall_tone: str | None) -> dict:
    """Page key to the tone of its sidebar dot, for the pages that need one.

    `firewall_tone` is the note tone the Firewall page is already showing -- "note" is its
    healthy end-state (the button just offers a manual re-check), so only "note-amber" and
    "note-fault" earn a dot; a plain boolean would also mark the healthy state."""
    marks = {}
    if config_error:
        marks["connection"] = "fault"
    if firewall_tone == "note-amber":
        marks["firewall"] = "amber"
    elif firewall_tone == "note-fault":
        marks["firewall"] = "fault"
    return marks
