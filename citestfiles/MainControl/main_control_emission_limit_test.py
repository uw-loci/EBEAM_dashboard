import os
import queue
import shutil
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

from subsystem.cathode_heating.cathode_heating import CathodeHeatingSubsystem
from subsystem.beam_pulse.beam_pulse import BeamPulseSubsystem
from subsystem.main_control.main_control import MainControlPanel
from usr.main_control_config import (
    load_total_max_emission_current,
    save_total_max_emission_current,
)


class FakeVar:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class FakeButton:
    def __init__(self):
        self.config_calls = []
        self.values = {"bg": "gray"}

    def config(self, **kwargs):
        self.config_calls.append(kwargs)
        self.values.update(kwargs)

    def cget(self, key):
        return self.values.get(key)


class FakeCathode:
    def __init__(self, values):
        self.values = values

    def get_predicted_emission_currents_ma(self):
        return list(self.values)


class FakeBCON:
    def __init__(self, enabled=False):
        self.enabled = enabled
        self.set_channel_enable = MagicMock(return_value=True)

    def is_channel_enabled(self, channel):
        return self.enabled


class FakeBeamPulse:
    def __init__(self, statuses, mode="PULSE"):
        self.statuses = statuses
        self.bcon_driver = FakeBCON(enabled=False)
        self.send_channel_config = MagicMock(return_value=True)
        self.send_channel_off = MagicMock(return_value=True)
        self.get_channel_config = MagicMock(return_value={"mode": mode, "duration_ms": 100, "count": 1})

    def get_beam_status(self, index):
        return self.statuses[index]

    def get_beams_armed_status(self):
        return True


class FakeLaserMonitor:
    def __init__(self):
        self.states = []

    def set_beams_on(self, active):
        self.states.append(bool(active))


def make_dashboard(limit=6.0, emission_values=None, beam_pulse=None, laser_monitor=None):
    dash = object.__new__(MainControlPanel)
    dash.logger = MagicMock()
    dash.total_max_emission_current_ma = limit
    dash.total_max_emission_current_value_var = FakeVar("")
    dash._initialize_main_control_beam_status_state()
    dash.beam_toggle_buttons = [FakeButton(), FakeButton(), FakeButton()]
    dash.enable_toggle_buttons = [FakeButton(), FakeButton(), FakeButton()]
    dash.beams_ready_button = FakeButton()
    dash.toggle_on_image = None
    dash.toggle_off_image = None
    dash._ch_enable_states = [False, False, False]
    dash.subsystems = {
        "Cathode Heating": FakeCathode(emission_values or [0.0, 0.0, 0.0]),
    }
    if beam_pulse is not None:
        dash.subsystems["Beam Pulse"] = beam_pulse
    if laser_monitor is not None:
        dash.subsystems["Laser Monitor"] = laser_monitor
    return dash


class TestMainControlEmissionConfig(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tempdir, ignore_errors=True)

    def test_missing_config_defaults_to_six_ma(self):
        filepath = os.path.join(self.tempdir, "missing.json")

        loaded = load_total_max_emission_current(filepath=filepath, logger=MagicMock())

        self.assertEqual(loaded, 6.0)

    def test_save_and_load_config_value(self):
        filepath = os.path.join(self.tempdir, "main_control.json")

        saved = save_total_max_emission_current(4.25, filepath=filepath, logger=MagicMock())
        loaded = load_total_max_emission_current(filepath=filepath, logger=MagicMock())

        self.assertTrue(saved)
        self.assertEqual(loaded, 4.25)

    def test_invalid_config_normalizes_to_default(self):
        filepath = os.path.join(self.tempdir, "main_control.json")
        with open(filepath, "w") as file:
            file.write('{"total_max_emission_current_ma": "NaN"}')

        loaded = load_total_max_emission_current(filepath=filepath, logger=MagicMock())

        self.assertEqual(loaded, 6.0)

    def test_legacy_config_object_still_loads(self):
        filepath = os.path.join(self.tempdir, "main_control.json")
        with open(filepath, "w") as file:
            file.write('{"total_max_emission_current_ma": 4.5}')

        loaded = load_total_max_emission_current(filepath=filepath, logger=MagicMock())

        self.assertEqual(loaded, 4.5)


