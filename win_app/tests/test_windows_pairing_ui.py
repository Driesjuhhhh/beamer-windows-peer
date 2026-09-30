import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import unittest
from unittest.mock import patch, Mock
from types import SimpleNamespace
from PySide6.QtWidgets import QApplication
from app_config import Config
import kvm_bridge_win
from windows_pairing_ui import WindowsPairDialog, pair_remote


class DialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_show_code_invokes_the_host_without_external_helper(self):
        host = Mock(return_value=True)
        dialog = WindowsPairDialog(None, host)
        dialog.host_button.click()
        host.assert_called_once()
        self.assertEqual(dialog.result(), dialog.DialogCode.Accepted)
        dialog.deleteLater()

    def test_errors_restore_controls_and_keep_dialog_open(self):
        dialog = WindowsPairDialog(None, lambda: True)
        dialog._set_busy(True)
        dialog.reject()
        self.assertFalse(dialog.join_button.isEnabled())
        dialog._error("Wrong code; show a fresh code on the other PC.")
        self.assertTrue(dialog.join_button.isEnabled())
        self.assertIn("Wrong code", dialog.status.text())
        dialog.deleteLater()

    def test_bad_address_and_code_fail_before_networking(self):
        factory = Mock()
        with self.assertRaises(ValueError):
            pair_remote("not-an-ip", "123456", factory)
        with patch("windows_pairing_ui.is_this_machine", return_value=False):
            with self.assertRaises(ValueError):
                pair_remote("192.168.1.3", "123", factory)
        factory.assert_not_called()

    def test_join_returns_the_authenticated_peer_and_stops_discovery(self):
        discovery = Mock(error=None)
        discovery.pcs.return_value = [dict(address="192.168.1.3", pair_id="id", name="PC B", port=24820)]
        discovery.pair.return_value = "secure-token"
        with patch("windows_pairing_ui.is_this_machine", return_value=False):
            result = pair_remote("192.168.1.3", "123 456", lambda **kwargs: discovery)
        self.assertEqual(result, ("secure-token", "PC B", "192.168.1.3", 24820))
        discovery.pair.assert_called_once_with(discovery.pcs.return_value[0], "123456")
        discovery.stop.assert_called_once()

    def test_timeout_closes_discovery(self):
        discovery = Mock(error=None)
        discovery.pcs.return_value = []
        with patch("windows_pairing_ui.is_this_machine", return_value=False):
            with self.assertRaises(Exception):
                pair_remote("192.168.1.3", "123456", lambda **kwargs: discovery, timeout=0)
        discovery.stop.assert_called_once()


class ApplicationPairingTests(unittest.TestCase):
    def owner(self, platform):
        owner = SimpleNamespace(_config=Config("",24820,"old"),_pairing_platform=platform,
                                _host="192.168.1.2",config_path="unused")
        for name in ("host_entry","port_entry","token_entry","edge_choice"):
            setattr(owner,name,Mock())
        owner.host_entry.text.return_value = "192.168.1.2"
        owner.port_entry.text.return_value = "24820"
        for name in ("_apply_config","_reflect_ways","_reflect_look","_refresh_pairing","_show_paired","_say_pairing"):
            setattr(owner,name,Mock())
        return owner

    def test_windows_join_saves_platform_address_port_and_left_edge(self):
        owner = self.owner("windows")
        with patch("kvm_bridge_win.save_config") as save:
            self.assertTrue(kvm_bridge_win.WindowsApplication._on_paired(owner,"new","PC B","192.168.1.3",24830))
        candidate = save.call_args.args[1]
        self.assertEqual((candidate.peer_platform,candidate.mac_host,candidate.port,candidate.mac_return_edge),
                         ("windows","192.168.1.3",24830,"left"))
        owner._apply_config.assert_called_once_with(candidate)

    def test_windows_host_saves_right_edge_and_mac_mode_remains_mac(self):
        for platform,edge in (("windows","right"),("mac","")):
            owner = self.owner(platform)
            with patch("kvm_bridge_win.save_config") as save:
                self.assertTrue(kvm_bridge_win.WindowsApplication._on_paired(owner,"new","Peer","192.168.1.3"))
            candidate = save.call_args.args[1]
            self.assertEqual((candidate.peer_platform,candidate.mac_return_edge),(platform,edge))
