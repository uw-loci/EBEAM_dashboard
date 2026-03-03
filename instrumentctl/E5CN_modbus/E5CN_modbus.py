import threading
import time
from pymodbus.client import ModbusSerialClient as ModbusClient
from utils import LogLevel  # Ensure this module is correctly implemented

class E5CNModbus:
    TEMPERATURE_ADDRESS = 0x0000  # Address for reading temperature, page 92
    UNIT_NUMBERS = [1, 2, 3]       # Unit numbers for each controller

    def __init__(self, port, baudrate=9600, timeout=1, parity='E', stopbits=1, bytesize=8, logger=None, debug_mode=False, poll_interval=0.5, retry_delay=0.02, disconnect_timeout=4.0):
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
            disconnect_timeout (float): Time without successful reads before a unit is marked disconnected.
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
        self.disconnect_timeout = max(1.0, float(disconnect_timeout))
        self.last_success_time = [None, None, None]
        self.unit_connected = [False, False, False]
        self.log_throttle_intervals = {
            "connect_failed": 30.0,
            "connect_exception": 30.0,
            "continuous_read_failed": 15.0,
            "continuous_read_exception": 15.0,
            "incomplete_response": 15.0,
            "read_error": 15.0,
            "unexpected_read_error": 15.0,
            "unit_temperature": 5.0,
        }
        self.last_log_times = {}
        self.log_throttle_lock = threading.Lock()
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

    def _close_client_best_effort(self, lock_timeout=0.2):
        """Attempt to close the client without blocking shutdown indefinitely."""
        acquired = False
        try:
            acquired = self.modbus_lock.acquire(timeout=lock_timeout)
            if not acquired:
                self.log("Timed out waiting for Modbus lock during shutdown close", LogLevel.WARNING)
                return False
            self._close_client_locked()
            return True
        except Exception as e:
            self.log(f"Error during best-effort client close: {str(e)}", LogLevel.ERROR)
            return False
        finally:
            if acquired:
                self.modbus_lock.release()

    # Minimum pause between reading successive slave IDs on the RS-485 bus (seconds).
    # Rapid slave switching without a settle delay causes "no response" errors.
    INTER_UNIT_DELAY = 0.15

    def start_reading_temperatures(self):
        """Start a single polling thread that reads all units sequentially.

        Using one thread eliminates the port-thrashing that occurs when multiple
        threads close and reopen the shared serial connection on read failures.
        """
        active_threads = [thread for thread in self.threads if thread.is_alive()]
        if active_threads:
            self.threads = active_threads
            self.log("Temperature reading thread already running", LogLevel.DEBUG)
            return True

        self.stop_event.clear()

        if not self.connect():
            self.log(
                "Initial E5CN connection failed; background polling will keep retrying.",
                LogLevel.WARNING,
            )

        thread = threading.Thread(
            target=self._poll_all_units,
            name="TempReader-AllUnits",
            daemon=True
        )
        thread.start()
        self.threads.append(thread)
        self.log("Started sequential temperature polling thread for all units", LogLevel.DEBUG)

        self.is_initialized.set()
        return True

    def _poll_all_units(self):
        """Single thread that polls all units sequentially with an inter-unit RS-485 delay.

        This replaces the previous per-unit thread design.  All three units share
        one serial port so running three threads simply serialised them through
        modbus_lock, but each thread's error path called _close_client_locked()
        which tore down the shared connection for every other thread.  That caused
        a reconnection storm visible as repeated 'E5CN Connected' log lines
        followed by 'No response received' errors on the remaining units.
        """
        while not self.stop_event.is_set():
            any_exception = False
            for unit in self.UNIT_NUMBERS:
                if self.stop_event.is_set():
                    break

                try:
                    temperature = self.read_temperature(unit)
                    if temperature is not None:
                        self._record_success(unit, temperature)
                    else:
                        self._record_failure(unit)
                        self._log_throttled(
                            key=f"continuous_read_failed_{unit}",
                            message=f"Unit {unit} read failed (no response/invalid response)",
                            level=LogLevel.ERROR,
                            interval_seconds=self.log_throttle_intervals["continuous_read_failed"],
                        )
                except Exception as e:
                    any_exception = True
                    self._record_failure(unit)
                    self._log_throttled(
                        key=f"continuous_read_exception_{unit}",
                        message=f"Error reading temperature for unit {unit}: {str(e)}",
                        level=LogLevel.ERROR,
                        interval_seconds=self.log_throttle_intervals["continuous_read_exception"],
                    )

                # Pause between slave IDs to allow RS-485 bus to settle.
                if not self.stop_event.is_set():
                    time.sleep(self.INTER_UNIT_DELAY)

            if self.stop_event.is_set():
                break

            if any_exception:
                # Back off longer when an unrecoverable exception occurred.
                time.sleep(1.0)
            else:
                # Normal steady-state inter-cycle delay.
                time.sleep(self.poll_interval)

    def stop_reading(self):
        """Stop all temperature reading threads and clean up connections."""
        self.log("Stopping temperature reading threads...", LogLevel.DEBUG)
        self.stop_event.set()

        # Try to close quickly, but never block shutdown waiting on modbus_lock.
        self._close_client_best_effort(lock_timeout=0.1)
        
        threads_to_join = list(self.threads)
        
        # Wait for threads to finish
        for thread in threads_to_join:
            thread.join(timeout=1.0)
            if thread.is_alive():
                self.log(f"Thread {thread.name} did not stop before timeout", LogLevel.WARNING)
            else:
                self.log(f"Thread {thread.name} stopped", LogLevel.DEBUG)

        self.threads = [thread for thread in threads_to_join if thread.is_alive()]

        with self.temperatures_lock:
            self.temperatures = [None, None, None]
            self.last_success_time = [None, None, None]
            self.unit_connected = [False, False, False]
        
        # Final non-blocking close attempt.
        self._close_client_best_effort(lock_timeout=0.1)

        self.is_initialized.clear()

    def connect(self):
        """
        Connect to the Modbus device. Opens the serial connection if not already open.
        
        Returns:
            bool: True if connected successfully, False otherwise.
        """
        with self.modbus_lock:
            return self._ensure_connection_locked(force_reopen=False)

    def _record_success(self, unit, temperature):
        idx = unit - 1
        now = time.monotonic()
        with self.temperatures_lock:
            was_connected = self.unit_connected[idx]
            self.temperatures[idx] = temperature
            self.last_success_time[idx] = now
            self.unit_connected[idx] = True

        if not was_connected:
            self.log(f"Temperature controller unit {unit} communication restored", LogLevel.INFO)

        self._log_throttled(
            key=f"unit_temperature_{unit}",
            message=f"Unit {unit} Temperature: {temperature} C",
            level=LogLevel.INFO,
            interval_seconds=self.log_throttle_intervals["unit_temperature"],
        )

    def _record_failure(self, unit):
        idx = unit - 1
        now = time.monotonic()
        with self.temperatures_lock:
            last_success = self.last_success_time[idx]
            if last_success is None:
                self.unit_connected[idx] = False
                self.temperatures[idx] = None
                return

            if (now - last_success) >= self.disconnect_timeout:
                if self.unit_connected[idx]:
                    self.log(
                        f"Temperature controller unit {unit} marked disconnected after {self.disconnect_timeout:.1f}s without valid data",
                        LogLevel.WARNING,
                    )
                self.unit_connected[idx] = False
                self.temperatures[idx] = None

    def get_temperature(self, unit):
        idx = unit - 1
        if idx < 0 or idx >= len(self.temperatures):
            return None

        now = time.monotonic()
        with self.temperatures_lock:
            last_success = self.last_success_time[idx]
            if last_success is None:
                self.unit_connected[idx] = False
                return None

            if (now - last_success) >= self.disconnect_timeout:
                self.unit_connected[idx] = False
                self.temperatures[idx] = None
                return None

            if not self.unit_connected[idx]:
                return None

            return self.temperatures[idx]

    def is_unit_connected(self, unit):
        idx = unit - 1
        if idx < 0 or idx >= len(self.unit_connected):
            return False

        with self.temperatures_lock:
            last_success = self.last_success_time[idx]
            if last_success is None:
                return False

            if (time.monotonic() - last_success) >= self.disconnect_timeout:
                self.unit_connected[idx] = False
                self.temperatures[idx] = None
                return False

            return self.unit_connected[idx]

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

    def _log_throttled(self, key, message, level, interval_seconds):
        now = time.monotonic()
        with self.log_throttle_lock:
            last_log_time = self.last_log_times.get(key)
            if last_log_time is not None and (now - last_log_time) < interval_seconds:
                return
            self.last_log_times[key] = now

        self.log(message, level)

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
            self._log_throttled(
                key="connect_failed",
                message="Failed to connect to the E5CN Modbus device.",
                level=LogLevel.ERROR,
                interval_seconds=self.log_throttle_intervals["connect_failed"],
            )
            return False
        except Exception as e:
            self.connected = False
            self._log_throttled(
                key="connect_exception",
                message=f"Error connecting to {self.port}: {str(e)}",
                level=LogLevel.ERROR,
                interval_seconds=self.log_throttle_intervals["connect_exception"],
            )
            return False

    def disconnect(self):
        """Disconnect from the Modbus device with proper locking."""
        self.stop_event.set()

        try:
            self.stop_reading()
        except Exception as e:
            self.log(f"Error while stopping temperature readers: {str(e)}", LogLevel.ERROR)

        with self.temperatures_lock:
            self.temperatures = [None, None, None]
            self.last_success_time = [None, None, None]
            self.unit_connected = [False, False, False]

        if self._close_client_best_effort(lock_timeout=0.2):
            self.log("Disconnected from the E5CN Modbus device.", LogLevel.INFO)
        else:
            self.log(
                "Disconnect proceeded without waiting for a busy Modbus lock; "
                "background thread will exit via stop_event.",
                LogLevel.WARNING,
            )

        self.is_initialized.clear()

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
                            self._log_throttled(
                                key=f"incomplete_response_{unit}",
                                message=f"Incomplete temperature register response from unit {unit}: {response}",
                                level=LogLevel.ERROR,
                                interval_seconds=self.log_throttle_intervals["incomplete_response"],
                            )
                            attempts -= 1
                            continue

                        reg0 = response.registers[0] & 0xFFFF
                        reg1 = response.registers[1] & 0xFFFF
                        pv_u32 = (reg0 << 16) | reg1
                        temperature = pv_u32 * 0.1
                        self.log(f"Temperature from unit {unit}: {temperature:.2f} C", LogLevel.INFO)
                        return temperature
                    else:
                        # A missing/error Modbus response does NOT mean the serial
                        # connection is broken — the RS-485 line is shared by all
                        # units.  Closing the port here tears down the connection
                        # for every other unit thread and causes a reconnection
                        # storm.  Simply retry without touching the socket.
                        self._log_throttled(
                            key=f"read_error_{unit}",
                            message=f"Error reading temperature from unit {unit}: {response}",
                            level=LogLevel.ERROR,
                            interval_seconds=self.log_throttle_intervals["read_error"],
                        )
                        attempts -= 1
                        continue

            except Exception as e:
                # A real communication exception (e.g. OSError, serial timeout)
                # may indicate a broken port — close and let the next attempt
                # reconnect.
                self._log_throttled(
                    key=f"unexpected_read_error_{unit}",
                    message=f"Unexpected error for unit {unit}: {str(e)}",
                    level=LogLevel.ERROR,
                    interval_seconds=self.log_throttle_intervals["unexpected_read_error"],
                )
                with self.modbus_lock:
                    self._close_client_locked()
                attempts -= 1

            if attempts > 0 and not self.stop_event.is_set():
                time.sleep(self.retry_delay)

        return None

    def log(self, message, level=LogLevel.INFO):
        try:
            # Tk widgets are not thread-safe. Avoid UI-backed logger calls from
            # background worker threads because they can hang during app close.
            if self.logger and threading.current_thread() is threading.main_thread():
                self.logger.log(message, level)
            else:
                print(f"{level.name}: {message}")
        except Exception:
            # Never allow logging failures (e.g., Tk widget teardown/threading)
            # to crash communication threads or shutdown paths.
            try:
                print(f"{level.name}: {message}")
            except Exception:
                pass
