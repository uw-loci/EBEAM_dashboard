"""Tests for 902B measurement consumption in the VTRX dashboard pane."""

import os
import queue
import sys
import threading
import unittest
from unittest.mock import MagicMock, patch

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from subsystem.vtrx.vtrx import VTRXSubsystem


def make_vtrx_consumer():
    """Build only the VTRX state needed by the 902B queue consumer."""
    subsystem = VTRXSubsystem.__new__(VTRXSubsystem)
    subsystem.mks_902b_driver = MagicMock()
    subsystem.mks_902b_driver.data_queue = queue.Queue()
    subsystem.logger = MagicMock()
    subsystem.error_state = False
    subsystem.last_valid_pressure_value = None
    subsystem.last_successful_read_time = None
    subsystem.latest_902b_pressure_mbar = None
    subsystem.last_valid_902b_timestamp = None
    subsystem._902b_webmonitor_cleared = True
    subsystem._902b_widget_suppressed = False
    subsystem.stop_event = threading.Event()
    subsystem._background_log_queue = queue.SimpleQueue()
    subsystem._main_thread_id = threading.get_ident()
    subsystem.ser = None
    return subsystem


class TestVTRX902BConsumer(unittest.TestCase):
    """Validate threshold-gated publication and stale clearing."""

    def test_newest_measurement_is_published_when_972b_is_unavailable(self):
        """An unavailable 972B does not suppress the newest 902B measurement."""
        subsystem = make_vtrx_consumer()
        subsystem.mks_902b_driver.data_queue.put((999.0, 2.0e-3))
        subsystem.mks_902b_driver.data_queue.put((1000.0, 1.234e-3))

        with patch("subsystem.vtrx.vtrx.time.time", return_value=1000.5):
            subsystem._process_902b_data()

        self.assertEqual(subsystem.latest_902b_pressure_mbar, 1.234e-3)
        self.assertEqual(subsystem.last_valid_902b_timestamp, 1000.0)
        subsystem.logger.update_field.assert_called_once_with(
            "pressure_902b_mbar",
            1.234e-3,
        )
        subsystem.logger.clear_value.assert_not_called()

    def test_six_second_stale_limit_clears_publication_once(self):
        """Clear publication once when the last 902B sample is stale."""
        subsystem = make_vtrx_consumer()
        subsystem.latest_902b_pressure_mbar = 1.234e-3
        subsystem.last_valid_902b_timestamp = 1000.0
        subsystem._902b_webmonitor_cleared = False
        subsystem.label_902b_pressure = MagicMock()

        with patch("subsystem.vtrx.vtrx.time.time", return_value=1006.01):
            subsystem._process_902b_data()
            subsystem._process_902b_data()

        subsystem.logger.clear_value.assert_called_once_with("pressure_902b_mbar")
        subsystem.label_902b_pressure.config.assert_called_with(
            text="No data...",
            bg="white",
            fg="black",
        )
        self.assertFalse(subsystem._902b_widget_suppressed)

    def test_fresh_value_remains_published_during_brief_poll_failures(self):
        """Retain publication while the 902B value remains fresh."""
        subsystem = make_vtrx_consumer()
        subsystem.latest_902b_pressure_mbar = 1.234e-3
        subsystem.last_valid_902b_timestamp = 1000.0
        subsystem._902b_webmonitor_cleared = False

        with patch("subsystem.vtrx.vtrx.time.time", return_value=1005.99):
            subsystem._process_902b_data()

        subsystem.logger.update_field.assert_not_called()
        subsystem.logger.clear_value.assert_not_called()

    def test_confirmed_972b_below_one_mbar_suppresses_new_902b_data(self):
        """Drain and retain a new 902B sample without publishing it below range."""
        subsystem = make_vtrx_consumer()
        subsystem.last_valid_pressure_value = 0.999
        subsystem.last_successful_read_time = 1000.0
        subsystem._902b_webmonitor_cleared = False
        subsystem.mks_902b_driver.data_queue.put((1000.0, 4.5e-3))

        with patch("subsystem.vtrx.vtrx.time.time", return_value=1000.5):
            subsystem._process_902b_data()
            subsystem._process_902b_data()

        self.assertEqual(subsystem.latest_902b_pressure_mbar, 4.5e-3)
        self.assertTrue(subsystem._902b_widget_suppressed)
        subsystem.logger.update_field.assert_not_called()
        subsystem.logger.clear_value.assert_called_once_with("pressure_902b_mbar")

    def test_972b_at_exactly_one_mbar_allows_902b_publication(self):
        """The suppression threshold is strictly less than one mbar."""
        subsystem = make_vtrx_consumer()
        subsystem.last_valid_pressure_value = 1.0
        subsystem.last_successful_read_time = 1000.0
        subsystem.mks_902b_driver.data_queue.put((1000.0, 4.5e-3))

        with patch("subsystem.vtrx.vtrx.time.time", return_value=1000.5):
            subsystem._process_902b_data()

        subsystem.logger.update_field.assert_called_once_with(
            "pressure_902b_mbar",
            4.5e-3,
        )
        self.assertFalse(subsystem._902b_widget_suppressed)
        subsystem.logger.clear_value.assert_not_called()

    def test_stale_or_error_972b_does_not_suppress_902b(self):
        """Only a fresh, valid low 972B measurement suppresses publication."""
        for last_successful_read_time, error_state in (
            (990.0, False),
            (1000.0, True),
        ):
            with self.subTest(
                last_successful_read_time=last_successful_read_time,
                error_state=error_state,
            ):
                subsystem = make_vtrx_consumer()
                subsystem.last_valid_pressure_value = 0.5
                subsystem.last_successful_read_time = last_successful_read_time
                subsystem.error_state = error_state
                subsystem.mks_902b_driver.data_queue.put((1000.0, 4.5e-3))

                with patch("subsystem.vtrx.vtrx.time.time", return_value=1000.5):
                    subsystem._process_902b_data()

                subsystem.logger.update_field.assert_called_once_with(
                    "pressure_902b_mbar",
                    4.5e-3,
                )
                subsystem.logger.clear_value.assert_not_called()

    def test_recovery_republishes_a_still_fresh_cached_902b_value(self):
        """A cached 902B sample resumes publication when the 972B recovers."""
        subsystem = make_vtrx_consumer()
        subsystem.last_valid_pressure_value = 0.5
        subsystem.last_successful_read_time = 1000.0
        subsystem.mks_902b_driver.data_queue.put((1000.0, 4.5e-3))

        with patch("subsystem.vtrx.vtrx.time.time", return_value=1000.5):
            subsystem._process_902b_data()

        subsystem.last_valid_pressure_value = 1.0
        subsystem.last_successful_read_time = 1001.0
        with patch("subsystem.vtrx.vtrx.time.time", return_value=1001.5):
            subsystem._process_902b_data()

        subsystem.logger.update_field.assert_called_once_with(
            "pressure_902b_mbar",
            4.5e-3,
        )
        self.assertFalse(subsystem._902b_widget_suppressed)

    def test_stale_972b_republishes_a_still_fresh_cached_902b_value(self):
        """Loss of 972B confirmation ends low-pressure suppression."""
        subsystem = make_vtrx_consumer()
        subsystem.last_valid_pressure_value = 0.5
        subsystem.last_successful_read_time = 1000.0
        subsystem.mks_902b_driver.data_queue.put((1000.0, 4.5e-3))

        with patch("subsystem.vtrx.vtrx.time.time", return_value=1000.5):
            subsystem._process_902b_data()

        with patch("subsystem.vtrx.vtrx.time.time", return_value=1003.01):
            subsystem._process_902b_data()

        subsystem.logger.update_field.assert_called_once_with(
            "pressure_902b_mbar",
            4.5e-3,
        )
        self.assertFalse(subsystem._902b_widget_suppressed)

    def test_recovery_does_not_republish_a_stale_cached_902b_value(self):
        """A cached 902B sample must still pass its own freshness rule."""
        subsystem = make_vtrx_consumer()
        subsystem.last_valid_pressure_value = 0.5
        subsystem.last_successful_read_time = 1000.0
        subsystem.latest_902b_pressure_mbar = 4.5e-3
        subsystem.last_valid_902b_timestamp = 990.0
        subsystem._902b_webmonitor_cleared = True

        subsystem.last_valid_pressure_value = 1.0
        subsystem.last_successful_read_time = 1000.0
        with patch("subsystem.vtrx.vtrx.time.time", return_value=1000.5):
            subsystem._process_902b_data()

        subsystem.logger.update_field.assert_not_called()
        subsystem.logger.clear_value.assert_not_called()

    def test_suppression_hides_902b_and_centers_972b_until_restored(self):
        """The pressure widgets follow the 972B publication gate."""
        subsystem = make_vtrx_consumer()
        subsystem.pressure_frame = MagicMock()
        subsystem.label_972b_title = MagicMock()
        subsystem.label_pressure = MagicMock()
        subsystem.label_902b_title = MagicMock()
        subsystem.label_902b_pressure = MagicMock()

        subsystem._set_902b_widget_suppressed(True)

        subsystem.label_902b_title.grid_remove.assert_called_once_with()
        subsystem.label_902b_pressure.grid_remove.assert_called_once_with()
        subsystem.label_972b_title.grid_configure.assert_called_with(column=1)
        subsystem.label_pressure.grid_configure.assert_called_with(
            column=2,
            sticky='',
        )

        subsystem._set_902b_widget_suppressed(False)

        subsystem.label_972b_title.grid_configure.assert_called_with(column=0)
        subsystem.label_pressure.grid_configure.assert_called_with(
            column=1,
            sticky='ew',
        )
        subsystem.label_902b_title.grid.assert_called_once_with()
        subsystem.label_902b_pressure.grid.assert_called_once_with()

    def test_low_972b_clears_902b_before_updating_the_972b_gui(self):
        """Prevent a low-pressure update from retaining a published 902B value."""
        subsystem = make_vtrx_consumer()
        subsystem._902b_webmonitor_cleared = False
        subsystem.firmware_error = False
        subsystem.vacuum_fields_cleared = False
        subsystem.last_no_data_log_time = 0.0
        subsystem.error_logged = False
        subsystem.log = MagicMock()
        events = []
        subsystem.logger.clear_value.side_effect = (
            lambda field: events.append(("clear", field))
        )
        subsystem.update_gui = MagicMock(
            side_effect=lambda *_args: events.append(("update_gui", None))
        )

        with patch("subsystem.vtrx.vtrx.time.time", return_value=1000.0):
            subsystem.handle_serial_data("0.5;5.0E-01;00000000")

        self.assertEqual(
            events,
            [
                ("clear", "pressure_902b_mbar"),
                ("update_gui", None),
            ],
        )


if __name__ == "__main__":
    unittest.main()
