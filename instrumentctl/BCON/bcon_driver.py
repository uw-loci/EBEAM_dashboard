"""
BCON (Beam Controller) Driver — Modbus RTU

Modbus RTU master driver for Arduino Mega running BCON firmware.
Provides register-based control, status polling, and telemetry access
for three independent pulser channels with safety interlocks.

Register map mirrors the firmware Modbus slave implementation:
  Control registers   0-2   : watchdog, telemetry, command
  Channel 1 params   10-13  : mode, pulse_ms, count, enable_toggle
  Channel 2 params   20-23  : (same layout)
  Channel 3 params   30-33  : (same layout)
  System status     100-109 : state, reason, fault, interlock, watchdog, error, supervisor, cmd status
  CH1 status        110-118 : mode_st, pulse_ms_st, count_st, remaining, ...
  CH2 status        120-128
  CH3 status        130-138
  CH1 supervisor    140-143 : run_state, stop_reason, complete, aborted
  CH2 supervisor    144-147
  CH3 supervisor    148-151
  Command diagnostics 152-153: last_reject_reason, last_cmd_seq
"""

from __future__ import annotations

import queue
import struct
import threading
import time
from typing import Optional, Dict, List
from enum import IntEnum

# pyserial — used directly for Modbus RTU (bypasses pymodbus v3 framer bug)
try:
    import serial
    import serial.tools.list_ports as list_ports
except ImportError:
    serial = None
    list_ports = None


# ======================== Register Map Constants ========================

TOTAL_REGS = 160

# --- Control registers (written by master) ---
REG_WATCHDOG_MS   = 0
REG_TELEMETRY_MS  = 1
REG_COMMAND       = 2     # 0=NOP, 3=ARM/CLEAR_FAULT

COMMAND_NOP                 = 0
COMMAND_ALL_OFF             = 1
COMMAND_CLEAR_FAULT         = 3
COMMAND_APPLY_STAGED_MODES  = 4

COMMAND_CODE_TO_LABEL = {
    COMMAND_NOP: "NOP",
    COMMAND_ALL_OFF: "ALL_OFF",
    COMMAND_CLEAR_FAULT: "CLEAR_FAULT",
    COMMAND_APPLY_STAGED_MODES: "APPLY_STAGED_MODES",
}

# --- Per-channel parameter registers ---
CH_BASE = [10, 20, 30]    # base address for CH1, CH2, CH3
CH_MODE_OFF          = 0   # offset: requested mode
CH_PULSE_MS_OFF      = 1   # offset: pulse duration (ms)
CH_COUNT_OFF         = 2   # offset: pulse count
CH_ENABLE_TOGGLE_OFF = 3   # offset: write 1 to toggle enable

# --- System status registers (read-only from master view) ---
REG_SYS_STATE      = 100
REG_SYS_REASON     = 101
REG_FAULT_LATCHED  = 102
REG_INTERLOCK_OK   = 103
REG_WATCHDOG_OK    = 104
REG_LAST_ERROR     = 105
REG_SUP_STATE      = 106
REG_CMD_QUEUE_DEPTH = 107
REG_LAST_CMD_CODE  = 108
REG_LAST_CMD_RESULT = 109

# --- Per-channel status registers (read-only from master view) ---
REG_CH_STATUS_BASE   = 110
REG_CH_STATUS_STRIDE = 10
# Offsets within each channel status block:
#   +0  mode (actual)
#   +1  pulse_ms (actual)
#   +2  count (actual)
#   +3  remaining pulses
#   +4  en_st
#   +5  pwr_st
#   +6  oc_st
#   +7  gated_st
#   +8  output_level

# --- Per-channel supervisor extension status registers (read-only) ---
REG_CH_SUP_BASE   = 140
REG_CH_SUP_STRIDE = 4

REG_LAST_REJECT_REASON = 152
REG_LAST_CMD_SEQ       = 153


# ======================== Mode Enumerations ========================

class BCONMode(IntEnum):
    """Channel operating modes (register values)."""
    OFF         = 0
    DC          = 1
    PULSE       = 2
    PULSE_TRAIN = 3

MODE_LABEL_TO_CODE = {
    "OFF":         BCONMode.OFF,
    "DC":          BCONMode.DC,
    "PULSE":       BCONMode.PULSE,
    "PULSE_TRAIN": BCONMode.PULSE_TRAIN,
}

MODE_CODE_TO_LABEL = {v: k for k, v in MODE_LABEL_TO_CODE.items()}


class BCONState(IntEnum):
    """System state codes read from REG_SYS_STATE."""
    READY          = 0
    SAFE_INTERLOCK = 1
    SAFE_WATCHDOG  = 2
    FAULT_LATCHED  = 3
    UNKNOWN        = 255

STATE_LABELS = {
    BCONState.READY:          "READY",
    BCONState.SAFE_INTERLOCK: "SAFE_INTERLOCK",
    BCONState.SAFE_WATCHDOG:  "SAFE_WATCHDOG",
    BCONState.FAULT_LATCHED:  "FAULT_LATCHED",
    BCONState.UNKNOWN:        "UNKNOWN",
}


class BCONSupervisorState(IntEnum):
    """Supervisor summary state codes read from REG_SUP_STATE."""
    IDLE                 = 0
    ACTIVE               = 1
    COMMAND_QUEUED       = 2
    SAFE_INTERLOCK_HOLD  = 3
    SAFE_WATCHDOG_HOLD   = 4
    FAULT_HOLD           = 5


SUPERVISOR_STATE_LABELS = {
    BCONSupervisorState.IDLE: "IDLE",
    BCONSupervisorState.ACTIVE: "ACTIVE",
    BCONSupervisorState.COMMAND_QUEUED: "COMMAND_QUEUED",
    BCONSupervisorState.SAFE_INTERLOCK_HOLD: "SAFE_INTERLOCK_HOLD",
    BCONSupervisorState.SAFE_WATCHDOG_HOLD: "SAFE_WATCHDOG_HOLD",
    BCONSupervisorState.FAULT_HOLD: "FAULT_HOLD",
}


class BCONChannelRunState(IntEnum):
    """Per-channel supervisor-visible semantic state."""
    OFF = 0
    STAGED = 1
    RUNNING_DC = 2
    RUNNING_PULSE = 3
    RUNNING_TRAIN = 4
    COMPLETE = 5
    ABORTED = 6


CHANNEL_RUN_STATE_LABELS = {
    BCONChannelRunState.OFF: "OFF",
    BCONChannelRunState.STAGED: "STAGED",
    BCONChannelRunState.RUNNING_DC: "RUNNING_DC",
    BCONChannelRunState.RUNNING_PULSE: "RUNNING_PULSE",
    BCONChannelRunState.RUNNING_TRAIN: "RUNNING_TRAIN",
    BCONChannelRunState.COMPLETE: "COMPLETE",
    BCONChannelRunState.ABORTED: "ABORTED",
}


class BCONStopReason(IntEnum):
    """Per-channel stop/abort reason reported by the firmware supervisor."""
    NONE = 0
    NORMAL_COMPLETE = 1
    ALL_OFF_COMMAND = 2
    SAFE_INTERLOCK = 3
    SAFE_WATCHDOG = 4
    FAULT_LATCHED = 5
    CLEAR_FAULT_COMMAND = 6


