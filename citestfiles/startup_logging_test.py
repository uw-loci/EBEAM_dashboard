import json
import os
import shutil
import sys
import unittest
import uuid
from unittest.mock import MagicMock, patch

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from utils import Logger, LogLevel
from usr.com_port_config import (
    get_beam_pulse_com_port,
    load_com_ports,
    save_com_ports,
)
from usr.panel_config import load_pane_states

TEST_TMP_ROOT = os.path.join(os.path.dirname(__file__), "_tmp")
os.makedirs(TEST_TMP_ROOT, exist_ok=True)


class FakeTextWidget:
    def __init__(self):
        self.messages = []
        self.tag_configs = []

    def insert(self, _index, message, _tags=None):
        self.messages.append(message)

    def tag_config(self, tag, **kwargs):
        self.tag_configs.append((tag, kwargs))

    def see(self, _index):
        pass

    def getvalue(self):
        return "".join(self.messages)


class FakeSubsystem:
    def __init__(self, *args, **kwargs):
        pass


class TestStartupLogger(unittest.TestCase):
    def setUp(self):
        self.tempdir = os.path.join(TEST_TMP_ROOT, f"case_{uuid.uuid4().hex}")
        os.makedirs(self.tempdir, exist_ok=False)
        self.expanduser_patcher = patch("utils.os.path.expanduser", return_value=self.tempdir)
        self.expanduser_patcher.start()

    def tearDown(self):
        self.expanduser_patcher.stop()
        shutil.rmtree(self.tempdir, ignore_errors=True)

    def test_logger_creates_file_and_persists_early_messages_without_widget(self):
        logger = Logger(text_widget=None, log_level=LogLevel.DEBUG, file_log_level=LogLevel.VERBOSE, log_to_file=True)
        self.addCleanup(logger.close)

        logger.info("Process launch")

        self.assertTrue(os.path.exists(logger.log_filepath))
        with open(logger.log_filepath, "r") as file:
            contents = file.read()

        self.assertIn("Log file created at", contents)
        self.assertIn("WebMonitor log file created at", contents)
        self.assertIn("Process launch", contents)

    def test_attach_text_widget_replays_buffer_without_creating_second_file(self):
        logger = Logger(text_widget=None, log_level=LogLevel.DEBUG, file_log_level=LogLevel.VERBOSE, log_to_file=True)
        self.addCleanup(logger.close)

        logger.info("Early startup milestone")
        original_log_path = logger.log_filepath
        widget = FakeTextWidget()

        logger.attach_text_widget(widget)
        logger.info("Post-attach milestone")

        self.assertEqual(original_log_path, logger.log_filepath)
        self.assertEqual(len(os.listdir(os.path.dirname(logger.log_filepath))), 1)

        widget_text = widget.getvalue()
        self.assertIn("Early startup milestone", widget_text)
        self.assertIn("Post-attach milestone", widget_text)
        self.assertLess(widget_text.index("Early startup milestone"), widget_text.index("Post-attach milestone"))


class TestComPortConfigLogging(unittest.TestCase):
    def setUp(self):
        self.tempdir = os.path.join(TEST_TMP_ROOT, f"case_{uuid.uuid4().hex}")
        os.makedirs(self.tempdir, exist_ok=False)

    def tearDown(self):
        shutil.rmtree(self.tempdir, ignore_errors=True)

    def test_save_and_load_com_ports_with_logger_avoid_print(self):
        logger = MagicMock()
        filepath = os.path.join(self.tempdir, "usr_data", "com_ports.json")
        expected = {"VTRXSubsystem": "COM1", "Interlocks": "COM2"}

        with patch("builtins.print") as mock_print:
            save_com_ports(expected, filepath=filepath, logger=logger)
            loaded = load_com_ports(filepath=filepath, logger=logger)

        self.assertEqual(loaded, expected)
        logger.info.assert_any_call(f"COM ports saved to {filepath}.")
        logger.info.assert_any_call(f"COM ports loaded from {filepath}.")
        mock_print.assert_not_called()

    def test_load_com_ports_missing_logs_without_print(self):
        logger = MagicMock()
        filepath = os.path.join(self.tempdir, "missing_com_ports.json")

        with patch("builtins.print") as mock_print:
            loaded = load_com_ports(filepath=filepath, logger=logger)

        self.assertEqual(loaded, {})
        logger.info.assert_called_with("No COM port configuration file found.")
        mock_print.assert_not_called()

    def test_load_com_ports_invalid_json_logs_error_without_print(self):
        logger = MagicMock()
        filepath = os.path.join(self.tempdir, "broken_com_ports.json")
        with open(filepath, "w") as file:
            file.write("{invalid json")

        with patch("builtins.print") as mock_print:
            loaded = load_com_ports(filepath=filepath, logger=logger)

        self.assertEqual(loaded, {})
        self.assertIn("Error loading COM ports", logger.error.call_args[0][0])
        mock_print.assert_not_called()

    def test_get_beam_pulse_com_port_prefers_canonical_key(self):
        com_ports = {
            "BeamPulse": "COM7",
            "Beam Pulse": "COM8",
        }

        self.assertEqual(get_beam_pulse_com_port(com_ports), "COM7")

    def test_get_beam_pulse_com_port_accepts_legacy_key(self):
        com_ports = {"Beam Pulse": "COM8"}

        self.assertEqual(get_beam_pulse_com_port(com_ports), "COM8")

    def test_get_beam_pulse_com_port_defaults_to_blank(self):
        self.assertEqual(get_beam_pulse_com_port({}), "")


