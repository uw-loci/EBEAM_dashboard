"""Tests for the threaded MKS 902B serial driver."""

import os
import queue
import sys
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from instrumentctl.mks_902b import mks_902b_driver as driver_module
from utils import LogLevel


class ScriptedSerial:
    """Provide deterministic command responses while recording serial thread use."""

    def __init__(self, responses=None, response_factory=None, max_chunk=None):
        """Initialize a fake open serial connection."""
        self.responses = list(responses or [])
        self.response_factory = response_factory
        self.max_chunk = max_chunk
        self.is_open = True
        self.writes = []
        self.pending = bytearray()
        self.thread_ids = {threading.get_ident()}
        self.open_thread_id = threading.get_ident()
        self.close_thread_id = None
        self.flush_calls = 0

    @property
    def in_waiting(self):
        """Return the number of response bytes ready to read."""
        return len(self.pending)

    def write(self, data):
        """Record a command and queue its scripted response."""
        self.thread_ids.add(threading.get_ident())
        command = data.decode("ascii").strip()
        self.writes.append(command)
        if self.response_factory is not None:
            response = self.response_factory(command)
        elif self.responses:
            response = self.responses.pop(0)
        else:
            response = None
        if response is not None:
            self.pending.extend(response.encode("ascii") if isinstance(response, str) else response)
        return len(data)

    def flush(self):
        """Record that flushing occurred on the serial-owner thread."""
        self.thread_ids.add(threading.get_ident())
        self.flush_calls += 1

    def read(self, size):
        """Return the next response chunk."""
        self.thread_ids.add(threading.get_ident())
        if not self.pending:
            time.sleep(0.001)
            return b""
        if self.max_chunk is not None:
            size = min(size, self.max_chunk)
        chunk = bytes(self.pending[:size])
        del self.pending[:size]
        return chunk

    def close(self):
        """Record closure and mark the fake connection closed."""
        self.thread_ids.add(threading.get_ident())
        self.close_thread_id = threading.get_ident()
        self.is_open = False


class TestMKS902BProtocol(unittest.TestCase):
    """Validate protocol parsing, initialization, conversion, and retry behavior."""

    def test_parse_response_returns_envelope_fields(self):
        """Parse a documented ACK response."""
        self.assertEqual(
            driver_module.parse_response("@253ACK1.234E-3;FF"),
            (253, "ACK", "1.234E-3"),
        )

    def test_unit_conversion_returns_mbar(self):
        """Convert every supported configured unit to mbar."""
        self.assertAlmostEqual(driver_module.convert_pressure_to_mbar(1.0, "MBAR"), 1.0)
        self.assertAlmostEqual(
            driver_module.convert_pressure_to_mbar(1.0, "TORR"),
            1.333223684,
        )
        self.assertAlmostEqual(driver_module.convert_pressure_to_mbar(100.0, "PASCAL"), 1.0)

    def test_framer_preserves_concatenated_frames(self):
        """Extract split protocol frames without relying on newlines."""
        driver = driver_module.MKS902BDriver("COM9")
        driver._receive_buffer.extend(
            b"garbage@253ACK1.000E0;FF\r\n@253ACK2.000E0;FF"
        )

        self.assertEqual(driver._extract_frame(), b"@253ACK1.000E0;FF")
        self.assertEqual(driver._extract_frame(), b"@253ACK2.000E0;FF")

    def test_incomplete_response_bytes_are_logged_before_timeout(self):
        """Log received bytes even when they never form a complete response frame."""
        driver = driver_module.MKS902BDriver("COM9")
        driver._serial = ScriptedSerial(responses=[b"@253ACK1.234E0"])

        with (
            patch.object(driver_module, "RESPONSE_TIMEOUT_SECONDS", 0.01),
            self.assertRaises(driver_module.MKS902BTimeoutError),
        ):
            driver._request("@253PR4?;FF", expected_address=253)

        self.assertIn(
            ("RX b'@253ACK1.234E0'", LogLevel.VERBOSE),
            list(driver._log_queue.queue),
        )

    def test_initialization_discovers_address_and_queries_read_only_metadata(self):
        """Use broadcast only for discovery and never send a setting command."""
        driver = driver_module.MKS902BDriver("COM9")
        driver._serial = ScriptedSerial(
            responses=[
                "@247ACK902B;FF",
                "@247ACK9600;FF",
                "@247ACKTORR;FF",
            ],
            max_chunk=3,
        )

        driver._initialize_transducer()

        self.assertEqual(driver._address, 247)
        self.assertEqual(driver._pressure_unit, "TORR")
        self.assertEqual(
            driver._serial.writes,
            ["@254MD?;FF", "@247BR?;FF", "@247U?;FF"],
        )
        self.assertEqual(driver._serial.flush_calls, 0)
        self.assertTrue(all("!" not in command for command in driver._serial.writes))
        queued_logs = list(driver._log_queue.queue)
        self.assertIn(
            (
                "902B pressure unit: TORR; dashboard will convert TORR to mbar",
                LogLevel.INFO,
            ),
            queued_logs,
        )

    def test_poll_retries_three_total_attempts_and_publishes_only_success(self):
        """Retry twice after failures and publish the third valid PR4 reply."""
        response_count = 0

        def respond(_command):
            """Return two NAK replies followed by a valid pressure reply."""
            nonlocal response_count
            response_count += 1
            if response_count < 3:
                return "@253NAK160;FF"
            return "@253ACK1.234E0;FF"

        driver = driver_module.MKS902BDriver("COM9")
        driver._serial = ScriptedSerial(response_factory=respond)
        driver._address = 253
        driver._pressure_unit = "MBAR"

        with patch.object(driver_module, "POLL_RETRY_DELAY_SECONDS", 0):
            self.assertTrue(driver._poll_pressure())

        self.assertEqual(response_count, 3)
        timestamp, pressure_mbar = driver.data_queue.get_nowait()
        self.assertLessEqual(timestamp, time.time())
        self.assertAlmostEqual(pressure_mbar, 1.234)
        debug_logs = [
            message
            for message, level in list(driver._log_queue.queue)
            if level == LogLevel.DEBUG and message.startswith("PR4 attempt")
        ]
        self.assertEqual(len(debug_logs), 2)

    def test_failed_poll_group_logs_each_attempt_without_publishing_data(self):
        """Log three request failures and one summary while leaving data empty."""
        driver = driver_module.MKS902BDriver("COM9")
        driver._serial = ScriptedSerial(response_factory=lambda _command: "@253NAK160;FF")
        driver._address = 253
        driver._pressure_unit = "MBAR"

        with patch.object(driver_module, "POLL_RETRY_DELAY_SECONDS", 0):
            self.assertFalse(driver._poll_pressure())

        self.assertTrue(driver.data_queue.empty())
        queued_logs = list(driver._log_queue.queue)
        debug_logs = [level for message, level in queued_logs if message.startswith("PR4 attempt")]
        error_logs = [
            message
            for message, level in queued_logs
            if level == LogLevel.ERROR and "failed after 3 attempts" in message
        ]
        self.assertEqual(debug_logs, [LogLevel.DEBUG] * 3)
        self.assertEqual(len(error_logs), 1)

    def test_bounded_data_queue_discards_oldest_measurement(self):
        """Keep recent measurements when the UI consumer falls behind."""
        driver = driver_module.MKS902BDriver("COM9")
        for value in range(driver_module.DATA_QUEUE_MAXSIZE + 1):
            driver._put_latest_data((float(value), float(value)))

        timestamps = []
        while not driver.data_queue.empty():
            timestamps.append(driver.data_queue.get_nowait()[0])
        self.assertEqual(timestamps[0], 1.0)
        self.assertEqual(timestamps[-1], float(driver_module.DATA_QUEUE_MAXSIZE))


