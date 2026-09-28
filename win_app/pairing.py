"""LAN discovery and pairing, shared by mac_app and win_app (two identical copies; the Mac
test suite checks they match byte for byte).

The Windows receiver broadcasts a small UDP beacon -- hostname, Beamer TCP port, and a random
pairing id while a code is on screen -- and the Mac lists what it hears. Pairing then runs as
one datagram each way:

  Mac -> PC   pair_request  {pair, pub: X25519 public key, proof, name}
  PC  -> Mac  pair_reply    {pair, ok, pub: X25519 public key, proof}

Both proofs are HMACs keyed from the six-digit code (scrypt, salted with the pairing id) over
the transcript, so each side shows the other that it knows the code. The shared token is
HKDF over the X25519 secret: an eavesdropper who records every datagram cannot derive it.

Where no broadcast reaches the Mac (another subnet, a VPN), the Mac asks a typed address for its
beacon with a `find` datagram, and pairing continues exactly as above.

What this protects against, and what it does not:

- The token never crosses the wire, and neither does the code. The beacon carries nothing a
  token or key could be derived from.
- A wrong code fails closed. The PC consumes its code on the first confirmation it receives,
  right or wrong, so one code gives one guess; a fresh code needs a person at the PC to press
  Pair a Mac again, and that is the rate limit. Codes expire after CODE_LIFETIME_SECONDS.
- A passive listener can, offline, brute-force the code out of a recorded proof. That is why
  the code is single-use and why the key stretching is memory-hard: the code is worthless the
  moment it is consumed, and the token does not depend on it anyway.
- An ACTIVE attacker on the LAN during the pairing window is not stopped. One that answers the
  Mac's request in the PC's place receives the Mac's proof, can crack the six digits in the
  time the code is still valid given enough hardware, and pair with either side as the other.
  One that merely sends a junk confirmation burns the code and stops that pairing (a denial,
  not a compromise). A six-digit code without a PAKE cannot do better; the scheme trusts the
  LAN for the minute the code is on screen, and no longer.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import queue
import secrets
import socket
import threading
import time

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

import protocol

# One home for the port, in the module both apps share byte-for-byte.
PAIRING_PORT = protocol.PAIRING_PORT
BEACON_VERSION = 1
BEACON_INTERVAL_SECONDS = 2.0
# Three missed beacons: long enough to ride out Wi-Fi hiccups, short enough that a PC that
# went to sleep leaves the list before anyone tries it.
BEACON_STALE_SECONDS = 7.0
CODE_LIFETIME_SECONDS = 60.0
CODE_DIGITS = 6
MAX_DATAGRAM_BYTES = 1024
PAIR_REPLY_TIMEOUT_SECONDS = 1.5
PAIR_ATTEMPTS = 3

MSG_BEACON = "beacon"
MSG_PAIR_REQUEST = "pair_request"
MSG_PAIR_REPLY = "pair_reply"
# The Mac asking one address for its beacon, for a PC that no broadcast reaches (another subnet,
# a VPN). The answer is the beacon every listener already hears, so it discloses nothing new.
MSG_FIND = "find"

ERROR_NOT_PAIRING = "not_pairing"
ERROR_REFUSED = "refused"

# Wire constant, deliberately kept as the pre-rename name: changing it would break an existing
# pairing and a mixed-version pair for no gain.
TOKEN_INFO = b"beamy-pair-token"
# Wire constant, deliberately kept as the pre-rename name: changing it would break an existing
# pairing and a mixed-version pair for no gain.
CODE_INFO = b"beamy-pair-code"


class PairingError(Exception):
    pass


def new_code() -> str:
    return "".join(secrets.choice("0123456789") for _ in range(CODE_DIGITS))


def _code_key(code: str, pair_id: str) -> bytes:
    # scrypt rather than HKDF on purpose: a recorded proof lets anyone try all million codes
    # offline, and 32MB per guess is what keeps that from finishing inside the code's minute.
    # maxmem is explicit because OpenSSL's default is exactly the 32MiB this needs, and it
    # refuses at the boundary.
    return hashlib.scrypt(
        code.encode("utf-8"), salt=pair_id.encode("utf-8") + CODE_INFO, n=2**15, r=8, p=1, dklen=32, maxmem=64 * 1024 * 1024
    )


def _proof(key: bytes, role: bytes, pair_id: str, mac_pub: bytes, pc_pub: bytes = b"") -> bytes:
    return hmac.new(key, role + pair_id.encode("utf-8") + mac_pub + pc_pub, hashlib.sha256).digest()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    if not isinstance(text, str):
        raise PairingError("expected base64 text")
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except ValueError as exc:
        raise PairingError("bad base64") from exc


def _public_bytes(key) -> bytes:
    return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def derive_token(private_key, peer_public: bytes, pair_id: str) -> str:
    shared = private_key.exchange(X25519PublicKey.from_public_bytes(peer_public))
    return _b64(HKDF(algorithm=hashes.SHA256(), length=32, salt=pair_id.encode("utf-8"), info=TOKEN_INFO).derive(shared))


def encode(message: dict) -> bytes:
    # The "beamy" key is a wire constant, deliberately kept as the pre-rename name: changing it
    # would break an existing pairing and a mixed-version pair for no gain.
    return json.dumps({"beamy": BEACON_VERSION, **message}, separators=(",", ":")).encode("utf-8")


def decode(data: bytes):
    """The dict a Beamer datagram carries, or None for anything else on the port."""
    if len(data) > MAX_DATAGRAM_BYTES:
        return None
    try:
        message = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(message, dict) or message.get("beamy") != BEACON_VERSION:
        return None
    return message


def beacon_msg(name: str, port: int, pair_id: str = None) -> dict:
    message = {"type": MSG_BEACON, "name": name, "port": int(port)}
    if pair_id:
        message["pair"] = pair_id
    return message


class PairingHost:
    """The PC's half: holds at most one live code and answers pair requests. Pure -- the
    Announcer owns the socket and the clock is injected for the tests."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.code = None
        self.pair_id = None
        self.expires_at = 0.0
        self._last = None
        self.paired = None
        # How the last code ended -- "paired", "refused" or "expired" -- for the window to say
        # so; None while a code is live or after a deliberate cancel.
        self.outcome = None

    @property
    def active(self) -> bool:
        if self.code is None:
            return False
        if self.clock() >= self.expires_at:
            self.cancel()
            self.outcome = "expired"
            return False
        return True

    @property
    def seconds_left(self) -> int:
        return max(0, int(self.expires_at - self.clock())) if self.active else 0

    def begin(self) -> str:
        self.code = new_code()
        self.pair_id = secrets.token_hex(4)
        self.expires_at = self.clock() + CODE_LIFETIME_SECONDS
        self._last = None
        self.outcome = None
        return self.code

    def cancel(self) -> None:
        self.code = None
        self.pair_id = None
        self.expires_at = 0.0
        self.outcome = None

    def handle(self, message: dict):
        """The reply to one datagram, or None when it deserves no answer. A successful pairing
        leaves the token in `self.paired` as (token, mac_name); the caller stores it."""
        if message.get("type") != MSG_PAIR_REQUEST:
            return None
        pair_id = message.get("pair")
        if not isinstance(pair_id, str):
            return None
        if self._last is not None and self._last[0] == (pair_id, message.get("pub"), message.get("proof")):
            # A lost reply makes the Mac send the same request again; answer it the same way,
            # so a retransmit is not read as a second attempt.
            return self._last[1]
        if not self.active or pair_id != self.pair_id:
            return {"type": MSG_PAIR_REPLY, "pair": pair_id, "ok": False, "error": ERROR_NOT_PAIRING}
        code, self.code = self.code, None
        try:
            mac_pub = _unb64(message.get("pub"))
            proof = _unb64(message.get("proof"))
            X25519PublicKey.from_public_bytes(mac_pub)
        except (PairingError, ValueError):
            return self._refuse(message, pair_id)
        key = _code_key(code, pair_id)
        if not hmac.compare_digest(proof, _proof(key, b"mac", pair_id, mac_pub)):
            return self._refuse(message, pair_id)
        private_key = X25519PrivateKey.generate()
        pc_pub = _public_bytes(private_key)
        name = message.get("name")
        self.paired = (derive_token(private_key, mac_pub, pair_id), name if isinstance(name, str) else "")
        reply = {
            "type": MSG_PAIR_REPLY,
            "pair": pair_id,
            "ok": True,
            "pub": _b64(pc_pub),
            "proof": _b64(_proof(key, b"pc", pair_id, mac_pub, pc_pub)),
        }
        self._last = ((pair_id, message.get("pub"), message.get("proof")), reply)
        self.cancel()
        self.outcome = "paired"
        return reply

    def _refuse(self, message: dict, pair_id: str) -> dict:
        reply = {"type": MSG_PAIR_REPLY, "pair": pair_id, "ok": False, "error": ERROR_REFUSED}
        self._last = ((pair_id, message.get("pub"), message.get("proof")), reply)
        self.cancel()
        self.outcome = "refused"
        return reply


