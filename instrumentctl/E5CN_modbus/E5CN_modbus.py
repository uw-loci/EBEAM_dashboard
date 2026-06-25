import threading
import time
import math
from queue import Queue, Empty, Full
from pymodbus.client import ModbusSerialClient as ModbusClient
from utils import LogLevel  # Ensure this module is correctly implemented

class E5CNModbus:
    TEMPERATURE_ADDRESS = 0x0000  # Address for reading temperature, page 92
    UNIT_NUMBERS = [1, 2, 3]       # Unit numbers for each controller
    MAX_VALID_TEMPERATURE_C = 999.9
    SENSOR_ERROR = "ERROR"
    THREAD_JOIN_TIMEOUT = 2.0
    MODBUS_CLOSE_LOCK_TIMEOUT = 0.5
    WORKER_LOG_QUEUE_MAXSIZE = 1000
    POLL_ERROR_LOG_INTERVAL = 10.0

    def __init__(
        self,
        port,
        baudrate=9600,
        timeout=1,
        parity='E',
        stopbits=2,
        bytesize=8,
        logger=None,
        debug_mode=False,
        disable_logging_when_ccs_power_off=False,
        ccs_power_on_provider=None,
    ):
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
        self.disable_logging_when_ccs_power_off = bool(disable_logging_when_ccs_power_off)
        self.ccs_power_on_provider = ccs_power_on_provider if callable(ccs_power_on_provider) else None
        self.stop_event = threading.Event()
        self.threads = [] # for each unit
        self.temperatures = [None, None, None] 
        self.temperatures_lock = threading.Lock()
        self.modbus_lock = threading.Lock()
        self.is_initialized = threading.Event()
        self.port = port
        self.connected = False
        self._main_thread_ident = threading.get_ident()
        self._log_queue = Queue(maxsize=self.WORKER_LOG_QUEUE_MAXSIZE)
        self._dropped_worker_log_count = 0
        self._dropped_worker_log_lock = threading.Lock()
        self._rate_limited_log_times = {}
        self._rate_limited_log_lock = threading.Lock()
        self._is_dummy_serial_port = self._is_dummy_port(port)
        self._dummy_port_logged = False
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

    def _logging_suppressed(self):
        if not self.disable_logging_when_ccs_power_off or self.ccs_power_on_provider is None:
            return False
        try:
            return not bool(self.ccs_power_on_provider())
        except Exception:
            return False

    @staticmethod
    def _is_dummy_port(port):
        return bool(port) and str(port).upper().startswith("DUMMY_COM")

    def start_reading_temperatures(self):
        """Start threads for continuously reading temperature for each unit."""
        if not self.connect():
            level = LogLevel.DEBUG if self._is_dummy_serial_port else LogLevel.ERROR
            self.log("Cannot start reading temperatures - connection failed", level)
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
        while not self.stop_event.is_set():
            try:
                temperature = self.read_temperature(unit)
                if self.stop_event.is_set():
                    self.connected = False
                    break
                if isinstance(temperature, (int, float)):
                    with self.temperatures_lock:
                        self.temperatures[unit - 1] = temperature
                        self.log(f"Unit {unit} Temperature: {temperature} C", LogLevel.VERBOSE)
                elif temperature == self.SENSOR_ERROR:
                    with self.temperatures_lock:
                        self.temperatures[unit - 1] = temperature
                    self._log_rate_limited(
                        ("sensor_error", unit),
                        f"Unit {unit} temperature reading is invalid",
                        LogLevel.ERROR,
                    )
                elif temperature is not None:
                    with self.temperatures_lock:
                        self.temperatures[unit - 1] = temperature
                    self._log_rate_limited(
                        ("unexpected_temperature", unit),
                        f"Unit {unit} returned unexpected temperature value: {temperature}",
                        LogLevel.ERROR,
                    )
                else:
                    with self.temperatures_lock:
                        self.temperatures[unit - 1] = None
                    self._log_rate_limited(
                        ("null_temperature", unit),
                        f"Unit {unit} is reading null",
                        LogLevel.ERROR,
                    )
                time.sleep(0.5)  # small delay between reads
            except Exception as e:
                if self.stop_event.is_set():
                    self.connected = False
                    break
                self._log_rate_limited(
                    ("continuous_read_exception", unit),
                    f"Error in continuous temperature reading for unit {unit}: {str(e)}",
                    LogLevel.ERROR,
                )
                time.sleep(1)  # Longer delay on error

    def stop_reading(self):
        """Stop all temperature reading threads and clean up connections."""
        self.log("Stopping temperature reading threads...", LogLevel.DEBUG)
        self.stop_event.set()
        self.connected = False
        
        # Wait for threads to finish
        for thread in self.threads:
            thread.join(timeout=self.THREAD_JOIN_TIMEOUT)
            if thread.is_alive():
                self.log(f"Thread {thread.name} did not stop before timeout", LogLevel.WARNING)
            else:
                self.log(f"Thread {thread.name} stopped", LogLevel.DEBUG)
            
        self.threads.clear()
        
        try:
            return self.disconnect()
        finally:
            self.is_initialized.clear()
            self.flush_queued_logs()

    def connect(self):
        """
        Connect to the Modbus device. Opens the serial connection if not already open.
        
        Returns:
            bool: True if connected successfully, False otherwise.
        """
        with self.modbus_lock:
            try:
                if self._is_dummy_serial_port:
                    if not self._dummy_port_logged:
                        self.log(
                            f"E5CN temperature controllers configured for dummy port {self.port}; "
                            "skipping Modbus serial connection.",
                            LogLevel.DEBUG,
                        )
                        self._dummy_port_logged = True
                    self.connected = False
                    return False

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
        """Disconnect from the Modbus device without blocking indefinitely on modbus_lock."""
        if self.modbus_lock.acquire(timeout=self.MODBUS_CLOSE_LOCK_TIMEOUT):
            try:
                return self._close_client()
            finally:
                self.modbus_lock.release()

        self.log("Timed out waiting for E5CN lock; force-closing client", LogLevel.WARNING)
        return self._close_client()

    def _close_client(self):
        """Best-effort close without acquiring modbus_lock."""
        self.connected = False

        if self.client is None:
            self.log("E5CN Modbus client is unavailable while closing connection", LogLevel.ERROR)
            return False

        try:
            if self.client.is_socket_open():
                self.client.close()
                self.log("Modbus connection closed", LogLevel.DEBUG)
            else:
                self.log("Modbus connection already closed", LogLevel.DEBUG)

            if self.client.is_socket_open():
                self.log("E5CN Modbus client still reports open after close", LogLevel.ERROR)
                return False

            return True
        except Exception as e:
            self.log(f"Error closing connection: {str(e)}", LogLevel.ERROR)
            return False

    def read_temperature(self, unit):
        attempts = 3
        original_attempts = attempts
        while attempts > 0 and not self.stop_event.is_set():
            try:
                with self.modbus_lock:
                    if self.stop_event.is_set():
                        return None

                    if not self.client.is_socket_open():
                        try:
                            was_connected = self.connected
                            if self.client.connect():
                                time.sleep(0.2)
                                # clear any stale data
                                if hasattr(self.client, 'socket'):
                                    self.client.socket.reset_input_buffer()
                                if not was_connected:
                                    self.log(f"E5CN reconnected for unit {unit} on {self.port}", LogLevel.INFO)
                                self.connected = True
                            else:
                                self._log_rate_limited(
                                    ("reconnect_failed", unit),
                                    f"Failed to reconnect for unit {unit}",
                                    LogLevel.ERROR,
                                )
                                self.connected = False
                                attempts -= 1
                                continue
                        except Exception as e:
                            self._log_rate_limited(
                                ("reconnect_exception", unit),
                                f"Error during reconnection for unit {unit}: {str(e)}",
                                LogLevel.ERROR,
                            )
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
                        if not math.isfinite(temperature) or temperature > self.MAX_VALID_TEMPERATURE_C:
                            self._log_rate_limited(
                                ("invalid_temperature", unit),
                                f"Invalid temperature from unit {unit}: {temperature:.2f} C "
                                f"exceeds hard maximum {self.MAX_VALID_TEMPERATURE_C:.2f} C",
                                LogLevel.ERROR
                            )
                            return self.SENSOR_ERROR
                        self.log(f"Temperature from unit {unit}: {temperature:.2f} C", LogLevel.VERBOSE)
                        return temperature
                    else:
                        self.log(f"Error reading temperature from unit {unit}: {response}", LogLevel.DEBUG)
                        attempts -= 1
                        continue

            except Exception as e:
                self._log_rate_limited(
                    ("unexpected_read_error", unit),
                    f"Unexpected error for unit {unit}: {str(e)}",
                    LogLevel.ERROR,
                )
                attempts -= 1
                time.sleep(0.1)  # Short delay between retries

        if self.stop_event.is_set():
            return None

        self._log_rate_limited(
            ("read_temperature_failed", unit),
            f"Failed to read temperature from unit {unit} after {original_attempts} attempt(s)",
            LogLevel.ERROR,
        )
        return None

    def _log_rate_limited(self, key, message, level=LogLevel.INFO, interval=None):
        interval = self.POLL_ERROR_LOG_INTERVAL if interval is None else interval
        now = time.monotonic()
        with self._rate_limited_log_lock:
            last_logged = self._rate_limited_log_times.get(key)
            if last_logged is not None and now - last_logged < interval:
                log_level = LogLevel.VERBOSE
            else:
                self._rate_limited_log_times[key] = now
                log_level = level
        self.log(message, log_level)

    def log(self, message, level=LogLevel.INFO):
        if self._logging_suppressed():
            return
        if not self.logger:
            return

        # Tkinter widgets must only be modified from the main GUI thread.
        # Queue logs from worker threads and flush them on the main thread.
        if threading.get_ident() == self._main_thread_ident:
            self.logger.log(message, level, tag="CCS-E5CN")
        else:
            self._enqueue_worker_log(message, level)

    def _enqueue_worker_log(self, message, level):
        """Queue one worker log without blocking if the UI drain is stalled."""
        try:
            self._log_queue.put_nowait((message, level))
            return
        except Full:
            pass

        try:
            self._log_queue.get_nowait()
            self._record_dropped_worker_log()
        except Empty:
            pass

        try:
            self._log_queue.put_nowait((message, level))
        except Full:
            self._record_dropped_worker_log()
            pass

    def _record_dropped_worker_log(self):
        with self._dropped_worker_log_lock:
            self._dropped_worker_log_count += 1

    def _pop_dropped_worker_log_count(self):
        with self._dropped_worker_log_lock:
            count = self._dropped_worker_log_count
            self._dropped_worker_log_count = 0
        return count

    def flush_queued_logs(self, max_messages=200):
        """Flush queued worker-thread log messages on the calling thread."""
        if not self.logger:
            return
        if self._logging_suppressed():
            self._pop_dropped_worker_log_count()
            while True:
                try:
                    self._log_queue.get_nowait()
                except Empty:
                    break
            return
        dropped_count = self._pop_dropped_worker_log_count()
        if dropped_count:
            self.logger.log(
                f"Dropped {dropped_count} queued E5CN worker log message(s) because the log queue was full.",
                LogLevel.WARNING,
                tag="CCS-E5CN",
            )
        processed = 0
        while processed < max_messages:
            try:
                message, level = self._log_queue.get_nowait()
            except Empty:
                break
            self.logger.log(message, level, tag="CCS-E5CN")
            processed += 1
