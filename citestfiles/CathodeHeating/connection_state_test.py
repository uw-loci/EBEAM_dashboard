import inspect
import os
import sys
import threading
import unittest
from queue import Queue
from unittest.mock import MagicMock

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from subsystem.cathode_heating.cathode_heating import CathodeHeatingSubsystem
from utils import LogLevel


class TestPowerSupplyConnectionStateOwnership(unittest.TestCase):
    def setUp(self):
        self.subsys = object.__new__(CathodeHeatingSubsystem)
        self.subsys._main_thread_ident = threading.get_ident()
        self.subsys._log_queue = Queue(maxsize=1000)
        self.subsys._dropped_worker_log_count = 0
        self.subsys._dropped_worker_log_lock = threading.Lock()
        self.subsys.power_supply_readback_lock = threading.Lock()
        self.subsys.power_supply_valid_connections = [False, False, False]
        self.subsys.com_ports = {
            "CathodeA PS": "COM1",
            "CathodeB PS": "COM2",
            "CathodeC PS": "COM3",
        }
        self.subsys.disable_logging_when_ccs_power_off = False
        self.subsys.ccs_power_on_provider = None
        self.subsys.logger = MagicMock()

    def make_readback(self, voltage=None, current=None, mode=None, connected=False, error=None):
        return {
            "voltage": voltage,
            "current": current,
            "mode": mode,
            "connected": connected,
            "error": error,
            "updated_at": None,
        }

    def valid_readback(self, voltage=1.23, current=4.56, mode="CV Mode"):
        return self.make_readback(
            voltage=voltage,
            current=current,
            mode=mode,
            connected=True,
        )

    def error_readback(self, error):
        return self.make_readback(error=error)

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

    def test_connection_tracking_reset_can_clear_one_or_all_indexes(self):
        self.subsys.power_supply_valid_connections = [True, True, True]

        self.subsys._reset_power_supply_connection_tracking(1)

        self.assertEqual(self.subsys.power_supply_valid_connections, [True, False, True])

        self.subsys._reset_power_supply_connection_tracking()

        self.assertEqual(self.subsys.power_supply_valid_connections, [False, False, False])

    def test_connection_tracking_mutation_rejects_worker_thread(self):
        errors = []

        def mutate_from_worker():
            try:
                self.subsys._reset_power_supply_connection_tracking(0)
            except Exception as exc:
                errors.append(exc)

        thread = threading.Thread(target=mutate_from_worker)
        thread.start()
        thread.join()

        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], RuntimeError)
        self.assertIn("main Tk thread", str(errors[0]))

    def test_connection_tracking_mutation_rejects_missing_main_thread_marker(self):
        del self.subsys._main_thread_ident

        with self.assertRaisesRegex(RuntimeError, "main thread ownership is initialized"):
            self.subsys._reset_power_supply_connection_tracking(0)

    def test_runtime_reset_rejects_worker_thread_before_mutating_readbacks(self):
        original_readbacks = [
            self.make_readback(voltage=1.0, current=2.0, mode="CV Mode", connected=True),
            self.make_readback(error="disconnected"),
            self.make_readback(error="busy"),
        ]
        self.subsys.power_supply_readbacks = [readback.copy() for readback in original_readbacks]
        errors = []

        def reset_from_worker():
            try:
                self.subsys._reset_power_supply_runtime_state()
            except Exception as exc:
                errors.append(exc)

        thread = threading.Thread(target=reset_from_worker)
        thread.start()
        thread.join()

        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], RuntimeError)
        self.assertEqual(self.subsys.power_supply_readbacks, original_readbacks)

    def test_poller_does_not_own_valid_connection_state(self):
        source = inspect.getsource(CathodeHeatingSubsystem._power_supply_polling_loop)

        self.assertNotIn("_log_valid_power_supply_connection", source)
        self.assertNotIn("_clear_power_supply_valid_connection", source)
        self.assertNotIn("_reset_power_supply_connection_tracking", source)
        self.assertNotIn("_reset_power_supply_runtime_state", source)
        self.assertNotIn("power_supply_valid_connections", source)


if __name__ == "__main__":
    unittest.main()
