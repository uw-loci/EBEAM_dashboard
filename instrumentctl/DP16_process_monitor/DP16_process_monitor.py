import time
import threading
from threading import Lock
import struct
from utils import LogLevel
from pymodbus.client import ModbusSerialClient as ModbusClient
from pymodbus.exceptions import ModbusIOException
from typing import Dict
import sys

class DP16ProcessMonitor:
    """Driver for Omega iSeries DP16PT Process Monitor - Modbus RTU"""

    PROCESS_VALUE_REG = 0x210   # Page 8: CNPt Series Programming User's Guide Modbus Interface
    RDGCNF_REG = 0x248          # Page 9: CNPt Series Programming User's Guide Modbus Interface
    STATUS_REG = 0x240          # Page 9: CNPt Series Programming User's Guide Modbus Interface

    STATUS_RUNNING = 0x0006

    # PT100 RTD temperature range
    MIN_TEMP = -90      # [C]
    MAX_TEMP = 500      # [C]
    
    # Polling delay
    BASE_DELAY = 0.1    # [seconds]
    MAX_DELAY = 5       # [seconds]

    ERROR_THRESHOLD = 5
    ERROR_LOG_INTERVAL = 30 # [seconds]

    # Error states
    DISCONNECTED = -1
    SENSOR_ERROR = -2

    def __init__(self, port, unit_numbers=(1,2,3,4,5), baudrate=9600, logger=None):
        """ Initialize Modbus settings """
        self.client = ModbusClient(
            port=port,
            baudrate=baudrate,
            bytesize=8,
            parity='N',
            stopbits=1,
            timeout=0.2
        )
        self.unit_numbers = set(unit_numbers)
        self.modbus_lock = Lock()
        self.logger = logger

        self.temperature_readings = {unit: None for unit in unit_numbers}
        self.consecutive_error_counts = {unit: 0 for unit in self.unit_numbers}
        self.last_good_readings = {unit: None for unit in self.unit_numbers}
        self.consecutive_connection_errors = 0

        self._is_running = True
        self._thread = None
        self.response_lock = Lock()
        self.last_critical_error_time = 0
        
        # Start single background polling thread after successful connection and configuration
        self._thread = threading.Thread(target=self.poll_all_units, daemon=True)
        self._thread.start()
    
    def connect(self):
        """
        Establish a connection to the DP16 units.

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
                
                # Check if any unit responds
                working_units = set()
                for unit in self.unit_numbers:
                    status = self.client.read_holding_registers(
                        address=self.STATUS_REG,
                        count=1,
                        slave=unit
                    )
                    if not status.isError():
                        working_units.add(unit)
                        self.log(
                            f"DP16 Unit {unit} responded with status: {status.registers[0]}", 
                            LogLevel.VERBOSE
                        )
                    else:
                        self.log(f"DP16 Unit {unit} not responding", LogLevel.WARNING)
                        # with self.response_lock:
                        #     self.temperature_readings[unit] = self.DISCONNECTED

                if working_units:
                    self.log(
                        f"Connected to {len(working_units)}/{len(self.unit_numbers)} DP16 units", 
                        LogLevel.INFO
                    )
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
                # First write: Set decimal format
                response1 = self.client.write_register(
                    address=self.RDGCNF_REG,
                    value=0x002, # e.g. "FFF.F"
                    slave=unit
                )
                if response1.isError():
                    self.log(f"Failed to write RDGCNF_REG for DP16 unit {unit}. Response:{response1}", LogLevel.ERROR)
                    return False # Exit early if the first write fails
                    
                # Second write: Update STATUS_REG
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
            current_time = time.time()
            try:
                # Check if client is still connected
                if not self.client.is_socket_open():
                    self.consecutive_connection_errors += 1
                    # Mark all disconnected if we exceed error threshold
                    if self.consecutive_connection_errors >= self.ERROR_THRESHOLD:
                        with self.response_lock:
                            for unit in self.unit_numbers:
                                self.temperature_readings[unit] = self.DISCONNECTED
                    
                    # Try to reconnect
                    if not self.connect():
                        if current_time - self.last_critical_error_time >= self.ERROR_LOG_INTERVAL:
                            self.log("Failed to reconnect to PMON", LogLevel.ERROR)
                            self.last_critical_error_time = current_time
                        time.sleep(1)  # Delay before next attempt
                        continue
                
                # Poll each unit individually
                for unit in sorted(self.unit_numbers):
                    try:
                        self._poll_single_unit(unit) 
                        self.consecutive_connection_errors = 0  # Reset on successful poll
                        time.sleep(0.1)
                    except ModbusIOException as e:
                        self._handle_poll_error(unit, e)
                        
                        # Rate limited error logging
                        if current_time - self.last_critical_error_time >= self.ERROR_LOG_INTERVAL:
                            self.log(f"Error polling unit {unit}: {e}", LogLevel.ERROR)
                            self.last_critical_error_time = current_time

                if self.consecutive_connection_errors == 0:
                    time.sleep(self.BASE_DELAY)
                    
            except Exception as e:
                self.consecutive_connection_errors += 1
                current_time = time.time()
                # if current_time - self.last_critical_error_time >= self.ERROR_LOG_INTERVAL:
                #     self.log(f"Polling error: {e}", LogLevel.ERROR)
                #     self.last_critical_error_time = current_time
                if current_time - self.last_critical_error_time >= self.ERROR_LOG_INTERVAL:
                    try:
                        self.log(f"Polling error: {e}", LogLevel.ERROR)
                    except RuntimeError:
                        # can’t write into the Text widget from here – just swallow or
                        # fallback to stderr
                        print(f"[{LogLevel.ERROR.name}] Polling error: {e}", file=sys.__stderr__)
                    finally:
                        self.last_critical_error_time = current_time


    def _poll_single_unit(self, unit):
        """Poll a single unit atomically"""
        if not self._is_running:
            return

        with self.modbus_lock:
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
                self.consecutive_error_counts[unit] += 1
                raise ModbusIOException("Status read failed")

            # Warn if not in expected running state
            if status.registers[0] != self.STATUS_RUNNING:
                self.log(
                    f"DP16 Unit {unit} status {status.registers[0]} differs from expected {self.STATUS_RUNNING}", 
                    LogLevel.WARNING
                )

            # Read temperature
            response = self.client.read_holding_registers(
                address=self.PROCESS_VALUE_REG,
                count=2,
                slave=unit
            )
            if response.isError():
                raise ModbusIOException("Temperature read failed")

            # Process response
            raw_float = struct.pack('>HH', response.registers[0], response.registers[1])
            value = struct.unpack('>f', raw_float)[0]

            # In-line validation
            if abs(value) < 0.001:
                raise ValueError("Zero reading indicates communication error")
            if not (self.MIN_TEMP <= value <= self.MAX_TEMP):
                raise ValueError(f"Temperature out of range: {value}")

            # All good, reset the consecutive error count
            self.consecutive_error_counts[unit] = 0
            
            # Update reading for GUI availability
            with self.response_lock:
                self.temperature_readings[unit] = value
                self.last_good_readings[unit] = value
    
    def _handle_poll_error(self, unit: int, exception: Exception):
            """
            Increments consecutive error counts, logs the error, and updates 
            self.temperature_readings based on the single ERROR_THRESHOLD logic.
            """
            self.log(f"Poll error on unit {unit}: {exception}", LogLevel.VERBOSE)
            self.consecutive_error_counts[unit] += 1

            err_str = str(exception).lower()
            is_modbus_error = isinstance(exception, ModbusIOException)

            # Classify the error for logging or bus-level increments
            if is_modbus_error:
                if ("port is closed" in err_str or
                    "could not open port" in err_str):
                    self.log(f"Hard port failure on unit {unit}: {exception}", LogLevel.ERROR)
                    self.client.close()
                    self.consecutive_connection_errors += 1
                elif ("failed to connect" in err_str or
                    "connection" in err_str):
                    self.log(f"Connection error on unit {unit}: {exception}", LogLevel.WARNING)
                    self.consecutive_connection_errors += 1
                elif "status read failed" in err_str:
                    self.log(f"Partial/incomplete status response on unit {unit}", LogLevel.DEBUG)
                elif "temperature read failed" in err_str:
                    self.log(f"Partial/incomplete temperature response on unit {unit}", LogLevel.DEBUG)
                else:
                    self.log(f"General Modbus IO error on unit {unit}: {exception}", LogLevel.ERROR)
            else:
                self.log(f"Invalid reading on unit {unit}: {exception}", LogLevel.WARNING)

            with self.response_lock:
                if self.consecutive_error_counts[unit] >= self.ERROR_THRESHOLD:
                    # Enough consecutive errors to declare full disconnection
                    self.temperature_readings[unit] = self.DISCONNECTED
                else:
                    # 1-5 consecutive failures => show last known good reading if exists
                    # Mark as SENSOR_ERROR if we never had a good reading
                    if self.last_good_readings[unit] is not None:
                        self.temperature_readings[unit] = self.last_good_readings[unit]
                    else:
                        self.temperature_readings[unit] = self.SENSOR_ERROR

    def get_all_temperatures(self):
        """ Thread-safe access method """
        with self.response_lock:
            return dict(self.temperature_readings)

    def disconnect(self):
        # Stop polling thread
        # self._is_running = False
        # if self._thread and self._thread.is_alive():
        #     self._thread.join()
        
        # Close connection
        # with self.modbus_lock:
        if self.client.is_socket_open():
            self.client.close()
            self.log("Disconnected from DP16 Process Monitors", LogLevel.INFO)
        else:
            self.log("No active connection to DP16 Process Monitors", LogLevel.INFO)

    def log(self, message, level=LogLevel.INFO):
        """Log a message with the specified level if a logger is configured."""
        if self.logger:
            self.logger.log(message, level)
        else:
            print(f"{level.name}: {message}")