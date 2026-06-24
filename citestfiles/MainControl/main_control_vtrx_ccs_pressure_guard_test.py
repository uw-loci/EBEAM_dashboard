import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from subsystem.main_control.main_control import MainControlPanel
from usr.main_control_config import (
    BEAMS_ESTOP_CURRENT_LIMIT_FIELD,
    DEFAULT_BEAMS_ESTOP_CURRENT_LIMIT_MA,
    DEFAULT_TOTAL_MAX_EMISSION_CURRENT_MA,
    DEFAULT_VTRX_CCS_DISABLE_GRACE_PERIOD_S,
    TOTAL_MAX_EMISSION_CURRENT_FIELD,
    VTRX_CCS_DISABLE_GRACE_PERIOD_FIELD,
    load_beams_estop_current_limit_ma,
    load_total_max_emission_current,
    load_vtrx_ccs_disable_grace_period_s,
    save_beams_estop_current_limit_ma,
    save_total_max_emission_current,
    save_vtrx_ccs_disable_grace_period_s,
)


class FakeVar:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class FakeLogger:
    def __init__(self):
        self.entries = []

    def info(self, message, tag=None):
        self.entries.append(("INFO", message, tag))

    def warning(self, message, tag=None):
        self.entries.append(("WARNING", message, tag))

    def error(self, message, tag=None):
        self.entries.append(("ERROR", message, tag))

    def critical(self, message, tag=None):
        self.entries.append(("CRITICAL", message, tag))

    def messages(self, level):
        return [message for entry_level, message, _tag in self.entries if entry_level == level]


class FakeCathode:
    def __init__(self, active=True):
        self.toggle_states = [active, False, False]
        self.turn_off_calls = 0

    def turn_off_all_beams(self):
        self.turn_off_calls += 1
        self.toggle_states = [False, False, False]


def make_main_control(now=100.0, cathode=None):
    main_control = MainControlPanel.__new__(MainControlPanel)
    main_control.logger = FakeLogger()
    main_control.root = None
    main_control.subsystems = {}
    if cathode is not None:
        main_control.subsystems["Cathode Heating"] = cathode
    main_control.disable_beams_on_vtrx_pressure_exceeded = False
    main_control.vtrx_ccs_pressure_shutdown_enabled = True
    main_control.total_max_emission_current_limit_enabled = True
    main_control.beams_estop_current_limit_enabled = True
    main_control._last_vtrx_pressure_mbar = None
    main_control.vtrx_ccs_disable_grace_period_s = 30.0
    main_control.vtrx_ccs_disable_grace_period_entry_var = FakeVar()
    main_control.vtrx_ccs_disable_grace_period_title_var = FakeVar(
        "Disable CCS Output after 30s above 1e-05"
    )
    main_control.vtrx_ccs_disable_grace_period_value_var = FakeVar(
        "30"
    )
    main_control._vtrx_ccs_disable_timer_started_at = None
    main_control._vtrx_ccs_disable_last_warning_at = None
    current_time = {"value": float(now)}
    main_control._time_monotonic = lambda: current_time["value"]
    main_control._test_time = current_time
    return main_control


