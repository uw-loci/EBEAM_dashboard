import json
import os
import shutil
import sys
import unittest
import uuid
from unittest.mock import MagicMock, patch

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from subsystem.beam_energy.beam_energy import BeamEnergySubsystem
from usr.beam_energy_warning_config import (
    DEFAULT_WARNING_LIMITS,
    load_beam_energy_warning_limits,
    normalize_warning_limits,
    save_beam_energy_warning_limits,
)


TEST_TMP_ROOT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "_tmp")
os.makedirs(TEST_TMP_ROOT, exist_ok=True)


class FakeLabel:
    def __init__(self):
        self.foreground = None

    def config(self, **kwargs):
        if "foreground" in kwargs:
            self.foreground = kwargs["foreground"]


class FakeVar:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


def copy_defaults():
    return {supply: dict(limits) for supply, limits in DEFAULT_WARNING_LIMITS.items()}


def make_subsystem(limits=None):
    subsystem = object.__new__(BeamEnergySubsystem)
    subsystem.logger = MagicMock()
    subsystem.supply_keys = [supply_key for supply_key, _unit_id in subsystem.supply_payload_map]
    subsystem.warning_limits = normalize_warning_limits(limits or DEFAULT_WARNING_LIMITS)
    subsystem.latest_actual_voltage_values = [None, None, None, None]
    subsystem.latest_actual_current_values = [None, None, None, None]
    subsystem.ui_elements = [
        {"voltage_display": FakeLabel(), "current_display": FakeLabel()}
        for _ in subsystem.supply_keys
    ]
    subsystem.warning_limit_entry_vars = [
        {field: FakeVar("") for field, _label, _unit in subsystem.warning_limit_fields}
        for _ in subsystem.supply_keys
    ]
    subsystem.warning_limit_value_vars = [
        {
            field: FakeVar(subsystem._format_warning_limit_setting(index, field))
            for field, _label, _unit in subsystem.warning_limit_fields
        }
        for index, _supply_key in enumerate(subsystem.supply_keys)
    ]
    return subsystem


class TestBeamEnergyWarningConfig(unittest.TestCase):
    def setUp(self):
        self.tempdir = os.path.join(TEST_TMP_ROOT, f"case_{uuid.uuid4().hex}")
        os.makedirs(self.tempdir, exist_ok=False)

    def tearDown(self):
        shutil.rmtree(self.tempdir, ignore_errors=True)

    def test_missing_file_returns_defaults(self):
        filepath = os.path.join(self.tempdir, "missing.json")
        logger = MagicMock()

        loaded = load_beam_energy_warning_limits(filepath=filepath, logger=logger)

        self.assertEqual(loaded, copy_defaults())
        logger.info.assert_called_with("No Beam Energy warning-limit configuration file found.")

    def test_partial_file_merges_with_defaults(self):
        filepath = os.path.join(self.tempdir, "limits.json")
        with open(filepath, "w") as file:
            json.dump({"pos1kv": {"max_current_ma": 12.5}}, file)

        loaded = load_beam_energy_warning_limits(filepath=filepath, logger=MagicMock())

        expected = copy_defaults()
        expected["pos1kv"]["max_current_ma"] = 12.5
        self.assertEqual(loaded, expected)

    def test_invalid_json_falls_back_to_defaults(self):
        filepath = os.path.join(self.tempdir, "limits.json")
        with open(filepath, "w") as file:
            file.write("{invalid json")
        logger = MagicMock()

        loaded = load_beam_energy_warning_limits(filepath=filepath, logger=logger)

        self.assertEqual(loaded, copy_defaults())
        self.assertIn("Error loading Beam Energy warning limits", logger.error.call_args[0][0])

    def test_save_writes_normalized_schema(self):
        filepath = os.path.join(self.tempdir, "usr_data", "limits.json")
        limits = copy_defaults()
        limits["pos20kv"]["max_current_ma"] = 0.75

        saved = save_beam_energy_warning_limits(limits, filepath=filepath, logger=MagicMock())

        self.assertTrue(saved)
        with open(filepath, "r") as file:
            data = json.load(file)
        self.assertEqual(data["pos20kv"]["max_current_ma"], 0.75)
        self.assertEqual(set(data.keys()), set(DEFAULT_WARNING_LIMITS.keys()))

    def test_values_above_default_caps_fall_back_to_defaults(self):
        loaded = normalize_warning_limits(
            {
                "pos1kv": {"max_voltage_v": 1000.1, "max_current_ma": 30.1},
                "pos20kv": {"min_voltage_v": 20000.1},
            },
            logger=MagicMock(),
        )

        self.assertEqual(loaded["pos1kv"]["max_voltage_v"], 1000.0)
        self.assertEqual(loaded["pos1kv"]["max_current_ma"], 30.0)
        self.assertEqual(loaded["pos20kv"]["min_voltage_v"], 0.0)


