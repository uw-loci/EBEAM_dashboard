import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from subsystem.main_control.main_control import BEAM_ACTION_NEUTRAL_COLOR, MainControlPanel
from usr.main_control_config import (
    BEAMS_DISABLE_CURRENT_LIMIT_FIELD,
    DEFAULT_BEAMS_DISABLE_CURRENT_LIMIT_MA,
    DEFAULT_TOTAL_MAX_EMISSION_CURRENT_MA,
    DEFAULT_VTRX_CCS_DISABLE_GRACE_PERIOD_S,
    TOTAL_MAX_EMISSION_CURRENT_FIELD,
    VTRX_CCS_DISABLE_GRACE_PERIOD_FIELD,
    load_beams_disable_current_limit_ma,
    load_total_max_emission_current,
    load_vtrx_ccs_disable_grace_period_s,
    save_beams_disable_current_limit_ma,
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


class FakeBeamPulse:
    def __init__(self, connected=True, disable_all_result=True):
        self.disable_all_calls = 0
        self.connected = connected
        self.disable_all_result = disable_all_result
        self.operation_tokens = []

    def disable_all_beams(self, defer_ui=False, operation_token=None):
        self.disable_all_calls += 1
        self.defer_ui_values = getattr(self, "defer_ui_values", []) + [defer_ui]
        self.operation_tokens.append(operation_token)
        return self.disable_all_result

    def is_connected(self):
        return self.connected


class FakeVtrx:
    def __init__(self):
        self.pressure_callback = None

    def set_pressure_update_callback(self, callback):
        self.pressure_callback = callback


class FakeBeamPulseEstop:
    def __init__(self, stop_all_result=True, armed=True, disarm_result=True):
        self.stop_all_result = stop_all_result
        self.armed = armed
        self.disarm_result = disarm_result
        self.stop_all_calls = 0
        self.disarm_calls = 0
        self.disarm_preserve_pending_acks_values = []
        self.complete_disarm_calls = 0

    def stop_all_channels(self, operation_token=None, defer_ui=False):
        self.stop_all_calls += 1
        return self.stop_all_result

    def get_beams_armed_status(self):
        return self.armed

    def disarm_beams(self, preserve_pending_acks=False, operation_token=None, defer_ui=False):
        self.disarm_calls += 1
        self.disarm_preserve_pending_acks_values.append(preserve_pending_acks)
        if self.disarm_result and not defer_ui:
            self.armed = False
        return self.disarm_result

    def complete_disarm(self):
        self.complete_disarm_calls += 1
        self.armed = False


def make_main_control(now=100.0, cathode=None, beam_pulse=None):
    main_control = MainControlPanel.__new__(MainControlPanel)
    main_control.logger = FakeLogger()
    main_control.root = None
    main_control.subsystems = {}
    if cathode is not None:
        main_control.subsystems["Cathode Heating"] = cathode
    if beam_pulse is not None:
        main_control.subsystems["Beam Pulse"] = beam_pulse
    main_control.disable_ccs_output_on_bcon_disconnect = True
    main_control.disable_beams_on_vtrx_pressure_exceeded = False
    main_control.vtrx_ccs_pressure_shutdown_enabled = True
    main_control.total_max_emission_current_limit_enabled = True
    main_control.beams_disable_current_limit_enabled = True
    main_control._last_vtrx_pressure_mbar = None
    main_control.pressure_reading_is_fresh = False
    main_control.vtrx_firmware_error = False
    main_control._vtrx_pressure_beam_disable_latched = True
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


def make_main_control_for_beams_off(beam_pulse, cathode=None):
    main_control = make_main_control(cathode=cathode, beam_pulse=beam_pulse)
    main_control.beam_toggle_updates = []
    main_control.software_interlock_control_updates = []
    main_control.activate_control_updates = []
    main_control.armed_ui_updates = []
    main_control.clear_output_calls = 0
    main_control._update_beam_output_button_states = (
        lambda **kwargs: main_control.beam_toggle_updates.append(kwargs)
    )
    main_control._update_software_interlock_control_states = (
        lambda **kwargs: main_control.software_interlock_control_updates.append(kwargs)
    )
    main_control._update_activate_enabled_beams_control_state = (
        lambda **kwargs: main_control.activate_control_updates.append(kwargs)
    )
    main_control._set_armed_ui = (
        lambda armed, reset=False: main_control.armed_ui_updates.append((armed, reset))
    )
    main_control._clear_all_beam_output_displays = (
        lambda: setattr(
            main_control,
            "clear_output_calls",
            main_control.clear_output_calls + 1,
        )
    )
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
                load_beams_disable_current_limit_ma(config_path),
                DEFAULT_BEAMS_DISABLE_CURRENT_LIMIT_MA,
            )

            self.assertTrue(save_vtrx_ccs_disable_grace_period_s(12.0, config_path))
            with open(config_path, "r") as file:
                saved = json.load(file)

            self.assertEqual(saved[TOTAL_MAX_EMISSION_CURRENT_FIELD], 7.5)
            self.assertEqual(saved[VTRX_CCS_DISABLE_GRACE_PERIOD_FIELD], 12.0)
            self.assertEqual(
                saved[BEAMS_DISABLE_CURRENT_LIMIT_FIELD],
                DEFAULT_BEAMS_DISABLE_CURRENT_LIMIT_MA,
            )

    def test_object_config_preserves_other_setting_on_save(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, "main_control_config.json")
            with open(config_path, "w") as file:
                json.dump(
                    {
                        TOTAL_MAX_EMISSION_CURRENT_FIELD: 4.0,
                        VTRX_CCS_DISABLE_GRACE_PERIOD_FIELD: 9.0,
                        BEAMS_DISABLE_CURRENT_LIMIT_FIELD: 0.7,
                    },
                    file,
                )

            self.assertTrue(save_total_max_emission_current(5.0, config_path))
            with open(config_path, "r") as file:
                saved = json.load(file)

            self.assertEqual(saved[TOTAL_MAX_EMISSION_CURRENT_FIELD], 5.0)
            self.assertEqual(saved[VTRX_CCS_DISABLE_GRACE_PERIOD_FIELD], 9.0)
            self.assertEqual(saved[BEAMS_DISABLE_CURRENT_LIMIT_FIELD], 0.7)

            self.assertTrue(save_beams_disable_current_limit_ma(0.5, config_path))
            with open(config_path, "r") as file:
                saved = json.load(file)

            self.assertEqual(saved[TOTAL_MAX_EMISSION_CURRENT_FIELD], 5.0)
            self.assertEqual(saved[VTRX_CCS_DISABLE_GRACE_PERIOD_FIELD], 9.0)
            self.assertEqual(saved[BEAMS_DISABLE_CURRENT_LIMIT_FIELD], 0.5)

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
                load_beams_disable_current_limit_ma(config_path),
                DEFAULT_BEAMS_DISABLE_CURRENT_LIMIT_MA,
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
                saved[BEAMS_DISABLE_CURRENT_LIMIT_FIELD],
                DEFAULT_BEAMS_DISABLE_CURRENT_LIMIT_MA,
            )


