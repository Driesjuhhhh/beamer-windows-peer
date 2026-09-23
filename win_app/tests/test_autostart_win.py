import subprocess
import unittest
import xml.etree.ElementTree as ET

import autostart_win

NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
EXE = r"C:\Users\alex\AppData\Local\Beamer\Beamer.exe"


class FakeSchtasks:
    def __init__(self, exists=False, fail=None):
        self.exists = exists
        self.fail = fail
        self.calls = []
        self.xml = None

    def __call__(self, args):
        self.calls.append(args[1])
        if args[1] == "/create" and self.fail is None:
            with open(args[args.index("/xml") + 1], encoding="utf-16") as handle:
                self.xml = handle.read()
            self.exists = True
        if args[1] == "/delete" and self.fail is None:
            self.exists = False
        if args[1] == "/query":
            return subprocess.CompletedProcess(args, 0 if self.exists else 1, "", "")
        return subprocess.CompletedProcess(args, 1 if self.fail else 0, "", self.fail or "")


class TaskXmlTests(unittest.TestCase):
    def test_starts_hidden_elevated_and_never_times_out(self):
        root = ET.fromstring(autostart_win.task_xml(EXE, r"STUDIO-PC\alex").replace('encoding="UTF-16"', ""))
        self.assertEqual(root.find("t:Actions/t:Exec/t:Command", NS).text, EXE)
        self.assertEqual(root.find("t:Actions/t:Exec/t:Arguments", NS).text, "--hidden")
        self.assertEqual(root.find("t:Principals/t:Principal/t:RunLevel", NS).text, "HighestAvailable")
        self.assertEqual(root.find("t:Settings/t:ExecutionTimeLimit", NS).text, "PT0S")
        self.assertEqual(root.find("t:Triggers/t:LogonTrigger/t:UserId", NS).text, r"STUDIO-PC\alex")

    def test_escapes_the_path(self):
        ET.fromstring(autostart_win.task_xml(r"C:\A & B\Beamer.exe", "u").replace('encoding="UTF-16"', ""))


class SwitchTests(unittest.TestCase):
    def test_on_then_off(self):
        fake = FakeSchtasks()
        autostart_win.set_enabled(True, EXE, user="u", run=fake)
        self.assertIn("--hidden", fake.xml)
        self.assertTrue(autostart_win.is_enabled(fake))
        autostart_win.set_enabled(False, EXE, run=fake)
        self.assertFalse(autostart_win.is_enabled(fake))

    def test_off_when_absent_touches_nothing(self):
        fake = FakeSchtasks()
        autostart_win.set_enabled(False, EXE, run=fake)
        self.assertEqual(fake.calls, ["/query"])

    def test_refusal_is_raised(self):
        fake = FakeSchtasks(fail="ERROR: Access is denied.")
        with self.assertRaises(OSError) as caught:
            autostart_win.set_enabled(True, EXE, user="u", run=fake)
        self.assertIn("Access is denied", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
