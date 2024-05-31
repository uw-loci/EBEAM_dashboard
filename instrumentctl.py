# instrumentctl.py
import serial


class ApexMassFlowController:
    def __init__(self, serial_port='COM8', baud_rate=19200, messages_frame=None): 
        self.serial_port = serial_port
        self.baud_rate = baud_rate
        self.ser = None
        self.messages_frame = messages_frame

    def open_serial_connection(self):
        try:
            self.ser = serial.Serial(self.serial_port, self.baud_rate)
            self.log_message("Apex MC Serial connection established.")
        except serial.SerialException as e:
            print(f"Error opening Apex MC serial port {self.serial_port}: {e}")
            self.ser = None

    def close_serial_connection(self):
        if self.ser is not None and self.ser.is_open:
            self.ser.close()
            print("Apex MC Serial connection closed.")

    def configure_unit_id(self, current_id, desired_id):
        if self.ser is not None and self.ser.is_open:
            command = f"{current_id}@={desired_id}\x0D"
            self.ser.write(command.encode())
            response = self.ser.readline().decode().strip()
            self.log_message(f"Configured Apex MC unit ID from {current_id} to {desired_id}. Response: {response}")
            return response

    def tare_flow(self):
        if self.ser:
            command = "av\n"
            self.ser.write(command.encode())
            response = self.ser.readline().decode().strip()
            self.log_message(f"Tare flow response: {response}")
            return response

    def tare_absolute_pressure(self):
        if self.ser:
            command = "pc\n"
            self.ser.write(command.encode())
            response = self.ser.readline().decode().strip()
            self.log_message(f"Tare absolute pressure response: {response}")
            return response
        
    def poll_live_data_frame(self, unit_id):
        if self.ser:
            command = f"{unit_id}\n"
            self.ser.write(command.encode())
            response = self.ser.readline().decode().strip()
            self.log_message(f"Live data frame: {response}")
            return response

    def begin_streaming_data(self, unit_id):
        if self.ser:
            command = f"{unit_id}@=@\n"
            self.ser.write(command.encode())
            response = self.ser.readline().decode().strip()
            self.log_message(f"Begin streaming data response: {response}")
            return response

    def stop_streaming_data(self, desired_id):
        if self.ser:
            command = f"@@={desired_id}\n"
            self.ser.write(command.encode())
            response = self.ser.readline().decode().strip()
            self.log_message(f"Stop streaming data response: {response}")
            return response
    def set_streaming_interval(self, unit_id, interval_ms):
            if self.ser:
                command = f"{unit_id}w91={interval_ms}\n"
                self.ser.write(command.encode())
                response = self.ser.readline().decode().strip()
                self.log_message(f"Set streaming interval response: {response}")
                return response

    def command_setpoint(self, unit_id, setpoint):
        if self.ser:
            if isinstance(setpoint, float):
                command = f"{unit_id}s{setpoint}\n"
            else:
                command = f"{unit_id}{setpoint}\n"
            self.ser.write(command.encode())
            response = self.ser.readline().decode().strip()
            self.log_message(f"Setpoint command response: {response}")
            return response

    def hold_valves_current_position(self, unit_id):
        if self.ser:
            command = f"{unit_id}hp\n"
            self.ser.write(command.encode())
            response = self.ser.readline().decode().strip()
            self.log_message(f"Hold valves current position response: {response}")
            return response

    def hold_valves_closed(self, unit_id):
        if self.ser:
            command = f"{unit_id}hc\n"
            self.ser.write(command.encode())
            response = self.ser.readline().decode().strip()
            self.log_message(f"Hold valves closed response: {response}")
            return response

    def cancel_valve_hold(self, unit_id):
        if self.ser:
            command = f"{unit_id}c\n"
            self.ser.write(command.encode())
            response = self.ser.readline().decode().strip()
            self.log_message(f"Cancel valve hold response: {response}")
            return response

    def query_gas_list_info(self, unit_id):
        if self.ser:
            command = f"{unit_id}??g*\n"
            self.ser.write(command.encode())
            response = self.ser.readline().decode().strip()
            self.log_message(f"Gas list info: {response}")
            return response

    def choose_different_gas(self, unit_id, gas_number):
        if self.ser:
            command = f"{unit_id}g{gas_number}\n"
            self.ser.write(command.encode())
            response = self.ser.readline().decode().strip()
            self.log_message(f"Choose gas response: {response}")
            return response

    def new_composer_mix(self, unit_id, mix_name, mix_number, gases):
        if self.ser:
            gas_parts = ' '.join(f"{gas[0]} {gas[1]}" for gas in gases)
            command = f"{unit_id}gm {mix_name} {mix_number} {gas_parts}\n"
            self.ser.write(command.encode())
            response = self.ser.readline().decode().strip()
            self.log_message(f"New composer mix response: {response}")
            return response

    def delete_composer_mix(self, unit_id, mix_number):
        if self.ser:
            command = f"{unit_id}gd {mix_number}\n"
            self.ser.write(command.encode())
            response = self.ser.readline().decode().strip()
            self.log_message(f"Delete composer mix response: {response}")
            return response

    def query_live_data_info(self, unit_id):
        if self.ser:
            command = f"{unit_id}??d*\n"
            self.ser.write(command.encode())
            response = self.ser.readline().decode().strip()
            self.log_message(f"Live data info: {response}")
            return response

    def query_manufacturer_info(self, unit_id):
        if self.ser:
            command = f"{unit_id}??m*\n"
            self.ser.write(command.encode())
            response = self.ser.readline().decode().strip()
            self.log_message(f"Manufacturer info: {response}")
            return response

    def query_firmware_version(self, unit_id):
        if self.ser:
            command = f"{unit_id}??m9\n"
            self.ser.write(command.encode())
            response = self.ser.readline().decode().strip()
            self.log_message(f"Firmware version: {response}")
            return response

    def lock_display(self, unit_id):
        if self.ser:
            command = f"{unit_id}l\n"
            self.ser.write(command.encode())
            response = self.ser.readline().decode().strip()
            self.log_message(f"Lock display response: {response}")
            return response

    def unlock_display(self, unit_id):
        if self.ser:
            command = f"{unit_id}u\n"
            self.ser.write(command.encode())
            response = self.ser.readline().decode().strip()
            self.log_message(f"Unlock display response: {response}")
            return response

    def log_message(self, message):
        if self.messages_frame:
            self.messages_frame.log_message(message)
        else:
            print(message)

