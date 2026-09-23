import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config as config_module
import protocol
import settings_store
from settings_store import SettingsError, SettingsStore, config_to_raw, migrate_legacy_config


class SettingsStoreTests(unittest.TestCase):
    def valid_raw(self):
        return {
            "host": "192.0.2.10",
            "port": 24820,
            "auth_token": "synthetic-token",
            "trigger_key": "alt_r",
            "double_tap_ms": 300,
            "key_map": {"cmd": "ctrl", "cmd_r": "ctrl"},
            "reconnect_interval_s": 2.0,
        }

    def test_save_is_private_and_round_trips_shared_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            store = SettingsStore(path)
            saved = store.save(self.valid_raw())
            loaded = store.load()
            self.assertEqual(saved, loaded)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            raw = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(raw["trigger_key"], "alt_r")

    def test_both_directions_default_on_and_each_switch_round_trips(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SettingsStore(Path(directory) / "config.json")
            loaded = store.save(self.valid_raw())
            self.assertTrue(loaded.send_to_windows)
            self.assertTrue(loaded.allow_windows_to_drive)
            raw = config_to_raw(loaded)
            raw["send_to_windows"] = False
            loaded = store.save(raw)
            self.assertFalse(loaded.send_to_windows)
            self.assertTrue(loaded.allow_windows_to_drive)
            self.assertFalse(store.load().send_to_windows)

    def test_legacy_positional_key_map_is_replaced_by_the_semantic_default(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            raw = self.valid_raw()
            raw["key_map"] = {
                "alt": "alt", "alt_r": "alt",
                "ctrl": "ctrl", "ctrl_r": "ctrl",
                "cmd": "cmd", "cmd_r": "cmd",
            }
            loaded = SettingsStore(path).save(raw)
            self.assertEqual(loaded.key_map["cmd"], "ctrl")
            self.assertEqual(loaded.key_map["ctrl"], "cmd")

    def test_hand_edited_key_map_survives(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            raw = self.valid_raw()
            raw["key_map"] = {"cmd": "cmd", "ctrl": "alt"}
            loaded = SettingsStore(path).save(raw)
            self.assertEqual(loaded.key_map["cmd"], "cmd")
            self.assertEqual(loaded.key_map["ctrl"], "alt")

    def test_rejects_placeholder_token(self):
        with tempfile.TemporaryDirectory() as directory:
            raw = self.valid_raw()
            raw["auth_token"] = "CHANGE_ME"
            with self.assertRaises(SettingsError):
                SettingsStore(Path(directory) / "config.json").save(raw)

    def test_rejects_unknown_trigger(self):
        with tempfile.TemporaryDirectory() as directory:
            raw = self.valid_raw()
            raw["trigger_key"] = "not_a_key"
            with self.assertRaises(SettingsError):
                SettingsStore(Path(directory) / "config.json").save(raw)

    def test_config_without_crossing_keys_loads_the_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps(self.valid_raw()), encoding="utf-8")
            loaded = SettingsStore(path).load()
            self.assertEqual(loaded.trigger_style, "double_tap")
            self.assertEqual(loaded.crossing, config_module.DEFAULT_CROSSING)
            self.assertIsNot(loaded.crossing, config_module.DEFAULT_CROSSING)

    def test_partial_crossing_object_keeps_the_other_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            raw = self.valid_raw()
            raw["crossing"] = {"edge": "left", "resistance_px": 40}
            raw["trigger_style"] = "hold"
            loaded = SettingsStore(Path(directory) / "config.json").save(raw)
            self.assertEqual(loaded.crossing["edge"], "left")
            self.assertEqual(loaded.crossing["resistance_px"], 40)
            self.assertEqual(loaded.crossing["methods"], ["shortcut", "edge"])
            self.assertTrue(loaded.crossing["haptics"])
            self.assertEqual(loaded.trigger_style, "hold")

    def test_rejects_bad_crossing_values_by_field(self):
        cases = [
            ({"methods": ["edge", "telepathy"]}, "crossing.methods"),
            ({"edge": "sideways"}, "crossing.edge"),
            ({"corner": "middle"}, "crossing.corner"),
            ({"resistance_px": 501}, "crossing.resistance_px"),
            ({"resistance_px": -1}, "crossing.resistance_px"),
            ({"glow": "yes"}, "crossing.glow"),
            ({"notch_style": "sparkle"}, "crossing.notch_style"),
            ({"notch_after_ms": 50}, "crossing.notch_after_ms"),
            ({"notch_after_ms": 1.5}, "crossing.notch_after_ms"),
            ({"haptic_feel": "thunderous"}, "crossing.haptic_feel"),
            ({"haptic_steps": "thirds"}, "crossing.haptic_steps"),
            ({"glow_style": "sparkle"}, "crossing.glow_style"),
            ({"glow_colour": "tartan"}, "crossing.glow_colour"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            for crossing, field in cases:
                with self.subTest(field=field):
                    raw = self.valid_raw()
                    raw["crossing"] = crossing
                    with self.assertRaises(SettingsError) as caught:
                        SettingsStore(Path(directory) / "config.json").save(raw)
                    self.assertIn(field, str(caught.exception))

    def test_rejects_unknown_trigger_style(self):
        with tempfile.TemporaryDirectory() as directory:
            raw = self.valid_raw()
            raw["trigger_style"] = "triple_tap"
            with self.assertRaises(SettingsError):
                SettingsStore(Path(directory) / "config.json").save(raw)

    def test_key_map_style_names_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            raw = self.valid_raw()
            raw["key_map"] = "positional"
            loaded = SettingsStore(path).save(raw)
            self.assertEqual(loaded.key_map, config_module.LEGACY_POSITIONAL_KEY_MAP)
            self.assertEqual(config_to_raw(loaded)["key_map"], "positional")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["key_map"], "positional")
            raw["key_map"] = "semantic"
            self.assertEqual(SettingsStore(path).save(raw).key_map, config_module.DEFAULT_KEY_MAP)
            raw["key_map"] = "chaotic"
            with self.assertRaises(SettingsError):
                SettingsStore(path).save(raw)

    def test_migrate_legacy_config_copies_without_touching_the_old_file(self):
        with tempfile.TemporaryDirectory() as directory:
            legacy_dir = Path(directory) / "OpenKB"
            legacy_dir.mkdir()
            legacy_path = legacy_dir / "config.json"
            legacy_path.write_text(json.dumps(self.valid_raw()), encoding="utf-8")
            os.chmod(legacy_path, 0o600)
            new_dir = Path(directory) / "Beamer"
            new_path = new_dir / "config.json"
            with mock.patch.multiple(
                settings_store,
                LEGACY_APP_SUPPORT_DIRECTORY=legacy_dir,
                LEGACY_SETTINGS_PATH=legacy_path,
                APP_SUPPORT_DIRECTORY=new_dir,
                DEFAULT_SETTINGS_PATH=new_path,
            ):
                self.assertTrue(migrate_legacy_config())
                self.assertTrue(legacy_path.exists())
                self.assertEqual(
                    json.loads(new_path.read_text(encoding="utf-8")),
                    json.loads(legacy_path.read_text(encoding="utf-8")),
                )
                self.assertEqual(new_path.stat().st_mode & 0o777, 0o600)
                # A second run must not overwrite the now-existing new config.
                new_path.write_text(json.dumps({"changed": True}), encoding="utf-8")
                self.assertFalse(migrate_legacy_config())
                self.assertEqual(json.loads(new_path.read_text(encoding="utf-8")), {"changed": True})

    def test_migrate_legacy_config_is_a_noop_with_no_legacy_file(self):
        with tempfile.TemporaryDirectory() as directory:
            legacy_dir = Path(directory) / "OpenKB"
            new_dir = Path(directory) / "Beamer"
            with mock.patch.multiple(
                settings_store,
                LEGACY_APP_SUPPORT_DIRECTORY=legacy_dir,
                LEGACY_SETTINGS_PATH=legacy_dir / "config.json",
                APP_SUPPORT_DIRECTORY=new_dir,
                DEFAULT_SETTINGS_PATH=new_dir / "config.json",
            ):
                self.assertFalse(migrate_legacy_config())
                self.assertFalse(new_dir.exists())


if __name__ == "__main__":
    unittest.main()


class LegacyPortTests(unittest.TestCase):
    def raw(self, port):
        return {
            "host": "192.0.2.10",
            "port": port,
            "auth_token": "synthetic-token",
            "trigger_key": "alt_r",
            "double_tap_ms": 300,
            "key_map": {"cmd": "ctrl", "cmd_r": "ctrl"},
            "reconnect_interval_s": 2.0,
        }

    def test_the_old_default_port_is_moved_and_the_move_is_written_down(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            store = SettingsStore(path)
            store.save(self.raw(protocol.LEGACY_DEFAULT_PORT))
            self.assertEqual(store.load().port, protocol.DEFAULT_PORT)
            on_disk = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(on_disk["port"], protocol.DEFAULT_PORT)

    def test_a_port_someone_chose_is_left_alone(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            store = SettingsStore(path)
            store.save(self.raw(9000))
            self.assertEqual(store.load().port, 9000)

    def test_both_ports_are_below_the_range_the_system_hands_out(self):
        self.assertLess(protocol.DEFAULT_PORT, 49152)
        self.assertLess(protocol.PAIRING_PORT, 49152)