class TestDashboardBeamPulseInitialization(unittest.TestCase):
    def _patch_required_subsystems(self, dashboard):
        subsystem_names = (
            "VTRXSubsystem",
            "ProcessMonitorSubsystem",
            "InterlocksSubsystem",
            "OilSubsystem",
            "CathodeHeatingSubsystem",
            "BeamEnergySubsystem",
        )
        for name in subsystem_names:
            patcher = patch.object(dashboard.subsystem, name, FakeSubsystem)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _create_dashboard(self, dashboard):
        frame_names = (
            "Vacuum System",
            "Process Monitor",
            "Interlocks",
            "Oil System",
            "Cathode Heating",
            "Beam Energy",
            "Beam Pulse",
        )
        frames = {name: MagicMock(name=name) for name in frame_names}

        instance = dashboard.EBEAMSystemDashboard.__new__(
            dashboard.EBEAMSystemDashboard
        )
        instance.frames = frames
        instance.com_ports = {
            "VTRXSubsystem": "",
            "ProcessMonitors": "",
            "Interlocks": "",
            "BeamPulse": "COM7",
        }
        instance.logger = MagicMock()
        instance.machine_status_frame = MagicMock(MACHINE_STATUS=False)
        return instance

    def test_beam_pulse_constructed_from_subsystem_package(self):
        import dashboard

        self._patch_required_subsystems(dashboard)
        instance = self._create_dashboard(dashboard)
        beam_pulse = MagicMock()

        with patch.object(
            dashboard.subsystem,
            "BeamPulseSubsystem",
            return_value=beam_pulse,
        ) as beam_pulse_factory:
            instance.create_subsystems()

        beam_pulse_factory.assert_called_once_with(
            parent_frame=instance.frames["Beam Pulse"],
            port="COM7",
            unit=1,
            baudrate=115200,
            logger=instance.logger,
        )
        self.assertIs(instance.subsystems["Beam Pulse"], beam_pulse)
        beam_pulse.set_dashboard_beam_callback.assert_called_once_with(
            instance.handle_beam_pulse_callback
        )


class TestPanelConfigLogging(unittest.TestCase):
    def setUp(self):
        self.tempdir = os.path.join(TEST_TMP_ROOT, f"case_{uuid.uuid4().hex}")
        os.makedirs(self.tempdir, exist_ok=False)

    def tearDown(self):
        shutil.rmtree(self.tempdir, ignore_errors=True)

    def test_load_pane_states_success_logs_without_print(self):
        logger = MagicMock()
        filepath = os.path.join(self.tempdir, "pane_state.json")
        expected = {"Interlocks": [100, 200]}
        with open(filepath, "w") as file:
            json.dump(expected, file)

        with patch("builtins.print") as mock_print:
            loaded = load_pane_states(filepath=filepath, logger=logger)

        self.assertEqual(loaded, expected)
        logger.info.assert_called_with(f"Pane state loaded from {filepath}.")
        mock_print.assert_not_called()

    def test_load_pane_states_missing_logs_without_print(self):
        logger = MagicMock()
        filepath = os.path.join(self.tempdir, "missing_pane_state.json")

        with patch("builtins.print") as mock_print:
            loaded = load_pane_states(filepath=filepath, logger=logger)

        self.assertIsNone(loaded)
        logger.info.assert_called_with("No previous pane state saved.")
        mock_print.assert_not_called()

    def test_load_pane_states_invalid_json_logs_error_without_print(self):
        logger = MagicMock()
        filepath = os.path.join(self.tempdir, "broken_pane_state.json")
        with open(filepath, "w") as file:
            file.write("{invalid json")

        with patch("builtins.print") as mock_print:
            loaded = load_pane_states(filepath=filepath, logger=logger)

        self.assertIsNone(loaded)
        self.assertIn("Failed to load pane states", logger.error.call_args[0][0])
        mock_print.assert_not_called()


if __name__ == "__main__":
    unittest.main()
