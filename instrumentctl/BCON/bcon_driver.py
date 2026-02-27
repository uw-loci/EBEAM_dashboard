"""
BCON (Beam Controller) Driver — Modbus RTU

Modbus RTU master driver for Arduino Mega running BCON firmware.
Provides register-based control, status polling, and telemetry access
for three independent pulser channels with safety interlocks.

Register map mirrors the firmware Modbus slave implementation:
  Control registers  0-9   : watchdog, telemetry, command
  Channel 1 params  10-13  : mode, pulse_ms, count, enable_toggle
  Channel 2 params  20-23  : (same layout)
  Channel 3 params  30-33  : (same layout)
  System status    100-105  : state, reason, fault, interlock, watchdog, error
  CH1 status       110-118  : mode_st, pulse_ms_st, count_st, remaining, ...
  CH2 status       120-128
  CH3 status       130-138
"""

from __future__ import annotations

import copy
import inspect
import logging
import platform
import queue
import threading
import time
from typing import Optional, Dict, List, Any, TYPE_CHECKING
from enum import IntEnum

if TYPE_CHECKING:
    from pymodbus.client import ModbusSerialClient

# Attempt pymodbus import
try:
    from pymodbus.client import ModbusSerialClient as ModbusClient
except ImportError:
    ModbusClient = None

# Attempt pyserial import (for port scanning)
try:
    import serial.tools.list_ports as list_ports
except ImportError:
    list_ports = None

# Suppress chatty pymodbus retry/timeout messages
logging.getLogger("pymodbus").setLevel(logging.ERROR)


# ======================== Register Map Constants ========================

TOTAL_REGS = 160

# --- Control registers (written by master) ---
REG_WATCHDOG_MS   = 0
REG_TELEMETRY_MS  = 1
REG_COMMAND       = 2     # 0=NOP, 3=ARM/CLEAR_FAULT

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


# ======================== Utility ========================

def scan_serial_ports() -> List[str]:
    """Return a list of available serial ports, with Arduino-like ports first."""
    if list_ports is None:
        return []
    is_windows = platform.system().lower() == "windows"
    is_linux = platform.system().lower() == "linux"
    ports = list_ports.comports()
    preferred, others = [], []
    for p in ports:
        device = getattr(p, "device", None)
        if not device:
            continue
        if is_windows and not str(device).upper().startswith("COM"):
            continue
        if is_linux and not str(device).startswith("/dev/tty"):
            continue
        desc = (getattr(p, "description", "") or "").lower()
        hwid = (getattr(p, "hwid", "") or "").lower()
        if any(tok in desc for tok in ("arduino", "usb serial", "ch340", "cp210")) or "vid:pid=2341" in hwid:
            preferred.append(device)
        else:
            others.append(device)
    return preferred + others


# ======================== BCONDriver ========================

