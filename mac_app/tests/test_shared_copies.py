"""The files both apps share are kept byte-identical, not merely similar.

`protocol.py`, `receiver.py` and `return_edge.py` each exist once in mac_app
and once in win_app because neither app can import across the other's
directory -- both are packaged as self-contained bundles. Everything
platform-shaped in them is injected at construction instead, so there is no
legitimate reason for the two copies to differ by a byte, and a diff is
always drift. This test is byte-for-byte on purpose: a structural comparison
would pass while the two sides' return-edge arithmetic or status wording
quietly diverged.

This file is itself one of those copies, and checks itself.
"""

import hashlib
import os
import unittest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_TESTS_DIR))

SHARED_MODULES = ("protocol.py", "receiver.py", "return_edge.py")
SHARED_TESTS = ("test_shared_copies.py",)


def _digest(path):
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


class SharedCopyTests(unittest.TestCase):
    def _assert_identical(self, mac_path, win_path, name):
        if not os.path.isfile(mac_path) or not os.path.isfile(win_path):
            self.skipTest(f"{name} is missing from one side; nothing to compare")
        self.assertEqual(
            _digest(mac_path),
            _digest(win_path),
            f"mac_app and win_app copies of {name} have drifted apart",
        )

    def test_shared_modules_are_identical(self):
        for name in SHARED_MODULES:
            with self.subTest(module=name):
                self._assert_identical(
                    os.path.join(_REPO_ROOT, "mac_app", name),
                    os.path.join(_REPO_ROOT, "win_app", name),
                    name,
                )

    def test_shared_tests_are_identical(self):
        for name in SHARED_TESTS:
            with self.subTest(module=name):
                self._assert_identical(
                    os.path.join(_REPO_ROOT, "mac_app", "tests", name),
                    os.path.join(_REPO_ROOT, "win_app", "tests", name),
                    name,
                )


if __name__ == "__main__":
    unittest.main()
