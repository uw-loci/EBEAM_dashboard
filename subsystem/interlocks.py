# interlocks.py
import tkinter as tk
import os, sys
import instrumentctl.g9_driver as g9_driv
from utils import LogLevel
import time
import instrumentctl.g9_driver as g9_driv
from utils import LogLevel
import time

class InterlocksSubsystem:
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

    INDICATORS = {
        'Door': None,
        'Water': None,
        'Vacuum Power': None,
        'Vacuum Pressure': None,
        'Low Oil': None,
        'High Oil': None,
        'E-STOP Int': None,
        'E-STOP Ext': None,
        'All Interlocks': None,
        'G9SP Active': None,
        'HVolt ON': None
    }

    def __init__(self, parent, com_ports, logger=None, frames=None):
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

    INDICATORS = {
        'Door': None,
        'Water': None,
        'Vacuum Power': None,
        'Vacuum Pressure': None,
        'Low Oil': None,
        'High Oil': None,
        'E-STOP Int': None,
        'E-STOP Ext': None,
        'All Interlocks': None,
        'G9SP Active': None,
        'HVolt ON': None
    }

    def __init__(self, parent, com_ports, logger=None, frames=None):
        self.parent = parent
        self.logger = logger
        self.frames = frames
        self.last_error_time = 0  # Track last error time
        self.error_count = 0      # Track consecutive errors
        self.update_interval = 500  # Default update interval (ms)
        self.max_interval = 5000   # Maximum update interval (ms)
        self._last_status = None
        self.frames = frames
        self.last_error_time = 0  # Track last error time
        self.error_count = 0      # Track consecutive errors
        self.update_interval = 500  # Default update interval (ms)
        self.max_interval = 5000   # Maximum update interval (ms)
        self._last_status = None
        self.setup_gui()

        try:
            if com_ports is not None:  # Better comparison
                try:
                    self.driver = g9_driv.G9Driver(com_ports, logger=self.logger)
                    self.log("G9 driver initialized", LogLevel.INFO)
                except Exception as e:
                    self.log(f"Failed to connect: {e}", LogLevel.ERROR)
                    self._set_all_indicators('red')
            else:
                self.driver._running = False
                self.log("No COM port provided for G9 driver", LogLevel.WARNING)
                self._set_all_indicators('red')
        except Exception as e:
            self.log(f"Failed to initialize G9 driver: {str(e)}", LogLevel.WARNING)
            self._set_all_indicators('red')
        
        self.parent.after(self.update_interval, self.update_data)

    def update_com_port(self, com_port):
        """
        Update the COM port and reinitialize the driver
        
        Catch:
            Expection: If inilizition throws an error
        """

        if com_port:
            try:
                if self.driver:
                    self.driver.setup_serial(com_port, 9600, 0.5)
                else:
                    self.driver = g9_driv.G9Driver(com_port, logger=self.logger)
                # Test connection by getting status
                self.driver.get_interlock_status()
                self.parent.after(self.update_interval, self.update_data)
                self.log(f"G9 driver updated to port {com_port}", LogLevel.INFO)
            except Exception as e:
                self._set_all_indicators('red')
                self.log(f"Failed to update G9 driver: {str(e)}", LogLevel.ERROR)
        else:
            self._set_all_indicators('red')
            self.driver.setup_serial(None, 9600, 0.5)
            self.log("update_com_port is being called without a com port", LogLevel.ERROR)

    def _adjust_update_interval(self, success=True):
        """Adjust the polling interval based on connection success/failure"""
        if success:
            # On success, return to normal update rate
            self.error_count = 0
            self.update_interval = 500  # Reset to default interval
        else:
            # On communication failure, use exponential backoff with a cap
            self.error_count = min(self.error_count + 1, 5)  # Cap error count
            self.update_interval = min(500 * (2 ** self.error_count), self.max_interval)

    def setup_gui(self):
        """Setup the GUI for the interlocks subsystem"""
        self._create_main_frame()
        interlocks_frame = self._create_interlocks_frame()
        self._create_indicators(interlocks_frame)

    def _create_main_frame(self):
        """Create and configure the main container frame"""
        """Setup the GUI for the interlocks subsystem"""
        self._create_main_frame()
        interlocks_frame = self._create_interlocks_frame()
        self._create_indicators(interlocks_frame)

    def _create_main_frame(self):
        """Create and configure the main container frame"""
        self.interlocks_frame = tk.Frame(self.parent)
        self.interlocks_frame.pack(fill=tk.BOTH, expand=True)
        
        # Configure grid weights for responsive layout
        self.parent.grid_rowconfigure(0, weight=1)
        self.parent.grid_columnconfigure(0, weight=1)
        self.interlocks_frame.grid_rowconfigure(0, weight=1)
        self.interlocks_frame.grid_columnconfigure(0, weight=1)
        self.interlocks_frame.grid(row=0, column=0, sticky='nsew')

    def _create_interlocks_frame(self):
        """Create the frame that will contain the interlock indicators"""
        interlocks_frame = tk.Frame(self.interlocks_frame, highlightbackground="black")
        interlocks_frame.grid(row=0, column=0, padx=0, pady=0, sticky="nsew")
        
        # Configure columns for indicator pairs (label + light)
        num_columns = 22
        for i in range(num_columns):
            interlocks_frame.grid_columnconfigure(i, weight=1)
        
        return interlocks_frame

    def _create_indicator_circle(self, frame, color):
        """Create a circular indicator light"""
        canvas = tk.Canvas(frame, width=30, height=30, highlightthickness=0)
        canvas.grid(sticky='nsew')
        oval_id = canvas.create_oval(5, 5, 25, 25, fill=color, outline="black")
        return canvas, oval_id

    def _create_indicators(self, frame):
        """Create all indicator lights and their labels"""
        for i, (name, _) in enumerate(self.INDICATORS.items()):
            # Create label
            tk.Label(frame, text=name, anchor="center").grid(
                row=0, column=i*2, sticky='ew'
            )
            
            # Create indicator light
            canvas, oval_id = self._create_indicator_circle(frame, 'red')
            canvas.grid(row=0, column=i*2+1, sticky='nsew')
            self.INDICATORS[name] = (canvas, oval_id)

    # updates indicator and logs updates
    def update_interlock(self, name, safety, data):
        """Update individual interlock indicator"""
        if name not in self.INDICATORS or safety == None or data == None:
            self.log("Invalid inputs to update_interlock", LogLevel.ERROR)

        color = 'green' if (safety & data) == 1 else 'red'

        if name in self.INDICATORS:
            canvas, oval_id = self.INDICATORS[name]
            current_color = canvas.itemcget(oval_id, 'fill')
            if current_color != color:
                canvas.itemconfig(oval_id, fill=color)
                self.log(f"Interlock {name}: {current_color} -> {color}", LogLevel.INFO)

    def _set_all_indicators(self, color):
        """Set all indicators to specified color"""
        if color == None or color == "":
            self.log("Invalid inputs to _set_all_indicators", LogLevel.ERROR)

        if self.INDICATORS:
            for name in self.INDICATORS:
                canvas, oval_id = self.INDICATORS[name]
                current_color = canvas.itemcget(oval_id, 'fill')
                if current_color != color:
                    canvas.itemconfig(oval_id, fill=color)
                    self.log(f"Interlock {name}: {current_color} -> {color}", LogLevel.INFO)

    def update_data(self):
        """
        Update interlock status

        Finally: Will always schedule the next time to refresh data

        Catch:
            ConnectionError: Thrown from G9Driver when serial connection throws error
            ValueError: Thrown from G9Driver when unexpected responce is recieved

            Exception: If anything else in message process throws an error

        """
        current_time = time.time()
        try:
            if not self.driver or not self.driver.is_connected():
                if current_time - self.last_error_time > (self.update_interval / 1000):
                    self._set_all_indicators('red')
                    self.log("G9 driver not connected", LogLevel.WARNING)
                    self.last_error_time = current_time
                    self.last_error_time = time.time()
                    self._adjust_update_interval(success=False)
            else:
                # Get interlock status from driver
                status = self.driver.get_interlock_status()
                
                if status is None:
                    self._set_all_indicators('red')
                    if current_time - self.last_error_time > (self.update_interval / 1000):
                        self.log("No data available from G9", LogLevel.CRITICAL)
                        self.last_error_time = current_time
                        self._adjust_update_interval(success=False)
                        self.parent.after(self.update_interval, self.update_data)
                        return
                    
                sitsf_bits, sitdf_bits, g9_active = status
                
                # Process dual-input interlocks (first 3 pairs)
                for i in range(3):
                    safety = (sitsf_bits[i*2] & 
                            sitsf_bits[i*2+1])
                    data = (sitdf_bits[i*2] & 
                        sitdf_bits[i*2+1])
                    
                    self.update_interlock(self.INPUTS[i*2], safety, data)
                
                # Process single-input interlocks
                for i in range(6, 12):
                    safety = sitsf_bits[i]
                    data = sitdf_bits[i]
                    self.update_interlock(self.INPUTS[i], safety, data)
                    
                # Update overall status
                all_good = sitsf_bits[:12] == sitdf_bits[:12] == [1] * 12
                self.update_interlock("All Interlocks", True, all_good)

                # make sure that the data output indicates button and been pressed and the input is not off/error
                if g9_active == sitsf_bits[12] == 1:
                    self.update_interlock("G9SP Active", True, all_good)
                else:
                    self.update_interlock("G9SP Active", False, all_good)

                self._adjust_update_interval(success=True)

        except Exception as e:
            if time.time() - self.last_error_time > (self.update_interval / 1000):
                self.log(f"Unexpected error: {str(e)}", LogLevel.ERROR)
                self._set_all_indicators('red')
                self.last_error_time = time.time()
                self._adjust_update_interval(success=False)
            
        finally:
            # Schedule next update
            if self.driver:
                self.parent.after(self.update_interval, self.update_data)

    def log(self, message, level=LogLevel.INFO):
        """Log a message with the specified level if a logger is configured."""
        if self.logger:
            self.logger.log(message, level)
        else:
            print(f"{level.name}: {message}")

