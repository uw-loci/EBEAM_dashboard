from pymodbus.client import ModbusSerialClient as ModbusClient
from utils import LogLevel  # Ensure this module is correctly implemented

class E5CNModbus:
    TEMPERATURE_ADDRESS = 0x0000  # Address for reading temperature, page 92
    UNIT_NUMBERS = [1, 2, 3]       # Unit numbers for each controller

    def __init__(self, port, baudrate=9600, timeout=1, parity='E', stopbits=2, bytesize=8, logger=None, debug_mode=False):
        self.logger = logger
        self.debug_mode = debug_mode
        self.log(f"Initializing E5CNModbus with port: {port}", LogLevel.DEBUG)

        # Initialize Modbus client without 'method' parameter
        self.client = ModbusClient(
            port=port,
            baudrate=baudrate,
            parity=parity,
            stopbits=stopbits,
            bytesize=bytesize,
            timeout=timeout
        )

        if self.debug_mode:
            self.log("Debug Mode: Modbus communication details will be outputted.", LogLevel.DEBUG)

    def connect(self):
        try:
            if self.client.is_socket_open():
                self.log("Modbus client already connected.", LogLevel.DEBUG)
                return True

            if self.client.connect():
                self.log(f"E5CN Connected to port {self.client.comm_params.port}.", LogLevel.INFO)
                return True
            else:
                self.log("Failed to connect to the E5CN Modbus device.", LogLevel.ERROR)
                return False
        except Exception as e:
            self.log(f"Error in connect: {str(e)}", LogLevel.ERROR)
            return False

    def disconnect(self):
        self.client.close()
        self.log("Disconnected from the E5CN Modbus device.", LogLevel.INFO)

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

                # Read holding registers with count=2 and slave=unit
                response = self.client.read_holding_registers(address=self.TEMPERATURE_ADDRESS, count=2, slave=unit)

                if response.isError():
                    self.log(f"Error reading temperature from unit {unit}: {response}", LogLevel.ERROR)
                    attempts -= 1
                    continue

                # Log the raw response registers
                self.log(f"Received registers: {response.registers}", LogLevel.DEBUG)

                # Directly access the second register for temperature
                temperature = response.registers[1] / 10.0  # Convert to °C
                self.log(f"Temperature from unit {unit}: {temperature:.2f} °C", LogLevel.INFO)
                return temperature

            except Exception as e:
                self.log(f"Unexpected error for unit {unit}: {str(e)}", LogLevel.ERROR)
                attempts -= 1

        self.log(f"Failed to read temperature from unit {unit} after 3 attempts.", LogLevel.ERROR)
        return None  # Return if all attempts fail

    def log(self, message, level=LogLevel.INFO):
        if self.logger:
            self.logger.log(message, level)
        else:
            print(f"{level.name}: {message}")