class BCONDriver:
    """
    BCON (Beam Controller) Modbus RTU driver.

    Communicates with Arduino Mega running BCON firmware over Modbus RTU
    to control three independent pulser channels with safety interlocks.

    Features:
        - Modbus RTU serial communication (pymodbus)
        - Background register polling thread
        - Thread-safe register cache
        - Write queue for non-blocking control
        - Watchdog and fault management
        - Auto-disconnect on repeated poll failures
    """

    # Defaults
    DEFAULT_BAUD       = 115200
    DEFAULT_UNIT       = 1
    DEFAULT_TIMEOUT    = 1.0
    POLL_INTERVAL      = 0.3     # seconds between register polls
    MAX_POLL_ERRORS    = 4       # consecutive failures before auto-disconnect
    SETTLE_TIME        = 2.5     # seconds to wait after opening port (Arduino DTR reset)

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

        # Modbus client
        self._client: Optional[ModbusSerialClient] = None
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
        if ModbusClient is None:
            self._log("pymodbus is not installed", "ERROR")
            return False

        if settle_s is None:
            settle_s = self.SETTLE_TIME

        if self._client:
            try:
                self._client.close()
            except Exception:
                pass

        try:
            # pymodbus v3 API
            try:
                self._client = ModbusClient(
                    port=self.port, framer="rtu",
                    baudrate=self.baudrate, timeout=self.timeout, retries=1
                )
            except TypeError:
                # Older pymodbus signature
                self._client = ModbusClient(
                    method="rtu", port=self.port,
                    baudrate=self.baudrate, timeout=self.timeout
                )

            ok = self._client.connect()
        except Exception as e:
            self._client = None
            self._connected = False
            self._log(f"Connect failed: {e}", "ERROR")
            self._ui_put("connected", False)
            return False

        if ok and settle_s > 0:
            self._log(f"Waiting {settle_s}s for firmware boot…", "INFO")
            time.sleep(settle_s)

        self._connected = ok
        self._poll_errors = 0

        if ok:
            self._log(f"Connected to {self.port} at {self.baudrate} baud (unit={self.unit})", "INFO")
            self._start_poll_thread()
        else:
            self._log("Modbus connect() returned False", "ERROR")

        self._ui_put("connected", ok)
        return ok

    def disconnect(self):
        """Disconnect from BCON hardware."""
        self._stop_poll_thread()
        self._connected = False
        self._poll_errors = 0
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None
        self._log("Disconnected", "INFO")
        self._ui_put("connected", False)

    def is_connected(self) -> bool:
        """Check if connected to BCON hardware."""
        return self._connected and self._client is not None

    # ================================================================== #
    #                      Low-level Modbus I/O                            #
    # ================================================================== #

    def _write_register_compat(self, reg: int, val: int):
        """Write a single holding register (compatible across pymodbus versions)."""
        write_fn = self._client.write_register
        sig = inspect.signature(write_fn)
        if "device_id" in sig.parameters:
            return write_fn(reg, int(val), device_id=self.unit)
        if "unit" in sig.parameters:
            return write_fn(reg, int(val), unit=self.unit)
        if "slave" in sig.parameters:
            return write_fn(reg, int(val), slave=self.unit)
        return write_fn(reg, int(val))

    def _read_holding_registers_compat(self, start: int, count: int):
        """Read a block of holding registers (compatible across pymodbus versions)."""
        read_fn = self._client.read_holding_registers
        sig = inspect.signature(read_fn)
        if "device_id" in sig.parameters:
            return read_fn(start, count=count, device_id=self.unit)
        if "unit" in sig.parameters:
            return read_fn(start, count, unit=self.unit)
        if "slave" in sig.parameters:
            return read_fn(start, count, slave=self.unit)
        return read_fn(start, count)

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
        for non-blocking UI interaction.

        Returns:
            True if write succeeded, False otherwise.
        """
        if not self.is_connected():
            return False
        try:
            self._write_register_compat(reg, value)
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

        while self._poll_running:
            # --- Process queued writes ---
            try:
                while not self._cmd_queue.empty():
                    cmd = self._cmd_queue.get_nowait()
                    if cmd[0] == "write" and self._client and self._connected:
                        _, reg, val = cmd
                        try:
                            self._write_register_compat(reg, val)
                            self._ui_put("wrote", reg, val)
                        except Exception as e:
                            self._log(f"Write reg {reg}: {e}", "ERROR")
                            self._ui_put("error", f"Write reg {reg}: {e}")
            except queue.Empty:
                pass

            # --- Poll registers ---
            if self._client and self._connected:
                try:
                    regs = [0] * TOTAL_REGS

                    def read_block(start, count):
                        rr = self._read_holding_registers_compat(start, count)
                        if not rr or not hasattr(rr, 'registers'):
                            return False
                        for i, value in enumerate(rr.registers):
                            idx = start + i
                            if 0 <= idx < TOTAL_REGS:
                                regs[idx] = value
                        return True

                    ok = True
                    ok &= read_block(0, 34)      # control + channel params
                    ok &= read_block(100, 6)     # system status
                    ok &= read_block(110, 9)     # CH1 status (110-118)
                    ok &= read_block(120, 9)     # CH2 status (120-128)
                    ok &= read_block(130, 9)     # CH3 status (130-138)

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
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None
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

    def set_channel_off(self, channel: int) -> None:
        """
        Turn off specified channel.

        Args:
            channel: Channel number (1-3).
        """
        if not (1 <= channel <= 3):
            self._log(f"Invalid channel: {channel} (must be 1-3)", "ERROR")
            return
        base = CH_BASE[channel - 1]
        self.enqueue_write(base + CH_MODE_OFF, BCONMode.OFF)

    def set_channel_dc(self, channel: int) -> None:
        """
        Set channel to DC mode (continuous output).

        Args:
            channel: Channel number (1-3).
        """
        if not (1 <= channel <= 3):
            self._log(f"Invalid channel: {channel} (must be 1-3)", "ERROR")
            return
        base = CH_BASE[channel - 1]
        self.enqueue_write(base + CH_MODE_OFF, BCONMode.DC)

    def set_channel_pulse(self, channel: int, duration_ms: int, count: int = 1) -> None:
        """
        Set channel to PULSE mode.

        Args:
            channel: Channel number (1-3).
            duration_ms: Pulse duration in milliseconds (1-60000).
            count: Number of pulses (default 1).
        """
        if not (1 <= channel <= 3):
            self._log(f"Invalid channel: {channel} (must be 1-3)", "ERROR")
            return
        if not (1 <= duration_ms <= 60000):
            self._log(f"Invalid pulse duration: {duration_ms}", "ERROR")
            return
        base = CH_BASE[channel - 1]
        self.enqueue_write(base + CH_PULSE_MS_OFF, duration_ms)
        self.enqueue_write(base + CH_COUNT_OFF, count)
        self.enqueue_write(base + CH_MODE_OFF, BCONMode.PULSE)

    def set_channel_pulse_train(self, channel: int, duration_ms: int, count: int) -> None:
        """
        Set channel to PULSE_TRAIN mode.

        Args:
            channel: Channel number (1-3).
            duration_ms: Pulse duration in milliseconds.
            count: Number of pulses (must be >= 2).
        """
        if not (1 <= channel <= 3):
            self._log(f"Invalid channel: {channel} (must be 1-3)", "ERROR")
            return
        if count < 2:
            self._log(f"PULSE_TRAIN requires count >= 2, got {count}", "ERROR")
            return
        base = CH_BASE[channel - 1]
        self.enqueue_write(base + CH_PULSE_MS_OFF, duration_ms)
        self.enqueue_write(base + CH_COUNT_OFF, count)
        self.enqueue_write(base + CH_MODE_OFF, BCONMode.PULSE_TRAIN)

    def set_channel_mode(self, channel: int, mode: str,
                         duration_ms: int = 100, count: int = 1) -> None:
        """
        Generic channel mode setter.

        Args:
            channel: Channel number (1-3).
            mode: Mode label string ('OFF', 'DC', 'PULSE', 'PULSE_TRAIN').
            duration_ms: Pulse width for PULSE / PULSE_TRAIN modes.
            count: Pulse count for PULSE / PULSE_TRAIN modes.
        """
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
        """
        Write pulse parameters without changing the mode register.

        Args:
            channel: Channel number (1-3).
            duration_ms: Pulse width in ms.
            count: Pulse count.
        """
        if not (1 <= channel <= 3):
            return
        base = CH_BASE[channel - 1]
        if duration_ms > 0:
            self.enqueue_write(base + CH_PULSE_MS_OFF, duration_ms)
        if count > 0:
            self.enqueue_write(base + CH_COUNT_OFF, count)

    def toggle_channel_enable(self, channel: int) -> None:
        """
        Toggle the enable status of a channel (write 1 to enable_toggle register).

        Args:
            channel: Channel number (1-3).
        """
        if not (1 <= channel <= 3):
            return
        base = CH_BASE[channel - 1]
        self.enqueue_write(base + CH_ENABLE_TOGGLE_OFF, 1)

    def stop_all(self) -> None:
        """Force all three channels to OFF immediately."""
        for ch in range(3):
            self.enqueue_write(CH_BASE[ch] + CH_MODE_OFF, BCONMode.OFF)

    # ================================================================== #
    #              Synchronous Multi-Channel Start/Stop                    #
    # ================================================================== #

    def sync_start(self, configs: List[Dict]) -> None:
        """
        Start multiple channels with minimal inter-channel jitter.

        Phase 1: write duration + count for all channels.
        Phase 2: write mode for all channels (back-to-back).

        Args:
            configs: List of dicts with keys:
                     ch (int 1-3), mode (str), duration_ms (int), count (int)
        """
        # Phase 1: parameters
        for cfg in configs:
            ch = cfg['ch']
            mode_code = MODE_LABEL_TO_CODE.get(cfg['mode'].upper(), BCONMode.OFF)
            if mode_code not in (BCONMode.OFF, BCONMode.DC):
                base = CH_BASE[ch - 1]
                self.enqueue_write(base + CH_PULSE_MS_OFF, cfg.get('duration_ms', 100))
                self.enqueue_write(base + CH_COUNT_OFF, cfg.get('count', 1))

        # Phase 2: modes (close together)
        for cfg in configs:
            ch = cfg['ch']
            mode_code = MODE_LABEL_TO_CODE.get(cfg['mode'].upper(), BCONMode.OFF)
            self.enqueue_write(CH_BASE[ch - 1] + CH_MODE_OFF, mode_code)

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
        Write to the special COMMAND register.

        Known codes:
            0 = NOP (can be used to trigger a register refresh),
            3 = ARM / CLEAR_FAULT.

        Args:
            cmd_code: Command code.
        """
        self.enqueue_write(REG_COMMAND, cmd_code)

    # ================================================================== #
    #                     Safety / Fault Management                        #
    # ================================================================== #

    def arm(self) -> None:
        """Send ARM / CLEAR_FAULT command."""
        self.send_command(3)

    def clear_fault(self) -> None:
        """Alias for arm()."""
        self.arm()

    # ================================================================== #
    #                     Status / Telemetry Access                        #
    # ================================================================== #

    def get_system_state(self) -> str:
        """
        Get current system state as a human-readable string.

        Returns:
            State label (e.g. 'READY', 'FAULT_LATCHED').
        """
        code = self.get_register(REG_SYS_STATE)
        try:
            return STATE_LABELS.get(BCONState(code), "UNKNOWN")
        except ValueError:
            return "UNKNOWN"

    def get_system_state_code(self) -> int:
        """Get raw system state register value."""
        return self.get_register(REG_SYS_STATE)

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

    # --- Per-channel status ---

    def get_channel_mode(self, channel: int) -> str:
        """
        Get actual operating mode for a channel (from status registers).

        Args:
            channel: Channel number (1-3).

        Returns:
            Mode label string.
        """
        if not (1 <= channel <= 3):
            return "UNKNOWN"
        addr = REG_CH_STATUS_BASE + (channel - 1) * REG_CH_STATUS_STRIDE
        code = self.get_register(addr + 0)
        return MODE_CODE_TO_LABEL.get(code, "UNKNOWN")

    def get_channel_remaining(self, channel: int) -> int:
        """Get remaining pulse count for a channel."""
        if not (1 <= channel <= 3):
            return 0
        addr = REG_CH_STATUS_BASE + (channel - 1) * REG_CH_STATUS_STRIDE
        return self.get_register(addr + 3)

    def get_channel_output_level(self, channel: int) -> int:
        """Get current output level for a channel (0 or 1)."""
        if not (1 <= channel <= 3):
            return 0
        addr = REG_CH_STATUS_BASE + (channel - 1) * REG_CH_STATUS_STRIDE
        return self.get_register(addr + 8)

    def get_channel_status(self, channel: int) -> Dict:
        """
        Get full status for a channel.

        Args:
            channel: Channel number (1-3).

        Returns:
            Dictionary with keys: mode, pulse_ms, count, remaining,
            en_st, pwr_st, oc_st, gated_st, output_level.
        """
        if not (1 <= channel <= 3):
            return {
                'mode': 'UNKNOWN', 'pulse_ms': 0, 'count': 0, 'remaining': 0,
                'en_st': 0, 'pwr_st': 0, 'oc_st': 0, 'gated_st': 0, 'output_level': 0
            }
        base = REG_CH_STATUS_BASE + (channel - 1) * REG_CH_STATUS_STRIDE
        with self._regs_lock:
            r = self._regs
            return {
                'mode':         MODE_CODE_TO_LABEL.get(r[base + 0], "UNKNOWN"),
                'pulse_ms':     r[base + 1],
                'count':        r[base + 2],
                'remaining':    r[base + 3],
                'en_st':        r[base + 4],
                'pwr_st':       r[base + 5],
                'oc_st':        r[base + 6],
                'gated_st':     r[base + 7],
                'output_level': r[base + 8],
            }

    def is_channel_overcurrent(self, channel: int) -> bool:
        """
        Check if a channel has an overcurrent condition.

        Args:
            channel: Channel number (1-3).
        """
        if not (1 <= channel <= 3):
            return False
        addr = REG_CH_STATUS_BASE + (channel - 1) * REG_CH_STATUS_STRIDE + 6
        return bool(self.get_register(addr))

    def is_channel_enabled(self, channel: int) -> bool:
        """
        Check if a channel is enabled.

        Args:
            channel: Channel number (1-3).
        """
        if not (1 <= channel <= 3):
            return False
        addr = REG_CH_STATUS_BASE + (channel - 1) * REG_CH_STATUS_STRIDE + 4
        return bool(self.get_register(addr))

    # --- Legacy-compatible telemetry dict ---

    def get_status(self) -> Dict:
        """
        Get full system status in a structured dictionary.

        Returns a dict compatible with the old telemetry format:
            {'system': {state, reason, fault_latched, interlock_ok, watchdog_ok, ...},
             'channels': [{mode, pulse_ms, count, remaining, en_st, pwr_st, oc_st, ...}, ...]}
        """
        with self._regs_lock:
            r = self._regs
            state_code = r[REG_SYS_STATE]
            try:
                state_label = STATE_LABELS.get(BCONState(state_code), "UNKNOWN")
            except ValueError:
                state_label = "UNKNOWN"

            system = {
                'state':         state_label,
                'reason':        r[REG_SYS_REASON],
                'fault_latched': r[REG_FAULT_LATCHED],
                'interlock_ok':  r[REG_INTERLOCK_OK],
                'watchdog_ok':   r[REG_WATCHDOG_OK],
                'last_error':    r[REG_LAST_ERROR],
                'telemetry_ms':  r[REG_TELEMETRY_MS],
                'watchdog_ms':   r[REG_WATCHDOG_MS],
            }
            channels = []
            for ch_idx in range(3):
                base = REG_CH_STATUS_BASE + ch_idx * REG_CH_STATUS_STRIDE
                channels.append({
                    'mode':         MODE_CODE_TO_LABEL.get(r[base + 0], "UNKNOWN"),
                    'pulse_ms':     r[base + 1],
                    'count':        r[base + 2],
                    'remaining':    r[base + 3],
                    'en_st':        r[base + 4],
                    'pwr_st':       r[base + 5],
                    'oc_st':        r[base + 6],
                    'gated_st':     r[base + 7],
                    'output_level': r[base + 8],
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
            rr = self._read_holding_registers_compat(REG_SYS_STATE, 1)
            return rr is not None and hasattr(rr, 'registers')
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
