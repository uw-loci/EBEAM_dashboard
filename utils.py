import serial
import sys
import tkinter as tk

class ApexMassFlowController:
    def __init__(self, serial_port='COM8', baud_rate=19200): 
        self.serial_port = serial_port
        self.baud_rate = baud_rate
        self.ser = None

    def open_serial_connection(self):
        try:
            self.ser = serial.Serial(self.serial_port, self.baud_rate)
            print("Apex MC Serial connection established.")
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
            print(f"Configured Apex MC unit ID from {current_id} to {desired_id}. Response: {response}")

    def tare_flow(self):
        if self.ser:
            self.ser.write(b"av\n")

    def tare_absolute_pressure(self):
        if self.ser:
            self.ser.write("pc\n")

    def command_setpoint(self, setpoint):
        pass  # TODO: Add code to command new setpoint here

class MessagesFrame:
    def __init__(self, parent):
        self.frame = tk.Frame(parent, borderwidth=2, relief="solid")
        self.frame.pack(fill=tk.BOTH, expand=True)  # Make sure it expands and fills space
        
        # Add a title to the Messages & Errors frame
        label = tk.Label(self.frame, text="Messages & Errors", font=("Helvetica", 16, "bold"))
        label.pack(pady=10, fill=tk.X)
        
        self.text_widget = tk.Text(self.frame, wrap=tk.WORD)
        self.text_widget.pack(fill=tk.BOTH, expand=True)  # Fill the frame entirely

        # Redirect stdout to the text widget
        self.stdout = sys.stdout
        sys.stdout = TextRedirector(self.text_widget, "stdout")

    def write(self, msg):
        self.text_widget.insert(tk.END, msg)

    def flush(self):
        pass  # Needed for compatibility

class TextRedirector:
    def __init__(self, widget, tag="stdout"):
        self.widget = widget
        self.tag = tag

    def write(self, msg):
        self.widget.insert(tk.END, msg, (self.tag,))
        self.widget.see(tk.END)  # Scroll to the end

    def flush(self):
        pass  # Needed for compatibility