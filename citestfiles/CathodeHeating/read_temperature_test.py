import os
import sys
import threading
import unittest
from unittest.mock import MagicMock

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from subsystem.cathode_heating.cathode_heating import CathodeHeatingSubsystem


class FakeStringVar:
    def __init__(self, value=None):
        self.value = value

    def set(self, value):
        self.value = value


class TestReadTemperature(unittest.TestCase):
    def setUp(self):
        self.subsys = object.__new__(CathodeHeatingSubsystem)
        self.subsys.temperature_controller = MagicMock()
        self.subsys.temperature_controller.connected = True
        self.subsys.clamp_temperature_vars = [FakeStringVar("--") for _ in range(3)]
        self.subsys.temperature_valid_connections = [False, False, False]
        self.subsys.poll_error_last_log_times = {}
        self.subsys.poll_error_log_lock = threading.Lock()
        self.subsys.set_plot_color = MagicMock()
        self.subsys.log = MagicMock()

    def test_cached_string_error_displays_err_without_fallthrough(self):
        self.subsys.temperature_controller.temperatures = ["ERROR", None, None]

        temperature = self.subsys.read_temperature(0)

        self.assertIsNone(temperature)
        self.assertEqual(self.subsys.clamp_temperature_vars[0].value, "ERR")
        self.subsys.set_plot_color.assert_called_once_with(0, 'ERROR')

    def test_missing_temperature_data_displays_blank_reading(self):
        self.subsys.temperature_controller.temperatures = [None, None, None]

        temperature = self.subsys.read_temperature(0)

        self.assertIsNone(temperature)
        self.assertEqual(self.subsys.clamp_temperature_vars[0].value, "-- C")
        self.subsys.set_plot_color.assert_not_called()


if __name__ == '__main__':
    unittest.main()