class TestMainControlEmissionLimit(unittest.TestCase):
    def test_cathode_getter_treats_invalid_values_as_zero(self):
        cathode = object.__new__(CathodeHeatingSubsystem)
        cathode.ideal_cathode_emission_currents = [1.25, float("nan"), "bad"]

        self.assertEqual(cathode.get_predicted_emission_currents_ma(), [1.25, 0.0, 0.0])

    def test_equality_blocks_output(self):
        dash = make_dashboard(limit=6.0, emission_values=[2.0, 4.0, float("nan")])

        allowed = dash.check_total_emission_current_limit("Test action", [0, 1])

        self.assertFalse(allowed)
        dash.logger.error.assert_called_once()

    def test_beam_on_blocks_before_sending_channel_config(self):
        beam_pulse = FakeBeamPulse(statuses=[False, True, False], mode="PULSE")
        dash = make_dashboard(
            limit=6.0,
            emission_values=[2.0, 4.0, 0.0],
            beam_pulse=beam_pulse,
        )

        dash.toggle_individual_beam_with_status(0)

        beam_pulse.send_channel_config.assert_not_called()
        dash.logger.error.assert_called_once()

    def test_beam_on_allows_below_limit(self):
        beam_pulse = FakeBeamPulse(statuses=[False, True, False], mode="PULSE")
        dash = make_dashboard(
            limit=6.1,
            emission_values=[2.0, 4.0, 0.0],
            beam_pulse=beam_pulse,
        )

        dash.toggle_individual_beam_with_status(0)

        beam_pulse.send_channel_config.assert_called_once_with(0)

    def test_beam_on_allows_off_mode_without_emission_check(self):
        beam_pulse = FakeBeamPulse(statuses=[False, True, False], mode="OFF")
        dash = make_dashboard(
            limit=1.0,
            emission_values=[2.0, 4.0, 0.0],
            beam_pulse=beam_pulse,
        )

        dash.toggle_individual_beam_with_status(0)

        beam_pulse.send_channel_config.assert_called_once_with(0)
        dash.logger.error.assert_not_called()

    def test_channel_enable_does_not_apply_emission_limit(self):
        beam_pulse = FakeBeamPulse(statuses=[False, False, False], mode="PULSE")
        dash = make_dashboard(
            limit=1.0,
            emission_values=[6.0, 0.0, 0.0],
            beam_pulse=beam_pulse,
        )
        dash._on_channel_enable_status_update = MagicMock()

        dash._toggle_channel_enable(0)

        beam_pulse.bcon_driver.set_channel_enable.assert_called_once_with(1, True)
        dash.logger.error.assert_not_called()


