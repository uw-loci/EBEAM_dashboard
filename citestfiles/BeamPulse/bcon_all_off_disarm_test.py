import os
import queue
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from instrumentctl.BCON.bcon_driver import (  # noqa: E402
    BCONCommandResult,
    BCONDriver,
    COMMAND_APPLY_STAGED_MODES,
    COMMAND_ALL_OFF,
    REG_CMD_QUEUE_DEPTH,
    REG_COMMAND,
    REG_CH_STATUS_BASE,
    REG_CH_STATUS_STRIDE,
    REG_LAST_CMD_CODE,
    REG_LAST_CMD_RESULT,
    REG_LAST_CMD_SEQ,
    REG_LAST_REJECT_REASON,
    REG_SUP_STATE,
    TOTAL_REGS,
)
from subsystem.beam_pulse.beam_pulse import BeamPulseSubsystem  # noqa: E402
from utils import LogLevel  # noqa: E402


class FakeOpenSerial:
    is_open = True


class StopAfterWait:
    def __init__(self, driver):
        self.driver = driver

    def clear(self):
        pass

    def set(self):
        pass

    def wait(self, _timeout):
        self.driver._poll_running = False


def make_driver():
    driver = object.__new__(BCONDriver)
    driver.unit = 1
    driver._connected = False
    driver._serial = FakeOpenSerial()
    driver._serial_lock = threading.RLock()
    driver._write_epoch = 0
    driver._cmd_queue = queue.Queue()
    driver._queue_wake = threading.Event()
    driver._regs = [0] * TOTAL_REGS
    driver._regs_lock = threading.Lock()
    driver.COMMAND_CONFIRM_RETRIES = 1
    driver.COMMAND_CONFIRM_DELAY_S = 0
    driver.ui_messages = []
    driver.logs = []
    driver._ui_put = lambda *msg: driver.ui_messages.append(msg)
    driver._log = lambda message, level="INFO": driver.logs.append((message, level))
    return driver


def command_snapshot(seq, code=COMMAND_ALL_OFF, result=BCONCommandResult.EXECUTED):
    return {
        "supervisor_state_code": 0,
        "cmd_queue_depth": 0,
        "last_command_code": code,
        "last_command_result_code": int(result),
        "last_reject_reason_code": 0,
        "last_cmd_seq": seq,
    }


def seed_cached_command_snapshot(driver, snapshot):
    driver._regs[REG_SUP_STATE] = snapshot["supervisor_state_code"]
    driver._regs[REG_CMD_QUEUE_DEPTH] = snapshot["cmd_queue_depth"]
    driver._regs[REG_LAST_CMD_CODE] = snapshot["last_command_code"]
    driver._regs[REG_LAST_CMD_RESULT] = snapshot["last_command_result_code"]
    driver._regs[REG_LAST_REJECT_REASON] = snapshot["last_reject_reason_code"]
    driver._regs[REG_LAST_CMD_SEQ] = snapshot["last_cmd_seq"]


