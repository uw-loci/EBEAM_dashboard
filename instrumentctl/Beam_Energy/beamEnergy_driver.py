import serial
import time
from utils import LogLevel

class BeamEnergy:
    def __init__(self, port, baudrate=9600, timeout=1.0, logger=None, debug_mode=False):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.logger = logger
        self.debug_mode = debug_mode
        self.stopbits = serial.STOPBITS_ONE
        self.bytesize = serial.EIGHTBITS
        self.parity = serial.PARITY_NONE
        self.ser = None
        self.setup_serial()

    def setup_serial(self):
        try:
            self.ser = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=self.bytesize,
                parity=self.parity,
                stopbits=self.stopbits,
                timeout=self.timeout
            )
            self.log(f"Serial connection established on {self.port}", LogLevel.INFO)
        except serial.SerialException as e:
            self.log(f"Error opening serial port {self.port}: {e}", LogLevel.ERROR)
            self.ser = None

    def update_com_port(self, new_port):
        self.log(f"Updating COM port from {self.port} to {new_port}", LogLevel.INFO)
        if self.ser:
            try: self.ser.close()
            finally: self.ser = None
        self.port = new_port
        self.setup_serial()

    def is_connected(self):
        return self.ser is not None and self.ser.is_open

    def flush_serial(self):
        if self.is_connected():
            self.log("Flushing serial input buffer for Beam Energy", LogLevel.DEBUG)
            self.ser.reset_input_buffer()
        else:
            self.log("Serial port for Beam Energy is not open. Cannot flush.", LogLevel.Warning)

    def read_stream(self):
        """
        Continuously read lines and log them (no parsing).
        If `command` is provided, it is sent before each read (for polling-style devices).
        Ctrl+C to stop.
        """
        if not self.is_connected():
            self.log("Serial port is not open. Cannot read stream.", LogLevel.ERROR)
            return

        try:
            raw = self.ser.readline()
            if not raw:
                continue

            line = raw.decode(errors="ignore").rstrip("\r\n")
            ts = time.strftime('%Y-%m-%d %H:%M:%S.%f')
            entry = f"[{ts}] {line}"

            self.log(entry, LogLevel.INFO)


        except KeyboardInterrupt:
            self.log("Stopped reading stream (KeyboardInterrupt).", LogLevel.INFO)
        except serial.SerialException as e:
            self.log(f"Serial error: {e}", LogLevel.ERROR)

    def log(self, message, level=LogLevel.INFO):
        if self.logger:
            self.logger.log(message, level)
        else:
            print(f"{level.name}: {message}")
