import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pages


class PagesTest(unittest.TestCase):
    def test_order(self):
        self.assertEqual(
            pages.KEYS, ("overview", "crossing", "design", "keyboard", "pairing", "connection", "permissions")
        )

    def test_first_open(self):
        self.assertEqual(pages.opening_page(None, True, True), "overview")
        self.assertEqual(pages.opening_page(None, False, True), "permissions")
        self.assertEqual(pages.opening_page(None, True, False), "permissions")

    def test_later_opens_keep_the_last_page(self):
        self.assertEqual(pages.opening_page("keyboard", False, False), "keyboard")
        self.assertEqual(pages.opening_page("overview", False, True), "overview")

    def test_dots(self):
        self.assertEqual(pages.dots(True, True, "mac"), {})
        self.assertEqual(pages.dots(True, False, "mac"), {"permissions": "amber"})
        self.assertEqual(pages.dots(True, True, "token"), {"pairing": "fault"})
        self.assertEqual(pages.dots(False, False, "token"), {"permissions": "amber", "pairing": "fault"})
        self.assertEqual(pages.dots(True, True, "unreachable"), {})

    def test_step_stops_at_the_ends(self):
        self.assertEqual(pages.step("overview", -1), "overview")
        self.assertEqual(pages.step("overview", 1), "crossing")
        self.assertEqual(pages.step("permissions", 1), "permissions")
        self.assertEqual(pages.step("pairing", -1), "keyboard")


if __name__ == "__main__":
    unittest.main()
