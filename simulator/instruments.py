"""
instruments.py — Simulated hardware instrument backends.

Each simulator runs in its own thread, reads commands from the master side of a
PTY pair, and writes responses (or streams data) back.  All state is stored in
plain dicts so the GUI can read / mutate it directly (with a lock).

Instrument simulators implemented:
- VTRXSimulator          (read-only ASCII stream — vacuum system)
- PowerSupply9104Sim     (ASCII cmd/response — cathode heater PSU)
- E5CNModbusSim          (Modbus RTU 8E2 — temperature controllers, 3 units)
- G9DriverSim            (raw binary packet — interlocks)
- DP16ProcessMonitorSim  (Modbus RTU 8N1 — process temperature monitors)
- BCONDriverSim          (Modbus RTU — beam pulse controller)
"""

from __future__ import annotations

import math
import os
import random
import select
import struct
import threading
import time
from typing import Any, Callable

from simulator.virtual_serial import VirtualSerialPair


# ---------------------------------------------------------------------------
#  Base class
# ---------------------------------------------------------------------------

class BaseSimulator:
    """Common lifecycle for all simulator threads."""

    def __init__(self, pair: VirtualSerialPair, name: str):
        self.pair = pair
        self.name = name
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run_wrapper, daemon=True, name=name)
        self.lock = threading.RLock()
        # Flat state dict; GUI reads/writes with self.lock held.
        self.state: dict[str, Any] = {}
        self._on_state_change: Callable | None = None

    def set_state_callback(self, cb: Callable):
        self._on_state_change = cb

    def _notify(self):
        if self._on_state_change:
            try:
                self._on_state_change()
            except Exception:
                pass

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run_wrapper(self):
        try:
            self.run()
        except Exception as exc:
            print(f"[{self.name}] simulator error: {exc}")

    def run(self):
        raise NotImplementedError


# ---------------------------------------------------------------------------
#  VTRX — vacuum system read-only stream
# ---------------------------------------------------------------------------

class VTRXSimulator(BaseSimulator):
    """Streams semicolon-delimited ASCII lines at ~1 Hz like the real VTRX."""

    def __init__(self, pair: VirtualSerialPair):
        super().__init__(pair, "VTRX")
        self.state = {
            "pressure": 5.0e-6,       # Torr
            "pumps_power": True,
            "turbo_rotor": True,
            "turbo_vent_open": False,
            "gauge_972b_power": True,
            "turbo_gate_closed": False,
            "turbo_gate_open": True,
            "argon_gate_open": False,
            "argon_gate_closed": True,
        }

    def run(self):
        while not self._stop.is_set():
            with self.lock:
                p = self.state["pressure"]
                bits = "".join([
                    "1" if self.state["pumps_power"] else "0",
                    "1" if self.state["turbo_rotor"] else "0",
                    "1" if self.state["turbo_vent_open"] else "0",
                    "1" if self.state["gauge_972b_power"] else "0",
                    "1" if self.state["turbo_gate_closed"] else "0",
                    "1" if self.state["turbo_gate_open"] else "0",
                    "1" if self.state["argon_gate_open"] else "0",
                    "1" if self.state["argon_gate_closed"] else "0",
                ])
            # add small random walk
            p *= 1 + random.gauss(0, 0.02)
            p = max(1e-9, min(1e-1, p))
            with self.lock:
                self.state["pressure"] = p
            sci = f"{p:.2E}"
            line = f"{p:.6e};{sci};{bits}\n"
            self.pair.write(line.encode())
            self._notify()
            self._stop.wait(1.0)


# ---------------------------------------------------------------------------
#  BK Precision 9104 power supply (ASCII)
# ---------------------------------------------------------------------------

