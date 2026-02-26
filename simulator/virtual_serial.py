"""
virtual_serial.py — Cross-platform virtual serial abstraction.

Linux/macOS:
  Uses PTY master/slave pairs. The dashboard opens the slave path
  (e.g. /dev/pts/12), while simulator threads read/write on the master fd.

Windows:
  Uses real COM null-modem pairs (typically provided by com0com).
  The simulator opens one endpoint (sim side), while the dashboard opens the
  paired endpoint (dashboard side).

Windows port mapping priority:
  1) EBEAM_SIM_PORT_MAP_FILE -> JSON file path
  2) EBEAM_SIM_PORT_MAP      -> JSON string
  3) Auto-detect com0com pairs CNCAx <-> CNCBx

Mapping JSON format:
{
  "VTRXSubsystem": {"sim": "CNCA0", "dashboard": "CNCB0"},
  "CathodeA PS":   {"sim": "CNCA1", "dashboard": "CNCB1"},
  ...
}
"""

from __future__ import annotations

import json
import os
import select
import threading
from typing import Dict, Tuple

if os.name != "nt":
    import pty
    import tty
else:
    pty = None
    tty = None

import serial
import serial.tools.list_ports as list_ports


class VirtualSerialPair:
    """Abstract pair API used by simulator backends."""

    def __init__(self, name: str):
        self.name = name
        self.slave_path: str = ""

    def write(self, data: bytes) -> None:
        raise NotImplementedError

    def read(self, size: int = 1024, timeout: float = 0.1) -> bytes:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError


class PtyVirtualSerialPair(VirtualSerialPair):
    """Linux/macOS PTY-backed virtual serial cable."""

    def __init__(self, name: str):
        super().__init__(name)
        self.master_fd, self.slave_fd = pty.openpty()
        tty.setraw(self.master_fd)
        tty.setraw(self.slave_fd)
        self.slave_path = os.ttyname(self.slave_fd)

    def write(self, data: bytes) -> None:
        try:
            os.write(self.master_fd, data)
        except OSError:
            pass

    def read(self, size: int = 1024, timeout: float = 0.1) -> bytes:
        ready, _, _ = select.select([self.master_fd], [], [], timeout)
        if ready:
            try:
                return os.read(self.master_fd, size)
            except OSError:
                return b""
        return b""

    def close(self) -> None:
        for fd in (self.master_fd, self.slave_fd):
            try:
                os.close(fd)
            except OSError:
                pass

    def __repr__(self) -> str:
        return f"PtyVirtualSerialPair({self.name!r}, slave={self.slave_path!r})"


class ComVirtualSerialPair(VirtualSerialPair):
    """Windows COM null-modem-backed simulator endpoint."""

    def __init__(self, name: str, sim_port: str, dashboard_port: str):
        super().__init__(name)
        self.sim_port = sim_port
        self.slave_path = dashboard_port
        self._lock = threading.Lock()
        self._ser = serial.Serial(
            port=self.sim_port,
            baudrate=115200,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0,
            write_timeout=0,
        )

    def write(self, data: bytes) -> None:
        with self._lock:
            try:
                self._ser.write(data)
            except Exception:
                pass

    def read(self, size: int = 1024, timeout: float = 0.1) -> bytes:
        with self._lock:
            try:
                waiting = self._ser.in_waiting
                if waiting > 0:
                    return self._ser.read(min(size, waiting))
            except Exception:
                return b""

        # mimic timeout behavior without busy spin
        if timeout > 0:
            import time
            time.sleep(timeout)

        with self._lock:
            try:
                waiting = self._ser.in_waiting
                if waiting > 0:
                    return self._ser.read(min(size, waiting))
            except Exception:
                return b""
        return b""

    def close(self) -> None:
        with self._lock:
            try:
                self._ser.close()
            except Exception:
                pass

    def __repr__(self) -> str:
        return (
            f"ComVirtualSerialPair({self.name!r}, sim={self.sim_port!r}, "
            f"dashboard={self.slave_path!r})"
        )


