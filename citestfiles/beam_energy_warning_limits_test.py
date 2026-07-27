import json
import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from subsystem.beam_energy.beam_energy import BeamEnergySubsystem
from subsystem.main_control.main_control import MainControlPanel
from usr.beam_energy_warning_config import (
    DEFAULT_WARNING_LIMITS,
    POS20KV_SUPPLY_KEY,
    load_beam_energy_warning_limits,
    normalize_warning_limits,
)
from unittest.mock import patch


SUPPLY_KEYS = ["pos1kv", "neg1kv", POS20KV_SUPPLY_KEY, "pos3kv"]
POWER_SUPPLIES = [
    {"name": "+1kV Matsusada PS"},
    {"name": "-1kV Matsusada PS"},
    {"name": "+20kV Bertan PS"},
    {"name": "+3kV Bertan PS"},
]


class FakeLogger:
    def __init__(self):
        self.entries = []

    def log(self, message, level=None, tag=None):
        self.entries.append((message, level, tag))


class FakeMainControlLogger:
    def __init__(self):
        self.info_entries = []
        self.warning_entries = []

    def info(self, message, tag=None):
        self.info_entries.append((message, tag))

    def warning(self, message, tag=None):
        self.warning_entries.append((message, tag))


class FakeVar:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class FakeBeamEnergyForMainControl:
    def __init__(self):
        self.raw_values = []
        self.callback = None

    def set_beams_disable_current_limit_ma(self, value_ma):
        self.raw_values.append(value_ma)
        return True

    def set_beams_disable_callback(self, callback):
        self.callback = callback


class FakeBeamPulseForDisarm:
    def __init__(self):
        self.disarm_calls = []

    def disarm_beams(self, operation_token=None, defer_ui=False):
        self.disarm_calls.append((operation_token, defer_ui))
        return True


def make_beam_energy():
    beam_energy = BeamEnergySubsystem.__new__(BeamEnergySubsystem)
    beam_energy.logger = FakeLogger()
    beam_energy.disable_logging_when_hvolt_off = False
    beam_energy.hvolt_on_provider = None
    beam_energy.supply_keys = list(SUPPLY_KEYS)
    beam_energy.power_supplies = list(POWER_SUPPLIES)
    beam_energy.warning_limits = {
        supply_key: dict(limits)
        for supply_key, limits in DEFAULT_WARNING_LIMITS.items()
    }
    beam_energy.beams_disable_current_limit_ma = None
    beam_energy.refresh_warning_indicators = lambda _index: None
    beam_energy.latest_actual_voltage_values = [None for _ in SUPPLY_KEYS]
    beam_energy.latest_actual_current_values = [None for _ in SUPPLY_KEYS]
    beam_energy.ui_elements = [None for _ in SUPPLY_KEYS]
    beam_energy.radiation_indicator_callback = lambda _active: None
    beam_energy._radiation_indicator_last_valid_state = None
    beam_energy._radiation_indicator_sent = None
    beam_energy._radiation_indicator_missing_callback_state = None
    beam_energy.beams_disable_callback = None
    beam_energy.beams_disable_current_limit_enabled = True
    return beam_energy


class BeamEnergyWarningLimitConfigTest(unittest.TestCase):
    def test_missing_config_saves_defaults(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, "beam_energy_warning_limits.json")

            limits = load_beam_energy_warning_limits(config_path)

            self.assertNotIn("beams_disable_current_ma", limits[POS20KV_SUPPLY_KEY])
            with open(config_path, "r") as file:
                saved = json.load(file)
            self.assertNotIn("beams_disable_current_ma", saved[POS20KV_SUPPLY_KEY])

    def test_pos20kv_current_warning_limit_normalizes(self):
        for max_current in (0.0, 0.5, 1.0):
            with self.subTest(max_current=max_current):
                normalized = normalize_warning_limits(
                    {
                        POS20KV_SUPPLY_KEY: {
                            "max_current_ma": max_current,
                        }
                    }
                )

                self.assertEqual(
                    normalized[POS20KV_SUPPLY_KEY]["max_current_ma"],
                    max_current,
                )


