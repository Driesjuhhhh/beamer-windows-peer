"""Pair two Windows installations using Beamer's existing one-use code exchange.

Run with Beamer closed on both PCs so configuration cannot be overwritten by
an already running window. No tokens or codes are passed on the command line.
"""

import argparse
from dataclasses import replace
from getpass import getpass
from pathlib import Path
import threading
import time

from app_config import default_config, default_config_path, load_config, save_config
import pairing
from sender import is_this_machine


def paired_config(current, token, name, address, edge, port):
    return replace(
        current, auth_token=token, paired_with=name, mac_host=address,
        host=pairing.local_address_towards(address), port=port,
        peer_platform="windows", mac_return_edge=edge,
        arrangement_set_at=int(time.time()), mac_hardware_address="",
    )


def host_pair(path, current, edge):
    completed = threading.Event()
    result = []

    def accepted(token, name, address):
        result.append((token, name, address))
        completed.set()

    announcer = pairing.Announcer(lambda: current.port, accepted)
    announcer.start()
    try:
        code = announcer.begin_pairing()
        print(f"Pairing code: {code} (valid for 60 seconds)", flush=True)
        print("Enter this code on the other PC. Both Beamer apps must be closed.", flush=True)
        deadline = time.monotonic() + pairing.CODE_LIFETIME_SECONDS
        while not completed.wait(0.1):
            if announcer.error:
                raise pairing.PairingError(announcer.error)
            if time.monotonic() >= deadline or announcer.outcome in ("refused", "expired"):
                raise pairing.PairingError("code expired or pairing was refused; start again")
        token, name, address = result[0]
        save_config(path, paired_config(current, token, name, address, edge, current.port))
    finally:
        announcer.stop()


def join_pair(path, current, address, edge):
    if is_this_machine(address):
        raise pairing.PairingError("choose the other PC's address")
    discovery = pairing.Discovery(bind_port=0)
    discovery.start()
    try:
        discovery.find(address)
        deadline = time.monotonic() + 10
        pc = None
        while time.monotonic() < deadline:
            if discovery.error:
                raise pairing.PairingError(discovery.error)
            pc = next((pc for pc in discovery.pcs() if pc.get("pair_id") and pc.get("address") == address), None)
            if pc:
                break
            time.sleep(0.05)
        if pc is None:
            raise pairing.PairingError("no pairing host found; check address, code and UDP firewall")
        code = getpass("Code shown on the other PC: ").replace(" ", "")
        if len(code) != pairing.CODE_DIGITS or not code.isascii() or not code.isdigit():
            raise pairing.PairingError("enter the six-digit code")
        token, authenticated_name = discovery.pair(pc, code)
        save_config(path, paired_config(current, token, authenticated_name, pc["address"], edge, pc["port"]))
    finally:
        discovery.stop()


def main():
    parser = argparse.ArgumentParser(description="Pair two Windows PCs; close Beamer first")
    parser.add_argument("mode", choices=("host", "join"))
    parser.add_argument("--address", help="pairing host IP address (join only)")
    parser.add_argument("--edge", required=True, choices=("left", "right", "top", "bottom"),
                        help="edge of THIS PC facing the other PC")
    parser.add_argument("--config", type=Path, default=default_config_path())
    args = parser.parse_args()
    if args.mode == "join" and not args.address:
        parser.error("join requires --address")
    current = load_config(args.config) if args.config.exists() else default_config()
    try:
        if args.mode == "host":
            host_pair(args.config, current, args.edge)
        else:
            join_pair(args.config, current, args.address, args.edge)
    except (OSError, ValueError, pairing.PairingError) as exc:
        parser.exit(1, f"Pairing failed: {exc}\n")
    print("Paired. Start the modified Beamer app on both PCs.")


if __name__ == "__main__":
    main()