class TestMainControlBeamStatusText(unittest.TestCase):
    def test_beam_status_formatting(self):
        dash = make_dashboard()

        self.assertEqual(
            dash._format_beam_output_status(0, None),
            "Beam A DISABLED, Output OFF",
        )
        dash._ch_enable_states[0] = True
        self.assertEqual(
            dash._format_beam_output_status(0, None),
            "Beam A ENABLED, Output OFF",
        )
        self.assertEqual(
            dash._format_beam_output_status(0, {"mode": "DC"}),
            "Beam A Output: ON, running DC",
        )
        self.assertEqual(
            dash._format_beam_output_status(0, {"mode": "PULSE", "duration_ms": 100}),
            "Beam A Output: ON, running PULSE for 100ms",
        )
        self.assertEqual(
            dash._format_beam_output_status(
                0,
                {"mode": "PULSE_TRAIN", "duration_ms": 100, "count": 5},
            ),
            "Beam A Output: ON, running PULSE_TRAIN: set to 5 pulses, 100ms each. Remaining: 5",
        )
        self.assertEqual(
            dash._format_beam_output_status(
                0,
                {"mode": "PULSE_TRAIN", "duration_ms": 100, "count": 5, "remaining": 3},
            ),
            "Beam A Output: ON, running PULSE_TRAIN: set to 5 pulses, 100ms each. Remaining: 3",
        )

    def test_manual_beam_on_updates_output_and_action_text(self):
        beam_pulse = FakeBeamPulse(statuses=[False, False, False], mode="PULSE")
        dash = make_dashboard(limit=6.1, emission_values=[1.0, 0.0, 0.0], beam_pulse=beam_pulse)

        dash.toggle_individual_beam_with_status(0)

        self.assertEqual(dash._beam_output_status_text[0], "Beam A Output: ON, running PULSE for 100ms")
        self.assertEqual(dash._beam_output_status_colors[0], "green")
        self.assertEqual(dash._beam_action_status_text, "Beam A successfully set to ON, running PULSE for 100ms")
        self.assertEqual(dash._beam_action_status_color, "green")

    def test_manual_beam_off_updates_output_and_action_text(self):
        beam_pulse = FakeBeamPulse(statuses=[True, False, False], mode="PULSE")
        dash = make_dashboard(beam_pulse=beam_pulse)
        dash._ch_enable_states[0] = True
        dash._set_beam_output_display(0, {"mode": "DC"}, is_on=True)

        dash.toggle_individual_beam_with_status(0)

        self.assertEqual(dash._beam_output_status_text[0], "Beam A ENABLED, Output OFF")
        self.assertEqual(dash._beam_output_status_colors[0], "gray")
        self.assertEqual(dash._beam_action_status_text, "Beam A successfully set to OFF")
        self.assertEqual(dash._beam_action_status_color, "green")

    def test_emission_limit_failure_updates_action_text_without_marking_on(self):
        beam_pulse = FakeBeamPulse(statuses=[False, True, False], mode="PULSE")
        dash = make_dashboard(
            limit=6.0,
            emission_values=[2.0, 4.0, 0.0],
            beam_pulse=beam_pulse,
        )
        dash._on_channel_enable_status_update(0, True)

        dash.toggle_individual_beam_with_status(0)

        beam_pulse.send_channel_config.assert_not_called()
        self.assertEqual(dash._beam_output_status_text[0], "Beam A ENABLED, Output OFF")
        self.assertEqual(
            dash._beam_action_status_text,
            "Failed to set Beam A ON, total emission current limit exceeded",
        )
        self.assertEqual(dash._beam_action_status_color, "red")

    def test_sync_feedback_updates_multiple_beam_lines(self):
        dash = make_dashboard()

        dash._handle_main_control_feedback(
            "beams_sent",
            "Sync Start: A=PULSE(100ms), B=PULSE_TRAIN(50ms x5)",
            "success",
            [
                {"ch": 1, "mode": "PULSE", "duration_ms": 100, "count": 1},
                {"ch": 2, "mode": "PULSE_TRAIN", "duration_ms": 50, "count": 5},
            ],
        )

        self.assertEqual(dash._beam_output_status_text[0], "Beam A Output: ON, running PULSE for 100ms")
        self.assertEqual(
            dash._beam_output_status_text[1],
            "Beam B Output: ON, running PULSE_TRAIN: set to 5 pulses, 50ms each. Remaining: 5",
        )
        self.assertEqual(dash._beam_action_status_color, "green")

    def test_live_status_clears_completed_pulse_line(self):
        dash = make_dashboard()
        dash._ch_enable_states[0] = True
        dash._set_beam_output_display(0, {"mode": "PULSE", "duration_ms": 100, "count": 1}, is_on=True)
        dash.beam_toggle_buttons[0].config(bg="green")

        dash._on_channel_status_update(0, 0, 0)

        self.assertEqual(dash._beam_output_status_text[0], "Beam A ENABLED, Output OFF")
        self.assertEqual(dash._beam_output_status_colors[0], "gray")

    def test_live_status_clears_stale_text_even_if_button_already_gray(self):
        dash = make_dashboard()
        dash._set_beam_output_display(0, {"mode": "PULSE", "duration_ms": 100, "count": 1}, is_on=True)

        dash._on_channel_status_update(0, 0, 0)

        self.assertEqual(dash._beam_output_status_text[0], "Beam A DISABLED, Output OFF")
        self.assertEqual(dash._beam_output_status_colors[0], "gray")

    def test_live_status_updates_output_text_from_firmware_state(self):
        dash = make_dashboard()

        dash._on_channel_status_update(
            0,
            2,
            1,
            {"mode": "PULSE", "duration_ms": 75, "count": 1},
        )

        self.assertEqual(dash._beam_output_status_text[0], "Beam A Output: ON, running PULSE for 75ms")
        self.assertEqual(dash._beam_output_status_colors[0], "green")

    def test_live_status_updates_pulse_train_remaining_from_firmware_state(self):
        dash = make_dashboard()

        dash._on_channel_status_update(
            0,
            3,
            3,
            {"mode": "PULSE_TRAIN", "duration_ms": 50, "count": 5, "remaining": 3},
        )

        self.assertEqual(
            dash._beam_output_status_text[0],
            "Beam A Output: ON, running PULSE_TRAIN: set to 5 pulses, 50ms each. Remaining: 3",
        )
        self.assertEqual(dash._beam_output_status_colors[0], "green")

    def test_laser_monitor_dc_status_sets_beams_on(self):
        laser_monitor = FakeLaserMonitor()
        dash = make_dashboard(laser_monitor=laser_monitor)

        dash._on_channel_status_update(0, 1, 0)

        self.assertEqual(laser_monitor.states, [True])

    def test_laser_monitor_pulsed_status_sets_beams_on(self):
        laser_monitor = FakeLaserMonitor()
        dash = make_dashboard(laser_monitor=laser_monitor)

        dash._on_channel_status_update(1, 2, 5)

        self.assertEqual(laser_monitor.states, [True])

    def test_laser_monitor_one_beam_off_does_not_clear_another_active_beam(self):
        laser_monitor = FakeLaserMonitor()
        dash = make_dashboard(laser_monitor=laser_monitor)

        dash._on_channel_status_update(0, 1, 0)
        dash._on_channel_status_update(1, 2, 5)
        dash._on_channel_status_update(0, 0, 0)

        self.assertEqual(laser_monitor.states, [True])
        self.assertEqual(dash._laser_monitor_active_channels, {1})

    def test_laser_monitor_all_channels_off_sends_false(self):
        laser_monitor = FakeLaserMonitor()
        dash = make_dashboard(laser_monitor=laser_monitor)

        for ch in range(3):
            dash._on_channel_status_update(ch, 1, 0)
        for ch in range(3):
            dash._on_channel_status_update(ch, 0, 0)

        self.assertEqual(laser_monitor.states, [True, False])
        self.assertEqual(dash._laser_monitor_active_channels, set())

    def test_laser_monitor_channel_disable_clears_inactive_channel(self):
        laser_monitor = FakeLaserMonitor()
        dash = make_dashboard(laser_monitor=laser_monitor)

        dash._on_channel_status_update(0, 1, 0)
        dash._on_channel_enable_status_update(0, False)

        self.assertEqual(laser_monitor.states, [True, False])
        self.assertEqual(dash._laser_monitor_active_channels, set())

    def test_laser_monitor_beams_off_forces_false(self):
        laser_monitor = FakeLaserMonitor()
        dash = make_dashboard(laser_monitor=laser_monitor)
        dash._laser_monitor_active_channels = {0}
        dash._laser_monitor_beams_on_sent = True

        dash.handle_beams_off()

        self.assertIn(False, laser_monitor.states)
        self.assertEqual(dash._laser_monitor_active_channels, set())

    def test_laser_monitor_reset_beam_toggle_states_forces_false(self):
        laser_monitor = FakeLaserMonitor()
        dash = make_dashboard(laser_monitor=laser_monitor)
        dash._laser_monitor_active_channels = {0}
        dash._laser_monitor_beams_on_sent = True

        dash.update_beam_toggle_states(enabled=False, reset=True)

        self.assertEqual(laser_monitor.states, [False])
        self.assertEqual(dash._laser_monitor_active_channels, set())

    def test_laser_monitor_connection_loss_forces_false(self):
        laser_monitor = FakeLaserMonitor()
        dash = make_dashboard(laser_monitor=laser_monitor)
        dash._laser_monitor_active_channels = {0}
        dash._laser_monitor_beams_on_sent = True

        dash._update_laser_monitor_beams_on(clear=True)

        self.assertEqual(laser_monitor.states, [False])
        self.assertEqual(dash._laser_monitor_active_channels, set())

    def test_channel_enable_updates_off_output_text(self):
        dash = make_dashboard()

        dash._on_channel_enable_status_update(0, True)

        self.assertEqual(dash._beam_output_status_text[0], "Beam A ENABLED, Output OFF")
        self.assertEqual(dash._beam_output_status_colors[0], "gray")

        dash._on_channel_enable_status_update(0, False)

        self.assertEqual(dash._beam_output_status_text[0], "Beam A DISABLED, Output OFF")
        self.assertEqual(dash._beam_output_status_colors[0], "gray")

    def test_channel_enable_button_press_updates_off_output_text(self):
        beam_pulse = FakeBeamPulse(statuses=[False, False, False], mode="PULSE")
        dash = make_dashboard(beam_pulse=beam_pulse)

        dash._toggle_channel_enable(0)

        self.assertEqual(dash._beam_output_status_text[0], "Beam A ENABLED, Output OFF")
        self.assertEqual(dash._beam_output_status_colors[0], "gray")

    def test_channel_enable_does_not_reword_active_output(self):
        dash = make_dashboard()
        dash._set_beam_output_display(0, {"mode": "DC"}, is_on=True)

        dash._on_channel_enable_status_update(0, True)

        self.assertEqual(dash._beam_output_status_text[0], "Beam A Output: ON, running DC")
        self.assertEqual(dash._beam_output_status_colors[0], "green")

    def test_auto_20kv_estop_clears_outputs_and_sets_required_message(self):
        dash = make_dashboard()
        dash._set_beam_output_display(0, {"mode": "DC"}, is_on=True)
        dash.handle_beams_off("20kV E-Stop Current Limit exceeded: All Beams Disabled")

        self.assertEqual(dash._beam_output_status_text[0], "Beam A DISABLED, Output OFF")
        self.assertEqual(
            dash._beam_action_status_text,
            "20kV E-Stop Current Limit exceeded: All Beams Disabled",
        )
        self.assertEqual(dash._beam_action_status_color, "red")

    def test_arm_button_disarms_without_popup_when_bcon_not_connected(self):
        beam_pulse = object.__new__(BeamPulseSubsystem)
        beam_pulse.beams_armed_status = True
        beam_pulse.beam_on_status = [False, False, False]
        beam_pulse.bcon_driver = None
        beam_pulse._seq_stop = threading.Event()
        beam_pulse._seq_thread = None
        beam_pulse._dashboard_beam_callback = None
        beam_pulse._channel_enable_status_callback = None
        beam_pulse._log = MagicMock()
        beam_pulse._update_armed_button_states = MagicMock()
        dash = make_dashboard(beam_pulse=beam_pulse)

        with patch("subsystem.main_control.main_control.messagebox.showerror") as showerror:
            dash.handle_arm_beams()

        showerror.assert_not_called()
        self.assertFalse(beam_pulse.get_beams_armed_status())
        self.assertEqual(dash._beam_action_status_text, "Beams disarmed")

    def test_arm_button_missing_subsystem_updates_status_without_popup(self):
        dash = make_dashboard()

        with patch("subsystem.main_control.main_control.messagebox.showerror") as showerror:
            dash.handle_arm_beams()

        showerror.assert_not_called()
        self.assertEqual(
            dash._beam_action_status_text,
            "Failed to arm beams, Beam Pulse subsystem not available",
        )
        self.assertEqual(dash._beam_action_status_color, "red")


