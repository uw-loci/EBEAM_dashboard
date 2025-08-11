import tkinter as tk
from tkinter import ttk
from instrumentctl.Beam_Energy.beamEnergy_driver import BeamEnergyDriver
import re
from utils import LogLevel

class BeamEnergy:
    def __init__(self, parent, com_port="", logger=None, poll_ms=500):
        self.logger = logger
        self.poll_ms = poll_ms
        self.frame = parent
        self.com_port = com_port or ""

        self.var_set     = tk.StringVar(value="--")
        self.var_current= tk.StringVar(value="--")
        self.var_voltage = tk.StringVar(value="--")

        self.pattern_match = re.compile(r'\b(Set|HV|I)\s*:\s*([^,]+)')

        grid = ttk.Frame(self.frame)
        grid.pack(fill="both", expand=True, padx=8, pady=6)

        def row(r, label, var):
            ttk.Label(grid, text=label).grid(row=r, column=0, sticky="w")
            ttk.Label(grid, textvariable=var, font=("Helvetica", 12, "bold")).grid(row=r, column=1, sticky="e")

        row(0, "Set:",          self.var_set)
        row(1, "Beam Current:", self.var_current)
        row(2, "Beam High Voltage:", self.var_voltage)

        self.driver = BeamEnergyDriver(port=self.com_port, logger=self.logger)
        self.poll()

    def poll(self):
        try:
            self.frame.after(self.poll_ms, self.poll)

            line = self.driver.readline() if hasattr(self.driver, "readline") else None
            if not line:
                return

            vals = {k.upper(): v.strip() for k, v in self.pattern_match.findall(line)}

            if "SET" in vals: self.var_set.set(vals["SET"])
            if "HV"  in vals: self.var_voltage.set(vals["HV"])
            if "I"   in vals: self.var_current.set(vals["I"])

            if self.logger and hasattr(self.logger, "update_field"):
                self.logger.update_field("Set",          vals.get("SET", "--"))
                self.logger.update_field("High Voltage", vals.get("HV",  "--"))
                self.logger.update_field("Current",      vals.get("I",   "--"))

            self.log(f"Set: {vals.get('SET','--')}, HV: {vals.get('HV','--')}, I: {vals.get('I','--')}",
                    level=LogLevel.DEBUG)
        except Exception as exc:
            self.log(f"Unexpected error in poll: {exc}", level=LogLevel.ERROR)

    def update_com_port(self, com_port):
        if hasattr(self.driver, "update_port"):
            self.driver.update_port(com_port)

    def close_com_ports(self):
        if hasattr(self.driver, "ser") and self.driver.ser:
            try: self.driver.ser.close()
            except: pass
            self.driver.ser = None

    def log(self, message, level=LogLevel.INFO):
        if self.logger:
            self.logger.log(message, level)
        else:
            print(f"{level.name}: {message}")
