# vtrx.py
import tkinter as tk
from tkinter import messagebox
import datetime
import serial
import threading
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import time
import os
import sys

def resource_path(relative_path):
    """ Get the absolute path to a resource, works for development and when running as bundled executable"""
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

class VTRXSubsystem: 
    MAX_POINTS = 20 # Maximum number of points to display on the plot
    ERROR_CODES = {
        0: "VALVE CONTENTION",
        1: "COLD CATHODE FAILURE",
        2: "MICROPIRANI FAILURE",
        3: "UNEXPECTED PRESSURE ERROR",
        4: "SAFETY RELAY ERROR",
        5: "ARGON GATE VALVE ERROR",
        6: "TURBO GATE VALVE ERROR",
        7: "VENT VALVE OPEN ERROR",
        8: "PRESSURE NACK ERROR",
        9: "PRESSURE SENSE ERROR",
        10: "PRESSURE UNIT ERROR",
        11: "USER TAG NACK ERROR",
        12: "RELAY NACK ERROR",
        13: "PRESSURE DOSE WARNING",
        14: "TURBO GATE VALVE WARNING",
        15: "TURBO ROTOR ON WARNING",
        16: "UNSAFE FOR HV WARNING"
    }

    def __init__(self, parent, serial_port='COM7', baud_rate=9600, messages_frame=None):
        self.parent = parent
        self.serial_port = serial_port
        self.baud_rate = baud_rate
        self.messages_frame = messages_frame
        self.x_data = []
        self.y_data = []
        self.indicators = {
            0: tk.PhotoImage(file=resource_path("media/off.png")),
            1: tk.PhotoImage(file=resource_path("media/on.png"))
        }
        self.error_state = False
        self.setup_serial()
        self.setup_gui()

        self.time_window = 100 # Time window in seconds
        self.data_timeout = 1.5 # Seconds timeout for receiving data
        self.init_time = datetime.datetime.now()
        self.x_data = [self.init_time + datetime.timedelta(seconds=i) for i in range(self.time_window)]
        self.y_data = [0] * self.time_window

        if self.ser is not None:
            self.start_serial_thread()

    def setup_serial(self):
        try:
            self.ser = serial.Serial(self.serial_port, self.baud_rate)
        except serial.SerialException as e:
            self.log_message(f"Error opening serial port {self.serial_port}: {e}")
            self.ser = None

    def read_serial(self):
        while True:
            try:
                # Read a line from the serial port
                data_bytes = self.ser.readline()
                self.last_data_received_time = time.time()  # Update last received time
                # Try to decode the bytes. Ignore or replace erroneous bytes to prevent crashes.
                data = data_bytes.decode('utf-8', errors='replace').strip()  # 'replace' will insert a � for bad bytes
                if data:
                    self.handle_serial_data(data)
            except serial.SerialException as e:
                self.log_message(f"Serial read error: {e}")
                self.error_state = True
            except UnicodeDecodeError as e:
                self.log_message(f"Unicode decode error: {e}")
                self.error_state = True
            except Exception as e:
                self.log_message(f"Unexpected error: {e}")
                self.error_state = True

            # Check for timeout
            if time.time() - self.last_data_received_time > self.data_timeout:
                self.error_state = True
                self.log_message("Error: No data received within the timeout period.")
                self.update_gui_with_error_state()

    def handle_serial_data(self, data):
        self.error_state = False
        data_parts = data.split(';')
        if len(data_parts) < 3:
            self.log_message("Incomplete data received.")
            self.error_state = True
            return
        
        try:
            pressure_value = float(data_parts[0])   # numerical pressure value
            pressure_raw = data_parts[1]            # raw string from 972b sensor
            switch_states_binary = data_parts[2]    # binary state switches
            switch_states = [int(bit) for bit in f"{int(switch_states_binary, 2):08b}"] # Ensures it's 8 bits long

            if len(data_parts) > 3: # Handle errors
                errors = data_parts[3:] # All subsequent parts are errors
                for error in errors:
                    if error.startswith("972b ERR:"):
                        error_code, error_message = error.split(":")[1:]
                        self.log_message(f"VTRX Err {error_code}: Actual:{error_message}")
                        self.error_state = True

            self.parent.after(0, lambda: self.update_gui(
                pressure_value, 
                pressure_raw, 
                switch_states)
            )
        
        except ValueError as e:    
            self.log_message(f"Error processing incoming data: {e}")
            self.error_state = True

    def log_message(self, message):
        if self.messages_frame:
            self.messages_frame.log_message(message)
        else:
            print(message)

    def setup_gui(self):
            layout_frame = tk.Frame(self.parent)
            layout_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

            # Formatting status indicators
            switches_frame = tk.Frame(layout_frame, width=135)
            switches_frame.pack(side=tk.LEFT, fill=tk.Y, padx=5) 

            # Setup labels for each switch
            switch_labels = [
                "Pumps Power On ", "Turbo Rotor ON ", "Turbo Vent Open ",
                "972b Power On ", "Turbo Gate Valve Open ",
                "Turbo Gate Valve Closed ", "Argon Gate Valve Closed ", "Argon Gate Valve Open "
            ]
            self.labels = []
            label_width = 17
            for switch in switch_labels:
                label = tk.Label(switches_frame, text=switch, image=self.indicators[0], compound='right', anchor='e', width=label_width)
                label.pack(anchor="e", pady=2, fill='x')
                self.labels.append(label)

            # Pressure label setup
            # Increase font size and make it bold
            self.label_pressure = tk.Label(switches_frame, text="No data...", anchor='e', width=label_width,
                                        font=('Helvetica', 11, 'bold'))
            self.label_pressure.pack(anchor="e", pady=1, fill='x')

            self.reset_button = tk.Button(switches_frame, text="Reset VTRX", command=self.confirm_reset)
            self.reset_button.pack(side=tk.LEFT, padx=5, pady=1)
            self.clear_button = tk.Button(switches_frame, text="Clear Plot", command=self.clear_graph)
            self.clear_button.pack(side=tk.LEFT, padx=5, pady=1)

            # Add button to clear display output
            #self.btn_clear_graph = tk.Button(switches_frame, text="Clear Plot", command=self.confirm_clear)
            #self.btn_clear_graph.pack(pady=10)

            # Plot frame
            plot_frame = tk.Frame(layout_frame)
            plot_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=1) 
            self.fig, self.ax = plt.subplots()
            self.fig.subplots_adjust(left=0.15, right=0.95, top=0.88, bottom=0.14) 
            self.line, = self.ax.plot(self.x_data, self.y_data, 'g-')
            self.ax.set_xlabel('Time', fontsize=8)
            self.ax.set_ylabel('Pressure [mbar]', fontsize=8)
            self.ax.set_title('Live Pressure Readout', fontsize=10)
            self.ax.set_yscale('log')
            self.ax.set_ylim(1e-6, 1200.0)
            self.ax.tick_params(axis='x', labelsize=6)
            self.ax.grid(True)

            self.canvas = FigureCanvasTkAgg(self.fig, master=plot_frame)
            self.canvas.draw()
            self.canvas_widget = self.canvas.get_tk_widget()
            self.canvas_widget.pack(fill=tk.BOTH, expand=True)
    
    def update_gui(self, pressure_value, pressure_raw, switch_states):
        current_time = datetime.datetime.now()
        self.label_pressure.config(text=f"Press: {pressure_raw} mbar", fg="red" if self.error_state else "black")

        # Update each switch indicator
        for idx, state in enumerate(switch_states):
            label = self.labels[idx]
            label.config(image=self.indicators[state])

        # Calculate elapsed time from the initial time
        elapsed_time = (current_time - self.init_time).total_seconds()

        if elapsed_time > self.time_window:
            # Shift the data window: remove the oldest data point and add the new one
            self.x_data.pop(0)
            self.y_data.pop(0)
            self.x_data.append(current_time)
            self.y_data.append(pressure_value)
            # Update the initial time to the start of the current window
            self.init_time = self.x_data[0]
        else:
            # If still within the initial window, just append the new data
            self.x_data.append(current_time)
            self.y_data.append(pressure_value)

        # Update the plot to reflect the new data
        self.update_plot()

    def update_plot(self):
        self.line.set_data(self.x_data, self.y_data)
        self.ax.set_xlim(self.x_data[0], self.x_data[-1])
        
        if self.error_state:
            self.line.set_color('red')  # Set the line color to red if there is an error
            self.ax.set_title('Live Pressure Readout (Error)', fontsize=10, color='red')
        else:
            self.line.set_color('green')  # Set the line color to green if there is no error
            self.ax.set_title('Live Pressure Readout', fontsize=10, color='black')

        self.ax.relim()
        self.ax.autoscale_view()
        self.canvas.draw()

    def start_serial_thread(self):
        thread = threading.Thread(target=self.read_serial)
        thread.daemon = True
        thread.start()

    def confirm_reset(self):
        if messagebox.askyesno("Confirm Reset", "Do you really want to reset the VTRX System?"):
            self.send_reset_command()

    def send_reset_command(self):
        try:
            self.ser.write("RESET\n".encode('utf-8')) # Send RESET command to Arduino
            self.log_message("Sent RESET command to VTRX.")
        except serial.SerialException as e:
            messagebox.showerror("Error", f"Failed to send reset command: {str(e)}")
            print(f"Serial execution {str(e)}")

    def clear_graph(self):
        # Clear the plot as defined in the original setup...
        self.line.set_data([], [])
        self.ax.relim()
        self.ax.autoscale_view()
        self.canvas.draw()
        self.x_data = [datetime.datetime.now() + datetime.timedelta(seconds=i) for i in range(self.time_window)]
        self.y_data = [0] * len(self.x_data)
        self.init_time = self.x_data[0]

