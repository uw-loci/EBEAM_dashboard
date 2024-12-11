import time
import threading
import struct
import queue
from utils import LogLevel
from pymodbus.client import ModbusSerialClient as ModbusClient
from pymodbus.exceptions import ModbusIOException
from typing import Dict

class DP16ProcessMonitor:
    """Driver for Omega iSeries DP16PT Process Monitor - Modbus RTU"""

    PROCESS_VALUE_REG = 0x210   # Register 39 in Table 6.2
    RDGCNF_REG = 0x248          # Register 8 in Table 6.2
    STATUS_REG = 0x240

    def __init__(self, port, unit_numbers=(1,2,3,4,5), baudrate=9600, logger=None):
        """ Initialize Modbus settings """
        self.client = ModbusClient(
            port=port,
            baudrate=baudrate,
            bytesize=8,
            parity='N',
            stopbits=1,
            timeout=1
        )
        self.unit_numbers = set(unit_numbers)
        self.modbus_lock = threading.Lock()
        self.logger = logger
        self.lst_resp = {unit: -1 for unit in unit_numbers}
        self._is_running = True
        self._thread = None
        
        # Establish serial connection
        if self.connect():
            self.log(f"{port} Connected to DP16 Process Monitors", LogLevel.INFO)
        else:
            self.log(f"Failed to connect to DP16 Process Monitors on {port}", LogLevel.WARNING)

         # Set configuration for each unit
        for unit in self.unit_numbers:
            self._set_config(unit)

        # Start single background polling thread
        self._thread = threading.Thread(target=self.poll_all_units, daemon=True)
        self._thread.start()

    def connect(self):
        """
        Checks to see if serial connection is good
        Returns True if good, false otherwise
        """
        with self.modbus_lock:
            try:
                if self.client.is_socket_open():
                    return True
                return self.client.connect()
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
                response2 = self.client.write_register(
                    address=self.STATUS_REG,
                    value=0x0006,
                    slave=unit
                )
                if response2.isError():
                    self.log(f"Failed to write STATUS_REG for unit {unit}: Response:{response2}", LogLevel.ERROR)
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
        """
        Continuously poll all units in a single thread.
        """
        while self._is_running:
            try:
                if not self.client.is_socket_open():
                    if not self.connect():
                        self.log("Failed to reconnect to DP16 Process Monitors", LogLevel.ERROR)
                        time.sleep(0.5)
                        continue

                with self.modbus_lock:
                    for unit in self.unit_numbers:
                        self._poll_single_unit(unit)

                time.sleep(0.1) # small delay between polls
            
            except Exception as e:
                self.log(f"Unexpected DP16 error in poll_all_units: {str(e)}", LogLevel.ERROR)
                time.sleep(0.5)

    def _poll_single_unit(self, unit):
        """
        Poll a single unit for status and temperature.
        """
        try:
            status = self.client.read_holding_registers(
                address=self.STATUS_REG,
                count=1,
                slave=unit
            )

            if not status.isError():
                self.log(f"Status for unit {unit}: {status.registers[0]}", LogLevel.DEBUG)

                if status.registers[0] == 6: # Normal operation
                    response = self.client.read_holding_registers(
                        address=self.PROCESS_VALUE_REG,
                        count=2,
                        slave=unit
                    )

                    if not response.isError():
                        raw_float = struct.pack('>HH', 
                            response.registers[0], 
                            response.registers[1])
                        value = struct.unpack('>f', raw_float)[0]
                        if -90 <= value <= 500:
                            self.log(f"DP16 Unit {unit} temp: {value:.2f}", LogLevel.INFO)
                            self.lst_resp[unit] = value
                        else:
                            self.log(f"DP16 Unit {unit} temp out of range: {value}°C", LogLevel.ERROR)
                            self.lst_resp[unit] = None
                    else:
                        self.log(f"Failed to read PROCESS_VALUE_REG for DP16 unit {unit}: {response}", LogLevel.ERROR)
                        self.lst_resp[unit] = None
                else:
                    self.log(f"DP16 Unit {unit} abnormal status: {status.registers[0]}", LogLevel.ERROR)
                    self.lst_resp[unit] = -1  
            else:
                self.log(f"Missed package on DP16 unit - {unit}", LogLevel.ERROR)   
                self.lst_resp[unit] = -1   

        except ModbusIOException as e:
            self.log(f"Modbus IO error (unit {unit}): {e}", LogLevel.ERROR)
            self.lst_resp[unit] = -1  # Mark unit as unavailable
        except Exception as e:
            self.log(f"Communication error (unit {unit}): {str(e)}", LogLevel.ERROR)

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