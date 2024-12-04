from pymodbus.client import ModbusSerialClient as ModbusClient
import threading
from typing import Dict

class DP16ProcessMonitor:
    """Driver for Omega iSeries DP16PT Process Monitor - Modbus RTU"""

    PROCESS_VALUE_REG = 39  # Register for current temperature reading
    RDGCNF_REG = 8          # Register for decimal point position

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
        self.logger = logger

    def connect(self):
        with self.modbus_lock:
            try:
                if self.client.is_socket_open():
                    return True
                return self.client.connect()
            except Exception as e:
                if self.logger:
                    self.logger.error(f"Error connecting: {str(e)}")
                return False

    def get_decimal_position(self, unit):
        try:
            with self.modbus_lock:
                response = self.client.read_holding_registers(
                    address = self.RDGCNF_REG,
                    count = 1,
                    slave = unit
                )

                if not response.isError():
                    rdgcnf = response.registers[0]
                    # extract bits 2-0 for decimal point position
                    dp_bits = rdgcnf & 0x07 # get last three bits


                # Decode decimal point position (section 5.7.2):
                # 000 = Not Allowed
                # 001 = FFFF. (1 decimal place)
                # 010 = FFF.F (1 decimal place)
                # 011 = FF.FF (2 decimal places)
                # 100 = F.FFF (3 decimal places)

                if dp_bits == 0b01 or dp_bits == 0b010:
                    return 1
                elif dp_bits == 0b011:
                    return 2
                elif dp_bits == 0b100:
                    return 3
                return 0
        except Exception as e:
            if self.logger:
                self.logger.error(f"Error reading decimal position for unit {unit}: {str(e)}")
            return 0

    def read_temperatures(self):
        """Single unit read with retries
        """
        temperatures = {}
        
        for unit in self.unit_numbers:
            try:

                decimal_pos = self.get_decimal_position(unit)

                with self.modbus_lock:
                    response = self.client.read_holding_registers(
                        address=self.PROCESS_VALUE_REG,
                        count=1,
                        slave=unit
                    )
                    
                    if not response.isError():
                        raw_value = response.registers[0]
                        value = raw_value / (10 ** decimal_pos)
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
