"""Protocol parity test: mac_app/protocol.py and win_app/protocol.py are two
independent copies of the same wire protocol (see the module docstring in
either file) and must never be allowed to silently drift apart -- a v2
sender talking to a stale v1-ish receiver (or vice versa) is exactly the
failure mode protocol.py's own version handshake exists to catch, and this
test exists to catch the same class of problem one step earlier, at review
time, before either app ships.

Both files are loaded via importlib file-path loading rather than a normal
`import protocol`, so this test has no dependency on sys.path/PYTHONPATH
ordering -- it always compares these two specific files on disk, not
whichever `protocol` module happens to be importable first. Dependency-free:
only the standard library (importlib, inspect, unittest).
"""

import importlib.util
import inspect
import os
import types
import unittest


_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_TESTS_DIR))
MAC_PROTOCOL_PATH = os.path.join(_REPO_ROOT, "mac_app", "protocol.py")
WIN_PROTOCOL_PATH = os.path.join(_REPO_ROOT, "win_app", "protocol.py")


def _load_module_from_path(module_name, path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _public_attribute_names(module):
    """Names protocol.py itself defines and exposes: everything not starting
    with "_", excluding re-exported stdlib modules (json, socket, struct)
    that show up in dir() purely because they were imported at module level
    -- those aren't part of the protocol surface being compared here."""
    return {
        name
        for name in dir(module)
        if not name.startswith("_") and not isinstance(getattr(module, name), types.ModuleType)
    }


class ProtocolParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.path.isfile(MAC_PROTOCOL_PATH):
            raise unittest.SkipTest(f"mac_app/protocol.py not found at {MAC_PROTOCOL_PATH}")
        if not os.path.isfile(WIN_PROTOCOL_PATH):
            raise unittest.SkipTest(f"win_app/protocol.py not found at {WIN_PROTOCOL_PATH}")
        # Distinct module names, so this never collides with (or is
        # satisfied by) an already-imported `protocol` module from either
        # app's own test suite / sys.path setup.
        cls.mac = _load_module_from_path("_protocol_parity_mac", MAC_PROTOCOL_PATH)
        cls.win = _load_module_from_path("_protocol_parity_win", WIN_PROTOCOL_PATH)

    def test_public_names_match(self):
        self.assertEqual(
            _public_attribute_names(self.mac),
            _public_attribute_names(self.win),
            "mac_app/protocol.py and win_app/protocol.py expose different public names",
        )

    def test_constants_have_identical_values(self):
        for name in sorted(_public_attribute_names(self.mac)):
            mac_value = getattr(self.mac, name)
            if not isinstance(mac_value, (int, float, str, bytes, bool)):
                continue
            win_value = getattr(self.win, name)
            with self.subTest(name=name):
                self.assertEqual(
                    mac_value,
                    win_value,
                    f"constant {name!r} differs between mac_app and win_app protocol.py",
                )

    def test_function_signatures_match(self):
        for name in sorted(_public_attribute_names(self.mac)):
            mac_value = getattr(self.mac, name)
            if not inspect.isfunction(mac_value):
                continue
            win_value = getattr(self.win, name)
            with self.subTest(name=name):
                self.assertTrue(
                    inspect.isfunction(win_value),
                    f"{name!r} is a function in mac_app/protocol.py but not in win_app/protocol.py",
                )
                self.assertEqual(
                    inspect.signature(mac_value),
                    inspect.signature(win_value),
                    f"signature of {name!r} differs between mac_app and win_app protocol.py",
                )

    def test_classes_match(self):
        for name in sorted(_public_attribute_names(self.mac)):
            mac_value = getattr(self.mac, name)
            if not inspect.isclass(mac_value):
                continue
            win_value = getattr(self.win, name)
            with self.subTest(name=name):
                self.assertTrue(
                    inspect.isclass(win_value),
                    f"{name!r} is a class in mac_app/protocol.py but not in win_app/protocol.py",
                )
                self.assertEqual(mac_value.__name__, win_value.__name__)
                self.assertEqual(
                    [base.__name__ for base in mac_value.__mro__],
                    [base.__name__ for base in win_value.__mro__],
                    f"MRO of {name!r} differs between mac_app and win_app protocol.py",
                )


if __name__ == "__main__":
    unittest.main()
