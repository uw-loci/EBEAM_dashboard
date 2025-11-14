"""
BCON Modbus Driver

Hardware driver for the Beam Pulse Control (BCON) system using Modbus RTU communication.
This module provides the low-level hardware interface for beam pulse control operations.

Contract:
  - Inputs: serial port and Modbus unit id (slave id)
  - Outputs: read/write access to BCON registers over Modbus
  - Error modes: connection failures return None/False and log errors

This maps high-level methods to the register map provided in the project
documentation. Registers are zero-based addresses matching the device map.
"""

import time
from typing import Optional, Dict
from instrumentctl.E5CN_modbus.E5CN_modbus import E5CNModbus
from utils import LogLevel


class BCONModbus:
    """Hardware driver for BCON (Beam Pulse Control) system using Modbus RTU.

    This class provides the low-level hardware interface for communicating with
    the BCON device over Modbus RTU serial communication.
    """

    # Register addresses (zero-based)
    REGISTER = {
        "COMMAND": 0,
        "X_DIRECT_WRITE": 1,
        "Y_DIRECT_WRITE": 2,
        "PULSER_1_DUTY": 3,
        "PULSER_2_DUTY": 4,
        "PULSER_3_DUTY": 5,
        "PULSER_1_DURATION": 6,
        "PULSER_2_DURATION": 7,
        "PULSER_3_DURATION": 8,
        "SAMPLES_RATE": 9,
        # Following registers are sequential for beams 1..3: amplitude, phase, offset
        "BEAM_1_AMPLITUDE": 10,
        "BEAM_1_PHASE": 11,
        "BEAM_1_OFFSET": 12,
        "BEAM_2_AMPLITUDE": 13,
        "BEAM_2_PHASE": 14,
        "BEAM_2_OFFSET": 15,
        "BEAM_3_AMPLITUDE": 16,
        "BEAM_3_PHASE": 17,
        "BEAM_3_OFFSET": 18,
    }

    def __init__(self, port: str = None, unit: int = 1, baudrate: int = 115200,
                 timeout: int = 1, logger=None, debug: bool = False):
        """Initialize the BCON Modbus driver.

        Parameters:
            port: serial port (e.g. 'COM3')
            unit: Modbus slave id for the BCON device
            baudrate, timeout: serial parameters passed to E5CNModbus
            logger: optional logger object compatible with utils.LogLevel
            debug: enable debug logs
        """
        self.unit = unit
        self.logger = logger
        self.debug = debug

        # Hardware connection (only if port is provided)
        self.modbus = None
        if port:
            self.modbus = E5CNModbus(
                port=port, baudrate=baudrate, timeout=timeout,
                logger=logger, debug_mode=debug)

    def _log(self, message: str, level: LogLevel = LogLevel.INFO):
        """Internal logging helper."""
        if self.logger:
            self.logger.log(message, level)

    # --- Connection Management ---
    def connect(self) -> bool:
        """Open Modbus connection to the device."""
        if not self.modbus:
            self._log("No Modbus connection configured", LogLevel.ERROR)
            return False
        return self.modbus.connect()

    def disconnect(self) -> None:
        """Close Modbus connection."""
        if self.modbus:
            self.modbus.disconnect()

    def is_connected(self) -> bool:
        """Check if connection is active and working."""
        if self.modbus and hasattr(self.modbus, 'client'):
            try:
                # Check if the client is connected and socket is open
                if (hasattr(self.modbus.client, 'is_socket_open') and
                        self.modbus.client.is_socket_open()):
                    # Try a simple temperature read to verify connection
                    result = self.modbus.read_temperature(self.unit)
                    # If we get a numeric result, connection is working
                    return isinstance(result, (int, float))
                else:
                    return False
            except Exception:
                return False
        else:
            # No modbus connection configured
            return False

    # --- Basic Register Primitives ---
    def read_register(self, name: str) -> Optional[int]:
        """Read a single holding register by name. Returns integer or None on error."""
        if not self.modbus:
            self._log("No Modbus connection configured", LogLevel.ERROR)
            return None

        if name not in self.REGISTER:
            self._log(f"Unknown register name: {name}", LogLevel.ERROR)
            return None

        addr = self.REGISTER[name]
        try:
            with self.modbus.modbus_lock:
                if not self.modbus.client.is_socket_open():
                    if not self.modbus.connect():
                        return None

                resp = self.modbus.client.read_holding_registers(
                    address=addr, count=1, slave=self.unit)

            if resp and not resp.isError():
                return int(resp.registers[0])
            else:
                self._log(f"Read error for {name} (addr={addr}): {resp}",
                          LogLevel.ERROR)
                return None

        except Exception as e:
            self._log(f"Exception reading register {name}: {e}", LogLevel.ERROR)
            return None

    def write_register(self, name: str, value: int) -> bool:
        """Write a single holding register by name. Returns True on success."""
        if not self.modbus:
            self._log("No Modbus connection configured", LogLevel.ERROR)
            return False

        if name not in self.REGISTER:
            self._log(f"Unknown register name: {name}", LogLevel.ERROR)
            return False

        addr = self.REGISTER[name]
        try:
            with self.modbus.modbus_lock:
                if not self.modbus.client.is_socket_open():
                    if not self.modbus.connect():
                        return False

                # write single 16-bit register
                resp = self.modbus.client.write_register(
                    address=addr, value=int(value), slave=self.unit)

            if resp and not getattr(resp, 'isError', lambda: False)():
                return True
            else:
                self._log(f"Write error for {name} (addr={addr}, value={value}): "
                          f"{resp}", LogLevel.ERROR)
                return False

        except Exception as e:
            self._log(f"Exception writing register {name}: {e}", LogLevel.ERROR)
            return False

    def read_all(self) -> Dict[str, Optional[int]]:
        """Read all defined registers and return a mapping name->value (or None on error)."""
        out = {}
        for name in sorted(self.REGISTER.keys(), key=lambda n: self.REGISTER[n]):
            out[name] = self.read_register(name)
            # small pause to avoid overwhelming the serial link
            time.sleep(0.01)
        return out

    # --- High-Level BCON Device Operations ---
    def set_command(self, cmd: int) -> bool:
        """Write the COMMAND register (register 0)."""
        return self.write_register("COMMAND", cmd)

    def direct_write_x(self, value: int) -> bool:
        """Direct write to DAC X (register 1)."""
        return self.write_register("X_DIRECT_WRITE", value)

    def direct_write_y(self, value: int) -> bool:
        """Direct write to DAC Y (register 2)."""
        return self.write_register("Y_DIRECT_WRITE", value)

    def set_pulser_duty(self, pulser_index: int, duty: int) -> bool:
        """Set pulser duty (0..255) for pulser_index 1..3."""
        if pulser_index not in (1, 2, 3):
            self._log("pulser_index must be 1..3", LogLevel.ERROR)
            return False
        name = f"PULSER_{pulser_index}_DUTY"
        if duty < 0 or duty > 0xFF:
            self._log("duty must be 0..255", LogLevel.ERROR)
            return False
        return self.write_register(name, duty)

    def set_pulser_duration(self, pulser_index: int, duration_ms: int) -> bool:
        """Set pulser duration in milliseconds (Uint16) for pulser_index 1..3."""
        if pulser_index not in (1, 2, 3):
            self._log("pulser_index must be 1..3", LogLevel.ERROR)
            return False
        name = f"PULSER_{pulser_index}_DURATION"
        if duration_ms < 0 or duration_ms > 0xFFFF:
            self._log("duration_ms out of range 0..65535",
                      LogLevel.ERROR)
            return False
        return self.write_register(name, duration_ms)

    def set_samples_rate(self, samples: int) -> bool:
        """Set SAMPLES_RATE (Uint16). Default device uses 8192."""
        if samples <= 0 or samples > 0xFFFF:
            self._log("samples out of range", LogLevel.ERROR)
            return False
        return self.write_register("SAMPLES_RATE", samples)

    def set_beam_parameters(self, beam_index: int,
                            amplitude: Optional[int] = None,
                            phase: Optional[int] = None,
                            offset: Optional[int] = None) -> Dict[str, bool]:
        """Set amplitude/phase/offset for beam 1..3. Values are Uint16.

        Returns a dict of results per field.
        """
        if beam_index not in (1, 2, 3):
            self._log("beam_index must be 1..3", LogLevel.ERROR)
            return {}

        results = {}
        mapping = {
            "amplitude": (f"BEAM_{beam_index}_AMPLITUDE", amplitude),
            "phase": (f"BEAM_{beam_index}_PHASE", phase),
            "offset": (f"BEAM_{beam_index}_OFFSET", offset),
        }

        for key, (regname, val) in mapping.items():
            if val is None:
                results[key] = False
                continue
            if val < 0 or val > 0xFFFF:
                self._log(f"{key} value out of range 0..65535: {val}",
                          LogLevel.ERROR)
                results[key] = False
                continue
            results[key] = self.write_register(regname, val)

        return results

    def get_beam_amplitude(self, beam_index: int) -> Optional[int]:
        """Get current amplitude setting for beam 1..3."""
        if beam_index not in (1, 2, 3):
            self._log("beam_index must be 1..3", LogLevel.ERROR)
            return None
        return self.read_register(f"BEAM_{beam_index}_AMPLITUDE")

    def get_beam_phase(self, beam_index: int) -> Optional[int]:
        """Get current phase setting for beam 1..3."""
        if beam_index not in (1, 2, 3):
            self._log("beam_index must be 1..3", LogLevel.ERROR)
            return None
        return self.read_register(f"BEAM_{beam_index}_PHASE")

    def get_beam_offset(self, beam_index: int) -> Optional[int]:
        """Get current offset setting for beam 1..3."""
        if beam_index not in (1, 2, 3):
            self._log("beam_index must be 1..3", LogLevel.ERROR)
            return None
        return self.read_register(f"BEAM_{beam_index}_OFFSET")

    def get_pulser_duty(self, pulser_index: int) -> Optional[int]:
        """Get current duty setting for pulser 1..3."""
        if pulser_index not in (1, 2, 3):
            self._log("pulser_index must be 1..3", LogLevel.ERROR)
            return None
        return self.read_register(f"PULSER_{pulser_index}_DUTY")

    def get_pulser_duration(self, pulser_index: int) -> Optional[int]:
        """Get current duration setting for pulser 1..3."""
        if pulser_index not in (1, 2, 3):
            self._log("pulser_index must be 1..3", LogLevel.ERROR)
            return None
        return self.read_register(f"PULSER_{pulser_index}_DURATION")

    def get_samples_rate(self) -> Optional[int]:
        """Get current samples rate setting."""
        return self.read_register("SAMPLES_RATE")