class PowerSupply9104Sim(BaseSimulator):
    """Simulates one 9104 PSU (ASCII command/response over RS-232)."""

    def __init__(self, pair: VirtualSerialPair, name: str = "9104"):
        super().__init__(pair, name)
        self.state = {
            "output_on": False,
            "voltage_set": 0.0,     # Volts
            "current_set": 0.0,     # Amps
            "voltage_read": 0.0,
            "current_read": 0.0,
            "mode": 0,              # 0=CV, 1=CC
            "ovp": 42.0,
            "ocp": 5.0,
            "preset": 3,
            "presets": {0: (0.0, 0.0), 1: (0.0, 0.0), 2: (0.0, 0.0), 3: (0.0, 0.0)},
            "sw_times": {0: 1, 1: 1, 2: 1},
            "delta_times": {0: 0, 1: 0, 2: 0, 3: 0, 4: 0, 5: 0},
        }
        self._buf = b""

    @staticmethod
    def _clamp(value: int, lo: int, hi: int) -> int:
        return max(lo, min(hi, value))

    @staticmethod
    def _split_preset_and_value(raw: str) -> tuple[int, int] | None:
        raw = raw.strip().replace(" ", "")
        if len(raw) < 5 or not raw.isdigit():
            return None
        preset = int(raw[0])
        value = int(raw[1:5])
        return preset, value

    def run(self):
        while not self._stop.is_set():
            chunk = self.pair.read(256, timeout=0.05)
            if chunk:
                self._buf += chunk
                self._process_buffer()
            # simulate actual readings
            with self.lock:
                if self.state["output_on"]:
                    self.state["voltage_read"] = self.state["voltage_set"] + random.gauss(0, 0.01)
                    self.state["current_read"] = self.state["current_set"] * 0.95 + random.gauss(0, 0.005)
                else:
                    self.state["voltage_read"] = 0.0
                    self.state["current_read"] = 0.0
            self._stop.wait(0.02)

    def _process_buffer(self):
        while b"\r" in self._buf or b"\n" in self._buf:
            for sep in (b"\r\n", b"\r", b"\n"):
                idx = self._buf.find(sep)
                if idx != -1:
                    cmd_bytes = self._buf[:idx]
                    self._buf = self._buf[idx + len(sep):]
                    break
            else:
                break
            cmd = cmd_bytes.decode("ascii", errors="ignore").strip()
            if not cmd:
                continue
            resp = self._handle_command(cmd)
            if resp is not None:
                self.pair.write(resp.encode() + b"\r")

    def _handle_command(self, cmd: str) -> str | None:
        with self.lock:
            if cmd.startswith("SOUT"):
                val = cmd[4:]
                self.state["output_on"] = val.strip() == "1"
                self._notify()
                return "OK"
            elif cmd == "GOUT":
                return f"{'1' if self.state['output_on'] else '0'}\rOK"
            elif cmd.startswith("VOLT"):
                parsed = self._split_preset_and_value(cmd[4:])
                if parsed:
                    preset, cv = parsed
                    self.state["voltage_set"] = cv / 100.0
                    if preset in self.state["presets"]:
                        _, cur = self.state["presets"][preset]
                        self.state["presets"][preset] = (self.state["voltage_set"], cur)
                    # If command targets active preset, reflect into active setpoint
                    if preset == self.state["preset"]:
                        self.state["voltage_set"] = cv / 100.0
                    self._notify()
                return "OK"
            elif cmd.startswith("CURR"):
                parsed = self._split_preset_and_value(cmd[4:])
                if parsed:
                    preset, ca = parsed
                    self.state["current_set"] = ca / 100.0
                    if preset in self.state["presets"]:
                        volt, _ = self.state["presets"][preset]
                        self.state["presets"][preset] = (volt, self.state["current_set"])
                    if preset == self.state["preset"]:
                        self.state["current_set"] = ca / 100.0
                    self._notify()
                return "OK"
            elif cmd == "GETD":
                v = int(self.state["voltage_read"] * 100) % 10000
                i = int(self.state["current_read"] * 100) % 10000
                m = self.state["mode"]
                return f"{v:04d}{i:04d}{m}\rOK"
            elif cmd.startswith("SOVP"):
                cv = int(cmd[4:8])
                self.state["ovp"] = cv / 100.0
                return "OK"
            elif cmd == "GOVP":
                v = int(self.state["ovp"] * 100)
                return f"{v:04d}\rOK"
            elif cmd.startswith("SOCP"):
                ca = int(cmd[4:8])
                self.state["ocp"] = ca / 100.0
                return "OK"
            elif cmd == "GOCP":
                c = int(self.state["ocp"] * 100)
                return f"{c:04d}\rOK"
            elif cmd.startswith("GETS"):
                p = int(cmd[4]) if len(cmd) > 4 else 0
                sv, si = self.state["presets"].get(p, (0, 0))
                return f"{int(sv*100):04d}{int(si*100):04d}\rOK"
            elif cmd.startswith("SETD"):
                # SETD<preset><voltage><current>
                raw = cmd[4:].strip().replace(" ", "")
                if len(raw) >= 9 and raw[:9].isdigit():
                    p = int(raw[0])
                    v = int(raw[1:5]) / 100.0
                    c = int(raw[5:9]) / 100.0
                    if p in self.state["presets"]:
                        self.state["presets"][p] = (v, c)
                    if p == self.state["preset"]:
                        self.state["voltage_set"] = v
                        self.state["current_set"] = c
                    self._notify()
                return "OK"
            elif cmd == "GABC":
                return f"{self.state['preset']}\rOK"
            elif cmd.startswith("SABC"):
                if len(cmd) > 4 and cmd[4].isdigit():
                    p = self._clamp(int(cmd[4]), 0, 3)
                    self.state["preset"] = p
                    v, c = self.state["presets"].get(p, (0.0, 0.0))
                    self.state["voltage_set"] = v
                    self.state["current_set"] = c
                    self._notify()
                return "OK"
            elif cmd.startswith("GDLT"):
                raw = cmd[4:].strip()
                idx = int(raw[0]) if raw and raw[0].isdigit() else 0
                idx = self._clamp(idx, 0, 5)
                return f"{int(self.state['delta_times'][idx]):02d}\rOK"
            elif cmd.startswith("SDLT"):
                raw = cmd[4:].strip().replace(" ", "")
                if len(raw) >= 3 and raw[:3].isdigit():
                    idx = self._clamp(int(raw[0]), 0, 5)
                    val = self._clamp(int(raw[1:3]), 0, 20)
                    self.state["delta_times"][idx] = val
                    self._notify()
                return "OK"
            elif cmd.startswith("GSWT"):
                raw = cmd[4:].strip()
                if raw and raw[0].isdigit():
                    idx = self._clamp(int(raw[0]), 0, 2)
                    return f"{int(self.state['sw_times'][idx]):03d}\rOK"
                # Some host code calls GSWT without index; return first entry.
                return f"{int(self.state['sw_times'][0]):03d}\rOK"
            elif cmd.startswith("SSWT"):
                raw = cmd[4:].strip().replace(" ", "")
                if len(raw) >= 4 and raw[:4].isdigit():
                    idx = self._clamp(int(raw[0]), 0, 2)
                    val = self._clamp(int(raw[1:4]), 0, 600)
                    self.state["sw_times"][idx] = val
                    self._notify()
                return "OK"
            elif cmd.startswith("RUNP"):
                return "OK"
            elif cmd in ("SESS", "ENDS", "STOP"):
                return "OK"
            elif cmd == "GALL":
                # Keep response shape close to manual examples while remaining lightweight.
                abc = int(self.state["preset"])
                channel = 0
                uvl = int(self.state["ovp"] * 100)
                ucl = int(self.state["ocp"] * 100)
                out = 1 if self.state["output_on"] else 0
                sw1 = int(self.state["sw_times"][0])
                sw2 = int(self.state["sw_times"][1])
                sw3 = int(self.state["sw_times"][2])
                dt = "".join(f"{int(self.state['delta_times'][i]):02d}" for i in range(6))
                mode = 8160
                set_values = []
                for p in (0, 1, 2, 3):
                    v, c = self.state["presets"][p]
                    set_values.append(f"{int(v * 100):04d}")
                    set_values.append(f"{int(c * 100):04d}")
                body = (
                    f"{abc}{channel}{uvl:04d}{ucl:04d}{out}"
                    f"{sw1:03d}{sw2:03d}{sw3:03d}{dt}{mode:04d}"
                    + "".join(set_values)
                )
                return f"{body}\rOK"
            elif cmd.startswith("SETM"):
                # SETM<v1><i1><sw1><v2><i2><sw2><v3><i3><sw3>
                raw = cmd[4:].strip().replace(" ", "")
                if len(raw) >= 33 and raw[:33].isdigit():
                    v1 = int(raw[0:4]) / 100.0
                    i1 = int(raw[4:8]) / 100.0
                    s1 = self._clamp(int(raw[8:11]), 0, 600)
                    v2 = int(raw[11:15]) / 100.0
                    i2 = int(raw[15:19]) / 100.0
                    s2 = self._clamp(int(raw[19:22]), 0, 600)
                    v3 = int(raw[22:26]) / 100.0
                    i3 = int(raw[26:30]) / 100.0
                    s3 = self._clamp(int(raw[30:33]), 0, 600)
                    self.state["presets"][0] = (v1, i1)
                    self.state["presets"][1] = (v2, i2)
                    self.state["presets"][2] = (v3, i3)
                    self.state["sw_times"][0] = s1
                    self.state["sw_times"][1] = s2
                    self.state["sw_times"][2] = s3
                    self._notify()
                return "OK"
            return "OK"


