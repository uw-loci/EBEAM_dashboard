import tkinter as tk
from tkinter import ttk
from instrumentctl.Beam_Energy.beamEnergy_driver import BeamEnergy
import re

class BeamEnergySubsystem:
    def __init__(self, parent, com_port="", logger=None, poll_ms=100):
        self.logger = logger
        self.poll_ms = poll_ms
        self.frame = parent

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

        self.driver = BeamEnergy(port=com_port, logger=self.logger)
        self.poll()

    def poll(self):
        try:
            line = self.driver.readline() if hasattr(self.driver, "readline") else None
            if line:
                parts = line.split(',')
                vals = {k.upper(): v.strip() for k, v in self.pattern_match.findall(line)}
                if all(k in vals for k in ("SET", "HV", "I")):
                    s, hv, i = vals["SET"], vals["HV"], vals["I"]

                    self.var_set.set(s)
                    self.var_voltage.set(hv)
                    self.var_current.set(i)

                    self.log(f"Set: {vals['SET']}, High Voltage: {vals['HV']}, Current: {vals['I']}")

                    self.logger.update_field('High Voltage', vals['HV'])
                    self.logger.update_field('Current', vals['I'])
                    self.logger.update_field('Set', vals['SET'])
                else:
                    self.log(line)

        except Exception as e:
            if self.logger:
                self.logger.warning(f"[BeamEnergySubsystem] poll error: {e}")
        finally:
            self.frame.after(self.poll_ms, self.poll)

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
