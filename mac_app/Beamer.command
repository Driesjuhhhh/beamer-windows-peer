#!/bin/bash
# Double-click launcher for Beamer (see build_notes.md: "Known issue: py2app
# packaging blocks LAN access" for why this runs as a script instead of the
# packaged .app).
cd "$(dirname "$0")"
exec .venv/bin/python3 kvm_bridge_app.py
