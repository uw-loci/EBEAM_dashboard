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
from instrumentctl.BCON import (
    CH_BASE,
    CH_COUNT_OFF,
    CH_PULSE_MS_OFF,
    REG_CH_STATUS_BASE,
    REG_CH_STATUS_STRIDE,
    REG_INTERLOCK_OK,
    REG_WATCHDOG_OK,
)
from instrumentctl.BCON.bcon_driver import BCONDriver
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
        self.send_channel_config = MagicMock(return_value=True)
        self.send_channel_off = MagicMock(return_value=True)
        self.get_channel_config = MagicMock(return_value={"mode": mode, "duration_ms": 100, "count": 1})
        self.get_last_send_failure_message = MagicMock(return_value="")
        self.toggle_channel_enable = MagicMock(
            return_value=(True, True, "Channel A successfully enabled")
        )
        self.sync_start = MagicMock()
        self.sync_stop_all = MagicMock()

    def get_beam_status(self, index):
        return self.statuses[index]

    def get_beams_armed_status(self):
        return True


def make_real_beam_pulse_for_send(
    mode="PULSE",
    duration="100",
    count="1",
    connected=True,
    driver=True,
    statuses=None,
    limit=6.0,
    currents=None,
):
    beam_pulse = object.__new__(BeamPulseSubsystem)
    beam_pulse.beams_armed_status = True
    beam_pulse.beam_on_status = list(statuses or [False, False, False])
    beam_pulse.channel_enable_status = [False, False, False]
    beam_pulse._active_channels = {
        index for index, is_on in enumerate(beam_pulse.beam_on_status) if is_on
    }
    beam_pulse.channel_vars = [
        {
            "mode": FakeVar(mode),
            "duration": FakeVar(duration),
            "count": FakeVar(count),
        },
        {
            "mode": FakeVar("OFF"),
            "duration": FakeVar("0"),
            "count": FakeVar("1"),
        },
        {
            "mode": FakeVar("OFF"),
            "duration": FakeVar("0"),
            "count": FakeVar("1"),
        },
    ]
    beam_pulse._dashboard_beam_callback = None
    beam_pulse._last_send_failure_message = ""
    beam_pulse._log = MagicMock()
    beam_pulse._log_event = MagicMock()
    beam_pulse.set_emission_limit_providers(
        lambda: limit,
        lambda: list(currents if currents is not None else [0.0, 0.0, 0.0]),
    )
    if driver:
        beam_pulse.bcon_driver = MagicMock()
        beam_pulse.bcon_driver.is_connected.return_value = connected
        beam_pulse.bcon_driver.set_channel_mode.return_value = True
    else:
        beam_pulse.bcon_driver = None
    return beam_pulse


