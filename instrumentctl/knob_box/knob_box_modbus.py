import threading
import time
from pymodbus.client import ModbusSerialClient as ModbusClient
from utils import LogLevel  # Ensure this module is correctly implemented

#============= MODBUS MAP ==================================
#===========================================================
"""Input Registers (Function Code 04)"""
IREG_HEALTH_ADDR =          0   # track health/error mode
IREG_V_SET_ADDR =           1   # integer volts
IREG_V_READ_ADDR =          2   # integer volts
IREG_I_READ_ADDR =          3   # integer microamps
IREG_3KV_RESET_COUNT_ADDR = 4   # count of reset events for 3kV Bertan

"""Discrete Inputs (Function Code 02)"""
DINPUT_HVENABLE_ADDR =          5
# below are just reported by the matsusada monitoring arduinos
DINPUT_RESET_STATE_1KV_ADDR =   6
# below are just reported by the 3kV monitoring arduino
# (raw switch states)
DINPUT_ARM80KV_ADDR =           7
# (logic arduino outputs)
DINPUT_ARMBEAMS_ADDR =          8
DINPUT_CCSPOWER_ADDR =          9 
DINPUT_3KV_ENABLE_ADDR =        10
# (logic arduino flags)
DINPUT_NOMOP_FLAG_ADDR =        11
DINPUT_3K_HVENABLE_FLAG_ADDR =  12
DINPUT_ARMBEAMS_FLAG_ADDR =     13
DINPUT_CCSPOWER_FLAG_ADDR =     14
DINPUT_ARM80KV_FLAG_ADDR =      15
DINPUT_1K_VCOMP_FLAG_ADDR =     16
DINPUT_1K_ICOMP_FLAG_ADDR =     17
DINPUT_NEG_1K_VCOMP_FLAG_ADDR = 18
DINPUT_NEG_1K_ICOMP_FLAG_ADDR = 19
DINPUT_20K_VCOMP_FLAG_ADDR =    20
DINPUT_20K_ICOMP_FLAG_ADDR =    21
DINPUT_3K_VCOMP_FLAG_ADDR =     22
DINPUT_3K_ICOMP_FLAG_ADDR =     23 
DINPUT_LOGIC_ALIVE_ADDR =       24

# as the Modbus Map is updated, update these counts:
IREG_COUNT = 5
DINPUT_COUNT = 20
TOTAL_REG_COUNT = IREG_COUNT + DINPUT_COUNT
#===========================================================
#============= END MODBUS MAP ==============================

