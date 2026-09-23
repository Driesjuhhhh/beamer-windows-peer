"""The Windows-to-Mac direction, driven over a real loopback socket against
the same receiver.py the Mac runs, so the two halves are proved against each
other rather than against a mock of each other."""

import socket
import threading
import time
import unittest

import capture_win
import protocol
import receiver
import sender
from app_config import Config
from fakes import FakeClipboard, FakeDesktop, FakeInjector, wait_for_calls
from return_edge import Rect

MONITORS = [Rect(0, 0, 1920, 1080)]


def make_config(**overrides):
    values = dict(
        host="127.0.0.1",
        port=0,
        auth_token="shared-token",
        mac_host="127.0.0.1",
        mac_return_edge="left",
        mac_resistance_px=40,
        crossing_resistance_px=40,
    )
    values.update(overrides)
    return Config(**values)


class EdgeTests(unittest.TestCase):
    """The outward crossing, with no link in the way: the model, the gate and
    the pin, which is everything the hook thread does per mouse move."""

    def setUp(self):
        self.desktop = FakeDesktop(MONITORS, cursor=(0, 500))
        self.link = MacSenderWithLink(desktop=self.desktop)

    def tearDown(self):
        self.link.close()

    def push(self, times, dx=-20):
        """The hand still moving left with the cursor already stopped at the
        left edge: the position never changes, which is exactly why the
        movement has to come from raw input rather than from the hook."""
        for _ in range(times):
            self.link.sender.on_motion(dx, 0)

    def test_a_push_against_the_edge_crosses(self):
        self.push(4)
        self.assertTrue(self.link.sender.redirecting, "a sustained push against the left edge never crossed")

    def test_the_edge_is_dead_while_the_mac_is_driving(self):
        self.link.sender.set_receiving(True)
        self.push(10)
        self.assertFalse(self.link.sender.redirecting)

    def test_the_shortcut_while_the_mac_is_driving_sends_its_input_home(self):
        sent_home = []
        self.link.sender.send_peer_home = lambda: sent_home.append(True) or True
        self.link.sender.set_receiving(True)
        self.assertTrue(self.link.sender.set_redirecting(True))
        self.assertEqual(sent_home, [True])
        self.assertFalse(self.link.sender.redirecting)

    def test_a_push_away_from_the_edge_never_crosses(self):
        self.push(10, dx=20)
        self.assertFalse(self.link.sender.redirecting)

    def test_a_pointer_off_the_edge_never_crosses(self):
        self.desktop.cursor = (900, 500)
        self.push(10)
        self.assertFalse(self.link.sender.redirecting)

    def test_the_edge_can_be_turned_off(self):
        self.link.sender.update_config(make_config(crossing_methods=["shortcut"]))
        self.push(10)
        self.assertFalse(self.link.sender.redirecting)
        self.assertTrue(self.link.sender.shortcut_armed)

    def test_the_shortcut_can_be_turned_off_on_its_own(self):
        self.link.sender.update_config(make_config(crossing_methods=["edge"]))
        self.assertFalse(self.link.sender.shortcut_armed)
        self.push(4)
        self.assertTrue(self.link.sender.redirecting)


class CornerTests(unittest.TestCase):
    """The corner is for a machine whose whole edge is busy: it wants a
    diagonal push in an 8-pixel box, and nothing else."""

    def setUp(self):
        self.desktop = FakeDesktop(MONITORS, cursor=(0, 0))
        self.link = MacSenderWithLink(desktop=self.desktop)
        self.link.sender.update_config(
            make_config(crossing_methods=["corner"], crossing_corner="top_left")
        )

    def tearDown(self):
        self.link.close()

    def test_a_diagonal_push_in_the_corner_crosses(self):
        for _ in range(4):
            self.link.sender.on_motion(-20, -20)
        self.assertTrue(self.link.sender.redirecting)

    def test_a_straight_push_along_the_edge_does_not(self):
        for _ in range(10):
            self.link.sender.on_motion(-20, 0)
        self.assertFalse(self.link.sender.redirecting)

    def test_the_same_diagonal_away_from_the_corner_does_not(self):
        self.desktop.cursor = (900, 500)
        for _ in range(10):
            self.link.sender.on_motion(-20, -20)
        self.assertFalse(self.link.sender.redirecting)


class SelfConnectionTests(unittest.TestCase):
    """The one way this PC could take its own daily link down: learning its
    own address as the Mac's, connecting to its own receiver with the shared
    token, and having the preempt rule close the real Mac's session."""

    def test_loopback_and_this_pcs_own_addresses_are_refused(self):
        self.assertTrue(sender.is_this_machine("127.0.0.1"))
        self.assertTrue(sender.is_this_machine("0.0.0.0"))
        self.assertTrue(sender.is_this_machine(""))
        self.assertTrue(sender.is_this_machine("192.168.1.3", ["192.168.1.3"]))

    def test_the_macs_address_is_not(self):
        self.assertFalse(sender.is_this_machine("192.168.1.5", ["192.168.1.3"], address_towards=lambda host: "192.168.1.3"))

    def test_this_pcs_own_real_address_is_not_missed_when_enumeration_fails(self):
        # local_addresses=[] is what pairing._local_ipv4_addresses() returns
        # when the hostname does not resolve; the route probe then answers,
        # and for this PC's own address it answers with that address.
        self.assertTrue(sender.is_this_machine("192.168.1.3", [], address_towards=lambda host: host))
        self.assertFalse(sender.is_this_machine("192.168.1.5", [], address_towards=lambda host: "192.168.1.3"))

    def test_a_route_probe_that_fails_does_not_stop_the_link(self):
        def refuse(host):
            raise OSError("network is unreachable")

        self.assertFalse(sender.is_this_machine("192.168.1.5", [], address_towards=refuse))

    def test_a_sender_pointed_at_this_pc_never_opens_a_link(self):
        attempts = []

        def refuse(address, timeout):
            attempts.append(address)
            raise AssertionError("the sender tried to connect to this PC")

        link = sender.MacSender(socket_factory=refuse, desktop=FakeDesktop(MONITORS))
        link.update_config(make_config(mac_host="127.0.0.1", port=51820))
        self.assertIsNone(link._ready_config())
        self.assertEqual(attempts, [])


