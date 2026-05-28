import json
import os
import shutil
import sys
import unittest
import uuid
from unittest.mock import MagicMock, patch

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from subsystem.beam_energy.beam_energy import BeamEnergySubsystem
from utils import LogLevel
from usr.beam_energy_warning_config import (
    BEAMS_ESTOP_CURRENT_FIELD,
    DEFAULT_WARNING_LIMITS,
    POS20KV_SUPPLY_KEY,
    load_beam_energy_warning_limits,
    normalize_warning_limits,
    save_beam_energy_warning_limits,
)


TEST_TMP_ROOT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "_tmp")
os.makedirs(TEST_TMP_ROOT, exist_ok=True)


# Lightweight stand-ins let these tests exercise BeamEnergy logic without starting Tk.
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
    # Build only the state touched by warning-limit validation and indicator refreshes.
    subsystem = object.__new__(BeamEnergySubsystem)
    subsystem.logger = MagicMock()
    subsystem.supply_keys = [supply_key for supply_key, _unit_id in subsystem.supply_payload_map]
    subsystem.warning_limits = normalize_warning_limits(limits or DEFAULT_WARNING_LIMITS)
    subsystem.power_supplies = [
        {"name": "+1kV Matsusada PS", "type": "matsusada", "voltage": 1000},
        {"name": "-1kV Matsusada PS", "type": "matsusada", "voltage": -1000},
        {"name": "+20kV Bertan PS", "type": "bertan", "voltage": 20000},
        {"name": "+3kV Bertan PS", "type": "bertan", "voltage": 3000},
    ]
    subsystem.latest_actual_voltage_values = [None, None, None, None]
    subsystem.latest_actual_current_values = [None, None, None, None]
    subsystem.beams_estop_callback = None
    subsystem.radiation_indicator_callback = None
    subsystem._radiation_indicator_sent = None
    subsystem.beams_estop_current_entry_var = FakeVar("")
    subsystem.beams_estop_current_value_var = FakeVar(
        subsystem._format_beams_estop_current_limit_setting()
    )
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
    """Persisted warning-limit configuration and startup normalization scenarios."""

    def setUp(self):
        self.tempdir = os.path.join(TEST_TMP_ROOT, f"case_{uuid.uuid4().hex}")
        os.makedirs(self.tempdir, exist_ok=False)

    def tearDown(self):
        shutil.rmtree(self.tempdir, ignore_errors=True)

    def test_missing_file_returns_defaults(self):
        # First launch should work without a user config file.
        filepath = os.path.join(self.tempdir, "missing.json")
        logger = MagicMock()

        loaded = load_beam_energy_warning_limits(filepath=filepath, logger=logger)

        self.assertEqual(loaded, copy_defaults())
        logger.info.assert_called_with("No Beam Energy warning-limit configuration file found.")

    def test_partial_file_merges_with_defaults(self):
        # Older/partial config files should preserve valid user values and fill the rest.
        filepath = os.path.join(self.tempdir, "limits.json")
        with open(filepath, "w") as file:
            json.dump({"pos1kv": {"max_current_ma": 12.5}}, file)

        loaded = load_beam_energy_warning_limits(filepath=filepath, logger=MagicMock())

        expected = copy_defaults()
        expected["pos1kv"]["max_current_ma"] = 12.5
        self.assertEqual(loaded, expected)

    def test_invalid_json_falls_back_to_defaults(self):
        # A corrupt config file must not prevent Beam Energy from initializing safely.
        filepath = os.path.join(self.tempdir, "limits.json")
        with open(filepath, "w") as file:
            file.write("{invalid json")
        logger = MagicMock()

        loaded = load_beam_energy_warning_limits(filepath=filepath, logger=logger)

        self.assertEqual(loaded, copy_defaults())
        self.assertIn("Error loading Beam Energy warning limits", logger.error.call_args[0][0])

    def test_save_writes_normalized_schema(self):
        # Save goes through normalization so the on-disk schema remains complete.
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
        # Stored values above hardware/display caps are discarded instead of trusted.
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

    def test_default_pos20kv_estop_limit_is_one_ma(self):
        # The new +20kV shutdown threshold defaults to the original 1 mA warning cap.
        self.assertEqual(
            DEFAULT_WARNING_LIMITS[POS20KV_SUPPLY_KEY][BEAMS_ESTOP_CURRENT_FIELD],
            1.0,
        )

    def test_invalid_pos20kv_estop_limit_falls_back_to_default(self):
        # Saved E-STOP limits above 1 mA are unsafe and fall back to the default.
        loaded = normalize_warning_limits(
            {"pos20kv": {BEAMS_ESTOP_CURRENT_FIELD: 1.1}},
            logger=MagicMock(),
        )

        self.assertEqual(
            loaded[POS20KV_SUPPLY_KEY][BEAMS_ESTOP_CURRENT_FIELD],
            1.0,
        )

    def test_pos20kv_max_current_clamps_to_estop_limit(self):
        # Migration path: if an old config has Max I above E-STOP, clamp Max I down.
        logger = MagicMock()

        loaded = normalize_warning_limits(
            {"pos20kv": {"max_current_ma": 0.9, BEAMS_ESTOP_CURRENT_FIELD: 0.75}},
            logger=logger,
        )

        self.assertEqual(loaded[POS20KV_SUPPLY_KEY]["max_current_ma"], 0.75)
        self.assertEqual(loaded[POS20KV_SUPPLY_KEY][BEAMS_ESTOP_CURRENT_FIELD], 0.75)
        self.assertTrue(logger.warning.called)


