import time
import threading
from threading import Lock, RLock
import struct
import math
from utils import LogLevel
from pymodbus.client import ModbusSerialClient as ModbusClient
from pymodbus.exceptions import ModbusIOException
from typing import Dict

class DP16ProcessMonitor:
    """Driver for Omega iSeries DP16PT Process Monitor - Modbus RTU"""

    PROCESS_VALUE_REG = 0x210   # Page 8: CNPt Series Programming User's Guide Modbus Interface
    RDGCNF_REG = 0x248          # Page 9: CNPt Series Programming User's Guide Modbus Interface
    STATUS_REG = 0x240          # Page 9: CNPt Series Programming User's Guide Modbus Interface

    # Alternate map from iSeries Modbus table (manual section 6.7)
    PROCESS_VALUE_REG_ALT = 39
    RDGCNF_REG_ALT = 8

    STATUS_RUNNING = 0x0006

    # PT100 RTD temperature range
    MIN_TEMP = -90      # [C]
    MAX_TEMP = 500      # [C]
    
    # Polling delay
    BASE_DELAY = 0.1    # [seconds]
    MAX_DELAY = 5       # [seconds]
    INTER_REQUEST_DELAY = 0.03
    REQUEST_RETRIES = 2

    ERROR_THRESHOLD = 5
    ERROR_LOG_INTERVAL = 10 # [seconds]

    # Error states
    DISCONNECTED = -1
    SENSOR_ERROR = -2

    def __init__(
        self,
        port,
        unit_numbers=(1, 2, 3, 4, 5, 6),
        baudrate=9600,
        bytesize=8,
        parity='N',
        stopbits=1,
        timeout=0.25,
        prefer_manual_map=True,
        auto_detect_serial_profile=True,
        logger=None,
    ):
        """ Initialize Modbus settings """
        self.port = port
        self.baudrate = baudrate
        self.bytesize = bytesize
        self.parity = parity
        self.stopbits = stopbits
        self.timeout = timeout
        self.auto_detect_serial_profile = auto_detect_serial_profile

        self.client = ModbusClient(
            port=self.port,
            baudrate=self.baudrate,
            bytesize=self.bytesize,
            parity=self.parity,
            stopbits=self.stopbits,
            timeout=self.timeout
        )
        self.prefer_manual_map = prefer_manual_map
        self.unit_numbers = set(unit_numbers)
        self.modbus_lock = RLock()
        self.logger = logger

        self.temperature_readings = {unit: None for unit in unit_numbers}
        self.consecutive_error_counts = {unit: 0 for unit in self.unit_numbers}
        self.last_good_readings = {unit: None for unit in self.unit_numbers}
        self.unit_map_mode = {unit: None for unit in self.unit_numbers}  # 'float_map' or 'int_map'
        self.consecutive_connection_errors = 0

        self._is_running = True
        self._thread = None
        self.response_lock = Lock()
        self.last_critical_error_time = 0
        
        # Start single background polling thread after successful connection and configuration
        self._thread = threading.Thread(target=self.poll_all_units, daemon=True)
        self._thread.start()

    def _set_serial_profile_locked(self, bytesize: int, parity: str, stopbits: int):
        """Rebuild serial client with a new framing profile. Caller must hold modbus_lock."""
        try:
            if self.client.is_socket_open():
                self.client.close()
        except Exception:
            pass

        self.bytesize = bytesize
        self.parity = parity
        self.stopbits = stopbits
        self.client = ModbusClient(
            port=self.port,
            baudrate=self.baudrate,
            bytesize=self.bytesize,
            parity=self.parity,
            stopbits=self.stopbits,
            timeout=self.timeout,
        )

    def _probe_working_units_locked(self):
        """Probe all configured units and return set of working unit ids. Caller must hold modbus_lock."""
        working_units = set()
        for unit in self.unit_numbers:
            try:
                map_mode = self._probe_unit_map_locked(unit)
                if map_mode:
                    working_units.add(unit)
                    self.unit_map_mode[unit] = map_mode
                    continue
                self.log(f"DP16 Unit {unit} not responding", LogLevel.WARNING)
            except ModbusIOException:
                self.log(f"DP16 Unit {unit} not responding", LogLevel.WARNING)
            finally:
                time.sleep(self.INTER_REQUEST_DELAY)
        return working_units

    @staticmethod
    def _to_signed_16(value: int) -> int:
        return value - 0x10000 if value >= 0x8000 else value

    @staticmethod
    def _rdgcnf_multiplier(rdgcnf: int) -> float:
        decimal_code = (rdgcnf >> 5) & 0x07
        if decimal_code == 1:
            return 1.0
        if decimal_code == 2:
            return 10.0
        if decimal_code == 3:
            return 100.0
        if decimal_code == 4:
            return 1000.0
        return 1.0

    def _probe_unit_map_locked(self, unit: int):
        """Probe unit register map. Caller must hold modbus_lock."""
        if self.prefer_manual_map:
            try:
                rdgcnf_resp = self._read_holding_registers_locked(
                    address=self.RDGCNF_REG_ALT,
                    count=1,
                    slave=unit
                )
                pv_resp = self._read_holding_registers_locked(
                    address=self.PROCESS_VALUE_REG_ALT,
                    count=1,
                    slave=unit
                )
                rdgcnf = rdgcnf_resp.registers[0]
                counts = self._to_signed_16(pv_resp.registers[0])
                multiplier = self._rdgcnf_multiplier(rdgcnf)
                value = counts / multiplier if multiplier else float(counts)
                if self.MIN_TEMP <= value <= self.MAX_TEMP:
                    self.log(
                        f"DP16 Unit {unit} responded on manual map (reg39/reg8): {value:.2f}C",
                        LogLevel.VERBOSE
                    )
                return 'int_map'
            except ModbusIOException:
                pass

        try:
            status = self._read_holding_registers_locked(
                address=self.STATUS_REG,
                count=1,
                slave=unit
            )
            self.log(
                f"DP16 Unit {unit} responded on float map with status: {status.registers[0]}",
                LogLevel.VERBOSE
            )
            return 'float_map'
        except ModbusIOException:
            pass

        try:
            rdgcnf_resp = self._read_holding_registers_locked(
                address=self.RDGCNF_REG_ALT,
                count=1,
                slave=unit
            )
            pv_resp = self._read_holding_registers_locked(
                address=self.PROCESS_VALUE_REG_ALT,
                count=1,
                slave=unit
            )
            rdgcnf = rdgcnf_resp.registers[0]
            counts = self._to_signed_16(pv_resp.registers[0])
            multiplier = self._rdgcnf_multiplier(rdgcnf)
            value = counts / multiplier if multiplier else float(counts)
            if self.MIN_TEMP <= value <= self.MAX_TEMP:
                self.log(
                    f"DP16 Unit {unit} responded on int map (reg39/reg8): {value:.2f}C",
                    LogLevel.VERBOSE
                )
            else:
                self.log(
                    f"DP16 Unit {unit} int-map probe returned out-of-range value {value:.2f}C; continuing",
                    LogLevel.DEBUG
                )
            return 'int_map'
        except ModbusIOException:
            return None

    def _read_holding_registers_locked(self, address: int, count: int, slave: int):
        """Read register(s) with retry. Caller must hold modbus_lock.

        Manual states 03/04 are valid for reads, so we try 03 first then 04.
        """
        last_exception = None
        for attempt in range(self.REQUEST_RETRIES + 1):
            try:
                response = self.client.read_holding_registers(
                    address=address,
                    count=count,
                    slave=slave
                )
                if response and not response.isError() and len(response.registers) >= count:
                    return response
            except Exception as exc:
                last_exception = exc

            try:
                response = self.client.read_input_registers(
                    address=address,
                    count=count,
                    slave=slave
                )
                if response and not response.isError() and len(response.registers) >= count:
                    return response
            except Exception as exc:
                last_exception = exc

            if attempt < self.REQUEST_RETRIES:
                time.sleep(self.INTER_REQUEST_DELAY)

        if last_exception:
            raise ModbusIOException(str(last_exception))
        raise ModbusIOException(
            f"Read failed for slave={slave}, address=0x{address:03X}, count={count}"
        )

    def _write_register_locked(self, address: int, value: int, slave: int):
        """Write single register with retry. Caller must hold modbus_lock."""
        last_exception = None
        for attempt in range(self.REQUEST_RETRIES + 1):
            try:
                response = self.client.write_register(
                    address=address,
                    value=value,
                    slave=slave
                )
                if response and not response.isError():
                    return response
            except Exception as exc:
                last_exception = exc

            if attempt < self.REQUEST_RETRIES:
                time.sleep(self.INTER_REQUEST_DELAY)

        if last_exception:
            raise ModbusIOException(str(last_exception))
        raise ModbusIOException(
            f"Write failed for slave={slave}, address=0x{address:03X}, value={value}"
        )
    
    def connect(self):
        """
        Establish a connection to the DP16 units.

        Returns:
            bool: True if the connection is successful, False otherwise.
        """
        with self.modbus_lock:
            try:
                if self.client.is_socket_open():
                    self.log("Reusing existing PMON Modbus connection", LogLevel.DEBUG)
                    return True

                current_profile = (self.bytesize, self.parity, self.stopbits)
                candidate_profiles = [current_profile]
                if self.auto_detect_serial_profile:
                    for profile in ((8, 'N', 1), (8, 'E', 1), (8, 'O', 1), (7, 'E', 1), (7, 'O', 1)):
                        if profile not in candidate_profiles:
                            candidate_profiles.append(profile)

                for bytesize, parity, stopbits in candidate_profiles:
                    if (bytesize, parity, stopbits) != (self.bytesize, self.parity, self.stopbits):
                        self._set_serial_profile_locked(bytesize, parity, stopbits)

                    self.log(
                        f"Attempting PMON connect on {self.port} @ {self.baudrate},{bytesize}{parity}{stopbits}",
                        LogLevel.DEBUG
                    )
                    if not self.client.connect():
                        continue

                    working_units = self._probe_working_units_locked()
                    if working_units:
                        self.consecutive_connection_errors = 0
                        self.log(
                            f"Connected to {len(working_units)}/{len(self.unit_numbers)} DP16 units using {bytesize}{parity}{stopbits}",
                            LogLevel.INFO
                        )
                        return True

                    self.client.close()

                return False

            except ModbusIOException as e:
                self.log(f"Modbus IO error during DP16 connection: {e}", LogLevel.ERROR)
                return False
            except Exception as e:
                self.log(f"DP16 Error connecting: {str(e)}", LogLevel.ERROR)
                return False

    def get_reading_config(self, unit):
        """Get reading configuration format
        Returns:
            int: 2 for FFF.F format, 3 for FFFF format, None on error
        """
        try:
            with self.modbus_lock:
                return self._get_reading_config_locked(unit)
        except ModbusIOException as e:
            self.log(f"Modbus IO error reading config for DP16 unit {unit}: {e}", LogLevel.WARNING)
            return None
        except Exception as e:
            self.log(f"Error reading config: {e}", LogLevel.ERROR)
            return None

    def _get_reading_config_locked(self, unit):
        """Read RDGCNF while caller holds modbus_lock."""
        if self.unit_map_mode.get(unit) == 'int_map' or self.prefer_manual_map:
            try:
                response = self._read_holding_registers_locked(
                    address=self.RDGCNF_REG_ALT,
                    count=1,
                    slave=unit
                )
                time.sleep(self.INTER_REQUEST_DELAY)
                return response.registers[0]
            except ModbusIOException:
                pass

        response = self._read_holding_registers_locked(
            address=self.RDGCNF_REG,
            count=1,
            slave=unit
        )
        time.sleep(self.INTER_REQUEST_DELAY)
        return response.registers[0]

    def _set_config(self, unit):
        """
        Sets the reading configuration format along with the run state
        2 - FFF.F
        3 - FFFF

        6 - Running 
        10 - Operating
        Returns:
            if setting is successful or not
        """
        if unit not in self.unit_numbers:
            self.log(f"DP16 set_decimal_config was called with an invalid unit address", LogLevel.ERROR)
            return False # exit for invalid unit
        
        try:
            with self.modbus_lock:
                self.log(f"Setting RDGCNF_REG for unit {unit}", LogLevel.DEBUG)
                # Manual register 8: default 0x4A (Decimal point 2, °F bit=0, filter=4)
                if self.unit_map_mode.get(unit) == 'int_map' or self.prefer_manual_map:
                    self._write_register_locked(
                        address=self.RDGCNF_REG_ALT,
                        value=0x004A,
                        slave=unit
                    )
                else:
                    self._write_register_locked(
                        address=self.RDGCNF_REG,
                        value=0x004A,
                        slave=unit
                    )
                time.sleep(self.INTER_REQUEST_DELAY)
                
                self.log(f"Configuration successful for DP16 unit {unit}", LogLevel.INFO)
                return True
            
        except ModbusIOException as e:
            self.log(f"Modbus IO error while setting config for unit {unit}: {e}", LogLevel.ERROR)
            return False
        except Exception as e:
            self.log(f"Error writing RDGCNF_REG config: {e}", LogLevel.ERROR)
            return False
        
    def poll_all_units(self):
        """Single polling loop with each unit independent"""
        while self._is_running:
            current_time = time.time()
            try:
                # Check if client is still connected
                if not self.client.is_socket_open():
                    self.consecutive_connection_errors += 1
                    # Mark all disconnected if we exceed error threshold
                    if self.consecutive_connection_errors >= self.ERROR_THRESHOLD:
                        with self.response_lock:
                            for unit in self.unit_numbers:
                                self.temperature_readings[unit] = self.DISCONNECTED
                    
                    # Try to reconnect
                    if not self.connect():
                        if current_time - self.last_critical_error_time >= self.ERROR_LOG_INTERVAL:
                            self.log("Failed to reconnect to PMON", LogLevel.ERROR)
                            self.last_critical_error_time = current_time
                        sleep_time = min(
                            self.MAX_DELAY,
                            max(self.BASE_DELAY, self.BASE_DELAY * (2 ** min(self.consecutive_connection_errors, 5)))
                        )
                        time.sleep(sleep_time)
                        continue
                
                # Poll each unit individually
                for unit in sorted(self.unit_numbers):
                    try:
                        self._poll_single_unit(unit) 
                        self.consecutive_connection_errors = 0  # Reset on successful poll
                        time.sleep(self.INTER_REQUEST_DELAY)
                    except Exception as e:
                        self._handle_poll_error(unit, e)
                        
                        # Rate limited error logging
                        if current_time - self.last_critical_error_time >= self.ERROR_LOG_INTERVAL:
                            self.log(f"Error polling unit {unit}: {e}", LogLevel.ERROR)
                            self.last_critical_error_time = current_time

                if self.consecutive_connection_errors == 0:
                    time.sleep(self.BASE_DELAY)
                    
            except Exception as e:
                self.consecutive_connection_errors += 1
                current_time = time.time()
                if current_time - self.last_critical_error_time >= self.ERROR_LOG_INTERVAL:
                    self.log(f"Polling error: {e}", LogLevel.ERROR)
                    self.last_critical_error_time = current_time

    def _poll_single_unit(self, unit):
        """Poll a single unit atomically"""
        if not self._is_running:
            return

        with self.modbus_lock:
            map_mode = self.unit_map_mode.get(unit)
            if map_mode is None:
                map_mode = self._probe_unit_map_locked(unit)
                self.unit_map_mode[unit] = map_mode
                if map_mode is None:
                    raise ModbusIOException("Unable to determine DP16 register map")

            if map_mode == 'float_map':
                try:
                    status = self._read_holding_registers_locked(
                        address=self.STATUS_REG,
                        count=1,
                        slave=unit
                    )
                    if status.registers[0] != self.STATUS_RUNNING:
                        self.log(
                            f"DP16 Unit {unit} status {status.registers[0]} differs from expected {self.STATUS_RUNNING}",
                            LogLevel.WARNING
                        )
                except ModbusIOException:
                    self.log(f"DP16 Unit {unit} status read skipped; continuing with PV read", LogLevel.DEBUG)

                response = self._read_holding_registers_locked(
                    address=self.PROCESS_VALUE_REG,
                    count=2,
                    slave=unit
                )
                raw_float = struct.pack('>HH', response.registers[0], response.registers[1])
                value = struct.unpack('>f', raw_float)[0]
            else:
                rdgcnf = self._get_reading_config_locked(unit)
                if rdgcnf is None:
                    raise ModbusIOException("RDGCNF read failed on int map")

                response = self._read_holding_registers_locked(
                    address=self.PROCESS_VALUE_REG_ALT,
                    count=1,
                    slave=unit
                )
                counts = self._to_signed_16(response.registers[0])
                value = counts / self._rdgcnf_multiplier(rdgcnf)

            # In-line validation
            if not math.isfinite(value):
                raise ValueError(f"Non-finite reading: {value}")
            if not (self.MIN_TEMP <= value <= self.MAX_TEMP):
                raise ValueError(f"Temperature out of range: {value}")

            # All good, reset the consecutive error count
            self.consecutive_error_counts[unit] = 0
            
            # Update reading for GUI availability
            with self.response_lock:
                self.temperature_readings[unit] = value
                self.last_good_readings[unit] = value
    
    def _handle_poll_error(self, unit: int, exception: Exception):
            """
            Increments consecutive error counts, logs the error, and updates 
            self.temperature_readings based on the single ERROR_THRESHOLD logic.
            """
            self.log(f"Poll error on unit {unit}: {exception}", LogLevel.VERBOSE)
            self.consecutive_error_counts[unit] += 1

            err_str = str(exception).lower()
            is_modbus_error = isinstance(exception, ModbusIOException)

            # Classify the error for logging or bus-level increments
            if is_modbus_error:
                if ("port is closed" in err_str or
                    "could not open port" in err_str):
                    self.log(f"Hard port failure on unit {unit}: {exception}", LogLevel.ERROR)
                    self.client.close()
                    self.consecutive_connection_errors += 1
                elif ("failed to connect" in err_str or
                    "connection" in err_str):
                    self.log(f"Connection error on unit {unit}: {exception}", LogLevel.WARNING)
                    self.consecutive_connection_errors += 1
                elif "status read failed" in err_str:
                    self.log(f"Partial/incomplete status response on unit {unit}", LogLevel.DEBUG)
                elif "temperature read failed" in err_str:
                    self.log(f"Partial/incomplete temperature response on unit {unit}", LogLevel.DEBUG)
                else:
                    self.log(f"General Modbus IO error on unit {unit}: {exception}", LogLevel.ERROR)
            else:
                self.log(f"Invalid reading on unit {unit}: {exception}", LogLevel.WARNING)

            with self.response_lock:
                if self.consecutive_error_counts[unit] >= self.ERROR_THRESHOLD:
                    # Enough consecutive errors to declare full disconnection
                    self.temperature_readings[unit] = self.DISCONNECTED
                else:
                    # 1-5 consecutive failures => show last known good reading if exists
                    # Mark as SENSOR_ERROR if we never had a good reading
                    if self.last_good_readings[unit] is not None:
                        self.temperature_readings[unit] = self.last_good_readings[unit]
                    else:
                        self.temperature_readings[unit] = self.SENSOR_ERROR

    def get_all_temperatures(self):
        """ Thread-safe access method """
        with self.response_lock:
            return dict(self.temperature_readings)

    def disconnect(self):
        self._is_running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)

        with self.modbus_lock:
            if self.client.is_socket_open():
                self.client.close()
                self.log("Disconnected from DP16 Process Monitors", LogLevel.INFO)
            else:
                self.log("No active connection to DP16 Process Monitors", LogLevel.INFO)

    def log(self, message, level=LogLevel.INFO):
        """Log a message with the specified level if a logger is configured."""
        if self.logger:
            self.logger.log(message, level)
        else:
            print(f"{level.name}: {message}")