class PowerSupply9014:
    def __init__(self, port, baudrate=9600, timeout=1):
        self.ser = serial.Serial(port, baudrate, timeout=timeout)

    def send_command(self, command):
        """Send a command to the power supply and read the response."""
        try:
            self.ser.write(f"{command}\r".encode())
            response = self.ser.readline().decode().strip()
            return response
        except serial.SerialException as e:
            print(f"Serial error: {e}")
            return None

    def set_output(self, state):
        """Set the output on/off."""
        command = f"SOUT{state}"
        return self.send_command(command)

    def get_output_status(self):
        """Get the output status."""
        command = "GOUT"
        return self.send_command(command)

    def set_voltage(self, preset, voltage):
        """Set the output voltage."""
        command = f"VOLT{preset}{voltage}"
        return self.send_command(command)

    def set_current(self, preset, current):
        """Set the output current."""
        command = f"CURR{preset}{current}"
        return self.send_command(command)

    def set_over_voltage_protection(self, ovp):
        """Set the over voltage protection value."""
        command = f"SOVP{ovp}"
        return self.send_command(command)

    def get_display_readings(self):
        """Get the display readings for voltage and current mode."""
        command = "GETD"
        return self.send_command(command)

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
        return self.send_command(command)

    def get_preset_selection(self):
        """Get the current preset selection."""
        command = "GABC"
        return self.send_command(command)

    def set_preset_selection(self, preset):
        """Set the ABC select."""
        command = f"SABC{preset}"
        return self.send_command(command)

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
        self.ser.close()