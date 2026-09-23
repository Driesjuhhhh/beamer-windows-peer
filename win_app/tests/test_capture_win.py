"""What this PC's keys become on the wire. The translation runs against the
real keyboard layout through ToUnicodeEx, which reads a keyboard state handed
to it rather than the live one, so nothing here touches what is actually being
typed."""

import sys
import unittest

import capture_win
from capture_win import REDIRECT, RETURN, TOGGLE, KeyboardState, Trigger, key_name, wheel_notches
from input_injector import INJECTED_MARK

VK_A = 0x41
VK_1 = 0x31
VK_NUMPAD5 = 0x65


def names_only(vk, scan, state):
    """A translate function for the tests that never touch Windows."""
    return {VK_A: "a"}.get(vk)


class NameTests(unittest.TestCase):
    def test_ctrl_leaves_this_pc_as_command(self):
        # The semantic swap happens here and nowhere else: the Mac injects
        # exactly the name it is given.
        state = KeyboardState()
        self.assertEqual(key_name(0xA2, 0, state, names_only), "cmd")
        self.assertEqual(key_name(0xA3, 0, state, names_only), "cmd_r")

    def test_the_windows_key_leaves_as_control(self):
        state = KeyboardState()
        self.assertEqual(key_name(0x5B, 0, state, names_only), "ctrl")

    def test_alt_stays_alt(self):
        state = KeyboardState()
        self.assertEqual(key_name(0xA4, 0, state, names_only), "alt")

    def test_a_key_with_no_character_sends_nothing(self):
        state = KeyboardState()
        self.assertIsNone(key_name(0xFF, 0, state, names_only))


@unittest.skipUnless(sys.platform == "win32", "ToUnicodeEx needs Windows")
class LayoutTests(unittest.TestCase):
    """Against the real layout. The state passed in is the one the hook keeps,
    not the live keyboard, so these translate a key without pressing it."""

    def translate(self, vk, shift=False, caps=False):
        state = KeyboardState()
        state.shift_down = shift
        state.caps_lock = caps
        return key_name(vk, 0, state, capture_win._to_unicode)

    def test_a_letter_comes_back_as_itself(self):
        self.assertEqual(self.translate(VK_A), "a")

    def test_shift_is_applied(self):
        self.assertEqual(self.translate(VK_A, shift=True), "A")

    def test_caps_lock_is_applied(self):
        self.assertEqual(self.translate(VK_A, caps=True), "A")

    def test_a_shifted_digit_gives_the_symbol_the_layout_prints(self):
        self.assertEqual(self.translate(VK_1), "1")
        self.assertEqual(self.translate(VK_1, shift=True), "!")

    def test_the_numpad_types_its_digit(self):
        self.assertEqual(self.translate(VK_NUMPAD5), "5")


class WheelTests(unittest.TestCase):
    def test_one_notch_each_way(self):
        self.assertEqual(wheel_notches(120 << 16), 1.0)
        self.assertEqual(wheel_notches((0x10000 - 120) << 16), -1.0)


class TriggerTests(unittest.TestCase):
    def test_two_taps_inside_the_window_fire_once(self):
        trigger = Trigger("cmd_r", "double_tap", 300)
        self.assertIsNone(trigger.feed("cmd_r", True, 1.00))
        self.assertEqual(trigger.feed("cmd_r", True, 1.20), TOGGLE)
        # The pair is spent: a third tap starts a new one rather than firing.
        self.assertIsNone(trigger.feed("cmd_r", True, 1.30))

    def test_a_slow_second_tap_does_not_fire(self):
        trigger = Trigger("cmd_r", "double_tap", 300)
        trigger.feed("cmd_r", True, 1.0)
        self.assertIsNone(trigger.feed("cmd_r", True, 2.0))

    def test_another_key_is_not_the_trigger(self):
        trigger = Trigger("cmd_r", "double_tap", 300)
        trigger.feed("cmd_r", True, 1.0)
        self.assertIsNone(trigger.feed("a", True, 1.1))

    def test_holding_sends_input_over_and_releasing_brings_it_back(self):
        trigger = Trigger("alt_r", "hold", 300)
        self.assertEqual(trigger.feed("alt_r", True, 1.0), REDIRECT)
        # Key repeat while held changes nothing, and is still swallowed.
        self.assertIsNone(trigger.feed("alt_r", True, 1.1))
        self.assertEqual(trigger.feed("alt_r", False, 1.4), RETURN)

    def test_the_key_and_the_style_can_be_changed(self):
        trigger = Trigger("cmd_r", "double_tap", 300)
        trigger.configure("alt_r", "hold", 300)
        self.assertIsNone(trigger.feed("cmd_r", True, 1.0))
        self.assertEqual(trigger.feed("alt_r", True, 1.0), REDIRECT)


class HandMotionTests(unittest.TestCase):
    """What the WM_INPUT reader keeps. Raw Input reports a SendInput move
    exactly as it reports the mouse, so the injector's stamp is the only
    thing keeping the Mac's pointer out of this PC's own edge."""

    def test_the_hands_counts_pass(self):
        self.assertEqual(capture_win.hand_motion(0, -20, 3, 0), (-20, 3))

    def test_a_move_beamer_injected_is_not_the_hands(self):
        self.assertIsNone(capture_win.hand_motion(0, -20, 3, INJECTED_MARK))

    def test_another_devices_own_signature_still_passes(self):
        # A pen stamps its own signature into the same field; only Beamer's
        # mark is Beamer's.
        self.assertEqual(capture_win.hand_motion(0, -20, 3, 0xFF515700), (-20, 3))

    def test_an_absolute_reading_is_not_measured(self):
        self.assertIsNone(capture_win.hand_motion(capture_win.MOUSE_MOVE_ABSOLUTE, 500, 500, 0))

    def test_no_movement_is_nothing(self):
        self.assertIsNone(capture_win.hand_motion(0, 0, 0, 0))


if __name__ == "__main__":
    unittest.main()
