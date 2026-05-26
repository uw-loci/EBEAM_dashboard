import os
import queue
import shutil
import tempfile
import threading
import unittest
from unittest.mock import MagicMock

from dashboard import EBEAMSystemDashboard
from subsystem.cathode_heating.cathode_heating import CathodeHeatingSubsystem
from subsystem.beam_pulse.beam_pulse import BeamPulseSubsystem
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

    def config(self, **kwargs):
        self.config_calls.append(kwargs)


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


def make_dashboard(limit=6.0, emission_values=None, beam_pulse=None):
    dash = object.__new__(EBEAMSystemDashboard)
    dash.logger = MagicMock()
    dash.total_max_emission_current_ma = limit
    dash.total_max_emission_current_value_var = FakeVar("")
    dash.beam_toggle_buttons = [FakeButton(), FakeButton(), FakeButton()]
    dash.enable_toggle_buttons = [FakeButton(), FakeButton(), FakeButton()]
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
