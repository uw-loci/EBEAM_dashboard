from pymodbus.client import ModbusSerialClient as ModbusClient
from pymodbus.payload import BinaryPayloadDecoder
from pymodbus.constants import Endian
import serial

class ES5CNModbus:
    ECHOBACK_ADDRESS = 0x0000  # Address for the echoback test, page 92
    TEMPERATURE_ADDRESS = 0x0000  # Address for reading temperature, page xx
    UNIT_NUMBERS = [1, 2, 3]  # Example unit numbers for each controller

    def __init__(self, port, baudrate=9600, timeout=1, parity='N', stopbits=1, bytesize=8, messages_frame=None, debug_mode=False):
        self.client = ModbusClient(method='rtu', port=port, baudrate=baudrate, parity=parity,
                                   stopbits=stopbits, bytesize=bytesize, timeout=timeout)
        self.messages_frame = messages_frame
        self.debug_mode = debug_mode
        if self.debug_mode:
            print("Debug Mode: Modbus communication details will be outputted.")

    def connect(self):
        return self.client.connect()

    def disconnect(self):
        self.client.close()

    def read_temperature(self, unit):
        response = self.client.read_input_registers(address=self.TEMPERATURE_ADDRESS, count=2, unit=unit)
        if not response.isError():
            decoder = BinaryPayloadDecoder.fromRegisters(response.registers, byteorder=Endian.Big, wordorder=Endian.Little)
            temperature = decoder.decode_32bit_float()
            message = f"Temperature from unit {unit}: {temperature:.2f} °C"
            if self.messages_frame:
                self.messages_frame.log_message(message)
            return temperature
        else:
            error_msg = f"Error reading temperature from unit {unit}"
            if self.messages_frame:
                self.messages_frame.log_message(error_msg)
            return None

    def perform_echoback_test(self, unit):
        test_data = [0x12, 0x34]  # Example data for echoback
        response = self.client.write_registers(address=self.ECHOBACK_ADDRESS, values=test_data, unit=unit)
        if not response.isError():
            success_msg = f"Echoback response from unit {unit}: Success"
            if self.messages_frame:
                self.messages_frame.log_message(success_msg)
            return True
        else:
            error_msg = f"Failed echoback from unit {unit}, error: {response}"
            if self.messages_frame:
                self.messages_frame.log_message(error_msg)
            return False