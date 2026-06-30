import os
import queue
import sys
import threading
import unittest

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from instrumentctl.BCON.bcon_driver import (  # noqa: E402
    BCONCommandResult,
    BCONDriver,
    COMMAND_ALL_OFF,
    REG_COMMAND,
    TOTAL_REGS,
)


class FakeOpenSerial:
    is_open = True


def make_driver():
    driver = object.__new__(BCONDriver)
    driver._connected = False
    driver._serial = FakeOpenSerial()
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


class BCONAllOffDriverTest(unittest.TestCase):
    def test_forced_immediate_write_can_use_open_serial_when_connected_flag_is_false(self):
        driver = make_driver()
        writes = []
        confirms = []
        baseline = command_snapshot(7)
        driver._read_command_snapshot_raw = lambda: baseline
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

    def test_immediate_command_sends_write_but_fails_when_preread_fails(self):
        driver = make_driver()
        writes = []

        def preread():
            raise RuntimeError("diagnostics offline")

        def confirm(*args, **kwargs):
            self.fail("write_register_immediate should not confirm without a pre-read")

        driver._read_command_snapshot_raw = preread
        driver._write_register_raw = lambda reg, value: writes.append((reg, value))
        driver._confirm_command_write = confirm

        ok = driver.write_register_immediate(
            REG_COMMAND,
            COMMAND_ALL_OFF,
            require_connected=False,
        )

        self.assertFalse(ok)
        self.assertEqual(writes, [(REG_COMMAND, COMMAND_ALL_OFF)])
        self.assertFalse(any(msg[0] == "command_result" for msg in driver.ui_messages))
        self.assertTrue(
            any(msg[0] == "error" and "confirmation pre-read failed" in msg[1]
                for msg in driver.ui_messages)
        )

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
            any(msg[0] == "error" and "diagnostics were inconclusive" in msg[1]
                for msg in driver.ui_messages)
        )


if __name__ == "__main__":
    unittest.main()
