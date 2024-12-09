import time
import threading
import struct
from pymodbus.client import ModbusSerialClient as ModbusClient
from typing import Dict
from utils import LogLevel

class DP16ProcessMonitor:
    """Driver for Omega iSeries DP16PT Process Monitor - Modbus RTU"""

    PROCESS_VALUE_REG = 0x210   # Register 39 in Table 6.2
    RDGCNF_REG = 0x248          # Register 8 in Table 6.2
    STATUS_REG = 0x240

    def __init__(self, port, unit_numbers={1,2,3,4,5}, baudrate=9600, logger=None):
        """ Initialize Modbus settings """
        self.client = ModbusClient(
            port=port,
            baudrate=baudrate,
            bytesize=8,
            parity='N',
            stopbits=1,
            timeout=.2
        )
        self.unit_numbers = unit_numbers
        self.modbus_lock = threading.Lock()
        self.logger = logger
        for unit in unit_numbers:
            self._set_config(unit)

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
        Sets the reading configuration format
        2 - FFF.F
        3 - FFFF
        Returns:
            if setting is successful or not
        """
        if unit not in self.unit_numbers:
            if self.logger:
                self.logger(f"set_decimal_config was called with an invalid unit address", LogLevel.DEBUG)
        try:
            with self.modbus_lock:
                response = self.client.write_register(
                    address=self.RDGCNF_REG,
                    value=0x002,
                    slave=unit
                )
                response = self.client.write_register(
                    address=self.STATUS_REG,
                    value=0x0006,
                    slave=unit
                )
                if not response.isError():
                    return True
                return False
        except Exception as e:
            if self.logger:
                self.logger.error(f"Error writing config: {e}")
            return None

    def read_temperatures(self):
        """
        Single unit read with retries
        """
        temperatures = {}
        try:
            # check/restore connection
            if not self.client.is_socket_open():
                if not self.connect():
                    if self.logger:
                        self.logger.error("Failed to reconnect to DP16 Process Monitors")
                    return temperatures
                
                time.sleep(0.2) # allow connection to stabilize. used for E5CN also
                if hasattr(self.client, 'socket'):
                    self.client.socket.reset_input_buffer()
                
            for unit in self.unit_numbers:

                    with self.modbus_lock:
                        # expected 6 for normal; 10 for error
                        status = self.client.read_holding_registers( # Read the Status
                            address=self.STATUS_REG,
                            count=1,
                            slave=unit
                        )

                        if not status.isError() and status.registers[0] == 6:
                            response = self.client.read_holding_registers( # Read the Temperature
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
                                    temperatures[unit] = value
                                else:
                                    if self.logger:
                                        self.logger.error(f"Temperature out of range: {value}°C")
                                    temperatures[unit] = None
                        else:
                            temperatures[unit] = -1
                            if self.logger:
                                    self.logger.error(f"Return message from unit indicating error status: unit - {unit}")
                            

        except Exception as e:
            if self.logger:
                self.logger.error(f"Communication error: {str(e)}")

        return temperatures

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
