import inspect
import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from subsystem.cathode_heating.cathode_heating import CathodeHeatingSubsystem
from utils import LogLevel


class TestPowerSupplyConnectionStateOwnership(unittest.TestCase):
    def setUp(self):
        self.subsys = object.__new__(CathodeHeatingSubsystem)
        self.subsys.power_supply_valid_connections = [False, False, False]
        self.subsys.com_ports = {
            "CathodeA PS": "COM1",
            "CathodeB PS": "COM2",
            "CathodeC PS": "COM3",
        }
        self.subsys.disable_logging_when_ccs_power_off = False
        self.subsys.ccs_power_on_provider = None
        self.subsys.logger = MagicMock()

    def valid_readback(self, voltage=1.23, current=4.56, mode="CV Mode"):
        return {
            "voltage": voltage,
            "current": current,
            "mode": mode,
            "connected": True,
            "error": None,
            "updated_at": None,
        }

    def error_readback(self, error):
        return {
            "voltage": None,
            "current": None,
            "mode": None,
            "connected": False,
            "error": error,
            "updated_at": None,
        }

    def test_valid_readback_logs_once_and_marks_connection_valid(self):
        self.subsys._update_power_supply_connection_state_from_readback(0, self.valid_readback())

        self.assertTrue(self.subsys.power_supply_valid_connections[0])
        self.subsys.logger.log.assert_called_once()
        message, level = self.subsys.logger.log.call_args.args[:2]
        self.assertIn("Cathode A", message)
        self.assertEqual(level, LogLevel.INFO)
        self.assertEqual(self.subsys.logger.log.call_args.kwargs["tag"], "CCS")

    def test_repeated_valid_readbacks_do_not_log_again(self):
        self.subsys._update_power_supply_connection_state_from_readback(0, self.valid_readback())
        self.subsys._update_power_supply_connection_state_from_readback(0, self.valid_readback())

        self.assertTrue(self.subsys.power_supply_valid_connections[0])
        self.subsys.logger.log.assert_called_once()

    def test_busy_readback_preserves_existing_valid_connection(self):
        self.subsys._update_power_supply_connection_state_from_readback(0, self.valid_readback())
        self.subsys.logger.reset_mock()

        self.subsys._update_power_supply_connection_state_from_readback(0, self.error_readback("busy"))

        self.assertTrue(self.subsys.power_supply_valid_connections[0])
        self.subsys.logger.log.assert_not_called()

    def test_unavailable_readbacks_clear_existing_valid_connection(self):
        for error in ["disconnected", "invalid_read", "not_initialized", "SerialException: boom"]:
            with self.subTest(error=error):
                self.subsys.power_supply_valid_connections = [True, False, False]

                self.subsys._update_power_supply_connection_state_from_readback(
                    0,
                    self.error_readback(error),
                )

                self.assertFalse(self.subsys.power_supply_valid_connections[0])

    def test_recovered_valid_readback_logs_after_cleared_state(self):
        self.subsys._update_power_supply_connection_state_from_readback(0, self.valid_readback())
        self.subsys._update_power_supply_connection_state_from_readback(
            0,
            self.error_readback("disconnected"),
        )
        self.subsys._update_power_supply_connection_state_from_readback(0, self.valid_readback())

        self.assertTrue(self.subsys.power_supply_valid_connections[0])
        self.assertEqual(self.subsys.logger.log.call_count, 2)

    def test_poller_does_not_own_valid_connection_state(self):
        source = inspect.getsource(CathodeHeatingSubsystem._power_supply_polling_loop)

        self.assertNotIn("_log_valid_power_supply_connection", source)
        self.assertNotIn("_clear_power_supply_valid_connection", source)


if __name__ == "__main__":
    unittest.main()
