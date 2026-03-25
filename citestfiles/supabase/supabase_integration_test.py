"""Tests for Supabase integration: SupabaseClient and Logger Supabase features."""
import datetime
import io
import json
import os
import shutil
import sys
import unittest
import uuid
from unittest.mock import MagicMock, patch

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from db.supabase_client import SupabaseClient
from utils import Logger, LogLevel

TEST_TMP_ROOT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "_tmp")
os.makedirs(TEST_TMP_ROOT, exist_ok=True)

EXPECTED_DICT_LOGGER_KEYS = {
    "pressure",
    "safetyOutputDataFlags",
    "safetyInputDataFlags",
    "safetyOutputStatusFlags",
    "safetyInputStatusFlags",
    "temperatures",
    "vacuumBits",
    "Cathode A - Heater Current:",
    "Cathode B - Heater Current:",
    "Cathode C - Heater Current:",
    "Cathode A - Heater Voltage:",
    "Cathode B - Heater Voltage:",
    "Cathode C - Heater Voltage:",
    "clamp_temperature_A",
    "clamp_temperature_B",
    "clamp_temperature_C",
}


# ---------------------------------------------------------------------------
# Class 1: SupabaseClient unit tests
# ---------------------------------------------------------------------------

class TestSupabaseClientUnit(unittest.TestCase):
    """Tests for SupabaseClient in isolation, mocking the Supabase SDK."""

    def _make_getenv(self, url_value, key_value):
        """Return a side_effect function for os.getenv that returns url/key values."""
        def _getenv(name, default=None):
            if name == "SUPABASE_API_URL":
                return url_value
            if name == "SUPABASE_API_KEY":
                return key_value
            return default
        return _getenv

    def test_init_raises_when_url_missing(self):
        with patch("db.supabase_client.load_dotenv"), \
             patch("db.supabase_client.os.getenv", side_effect=self._make_getenv(None, "fake-key")), \
             patch("db.supabase_client.create_client") as mock_create:
            with self.assertRaises(ValueError) as ctx:
                SupabaseClient()
            self.assertIn("SUPABASE_API_URL", str(ctx.exception))
            mock_create.assert_not_called()

    def test_init_raises_when_key_missing(self):
        with patch("db.supabase_client.load_dotenv"), \
             patch("db.supabase_client.os.getenv", side_effect=self._make_getenv("https://fake.supabase.co", None)), \
             patch("db.supabase_client.create_client") as mock_create:
            with self.assertRaises(ValueError):
                SupabaseClient()
            mock_create.assert_not_called()

    def test_init_raises_when_both_missing(self):
        with patch("db.supabase_client.load_dotenv"), \
             patch("db.supabase_client.os.getenv", side_effect=self._make_getenv(None, None)):
            with self.assertRaises(ValueError):
                SupabaseClient()

    def test_init_success_calls_create_client(self):
        fake_url = "https://fake.supabase.co"
        fake_key = "fake-anon-key"
        mock_client_instance = MagicMock()

        with patch("db.supabase_client.load_dotenv"), \
             patch("db.supabase_client.os.getenv", side_effect=self._make_getenv(fake_url, fake_key)), \
             patch("db.supabase_client.create_client", return_value=mock_client_instance) as mock_create:
            client = SupabaseClient()

        mock_create.assert_called_once_with(fake_url, fake_key)
        self.assertIs(client.client, mock_client_instance)

    def test_insert_status_log_returns_true_on_success(self):
        mock_client_instance = MagicMock()
        status = {"pressure": 1.5e-5, "temperatures": [100, 200]}

        with patch("db.supabase_client.load_dotenv"), \
             patch("db.supabase_client.os.getenv", side_effect=self._make_getenv("url", "key")), \
             patch("db.supabase_client.create_client", return_value=mock_client_instance):
            sb = SupabaseClient()

        result = sb.insert_status_log(status)

        self.assertTrue(result)
        mock_client_instance.table.assert_called_once_with("short_term_logs")
        mock_client_instance.table.return_value.insert.assert_called_once_with({"data": status})
        mock_client_instance.table.return_value.insert.return_value.execute.assert_called_once()

    def test_insert_status_log_returns_false_on_exception(self):
        mock_client_instance = MagicMock()
        mock_client_instance.table.return_value.insert.return_value.execute.side_effect = Exception("network error")

        with patch("db.supabase_client.load_dotenv"), \
             patch("db.supabase_client.os.getenv", side_effect=self._make_getenv("url", "key")), \
             patch("db.supabase_client.create_client", return_value=mock_client_instance):
            sb = SupabaseClient()

        with patch("builtins.print") as mock_print:
            result = sb.insert_status_log({})

        self.assertFalse(result)
        printed = " ".join(str(c) for c in mock_print.call_args_list)
        self.assertIn("Supabase insert error", printed)


