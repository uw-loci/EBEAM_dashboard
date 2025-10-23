import threading
import time
from pymodbus.client import ModbusSerialClient as ModbusClient
from utils import LogLevel  # Ensure this module is correctly implemented

# ==== MODBUS MAP (update with firmware) =====
# Input Registers (Function Code 04)
IREG_MODE_ADDR        = 1   # 0=3kV Bertan, 1=20kV Bertan, 2=1kV Matsusada, 255=error
IREG_V_SET_ADDR       = 2   # integer volts
IREG_V_READ_ADDR      = 3   # integer volts
IREG_I_READ_ADDR      = 4   # integer milliamps

# Discrete Inputs (Function Code 02)
DINPUT_OVERCURRENT_ADDR = 0  # boolean 0/1

DATA_TEMPLATE = {
    "mode": 255,
    "set_voltage_V": 0.0,
    "actual_voltage_V": 0.0,
    "actual_current_mA": 0.0,
    "overcurrent": 0
}

class KnobBoxModbus:
    """
    Modbus RTU driver for multiple power supply monitoring via RS485.
    
    This class manages communication with multiple power supplies through a single
    RS485 connection using the Modbus RTU protocol. It provides thread-safe access
    to power supply data and handles connection management automatically.
    
    Attributes:
        OUTPUT_STATUS_ADDRESS (int): Register address for output status
        SET_VOLTAGE_ADDRESS (int): Register address for set voltage
        ACTUAL_VOLTAGE_ADDRESS (int): Register address for measured voltage
        ACTUAL_CURRENT_ADDRESS (int): Register address for measured current
        UNIT_NUMBERS (list): List of valid unit addresses
        MAX_ATTEMPTS (int): Maximum retry attempts for failed reads
    """
    UNIT_IDS = [1, 2, 3, 4, 5] # Unit numbers for each power supply
    MAX_ATTEMPTS = 3  # Max attempts for reading data

    def __init__(self, port, baudrate=9600, timeout=1, parity='E', stopbits=2, bytesize=8, logger=None, debug_mode=False):
        """
        Initialize the KnobBoxModbus instance with serial communication parameters and optional logging.
        
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
        self.modbus_lock = threading.Lock() # Lock for Modbus communication
        self.data_lock = threading.Lock()  # Lock for data state updates
        self.port = port
        self.connected = False

        # Create data dictionary for each unit in the list of UNIT_IDS
        self.data: dict[int, dict] = {uid: DATA_TEMPLATE.copy() for uid in self.UNIT_IDS} 

        # Initialize Modbus client without 'method' parameter
        self.client = ModbusClient(
            method='rtu', # Specify RTU method for serial communication
            port=port,
            baudrate=baudrate,
            parity=parity,
            stopbits=stopbits,
            bytesize=bytesize,
            timeout=timeout,
            retries=2
        )

    def connect(self):
        """
        Connect to the Modbus device. Opens the serial connection if not already open.
        
        Returns:
            bool: True if connected successfully, False otherwise.
        """
        with self.modbus_lock:
            try:
                if self.connected:
                    return True
                if self.client.connect():
                    self.connected = True
                    self.log(f"Knob Box Connected to port {self.port}.", LogLevel.INFO)
                    return True
                else:
                    self.log("Failed to connect to the Knob Box Modbus device.", LogLevel.ERROR)
                    return False
            except Exception as e:
                self.log(f"Error connecting to {self.port}: {str(e)}", LogLevel.ERROR)
                return False
            
    def disconnect(self):
        """Disconnect from the Modbus device."""
        with self.modbus_lock:
            try:
                if self.connected:
                    self.client.close()
                    self.connected = False
                    self.log("Disconnected from the Knob Box Modbus device.", LogLevel.INFO)
                else:
                    self.log("Client already disconnected from Knob Box Modbus device", LogLevel.INFO)
            except Exception as e:
                self.log(f"Error in disconnect: {str(e)}", LogLevel.ERROR)

    def poll_all(self):
        """
        Poll all power supplies and update self.data
        Returns copy of data dictionary
        """
        if not self.connect():
            raise RuntimeError("Unable to open Modbus serial port")
        for uid in self.UNIT_IDS:
            try:
                self.poll_one(uid)
            except Exception as e:
                self.log(f"[unit {uid}] poll error: {e}", LogLevel.ERROR)
        # Return a copy to avoid external mutation
        with self.data_lock:
            return self.data.copy()
    
    def poll_one(self, unit_id):
        """
        Poll a single power supply unit and update self.data.
        Parameters:
            unit_id (int): Unit ID of the power supply to poll.
        """
        with self.modbus_lock:
            # Read Input Registers containing MODE, V_SET, V_READ, I_READ
            # Continuous block starting at address 1 (count=4)
            input_registers = self.client.read_input_registers(address=IREG_MODE_ADDR, count=4, slave=unit_id)
            if input_registers is None or not getattr(input_registers, "registers"):
                raise RuntimeError(f"FC04 read failed or invalid response (unit {unit_id})")

            if len(input_registers.registers) < 4:
                raise RuntimeError(f"FC04 read returned insufficient registers (unit {unit_id})")
            
            mode, v_set, v_read, i_read = input_registers.registers
        
            # Read Discrete Input for Overcurrent status
            discrete_input = self.client.read_discrete_inputs(address=DINPUT_OVERCURRENT_ADDR, count=1, slave=unit_id)
            if discrete_input is None or not getattr(discrete_input, "bits"):
                raise RuntimeError(f"FC02 read failed or invalid response (unit {unit_id})")

            overcurrent = int(bool(discrete_input.bits[0])) if discrete_input.bits else 0

            new_data = {
                "mode": mode,
                "set_voltage_V": float(v_set),
                "actual_voltage_V": float(v_read),
                "actual_current_mA": float(i_read),
                "overcurrent": overcurrent
            }

            with self.data_lock:
                self.data[unit_id] = new_data
                self.log(f"[unit {unit_id}] polled data: {new_data}", LogLevel.DEBUG)

    def get_data_snapshot(self):
        """
        Get a snapshot of the current data for all power supplies.
        
        Returns:
            dict: A copy of the current data dictionary.
        """
        with self.data_lock:
            return self.data.copy()

    def check_connection(self):
        """Check if the Modbus client is connected and attempt to reconnect if not."""
        try:
            if not self.connected:
                self.log("Modbus client not connected. Attempting to reconnect...", LogLevel.WARNING)
                self.connect()
                return self.connected
        except Exception as e:
            self.log(f"Error checking connection: {str(e)}", LogLevel.ERROR)
            self.connected = False
            try:
                self.client.close()
            except Exception:
                pass
            self.connected = self.connect()
            return self.connected

    def log(self, message, level=LogLevel.INFO):
        if self.logger:
            self.logger.log(message, level)
        else:
            print(f"{level.name}: {message}")

# TODO: Implement retry logic for register reads