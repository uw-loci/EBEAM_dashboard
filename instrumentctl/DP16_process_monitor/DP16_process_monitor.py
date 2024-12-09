import time
import threading
import struct
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
            timeout=.5
        )
        self.unit_numbers = set(unit_numbers)
        self.modbus_lock = threading.Lock()
        self.logger = logger
        self.lst_resp = {unit: -1 for unit in unit_numbers}
        self._is_running = True
        self._threads = []
        self.start_up_threading()
    
    def start_up_threading(self):
        """
        Starts up the thread for each unit, and called _set_config, before going into the update loop
        """
        try:
            for unit in self.unit_numbers:
                self._set_config(unit)
            self._threads.append(threading.Thread(target=self.update_temperature, daemon=True))
            self._threads[-1].start()
        except Exception as e:
            if self.logger:
                self.logger.error(f"Threading start up failed: {e}")


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


    def _update_temperature(self):
        """
        Single unit read with retries
        """
        
        try:
                # for unit in self.unit_numbers:
                with self.modbus_lock:
                    for unit in self.unit_numbers:
                    # expected 6 for normal; 10 for error
                        status = self.client.read_holding_registers( # Read the Status
                            address=self.STATUS_REG,
                            count=1,
                            slave=unit
                        )

                        if not status.isError():
                            self.logger.debug(f"Status for unit {unit}: {status.registers[0]}")

                            if status.registers[0] == 6: # Normal operation
                                # Read the Temperature
                                response = self.client.read_holding_registers(
                                    address=self.PROCESS_VALUE_REG,
                                    count=2, # for 32 bit float
                                    slave=unit
                                )

                                if not response.isError():
                                    # Convert two 16-bit registers to float
                                    raw_float = struct.pack('>HH', 
                                        response.registers[0], 
                                        response.registers[1])
                                    value = struct.unpack('>f', raw_float)[0]
                                    # inline validation
                                    if -90 <= value <= 500:  # RTD range (P3A-TAPE-REC-PX-1-PFXX-40-STWL)
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
                self.logger.error(f"Communication error: {str(e)}")
        finally:
            time.sleep(0.2)

    def last_response(self):
        # return self.lst_resp
        with self.modbus_lock: # guard access to shared lst_resp variable
            return self.lst_resp.copy()

    def disconnect(self):
        """ Close Modbus connection """
        with self.modbus_lock:
            try:
                if self.client.is_socket_open():
                    self.client.close()
                    if self.logger:
                        self.logger.info("Disconnected from DP16 Process Monitors")
            except Exception as e:
                if self.logger:
                    self.logger.error(f"Error disconnecting: {str(e)}")