# ---------------------------------------------------------------------------
# Class 2: Logger Supabase initialization
# ---------------------------------------------------------------------------

class TestLoggerSupabaseInit(unittest.TestCase):
    """Tests for how Logger.__init__ handles SupabaseClient construction."""

    def setUp(self):
        self.sb_patcher = patch("utils.SupabaseClient")
        self.mock_sb_class = self.sb_patcher.start()

    def tearDown(self):
        self.sb_patcher.stop()

    def test_logger_stores_supabase_client_when_init_succeeds(self):
        mock_instance = MagicMock()
        self.mock_sb_class.return_value = mock_instance

        logger = Logger(text_widget=None)

        self.assertIsNotNone(logger.supabase_client)
        self.assertIs(logger.supabase_client, mock_instance)

    def test_logger_sets_supabase_client_to_none_when_init_raises_valueerror(self):
        self.mock_sb_class.side_effect = ValueError(
            "SUPABASE_API_URL and SUPABASE_API_KEY must be set in .env file"
        )

        with patch("builtins.print") as mock_print:
            logger = Logger(text_widget=None)

        self.assertIsNone(logger.supabase_client)
        printed = " ".join(str(c) for c in mock_print.call_args_list)
        self.assertIn("Warning: Supabase client failed to initialize", printed)

    def test_logger_sets_supabase_client_to_none_when_init_raises_generic(self):
        self.mock_sb_class.side_effect = Exception("connection refused")

        logger = Logger(text_widget=None)

        self.assertIsNone(logger.supabase_client)

    def test_logger_last_supabase_write_starts_as_none(self):
        self.mock_sb_class.return_value = MagicMock()

        logger = Logger(text_widget=None)

        self.assertIsNone(logger.last_supabase_write)


# ---------------------------------------------------------------------------
# Class 3: Supabase rate limiting
# ---------------------------------------------------------------------------

class TestSupabaseRateLimiting(unittest.TestCase):
    """Tests for the 2-second write throttle in log_dict_update."""

    def setUp(self):
        self.sb_patcher = patch("utils.SupabaseClient")
        self.mock_sb_class = self.sb_patcher.start()
        self.mock_sb_instance = MagicMock()
        self.mock_sb_class.return_value = self.mock_sb_instance

        self.logger = Logger(text_widget=None, log_to_file=True)
        # Inject a mock webMonitor_log_file so the file-write branch doesn't crash
        self.logger.webMonitor_log_file = MagicMock()
        self.logger.webMonitor_log_start_time = datetime.datetime.now()

    def tearDown(self):
        self.sb_patcher.stop()

    def test_first_call_always_writes_to_supabase(self):
        self.assertIsNone(self.logger.last_supabase_write)

        self.logger.log_dict_update({"pressure": 1.0})

        self.mock_sb_instance.insert_status_log.assert_called_once()
        self.assertIsNotNone(self.logger.last_supabase_write)

    def test_second_call_within_2s_is_throttled(self):
        self.logger.last_supabase_write = datetime.datetime.now()

        self.logger.log_dict_update({"pressure": 2.0})

        self.mock_sb_instance.insert_status_log.assert_not_called()

    def test_call_after_2s_elapsed_writes_to_supabase(self):
        self.logger.last_supabase_write = datetime.datetime.now() - datetime.timedelta(seconds=3)

        self.logger.log_dict_update({"pressure": 3.0})

        self.mock_sb_instance.insert_status_log.assert_called_once()

    def test_call_exactly_at_2s_boundary_writes_to_supabase(self):
        self.logger.last_supabase_write = datetime.datetime.now() - datetime.timedelta(seconds=2)

        self.logger.log_dict_update({"pressure": 4.0})

        self.mock_sb_instance.insert_status_log.assert_called_once()

    def test_supabase_not_called_when_log_to_file_is_false(self):
        self.logger.log_to_file = False

        self.logger.log_dict_update({"pressure": 5.0})

        self.mock_sb_instance.insert_status_log.assert_not_called()


