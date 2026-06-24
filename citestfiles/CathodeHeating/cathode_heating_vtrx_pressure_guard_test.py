import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from subsystem.cathode_heating.cathode_heating import CathodeHeatingSubsystem
from utils import LogLevel


class CathodeHeatingVtrxPressureGuardTest(unittest.TestCase):
    def make_subsystem(self, pressure_provider):
        subsystem = object.__new__(CathodeHeatingSubsystem)
        subsystem.power_supplies_initialized = True
        subsystem.power_supplies = [MagicMock(), MagicMock(), MagicMock()]
        subsystem.toggle_states = [False, False, False]
        subsystem.ramp_control_mode = ["current", "current", "current"]
        subsystem.disable_ccs_output_on_bcon_disconnect = True
        subsystem.bcon_is_connected = lambda: True
        subsystem.vtrx_ccs_pressure_allows_output = pressure_provider
        subsystem.log_entries = []
        subsystem.log = lambda message, level=LogLevel.INFO: subsystem.log_entries.append((message, level))
        subsystem.user_set_voltages = [10.0, 10.0, 10.0]
        subsystem.user_set_currents = [1.0, 1.0, 1.0]
        return subsystem

    def test_vtrx_pressure_guard_blocks_output_after_bcon_check_passes(self):
        subsystem = self.make_subsystem(lambda: False)

        subsystem.toggle_output(0)

        self.assertFalse(subsystem.toggle_states[0])
        subsystem.power_supplies[0].set_output.assert_not_called()
        self.assertIn(
            (
                "CCS output enable blocked for Cathode A: VTRX pressure is above 1e-5 mbar.",
                LogLevel.WARNING,
            ),
            subsystem.log_entries,
        )

    def test_vtrx_pressure_guard_failure_blocks_output(self):
        def pressure_provider():
            raise RuntimeError("no pressure")

        subsystem = self.make_subsystem(pressure_provider)

        subsystem.toggle_output(0)

        self.assertFalse(subsystem.toggle_states[0])
        subsystem.power_supplies[0].set_output.assert_not_called()
        self.assertIn(
            (
                "CCS output enable blocked for Cathode A: VTRX pressure check failed (no pressure).",
                LogLevel.WARNING,
            ),
            subsystem.log_entries,
        )


if __name__ == "__main__":
    unittest.main()