STOP_REASON_LABELS = {
    BCONStopReason.NONE: "NONE",
    BCONStopReason.NORMAL_COMPLETE: "NORMAL_COMPLETE",
    BCONStopReason.ALL_OFF_COMMAND: "ALL_OFF_COMMAND",
    BCONStopReason.SAFE_INTERLOCK: "SAFE_INTERLOCK",
    BCONStopReason.SAFE_WATCHDOG: "SAFE_WATCHDOG",
    BCONStopReason.FAULT_LATCHED: "FAULT_LATCHED",
    BCONStopReason.CLEAR_FAULT_COMMAND: "CLEAR_FAULT_COMMAND",
}


class BCONCommandResult(IntEnum):
    """Last-command execution status reported by the firmware."""
    NONE = 0
    QUEUED = 1
    EXECUTED = 2
    REJECTED = 3


COMMAND_RESULT_LABELS = {
    BCONCommandResult.NONE: "NONE",
    BCONCommandResult.QUEUED: "QUEUED",
    BCONCommandResult.EXECUTED: "EXECUTED",
    BCONCommandResult.REJECTED: "REJECTED",
}


class BCONRejectReason(IntEnum):
    """Reason the most recent firmware command was rejected."""
    NONE = 0
    INVALID_COMMAND = 1
    QUEUE_FULL = 2
    UNSAFE_INTERLOCK = 3
    UNSAFE_WATCHDOG = 4
    FAULT_LATCHED = 5
    CLEAR_FAULT_WHILE_INTERLOCK_OPEN = 6


REJECT_REASON_LABELS = {
    BCONRejectReason.NONE: "NONE",
    BCONRejectReason.INVALID_COMMAND: "INVALID_COMMAND",
    BCONRejectReason.QUEUE_FULL: "QUEUE_FULL",
    BCONRejectReason.UNSAFE_INTERLOCK: "UNSAFE_INTERLOCK",
    BCONRejectReason.UNSAFE_WATCHDOG: "UNSAFE_WATCHDOG",
    BCONRejectReason.FAULT_LATCHED: "FAULT_LATCHED",
    BCONRejectReason.CLEAR_FAULT_WHILE_INTERLOCK_OPEN: "CLEAR_FAULT_WHILE_INTERLOCK_OPEN",
}


# ======================== Utility ========================

def scan_serial_ports() -> List[str]:
    """Return a list of available serial ports, with Arduino-like ports first."""
    if list_ports is None:
        return []
    ports = list_ports.comports()
    preferred, others = [], []
    for p in ports:
        desc = (getattr(p, "description", "") or "").lower()
        hwid = (getattr(p, "hwid", "") or "").lower()
        if any(tok in desc for tok in ("arduino", "usb serial", "ch340", "cp210")) or "vid:pid=2341" in hwid:
            preferred.append(p.device)
        else:
            others.append(p.device)
    return preferred + others


# ======================== BCONDriver ========================