# ---------------------------------------------------------------------------
# Class 4: WebMonitor log format
# ---------------------------------------------------------------------------

class TestWebMonitorLogFormat(unittest.TestCase):
    """Tests for the JSON structure written to webMonitor_log_file."""

    def setUp(self):
        self.sb_patcher = patch("utils.SupabaseClient")
        mock_sb_class = self.sb_patcher.start()
        mock_sb_class.return_value = MagicMock()

        self.logger = Logger(text_widget=None, log_to_file=False)
        # Inject StringIO so log_dict_update writes to it
        self.buf = io.StringIO()
        self.logger.webMonitor_log_file = self.buf
        self.logger.webMonitor_log_start_time = datetime.datetime.now()
        self.logger.log_to_file = True

    def tearDown(self):
        self.sb_patcher.stop()

    def _get_entry(self):
        self.buf.seek(0)
        line = self.buf.readline().strip()
        return json.loads(line)

    def test_webmonitor_log_entry_is_valid_json(self):
        self.logger.log_dict_update({"pressure": 1.2e-5})
        self.buf.seek(0)
        line = self.buf.readline().strip()
        # Should not raise
        json.loads(line)

    def test_webmonitor_log_entry_has_timestamp_and_status_keys(self):
        self.logger.log_dict_update({"pressure": 1.0})
        entry = self._get_entry()
        self.assertIn("timestamp", entry)
        self.assertIn("status", entry)

    def test_webmonitor_log_timestamp_format(self):
        self.logger.log_dict_update({"pressure": 1.0})
        entry = self._get_entry()
        # Should not raise if format matches
        datetime.datetime.strptime(entry["timestamp"], "%Y-%m-%d %H:%M:%S")

    def test_webmonitor_log_status_contains_dict_logger_snapshot(self):
        self.logger.dict_logger["pressure"] = 9.9e-6
        self.logger.log_dict_update(self.logger.dict_logger)
        entry = self._get_entry()

        self.assertEqual(entry["status"]["pressure"], 9.9e-6)
        for key in EXPECTED_DICT_LOGGER_KEYS:
            self.assertIn(key, entry["status"])


# ---------------------------------------------------------------------------
# Class 5: WebMonitor rotation
# ---------------------------------------------------------------------------