class BCONAllOffDriverTest(unittest.TestCase):
    def test_enqueue_write_wakes_waiting_poll_worker(self):
        driver = make_driver()

        driver.enqueue_write(10, 1)

        self.assertTrue(driver._queue_wake.is_set())
        self.assertEqual(driver._cmd_queue.get_nowait(), ("write", 10, 1, 0))

    def test_stop_poll_thread_wakes_waiting_worker(self):
        driver = make_driver()
        driver._poll_running = True
        waiting = threading.Event()

        def wait_for_wake():
            waiting.set()
            driver._queue_wake.wait(5)

        driver._poll_thread = threading.Thread(target=wait_for_wake)
        driver._poll_thread.start()
        self.assertTrue(waiting.wait(1))

        driver._stop_poll_thread()

        self.assertFalse(driver._poll_thread)

    def test_pvx_toggle_is_rate_limited_per_channel_for_150_ms(self):
        driver = make_driver()
        writes = []
        driver.write_register_immediate = lambda reg, value: writes.append((reg, value)) or True

        with patch(
            "instrumentctl.BCON.bcon_driver.time.monotonic",
            side_effect=[10.0, 10.001, 10.149, 10.151],
        ):
            self.assertTrue(driver.trigger_channel_enable_toggle(1))
            self.assertTrue(driver.trigger_channel_enable_toggle(2))
            self.assertFalse(driver.trigger_channel_enable_toggle(1))
            self.assertTrue(driver.trigger_channel_enable_toggle(1))

        self.assertEqual(writes, [(13, 1), (23, 1), (13, 1)])
        self.assertTrue(
            any(
                level == "ERROR" and "150 ms cooldown active" in message
                for message, level in driver.logs
            )
        )

    def test_pvx_toggle_writes_one_when_channel_is_not_busy(self):
        driver = make_driver()
        writes = []
        driver.write_register_immediate = lambda reg, value: writes.append((reg, value)) or True

        self.assertTrue(driver.trigger_channel_enable_toggle(3))
        self.assertEqual(writes, [(33, 1)])

    def test_forced_immediate_write_uses_cached_baseline_when_connected_flag_is_false(self):
        driver = make_driver()
        writes = []
        confirms = []
        baseline = command_snapshot(7)
        seed_cached_command_snapshot(driver, baseline)
        driver._write_register_raw = lambda reg, value: writes.append((reg, value))

        def confirm(cmd_code, baseline=None, require_connected=True):
            confirms.append((cmd_code, baseline, require_connected))
            return {"accepted": True}

        driver._confirm_command_write = confirm

        ok = driver.write_register_immediate(
            REG_COMMAND,
            COMMAND_ALL_OFF,
            require_connected=False,
        )

        self.assertTrue(ok)
        self.assertEqual(writes, [(REG_COMMAND, COMMAND_ALL_OFF)])
        self.assertEqual(confirms, [(COMMAND_ALL_OFF, baseline, False)])

    def test_immediate_command_does_not_raw_preread_before_write(self):
        driver = make_driver()
        writes = []
        confirms = []
        baseline = command_snapshot(9)
        seed_cached_command_snapshot(driver, baseline)

        def preread():
            self.fail("write_register_immediate should not raw-read before sending")

        def confirm(cmd_code, baseline=None, require_connected=True):
            confirms.append((cmd_code, baseline, require_connected))
            return {"accepted": True}

        driver._read_command_snapshot_raw = preread
        driver._write_register_raw = lambda reg, value: writes.append((reg, value))
        driver._confirm_command_write = confirm

        ok = driver.write_register_immediate(
            REG_COMMAND,
            COMMAND_ALL_OFF,
            require_connected=False,
        )

        self.assertTrue(ok)
        self.assertEqual(writes, [(REG_COMMAND, COMMAND_ALL_OFF)])
        self.assertEqual(confirms, [(COMMAND_ALL_OFF, baseline, False)])
        self.assertFalse(any(msg[0] == "error" for msg in driver.ui_messages))

    def test_stop_all_clears_queue_and_uses_forced_confirmed_write(self):
        driver = make_driver()
        driver._cmd_queue.put(("write", 10, 1))
        calls = []

        def immediate(reg, value, require_connected=True):
            calls.append((reg, value, require_connected))
            driver._cmd_queue.put(("write", 20, 2))
            return True

        driver.write_register_immediate = immediate

        self.assertTrue(driver.stop_all())
        self.assertEqual(calls, [(REG_COMMAND, COMMAND_ALL_OFF, False)])
        self.assertTrue(driver._cmd_queue.empty())
        self.assertEqual(driver._write_epoch, 1)

    def test_stale_epoch_write_is_dropped_before_serial_transaction(self):
        driver = make_driver()
        driver._write_epoch = 1
        transactions = []
        driver._serial_transaction = lambda payload, expected_min: transactions.append(
            (payload, expected_min)
        )

        ok = driver._write_register_raw(REG_COMMAND, COMMAND_ALL_OFF, epoch=0)

        self.assertFalse(ok)
        self.assertEqual(transactions, [])

    def test_current_epoch_write_reaches_serial_transaction(self):
        driver = make_driver()
        driver._write_epoch = 1
        transactions = []
        driver._serial_transaction = lambda payload, expected_min: transactions.append(
            (payload, expected_min)
        )

        ok = driver._write_register_raw(REG_COMMAND, COMMAND_ALL_OFF, epoch=1)

        self.assertTrue(ok)
        self.assertEqual(len(transactions), 1)
        self.assertEqual(transactions[0][1], 8)

    def test_executed_command_requires_sequence_advance(self):
        driver = make_driver()
        driver.COMMAND_CONFIRM_RETRIES = 2
        snapshots = [
            command_snapshot(7),
            command_snapshot(8),
        ]
        driver._read_command_snapshot_raw = lambda: snapshots.pop(0)

        result = driver._confirm_command_write(
            COMMAND_ALL_OFF,
            baseline={"last_cmd_seq": 7},
            require_connected=False,
        )

        self.assertIsNotNone(result)
        self.assertTrue(result["accepted"])

    def test_executed_command_without_sequence_advance_is_inconclusive(self):
        driver = make_driver()
        driver._read_command_snapshot_raw = lambda: command_snapshot(7)

        result = driver._confirm_command_write(
            COMMAND_ALL_OFF,
            baseline={"last_cmd_seq": 7},
            require_connected=False,
        )

        self.assertIsNone(result)
        self.assertTrue(
            any(
                msg[0] == "error" and "diagnostics were inconclusive" in msg[1]
                for msg in driver.ui_messages
            )
        )

    def test_partial_staging_failure_skips_apply_and_forces_all_off(self):
        driver = make_driver()
        driver._connected = True
        driver._poll_running = True
        driver._last_heartbeat_time = float("inf")
        driver._watchdog_timeout_ms = 1500
        driver._poll_errors = 0
        driver._failed_batches = set()
        driver._completed_stage_batches = set()
        writes = []
        all_off_calls = []

        def write(reg, value, epoch=None):
            writes.append((reg, value))
            if len(writes) == 2:
                raise RuntimeError("serial write failed")
            return True

        driver._write_register_raw = write
        driver.stop_all = lambda: all_off_calls.append(True) or True
        driver._read_holding_registers_raw = lambda _start, count: (
            setattr(driver, "_poll_running", False) or [0] * count
        )
        driver.set_channel_pulse(1, 100, operation_token="stage-failure")

        with patch("instrumentctl.BCON.bcon_driver.time.sleep", lambda _delay: None):
            driver._poll_thread_func()

        self.assertEqual(len(writes), 2)
        self.assertNotIn((REG_COMMAND, COMMAND_APPLY_STAGED_MODES), writes)
        self.assertEqual(all_off_calls, [True])
        self.assertTrue(any(
            msg[0] == "operation_failed"
            and msg[1]["token"] == "stage-failure"
            and msg[1]["critical"]
            for msg in driver.ui_messages
        ))
        self.assertTrue(any(level == "CRITICAL" for _message, level in driver.logs))

    def test_first_staging_failure_skips_apply_without_all_off(self):
        driver = make_driver()
        driver._connected = True
        driver._poll_running = True
        driver._last_heartbeat_time = float("inf")
        driver._watchdog_timeout_ms = 1500
        driver._poll_errors = 0
        driver._failed_batches = set()
        driver._completed_stage_batches = set()
        writes = []
        all_off_calls = []

        def write(reg, value, epoch=None):
            writes.append((reg, value))
            raise RuntimeError("serial write failed")

        driver._write_register_raw = write
        driver.stop_all = lambda: all_off_calls.append(True) or True
        driver._read_holding_registers_raw = lambda _start, count: (
            setattr(driver, "_poll_running", False) or [0] * count
        )
        driver.set_channel_pulse(1, 100, operation_token="first-stage-failure")

        with patch("instrumentctl.BCON.bcon_driver.time.sleep", lambda _delay: None):
            driver._poll_thread_func()

        self.assertEqual(len(writes), 1)
        self.assertNotIn((REG_COMMAND, COMMAND_APPLY_STAGED_MODES), writes)
        self.assertEqual(all_off_calls, [])
        self.assertTrue(any(
            msg[0] == "operation_failed"
            and msg[1]["token"] == "first-stage-failure"
            and not msg[1]["critical"]
            for msg in driver.ui_messages
        ))

    def test_disconnected_worker_cancels_a_token_once(self):
        driver = make_driver()
        driver._poll_running = True
        driver._queue_wake = StopAfterWait(driver)
        for reg in (10, 11, 12):
            driver.enqueue_write(reg, 1, operation_token="cancel-once", stage_write=True)

        with patch("instrumentctl.BCON.bcon_driver.time.sleep", lambda _delay: None):
            driver._poll_thread_func()

        cancellations = [
            msg for msg in driver.ui_messages
            if msg[0] == "operation_cancelled" and msg[1]["token"] == "cancel-once"
        ]
        self.assertEqual(len(cancellations), 1)