class BeamEnergyWarningLimitSetterTest(unittest.TestCase):
    def test_beams_disable_limit_stores_value_sent_by_main_control(self):
        beam_energy = make_beam_energy()
        pos20kv_index = SUPPLY_KEYS.index(POS20KV_SUPPLY_KEY)
        refreshed_indexes = []
        beam_energy.refresh_warning_indicators = refreshed_indexes.append

        result = beam_energy.set_beams_disable_current_limit_ma(0.5)

        self.assertTrue(result)
        self.assertEqual(beam_energy.beams_disable_current_limit_ma, 0.5)
        self.assertEqual(refreshed_indexes, [pos20kv_index])

    def test_pos20kv_current_beams_disable_uses_main_control_limit(self):
        beam_energy = make_beam_energy()
        pos20kv_index = SUPPLY_KEYS.index(POS20KV_SUPPLY_KEY)
        triggered = []
        beam_energy.beams_disable_callback = lambda: triggered.append(True)
        beam_energy.set_beams_disable_current_limit_ma(0.5)

        beam_energy.apply_warning_indicators(pos20kv_index, 0, 0.49)
        self.assertEqual(triggered, [])

        beam_energy.apply_warning_indicators(pos20kv_index, 0, 0.5)
        self.assertEqual(triggered, [True])

    def test_pos20kv_current_beams_disable_can_be_disabled(self):
        beam_energy = make_beam_energy()
        pos20kv_index = SUPPLY_KEYS.index(POS20KV_SUPPLY_KEY)
        refreshed_indexes = []
        triggered = []
        beam_energy.refresh_warning_indicators = refreshed_indexes.append
        beam_energy.beams_disable_callback = lambda: triggered.append(True)
        beam_energy.set_beams_disable_current_limit_ma(0.5)

        result = beam_energy.set_beams_disable_current_limit_enabled(False)
        beam_energy.apply_warning_indicators(pos20kv_index, 0, 0.5)

        self.assertTrue(result)
        self.assertFalse(beam_energy.beams_disable_current_limit_enabled)
        self.assertEqual(triggered, [])
        self.assertEqual(refreshed_indexes, [pos20kv_index, pos20kv_index])

    def test_pos20kv_max_current_warning_accepts_values_above_or_below_beams_disable(self):
        pos20kv_index = SUPPLY_KEYS.index(POS20KV_SUPPLY_KEY)

        for max_current, beams_disable_current in ((1.0, 0.25), (0.25, 1.0)):
            with self.subTest(max_current=max_current, beams_disable_current=beams_disable_current):
                beam_energy = make_beam_energy()
                beam_energy.beams_disable_current_limit_ma = beams_disable_current

                result = beam_energy._set_warning_limit_from_raw(
                    pos20kv_index,
                    "max_current_ma",
                    str(max_current),
                    show_dialogs=False,
                    persist=False,
                )

                self.assertTrue(result)
                self.assertEqual(
                    beam_energy.warning_limits[POS20KV_SUPPLY_KEY]["max_current_ma"],
                    max_current,
                )


class BeamEnergyRadiationIndicatorTest(unittest.TestCase):
    def test_initial_missing_pos20kv_readback_does_not_send_indicator_state(self):
        beam_energy = make_beam_energy()
        pos20kv_index = SUPPLY_KEYS.index(POS20KV_SUPPLY_KEY)
        sent_states = []
        beam_energy.radiation_indicator_callback = sent_states.append

        beam_energy.apply_warning_indicators(pos20kv_index, None, None)

        self.assertEqual(sent_states, [])

    def test_missing_pos20kv_readback_preserves_asserted_indicator(self):
        beam_energy = make_beam_energy()
        pos20kv_index = SUPPLY_KEYS.index(POS20KV_SUPPLY_KEY)
        sent_states = []
        beam_energy.radiation_indicator_callback = sent_states.append

        beam_energy.apply_warning_indicators(pos20kv_index, 12000.0, 0)
        beam_energy.apply_warning_indicators(pos20kv_index, None, None)

        self.assertEqual(sent_states, [True])

    def test_invalid_pos20kv_readback_preserves_asserted_indicator(self):
        pos20kv_index = SUPPLY_KEYS.index(POS20KV_SUPPLY_KEY)

        for invalid_readback in ("bad", float("nan"), float("inf")):
            with self.subTest(invalid_readback=invalid_readback):
                beam_energy = make_beam_energy()
                sent_states = []
                beam_energy.radiation_indicator_callback = sent_states.append

                beam_energy.apply_warning_indicators(pos20kv_index, 12000.0, 0)
                beam_energy.apply_warning_indicators(pos20kv_index, invalid_readback, None)

                self.assertEqual(sent_states, [True])

    def test_valid_below_threshold_readback_clears_asserted_indicator(self):
        beam_energy = make_beam_energy()
        pos20kv_index = SUPPLY_KEYS.index(POS20KV_SUPPLY_KEY)
        sent_states = []
        beam_energy.radiation_indicator_callback = sent_states.append

        beam_energy.apply_warning_indicators(pos20kv_index, 12000.0, 0)
        beam_energy.apply_warning_indicators(pos20kv_index, 9000.0, 0)

        self.assertEqual(sent_states, [True, False])

    def test_set_default_values_preserves_asserted_indicator(self):
        beam_energy = make_beam_energy()
        pos20kv_index = SUPPLY_KEYS.index(POS20KV_SUPPLY_KEY)
        sent_states = []
        beam_energy.radiation_indicator_callback = sent_states.append
        beam_energy.set_voltages = [FakeVar() for _ in SUPPLY_KEYS]
        beam_energy.actual_voltages = [FakeVar() for _ in SUPPLY_KEYS]
        beam_energy.actual_currents = [FakeVar() for _ in SUPPLY_KEYS]
        beam_energy.update_connection_status = lambda *_args, **_kwargs: None
        beam_energy.update_output_status = lambda *_args, **_kwargs: None
        beam_energy.update_reset_status = lambda *_args, **_kwargs: None
        beam_energy.update_supply_interlock_status = lambda *_args, **_kwargs: None
        beam_energy.update_indicators_panel = lambda *_args, **_kwargs: None

        beam_energy.apply_warning_indicators(pos20kv_index, 12000.0, 0)
        beam_energy.set_default_values(pos20kv_index)

        self.assertEqual(sent_states, [True])


