import threading
import time

from pymodbus.client import ModbusSerialClient as ModbusClient
from utils import LogLevel  # Ensure this module is correctly implemented

# ============= MODBUS MAP =================================
"""Input Registers (Function Code 04)"""
IREG_HEALTH_ADDR = 0  # track health/error mode
IREG_V_SET_ADDR = 1  # integer volts
IREG_V_READ_ADDR = 2  # integer volts
IREG_I_READ_ADDR = 3  # integer microamps
IREG_3KV_RESET_COUNT_ADDR = 4   # count of reset events for 3kV Bertan

"""
Packed DINPUT words (also read with Function Code 04):
    5 = unlatched signals
    6 = latched flags
"""
DINPUT_UNLATCHED_SIGNALS_ADDR = 5
DINPUT_LATCHED_FLAGS_ADDR = 6

UNLATCHED_SIGNAL_MASK_HVENABLE        = 1 << 0
UNLATCHED_SIGNAL_MASK_RESET_STATE_1KV = 1 << 1
UNLATCHED_SIGNAL_MASK_ARM80KV_ENABLE  = 1 << 2
UNLATCHED_SIGNAL_MASK_CCSPOWER_ENABLE = 1 << 3
UNLATCHED_SIGNAL_MASK_ARMBEAMS_ENABLE = 1 << 4
UNLATCHED_SIGNAL_MASK_3KV_ENABLE      = 1 << 5
UNLATCHED_SIGNAL_MASK_NOMOP           = 1 << 6
UNLATCHED_SIGNAL_MASK_LOGIC_ALIVE     = 1 << 7

LATCHED_FLAG_MASK_3KV_TIMER       = 1 << 4
LATCHED_FLAG_MASK_ARMBEAMS_SWITCH = 1 << 5
LATCHED_FLAG_MASK_CCSPOWER_ALLOW  = 1 << 6
LATCHED_FLAG_MASK_ARM80KV_SWITCH  = 1 << 7
LATCHED_FLAG_MASK_1K_VCOMP        = 1 << 8
LATCHED_FLAG_MASK_1K_ICOMP        = 1 << 9
LATCHED_FLAG_MASK_NEG_1K_VCOMP    = 1 << 10
LATCHED_FLAG_MASK_NEG_1K_ICOMP    = 1 << 11
LATCHED_FLAG_MASK_20K_VCOMP       = 1 << 12
LATCHED_FLAG_MASK_20K_ICOMP       = 1 << 13
LATCHED_FLAG_MASK_3K_VCOMP        = 1 << 14
LATCHED_FLAG_MASK_3K_ICOMP        = 1 << 15

# As the Modbus map is updated, update these counts.
IREG_COUNT = 5
DINPUT_COUNT = 2
TOTAL_REG_COUNT = IREG_COUNT + DINPUT_COUNT
# ============= END MODBUS MAP =============================