class TestBeamPulseEmissionLimitHook(unittest.TestCase):
    def make_beam_pulse(self):
        beam_pulse = object.__new__(BeamPulseSubsystem)
        beam_pulse.beams_armed_status = True
        beam_pulse.bcon_driver = MagicMock()
        beam_pulse.channel_vars = [object(), object(), object()]
        beam_pulse._ch_enable_getter = lambda: [True, True, False]
        beam_pulse._emission_limit_checker = MagicMock(return_value=False)
        beam_pulse._log_event = MagicMock()
        return beam_pulse

    def test_sync_start_blocks_before_bcon_sync_start(self):
        beam_pulse = self.make_beam_pulse()
        beam_pulse._validate_and_get_config = MagicMock(side_effect=[
            {"mode": "OFF", "duration_ms": 0, "count": 1},
            {"mode": "PULSE", "duration_ms": 100, "count": 1},
        ])

        beam_pulse._sync_start()

        beam_pulse._emission_limit_checker.assert_called_once()
        self.assertEqual(beam_pulse._emission_limit_checker.call_args.args[1], [1])
        beam_pulse.bcon_driver.sync_start.assert_not_called()

    def test_sync_start_allows_bcon_sync_start_below_limit(self):
        beam_pulse = self.make_beam_pulse()
        beam_pulse._emission_limit_checker = MagicMock(return_value=True)
        beam_pulse._validate_and_get_config = MagicMock(side_effect=[
            {"mode": "OFF", "duration_ms": 0, "count": 1},
            {"mode": "PULSE", "duration_ms": 100, "count": 1},
        ])

        beam_pulse._sync_start()

        beam_pulse.bcon_driver.sync_start.assert_called_once()

    def test_sync_start_feedback_after_bcon_sync_start(self):
        beam_pulse = self.make_beam_pulse()
        feedback = MagicMock()
        beam_pulse.set_main_control_feedback_callback(feedback)
        beam_pulse._emission_limit_checker = MagicMock(return_value=True)
        beam_pulse._validate_and_get_config = MagicMock(side_effect=[
            {"mode": "PULSE", "duration_ms": 100, "count": 1},
            {"mode": "PULSE_TRAIN", "duration_ms": 50, "count": 5},
        ])

        beam_pulse._sync_start()

        beam_pulse.bcon_driver.sync_start.assert_called_once()
        feedback.assert_called_once()
        event_type, message, outcome, configs = feedback.call_args.args
        self.assertEqual(event_type, "beams_sent")
        self.assertEqual(outcome, "success")
        self.assertIn("Sync Start", message)
        self.assertEqual(configs[0]["mode"], "PULSE")
        self.assertEqual(configs[1]["count"], 5)

    def test_firmware_rejection_updates_main_control_feedback(self):
        beam_pulse = self.make_beam_pulse()
        feedback = MagicMock()
        beam_pulse.set_main_control_feedback_callback(feedback)

        beam_pulse._handle_driver_msg(("command_result", {
            "requested_label": "APPLY_STAGED_MODES",
            "last_command_label": "APPLY_STAGED_MODES",
            "last_cmd_seq": 12,
            "rejected": True,
            "last_reject_reason": "UNSAFE_INTERLOCK",
        }))

        feedback.assert_called_once_with(
            "status",
            "BCON command APPLY_STAGED_MODES rejected: UNSAFE_INTERLOCK",
            "failure",
            None,
        )
        beam_pulse._log_event.assert_called_once_with(
            "BCON command APPLY_STAGED_MODES rejected: UNSAFE_INTERLOCK (seq=12)"
        )

    def test_connection_status_callback_runs_on_connected_message_change(self):
        beam_pulse = object.__new__(BeamPulseSubsystem)
        beam_pulse.bcon_connection_status = True
        beam_pulse.beams_armed_status = True
        beam_pulse.beam_on_status = [True, False, False]
        beam_pulse._active_channels = {0}
        beam_pulse._connection_status_callback = None
        beam_pulse._update_armed_button_states = MagicMock()
        beam_pulse._notify_all_channel_enables = MagicMock()
        callback = MagicMock()
        beam_pulse.set_connection_status_callback(callback)

        beam_pulse._handle_driver_msg(("connected", False))

        callback.assert_called_once_with(False)
        self.assertEqual(beam_pulse.beam_on_status, [False, False, False])
        self.assertEqual(beam_pulse._active_channels, set())

    def test_csv_sequence_block_stops_before_bcon_sync_start(self):
        beam_pulse = object.__new__(BeamPulseSubsystem)
        beam_pulse._seq_steps = [
            (1, [{"ch": 0, "mode": "PULSE", "duration_ms": 100, "count": 1}], 0)
        ]
        beam_pulse._seq_stop = threading.Event()
        beam_pulse.beams_armed_status = True
        beam_pulse._ui_queue = queue.Queue()
        beam_pulse.bcon_driver = MagicMock()
        beam_pulse._emission_limit_checker = MagicMock(return_value=False)

        beam_pulse._sequence_worker()

        beam_pulse._emission_limit_checker.assert_called_once()
        beam_pulse.bcon_driver.sync_start.assert_not_called()
        self.assertTrue(beam_pulse._seq_stop.is_set())


if __name__ == "__main__":
    unittest.main()