class TestWebMonitorRotation(unittest.TestCase):
    """Tests for 4-hour web monitor rollover and retry behavior."""

    def setUp(self):
        self.sb_patcher = patch("utils.SupabaseClient")
        mock_sb_class = self.sb_patcher.start()
        mock_sb_class.return_value = MagicMock()

        self.test_root = os.path.join(TEST_TMP_ROOT, f"wm_rotation_{uuid.uuid4().hex}")
        os.makedirs(self.test_root, exist_ok=True)
        self.base_path_patcher = patch.object(Logger, "_get_dashboard_base_path", return_value=self.test_root)
        self.base_path_patcher.start()

        self.logger = Logger(text_widget=None, log_to_file=False)
        self.logger.supabase_client = None
        self.logger.setup_wm_logfile()
        self.logger.log_to_file = True

    def tearDown(self):
        try:
            self.logger.close()
        finally:
            self.base_path_patcher.stop()
            self.sb_patcher.stop()
            shutil.rmtree(self.test_root, ignore_errors=True)

    def _read_wm_lines(self):
        with open(self.logger.webMonitor_log_filepath, "r", encoding="utf-8") as fh:
            return [line.rstrip("\n") for line in fh]

    def test_webmonitor_log_rotates_after_four_hours(self):
        seed_entry = json.dumps({"timestamp": "seed", "status": {"pressure": 0}})
        self.logger.webMonitor_log_file.write(seed_entry + "\n")
        self.logger.webMonitor_log_file.flush()
        self.logger.webMonitor_log_start_time = datetime.datetime.now() - datetime.timedelta(hours=4, seconds=1)

        self.logger.log_dict_update({"pressure": 1.0})

        lines = self._read_wm_lines()
        self.assertEqual(len(lines), 1)
        entry = json.loads(lines[0])
        self.assertEqual(entry["status"]["pressure"], 1.0)
        datetime.datetime.strptime(entry["timestamp"], "%Y-%m-%d %H:%M:%S")

    def test_webmonitor_log_does_not_rotate_before_four_hours(self):
        seed_entry = json.dumps({"timestamp": "seed", "status": {"pressure": 0}})
        self.logger.webMonitor_log_file.write(seed_entry + "\n")
        self.logger.webMonitor_log_file.flush()
        original_start_time = datetime.datetime.now() - datetime.timedelta(hours=3, minutes=59, seconds=59)
        self.logger.webMonitor_log_start_time = original_start_time

        self.logger.log_dict_update({"pressure": 2.0})

        lines = self._read_wm_lines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0], seed_entry)
        self.assertEqual(self.logger.webMonitor_log_start_time, original_start_time)
        entry = json.loads(lines[1])
        self.assertEqual(entry["status"]["pressure"], 2.0)

    def test_webmonitor_retry_reopens_in_append_mode_within_window(self):
        seed_entry = json.dumps({"timestamp": "seed", "status": {"pressure": 0}})
        self.logger.webMonitor_log_file.write(seed_entry + "\n")
        self.logger.webMonitor_log_file.flush()
        self.logger.webMonitor_log_start_time = datetime.datetime.now() - datetime.timedelta(hours=1)

        class FailingWriter:
            def write(self, _message):
                raise OSError("simulated write failure")

            def flush(self):
                pass

            def close(self):
                pass

        self.logger.webMonitor_log_file = FailingWriter()

        self.logger.log_dict_update({"pressure": 3.0})

        lines = self._read_wm_lines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0], seed_entry)
        entry = json.loads(lines[1])
        self.assertEqual(entry["status"]["pressure"], 3.0)


# ---------------------------------------------------------------------------
# Class 6: dict_logger field management
# ---------------------------------------------------------------------------

class TestDictLoggerFieldManagement(unittest.TestCase):
    """Tests for update_field, clear_value, and dict_logger schema."""

    def setUp(self):
        self.sb_patcher = patch("utils.SupabaseClient")
        mock_sb_class = self.sb_patcher.start()
        mock_sb_class.return_value = MagicMock()
        # log_to_file=False isolates from file I/O
        self.logger = Logger(text_widget=None, log_to_file=False)

    def tearDown(self):
        self.sb_patcher.stop()

    def test_dict_logger_has_all_expected_keys_on_init(self):
        self.assertEqual(set(self.logger.dict_logger.keys()), EXPECTED_DICT_LOGGER_KEYS)

    def test_dict_logger_all_values_none_on_init(self):
        self.assertTrue(all(v is None for v in self.logger.dict_logger.values()))

    def test_update_field_sets_value_for_all_valid_keys(self):
        for key in EXPECTED_DICT_LOGGER_KEYS:
            with self.subTest(key=key):
                self.logger.update_field(key, "test_value")
                self.assertEqual(self.logger.dict_logger[key], "test_value")
                # Reset for next iteration
                self.logger.dict_logger[key] = None

    def test_update_field_raises_key_error_for_invalid_key(self):
        with self.assertRaises(KeyError) as ctx:
            self.logger.update_field("nonexistent_field", 42)
        self.assertIn("nonexistent_field", str(ctx.exception))
        self.assertIn("is not a valid key", str(ctx.exception))

    def test_clear_value_sets_field_to_none(self):
        self.logger.dict_logger["pressure"] = 5.0
        self.logger.clear_value("pressure")
        self.assertIsNone(self.logger.dict_logger["pressure"])

    def test_clear_value_raises_key_error_for_invalid_key(self):
        with self.assertRaises(KeyError) as ctx:
            self.logger.clear_value("not_a_field")
        self.assertIn("not_a_field", str(ctx.exception))

    def test_update_field_triggers_log_dict_update(self):
        self.logger.log_dict_update = MagicMock()
        self.logger.update_field("pressure", 7.7e-6)
        self.logger.log_dict_update.assert_called_once()
        call_arg = self.logger.log_dict_update.call_args[0][0]
        self.assertEqual(call_arg["pressure"], 7.7e-6)


if __name__ == "__main__":
    unittest.main()
