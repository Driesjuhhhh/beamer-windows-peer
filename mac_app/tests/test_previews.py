import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import previews


class PreviewFrameTest(unittest.TestCase):
    def test_a_push_builds_goes_through_plays_and_rests(self):
        self.assertEqual(previews.preview_frame(0.0, 1.2), (0.0, "push"))
        self.assertLess(previews.preview_frame(0.5, 1.2)[0], previews.preview_frame(1.5, 1.2)[0])
        self.assertEqual(previews.preview_frame(previews.PUSH_S + 0.1, 1.2), (0.0, "after"))
        self.assertEqual(previews.preview_frame(previews.PUSH_S + 1.3, 1.2), (0.0, "rest"))

    def test_loops_and_plays_for_as_long_as_keep_animating_says(self):
        cycle = previews.PUSH_S + 3.0 + previews.REST_S
        self.assertEqual(previews.preview_frame(previews.PUSH_S + 2.5, 3.0)[1], "after")
        self.assertEqual(previews.preview_frame(cycle + 0.1, 3.0)[1], "push")


if __name__ == "__main__":
    unittest.main()