class TestBeamEnergyWarningIndicators(unittest.TestCase):
    """Runtime display-color and automatic E-STOP trigger scenarios."""

    def test_missing_readings_are_black(self):
        # Missing/disconnected readings should clear warning colors and never trip.
        subsystem = make_subsystem()

        subsystem.apply_warning_indicators(0, None, None)

        self.assertEqual(subsystem.ui_elements[0]["voltage_display"].foreground, "black")
        self.assertEqual(subsystem.ui_elements[0]["current_display"].foreground, "black")

    def test_voltage_below_min_and_above_max_use_warning_color(self):
        # Voltage warnings use the warning color for either side of the allowed range.
        subsystem = make_subsystem({"pos1kv": {"min_voltage_v": 100, "max_voltage_v": 900}})

        subsystem.apply_warning_indicators(0, 99.9, 1.0)
        self.assertEqual(
            subsystem.ui_elements[0]["voltage_display"].foreground,
            BeamEnergySubsystem.WARNING_TEXT_COLOR,
        )

        subsystem.apply_warning_indicators(0, 900.1, 1.0)
        self.assertEqual(
            subsystem.ui_elements[0]["voltage_display"].foreground,
            BeamEnergySubsystem.WARNING_TEXT_COLOR,
        )

    def test_current_above_max_uses_warning_color(self):
        # Non-20kV over-current warnings are visual/logging only.
        subsystem = make_subsystem({"pos1kv": {"max_current_ma": 10}})

        subsystem.apply_warning_indicators(0, 100.0, 10.001)

        self.assertEqual(
            subsystem.ui_elements[0]["current_display"].foreground,
            BeamEnergySubsystem.WARNING_TEXT_COLOR,
        )

    def test_pos20kv_current_above_max_below_estop_uses_warning_color_without_estop(self):
        # +20kV current between Max I and E-STOP is still only a warning.
        subsystem = make_subsystem(
            {"pos20kv": {"max_current_ma": 0.5, BEAMS_ESTOP_CURRENT_FIELD: 0.75}}
        )
        subsystem.beams_estop_callback = MagicMock()

        subsystem.apply_warning_indicators(2, 100.0, 0.6)

        self.assertEqual(
            subsystem.ui_elements[2]["current_display"].foreground,
            BeamEnergySubsystem.WARNING_TEXT_COLOR,
        )
        subsystem.beams_estop_callback.assert_not_called()

    def test_pos20kv_current_equal_to_estop_limit_is_not_estop(self):
        # Threshold checks are strict "greater than"; equality remains in range.
        subsystem = make_subsystem(
            {"pos20kv": {"max_current_ma": 0.5, BEAMS_ESTOP_CURRENT_FIELD: 0.75}}
        )
        subsystem.beams_estop_callback = MagicMock()

        subsystem.apply_warning_indicators(2, 100.0, 0.75)

        self.assertEqual(
            subsystem.ui_elements[2]["current_display"].foreground,
            BeamEnergySubsystem.WARNING_TEXT_COLOR,
        )
        subsystem.beams_estop_callback.assert_not_called()

    def test_pos20kv_current_above_estop_is_red_and_calls_estop_each_poll(self):
        # While current exceeds the E-STOP threshold, red overrides the warning color.
        subsystem = make_subsystem(
            {"pos20kv": {"max_current_ma": 0.5, BEAMS_ESTOP_CURRENT_FIELD: 0.75}}
        )
        subsystem.beams_estop_callback = MagicMock()

        subsystem.apply_warning_indicators(2, 100.0, 0.751)
        # A second over-limit poll should retry the E-STOP handler.
        subsystem.apply_warning_indicators(2, 100.0, 0.8)

        self.assertEqual(subsystem.ui_elements[2]["current_display"].foreground, "red")
        self.assertEqual(subsystem.beams_estop_callback.call_count, 2)

        critical_logs = [
            call for call in subsystem.logger.log.call_args_list
            if len(call.args) >= 2 and call.args[1] == LogLevel.CRITICAL
        ]
        self.assertEqual(len(critical_logs), 2)

    def test_pos20kv_estop_does_not_trigger_at_or_below_limit(self):
        # At-limit readings do not fire; later over-limit readings still do.
        subsystem = make_subsystem(
            {"pos20kv": {"max_current_ma": 0.5, BEAMS_ESTOP_CURRENT_FIELD: 0.75}}
        )
        subsystem.beams_estop_callback = MagicMock()

        subsystem.apply_warning_indicators(2, 100.0, 0.8)
        subsystem.apply_warning_indicators(2, 100.0, 0.75)
        subsystem.apply_warning_indicators(2, 100.0, 0.8)

        self.assertEqual(subsystem.beams_estop_callback.call_count, 2)

    def test_other_supplies_never_trigger_beams_estop(self):
        # The automatic shutdown path is intentionally scoped to the +20kV Bertan.
        subsystem = make_subsystem()
        subsystem.beams_estop_callback = MagicMock()

        subsystem.apply_warning_indicators(0, 100.0, 31.0)
        subsystem.apply_warning_indicators(1, -100.0, 31.0)
        subsystem.apply_warning_indicators(3, 100.0, 11.0)

        subsystem.beams_estop_callback.assert_not_called()

    def test_pos20kv_voltage_above_threshold_sets_radiation_indicator_true(self):
        subsystem = make_subsystem()
        subsystem.radiation_indicator_callback = MagicMock()

        subsystem.apply_warning_indicators(2, 10000.1, 0.0)

        subsystem.radiation_indicator_callback.assert_called_once_with(True)

    def test_pos20kv_voltage_equal_to_threshold_sets_radiation_indicator_true(self):
        subsystem = make_subsystem()
        subsystem.radiation_indicator_callback = MagicMock()

        subsystem.apply_warning_indicators(2, 10000.0, 0.0)

        subsystem.radiation_indicator_callback.assert_called_once_with(True)

    def test_pos20kv_voltage_below_threshold_sets_radiation_indicator_false(self):
        subsystem = make_subsystem()
        subsystem.radiation_indicator_callback = MagicMock()

        subsystem.apply_warning_indicators(2, 9999.9, 0.0)

        subsystem.radiation_indicator_callback.assert_called_once_with(False)

    def test_pos20kv_voltage_falling_below_threshold_sets_radiation_indicator_false(self):
        subsystem = make_subsystem()
        subsystem.radiation_indicator_callback = MagicMock()

        subsystem.apply_warning_indicators(2, 10000.1, 0.0)
        subsystem.apply_warning_indicators(2, 9999.9, 0.0)

        self.assertEqual(
            [call.args[0] for call in subsystem.radiation_indicator_callback.call_args_list],
            [True, False],
        )

    def test_pos20kv_missing_voltage_sets_radiation_indicator_false(self):
        subsystem = make_subsystem()
        subsystem.radiation_indicator_callback = MagicMock()

        subsystem.apply_warning_indicators(2, None, 0.0)

        subsystem.radiation_indicator_callback.assert_called_once_with(False)

    def test_non_20kv_voltage_does_not_update_radiation_indicator(self):
        subsystem = make_subsystem()
        subsystem.radiation_indicator_callback = MagicMock()

        subsystem.apply_warning_indicators(0, 20000.0, 0.0)
        subsystem.apply_warning_indicators(1, -20000.0, 0.0)
        subsystem.apply_warning_indicators(3, 20000.0, 0.0)

        subsystem.radiation_indicator_callback.assert_not_called()

    def test_boundary_values_are_black(self):
        # Standard warning limits are also strict: exact boundary values are safe.
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
        # The -1kV supply displays signed voltage but compares warning limits by magnitude.
        subsystem = make_subsystem(
            {"neg1kv": {"min_voltage_v": 0, "max_voltage_v": 1000, "max_current_ma": 30}}
        )

        subsystem.apply_warning_indicators(1, -1001.0, -30.1)

        self.assertEqual(
            subsystem.ui_elements[1]["voltage_display"].foreground,
            BeamEnergySubsystem.WARNING_TEXT_COLOR,
        )
        self.assertEqual(
            subsystem.ui_elements[1]["current_display"].foreground,
            BeamEnergySubsystem.WARNING_TEXT_COLOR,
        )

    def test_warning_logs_each_time_voltage_is_outside_limit(self):
        # Warning logs are not latched; operators should see repeated out-of-range polls.
        subsystem = make_subsystem({"pos1kv": {"min_voltage_v": 100, "max_voltage_v": 900}})

        subsystem.apply_warning_indicators(0, 900.1, 1.0)
        subsystem.apply_warning_indicators(0, 901.0, 1.0)

        warning_logs = [
            call for call in subsystem.logger.log.call_args_list
            if len(call.args) >= 2 and call.args[1] == LogLevel.WARNING
        ]
        self.assertEqual(len(warning_logs), 2)
        self.assertIn("+1kV Matsusada PS", warning_logs[0].args[0])
        self.assertIn("actual voltage", warning_logs[0].args[0])

    def test_warning_does_not_log_when_current_is_in_range(self):
        # Logs should match actual warning states and skip in-range samples.
        subsystem = make_subsystem({"pos1kv": {"max_current_ma": 10}})

        subsystem.apply_warning_indicators(0, 100.0, 10.1)
        subsystem.apply_warning_indicators(0, 100.0, 10.0)
        subsystem.apply_warning_indicators(0, 100.0, 10.2)

        warning_logs = [
            call for call in subsystem.logger.log.call_args_list
            if len(call.args) >= 2 and call.args[1] == LogLevel.WARNING
        ]
        self.assertEqual(len(warning_logs), 2)
        self.assertTrue(all("actual current" in call.args[0] for call in warning_logs))

    def test_negative_one_kv_warning_log_mentions_absolute_reading(self):
        # Log wording calls out absolute-value comparison for the negative supply.
        subsystem = make_subsystem(
            {"neg1kv": {"min_voltage_v": 0, "max_voltage_v": 1000, "max_current_ma": 30}}
        )

        subsystem.apply_warning_indicators(1, -1001.0, 1.0)

        warning_logs = [
            call for call in subsystem.logger.log.call_args_list
            if len(call.args) >= 2 and call.args[1] == LogLevel.WARNING
        ]
        self.assertEqual(len(warning_logs), 1)
        self.assertIn("absolute actual voltage", warning_logs[0].args[0])


