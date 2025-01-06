import time
import threading
from threading import Lock
import struct
from utils import LogLevel
from pymodbus.client import ModbusSerialClient as ModbusClient
from pymodbus.exceptions import ModbusIOException
from typing import Dict

class DP16ProcessMonitor:
    """Driver for Omega iSeries DP16PT Process Monitor - Modbus RTU"""

    PROCESS_VALUE_REG = 0x210   # Register 39 in Table 6.2
    RDGCNF_REG = 0x248          # Register 8 in Table 6.2
    STATUS_REG = 0x240

    # PT100 RTD temperature range
    MIN_TEMP = -90      # [C]
    MAX_TEMP = 500      # [C]
    
    # Polling delay
    BASE_DELAY = 0.1    # [seconds]
    MAX_DELAY = 5       # [seconds]

    # Status Codes
    STATUS_RUNNING = 0x0006

    # Error states
    DISCONNECTED = -1
    SENSOR_ERROR = -2
    MAX_ERROR_THRESHOLD = 3

    def __init__(self, port, unit_numbers=(1,2,3,4,5), baudrate=9600, logger=None):
        """ Initialize Modbus settings """
        self.client = ModbusClient(
            port=port,
            baudrate=baudrate,
            bytesize=8,
            parity='N',
            stopbits=1,
            timeout=0.5
        )
        self.unit_numbers = set(unit_numbers)
        self.modbus_lock = Lock()
        self.logger = logger
        self.temperature_readings = {unit: None for unit in unit_numbers}
        self.error_counts = {unit: 0 for unit in self.unit_numbers}
        self.last_good_readings = {unit: None for unit in self.unit_numbers}
        self._is_running = True
        self._thread = None
        self.response_lock = Lock()
        
        try:
            # First establish connection
            if not self.connect():
                raise RuntimeError(f"Failed to connect to any DP16 Process Monitors on {port}")
            
            # Set configuration for each unit
            configured_units = set()
            for unit in self.unit_numbers:
                if self._set_config(unit):
                    configured_units.add(unit)
                else:
                    self.log(f"Failed to configure unit {unit}", LogLevel.WARNING)
                    with self.response_lock:
                        self.temperature_readings[unit] = self.SENSOR_ERROR

            if not configured_units:
                raise RuntimeError(f"Failed to configure any DP16 units")
            
            # Start single background polling thread after successful connection and configuration
            self._thread = threading.Thread(target=self.poll_all_units, daemon=True)
            self._thread.start()
        
        except Exception as e:
            self._is_running = False # Ensure the thread won't start
            self.disconnect() # clean up resources
            self.log(f"Failed to connect to DP16 Process Monitors on {port}", LogLevel.WARNING)
            raise RuntimeError(f"Failed to connect to PMON: {str(e)}")

    def connect(self):
        """
        Establish a connection to the DP16 units.

        Tries to open communication with the units using the configured 
        baud rate and serial port. Logs any connection issues.

        Returns:
            bool: True if the connection is successful, False otherwise.
        """
        with self.modbus_lock:
            try:
                if self.client.is_socket_open():
                    self.log("Reusing existing PMON Modbus connection", LogLevel.DEBUG)
                    return True
                
                self.log(f"Attempting to connect on port {self.client}", LogLevel.DEBUG)
                if not self.client.connect():
                    return False
                
                # Track working units
                working_units = set()
                for unit in self.unit_numbers:
                    status = self.client.read_holding_registers(
                        address=self.STATUS_REG,
                        count=1,
                        slave=unit
                    )
                    if not status.isError():
                        working_units.add(unit)
                        self.log(f"DP16 Unit {unit} responded with status: {status.registers[0]}", LogLevel.VERBOSE)
                    else:
                        self.log(f"DP16 Unit {unit} not responding", LogLevel.WARNING)
                        with self.response_lock:
                            self.temperature_readings[unit] = self.DISCONNECTED

                # Return True if at least one unit is working
                if working_units:
                    self.log(f"Connected to {len(working_units)}/{len(self.unit_numbers)} DP16 units", LogLevel.INFO)
                    return True
                return False
            except ModbusIOException as e:
                self.log(f"Modbus IO error during DP16 connection: {e}", LogLevel.ERROR)
                return False
            except Exception as e:
                self.log(f"DP16 Error connecting: {str(e)}", LogLevel.ERROR)
                return False

    def get_reading_config(self, unit):
        """Get reading configuration format
        Returns:
            int: 2 for FFF.F format, 3 for FFFF format, None on error
        """
        try:
            with self.modbus_lock:
                response = self.client.read_holding_registers(
                    address=self.RDGCNF_REG,
                    count=1,
                    slave=unit
                )
                time.sleep(0.1)
                if not response.isError():
                    return response.registers[0]
                return None
        except ModbusIOException as e:
            self.log(f"Modbus IO error reading config for DP16 unit {unit}: {e}", LogLevel.WARNING)
        except Exception as e:
            self.log(f"Error reading config: {e}", LogLevel.ERROR)
            return None

    def _set_config(self, unit):
        """
        Sets the reading configuration format along with the run state
        2 - FFF.F
        3 - FFFF

        6 - Running 
        10 - Operating
        Returns:
            if setting is successful or not
        """
        if unit not in self.unit_numbers:
            self.log(f"DP16 set_decimal_config was called with an invalid unit address", LogLevel.ERROR)
            return False # exit for invalid unit
        
        try:
            with self.modbus_lock:
                self.log(f"Setting RDGCNF_REG for unit {unit}", LogLevel.DEBUG)
                # First write: Set the reading configuration format
                response1 = self.client.write_register(
                    address=self.RDGCNF_REG,
                    value=0x002,
                    slave=unit
                )
                if response1.isError():
                    self.log(f"Failed to write RDGCNF_REG for DP16 unit {unit}. Response:{response1}", LogLevel.ERROR)
                    return False # Exit early if the first write fails
                    
                # Second write: Update the status register
                self.log(f"Setting STATUS_REG for unit {unit}", LogLevel.DEBUG)
                response2 = self.client.write_register(
                    address=self.STATUS_REG,
                    value=self.STATUS_RUNNING,
                    slave=unit
                )
                time.sleep(0.1)
                if response2.isError():
                    self.log(f"Failed to write STATUS_REG for DP16 unit {unit}: Response:{response2}", LogLevel.ERROR)
                    return False # Exit if second write fails
                
                self.log(f"Configuration successful for DP16 unit {unit}", LogLevel.INFO)
                return True
        except ModbusIOException as e:
            self.log(f"Modbus IO error while setting config for unit {unit}: {e}", LogLevel.ERROR)
            return False
        except Exception as e:
            self.log(f"Error writing RDGCNF_REG config: {e}", LogLevel.ERROR)
            return False
        
    def poll_all_units(self):
        """Single polling loop with each unit independent"""
        while self._is_running:
            for unit in sorted(self.unit_numbers):
                try:
                    self._poll_single_unit(unit)
                    time.sleep(0.1)  # Inter-unit polling delay
                except Exception as e:
                    self.log(f"Critical error polling unit {unit}: {e}", LogLevel.ERROR)

            time.sleep(self.BASE_DELAY)

    def _poll_single_unit(self, unit):
        """Poll a single unit atomically"""
        if not self._is_running:
            return

        with self.modbus_lock:
            try:
                # Clear any stale data
                if hasattr(self.client, 'serial'):
                    self.client.serial.reset_input_buffer()

                # Read status first
                status = self.client.read_holding_registers(
                    address=self.STATUS_REG,
                    count=1,
                    slave=unit
                )

                if status.isError():
                    # self.error_counts[unit] += 1
                    raise ModbusIOException("Status read failed")

                # Quick validation of status
                if status.registers[0] != self.STATUS_RUNNING:
                    # self.error_counts[unit] += 1
                    raise ModbusIOException("Unit not in running state")

                # Read temperature
                response = self.client.read_holding_registers(
                    address=self.PROCESS_VALUE_REG,
                    count=2,
                    slave=unit
                )

                if response.isError():
                    # self.error_counts[unit] += 1
                    raise ModbusIOException("Temperature read failed")

                # Process response
                raw_float = struct.pack('>HH', response.registers[0], response.registers[1])
                value = struct.unpack('>f', raw_float)[0]

                if abs(value) < 0.001:
                    raise ValueError("Zero reading indicates communication error")

                if not (self.MIN_TEMP <= value <= self.MAX_TEMP):
                    raise ValueError(f"Temperature out of range: {value}")

                # Success! Clear error count and update reading
                self.error_counts[unit] = 0
                with self.response_lock:
                    self.temperature_readings[unit] = value
                    self.last_good_readings[unit] = value

            except (ModbusIOException, ValueError) as e:
                self.log(f"Error polling unit {unit}: {e}", LogLevel.ERROR)
                if isinstance(e, ModbusIOException):
                    with self.response_lock:
                        self.temperature_readings[unit] = self.DISCONNECTED
                
                if self.error_counts[unit] >= self.MAX_ERROR_THRESHOLD:
                    with self.response_lock:
                        self.temperature_readings[unit] = self.DISCONNECTED
                elif self.last_good_readings[unit] is not None:
                    with self.response_lock:
                        self.temperature_readings[unit] = self.last_good_readings[unit]

    def get_all_temperatures(self):
        """ Thread-safe access method """
        with self.response_lock:
            return dict(self.temperature_readings) # create new response dict while holding lock

    def disconnect(self):
        # Stop polling thread
        self._is_running = False
        if self._thread and self._thread.is_alive():
            self._thread.join()
        
        # Close connection
        with self.modbus_lock:
            if self.client.is_socket_open():
                self.client.close()
                self.log("Disconnected from DP16 Process Monitors", LogLevel.INFO)

    def log(self, message, level=LogLevel.INFO):
        """Log a message with the specified level if a logger is configured."""
        if self.logger:
            self.logger.log(message, level)
        else:
            print(f"{level.name}: {message}")