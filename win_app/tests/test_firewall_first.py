import sys
import unittest
from types import SimpleNamespace
from unittest import mock


@unittest.skipUnless(sys.platform == "win32", "the app module needs Windows")
class RulesBeforeListeningTests(unittest.TestCase):
    """A listener Windows has no rule for makes it ask, and Allow there opens every network."""

    def owner(self, events):
        import kvm_bridge_win

        owner = SimpleNamespace(
            update_checker=SimpleNamespace(start=lambda: None),
            _firewall_target=lambda: ("C:\\Beamer\\Beamer.exe", 24820),
            bridge=SimpleNamespace(rules_ready=SimpleNamespace(emit=lambda: events.append("listen"))),
            _listen=lambda: events.append("listen"),
        )
        owner._rules_then_listen = lambda: kvm_bridge_win.WindowsApplication._rules_then_listen(owner)
        return kvm_bridge_win, owner

    def status(self, allowed=False, blocked=False, error=""):
        return SimpleNamespace(allowed=allowed, blocked=blocked, error=error)

    def test_missing_rules_are_added_before_anything_listens(self):
        events = []
        module, owner = self.owner(events)
        with mock.patch.object(module.firewall_win, "status", return_value=self.status()), \
                mock.patch.object(module.firewall_win, "repair", side_effect=lambda *a: events.append("rules")):
            owner._rules_then_listen()
        self.assertEqual(events, ["rules", "listen"])

    def test_an_existing_rule_or_a_block_is_left_alone(self):
        for existing in (self.status(allowed=True), self.status(blocked=True), self.status(error="no PowerShell")):
            events = []
            module, owner = self.owner(events)
            with self.subTest(existing=existing), \
                    mock.patch.object(module.firewall_win, "status", return_value=existing), \
                    mock.patch.object(module.firewall_win, "repair", side_effect=lambda *a: events.append("rules")):
                owner._rules_then_listen()
            self.assertEqual(events, ["listen"])

    def test_a_failure_still_listens(self):
        events = []
        module, owner = self.owner(events)
        with mock.patch.object(module.firewall_win, "status", side_effect=OSError("denied")):
            owner._rules_then_listen()
        self.assertEqual(events, ["listen"])

    def test_without_elevation_it_listens_at_once(self):
        events = []
        module, owner = self.owner(events)
        with mock.patch.object(module.firewall_win, "is_elevated", return_value=False):
            module.WindowsApplication.start(owner)
        self.assertEqual(events, ["listen"])


if __name__ == "__main__":
    unittest.main()