class PairingClient:
    """The Mac's half of one attempt: builds the request, checks the reply, yields the token."""

    def __init__(self, pair_id: str, code: str, name: str):
        self.pair_id = pair_id
        self.name = name
        self._private_key = X25519PrivateKey.generate()
        self._pub = _public_bytes(self._private_key)
        self._key = _code_key(code, pair_id)

    def request(self) -> dict:
        return {
            "type": MSG_PAIR_REQUEST,
            "pair": self.pair_id,
            "pub": _b64(self._pub),
            "proof": _b64(_proof(self._key, b"mac", self.pair_id, self._pub)),
            "name": self.name,
        }

    def accept(self, reply: dict) -> str:
        """The agreed token, or PairingError naming why not."""
        if reply.get("type") != MSG_PAIR_REPLY or reply.get("pair") != self.pair_id:
            raise PairingError("not a reply to this attempt")
        if reply.get("ok") is not True:
            raise PairingError(reply.get("error") if reply.get("error") in (ERROR_NOT_PAIRING, ERROR_REFUSED) else ERROR_REFUSED)
        pc_pub = _unb64(reply.get("pub"))
        proof = _unb64(reply.get("proof"))
        if not hmac.compare_digest(proof, _proof(self._key, b"pc", self.pair_id, self._pub, pc_pub)):
            raise PairingError(ERROR_REFUSED)
        return derive_token(self._private_key, pc_pub, self.pair_id)


