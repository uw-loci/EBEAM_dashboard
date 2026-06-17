import queue
import struct
import threading
import time

from utils import LogLevel, tag_log_message

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

    ERROR_THRESHOLD = 5
    ERROR_LOG_INTERVAL = 10  # [seconds]

    # Raw Modbus/serial timing.
    SERIAL_READ_TIMEOUT = 0.02
    SERIAL_INTER_BYTE_TIMEOUT = 0.02
    WRITE_TIMEOUT = 1.0
    TRANSACTION_TIMEOUT = 0.75
    INTERFRAME_DELAY = 0.005
    RECONNECT_DELAY = 1.0
    BETWEEN_UNIT_DELAY = 0.1
    THREAD_JOIN_TIMEOUT = 2.0
    SERIAL_CLOSE_LOCK_TIMEOUT = 0.5

    # Error states
    DISCONNECTED = -1
    SENSOR_ERROR = -2

    UNIT_UNKNOWN = "unknown"
    UNIT_HEALTHY = "healthy"
    UNIT_DEGRADED = "degraded"
    UNIT_DISCONNECTED = "disconnected"

    def __init__(self, port, unit_numbers=(1, 2, 3, 4, 5), baudrate=9600, logger=None):
        """Initialize serial settings and start the background polling thread."""
        if serial is None:
            raise RuntimeError("pyserial is not installed. Install with: python -m pip install pyserial")

        self.port = port
        self.baudrate = baudrate
        self._serial = None
        self.unit_numbers = set(unit_numbers)
        self.modbus_lock = threading.Lock()
        self.logger = logger
        self._main_thread_id = threading.get_ident()
        self._background_log_queue = queue.SimpleQueue()

        self.temperature_readings = {unit: None for unit in self.unit_numbers}
        self.consecutive_error_counts = {unit: 0 for unit in self.unit_numbers}
        self.last_good_readings = {unit: None for unit in self.unit_numbers}
        self.consecutive_connection_errors = 0

        self.response_lock = threading.Lock()
        self._last_rate_limited_log_times = {}
        self._unit_states = {unit: self.UNIT_UNKNOWN for unit in self.unit_numbers}
        self._last_error_type_by_unit = {unit: None for unit in self.unit_numbers}
        self._last_status_by_unit = {unit: None for unit in self.unit_numbers}
        self._first_valid_reading_logged = set()
        self._local_echo_logged = False
        self._pmon_unavailable_since = None
        self._all_units_disconnected_logged = False
        self._has_connected_once = False
        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target=self.poll_all_units,
            name=f"DP16ProcessMonitor[{self.port}]",
            daemon=True,
        )
        self._thread.start()

    def _stop_requested(self) -> bool:
        return self._stop_event.is_set()

    def _sleep_or_stop(self, seconds: float) -> bool:
        """Sleep for up to seconds, returning True if shutdown was requested."""
        return self._stop_event.wait(seconds)

    def _unit_is_available(self, unit, caller: str) -> bool:
        if unit not in self.unit_numbers:
            self.log(f"DP16 {caller} was called with an invalid unit address", LogLevel.ERROR)
            return False
        return not self._stop_requested()

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

    def _validate_crc(self, response: bytes, context: str = "response"):
        received_crc = response[-2] | (response[-1] << 8)
        calculated_crc = self._modbus_crc16(response[:-2])
        if received_crc != calculated_crc:
            raise DP16ModbusError(
                f"CRC mismatch on {context}: received 0x{received_crc:04X}, "
                f"calculated 0x{calculated_crc:04X}, response={self._hex_bytes(response)}"
            )

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

    def _serial_is_open_unlocked(self) -> bool:
        return self._serial is not None and self._serial.is_open

    def _serial_is_open(self) -> bool:
        with self.modbus_lock:
            return self._serial_is_open_unlocked()

    def _mark_pmon_unavailable(self, current_time=None):
        if self._pmon_unavailable_since is None:
            self._pmon_unavailable_since = time.time() if current_time is None else current_time
            self._first_valid_reading_logged.clear()

    def _mark_pmon_available(self, current_time=None):
        if self._pmon_unavailable_since is not None and self._has_connected_once:
            if current_time is None:
                current_time = time.time()
            outage_seconds = max(0.0, current_time - self._pmon_unavailable_since)
            self.log(f"PMON reconnected after {outage_seconds:.1f}s", LogLevel.INFO)
        self._pmon_unavailable_since = None
        self._all_units_disconnected_logged = False
        self._has_connected_once = True

    def connect(self):
        """
        Establish a connection to the DP16 units.

        Returns:
            bool: True if at least one unit responds, False otherwise.
        """
        if self._stop_requested():
            return False

        with self.modbus_lock:
            try:
                if self._stop_requested():
                    return False

                if self._serial_is_open_unlocked():
                    self.log("Reusing existing PMON Modbus connection", LogLevel.DEBUG)
                else:
                    self.log(f"Attempting to connect PMON on port {self.port}", LogLevel.DEBUG)
                    self._local_echo_logged = False
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
                    if self._sleep_or_stop(0.2):
                        self._close_serial_unlocked()
                        return False
                    self._serial.reset_input_buffer()
                    self._serial.reset_output_buffer()

                # Check if any unit responds.
                working_unit_count = 0
                missing_units = []
                for unit in sorted(self.unit_numbers):
                    if self._stop_requested():
                        return False
                    try:
                        status_registers = self._read_holding_registers_unlocked(
                            unit=unit,
                            address=self.STATUS_REG,
                            count=1,
                        )
                    except Exception as exc:
                        missing_units.append(unit)
                        self._log_rate_limited(
                            ("connect_probe", unit),
                            f"DP16 Unit {unit} did not respond during connect probe: {exc}",
                            LogLevel.DEBUG,
                        )
                        continue

                    working_unit_count += 1
                    self.log(
                        f"DP16 Unit {unit} responded with status: {status_registers[0]}",
                        LogLevel.VERBOSE,
                    )

                total_units = len(self.unit_numbers)
                if working_unit_count:
                    if missing_units:
                        self.log(
                            f"Connected to {working_unit_count}/{total_units} DP16 units; "
                            f"missing units: {', '.join(str(unit) for unit in sorted(missing_units))}",
                            LogLevel.WARNING,
                        )
                    else:
                        self.log(
                            f"Connected to {working_unit_count}/{total_units} DP16 units",
                            LogLevel.INFO,
                        )
                    self._mark_pmon_available()
                    return True
                self._mark_pmon_unavailable()
                self._log_rate_limited(
                    ("connect", "no_units", self.port),
                    f"PMON unavailable on {self.port}: serial opened but no configured DP16 units responded",
                    LogLevel.ERROR,
                )
                return False

            except serial.SerialException as exc:
                self._mark_pmon_unavailable()
                self._log_rate_limited(
                    ("connect", "serial_error", self.port),
                    f"Serial error during DP16 connection: {exc}",
                    LogLevel.ERROR,
                    interval=5,
                )
                self._close_serial_unlocked()
                return False
            except Exception as exc:
                self._mark_pmon_unavailable()
                self.log(f"DP16 Error connecting: {exc}", LogLevel.ERROR)
                self._close_serial_unlocked()
                return False

    def _close_serial_unlocked(self):
        ser = self._serial
        self._serial = None
        if ser is None:
            return False

        try:
            ser.close()
        except Exception as exc:
            self.log(f"Error closing DP16 serial port: {exc}", LogLevel.WARNING)
        return True

    def _close_serial_threadsafe(self, timeout):
        acquired = self.modbus_lock.acquire(timeout=timeout)
        if not acquired:
            return None

        try:
            return self._close_serial_unlocked()
        finally:
            self.modbus_lock.release()

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

        while not self._stop_requested() and time.monotonic() < deadline:
            waiting = getattr(ser, "in_waiting", 0)
            remaining = max(1, max_possible_len - len(response))
            chunk = ser.read(max(1, min(remaining, waiting or 1)))
            if not chunk:
                if self._sleep_or_stop(0.001):
                    raise DP16ModbusError("Transaction stopped")
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

        if self._stop_requested():
            raise DP16ModbusError("Transaction stopped")

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
        if self._stop_requested():
            raise DP16ModbusError("Transaction stopped")

        try:
            ser.reset_input_buffer()
            ser.reset_output_buffer()

            # Modbus RTU requires a quiet interval between frames. At 9600 baud,
            # 5 ms is conservative and matches the standalone PMON smoke test.
            if self.INTERFRAME_DELAY > 0:
                if self._sleep_or_stop(self.INTERFRAME_DELAY):
                    raise DP16ModbusError("Transaction stopped")

            if self._stop_requested():
                raise DP16ModbusError("Transaction stopped")

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
            if not self._local_echo_logged:
                self.log("PMON local echo detected and stripped before parsing", LogLevel.DEBUG)
                self._local_echo_logged = True
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

        self._validate_crc(response)

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

        self._validate_crc(response, context="write response")

        if response[1] & 0x80:
            raise DP16ModbusError(f"Modbus write exception response: code 0x{response[2]:02X}")

        return True

    def get_reading_config(self, unit):
        """Get reading configuration format.

        Returns:
            int: 2 for FFF.F format, 3 for FFFF format, None on error.
        """
        if not self._unit_is_available(unit, "get_reading_config"):
            return None

        try:
            with self.modbus_lock:
                if self._stop_requested():
                    return None
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
        if not self._unit_is_available(unit, "set_decimal_config"):
            return False

        try:
            with self.modbus_lock:
                if self._stop_requested():
                    return False

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
            self.log(f"Error writing DP16 config for unit {unit}: {exc}", LogLevel.ERROR)
            return False

    def _mark_all_disconnected(self, reason=None, level=LogLevel.WARNING, log=False):
        with self.response_lock:
            for unit in self.unit_numbers:
                self.temperature_readings[unit] = self.DISCONNECTED
                self._unit_states[unit] = self.UNIT_DISCONNECTED

        if log and not self._all_units_disconnected_logged:
            message = "All DP16 units marked disconnected"
            if reason:
                message = f"{message}: {reason}"
            self.log(message, level)
            self._all_units_disconnected_logged = True

    def _log_rate_limited(self, key, message, level=LogLevel.ERROR, interval=None, current_time=None):
        if current_time is None:
            current_time = time.time()
        if interval is None:
            interval = self.ERROR_LOG_INTERVAL
        if not isinstance(key, tuple):
            key = (key,)
        last_log_time = self._last_rate_limited_log_times.get(key)
        if last_log_time is None or current_time - last_log_time >= interval:
            self.log(message, level)
            self._last_rate_limited_log_times[key] = current_time

    def _error_display_value_unlocked(self, unit):
        if self.consecutive_error_counts[unit] >= self.ERROR_THRESHOLD:
            return self.DISCONNECTED
        return (
            self.last_good_readings[unit]
            if self.last_good_readings[unit] is not None
            else self.SENSOR_ERROR
        )

    def poll_all_units(self):
        """Single polling loop with each unit independent."""
        while not self._stop_requested():
            current_time = time.time()
            try:
                # Check if client is still connected.
                if not self._serial_is_open():
                    self._mark_pmon_unavailable(current_time)
                    self.consecutive_connection_errors += 1
                    # Mark all disconnected if we exceed error threshold.
                    if self.consecutive_connection_errors >= self.ERROR_THRESHOLD:
                        self._mark_all_disconnected(
                            reason=(
                                f"{self.consecutive_connection_errors} consecutive PMON "
                                f"connection failures on {self.port}"
                            ),
                            level=LogLevel.ERROR,
                            log=True,
                        )

                    if self._stop_requested():
                        break

                    # Try to reconnect.
                    if not self.connect():
                        if self._stop_requested():
                            break
                        if self._sleep_or_stop(self.RECONNECT_DELAY):
                            break
                        continue

                # Poll each unit individually.
                for unit in sorted(self.unit_numbers):
                    if self._stop_requested():
                        break
                    try:
                        self._poll_single_unit(unit)
                        self.consecutive_connection_errors = 0
                        if self._sleep_or_stop(self.BETWEEN_UNIT_DELAY):
                            break
                    except Exception as exc:
                        if self._stop_requested():
                            break
                        self._handle_poll_error(unit, exc)

                if self._stop_requested():
                    break

                if self.consecutive_connection_errors == 0:
                    if self._sleep_or_stop(self.BASE_DELAY):
                        break

            except Exception as exc:
                if self._stop_requested():
                    break
                self.consecutive_connection_errors += 1
                current_time = time.time()
                self._mark_pmon_unavailable(current_time)
                self._log_rate_limited(
                    ("poll_loop", type(exc).__name__),
                    f"Polling error: {exc}",
                    current_time=current_time,
                )

    def _record_status(self, unit, status):
        previous_status = self._last_status_by_unit.get(unit)
        self._last_status_by_unit[unit] = status

        if previous_status == status:
            return

        if status != self.STATUS_RUNNING:
            if previous_status is None:
                self.log(
                    f"DP16 Unit {unit} status {status} differs from expected {self.STATUS_RUNNING}",
                    LogLevel.WARNING,
                )
            else:
                self.log(
                    f"DP16 Unit {unit} status changed: {previous_status} -> {status} "
                    f"(expected {self.STATUS_RUNNING})",
                    LogLevel.WARNING,
                )
        elif previous_status is not None and previous_status != self.STATUS_RUNNING:
            self.log(f"DP16 Unit {unit} status returned to RUNNING", LogLevel.INFO)

    def _record_successful_reading(self, unit, value):
        previous_error_count = self.consecutive_error_counts.get(unit, 0)
        previous_state = self._unit_states.get(unit, self.UNIT_UNKNOWN)

        self.consecutive_error_counts[unit] = 0
        self._unit_states[unit] = self.UNIT_HEALTHY
        self._last_error_type_by_unit[unit] = None
        self._all_units_disconnected_logged = False
        self._mark_pmon_available()

        if previous_error_count > 0:
            poll_word = "poll" if previous_error_count == 1 else "polls"
            self.log(
                f"DP16 Unit {unit} recovered after {previous_error_count} failed {poll_word}; "
                f"temperature={value:.1f} C",
                LogLevel.INFO,
            )
            self._first_valid_reading_logged.add(unit)
        elif previous_state == self.UNIT_DISCONNECTED:
            self.log(f"DP16 Unit {unit} recovered; temperature={value:.1f} C", LogLevel.INFO)
            self._first_valid_reading_logged.add(unit)
        elif unit not in self._first_valid_reading_logged:
            self.log(f"DP16 Unit {unit} first valid reading: {value:.1f} C", LogLevel.INFO)
            self._first_valid_reading_logged.add(unit)

    def _poll_single_unit(self, unit):
        """Poll a single unit atomically."""
        if self._stop_requested():
            return

        with self.modbus_lock:
            if self._stop_requested():
                return

            # Read status first.
            status_registers = self._read_holding_registers_unlocked(
                unit=unit,
                address=self.STATUS_REG,
                count=1,
            )
            status = status_registers[0]
            self._record_status(unit, status)

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

            # Update reading for GUI availability.
            with self.response_lock:
                self.temperature_readings[unit] = value
                self.last_good_readings[unit] = value
            self._record_successful_reading(unit, value)

    def _classify_poll_error(self, unit: int, exception: Exception):
        err_str = str(exception).lower()
        is_modbus_error = isinstance(exception, DP16ModbusError)

        if is_modbus_error:
            hard_port_error = any(
                text in err_str
                for text in ("port is closed", "could not open port", "serial port is not open")
            )
            connection_error = "failed to connect" in err_str or "connection" in err_str

            if hard_port_error:
                return "hard_port", f"Hard port failure on unit {unit}: {exception}", LogLevel.ERROR, True, True
            if connection_error:
                return "connection", f"Connection error on unit {unit}: {exception}", LogLevel.ERROR, True, False
            if "only local echo was received" in err_str:
                return (
                    "local_echo_only",
                    f"Only local echo from unit {unit}; no slave response followed",
                    LogLevel.WARNING,
                    False,
                    False,
                )
            if "timeout" in err_str or "no bytes received" in err_str:
                return "no_response", f"No PMON response from unit {unit}", LogLevel.DEBUG, False, False
            return "modbus_io", f"General Modbus IO error on unit {unit}: {exception}", LogLevel.ERROR, False, False

        if "zero reading" in err_str:
            return "zero_reading", f"Zero PMON reading on unit {unit}: {exception}", LogLevel.ERROR, False, False
        if "temperature out of range" in err_str:
            return (
                "temperature_out_of_range",
                f"Temperature out of range on unit {unit}: {exception}",
                LogLevel.WARNING,
                False,
                False,
            )
        return "invalid_reading", f"Invalid reading on unit {unit}: {exception}", LogLevel.ERROR, False, False

    def _handle_poll_error(self, unit: int, exception: Exception):
        """
        Increment consecutive error counts, log the error, and update
        self.temperature_readings based on the single ERROR_THRESHOLD logic.
        """
        self.log(f"Poll error on unit {unit}: {exception}", LogLevel.VERBOSE)
        previous_error_count = self.consecutive_error_counts[unit]
        previous_state = self._unit_states.get(unit, self.UNIT_UNKNOWN)
        previous_error_type = self._last_error_type_by_unit.get(unit)

        self.consecutive_error_counts[unit] += 1
        current_error_count = self.consecutive_error_counts[unit]

        error_type, message, level, counts_as_connection_error, should_close_serial = self._classify_poll_error(
            unit,
            exception,
        )
        new_state = (
            self.UNIT_DISCONNECTED
            if current_error_count >= self.ERROR_THRESHOLD
            else self.UNIT_DEGRADED
        )
        threshold_crossed = previous_error_count < self.ERROR_THRESHOLD <= current_error_count
        state_changed = previous_state != new_state
        error_type_changed = previous_error_type != error_type

        self._unit_states[unit] = new_state
        self._last_error_type_by_unit[unit] = error_type
        rate_limit_key = ("poll_error", unit, error_type)
        current_time = time.time()

        if should_close_serial:
            with self.modbus_lock:
                self._close_serial_unlocked()
        if counts_as_connection_error:
            self.consecutive_connection_errors += 1
            self._mark_pmon_unavailable()

        if threshold_crossed:
            self.log(
                f"DP16 Unit {unit} marked disconnected after {current_error_count} "
                f"consecutive errors: {message}",
                LogLevel.ERROR if level >= LogLevel.ERROR else LogLevel.WARNING,
            )
            self._last_rate_limited_log_times[rate_limit_key] = current_time
        elif state_changed and new_state == self.UNIT_DEGRADED:
            event_level = level if level >= LogLevel.ERROR else LogLevel.WARNING
            if self.last_good_readings[unit] is None:
                fallback_text = "showing SENSOR_ERROR until a valid reading is available"
            else:
                fallback_text = "holding last good reading"
            self.log(
                f"DP16 Unit {unit} degraded after poll failure; {fallback_text}: {message}",
                event_level,
            )
            self._last_rate_limited_log_times[rate_limit_key] = current_time
        elif error_type_changed:
            self.log(message, level)
            self._last_rate_limited_log_times[rate_limit_key] = current_time
        else:
            self._log_rate_limited(
                rate_limit_key,
                message,
                level,
                current_time=current_time,
            )

        with self.response_lock:
            self.temperature_readings[unit] = self._error_display_value_unlocked(unit)

    def get_all_temperatures(self):
        """Thread-safe access method."""
        self.flush_queued_logs()
        with self.response_lock:
            return dict(self.temperature_readings)

    def disconnect(self):
        """Stop polling and close the serial port without blocking indefinitely."""
        self._stop_event.set()
        self._mark_all_disconnected()

        close_before_join = self._close_serial_threadsafe(timeout=self.SERIAL_CLOSE_LOCK_TIMEOUT)

        thread = self._thread
        current_thread = threading.current_thread()
        if thread is not None and thread.is_alive() and current_thread is not thread:
            thread.join(timeout=self.THREAD_JOIN_TIMEOUT)
            if thread.is_alive():
                self.log(
                    "DP16 polling thread did not stop within timeout; serial transaction may be stuck",
                    LogLevel.WARNING,
                )

        close_after_join = self._close_serial_threadsafe(timeout=self.SERIAL_CLOSE_LOCK_TIMEOUT)

        if close_before_join is True or close_after_join is True:
            self.log("Disconnected from DP16 Process Monitors", LogLevel.INFO)
        elif close_before_join is None or close_after_join is None:
            self.log("Could not acquire DP16 Modbus lock while closing serial port", LogLevel.WARNING)
        else:
            self.log("No active connection to DP16 Process Monitors", LogLevel.INFO)

        self.flush_queued_logs()

    def close(self):
        """Compatibility alias for callers that use close() during shutdown."""
        self.disconnect()

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
        message = tag_log_message(message, "PMON")
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