class TestMKS902BWorker(unittest.TestCase):
    """Validate worker lifecycle and serial ownership."""

    def test_worker_is_sole_serial_owner(self):
        """Open, read, write, and close the serial connection on one worker thread."""
        serial_instances = []

        def respond(command):
            """Return a valid response for every driver command."""
            responses = {
                "@254MD?;FF": "@253ACK902B;FF",
                "@253BR?;FF": "@253ACK9600;FF",
                "@253U?;FF": "@253ACKMBAR;FF",
                "@253PR4?;FF": "@253ACK1.234E0;FF",
            }
            return responses[command]

        def serial_factory(**_kwargs):
            """Create a fake connection in whichever thread opens the port."""
            serial_connection = ScriptedSerial(response_factory=respond)
            serial_instances.append(serial_connection)
            return serial_connection

        main_thread_id = threading.get_ident()
        driver = driver_module.MKS902BDriver("COM9", logger=MagicMock())
        with (
            patch.object(driver_module.serial, "Serial", side_effect=serial_factory),
            patch.object(driver_module, "POLL_INTERVAL_SECONDS", 0.01),
            patch.object(driver_module, "THREAD_JOIN_TIMEOUT_SECONDS", 1.0),
        ):
            driver.start()
            driver.data_queue.get(timeout=1.0)
            driver.close()

        self.assertEqual(len(serial_instances), 1)
        serial_connection = serial_instances[0]
        self.assertNotEqual(serial_connection.open_thread_id, main_thread_id)
        self.assertEqual(serial_connection.close_thread_id, serial_connection.open_thread_id)
        self.assertEqual(serial_connection.thread_ids, {serial_connection.open_thread_id})

    def test_flush_queued_logs_uses_902b_tag(self):
        """Forward severity and message through the timestamping central logger."""
        logger = MagicMock()
        driver = driver_module.MKS902BDriver("COM9", logger=logger)
        driver._queue_log("unit test message", LogLevel.INFO)

        driver.flush_queued_logs()

        logger.log.assert_called_once_with(
            "unit test message",
            LogLevel.INFO,
            tag="902B",
        )


if __name__ == "__main__":
    unittest.main()