class PortManager:
    """Creates and manages all virtual serial pairs needed by the simulator."""

    PORT_NAMES = [
        "VTRXSubsystem",
        "CathodeA PS",
        "CathodeB PS",
        "CathodeC PS",
        "TempControllers",
        "Interlocks",
        "ProcessMonitors",
        "BeamPulse",
    ]

    def __init__(self):
        self.pairs: dict[str, VirtualSerialPair] = {}

        if os.name == "nt":
            mapping = self._load_windows_mapping()
            for name in self.PORT_NAMES:
                pair = mapping.get(name)
                if not pair:
                    raise RuntimeError(
                        f"Windows port map missing entry for '{name}'."
                    )
                self.pairs[name] = ComVirtualSerialPair(
                    name=name,
                    sim_port=pair[0],
                    dashboard_port=pair[1],
                )
        else:
            for name in self.PORT_NAMES:
                self.pairs[name] = PtyVirtualSerialPair(name)

    def _load_windows_mapping(self) -> Dict[str, Tuple[str, str]]:
        # 1) Mapping file
        map_file = os.environ.get("EBEAM_SIM_PORT_MAP_FILE", "").strip()
        if map_file:
            with open(map_file, "r", encoding="utf-8") as f:
                raw = json.load(f)
            return self._normalize_mapping(raw)

        # 2) Mapping json string
        map_json = os.environ.get("EBEAM_SIM_PORT_MAP", "").strip()
        if map_json:
            raw = json.loads(map_json)
            return self._normalize_mapping(raw)

        # 3) Auto-detect com0com style CNCAx<->CNCBx
        auto = self._autodetect_com0com_pairs()
        if auto:
            return auto

        raise RuntimeError(
            "Windows requires COM pair mapping. Install com0com and create "
            "at least 8 CNCAx/CNCBx pairs, or set EBEAM_SIM_PORT_MAP_FILE / "
            "EBEAM_SIM_PORT_MAP."
        )

    def _normalize_mapping(self, raw: dict) -> Dict[str, Tuple[str, str]]:
        out: Dict[str, Tuple[str, str]] = {}
        for name in self.PORT_NAMES:
            entry = raw.get(name)
            if not isinstance(entry, dict):
                continue
            sim_port = str(entry.get("sim", "")).strip()
            dashboard_port = str(entry.get("dashboard", "")).strip()
            if sim_port and dashboard_port:
                out[name] = (sim_port, dashboard_port)
        return out

    def _autodetect_com0com_pairs(self) -> Dict[str, Tuple[str, str]]:
        ports = [p.device.upper() for p in list_ports.comports()]

        # Build CNCAx/CNCBx index
        a_ports: dict[str, str] = {}
        b_ports: dict[str, str] = {}
        for dev in ports:
            if dev.startswith("CNCA"):
                a_ports[dev[4:]] = dev
            elif dev.startswith("CNCB"):
                b_ports[dev[4:]] = dev

        suffixes = sorted(set(a_ports.keys()) & set(b_ports.keys()), key=lambda s: (len(s), s))
        if len(suffixes) < len(self.PORT_NAMES):
            return {}

        mapping: Dict[str, Tuple[str, str]] = {}
        for i, name in enumerate(self.PORT_NAMES):
            suf = suffixes[i]
            mapping[name] = (a_ports[suf], b_ports[suf])
        return mapping

    def com_ports(self) -> dict[str, str]:
        return {name: pair.slave_path for name, pair in self.pairs.items()}

    def get(self, name: str) -> VirtualSerialPair:
        return self.pairs[name]

    def close_all(self) -> None:
        for pair in self.pairs.values():
            pair.close()

    def __repr__(self) -> str:
        lines = [f"  {name}: {pair.slave_path}" for name, pair in self.pairs.items()]
        return "PortManager(\n" + "\n".join(lines) + "\n)"