class LinkTests(unittest.TestCase):
    def setUp(self):
        self.injector = FakeInjector()
        self.clipboard = FakeClipboard()
        self.mac_desktop = FakeDesktop(MONITORS, cursor=(900, 500))
        self.statuses = []
        self.arrangements = []
        self.server = receiver.ReceiverServer(
            status_callback=lambda state, detail: self.statuses.append((state, detail)),
            arrangement_callback=lambda edge, set_at: self.arrangements.append((edge, set_at)),
            clipboard=self.clipboard,
            unlock=NoUnlock(),
            desktop=self.mac_desktop,
            injector=self.injector,
            self_name="Mac",
            peer_name="PC",
            self_target="mac",
            peer_target="windows",
        )
        self.port = free_port()
        self.server.start(Config(host="127.0.0.1", port=self.port, auth_token="shared-token"))
        self.desktop = FakeDesktop(MONITORS, cursor=(0, 500))
        # The loopback address is this PC's own, which the real guard refuses
        # to connect to; here it is the Mac at the other end of the test.
        self.sender = sender.MacSender(
            desktop=self.desktop, clipboard=FakeClipboard("copied"), is_local=lambda host: False
        )
        self.sender.start(make_config(port=self.port))
        self.assertTrue(wait_for(lambda: self.sender.connected), f"never connected: {self.sender.status}")

    def tearDown(self):
        self.sender.stop()
        self.server.stop()

    def test_keys_reach_the_mac_injector(self):
        self.sender.set_redirecting(True, arrival_edge="right", offset=0.5)
        self.sender.on_key("cmd", True)
        self.sender.on_key("c", True)
        self.sender.on_key("c", False)
        self.sender.on_key("cmd", False)
        wait_for_calls(self.injector.calls, 4)
        self.assertEqual(
            self.injector.calls,
            [
                ("key", ("cmd", True)),
                ("key", ("c", True)),
                ("key", ("c", False)),
                ("key", ("cmd", False)),
            ],
        )

    def test_the_switch_places_the_mac_pointer_and_arms_its_way_home(self):
        self.sender.set_redirecting(True, arrival_edge="right", offset=0.25)
        self.assertTrue(wait_for(lambda: self.server.return_edge == "right"))
        self.assertEqual(self.mac_desktop.cursor[0], MONITORS[0].right)

    def test_nothing_is_sent_while_input_is_this_pcs(self):
        self.sender.on_key("a", True)
        time.sleep(0.2)
        self.assertEqual(self.injector.calls, [])

    def test_the_mac_pushing_home_takes_input_back(self):
        self.sender.set_redirecting(True, arrival_edge="right", offset=0.5)
        self.assertTrue(wait_for(lambda: self.server.return_edge == "right"))
        # The Mac's own pointer, pushed off its right edge: the receiver
        # answers with a switch, which must stop this PC sending.
        self.mac_desktop.cursor = (MONITORS[0].right, 500)
        for _ in range(20):
            self.sender.on_motion(40, 0)
            self.mac_desktop.cursor = (MONITORS[0].right, 500)
            if not self.sender.redirecting:
                break
        self.assertTrue(wait_for(lambda: not self.sender.redirecting), "the Mac's push home was ignored")

    def test_the_arrangement_travels_to_the_mac(self):
        self.sender.send_arrangement("right", 1758100000)
        wait_for_calls(self.arrangements, 1)
        self.assertEqual(self.arrangements[0], ("right", 1758100000))

    def test_the_arrangement_travels_back_from_the_mac(self):
        heard = []
        self.sender._arrangement_callback = lambda edge, set_at: heard.append((edge, set_at))
        self.assertTrue(self.server.send_arrangement("top", 1758100001))
        wait_for_calls(heard, 1)
        self.assertEqual(heard[0], ("top", 1758100001))

    def test_a_malformed_arrangement_does_not_take_the_link_down(self):
        self.sender._send_raw({"type": protocol.MSG_ARRANGEMENT, "data": {"mac_edge": "sideways"}})
        time.sleep(0.2)
        self.assertEqual(self.arrangements, [])
        self.assertTrue(self.sender.connected)

    def test_the_clipboard_travels_with_the_switch(self):
        self.sender.set_redirecting(True, arrival_edge="right", offset=0.5)
        wait_for_calls(self.clipboard.set_calls, 1)
        self.assertEqual(self.clipboard.set_calls[0][0], "copied")


class NoUnlock:
    def is_locked(self):
        return None


class MacSenderWithLink:
    """A sender with no socket at all, for the edge tests: `connected` is
    forced true so the gate opens, and nothing is ever sent."""

    def __init__(self, desktop):
        self.sender = sender.MacSender(desktop=desktop, clipboard=FakeClipboard(), is_local=lambda host: False)
        self.sender.update_config(make_config())
        self.sender._sock = object()
        self.sender._connected_at = time.monotonic()
        self.sender._last_ack_at = time.monotonic()

    def close(self):
        self.sender._sock = None


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


if __name__ == "__main__":
    unittest.main()
