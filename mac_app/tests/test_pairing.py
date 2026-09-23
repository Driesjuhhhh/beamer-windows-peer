import filecmp
import logging
import os
import socket
import time
import unittest

import pairing
from pairing import Announcer, Discovery, PairingClient, PairingHost, beacon_msg, encode


_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_TESTS_DIR))


def quiet_logger():
    logger = logging.getLogger("pairing-tests")
    logger.handlers = [logging.NullHandler()]
    logger.propagate = False
    return logger


def free_udp_port():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def wait_until(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


class ParityTests(unittest.TestCase):
    def test_both_copies_are_identical(self):
        mac = os.path.join(_REPO_ROOT, "mac_app", "pairing.py")
        win = os.path.join(_REPO_ROOT, "win_app", "pairing.py")
        self.assertTrue(filecmp.cmp(mac, win, shallow=False), "mac_app/pairing.py and win_app/pairing.py differ")


class ExchangeTests(unittest.TestCase):
    def test_wire_never_carries_the_code_or_the_token(self):
        host = PairingHost()
        code = host.begin()
        client = PairingClient(host.pair_id, code, "Test Mac")
        request = client.request()
        reply = host.handle(request)
        token = client.accept(reply)
        self.assertEqual(token, host.paired[0])
        wire = encode(beacon_msg("PC", 51820, host.pair_id)) + encode(request) + encode(reply)
        self.assertNotIn(code.encode(), wire)
        self.assertNotIn(token.encode(), wire)

    def test_wrong_code_fails_closed_for_the_client_too(self):
        host = PairingHost()
        code = host.begin()
        wrong = str((int(code) + 7) % 10**6).zfill(6)
        client = PairingClient(host.pair_id, wrong, "Test Mac")
        with self.assertRaises(pairing.PairingError) as caught:
            client.accept(host.handle(client.request()))
        self.assertEqual(str(caught.exception), pairing.ERROR_REFUSED)
        self.assertFalse(host.active)


class LoopbackTests(unittest.TestCase):
    """The two socket loops against each other on 127.0.0.1, with the broadcast address
    replaced so nothing leaves this machine."""

    def setUp(self):
        self.pc_port = free_udp_port()
        self.mac_port = free_udp_port()
        self.paired = []
        self.announcer = Announcer(
            lambda: 51820,
            lambda token, name, address: self.paired.append((token, name, address)),
            logger=quiet_logger(),
            bind_port=self.pc_port,
            announce_to=("127.0.0.1", self.mac_port),
            name="TEST-PC",
        )
        self.discovery = Discovery(logger=quiet_logger(), bind_port=self.mac_port)
        self.discovery.start()
        self.announcer.start()
        self.addCleanup(self.announcer.stop)
        self.addCleanup(self.discovery.stop)

    def test_discovers_pairs_and_stores_one_token_each_side(self):
        self.assertTrue(wait_until(lambda: self.discovery.pcs()))
        pc = self.discovery.pcs()[0]
        self.assertEqual((pc["name"], pc["port"], pc["address"], pc["reply_port"]), ("TEST-PC", 51820, "127.0.0.1", self.pc_port))
        self.assertIsNone(pc["pair_id"])
        code = self.announcer.begin_pairing()
        self.assertTrue(wait_until(lambda: self.discovery.pcs()[0]["pair_id"] is not None))
        pc = self.discovery.pcs()[0]
        token = self.discovery.pair(pc, code, name="Loopback Mac")
        self.assertTrue(wait_until(lambda: self.paired))
        self.assertEqual(self.paired[0], (token, "Loopback Mac", "127.0.0.1"))
        self.assertIsNone(self.announcer.code)

    def test_wrong_code_over_the_wire_is_refused(self):
        self.assertTrue(wait_until(lambda: self.discovery.pcs()))
        code = self.announcer.begin_pairing()
        self.assertTrue(wait_until(lambda: self.discovery.pcs()[0]["pair_id"] is not None))
        wrong = str((int(code) + 1) % 10**6).zfill(6)
        with self.assertRaises(pairing.PairingError) as caught:
            self.discovery.pair(self.discovery.pcs()[0], wrong)
        self.assertEqual(str(caught.exception), pairing.ERROR_REFUSED)
        self.assertEqual(self.paired, [])
        self.assertIsNone(self.announcer.code)

    def test_pairing_without_a_code_on_the_pc_says_so(self):
        self.assertTrue(wait_until(lambda: self.discovery.pcs()))
        pc = dict(self.discovery.pcs()[0], pair_id="00000000")
        with self.assertRaises(pairing.PairingError) as caught:
            self.discovery.pair(pc, "123456")
        self.assertEqual(str(caught.exception), pairing.ERROR_NOT_PAIRING)


if __name__ == "__main__":
    unittest.main()
