import serial
import threading
import time
from utils import LogLevel
import os
import queue

class PowerSupply9104:
    MAX_RETRIES = 3 # 9104 display display reading attempts

    def __init__(self, port, baudrate=9600, timeout=3, logger=None, debug_mode=False):
        self.ser = serial.Serial(port, baudrate, timeout=timeout)
        self.debug_mode = debug_mode
        self.logger = logger
        self.command_queue = queue.Queue()
        self.worker_thread = threading.Thread(target=self._command_worker, daemon=True)
        self.worker_thread.start()
        
    def _command_worker(self):
        while True:
            try:
                command, args, callback = self.command_queue.get(block=True)
                result = getattr(self, command)(*args)
                if callback:
                    callback(result)
            except Exception as e:
                # self.log(f"Error in command worker: {str(e)}", LogLevel.ERROR)
                pass
            finally:
                self.command_queue.task_done()

    def enqueue_command(self, command, *args, callback=None):
        self.command_queue.put((command, args, callback))

    def is_connected(self):
        """Check if the serial connection is still active."""
        try:
            # Attempt to write a simple command to the device
            self.ser.write(b'\r')  # Send a carriage return
            # Try to read a response (there might not be one)
            self.ser.read(1)
            return True
        except serial.SerialException:
            return False

    def flush_serial(self):
        self.ser.reset_input_buffer()    

    def send_command(self, command):
        """Send a command to the power supply and read the response."""
        if self.debug_mode:
            return "Mock response based on " + command
        try:
            self.ser.write(f"{command}\r".encode())
            time.sleep(0.1) # allow small delay to let PS process command
            response = ""
            start_time = time.time()
            while True:
                line = self.ser.readline().decode().strip()
                if line:
                    response += line + "\n"
                    if "OK" in line or "ERROR" in line:
                        break
                if time.time() - start_time > 1:
                    break
            
            response = response.strip()
            if not response:
                raise ValueError("No response received from the device.")
            return response
        except serial.SerialException as e:
            # self.log(f"Serial error: {e}", LogLevel.ERROR)
            return None
        except ValueError as e:
            # self.log(f"Error processing response for command '{command}': {str(e)}", LogLevel.ERROR)
            return None

    def set_output(self, state):
        """Set the output on/off."""
        command = f"SOUT{state}"
        response = self.send_command(command)
        # self.log(f"Set output to {state}: {response}", LogLevel.DEBUG)
        return response

    def get_output_status(self):
        """Get the output status."""
        command = "GOUT"
        return self.send_command(command)

    def set_voltage(self, preset, voltage):
        """Set the output voltage. Assumes input voltage is in a form such as: 5.00"""
        formatted_voltage = int(voltage * 100)
        command = f"VOLT {preset}{formatted_voltage:04d}"
    
        response = self.send_command(command)
        # self.log(f"Raw command sent to preset {preset}: {command}", LogLevel.DEBUG)
        if response and response.strip() == "OK":
            # self.log(f"Voltage set to {voltage:.2f}V for preset {preset}: {response}", LogLevel.INFO)
            return True
        else:
            error_message = "No response" if response is None else response
            # self.log(f"Error setting voltage: {error_message}", LogLevel.ERROR)
            return False
    
    def set_current(self, preset, current):
        """Set the output current."""
        formatted_current = int(current * 100)
        command = f"CURR {preset}{formatted_current:04d}"
        response = self.send_command(command)
        if response and response.strip() == "OK":
            # self.log(f"Current set to {current:.2f}A for preset {preset}: {response}", LogLevel.INFO)
            return True
        else:
            error_message = "No response" if response is None else response
            # self.log(f"Error setting current: {error_message}", LogLevel.ERROR)
            return False

    def ramp_voltage(self, target_voltage, ramp_rate=0.01, callback=None):
        """
        Slowly ramp the voltage to the target voltage at the specified ramp rate.
        Runs in a separate thread to avoid blocking the GUI
        
        Args:
            target_voltage (float): The target voltage to reach in volts.
            ramp_rate (float): The rate at which to change the voltage in volts per second.
            callback (function): Optional function to call when ramping is complete.
        """        
        thread = threading.Thread(target=self._ramp_voltage_thread,
                                  args=(target_voltage, ramp_rate, callback))
        thread.start()

    def _ramp_voltage_thread(self, target_voltage, ramp_rate, callback):
        current_voltage = 0.0  # Starting voltage, adjust if you can fetch from the PSU.
        step_size = 0.1  # Voltage step in volts.
        step_delay = step_size / ramp_rate  # Delay in seconds.

        while current_voltage < target_voltage:
            next_voltage = min(current_voltage + step_size, target_voltage)
            if not self.set_voltage(1, next_voltage):  # Assume preset 1
                self.log(f"Failed to set voltage to {next_voltage:.2f}V.", LogLevel.ERROR)
                if callback:
                    callback(False)
                return
            time.sleep(step_delay)
            current_voltage = next_voltage

        self.log("Target voltage reached.", LogLevel.INFO)
        if callback:
            callback(True)

    def set_over_voltage_protection(self, ovp):
        """Set the over voltage protection value."""
        command = f"SOVP{ovp}"
        return self.send_command(command)

    def get_display_readings(self):
        """Get the display readings for voltage and current mode."""
        self.flush_serial()
        command = "GETD"
        # self.log(f"Sent command:{command}", LogLevel.DEBUG)
        return self.send_command(command)
    
    def parse_getd_response(self, response):
        try:
            # Remove all whitespace and split by 'OK'
            parts = response.replace('\r', '').replace('\n', '').split('OK')
            
            # Check if 'OK' is present in the response
            if len(parts) < 2:
                raise ValueError(f"Missing 'OK' in response: {response}")
            
            # The data should be in the first part
            data = parts[0].strip()
            data = data.lstrip('r')
            
            if len(data) != 9:
                raise ValueError(f"Invalid GETD data format: {data}")
                
            voltage = float(data[:4]) / 100.0
            current = float(data[4:8]) / 100.0
            mode = "CV Mode" if data[8] == "0" else "CC Mode"
            
            # self.log(f"Parsed GETD response: {voltage:.2f}V, {current:.2f}A, {mode}", LogLevel.DEBUG)
            return voltage, current, mode
        except Exception as e:
            # self.log(f"Error parsing GETD response: {response}. {e}", LogLevel.ERROR)
            return 0.0, 0.0, "Err"
    
    def get_voltage_current_mode(self):
        """
        Extract voltage and current from the power supply reading.
        
        Returns:
        (voltage, current, mode)
        """
        for attempt in range(self.MAX_RETRIES):
            reading = self.get_display_readings()
            if reading:
                # self.log(f"Raw GETD response (attempt {attempt + 1}): {reading}", LogLevel.DEBUG)
                voltage, current, mode = self.parse_getd_response(reading)
                if voltage is not None and current is not None:
                    return voltage, current, mode
            # self.log(f"Failed to get valid reading, attempt {attempt + 1}", LogLevel.WARNING)
            time.sleep(0.1)

        # self.log(f"Failed to get valid reading, attempt {attempt + 1}", LogLevel.WARNING)
        return None, None, "Err"

    def set_over_current_protection(self, ocp):
        """Set the over current protection value."""
        command = f"SOCP{ocp}"
        return self.send_command(command)

    def get_over_voltage_protection(self):
        """Get the upper limit of the output voltage."""
        command = "GOVP"
        return self.send_command(command)

    def get_over_current_protection(self):
        """Get the upper limit of the output current."""
        command = "GOCP"
        return self.send_command(command)

    def set_preset(self, preset, voltage, current):
        """Set the voltage and current for a preset."""
        command = f"SETD{preset}{voltage}{current}"
        return self.send_command(command)

    def get_settings(self, preset):
        """Get settings of a preset."""
        command = f"GETS{preset}"
        # Expected response: VVVVIIII
        response = self.send_command(command)
        return response.strip()

    def get_preset_selection(self):
        """Get the current preset selection."""
        command = "GABC"
        # self.log(f"Raw command sent: {command}", LogLevel.DEBUG)
        response = self.send_command(command)
        # self.log(f"Raw response received: {response}", LogLevel.DEBUG)
        if response:
            # self.log(f"Current preset selection: {response.strip()}", LogLevel.INFO)
            return response.strip()
        else:
            # self.log("Failed to get preset selection", LogLevel.ERROR)
            return None

    def set_preset_selection(self, preset):
        """Set the ABC select."""
        command = f"SABC{preset}"
        # self.log(f"Raw command sent: {command}", LogLevel.DEBUG)
        response = self.send_command(command)
        # self.log(f"Raw response received: {response}", LogLevel.DEBUG)
        if response and response.strip() == "OK":
            # self.log(f"Successfully set preset selection to {preset}", LogLevel.INFO)
            return True
        else:
            error_message = "No response" if response is None else response
            # self.log(f"Error setting preset selection: {error_message}", LogLevel.WARNING)
            return False

    def get_delta_time(self, index):
        """Get delta time setting value."""
        command = f"GDLT{index}"
        return self.send_command(command)

    def set_delta_time(self, index, time):
        """Set delta time."""
        command = f"SDLT{index}{time:02}"
        return self.send_command(command)

    def get_sw_time(self):
        """Get SW time."""
        command = "GSWT"
        return self.send_command(command)

    def set_sw_time(self, sw_time):
        """Set SW time."""
        command = f"SSWT{sw_time:03}"
        return self.send_command(command)

    def run_sw(self, first, end):
        """Run SW running."""
        command = f"RUNP{first}{end}"
        return self.send_command(command)

    def stop_sw(self):
        """Stop SW running."""
        command = "STOP"
        return self.send_command(command)

    def disable_keyboard(self):
        """Disable keyboard."""
        command = "SESS"
        return self.send_command(command)

    def enable_keyboard(self):
        """Enable keyboard."""
        command = "ENDS"
        return self.send_command(command)

    def get_all_information(self):
        """Get all information from the power supply."""
        command = "GALL"
        return self.send_command(command)

    def configure_presets(self, setv1, seti1, swtime1, setv2, seti2, swtime2, setv3, seti3, swtime3):
        """Configure presets for voltage, current, and SW time."""
        command = f"SETM{setv1:04}{seti1:04}{swtime1:03}{setv2:04}{seti2:04}{swtime2:03}{setv3:04}{seti3:04}{swtime3:03}"
        return self.send_command(command)

    def close(self):
        """Close the serial connection."""
        self.command_queue.join() # wait for all commands to complete
        self.ser.close()
        # self.log("Serial connection closed", LogLevel.INFO)

    def log(self, message, level=LogLevel.INFO):
        if self.logger:
            self.logger.log(message, level)
        else:
            print(f"{level.name}: {message}")