class TestBeamEnergyWarningValidation(unittest.TestCase):
    """User entry validation, popup wording, persistence, and live refresh scenarios."""

    def test_invalid_entry_does_not_mutate_limits(self):
        # Blank entries should show a popup and leave the active config untouched.
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
        # Voltage range edits are validated as a pair before being saved.
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
        # A valid edit updates state, persists, clears the entry, and recolors cached readings.
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
        self.assertEqual(
            subsystem.ui_elements[0]["current_display"].foreground,
            BeamEnergySubsystem.WARNING_TEXT_COLOR,
        )
        save_limits.assert_called_once()

    def test_pos20kv_max_current_above_estop_limit_is_rejected(self):
        # Max I cannot be raised above the shutdown threshold.
        subsystem = make_subsystem(
            {"pos20kv": {"max_current_ma": 0.5, BEAMS_ESTOP_CURRENT_FIELD: 0.75}}
        )
        before = dict(subsystem.warning_limits[POS20KV_SUPPLY_KEY])

        changed = subsystem._set_warning_limit_from_raw(
            2,
            "max_current_ma",
            "0.751",
            show_dialogs=False,
            persist=False,
        )

        self.assertFalse(changed)
        self.assertEqual(subsystem.warning_limits[POS20KV_SUPPLY_KEY], before)

    def test_3kv_current_limit_popup_names_supply_and_units(self):
        # Popup text should identify the exact supply/limit being changed.
        subsystem = make_subsystem()

        with patch("subsystem.beam_energy.beam_energy.messagebox.showerror") as showerror:
            changed = subsystem._set_warning_limit_from_raw(
                3,
                "max_current_ma",
                "10.1",
                show_dialogs=True,
                persist=False,
            )

        self.assertFalse(changed)
        message = showerror.call_args.args[1]
        self.assertTrue(message.startswith("+3kV Bertan PS Max I current limit:"))
        self.assertIn("mA", message)
        self.assertIn("10mA", message)

    def test_pos20kv_max_current_above_estop_popup_mentions_estop_limit(self):
        # This relationship gets a specific E-STOP message, not a generic range error.
        subsystem = make_subsystem(
            {"pos20kv": {"max_current_ma": 0.5, BEAMS_ESTOP_CURRENT_FIELD: 0.75}}
        )

        with patch("subsystem.beam_energy.beam_energy.messagebox.showerror") as showerror:
            changed = subsystem._set_warning_limit_from_raw(
                2,
                "max_current_ma",
                "0.751",
                show_dialogs=True,
                persist=False,
            )

        self.assertFalse(changed)
        message = showerror.call_args.args[1]
        self.assertTrue(message.startswith("+20kV Bertan PS Max I current limit:"))
        self.assertIn("at or below the Beams E-Stop Current Limit", message)
        self.assertIn("0.75mA", message)
        self.assertNotIn("between", message)

    def test_pos20kv_estop_limit_below_max_current_is_rejected(self):
        # The shutdown threshold cannot be lowered below the warning threshold.
        subsystem = make_subsystem(
            {"pos20kv": {"max_current_ma": 0.5, BEAMS_ESTOP_CURRENT_FIELD: 0.75}}
        )
        before = dict(subsystem.warning_limits[POS20KV_SUPPLY_KEY])

        changed = subsystem._set_beams_estop_current_limit_from_raw(
            "0.499",
            show_dialogs=False,
            persist=False,
        )

        self.assertFalse(changed)
        self.assertEqual(subsystem.warning_limits[POS20KV_SUPPLY_KEY], before)

    def test_pos20kv_estop_limit_below_max_popup_names_supply_and_units(self):
        # E-STOP popup wording should include the related Max I value with units.
        subsystem = make_subsystem(
            {"pos20kv": {"max_current_ma": 0.5, BEAMS_ESTOP_CURRENT_FIELD: 0.75}}
        )

        with patch("subsystem.beam_energy.beam_energy.messagebox.showerror") as showerror:
            changed = subsystem._set_beams_estop_current_limit_from_raw(
                "0.499",
                show_dialogs=True,
                persist=False,
            )

        self.assertFalse(changed)
        message = showerror.call_args.args[1]
        self.assertTrue(message.startswith("+20kV Bertan PS Beams E-Stop Current Limit:"))
        self.assertIn("Max I current limit", message)
        self.assertIn("0.5mA", message)

    def test_pos20kv_estop_limit_above_one_ma_is_rejected(self):
        # The E-STOP current limit is capped at the default +20kV 1 mA value.
        subsystem = make_subsystem()
        before = dict(subsystem.warning_limits[POS20KV_SUPPLY_KEY])

        changed = subsystem._set_beams_estop_current_limit_from_raw(
            "1.001",
            show_dialogs=False,
            persist=False,
        )

        self.assertFalse(changed)
        self.assertEqual(subsystem.warning_limits[POS20KV_SUPPLY_KEY], before)

    def test_valid_estop_limit_updates_state_saves_and_rechecks_current(self):
        # Lowering E-STOP below the cached current should immediately trip and color red.
        subsystem = make_subsystem(
            {"pos20kv": {"max_current_ma": 0.5, BEAMS_ESTOP_CURRENT_FIELD: 1.0}}
        )
        subsystem.latest_actual_voltage_values[2] = 0.0
        subsystem.latest_actual_current_values[2] = 0.8
        subsystem.beams_estop_callback = MagicMock()
        subsystem.beams_estop_current_entry_var.set("0.75")

        with patch(
            "subsystem.beam_energy.beam_energy.save_beam_energy_warning_limits",
            return_value=True,
        ) as save_limits:
            subsystem.set_beams_estop_current_limit()

        self.assertEqual(
            subsystem.warning_limits[POS20KV_SUPPLY_KEY][BEAMS_ESTOP_CURRENT_FIELD],
            0.75,
        )
        self.assertEqual(subsystem.beams_estop_current_entry_var.get(), "")
        self.assertEqual(
            subsystem.beams_estop_current_value_var.get(),
            "Limit set to: 0.75mA",
        )
        self.assertEqual(subsystem.ui_elements[2]["current_display"].foreground, "red")
        subsystem.beams_estop_callback.assert_called_once()
        save_limits.assert_called_once()

    def test_value_above_default_cap_is_rejected(self):
        # Generic limits still obey their per-supply default caps.
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
        # The config display mirrors the negative supply sign for voltage limits only.
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