class TestBeamEnergyWarningIndicators(unittest.TestCase):
    def test_missing_readings_are_black(self):
        subsystem = make_subsystem()

        subsystem.apply_warning_indicators(0, None, None)

        self.assertEqual(subsystem.ui_elements[0]["voltage_display"].foreground, "black")
        self.assertEqual(subsystem.ui_elements[0]["current_display"].foreground, "black")

    def test_voltage_below_min_and_above_max_are_orange(self):
        subsystem = make_subsystem({"pos1kv": {"min_voltage_v": 100, "max_voltage_v": 900}})

        subsystem.apply_warning_indicators(0, 99.9, 1.0)
        self.assertEqual(subsystem.ui_elements[0]["voltage_display"].foreground, "#FFA500")

        subsystem.apply_warning_indicators(0, 900.1, 1.0)
        self.assertEqual(subsystem.ui_elements[0]["voltage_display"].foreground, "#FFA500")

    def test_current_above_max_is_orange(self):
        subsystem = make_subsystem({"pos1kv": {"max_current_ma": 10}})

        subsystem.apply_warning_indicators(0, 100.0, 10.001)

        self.assertEqual(subsystem.ui_elements[0]["current_display"].foreground, "#FFA500")

    def test_boundary_values_are_black(self):
        subsystem = make_subsystem(
            {"pos1kv": {"min_voltage_v": 100, "max_voltage_v": 900, "max_current_ma": 10}}
        )

        subsystem.apply_warning_indicators(0, 100.0, 10.0)
        self.assertEqual(subsystem.ui_elements[0]["voltage_display"].foreground, "black")
        self.assertEqual(subsystem.ui_elements[0]["current_display"].foreground, "black")

        subsystem.apply_warning_indicators(0, 900.0, 10.0)
        self.assertEqual(subsystem.ui_elements[0]["voltage_display"].foreground, "black")
        self.assertEqual(subsystem.ui_elements[0]["current_display"].foreground, "black")

    def test_negative_one_kv_uses_absolute_values(self):
        subsystem = make_subsystem(
            {"neg1kv": {"min_voltage_v": 0, "max_voltage_v": 1000, "max_current_ma": 30}}
        )

        subsystem.apply_warning_indicators(1, -1001.0, -30.1)

        self.assertEqual(subsystem.ui_elements[1]["voltage_display"].foreground, "#FFA500")
        self.assertEqual(subsystem.ui_elements[1]["current_display"].foreground, "#FFA500")


class TestBeamEnergyWarningValidation(unittest.TestCase):
    def test_invalid_entry_does_not_mutate_limits(self):
        subsystem = make_subsystem()
        before = dict(subsystem.warning_limits["pos1kv"])

        with patch("subsystem.beam_energy.beam_energy.messagebox.showerror") as showerror:
            changed = subsystem._set_warning_limit_from_raw(
                0,
                "max_voltage_v",
                "",
                show_dialogs=True,
                persist=False,
            )

        self.assertFalse(changed)
        self.assertEqual(subsystem.warning_limits["pos1kv"], before)
        showerror.assert_called_once()

    def test_max_voltage_below_min_is_rejected(self):
        subsystem = make_subsystem({"pos1kv": {"min_voltage_v": 500, "max_voltage_v": 1000}})
        before = dict(subsystem.warning_limits["pos1kv"])

        changed = subsystem._set_warning_limit_from_raw(
            0,
            "max_voltage_v",
            "499.99",
            show_dialogs=False,
            persist=False,
        )

        self.assertFalse(changed)
        self.assertEqual(subsystem.warning_limits["pos1kv"], before)

    def test_valid_set_updates_state_saves_and_rechecks_warning(self):
        subsystem = make_subsystem({"pos1kv": {"max_current_ma": 30}})
        subsystem.latest_actual_voltage_values[0] = 0.0
        subsystem.latest_actual_current_values[0] = 23.0
        subsystem.warning_limit_entry_vars[0]["max_current_ma"].set("22.5")

        with patch(
            "subsystem.beam_energy.beam_energy.save_beam_energy_warning_limits",
            return_value=True,
        ) as save_limits:
            subsystem.set_warning_limit(0, "max_current_ma")

        self.assertEqual(subsystem.warning_limits["pos1kv"]["max_current_ma"], 22.5)
        self.assertEqual(subsystem.warning_limit_entry_vars[0]["max_current_ma"].get(), "")
        self.assertEqual(
            subsystem.warning_limit_value_vars[0]["max_current_ma"].get(),
            "Limit set to: 22.5mA",
        )
        self.assertEqual(subsystem.ui_elements[0]["current_display"].foreground, "#FFA500")
        save_limits.assert_called_once()

    def test_value_above_default_cap_is_rejected(self):
        subsystem = make_subsystem()
        before = dict(subsystem.warning_limits["pos1kv"])

        changed = subsystem._set_warning_limit_from_raw(
            0,
            "max_voltage_v",
            "1000.1",
            show_dialogs=False,
            persist=False,
        )

        self.assertFalse(changed)
        self.assertEqual(subsystem.warning_limits["pos1kv"], before)

    def test_negative_one_kv_voltage_limit_display_has_negative_marker(self):
        subsystem = make_subsystem({"neg1kv": {"max_voltage_v": 955, "min_voltage_v": 12}})

        self.assertEqual(
            subsystem.warning_limit_value_vars[1]["max_voltage_v"].get(),
            "Limit set to: -955V",
        )
        self.assertEqual(
            subsystem.warning_limit_value_vars[1]["min_voltage_v"].get(),
            "Limit set to: -12V",
        )
        self.assertEqual(
            subsystem.warning_limit_value_vars[1]["max_current_ma"].get(),
            "Limit set to: 30mA",
        )


if __name__ == "__main__":
    unittest.main()
