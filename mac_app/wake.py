"""Wake-on-LAN for the PC, and the controller that sends it when a switch finds the PC asleep.

The hardware address is never typed. It is read from this Mac's ARP table whenever a
connection succeeds -- the Mac has just exchanged packets with the PC, so the entry is fresh --
and stored with the rest of that PC's settings.
"""

from __future__ import annotations

import re
import socket
import subprocess
import threading

from bridge import KVMController

WOL_PORT = 9
# Sleep answers in a few seconds; hibernate and a cold boot take most of a minute. Past this
# the PC is reported as not woken rather than the switch waiting forever.
WAKE_WINDOW_SECONDS = 60.0
WAKING_STATUS = "Waking Windows…"
NOT_WOKEN_STATUS = "Windows did not wake"

# Six groups of one or two hex digits: Windows pads and joins with "-", macOS leaves a leading
# zero off and joins with ":".
_MAC_PATTERN = re.compile(r"(?<![0-9A-Fa-f])([0-9A-Fa-f]{1,2}(?:[:-][0-9A-Fa-f]{1,2}){5})(?![0-9A-Fa-f])")


def parse_mac(text: str):
    """The address as six upper-case, zero-padded pairs joined with ":", or None."""
    match = _MAC_PATTERN.fullmatch(text.strip()) if isinstance(text, str) else None
    if match is None:
        return None
    return ":".join(part.zfill(2).upper() for part in re.split(r"[:-]", match.group(1)))


def mac_from_arp_output(output: str, ip: str):
    """The hardware address `arp` printed for `ip`, from either platform's layout:

        Windows   192.168.1.3           02-1a-2b-3c-0d-4e     dynamic
        macOS     ? (192.168.1.3) at 2:1a:2b:3c:d:4e on en0 ifscope [ethernet]
    """
    ip_pattern = re.compile(r"(?<![\d.])" + re.escape(ip) + r"(?![\d.])")
    for line in output.splitlines():
        if not ip_pattern.search(line):
            continue
        match = _MAC_PATTERN.search(line)
        if match is not None:
            return parse_mac(match.group(1))
    return None


def lookup_mac(host: str):
    """The hardware address this Mac's ARP table holds for `host`, or None. Only useful right
    after talking to the host, which is the only time it is called."""
    try:
        ip = socket.gethostbyname(host)
        completed = subprocess.run(["arp", "-n", ip], capture_output=True, text=True, timeout=3.0, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return mac_from_arp_output(completed.stdout, ip)


def magic_packet(mac: str) -> bytes:
    address = parse_mac(mac)
    if address is None:
        raise ValueError(f"not a hardware address: {mac!r}")
    return b"\xff" * 6 + bytes.fromhex(address.replace(":", "")) * 16


def send_magic_packet(mac: str, host: str = None) -> None:
    """Broadcast the packet, and also send it straight at the host's last address, which is
    what gets through on a network that filters broadcasts."""
    packet = magic_packet(mac)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(packet, ("255.255.255.255", WOL_PORT))
        if host:
            try:
                sock.sendto(packet, (host, WOL_PORT))
            except OSError:
                pass
    finally:
        sock.close()


class WakingController(KVMController):
    """KVMController plus wake-on-LAN. A switch attempted while the PC is unreachable sends the
    magic packet and shows WAKING_STATUS until the connection worker gets through, the same
    shape as the receiver's "Unlocking Windows…" -- and, like that path, nothing is queued: the
    switch is refused, and the person switches again once the PC is up. Completing it for them
    a minute later, into whatever they had gone back to typing on the Mac, would be worse.

    `on_mac_learned(mac)` fires off the connection thread when the ARP table names a different
    address from the one stored; the app persists it."""

    WAKE_POLL_SECONDS = 0.5

    def __init__(self, cfg, wake_sender=send_magic_packet, mac_lookup=lookup_mac, **kwargs):
        self._waking = False
        self._wake_lock = threading.Lock()
        self.wake_sender = wake_sender
        self.mac_lookup = mac_lookup
        self.on_mac_learned = None
        super().__init__(cfg, **kwargs)

    @property
    def connection_status(self):
        return WAKING_STATUS if self._waking else self._connection_status

    @connection_status.setter
    def connection_status(self, value):
        self._connection_status = value

    @property
    def waking(self) -> bool:
        return self._waking

    @property
    def can_wake(self) -> bool:
        return bool(self.cfg.mac_address) and not self.connected

    def set_redirecting(self, value, edge=None, offset=None):
        if value and not self.redirecting and not self.connected and self.cfg.mac_address:
            self.wake()
            return False
        return super().set_redirecting(value, edge, offset)

    def wake(self) -> bool:
        """Sends the packet and starts waiting, unless a wake is already in flight."""
        with self._wake_lock:
            if self._waking or self.connected:
                return False
            self._waking = True
        threading.Thread(target=self._wake_worker, name="wake", daemon=True).start()
        return True

    def _wake_worker(self):
        started = self.clock()
        try:
            self.wake_sender(self.cfg.mac_address, self.cfg.host)
        except (OSError, ValueError) as exc:
            self.logger.warning("wake-on-LAN packet not sent: %s", exc)
            self._waking = False
            self.connection_status = NOT_WOKEN_STATUS
            self._alert("Beamer", "Could not send the wake-up packet")
            return
        self.logger.info("sent wake-on-LAN to %s", self.cfg.host)
        self._alert("Beamer", WAKING_STATUS)
        while not self.stop_event.wait(self.WAKE_POLL_SECONDS):
            if self.connected:
                self._waking = False
                self.logger.info("Windows woke and connected")
                self._alert("Beamer", "Windows is awake — switch again to send input")
                return
            if self.clock() - started >= WAKE_WINDOW_SECONDS:
                break
        self._waking = False
        self.connection_status = NOT_WOKEN_STATUS
        self.logger.warning("Windows did not answer within %.0fs of the wake-on-LAN packet", WAKE_WINDOW_SECONDS)
        self._alert("Beamer", NOT_WOKEN_STATUS)

    def _connect_once(self):
        connected = super()._connect_once()
        if connected:
            self._learn_mac()
        return connected

    def _learn_mac(self):
        try:
            mac = self.mac_lookup(self.cfg.host)
        except Exception:
            self.logger.exception("hardware address lookup failed")
            return
        if not mac or mac == self.cfg.mac_address:
            return
        self.cfg.mac_address = mac
        self.logger.info("learned the PC's hardware address from the ARP table")
        callback = self.on_mac_learned
        if callback is not None:
            try:
                callback(mac)
            except Exception:
                self.logger.exception("on_mac_learned callback failed")
