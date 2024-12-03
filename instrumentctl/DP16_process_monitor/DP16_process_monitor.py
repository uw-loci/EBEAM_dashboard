from pymodbus.client import ModbusSerialClient as ModbusClient
import threading
from typing import Dict

class DP16ProcessMonitor:
    """Driver for Omega iSeries DP16PT Process Monitor - Modbus RTU"""

    PROCESS_VALUE_REG = 39  # Register for current temperature reading

    def __init__(self, port, unit_numbers=[1,2,3,4,5], baudrate=9600, logger=None):
        """ Initialize Modbus settings """
        self.client = ModbusClient(
            port=port,
            baudrate=baudrate,
            bytesize=8,
            parity='N',
            stopbits=1,
            timeout=0.5
        )
        self.unit_numbers = unit_numbers
        self.modbus_lock = threading.Lock()

    def read_temperatures(self) -> Dict[int, float]:
        """Read temperatures from all configured units
        
        Returns:
            Dictionary mapping unit numbers to temperature values
        """
        temperatures = {}
        
        for unit in self.unit_numbers:
            try:
                with self.modbus_lock:
                    response = self.client.read_holding_registers(
                        address=self.PROCESS_VALUE_REG,
                        count=1,
                        slave=unit
                    )
                    
                    if not response.isError():
                        # Convert raw value based on decimal point position
                        value = response.registers[0] / 10.0  # TODO: this
                        temperatures[unit] = value
                    else:
                        if self.logger:
                            self.logger.error(f"Error reading unit {unit}")
                        temperatures[unit] = None
                        
            except Exception as e:
                if self.logger:
                    self.logger.error(f"Communication error with unit {unit}: {str(e)}")
                temperatures[unit] = None
                
        return temperatures
