import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import link_state
import widgets
from bridge import AUTH_FAILED_STATUS, OLD_RECEIVER_STATUS, connection_error_message
from wake import NOT_WOKEN_STATUS


def controller(status="Connected to 192.168.1.3:51820", connected=True, **overrides):
    values = dict(
        cfg=SimpleNamespace(host="192.168.1.3", port=51820, auth_token="t", pc_name="STUDIO-PC"),
        connection_status=status,
        connected=connected,
        waking=False,
        windows_locked=False,
        redirecting=False,
        crossing=SimpleNamespace(armed=True),
        crossing_paused=False,
        full_screen_app=None,
        receiving=False,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


class ErrnoError(OSError):
    pass


class LinkStateTest(unittest.TestCase):
    def assertState(self, expected_key, tone, **kwargs):
        state = link_state.describe(controller(**kwargs))
        self.assertEqual((state.key, state.tone), (expected_key, tone))
        self.assertTrue(state.word and state.tag and state.detail)

    def test_the_pc_driving_this_mac_beats_every_other_state(self):
        # Whatever this Mac's own link is doing, the keyboard in the hand is
        # the PC's: nothing else the status could say is more true than that.
        self.assertState("receiving", "signal", receiving=True)
        self.assertState("receiving", "signal", receiving=True, redirecting=True)
        self.assertState("receiving", "signal", receiving=True, connected=False)

    def test_connected_states(self):
        self.assertState("mac", "ink")
        self.assertState("windows", "signal", redirecting=True)
        self.assertState("unlocking", "amber", status="Unlocking Windows…", windows_locked=True, redirecting=True)
        self.assertState("paused", "ink", crossing_paused=True)
        self.assertState("full_screen", "ink", full_screen_app="Final Cut Pro")
        self.assertState("waking", "amber", waking=True, connected=False)

    def test_tunnel_is_tagged(self):
        state = link_state.describe(controller(status=link_state.TUNNEL_STATUS))
        self.assertEqual((state.key, state.tag), ("mac", "Tunnel"))

    def test_every_failure_status_has_a_word(self):
        cases = {
            AUTH_FAILED_STATUS: "token",
            OLD_RECEIVER_STATUS: "version",
            "Windows receiver speaks Beamer protocol v3, this Mac v4 — update both apps": "version",
            "Windows rejected the connection: busy": "rejected",
            NOT_WOKEN_STATUS: "not_woken",
            connection_error_message(OSError(65, "No route")): "unreachable",
            connection_error_message(OSError(65, "Open /Applications/Beamer Tunnel.command")): "blocked",
            connection_error_message(OSError(61, "Refused")): "not_listening",
            connection_error_message(TimeoutError()): "unreachable",
            "Windows stopped responding": "stopped",
            "Connecting to 192.168.1.3:51820": "waiting",
            "Waiting to connect": "waiting",
            "Settings saved; reconnecting": "waiting",
            "Windows closed the connection": "dropped",
            "send failed: broken pipe": "dropped",
            "": "dropped",
        }
        for status, key in cases.items():
            with self.subTest(status=status):
                self.assertState(key, "amber" if key == "waiting" else "fault", status=status, connected=False)

    def test_unpaired(self):
        cfg = SimpleNamespace(host="192.168.1.3", port=51820, auth_token="", pc_name="")
        self.assertEqual(link_state.describe(controller(connected=False, cfg=cfg)).key, "unpaired")


class RulerScaleTest(unittest.TestCase):
    def test_square_root_gives_the_useful_band_half_the_travel(self):
        low = widgets.scale_fraction(150, 50, 1000, "sqrt")
        high = widgets.scale_fraction(600, 50, 1000, "sqrt")
        self.assertGreaterEqual(high - low, 0.49)

    def test_round_trip_and_pinning(self):
        for value in (50, 300, 1000):
            fraction = widgets.scale_fraction(value, 50, 1000, "sqrt")
            self.assertAlmostEqual(widgets.scale_value(fraction, 50, 1000, "sqrt"), value)
        self.assertEqual(widgets.scale_fraction(2000, 50, 1000, "sqrt"), 1.0)
        self.assertEqual(widgets.scale_fraction(250, 0, 500), 0.5)


if __name__ == "__main__":
    unittest.main()