class FakeStopAllBCONDriver:
    def __init__(self, stop_all_result):
        self.stop_all_result = stop_all_result
        self.stop_all_calls = 0

    def stop_all(self):
        self.stop_all_calls += 1
        return self.stop_all_result


class FakeArmBCONDriver:
    def __init__(self, serial_exists=True, connected=True):
        self._serial = FakeOpenSerial() if serial_exists else None
        self.connected = connected

    def is_connected(self):
        return self.connected


class BeamPulseArmBeamsTest(unittest.TestCase):
    def make_subsystem(self, serial_exists=True, connected=True):
        subsystem = object.__new__(BeamPulseSubsystem)
        subsystem.bcon_driver = FakeArmBCONDriver(
            serial_exists=serial_exists,
            connected=connected,
        )
        subsystem.beams_armed_status = False
        subsystem.armed_status_updates = []
        subsystem.armed_button_updates = []
        subsystem._armed_status_callback = subsystem.armed_status_updates.append
        subsystem._update_armed_button_states = subsystem.armed_button_updates.append
        subsystem.log_events = []
        subsystem.logs = []
        subsystem._log_event = lambda message, level=None: subsystem.log_events.append(
            (message, level)
        )
        subsystem._log = lambda message, level=None: subsystem.logs.append((message, level))
        return subsystem

    def test_arm_returns_false_without_bcon_serial(self):
        subsystem = self.make_subsystem(serial_exists=False, connected=True)

        ok = subsystem.arm_beams()

        self.assertFalse(ok)
        self.assertFalse(subsystem.beams_armed_status)
        self.assertEqual(subsystem.armed_status_updates, [])
        self.assertEqual(subsystem.armed_button_updates, [])
        self.assertEqual(
            subsystem.log_events,
            [("Failed to arm beams: BCON serial port is not open", LogLevel.ERROR)],
        )

    def test_arm_returns_false_when_bcon_is_disconnected(self):
        subsystem = self.make_subsystem(serial_exists=True, connected=False)

        ok = subsystem.arm_beams()

        self.assertFalse(ok)
        self.assertFalse(subsystem.beams_armed_status)
        self.assertEqual(subsystem.armed_status_updates, [])
        self.assertEqual(subsystem.armed_button_updates, [])
        self.assertEqual(
            subsystem.log_events,
            [("Failed to arm beams: BCON device not connected", LogLevel.ERROR)],
        )

    def test_arm_sets_armed_when_bcon_serial_exists_and_connected(self):
        subsystem = self.make_subsystem(serial_exists=True, connected=True)

        ok = subsystem.arm_beams()

        self.assertTrue(ok)
        self.assertTrue(subsystem.beams_armed_status)
        self.assertEqual(subsystem.armed_status_updates, [True])
        self.assertEqual(subsystem.armed_button_updates, [True])


