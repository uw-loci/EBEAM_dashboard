import threading
import time
from pymodbus.client import ModbusSerialClient as ModbusClient
from utils import LogLevel  # Ensure this module is correctly implemented

class E5CNModbus:
    TEMPERATURE_ADDRESS = 0x0000  # Address for reading temperature, page 92
    UNIT_NUMBERS = [1, 2, 3]       # Unit numbers for each controller

    def __init__(self, port, baudrate=9600, timeout=1, parity='E', stopbits=1, bytesize=8, logger=None, debug_mode=False, poll_interval=0.5, retry_delay=0.02):
        """
        Initialize the E5CNModbus instance with serial communication parameters and optional logging.
        
        Parameters:
            port (str): Serial port to connect.
            baudrate (int): Communication baud rate (default: 9600).
            timeout (int): Timeout duration for Modbus communication (default: 1 second).
            parity (str): Parity setting for serial communication (default: 'E' for Even).
            stopbits (int): Number of stop bits (default: 1).
            bytesize (int): Data bits size (default: 8).
            logger (optional): Logger instance for output messages.
            debug_mode (bool): If True, enables debug logging.
            poll_interval (float): Delay between successful steady-state reads (default: 0.5 seconds).
            retry_delay (float): Delay between retries/reconnect attempts (default: 0.02 seconds).
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
        self.poll_interval = max(0.05, float(poll_interval))
        self.retry_delay = max(0.0, float(retry_delay))
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
        active_threads = [thread for thread in self.threads if thread.is_alive()]
        if active_threads:
            self.threads = active_threads
            self.log("Temperature reading threads already running", LogLevel.DEBUG)
            return True

        self.stop_event.clear()

        if not self.connect():
            self.log(
                "Initial E5CN connection failed; background polling will keep retrying.",
                LogLevel.WARNING,
            )
        
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
            time.sleep(self.retry_delay)  # Small delay between thread starts

        if self.threads:
            self.is_initialized.set()
            return True

        self.log("No temperature reading threads were started", LogLevel.ERROR)
        return False

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
                        self.temperatures[unit - 1] = temperature
                        self.log(f"Unit {unit} Temperature: {temperature} C", LogLevel.INFO)
                    time.sleep(self.poll_interval)
                else:
                    self.log(f"Unit {unit} read failed (no response/invalid response)", LogLevel.ERROR)
                    time.sleep(self.retry_delay)
            except Exception as e:
                self.log(f"Error in continuous xtemperature reading for unit {unit}: {str(e)}", LogLevel.ERROR)
                time.sleep(1)  # Longer delay on error

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
                self._close_client_locked()
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
            return self._ensure_connection_locked(force_reopen=False)

    def _close_client_locked(self):
        """Close the Modbus client. Caller must hold modbus_lock."""
        try:
            if self.client.is_socket_open():
                self.client.close()
                self.log("Modbus connection closed", LogLevel.DEBUG)
        except Exception as e:
            self.log(f"Error closing Modbus connection: {str(e)}", LogLevel.ERROR)
        finally:
            self.connected = False

    def _ensure_connection_locked(self, force_reopen=False):
        """Ensure the serial connection is open. Caller must hold modbus_lock."""
        try:
            if force_reopen:
                self._close_client_locked()

            if self.client.is_socket_open():
                self.connected = True
                return True

            if self.client.connect():
                self.connected = True
                self.log(f"E5CN Connected to port {self.port}.", LogLevel.INFO)
                return True

            self.connected = False
            self.log("Failed to connect to the E5CN Modbus device.", LogLevel.ERROR)
            return False
        except Exception as e:
            self.connected = False
            self.log(f"Error connecting to {self.port}: {str(e)}", LogLevel.ERROR)
            return False

    def disconnect(self):
        """Disconnect from the Modbus device with proper locking."""
        with self.modbus_lock:
            try:
                if self.client.is_socket_open():
                    self.client.close()
                    self.connected = False
                    self.log("Disconnected from the E5CN Modbus device.", LogLevel.INFO)
                else:
                    self.log("Client already disconnected from E5CN Modbus device", LogLevel.INFO)
            except Exception as e:
                self.log(f"Error in disconnect: {str(e)}", LogLevel.ERROR)

    def read_temperature(self, unit):
        attempts = 3
        while attempts > 0 and not self.stop_event.is_set():
            try:
                with self.modbus_lock:
                    if not self._ensure_connection_locked(force_reopen=False):
                        attempts -= 1
                        continue

                    response = self.client.read_holding_registers(
                        address=self.TEMPERATURE_ADDRESS,
                        count=2,
                        slave=unit
                    )
                    
                    if response and not response.isError():
                        self.connected = True
                        if not hasattr(response, 'registers') or len(response.registers) < 2:
                            self.log(f"Incomplete temperature register response from unit {unit}: {response}", LogLevel.ERROR)
                            attempts -= 1
                            continue

                        reg0 = response.registers[0] & 0xFFFF
                        reg1 = response.registers[1] & 0xFFFF
                        pv_u32 = (reg0 << 16) | reg1
                        temperature = pv_u32 * 0.1
                        self.log(f"Temperature from unit {unit}: {temperature:.2f} C", LogLevel.INFO)
                        return temperature
                    else:
                        self.log(f"Error reading temperature from unit {unit}: {response}", LogLevel.ERROR)
                        self.connected = False
                        self._close_client_locked()
                        attempts -= 1
                        continue

            except Exception as e:
                self.log(f"Unexpected error for unit {unit}: {str(e)}", LogLevel.ERROR)
                with self.modbus_lock:
                    self._close_client_locked()
                attempts -= 1

            if attempts > 0 and not self.stop_event.is_set():
                time.sleep(self.retry_delay)

        return None

    def log(self, message, level=LogLevel.INFO):
        if self.logger:
            self.logger.log(message, level)
        else:
            print(f"{level.name}: {message}")