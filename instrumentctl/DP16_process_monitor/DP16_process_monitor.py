import time
import threading
import struct
import queue
from pymodbus.client import ModbusSerialClient as ModbusClient
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
        if self.connect() and self.logger:
            self.logger.debug(f"{port} Connected to DP16 Process Monitor")
        else:
            if self.logger:
                self.logger.warning("Failed to connect to DP16 Process Monitor")

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
            except Exception as e:
                if self.logger:
                    self.logger.error(f"Error connecting: {str(e)}")
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
        except Exception as e:
            if self.logger:
                self.logger.error(f"Error reading config: {e}")
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
            if self.logger:
                self.logger.debug(f"set_decimal_config was called with an invalid unit address")
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
                    if self.logger:
                        self.logger.error(f"Failed to write RDGCNF_REG for unit {unit}. Response:{response1}")
                    return False # Exit early if the first write fails
                    
                # Second write: Update the status register
                response2 = self.client.write_register(
                    address=self.STATUS_REG,
                    value=0x0006,
                    slave=unit
                )
                if response2.isError():
                    if self.logger:
                        self.logger.error(f"Failed to write STATUS_REG for unit {unit}: Response:{response2}")
                    return False # Exit if second write fails
                
                self.logger.info(f"Configuration successful for DP16 unit {unit}")
                return True
            
        except Exception as e:
            if self.logger:
                self.logger.error(f"Error writing config: {e}")
            return False
        
    def poll_all_units(self):
        """
        Continuously poll all units in a single thread.
        """
        while self._is_running:
            if not self.client.is_socket_open():
                if not self.connect():
                    if self.logger:
                        self.logger.error("Failed to reconnect to DP16 Process Monitors")
                    time.sleep(0.5)
                    continue

            with self.modbus_lock:
                for unit in self.unit_numbers:
                    self._poll_single_unit(unit)

            time.sleep(0.1) # TODO: Test this interval

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
                if self.logger:
                    self.logger.debug(f"Status for unit {unit}: {status.registers[0]}")

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
                            if self.logger:
                                self.logger.info(f"DP16 Unit {unit} temp: {value:.2f}")
                            self.lst_resp[unit] = value
                        else:
                            if self.logger:
                                self.logger.error(f"DP16 Unit {unit} temp out of range: {value}°C")
                            self.lst_resp[unit] = None
                    else:
                        if self.logger:
                            self.logger.error(f"Failed to read PROCESS_VALUE_REG for unit {unit}: {response}")
                        self.lst_resp[unit] = None
                else:
                    if self.logger:
                        self.logger.error(f"DP16 Unit {unit} abnormal status: {status.registers[0]}")
                    self.lst_resp[unit] = -1  
            else:
                if self.logger:
                    self.logger.error(f"Missed package on unit - {unit}")   
                self.lst_resp[unit] = -1   

        except Exception as e:
            if self.logger:
                self.logger.error(f"Communication error (unit {unit}): {str(e)}")

def disconnect(self):
    # Stop polling thread
    self._is_running = False
    if self._thread and self._thread.is_alive():
        self._thread.join()
    
    # Close connection
    with self.modbus_lock:
        if self.client.is_socket_open():
            self.client.close()
            if self.logger:
                self.logger.info("Disconnected from DP16 Process Monitors")