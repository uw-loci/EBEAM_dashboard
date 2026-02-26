"""
virtual_serial.py — Linux PTY-based virtual serial port pairs.

Creates master/slave pseudo-terminal pairs.  The *slave* path is given to the
dashboard (it looks like ``/dev/pts/XX`` — a normal serial device) while the
*master* file-descriptor is used internally by the simulator threads.
"""

import os
import pty
import tty
import threading
import select


class VirtualSerialPair:
    """One PTY pair representing a virtual serial cable between simulator and dashboard."""

    def __init__(self, name: str):
        self.name = name
        self.master_fd, self.slave_fd = pty.openpty()
        # Put master in raw mode so the kernel doesn't interpret control chars.
        tty.setraw(self.master_fd)
        tty.setraw(self.slave_fd)
        self.slave_path: str = os.ttyname(self.slave_fd)

    # -- Simulator side (master fd) helpers ----------------------------------

    def write(self, data: bytes) -> None:
        """Write *data* from the simulator side to the dashboard side."""
        try:
            os.write(self.master_fd, data)
        except OSError:
            pass

    def read(self, size: int = 1024, timeout: float = 0.1) -> bytes:
        """Non-blocking read of up to *size* bytes from the dashboard side.

        Returns ``b''`` if nothing is available within *timeout* seconds.
        """
        ready, _, _ = select.select([self.master_fd], [], [], timeout)
        if ready:
            try:
                return os.read(self.master_fd, size)
            except OSError:
                return b""
        return b""

    def fileno(self) -> int:
        return self.master_fd

    def close(self) -> None:
        for fd in (self.master_fd, self.slave_fd):
            try:
                os.close(fd)
            except OSError:
                pass

    def __repr__(self) -> str:
        return f"VirtualSerialPair({self.name!r}, slave={self.slave_path!r})"


class PortManager:
    """Creates and manages all virtual serial pairs needed by the simulator."""

    # Map of logical port name → VirtualSerialPair
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
        for name in self.PORT_NAMES:
            self.pairs[name] = VirtualSerialPair(name)

    def com_ports(self) -> dict[str, str]:
        """Return a dict compatible with the dashboard's *com_ports* mapping.

        Values are slave PTY paths that the dashboard can open like real serial
        ports.
        """
        return {name: pair.slave_path for name, pair in self.pairs.items()}

    def get(self, name: str) -> VirtualSerialPair:
        return self.pairs[name]

    def close_all(self) -> None:
        for pair in self.pairs.values():
            pair.close()

    def __repr__(self) -> str:
        lines = [f"  {name}: {pair.slave_path}" for name, pair in self.pairs.items()]
        return "PortManager(\n" + "\n".join(lines) + "\n)"