# ---------------------------------------------------------------------------
#  Modbus RTU helpers
# ---------------------------------------------------------------------------

def _modbus_crc(data: bytes) -> int:
    """CRC-16/Modbus."""
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc


def _modbus_response(slave: int, func: int, payload: bytes) -> bytes:
    """Build a complete Modbus RTU response frame."""
    frame = bytes([slave, func]) + payload
    crc = _modbus_crc(frame)
    return frame + struct.pack("<H", crc)


def _modbus_exception(slave: int, func: int, exc_code: int) -> bytes:
    return _modbus_response(slave, func | 0x80, bytes([exc_code]))


# ---------------------------------------------------------------------------
#  E5CN temperature controllers (Modbus RTU, 3 units, 8E2)
# ---------------------------------------------------------------------------

class E5CNModbusSim(BaseSimulator):
    """Simulates 3 × Omron E5CN temp controllers (slave 1–3) on one bus."""

    def __init__(self, pair: VirtualSerialPair):
        super().__init__(pair, "E5CN")
        self.state = {
            "temp_1": 25.0,
            "temp_2": 26.0,
            "temp_3": 24.5,
        }
        self._buf = b""

    def run(self):
        while not self._stop.is_set():
            chunk = self.pair.read(256, timeout=0.05)
            if chunk:
                self._buf += chunk
                self._process()
            # random walk temperatures
            with self.lock:
                for k in ("temp_1", "temp_2", "temp_3"):
                    self.state[k] += random.gauss(0, 0.1)
                    self.state[k] = max(-20.0, min(500.0, self.state[k]))
            self._notify()
            self._stop.wait(0.02)

    def _process(self):
        # Modbus RTU: minimum frame = 8 bytes (1 slave + 1 func + 2 addr + 2 count + 2 crc)
        while len(self._buf) >= 8:
            slave = self._buf[0]
            func = self._buf[1]
            if func == 0x03:  # read holding registers
                if len(self._buf) < 8:
                    break
                frame = self._buf[:8]
                crc_recv = struct.unpack("<H", frame[6:8])[0]
                crc_calc = _modbus_crc(frame[:6])
                if crc_recv != crc_calc:
                    self._buf = self._buf[1:]
                    continue
                self._buf = self._buf[8:]
                addr = struct.unpack(">H", frame[2:4])[0]
                count = struct.unpack(">H", frame[4:6])[0]
                self._respond_read(slave, addr, count)
            else:
                self._buf = self._buf[1:]

    def _respond_read(self, slave: int, addr: int, count: int):
        if slave < 1 or slave > 3:
            return
        with self.lock:
            temp = self.state.get(f"temp_{slave}", 25.0)
        # E5CN PV representation used by this project:
        # read addr 0x0000, count=2, with PV in regs[1] at 0.1°C resolution.
        # Encode as signed 16-bit two's complement for sub-zero values.
        regs = [0] * count
        if addr == 0x0000 and count >= 2:
            pv_raw = int(round(temp * 10.0))
            regs[1] = pv_raw & 0xFFFF
        payload = bytes([count * 2])
        for r in regs:
            payload += struct.pack(">H", r & 0xFFFF)
        resp = _modbus_response(slave, 0x03, payload)
        time.sleep(0.005)  # simulate bus turnaround
        self.pair.write(resp)


# ---------------------------------------------------------------------------
#  G9SP interlocks (raw binary packet)
# ---------------------------------------------------------------------------

