"""Headless packaged Qt smoke check; no hooks, config changes or network listeners."""
import os
import json
from pathlib import Path
import sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
report = Path(sys.argv[1]) if len(sys.argv) > 1 else None
if report:
    report.write_text(json.dumps({"stage": "starting"}))
from PySide6.QtCore import qVersion
from PySide6.QtWidgets import QApplication, QLabel
from PySide6.QtGui import QPixmap

app = QApplication([])
label = QLabel("Beamer package check")
label.resize(240, 60)
image = QPixmap(label.size())
label.render(image)
assert not image.isNull()
print(f"Packaged Qt {qVersion()}: Core, Gui, Widgets and offscreen rendering OK", flush=True)
if report:
    report.write_text(json.dumps({"stage": "passed", "qt": qVersion(), "frozen": bool(getattr(sys,"frozen",False))}))
