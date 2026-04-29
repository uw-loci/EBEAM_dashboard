import threading
import time
import sys
import traceback
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
        self.thread_shutdown_timeout = 3.0
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
        self.threads.clear()
        
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
        while not self.stop_event.is_set():
            try:
                temperature = self.read_temperature(unit)
                if temperature is not None:
                    with self.temperatures_lock:
                        self.temperatures[unit - 1] = temperature
                        # self.log(f"Unit {unit} Temperature: {temperature} C", LogLevel.INFO)
                # else:
                    # self.log(f"Unit {unit} is reading null", LogLevel.ERROR)
                self.stop_event.wait(0.5)  # interruptible delay between reads
            except Exception as e:
                # self.log(f"Error in continuous temperature reading for unit {unit}: {str(e)}", LogLevel.ERROR)
                self.stop_event.wait(1)  # interruptible delay on error

    def _log_thread_stack(self, thread):
        """Log the current Python stack for a still-alive thread."""
        try:
            frames = sys._current_frames()
            frame = frames.get(thread.ident)
            if frame is None:
                self.log(f"No stack frame available for {thread.name} (id={thread.ident})", LogLevel.WARNING)
                return

            stack_text = ''.join(traceback.format_stack(frame))
            self.log(
                f"Stack dump for alive thread {thread.name} (id={thread.ident}):\n{stack_text}",
                LogLevel.WARNING,
            )
        except Exception as e:
            self.log(f"Failed to collect stack for {thread.name}: {e}", LogLevel.ERROR)


    def stop_reading(self):
        """Stop all temperature reading threads and clean up connections."""
        self.log("Stopping temperature reading threads...", LogLevel.DEBUG)
        self.stop_event.set()

        # Close the transport first to interrupt blocking read calls.
        # Do this *before* join so workers can exit promptly.
        try:
            if self.client.is_socket_open():
                self.client.close()
                self.log("Modbus connection closed for shutdown", LogLevel.DEBUG)
            else:
                self.log("Client already disconnected from E5CN Modbus device", LogLevel.INFO)
        except Exception as e:
            self.log(f"Error pre-closing connection during shutdown: {str(e)}", LogLevel.ERROR)

        # Wait for threads to finish and report stragglers.
        for thread in list(self.threads):
            thread.join(timeout=self.thread_shutdown_timeout)
            if thread.is_alive():
                self.log(
                    f"Thread {thread.name} did not stop within {self.thread_shutdown_timeout:.1f}s",
                    LogLevel.WARNING,
                )
                self._log_thread_stack(thread)
            else:
                self.log(f"Thread {thread.name} stopped", LogLevel.DEBUG)

        self.threads.clear()

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
        if self.stop_event.is_set():
            return None
        attempts = 3
        while attempts > 0 and not self.stop_event.is_set():
            try:
                with self.modbus_lock:
                    if self.stop_event.is_set():
                        return None
                    
                    if not self.client.is_socket_open():
                        try:
                            if self.stop_event.is_set():
                                return None
                            
                            if self.client.connect():
                                if self.stop_event.wait(0.2):
                                    return None
                                
                                # clear any stale data
                                if hasattr(self.client, 'socket'):
                                    self.client.socket.reset_input_buffer()
                            else:
                                # self.log(f"Failed to reconnect for unit {unit}", LogLevel.ERROR)
                                self.connected = False
                                attempts -= 1
                                continue
                        except Exception as e:
                            # self.log(f"Error during reconnection for unit {unit}: {str(e)}", LogLevel.ERROR)
                            self.connected = False
                            attempts -= 1
                            continue

                    if self.stop_event.is_set():
                        return None

                    response = self.client.read_holding_registers(
                        address=self.TEMPERATURE_ADDRESS,
                        count=2,
                        slave=unit
                    )
                    
                    if response and not response.isError():
                        self.connected = True
                        temperature = response.registers[1] / 10.0
                        # self.log(f"Temperature from unit {unit}: {temperature:.2f} C", LogLevel.INFO)
                        return temperature
                    else:
                        # self.log(f"Error reading temperature from unit {unit}: {response}", LogLevel.ERROR)
                        attempts -= 1
                        return "ERROR"

            except Exception as e:
                # self.log(f"Unexpected error for unit {unit}: {str(e)}", LogLevel.ERROR)
                attempts -= 1
                if self.stop_event.wait(0.1):
                    return None

        return None

    def log(self, message, level=LogLevel.INFO):
        if self.logger:
            self.logger.log(message, level)
        else:
            print(f"{level.name}: {message}")