import logging
import threading
import unittest

import config
import wake
from test_bridge import FakeQuartz, quiet_logger
from wake import NOT_WOKEN_STATUS, WAKING_STATUS, WakingController, mac_from_arp_output, magic_packet, parse_mac


WINDOWS_ARP = """
Interface: 192.168.1.5 --- 0x10
  Internet Address      Physical Address      Type
  192.168.1.1           a8-5e-45-1c-22-f0     dynamic
  192.168.1.3           02-1a-2b-3c-0d-4e     dynamic
  192.168.1.30          00-11-22-33-44-55     dynamic
  224.0.0.22            01-00-5e-00-00-16     static
"""

MAC_ARP = "? (192.168.1.3) at 2:1a:2b:3c:d:4e on en0 ifscope [ethernet]\n"


class FakeClock:
    def __init__(self, value=1000.0):
        self.value = value

    def __call__(self):
        return self.value


def make_config(mac="02:1A:2B:3C:0D:4E"):
    return config.Config(
        host="192.0.2.10",
        port=51820,
        auth_token="synthetic-token",
        reconnect_interval_s=0.1,
        mac_address=mac,
    )


class ParsingTests(unittest.TestCase):
    def test_parse_mac_normalises_both_platforms(self):
        self.assertEqual(parse_mac("02-1a-2b-3c-0d-4e"), "02:1A:2B:3C:0D:4E")
        self.assertEqual(parse_mac("2:1a:2b:3c:d:4e"), "02:1A:2B:3C:0D:4E")
        self.assertEqual(parse_mac(" 02:1A:2B:3C:0D:4E "), "02:1A:2B:3C:0D:4E")
        self.assertIsNone(parse_mac("02:1a:2b:3c:0d"))
        self.assertIsNone(parse_mac("not a mac"))
        self.assertIsNone(parse_mac(""))
        self.assertIsNone(parse_mac(None))

    def test_windows_arp_line_yields_the_right_host(self):
        self.assertEqual(mac_from_arp_output(WINDOWS_ARP, "192.168.1.3"), "02:1A:2B:3C:0D:4E")
        # 192.168.1.3 is a prefix of 192.168.1.30; the match must be the whole address.
        self.assertEqual(mac_from_arp_output(WINDOWS_ARP, "192.168.1.30"), "00:11:22:33:44:55")
        self.assertIsNone(mac_from_arp_output(WINDOWS_ARP, "192.168.1.9"))

    def test_macos_arp_line_is_padded(self):
        self.assertEqual(mac_from_arp_output(MAC_ARP, "192.168.1.3"), "02:1A:2B:3C:0D:4E")
        self.assertIsNone(mac_from_arp_output("? (192.168.1.3) at (incomplete) on en0 ifscope [ethernet]\n", "192.168.1.3"))


class MagicPacketTests(unittest.TestCase):
    def test_layout_is_six_ff_then_the_address_sixteen_times(self):
        packet = magic_packet("02-1a-2b-3c-0d-4e")
        address = bytes.fromhex("021a2b3c0d4e")
        self.assertEqual(len(packet), 102)
        self.assertEqual(packet[:6], b"\xff" * 6)
        self.assertEqual(packet[6:], address * 16)
        for index in range(16):
            self.assertEqual(packet[6 + index * 6 : 12 + index * 6], address)

    def test_rejects_a_bad_address(self):
        with self.assertRaises(ValueError):
            magic_packet("nope")


class WakingControllerTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.sent = []
        self.learned = []

        def socket_factory(address, timeout):
            raise OSError("synthetic: host asleep")

        self.controller = WakingController(
            make_config(),
            wake_sender=lambda mac, host: self.sent.append((mac, host)),
            mac_lookup=lambda host: "AA:BB:CC:DD:EE:FF",
            logger=quiet_logger(),
            quartz=FakeQuartz,
            clock=self.clock,
            socket_factory=socket_factory,
        )
        self.controller.WAKE_POLL_SECONDS = 0.01
        self.alerts = []
        self.controller.on_user_alert = lambda title, message: self.alerts.append(message)
        self.controller.on_mac_learned = self.learned.append

    def _wait_for_wake_thread(self):
        for thread in threading.enumerate():
            if thread.name == "wake":
                thread.join(timeout=5)

    def test_switch_while_unreachable_sends_the_packet_and_shows_waking(self):
        # The wake thread must see the packet as sent before the window is checked.
        self.controller.stop_event.set()
        self.assertFalse(self.controller.set_redirecting(True))
        self._wait_for_wake_thread()
        self.assertEqual(self.sent, [("02:1A:2B:3C:0D:4E", "192.0.2.10")])
        self.assertFalse(self.controller.redirecting)
        self.assertTrue(self.controller.outbound.empty())
        self.assertIn(WAKING_STATUS, self.alerts)

    def test_gives_up_after_the_window_with_nothing_queued(self):
        self.assertTrue(self.controller.wake())
        self.assertTrue(self.controller.waking)
        self.assertEqual(self.controller.connection_status, WAKING_STATUS)
        self.assertFalse(self.controller.wake(), "a second wake while one is in flight is refused")
        self.clock.value += wake.WAKE_WINDOW_SECONDS
        self._wait_for_wake_thread()
        self.assertFalse(self.controller.waking)
        self.assertEqual(self.controller.connection_status, NOT_WOKEN_STATUS)
        self.assertEqual(self.alerts[-1], NOT_WOKEN_STATUS)
        self.assertEqual(len(self.sent), 1)
        self.assertTrue(self.controller.outbound.empty())

    def test_status_written_underneath_a_wake_shows_through_afterwards(self):
        self.controller.wake()
        self.controller.connection_status = "Windows is unreachable from this Mac"
        self.assertEqual(self.controller.connection_status, WAKING_STATUS)
        self.clock.value += wake.WAKE_WINDOW_SECONDS
        self._wait_for_wake_thread()
        self.assertEqual(self.controller.connection_status, NOT_WOKEN_STATUS)

    def test_without_a_hardware_address_the_switch_fails_as_before(self):
        controller = WakingController(
            make_config(mac=""),
            wake_sender=lambda mac, host: self.sent.append((mac, host)),
            logger=quiet_logger(),
            quartz=FakeQuartz,
            clock=self.clock,
        )
        controller.on_user_alert = lambda title, message: self.alerts.append(message)
        self.assertFalse(controller.set_redirecting(True))
        self.assertEqual(self.sent, [])
        self.assertFalse(controller.can_wake)
        self.assertTrue(self.alerts[0].startswith("Cannot switch"))

    def test_successful_connection_learns_and_reports_a_new_address(self):
        from test_bridge import FakeSocket, seed_receiver_reply
        import protocol

        sock = FakeSocket()
        seed_receiver_reply(sock, protocol.welcome_msg())
        self.controller.socket_factory = lambda address, timeout: sock
        self.assertTrue(self.controller._connect_once())
        self.assertEqual(self.learned, ["AA:BB:CC:DD:EE:FF"])
        self.assertEqual(self.controller.cfg.mac_address, "AA:BB:CC:DD:EE:FF")
        self.assertFalse(self.controller.can_wake)


if __name__ == "__main__":
    unittest.main()