class BCONDriver:
    """
    BCON (Beam Controller) Modbus RTU driver.

    Communicates with Arduino Mega running BCON firmware over Modbus RTU
    to control three independent pulser channels with safety interlocks.

    Features:
        - Raw Modbus RTU serial communication over pyserial
        - Background register polling thread
        - Thread-safe register cache
        - Write queue for non-blocking control
        - Staged/apply channel control aligned with current firmware
        - Watchdog and fault management
        - Auto-disconnect on repeated poll failures
    """

    # Defaults
    DEFAULT_BAUD       = 115200
    DEFAULT_UNIT       = 1
    DEFAULT_TIMEOUT    = 1.0
    POLL_INTERVAL      = 0.5     # seconds between register polls
    MAX_POLL_ERRORS    = 15      # consecutive failures before auto-disconnect
    SETTLE_TIME        = 4.5     # seconds to wait after opening port (Arduino DTR reset)
    WATCHDOG_HEARTBEAT_S = 1.0   # write watchdog register this often (firmware default: 2000ms)
    COMMAND_CONFIRM_RETRIES = 4
    COMMAND_CONFIRM_DELAY_S = 0.02

    def __init__(self, port: str, baudrate: int = DEFAULT_BAUD,
                 unit: int = DEFAULT_UNIT, timeout: float = DEFAULT_TIMEOUT,
                 debug: bool = False):
        """
        Initialize BCON driver.

        Args:
            port: Serial port name (e.g., 'COM3')
            baudrate: Serial baudrate (default: 115200)
            unit: Modbus slave/unit address (default: 1)
            timeout: Modbus read timeout in seconds (default: 1.0)
            debug: Enable debug logging (default: False)
        """
        self.port = port
        self.baudrate = baudrate
        self.unit = unit
        self.timeout = timeout
        self.debug = debug

        # Serial port (raw pyserial — replaces pymodbus which has a v3 framer bug)
        self._serial: Optional[serial.Serial] = None
        self._serial_lock = threading.Lock()  # serialize all serial I/O
        self._connected = False

        # Write command queue (thread-safe)
        self._cmd_queue: queue.Queue = queue.Queue()

        # Latest register snapshot
        self._regs: List[int] = [0] * TOTAL_REGS
        self._regs_lock = threading.Lock()

        # Polling thread
        self._poll_thread: Optional[threading.Thread] = None
        self._poll_running = False
        self._poll_errors = 0

        # Callbacks for UI notification  (msg_type, *args)
        self._ui_queue: Optional[queue.Queue] = None

        self._user_requested_disconnect = False
        self._last_heartbeat_time: float = 0.0  # tracks last watchdog write
        self._channel_enable_shadow: List[bool] = [False, False, False]

    def set_ui_queue(self, q: queue.Queue):
        """Set an optional queue to receive UI notification messages."""
        self._ui_queue = q

    def _ui_put(self, *msg):
        """Post a message to the UI queue if one is set."""
        if self._ui_queue:
            self._ui_queue.put(msg)

    # ------------------------------------------------------------------ #
    #                           Logging                                    #
    # ------------------------------------------------------------------ #

    def _log(self, message: str, level: str = "INFO"):
        """Internal logging helper."""
        if self.debug or level in ("ERROR", "WARNING"):
            print(f"[BCON {level}] {message}")

    def _reset_cached_state(self):
        """Clear cached registers and best-effort local shadow state."""
        with self._regs_lock:
            self._regs = [0] * TOTAL_REGS
            self._channel_enable_shadow = [False, False, False]
        self._last_heartbeat_time = 0.0

    def reset_channel_enable_cache(self, enabled: bool = False):
        """Reset the software-only channel enable shadow used by the dashboard UI."""
        with self._regs_lock:
            self._channel_enable_shadow = [bool(enabled)] * 3

    @staticmethod
    def _command_label(cmd_code: int) -> str:
        """Map a command register value to a stable label."""
        return COMMAND_CODE_TO_LABEL.get(int(cmd_code), f"UNKNOWN({int(cmd_code)})")

    def _get_cached_command_snapshot(self) -> Dict[str, int]:
        """Read the currently cached firmware command-diagnostic registers."""
        with self._regs_lock:
            return {
                'supervisor_state_code': self._regs[REG_SUP_STATE],
                'cmd_queue_depth': self._regs[REG_CMD_QUEUE_DEPTH],
                'last_command_code': self._regs[REG_LAST_CMD_CODE],
                'last_command_result_code': self._regs[REG_LAST_CMD_RESULT],
                'last_reject_reason_code': self._regs[REG_LAST_REJECT_REASON],
                'last_cmd_seq': self._regs[REG_LAST_CMD_SEQ],
            }

    def _read_command_snapshot_raw(self) -> Dict[str, int]:
        """Read command diagnostics directly after a COMMAND write."""
        supervisor_block = self._read_holding_registers_raw(REG_SUP_STATE, 4)
        diag_block = self._read_holding_registers_raw(REG_LAST_REJECT_REASON, 2)

        snapshot = {
            'supervisor_state_code': supervisor_block[0],
            'cmd_queue_depth': supervisor_block[1],
            'last_command_code': supervisor_block[2],
            'last_command_result_code': supervisor_block[3],
            'last_reject_reason_code': diag_block[0],
            'last_cmd_seq': diag_block[1],
        }

        with self._regs_lock:
            self._regs[REG_SUP_STATE:REG_SUP_STATE + 4] = supervisor_block
            self._regs[REG_LAST_REJECT_REASON:REG_LAST_REJECT_REASON + 2] = diag_block

        return snapshot

    def _build_command_result_payload(
        self,
        requested_code: int,
        snapshot: Dict[str, int],
        baseline: Optional[Dict[str, int]] = None,
    ) -> Dict[str, object]:
        """Translate raw command diagnostics into a UI-friendly payload."""
        result_code = snapshot['last_command_result_code']
        reject_code = snapshot['last_reject_reason_code']
        actual_code = snapshot['last_command_code']
        return {
            'requested_code': int(requested_code),
            'requested_label': self._command_label(requested_code),
            'last_command_code': actual_code,
            'last_command_label': self._command_label(actual_code),
            'last_command_result': self._label_from_code(
                result_code, BCONCommandResult, COMMAND_RESULT_LABELS),
            'last_command_result_code': result_code,
            'last_reject_reason': self._label_from_code(
                reject_code, BCONRejectReason, REJECT_REASON_LABELS),
            'last_reject_reason_code': reject_code,
            'last_cmd_seq': snapshot['last_cmd_seq'],
            'supervisor_state': self._label_from_code(
                snapshot['supervisor_state_code'], BCONSupervisorState, SUPERVISOR_STATE_LABELS),
            'supervisor_state_code': snapshot['supervisor_state_code'],
            'cmd_queue_depth': snapshot['cmd_queue_depth'],
            'accepted': result_code == int(BCONCommandResult.EXECUTED),
            'rejected': result_code == int(BCONCommandResult.REJECTED),
            'fresh_snapshot': baseline is None or snapshot != baseline,
        }

    def _confirm_command_write(
        self,
        cmd_code: int,
        baseline: Optional[Dict[str, int]] = None,
    ) -> Optional[Dict[str, object]]:
        """Confirm a nonzero COMMAND write from LAST_CMD diagnostics."""
        cmd_code = int(cmd_code)
        if cmd_code == COMMAND_NOP or not (self._serial and self._connected):
            return None

        if baseline is None:
            baseline = self._get_cached_command_snapshot()

        last_error: Optional[Exception] = None
        last_snapshot: Optional[Dict[str, int]] = None

        for attempt in range(self.COMMAND_CONFIRM_RETRIES):
            try:
                snapshot = self._read_command_snapshot_raw()
                last_snapshot = snapshot
                if (
                    snapshot['last_command_code'] == cmd_code
                    and snapshot['last_command_result_code'] in (
                        int(BCONCommandResult.EXECUTED),
                        int(BCONCommandResult.REJECTED),
                    )
                ):
                    payload = self._build_command_result_payload(cmd_code, snapshot, baseline)
                    if payload['rejected']:
                        self._log(
                            f"Command {payload['requested_label']} rejected: "
                            f"{payload['last_reject_reason']} "
                            f"(seq={payload['last_cmd_seq']})",
                            "WARNING",
                        )
                    elif self.debug:
                        self._log(
                            f"Command {payload['requested_label']} executed "
                            f"(seq={payload['last_cmd_seq']})",
                            "INFO",
                        )
                    self._ui_put("command_result", payload)
                    return payload
            except Exception as exc:
                last_error = exc

            if attempt < self.COMMAND_CONFIRM_RETRIES - 1:
                time.sleep(self.COMMAND_CONFIRM_DELAY_S)

        if last_error is not None:
            message = (
                f"Command {self._command_label(cmd_code)} write completed, "
                f"but diagnostics read failed: {last_error}"
            )
        elif last_snapshot is not None:
            message = (
                f"Command {self._command_label(cmd_code)} write completed, "
                f"but diagnostics were inconclusive "
                f"(last_code={last_snapshot['last_command_code']}, "
                f"result={last_snapshot['last_command_result_code']}, "
                f"reject={last_snapshot['last_reject_reason_code']}, "
                f"seq={last_snapshot['last_cmd_seq']})"
            )
        else:
            message = (
                f"Command {self._command_label(cmd_code)} write completed, "
                f"but diagnostics were unavailable"
            )

        self._log(message, "WARNING")
        self._ui_put("error", message)
        return None

    # ================================================================== #
    #                       Connection Management                          #
    # ================================================================== #

    def connect(self, settle_s: Optional[float] = None) -> bool:
        """
        Connect to BCON hardware via Modbus RTU.

        Opening the serial port asserts DTR which resets the Arduino Mega.
        The driver waits *settle_s* seconds for the firmware to finish setup()
        before sending any Modbus frames.

        Args:
            settle_s: Seconds to wait after port open (default: SETTLE_TIME).

        Returns:
            True if connection successful, False otherwise.
        """
        if serial is None:
            self._log("pyserial is not installed", "ERROR")
            return False

        if settle_s is None:
            settle_s = self.SETTLE_TIME

        if self._serial:
            try:
                self._serial.close()
            except Exception:
                pass

        try:
            self._serial = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=self.timeout,
            )
            ok = self._serial.is_open
        except Exception as e:
            self._serial = None
            self._connected = False
            self._reset_cached_state()
            self._log(f"Connect failed: {e}", "ERROR")
            self._ui_put("connected", False)
            return False

        if ok and settle_s > 0:
            self._log(f"Waiting {settle_s}s for firmware boot…", "INFO")
            time.sleep(settle_s)

            # Flush any stale bytes left by the bootloader
            try:
                self._serial.reset_input_buffer()
                self._serial.reset_output_buffer()
                self._log("Serial buffers flushed after settle", "INFO")
            except Exception as e:
                self._log(f"Buffer flush warning: {e}", "WARNING")

            # Validate communication with a test write + read
            try:
                self._write_register_raw(REG_WATCHDOG_MS, 2000)
                self._log("Watchdog heartbeat sent", "INFO")
            except Exception as e:
                self._log(f"Post-settle watchdog write failed: {e}", "WARNING")

            try:
                vals = self._read_holding_registers_raw(0, 3)
                self._log(f"Test read(0,3) OK: {vals}", "INFO")
            except Exception as e:
                self._log(f"Test read failed: {e}", "ERROR")
                ok = False

        self._connected = ok
        self._poll_errors = 0
        self._reset_cached_state()

        if ok:
            self._user_requested_disconnect = False
            self._log(f"Connected to {self.port} at {self.baudrate} baud (unit={self.unit})", "INFO")
            self._start_poll_thread()
        else:
            self._log("Modbus connect() returned False", "ERROR")

        self._ui_put("connected", ok)
        return ok

    def disconnect(self):
        """Disconnect from BCON hardware."""
        self._user_requested_disconnect = True
        self._stop_poll_thread()
        self._connected = False
        self._poll_errors = 0
        if self._serial:
            try:
                self._serial.close()
            except Exception:
                pass
            self._serial = None
        self._reset_cached_state()
        self._log("Disconnected", "INFO")
        self._ui_put("connected", False)

    def is_connected(self) -> bool:
        """Check if connected to BCON hardware."""
        return self._connected and self._serial is not None

    # ================================================================== #
    #          Raw Modbus RTU I/O  (bypasses pymodbus v3 framer bug)       #
    # ================================================================== #

    @staticmethod
    def _modbus_crc16(data: bytes) -> int:
        """Compute Modbus CRC-16."""
        crc = 0xFFFF
        for byte in data:
            crc ^= byte
            for _ in range(8):
                if crc & 1:
                    crc = (crc >> 1) ^ 0xA001
                else:
                    crc >>= 1
        return crc

    def _serial_transaction(self, request_payload: bytes, expected_min: int) -> bytes:
        """
        Send a Modbus RTU frame and read the response.

        Args:
            request_payload: Frame bytes WITHOUT CRC (slave + FC + data)
            expected_min: Minimum expected response bytes (including CRC)

        Returns:
            Response payload (without CRC), or raises RuntimeError.
        """
        crc = self._modbus_crc16(request_payload)
        frame = request_payload + struct.pack("<H", crc)

        with self._serial_lock:
            ser = self._serial
            if not ser or not ser.is_open:
                raise RuntimeError("Serial port not open")

            # Drain any stale bytes before sending
            if ser.in_waiting:
                ser.read(ser.in_waiting)

            ser.write(frame)
            ser.flush()

            # Read the response.  First read minimum expected bytes, then
            # consume any additional bytes that arrive (for variable-length
            # responses like FC 0x03).
            response = ser.read(expected_min)
            if not response:
                raise RuntimeError(f"No response (0 bytes in {self.timeout}s)")

            # For FC 0x03, the 3rd byte is the byte-count; we may need more
            time.sleep(0.005)  # 5 ms for any trailing bytes to arrive
            if ser.in_waiting:
                response += ser.read(ser.in_waiting)

        if len(response) < 4:
            raise RuntimeError(
                f"Short response: {len(response)} bytes "
                f"(hex: {' '.join(f'{b:02X}' for b in response)})")

        # Verify CRC
        rx_crc = struct.unpack("<H", response[-2:])[0]
        calc_crc = self._modbus_crc16(response[:-2])
        if rx_crc != calc_crc:
            raise RuntimeError(
                f"CRC mismatch: rx=0x{rx_crc:04X} calc=0x{calc_crc:04X}")

        # Check for Modbus exception response (FC | 0x80)
        if response[1] & 0x80:
            ex_code = response[2] if len(response) > 2 else 0xFF
            raise RuntimeError(
                f"Modbus exception: FC=0x{response[1]:02X} code={ex_code}")

        return response[:-2]  # strip CRC

    def _write_register_raw(self, reg: int, val: int):
        """Write a single holding register (FC 0x06) via raw serial."""
        payload = struct.pack(">BBHH", self.unit, 0x06, reg, int(val) & 0xFFFF)
        self._serial_transaction(payload, 8)  # FC 0x06 response is always 8 bytes

    def _read_holding_registers_raw(self, start: int, count: int) -> list:
        """Read holding registers (FC 0x03) via raw serial. Returns list of ints."""
        payload = struct.pack(">BBHH", self.unit, 0x03, start, count)
        # Response: slave(1) + FC(1) + bytecount(1) + data(2*count) + CRC(2)
        expected = 3 + 2 * count + 2
        resp = self._serial_transaction(payload, expected)
        # Parse register values from response payload (skip slave + FC + bytecount)
        byte_count = resp[2]
        values = []
        for i in range(0, byte_count, 2):
            values.append(struct.unpack(">H", resp[3 + i:5 + i])[0])
        return values

    # ================================================================== #
    #                        Write Queue                                   #
    # ================================================================== #

    def enqueue_write(self, reg: int, value: int):
        """
        Enqueue a register write to be executed by the poll thread.

        This is the primary way to send commands from the UI thread.
        Writes are executed before each poll cycle to minimise latency.

        Args:
            reg: Register address.
            value: 16-bit unsigned value.
        """
        self._cmd_queue.put(("write", reg, value))

    def write_register_immediate(self, reg: int, value: int) -> bool:
        """
        Write a register synchronously (blocks until complete).

        Use this only when you need confirmation; prefer enqueue_write()
        for non-blocking UI interaction. Nonzero COMMAND writes are confirmed
        from LAST_CMD diagnostics rather than queue-depth or register echo timing.

        Returns:
            True if the write succeeded. For nonzero COMMAND writes, True means
            the firmware reported EXECUTED and False means rejected or inconclusive.
        """
        if not self.is_connected():
            return False

        reg = int(reg)
        value = int(value)
        baseline = None
        if reg == REG_COMMAND and value != COMMAND_NOP:
            baseline = self._get_cached_command_snapshot()

        try:
            self._write_register_raw(reg, value)
            if baseline is not None:
                result = self._confirm_command_write(value, baseline=baseline)
                return bool(result and result.get('accepted'))
            return True
        except Exception as e:
            self._log(f"Immediate write reg {reg}: {e}", "ERROR")
            return False

    # ================================================================== #
    #                  Background Polling Thread                            #
    # ================================================================== #

    def _poll_thread_func(self):
        """Background thread: process write queue then poll registers."""
        last_error_msg = None

        # Brief initial settle before the first poll cycle.  Opening the serial
        # port (even without DTR) can cause brief USB-CDC enumeration traffic;
        # waiting here prevents that traffic from disrupting the first reads.
        time.sleep(1.0)

        while self._poll_running:
            now = time.monotonic()

            # --- Watchdog heartbeat (keeps firmware from timing out) ---
            # Send a write to REG_WATCHDOG_MS if no queued writes are pending
            # and enough time has elapsed. This prevents the firmware's software
            # watchdog from expiring and forcing all channels OFF.
            if (self._serial and self._connected
                    and self._cmd_queue.empty()
                    and (now - self._last_heartbeat_time) >= self.WATCHDOG_HEARTBEAT_S):
                try:
                    self._write_register_raw(REG_WATCHDOG_MS, 2000)
                    self._last_heartbeat_time = now
                except Exception as e:
                    self._log(f"Watchdog heartbeat failed: {e}", "WARNING")

            # --- Process queued writes ---
            try:
                while not self._cmd_queue.empty():
                    cmd = self._cmd_queue.get_nowait()
                    if cmd[0] == "write" and self._serial and self._connected:
                        _, reg, val = cmd
                        reg = int(reg)
                        val = int(val)
                        baseline = None
                        if reg == REG_COMMAND and val != COMMAND_NOP:
                            baseline = self._get_cached_command_snapshot()
                        try:
                            self._write_register_raw(reg, val)
                            self._ui_put("wrote", reg, val)
                            if baseline is not None:
                                self._confirm_command_write(val, baseline=baseline)
                        except Exception as e:
                            self._log(f"Write reg {reg}: {e}", "ERROR")
                            self._ui_put("error", f"Write reg {reg}: {e}")
            except queue.Empty:
                pass

            # --- Poll registers ---
            if self._serial and self._connected:
                try:
                    regs = [0] * TOTAL_REGS

                    def read_block(start, count):
                        try:
                            vals = self._read_holding_registers_raw(start, count)
                            for i, value in enumerate(vals):
                                idx = start + i
                                if 0 <= idx < TOTAL_REGS:
                                    regs[idx] = value
                            return True
                        except Exception as e:
                            self._log(f"  read_block({start}, {count}) FAILED: {e}", "WARNING")
                            return False

                    ok = True
                    # Read only the register addresses that the firmware actually
                    # defines. Registers 3-9, 14-19, and 24-29 are gaps in the
                    # control map, while channel status omits the +9 stride slot.
                    ok &= read_block(0, 3)       # control: watchdog(0), telemetry(1), command(2)
                    ok &= read_block(10, 4)      # CH1 params: mode, pulse_ms, count, enable_toggle
                    ok &= read_block(20, 4)      # CH2 params
                    ok &= read_block(30, 4)      # CH3 params
                    ok &= read_block(100, 10)    # system + supervisor status (100-109)
                    ok &= read_block(110, 9)     # CH1 status (110-118)
                    ok &= read_block(120, 9)     # CH2 status (120-128)
                    ok &= read_block(130, 9)     # CH3 status (130-138)
                    ok &= read_block(140, 12)    # CH1-CH3 supervisor status (140-151)
                    ok &= read_block(152, 2)     # last reject reason + last cmd seq

                    if not ok:
                        self._poll_errors += 1
                        err = f"Modbus read failed ({self._poll_errors}/{self.MAX_POLL_ERRORS})"
                        if err != last_error_msg:
                            self._log(err, "WARNING")
                            self._ui_put("error", err)
                            last_error_msg = err
                        if self._poll_errors >= self.MAX_POLL_ERRORS:
                            self._auto_disconnect()
                    else:
                        self._poll_errors = 0
                        last_error_msg = None
                        with self._regs_lock:
                            changed = (regs != self._regs)
                            self._regs = regs
                        if changed:
                            self._ui_put("regs", regs)

                except Exception as e:
                    self._poll_errors += 1
                    err = f"Poll error ({self._poll_errors}/{self.MAX_POLL_ERRORS}): {e}"
                    if err != last_error_msg:
                        self._log(err, "WARNING")
                        self._ui_put("error", err)
                        last_error_msg = err
                    if self._poll_errors >= self.MAX_POLL_ERRORS:
                        self._auto_disconnect()

            time.sleep(self.POLL_INTERVAL)

    def _auto_disconnect(self):
        """Called from poll thread when too many consecutive errors."""
        self._connected = False
        self._poll_running = False   # tell the poll thread to exit cleanly
        if self._serial:
            try:
                self._serial.close()
            except Exception:
                pass
            self._serial = None
        self._poll_errors = 0
        self._reset_cached_state()
        self._log("Auto-disconnected after repeated poll failures", "WARNING")
        self._ui_put("connected", False)

    def _start_poll_thread(self):
        """Start the background polling thread."""
        if self._poll_thread and self._poll_thread.is_alive():
            return
        self._poll_running = True
        self._poll_thread = threading.Thread(target=self._poll_thread_func, daemon=True)
        self._poll_thread.start()

    def _stop_poll_thread(self):
        """Stop the background polling thread."""
        self._poll_running = False
        if self._poll_thread:
            self._poll_thread.join(timeout=3.0)
            self._poll_thread = None

    # ================================================================== #
    #                      Register Cache Access                           #
    # ================================================================== #

    def get_registers(self) -> List[int]:
        """Get a thread-safe copy of the latest register snapshot."""
        with self._regs_lock:
            return self._regs.copy()

    def get_register(self, addr: int) -> int:
        """Get a single register value from the cache."""
        with self._regs_lock:
            if 0 <= addr < TOTAL_REGS:
                return self._regs[addr]
            return 0

    # ================================================================== #
    #                     High-Level Channel Control                       #
    # ================================================================== #

    def _validate_channel(self, channel: int) -> bool:
        """Validate a 1-based channel number."""
        if 1 <= channel <= 3:
            return True
        self._log(f"Invalid channel: {channel} (must be 1-3)", "ERROR")
        return False

    def _stage_channel_mode(self, channel: int, mode_code: int,
                            duration_ms: Optional[int] = None,
                            count: Optional[int] = None) -> bool:
        """Stage parameters plus requested mode without committing them yet."""
        if not self._validate_channel(channel):
            return False

        base = CH_BASE[channel - 1]
        mode_code = int(mode_code)

        if mode_code not in (int(BCONMode.OFF), int(BCONMode.DC)):
            if duration_ms is None or not (1 <= int(duration_ms) <= 60000):
                self._log(f"Invalid pulse duration: {duration_ms}", "ERROR")
                return False
            if count is None or not (1 <= int(count) <= 10000):
                self._log(f"Invalid pulse count: {count}", "ERROR")
                return False
            self.enqueue_write(base + CH_PULSE_MS_OFF, int(duration_ms))
            self.enqueue_write(base + CH_COUNT_OFF, int(count))

        self.enqueue_write(base + CH_MODE_OFF, mode_code)
        return True

    def apply_staged_modes(self) -> None:
        """Commit any staged channel mode writes in the firmware."""
        self.send_command(COMMAND_APPLY_STAGED_MODES)

    def set_channel_off(self, channel: int) -> None:
        """Stage OFF for one channel and apply it immediately."""
        if self._stage_channel_mode(channel, BCONMode.OFF):
            self.apply_staged_modes()

    def set_channel_dc(self, channel: int) -> None:
        """Stage DC for one channel and apply it immediately."""
        if self._stage_channel_mode(channel, BCONMode.DC):
            self.apply_staged_modes()

    def set_channel_pulse(self, channel: int, duration_ms: int, count: int = 1) -> None:
        """Stage a single pulse request and apply it immediately."""
        if count < 1:
            self._log(f"PULSE requires count >= 1, got {count}", "ERROR")
            return

        effective_mode = BCONMode.PULSE if count == 1 else BCONMode.PULSE_TRAIN
        if count > 1:
            self._log(
                f"PULSE request for CH{channel} promoted to PULSE_TRAIN because count={count}",
                "WARNING",
            )

        if self._stage_channel_mode(channel, effective_mode, duration_ms=duration_ms, count=count):
            self.apply_staged_modes()

    def set_channel_pulse_train(self, channel: int, duration_ms: int, count: int) -> None:
        """Stage a pulse-train request and apply it immediately."""
        if count < 2:
            self._log(f"PULSE_TRAIN requires count >= 2, got {count}", "ERROR")
            return
        if self._stage_channel_mode(channel, BCONMode.PULSE_TRAIN, duration_ms=duration_ms, count=count):
            self.apply_staged_modes()

    def set_channel_mode(self, channel: int, mode: str,
                         duration_ms: int = 100, count: int = 1) -> None:
        """Generic immediate mode setter built on the firmware stage/apply flow."""
        mode_upper = mode.strip().upper()
        if mode_upper == "OFF":
            self.set_channel_off(channel)
        elif mode_upper == "DC":
            self.set_channel_dc(channel)
        elif mode_upper == "PULSE":
            self.set_channel_pulse(channel, duration_ms, count)
        elif mode_upper == "PULSE_TRAIN":
            self.set_channel_pulse_train(channel, duration_ms, count)
        else:
            self._log(f"Unknown mode '{mode}'", "ERROR")

    def set_channel_params(self, channel: int, duration_ms: int, count: int) -> None:
        """Write pulse parameters without changing staged or active mode."""
        if not self._validate_channel(channel):
            return
        base = CH_BASE[channel - 1]
        if duration_ms > 0:
            if not (1 <= int(duration_ms) <= 60000):
                self._log(f"Invalid pulse duration: {duration_ms}", "ERROR")
                return
            self.enqueue_write(base + CH_PULSE_MS_OFF, int(duration_ms))
        if count > 0:
            if not (1 <= int(count) <= 10000):
                self._log(f"Invalid pulse count: {count}", "ERROR")
                return
            self.enqueue_write(base + CH_COUNT_OFF, int(count))

    def toggle_channel_enable(self, channel: int) -> None:
        """Pulse the channel's enable-toggle output and update the UI shadow state."""
        if not self._validate_channel(channel):
            return
        base = CH_BASE[channel - 1]
        with self._regs_lock:
            self._channel_enable_shadow[channel - 1] = not self._channel_enable_shadow[channel - 1]
        self.enqueue_write(base + CH_ENABLE_TOGGLE_OFF, 1)

    def stop_all(self) -> None:
        """Force all three channels OFF using the firmware's dedicated command."""
        self.send_command(COMMAND_ALL_OFF)

    # ================================================================== #
    #              Synchronous Multi-Channel Start/Stop                    #
    # ================================================================== #

    def sync_start(self, configs: List[Dict]) -> None:
        """
        Stage multiple channel updates, then commit them together with COMMAND=4.

        Args:
            configs: List of dicts with keys:
                     ch (int 1-3), mode (str), duration_ms (int), count (int)
        """
        if not configs:
            return

        normalized = []
        for cfg in configs:
            try:
                ch = int(cfg['ch'])
            except Exception:
                self._log(f"Invalid sync config channel: {cfg!r}", "ERROR")
                return

            if not self._validate_channel(ch):
                return

            mode_label = str(cfg.get('mode', 'OFF')).strip().upper()
            if mode_label not in MODE_LABEL_TO_CODE:
                self._log(f"Unknown sync mode '{mode_label}' for CH{ch}", "ERROR")
                return

            duration_ms = int(cfg.get('duration_ms', 100) or 100)
            count = int(cfg.get('count', 1) or 1)
            mode_code = MODE_LABEL_TO_CODE[mode_label]

            if mode_code == BCONMode.PULSE:
                if count < 1:
                    self._log(f"CH{ch}: PULSE requires count >= 1", "ERROR")
                    return
                if count > 1:
                    mode_code = BCONMode.PULSE_TRAIN
            elif mode_code == BCONMode.PULSE_TRAIN:
                if count < 2:
                    self._log(f"CH{ch}: PULSE_TRAIN requires count >= 2", "ERROR")
                    return

            if mode_code not in (BCONMode.OFF, BCONMode.DC):
                if not (1 <= duration_ms <= 60000):
                    self._log(f"CH{ch}: invalid pulse duration {duration_ms}", "ERROR")
                    return
                if not (1 <= count <= 10000):
                    self._log(f"CH{ch}: invalid pulse count {count}", "ERROR")
                    return

            normalized.append({
                'ch': ch,
                'mode_code': int(mode_code),
                'duration_ms': duration_ms,
                'count': count,
            })

        for cfg in normalized:
            if cfg['mode_code'] in (int(BCONMode.OFF), int(BCONMode.DC)):
                continue
            base = CH_BASE[cfg['ch'] - 1]
            self.enqueue_write(base + CH_PULSE_MS_OFF, cfg['duration_ms'])
            self.enqueue_write(base + CH_COUNT_OFF, cfg['count'])

        for cfg in normalized:
            self.enqueue_write(CH_BASE[cfg['ch'] - 1] + CH_MODE_OFF, cfg['mode_code'])

        self.apply_staged_modes()

    # ================================================================== #
    #                      System Configuration                            #
    # ================================================================== #

    def set_watchdog(self, timeout_ms: int) -> None:
        """
        Configure communication watchdog timeout.

        Args:
            timeout_ms: Watchdog timeout in milliseconds.
        """
        self.enqueue_write(REG_WATCHDOG_MS, timeout_ms)

    def set_telemetry(self, interval_ms: int) -> None:
        """
        Configure periodic telemetry/polling interval on the firmware side.

        Args:
            interval_ms: Telemetry interval in milliseconds (0 to disable).
        """
        self.enqueue_write(REG_TELEMETRY_MS, interval_ms)

    def send_command(self, cmd_code: int) -> None:
        """
        Queue a write to the special COMMAND register.

        Nonzero commands are confirmed from LAST_CMD diagnostics after the
        write completes; queue-depth and COMMAND echo timing are not used as
        completion handshakes.
        """
        self.enqueue_write(REG_COMMAND, int(cmd_code))

    # ================================================================== #
    #                     Safety / Fault Management                        #
    # ================================================================== #

    def arm(self) -> None:
        """Send the firmware clear-fault / re-arm command."""
        self.send_command(COMMAND_CLEAR_FAULT)

    def clear_fault(self) -> None:
        """Alias for arm()."""
        self.arm()

    # ================================================================== #
    #                     Status / Telemetry Access                        #
    # ================================================================== #

    @staticmethod
    def _label_from_code(code: int, enum_type: type[IntEnum], labels: Dict[IntEnum, str]) -> str:
        """Map an integer register value to a stable label."""
        try:
            return labels.get(enum_type(code), "UNKNOWN")
        except ValueError:
            return "UNKNOWN"

    def get_system_state(self) -> str:
        """Get current top-level safety state as a human-readable string."""
        return self._label_from_code(self.get_register(REG_SYS_STATE), BCONState, STATE_LABELS)

    def get_system_state_code(self) -> int:
        """Get raw system state register value."""
        return self.get_register(REG_SYS_STATE)

    def get_supervisor_state(self) -> str:
        """Get the firmware supervisor summary state as a label."""
        return self._label_from_code(
            self.get_register(REG_SUP_STATE),
            BCONSupervisorState,
            SUPERVISOR_STATE_LABELS,
        )

    def get_supervisor_state_code(self) -> int:
        """Get raw supervisor summary state register value."""
        return self.get_register(REG_SUP_STATE)

    def is_interlock_ok(self) -> bool:
        """Check if the hardware interlock is satisfied."""
        return bool(self.get_register(REG_INTERLOCK_OK))

    def is_watchdog_ok(self) -> bool:
        """Check if the communication watchdog is satisfied."""
        return bool(self.get_register(REG_WATCHDOG_OK))

    def is_fault_latched(self) -> bool:
        """Check if a latched fault condition exists."""
        return bool(self.get_register(REG_FAULT_LATCHED))

    def get_last_error(self) -> int:
        """Get the last error code from firmware."""
        return self.get_register(REG_LAST_ERROR)

    def get_last_command_code(self) -> int:
        """Get the raw code of the most recent supervisor command."""
        return self.get_register(REG_LAST_CMD_CODE)

    def get_last_command_result(self) -> str:
        """Get the most recent supervisor command result as a label."""
        return self._label_from_code(
            self.get_register(REG_LAST_CMD_RESULT),
            BCONCommandResult,
            COMMAND_RESULT_LABELS,
        )

    def get_last_command_result_code(self) -> int:
        """Get the raw result code for the most recent supervisor command."""
        return self.get_register(REG_LAST_CMD_RESULT)

    def get_last_reject_reason(self) -> str:
        """Get the most recent supervisor reject reason as a label."""
        return self._label_from_code(
            self.get_register(REG_LAST_REJECT_REASON),
            BCONRejectReason,
            REJECT_REASON_LABELS,
        )

    def get_last_reject_reason_code(self) -> int:
        """Get the raw reject reason code for the most recent supervisor command."""
        return self.get_register(REG_LAST_REJECT_REASON)

    def get_last_command_sequence(self) -> int:
        """Get the firmware sequence number for the most recent accepted command."""
        return self.get_register(REG_LAST_CMD_SEQ)

    # --- Per-channel status ---

    def get_channel_mode(self, channel: int) -> str:
        """Get actual operating mode for a channel (from status registers)."""
        if not self._validate_channel(channel):
            return "UNKNOWN"
        addr = REG_CH_STATUS_BASE + (channel - 1) * REG_CH_STATUS_STRIDE
        code = self.get_register(addr + 0)
        return MODE_CODE_TO_LABEL.get(code, "UNKNOWN")

    def get_channel_remaining(self, channel: int) -> int:
        """Get remaining pulse count for a channel."""
        if not self._validate_channel(channel):
            return 0
        addr = REG_CH_STATUS_BASE + (channel - 1) * REG_CH_STATUS_STRIDE
        return self.get_register(addr + 3)

    def get_channel_output_level(self, channel: int) -> int:
        """Get current output level for a channel (0 or 1)."""
        if not self._validate_channel(channel):
            return 0
        addr = REG_CH_STATUS_BASE + (channel - 1) * REG_CH_STATUS_STRIDE
        return self.get_register(addr + 8)

    def get_channel_supervisor_status(self, channel: int) -> Dict:
        """Get the semantic supervisor status block for one channel."""
        if not self._validate_channel(channel):
            return {
                'run_state': 'UNKNOWN',
                'run_state_code': -1,
                'stop_reason': 'UNKNOWN',
                'stop_reason_code': -1,
                'complete': False,
                'aborted': False,
            }

        base = REG_CH_SUP_BASE + (channel - 1) * REG_CH_SUP_STRIDE
        with self._regs_lock:
            r = self._regs
            run_state_code = r[base + 0]
            stop_reason_code = r[base + 1]
            return {
                'run_state': self._label_from_code(run_state_code, BCONChannelRunState, CHANNEL_RUN_STATE_LABELS),
                'run_state_code': run_state_code,
                'stop_reason': self._label_from_code(stop_reason_code, BCONStopReason, STOP_REASON_LABELS),
                'stop_reason_code': stop_reason_code,
                'complete': bool(r[base + 2]),
                'aborted': bool(r[base + 3]),
            }

    def get_channel_status(self, channel: int) -> Dict:
        """Get the combined live + supervisor status for one channel."""
        if not self._validate_channel(channel):
            return {
                'mode': 'UNKNOWN',
                'pulse_ms': 0,
                'count': 0,
                'remaining': 0,
                'en_st': False,
                'en_st_raw': 0,
                'pwr_st': 0,
                'oc_st': 0,
                'gated_st': 0,
                'output_level': 0,
                'run_state': 'UNKNOWN',
                'run_state_code': -1,
                'stop_reason': 'UNKNOWN',
                'stop_reason_code': -1,
                'complete': False,
                'aborted': False,
            }

        base = REG_CH_STATUS_BASE + (channel - 1) * REG_CH_STATUS_STRIDE
        sup_base = REG_CH_SUP_BASE + (channel - 1) * REG_CH_SUP_STRIDE
        with self._regs_lock:
            r = self._regs
            enabled_shadow = self._channel_enable_shadow[channel - 1]
            run_state_code = r[sup_base + 0]
            stop_reason_code = r[sup_base + 1]
            return {
                'mode': MODE_CODE_TO_LABEL.get(r[base + 0], "UNKNOWN"),
                'pulse_ms': r[base + 1],
                'count': r[base + 2],
                'remaining': r[base + 3],
                'en_st': enabled_shadow,
                'en_st_raw': r[base + 4],
                'pwr_st': r[base + 5],
                'oc_st': r[base + 6],
                'gated_st': r[base + 7],
                'output_level': r[base + 8],
                'run_state': self._label_from_code(run_state_code, BCONChannelRunState, CHANNEL_RUN_STATE_LABELS),
                'run_state_code': run_state_code,
                'stop_reason': self._label_from_code(stop_reason_code, BCONStopReason, STOP_REASON_LABELS),
                'stop_reason_code': stop_reason_code,
                'complete': bool(r[sup_base + 2]),
                'aborted': bool(r[sup_base + 3]),
            }

    def is_channel_overcurrent(self, channel: int) -> bool:
        """Check if a channel has an overcurrent condition."""
        if not self._validate_channel(channel):
            return False
        addr = REG_CH_STATUS_BASE + (channel - 1) * REG_CH_STATUS_STRIDE + 6
        return bool(self.get_register(addr))

    def is_channel_enabled(self, channel: int) -> bool:
        """Return the dashboard's best-effort software shadow for channel enable state."""
        if not self._validate_channel(channel):
            return False
        with self._regs_lock:
            return self._channel_enable_shadow[channel - 1]

    # --- Legacy-compatible telemetry dict ---

    def get_status(self) -> Dict:
        """Get full system status in a structured dictionary."""
        with self._regs_lock:
            r = self._regs
            state_code = r[REG_SYS_STATE]
            supervisor_state_code = r[REG_SUP_STATE]
            last_result_code = r[REG_LAST_CMD_RESULT]
            last_reject_code = r[REG_LAST_REJECT_REASON]

            system = {
                'state': self._label_from_code(state_code, BCONState, STATE_LABELS),
                'state_code': state_code,
                'reason': r[REG_SYS_REASON],
                'fault_latched': r[REG_FAULT_LATCHED],
                'interlock_ok': r[REG_INTERLOCK_OK],
                'watchdog_ok': r[REG_WATCHDOG_OK],
                'last_error': r[REG_LAST_ERROR],
                'telemetry_ms': r[REG_TELEMETRY_MS],
                'watchdog_ms': r[REG_WATCHDOG_MS],
                'supervisor_state': self._label_from_code(
                    supervisor_state_code, BCONSupervisorState, SUPERVISOR_STATE_LABELS),
                'supervisor_state_code': supervisor_state_code,
                'cmd_queue_depth': r[REG_CMD_QUEUE_DEPTH],
                'last_command_code': r[REG_LAST_CMD_CODE],
                'last_command_label': self._command_label(r[REG_LAST_CMD_CODE]),
                'last_command_result': self._label_from_code(
                    last_result_code, BCONCommandResult, COMMAND_RESULT_LABELS),
                'last_command_result_code': last_result_code,
                'last_reject_reason': self._label_from_code(
                    last_reject_code, BCONRejectReason, REJECT_REASON_LABELS),
                'last_reject_reason_code': last_reject_code,
                'last_cmd_seq': r[REG_LAST_CMD_SEQ],
            }

            channels = []
            for ch_idx in range(3):
                base = REG_CH_STATUS_BASE + ch_idx * REG_CH_STATUS_STRIDE
                sup_base = REG_CH_SUP_BASE + ch_idx * REG_CH_SUP_STRIDE
                run_state_code = r[sup_base + 0]
                stop_reason_code = r[sup_base + 1]
                channels.append({
                    'mode': MODE_CODE_TO_LABEL.get(r[base + 0], "UNKNOWN"),
                    'pulse_ms': r[base + 1],
                    'count': r[base + 2],
                    'remaining': r[base + 3],
                    'en_st': self._channel_enable_shadow[ch_idx],
                    'en_st_raw': r[base + 4],
                    'pwr_st': r[base + 5],
                    'oc_st': r[base + 6],
                    'gated_st': r[base + 7],
                    'output_level': r[base + 8],
                    'run_state': self._label_from_code(
                        run_state_code, BCONChannelRunState, CHANNEL_RUN_STATE_LABELS),
                    'run_state_code': run_state_code,
                    'stop_reason': self._label_from_code(
                        stop_reason_code, BCONStopReason, STOP_REASON_LABELS),
                    'stop_reason_code': stop_reason_code,
                    'complete': bool(r[sup_base + 2]),
                    'aborted': bool(r[sup_base + 3]),
                })

        return {'system': system, 'channels': channels}

    def get_latest_telemetry(self) -> Dict:
        """Alias for get_status() — backwards compatibility."""
        return self.get_status()

    # --- Convenience: ping-like check ---

    def ping(self) -> bool:
        """
        Check communication by reading a register block.

        Returns True if the read succeeds, False otherwise.
        (There is no PING command over Modbus; this reads system status.)
        """
        if not self.is_connected():
            return False
        try:
            self._read_holding_registers_raw(REG_SYS_STATE, 1)
            return True
        except Exception:
            return False


