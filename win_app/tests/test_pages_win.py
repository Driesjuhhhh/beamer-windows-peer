import unittest

import pages_win


class PagesWinTest(unittest.TestCase):
    def test_keys_match_pages_in_order(self):
        self.assertEqual(pages_win.KEYS, tuple(page[0] for page in pages_win.PAGES))

    def test_every_page_has_a_name_and_purpose(self):
        for key, name, purpose in pages_win.PAGES:
            self.assertTrue(name)
            self.assertTrue(purpose)
            self.assertEqual(key, key.lower())

    def test_no_dots_when_all_clear(self):
        self.assertEqual(pages_win.dots(False, None), {})

    def test_no_dot_for_the_healthy_firewall_tone(self):
        # "note" is Firewall's own healthy end-state -- its button just offers a manual
        # re-check, so it must not earn a dot the way an amber or fault tone does.
        self.assertEqual(pages_win.dots(False, "note"), {})

    def test_config_error_marks_connection(self):
        self.assertEqual(pages_win.dots(True, None), {"connection": "fault"})

    def test_firewall_amber_marks_firewall(self):
        self.assertEqual(pages_win.dots(False, "note-amber"), {"firewall": "amber"})

    def test_firewall_fault_marks_firewall(self):
        self.assertEqual(pages_win.dots(False, "note-fault"), {"firewall": "fault"})

    def test_both_problems_mark_both_pages(self):
        self.assertEqual(
            pages_win.dots(True, "note-amber"), {"connection": "fault", "firewall": "amber"}
        )


if __name__ == "__main__":
    unittest.main()
