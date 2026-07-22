"""Threaded serial driver for an MKS 902B connected through a 900USB."""

import math
import queue
import re
import threading
import time

import serial

from utils import LogLevel


BAUDRATE = 115200
SERIAL_READ_TIMEOUT_MS = 10
SERIAL_WRITE_TIMEOUT_MS = 100
RESPONSE_TIMEOUT_MS = 100
POLL_INTERVAL_SECONDS = 0.5
POLL_RETRY_DELAY_SECONDS = 0.02
POLL_ATTEMPTS = 3
COMMUNICATION_LOSS_SECONDS = 5.0
RECONNECT_INTERVAL_SECONDS = 5.0
THREAD_JOIN_TIMEOUT_MS = 2000
DATA_QUEUE_MAXSIZE = 8
LOG_QUEUE_MAXSIZE = 1000
FRAME_TERMINATOR = b";FF"
SUPPORTED_BAUD_RATES = {4800, 9600, 19200, 38400, 57600, 115200, 230400}

# Discover the model and responding device address using the reply-enabled broadcast address.
COMMAND_MODEL_QUERY = "@254MD?;FF"
# Read the transducer-side communication baud rate.
COMMAND_BAUD_QUERY = "@{address:03d}BR?;FF"
# Read the pressure unit currently configured on the transducer.
COMMAND_UNIT_QUERY = "@{address:03d}U?;FF"
# Read absolute Piezo pressure in scientific notation.
COMMAND_PRESSURE_QUERY = "@{address:03d}PR4?;FF"

UNIT_TO_MBAR = {
    "MBAR": 1.0,
    "TORR": 1.333223684,
    "PASCAL": 0.01,
}
MIN_PRESSURE_MBAR = 0.1 * UNIT_TO_MBAR["TORR"]
MAX_PRESSURE_MBAR = 1000.0 * UNIT_TO_MBAR["TORR"]

_RESPONSE_RE = re.compile(r"^@(\d{3})(ACK|NAK)(.*);FF$")
_SCIENTIFIC_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)[Ee][+-]?\d+$")


class MKS902BError(Exception):
    """Base error raised by the MKS 902B driver."""


class MKS902BProtocolError(MKS902BError):
    """Raised when a response violates the MKS 902B protocol."""


class MKS902BTimeoutError(MKS902BError):
    """Raised when a complete response does not arrive before the deadline."""


def parse_response(frame):
    """Return the address, response type, and payload from one 902B frame."""
    match = _RESPONSE_RE.fullmatch(frame)
    if match is None:
        raise MKS902BProtocolError(f"Malformed response: {frame!r}")
    return int(match.group(1)), match.group(2), match.group(3)


def convert_pressure_to_mbar(pressure, unit):
    """Convert a documented 902B pressure unit to mbar."""
    try:
        conversion_factor = UNIT_TO_MBAR[unit]
    except KeyError as exc:
        raise MKS902BProtocolError(f"Unsupported pressure unit: {unit!r}") from exc

    pressure_mbar = pressure * conversion_factor
    if not math.isfinite(pressure_mbar):
        raise MKS902BProtocolError("Pressure is not finite")
    if not MIN_PRESSURE_MBAR <= pressure_mbar <= MAX_PRESSURE_MBAR:
        raise MKS902BProtocolError(
            f"Pressure {pressure_mbar:.6g} mbar is outside the 902B measurement range"
        )
    return pressure_mbar


