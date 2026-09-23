import json
import unittest

import pairing
from pairing import PairingClient, PairingHost, beacon_msg, decode, encode


class FakeClock:
    def __init__(self, value=1000.0):
        self.value = value

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


def exchange(host, code, pair_id=None):
    client = PairingClient(pair_id or host.pair_id, code, "Test Mac")
    request = client.request()
    return client, request, host.handle(request)


class BeaconTests(unittest.TestCase):
    def test_beacon_carries_only_name_port_and_pairing_id(self):
        host = PairingHost(FakeClock())
        code = host.begin()
        raw = encode(beacon_msg("TEST-PC", 51820, host.pair_id))
        message = json.loads(raw)
        self.assertEqual(set(message), {"beamy", "type", "name", "port", "pair"})
        self.assertEqual(message["pair"], host.pair_id)
        self.assertNotIn(code.encode(), raw)
        self.assertEqual(decode(raw), message)

    def test_beacon_without_a_code_has_no_pairing_id(self):
        self.assertNotIn("pair", beacon_msg("TEST-PC", 51820, None))

    def test_decode_ignores_foreign_datagrams(self):
        self.assertIsNone(decode(b"\xff\x00not json"))
        self.assertIsNone(decode(b'{"beamy": 99, "type": "beacon"}'))
        self.assertIsNone(decode(b"[]"))
        self.assertIsNone(decode(b"x" * (pairing.MAX_DATAGRAM_BYTES + 1)))


class PairingHostTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.host = PairingHost(self.clock)

    def test_right_code_agrees_one_token_on_both_sides_without_sending_it(self):
        code = self.host.begin()
        client, request, reply = exchange(self.host, code)
        self.assertTrue(reply["ok"])
        token = client.accept(reply)
        self.assertEqual(self.host.paired[0], token)
        self.assertEqual(self.host.paired[1], "Test Mac")
        self.assertGreaterEqual(len(token), 40)
        wire = encode(request) + encode(reply)
        self.assertNotIn(token.encode(), wire)
        self.assertNotIn(code.encode(), wire)
        self.assertFalse(self.host.active)

    def test_wrong_code_is_refused_and_burns_the_code(self):
        code = self.host.begin()
        wrong = str((int(code) + 1) % 10**6).zfill(6)
        client, _request, reply = exchange(self.host, wrong)
        self.assertEqual(reply, {"type": "pair_reply", "pair": client.pair_id, "ok": False, "error": "refused"})
        with self.assertRaises(pairing.PairingError):
            client.accept(reply)
        self.assertIsNone(self.host.paired)
        self.assertFalse(self.host.active)
        # The right code, one second later, is no longer accepted either.
        _client, _request, retry = exchange(self.host, code, client.pair_id)
        self.assertFalse(retry["ok"])
        self.assertEqual(retry["error"], "not_pairing")

    def test_expired_code_is_refused(self):
        code = self.host.begin()
        pair_id = self.host.pair_id
        self.clock.advance(pairing.CODE_LIFETIME_SECONDS)
        _client, _request, reply = exchange(self.host, code, pair_id)
        self.assertFalse(reply["ok"])
        self.assertEqual(reply["error"], "not_pairing")
        self.assertIsNone(self.host.paired)

    def test_unknown_pairing_id_does_not_burn_the_code(self):
        code = self.host.begin()
        _client, _request, reply = exchange(self.host, code, "deadbeef")
        self.assertEqual(reply["error"], "not_pairing")
        self.assertTrue(self.host.active)
        _client, _request, reply = exchange(self.host, code)
        self.assertTrue(reply["ok"])

    def test_retransmitted_request_gets_the_same_reply(self):
        code = self.host.begin()
        client, request, reply = exchange(self.host, code)
        self.assertEqual(self.host.handle(request), reply)
        self.assertEqual(client.accept(reply), client.accept(self.host.handle(request)))

    def test_malformed_request_burns_the_code(self):
        self.host.begin()
        reply = self.host.handle({"type": "pair_request", "pair": self.host.pair_id, "pub": "!!", "proof": "??"})
        self.assertEqual(reply["error"], "refused")
        self.assertFalse(self.host.active)

    def test_seconds_left_counts_down_to_zero(self):
        self.host.begin()
        self.assertEqual(self.host.seconds_left, int(pairing.CODE_LIFETIME_SECONDS))
        self.clock.advance(10)
        self.assertEqual(self.host.seconds_left, int(pairing.CODE_LIFETIME_SECONDS) - 10)
        self.clock.advance(100)
        self.assertEqual(self.host.seconds_left, 0)
        self.assertIsNone(self.host.code)


class PairingClientTests(unittest.TestCase):
    def test_pc_that_does_not_know_the_code_is_rejected(self):
        host = PairingHost(FakeClock())
        code = host.begin()
        client = PairingClient(host.pair_id, code, "Test Mac")
        client.request()
        # A different host, holding a different code, answers in the real one's place.
        impostor = PairingHost(FakeClock())
        impostor.begin()
        impostor.pair_id = host.pair_id
        reply = impostor.handle(client.request())
        self.assertFalse(reply["ok"])
        with self.assertRaises(pairing.PairingError):
            client.accept(reply)

    def test_tampered_reply_is_rejected(self):
        host = PairingHost(FakeClock())
        code = host.begin()
        client, _request, reply = exchange(host, code)
        other = pairing.X25519PrivateKey.generate()
        reply["pub"] = pairing._b64(pairing._public_bytes(other))
        with self.assertRaises(pairing.PairingError):
            client.accept(reply)


if __name__ == "__main__":
    unittest.main()
