# interlocks.py
import tkinter as tk
import os, sys
import instrumentctl.G9SP_interlock.g9_driver as g9_driv
from utils import LogLevel
import time
import queue

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

    def __init__(self, parent, com_ports, logger=None, frames=None, active=None):
        self.parent = parent
        self.logger = logger
        self.frames = frames
        self.active = active
        self.com_port = com_ports
        self.last_error_time = 0  # Track last error time
        self.error_count = 0      # Track consecutive errors
        self.update_interval = 500  # Default update interval (ms)
        self.max_interval = 5000   # Maximum update interval (ms)
        self._last_status = None
        self.setup_gui()

        try:
            if com_ports is not None:
                try:
                    self.driver = g9_driv.G9Driver(com_ports, logger=self.logger)
                    self.log("G9 driver initialized", LogLevel.INFO)
                except Exception as e:
                    self.log(f"Failed to connect: {e}", LogLevel.ERROR)
                    self._set_all_indicators('red')
            else:
                self.driver = None
                self.log("No COM port provided for G9 driver", LogLevel.WARNING)
                self._set_all_indicators('red')
        except Exception as e:
            self.driver = None
            self.log(f"Failed to initialize G9 driver: {str(e)}", LogLevel.WARNING)
            self._set_all_indicators('red')
        
        self.parent.after(self.update_interval, self.update_data)

    def update_com_port(self, com_port):
        """
        Update the COM port and reinitialize the driver
        
        Catch:
            Exception: If inilizition throws an error
        """
        if com_port:
            try:
                if not self.driver:
                    self.driver = g9_driv.G9Driver(com_port, logger=self.logger)
                else:
                    self.driver.setup_serial(port=com_port)
                # Test connection by getting status
                self.driver.get_interlock_status()
                self.log(f"G9 driver updated to port {com_port}", LogLevel.INFO)
            except Exception as e:
                self.log(f"Failed to update G9 driver: {str(e)}", LogLevel.ERROR)
                self._set_all_indicators('red')
        else:
            self.driver.setup_serial(port=None)
            self._set_all_indicators('red')
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
        """
        Create a circular indicator light
        
        Args:
            frame: Parent frame for the indicator
           color: Initial color of the indicator

        Returns:
            tuple: (canvas, oval_id) for the created indicator
        """
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
        """
        Update individual interlock indicator
        
        Args:
            name: interlock to update
            safety: Safety status bit
            data: Data status bit
        """
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

    def _check_terminal_status(self, data, status_dict, terminal_type):
        """
        Generic terminal status checker
        
        Raise:
            ValueError: If an error is found in the Error Cause Data or with invalid inputs
        """
        for i, byte in enumerate(reversed(data[:self.driver.NUMIN])):
            msb = byte >> 4
            lsb = byte & 0x0F

            for nibble, position in [(msb, 'H'), (lsb, 'L')]:
                if nibble in status_dict and nibble != 0:
                    self.log(f"{terminal_type} error at byte {i}{position}: {status_dict[nibble]} (code {nibble})", LogLevel.ERROR)

    def extract_flags(self, byte_string, num_bits):
        """Extracts num_bits from the data
        the bytes are order in big-endian meaning the first 8 are on top 
        but the bits in the bye are ordered in little-endian 7 MSB and 0 LSB
        
        Raise:
            ValueError: When called requesting more bits than in the bytes
        Return:
            num_bits array - MSB is 0 signal LSB if (num_bits - 1)th bit (aka little endian)
        """
        num_bytes = (num_bits + 7) // 8

        if len(byte_string) < num_bytes:
            self.log(f"Input must contain at least {num_bytes} bytes; received {len(byte_string)}", LogLevel.ERROR)

        extracted_bits = []
        for byte_index in range(num_bytes):
            byte = byte_string[byte_index]
            bits_to_extract = min(8, num_bits - (byte_index * 8))
            extracted_bits.extend(((byte >> i) & 1) for i in range(bits_to_extract - 1, -1, -1)[::-1])

        return extracted_bits[:num_bits]
    
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
                try:
                    status = self.driver.get_interlock_status()
                    
                    if status is None:
                        self._set_all_indicators('red')
                        if current_time - self.last_error_time > (self.update_interval / 1000):
                            self.log("No data available from G9", LogLevel.CRITICAL)
                            self.last_error_time = current_time
                            self._adjust_update_interval(success=False)
                            self.parent.after(self.update_interval, self.update_data)
                            return
                        
                    sitsf_bits, sitdf_bits, g9_active, unit_status, input_terms, output_terms = status

                    # parse unit status
                    if unit_status != b'\x01\x00':
                        bits = self.extract_flags(status, 16)
                        for k, v in self.driver.US_STATUS.items():
                            if bits[k] == 1:
                                self.log(f"Unit State Error: {v}", LogLevel.CRITICAL)
                        if bits[0] == 0:
                            self.log("Unit State Error: Normal Operation Error Flag", LogLevel.CRITICAL)

                    # check input terms
                    self._check_terminal_status(
                        input_terms,
                        self.driver.IN_STATUS,
                        "Input")
                    
                    # check output terms
                    self._check_terminal_status(
                        output_terms,
                        self.driver.OUT_STATUS,
                        "Output")

                    # Process dual-input interlocks (first 3 pairs)
                    for i in range(3):
                        safety = (sitsf_bits[i*2] & 
                                sitsf_bits[i*2+1])
                        data = (sitdf_bits[i*2] & 
                            sitdf_bits[i*2+1])
                        
                        self.update_interlock(self.INPUTS[i*2], safety, data)
                    
                    # Process single-input interlocks
                    for i in range(6, 11):
                        safety = sitsf_bits[i]
                        data = sitdf_bits[i]
                        self.update_interlock(self.INPUTS[i], safety, data)

                    # Checks all 11 first interlocks
                    all_good = sitsf_bits[:11] == sitdf_bits[:11] == [1] * 11
                    self.update_interlock("All Interlocks", True, all_good)

                    # Updates progress bar on dashboard if all interlocks pass
                    if self.active:
                        self.active['Interlocks Pass'] = all_good

                    # High Voltage Interlock (unrelated to All interlocks)
                    if sitsf_bits[11] == 1 and sitdf_bits[11] == 0:
                        self.update_interlock(self.INPUTS[11], True, True)
                    else:
                        self.update_interlock(self.INPUTS[11], True, False)

                    # make sure that the data output indicates button and been pressed and the input is not off/error
                    if g9_active == sitsf_bits[12] == 1:
                        self.update_interlock("G9SP Active", True, all_good)
                    else:
                        self.update_interlock("G9SP Active", False, all_good)

                    self._adjust_update_interval(success=True)
                except queue.Empty:
                    self.log("G9 Driver No Data - Queue is empty", LogLevel.CRITICAL)

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

    def close_com_ports(self):
        """
        Closes the serial port connection upon quitting the application.
        """
        if self.driver and hasattr(self.driver, 'ser'):
            if self.driver.ser and self.driver.ser.is_open:
                self.driver.ser.close()
                self.log(f"Closed serial port {self.com_port}", LogLevel.INFO)
            else:
                self.log(f"{self.com_port} is already closed", LogLevel.INFO)       