class MKS902BDriver:
    """Own the 902B serial connection and publish valid mbar measurements."""

    def __init__(self, port, logger=None):
        """Prepare a stopped driver for the selected 900USB COM port."""
        self.port = str(port)
        self.logger = logger
        self.data_queue = queue.Queue(maxsize=DATA_QUEUE_MAXSIZE)
        self._log_queue = queue.Queue(maxsize=LOG_QUEUE_MAXSIZE)
        self._stop_event = threading.Event()
        self._thread = None
        self._serial = None
        self._receive_buffer = bytearray()
        self._address = None
        self._pressure_unit = None
        self._main_thread_id = threading.get_ident()
        self._dropped_log_count = 0
        self._dropped_log_lock = threading.Lock()
        self._has_connected = False

    def start(self):
        """Start the sole serial-owner worker if it is not already running."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._worker_loop,
            name="MKS902BWorker",
            daemon=True,
        )
        self._thread.start()

    def close(self):
        """Request worker shutdown and wait briefly without touching the serial port."""
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=THREAD_JOIN_TIMEOUT_MS / 1000.0)
        if self._thread is not None and self._thread.is_alive():
            self._queue_log("902B worker did not stop before the join timeout", LogLevel.ERROR)

    def flush_queued_logs(self, max_messages=200):
        """Forward queued worker logs through the shared logger on the main thread."""
        if self.logger is None or threading.get_ident() != self._main_thread_id:
            return

        with self._dropped_log_lock:
            dropped_count = self._dropped_log_count
            self._dropped_log_count = 0
        if dropped_count:
            self.logger.log(
                f"Dropped {dropped_count} queued 902B log message(s) because the queue was full",
                LogLevel.WARNING,
                tag="902B",
            )

        for _ in range(max_messages):
            try:
                message, level = self._log_queue.get_nowait()
            except queue.Empty:
                break
            self.logger.log(message, level, tag="902B")

    def _worker_loop(self):
        """Connect, initialize, poll, and reconnect until shutdown is requested."""
        self._queue_log(f"902B worker started for {self.port}", LogLevel.INFO)
        try:
            while not self._stop_event.is_set():
                initialized = False
                try:
                    initialized = self._connect_and_initialize()
                    if initialized:
                        self._poll_until_communication_loss()
                except Exception as exc:
                    self._queue_log(
                        f"Unexpected 902B communication failure: {type(exc).__name__}: {exc}",
                        LogLevel.ERROR,
                    )
                finally:
                    self._close_serial()

                if self._stop_event.is_set():
                    break
                if initialized:
                    self._queue_log(
                        f"902B disconnected; retrying {self.port} in {RECONNECT_INTERVAL_SECONDS:g} seconds",
                        LogLevel.ERROR,
                    )
                if self._stop_event.wait(RECONNECT_INTERVAL_SECONDS):
                    break
        finally:
            self._close_serial()
            self._queue_log("902B worker stopped", LogLevel.INFO)

    def _connect_and_initialize(self):
        """Open the port and complete all read-only initialization queries."""
        try:
            self._serial = serial.Serial(
                port=self.port,
                baudrate=BAUDRATE,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=SERIAL_READ_TIMEOUT_MS / 1000.0,
                write_timeout=SERIAL_WRITE_TIMEOUT_MS / 1000.0,
                xonxoff=False,
                rtscts=False,
                dsrdtr=False,
            )
            self._receive_buffer.clear()
            self._address = None
            self._pressure_unit = None
            self._queue_log(f"Opened 902B serial connection on {self.port}", LogLevel.INFO)
            self._initialize_transducer()
        except Exception as exc:
            self._queue_log(
                f"Failed to initialize 902B on {self.port}: {type(exc).__name__}: {exc}",
                LogLevel.ERROR,
            )
            return False

        connection_message = "Reconnected to" if self._has_connected else "Connected to"
        self._has_connected = True
        self._queue_log(
            f"{connection_message} 902B at address {self._address:03d} on {self.port}",
            LogLevel.INFO,
        )
        return True

    def _initialize_transducer(self):
        """Discover the transducer and read its baud rate and pressure unit."""
        model_address, model = self._request(COMMAND_MODEL_QUERY, expected_address=None)
        if model != "902B" or not 1 <= model_address <= 253:
            raise MKS902BProtocolError(
                f"Expected a 902B at address 001-253, received address {model_address:03d} model {model!r}"
            )
        self._address = model_address
        self._queue_log(
            f"Detected 902B model at address {self._address:03d}",
            LogLevel.INFO,
        )

        _, baud_payload = self._request(
            COMMAND_BAUD_QUERY.format(address=self._address),
            expected_address=self._address,
        )
        try:
            transducer_baud = int(baud_payload)
        except ValueError as exc:
            raise MKS902BProtocolError(f"Invalid baud-rate response: {baud_payload!r}") from exc
        if transducer_baud not in SUPPORTED_BAUD_RATES:
            raise MKS902BProtocolError(f"Unsupported transducer baud rate: {transducer_baud}")
        self._queue_log(
            f"902B transducer-side baud rate: {transducer_baud}",
            LogLevel.INFO,
        )
        if transducer_baud > 19200:
            self._queue_log(
                f"902B transducer-side baud rate {transducer_baud} exceeds the known reliable 900USB range",
                LogLevel.WARNING,
            )

        _, unit_payload = self._request(
            COMMAND_UNIT_QUERY.format(address=self._address),
            expected_address=self._address,
        )
        pressure_unit = unit_payload.upper()
        if pressure_unit not in UNIT_TO_MBAR:
            raise MKS902BProtocolError(f"Unsupported pressure unit: {unit_payload!r}")
        self._pressure_unit = pressure_unit
        if pressure_unit == "MBAR":
            unit_message = "902B pressure unit: MBAR"
        else:
            unit_message = (
                f"902B pressure unit: {pressure_unit}; dashboard will convert "
                f"{pressure_unit} to mbar"
            )
        self._queue_log(unit_message, LogLevel.INFO)
        self._queue_log("902B initialization complete", LogLevel.INFO)

    def _poll_until_communication_loss(self):
        """Poll on a 500 ms start-to-start schedule until five seconds are lost."""
        last_success = time.monotonic()
        next_poll = last_success

        while not self._stop_event.is_set():
            now = time.monotonic()
            if now < next_poll and self._stop_event.wait(next_poll - now):
                return

            if self._poll_pressure():
                last_success = time.monotonic()
            elif time.monotonic() - last_success >= COMMUNICATION_LOSS_SECONDS:
                self._queue_log(
                    f"No valid 902B pressure response for {COMMUNICATION_LOSS_SECONDS:g} seconds",
                    LogLevel.ERROR,
                )
                return

            next_poll += POLL_INTERVAL_SECONDS
            now = time.monotonic()
            if next_poll <= now:
                missed_intervals = math.floor((now - next_poll) / POLL_INTERVAL_SECONDS) + 1
                next_poll += missed_intervals * POLL_INTERVAL_SECONDS

    def _poll_pressure(self):
        """Try one PR4 polling group and publish a valid converted measurement."""
        command = COMMAND_PRESSURE_QUERY.format(address=self._address)
        for attempt in range(1, POLL_ATTEMPTS + 1):
            try:
                _, payload = self._request(command, expected_address=self._address)
                if _SCIENTIFIC_RE.fullmatch(payload) is None:
                    raise MKS902BProtocolError(
                        f"PR4 did not return scientific notation: {payload!r}"
                    )
                pressure_mbar = convert_pressure_to_mbar(float(payload), self._pressure_unit)
                self._put_latest_data((time.time(), pressure_mbar))
                return True
            except (MKS902BError, OSError, serial.SerialException) as exc:
                self._queue_log(
                    f"PR4 attempt {attempt}/{POLL_ATTEMPTS} failed: {type(exc).__name__}: {exc}",
                    LogLevel.DEBUG,
                )
                if attempt < POLL_ATTEMPTS and self._stop_event.wait(POLL_RETRY_DELAY_SECONDS):
                    return False

        if not self._stop_event.is_set():
            self._queue_log(
                f"PR4 pressure request failed after {POLL_ATTEMPTS} attempts",
                LogLevel.ERROR,
            )
        return False

    def _request(self, command, expected_address):
        """Send one command and return the matching ACK address and payload."""
        if self._serial is None or not self._serial.is_open:
            raise MKS902BProtocolError("Serial port is not open")

        wire_command = f"{command}\r\n"
        self._queue_log(f"TX {self._safe_log_text(wire_command)}", LogLevel.VERBOSE)
        self._serial.write(wire_command.encode("ascii"))
        self._serial.flush()

        deadline = time.monotonic() + RESPONSE_TIMEOUT_MS / 1000.0
        last_unexpected = None
        while not self._stop_event.is_set():
            frame = self._read_frame(deadline)
            self._queue_log(f"RX {self._safe_log_text(frame)}", LogLevel.VERBOSE)
            try:
                address, response_type, payload = parse_response(frame)
            except MKS902BProtocolError as exc:
                last_unexpected = str(exc)
                self._queue_log(last_unexpected, LogLevel.DEBUG)
                continue

            if expected_address is not None and address != expected_address:
                last_unexpected = (
                    f"Expected response from address {expected_address:03d}, received {address:03d}"
                )
                self._queue_log(last_unexpected, LogLevel.DEBUG)
                continue
            if response_type == "NAK":
                raise MKS902BProtocolError(f"902B returned NAK {payload}")
            return address, payload

        if last_unexpected is not None:
            raise MKS902BProtocolError(last_unexpected)
        raise MKS902BTimeoutError("Request stopped before a response was received")

    def _read_frame(self, deadline):
        """Read and return one ASCII frame terminated by the literal ;FF sequence."""
        while not self._stop_event.is_set():
            frame_bytes = self._extract_frame()
            if frame_bytes is not None:
                try:
                    return frame_bytes.decode("ascii")
                except UnicodeDecodeError as exc:
                    raise MKS902BProtocolError("Response contained non-ASCII data") from exc

            if time.monotonic() >= deadline:
                raise MKS902BTimeoutError(
                    f"Timed out after {RESPONSE_TIMEOUT_MS:g} ms waiting for ;FF"
                )

            bytes_waiting = self._serial.in_waiting
            chunk = self._serial.read(max(1, bytes_waiting))
            if chunk:
                self._receive_buffer.extend(chunk)

        raise MKS902BTimeoutError("Request stopped before a response was received")

    def _extract_frame(self):
        """Remove and return the next complete frame from the receive buffer."""
        terminator_index = self._receive_buffer.find(FRAME_TERMINATOR)
        if terminator_index < 0:
            return None

        frame_end = terminator_index + len(FRAME_TERMINATOR)
        candidate = bytes(self._receive_buffer[:frame_end])
        del self._receive_buffer[:frame_end]

        frame_start = candidate.find(b"@")
        if frame_start < 0:
            return candidate.strip()
        return candidate[frame_start:].strip()

    def _put_latest_data(self, measurement):
        """Publish a measurement without allowing stale data to block the worker."""
        try:
            self.data_queue.put_nowait(measurement)
            return
        except queue.Full:
            pass

        try:
            self.data_queue.get_nowait()
        except queue.Empty:
            pass
        self.data_queue.put_nowait(measurement)

    def _queue_log(self, message, level):
        """Queue a log without blocking serial communication."""
        try:
            self._log_queue.put_nowait((message, level))
            return
        except queue.Full:
            pass

        try:
            self._log_queue.get_nowait()
        except queue.Empty:
            pass
        else:
            with self._dropped_log_lock:
                self._dropped_log_count += 1

        try:
            self._log_queue.put_nowait((message, level))
        except queue.Full:
            with self._dropped_log_lock:
                self._dropped_log_count += 1

    def _close_serial(self):
        """Close and discard the worker-owned serial connection."""
        serial_connection = self._serial
        self._serial = None
        self._receive_buffer.clear()
        self._address = None
        self._pressure_unit = None
        if serial_connection is None:
            return
        try:
            serial_connection.close()
        except Exception as exc:
            self._queue_log(
                f"Failed to close 902B serial connection: {type(exc).__name__}: {exc}",
                LogLevel.ERROR,
            )

    @staticmethod
    def _safe_log_text(value):
        """Escape control and non-ASCII characters for one-line serial logs."""
        return str(value).encode("unicode_escape", "backslashreplace").decode("ascii")
