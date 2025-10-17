import serial
import threading
import time
from utils import LogLevel

class GlassmanPowerSupply:
    MAX_RETRIES = 3
    BACKOFF_MAX_SECONDS = 5.0

    def __init__(self, port, power_supply_id, baudrate=9600, timeout=1, logger=None, debug_mode=False):
        """Driver for Arduino & power supply pair monitoring in knob box."""
        self.port = port
        self.power_supply_id = power_supply_id
        self.baudrate = baudrate
        self.timeout = timeout
        self.logger = logger
        self.debug_mode = debug_mode

        self.ser = None
        self.ps_connected = False
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.monitor_thread = None

        self.power_supply_data = {
            'output_status': None,
        }

        # self.setup_serial_connection()
        # self.start_monitoring()

    def setup_serial_connection(self):
        """Set up the serial connection to the power supply."""
        try:
            self.ser = serial.Serial(
                self.port, 
                self.baudrate, 
                timeout=self.timeout,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE
                )
            if self.ser:
                self.ser.reset_input_buffer()  # Clear any stale data
                self.ps_connected = True
                self.log(f"Connected to Glassman Power Supply on {self.port}", LogLevel.INFO)
            else:
                self.ps_connected = False
                self.log(f"Failed to connect to Glassman Power Supply on {self.port}", LogLevel.ERROR)
        except Exception as e:
            self.ser = None
            self.ps_connected = False
            self.log(f"Failed to connect to Glassman Power Supply on {self.port}: {e}", LogLevel.ERROR)

    def start_monitoring(self):
        """Start the background thread to monitor the power supply."""
        if self.monitor_thread and self.monitor_thread.is_alive():
            return  # Already running

        self.stop_event.clear()
        self.monitor_thread = threading.Thread(
            target=self.monitor_data_continuously,
            daemon=True
        )
        self.monitor_thread.start()

    
    def close(self):
        """Clean up resources."""
        self.stop_event.set()
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=2.0)
        if self.ser and self.ser.is_open:
            self.ser.close()
        self.ser = None
        self.ps_connected = False

    def write_command(self, cmd: str):
        """Write a command to the power supply."""
        payload = (cmd + "\r").encode('ascii')
        with self.lock:
            if not self.ps_connected:
                return False
            self.ser.write(payload)
            self.ser.flush() # Ensure command is sent
        return True

    def query_command(self, cmd: str, read_timeout_s = 0.5):
        """Send a command and read one line reply"""
        deadline = time.time() + read_timeout_s
        self.write_command(cmd)
        buffer = b"" # Initialize empty buffer

        # Loop reads line until timeout or data is received
        while time.time() < deadline:
            with self.lock:
                if not self.is_connected():
                    return None
                line = self.ser.readline()
            if line:
                buffer = line
                break
        
        text = buffer.decode('ascii').strip()
        if text:
            return text
        return None

    def monitor_data_continuously(self):
        """Continuously monitor the power supply for data."""
        consecutive_failures = 0
        backoff = min(0.5, self.BACKOFF_MAX_SECONDS)

        while not self.stop_event.is_set():
            try:
                if not self.is_connected():
                    # Attempt to reconnect
                    self.setup_serial_connection()
                    time.sleep(backoff)
                    continue

                # Read data from the power supply
                with self.lock:
                    line = self.ser.readline()
                
                if not line:
                    consecutive_failures += 1
                    if consecutive_failures >= self.MAX_RETRIES:
                        self.handle_disconnect("No data received")
                    continue  # No data received

                consecutive_failures = 0  # Reset on successful read

                data_str = line.decode('ascii').strip() # decode bytes to string - check ascii vs utf-8
                self.parse_data_and_update(data_str) # Parse data and  update shared data

            except (serial.SerialException, OSError) as e:
                self.handle_disconnect(e)
                time.sleep(backoff)
            except Exception as e:
                consecutive_failures += 1
                if consecutive_failures >= self.MAX_RETRIES:
                    self.handle_disconnect()
                time.sleep(backoff)  # wait before retrying or handle reconnection

    # TODO: Verify parsing with Glassman data format
    def parse_data_and_update(self, line):
        """
        Parse a line of data from the power supply.
        Expected format: TBD
        """
        pass
        
    def get_power_supply_data(self):
        """Get the latest power supply data."""
        with self.lock:
            return self.power_supply_data.copy()

    def update_com_port(self, new_port):
        """Update the COM port and re-establish the connection."""
        if self.ser is not None:
            self.ser.close()
            self.ser = None
        
        self.port = new_port
        self.setup_serial_connection()

    def is_connected(self):
        self.ps_connected = self.ser is not None and self.ser.is_open
        return self.ps_connected
    
    def handle_disconnect(self, msg=''):
        self.log(f"Disconnect: {msg}", err=True)
        self.ps_connected = False
        
        if self.ser and self.ser.is_open:
            self.ser.close()
        self.ser = None

    def log(self, message, level=LogLevel.INFO):
        if self.logger:
            self.logger.log(message, level)
        else:
            print(f"{level.name}: {message}")