# interlocks.py
import tkinter as tk
import os, sys
import instrumentctl.g9_driver as g9_driv
from utils import LogLevel
import time

# the bit poistion for each interlock
INPUTS = {
    0 : "E-STOP Int", # Chassis Estop
    1 : "E-STOP Int", # Chassis Estop
    2 : "E-STOP Ext", # Peripheral Estop
    3 : "E-STOP Ext", # Peripheral Estop
    4 : "Door", # Door 
    5 : "Door", # Door Lock
    6 : "Vacuum Power", # Vacuum Power
    7 : "Vacuum Pressure", # Vacuum Pressure
    8 : "High Oil", # Oil High
    9 : "Low Oil", # Oil Low
    10 : "Water", # Water
    11 : "HVolt ON", # HVolt ON
    12 : "G9SP Active" # G9SP Active
    }

class InterlocksSubsystem:
    def __init__(self, parent, com_ports, logger=None, frames=None):
        self.parent = parent
        self.logger = logger
        self.frames = frames
        self.indicators = None
        self.last_error_time = 0  # Track last error time
        self.error_count = 0      # Track consecutive errors
        self.update_interval = 500  # Default update interval (ms)
        self.max_interval = 5000   # Maximum update interval (ms)
        self.setup_gui()

        try:
            if com_ports is not None:  # Better comparison
                self.driver = g9_driv.G9Driver(com_ports, logger=self.logger)
                if self.logger:
                    self.logger.info("G9 driver initialized")
            else:
                self.driver = None
                if self.logger:
                    self.logger.warning("No COM port provided for G9 driver")
                self._set_all_indicators('red')
        except Exception as e:
            self.driver = None
            if self.logger:
                self.logger.error(f"Failed to initialize G9 driver: {str(e)}")
            self._set_all_indicators('red')
        
        self.parent.after(self.update_interval, self.update_data)

    def update_com_port(self, com_port):
        """Update the COM port and reinitialize the driver"""
        if com_port:
            try:
                new_driver = g9_driv.G9Driver(com_port, logger=self.logger)
                # Test connection by getting status
                new_driver.get_interlock_status()
                self.driver = new_driver
                if self.logger:
                    self.logger.info(f"G9 driver updated to port {com_port}")
            except Exception as e:
                if self.logger:
                    self.logger.error(f"Failed to update G9 driver: {str(e)}")
                self._set_all_indicators('red')

    def _adjust_update_interval(self, success=True):
        """Adjust the polling interval based on connection success/failure"""
        if success:
            # On success, return to normal update rate
            self.error_count = 0
            self.update_interval = max(500, self.update_interval // 2)
        else:
            # On communication failure, increase interval up to max_interval
            self.error_count += 1

            new_interval = self.update_interval * (1.5 if self.error_count < 5 else 1)
            self.update_interval = min(self.max_interval, int(new_interval))

            if self.logger and self.error_count % 5 == 0:  # Log every 5th error
                self.logger.warning(
                    f"G9 Connection issue. Update interval: {self.update_interval}ms"
                )

    def setup_gui(self):
        def create_indicator_circle(frame, color):
            canvas = tk.Canvas(frame, width=30, height=30, highlightthickness=0)
            canvas.grid(sticky='nsew')
            oval_id = canvas.create_oval(5, 5, 25, 25, fill=color, outline="black")
            return canvas, oval_id

        self.interlocks_frame = tk.Frame(self.parent)
        self.interlocks_frame.pack(fill=tk.BOTH, expand=True)

        self.parent.grid_rowconfigure(0, weight=1)
        self.parent.grid_columnconfigure(0, weight=1)

        self.interlocks_frame.grid_rowconfigure(0, weight=1)
        self.interlocks_frame.grid_columnconfigure(0, weight=1)
        self.interlocks_frame.grid(row=0, column=0, sticky='nsew')

        interlocks_frame = tk.Frame(self.interlocks_frame, highlightbackground="black")
        interlocks_frame.grid(row=0, column=0, padx=0, pady=0, sticky="nsew")

        num_columns = 22  
        for i in range(num_columns):
            interlocks_frame.grid_columnconfigure(i, weight=1)

        self.indicators = {
            'Door': None, 'Water': None, 'Vacuum Power': None, 
            'Vacuum Pressure': None, 'Low Oil': None, 'High Oil': None, 
            'E-STOP Int': None, 'E-STOP Ext' : None, 'All Interlocks': None, 
            'G9SP Active': None, 'HVolt ON': None
                      }
        
        # Makes all the inticators and labels
        for i, (k,v) in enumerate(self.indicators.items()):
            tk.Label(interlocks_frame, text=f"{k}", anchor="center").grid(row=0, column=i*2, sticky='ew')
            canvas, oval_id = create_indicator_circle(interlocks_frame, 'red')
            canvas.grid(row=0, column=i*2+1, sticky='nsew')
            self.indicators[k] = (canvas, oval_id)

    # logging the history of updates
    def update_interlock(self, name, safety, data):
        """Update individual interlock indicator"""
        # means good
        color = 'green' if (safety & data) == 1 else 'red'

        if name in self.indicators:
            canvas, oval_id = self.indicators[name]
            current_color = canvas.itemcget(oval_id, 'fill')
            if current_color != color:
                canvas.itemconfig(oval_id, fill=color)
                if self.logger:
                    self.logger.info(f"Interlock {name}: {current_color} -> {color}")

    def _set_all_indicators(self, color):
        """Set all indicators to specified color"""
        if self.indicators:
            for name in self.indicators:
                canvas, oval_id = self.indicators[name]
                current_color = canvas.itemcget(oval_id, 'fill')
                if current_color != color:
                    canvas.itemconfig(oval_id, fill=color)
                    if self.logger:
                        self.logger.info(f"Interlock {name}: {current_color} -> {color}")

    def update_data(self):
        """Update interlock status"""
        current_time = time.time()
        try:
            if not self.driver or not self.driver.is_connected():
                if current_time - self.last_error_time > (self.update_interval / 1000):
                    self._set_all_indicators('red')
                    if self.logger:
                        self.logger.warning("G9 driver not connected")
                    self.last_error_time = current_time
                    self._adjust_update_interval(success=False)

                self.parent.after(500, self.update_data)
                return

            # Get interlock status from driver
            sitsf_bits, sitdf_bits = self.driver.get_interlock_status()
            
            # Process dual-input interlocks (first 3 pairs)
            for i in range(3):
                safety = (int(sitsf_bits[-i*2-1], 2) & 
                         int(sitsf_bits[-i*2-2], 2))
                data = (int(sitdf_bits[-i*2-1], 2) & 
                       int(sitdf_bits[-i*2-2], 2))
                self.update_interlock(INPUTS[i*2], safety, data)
            
            # Process single-input interlocks
            for i in range(6, 13):
                safety = int(sitsf_bits[-i-1], 2)
                data = int(sitdf_bits[-i-1], 2)
                self.update_interlock(INPUTS[i], safety, data)
            
            # Update overall status
            all_good = sitsf_bits == sitdf_bits == "1" * 13
            self.update_interlock("All Interlocks", True, all_good)

        except (ConnectionError, ValueError) as e:
            if current_time - self.last_error_time > (self.update_interval / 1000):
                if self.logger:
                    self.logger.error(f"G9 communication error: {str(e)}")
                self._set_all_indicators('red')
                self.last_error_time = current_time
                self._adjust_update_interval(success=False)
            
        except Exception as e:
            if current_time - self.last_error_time > (self.update_interval / 1000):
                if self.logger:
                    self.logger.error(f"Unexpected error: {str(e)}")
                self._set_all_indicators('red')
                self.last_error_time = current_time
                self._adjust_update_interval(success=False)
            
        finally:
            # Schedule next update
            self.parent.after(self.update_interval, self.update_data)
