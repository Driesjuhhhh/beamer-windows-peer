import os
from pathlib import Path
import subprocess
import sys
import unittest

# The scale factor only takes effect before a QApplication exists, and another test may already
# have made one, so the render runs in its own process.
PROBE = """
from PySide6.QtWidgets import QApplication
app = QApplication([])
import kvm_bridge_win as k
pixmap = k.status_icon(k.ServerState.CONNECTED)
print(pixmap.width(), pixmap.toImage().pixelColor(32, 32).name())
"""


class TrayIconTest(unittest.TestCase):
    def test_mark_survives_a_scaled_display(self):
        # At 150% the tray once showed only the state dot on a taskbar-coloured square.
        env = dict(os.environ, QT_SCALE_FACTOR="1.5", QT_QPA_PLATFORM="offscreen")
        out = subprocess.run(
            [sys.executable, "-c", PROBE],
            cwd=Path(__file__).resolve().parent.parent,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(out.returncode, 0, out.stderr)
        width, centre = out.stdout.split()
        self.assertEqual(width, "64")
        # The centre of the mark is the cursor's off-white, not the fallback panel fill.
        self.assertEqual(centre, "#efeee6")


if __name__ == "__main__":
    unittest.main()