def make_dashboard(limit=6.0, emission_values=None, beam_pulse=None):
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
        beam_pulse = make_real_beam_pulse_for_send(
            limit=6.0,
            currents=[2.0, 4.0, float("nan")],
        )

        allowed, message = beam_pulse._emission_limit_allows_output(
            "Test action",
            [
                {"ch": 1, "mode": "PULSE", "duration_ms": 100, "count": 1},
                {"ch": 2, "mode": "DC", "duration_ms": 0, "count": 1},
            ],
        )

        self.assertFalse(allowed)
        self.assertIn("total emission current limit exceeded", message)

    def test_beam_on_blocks_before_sending_channel_config(self):
        beam_pulse = make_real_beam_pulse_for_send(
            statuses=[False, True, False],
            limit=6.0,
            currents=[2.0, 4.0, 0.0],
        )
        dash = make_dashboard(
            limit=6.0,
            emission_values=[2.0, 4.0, 0.0],
            beam_pulse=beam_pulse,
        )

        dash.toggle_individual_beam_with_status(0)

        beam_pulse.bcon_driver.set_channel_mode.assert_not_called()
        self.assertEqual(
            dash._beam_action_status_text,
            "Failed to set Beam A ON, total emission current limit exceeded",
        )

    def test_beam_on_delegates_emission_check_to_beam_pulse(self):
        beam_pulse = FakeBeamPulse(statuses=[False, True, False], mode="PULSE")
        dash = make_dashboard(
            limit=1.0,
            emission_values=[2.0, 4.0, 0.0],
            beam_pulse=beam_pulse,
        )

        dash.toggle_individual_beam_with_status(0)

        beam_pulse.send_channel_config.assert_called_once_with(0)

    def test_beam_on_allows_off_mode_without_emission_check(self):
        beam_pulse = make_real_beam_pulse_for_send(
            mode="OFF",
            statuses=[False, True, False],
            limit=0.0,
        )
        dash = make_dashboard(
            limit=1.0,
            emission_values=[2.0, 4.0, 0.0],
            beam_pulse=beam_pulse,
        )

        dash.toggle_individual_beam_with_status(0)

        beam_pulse.bcon_driver.set_channel_mode.assert_called_once()
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

        beam_pulse.toggle_channel_enable.assert_called_once_with(0)
        dash.logger.error.assert_not_called()

    def test_sync_start_handler_calls_beam_pulse_api(self):
        beam_pulse = FakeBeamPulse(statuses=[False, False, False], mode="PULSE")
        dash = make_dashboard(beam_pulse=beam_pulse)

        dash.handle_sync_start()

        beam_pulse.sync_start.assert_called_once_with()

    def test_sync_stop_handler_calls_beam_pulse_api(self):
        beam_pulse = FakeBeamPulse(statuses=[False, False, False], mode="PULSE")
        dash = make_dashboard(beam_pulse=beam_pulse)

        dash.handle_sync_stop()

        beam_pulse.sync_stop_all.assert_called_once_with()


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
        beam_pulse = make_real_beam_pulse_for_send(
            statuses=[False, True, False],
            limit=6.0,
            currents=[2.0, 4.0, 0.0],
        )
        dash = make_dashboard(
            limit=6.0,
            emission_values=[2.0, 4.0, 0.0],
            beam_pulse=beam_pulse,
        )
        dash._on_channel_enable_status_update(0, True)

        dash.toggle_individual_beam_with_status(0)

        beam_pulse.bcon_driver.set_channel_mode.assert_not_called()
        self.assertEqual(dash._beam_output_status_text[0], "Beam A ENABLED, Output OFF")
        self.assertEqual(
            dash._beam_action_status_text,
            "Failed to set Beam A ON, total emission current limit exceeded",
        )
        self.assertEqual(dash._beam_action_status_color, "red")

    def test_invalid_pulse_train_count_updates_failure_without_marking_on(self):
        beam_pulse = make_real_beam_pulse_for_send(
            mode="PULSE_TRAIN",
            duration="100",
            count="10001",
        )
        dash = make_dashboard(limit=6.1, emission_values=[1.0, 0.0, 0.0], beam_pulse=beam_pulse)
        dash._on_channel_enable_status_update(0, True)

        with patch("subsystem.beam_pulse.beam_pulse.messagebox.showerror"):
            dash.toggle_individual_beam_with_status(0)

        beam_pulse.bcon_driver.set_channel_mode.assert_not_called()
        self.assertEqual(dash._beam_output_status_text[0], "Beam A ENABLED, Output OFF")
        self.assertEqual(dash._beam_output_status_colors[0], "gray")
        self.assertIn("Failed to send Beam A config", dash._beam_action_status_text)
        self.assertIn("10000", dash._beam_action_status_text)
        self.assertEqual(dash._beam_action_status_color, "red")

    def test_invalid_pulse_duration_updates_failure_without_marking_on(self):
        beam_pulse = make_real_beam_pulse_for_send(
            mode="PULSE",
            duration="60001",
            count="1",
        )
        dash = make_dashboard(limit=6.1, emission_values=[1.0, 0.0, 0.0], beam_pulse=beam_pulse)
        dash._on_channel_enable_status_update(0, True)

        with patch("subsystem.beam_pulse.beam_pulse.messagebox.showerror"):
            dash.toggle_individual_beam_with_status(0)

        beam_pulse.bcon_driver.set_channel_mode.assert_not_called()
        self.assertEqual(dash._beam_output_status_text[0], "Beam A ENABLED, Output OFF")
        self.assertIn("60000", dash._beam_action_status_text)
        self.assertEqual(dash._beam_action_status_color, "red")

    def test_disconnected_bcon_updates_failure_without_marking_on(self):
        beam_pulse = make_real_beam_pulse_for_send(connected=False)
        dash = make_dashboard(limit=6.1, emission_values=[1.0, 0.0, 0.0], beam_pulse=beam_pulse)
        dash._on_channel_enable_status_update(0, True)

        dash.toggle_individual_beam_with_status(0)

        beam_pulse.bcon_driver.set_channel_mode.assert_not_called()
        self.assertEqual(dash._beam_output_status_text[0], "Beam A ENABLED, Output OFF")
        self.assertIn("BCON device not connected", dash._beam_action_status_text)
        self.assertEqual(dash._beam_action_status_color, "red")

    def test_missing_bcon_driver_updates_failure_without_marking_on(self):
        beam_pulse = make_real_beam_pulse_for_send(driver=False)
        dash = make_dashboard(limit=6.1, emission_values=[1.0, 0.0, 0.0], beam_pulse=beam_pulse)
        dash._on_channel_enable_status_update(0, True)

        dash.toggle_individual_beam_with_status(0)

        self.assertEqual(dash._beam_output_status_text[0], "Beam A ENABLED, Output OFF")
        self.assertIn("BCON driver not available", dash._beam_action_status_text)
        self.assertEqual(dash._beam_action_status_color, "red")

    def test_sync_feedback_updates_multiple_beam_lines(self):
        dash = make_dashboard()

        dash._handle_action_feedback(
            "beams_sent",
            "",
            "success",
            [
                {"ch": 1, "mode": "PULSE", "duration_ms": 100, "count": 1},
                {"ch": 2, "mode": "PULSE_TRAIN", "duration_ms": 50, "count": 5},
            ],
        )

        self.assertEqual(
            dash._beam_action_status_text,
            "Sync Start: A=PULSE(100ms), B=PULSE_TRAIN(50ms x5)",
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
    def make_beam_pulse(self, limit=4.0, currents=None, active=None):
        beam_pulse = object.__new__(BeamPulseSubsystem)
        beam_pulse.beams_armed_status = True
        beam_pulse.beam_on_status = [False, False, False]
        if active:
            for index in active:
                beam_pulse.beam_on_status[index] = True
        beam_pulse._active_channels = set(active or [])
        beam_pulse.bcon_driver = MagicMock()
        beam_pulse.channel_vars = [object(), object(), object()]
        beam_pulse.channel_enable_status = [True, True, False]
        beam_pulse._emission_limit_provider = MagicMock(return_value=limit)
        beam_pulse._predicted_currents_provider = MagicMock(
            return_value=list(currents if currents is not None else [0.0, 4.0, 0.0])
        )
        beam_pulse._log_event = MagicMock()
        beam_pulse._last_send_failure_message = ""
        return beam_pulse

    def test_sync_start_blocks_before_bcon_sync_start(self):
        beam_pulse = self.make_beam_pulse()
        beam_pulse._validate_and_get_config = MagicMock(side_effect=[
            {"mode": "OFF", "duration_ms": 0, "count": 1},
            {"mode": "PULSE", "duration_ms": 100, "count": 1},
        ])

        beam_pulse.sync_start()

        beam_pulse._emission_limit_provider.assert_called_once()
        beam_pulse._predicted_currents_provider.assert_called_once()
        beam_pulse.bcon_driver.sync_start.assert_not_called()

    def test_sync_start_allows_bcon_sync_start_below_limit(self):
        beam_pulse = self.make_beam_pulse(limit=4.1)
        beam_pulse._validate_and_get_config = MagicMock(side_effect=[
            {"mode": "OFF", "duration_ms": 0, "count": 1},
            {"mode": "PULSE", "duration_ms": 100, "count": 1},
        ])

        beam_pulse.sync_start()

        beam_pulse.bcon_driver.sync_start.assert_called_once()

    def test_send_channel_config_blocks_before_bcon_write_at_limit(self):
        beam_pulse = make_real_beam_pulse_for_send(
            limit=2.0,
            currents=[2.0, 0.0, 0.0],
        )

        ok = beam_pulse.send_channel_config(0)

        self.assertFalse(ok)
        beam_pulse.bcon_driver.set_channel_mode.assert_not_called()
        self.assertEqual(
            beam_pulse.get_last_send_failure_message(),
            "Failed to set Beam A ON, total emission current limit exceeded",
        )

    def test_send_channel_config_sanitizes_bad_currents_as_zero(self):
        beam_pulse = make_real_beam_pulse_for_send(
            limit=0.1,
            currents=["--", float("nan"), "bad"],
        )

        ok = beam_pulse.send_channel_config(0)

        self.assertTrue(ok)
        beam_pulse.bcon_driver.set_channel_mode.assert_called_once()

    def test_missing_emission_providers_block_output_start(self):
        beam_pulse = make_real_beam_pulse_for_send()
        beam_pulse._emission_limit_provider = None
        beam_pulse._predicted_currents_provider = None

        ok = beam_pulse.send_channel_config(0)

        self.assertFalse(ok)
        beam_pulse.bcon_driver.set_channel_mode.assert_not_called()
        self.assertIn("provider unavailable", beam_pulse.get_last_send_failure_message())

    def test_provider_exception_blocks_output_start(self):
        beam_pulse = make_real_beam_pulse_for_send()
        beam_pulse._predicted_currents_provider = MagicMock(side_effect=RuntimeError("offline"))

        ok = beam_pulse.send_channel_config(0)

        self.assertFalse(ok)
        beam_pulse.bcon_driver.set_channel_mode.assert_not_called()
        self.assertIn("provider failed", beam_pulse.get_last_send_failure_message())

    def test_existing_active_channels_are_counted_for_single_beam_on(self):
        beam_pulse = make_real_beam_pulse_for_send(
            statuses=[False, True, False],
            limit=6.0,
            currents=[2.0, 4.0, 0.0],
        )

        ok = beam_pulse.send_channel_config(0)

        self.assertFalse(ok)
        beam_pulse.bcon_driver.set_channel_mode.assert_not_called()

    def test_existing_active_channels_are_counted_for_sync_start(self):
        beam_pulse = self.make_beam_pulse(
            limit=6.0,
            currents=[2.0, 4.0, 0.0],
            active=[1],
        )
        beam_pulse.channel_enable_status = [True, False, False]
        beam_pulse._validate_and_get_config = MagicMock(return_value={
            "mode": "PULSE",
            "duration_ms": 100,
            "count": 1,
        })

        beam_pulse.sync_start()

        beam_pulse.bcon_driver.sync_start.assert_not_called()

    def test_off_configs_remove_active_channels_from_projection(self):
        beam_pulse = self.make_beam_pulse(
            limit=2.0,
            currents=[4.0, 0.0, 1.0],
            active=[0],
        )

        allowed, message = beam_pulse._emission_limit_allows_output(
            "Sync Start",
            [
                {"ch": 1, "mode": "OFF", "duration_ms": 0, "count": 1},
                {"ch": 3, "mode": "PULSE", "duration_ms": 100, "count": 1},
            ],
        )

        self.assertTrue(allowed)
        self.assertIsNone(message)

    def test_sync_start_feedback_after_bcon_sync_start(self):
        beam_pulse = self.make_beam_pulse(limit=10.0, currents=[1.0, 2.0, 0.0])
        feedback = MagicMock()
        beam_pulse.set_action_feedback_callback(feedback)
        beam_pulse._validate_and_get_config = MagicMock(side_effect=[
            {"mode": "PULSE", "duration_ms": 100, "count": 1},
            {"mode": "PULSE_TRAIN", "duration_ms": 50, "count": 5},
        ])

        beam_pulse.sync_start()

        beam_pulse.bcon_driver.sync_start.assert_called_once()
        feedback.assert_called_once()
        event_type, message, outcome, configs = feedback.call_args.args
        self.assertEqual(event_type, "beams_sent")
        self.assertEqual(outcome, "success")
        self.assertEqual(message, "")
        self.assertEqual(configs[0]["mode"], "PULSE")
        self.assertEqual(configs[1]["count"], 5)

    def test_sync_start_invalid_count_feedback_before_bcon_sync_start(self):
        beam_pulse = self.make_beam_pulse()
        feedback = MagicMock()
        beam_pulse.set_action_feedback_callback(feedback)
        beam_pulse.channel_vars = [
            {"mode": FakeVar("PULSE_TRAIN"), "duration": FakeVar("100"), "count": FakeVar("10001")},
            {"mode": FakeVar("OFF"), "duration": FakeVar("0"), "count": FakeVar("1")},
            {"mode": FakeVar("OFF"), "duration": FakeVar("0"), "count": FakeVar("1")},
        ]

        with patch("subsystem.beam_pulse.beam_pulse.messagebox.showerror"):
            beam_pulse.sync_start()

        beam_pulse.bcon_driver.sync_start.assert_not_called()
        feedback.assert_called_once()
        event_type, message, outcome, configs = feedback.call_args.args
        self.assertEqual(event_type, "status")
        self.assertEqual(outcome, "failure")
        self.assertIn("Failed to sync start", message)
        self.assertIn("10000", message)
        self.assertIsNone(configs)

    def test_sync_start_invalid_duration_feedback_before_bcon_sync_start(self):
        beam_pulse = self.make_beam_pulse()
        feedback = MagicMock()
        beam_pulse.set_action_feedback_callback(feedback)
        beam_pulse.channel_vars = [
            {"mode": FakeVar("PULSE"), "duration": FakeVar("60001"), "count": FakeVar("1")},
            {"mode": FakeVar("OFF"), "duration": FakeVar("0"), "count": FakeVar("1")},
            {"mode": FakeVar("OFF"), "duration": FakeVar("0"), "count": FakeVar("1")},
        ]

        with patch("subsystem.beam_pulse.beam_pulse.messagebox.showerror"):
            beam_pulse.sync_start()

        beam_pulse.bcon_driver.sync_start.assert_not_called()
        feedback.assert_called_once()
        self.assertEqual(feedback.call_args.args[2], "failure")
        self.assertIn("60000", feedback.call_args.args[1])

    def test_firmware_rejection_updates_action_feedback(self):
        beam_pulse = self.make_beam_pulse()
        feedback = MagicMock()
        beam_pulse.set_action_feedback_callback(feedback)

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

    def test_register_update_sets_beam_pulse_output_state(self):
        beam_pulse = object.__new__(BeamPulseSubsystem)
        beam_pulse.channel_vars = [
            {
                "status": MagicMock(),
                "pulses": MagicMock(),
                "duration": FakeVar("0"),
                "count": FakeVar("0"),
                "mode": FakeVar("PULSE"),
            },
            {
                "status": MagicMock(),
                "pulses": MagicMock(),
                "duration": FakeVar("0"),
                "count": FakeVar("0"),
                "mode": FakeVar("OFF"),
            },
            {
                "status": MagicMock(),
                "pulses": MagicMock(),
                "duration": FakeVar("0"),
                "count": FakeVar("0"),
                "mode": FakeVar("OFF"),
            },
        ]
        beam_pulse.beam_on_status = [False, False, False]
        beam_pulse.channel_enable_status = [False, False, False]
        beam_pulse._active_channels = set()
        beam_pulse._channel_status_callback = None
        beam_pulse._channel_enable_status_callback = None
        beam_pulse._set_manual_channel_lock = MagicMock()
        beam_pulse._safe_fill = MagicMock()
        beam_pulse.update_pulser_status_display = MagicMock()
        beam_pulse.MODE_OFF = BeamPulseSubsystem.MODE_OFF
        beam_pulse.MODE_DC = BeamPulseSubsystem.MODE_DC

        regs = [0] * 300
        regs[REG_CH_STATUS_BASE] = BeamPulseSubsystem.MODE_PULSE
        regs[REG_CH_STATUS_BASE + 3] = 1
        regs[REG_CH_STATUS_BASE + 4] = 1
        regs[REG_CH_STATUS_BASE + 8] = 1
        regs[CH_BASE[0] + CH_PULSE_MS_OFF] = 100
        regs[CH_BASE[0] + CH_COUNT_OFF] = 1
        regs[REG_INTERLOCK_OK] = 1
        regs[REG_WATCHDOG_OK] = 1

        beam_pulse._update_ui_from_registers(regs)

        self.assertTrue(beam_pulse.beam_on_status[0])
        self.assertTrue(beam_pulse.channel_enable_status[0])

    def test_beam_pulse_toggle_channel_enable_owns_bcon_write(self):
        beam_pulse = object.__new__(BeamPulseSubsystem)
        beam_pulse.beams_armed_status = True
        beam_pulse.channel_enable_status = [False, False, False]
        beam_pulse.bcon_driver = FakeBCON(enabled=False)
        beam_pulse._channel_enable_status_callback = MagicMock()
        beam_pulse._log_event = MagicMock()

        ok, enabled, _detail = beam_pulse.toggle_channel_enable(0)

        self.assertTrue(ok)
        self.assertTrue(enabled)
        beam_pulse.bcon_driver.set_channel_enable.assert_called_once_with(1, True)
        self.assertTrue(beam_pulse.channel_enable_status[0])
        beam_pulse._channel_enable_status_callback.assert_called_once_with(0, True)

    def test_csv_sequence_block_stops_before_bcon_sync_start(self):
        beam_pulse = object.__new__(BeamPulseSubsystem)
        beam_pulse._seq_steps = [
            (1, [{"ch": 0, "mode": "PULSE", "duration_ms": 100, "count": 1}], 0)
        ]
        beam_pulse._seq_stop = threading.Event()
        beam_pulse.beams_armed_status = True
        beam_pulse.beam_on_status = [False, False, False]
        beam_pulse._active_channels = set()
        beam_pulse._ui_queue = queue.Queue()
        beam_pulse.bcon_driver = MagicMock()
        beam_pulse._emission_limit_provider = MagicMock(return_value=2.0)
        beam_pulse._predicted_currents_provider = MagicMock(return_value=[2.0, 0.0, 0.0])
        beam_pulse._log_event = MagicMock()
        beam_pulse._last_send_failure_message = ""

        beam_pulse._sequence_worker()

        beam_pulse._emission_limit_provider.assert_called_once()
        beam_pulse._predicted_currents_provider.assert_called_once()
        beam_pulse.bcon_driver.sync_start.assert_not_called()
        self.assertTrue(beam_pulse._seq_stop.is_set())

    def test_csv_sequence_counts_existing_active_channels(self):
        beam_pulse = object.__new__(BeamPulseSubsystem)
        beam_pulse._seq_steps = [
            (1, [{"ch": 0, "mode": "PULSE", "duration_ms": 100, "count": 1}], 0)
        ]
        beam_pulse._seq_stop = threading.Event()
        beam_pulse.beams_armed_status = True
        beam_pulse.beam_on_status = [False, True, False]
        beam_pulse._active_channels = {1}
        beam_pulse._ui_queue = queue.Queue()
        beam_pulse.bcon_driver = MagicMock()
        beam_pulse._emission_limit_provider = MagicMock(return_value=6.0)
        beam_pulse._predicted_currents_provider = MagicMock(return_value=[2.0, 4.0, 0.0])
        beam_pulse._log_event = MagicMock()
        beam_pulse._last_send_failure_message = ""

        beam_pulse._sequence_worker()

        beam_pulse.bcon_driver.sync_start.assert_not_called()
        self.assertTrue(beam_pulse._seq_stop.is_set())

    def test_csv_sequence_invalid_count_stops_before_bcon_sync_start(self):
        beam_pulse = object.__new__(BeamPulseSubsystem)
        beam_pulse._seq_steps = [
            (1, [{"ch": 0, "mode": "PULSE_TRAIN", "duration_ms": 100, "count": 10001}], 0)
        ]
        beam_pulse._seq_stop = threading.Event()
        beam_pulse.beams_armed_status = True
        beam_pulse.beam_on_status = [False, False, False]
        beam_pulse._active_channels = set()
        beam_pulse._ui_queue = queue.Queue()
        beam_pulse.bcon_driver = MagicMock()
        beam_pulse._emission_limit_provider = MagicMock(return_value=10.0)
        beam_pulse._predicted_currents_provider = MagicMock(return_value=[1.0, 0.0, 0.0])
        beam_pulse._log_event = MagicMock()
        beam_pulse._last_send_failure_message = ""

        beam_pulse._sequence_worker()

        beam_pulse._emission_limit_provider.assert_not_called()
        beam_pulse._predicted_currents_provider.assert_not_called()
        beam_pulse.bcon_driver.sync_start.assert_not_called()
        self.assertTrue(beam_pulse._seq_stop.is_set())
        messages = list(beam_pulse._ui_queue.queue)
        feedback = [msg for msg in messages if msg[0] == "action_feedback"]
        self.assertEqual(feedback[0][1], "status")
        self.assertEqual(feedback[0][3], "failure")
        self.assertIn("10000", feedback[0][2])

    def test_load_sequence_rejects_invalid_count_before_accepting_file(self):
        beam_pulse = object.__new__(BeamPulseSubsystem)
        beam_pulse._seq_steps = []
        beam_pulse._log_event = MagicMock()
        beam_pulse._last_send_failure_message = ""
        fd, path = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        try:
            with open(path, "w") as file:
                file.write("step,ch,mode,duration_ms,count,dwell_ms\n")
                file.write("1,1,PULSE_TRAIN,100,10001,0\n")

            with patch("subsystem.beam_pulse.beam_pulse.filedialog.askopenfilename", return_value=path), \
                    patch("subsystem.beam_pulse.beam_pulse.messagebox.showerror") as showerror:
                beam_pulse._load_sequence()
        finally:
            os.remove(path)

        self.assertEqual(beam_pulse._seq_steps, [])
        showerror.assert_called_once()
        self.assertIn("10000", showerror.call_args.args[1])


class TestBCONPulseValidation(unittest.TestCase):
    def make_driver(self):
        driver = object.__new__(BCONDriver)
        driver._log = MagicMock()
        return driver

    def test_invalid_pulse_count_returns_false(self):
        driver = self.make_driver()

        self.assertFalse(driver.set_channel_pulse_train(1, 100, 10001))

    def test_invalid_pulse_duration_returns_false(self):
        driver = self.make_driver()

        self.assertFalse(driver.set_channel_pulse(1, 60001))


if __name__ == "__main__":
    unittest.main()
