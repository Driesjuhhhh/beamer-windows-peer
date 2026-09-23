"""Shared config.json loader for mac_sender.py and win_receiver.py."""

import json
import os
from dataclasses import dataclass, field

from crossing import DEFAULT_CROSSING

DEFAULT_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

DEFAULT_KEY_MAP = {
    "alt": "alt",
    "alt_r": "alt",
    "ctrl": "cmd",
    "ctrl_r": "cmd",
    "cmd": "ctrl",
    "cmd_r": "ctrl",
}

# The positional map Beamer shipped before 09-09-2026, written verbatim into
# every existing config.json. A saved key_map beats the default, so without
# this an upgraded install would silently keep sending Cmd as the Windows key.
# A saved map whose every entry matches this one is the old default rather
# than a deliberate choice, so it is discarded.
LEGACY_POSITIONAL_KEY_MAP = {
    "alt": "alt",
    "alt_r": "alt",
    "ctrl": "ctrl",
    "ctrl_r": "ctrl",
    "cmd": "cmd",
    "cmd_r": "cmd",
}


# The two modifier styles the settings window offers. A saved key_map may be one of these
# names instead of a JSON object; Positional has to be saved by name, because its object form is
# the pre-09-09-2026 default and is discarded on load (see LEGACY_POSITIONAL_KEY_MAP).
KEY_MAP_STYLES = {
    "semantic": DEFAULT_KEY_MAP,
    "positional": LEGACY_POSITIONAL_KEY_MAP,
}


class ConfigError(Exception):
    pass


@dataclass
class Config:
    host: str
    port: int
    auth_token: str
    trigger_key: str = "alt_r"
    double_tap_ms: int = 300
    key_map: dict = field(default_factory=lambda: dict(DEFAULT_KEY_MAP))
    reconnect_interval_s: float = 2.0
    trigger_style: str = "double_tap"
    crossing: dict = field(default_factory=lambda: dict(DEFAULT_CROSSING))
    # Learned, never typed: the PC's name from its pairing beacon and its hardware address from
    # the ARP table, which is what wake-on-LAN needs.
    pc_name: str = ""
    mac_address: str = ""
    # One switch per direction, each in the menu bar: this Mac's input going to Windows, and
    # the PC's input arriving here. Off stops that direction only; the other keeps working.
    send_to_windows: bool = True
    allow_windows_to_drive: bool = True


def key_map_style(key_map):
    """The name of a key_map when it is one of the two offered styles, else None."""
    for name, mapping in KEY_MAP_STYLES.items():
        if key_map == mapping:
            return name
    return None


def load_config(path: str = None) -> Config:
    path = path or DEFAULT_CONFIG_PATH
    if not os.path.exists(path):
        raise ConfigError(
            f"config file not found: {path}\n"
            f"Copy config.example.json to config.json and fill in your own values."
        )

    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    missing = [k for k in ("host", "port", "auth_token") if k not in raw]
    if missing:
        raise ConfigError(f"config.json is missing required field(s): {', '.join(missing)}")

    # Empty means not yet paired, which every setting must still be able to save
    # around; only the example file's placeholder is refused.
    if raw["auth_token"] == "CHANGE_ME":
        raise ConfigError("config.json auth_token is still the placeholder — pair with a PC or pick a real shared secret")

    key_map = dict(DEFAULT_KEY_MAP)
    saved_key_map = raw.get("key_map", {})
    if isinstance(saved_key_map, str):
        if saved_key_map not in KEY_MAP_STYLES:
            raise ConfigError(f"config.json key_map style must be one of: {', '.join(KEY_MAP_STYLES)}")
        key_map = dict(KEY_MAP_STYLES[saved_key_map])
    elif not isinstance(saved_key_map, dict):
        raise ConfigError("config.json key_map must be a JSON object or a style name")
    elif saved_key_map != LEGACY_POSITIONAL_KEY_MAP:
        # Only the whole old default is the accident. A partial map whose
        # entries happen to agree with it -- {"cmd": "cmd"} on its own -- is a
        # choice, and was being thrown away.
        key_map.update(saved_key_map)

    crossing = dict(DEFAULT_CROSSING)
    saved_crossing = raw.get("crossing", {})
    if not isinstance(saved_crossing, dict):
        raise ConfigError("config.json crossing must be a JSON object")
    crossing.update(saved_crossing)
    crossing["methods"] = list(crossing["methods"])
    crossing["resistance_px"] = int(crossing["resistance_px"])

    return Config(
        host=raw["host"],
        port=int(raw["port"]),
        auth_token=raw["auth_token"],
        trigger_key=raw.get("trigger_key", "alt_r"),
        double_tap_ms=int(raw.get("double_tap_ms", 300)),
        key_map=key_map,
        reconnect_interval_s=float(raw.get("reconnect_interval_s", 2.0)),
        trigger_style=str(raw.get("trigger_style", "double_tap")),
        crossing=crossing,
        pc_name=str(raw.get("pc_name", "") or ""),
        mac_address=str(raw.get("mac_address", "") or ""),
        send_to_windows=raw.get("send_to_windows", True) is not False,
        allow_windows_to_drive=raw.get("allow_windows_to_drive", True) is not False,
    )
