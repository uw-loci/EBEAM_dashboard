import serial
from utils import LogLevel
from serial import EIGHTBITS, PARITY_NONE, STOPBITS_ONE

class BeamEnergyDriver:
    def __init__(self, port="", baudrate=9600, timeout=0.5, logger=None):
        self.port = port or ""
        self.baudrate = baudrate
        self.timeout = timeout
        self.logger = logger
        self.ser = None
        if self.port:
            self._open()

    def _open(self):
        try:
            self.ser = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=EIGHTBITS,
                parity=PARITY_NONE,
                stopbits=STOPBITS_ONE,
                timeout=self.timeout
            )
            self.log(f"Serial connection established on {self.port}", LogLevel.INFO)
        except Exception as e:
            self.log(f"Error opening serial port {self.port}: {e}", LogLevel.ERROR)
            self.ser = None

    def update_port(self, new_port):
        if self.ser:
            try: self.ser.close()
            except: pass
            self.ser = None
        self.port = new_port or ""
        if self.port:
            self._open()

    def is_connected(self):
        return bool(self.ser and self.ser.is_open)

    def readline(self):
        """Return one decoded line or None."""
        if not self.is_connected():
            return None
        try:
            raw = self.ser.readline()
            return raw.decode(errors="ignore").strip() if raw else None
        except Exception as exc:
            self.log(f"Serial read error on {self.port}: {exc}", LogLevel.WARNING)
            return None


    def log(self, message, level=LogLevel.INFO):
        if self.logger:
            self.logger.log(message, level)
        else:
            print(f"{level.name}: {message}")
