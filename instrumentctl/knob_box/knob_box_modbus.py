import threading
import time
from pymodbus.client import ModbusSerialClient as ModbusClient
from utils import LogLevel  # Ensure this module is correctly implemented

#============= MODBUS MAP ==================================
#===========================================================
# Input Registers (Function Code 04)
IREG_HEALTH_ADDR =      0   # track health/error mode
IREG_V_SET_ADDR =       1   # integer volts
IREG_V_READ_ADDR =      2   # integer volts
IREG_I_READ_ADDR =      3   # integer microamps

# Discrete Inputs (Function Code 02)
DINPUT_HVENABLE_ADDR =          0
# below are just reported by the matsusada monitoring arduinos
DINPUT_RESET_STATE_ADDR =       1
# below are just reported by the 3kV monitoring arduino
# (logic arduino outputs)
DINPUT_ARMBEAMS_ADDR =          2
DINPUT_CCSPOWER_ADDR =          3
DINPUT_ARM80KV_ADDR =           4 
DINPUT_3KV_ENABLE_ADDR =        5
# (logic arduino flags)
DINPUT_NOMOP_FLAG_ADDR =        6
DINPUT_3K_HVENABLE_FLAG_ADDR =  7
DINPUT_ARMBEAMS_FLAG_ADDR =     8
DINPUT_CCSPOWER_FLAG_ADDR =     9
DINPUT_ARM80KV_FLAG_ADDR =      10
DINPUT_1K_VCOMP_FLAG_ADDR =     11
DINPUT_1K_ICOMP_FLAG_ADDR =     12
DINPUT_NEG_1K_VCOMP_FLAG_ADDR = 13
DINPUT_NEG_1K_ICOMP_FLAG_ADDR = 14
DINPUT_20K_VCOMP_FLAG_ADDR =    15
DINPUT_20K_ICOMP_FLAG_ADDR =    16
DINPUT_3K_VCOMP_FLAG_ADDR =     17
DINPUT_3K_ICOMP_FLAG_ADDR =     18

# as the Modbus Map is updated, update these counts:
IREG_COUNT = 4
DINPUT_COUNT = 19
#===========================================================
#============= END MODBUS MAP ==============================

DATA_TEMPLATE = {
    "health": 255,
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
    # Identifiers for power supplies:
    #      - 1: -1kV Matsusada
    #      - 2: +1kV Matsusada
    #      - 3: +20kV Bertan
    #      - 4: +3kV Bertan
    UNIT_IDS = [1, 2, 3, 4]
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
        last_exception = None
        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            try:
                with self.modbus_lock:
                    # Read Input Registers containing HEALTH, V_SET, V_READ, I_READ
                    # Continuous block starting at address 1 (count=4)
                    input_registers = self.client.read_input_registers(address=IREG_HEALTH_ADDR, count=IREG_COUNT, slave=unit_id)
                    if input_registers is None or not getattr(input_registers, "registers"):
                        raise RuntimeError(f"FC04 read failed or invalid response (unit {unit_id})")

                    if len(input_registers.registers) < 4:
                        raise RuntimeError(f"FC04 read returned insufficient registers (unit {unit_id})")
                    
                    health, v_set, v_read, i_read = input_registers.registers
                
                    # Read Discrete Input for Overcurrent status
                    discrete_input = self.client.read_discrete_inputs(address=DINPUT_HVENABLE_ADDR, count=DINPUT_COUNT, slave=unit_id)
                    if discrete_input is None or not getattr(discrete_input, "bits"):
                        raise RuntimeError(f"FC02 read failed or invalid response (unit {unit_id})")
                    
                    # 3kV Bertan must report 16 bits
                    if len(discrete_input.bits) < 18:
                        raise RuntimeError(f"FC02 read returned insufficient bits (unit {unit_id})")
                    
                    hv_enable = int(bool(discrete_input.bits[DINPUT_HVENABLE_ADDR]))
                    arm_beams = int(bool(discrete_input.bits[DINPUT_ARMBEAMS_ADDR]))
                    ccs_power = int(bool(discrete_input.bits[DINPUT_CCSPOWER_ADDR]))
                    arm_80kv = int(bool(discrete_input.bits[DINPUT_ARM80KV_ADDR]))

                    reset_state = int(bool(discrete_input.bits[DINPUT_RESET_STATE_ADDR]))

                    nomop_flag = int(bool(discrete_input.bits[DINPUT_NOMOP_FLAG_ADDR]))
                    hvenable_flag = int(bool(discrete_input.bits[DINPUT_3K_HVENABLE_FLAG_ADDR]))
                    armbeams_flag = int(bool(discrete_input.bits[DINPUT_ARMBEAMS_FLAG_ADDR]))
                    ccspower_flag = int(bool(discrete_input.bits[DINPUT_CCSPOWER_FLAG_ADDR]))
                    arm80kv_flag = int(bool(discrete_input.bits[DINPUT_ARM80KV_FLAG_ADDR]))
                    vcomp_1k_flag = int(bool(discrete_input.bits[DINPUT_1K_VCOMP_FLAG_ADDR]))
                    icomp_1k_flag = int(bool(discrete_input.bits[DINPUT_1K_ICOMP_FLAG_ADDR]))
                    neg_vcomp_1k_flag = int(bool(discrete_input.bits[DINPUT_NEG_1K_VCOMP_FLAG_ADDR]))
                    neg_icomp_1k_flag = int(bool(discrete_input.bits[DINPUT_NEG_1K_ICOMP_FLAG_ADDR]))
                    vcomp_20k_flag = int(bool(discrete_input.bits[DINPUT_20K_VCOMP_FLAG_ADDR]))
                    icomp_20k_flag = int(bool(discrete_input.bits[DINPUT_20K_ICOMP_FLAG_ADDR]))
                    vcomp_3k_flag = int(bool(discrete_input.bits[DINPUT_3K_VCOMP_FLAG_ADDR]))
                    icomp_3k_flag = int(bool(discrete_input.bits[DINPUT_3K_ICOMP_FLAG_ADDR]))

                    new_data = {
                        "health": health,
                        "set_voltage_V": float(v_set),
                        "actual_voltage_V": float(v_read),
                        "actual_current_mA": float(i_read),
                        "hv_enable": hv_enable,
                        "arm_beams": arm_beams,
                        "ccs_power": ccs_power,
                        "arm_80kv": arm_80kv,
                        "reset_state": reset_state,
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
                        "icomp_3k_flag": icomp_3k_flag
                    }

                    # Success - update data and return
                    with self.data_lock:
                        self.data[unit_id] = new_data
                        self.log(f"[unit {unit_id}] polled data: {new_data}", LogLevel.DEBUG)
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

# TODO: Figure out how output status will be recorded and stored in firmware