class MainControlBeamsOffTest(unittest.TestCase):
    def test_disarm_failure_after_confirmed_all_off_reports_failure(self):
        beam_pulse = FakeBeamPulseEstop(
            stop_all_result=True,
            armed=True,
            disarm_result=False,
        )
        cathode = FakeCathode(active=True)
        main_control = make_main_control_for_beams_off(
            beam_pulse=beam_pulse,
            cathode=cathode,
        )

        main_control.handle_beams_off()

        self.assertEqual(beam_pulse.stop_all_calls, 1)
        self.assertEqual(beam_pulse.disarm_calls, 1)
        self.assertEqual(beam_pulse.disarm_preserve_pending_acks_values, [True])
        self.assertTrue(beam_pulse.armed)
        self.assertEqual(cathode.turn_off_calls, 1)
        self.assertEqual(
            main_control._beam_action_status_text,
            "Failed to stop beams: BCON all-off was not confirmed",
        )
        self.assertEqual(main_control._beam_action_status_outcome, "failure")
        self.assertTrue(
            any(
                "Failed to send redundant BCON all-off via Beams E-stop" in message
                for message in main_control.logger.messages("CRITICAL")
            )
        )

    def test_estop_sends_both_redundant_all_off_commands_while_unarmed(self):
        beam_pulse = FakeBeamPulseEstop(armed=False)
        main_control = make_main_control_for_beams_off(beam_pulse=beam_pulse)

        main_control.handle_beams_off()

        self.assertEqual(beam_pulse.stop_all_calls, 1)
        self.assertEqual(beam_pulse.disarm_calls, 1)

    def test_estop_retains_supplied_cause_after_bcon_confirmation(self):
        beam_pulse = FakeBeamPulseEstop()
        main_control = make_main_control_for_beams_off(beam_pulse=beam_pulse)
        cause = "Operator-requested E-Stop: All Beams Disabled"

        main_control.handle_beams_off(cause)
        token = main_control._pending_bcon_operation["token"]
        main_control._handle_bcon_operation_event("operation_sent", {
            "token": token,
            "sent_at": 100.0,
        })
        main_control._handle_bcon_operation_event("operation_result", {
            "operation_token": token,
            "accepted": True,
            "last_command_result": "EXECUTED",
        })
        main_control._handle_bcon_operation_event("operation_poll", {
            "completed_at": 100.1,
        })

        self.assertEqual(
            main_control._beam_action_status_text,
            (
                f"Command Success: {cause} | E-STOP command: all channels mode=OFF | "
                "FW: OK | Status Poll: OK"
            ),
        )
        self.assertEqual(main_control._beam_action_status_outcome, "estop")
        self.assertEqual(main_control._beam_action_status_color, BEAM_ACTION_NEUTRAL_COLOR)
        self.assertEqual(beam_pulse.complete_disarm_calls, 1)

    def test_estop_timeout_preserves_arming_state_and_allows_recovery_action(self):
        beam_pulse = FakeBeamPulseEstop(armed=True)
        main_control = make_main_control_for_beams_off(beam_pulse=beam_pulse)

        main_control.handle_beams_off()
        token = main_control._pending_bcon_operation["token"]
        main_control._handle_bcon_operation_event("operation_sent", {
            "token": token,
            "sent_at": 100.0,
        })
        main_control._expire_bcon_operation(token, "ack")

        self.assertTrue(beam_pulse.armed)
        self.assertIsNone(main_control._pending_bcon_operation)
        self.assertIn("E-STOP confirmation timed out", main_control._beam_action_status_text)
        self.assertIn("arming state is unchanged", main_control._beam_action_status_text)
        self.assertIn("controls remain available", main_control._beam_action_status_text)
        self.assertEqual(main_control._beam_action_status_outcome, "failure")
        self.assertTrue(any(
            "E-STOP confirmation timed out" in message
            for message in main_control.logger.messages("CRITICAL")
        ))

        recovery_token = main_control._start_bcon_operation("Beam A ON", (0,))
        self.assertIsNotNone(recovery_token)

    def test_failed_estop_allows_operator_recovery_before_timeout(self):
        beam_pulse = FakeBeamPulseEstop(armed=True)
        main_control = make_main_control_for_beams_off(beam_pulse=beam_pulse)

        main_control.handle_beams_off()
        token = main_control._pending_bcon_operation["token"]
        main_control._handle_bcon_operation_event("operation_sent", {
            "token": token,
            "sent_at": 100.0,
        })
        main_control._handle_bcon_operation_event("operation_result", {
            "operation_token": token,
            "accepted": False,
            "rejected": True,
            "last_reject_reason": "NOT_READY",
        })

        recovery_token = main_control._start_bcon_operation("Beam A ON", (0,))

        self.assertIsNotNone(recovery_token)
        self.assertEqual(main_control._pending_bcon_operation["token"], recovery_token)
        self.assertTrue(any(
            "proceeding after failed E-STOP confirmation" in message
            for message in main_control.logger.messages("WARNING")
        ))


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
    @staticmethod
    def _start_sent_all_off(main_control, kind):
        token = main_control._start_bcon_operation(
            f"{kind} all-off",
            range(3),
            expected="all_off",
            kind=kind,
        )
        main_control._handle_bcon_operation_event(
            "operation_sent",
            {"token": token, "sent_at": 100.0},
        )
        return token

    @staticmethod
    def _fail_operation(main_control, token, event_type):
        info = {"operation_token": token}
        if event_type == "operation_result":
            info.update(rejected=True, last_reject_reason="TEST_REJECTION")
        else:
            info["reason"] = "test failure"
        main_control._handle_bcon_operation_event(event_type, info)

    @staticmethod
    def _enable_beam_pressure_guard(main_control):
        main_control.disable_beams_on_vtrx_pressure_exceeded = True
        main_control._vtrx_pressure_beam_disable_latched = False

    def test_wire_vtrx_gives_cathode_pressure_guard_without_beam_pulse(self):
        cathode = FakeCathode(active=False)
        vtrx = FakeVtrx()
        main_control = make_main_control(cathode=cathode)

        main_control.wire_vtrx(vtrx)

        self.assertEqual(vtrx.pressure_callback.__self__, main_control)
        self.assertEqual(
            vtrx.pressure_callback.__func__,
            MainControlPanel._handle_vtrx_pressure_update,
        )
        pressure_guard = cathode.vtrx_ccs_pressure_allows_output
        self.assertEqual(pressure_guard.__self__, main_control)
        self.assertEqual(
            pressure_guard.__func__,
            MainControlPanel._vtrx_ccs_pressure_output_status,
        )

    def test_wire_vtrx_none_still_gives_cathode_pressure_guard(self):
        cathode = FakeCathode(active=False)
        main_control = make_main_control(cathode=cathode)

        main_control.wire_vtrx(None)

        pressure_guard = cathode.vtrx_ccs_pressure_allows_output
        self.assertEqual(pressure_guard.__self__, main_control)
        self.assertEqual(
            pressure_guard.__func__,
            MainControlPanel._vtrx_ccs_pressure_output_status,
        )

    def test_wire_beam_pulse_uses_passed_instance_for_cathode_guard_wiring(self):
        cathode = FakeCathode(active=False)
        beam_pulse = FakeBeamPulse(connected=True)
        main_control = make_main_control(cathode=cathode)

        main_control.wire_beam_pulse(beam_pulse)

        self.assertTrue(cathode.disable_ccs_output_on_bcon_disconnect)
        self.assertTrue(cathode.bcon_is_connected())
        pressure_guard = cathode.vtrx_ccs_pressure_allows_output
        self.assertEqual(pressure_guard.__self__, main_control)
        self.assertEqual(
            pressure_guard.__func__,
            MainControlPanel._vtrx_ccs_pressure_output_status,
        )

    def test_timer_warns_and_turns_off_ccs_once_after_grace_period(self):
        cathode = FakeCathode(active=True)
        main_control = make_main_control(cathode=cathode)

        main_control._handle_vtrx_pressure_update(2e-5, pressure_reading_is_fresh=True)

        self.assertEqual(main_control._vtrx_ccs_disable_timer_started_at, 100.0)
        self.assertTrue(
            any("CCS output will be disabled in 30 seconds" in message for message in main_control.logger.messages("CRITICAL"))
        )

        main_control._test_time["value"] = 109.0
        main_control._handle_vtrx_pressure_update(2e-5, pressure_reading_is_fresh=True)
        self.assertEqual(main_control.logger.messages("WARNING"), [])
        self.assertEqual(cathode.turn_off_calls, 0)

        main_control._test_time["value"] = 110.0
        main_control._handle_vtrx_pressure_update(2e-5, pressure_reading_is_fresh=True)
        self.assertTrue(
            any(
                "CCS output will be disabled in 20 seconds due to VTRX pressure being above"
                in message
                for message in main_control.logger.messages("WARNING")
            )
        )

        main_control._test_time["value"] = 130.0
        main_control._handle_vtrx_pressure_update(2e-5, pressure_reading_is_fresh=True)
        self.assertEqual(cathode.turn_off_calls, 1)
        self.assertEqual(main_control._vtrx_ccs_disable_timer_started_at, 100.0)

        main_control._test_time["value"] = 140.0
        main_control._handle_vtrx_pressure_update(2e-5, pressure_reading_is_fresh=True)
        self.assertEqual(cathode.turn_off_calls, 1)

    def test_timer_does_not_start_when_ccs_inactive(self):
        main_control = make_main_control(cathode=FakeCathode(active=False))

        main_control._handle_vtrx_pressure_update(2e-5, pressure_reading_is_fresh=True)

        self.assertIsNone(main_control._vtrx_ccs_disable_timer_started_at)
        self.assertFalse(
            any("CCS output will be disabled after" in message for message in main_control.logger.messages("CRITICAL"))
        )
        self.assertEqual(main_control.logger.messages("WARNING"), [])

    def test_inactive_ccs_output_clears_existing_shutdown_timer(self):
        cathode = FakeCathode(active=True)
        main_control = make_main_control(cathode=cathode)

        main_control._handle_vtrx_pressure_update(2e-5, pressure_reading_is_fresh=True)
        self.assertEqual(main_control._vtrx_ccs_disable_timer_started_at, 100.0)

        cathode.toggle_states = [False, False, False]
        main_control._test_time["value"] = 110.0
        main_control._handle_vtrx_pressure_update(2e-5, pressure_reading_is_fresh=True)

        self.assertIsNone(main_control._vtrx_ccs_disable_timer_started_at)
        self.assertIsNone(main_control._vtrx_ccs_disable_last_warning_at)
        self.assertEqual(cathode.turn_off_calls, 0)
        self.assertEqual(main_control.logger.messages("WARNING"), [])

    def test_pressure_recovery_clears_timer(self):
        main_control = make_main_control(cathode=FakeCathode(active=True))

        main_control._handle_vtrx_pressure_update(2e-5, pressure_reading_is_fresh=True)
        self.assertIsNotNone(main_control._vtrx_ccs_disable_timer_started_at)

        main_control._handle_vtrx_pressure_update(5e-6, pressure_reading_is_fresh=True)

        self.assertIsNone(main_control._vtrx_ccs_disable_timer_started_at)

    def test_stale_pressure_starts_ccs_shutdown_sequence_and_blocks_output(self):
        cathode = FakeCathode(active=True)
        main_control = make_main_control(cathode=cathode)

        main_control._handle_vtrx_pressure_update(5e-6, pressure_reading_is_fresh=False)

        self.assertEqual(main_control._vtrx_ccs_disable_timer_started_at, 100.0)
        self.assertFalse(main_control.pressure_reading_is_fresh)
        self.assertFalse(main_control._vtrx_ccs_pressure_allows_output())
        self.assertEqual(cathode.turn_off_calls, 0)
        self.assertTrue(
            any(
                "pressure reading is stale; CCS output will be disabled in 30 seconds" in message
                for message in main_control.logger.messages("CRITICAL")
            )
        )

        main_control._test_time["value"] = 130.0
        main_control._handle_vtrx_pressure_update(5e-6, pressure_reading_is_fresh=False)

        self.assertEqual(cathode.turn_off_calls, 1)

    def test_stale_pressure_status_explains_ccs_output_block_reason(self):
        main_control = make_main_control(cathode=FakeCathode(active=True))

        main_control._handle_vtrx_pressure_update(5e-6, pressure_reading_is_fresh=False)

        self.assertEqual(
            main_control._vtrx_ccs_pressure_output_status(),
            (False, "VTRX pressure reading is stale."),
        )

    def test_vtrx_firmware_error_starts_ccs_shutdown_sequence_and_blocks_output(self):
        cathode = FakeCathode(active=True)
        main_control = make_main_control(cathode=cathode)

        main_control._handle_vtrx_pressure_update(
            5e-6,
            pressure_reading_is_fresh=True,
            firmware_error=True,
        )

        self.assertTrue(main_control.vtrx_firmware_error)
        self.assertEqual(main_control._vtrx_ccs_disable_timer_started_at, 100.0)
        self.assertEqual(
            main_control._vtrx_ccs_pressure_output_status(),
            (False, "VTRX firmware error reported."),
        )
        self.assertEqual(cathode.turn_off_calls, 0)
        self.assertTrue(
            any(
                "VTRX firmware error reported; CCS output will be disabled in 30 seconds"
                in message
                for message in main_control.logger.messages("CRITICAL")
            )
        )

        main_control._test_time["value"] = 130.0
        main_control._handle_vtrx_pressure_update(
            5e-6,
            pressure_reading_is_fresh=True,
            firmware_error=True,
        )

        self.assertEqual(cathode.turn_off_calls, 1)
        self.assertTrue(
            any(
                "VTRX firmware error remained active for 30 seconds; disabling CCS output."
                in message
                for message in main_control.logger.messages("CRITICAL")
            )
        )

    def test_fresh_safe_pressure_clears_firmware_error_ccs_shutdown(self):
        main_control = make_main_control(cathode=FakeCathode(active=True))
        main_control._vtrx_ccs_disable_timer_started_at = 90.0
        main_control._vtrx_ccs_disable_last_warning_at = 90.0
        main_control.vtrx_firmware_error = True

        main_control._handle_vtrx_pressure_update(
            5e-6,
            pressure_reading_is_fresh=True,
            firmware_error=False,
        )

        self.assertFalse(main_control.vtrx_firmware_error)
        self.assertTrue(main_control.pressure_reading_is_fresh)
        self.assertIsNone(main_control._vtrx_ccs_disable_timer_started_at)
        self.assertTrue(main_control._vtrx_ccs_pressure_allows_output())

    def test_fresh_pressure_below_limit_clears_stale_ccs_shutdown(self):
        main_control = make_main_control(cathode=FakeCathode(active=True))
        main_control._vtrx_ccs_disable_timer_started_at = 90.0
        main_control._vtrx_ccs_disable_last_warning_at = 90.0

        main_control._handle_vtrx_pressure_update(5e-6, pressure_reading_is_fresh=True)

        self.assertTrue(main_control.pressure_reading_is_fresh)
        self.assertIsNone(main_control._vtrx_ccs_disable_timer_started_at)
        self.assertTrue(main_control._vtrx_ccs_pressure_allows_output())

    def test_stale_pressure_turns_off_bcon_channels_and_latches_until_fresh_safe(self):
        beam_pulse = FakeBeamPulse()
        main_control = make_main_control(beam_pulse=beam_pulse)
        self._enable_beam_pressure_guard(main_control)
        main_control._beam_software_interlock_states = [True, True, True]

        main_control._handle_vtrx_pressure_update(5e-6, pressure_reading_is_fresh=False)

        self.assertEqual(beam_pulse.disable_all_calls, 1)
        self.assertEqual(beam_pulse.defer_ui_values, [True])
        token = main_control._pending_bcon_operation["token"]
        self.assertEqual(beam_pulse.operation_tokens, [token])
        self.assertTrue(main_control._vtrx_pressure_beam_disable_latched)
        self.assertTrue(
            any(
                "VTRX pressure reading is stale; disabling all beams" in message
                for message in main_control.logger.messages("CRITICAL")
            )
        )

        main_control._handle_bcon_operation_event("operation_sent", {
            "token": token,
            "sent_at": 100.0,
        })
        main_control._handle_bcon_operation_event("operation_result", {
            "operation_token": token,
            "accepted": True,
            "last_command_result": "EXECUTED",
        })
        main_control._handle_bcon_operation_event("operation_poll", {
            "completed_at": 100.1,
        })

        self.assertEqual(main_control._beam_software_interlock_states, [False, False, False])
        self.assertIn("VTRX pressure reading stale safety shutdown", main_control._beam_action_status_text)

        main_control._handle_vtrx_pressure_update(5e-6, pressure_reading_is_fresh=True)

        self.assertFalse(main_control._vtrx_pressure_beam_disable_latched)

    def test_failed_estop_retries_pressure_shutdown_in_either_event_order(self):
        for event_type in (
            "operation_result",
            "operation_failed",
            "operation_cancelled",
        ):
            for failure_before_pressure in (True, False):
                with self.subTest(
                    event_type=event_type,
                    failure_before_pressure=failure_before_pressure,
                ):
                    beam_pulse = FakeBeamPulse()
                    main_control = make_main_control(beam_pulse=beam_pulse)
                    self._enable_beam_pressure_guard(main_control)
                    token = self._start_sent_all_off(main_control, "estop")

                    if failure_before_pressure:
                        self._fail_operation(main_control, token, event_type)
                    else:
                        main_control._handle_vtrx_pressure_update(
                            2e-5,
                            pressure_reading_is_fresh=True,
                        )
                        self.assertEqual(beam_pulse.disable_all_calls, 0)
                        self.assertTrue(
                            main_control._vtrx_pressure_beam_disable_latched
                        )
                        self._fail_operation(main_control, token, event_type)
                        self.assertFalse(
                            main_control._vtrx_pressure_beam_disable_latched
                        )

                    failed_estop = main_control._pending_bcon_operation
                    self.assertEqual(failed_estop["token"], token)
                    self.assertTrue(failed_estop["safety_failed"])

                    main_control._handle_vtrx_pressure_update(
                        2e-5,
                        pressure_reading_is_fresh=True,
                    )

                    self.assertEqual(beam_pulse.disable_all_calls, 1)
                    self.assertEqual(
                        main_control._pending_bcon_operation["kind"],
                        "disable_all",
                    )
                    self.assertNotEqual(
                        main_control._pending_bcon_operation["token"],
                        token,
                    )
                    self.assertTrue(
                        main_control._vtrx_pressure_beam_disable_latched
                    )

    def test_healthy_pending_all_off_covers_pressure_until_safe(self):
        for kind in ("disable_all", "disarm", "estop"):
            with self.subTest(kind=kind):
                beam_pulse = FakeBeamPulse()
                main_control = make_main_control(beam_pulse=beam_pulse)
                self._enable_beam_pressure_guard(main_control)
                token = self._start_sent_all_off(main_control, kind)

                main_control._handle_vtrx_pressure_update(
                    2e-5,
                    pressure_reading_is_fresh=True,
                )
                main_control._handle_vtrx_pressure_update(
                    2e-5,
                    pressure_reading_is_fresh=True,
                )

                self.assertEqual(beam_pulse.disable_all_calls, 0)
                self.assertTrue(main_control._vtrx_pressure_beam_disable_latched)

                main_control._handle_bcon_operation_event(
                    "operation_result",
                    {
                        "operation_token": token,
                        "accepted": True,
                        "last_command_result": "EXECUTED",
                    },
                )
                main_control._handle_bcon_operation_event(
                    "operation_poll",
                    {"completed_at": 100.1},
                )
                main_control._handle_vtrx_pressure_update(
                    2e-5,
                    pressure_reading_is_fresh=True,
                )

                self.assertIsNone(main_control._pending_bcon_operation)
                self.assertEqual(beam_pulse.disable_all_calls, 0)
                self.assertTrue(main_control._vtrx_pressure_beam_disable_latched)

                main_control._handle_vtrx_pressure_update(
                    5e-6,
                    pressure_reading_is_fresh=True,
                )
                self.assertFalse(main_control._vtrx_pressure_beam_disable_latched)

    def test_unsuccessful_all_off_outcomes_release_pressure_latch(self):
        event_types = (
            "operation_result",
            "operation_failed",
            "operation_cancelled",
        )
        for event_type in event_types:
            with self.subTest(outcome=event_type):
                main_control = make_main_control()
                token = self._start_sent_all_off(main_control, "disarm")
                main_control._vtrx_pressure_beam_disable_latched = True

                self._fail_operation(main_control, token, event_type)

                self.assertIsNone(main_control._pending_bcon_operation)
                self.assertFalse(main_control._vtrx_pressure_beam_disable_latched)

        for state, phase in (
            ("awaiting_send", "send"),
            ("awaiting_ack", "ack"),
            ("awaiting_poll", "ack"),
        ):
            with self.subTest(outcome="timeout", state=state):
                main_control = make_main_control()
                token = main_control._start_bcon_operation(
                    "disarm all-off",
                    range(3),
                    expected="all_off",
                    kind="disarm",
                )
                main_control._pending_bcon_operation["state"] = state
                if state != "awaiting_send":
                    main_control._pending_bcon_operation["sent_at"] = 100.0
                main_control._vtrx_pressure_beam_disable_latched = True

                main_control._expire_bcon_operation(token, phase)

                self.assertIsNone(main_control._pending_bcon_operation)
                self.assertFalse(main_control._vtrx_pressure_beam_disable_latched)

        main_control = make_main_control()
        self._start_sent_all_off(main_control, "disarm")
        main_control._vtrx_pressure_beam_disable_latched = True

        main_control._terminate_pending_bcon_operation("test disconnect")

        self.assertIsNone(main_control._pending_bcon_operation)
        self.assertFalse(main_control._vtrx_pressure_beam_disable_latched)

    def test_non_all_off_failures_do_not_release_pressure_latch(self):
        for outcome in ("rejected", "failed", "cancelled", "timeout", "terminated"):
            with self.subTest(outcome=outcome):
                main_control = make_main_control()
                token = main_control._start_bcon_operation(
                    "normal operation",
                    (0,),
                    expected="poll",
                    kind="normal",
                )
                main_control._vtrx_pressure_beam_disable_latched = True

                if outcome == "rejected":
                    self._fail_operation(
                        main_control,
                        token,
                        "operation_result",
                    )
                elif outcome == "failed":
                    self._fail_operation(
                        main_control,
                        token,
                        "operation_failed",
                    )
                elif outcome == "cancelled":
                    self._fail_operation(
                        main_control,
                        token,
                        "operation_cancelled",
                    )
                elif outcome == "timeout":
                    main_control._expire_bcon_operation(token, "send")
                else:
                    main_control._terminate_pending_bcon_operation(
                        "test disconnect"
                    )

                self.assertTrue(main_control._vtrx_pressure_beam_disable_latched)

    def test_all_off_preemption_keeps_latch_until_final_operation_fails(self):
        beam_pulse = FakeBeamPulse()
        main_control = make_main_control(beam_pulse=beam_pulse)
        self._enable_beam_pressure_guard(main_control)
        disable_token = self._start_sent_all_off(main_control, "disable_all")

        main_control._handle_vtrx_pressure_update(
            2e-5,
            pressure_reading_is_fresh=True,
        )
        disarm_token = self._start_sent_all_off(main_control, "disarm")

        self.assertNotEqual(disarm_token, disable_token)
        self.assertTrue(main_control._vtrx_pressure_beam_disable_latched)

        self._fail_operation(main_control, disable_token, "operation_failed")

        self.assertEqual(
            main_control._pending_bcon_operation["token"],
            disarm_token,
        )
        self.assertTrue(main_control._vtrx_pressure_beam_disable_latched)

        estop_token = self._start_sent_all_off(main_control, "estop")

        self.assertNotEqual(estop_token, disarm_token)
        self.assertTrue(main_control._vtrx_pressure_beam_disable_latched)

        self._fail_operation(main_control, estop_token, "operation_failed")

        self.assertFalse(main_control._vtrx_pressure_beam_disable_latched)

        main_control._handle_vtrx_pressure_update(
            2e-5,
            pressure_reading_is_fresh=True,
        )

        self.assertEqual(beam_pulse.disable_all_calls, 1)
        self.assertTrue(main_control._vtrx_pressure_beam_disable_latched)

    def test_failed_estop_poll_still_allows_conservative_pressure_retry(self):
        beam_pulse = FakeBeamPulse()
        main_control = make_main_control(beam_pulse=beam_pulse)
        self._enable_beam_pressure_guard(main_control)
        token = self._start_sent_all_off(main_control, "estop")

        main_control._handle_vtrx_pressure_update(
            2e-5,
            pressure_reading_is_fresh=True,
        )
        self._fail_operation(main_control, token, "operation_failed")
        main_control._handle_bcon_operation_event(
            "operation_poll",
            {"completed_at": 100.1},
        )

        self.assertIsNone(main_control._pending_bcon_operation)
        self.assertFalse(main_control._vtrx_pressure_beam_disable_latched)

        main_control._handle_vtrx_pressure_update(
            2e-5,
            pressure_reading_is_fresh=True,
        )

        self.assertEqual(beam_pulse.disable_all_calls, 1)
        self.assertTrue(main_control._vtrx_pressure_beam_disable_latched)

    def test_synchronous_all_off_failure_waits_for_timeout_before_retry(self):
        beam_pulse = FakeBeamPulse(disable_all_result=False)
        main_control = make_main_control(beam_pulse=beam_pulse)
        self._enable_beam_pressure_guard(main_control)

        main_control._handle_vtrx_pressure_update(
            2e-5,
            pressure_reading_is_fresh=True,
        )

        failed_token = main_control._pending_bcon_operation["token"]
        self.assertEqual(beam_pulse.disable_all_calls, 1)
        self.assertFalse(main_control._vtrx_pressure_beam_disable_latched)

        main_control._handle_vtrx_pressure_update(
            2e-5,
            pressure_reading_is_fresh=True,
        )

        self.assertEqual(beam_pulse.disable_all_calls, 1)
        self.assertTrue(main_control._vtrx_pressure_beam_disable_latched)

        main_control._expire_bcon_operation(failed_token, "send")

        self.assertIsNone(main_control._pending_bcon_operation)
        self.assertFalse(main_control._vtrx_pressure_beam_disable_latched)

        main_control._handle_vtrx_pressure_update(
            2e-5,
            pressure_reading_is_fresh=True,
        )

        self.assertEqual(beam_pulse.disable_all_calls, 2)
        self.assertFalse(main_control._vtrx_pressure_beam_disable_latched)

    def test_all_unsafe_pressure_sources_share_all_off_retry_behavior(self):
        unsafe_updates = (
            (2e-5, True, False),
            (5e-6, False, False),
            (5e-6, True, True),
        )
        for pressure, fresh, firmware_error in unsafe_updates:
            with self.subTest(
                pressure=pressure,
                fresh=fresh,
                firmware_error=firmware_error,
            ):
                beam_pulse = FakeBeamPulse()
                main_control = make_main_control(beam_pulse=beam_pulse)
                self._enable_beam_pressure_guard(main_control)
                token = self._start_sent_all_off(main_control, "estop")

                main_control._handle_vtrx_pressure_update(
                    pressure,
                    pressure_reading_is_fresh=fresh,
                    firmware_error=firmware_error,
                )
                self.assertEqual(beam_pulse.disable_all_calls, 0)

                self._fail_operation(
                    main_control,
                    token,
                    "operation_cancelled",
                )
                main_control._handle_vtrx_pressure_update(
                    pressure,
                    pressure_reading_is_fresh=fresh,
                    firmware_error=firmware_error,
                )

                self.assertEqual(beam_pulse.disable_all_calls, 1)
                self.assertTrue(main_control._vtrx_pressure_beam_disable_latched)

    def test_high_pressure_resets_interlocks_only_after_confirmed_all_off_poll(self):
        beam_pulse = FakeBeamPulse()
        main_control = make_main_control(beam_pulse=beam_pulse)
        self._enable_beam_pressure_guard(main_control)
        main_control._beam_software_interlock_states = [True, True, True]

        main_control._handle_vtrx_pressure_update(2e-5, pressure_reading_is_fresh=True)

        token = main_control._pending_bcon_operation["token"]
        self.assertEqual(main_control._beam_software_interlock_states, [True, True, True])

        main_control._handle_bcon_operation_event("operation_sent", {
            "token": token,
            "sent_at": 100.0,
        })
        main_control._handle_bcon_operation_event("operation_result", {
            "operation_token": token,
            "accepted": True,
            "last_command_result": "EXECUTED",
        })
        main_control._handle_bcon_operation_event("operation_poll", {
            "completed_at": 100.1,
        })

        self.assertEqual(main_control._beam_software_interlock_states, [False, False, False])
        self.assertIn("VTRX pressure safety shutdown", main_control._beam_action_status_text)

    def test_vtrx_firmware_error_turns_off_bcon_channels_and_latches_until_clear(self):
        beam_pulse = FakeBeamPulse()
        main_control = make_main_control(beam_pulse=beam_pulse)
        self._enable_beam_pressure_guard(main_control)

        main_control._handle_vtrx_pressure_update(
            5e-6,
            pressure_reading_is_fresh=True,
            firmware_error=True,
        )

        self.assertEqual(beam_pulse.disable_all_calls, 1)
        self.assertTrue(main_control._vtrx_pressure_beam_disable_latched)
        self.assertTrue(
            any(
                "VTRX firmware error reported; disabling all beams" in message
                for message in main_control.logger.messages("CRITICAL")
            )
        )

        main_control._handle_vtrx_pressure_update(
            5e-6,
            pressure_reading_is_fresh=True,
            firmware_error=False,
        )

        self.assertFalse(main_control._vtrx_pressure_beam_disable_latched)

    def test_disabled_pressure_shutdown_does_not_start_timer_or_turn_off_ccs(self):
        cathode = FakeCathode(active=True)
        main_control = make_main_control(cathode=cathode)
        main_control.vtrx_ccs_pressure_shutdown_enabled = False
        main_control._vtrx_ccs_disable_timer_started_at = 90.0
        main_control._vtrx_ccs_disable_last_warning_at = 90.0

        main_control._handle_vtrx_pressure_update(2e-5, pressure_reading_is_fresh=True)

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
