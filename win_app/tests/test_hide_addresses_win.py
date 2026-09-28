"""Hide addresses in the real window, built offscreen as tools/readme_shots_win.py builds it, which
starts no receiver, hooks or announcer."""

import json
import os
import tempfile
import unittest
from pathlib import Path

try:
    from PySide6.QtWidgets import QApplication, QLineEdit

    import kvm_bridge_win
    import theme
except ImportError:  # PySide6 is only in the Windows venv
    kvm_bridge_win = None


@unittest.skipIf(kvm_bridge_win is None, "needs PySide6")
class HideAddressesWindowTest(unittest.TestCase):
    def setUp(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        self.app = QApplication.instance() or QApplication([])
        theme.init_fonts()
        self.config = Path(tempfile.mkdtemp()) / "config.json"
        self.raw = {"host": "192.0.2.20", "port": 24820, "auth_token": "synthetic", "paired_with": "MacBook Pro",
                    "mac_host": "192.0.2.10", "mac_return_edge": "left"}
        self.config.write_text(json.dumps(self.raw))
        self.window = kvm_bridge_win.WindowsApplication(self.config)

    def tearDown(self):
        self.window.deleteLater()

    def test_a_reload_that_turns_it_on_hides_this_pcs_address(self):
        # The final bug pass, 28-09-2026: the tray's Reload configuration set the switch on but left
        # the address field readable, as the switch's handler never ran.
        self.assertEqual(self.window.host_entry.echoMode(), QLineEdit.EchoMode.Normal)
        self.config.write_text(json.dumps(dict(self.raw, hide_addresses=True)))
        self.window.reload_config()
        self.assertTrue(self.window.hide_switch.isChecked())
        self.assertEqual(self.window.host_entry.echoMode(), QLineEdit.EchoMode.Password)


if __name__ == "__main__":
    unittest.main()
