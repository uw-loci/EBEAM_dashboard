import threading
import time

from pymodbus.client import ModbusSerialClient as ModbusClient
from utils import LogLevel  # Ensure this module is correctly implemented

# ============= MODBUS MAP =================================
"""Input Registers (Function Code 04)"""
IREG_V_SET_ADDR = 0  # integer volts
IREG_V_READ_ADDR = 1  # integer volts
IREG_I_READ_ADDR = 2  # integer microamps
IREG_3KV_RESET_COUNT_ADDR = 3   # count of reset events for 3kV Bertan

"""
Packed DINPUT words (also read with Function Code 04):
    4 = unlatched signals
    5 = latched flags
"""
DINPUT_UNLATCHED_SIGNALS_ADDR = 4
DINPUT_LATCHED_FLAGS_ADDR = 5

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
IREG_COUNT = 4
DINPUT_COUNT = 2
TOTAL_REG_COUNT = IREG_COUNT + DINPUT_COUNT
# ============= END MODBUS MAP =============================

DATA_TEMPLATE = {
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
    MAX_ATTEMPTS = 5  # Max attempts for reading data

    def __init__(
        self,
        port,
        baudrate=9600,
        timeout=0.5,
        parity="N",
        stopbits=1,
        bytesize=8,
        logger=None,
        debug_mode=False,
    ):
        """
        Initialize the KnobBoxModbus instance with serial communication parameters and optional logging.

        Parameters:
            port (str): Serial port to connect.
            baudrate (int): Communication baud rate (default: 9600).
            timeout (int): Timeout duration for Modbus communication (default: 0.5 seconds).
            parity (str): Parity setting for serial communication (default: 'N' for No Parity Bit).
            stopbits (int): Number of stop bits (default: 1).
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

        '''Connection management parameters:'''
        self.CONNECTION_TIMEOUT = 6.0  # seconds without successful poll before considering connection lost
        self._connect_backoff_sec = 0.25  # initial time between connection attempts
        self._connect_backoff_max_sec = 2.0  # max backoff between attempts
        self._next_connect_time = 0.0  # used for backoff timing of connection attempts

        '''Polling management paramters:'''
        self._poll_index = 0  # rotate unit polling order to avoid always lagging the same unit
        self._unit_poll_backoff_base_sec = 0.25  # per-unit backoff after poll failures
        self._unit_poll_backoff_max_sec = 2.0
        self._unit_poll_backoff_sec = {uid: 0.0 for uid in self.UNIT_IDS}
        self._next_unit_poll_time = {uid: 0.0 for uid in self.UNIT_IDS}

        '''Switch states, flags, 3k counter (to check for changes on each read)'''
        self.switch_states = [0 for _ in range(7)] # 4 HV enable signals, arm beams, ccs power, arm 80kv
        self.latched_flags = [0 for _ in range(12)]  # 12 latched flags from DINPUT word
        self.unlatched_signals = [0 for _ in range(8)]  # 8 unlatched signals from DINPUT word
        self.reset_counter = 0

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
            except Exception:
                # poll_one already logs a single ERROR only when all retries are exhausted.
                pass

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
                    # V set/read, I read, 3kV reset count, unlatched signals, latched flags
                    input_registers = self.client.read_input_registers(
                        address=IREG_V_SET_ADDR,
                        count=TOTAL_REG_COUNT,
                        slave=unit_id
                    )
                if input_registers.isError():
                    raise RuntimeError() # no print, overflows log because read errors are not uncommon and handled with retries/backoff

                if len(input_registers.registers) < TOTAL_REG_COUNT:
                    raise RuntimeError(f"Knob Box Modbus: Expected {TOTAL_REG_COUNT} registers but got {len(input_registers.registers)}")
                
                # Unpack all 6 modbus registers received in packet.
                registers = input_registers.registers
                v_set = registers[IREG_V_SET_ADDR]
                v_read = registers[IREG_V_READ_ADDR]
                i_read = registers[IREG_I_READ_ADDR]
                reset_counter = registers[IREG_3KV_RESET_COUNT_ADDR]
                unlatched_signals = registers[DINPUT_UNLATCHED_SIGNALS_ADDR]
                flags = registers[DINPUT_LATCHED_FLAGS_ADDR]

                # Unpack the unlatched signals
                raw_hv_enable = int(bool(unlatched_signals & UNLATCHED_SIGNAL_MASK_HVENABLE))
                reset_state_1kV = int(bool(unlatched_signals & UNLATCHED_SIGNAL_MASK_RESET_STATE_1KV))
                arm_80kV = int(bool(unlatched_signals & UNLATCHED_SIGNAL_MASK_ARM80KV_ENABLE))
                ccs_power = int(bool(unlatched_signals & UNLATCHED_SIGNAL_MASK_CCSPOWER_ENABLE))
                arm_beams = int(bool(unlatched_signals & UNLATCHED_SIGNAL_MASK_ARMBEAMS_ENABLE))
                enable_3kV = int(bool(unlatched_signals & UNLATCHED_SIGNAL_MASK_3KV_ENABLE))
                nomop_flag = int(bool(unlatched_signals & UNLATCHED_SIGNAL_MASK_NOMOP))
                logic_alive_flag = int(bool(unlatched_signals & UNLATCHED_SIGNAL_MASK_LOGIC_ALIVE))

                # HV enable for 3kV comes from the logic arduino output signal.
                hv_enable = enable_3kV if unit_id == 4 else raw_hv_enable

                # Unpack the latched flags
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

                # Create a full data dict to update this unit's global data dict.
                new_data = {
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

                # Update this unit's global data dict with the data lock.
                with self.data_lock:
                    self.data[unit_id] = new_data
                    self.last_success[unit_id] = time.time()

                # Reset polling timing parameters with lock (successul read).
                with self.poll_schedule_lock:
                    self._unit_poll_backoff_sec[unit_id] = 0.0
                    self._next_unit_poll_time[unit_id] = 0.0

                """
                3kV Specific logging: all flags and signals except for 1kV reset state.
                """
                if (unit_id == 4):
                    # Check for an increment of the 3kV reset counter
                    if self.reset_counter < reset_counter:
                        self.log(f"Knob Box: 3kV Bertan timer state counter incremented, counter = {reset_counter}", LogLevel.ERROR)

                    # Check if 3kV forced off
                    if reset_counter > 0 and self.reset_counter == 0:
                        self.log(f"Knob Box: 3kV Bertan enable was forced off.", LogLevel.ERROR)

                    # Update the stored reset counter
                    self.reset_counter = reset_counter    

                    # Check for edges on switch states
                    if self.switch_states[4] != arm_80kV:
                            if (self.switch_states[4] == 0 and arm_80kV == 1):
                                self.log(f"Knob Box: Arm 80kV switch turned ON", LogLevel.INFO)
                            else:
                                self.log(f"Knob Box: Arm 80kV switch turned OFF", LogLevel.INFO)
                    if self.switch_states[5] != arm_beams:
                            if (self.switch_states[5] == 0 and arm_beams == 1):
                                self.log(f"Knob Box: Arm beams switch turned ON", LogLevel.INFO)
                            else:
                                self.log(f"Knob Box: Arm beams switch turned OFF", LogLevel.INFO)
                    if self.switch_states[6] != ccs_power:
                            if (self.switch_states[6] == 0 and ccs_power == 1):
                                self.log(f"Knob Box: CCS power switch turned ON", LogLevel.INFO)
                            else:
                                self.log(f"Knob Box: CCS power switch turned OFF", LogLevel.INFO)

                    # Check for edges on all latched flags and log them
                    new_flag_states = [ # just a list of new data to cleanly iterate through
                        (0, timer_state_flag, "3kV Timer State"),
                        (1, armbeams_flag, "Arm Beams"),
                        (2, ccspower_flag, "CCS Power Allow"),
                        (3, arm80kv_flag, "Arm 80kV"),
                        (4, vcomp_1k_flag, "1kV Voltage Comp"),
                        (5, icomp_1k_flag, "1kV Current Comp"),
                        (6, neg_vcomp_1k_flag, "Negative 1kV Voltage Comp"),
                        (7, neg_icomp_1k_flag, "Negative 1kV Current Comp"),
                        (8, vcomp_20k_flag, "20kV Voltage Comp"),
                        (9, icomp_20k_flag, "20kV Current Comp"),
                        (10, vcomp_3k_flag, "3kV Voltage Comp"),
                        (11, icomp_3k_flag, "3kV Current Comp"),
                    ]
                    for idx, new_val, flag_name in new_flag_states:
                        if self.latched_flags[idx] != new_val:
                            if self.latched_flags[idx] == 0 and new_val == 1:
                                # When any flag is tripped, it should be an ERROR.
                                self.log(f"Knob Box: {flag_name} flag tripped.", LogLevel.ERROR)
                            else:
                                # Log as INFO on falling edge.
                                # TODO unsure if this will cause log overflowing/if it is needed at all.
                                self.log(f"Knob Box: {flag_name} flag deasserted.", LogLevel.INFO)

                    # Check for edges on all unlatched signals and log them.
                    new_signal_states = [
                        (0, raw_hv_enable, "HV Enable"),
                        # (1kV reset is sent over by the +-1kV arduinos)
                        (2, arm_80kV, "Arm 80kV"),
                        (3, ccs_power, "CCS Power"),
                        (4, arm_beams, "Arm Beams"),
                        (5, enable_3kV, "3kV Enable"),
                        (6, nomop_flag, "Nomop"),
                        (7, logic_alive_flag, "Logic Comms")
                    ]
                    for idx, new_val, signal_name in new_signal_states:
                        if self.unlatched_signals[idx] != new_val:
                            if self.unlatched_signals[idx] == 0 and new_val == 1:
                                self.log(f"Knob Box: {signal_name} signal ON.", LogLevel.INFO)
                            
                            elif idx == 6:
                                # Nomop Signal: 1-->0 transition is an ERROR
                                self.log(f"Knob Box: Entered INTERLOCKS State.", LogLevel.ERROR)
                            elif idx == 7:
                                # Logic Alive Signal: 1-->0 transistion is an ERROR
                                self.log(f"Knob Box: Lost communication with the Logic Arduino.", LogLevel.ERROR)
                            else:
                                self.log(f"Knob Box: {signal_name} signal OFF.", LogLevel.INFO)

                    # Arm Beams, CCS Power, and Arm 80kV are only recieved by the 3kv arduino.
                    self.switch_states[4] = 0 if arm_80kV == 0 else 1
                    self.switch_states[5] = 0 if arm_beams == 0 else 1
                    self.switch_states[6] = 0 if ccs_power == 0 else 1
                    # Latched flags are only recieved by the 3kV arduino.
                    self.latched_flags = [
                        timer_state_flag,
                        armbeams_flag,
                        ccspower_flag,
                        arm80kv_flag,
                        vcomp_1k_flag,
                        icomp_1k_flag,
                        neg_vcomp_1k_flag,
                        neg_icomp_1k_flag,
                        vcomp_20k_flag,
                        icomp_20k_flag,
                        vcomp_3k_flag,
                        icomp_3k_flag
                    ]
                    # Unlatched flags are only recieved by the 3kV arduino (exception: 1kV reset state).
                    reset_state = self.unlatched_signals[1]
                    self.unlatched_signals = [
                        raw_hv_enable,
                        reset_state, # this needs to stay unchanged, only units 1 and 2 should update it
                        arm_80kV,
                        ccs_power,
                        arm_beams,
                        enable_3kV,
                        nomop_flag,
                        logic_alive_flag
                    ]

                """
                +-1kV Specific logging: just the reset state.
                """
                if (unit_id in [1, 2]):
                    new_reset_state = reset_state_1kV
                    if self.unlatched_signals[1] != new_reset_state:
                        if self.unlatched_signals[1] == 0 and new_reset_state == 1:
                            if (unit_id == 1):
                                self.log(f"Knob Box: +1kV entered Overcurrent Reset Mode", LogLevel.ERROR)
                            else:
                                self.log(f"Knob Box: -1kV entered Overcurrent Reset Mode", LogLevel.ERROR)
                        else:
                            if (unit_id == 1):
                                self.log(f"Knob Box: +1kV exited Overcurrent Reset Mode", LogLevel.INFO)
                            else:   
                                self.log(f"Knob Box: -1kV exited Overcurrent Reset Mode", LogLevel.INFO)

                    # Just update the 1kv reset state
                    self.unlatched_signals[1] = new_reset_state

                
                """
                All units: check for HV enable switch state edge and log.
                """
                if self.switch_states[unit_id-1] != hv_enable:
                    unit = "+1kV" if unit_id == 1 else ("-1kV" if unit_id == 2 else ("20kV" if unit_id == 3 else "3kV"))
                    if (self.switch_states[unit_id-1] == 0 and hv_enable == 1):
                        self.log(f"Knob Box: {unit} HV enable turned ON", LogLevel.INFO)
                    else:
                        self.log(f"Knob Box: {unit} HV enable turned OFF", LogLevel.INFO)

                # Update HV enable switch state
                self.switch_states[unit_id-1] = 0 if hv_enable == 0 else 1

                return

            except Exception as e:
                last_exception = e
                if attempt < self.MAX_ATTEMPTS:
                    time.sleep(0.05)
                else:
                    self.log(f"Knob Box: [unit {unit_id}] all {self.MAX_ATTEMPTS} read attempts failed", LogLevel.INFO)

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