class G9DriverSim(BaseSimulator):
    """Simulates the Omron G9SP safety controller binary protocol."""

    # 13 interlock names in bit order
    INTERLOCK_NAMES = [
        "e_stop_int_a", "e_stop_int_b",
        "e_stop_ext_a", "e_stop_ext_b",
        "door_a", "door_b",
        "vacuum_power", "vacuum_pressure",
        "high_oil", "low_oil",
        "water", "hvolt_on", "g9sp_active",
    ]

    def __init__(self, pair: VirtualSerialPair):
        super().__init__(pair, "G9SP")
        self.state = {name: True for name in self.INTERLOCK_NAMES}
        self.state.update({
            "config_id": 0x0001,
            "unit_conduction_minutes": 0,
            "output_power_error": False,
            "function_block_error": False,
            "input_error_codes": [0] * 20,
            "output_error_codes": [0] * 20,
        })
        self._buf = b""
        self._started_at = time.time()

    def interlock_chain_ok(self) -> bool:
        with self.lock:
            return all(self.state.get(name, True) for name in self.INTERLOCK_NAMES[:11])

    def _pack_flags(self, bits: list[bool], total_bytes: int = 6) -> bytes:
        packed = bytearray(total_bytes)
        for i, bit in enumerate(bits):
            if bit:
                packed[i // 8] |= (1 << (i % 8))
        return bytes(packed)

    @staticmethod
    def _pack_nibbles(error_codes: list[int], total_bytes: int) -> bytes:
        packed = bytearray(total_bytes)
        for i in range(total_bytes):
            lo_idx = i * 2
            hi_idx = lo_idx + 1
            lo = int(error_codes[lo_idx]) & 0x0F if lo_idx < len(error_codes) else 0
            hi = int(error_codes[hi_idx]) & 0x0F if hi_idx < len(error_codes) else 0
            packed[i] = lo | (hi << 4)
        return bytes(packed)

    def _is_valid_request(self, frame: bytes) -> bool:
        if len(frame) != 19:
            return False
        # +0..+8 fixed command header per manual
        if frame[:9] != b"\x40\x00\x00\x0F\x4B\x03\x4D\x00\x01":
            return False
        if frame[17:19] != b"\x2A\x0D":
            return False
        recv_cksum = struct.unpack(">H", frame[15:17])[0]
        calc_cksum = sum(frame[:15]) & 0xFFFF
        return recv_cksum == calc_cksum

    def run(self):
        while not self._stop.is_set():
            chunk = self.pair.read(256, timeout=0.05)
            if chunk:
                self._buf += chunk
                self._try_respond()
            self._stop.wait(0.02)

    def _try_respond(self):
        # G9SP send packet = 19 bytes, starts with 0x40
        while len(self._buf) >= 19:
            idx = self._buf.find(b'\x40')
            if idx == -1:
                self._buf = b""
                return
            if idx > 0:
                self._buf = self._buf[idx:]
            if len(self._buf) < 19:
                return
            frame = self._buf[:19]
            self._buf = self._buf[19:]  # consume request
            if self._is_valid_request(frame):
                self._send_response()
            else:
                self._send_error_response()

    def _send_error_response(self):
        """Build a manual-conformant command-format error response."""
        resp = bytearray(199)
        resp[0] = 0x40
        resp[1] = 0x00
        resp[2] = 0x00
        resp[3] = 0x06  # Incorrect command format
        resp[4] = 0x00
        resp[5] = 0x01  # non-zero end code for format error
        # no service code/data for incorrect command format
        cksum = sum(resp[:195]) & 0xFFFF
        resp[195] = (cksum >> 8) & 0xFF
        resp[196] = cksum & 0xFF
        resp[197] = 0x2A
        resp[198] = 0x0D
        time.sleep(0.01)
        self.pair.write(bytes(resp))
        self._notify()

    def _send_response(self):
        """Build a 199-byte G9SP response packet."""
        resp = bytearray(199)
        resp[0] = 0x40
        resp[1] = 0x00
        resp[2] = 0x00
        resp[3] = 0xC3
        # End code + service code for normal response
        resp[4] = 0x00
        resp[5] = 0x00
        resp[6] = 0xCB
        # OCTD starts at byte 7
        resp[7:11] = b"\x00\x00\x00\x00"

        with self.lock:
            input_bits = [bool(self.state.get(name, False)) for name in self.INTERLOCK_NAMES]
            chain_ok = all(input_bits[:11])
            g9_active = bool(self.state.get("g9sp_active", True))
            input_error_codes = list(self.state.get("input_error_codes", [0] * 20))
            output_error_codes = list(self.state.get("output_error_codes", [0] * 20))
            output_power_error = bool(self.state.get("output_power_error", False))
            function_block_error = bool(self.state.get("function_block_error", False))
            config_id = int(self.state.get("config_id", 0x0001)) & 0xFFFF
            started_at = self._started_at

        # Update conduction time in minutes.
        conduction_minutes = max(0, int((time.time() - started_at) / 60.0)) & 0xFFFFFF
        with self.lock:
            self.state["unit_conduction_minutes"] = conduction_minutes

        sitdf_bytes = self._pack_flags(input_bits, total_bytes=6)
        # Status flags indicate terminal health (1=normal, 0=error), independent from ON/OFF data flags.
        input_status_bits = []
        for i in range(len(self.INTERLOCK_NAMES)):
            has_error = (i < len(input_error_codes) and int(input_error_codes[i]) != 0)
            input_status_bits.append(not has_error)
        sitsf_bytes = self._pack_flags(input_status_bits, total_bytes=6)

        # Output flags: bit 4 is consumed by driver as g9_active signal
        out_bits = [False] * 7
        out_bits[4] = bool(chain_ok and g9_active)
        sotdf_bytes = self._pack_flags(out_bits, total_bytes=4)
        output_status_bits = [True] * 7
        for i in range(7):
            if i < len(output_error_codes) and int(output_error_codes[i]) != 0:
                output_status_bits[i] = False
        sotsf_bytes = self._pack_flags(output_status_bits, total_bytes=4)

        sitec_bytes = self._pack_nibbles(input_error_codes, total_bytes=24)
        sotec_bytes = self._pack_nibbles(output_error_codes, total_bytes=16)

        safety_io_error = any(code != 0 for code in input_error_codes[:20]) or any(
            code != 0 for code in output_error_codes[:20]
        )

        # Unit Status bits per manual:
        # byte0 bit0: Unit Normal Operating Flag
        # byte1 bit1: Output Power Supply Error Flag
        # byte1 bit2: Safety I/O Terminal Error Flag
        # byte1 bit5: Function Block Error Flag
        unit_status_lo = 0x01 if not (output_power_error or safety_io_error or function_block_error) else 0x00
        unit_status_hi = 0x00
        if output_power_error:
            unit_status_hi |= 0x02
        if safety_io_error:
            unit_status_hi |= 0x04
        if function_block_error:
            unit_status_hi |= 0x20

        # SITDF at offset 11, 6 bytes
        resp[11:17] = sitdf_bytes
        # SOTDF at offset 17, 4 bytes
        resp[17:21] = sotdf_bytes
        # SITSF at offset 21, 6 bytes
        resp[21:27] = sitsf_bytes
        # SOTSF at offset 27, 4 bytes
        resp[27:31] = sotsf_bytes

        # SITEC at offset 31, 24 bytes
        resp[31:55] = sitec_bytes
        # SOTEC at offset 55, 16 bytes
        resp[55:71] = sotec_bytes
        # Unit Status at offset 73, 2 bytes
        resp[73] = unit_status_lo
        resp[74] = unit_status_hi

        # Configuration ID at offset 75, rightmost then leftmost byte
        resp[75] = config_id & 0xFF
        resp[76] = (config_id >> 8) & 0xFF

        # Unit conduction time at offset 77: 3 bytes little significance first + reserved byte
        resp[77] = conduction_minutes & 0xFF
        resp[78] = (conduction_minutes >> 8) & 0xFF
        resp[79] = (conduction_minutes >> 16) & 0xFF
        resp[80] = 0x00

        # Checksum at bytes 195–196: sum of 0..194 & 0xFFFF big-endian
        cksum = sum(resp[:195]) & 0xFFFF
        resp[195] = (cksum >> 8) & 0xFF
        resp[196] = cksum & 0xFF
        # Footer
        resp[197] = 0x2A
        resp[198] = 0x0D
        time.sleep(0.01)
        self.pair.write(bytes(resp))
        self._notify()


# ---------------------------------------------------------------------------
#  DP16 process monitor (Modbus RTU, up to 6 units)
# ---------------------------------------------------------------------------

class DP16ProcessMonitorSim(BaseSimulator):
    """Simulates 6 × DP16PT RTD temperature monitors (Modbus slaves 1–6)."""

    def __init__(self, pair: VirtualSerialPair):
        super().__init__(pair, "DP16")
        self.state = {
            "temp_1": 32.0,    # Solenoid 1
            "temp_2": 33.5,    # Solenoid 2
            "temp_3": 29.0,    # Chamber Top
            "temp_4": 30.0,    # Chamber Bot
            "temp_5": 22.0,    # Air temp
            "temp_6": 25.0,    # Unassigned
        }
        self._status_by_unit = {unit: 0x0006 for unit in range(1, 7)}
        # Manual default: 0x4A (Decimal point 2, °C, filter constant 4)
        self._rdgcnf_by_unit = {unit: 0x004A for unit in range(1, 7)}
        self._buf = b""

    def run(self):
        while not self._stop.is_set():
            chunk = self.pair.read(256, timeout=0.05)
            if chunk:
                self._buf += chunk
                self._process()
            # random walk
            with self.lock:
                for k in list(self.state.keys()):
                    self.state[k] += random.gauss(0, 0.05)
                    self.state[k] = max(-50.0, min(400.0, self.state[k]))
            self._notify()
            self._stop.wait(0.02)

    def _process(self):
        while len(self._buf) >= 8:
            slave = self._buf[0]
            func = self._buf[1]
            if func in (0x03, 0x04):
                if len(self._buf) < 8:
                    break
                frame = self._buf[:8]
                crc_recv = struct.unpack("<H", frame[6:8])[0]
                crc_calc = _modbus_crc(frame[:6])
                if crc_recv != crc_calc:
                    self._buf = self._buf[1:]
                    continue
                self._buf = self._buf[8:]
                addr = struct.unpack(">H", frame[2:4])[0]
                count = struct.unpack(">H", frame[4:6])[0]
                self._respond_read(slave, func, addr, count)
            elif func == 0x06:
                if len(self._buf) < 8:
                    break
                frame = self._buf[:8]
                crc_recv = struct.unpack("<H", frame[6:8])[0]
                crc_calc = _modbus_crc(frame[:6])
                if crc_recv != crc_calc:
                    self._buf = self._buf[1:]
                    continue
                self._buf = self._buf[8:]
                addr = struct.unpack(">H", frame[2:4])[0]
                value = struct.unpack(">H", frame[4:6])[0]
                self._respond_write_single(slave, addr, value)
            else:
                # Unknown function code for a valid slave -> Modbus exception 01
                self._buf = self._buf[1:]
                if 1 <= slave <= 6:
                    self.pair.write(_modbus_exception(slave, func, 0x01))

    @staticmethod
    def _rdgcnf_decimal_multiplier(rdgcnf: int) -> int:
        decimal_code = (rdgcnf >> 5) & 0x07
        if decimal_code == 1:
            return 1
        if decimal_code == 2:
            return 10
        if decimal_code == 3:
            return 100
        if decimal_code == 4:
            return 1000
        return 1

    def _respond_read(self, slave: int, func: int, addr: int, count: int):
        if slave < 1 or slave > 6:
            return

        if count <= 0:
            self.pair.write(_modbus_exception(slave, func, 0x03))
            return

        with self.lock:
            temp = self.state.get(f"temp_{slave}", 25.0)

        if addr == 0x0210:
            # Driver map: process value as IEEE 754 float in two registers
            if count != 2:
                self.pair.write(_modbus_exception(slave, func, 0x03))
                return
            # Process value as IEEE 754 big-endian float
            raw = struct.pack(">f", temp)
            hi, lo = struct.unpack(">HH", raw)
            payload = bytes([4]) + struct.pack(">H", hi) + struct.pack(">H", lo)
        elif addr == 0x0240:
            # Driver map: status register
            if count != 1:
                self.pair.write(_modbus_exception(slave, func, 0x03))
                return
            with self.lock:
                status = self._status_by_unit.get(slave, 0x0006)
            payload = bytes([2]) + struct.pack(">H", status)
        elif addr == 0x0248:
            # Driver map: reading config register
            if count != 1:
                self.pair.write(_modbus_exception(slave, func, 0x03))
                return
            with self.lock:
                rdgcnf = self._rdgcnf_by_unit.get(slave, 0x004A)
            payload = bytes([2]) + struct.pack(">H", rdgcnf)
        elif addr == 8:
            # Manual table 6.2: RDGCNF register
            if count != 1:
                self.pair.write(_modbus_exception(slave, func, 0x03))
                return
            with self.lock:
                rdgcnf = self._rdgcnf_by_unit.get(slave, 0x004A)
            payload = bytes([2]) + struct.pack(">H", rdgcnf)
        elif addr == 39:
            # Manual table 6.2: Process value as signed integer counts
            if count != 1:
                self.pair.write(_modbus_exception(slave, func, 0x03))
                return
            with self.lock:
                rdgcnf = self._rdgcnf_by_unit.get(slave, 0x004A)
            multiplier = self._rdgcnf_decimal_multiplier(rdgcnf)
            raw_counts = int(round(temp * multiplier))
            raw_counts = max(-32768, min(32767, raw_counts))
            payload = bytes([2]) + struct.pack(">H", raw_counts & 0xFFFF)
        else:
            self.pair.write(_modbus_exception(slave, func, 0x02))
            return

        resp = _modbus_response(slave, func, payload)
        time.sleep(0.005)
        self.pair.write(resp)

    def _respond_write_single(self, slave: int, addr: int, value: int):
        if slave < 1 or slave > 6:
            return

        with self.lock:
            if addr in (8, 0x0248):
                # RDGCNF is 8-bit in manual; keep upper byte zeroed
                self._rdgcnf_by_unit[slave] = value & 0x00FF
            elif addr == 0x0240:
                self._status_by_unit[slave] = value & 0xFFFF
            else:
                self.pair.write(_modbus_exception(slave, 0x06, 0x02))
                return

        # Per Modbus spec for FC06: echo request fields
        payload = struct.pack(">H", addr) + struct.pack(">H", value & 0xFFFF)
        resp = _modbus_response(slave, 0x06, payload)
        time.sleep(0.005)
        self.pair.write(resp)


# ---------------------------------------------------------------------------
#  BCON beam pulse controller (Modbus RTU, 160 registers)
# ---------------------------------------------------------------------------

class BCONDriverSim(BaseSimulator):
    """Simulates the BCON Arduino Mega Modbus RTU firmware."""

    # Register layout
    REG_WATCHDOG_MS = 0
    REG_TELEMETRY_MS = 1
    REG_COMMAND = 2
    # CH params: base 10/20/30  +  0=mode, 1=pulse_ms, 2=count, 3=enable_toggle
    # Status: base 100
    REG_SYS_STATE = 100
    REG_SYS_REASON = 101
    REG_FAULT_LATCHED = 102
    REG_INTERLOCK_OK = 103
    REG_WATCHDOG_OK = 104
    REG_LAST_ERROR = 105
    # CH status: base 110/120/130  +  0=mode,1=pulse_ms,2=count,3=remaining,4=en_st,5=pwr_st,6=oc_st,7=gated_st,8=output_level

    MODBUS_SLAVE_ID = 1
    HEARTBEAT_MIN_MS = 50
    HEARTBEAT_MAX_MS = 60000
    DEFAULT_WATCHDOG_MS = 1500
    DEFAULT_TELEMETRY_MS = 1500
    WATCHDOG_BOOT_GRACE_MS = 4000

    PULSE_DURATION_MIN_MS = 1
    PULSE_DURATION_MAX_MS = 60000
    PULSE_COUNT_MIN = 1
    PULSE_COUNT_MAX = 10000

    # Firmware-like modbus error codes exposed in REG_LAST_ERROR
    ERR_NONE = 0
    ERR_ILLEGAL_FUNCTION = 1
    ERR_ILLEGAL_ADDRESS = 2
    ERR_ILLEGAL_VALUE = 3
    ERR_DEVICE_FAILURE = 4
    ERR_NOT_READY = 10
    ERR_FAULT_STILL_ACTIVE = 11
    ERR_INTERLOCK_NOT_READY = 12
    ERR_BUFFER_OVERFLOW = 13

    def __init__(self, pair: VirtualSerialPair):
        super().__init__(pair, "BCON")

        self.watchdog_timeout_ms = self.DEFAULT_WATCHDOG_MS
        self.telemetry_period_ms = self.DEFAULT_TELEMETRY_MS
        self._interlock_input_ok = True
        self.last_command_ms = self._now_ms()
        self.watchdog_grace_deadline_ms = self.last_command_ms + self.WATCHDOG_BOOT_GRACE_MS
        self.last_modbus_error = self.ERR_NONE

        self._channels = {
            1: {"mode": 0, "pulse_ms": 100, "count": 1, "remaining": 0, "output": 0,
                "enabled": False, "power": False, "overcurrent": False, "gated": 0,
                "phase": "idle", "deadline_ms": 0},
            2: {"mode": 0, "pulse_ms": 100, "count": 1, "remaining": 0, "output": 0,
                "enabled": False, "power": False, "overcurrent": False, "gated": 0,
                "phase": "idle", "deadline_ms": 0},
            3: {"mode": 0, "pulse_ms": 100, "count": 1, "remaining": 0, "output": 0,
                "enabled": False, "power": False, "overcurrent": False, "gated": 0,
                "phase": "idle", "deadline_ms": 0},
        }

        self.state = {
            "sys_state": 0,       # 0=READY
            "armed": False,
            "interlock_ok": True,
            "interlock_forced_off": False,
            "fault_latched": False,
            "watchdog_ok": True,
            "last_error": 0,
            "ch1_mode": 0, "ch1_enabled": False, "ch1_output": 0,
            "ch2_mode": 0, "ch2_enabled": False, "ch2_output": 0,
            "ch3_mode": 0, "ch3_enabled": False, "ch3_output": 0,
        }
        self._buf = b""

    def run(self):
        while not self._stop.is_set():
            chunk = self.pair.read(512, timeout=0.05)
            if chunk:
                self._buf += chunk
                self._process()
            self._update_overcurrent_latch()
            self._apply_outputs()
            self._sync_public_state()
            self._stop.wait(0.02)

    def set_interlock_ok(self, ok: bool):
        with self.lock:
            self._interlock_input_ok = bool(ok)

    def force_interlock_off(self):
        with self.lock:
            self.state["interlock_forced_off"] = True
            self.state["interlock_ok"] = False

    def reset_interlock(self):
        with self.lock:
            self.state["interlock_forced_off"] = False
            self.state["interlock_ok"] = bool(self._interlock_input_ok)

    def _now_ms(self) -> int:
        return int(time.monotonic() * 1000)

    def _is_watchdog_healthy(self) -> bool:
        now = self._now_ms()
        if now < self.watchdog_grace_deadline_ms:
            return True
        return (now - self.last_command_ms) <= self.watchdog_timeout_ms

    def _is_interlock_satisfied(self) -> bool:
        if bool(self.state.get("interlock_forced_off", False)):
            return False
        return bool(self._interlock_input_ok)

    def _is_any_overcurrent_asserted(self) -> bool:
        return any(self._channels[ch]["overcurrent"] for ch in (1, 2, 3))

    def _evaluate_top_level_state(self) -> int:
        if not self._is_interlock_satisfied():
            return 1
        if not self._is_watchdog_healthy():
            return 2
        if self.state.get("fault_latched", False):
            return 3
        return 0

    def _set_modbus_error(self, code: int):
        self.last_modbus_error = code

    def _set_channel_off(self, ch: int):
        c = self._channels[ch]
        c["mode"] = 0
        c["remaining"] = 0
        c["output"] = 0
        c["gated"] = 0
        c["phase"] = "idle"
        c["deadline_ms"] = 0

    def _set_channel_dc(self, ch: int):
        c = self._channels[ch]
        c["mode"] = 1
        c["remaining"] = 0
        c["output"] = 1
        c["gated"] = 1
        c["phase"] = "dc"
        c["deadline_ms"] = 0

    def _set_channel_pulse(self, ch: int):
        c = self._channels[ch]
        c["mode"] = 2
        c["remaining"] = 1
        c["output"] = 1
        c["gated"] = 1
        c["phase"] = "pulse_high"
        c["deadline_ms"] = self._now_ms() + int(c["pulse_ms"])

    def _set_channel_pulse_train(self, ch: int):
        c = self._channels[ch]
        c["mode"] = 3
        c["remaining"] = int(c["count"])
        c["output"] = 1
        c["gated"] = 1
        c["phase"] = "train_high"
        c["deadline_ms"] = self._now_ms() + int(c["pulse_ms"])

    def _update_overcurrent_latch(self):
        if self._is_any_overcurrent_asserted():
            self.state["fault_latched"] = True

    def _apply_outputs(self):
        now = self._now_ms()
        top_state = self._evaluate_top_level_state()

        if top_state != 0:
            for ch in (1, 2, 3):
                self._channels[ch]["output"] = 0
                self._channels[ch]["gated"] = 0
            return

        for ch in (1, 2, 3):
            c = self._channels[ch]
            mode = c["mode"]

            if mode == 0:
                c["output"] = 0
                c["gated"] = 0
                c["phase"] = "idle"
                c["deadline_ms"] = 0
                c["remaining"] = 0
                continue

            if mode == 1:
                c["output"] = 1
                c["gated"] = 1
                c["phase"] = "dc"
                continue

            if mode == 2:
                if now >= c["deadline_ms"]:
                    self._set_channel_off(ch)
                continue

            if mode == 3 and now >= c["deadline_ms"]:
                if c["phase"] == "train_high":
                    c["output"] = 0
                    c["gated"] = 0
                    if c["remaining"] > 0:
                        c["remaining"] -= 1
                    if c["remaining"] == 0:
                        self._set_channel_off(ch)
                    else:
                        c["phase"] = "train_low"
                        c["deadline_ms"] = now + int(c["pulse_ms"])
                else:
                    c["output"] = 1
                    c["gated"] = 1
                    c["phase"] = "train_high"
                    c["deadline_ms"] = now + int(c["pulse_ms"])

    def _sync_public_state(self):
        with self.lock:
            self.state["sys_state"] = self._evaluate_top_level_state()
            self.state["interlock_ok"] = self._is_interlock_satisfied()
            self.state["watchdog_ok"] = self._is_watchdog_healthy()
            self.state["fault_latched"] = bool(self.state.get("fault_latched", False))
            self.state["last_error"] = self.last_modbus_error
            self.state["armed"] = (self.state["sys_state"] == 0 and not self.state["fault_latched"])
            for ch in (1, 2, 3):
                c = self._channels[ch]
                self.state[f"ch{ch}_mode"] = c["mode"]
                self.state[f"ch{ch}_enabled"] = bool(c["enabled"])
                self.state[f"ch{ch}_output"] = int(c["output"])

    def _decode_channel_control_register(self, reg: int):
        if reg < 10 or reg > 33:
            return None
        decade = reg // 10
        units = reg % 10
        if decade < 1 or decade > 3 or units > 3:
            return None
        return decade, units

    def _decode_channel_status_register(self, reg: int):
        if reg < 110:
            return None
        delta = reg - 110
        ch_index = delta // 10
        field = delta % 10
        if ch_index > 2 or field > 8:
            return None
        return ch_index + 1, field

    def _read_holding_register(self, reg: int):
        if reg == self.REG_WATCHDOG_MS:
            return int(self.watchdog_timeout_ms)
        if reg == self.REG_TELEMETRY_MS:
            return int(self.telemetry_period_ms)
        if reg == self.REG_COMMAND:
            return 0
        if reg == self.REG_SYS_STATE:
            return self._evaluate_top_level_state()
        if reg == self.REG_SYS_REASON:
            return self._evaluate_top_level_state()
        if reg == self.REG_FAULT_LATCHED:
            return 1 if self.state.get("fault_latched", False) else 0
        if reg == self.REG_INTERLOCK_OK:
            return 1 if self._is_interlock_satisfied() else 0
        if reg == self.REG_WATCHDOG_OK:
            return 1 if self._is_watchdog_healthy() else 0
        if reg == self.REG_LAST_ERROR:
            return int(self.last_modbus_error)

        decoded_control = self._decode_channel_control_register(reg)
        if decoded_control:
            ch, field = decoded_control
            c = self._channels[ch]
            if field == 0:
                return int(c["mode"])
            if field == 1:
                return int(c["pulse_ms"])
            if field == 2:
                return int(c["count"])
            if field == 3:
                return 0

        decoded_status = self._decode_channel_status_register(reg)
        if decoded_status:
            ch, field = decoded_status
            c = self._channels[ch]
            if field == 0:
                return int(c["mode"])
            if field == 1:
                return int(c["pulse_ms"])
            if field == 2:
                return int(c["count"])
            if field == 3:
                return int(c["remaining"])
            if field == 4:
                return 1 if c["enabled"] else 0
            if field == 5:
                return 1 if c["power"] else 0
            if field == 6:
                return 1 if c["overcurrent"] else 0
            if field == 7:
                return 1 if c["gated"] else 0
            if field == 8:
                return 1 if c["output"] else 0

        return None

    def _write_holding_register(self, reg: int, value: int):
        ex_out = 0x03

        if reg == self.REG_WATCHDOG_MS:
            if value < self.HEARTBEAT_MIN_MS or value > self.HEARTBEAT_MAX_MS:
                self._set_modbus_error(self.ERR_ILLEGAL_VALUE)
                return False, ex_out
            self.watchdog_timeout_ms = int(value)
            self._set_modbus_error(self.ERR_NONE)
            return True, ex_out

        if reg == self.REG_TELEMETRY_MS:
            self.telemetry_period_ms = int(value)
            self._set_modbus_error(self.ERR_NONE)
            return True, ex_out

        if reg == self.REG_COMMAND:
            if value == 0:
                self._set_modbus_error(self.ERR_NONE)
                return True, ex_out
            if value == 1:
                for ch in (1, 2, 3):
                    self._set_channel_off(ch)
                self._set_modbus_error(self.ERR_NONE)
                return True, ex_out
            if value in (2, 3):
                if self._is_any_overcurrent_asserted():
                    self._set_modbus_error(self.ERR_FAULT_STILL_ACTIVE)
                    return False, 0x04
                if not self._is_interlock_satisfied():
                    self._set_modbus_error(self.ERR_INTERLOCK_NOT_READY)
                    return False, 0x04
                self.state["fault_latched"] = False
                self._set_modbus_error(self.ERR_NONE)
                return True, ex_out
            self._set_modbus_error(self.ERR_ILLEGAL_VALUE)
            return False, ex_out

        decoded = self._decode_channel_control_register(reg)
        if not decoded:
            self._set_modbus_error(self.ERR_ILLEGAL_ADDRESS)
            return False, 0x02

        ch, field = decoded
        c = self._channels[ch]

        if field == 1:
            if value < self.PULSE_DURATION_MIN_MS or value > self.PULSE_DURATION_MAX_MS:
                self._set_modbus_error(self.ERR_ILLEGAL_VALUE)
                return False, ex_out
            c["pulse_ms"] = int(value)
            self._set_modbus_error(self.ERR_NONE)
            return True, ex_out

        if field == 2:
            if value < self.PULSE_COUNT_MIN or value > self.PULSE_COUNT_MAX:
                self._set_modbus_error(self.ERR_ILLEGAL_VALUE)
                return False, ex_out
            c["count"] = int(value)
            self._set_modbus_error(self.ERR_NONE)
            return True, ex_out

        if field == 3:
            if value != 1:
                self._set_modbus_error(self.ERR_ILLEGAL_VALUE)
                return False, ex_out
            c["enabled"] = not c["enabled"]
            c["power"] = bool(c["enabled"])
            self._set_modbus_error(self.ERR_NONE)
            return True, ex_out

        if field == 0:
            top_state = self._evaluate_top_level_state()

            if value == 0:
                self._set_channel_off(ch)
                self._set_modbus_error(self.ERR_NONE)
                return True, ex_out

            if top_state != 0:
                self._set_modbus_error(self.ERR_NOT_READY)
                return False, 0x04

            if value == 1:
                if not c["enabled"]:
                    c["enabled"] = True
                    c["power"] = True
                self._set_channel_dc(ch)
                self._set_modbus_error(self.ERR_NONE)
                return True, ex_out

            if value == 2:
                if not c["enabled"]:
                    c["enabled"] = True
                    c["power"] = True
                if c["count"] <= 1:
                    self._set_channel_pulse(ch)
                else:
                    self._set_channel_pulse_train(ch)
                self._set_modbus_error(self.ERR_NONE)
                return True, ex_out

            if value == 3:
                if c["count"] < 2:
                    self._set_modbus_error(self.ERR_ILLEGAL_VALUE)
                    return False, ex_out
                if not c["enabled"]:
                    c["enabled"] = True
                    c["power"] = True
                self._set_channel_pulse_train(ch)
                self._set_modbus_error(self.ERR_NONE)
                return True, ex_out

            self._set_modbus_error(self.ERR_ILLEGAL_VALUE)
            return False, ex_out

        self._set_modbus_error(self.ERR_ILLEGAL_ADDRESS)
        return False, 0x02

    def _process(self):
        while len(self._buf) >= 8:
            slave = self._buf[0]
            func = self._buf[1]
            is_broadcast = (slave == 0)

            if func == 0x03:  # read holding registers
                if len(self._buf) < 8:
                    break
                frame = self._buf[:8]
                crc_recv = struct.unpack("<H", frame[6:8])[0]
                if crc_recv != _modbus_crc(frame[:6]):
                    self._buf = self._buf[1:]
                    continue
                self._buf = self._buf[8:]
                if slave not in (0, self.MODBUS_SLAVE_ID):
                    continue
                self.last_command_ms = self._now_ms()
                addr = struct.unpack(">H", frame[2:4])[0]
                count = struct.unpack(">H", frame[4:6])[0]
                self._respond_read(slave, addr, count, is_broadcast)

            elif func == 0x06:  # write single register
                if len(self._buf) < 8:
                    break
                frame = self._buf[:8]
                crc_recv = struct.unpack("<H", frame[6:8])[0]
                if crc_recv != _modbus_crc(frame[:6]):
                    self._buf = self._buf[1:]
                    continue
                self._buf = self._buf[8:]
                if slave not in (0, self.MODBUS_SLAVE_ID):
                    continue
                self.last_command_ms = self._now_ms()
                addr = struct.unpack(">H", frame[2:4])[0]
                value = struct.unpack(">H", frame[4:6])[0]
                self._handle_write_single(slave, addr, value, frame, is_broadcast)

            elif func == 0x10:  # write multiple registers
                if len(self._buf) < 9:
                    break
                quantity = struct.unpack(">H", self._buf[4:6])[0]
                byte_count = self._buf[6]
                frame_len = 9 + byte_count
                if len(self._buf) < frame_len:
                    break
                frame = self._buf[:frame_len]
                crc_recv = struct.unpack("<H", frame[-2:])[0]
                if crc_recv != _modbus_crc(frame[:-2]):
                    self._buf = self._buf[1:]
                    continue
                self._buf = self._buf[frame_len:]
                if slave not in (0, self.MODBUS_SLAVE_ID):
                    continue
                self.last_command_ms = self._now_ms()
                self._handle_write_multiple(slave, frame, is_broadcast)
            else:
                # Unsupported function: drop one byte and keep searching.
                self._buf = self._buf[1:]

    def _respond_read(self, slave: int, addr: int, count: int, is_broadcast: bool):
        if count == 0 or count > 125:
            self._set_modbus_error(self.ERR_ILLEGAL_VALUE)
            if not is_broadcast:
                self.pair.write(_modbus_exception(slave, 0x03, 0x03))
            return

        regs: list[int] = []
        with self.lock:
            for i in range(count):
                val = self._read_holding_register(addr + i)
                if val is None:
                    self._set_modbus_error(self.ERR_ILLEGAL_ADDRESS)
                    if not is_broadcast:
                        self.pair.write(_modbus_exception(slave, 0x03, 0x02))
                    return
                regs.append(int(val) & 0xFFFF)

        payload = bytes([count * 2])
        for val in regs:
            payload += struct.pack(">H", val)

        self._set_modbus_error(self.ERR_NONE)
        if not is_broadcast:
            resp = _modbus_response(slave, 0x03, payload)
            time.sleep(0.002)
            self.pair.write(resp)

    def _handle_write_single(self, slave: int, addr: int, value: int, frame: bytes, is_broadcast: bool):
        with self.lock:
            ok, ex_code = self._write_holding_register(addr, value)
            self._sync_public_state()

        self._notify()
        if ok:
            if not is_broadcast:
                resp = _modbus_response(slave, 0x06, frame[2:6])
                time.sleep(0.002)
                self.pair.write(resp)
            return

        if not is_broadcast:
            self.pair.write(_modbus_exception(slave, 0x06, ex_code))

    def _handle_write_multiple(self, slave: int, frame: bytes, is_broadcast: bool):
        start_reg = struct.unpack(">H", frame[2:4])[0]
        quantity = struct.unpack(">H", frame[4:6])[0]
        byte_count = frame[6]

        if quantity == 0 or quantity > 123 or byte_count != quantity * 2:
            self._set_modbus_error(self.ERR_ILLEGAL_VALUE)
            if not is_broadcast:
                self.pair.write(_modbus_exception(slave, 0x10, 0x03))
            return

        values = []
        for i in range(quantity):
            off = 7 + i * 2
            values.append(struct.unpack(">H", frame[off:off + 2])[0])

        with self.lock:
            for i, value in enumerate(values):
                ok, ex_code = self._write_holding_register(start_reg + i, value)
                if not ok:
                    self._sync_public_state()
                    if not is_broadcast:
                        self.pair.write(_modbus_exception(slave, 0x10, ex_code))
                    return
            self._sync_public_state()

        self._notify()
        if not is_broadcast:
            payload = struct.pack(">HH", start_reg, quantity)
            resp = _modbus_response(slave, 0x10, payload)
            time.sleep(0.002)
            self.pair.write(resp)
