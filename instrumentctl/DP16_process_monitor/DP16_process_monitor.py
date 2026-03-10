import time
import threading
from threading import Lock
import struct
from utils import LogLevel
from pymodbus.client import ModbusSerialClient as ModbusClient
from pymodbus.exceptions import ModbusIOException
from typing import Dict

class DP16ProcessMonitor:
    """Driver for Omega iSeries DP16PT Process Monitor - Modbus RTU"""

    PROCESS_VALUE_REG = 0x210   # Page 8: CNPt Series Programming User's Guide Modbus Interface
    RDGCNF_REG = 0x248          # Page 9: CNPt Series Programming User's Guide Modbus Interface
    STATUS_REG = 0x240          # Page 9: CNPt Series Programming User's Guide Modbus Interface

    STATUS_RUNNING = 0x0006

    # PT100 RTD temperature range
    MIN_TEMP = -90      # [C]
    MAX_TEMP = 500      # [C]
    
    # Polling delay
    BASE_DELAY = 0.1    # [seconds]
    MAX_DELAY = 5       # [seconds]
    INTER_COMMAND_DELAY = 0.05  # [seconds] RS-485 bus turnaround between register reads

    ERROR_THRESHOLD = 5
    ERROR_LOG_INTERVAL = 10 # [seconds]

    # Error states
    DISCONNECTED = -1
    SENSOR_ERROR = -2

    def __init__(self, port, unit_numbers=(1,2,3,4,5), baudrate=9600, logger=None):
        """ Initialize Modbus settings """
        self.logger = logger
        self.log(
            f"DP16 __init__: port={port}, units={unit_numbers}, "
            f"baud={baudrate}, timeout=0.3",
            LogLevel.INFO
        )
        self.client = ModbusClient(
            port=port,
            baudrate=baudrate,
            bytesize=8,
            parity='N',
            stopbits=1,
            timeout=0.3
        )
        self.unit_numbers = set(unit_numbers)
        self.modbus_lock = Lock()

        self.temperature_readings = {unit: None for unit in unit_numbers}
        self.consecutive_error_counts = {unit: 0 for unit in self.unit_numbers}
        self.last_good_readings = {unit: None for unit in self.unit_numbers}
        self.consecutive_connection_errors = 0

        self._is_running = True
        self._thread = None
        self.response_lock = Lock()
        self.last_critical_error_time = 0

        # Start single background polling thread (connection is established there,
        # keeping __init__ non-blocking so the main/GUI thread is never stalled)
        self.log("DP16 __init__: launching background polling thread", LogLevel.DEBUG)
        self._thread = threading.Thread(target=self._polling_entry, daemon=True)
        self._thread.start()
    
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
                
                self.log(
                    f"connect(): opening serial port {self.client.comm_params.host} "
                    f"@ {self.client.comm_params.baudrate} 8N1",
                    LogLevel.INFO
                )
                if not self.client.connect():
                    self.log("connect(): client.connect() returned False — port open failed", LogLevel.ERROR)
                    return False
                
                self.log("connect(): serial port opened successfully, probing units...", LogLevel.INFO)

                # Check if any unit responds
                working_units = set()
                for unit in sorted(self.unit_numbers):
                    # Clear stale data before probing
                    if hasattr(self.client, 'serial') and self.client.serial:
                        self.client.serial.reset_input_buffer()

                    self.log(f"connect(): probing unit {unit} (STATUS_REG 0x{self.STATUS_REG:04X})", LogLevel.DEBUG)
                    status = self.client.read_holding_registers(
                        address=self.STATUS_REG,
                        count=1,
                        slave=unit
                    )
                    time.sleep(self.INTER_COMMAND_DELAY)

                    if not status.isError():
                        working_units.add(unit)
                        self.log(
                            f"connect(): unit {unit} responded — status=0x{status.registers[0]:04X}",
                            LogLevel.INFO
                        )
                    else:
                        self.log(
                            f"connect(): unit {unit} probe FAILED — response: {status}",
                            LogLevel.WARNING
                        )

                if working_units:
                    self.log(
                        f"connect(): {len(working_units)}/{len(self.unit_numbers)} "
                        f"units online: {sorted(working_units)}",
                        LogLevel.INFO
                    )
                    return True
                    
                self.log("connect(): no units responded — all probes failed", LogLevel.ERROR)
                return False

            except ModbusIOException as e:
                self.log(f"connect(): ModbusIOException: {e}", LogLevel.ERROR)
                return False
            except Exception as e:
                self.log(f"connect(): unexpected {type(e).__name__}: {e}", LogLevel.ERROR)
                return False

    def get_reading_config(self, unit):
        """Get reading configuration format
        Returns:
            int: 2 for FFF.F format, 3 for FFFF format, None on error
        """
        try:
            with self.modbus_lock:
                if hasattr(self.client, 'serial') and self.client.serial:
                    self.client.serial.reset_input_buffer()
                response = self.client.read_holding_registers(
                    address=self.RDGCNF_REG,
                    count=1,
                    slave=unit
                )
                time.sleep(self.INTER_COMMAND_DELAY)
                if not response.isError():
                    return response.registers[0]
                return None
        except ModbusIOException as e:
            self.log(f"Modbus IO error reading config for DP16 unit {unit}: {e}", LogLevel.WARNING)
        except Exception as e:
            self.log(f"Error reading config: {e}", LogLevel.ERROR)
            return None

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
                # First write: Set decimal format
                response1 = self.client.write_register(
                    address=self.RDGCNF_REG,
                    value=0x002, # e.g. "FFF.F"
                    slave=unit
                )
                if response1.isError():
                    self.log(f"Failed to write RDGCNF_REG for DP16 unit {unit}. Response:{response1}", LogLevel.ERROR)
                    return False # Exit early if the first write fails
                    
                # Second write: Update STATUS_REG
                self.log(f"Setting STATUS_REG for unit {unit}", LogLevel.DEBUG)
                response2 = self.client.write_register(
                    address=self.STATUS_REG,
                    value=self.STATUS_RUNNING,
                    slave=unit
                )
                time.sleep(0.1)
                if response2.isError():
                    self.log(f"Failed to write STATUS_REG for DP16 unit {unit}: Response:{response2}", LogLevel.ERROR)
                    return False # Exit if second write fails
                
                self.log(f"Configuration successful for DP16 unit {unit}", LogLevel.INFO)
                return True
            
        except ModbusIOException as e:
            self.log(f"Modbus IO error while setting config for unit {unit}: {e}", LogLevel.ERROR)
            return False
        except Exception as e:
            self.log(f"Error writing RDGCNF_REG config: {e}", LogLevel.ERROR)
            return False
        
    def _polling_entry(self):
        """Background thread entry point: connect then poll."""
        self.log("_polling_entry: background thread started", LogLevel.INFO)
        try:
            self.log(f"_polling_entry: attempting initial connection to {self.client.comm_params.host}", LogLevel.DEBUG)
            if not self.client.connect():
                self.log(
                    f"_polling_entry: initial connection to {self.client.comm_params.host} failed — "
                    f"poll loop will retry",
                    LogLevel.WARNING
                )
            else:
                self.log("_polling_entry: initial connection succeeded", LogLevel.INFO)
        except Exception as e:
            self.log(f"_polling_entry: initial connection exception: {type(e).__name__}: {e}", LogLevel.WARNING)
        self.poll_all_units()

    def poll_all_units(self):
        """Single polling loop with each unit independent"""
        self.log("poll_all_units: entering main loop", LogLevel.DEBUG)
        poll_cycle = 0
        while self._is_running:
            poll_cycle += 1
            cycle_start = time.time()
            current_time = cycle_start
            try:
                # Check if client is still connected
                socket_open = self.client.is_socket_open()
                if not socket_open:
                    self.consecutive_connection_errors += 1
                    self.log(
                        f"poll cycle {poll_cycle}: socket closed "
                        f"(consecutive_connection_errors={self.consecutive_connection_errors})",
                        LogLevel.DEBUG
                    )
                    # Mark all disconnected if we exceed error threshold
                    if self.consecutive_connection_errors >= self.ERROR_THRESHOLD:
                        with self.response_lock:
                            for unit in self.unit_numbers:
                                self.temperature_readings[unit] = self.DISCONNECTED
                        self.log(
                            f"poll cycle {poll_cycle}: all units marked DISCONNECTED "
                            f"(threshold {self.ERROR_THRESHOLD} reached)",
                            LogLevel.WARNING
                        )
                    
                    # Try to reconnect
                    self.log(f"poll cycle {poll_cycle}: attempting reconnect...", LogLevel.DEBUG)
                    if not self.connect():
                        if current_time - self.last_critical_error_time >= self.ERROR_LOG_INTERVAL:
                            self.log(
                                f"poll cycle {poll_cycle}: reconnect failed — "
                                f"retrying in 1s",
                                LogLevel.ERROR
                            )
                            self.last_critical_error_time = current_time
                        time.sleep(1)  # Delay before next attempt
                        continue
                    else:
                        self.log(f"poll cycle {poll_cycle}: reconnect succeeded", LogLevel.INFO)
                
                # Poll each unit individually
                units_ok = 0
                units_err = 0
                for unit in sorted(self.unit_numbers):
                    try:
                        self._poll_single_unit(unit) 
                        self.consecutive_connection_errors = 0  # Reset on successful poll
                        units_ok += 1
                        time.sleep(0.1)
                    except (ModbusIOException, ValueError) as e:
                        self._handle_poll_error(unit, e)
                        units_err += 1
                        
                        # Rate limited error logging
                        if current_time - self.last_critical_error_time >= self.ERROR_LOG_INTERVAL:
                            self.log(
                                f"poll cycle {poll_cycle}: unit {unit} error: "
                                f"{type(e).__name__}: {e}",
                                LogLevel.ERROR
                            )
                            self.last_critical_error_time = current_time

                cycle_ms = (time.time() - cycle_start) * 1000
                self.log(
                    f"poll cycle {poll_cycle}: ok={units_ok} err={units_err} "
                    f"cycle_time={cycle_ms:.0f}ms",
                    LogLevel.VERBOSE
                )

                if self.consecutive_connection_errors == 0:
                    time.sleep(self.BASE_DELAY)
                    
            except Exception as e:
                self.consecutive_connection_errors += 1
                current_time = time.time()
                if current_time - self.last_critical_error_time >= self.ERROR_LOG_INTERVAL:
                    self.log(
                        f"poll cycle {poll_cycle}: unhandled {type(e).__name__}: {e}",
                        LogLevel.ERROR
                    )
                    self.last_critical_error_time = current_time
                time.sleep(1)  # Backoff to prevent spin-loop on persistent errors

    def _poll_single_unit(self, unit):
        """Poll a single unit atomically"""
        if not self._is_running:
            return

        with self.modbus_lock:
            # Clear any stale data before status read
            if hasattr(self.client, 'serial') and self.client.serial:
                self.client.serial.reset_input_buffer()

            # Read status first
            self.log(f"_poll unit {unit}: reading STATUS_REG (0x{self.STATUS_REG:04X})", LogLevel.VERBOSE)
            status = self.client.read_holding_registers(
                address=self.STATUS_REG,
                count=1,
                slave=unit
            )
            time.sleep(self.INTER_COMMAND_DELAY)
            if status.isError():
                self.consecutive_error_counts[unit] += 1
                self.log(
                    f"_poll unit {unit}: STATUS_REG read error — response: {status}",
                    LogLevel.DEBUG
                )
                raise ModbusIOException("Status read failed")

            status_val = status.registers[0]
            self.log(
                f"_poll unit {unit}: status=0x{status_val:04X}",
                LogLevel.VERBOSE
            )

            # Warn if not in expected running state
            if status_val != self.STATUS_RUNNING:
                self.log(
                    f"_poll unit {unit}: status 0x{status_val:04X} differs from "
                    f"expected RUNNING (0x{self.STATUS_RUNNING:04X})",
                    LogLevel.WARNING
                )

            # Clear buffer before temperature read
            if hasattr(self.client, 'serial') and self.client.serial:
                self.client.serial.reset_input_buffer()

            # Read temperature
            self.log(
                f"_poll unit {unit}: reading PROCESS_VALUE_REG (0x{self.PROCESS_VALUE_REG:04X}, 2 regs)",
                LogLevel.VERBOSE
            )
            response = self.client.read_holding_registers(
                address=self.PROCESS_VALUE_REG,
                count=2,
                slave=unit
            )
            time.sleep(self.INTER_COMMAND_DELAY)
            if response.isError():
                self.log(
                    f"_poll unit {unit}: PROCESS_VALUE read error — response: {response}",
                    LogLevel.DEBUG
                )
                raise ModbusIOException("Temperature read failed")

            # Process response
            reg0, reg1 = response.registers[0], response.registers[1]
            raw_float = struct.pack('>HH', reg0, reg1)
            value = struct.unpack('>f', raw_float)[0]
            self.log(
                f"_poll unit {unit}: raw regs=[0x{reg0:04X}, 0x{reg1:04X}] "
                f"-> {value:.3f}°C",
                LogLevel.VERBOSE
            )

            # In-line validation
            if abs(value) < 0.001:
                self.log(
                    f"_poll unit {unit}: near-zero reading {value:.6f} — likely comms error",
                    LogLevel.DEBUG
                )
                raise ValueError("Zero reading indicates communication error")
            if not (self.MIN_TEMP <= value <= self.MAX_TEMP):
                self.log(
                    f"_poll unit {unit}: out of range {value:.2f} "
                    f"(valid: {self.MIN_TEMP}–{self.MAX_TEMP})",
                    LogLevel.DEBUG
                )
                raise ValueError(f"Temperature out of range: {value}")

            # All good, reset the consecutive error count
            self.consecutive_error_counts[unit] = 0
            
            # Update reading for GUI availability
            with self.response_lock:
                prev = self.temperature_readings[unit]
                self.temperature_readings[unit] = value
                self.last_good_readings[unit] = value
            
            self.log(
                f"_poll unit {unit}: updated {prev} -> {value:.2f}°C",
                LogLevel.VERBOSE
            )
    
    def _handle_poll_error(self, unit: int, exception: Exception):
            """
            Increments consecutive error counts, logs the error, and updates 
            self.temperature_readings based on the single ERROR_THRESHOLD logic.
            """
            self.consecutive_error_counts[unit] += 1
            err_count = self.consecutive_error_counts[unit]

            err_str = str(exception).lower()
            is_modbus_error = isinstance(exception, ModbusIOException)

            self.log(
                f"_handle_poll_error unit {unit}: {type(exception).__name__}: {exception} "
                f"(consecutive={err_count}/{self.ERROR_THRESHOLD})",
                LogLevel.DEBUG
            )

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
                    self.log(f"Status read failed on unit {unit} (err #{err_count})", LogLevel.DEBUG)
                elif "temperature read failed" in err_str:
                    self.log(f"Temperature read failed on unit {unit} (err #{err_count})", LogLevel.DEBUG)
                else:
                    self.log(f"General Modbus IO error on unit {unit}: {exception}", LogLevel.ERROR)
            else:
                self.log(
                    f"Validation error on unit {unit}: {type(exception).__name__}: {exception}",
                    LogLevel.WARNING
                )

            with self.response_lock:
                if err_count >= self.ERROR_THRESHOLD:
                    # Enough consecutive errors to declare full disconnection
                    self.temperature_readings[unit] = self.DISCONNECTED
                    self.log(
                        f"Unit {unit} -> DISCONNECTED (threshold {self.ERROR_THRESHOLD} reached)",
                        LogLevel.WARNING
                    )
                else:
                    # 1-5 consecutive failures => show last known good reading if exists
                    # Mark as SENSOR_ERROR if we never had a good reading
                    if self.last_good_readings[unit] is not None:
                        self.temperature_readings[unit] = self.last_good_readings[unit]
                        self.log(
                            f"Unit {unit} -> holding last good reading "
                            f"{self.last_good_readings[unit]:.2f}°C (err #{err_count})",
                            LogLevel.DEBUG
                        )
                    else:
                        self.temperature_readings[unit] = self.SENSOR_ERROR
                        self.log(
                            f"Unit {unit} -> SENSOR_ERROR (no prior good reading, err #{err_count})",
                            LogLevel.DEBUG
                        )

    def get_all_temperatures(self):
        """ Thread-safe access method """
        with self.response_lock:
            return dict(self.temperature_readings)

    def disconnect(self):
        self.log("disconnect(): stopping polling thread and closing port", LogLevel.INFO)
        self._is_running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
            if self._thread.is_alive():
                self.log("disconnect(): polling thread did not stop within 3s", LogLevel.WARNING)
            else:
                self.log("disconnect(): polling thread stopped", LogLevel.DEBUG)
        
        if self.client.is_socket_open():
            self.client.close()
            self.log("disconnect(): serial port closed", LogLevel.INFO)
        else:
            self.log("disconnect(): serial port was already closed", LogLevel.DEBUG)

    def log(self, message, level=LogLevel.INFO):
        """Log a message with the specified level if a logger is configured."""
        if self.logger:
            self.logger.log(message, level)
        else:
            print(f"{level.name}: {message}")