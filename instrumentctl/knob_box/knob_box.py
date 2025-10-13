import serial
import threading
import time
from utils import LogLevel

class KnobBoxPowerSupply:
    MAX_RETRIES = 3

    def __init__(self, port, power_supply_id, baudrate=9600, timeout=1, logger=None, debug_mode=False):
        """Driver for Arduino & power supply pair monitoring in knob box."""
        self.port = port
        self.power_supply_id = power_supply_id
        self.baudrate = baudrate
        self.timeout = timeout
        self.logger = logger
        self.debug_mode = debug_mode

        self.ser = None

        self.lock = threading.Lock()
        self.stop_event = threading.Event()

        self.power_supply_data = {
            # 'output_status': None, ## ignore until added to firmware
            'set_voltage': None,
            'meas_voltage': None,
            'meas_current': None,
            'connected': False
        }

        self.setup_serial_connection()
        self.start_monitoring()

    def setup_serial_connection(self):
        """Set up the serial connection to the power supply."""
        try:
            self.ser = serial.Serial(self.port, self.baudrate, timeout=self.timeout)
            if self.ser:
                self.ser.reset_input_buffer()  # Clear any stale data
            self.power_supply_data['connected'] = True
            # self.log(f"Connected to Knob Box Power Supply on {self.port}", LogLevel.INFO)
        except Exception as e:
            # self.log(f"Failed to connect to Knob Box Power Supply on {self.port}: {e}", LogLevel.ERROR)
            self.ser = None

    def start_monitoring(self):
        """Start the background thread to monitor the power supply."""
        self.monitor_thread = threading.Thread(
            target=self.monitor_data_continuously,
            daemon=True
        )
        self.monitor_thread.start()

    def monitor_data_continuously(self):
        """Continuously monitor the power supply for data."""
        consecutive_failures = 0

        while not self.stop_event.is_set():
            try:
                if not self.is_connected():
                    # Attempt to reconnect
                    self.handle_disconnect()
                    self.setup_serial_connection()
                    continue

                if not self.ser.is_open:
                    raise serial.SerialException("Serial port is not open")
                
                # Read data from the power supply
                line =  self.ser.readline()
                if not line:
                    consecutive_failures += 1
                    if consecutive_failures >= self.MAX_RETRIES:
                        self.handle_disconnect()
                    continue  # No data received

                data_str = line.decode('ascii').strip() # decode bytes to string - check ascii vs utf-8
                data = self.parse_data(data_str) # Parse data and check for issues

                if data:
                    consecutive_failures = 0  # Reset on successful read
                    # Only hold lock while updating shared data
                    with self.lock:
                        # Update global data variable
                        self.power_supply_data.update({
                            # 'output_status': data['output_status'],
                            'set_voltage': data['set_voltage'],
                            'meas_voltage': data['meas_voltage'],
                            'meas_current': data['meas_current'],
                            'connected': True
                        })
                else:
                    consecutive_failures += 1
                    if consecutive_failures >= self.MAX_RETRIES:
                        self.handle_disconnect()

                # time.sleep(0.2)  # should match arduino display_value timer
            except (serial.SerialException, OSError) as se:
                self.handle_disconnect()
            except Exception as e:
                consecutive_failures += 1
                if consecutive_failures >= self.MAX_RETRIES:
                    self.handle_disconnect()
                time.sleep(1)  # wait before retrying or handle reconnection

    def parse_data(self, line):
        """
        Parse a line of data from the power supply.
        Expected format: set_voltage,measured_voltage,measured_current
        """
        try:    
                # Split line into values and convert to float
                line = line.strip()
                values = line.split(',')
                if len(values) != 3:
                    # self.log(f"Unexpected data format: {line}", LogLevel.ERROR)
                    return None
                
                try:
                    set_v = float(values[0]) if values[0] else 0.0
                    meas_v = float(values[1]) if values[1] else 0.0
                    meas_c = float(values[2]) if values[2] else 0.0

                    return {
                        'set_voltage': set_v,
                        'meas_voltage': meas_v,
                        'meas_current': meas_c
                    }
                except Exception as e:
                    # self.log(f"Error converting data to float: {e}", LogLevel.ERROR)
                    return None
        except ValueError as ve:
            # self.log(f"Failed to parse data: {line} - {ve}", LogLevel.ERROR)
            return None
        
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

        # if self.ser is not None:
        #     self.log(f"Updated COM port to {new_port}", LogLevel.INFO)
        # else:
        #     self.log(f"Failed to update COM port to {new_port}", LogLevel.ERROR)

    def handle_disconnect(self):
        """Handle disconnection and update data accordingly."""
        with self.lock:
            self.power_supply_data['connected'] = False
            self.power_supply_data['set_voltage'] = None
            self.power_supply_data['meas_voltage'] = None
            self.power_supply_data['meas_current'] = None
        if self.ser:
            self.ser.close()
            self.ser = None

    def is_connected(self):
        return self.ser is not None and self.ser.is_open
    
    def log(self, message, level=LogLevel.INFO):
        if self.logger:
            self.logger.log(message, level)
        else:
            print(f"{level.name}: {message}")

    def close(self):
        """Clean up resources."""
        self.stop_event.set()
        if self.monitor_thread.is_alive():
            self.monitor_thread.join()
        if self.ser is not None:
            self.ser.close()
            self.ser = None
        # self.log("Closed connection to Knob Box Power Supply", LogLevel.INFO)

# TODO: Add output status retrieval in KnobBoxPowerSupply and update_output_status method