def _udp_socket(bind_port: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(socket, "SO_REUSEPORT"):
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.bind(("", bind_port))
    sock.settimeout(0.5)
    return sock


def local_address_towards(host: str) -> str:
    """This machine's address on the interface that reaches `host`; nothing is sent."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect((host, 9))
        return probe.getsockname()[0]
    finally:
        probe.close()


def broadcast_targets(port: int) -> list:
    """Every address worth sending a beacon to, one per local IPv4 interface plus the limited
    broadcast as a backstop.

    ⚠ 255.255.255.255 alone is not enough and this is not theoretical: it leaves by the default
    route only, so a PC with a second interface — a Hyper-V vEthernet switch is the common case —
    announces on whichever the routing table prefers and may never reach the LAN the Mac is on.
    Seen in practice: the PC beaconed steadily while no beacon reached the Mac at all, and the Mac
    then paired against a stale id from an older beacon that had got through, which is what
    produced `not_pairing`.

    The per-interface directed broadcast assumes a /24, because the stdlib exposes no netmask.
    A wrong guess costs one datagram that goes nowhere; the limited broadcast is still sent, so
    this can only add delivery, never remove it."""
    targets = [("255.255.255.255", port)]
    seen = {"255.255.255.255"}
    for address in _local_ipv4_addresses():
        parts = address.split(".")
        if len(parts) != 4:
            continue
        directed = ".".join(parts[:3] + ["255"])
        if directed not in seen:
            seen.add(directed)
            targets.append((directed, port))
    return targets


def _local_ipv4_addresses() -> list:
    found = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = info[4][0]
            if not address.startswith("127.") and address not in found:
                found.append(address)
    except OSError:
        pass
    return found


def machine_name() -> str:
    return socket.gethostname().split(".", 1)[0] or "This machine"


class Announcer:
    """The PC's socket loop: broadcasts the beacon and answers pairing requests on one socket.
    `port_getter` returns the current TCP port, so a changed listen port is announced without a
    restart. `on_paired(token, mac_name, mac_address)` is called on this thread."""

    def __init__(self, port_getter, on_paired, logger=None, bind_port=PAIRING_PORT, announce_to=("255.255.255.255", PAIRING_PORT), name=None):
        self.port_getter = port_getter
        self.on_paired = on_paired
        self.logger = logger or logging.getLogger("Beamer")
        self.bind_port = bind_port
        self.announce_to = announce_to
        self.name = name or machine_name()
        self.host = PairingHost()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self.error = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="Beamer-announcer", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        self._thread = None

    def begin_pairing(self) -> str:
        with self._lock:
            return self.host.begin()

    def cancel_pairing(self) -> None:
        with self._lock:
            self.host.cancel()

    @property
    def code(self):
        with self._lock:
            return self.host.code if self.host.active else None

    @property
    def seconds_left(self) -> int:
        with self._lock:
            return self.host.seconds_left

    @property
    def outcome(self):
        with self._lock:
            self.host.active
            return self.host.outcome

    def _beacon(self) -> bytes:
        with self._lock:
            pair_id = self.host.pair_id if self.host.active else None
        return encode(beacon_msg(self.name, self.port_getter(), pair_id))

    def _run(self) -> None:
        try:
            sock = _udp_socket(self.bind_port)
        except OSError as exc:
            self.error = str(exc)
            self.logger.error("pairing beacon could not bind UDP %s: %s", self.bind_port, exc)
            return
        self.error = None
        next_beacon = 0.0
        answered = {}
        try:
            while not self._stop.is_set():
                now = time.monotonic()
                if now >= next_beacon:
                    next_beacon = now + BEACON_INTERVAL_SECONDS
                    beacon = self._beacon()
                    delivered = 0
                    # Only a caller asking for the limited broadcast wants the per-interface
                    # fan-out; a named address is honoured exactly, which keeps the tests off
                    # the real network.
                    if self.announce_to[0] == "255.255.255.255":
                        targets = broadcast_targets(self.announce_to[1])
                    else:
                        targets = [self.announce_to]
                    for target in targets:
                        try:
                            sock.sendto(beacon, target)
                            delivered += 1
                        except OSError:
                            continue
                    if not delivered:
                        self.logger.warning("beacon reached no interface")
                try:
                    data, address = sock.recvfrom(MAX_DATAGRAM_BYTES + 1)
                except socket.timeout:
                    continue
                except ConnectionResetError:
                    # Windows reports an ICMP port-unreachable for a datagram this
                    # socket sent as a reset on the next receive. The socket is
                    # fine; the peer that was not listening is the Mac's problem.
                    continue
                except OSError as exc:
                    if self._stop.is_set():
                        break
                    self.error = str(exc)
                    self.logger.error("pairing beacon stopped: %s", exc)
                    break
                message = decode(data)
                if message is None:
                    continue
                if message.get("type") == MSG_FIND:
                    # At most one answer per address per interval, so the port is no amplifier.
                    if now - answered.get(address[0], -BEACON_INTERVAL_SECONDS) >= BEACON_INTERVAL_SECONDS / 4:
                        if len(answered) > 256:
                            answered.clear()
                        answered[address[0]] = now
                        try:
                            sock.sendto(self._beacon(), address)
                        except OSError as exc:
                            self.logger.warning("beacon to %s not sent: %s", address[0], exc)
                    continue
                with self._lock:
                    reply = self.host.handle(message)
                    paired, self.host.paired = self.host.paired, None
                if reply is not None:
                    try:
                        sock.sendto(encode(reply), address)
                    except OSError as exc:
                        self.logger.warning("pairing reply not sent: %s", exc)
                if paired is not None:
                    self.logger.info("paired with %s at %s", paired[1] or "a Mac", address[0])
                    try:
                        self.on_paired(paired[0], paired[1], address[0])
                    except Exception:
                        self.logger.exception("on_paired failed")
        except Exception as exc:
            self.error = str(exc)
            self.logger.exception("pairing beacon stopped")
        finally:
            sock.close()


class Discovery:
    """The Mac's socket loop: listens for beacons and carries pairing attempts on the same
    socket, so a reply comes back to the port the PC heard from."""

    def __init__(self, logger=None, bind_port=PAIRING_PORT, clock=time.monotonic):
        self.logger = logger or logging.getLogger("Beamer")
        self.bind_port = bind_port
        self.clock = clock
        self._lock = threading.Lock()
        self._seen = {}
        self._replies = queue.Queue()
        self._stop = threading.Event()
        self._thread = None
        self._sock = None
        self._finding = None
        self._find_serial = 0
        self._next_find = 0.0
        self.error = None

    def find(self, host: str, port: int = PAIRING_PORT) -> None:
        """Ask `host` for its beacon, for a PC no broadcast reaches, and keep asking while
        discovery runs so it stays listed. Returns at once; the PC appears in pcs() when it
        answers. An empty host stops asking."""
        host = (host or "").strip()
        with self._lock:
            self._find_serial += 1
            serial = self._find_serial
            self._finding = None
            self._next_find = 0.0
        if host:
            # A name can take seconds to resolve, and this loop also carries the pairing replies.
            threading.Thread(target=self._resolve, args=(host, int(port), serial),
                             name="Beamer-find", daemon=True).start()

    def _resolve(self, host: str, port: int, serial: int) -> None:
        try:
            address = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_DGRAM)[0][4][0]
        except (OSError, IndexError) as exc:
            self.logger.warning("could not resolve %s: %s", host, exc)
            return
        with self._lock:
            if serial == self._find_serial:
                self._finding = (address, port)

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="Beamer-discovery", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        self._thread = None

    def pcs(self) -> list:
        """Every PC heard from recently: dicts of name, address, port, reply_port, pairing."""
        cutoff = self.clock() - BEACON_STALE_SECONDS
        with self._lock:
            stale = [key for key, entry in self._seen.items() if entry["seen_at"] < cutoff]
            for key in stale:
                del self._seen[key]
            return sorted(
                ({k: v for k, v in entry.items() if k != "seen_at"} for entry in self._seen.values()),
                key=lambda entry: (entry["name"].lower(), entry["address"]),
            )

    def pair(self, pc: dict, code: str, name: str = None) -> str:
        """Runs the exchange with `pc` (an entry from pcs()) and returns the token. Blocks for
        up to PAIR_ATTEMPTS replies' worth; call it off the main thread."""
        sock = self._sock
        if sock is None:
            raise PairingError("discovery is not running")
        client = PairingClient(pc["pair_id"], code, name or machine_name())
        target = (pc["address"], pc["reply_port"])
        while True:
            try:
                self._replies.get_nowait()
            except queue.Empty:
                break
        request = encode(client.request())
        for _attempt in range(PAIR_ATTEMPTS):
            sock.sendto(request, target)
            deadline = self.clock() + PAIR_REPLY_TIMEOUT_SECONDS
            while True:
                remaining = deadline - self.clock()
                if remaining <= 0:
                    break
                try:
                    reply, address = self._replies.get(timeout=remaining)
                except queue.Empty:
                    break
                if address[0] != target[0] or reply.get("pair") != client.pair_id:
                    continue
                return client.accept(reply)
        raise PairingError("no_answer")

    def _run(self) -> None:
        try:
            sock = _udp_socket(self.bind_port)
        except OSError as exc:
            self.error = str(exc)
            self.logger.error("discovery could not bind UDP %s: %s", self.bind_port, exc)
            return
        self.error = None
        self._sock = sock
        try:
            while not self._stop.is_set():
                self._send_find(sock)
                try:
                    data, address = sock.recvfrom(MAX_DATAGRAM_BYTES + 1)
                except socket.timeout:
                    continue
                except ConnectionResetError:
                    continue
                except OSError as exc:
                    if self._stop.is_set():
                        break
                    self.error = str(exc)
                    self.logger.error("discovery stopped: %s", exc)
                    break
                message = decode(data)
                if message is None:
                    continue
                kind = message.get("type")
                if kind == MSG_BEACON:
                    self._note_beacon(message, address)
                elif kind == MSG_PAIR_REPLY:
                    self._replies.put((message, address))
        except Exception as exc:
            self.error = str(exc)
            self.logger.exception("discovery stopped")
        finally:
            self._sock = None
            sock.close()

    def _send_find(self, sock) -> None:
        with self._lock:
            target = self._finding
            if target is None or self.clock() < self._next_find:
                return
            self._next_find = self.clock() + BEACON_INTERVAL_SECONDS
        try:
            sock.sendto(encode({"type": MSG_FIND}), target)
        except OSError as exc:
            self.logger.warning("could not ask %s for its beacon: %s", target[0], exc)

    def _note_beacon(self, message: dict, address) -> None:
        name = message.get("name")
        port = message.get("port")
        pair_id = message.get("pair")
        if not isinstance(name, str) or isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            return
        entry = {
            "name": name[:64] or address[0],
            "address": address[0],
            "port": port,
            "reply_port": address[1],
            "pair_id": pair_id if isinstance(pair_id, str) and pair_id else None,
            "seen_at": self.clock(),
        }
        with self._lock:
            self._seen[address[0]] = entry