class MainControlConfigPersistenceTest(unittest.TestCase):
    def test_legacy_numeric_config_loads_total_and_default_grace_period(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, "main_control_config.json")
            with open(config_path, "w") as file:
                json.dump(7.5, file)

            self.assertEqual(load_total_max_emission_current(config_path), 7.5)
            self.assertEqual(
                load_vtrx_ccs_disable_grace_period_s(config_path),
                DEFAULT_VTRX_CCS_DISABLE_GRACE_PERIOD_S,
            )
            self.assertEqual(
                load_beams_estop_current_limit_ma(config_path),
                DEFAULT_BEAMS_ESTOP_CURRENT_LIMIT_MA,
            )

            self.assertTrue(save_vtrx_ccs_disable_grace_period_s(12.0, config_path))
            with open(config_path, "r") as file:
                saved = json.load(file)

            self.assertEqual(saved[TOTAL_MAX_EMISSION_CURRENT_FIELD], 7.5)
            self.assertEqual(saved[VTRX_CCS_DISABLE_GRACE_PERIOD_FIELD], 12.0)
            self.assertEqual(
                saved[BEAMS_ESTOP_CURRENT_LIMIT_FIELD],
                DEFAULT_BEAMS_ESTOP_CURRENT_LIMIT_MA,
            )

    def test_object_config_preserves_other_setting_on_save(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, "main_control_config.json")
            with open(config_path, "w") as file:
                json.dump(
                    {
                        TOTAL_MAX_EMISSION_CURRENT_FIELD: 4.0,
                        VTRX_CCS_DISABLE_GRACE_PERIOD_FIELD: 9.0,
                        BEAMS_ESTOP_CURRENT_LIMIT_FIELD: 0.7,
                    },
                    file,
                )

            self.assertTrue(save_total_max_emission_current(5.0, config_path))
            with open(config_path, "r") as file:
                saved = json.load(file)

            self.assertEqual(saved[TOTAL_MAX_EMISSION_CURRENT_FIELD], 5.0)
            self.assertEqual(saved[VTRX_CCS_DISABLE_GRACE_PERIOD_FIELD], 9.0)
            self.assertEqual(saved[BEAMS_ESTOP_CURRENT_LIMIT_FIELD], 0.7)

            self.assertTrue(save_beams_estop_current_limit_ma(0.5, config_path))
            with open(config_path, "r") as file:
                saved = json.load(file)

            self.assertEqual(saved[TOTAL_MAX_EMISSION_CURRENT_FIELD], 5.0)
            self.assertEqual(saved[VTRX_CCS_DISABLE_GRACE_PERIOD_FIELD], 9.0)
            self.assertEqual(saved[BEAMS_ESTOP_CURRENT_LIMIT_FIELD], 0.5)

    def test_missing_config_uses_defaults(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, "missing.json")

            self.assertEqual(
                load_total_max_emission_current(config_path),
                DEFAULT_TOTAL_MAX_EMISSION_CURRENT_MA,
            )
            self.assertEqual(
                load_vtrx_ccs_disable_grace_period_s(config_path),
                DEFAULT_VTRX_CCS_DISABLE_GRACE_PERIOD_S,
            )
            self.assertEqual(
                load_beams_estop_current_limit_ma(config_path),
                DEFAULT_BEAMS_ESTOP_CURRENT_LIMIT_MA,
            )
            with open(config_path, "r") as file:
                saved = json.load(file)

            self.assertEqual(
                saved[TOTAL_MAX_EMISSION_CURRENT_FIELD],
                DEFAULT_TOTAL_MAX_EMISSION_CURRENT_MA,
            )
            self.assertEqual(
                saved[VTRX_CCS_DISABLE_GRACE_PERIOD_FIELD],
                DEFAULT_VTRX_CCS_DISABLE_GRACE_PERIOD_S,
            )
            self.assertEqual(
                saved[BEAMS_ESTOP_CURRENT_LIMIT_FIELD],
                DEFAULT_BEAMS_ESTOP_CURRENT_LIMIT_MA,
            )


class MainControlVtrxCcsGracePeriodUiTest(unittest.TestCase):
    @patch("subsystem.main_control.main_control.messagebox.showerror")
    @patch("subsystem.main_control.main_control.save_vtrx_ccs_disable_grace_period_s")
    def test_setter_rejects_invalid_values(self, save_mock, showerror_mock):
        main_control = make_main_control()

        for value in ("", "abc", "-1", "nan", "inf"):
            with self.subTest(value=value):
                main_control.vtrx_ccs_disable_grace_period_entry_var.set(value)
                main_control.set_vtrx_ccs_disable_grace_period()

        self.assertEqual(main_control.vtrx_ccs_disable_grace_period_s, 30.0)
        self.assertFalse(save_mock.called)
        self.assertEqual(showerror_mock.call_count, 5)

    @patch("subsystem.main_control.main_control.messagebox.showwarning")
    @patch("subsystem.main_control.main_control.save_vtrx_ccs_disable_grace_period_s")
    def test_setter_updates_runtime_display_even_when_save_fails(self, save_mock, showwarning_mock):
        save_mock.return_value = False
        main_control = make_main_control()
        main_control.vtrx_ccs_disable_grace_period_entry_var.set("15")

        main_control.set_vtrx_ccs_disable_grace_period()

        self.assertEqual(main_control.vtrx_ccs_disable_grace_period_s, 15.0)
        self.assertEqual(main_control.vtrx_ccs_disable_grace_period_entry_var.get(), "")
        self.assertIn("15s", main_control.vtrx_ccs_disable_grace_period_title_var.get())
        self.assertNotIn("--", main_control.vtrx_ccs_disable_grace_period_title_var.get())
        self.assertEqual(
            main_control.vtrx_ccs_disable_grace_period_value_var.get(),
            "15",
        )
        showwarning_mock.assert_called_once()

    def test_invalid_internal_duration_runs_as_default(self):
        main_control = make_main_control()

        for value in (None, "bad", -1, float("nan"), float("inf")):
            with self.subTest(value=value):
                self.assertEqual(
                    main_control._coerce_vtrx_ccs_disable_grace_period_s(value),
                    30.0,
                )