# ==================== Standalone Test ====================

def main():
    """Standalone test function."""
    import argparse

    parser = argparse.ArgumentParser(description="BCON Modbus RTU Driver Test")
    parser.add_argument("--port", required=True, help="Serial port (e.g., COM3)")
    parser.add_argument("--baudrate", type=int, default=115200, help="Baud rate")
    parser.add_argument("--unit", type=int, default=1, help="Modbus unit/slave ID")
    parser.add_argument("--test", action="store_true", help="Run interactive test")
    args = parser.parse_args()

    bcon = BCONDriver(port=args.port, baudrate=args.baudrate, unit=args.unit, debug=True)

    if not bcon.connect():
        print("Failed to connect to BCON")
        return

    print("\n=== BCON Connected ===\n")

    try:
        if args.test:
            while True:
                print("\nBCON Modbus Test Menu:")
                print("1. Ping (register read)")
                print("2. Get Status")
                print("3. Set Channel 1 DC")
                print("4. Set Channel 2 PULSE (250ms x1)")
                print("5. Stop All")
                print("6. Set Watchdog (1000ms)")
                print("7. Set Telemetry (500ms)")
                print("8. ARM / Clear Fault")
                print("9. Show Latest Registers")
                print("0. Exit")

                choice = input("\nSelect option: ").strip()

                if choice == "1":
                    ok = bcon.ping()
                    print(f"Ping: {'SUCCESS' if ok else 'FAILED'}")
                elif choice == "2":
                    status = bcon.get_status()
                    print(f"\nSystem: {status['system']}")
                    for i, ch in enumerate(status['channels'], 1):
                        print(f"Channel {i}: {ch}")
                elif choice == "3":
                    bcon.set_channel_dc(1)
                    print("Enqueued: CH1 -> DC")
                elif choice == "4":
                    bcon.set_channel_pulse(2, 250)
                    print("Enqueued: CH2 -> PULSE 250ms")
                elif choice == "5":
                    bcon.stop_all()
                    print("Enqueued: STOP ALL")
                elif choice == "6":
                    bcon.set_watchdog(1000)
                    print("Enqueued: Watchdog = 1000ms")
                elif choice == "7":
                    bcon.set_telemetry(500)
                    print("Enqueued: Telemetry = 500ms")
                elif choice == "8":
                    bcon.arm()
                    print("Enqueued: ARM command")
                elif choice == "9":
                    regs = bcon.get_registers()
                    print(f"Control regs [0-33]: {regs[0:34]}")
                    print(f"System regs [100-105]: {regs[100:106]}")
                    for ch in range(3):
                        b = 110 + ch * 10
                        print(f"CH{ch+1} status [{b}-{b+8}]: {regs[b:b+9]}")
                elif choice == "0":
                    break
                else:
                    print("Invalid option")

                time.sleep(0.5)  # let poll thread update
        else:
            print("Running quick test...")
            time.sleep(1)  # let initial poll complete

            ok = bcon.ping()
            print(f"Ping: {'SUCCESS' if ok else 'FAILED'}")

            status = bcon.get_status()
            print(f"System state: {status['system']['state']}")
            for i, ch in enumerate(status['channels'], 1):
                print(f"Channel {i}: mode={ch['mode']} oc={ch['oc_st']}")

    finally:
        print("\nDisconnecting...")
        bcon.disconnect()
        print("Done")


if __name__ == "__main__":
    main()