DATA_TEMPLATE = {
    "health": 255,
    "set_voltage_V": 0.0,
    "actual_voltage_V": 0.0,
    "actual_current_mA": 0.0,
    "3kv_reset_count": 0,
    "hv_enable": 0,
    "arm_80kv": 0,
    "arm_beams": 0,
    "ccs_power": 0,
    "3kV_enable": 0,
    "timer_state_3kV": 0,
    "reset_state_1kV": 0,
    "nomop_flag": 0,
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
    "logic_alive": 0,
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
    #      - 1: +1kV Matsusada
    #      - 2: -1kV Matsusada
    #      - 3: +20kV Bertan
    #      - 4: +3kV Bertan
    UNIT_IDS = [1, 2, 3, 4]
    MAX_ATTEMPTS = 3  # Max attempts for reading data

    def __init__(
        self,
        port,
        baudrate=9600,
        timeout=0.5,
        parity="N",
        stopbits=1,
        bytesize=8,
        logger=None,
        debug_mode=True,
    ):
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
        self.modbus_lock = threading.Lock()  # Lock for Modbus communication
        self.data_lock = threading.Lock()  # Lock for data state updates
        self.poll_schedule_lock = threading.Lock()  # Lock for per-unit poll scheduling/backoff
        self.port = port
        self.connected = False
        self.last_success = {uid: 0 for uid in self.UNIT_IDS}  # Track last successful poll time for each unit
        self.CONNECTION_TIMEOUT = 10.0  # seconds without successful poll before considering connection lost
        self._connect_backoff_sec = 0.5  # time between connection attempts, will exponentially back off on failures up to a max
        self._connect_backoff_max_sec = 5.0  # backoff will max out at this duration between attempts
        self._next_connect_time = 0.0  # used for backoff timing of connection attempts
        self._poll_index = 0  # rotate unit polling order to avoid always lagging the same unit
        self._unit_poll_backoff_base_sec = 0.5  # per-unit backoff after poll failures
        self._unit_poll_backoff_max_sec = 5.0
        self._unit_poll_backoff_sec = {uid: 0.0 for uid in self.UNIT_IDS}
        self._next_unit_poll_time = {uid: 0.0 for uid in self.UNIT_IDS}

        # Create data dictionary for each unit in the list of UNIT_IDS
        self.data: dict[int, dict] = {uid: DATA_TEMPLATE.copy() for uid in self.UNIT_IDS}

        # Initialize Modbus client without 'method' parameter
        self.client = ModbusClient(
            port=port,
            baudrate=baudrate,
            parity=parity,
            stopbits=stopbits,
            bytesize=bytesize,
            timeout=timeout,
            retries=0  # avoid double-retry (manual retries handled in poll_one)
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
            except PermissionError as e:  # COMx access denied
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
            except Exception as e:  # general catch-all for errors
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

        # Rotate polling order to distribute latency across units
        if self.UNIT_IDS:
            start_index = self._poll_index % len(self.UNIT_IDS)
            unit_order = self.UNIT_IDS[start_index:] + self.UNIT_IDS[:start_index]
            self._poll_index = (start_index + 1) % len(self.UNIT_IDS)
        else:
            unit_order = []

        for uid in unit_order:
            now = time.time()
            with self.poll_schedule_lock:
                next_due = self._next_unit_poll_time.get(uid, 0.0)
            if now < next_due:
                continue
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
                    # Read the full packed input-register block:
                    # health, V set/read, I read, 3kV reset count, unlatched signals, latched flags
                    input_registers = self.client.read_input_registers(
                        address=IREG_HEALTH_ADDR,
                        count=TOTAL_REG_COUNT,
                        slave=unit_id
                    )
                if input_registers.isError():
                    raise RuntimeError(f"FC04 read failed or invalid response (unit {unit_id}): {input_registers}")

                if len(input_registers.registers) < TOTAL_REG_COUNT:
                    raise RuntimeError(f"FC04 read returned insufficient registers (unit {unit_id})")

                registers = input_registers.registers

                health = registers[IREG_HEALTH_ADDR]
                v_set = registers[IREG_V_SET_ADDR]
                v_read = registers[IREG_V_READ_ADDR]
                i_read = registers[IREG_I_READ_ADDR]
                reset_counter = registers[IREG_3KV_RESET_COUNT_ADDR]
                unlatched_signals = registers[DINPUT_UNLATCHED_SIGNALS_ADDR]
                flags = registers[DINPUT_LATCHED_FLAGS_ADDR]

                raw_hv_enable = int(bool(unlatched_signals & UNLATCHED_SIGNAL_MASK_HVENABLE))
                reset_state_1kV = int(bool(unlatched_signals & UNLATCHED_SIGNAL_MASK_RESET_STATE_1KV))
                arm_80kV = int(bool(unlatched_signals & UNLATCHED_SIGNAL_MASK_ARM80KV_ENABLE))
                ccs_power = int(bool(unlatched_signals & UNLATCHED_SIGNAL_MASK_CCSPOWER_ENABLE))
                arm_beams = int(bool(unlatched_signals & UNLATCHED_SIGNAL_MASK_ARMBEAMS_ENABLE))
                enable_3kV = int(bool(unlatched_signals & UNLATCHED_SIGNAL_MASK_3KV_ENABLE))
                nomop_flag = int(bool(unlatched_signals & UNLATCHED_SIGNAL_MASK_NOMOP))
                logic_alive_flag = int(bool(unlatched_signals & UNLATCHED_SIGNAL_MASK_LOGIC_ALIVE))

                hv_enable = enable_3kV if unit_id == 4 else raw_hv_enable

                timer_state_flag = int(bool(flags & LATCHED_FLAG_MASK_3KV_TIMER))
                armbeams_flag = int(bool(flags & LATCHED_FLAG_MASK_ARMBEAMS_SWITCH))
                ccspower_flag = int(bool(flags & LATCHED_FLAG_MASK_CCSPOWER_ALLOW))
                arm80kv_flag = int(bool(flags & LATCHED_FLAG_MASK_ARM80KV_SWITCH))
                vcomp_1k_flag = int(bool(flags & LATCHED_FLAG_MASK_1K_VCOMP))
                icomp_1k_flag = int(bool(flags & LATCHED_FLAG_MASK_1K_ICOMP))
                neg_vcomp_1k_flag = int(bool(flags & LATCHED_FLAG_MASK_NEG_1K_VCOMP))
                neg_icomp_1k_flag = int(bool(flags & LATCHED_FLAG_MASK_NEG_1K_ICOMP))
                vcomp_20k_flag = int(bool(flags & LATCHED_FLAG_MASK_20K_VCOMP))
                icomp_20k_flag = int(bool(flags & LATCHED_FLAG_MASK_20K_ICOMP))
                vcomp_3k_flag = int(bool(flags & LATCHED_FLAG_MASK_3K_VCOMP))
                icomp_3k_flag = int(bool(flags & LATCHED_FLAG_MASK_3K_ICOMP))

                new_data = {
                    "health": health,
                    "set_voltage_V": float(v_set),
                    "actual_voltage_V": float(v_read),
                    "actual_current_mA": float(i_read) / 1000.0,  # convert uA to mA
                    "3kv_reset_count": reset_counter,
                    "hv_enable": hv_enable,
                    "arm_80kV": arm_80kV,
                    "arm_beams": arm_beams,
                    "ccs_power": ccs_power,
                    "3kV_enable": enable_3kV,
                    "reset_state_1kV": reset_state_1kV,
                    "nomop_flag": nomop_flag,
                    "timer_state_3kV": timer_state_flag,
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
                with self.poll_schedule_lock:
                    self._unit_poll_backoff_sec[unit_id] = 0.0
                    self._next_unit_poll_time[unit_id] = 0.0
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
        with self.poll_schedule_lock:
            backoff = self._unit_poll_backoff_sec.get(unit_id, 0.0)
            if backoff <= 0.0:
                backoff = self._unit_poll_backoff_base_sec
            else:
                backoff = min(backoff * 2, self._unit_poll_backoff_max_sec)
            self._unit_poll_backoff_sec[unit_id] = backoff
            self._next_unit_poll_time[unit_id] = time.time() + backoff
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
            return any(
                (now - self.last_success.get(uid, 0)) < self.CONNECTION_TIMEOUT
                for uid in self.UNIT_IDS
            )

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
