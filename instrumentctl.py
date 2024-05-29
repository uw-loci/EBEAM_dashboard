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