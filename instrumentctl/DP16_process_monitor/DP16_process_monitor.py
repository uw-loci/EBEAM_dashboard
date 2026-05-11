import queue
import struct
import threading
import time
from threading import Lock

from utils import LogLevel

try:
    import serial
except ImportError:  # pragma: no cover - handled at runtime with a clear error
    serial = None


class DP16ModbusError(Exception):
    """Raised when a raw Modbus RTU transaction fails."""


class DP16ProcessMonitor:
    """Driver for Omega iSeries DP16PT Process Monitor - Modbus RTU."""

    PROCESS_VALUE_REG = 0x210   # Page 8: CNPt Series Programming User's Guide Modbus Interface
    RDGCNF_REG = 0x248          # Page 9: CNPt Series Programming User's Guide Modbus Interface
    STATUS_REG = 0x240          # Page 9: CNPt Series Programming User's Guide Modbus Interface

    STATUS_RUNNING = 0x0006

    # PT100 RTD temperature range
    MIN_TEMP = -90      # [C]
    MAX_TEMP = 500      # [C]

    # Polling delay
    BASE_DELAY = 0.1    # [seconds]
    MAX_DELAY = 5       # [seconds]

    ERROR_THRESHOLD = 5
    ERROR_LOG_INTERVAL = 10  # [seconds]

    # Raw Modbus/serial timing.
    SERIAL_READ_TIMEOUT = 0.02
    SERIAL_INTER_BYTE_TIMEOUT = 0.02
    WRITE_TIMEOUT = 1.0
    TRANSACTION_TIMEOUT = 0.75
    INTERFRAME_DELAY = 0.005

    # Error states
    DISCONNECTED = -1
    SENSOR_ERROR = -2

    def __init__(self, port, unit_numbers=(1, 2, 3, 4, 5), baudrate=9600, logger=None):
        """Initialize serial settings and start the background polling thread."""
        if serial is None:
            raise RuntimeError("pyserial is not installed. Install with: python -m pip install pyserial")

        self.port = port
        self.baudrate = baudrate
        self._serial = None
        self.unit_numbers = set(unit_numbers)
        self.modbus_lock = Lock()
        self.logger = logger
        self._main_thread_id = threading.get_ident()
        self._background_log_queue = queue.SimpleQueue()

        self.temperature_readings = {unit: None for unit in unit_numbers}
        self.consecutive_error_counts = {unit: 0 for unit in self.unit_numbers}
        self.last_good_readings = {unit: None for unit in self.unit_numbers}
        self.consecutive_connection_errors = 0

        self._is_running = True
        self._thread = threading.Thread(target=self.poll_all_units, daemon=True)
        self.response_lock = Lock()
        self.last_critical_error_time = 0
        self._thread.start()

    @staticmethod
    def _hex_bytes(data: bytes) -> str:
        return " ".join(f"{byte:02X}" for byte in data)

    @staticmethod
    def _modbus_crc16(data: bytes) -> int:
        """Return Modbus RTU CRC-16 as an integer."""
        crc = 0xFFFF
        for byte in data:
            crc ^= byte
            for _ in range(8):
                if crc & 0x0001:
                    crc = (crc >> 1) ^ 0xA001
                else:
                    crc >>= 1
        return crc & 0xFFFF

    @classmethod
    def _append_crc(cls, frame_without_crc: bytes) -> bytes:
        crc = cls._modbus_crc16(frame_without_crc)
        return frame_without_crc + bytes((crc & 0xFF, (crc >> 8) & 0xFF))

    @classmethod
    def _build_read_request(cls, slave: int, function_code: int, address: int, count: int) -> bytes:
        payload = bytes((
            slave,
            function_code,
            (address >> 8) & 0xFF,
            address & 0xFF,
            (count >> 8) & 0xFF,
            count & 0xFF,
        ))
        return cls._append_crc(payload)

    @classmethod
    def _build_write_register_request(cls, slave: int, address: int, value: int) -> bytes:
        payload = bytes((
            slave,
            0x06,
            (address >> 8) & 0xFF,
            address & 0xFF,
            (value >> 8) & 0xFF,
            value & 0xFF,
        ))
        return cls._append_crc(payload)

    def _serial_is_open(self) -> bool:
        return self._serial is not None and self._serial.is_open

    def connect(self):
        """
        Establish a connection to the DP16 units.

        Returns:
            bool: True if at least one unit responds, False otherwise.
        """
        with self.modbus_lock:
            try:
                if self._serial_is_open():
                    self.log("Reusing existing PMON Modbus connection", LogLevel.DEBUG)
                else:
                    self.log(f"Attempting to connect PMON on port {self.port}", LogLevel.DEBUG)
                    self._serial = serial.Serial(
                        port=self.port,
                        baudrate=self.baudrate,
                        bytesize=serial.EIGHTBITS,
                        parity=serial.PARITY_NONE,
                        stopbits=serial.STOPBITS_ONE,
                        timeout=self.SERIAL_READ_TIMEOUT,
                        write_timeout=self.WRITE_TIMEOUT,
                        inter_byte_timeout=self.SERIAL_INTER_BYTE_TIMEOUT,
                    )

                    # Give USB serial adapters a moment after opening the port.
                    time.sleep(0.2)
                    self._serial.reset_input_buffer()
                    self._serial.reset_output_buffer()

                # Check if any unit responds.
                working_units = set()
                for unit in sorted(self.unit_numbers):
                    try:
                        status_registers = self._read_holding_registers_unlocked(
                            unit=unit,
                            address=self.STATUS_REG,
                            count=1,
                        )
                    except Exception as exc:
                        self.log(f"DP16 Unit {unit} not responding: {exc}", LogLevel.WARNING)
                        continue

                    working_units.add(unit)
                    self.log(
                        f"DP16 Unit {unit} responded with status: {status_registers[0]}",
                        LogLevel.VERBOSE,
                    )

                if working_units:
                    self.log(
                        f"Connected to {len(working_units)}/{len(self.unit_numbers)} DP16 units",
                        LogLevel.INFO,
                    )
                    return True
                return False

            except serial.SerialException as exc:
                self.log(f"Serial error during DP16 connection: {exc}", LogLevel.ERROR)
                self._close_serial_unlocked()
                return False
            except Exception as exc:
                self.log(f"DP16 Error connecting: {exc}", LogLevel.ERROR)
                return False

    def _close_serial_unlocked(self):
        if self._serial is not None:
            try:
                self._serial.close()
            finally:
                self._serial = None

    def _read_modbus_response_unlocked(
        self,
        request: bytes,
        expected_function: int,
        expected_register_count: int,
    ) -> bytes:
        """Read until a complete normal/exception Modbus RTU response arrives."""
        ser = self._serial
        if ser is None or not ser.is_open:
            raise DP16ModbusError("Serial port is not open")

        deadline = time.monotonic() + self.TRANSACTION_TIMEOUT
        response = bytearray()

        if expected_function in (0x03, 0x04):
            normal_len = 5 + (2 * expected_register_count)
        elif expected_function == 0x06:
            normal_len = 8
        else:
            raise DP16ModbusError(f"Unsupported Modbus function 0x{expected_function:02X}")

        exception_len = 5
        max_possible_len = len(request) + max(normal_len, exception_len)

        while time.monotonic() < deadline:
            waiting = getattr(ser, "in_waiting", 0)
            remaining = max(1, max_possible_len - len(response))
            chunk = ser.read(max(1, min(remaining, waiting or 1)))
            if not chunk:
                time.sleep(0.001)
                continue

            response.extend(chunk)
            buf = bytes(response)

            # If the beginning is a partial local echo of our request, keep reading.
            if len(buf) < len(request) and request.startswith(buf):
                continue

            # If there is a full echo, parse the candidate response after the echo.
            candidate = buf[len(request):] if buf.startswith(request) and len(buf) > len(request) else buf
            if not candidate:
                continue

            # Exception response: slave, function|0x80, exception_code, crc_lo, crc_hi
            if len(candidate) >= 2 and candidate[1] == (expected_function | 0x80):
                if len(candidate) >= exception_len:
                    break

            if expected_function == 0x06:
                if len(candidate) >= normal_len:
                    break
            elif len(candidate) >= 3 and candidate[1] == expected_function:
                byte_count = candidate[2]
                expected_len = 5 + byte_count
                if len(candidate) >= expected_len:
                    break

            if len(response) >= max_possible_len:
                break

        return bytes(response)

    def _transaction_unlocked(
        self,
        request: bytes,
        expected_function: int,
        expected_register_count: int,
    ) -> bytes:
        ser = self._serial
        if ser is None or not ser.is_open:
            raise DP16ModbusError("Serial port is not open")

        try:
            ser.reset_input_buffer()
            ser.reset_output_buffer()

            # Modbus RTU requires a quiet interval between frames. At 9600 baud,
            # 5 ms is conservative and matches the standalone PMON smoke test.
            if self.INTERFRAME_DELAY > 0:
                time.sleep(self.INTERFRAME_DELAY)

            ser.write(request)
            ser.flush()

            raw_response = self._read_modbus_response_unlocked(
                request=request,
                expected_function=expected_function,
                expected_register_count=expected_register_count,
            )
        except serial.SerialException as exc:
            self._close_serial_unlocked()
            raise DP16ModbusError(f"Serial transaction failed: {exc}") from exc

        if raw_response.startswith(request) and len(raw_response) > len(request):
            self.log("PMON local echo detected and stripped before parsing", LogLevel.DEBUG)
            return raw_response[len(request):]

        if expected_function != 0x06 and raw_response == request:
            raise DP16ModbusError("Only local echo was received; no slave response followed")

        return raw_response

    def _parse_read_response(
        self,
        response: bytes,
        expected_slave: int,
        expected_function: int,
        expected_register_count: int,
    ):
        if not response:
            raise DP16ModbusError("Timeout: no bytes received")

        if len(response) < 5:
            raise DP16ModbusError(f"Incomplete response: only {len(response)} byte(s) received")

        received_crc = response[-2] | (response[-1] << 8)
        calculated_crc = self._modbus_crc16(response[:-2])
        if received_crc != calculated_crc:
            raise DP16ModbusError(
                f"CRC mismatch: received 0x{received_crc:04X}, calculated 0x{calculated_crc:04X}, "
                f"response={self._hex_bytes(response)}"
            )

        slave = response[0]
        function = response[1]

        if slave != expected_slave:
            raise DP16ModbusError(f"Wrong slave address in response: got {slave}, expected {expected_slave}")

        if function == (expected_function | 0x80):
            raise DP16ModbusError(f"Modbus exception response: code 0x{response[2]:02X}")

        if function != expected_function:
            raise DP16ModbusError(
                f"Wrong function code in response: got 0x{function:02X}, expected 0x{expected_function:02X}"
            )

        byte_count = response[2]
        expected_byte_count = 2 * expected_register_count
        if byte_count != expected_byte_count:
            raise DP16ModbusError(f"Wrong byte count: got {byte_count}, expected {expected_byte_count}")

        expected_len = 5 + byte_count
        if len(response) != expected_len:
            raise DP16ModbusError(f"Wrong response length: got {len(response)}, expected {expected_len}")

        data = response[3:3 + byte_count]
        return [int.from_bytes(data[i:i + 2], byteorder="big") for i in range(0, len(data), 2)]

    def _read_holding_registers_unlocked(self, unit: int, address: int, count: int):
        request = self._build_read_request(unit, 0x03, address, count)
        response = self._transaction_unlocked(
            request=request,
            expected_function=0x03,
            expected_register_count=count,
        )
        return self._parse_read_response(
            response=response,
            expected_slave=unit,
            expected_function=0x03,
            expected_register_count=count,
        )

    def _write_register_unlocked(self, unit: int, address: int, value: int):
        request = self._build_write_register_request(unit, address, value)
        response = self._transaction_unlocked(
            request=request,
            expected_function=0x06,
            expected_register_count=1,
        )
        if len(response) != 8:
            raise DP16ModbusError(f"Unexpected write response length: got {len(response)}, expected 8")

        received_crc = response[-2] | (response[-1] << 8)
        calculated_crc = self._modbus_crc16(response[:-2])
        if received_crc != calculated_crc:
            raise DP16ModbusError(
                f"CRC mismatch on write response: received 0x{received_crc:04X}, calculated 0x{calculated_crc:04X}"
            )

        if response[1] & 0x80:
            raise DP16ModbusError(f"Modbus write exception response: code 0x{response[2]:02X}")

        return True

    def get_reading_config(self, unit):
        """Get reading configuration format.

        Returns:
            int: 2 for FFF.F format, 3 for FFFF format, None on error.
        """
        try:
            with self.modbus_lock:
                return self._read_holding_registers_unlocked(
                    unit=unit,
                    address=self.RDGCNF_REG,
                    count=1,
                )[0]
        except Exception as exc:
            self.log(f"Error reading config for DP16 unit {unit}: {exc}", LogLevel.WARNING)
            return None

    def _set_config(self, unit):
        """
        Sets the reading configuration format along with the run state.

        2 - FFF.F
        3 - FFFF

        6 - Running
        10 - Operating
        """
        if unit not in self.unit_numbers:
            self.log("DP16 set_decimal_config was called with an invalid unit address", LogLevel.ERROR)
            return False

        try:
            with self.modbus_lock:
                self.log(f"Setting RDGCNF_REG for unit {unit}", LogLevel.DEBUG)
                self._write_register_unlocked(
                    unit=unit,
                    address=self.RDGCNF_REG,
                    value=0x002,
                )

                self.log(f"Setting STATUS_REG for unit {unit}", LogLevel.DEBUG)
                self._write_register_unlocked(
                    unit=unit,
                    address=self.STATUS_REG,
                    value=self.STATUS_RUNNING,
                )

                self.log(f"Configuration successful for DP16 unit {unit}", LogLevel.INFO)
                return True

        except Exception as exc:
            self.log(f"Error writing RDGCNF_REG config for unit {unit}: {exc}", LogLevel.ERROR)
            return False

    def poll_all_units(self):
        """Single polling loop with each unit independent."""
        while self._is_running:
            current_time = time.time()
            try:
                # Check if client is still connected.
                if not self._serial_is_open():
                    self.consecutive_connection_errors += 1
                    # Mark all disconnected if we exceed error threshold.
                    if self.consecutive_connection_errors >= self.ERROR_THRESHOLD:
                        with self.response_lock:
                            for unit in self.unit_numbers:
                                self.temperature_readings[unit] = self.DISCONNECTED

                    # Try to reconnect.
                    if not self.connect():
                        if current_time - self.last_critical_error_time >= self.ERROR_LOG_INTERVAL:
                            self.log("Failed to reconnect to PMON", LogLevel.ERROR)
                            self.last_critical_error_time = current_time
                        time.sleep(1)
                        continue

                # Poll each unit individually.
                for unit in sorted(self.unit_numbers):
                    if not self._is_running:
                        break
                    try:
                        self._poll_single_unit(unit)
                        self.consecutive_connection_errors = 0
                        time.sleep(0.1)
                    except Exception as exc:
                        self._handle_poll_error(unit, exc)

                        # Rate limited error logging.
                        if current_time - self.last_critical_error_time >= self.ERROR_LOG_INTERVAL:
                            self.log(f"Error polling unit {unit}: {exc}", LogLevel.ERROR)
                            self.last_critical_error_time = current_time

                if self.consecutive_connection_errors == 0:
                    time.sleep(self.BASE_DELAY)

            except Exception as exc:
                self.consecutive_connection_errors += 1
                current_time = time.time()
                if current_time - self.last_critical_error_time >= self.ERROR_LOG_INTERVAL:
                    self.log(f"Polling error: {exc}", LogLevel.ERROR)
                    self.last_critical_error_time = current_time

    def _poll_single_unit(self, unit):
        """Poll a single unit atomically."""
        if not self._is_running:
            return

        with self.modbus_lock:
            # Read status first.
            status_registers = self._read_holding_registers_unlocked(
                unit=unit,
                address=self.STATUS_REG,
                count=1,
            )
            status = status_registers[0]

            # Warn if not in expected running state.
            if status != self.STATUS_RUNNING:
                self.log(
                    f"DP16 Unit {unit} status {status} differs from expected {self.STATUS_RUNNING}",
                    LogLevel.WARNING,
                )

            # Read temperature.
            registers = self._read_holding_registers_unlocked(
                unit=unit,
                address=self.PROCESS_VALUE_REG,
                count=2,
            )

            # Process response.
            raw_float = struct.pack(">HH", registers[0], registers[1])
            value = struct.unpack(">f", raw_float)[0]

            # In-line validation.
            if abs(value) < 0.001:
                raise ValueError("Zero reading indicates communication error")
            if not (self.MIN_TEMP <= value <= self.MAX_TEMP):
                raise ValueError(f"Temperature out of range: {value}")

            # All good, reset the consecutive error count.
            self.consecutive_error_counts[unit] = 0

            # Update reading for GUI availability.
            with self.response_lock:
                self.temperature_readings[unit] = value
                self.last_good_readings[unit] = value

    def _handle_poll_error(self, unit: int, exception: Exception):
        """
        Increment consecutive error counts, log the error, and update
        self.temperature_readings based on the single ERROR_THRESHOLD logic.
        """
        self.log(f"Poll error on unit {unit}: {exception}", LogLevel.VERBOSE)
        self.consecutive_error_counts[unit] += 1

        err_str = str(exception).lower()
        is_modbus_error = isinstance(exception, DP16ModbusError)

        # Classify the error for logging or bus-level increments.
        if is_modbus_error:
            if ("port is closed" in err_str or
                "could not open port" in err_str or
                "serial port is not open" in err_str):
                self.log(f"Hard port failure on unit {unit}: {exception}", LogLevel.ERROR)
                with self.modbus_lock:
                    self._close_serial_unlocked()
                self.consecutive_connection_errors += 1
            elif ("failed to connect" in err_str or
                "connection" in err_str):
                self.log(f"Connection error on unit {unit}: {exception}", LogLevel.WARNING)
                self.consecutive_connection_errors += 1
            elif "timeout" in err_str or "no bytes received" in err_str:
                self.log(f"No PMON response from unit {unit}", LogLevel.DEBUG)
            else:
                self.log(f"General Modbus IO error on unit {unit}: {exception}", LogLevel.ERROR)
        else:
            self.log(f"Invalid reading on unit {unit}: {exception}", LogLevel.WARNING)

        with self.response_lock:
            if self.consecutive_error_counts[unit] >= self.ERROR_THRESHOLD:
                # Enough consecutive errors to declare full disconnection.
                self.temperature_readings[unit] = self.DISCONNECTED
            else:
                # Early failures show the last known good reading if it exists.
                # Mark as SENSOR_ERROR if we never had a good reading.
                if self.last_good_readings[unit] is not None:
                    self.temperature_readings[unit] = self.last_good_readings[unit]
                else:
                    self.temperature_readings[unit] = self.SENSOR_ERROR

    def get_all_temperatures(self):
        """Thread-safe access method."""
        self.flush_queued_logs()
        with self.response_lock:
            return dict(self.temperature_readings)

    def disconnect(self):
        self._is_running = False
        if self._thread and self._thread.is_alive() and threading.get_ident() != self._thread.ident:
            self._thread.join(timeout=2.0)

        with self.modbus_lock:
            if self._serial_is_open():
                self._close_serial_unlocked()
                self.log("Disconnected from DP16 Process Monitors", LogLevel.INFO)
            else:
                self.log("No active connection to DP16 Process Monitors", LogLevel.INFO)

    def flush_queued_logs(self):
        """Flush queued background-thread logs from the main thread only."""
        if threading.get_ident() != self._main_thread_id:
            return

        while True:
            try:
                queued_message, queued_level = self._background_log_queue.get_nowait()
            except queue.Empty:
                break
            self._emit_log(queued_message, queued_level)

    def _emit_log(self, message, level=LogLevel.INFO):
        try:
            if self.logger:
                self.logger.log(message, level)
            else:
                print(f"{level.name}: {message}")
        except Exception as exc:
            print(f"{level.name}: {message}")
            print(f"PMON logger error: {exc}")

    def log(self, message, level=LogLevel.INFO):
        """Log a message without letting Tk logging exceptions stop polling."""
        if self.logger and threading.get_ident() != self._main_thread_id:
            self._background_log_queue.put((message, level))
            return

        self.flush_queued_logs()
        self._emit_log(message, level)
