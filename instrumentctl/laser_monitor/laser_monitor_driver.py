from __future__ import annotations

import threading
import time

# Laser Monitor driver
#
# This driver talks to an Arduino Uno over USB serial. The Arduino drives the physical
# beam/laser indicator LEDs. The dashboard calls set_beams_on() and set_radiation_indicator().

try:
    import serial
except ImportError:  # pragma: no cover - handled at runtime with a clear error
    serial = None


# Serial timing and reconnect settings
BAUDRATE = 9600
POLL_INTERVAL_SECONDS = 0.5
SERIAL_TIMEOUT_SECONDS = 0.25
WRITE_TIMEOUT_SECONDS = 0.5
ARDUINO_BOOT_DELAY_SECONDS = 2.0
RECONNECT_BACKOFF_INITIAL_SECONDS = 0.5
RECONNECT_BACKOFF_MAX_SECONDS = 5.0
THREAD_JOIN_TIMEOUT_SECONDS = 2.0

# Line-delimited ASCII protocol:
#   Host -> Arduino:  PING
#   Arduino -> Host:  PONG
#   Host -> Arduino:  STATE beams=<0|1> radiation=<0|1>
#   Arduino -> Host:  OK
PING_COMMAND = "PING\n"
PONG_RESPONSE = "PONG"
STATE_OK_RESPONSE = "OK"
ENCODING = "ascii"


class LaserMonitorProtocolError(RuntimeError):
    """Raised when the Arduino returns an unexpected serial response."""


