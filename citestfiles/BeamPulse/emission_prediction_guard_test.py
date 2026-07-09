import math
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from subsystem.beam_pulse.beam_pulse import BeamPulseSubsystem
from utils import LogLevel


class DummyBCONDriver:
    def __init__(self, enabled=False):
        self.enabled = bool(enabled)
        self.enable_calls = []
        self.off_calls = []

    def is_connected(self):
        return True

    def is_channel_enabled(self, channel):
        return self.enabled

    def set_channel_enable(self, channel, enabled):
        self.enable_calls.append((channel, enabled))
        self.enabled = bool(enabled)
        return True

    def set_channel_off(self, channel):
        self.off_calls.append(channel)
        return True


class BeamPulseEmissionPredictionGuardTest(unittest.TestCase):
    def make_subsystem(self, currents, limit=5.0, limit_enabled=True):
        subsystem = object.__new__(BeamPulseSubsystem)
        subsystem.beams_armed_status = True
        subsystem.beam_on_status = [False, False, False]
        subsystem.channel_enable_status = [False, False, False]
        subsystem._active_channels = set()
        subsystem._emission_limit_provider = lambda: limit
        subsystem._predicted_currents_provider = lambda: currents
        subsystem._emission_limit_enabled_provider = lambda: limit_enabled
        subsystem._vtrx_pressure_guard_enabled_provider = None
        subsystem._vtrx_pressure_provider = None
        subsystem._vtrx_pressure_limit_provider = None
        subsystem._vtrx_pressure_fresh_provider = None
        subsystem._channel_enable_status_callback = None
        subsystem.log_entries = []
        subsystem._log_event = lambda message, level=LogLevel.INFO: subsystem.log_entries.append(
            (message, level)
        )
        subsystem._log_once = subsystem._log_event
        return subsystem

    def set_unsafe_vtrx_pressure(self, subsystem):
        subsystem._vtrx_pressure_guard_enabled_provider = lambda: True
        subsystem._vtrx_pressure_provider = lambda: 2e-5
        subsystem._vtrx_pressure_limit_provider = lambda: 1e-5
        subsystem._vtrx_pressure_fresh_provider = lambda: True

    def assert_allows(self, subsystem, configs):
        allowed, message = subsystem._beam_checks_allow_output("Beam A ON", configs)
        self.assertTrue(allowed)
        self.assertIsNone(message)

    def assert_blocks_with(self, subsystem, configs, expected_text):
        allowed, message = subsystem._beam_checks_allow_output("Beam A ON", configs)
        self.assertFalse(allowed)
        self.assertIn(expected_text, message)

    def test_valid_projected_prediction_below_limit_allows_output(self):
        subsystem = self.make_subsystem([1.0, None, None], limit=5.0)

        self.assert_allows(subsystem, [{"ch": 1, "mode": "DC"}])

    def test_real_zero_prediction_allows_output(self):
        subsystem = self.make_subsystem([0.0, None, None], limit=5.0)

        self.assert_allows(subsystem, [{"ch": 1, "mode": "DC"}])

    def test_unknown_projected_prediction_blocks_output(self):
        subsystem = self.make_subsystem([None, 1.0, 1.0], limit=5.0)

        self.assert_blocks_with(
            subsystem,
            [{"ch": 1, "mode": "DC"}],
            "predicted emission current unavailable for A",
        )

    def test_unknown_non_projected_prediction_does_not_block_output(self):
        subsystem = self.make_subsystem([1.0, None, None], limit=5.0)

        self.assert_allows(subsystem, [{"ch": 1, "mode": "DC"}])

    def test_missing_projected_prediction_blocks_output(self):
        subsystem = self.make_subsystem([1.0], limit=5.0)

        allowed, message = subsystem._beam_checks_allow_output(
            "Beam B ON",
            [{"ch": 2, "mode": "DC"}],
        )

        self.assertFalse(allowed)
        self.assertIn("predicted emission current unavailable for B", message)

    def test_invalid_projected_predictions_block_output(self):
        invalid_values = ["bad", math.nan, math.inf, -0.1]
        for value in invalid_values:
            with self.subTest(value=value):
                subsystem = self.make_subsystem([value, 0.0, 0.0], limit=5.0)

                self.assert_blocks_with(
                    subsystem,
                    [{"ch": 1, "mode": "DC"}],
                    "predicted emission current unavailable for A",
                )

    def test_projected_total_at_or_above_limit_blocks_output(self):
        subsystem = self.make_subsystem([3.0, 2.0, None], limit=5.0)
        subsystem.beam_on_status = [False, True, False]

        self.assert_blocks_with(
            subsystem,
            [{"ch": 1, "mode": "DC"}],
            "total emission current limit exceeded",
        )

    def test_limit_disabled_allows_unknown_projected_prediction(self):
        subsystem = self.make_subsystem([None, 0.0, 0.0], limit=5.0, limit_enabled=False)

        self.assert_allows(subsystem, [{"ch": 1, "mode": "DC"}])

    def test_limit_disabled_skips_prediction_and_threshold_providers(self):
        def fail_if_called():
            raise AssertionError("provider should not be called")

        subsystem = self.make_subsystem([], limit_enabled=False)
        subsystem._predicted_currents_provider = fail_if_called
        subsystem._emission_limit_provider = fail_if_called

        self.assert_allows(subsystem, [{"ch": 1, "mode": "DC"}])

    def test_machine_status_guard_ignores_vtrx_pressure_guard(self):
        subsystem = self.make_subsystem([1.0, 0.0, 0.0], limit=5.0)
        subsystem.channel_enable_status = [True, False, False]
        subsystem._vtrx_pressure_guard_enabled_provider = lambda: True
        subsystem._vtrx_pressure_provider = lambda: 2e-5
        subsystem._vtrx_pressure_limit_provider = lambda: 1e-5
        subsystem._vtrx_pressure_fresh_provider = lambda: False

        self.assertTrue(subsystem._activate_enabled_beams_guard_clear())

    def test_machine_status_guard_allows_output_when_emission_limit_disabled(self):
        def fail_if_called():
            raise AssertionError("provider should not be called")

        subsystem = self.make_subsystem([], limit_enabled=False)
        subsystem.channel_enable_status = [True, False, False]
        subsystem._predicted_currents_provider = fail_if_called
        subsystem._emission_limit_provider = fail_if_called

        self.assertTrue(subsystem._activate_enabled_beams_guard_clear())

    def test_channel_enable_is_blocked_by_vtrx_pressure_guard(self):
        subsystem = self.make_subsystem([1.0, 0.0, 0.0], limit=5.0)
        self.set_unsafe_vtrx_pressure(subsystem)
        driver = DummyBCONDriver(enabled=False)
        subsystem.bcon_driver = driver

        ok, enabled, message = subsystem.toggle_channel_enable(0)

        self.assertFalse(ok)
        self.assertFalse(enabled)
        self.assertIn("VTRX pressure", message)
        self.assertEqual([], driver.enable_calls)

    def test_channel_disable_is_not_blocked_by_vtrx_pressure_guard(self):
        subsystem = self.make_subsystem([1.0, 0.0, 0.0], limit=5.0)
        self.set_unsafe_vtrx_pressure(subsystem)
        subsystem.channel_enable_status = [True, False, False]
        subsystem.beam_on_status = [True, False, False]
        driver = DummyBCONDriver(enabled=True)
        subsystem.bcon_driver = driver

        ok, enabled, message = subsystem.toggle_channel_enable(0)

        self.assertTrue(ok)
        self.assertFalse(enabled)
        self.assertIn("successfully disabled", message)
        self.assertEqual([(1, False)], driver.enable_calls)
        self.assertEqual([1], driver.off_calls)


if __name__ == "__main__":
    unittest.main()
