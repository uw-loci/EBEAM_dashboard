from pymodbus.client import ModbusSerialClient as ModbusClient
from pymodbus.payload import BinaryPayloadDecoder
from pymodbus.constants import Endian
from pymodbus.exceptions import ModbusException, ConnectionException
from pymodbus.transaction import ModbusRtuFramer
from pymodbus.pdu import ModbusRequest
import struct

class ES5CNModbus:
    ECHOBACK_ADDRESS = 0x0000  # Address for the echoback test, page 92
    TEMPERATURE_ADDRESS = 0x0000  # Address for reading temperature, page 92
    UNIT_NUMBERS = [1, 2, 3]  # Unit numbers for each controller

    def __init__(self, port, baudrate=9600, timeout=1, parity='E', stopbits=2, bytesize=7, messages_frame=None, debug_mode=False):
        self.client = ModbusClient(method='rtu', port=port, baudrate=baudrate, parity=parity,
                                   stopbits=stopbits, bytesize=bytesize, timeout=timeout)
        self.messages_frame = messages_frame
        self.debug_mode = debug_mode
        if self.debug_mode:
            print("Debug Mode: Modbus communication details will be outputted.")

    def connect(self):
        try:
            if self.client.connect():
                return True
            else:
                raise ConnectionException("Failed to connect to the TempCtrl Modbus device.")
        except ConnectionException as e:
            self.log_message(str(e))
            return False

    def disconnect(self):
        self.client.close()

    def read_temperature(self, unit):
        if not self.client.is_socket_open():
            if not self.connect():
                self.log_message(f"Cannot read temperature: no connection to unit {unit}")
        try:
            response = self.client.read_holding_registers(address=self.TEMPERATURE_ADDRESS, count=2, unit=unit)
            if not response.isError():
                decoder = BinaryPayloadDecoder.fromRegisters(response.registers, byteorder=Endian.Big, wordorder=Endian.Little)
                temperature = decoder.decode_32bit_float()
                self.log_message(f"Temperature from unit {unit}: {temperature:.2f} °C")
                return temperature
            else:
                raise ModbusException("Failed to read temperature due to Modbus error.")
        except ModbusException as e:
            self.log_message(f"Error reading temperature from unit {unit}: {str(e)}")
            return None

    def perform_echoback_test(self, unit):
        if not self.client.is_socket_open():
            if not self.connect():
                self.log_message(f"Cannot perform echoback test: no connection to unit {unit}")
                return False
            
        request = echobackRequest(address=self.ECHOBACK_ADDRESS, values=[0x1234])
        response = self.client.execute(request.create(unit))
        if not response.isError():
            self.log_message(f"Echoback test succeeded for unit {unit}")
            return True
        else:
            self.log_message(f"Echoback test failed for unit {unit}: {response}")
            return False
        
    def log_message(self, message):
        if self.messages_frame:
            self.messages_frame.log_message(message)
        else:
            print(message)

class echobackRequest(ModbusRequest):
    
    function_code = 0x08

    def __init__(self, address, values):
        """ Initializes the request with the address and data values """
        super().__init__()
        self.address = address
        self.values = values

    def encode(self):
        """ Encode request data """
        packet = struct.pack('>H', self.address)  # Echo back the address
        for value in self.values:
            packet += struct.pack('>H', value)
        return packet

    def decode(self, data):
        """ Decode response data from the server """
        self.address, self.values = struct.unpack('>HH', data)

    def create(self, unit):
        """ Create the full request packet, including unit ID """
        return self.encode() + struct.pack('>B', unit)