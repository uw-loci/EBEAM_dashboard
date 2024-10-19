from pymodbus.client import ModbusSerialClient as ModbusClient
from pymodbus.payload import BinaryPayloadDecoder
from pymodbus.constants import Endian
from pymodbus.exceptions import ModbusException, ConnectionException
from pymodbus.diag_message import ReturnQueryDataRequest
from pymodbus.pdu import ModbusRequest
import struct
import serial.tools.list_ports
from utils import LogLevel

class E5CNModbus:
    TEMPERATURE_ADDRESS = 0x0000  # Address for reading temperature, page 92
    UNIT_NUMBERS = [1, 2, 3]  # Unit numbers for each controller

    def __init__(self, port, baudrate=9600, timeout=1, parity='E', stopbits=2, bytesize=8, logger=None, debug_mode=False):
        self.logger = logger
        self.log(f"Initializing E5CNModbus with port: {port}", LogLevel.DEBUG)
        self.client = ModbusClient(method='rtu', port=port, baudrate=baudrate, parity=parity,
                                   stopbits=stopbits, bytesize=bytesize, timeout=timeout)
        
        self.client.comm_params.port = port
        self.debug_mode = debug_mode
        if self.debug_mode:
            self.log("Debug Mode: Modbus communication details will be outputted.", LogLevel.DEBUG)

    def connect(self):
        try:
            if self.client.is_socket_open():
                return True
            if self.client.connect():
                self.log(f"E5CN Connected to port {self.client.comm_params.port}.", LogLevel.INFO)
                return True
            else:
                self.log("Failed to connect to the E5CN modbus device.", LogLevel.ERROR)
                return False
        except Exception as e:
            self.log(str(e), LogLevel.ERROR)
            return False

    def disconnect(self):
        self.client.close()

    def read_temperature(self, unit):
        attempts = 3
        while attempts > 0:
            try:
                if not self.client.is_socket_open():
                    self.log(f"Socket not open for unit {unit}. Attempting to reconnect...", LogLevel.WARNING)
                    if not self.connect():
                        self.log(f"Failed to reconnect for unit {unit}", LogLevel.ERROR)
                        attempts -= 1
                        continue

                response = self.client.read_holding_registers(address=self.TEMPERATURE_ADDRESS, count=10, unit=unit)
                if response.isError():
                    self.log(f"Error reading temperature from unit {unit}: {response}", LogLevel.ERROR)
                    attempts -= 1
                    continue                        

                decoder = BinaryPayloadDecoder.fromRegisters(
                    response.registers, 
                    byteorder=Endian.Big
                    )
                
                value = decoder.decode_16bit_int()

                """
                Section 5.3 Variable Area, page 5-8 (PDF pg.90):
                    The values read from the variable area or written to the variable area
                    are expressed in hexadecimal, ignoring the decimal point position
                """
                temperature = value / 10.0 # Reference pg. 90 E5CN Digital Communications Manual
                self.log(f"Temperature from unit {unit}: {temperature:.2f} °C", )
                return temperature

            except Exception as e:
                self.log(f"Unexpected error for unit {unit}: {str(e)}", LogLevel.ERROR)
                attempts -= 1
        
        self.log(f"Failed to read temperature from unit {unit} after {3 - attempts} attempts.", LogLevel.ERROR)
        return None # return if all the attempts fail

    def perform_echoback_test(self, unit):
        if not self.client.is_socket_open():
            if not self.connect():
                self.log(f"Cannot perform echoback test: no connection to unit {unit}", LogLevel.ERROR)
                return False
        
        try:
            request = ReturnQueryDataRequest(message=b'\x12\x34')
            request.unit_id = unit
            response = self.client.execute(request)
            
            if not response.isError() and response.message == b'\x12\x34':
                self.log(f"Echoback test succeeded for unit {unit}", LogLevel.INFO)
                return True
            else:
                self.log(f"Echoback test failed for unit {unit}: unexpected response data", LogLevel.ERROR)
                return False

        except Exception as e:
            self.log(f"Echoback test failed with error: {str(e)}", LogLevel.ERROR)
            return False
    
    def log(self, message, level=LogLevel.INFO):
        if self.logger:
            self.logger.log(message, level)
        else:
            print(f"{level.name}: {message}")
