#!/usr/bin/env python3
"""
run_simulator.py — Launch the EBEAM hardware simulator.

Creates virtual serial port pairs, starts all instrument simulator threads,
opens the Material-style simulator GUI, and (optionally) launches the
dashboard pointing at the virtual ports.

Usage:
    python -m simulator.run_simulator               # simulator GUI only
    python -m simulator.run_simulator --dashboard    # also start dashboard
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

# Ensure project root is on sys.path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from simulator.virtual_serial import PortManager
from simulator.instruments import (
    VTRXSimulator,
    PowerSupply9104Sim,
    E5CNModbusSim,
    G9DriverSim,
    DP16ProcessMonitorSim,
    BCONDriverSim,
)
from simulator.sim_gui import SimulatorGUI


def main():
    parser = argparse.ArgumentParser(description="EBEAM Hardware Simulator")
    parser.add_argument("--dashboard", action="store_true",
                        help="Automatically launch the dashboard connected to virtual ports")
    parser.add_argument("--print-ports", action="store_true",
                        help="Print the virtual port mapping as JSON and exit")
    args = parser.parse_args()

    # ── 1. Create virtual serial port pairs ───────────────────────────────
    pm = PortManager()
    print("Virtual serial port pairs created:")
    print(pm)

    # ── 2. Instantiate instrument simulators ──────────────────────────────
    simulators = {
        "VTRX":      VTRXSimulator(pm.get("VTRXSubsystem")),
        "CathodeA":  PowerSupply9104Sim(pm.get("CathodeA PS"), "CathodeA"),
        "CathodeB":  PowerSupply9104Sim(pm.get("CathodeB PS"), "CathodeB"),
        "CathodeC":  PowerSupply9104Sim(pm.get("CathodeC PS"), "CathodeC"),
        "E5CN":      E5CNModbusSim(pm.get("TempControllers")),
        "G9SP":      G9DriverSim(pm.get("Interlocks")),
        "DP16":      DP16ProcessMonitorSim(pm.get("ProcessMonitors")),
        "BCON":      BCONDriverSim(pm.get("BeamPulse")),
    }

    # ── 3. Start all simulator threads ────────────────────────────────────
    for name, sim in simulators.items():
        sim.start()
        print(f"  ✓ {name} simulator started")

    # ── 4. Optionally print ports and exit ────────────────────────────────
    if args.print_ports:
        print(json.dumps(pm.com_ports(), indent=2))
        return

    # ── 5. Optionally launch the dashboard ────────────────────────────────
    dashboard_proc = None
    if args.dashboard:
        # Write the virtual-port mapping so the dashboard can load it
        com_ports_path = os.path.join(_PROJECT_ROOT, "usr", "usr_data", "com_ports.json")
        os.makedirs(os.path.dirname(com_ports_path), exist_ok=True)
        with open(com_ports_path, "w") as f:
            json.dump(pm.com_ports(), f, indent=2)
        print(f"\n  COM port mapping written to {com_ports_path}")

        # Launch dashboard as a subprocess
        dashboard_proc = subprocess.Popen(
            [sys.executable, os.path.join(_PROJECT_ROOT, "main.py")],
            cwd=_PROJECT_ROOT,
        )
        print(f"  Dashboard launched (PID {dashboard_proc.pid})")

    # ── 6. Open the simulator GUI (blocks until closed) ───────────────────
    print("\nOpening simulator GUI …")
    gui = SimulatorGUI(simulators)
    try:
        gui.mainloop()
    except KeyboardInterrupt:
        pass
    finally:
        # ── 7. Cleanup ────────────────────────────────────────────────────
        print("\nShutting down …")
        for sim in simulators.values():
            sim.stop()
        pm.close_all()
        if dashboard_proc and dashboard_proc.poll() is None:
            dashboard_proc.terminate()
        print("Done.")


if __name__ == "__main__":
    main()
