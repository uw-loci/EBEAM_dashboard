import threading
import time
from pymodbus.client import ModbussSerialClient as ModbusClient
from utils import LogLevel  # Ensure this module is correctly implemented

class KnobBoxModbus:
    # TODO verify addresses for reading output status, set voltage, actual voltage, actual current
    UNIT_NUMBERS = [1, 2, 3, 4] # Unit numbers for each power supply

    def __init__(self, port, baudrate=9600, timeout=1, parity='E', stopbits=2, bytesize=8, logger=None, debug_mode=False):
        """
        Initialize the KnobBoxModbus instance with serial communication parameters and optional logging.
        
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
        self.voltages = [None, None, None, None] 
        self.currents = [None, None, None, None] 
        self.output_statuses = [None, None, None, None] 
        self.voltages_lock = threading.Lock() # Lock for thread-safe access to voltages
        self.currents_lock = threading.Lock() # Lock for thread-safe access to currents
        self.statuses_lock = threading.Lock() # Lock for thread-safe access to output statuses
        self.modbus_lock = threading.Lock() # Lock for Modbus communication
        self.is_initialized = threading.Event() # Event to signal successful initialization
        self.port = port
        self.connected = False
        self.log(f"Initializing KnobBoxModbus with port: {port}", LogLevel.DEBUG)

        # Initialize Modbus client without 'method' parameter
        self.client = ModbusClient(
            port=port,
            baudrate=baudrate,
            parity=parity,
            stopbits=stopbits,
            bytesize=bytesize,
            timeout=timeout,
            retries=2
        )

        if self.debug_mode:
            self.log("Debug Mode: Modbus communication details will be outputted.", LogLevel.DEBUG)
    
    def start_reading_power_supply_data(self):
        """Start threads for continuously reading data for each power supply."""
        if not self.connect():
            self.log("Cannot start reading power supply data - connection failed", LogLevel.ERROR)
            return False
            
        self.stop_event.clear()
        
        for unit in self.UNIT_NUMBERS:
            if self.stop_event.is_set():
                break
                
            thread = threading.Thread(
                target=self.read_power_supply_data, args=(unit))
            thread.start()
            self.threads.append(thread)
            
        self.is_initialized.set()
        return True
    
    def read_power_supply_data(self, unit):
        """Continuously read voltage, current, and output status for a specific power supply unit."""
        while not self.stop_event.is_set():
            try:
                with self.modbus_lock:
                    # Read holding registers for set voltage, actual voltage, actual current, and output status
                    self.log(f"Reading power supply data for unit {unit}", LogLevel.DEBUG)
                    # TODO read actual register addresses and update data
                    time.sleep(.5)  # small delay between reads
            except Exception as e:
                self.log(f"Error reading power supply data for unit {unit}: {str(e)}", LogLevel.ERROR)
                time.sleep(1)  # Wait before retrying

    def stop_reading(self):
        """Stop all reading threads and disconnect from the Modbus device."""
        self.stop_event.set()
        for thread in self.threads:
            thread.join(timeout=2)

        self.threads.clear()
        self.is_initialized.clear()

        self.disconnect()

    def connect(self):
        """
        Connect to the Modbus device. Opens the serial connection if not already open.
        
        Returns:
            bool: True if connected successfully, False otherwise.
        """
        with self.modbus_lock:
            try:
                if self.client.is_socket_open():
                    self.connected = True
                    self.log("Modbus client already connected.", LogLevel.DEBUG)
                    return True

                if self.client.connect():
                    self.connected = True
                    self.log(f"E5CN Connected to port {self.port}.", LogLevel.INFO)
                    return True
                else:
                    self.log("Failed to connect to the E5CN Modbus device.", LogLevel.ERROR)
                    return False
            except Exception as e:
                self.log(f"Error connecting to {self.port}: {str(e)}", LogLevel.ERROR)
                return False

    def disconnect(self):
        """Disconnect from the Modbus device."""
        with self.modbus_lock:
            try:
                if self.client.is_socket_open():
                    self.client.close()
                    self.log("Disconnected from the E5CN Modbus device.", LogLevel.INFO)
                else:
                    self.log("Client already disconnected from E5CN Modbus device", LogLevel.INFO)
            except Exception as e:
                self.log(f"Error in disconnect: {str(e)}", LogLevel.ERROR)

    def log(self, message, level=LogLevel.INFO):
        if self.logger:
            self.logger.log(message, level)
        else:
            print(f"{level.name}: {message}")