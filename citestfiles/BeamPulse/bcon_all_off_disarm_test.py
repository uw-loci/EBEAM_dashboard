import os
import queue
import sys
import threading
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from instrumentctl.BCON.bcon_driver import (  # noqa: E402
    BCONCommandResult,
    BCONDriver,
    COMMAND_ALL_OFF,
    REG_CMD_QUEUE_DEPTH,
    REG_COMMAND,
    REG_LAST_CMD_CODE,
    REG_LAST_CMD_RESULT,
    REG_LAST_CMD_SEQ,
    REG_LAST_REJECT_REASON,
    REG_SUP_STATE,
    TOTAL_REGS,
)
from subsystem.beam_pulse.beam_pulse import BeamPulseSubsystem  # noqa: E402


class FakeOpenSerial:
    is_open = True


def make_driver():
    driver = object.__new__(BCONDriver)
    driver.unit = 1
    driver._connected = False
    driver._serial = FakeOpenSerial()
    driver._serial_lock = threading.RLock()
    driver._write_epoch = 0
    driver._cmd_queue = queue.Queue()
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


class FakeStopAllBCONDriver:
    def __init__(self, stop_all_result):
        self.stop_all_result = stop_all_result
        self.stop_all_calls = 0
        self.reset_enable_cache_calls = []

    def stop_all(self):
        self.stop_all_calls += 1
        return self.stop_all_result

    def reset_channel_enable_cache(self, enabled=False):
        self.reset_enable_cache_calls.append(bool(enabled))


class BeamPulseDisarmBeamsTest(unittest.TestCase):
    def make_subsystem(self, stop_all_result=True):
        subsystem = object.__new__(BeamPulseSubsystem)
        subsystem.bcon_driver = FakeStopAllBCONDriver(stop_all_result)
        subsystem.beams_armed_status = True
        subsystem.beam_on_status = [True, True, False]
        subsystem.channel_enable_status = [True, False, True]
        subsystem._active_channels = {0, 1}
        subsystem._seq_stop = threading.Event()
        subsystem._seq_thread = None
        subsystem.armed_status_updates = []
        subsystem.armed_button_updates = []
        subsystem._armed_status_callback = subsystem.armed_status_updates.append
        subsystem._update_armed_button_states = subsystem.armed_button_updates.append
        subsystem._channel_enable_status_callback = None
        subsystem._beam_activity_callback = None
        subsystem._last_beam_activity_sent = True
        subsystem.log_events = []
        subsystem.logs = []
        subsystem._log_event = lambda message, level=None: subsystem.log_events.append(
            (message, level)
        )
        subsystem._log = lambda message, level=None: subsystem.logs.append((message, level))
        return subsystem

    def test_disarm_preserves_output_and_enable_state_when_all_off_unconfirmed(self):
        subsystem = self.make_subsystem(stop_all_result=False)

        ok = subsystem.disarm_beams()

        self.assertFalse(ok)
        self.assertTrue(subsystem.beams_armed_status)
        self.assertEqual(subsystem.beam_on_status, [True, True, False])
        self.assertEqual(subsystem.channel_enable_status, [True, False, True])
        self.assertEqual(subsystem._active_channels, {0, 1})
        self.assertEqual(subsystem.bcon_driver.stop_all_calls, 1)
        self.assertEqual(subsystem.bcon_driver.reset_enable_cache_calls, [])
        self.assertEqual(subsystem.armed_status_updates, [])
        self.assertEqual(subsystem.armed_button_updates, [])

    def test_disarm_clears_output_and_enable_state_after_confirmed_all_off(self):
        subsystem = self.make_subsystem(stop_all_result=True)

        ok = subsystem.disarm_beams()

        self.assertTrue(ok)
        self.assertFalse(subsystem.beams_armed_status)
        self.assertEqual(subsystem.beam_on_status, [False, False, False])
        self.assertEqual(subsystem.channel_enable_status, [False, False, False])
        self.assertEqual(subsystem._active_channels, set())
        self.assertEqual(subsystem.bcon_driver.stop_all_calls, 1)
        self.assertEqual(subsystem.bcon_driver.reset_enable_cache_calls, [False])
        self.assertEqual(subsystem.armed_status_updates, [False])
        self.assertEqual(subsystem.armed_button_updates, [False])

    def test_disarm_returns_false_without_bcon_driver(self):
        subsystem = self.make_subsystem(stop_all_result=True)
        subsystem.bcon_driver = None

        ok = subsystem.disarm_beams()

        self.assertFalse(ok)
        self.assertTrue(subsystem.beams_armed_status)
        self.assertEqual(subsystem.beam_on_status, [True, True, False])
        self.assertEqual(subsystem.channel_enable_status, [True, False, True])
        self.assertEqual(subsystem.armed_status_updates, [])
        self.assertEqual(subsystem.armed_button_updates, [])


if __name__ == "__main__":
    unittest.main()
