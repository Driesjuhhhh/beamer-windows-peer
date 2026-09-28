import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import updates


def release(tag, **extra):
    return dict({"tag_name": tag, "html_url": f"https://github.com/kalkman-code/beamer/releases/tag/{tag}",
                 "draft": False, "prerelease": False}, **extra)


class NewerReleaseTests(unittest.TestCase):
    def test_a_patch_release_is_quiet_unless_its_notes_announce_it(self):
        self.assertIsNone(updates.newer_release("1.4.0", release("v1.4.1", body="Small fixes.")))
        self.assertIsNone(updates.newer_release("1.4.0", release("v1.4.1")))
        self.assertIsNotNone(updates.newer_release("1.4.0", release("v1.4.1", body="Fixes a crash.\n<!-- announce -->")))

    def test_a_quiet_patch_still_offers_the_minor_version_someone_is_behind(self):
        self.assertIsNotNone(updates.newer_release("1.4.2", release("v1.5.1", body="Small fixes.")))
        self.assertIsNotNone(updates.newer_release("1.9.0", release("v2.0.1")))

    def test_a_newer_tag_is_offered_with_its_page(self):
        self.assertEqual(updates.newer_release("1.3.3", release("v1.4.0")),
                         ("1.4.0", "https://github.com/kalkman-code/beamer/releases/tag/v1.4.0"))

    def test_the_same_or_an_older_tag_is_not(self):
        self.assertIsNone(updates.newer_release("1.4.0", release("v1.4.0")))
        self.assertIsNone(updates.newer_release("1.4.0", release("v1.3.9")))

    def test_versions_compare_as_numbers(self):
        self.assertIsNotNone(updates.newer_release("1.9.0", release("v1.10.0")))
        self.assertIsNone(updates.newer_release("1.4", release("v1.4.1")))

    def test_drafts_prereleases_and_odd_tags_never_count(self):
        self.assertIsNone(updates.newer_release("1.3.3", release("v2.0.0", prerelease=True)))
        self.assertIsNone(updates.newer_release("1.3.3", release("v2.0.0", draft=True)))
        self.assertIsNone(updates.newer_release("1.3.3", release("v2.0.0-beta")))
        self.assertIsNone(updates.newer_release("1.3.3", {"message": "rate limited"}))
        self.assertIsNone(updates.newer_release("1.3.3", ["not", "a", "dict"]))

    def test_a_dev_build_is_never_told_to_update(self):
        self.assertIsNone(updates.newer_release("dev", release("v9.0.0")))

    def test_a_page_outside_the_project_is_replaced_by_the_releases_page(self):
        found = updates.newer_release("1.3.3", release("v1.4.0", html_url="https://example.com/beamer.exe"))
        self.assertEqual(found, ("1.4.0", updates.RELEASES_PAGE))


class CheckerTests(unittest.TestCase):
    def make(self, payload=None, enabled=True, error=None):
        results = []

        def fetcher():
            if error:
                raise error
            return json.dumps(payload).encode("utf-8")

        checker = updates.Checker("1.3.3", lambda: enabled, results.append, fetcher=fetcher,
                                  logger=updates.logging.getLogger("test-updates"))
        return checker, results

    def test_reports_a_newer_release(self):
        checker, results = self.make(release("v1.4.0"))
        checker.check_once()
        self.assertEqual(results, [("1.4.0", "https://github.com/kalkman-code/beamer/releases/tag/v1.4.0")])

    def test_reports_none_when_current(self):
        checker, results = self.make(release("v1.3.3"))
        checker.check_once()
        self.assertEqual(results, [None])

    def test_switched_off_it_asks_nothing(self):
        checker, results = self.make(error=AssertionError("fetched while switched off"), enabled=False)
        checker.check_once()
        self.assertEqual(results, [])

    def test_a_failed_check_keeps_the_last_answer(self):
        checker, results = self.make(release("v1.4.0"))
        checker.check_once()
        checker.fetcher = lambda: (_ for _ in ()).throw(OSError("offline"))
        checker.check_once()
        self.assertEqual(checker.latest[0], "1.4.0")
        self.assertEqual(len(results), 1)


if __name__ == "__main__":
    unittest.main()