class BeamPulseDisarmBeamsTest(unittest.TestCase):
    def make_subsystem(self, stop_all_result=True):
        subsystem = object.__new__(BeamPulseSubsystem)
        subsystem.bcon_driver = FakeStopAllBCONDriver(stop_all_result)
        subsystem.beams_armed_status = True
        subsystem.beam_on_status = [True, True, False]
        subsystem._active_channels = {0, 1}
        subsystem._seq_stop = threading.Event()
        subsystem._seq_thread = None
        subsystem.armed_status_updates = []
        subsystem.armed_button_updates = []
        subsystem._armed_status_callback = subsystem.armed_status_updates.append
        subsystem._update_armed_button_states = subsystem.armed_button_updates.append
        subsystem._beam_activity_callback = None
        subsystem._last_beam_activity_sent = True
        subsystem.log_events = []
        subsystem.logs = []
        subsystem._log_event = lambda message, level=None: subsystem.log_events.append(
            (message, level)
        )
        subsystem._log = lambda message, level=None: subsystem.logs.append((message, level))
        return subsystem

    def test_disarm_preserves_output_state_when_all_off_unconfirmed(self):
        subsystem = self.make_subsystem(stop_all_result=False)

        ok = subsystem.disarm_beams()

        self.assertFalse(ok)
        self.assertTrue(subsystem.beams_armed_status)
        self.assertEqual(subsystem.beam_on_status, [True, True, False])
        self.assertEqual(subsystem._active_channels, {0, 1})
        self.assertEqual(subsystem.bcon_driver.stop_all_calls, 1)
        self.assertEqual(subsystem.armed_status_updates, [])
        self.assertEqual(subsystem.armed_button_updates, [])

    def test_disarm_clears_output_state_after_confirmed_all_off(self):
        subsystem = self.make_subsystem(stop_all_result=True)

        ok = subsystem.disarm_beams()

        self.assertTrue(ok)
        self.assertFalse(subsystem.beams_armed_status)
        self.assertEqual(subsystem.beam_on_status, [False, False, False])
        self.assertEqual(subsystem._active_channels, set())
        self.assertEqual(subsystem.bcon_driver.stop_all_calls, 1)
        self.assertEqual(subsystem.armed_status_updates, [False])
        self.assertEqual(subsystem.armed_button_updates, [False])

    def test_disarm_returns_false_without_bcon_driver(self):
        subsystem = self.make_subsystem(stop_all_result=True)
        subsystem.bcon_driver = None

        ok = subsystem.disarm_beams()

        self.assertFalse(ok)
        self.assertTrue(subsystem.beams_armed_status)
        self.assertEqual(subsystem.beam_on_status, [True, True, False])
        self.assertEqual(subsystem.armed_status_updates, [])
        self.assertEqual(subsystem.armed_button_updates, [])


if __name__ == "__main__":
    unittest.main()
