import threading
import time
from pymodbus.client import ModbusSerialClient as ModbusClient
from utils import LogLevel  # Ensure this module is correctly implemented

class E5CNModbus:
    TEMPERATURE_ADDRESS = 0x0000  # Address for reading temperature, page 92
    UNIT_NUMBERS = [1, 2, 3]       # Unit numbers for each controller

    def __init__(self, port, baudrate=9600, timeout=1, parity='E', stopbits=2, bytesize=8, logger=None, debug_mode=False):
        """
        Initialize the E5CNModbus instance with serial communication parameters and optional logging.
        
        Parameters:
            port (str): Serial port to connect.
            baudrate (int): Communication baud rate (default: 9600).
            timeout (int): Timeout duration for Modbus communication (default: 1 second).
            parity (str): Parity setting for serial communication (default: 'E' for Even).
            stopbits (int): Number of stop bits (default: 2).
            bytesize (int): Data bits size (default: 8).
            logger (optional): Logger instance for output messages.
            debug_mode (bool): If True, enables debug logging.
        """
        self.logger = logger
        self.debug_mode = debug_mode
        self.stop_event = threading.Event()
        self.threads = [] # for each unit
        self.temperatures = [None, None, None] 
        self.temperatures_lock = threading.Lock()
        self.client_lock = threading.Lock()
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

    def start_reading_temperatures(self):
        """Start threads for continuously reading temperature for each unit."""
        for unit in self.UNIT_NUMBERS:
            thread = threading.Thread(target=self._read_temperature_continuously, args=(unit,), daemon=True)
            thread.start()
            self.threads.append(thread)

    def _read_temperature_continuously(self, unit):
        """
        Continuously read temperature data in a loop for the specified unit.

        Parameters:
            unit (int): The unit number to read temperature from.
        """
        while not self.stop_event.is_set():
            try:
                temperature = self.read_temperature(unit)
                if temperature is not None:
                    with self.temperatures_lock:
                        
                        self.temperatures[unit - 1] = temperature  # Store the latest temperature
                        self.log(f"Unit {unit} Temperature: {temperature} °C", LogLevel.INFO)

            except Exception as e:
                self.log(f"Error reading temperature for unit {unit}: {str(e)}", LogLevel.ERROR)

            # Sleep for 500 ms before the next reading
            time.sleep(0.5)

    def stop_reading(self):
        """Stop all active temperature reading threads and clear them from the thread list."""
        self.stop_event.set()
        for thread in self.threads:
            thread.join()  # Wait for the thread to finish
        self.threads.clear()
        self.log("Stopped all temperature reading threads", LogLevel.INFO)

    def connect(self):
        """
        Connect to the Modbus device. Opens the serial connection if not already open.
        
        Returns:
            bool: True if connected successfully, False otherwise.
        """
        with self.client_lock:
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
        """
        Read the temperature value from the specified unit.
        
        Parameters:
            unit (int): Unit number to read from.

        Returns:
            float or None: The temperature in Celsius if successful, None if all attempts fail.
        """
        attempts = 3
        while attempts > 0:
            try:
                with self.client_lock: # Synchronize access to client
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