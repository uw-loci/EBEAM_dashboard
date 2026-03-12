# Supabase Integration Test Results

**File:** `citestfiles/supabase/supabase_integration_test.py`
**Run command:** `python -m pytest citestfiles/supabase/supabase_integration_test.py -v`
**Python version:** 3.12.9
**Date last run:** 2026-03-12
**Overall status:** PASS — 26/26 passed, 0 failed, 0 errors
**Full suite (`citestfiles/`):** 52/52 passed, 0 failed

---

## TestSupabaseClientUnit

Unit tests for `db/supabase_client.py`. All SDK and env-var calls are mocked — no credentials or network access required.

| Test | What It Verifies | Expected Result | Status |
|------|-----------------|-----------------|--------|
| `test_init_raises_when_url_missing` | `ValueError` raised when `SUPABASE_API_URL` env var is absent; `create_client` never called | `ValueError` with message containing `"SUPABASE_API_URL"`; SDK untouched | PASS |
| `test_init_raises_when_key_missing` | `ValueError` raised when `SUPABASE_API_KEY` env var is absent | `ValueError` raised before `create_client` | PASS |
| `test_init_raises_when_both_missing` | `ValueError` raised when both env vars are absent | `ValueError` raised | PASS |
| `test_init_success_calls_create_client` | `create_client` is called with correct `(url, key)` args; `self.client` is set | `create_client` called once with `("https://fake.supabase.co", "fake-anon-key")`; `client.client` is the mock instance | PASS |
| `test_insert_status_log_returns_true_on_success` | Successful insert returns `True`; full method chain `table().insert().execute()` exercised | Returns `True`; `table("short_term_logs")` and `.insert({"data": ...})` called | PASS |
| `test_insert_status_log_returns_false_on_exception` | Exception during `.execute()` is caught; returns `False`; error is printed | Returns `False`; print output contains `"Supabase insert error"`; no re-raise | PASS |

---

## TestLoggerSupabaseInit

Tests for `Logger.__init__` Supabase initialization path (`utils.py` lines 38–43). `utils.SupabaseClient` is patched in every test.

| Test | What It Verifies | Expected Result | Status |
|------|-----------------|-----------------|--------|
| `test_logger_stores_supabase_client_when_init_succeeds` | `logger.supabase_client` holds the client instance when init succeeds | `logger.supabase_client` is not `None`; is the mock instance | PASS |
| `test_logger_sets_supabase_client_to_none_when_init_raises_valueerror` | Graceful degradation when `SupabaseClient()` raises `ValueError` | `logger.supabase_client is None`; warning printed with `"Warning: Supabase client failed to initialize"` | PASS |
| `test_logger_sets_supabase_client_to_none_when_init_raises_generic` | `except Exception` catches all failure types, not just `ValueError` | `logger.supabase_client is None`; Logger otherwise functional | PASS |
| `test_logger_last_supabase_write_starts_as_none` | `last_supabase_write` starts as `None` so the first `log_dict_update` call always writes | `logger.last_supabase_write is None` immediately after construction | PASS |

---

## TestSupabaseRateLimiting

Tests for the 2-second write throttle in `log_dict_update` (`utils.py` lines 172–178).

| Test | What It Verifies | Expected Result | Status |
|------|-----------------|-----------------|--------|
| `test_first_call_always_writes_to_supabase` | When `last_supabase_write is None`, the first call fires immediately | `insert_status_log` called once; `last_supabase_write` set to a `datetime` | PASS |
| `test_second_call_within_2s_is_throttled` | A call made < 2s after the previous write is suppressed | `insert_status_log` NOT called; `last_supabase_write` unchanged | PASS |
| `test_call_after_2s_elapsed_writes_to_supabase` | A call made 3s after the previous write goes through | `insert_status_log` called once | PASS |
| `test_call_exactly_at_2s_boundary_writes_to_supabase` | The `>= 2` boundary is inclusive — a call exactly 2s later fires | `insert_status_log` called once | PASS |
| `test_supabase_not_called_when_log_to_file_is_false` | `log_to_file=False` gates all Supabase access regardless of client state | `insert_status_log` never called | PASS |

---

## TestWebMonitorLogFormat

Tests for the JSON structure written to `webMonitor_log_file` in `log_dict_update` (`utils.py` lines 180–188). Uses `io.StringIO` instead of a real file.

| Test | What It Verifies | Expected Result | Status |
|------|-----------------|-----------------|--------|
| `test_webmonitor_log_entry_is_valid_json` | Each written line is parseable JSON | `json.loads()` succeeds without error | PASS |
| `test_webmonitor_log_entry_has_timestamp_and_status_keys` | Required top-level keys are present | Entry dict contains both `"timestamp"` and `"status"` | PASS |
| `test_webmonitor_log_timestamp_format` | Timestamp is `"YYYY-MM-DD HH:MM:SS"` format | `datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")` parses without error | PASS |
| `test_webmonitor_log_status_contains_dict_logger_snapshot` | Full `dict_logger` snapshot is embedded (not just the changed field); updated value is visible | All 16 schema keys present in `entry["status"]`; updated `pressure` value correct | PASS |

---

## TestDictLoggerFieldManagement

Tests for `update_field`, `clear_value`, and the `dict_logger` schema in `utils.py` (lines 44–61, 155–165).

| Test | What It Verifies | Expected Result | Status |
|------|-----------------|-----------------|--------|
| `test_dict_logger_has_all_expected_keys_on_init` | Schema has exactly the 16 expected keys, no more and no less | `set(dict_logger.keys()) == EXPECTED_DICT_LOGGER_KEYS` | PASS |
| `test_dict_logger_all_values_none_on_init` | All values start as `None` | `all(v is None for v in dict_logger.values())` | PASS |
| `test_update_field_sets_value_for_all_valid_keys` | All 16 schema keys accept writes (tested with `subTest`) | Each key shows the updated value after `update_field` | PASS |
| `test_update_field_raises_key_error_for_invalid_key` | An unrecognized key raises `KeyError` with a descriptive message | `KeyError` with message containing the key name and `"is not a valid key"` | PASS |
| `test_clear_value_sets_field_to_none` | `clear_value` resets a field back to `None` | `dict_logger["pressure"] is None` after `clear_value` | PASS |
| `test_clear_value_raises_key_error_for_invalid_key` | `clear_value` with an unrecognized key raises `KeyError` | `KeyError` with message containing the key name | PASS |
| `test_update_field_triggers_log_dict_update` | `update_field` always delegates to `log_dict_update` after modifying state | `log_dict_update` called once; argument contains the updated value | PASS |

---

## How to Re-run

```bash
# Supabase tests only
python -m pytest citestfiles/supabase/supabase_integration_test.py -v

# Full suite
python -m pytest citestfiles/ -v
```
