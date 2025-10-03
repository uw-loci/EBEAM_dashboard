import threading
import time
from pymodbus.client import ModbusSerialClient as ModbusClient
from utils import LogLevel  # Ensure this module is correctly implemented

class KnobBoxModbus:
    # TODO verify addresses for reading output status, set voltage, actual voltage, actual current
    OUTPUT_STATUS_ADDRESS = 0x0000  # Placeholder address for reading output status
    SET_VOLTAGE_ADDRESS = 0x0001    # Placeholder address for reading set voltage
    ACTUAL_VOLTAGE_ADDRESS = 0x0002  # Placeholder address for reading actual voltage
    ACTUAL_CURRENT_ADDRESS = 0x0003  # Placeholder address for reading actual current
    UNIT_NUMBERS = [1, 2, 3, 4, 5] # Unit numbers for each power supply
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
        self.stop_event = threading.Event()
        self.threads = [] # for each unit
        self.set_voltages = [None, None, None, None, None] 
        self.actual_voltages = [None, None, None, None, None] 
        self.actual_currents = [None, None, None, None, None] 
        self.output_statuses = [None, None, None, None, None]
        self.modbus_lock = threading.Lock() # Lock for Modbus communication
        self.is_initialized = threading.Event() # Event to signal successful initialization
        self.port = port
        self.connected = False
        self.log(f"Initializing KnobBoxModbus with port: {port}", LogLevel.DEBUG)

        # Initialize Modbus client without 'method' parameter
        self.client = ModbusClient(
            port=port,
            baudrate=baudrate,
            parity=parity,
            stopbits=stopbits,
            bytesize=bytesize,
            timeout=timeout,
            retries=2
        )

        if self.debug_mode:
            self.log("Debug Mode: Modbus communication details will be outputted.", LogLevel.DEBUG)
    
    def start_reading_power_supply_data(self):
        """Start threads for continuously reading data for each power supply."""
        if not self.connect():
            self.log("Cannot start reading power supply data - connection failed", LogLevel.ERROR)
            return False
            
        self.threads = []  # Should clear old threads first
        self.stop_event.clear()
        
        for unit in self.UNIT_NUMBERS:
            if self.stop_event.is_set():
                break
                
            thread = threading.Thread(
                target=self.read_power_supply_data_continuously,
                args=(unit,),
                name=f"PowerSupplyReader-Unit{unit}",
                daemon=True
            )
        
            thread.start()
            self.threads.append(thread)
            self.log(f"Started thread for unit {unit}", LogLevel.DEBUG)
            time.sleep(0.1)  # Small delay between thread starts
            
        self.is_initialized.set()
        return True
    
    def read_power_supply_data_continuously(self, unit):
        """Continuously read voltage, current, and output status for a specific power supply unit."""
        while not self.stop_event.is_set():
            try:
                # Read data for each and update the respective lists
                data = self.batch_read_registers(unit)
                if data:
                    self.update_data_states(unit, data)
                else:
                    self.log(f"Failed to read data for unit {unit}", LogLevel.WARNING)
                    time.sleep(1)  # Wait before retrying
                    continue

                time.sleep(.5)  # small delay between reads
            except Exception as e:
                self.log(f"Error reading power supply data for unit {unit}: {str(e)}", LogLevel.ERROR)
                time.sleep(1)  # Wait before retrying
        
    def batch_read_registers(self, unit):
        """Read all registers for a specific power supply unit in a single Modbus transaction."""
        attempts = 0
        while attempts < self.MAX_ATTEMPTS:
            try:
                with self.modbus_lock:
                    is_connected = self.check_connection()
                    if not is_connected:
                        self.log(f"Modbus not connected when batch reading registers for unit {unit}", LogLevel.ERROR)
                        attempts += 1
                        time.sleep(0.1)
                        continue

                # READ MULTIPLE REGISTERS: THIS NEEDS TO BE VERIFIED WITH TIANRUI FIRMWARE
                response = self.client.read_holding_registers(
                    address = self.OUTPUT_STATUS_ADDRESS,
                    count = 4, # Number of registers to read (status, set voltage, actual voltage, actual current) assuming registers are contiguous
                    slave = unit
                )

                if response and not response.isError():
                    self.connected = True
                    return {
                        "output_status": response.registers[0],
                        "set_voltage": response.registers[1] / 10.0,
                        "actual_voltage": response.registers[2] / 10.0,
                        "actual_current": response.registers[3] / 10.0
                    }
                
                self.log(f"Error batch reading registers from unit {unit}: {response}", LogLevel.ERROR)
                attempts += 1
            except Exception as e:
                self.log(f"Error batch reading registers for unit {unit}: {str(e)}", LogLevel.ERROR)
                attempts += 1
                time.sleep(0.1)
                continue
        return None
    
    def update_data_states(self, unit, data):
        """Update all data states for a specific power supply unit."""
        try:
            with self.modbus_lock:
                idx = unit - 1
                self.output_statuses[idx] = data['output_status']
                self.set_voltages[idx] = data['set_voltage']
                self.actual_voltages[idx] = data['actual_voltage']
                self.actual_currents[idx] = data['actual_current']
        except Exception as e:
            self.log(f"Error updating data states for unit {unit}: {str(e)}", LogLevel.ERROR)

    def check_connection(self):
        """Check if the Modbus client is connected and attempt to reconnect if not."""
        if self.client.is_socket_open():
            return True
        else:
            try:
                if self.client.connect():
                    time.sleep(0.1)  # Small delay to ensure connection stability
                    if hasattr(self.client, 'socket'):
                        self.client.socket.reset_input_buffer()
                    return True
                else:
                    self.log(f"Failed to reconnect to {self.port}", LogLevel.ERROR)
                    self.connected = False
                    return False
            except Exception as e:
                self.log(f"Error reconnecting to {self.port}: {str(e)}", LogLevel.ERROR)
                self.connected = False
                return False

    def stop_reading(self):
        """Stop all reading threads and disconnect from the Modbus device."""
        self.stop_event.set()
        for thread in self.threads:
            thread.join(timeout=2)

        self.threads.clear()
        self.disconnect()

        self.is_initialized.clear()

    def connect(self):
        """
        Connect to the Modbus device. Opens the serial connection if not already open.
        
        Returns:
            bool: True if connected successfully, False otherwise.
        """
        with self.modbus_lock:
            try:
                if self.client.is_socket_open():
                    self.connected = True
                    self.log("Modbus client already connected.", LogLevel.DEBUG)
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
                if self.client.is_socket_open():
                    self.client.close()
                    self.log("Disconnected from the Knob Box Modbus device.", LogLevel.INFO)
                else:
                    self.log("Client already disconnected from Knob Box Modbus device", LogLevel.INFO)
            except Exception as e:
                self.log(f"Error in disconnect: {str(e)}", LogLevel.ERROR)

    def log(self, message, level=LogLevel.INFO):
        if self.logger:
            self.logger.log(message, level)
        else:
            print(f"{level.name}: {message}")