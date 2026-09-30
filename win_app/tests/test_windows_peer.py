"""Two Windows senders/receivers over real encrypted sockets, with fake desktops."""
import unittest
import tempfile
import threading
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch

from app_config import Config, ConfigError, config_from_dict, config_to_dict, validate_config
from fakes import FakeClipboard, FakeDesktop, FakeInjector, wait_for_calls
from peer_receiver import PeerReceiver
from return_edge import Rect
from sender import MacSender
from test_sender import NoUnlock, free_port, wait_for
from pair_windows import paired_config
import pair_windows
import pairing


class ConfigurationTests(unittest.TestCase):
    def test_legacy_defaults_and_roundtrip(self):
        old = config_from_dict(dict(host="", port=24820, auth_token="token"))
        self.assertEqual(old.peer_platform, "mac")
        new = replace(old, peer_platform="windows")
        self.assertEqual(config_from_dict(config_to_dict(new)), new)
        with self.assertRaises(ConfigError):
            validate_config(replace(old, peer_platform="linux"))

    def test_windows_preserves_both_modifier_sides_in_both_styles(self):
        link = MacSender()
        for style in ("semantic", "positional"):
            link.update_config(Config("", 24820, "token", peer_platform="windows", modifier_style=style))
            for source, target in (("cmd", "ctrl"), ("cmd_r", "ctrl_r"),
                                   ("ctrl", "cmd"), ("ctrl_r", "cmd_r"), ("alt", "alt")):
                self.assertEqual(link._wire_name(source), target)
        link.update_config(Config("", 24820, "token"))
        self.assertEqual(link._wire_name("cmd"), "cmd")

    def test_pairing_preserves_preferences_and_sets_peer(self):
        with patch("pair_windows.pairing.local_address_towards", return_value="192.168.1.2"):
            config = paired_config(Config("", 24820, "old", pointer_speed=2),
                                   "new", "PC B", "192.168.1.3", "right", 24820)
        self.assertEqual((config.peer_platform, config.mac_host, config.auth_token),
                         ("windows", "192.168.1.3", "new"))
        self.assertEqual(config.pointer_speed, 2)


class TwoWindowsTests(unittest.TestCase):
    def setUp(self):
        self.senders = []
        self.receivers = []
        self.injectors = []
        self.clipboards = []
        self.desktops = []
        ports = [free_port(), free_port()]
        for index in range(2):
            desktop = FakeDesktop([Rect(0, 0, 1920, 1080)], cursor=(500, 500))
            clipboard = FakeClipboard(f"PC {index}")
            injector = FakeInjector()
            link = MacSender(desktop=desktop, clipboard=clipboard, is_local=lambda host: False)
            server = PeerReceiver(lambda *args: None, desktop=desktop, clipboard=clipboard,
                                  injector=injector, unlock=NoUnlock(),
                                  focus_callback=lambda target, link=link: link.set_receiving(target == "mac"))
            link.send_peer_home = server.send_home
            self.senders.append(link)
            self.receivers.append(server)
            self.injectors.append(injector)
            self.clipboards.append(clipboard)
            self.desktops.append(desktop)
            self.addCleanup(server.stop)
            self.addCleanup(link.stop)
            server.start(Config("127.0.0.1", ports[index], "token", peer_platform="windows"))
        for index, link in enumerate(self.senders):
            link.start(Config("127.0.0.1", ports[1-index], "token", peer_platform="windows",
                              mac_host="127.0.0.1", mac_return_edge="right" if index == 0 else "left"))
            self.assertTrue(wait_for(lambda: link.connected), link.status)

    def test_input_focus_clipboard_and_switch_home_in_both_directions(self):
        for source in range(2):
            destination = 1-source
            link = self.senders[source]
            remote = self.receivers[destination]
            link.set_redirecting(True, arrival_edge="left", offset=0.25)
            self.assertTrue(wait_for(lambda: remote.return_edge == "left"))
            self.assertTrue(wait_for(lambda: self.senders[destination]._receiving))
            link.on_key("cmd", True)
            link.on_key("c", True)
            link.on_key("c", False)
            link.on_key("cmd", False)
            link.on_motion(10, 5)
            wait_for_calls(self.injectors[destination].calls, 5)
            self.assertIn(("key", ("ctrl", True)), self.injectors[destination].calls)
            self.assertIn(("mouse_move", (10, 5)), self.injectors[destination].calls)
            self.assertTrue(wait_for(lambda: bool(self.clipboards[destination].set_calls)))
            # The destination's own trigger gives the driving PC its input back.
            self.senders[destination].toggle()
            self.assertTrue(wait_for(lambda: not link.redirecting))
            self.assertTrue(wait_for(lambda: not self.senders[destination]._receiving))

    def test_connection_drop_returns_control(self):
        self.senders[0].set_redirecting(True)
        self.assertTrue(wait_for(lambda: self.senders[1]._receiving))
        self.receivers[1].stop()
        self.assertTrue(wait_for(lambda: not self.senders[0].redirecting))
        self.assertTrue(wait_for(lambda: not self.senders[1]._receiving))


class PairHelperTests(unittest.TestCase):
    def test_code_exchange_saves_matching_tokens_on_both_pcs(self):
        port = free_port()
        code_ready = threading.Event()
        code = []
        errors = []
        original_announcer = pairing.Announcer
        original_discovery = pairing.Discovery

        class LocalDiscovery(original_discovery):
            def find(self, host, ignored_port=None):
                return super().find(host, port)

        def local_announcer(getter, callback):
            return original_announcer(getter, callback, bind_port=port,
                                      announce_to=("127.0.0.1", port), name="PC A")

        def shown(message, **kwargs):
            if message.startswith("Pairing code:"):
                code.append(message.split()[2])
                code_ready.set()

        with tempfile.TemporaryDirectory() as directory:
            first, second = Path(directory)/"a.json", Path(directory)/"b.json"
            with patch("pair_windows.pairing.Announcer", local_announcer), \
                 patch("pair_windows.pairing.Discovery", LocalDiscovery), \
                 patch("pair_windows.is_this_machine", return_value=False), \
                 patch("builtins.print", shown), \
                 patch("pair_windows.getpass", side_effect=lambda prompt: code[0]):
                def host():
                    try:
                        pair_windows.host_pair(first, Config("", 24820, ""), "right")
                    except Exception as exc:
                        errors.append(exc)
                thread = threading.Thread(target=host, daemon=True)
                thread.start()
                self.assertTrue(code_ready.wait(5))
                pair_windows.join_pair(second, Config("", 24820, ""), "127.0.0.1", "left")
                thread.join(5)
                self.assertFalse(thread.is_alive())
                self.assertEqual(errors, [])
            a, b = pair_windows.load_config(first), pair_windows.load_config(second)
            self.assertEqual(a.auth_token, b.auth_token)
            self.assertTrue(a.auth_token)
            self.assertEqual((a.peer_platform, b.peer_platform), ("windows", "windows"))
            self.assertEqual((a.mac_return_edge, b.mac_return_edge), ("right", "left"))