class MainControlVtrxCcsPressureTimerTest(unittest.TestCase):
    def test_timer_warns_and_turns_off_ccs_once_after_grace_period(self):
        cathode = FakeCathode(active=True)
        main_control = make_main_control(cathode=cathode)

        main_control._handle_vtrx_pressure_update(2e-5)

        self.assertEqual(main_control._vtrx_ccs_disable_timer_started_at, 100.0)
        self.assertTrue(
            any("CCS will shut off after 30 seconds" in message for message in main_control.logger.messages("CRITICAL"))
        )

        main_control._test_time["value"] = 109.0
        main_control._handle_vtrx_pressure_update(2e-5)
        self.assertEqual(main_control.logger.messages("WARNING"), [])
        self.assertEqual(cathode.turn_off_calls, 0)

        main_control._test_time["value"] = 110.0
        main_control._handle_vtrx_pressure_update(2e-5)
        self.assertTrue(
            any(
                "CCS will shut off in 20 seconds due to VTRX pressure being above"
                in message
                for message in main_control.logger.messages("WARNING")
            )
        )

        main_control._test_time["value"] = 130.0
        main_control._handle_vtrx_pressure_update(2e-5)
        self.assertEqual(cathode.turn_off_calls, 1)
        self.assertEqual(main_control._vtrx_ccs_disable_timer_started_at, 100.0)

        main_control._test_time["value"] = 140.0
        main_control._handle_vtrx_pressure_update(2e-5)
        self.assertEqual(cathode.turn_off_calls, 1)

    def test_timer_start_does_not_log_initial_shutdown_warning_when_ccs_inactive(self):
        main_control = make_main_control(cathode=FakeCathode(active=False))

        main_control._handle_vtrx_pressure_update(2e-5)

        self.assertFalse(
            any("CCS will shut off after" in message for message in main_control.logger.messages("CRITICAL"))
        )

    def test_pressure_recovery_clears_timer(self):
        main_control = make_main_control(cathode=FakeCathode(active=True))

        main_control._handle_vtrx_pressure_update(2e-5)
        self.assertIsNotNone(main_control._vtrx_ccs_disable_timer_started_at)

        main_control._handle_vtrx_pressure_update(5e-6)

        self.assertIsNone(main_control._vtrx_ccs_disable_timer_started_at)

    def test_disabled_pressure_shutdown_does_not_start_timer_or_turn_off_ccs(self):
        cathode = FakeCathode(active=True)
        main_control = make_main_control(cathode=cathode)
        main_control.vtrx_ccs_pressure_shutdown_enabled = False
        main_control._vtrx_ccs_disable_timer_started_at = 90.0
        main_control._vtrx_ccs_disable_last_warning_at = 90.0

        main_control._handle_vtrx_pressure_update(2e-5)

        self.assertIsNone(main_control._vtrx_ccs_disable_timer_started_at)
        self.assertIsNone(main_control._vtrx_ccs_disable_last_warning_at)
        self.assertEqual(cathode.turn_off_calls, 0)
        self.assertEqual(main_control.logger.messages("CRITICAL"), [])
        self.assertTrue(main_control._vtrx_ccs_pressure_allows_output())

    def test_pressure_provider_allows_output_when_shutdown_guard_is_disabled(self):
        main_control = make_main_control()
        main_control._vtrx_ccs_disable_timer_started_at = 100.0

        self.assertFalse(main_control._vtrx_ccs_pressure_allows_output())

        main_control.vtrx_ccs_pressure_shutdown_enabled = False

        self.assertTrue(main_control._vtrx_ccs_pressure_allows_output())


if __name__ == "__main__":
    unittest.main()
