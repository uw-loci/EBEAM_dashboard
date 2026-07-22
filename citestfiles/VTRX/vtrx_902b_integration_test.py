"""Tests for 902B measurement consumption in the VTRX dashboard pane."""

import os
import queue
import sys
import threading
import unittest
from unittest.mock import MagicMock, patch

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from subsystem.vtrx.vtrx import VTRXSubsystem


class FakeLabel:
    """Record Tk label configuration without creating a GUI."""

    def __init__(self):
        """Initialize an empty configuration snapshot."""
        self.options = {}

    def config(self, **options):
        """Store the newest widget options."""
        self.options.update(options)


def make_vtrx_consumer():
    """Build only the VTRX state needed by the 902B queue consumer."""
    subsystem = VTRXSubsystem.__new__(VTRXSubsystem)
    subsystem.mks_902b_driver = MagicMock()
    subsystem.mks_902b_driver.data_queue = queue.Queue()
    subsystem.label_902b_pressure = FakeLabel()
    subsystem.logger = MagicMock()
    subsystem.latest_902b_pressure_mbar = None
    subsystem.last_valid_902b_timestamp = None
    subsystem._902b_webmonitor_cleared = True
    subsystem.stop_event = threading.Event()
    subsystem._background_log_queue = queue.SimpleQueue()
    subsystem._main_thread_id = threading.get_ident()
    subsystem.ser = None
    return subsystem


class TestVTRX902BConsumer(unittest.TestCase):
    """Validate latest-value display, publishing, and stale clearing."""

    def test_newest_measurement_updates_display_and_webmonitor(self):
        """Drain accumulated measurements and publish only the newest one."""
        subsystem = make_vtrx_consumer()
        subsystem.mks_902b_driver.data_queue.put((999.0, 2.0e-3))
        subsystem.mks_902b_driver.data_queue.put((1000.0, 1.234e-3))

        with patch("subsystem.vtrx.vtrx.time.time", return_value=1000.5):
            subsystem._process_902b_data()

        self.assertEqual(subsystem.latest_902b_pressure_mbar, 1.234e-3)
        self.assertEqual(subsystem.last_valid_902b_timestamp, 1000.0)
        self.assertEqual(subsystem.label_902b_pressure.options["text"], "1.234E-03 mbar")
        subsystem.logger.update_field.assert_called_once_with(
            "pressure_902b_mbar",
            1.234e-3,
        )
        subsystem.logger.clear_value.assert_not_called()

    def test_three_second_stale_limit_clears_display_and_webmonitor_once(self):
        """Show no data and clear publication once when the last sample is stale."""
        subsystem = make_vtrx_consumer()
        subsystem.latest_902b_pressure_mbar = 1.234e-3
        subsystem.last_valid_902b_timestamp = 1000.0
        subsystem._902b_webmonitor_cleared = False

        with patch("subsystem.vtrx.vtrx.time.time", return_value=1003.01):
            subsystem._process_902b_data()
            subsystem._process_902b_data()

        self.assertEqual(subsystem.label_902b_pressure.options["text"], "No data...")
        subsystem.logger.clear_value.assert_called_once_with("pressure_902b_mbar")

    def test_fresh_value_remains_visible_during_brief_poll_failures(self):
        """Retain the latest pressure while it remains within the freshness window."""
        subsystem = make_vtrx_consumer()
        subsystem.latest_902b_pressure_mbar = 1.234e-3
        subsystem.last_valid_902b_timestamp = 1000.0
        subsystem.label_902b_pressure.config(text="1.234E-03 mbar")

        with patch("subsystem.vtrx.vtrx.time.time", return_value=1002.99):
            subsystem._process_902b_data()

        self.assertEqual(subsystem.label_902b_pressure.options["text"], "1.234E-03 mbar")
        subsystem.logger.clear_value.assert_not_called()


if __name__ == "__main__":
    unittest.main()