class MainControlBeamsDisableLimitUiTest(unittest.TestCase):
    def test_main_control_formats_beams_disable_limit_display(self):
        main_control = MainControlPanel.__new__(MainControlPanel)

        self.assertEqual(
            main_control._format_beams_disable_current_limit_ma(0.5),
            "0.5",
        )
        self.assertEqual(
            main_control._format_beams_disable_current_limit_ma(None),
            "--",
        )

    def test_beam_energy_threshold_uses_disarm_beams_path(self):
        main_control = MainControlPanel.__new__(MainControlPanel)
        beam_energy = FakeBeamEnergyForMainControl()
        disarm_causes = []
        main_control.subsystems = {"Beam Energy": beam_energy}
        main_control.beams_disable_current_limit_ma = 0.7
        main_control.beams_disable_current_limit_enabled = True
        main_control._request_disarm_beams = (
            lambda cause=None: disarm_causes.append(cause) or True
        )
        main_control.refresh_beams_disable_current_limit_display = lambda: None
        main_control._apply_logging_suppression_settings = lambda: None

        main_control.wire_beam_energy(beam_energy)
        beam_energy.callback()

        self.assertEqual(
            disarm_causes,
            ["Disable Beams if 20kV Bertan exceeds 0.7mA"],
        )

    def test_request_disarm_beams_calls_beam_pulse_disarm(self):
        main_control = MainControlPanel.__new__(MainControlPanel)
        beam_pulse = FakeBeamPulseForDisarm()
        operations = []
        main_control.subsystems = {"Beam Pulse": beam_pulse}

        def start_operation(action, channels, expected="poll", kind="normal", cause=None):
            operations.append((action, tuple(channels), expected, kind, cause))
            return "bcon-1"

        main_control._start_bcon_operation = start_operation

        self.assertTrue(main_control._request_disarm_beams(cause="20kV threshold"))
        self.assertEqual(
            operations,
            [(
                "Disarm Beams command: all channels mode=OFF",
                (0, 1, 2),
                "all_off",
                "disarm",
                "20kV threshold",
            )],
        )
        self.assertEqual(beam_pulse.disarm_calls, [("bcon-1", True)])

    @patch("subsystem.main_control.main_control.save_beams_disable_current_limit_ma")
    def test_main_control_logs_successful_beams_disable_limit_update(self, save_mock):
        save_mock.return_value = True
        main_control = MainControlPanel.__new__(MainControlPanel)
        beam_energy = FakeBeamEnergyForMainControl()
        logger = FakeMainControlLogger()
        main_control.subsystems = {"Beam Energy": beam_energy}
        main_control.logger = logger
        main_control.beams_disable_current_limit_ma = 0.7
        main_control.beams_disable_current_entry_var = FakeVar("0.5")
        main_control.beams_disable_current_value_var = FakeVar()

        main_control.set_beams_disable_current_limit()

        self.assertEqual(beam_energy.raw_values, [0.5])
        self.assertEqual(main_control.beams_disable_current_entry_var.get(), "")
        self.assertEqual(
            main_control.beams_disable_current_value_var.get(),
            "0.5",
        )
        self.assertEqual(
            logger.info_entries,
            [
                (
                    "Disable Beams if 20kV Bertan exceeds 0.5mA: "
                    "setting successfully changed.",
                    "Main Control",
                )
            ],
        )

    @patch("subsystem.main_control.main_control.messagebox.showerror")
    @patch("subsystem.main_control.main_control.save_beams_disable_current_limit_ma")
    def test_main_control_rejects_beams_disable_limit_above_one_ma(self, save_mock, showerror_mock):
        main_control = MainControlPanel.__new__(MainControlPanel)
        main_control.subsystems = {"Beam Energy": FakeBeamEnergyForMainControl()}
        main_control.logger = FakeMainControlLogger()
        main_control.beams_disable_current_limit_ma = 0.7
        main_control.beams_disable_current_entry_var = FakeVar("1.1")
        main_control.beams_disable_current_value_var = FakeVar("0.7")

        main_control.set_beams_disable_current_limit()

        self.assertEqual(main_control.beams_disable_current_limit_ma, 0.7)
        self.assertFalse(save_mock.called)
        showerror_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
