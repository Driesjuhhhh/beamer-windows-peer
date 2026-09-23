import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import kvm_bridge_app

# The 16" MacBook this was found on: a 1728x1117 display whose menu bar is the 33pt notch inset.
DISPLAYS = [(0.0, 0.0, 1728.0, 1117.0)]


def window(pid, layer, x, y, width, height):
    return {
        "kCGWindowOwnerPID": pid,
        "kCGWindowLayer": layer,
        "kCGWindowBounds": {"X": x, "Y": y, "Width": width, "Height": height},
    }


class CoversADisplayTest(unittest.TestCase):
    def test_a_zoomed_window_under_the_menu_bar_is_not_full_screen(self):
        self.assertFalse(
            kvm_bridge_app._covers_a_display([window(9, 0, 0, 33, 1728, 1084)], 9, DISPLAYS)
        )

    def test_the_desktop_window_is_not_full_screen(self):
        self.assertFalse(
            kvm_bridge_app._covers_a_display(
                [window(9, -2147483603, 0, 0, 1728, 1117)], 9, DISPLAYS
            )
        )

    def test_a_borderless_window_sized_to_the_display_is(self):
        self.assertTrue(
            kvm_bridge_app._covers_a_display([window(9, 0, 0, 0, 1728, 1117)], 9, DISPLAYS)
        )

    def test_another_process_does_not_count(self):
        self.assertFalse(
            kvm_bridge_app._covers_a_display([window(4, 0, 0, 0, 1728, 1117)], 9, DISPLAYS)
        )


if __name__ == "__main__":
    unittest.main()
