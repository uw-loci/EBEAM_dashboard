import enum
import importlib.util
import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
PROCESS_MONITOR_PATH = os.path.join(
    REPO_ROOT,
    "subsystem",
    "process_monitor",
    "process_monitor.py",
)


class FakeLogLevel(enum.IntEnum):
    VERBOSE = 0
    DEBUG = 1
    INFO = 2
    WARNING = 3
    ERROR = 4
    CRITICAL = 5


def load_process_monitor_module():
    instrumentctl_pkg = types.ModuleType("instrumentctl")
    dp16_pkg = types.ModuleType("instrumentctl.DP16_process_monitor")
    dp16_module = types.ModuleType("instrumentctl.DP16_process_monitor.DP16_process_monitor")
    utils_module = types.ModuleType("utils")

    class StubDP16ProcessMonitor:
        DISCONNECTED = -1
        SENSOR_ERROR = -2

        def __init__(self, *args, **kwargs):
            pass

    dp16_module.DP16ProcessMonitor = StubDP16ProcessMonitor
    dp16_pkg.DP16_process_monitor = dp16_module
    instrumentctl_pkg.DP16_process_monitor = dp16_pkg
    utils_module.LogLevel = FakeLogLevel

    module_name = "citest_process_monitor_module"
    spec = importlib.util.spec_from_file_location(module_name, PROCESS_MONITOR_PATH)
    module = importlib.util.module_from_spec(spec)

    with patch.dict(
        sys.modules,
        {
            "instrumentctl": instrumentctl_pkg,
            "instrumentctl.DP16_process_monitor": dp16_pkg,
            "instrumentctl.DP16_process_monitor.DP16_process_monitor": dp16_module,
            "utils": utils_module,
        },
    ):
        spec.loader.exec_module(module)

    return module


class TestProcessMonitorSubsystem(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.process_monitor_module = load_process_monitor_module()

    def setUp(self):
        self.parent = MagicMock()
        self.logger = MagicMock()
        self.active = {"Environment Pass": True}

    def test_dummy_port_skips_driver_and_marks_disconnected(self):
        module = self.process_monitor_module

        with patch.object(module.ProcessMonitorSubsystem, "setup_gui", autospec=True), \
             patch.object(module.ProcessMonitorSubsystem, "_set_all_temps_disconnected", autospec=True) as set_disconnected, \
             patch.object(module.ProcessMonitorSubsystem, "update_temperatures", autospec=True) as update_temperatures, \
             patch.object(module, "DP16ProcessMonitor", autospec=True) as driver_cls:
            subsystem = module.ProcessMonitorSubsystem(
                self.parent,
                com_port="DUMMY_COM7",
                active=self.active,
                logger=self.logger,
            )

        self.assertIsNone(subsystem.monitor)
        driver_cls.assert_not_called()
        set_disconnected.assert_called_once_with(subsystem)
        update_temperatures.assert_not_called()
        self.assertFalse(self.active["Environment Pass"])
        self.logger.clear_value.assert_called_once_with("temperatures")
        self.parent.after.assert_not_called()

    def test_empty_port_uses_disconnected_dummy_behavior(self):
        module = self.process_monitor_module

        with patch.object(module.ProcessMonitorSubsystem, "setup_gui", autospec=True), \
             patch.object(module.ProcessMonitorSubsystem, "_set_all_temps_disconnected", autospec=True), \
             patch.object(module.ProcessMonitorSubsystem, "update_temperatures", autospec=True), \
             patch.object(module, "DP16ProcessMonitor", autospec=True) as driver_cls:
            subsystem = module.ProcessMonitorSubsystem(
                self.parent,
                com_port="",
                active=self.active,
                logger=self.logger,
            )

        self.assertIsNone(subsystem.monitor)
        driver_cls.assert_not_called()
        self.assertFalse(self.active["Environment Pass"])

    def test_real_port_initializes_driver(self):
        module = self.process_monitor_module
        driver_instance = MagicMock()

        with patch.object(module.ProcessMonitorSubsystem, "setup_gui", autospec=True), \
             patch.object(module.ProcessMonitorSubsystem, "update_temperatures", autospec=True) as update_temperatures, \
             patch.object(module, "DP16ProcessMonitor", autospec=True, return_value=driver_instance) as driver_cls:
            subsystem = module.ProcessMonitorSubsystem(
                self.parent,
                com_port="COM7",
                active=self.active,
                logger=self.logger,
            )

        self.assertIs(subsystem.monitor, driver_instance)
        driver_cls.assert_called_once_with(
            port="COM7",
            unit_numbers=[1, 2, 3, 4, 5, 6],
            logger=self.logger,
        )
        update_temperatures.assert_called_once_with(subsystem)


if __name__ == "__main__":
    unittest.main()