class LaserMonitorDriver:
    """
    USB-serial driver for the Arduino Laser Monitor indicator.

    The worker thread owns all serial I/O. Public setters only update desired
    state; the worker pushes the latest state to the Arduino after successful
    communication polling.
    """

    def __init__(self, port):
        if serial is None:
            raise RuntimeError(
                "pyserial is not installed. Install with: python -m pip install pyserial"
            )

        self.port = port
        self._serial = None

        # Locks split responsibility:
        # - serial lock: protects the pyserial object
        # - state lock: protects desired dashboard state
        # - status lock: protects connection/error status read by other threads
        self._serial_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._status_lock = threading.Lock()

        # Desired output state. These values are updated by public setters and
        # sent by the worker thread on every communication poll.
        self._beams_on = False
        self._radiation_indicator = False

        # Status state. These values are intentionally separate from desired
        # output state so callers can distinguish "what should be displayed"
        # from "is the Arduino currently reachable".
        self._connected = False
        self._last_error = None

        # One worker thread owns all serial I/O. This avoids direct serial
        # writes from Tk callbacks or future dashboard status handlers.
        self._stop_event = threading.Event()
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            name=f"LaserMonitorDriver[{self.port}]",
            daemon=True,
        )
        self._worker_thread.start()

    def set_beams_on(self, active: bool) -> None:
        """Update the desired beams-on state for the next worker-cycle send."""
        with self._state_lock:
            self._beams_on = bool(active)

    def set_radiation_indicator(self, active: bool) -> None:
        """Update the desired radiation-indicator state for the next worker-cycle send."""
        with self._state_lock:
            self._radiation_indicator = bool(active)

    def is_connected(self) -> bool:
        """Return True when the most recent poll exchange succeeded."""
        with self._status_lock:
            return self._connected

    def disconnect(self) -> None:
        """Set beams off, stop the worker thread, and close the serial connection."""
        with self._state_lock:
            radiation_indicator = self._radiation_indicator
            self._beams_on = False

        if self._serial_is_open():
            state = (False, radiation_indicator)
            try:
                command = self._build_state_command(*state)
                self._write_line_expect(command, STATE_OK_RESPONSE)
            except Exception as exc:
                self._record_error(exc)

        self._stop_event.set()
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=THREAD_JOIN_TIMEOUT_SECONDS)

        self._set_connected(False)
        self._close_serial()

    def close(self) -> None:
        """Compatibility alias for disconnect()."""
        self.disconnect()

    def close_com_ports(self) -> None:
        """Dashboard cleanup hook."""
        self.disconnect()

    @property
    def last_error(self):
        """Most recent connection/protocol error text, or None."""
        with self._status_lock:
            return self._last_error

    def _worker_loop(self) -> None:
        # Main lifecycle loop:
        # 1. Connect/reconnect if needed.
        # 2. Poll Arduino with the complete desired state every 500 ms.
        # A successful OK response both confirms link health and resynchronizes
        # outputs if the firmware watchdog changed them during a quiet period.
        reconnect_backoff = RECONNECT_BACKOFF_INITIAL_SECONDS
        next_reconnect_time = 0.0

        while not self._stop_requested():
            try:
                if not self._serial_is_open():
                    self._set_connected(False)

                    now = time.monotonic()
                    if now < next_reconnect_time:
                        wait_time = min(POLL_INTERVAL_SECONDS, next_reconnect_time - now)
                        self._sleep_or_stop(wait_time)
                        continue

                    if not self._connect():
                        next_reconnect_time = time.monotonic() + reconnect_backoff
                        reconnect_backoff = min(
                            reconnect_backoff * 2,
                            RECONNECT_BACKOFF_MAX_SECONDS,
                        )
                        continue

                    reconnect_backoff = RECONNECT_BACKOFF_INITIAL_SECONDS
                    next_reconnect_time = 0.0

                self._send_state()
                self._set_connected(True)

                self._sleep_or_stop(POLL_INTERVAL_SECONDS)

            except Exception as exc:
                self._record_error(exc)
                self._set_connected(False)
                self._close_serial()
                next_reconnect_time = time.monotonic() + reconnect_backoff
                reconnect_backoff = min(
                    reconnect_backoff * 2,
                    RECONNECT_BACKOFF_MAX_SECONDS,
                )

        self._set_connected(False)
        self._close_serial()

    def _connect(self) -> bool:
        # Opening an Arduino Uno USB serial port resets the board. Wait before
        # flushing buffers so setup() has time to start reading commands.
        self._close_serial()

        try:
            ser = serial.Serial(
                port=self.port,
                baudrate=BAUDRATE,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=SERIAL_TIMEOUT_SECONDS,
                write_timeout=WRITE_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            self._record_error(exc)
            return False

        with self._serial_lock:
            self._serial = ser

        if self._sleep_or_stop(ARDUINO_BOOT_DELAY_SECONDS):
            self._close_serial()
            return False

        try:
            with self._serial_lock:
                if self._serial is not ser or not ser.is_open:
                    return False
                ser.reset_input_buffer()
                ser.reset_output_buffer()
        except Exception as exc:
            self._record_error(exc)
            self._close_serial()
            return False

        with self._status_lock:
            self._last_error = None
        return True

    def _send_ping(self) -> None:
        self._write_line_expect(PING_COMMAND, PONG_RESPONSE)

    def _send_state(self) -> None:
        state = self._get_state()
        command = self._build_state_command(*state)
        self._write_line_expect(command, STATE_OK_RESPONSE)

    def _write_line_expect(self, command: str, expected_response: str) -> None:
        # Serial transactions are intentionally request/response. A missing or
        # unexpected response is treated as a lost connection and handled by the
        # worker reconnect loop.
        with self._serial_lock:
            ser = self._serial
            if ser is None or not ser.is_open:
                raise LaserMonitorProtocolError("Serial port is not open")

            ser.reset_input_buffer()
            ser.write(command.encode(ENCODING))
            ser.flush()

            response = ser.readline().decode(ENCODING, errors="replace").strip()

        if response != expected_response:
            raise LaserMonitorProtocolError(
                f"Expected {expected_response!r}, received {response!r}"
            )

    def _get_state(self):
        with self._state_lock:
            return self._beams_on, self._radiation_indicator

    @staticmethod
    def _build_state_command(beams_on: bool, radiation_indicator: bool) -> str:
        beams_value = 1 if beams_on else 0
        radiation_value = 1 if radiation_indicator else 0
        return f"STATE beams={beams_value} radiation={radiation_value}\n"

    def _serial_is_open(self) -> bool:
        with self._serial_lock:
            return self._serial is not None and self._serial.is_open

    def _close_serial(self) -> None:
        with self._serial_lock:
            ser = self._serial
            self._serial = None

        if ser is None:
            return

        try:
            ser.close()
        except Exception as exc:
            self._record_error(exc)

    def _set_connected(self, connected: bool) -> None:
        with self._status_lock:
            self._connected = connected

    def _record_error(self, exc) -> None:
        with self._status_lock:
            self._last_error = str(exc)

    def _stop_requested(self) -> bool:
        return self._stop_event.is_set()

    def _sleep_or_stop(self, seconds: float) -> bool:
        # Interruptible sleep: returns early when disconnect() requests shutdown.
        return self._stop_event.wait(max(0.0, seconds))
