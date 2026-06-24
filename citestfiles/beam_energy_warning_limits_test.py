import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from subsystem.beam_energy.beam_energy import BeamEnergySubsystem
from subsystem.main_control.main_control import MainControlPanel
from usr.beam_energy_warning_config import (
    BEAMS_ESTOP_CURRENT_FIELD,
    DEFAULT_WARNING_LIMITS,
    POS20KV_SUPPLY_KEY,
    normalize_warning_limits,
)


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

    def info(self, message, tag=None):
        self.info_entries.append((message, tag))


class FakeVar:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class FakeBeamEnergyForMainControl:
    def __init__(self):
        self.limit_ma = 1.0
        self.raw_values = []

    def set_beams_estop_current_limit_ma(self, value_ma):
        self.raw_values.append(value_ma)
        self.limit_ma = float(value_ma)
        return True

    def get_beams_estop_current_limit_ma(self):
        return self.limit_ma


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
    beam_energy.refresh_warning_indicators = lambda _index: None
    return beam_energy


class BeamEnergyWarningLimitConfigTest(unittest.TestCase):
    def test_pos20kv_current_limits_normalize_independently(self):
        for max_current, estop_current in ((0.0, 1.0), (1.0, 0.0), (0.5, 0.25)):
            with self.subTest(max_current=max_current, estop_current=estop_current):
                normalized = normalize_warning_limits(
                    {
                        POS20KV_SUPPLY_KEY: {
                            "max_current_ma": max_current,
                            BEAMS_ESTOP_CURRENT_FIELD: estop_current,
                        }
                    }
                )

                self.assertEqual(
                    normalized[POS20KV_SUPPLY_KEY]["max_current_ma"],
                    max_current,
                )
                self.assertEqual(
                    normalized[POS20KV_SUPPLY_KEY][BEAMS_ESTOP_CURRENT_FIELD],
                    estop_current,
                )


class BeamEnergyWarningLimitSetterTest(unittest.TestCase):
    def test_beams_estop_limit_accepts_zero_through_rated_limit(self):
        for value in ("0", "0.5", "1.0"):
            with self.subTest(value=value):
                beam_energy = make_beam_energy()
                beam_energy.warning_limits[POS20KV_SUPPLY_KEY]["max_current_ma"] = 1.0

                result = beam_energy.set_beams_estop_current_limit_ma(
                    float(value),
                    persist=False,
                )

                self.assertTrue(result)
                self.assertEqual(
                    beam_energy.warning_limits[POS20KV_SUPPLY_KEY][BEAMS_ESTOP_CURRENT_FIELD],
                    float(value),
                )

    def test_beams_estop_limit_rejects_invalid_values(self):
        for value in ("", "not-a-number", "-0.1", "nan", "inf", "1.01"):
            with self.subTest(value=value):
                beam_energy = make_beam_energy()

                with self.assertRaises(ValueError):
                    beam_energy.set_beams_estop_current_limit_ma(
                        value,
                        persist=False,
                    )

                self.assertEqual(
                    beam_energy.warning_limits[POS20KV_SUPPLY_KEY][BEAMS_ESTOP_CURRENT_FIELD],
                    DEFAULT_WARNING_LIMITS[POS20KV_SUPPLY_KEY][BEAMS_ESTOP_CURRENT_FIELD],
                )

    def test_pos20kv_max_current_warning_accepts_values_above_or_below_estop(self):
        pos20kv_index = SUPPLY_KEYS.index(POS20KV_SUPPLY_KEY)

        for max_current, estop_current in ((1.0, 0.25), (0.25, 1.0)):
            with self.subTest(max_current=max_current, estop_current=estop_current):
                beam_energy = make_beam_energy()
                beam_energy.warning_limits[POS20KV_SUPPLY_KEY][BEAMS_ESTOP_CURRENT_FIELD] = (
                    estop_current
                )

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


class MainControlBeamsEstopLimitUiTest(unittest.TestCase):
    def test_main_control_formats_beams_estop_limit_display(self):
        main_control = MainControlPanel.__new__(MainControlPanel)

        self.assertEqual(
            main_control._format_beams_estop_current_limit_ma(0.5),
            "Limit set to: 0.5mA",
        )
        self.assertEqual(
            main_control._format_beams_estop_current_limit_ma(None),
            "Limit set to: --mA",
        )

    def test_main_control_logs_successful_beams_estop_limit_update(self):
        main_control = MainControlPanel.__new__(MainControlPanel)
        beam_energy = FakeBeamEnergyForMainControl()
        logger = FakeMainControlLogger()
        main_control.subsystems = {"Beam Energy": beam_energy}
        main_control.logger = logger
        main_control.beams_estop_current_entry_var = FakeVar("0.5")
        main_control.beams_estop_current_value_var = FakeVar()

        main_control.set_beams_estop_current_limit()

        self.assertEqual(beam_energy.raw_values, [0.5])
        self.assertEqual(main_control.beams_estop_current_entry_var.get(), "")
        self.assertEqual(
            main_control.beams_estop_current_value_var.get(),
            "Limit set to: 0.5mA",
        )
        self.assertEqual(
            logger.info_entries,
            [
                (
                    "20kV Bertan Current Limit for E-Stop Trigger: "
                    "setting successfully changed to 0.5mA.",
                    "Main Control",
                )
            ],
        )


if __name__ == "__main__":
    unittest.main()
