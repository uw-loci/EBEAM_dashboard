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
        self.modbus_lock = threading.Lock()
        self.is_initialized = threading.Event()
        self.port = port
        self.connected = False
        self.log(f"Initializing E5CNModbus with port: {port}", LogLevel.DEBUG)

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

    def start_reading_temperatures(self):
        """Start threads for continuously reading temperature for each unit."""
        if not self.connect():
            self.log("Cannot start reading temperatures - connection failed", LogLevel.ERROR)
            return False
            
        self.stop_event.clear()
        
        for unit in self.UNIT_NUMBERS:
            if self.stop_event.is_set():
                break
                
            thread = threading.Thread(
                target=self._read_temperature_continuously, 
                args=(unit,),
                name=f"TempReader-Unit{unit}",
                daemon=True
            )
            thread.start()
            self.threads.append(thread)
            self.log(f"Started temperature reading thread for unit {unit}", LogLevel.DEBUG)
            time.sleep(0.1)  # Small delay between thread starts
            
        return True

    def _read_temperature_continuously(self, unit):
        """
        Continuously read temperature data in a loop for the specified unit.

        Parameters:
            unit (int): The unit number to read temperature from.
        """
        consecutive_errors = 0
        max_consecutive_errors = 5
        
        while not self.stop_event.is_set():
            try:
                temperature = self.read_temperature(unit)
                if temperature is not None and isinstance(temperature, (int, float)):
                    with self.temperatures_lock:
                        self.temperatures[unit - 1] = temperature
                        self.log(f"Unit {unit} Temperature: {temperature} C", LogLevel.INFO)
                    consecutive_errors = 0  # Reset error counter on successful read
                elif isinstance(temperature, str):
                    # Handle error string from read_temperature
                    with self.temperatures_lock:
                        self.temperatures[unit - 1] = temperature
                    consecutive_errors += 1
                    self.log(f"Unit {unit} returned error: {temperature}", LogLevel.ERROR)
                else:
                    consecutive_errors += 1
                    self.log(f"Unit {unit} is reading null", LogLevel.ERROR)
                    
                # If too many consecutive errors, increase the sleep time to reduce load
                if consecutive_errors >= max_consecutive_errors:
                    self.log(f"Unit {unit} has {consecutive_errors} consecutive errors, increasing read interval", LogLevel.WARNING)
                    time.sleep(2.0)  # Longer delay after many errors
                else:
                    time.sleep(0.5)  # Normal delay between reads
                    
            except Exception as e:
                consecutive_errors += 1
                self.log(f"Error in continuous temperature reading for unit {unit}: {str(e)}", LogLevel.ERROR)
                with self.temperatures_lock:
                    self.temperatures[unit - 1] = "ERROR"
                    
                # Increase delay based on error count
                if consecutive_errors >= max_consecutive_errors:
                    time.sleep(5.0)  # Much longer delay if repeated exceptions
                else:
                    time.sleep(1.0)  # Longer delay on error

    def stop_reading(self):
        """Stop all temperature reading threads and clean up connections."""
        self.log("Stopping temperature reading threads...", LogLevel.DEBUG)
        self.stop_event.set()
        
        # Wait for threads to finish
        for thread in self.threads:
            thread.join(timeout=2.0)
            self.log(f"Thread {thread.name} stopped", LogLevel.DEBUG)
            
        self.threads.clear()
        
        # Clean up the connection
        with self.modbus_lock:
            try:
                if self.client.is_socket_open():
                    self.client.close()
                    self.log("Modbus connection closed", LogLevel.DEBUG)
            except Exception as e:
                self.log(f"Error closing connection: {str(e)}", LogLevel.ERROR)
                
        self.is_initialized.clear()

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
        """Disconnect from the Modbus device with proper locking."""
       # with self.modbus_lock:
        try:
            if self.client.is_socket_open():
                self.client.close()
                self.log("Disconnected from the E5CN Modbus device.", LogLevel.INFO)
            else:
                self.log("Client already disconnected from E5CN Modbus device", LogLevel.INFO)
        except Exception as e:
            self.log(f"Error in disconnect: {str(e)}", LogLevel.ERROR)

    def read_temperature(self, unit):
        """
        Read temperature from a specific unit with reduced blocking and timeout.
        This method is used for one-off reads and includes retry logic.
        For continuous monitoring, use the threaded reading approach instead.
        """
        attempts = 2  # Reduced from 3 to minimize blocking time
        timeout_per_attempt = 0.5  # Maximum time per attempt
        
        while attempts > 0:
            start_time = time.time()
            try:
                # Use a shorter timeout for the lock to avoid long blocks
                if self.modbus_lock.acquire(timeout=timeout_per_attempt):
                    try:
                        if not self.client.is_socket_open():
                            try:
                                if self.client.connect():
                                    time.sleep(0.1)  # Reduced from 0.2
                                    # clear any stale data
                                    if hasattr(self.client, 'socket'):
                                        self.client.socket.reset_input_buffer()
                                else:
                                    self.log(f"Failed to reconnect for unit {unit}", LogLevel.ERROR)
                                    self.connected = False
                                    attempts -= 1
                                    continue
                            except Exception as e:
                                self.log(f"Error during reconnection for unit {unit}: {str(e)}", LogLevel.ERROR)
                                self.connected = False
                                attempts -= 1
                                continue

                        response = self.client.read_holding_registers(
                            address=self.TEMPERATURE_ADDRESS,
                            count=2,
                            slave=unit
                        )
                        
                        if response and not response.isError():
                            self.connected = True
                            temperature = response.registers[1] / 10.0
                            self.log(f"Temperature from unit {unit}: {temperature:.2f} C", LogLevel.INFO)
                            return temperature
                        else:
                            self.log(f"Error reading temperature from unit {unit}: {response}", LogLevel.ERROR)
                            attempts -= 1
                            return "ERROR"
                    finally:
                        self.modbus_lock.release()
                else:
                    # Lock acquisition timeout
                    self.log(f"Timeout acquiring lock for unit {unit}", LogLevel.WARNING)
                    attempts -= 1
                    
                # Check if we've exceeded the per-attempt timeout
                if time.time() - start_time > timeout_per_attempt:
                    self.log(f"Timeout reading temperature from unit {unit}", LogLevel.WARNING)
                    attempts -= 1

            except Exception as e:
                self.log(f"Unexpected error for unit {unit}: {str(e)}", LogLevel.ERROR)
                attempts -= 1
                # Reduced sleep time to minimize blocking
                if attempts > 0:
                    time.sleep(0.05)  # Reduced from 0.1

        return None

    def get_latest_temperature(self, unit):
        """
        Get the latest temperature reading for a unit without blocking.
        This uses the continuously updated temperature data from the background threads.
        
        Parameters:
            unit (int): The unit number (1-3)
        
        Returns:
            float, str, or None: Latest temperature value, "ERROR" string, or None if no data
        """
        try:
            if unit < 1 or unit > 3:
                self.log(f"Invalid unit number: {unit}. Must be 1-3.", LogLevel.ERROR)
                return None
                
            with self.temperatures_lock:
                return self.temperatures[unit - 1]
        except Exception as e:
            self.log(f"Error getting latest temperature for unit {unit}: {str(e)}", LogLevel.ERROR)
            return None

    def log(self, message, level=LogLevel.INFO):
        if self.logger:
            self.logger.log(message, level)
        else:
            print(f"{level.name}: {message}")