DATA_TEMPLATE = {
    "health": 255,
    "set_voltage_V": 0.0,
    "actual_voltage_V": 0.0,
    "actual_current_mA": 0.0,
    "hv_enable": 0,
    "arm_80kv": 0,
    "arm_beams": 0,
    "ccs_power": 0,
    "3kV_enable": 0,
    "reset_state_1kV": 0,
    "nomop_flag": 0,
    "hvenable_flag": 0,
    "armbeams_flag": 0,
    "ccspower_flag": 0,
    "arm80kv_flag": 0,
    "vcomp_1k_flag": 0,
    "icomp_1k_flag": 0,
    "neg_vcomp_1k_flag": 0,
    "neg_icomp_1k_flag": 0,
    "vcomp_20k_flag": 0,
    "icomp_20k_flag": 0,
    "vcomp_3k_flag": 0,
    "icomp_3k_flag": 0,
    "logic_alive": 0
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
    # Identifiers for power supplies:
    #      - 1: -1kV Matsusada
    #      - 2: +1kV Matsusada
    #      - 3: +20kV Bertan
    #      - 4: +3kV Bertan
    UNIT_IDS = [1,2,3,4] # for testing, just using one slave
    MAX_ATTEMPTS = 3  # Max attempts for reading data

    def __init__(self, port, baudrate=9600, timeout=1, parity='N', stopbits=1, bytesize=8, logger=None, debug_mode=True):
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
        self.last_success = {uid: 0 for uid in self.UNIT_IDS} # Track last successful poll time for each unit
        self.CONNECTION_TIMEOUT = 10.0 # seconds without successful poll before considering connection lost
        self._connect_backoff_sec = 0.5 # time between connection attempts, will exponentially back off on failures up to a max
        self._connect_backoff_max_sec = 5.0 # backoff will max out at this duration between attempts
        self._next_connect_time = 0.0 # used for backoff timing of connection attempts

        # Create data dictionary for each unit in the list of UNIT_IDS
        self.data: dict[int, dict] = {uid: DATA_TEMPLATE.copy() for uid in self.UNIT_IDS} 

        # Initialize Modbus client without 'method' parameter
        self.client = ModbusClient(
            #method='rtu', # Specify RTU method for serial communication
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
                now = time.time()
                if now < self._next_connect_time:
                    return False
                if self.client.connect():
                    self.connected = True
                    self._connect_backoff_sec = 0.5
                    self._next_connect_time = 0.0
                    self.log(f"Knob Box Connected to port {self.port}.", LogLevel.INFO)
                    return True
                else:
                    # Connection failed --> schedule next attempt with backoff
                    self.log("Failed to connect to the Knob Box Modbus device.", LogLevel.ERROR)
                    self._next_connect_time = now + self._connect_backoff_sec
                    # Exponential backoff for next connection attempt
                    self._connect_backoff_sec = min(self._connect_backoff_sec * 2, self._connect_backoff_max_sec)
                    return False
            except PermissionError as e: # COMx access denied
                self.connected = False
                try:
                    self.client.close()
                except Exception:
                    pass
                self.log(f"Permission error connecting to {self.port}: {str(e)}", LogLevel.ERROR)
                now = time.time()
                self._next_connect_time = now + self._connect_backoff_sec
                self._connect_backoff_sec = min(self._connect_backoff_sec * 2, self._connect_backoff_max_sec)
                return False
            except Exception as e: # general catch-all for errors
                self.connected = False
                self.log(f"Error connecting to {self.port}: {str(e)}", LogLevel.ERROR)
                now = time.time()
                self._next_connect_time = now + self._connect_backoff_sec
                self._connect_backoff_sec = min(self._connect_backoff_sec * 2, self._connect_backoff_max_sec)
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
            return {uid: values.copy() for uid, values in self.data.items()}
    
    def poll_one(self, unit_id):
        """
        Poll a single power supply unit and update self.data.
        Parameters:
            unit_id (int): Unit ID of the power supply to poll.
        """
        last_exception = None
        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            try:
                with self.modbus_lock:
                    # Read Input Registers containing HEALTH, V_SET, V_READ, I_READ, 3kv reset count, and flags
                    # Continuous block starting at address 1 (count=24)
                    input_registers = self.client.read_input_registers(address=IREG_HEALTH_ADDR, count=TOTAL_REG_COUNT, slave=unit_id)
                    if input_registers.isError():
                        raise RuntimeError(f"FC04 read failed or invalid response (unit {unit_id}): {input_registers}")

                    if len(input_registers.registers) < TOTAL_REG_COUNT:
                        raise RuntimeError(f"FC04 read returned insufficient registers (unit {unit_id})")
                    
                    health = input_registers.registers[IREG_HEALTH_ADDR]
                    v_set = input_registers.registers[IREG_V_SET_ADDR]
                    v_read = input_registers.registers[IREG_V_READ_ADDR]
                    i_read = input_registers.registers[IREG_I_READ_ADDR]
                    reset_counter = input_registers.registers[IREG_3KV_RESET_COUNT_ADDR]
                    
                    hv_enable = int(bool(input_registers.registers[DINPUT_HVENABLE_ADDR]))

                    arm_80kV = int(bool(input_registers.registers[DINPUT_ARM80KV_ADDR]))
                    arm_beams = not int(bool(input_registers.registers[DINPUT_ARMBEAMS_ADDR]))
                    ccs_power = not int(bool(input_registers.registers[DINPUT_CCSPOWER_ADDR]))
                    enable_3kV = not int(bool(input_registers.registers[DINPUT_3KV_ENABLE_ADDR]))

                    if (unit_id == 4 ):
                        hv_enable = enable_3kV # for the 3kV Bertan, hv enable comes from logic arduino output

                    reset_state_1kV = int(bool(input_registers.registers[DINPUT_RESET_STATE_1KV_ADDR]))

                    nomop_flag = int(bool(input_registers.registers[DINPUT_NOMOP_FLAG_ADDR]))
                    hvenable_flag = int(bool(input_registers.registers[DINPUT_3K_HVENABLE_FLAG_ADDR]))
                    armbeams_flag = int(bool(input_registers.registers[DINPUT_ARMBEAMS_FLAG_ADDR]))
                    ccspower_flag = int(bool(input_registers.registers[DINPUT_CCSPOWER_FLAG_ADDR]))
                    arm80kv_flag = int(bool(input_registers.registers[DINPUT_ARM80KV_FLAG_ADDR]))
                    vcomp_1k_flag = int(bool(input_registers.registers[DINPUT_1K_VCOMP_FLAG_ADDR]))
                    icomp_1k_flag = int(bool(input_registers.registers[DINPUT_1K_ICOMP_FLAG_ADDR]))
                    neg_vcomp_1k_flag = int(bool(input_registers.registers[DINPUT_NEG_1K_VCOMP_FLAG_ADDR]))
                    neg_icomp_1k_flag = int(bool(input_registers.registers[DINPUT_NEG_1K_ICOMP_FLAG_ADDR]))
                    vcomp_20k_flag = int(bool(input_registers.registers[DINPUT_20K_VCOMP_FLAG_ADDR]))
                    icomp_20k_flag = int(bool(input_registers.registers[DINPUT_20K_ICOMP_FLAG_ADDR]))
                    vcomp_3k_flag = int(bool(input_registers.registers[DINPUT_3K_VCOMP_FLAG_ADDR]))
                    icomp_3k_flag = int(bool(input_registers.registers[DINPUT_3K_ICOMP_FLAG_ADDR]))

                    logic_alive_flag = int(bool(input_registers.registers[DINPUT_LOGIC_ALIVE_ADDR]))

                    new_data = {
                        "health": health,
                        "set_voltage_V": float(v_set),
                        "actual_voltage_V": float(v_read),
                        "actual_current_mA": float(i_read) / 1000.0, # convert uA to mA    
                        "3kv_reset_count": reset_counter,
                        "hv_enable": hv_enable,
                        "arm_80kV": arm_80kV,
                        "arm_beams": arm_beams,
                        "ccs_power": ccs_power,
                        "3kV_enable": enable_3kV,
                        "reset_state_1kV": reset_state_1kV,
                        "nomop_flag": nomop_flag,
                        "hvenable_flag": hvenable_flag,
                        "armbeams_flag": armbeams_flag,
                        "ccspower_flag": ccspower_flag,
                        "arm80kv_flag": arm80kv_flag,
                        "vcomp_1k_flag": vcomp_1k_flag,
                        "icomp_1k_flag": icomp_1k_flag,
                        "neg_vcomp_1k_flag": neg_vcomp_1k_flag,
                        "neg_icomp_1k_flag": neg_icomp_1k_flag,
                        "vcomp_20k_flag": vcomp_20k_flag,
                        "icomp_20k_flag": icomp_20k_flag,
                        "vcomp_3k_flag": vcomp_3k_flag,
                        "icomp_3k_flag": icomp_3k_flag,
                        "logic_alive": logic_alive_flag
                    }

                    # Success - update data and return
                    with self.data_lock:
                        self.data[unit_id] = new_data
                        self.last_success[unit_id] = time.time()
                    # Keep UI-thread unsafe logger usage outside shared-state lock
                    # self.log(f"[unit {unit_id}] polled data: {new_data}", LogLevel.DEBUG)
                    return

            except Exception as e:
                last_exception = e
                if attempt < self.MAX_ATTEMPTS:
                    self.log(f"[unit {unit_id}] Retry attempt {attempt}/{self.MAX_ATTEMPTS}: {str(e)}", LogLevel.WARNING)
                    time.sleep(0.1)  # Short delay between retries
                else:
                    self.log(f"[unit {unit_id}] All {self.MAX_ATTEMPTS} retry attempts failed: {str(e)}", LogLevel.ERROR)
        
        # All retries exhausted, raise the last exception
        raise last_exception

    def get_data_snapshot(self):
        """
        Get a snapshot of the current data for all power supplies.
        
        Returns:
            dict: A copy of the current data dictionary.
        """
        with self.data_lock:
            return {uid: values.copy() for uid, values in self.data.items()}

    def close(self):
        """Compatibility alias used by subsystem shutdown/reconnect paths."""
        self.disconnect()
        
    def get_unit_connection_status(self, uid):
        now = time.time()
        with self.data_lock:
            last_ok = self.last_success.get(uid, 0)
        return (now - last_ok) < self.CONNECTION_TIMEOUT

    def any_unit_connected(self):
        now = time.time()
        with self.data_lock:
            return any((now - self.last_success.get(uid, 0)) < self.CONNECTION_TIMEOUT for uid in self.UNIT_IDS)

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
