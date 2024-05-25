# subsystem.py
import tkinter as tk
from tkinter import font as tkFont
from tkdial import Meter
import time
import serial
import threading
import random
from utils import ApexMassFlowController
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize

# TODO: handling lack of pressure response -- reset live plot
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

    def __init__(self, parent, serial_port='COM7', baud_rate=9600):
        self.parent = parent
        self.serial_port = serial_port
        self.baud_rate = baud_rate
        self.x_data = []
        self.y_data = []
        self.indicators = {0: tk.PhotoImage(file="media/off.png"),
                           1: tk.PhotoImage(file="media/on.png")}
        self.error_state = False
        self.setup_serial()
        self.setup_gui()

        self.time_window = 300 # Time window in seconds
        self.init_time = time.time()
        self.x_data = [self.init_time + i for i in range(self.time_window)]
        self.y_data = [0] * self.time_window

        if self.ser is not None:
            self.start_serial_thread()

    def setup_serial(self):
        try:
            self.ser = serial.Serial(self.serial_port, self.baud_rate)
        except serial.SerialException as e:
            print(f"Error opening serial port {self.serial_port}: {e}")
            self.ser = None

    def read_serial(self):
        while True:
            try:
                # Read a line from the serial port
                data_bytes = self.ser.readline()
                # Try to decode the bytes. Ignore or replace erroneous bytes to prevent crashes.
                data = data_bytes.decode('utf-8', errors='replace').strip()  # 'replace' will insert a � for bad bytes
                if data:
                    self.handle_serial_data(data)
            except serial.SerialException as e:
                self.report_error_to_messages(f"Serial read error: {e}")
            except UnicodeDecodeError as e:
                self.report_error_to_messages(f"Unicode decode error: {e}")

    def handle_serial_data(self, data):
        self.error_state = False
        data_parts = data.split(';')
        if len(data_parts) < 3:
            self.report_error_to_messages("Incomplete data received.")
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
                        error_description = self.ERROR_CODES.get(error_code, "Unknown Error")
                        self.report_error_to_messages(f"Error {error_code}: Actual:{error_message}")
                        self.error_state = True

            self.parent.after(0, lambda: self.update_gui(
                pressure_value, 
                pressure_raw, 
                switch_states, 
                self.error_state)
            )
        
        except ValueError as e:    
            self.report_error_to_messages(f"Error processing incoming data: {e}")
            self.error_state = True

    def report_error_to_messages(self, message):
        if hasattr(self, 'messages_frame'):
            self.messages_frame.write(message + "\n")
        else:
            print(message) # Fallback to console if messages_frame is unavailable

    def update_gui(self, pressure_value, pressure_raw, switch_states, error_state):
        current_time = time.time()
        self.label_pressure.config(text=f"Press: {pressure_raw} mbar", fg="red" if self.error_state else "black")

        # Update each switch indicator
        for idx, state in enumerate(switch_states):
            label = self.labels[idx]
            label.config(image=self.indicators[state])

        # Calculate elapsed time from the initial time
        elapsed_time = current_time - self.init_time

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

    def setup_gui(self):
        layout_frame = tk.Frame(self.parent)
        layout_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Formatting status indicators
        switches_frame = tk.Frame(layout_frame, width=155)
        switches_frame.pack(side=tk.LEFT, fill=tk.Y, padx=15) 

        # Setup labels for each switch
        switch_labels = [
            "Pumps Power On ", "Turbo Rotor ON ", "Turbo Vent Open ",
            "972b Power On ", "Turbo Gate Valve Open ",
            "Turbo Gate Valve Closed ", "Argon Gate Valve Closed ", "Argon Gate Valve Open "
        ]
        self.labels = []
        label_width = 15
        for switch in switch_labels:
            label = tk.Label(switches_frame, text=switch, image=self.indicators[0], compound='right', anchor='e', width=label_width)
            label.pack(anchor="e", pady=2, fill='x')
            self.labels.append(label)

        # Pressure label setup
        # Increase font size and make it bold
        self.label_pressure = tk.Label(switches_frame, text="Waiting for pressure data...", anchor='e', width=label_width,
                                    font=('Helvetica', 12, 'bold'))
        self.label_pressure.pack(anchor="e", pady=10, fill='x')

        # Plot frame
        plot_frame = tk.Frame(layout_frame)
        plot_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=1) 
        self.fig, self.ax = plt.subplots()
        self.line, = self.ax.plot(self.x_data, self.y_data, 'g-')
        self.ax.set_xlabel('Time')
        self.ax.set_ylabel('Pressure [mbar]')
        title_color = "red" if self.error_state else "green"
        self.ax.set_title('Live Pressure Readout', fontsize=10)
        self.ax.set_yscale('log')
        self.ax.set_ylim(1e-6, 1200.0)
        self.canvas = FigureCanvasTkAgg(self.fig, master=plot_frame)
        self.canvas.draw()
        self.canvas_widget = self.canvas.get_tk_widget()
        self.canvas_widget.pack(fill=tk.BOTH, expand=True)

class EnvironmentalSubsystem:
    def __init__(self, parent):
        self.parent = parent
        self.thermometers = ['Solenoid 1', 'Solenoid 2', 'Chmbr Bot', 'Chmbr Top', 'Air temp']
        self.temperatures = {name: (random.uniform(60, 90) if 'Solenoid' in name else random.uniform(50, 70)) for name in self.thermometers}

        self.setup_gui()
        self.update_temperatures()

    def setup_gui(self):
        self.fig, self.axs = plt.subplots(1, len(self.thermometers), figsize=(15, 5))
        self.bars = []

        bar_width = 0.5  # Make the bars skinnier

        for ax, name in zip(self.axs, self.thermometers):
            ax.set_title(name, fontsize=6)
            ax.set_ylim(0, 100)
            bar = ax.bar(name, self.temperatures[name], width=bar_width)
            ax.set_xticks([])
            ax.set_xticklabels([])
            self.bars.append(bar)

            # Set the x-axis limits to make sure bars are centered and skinny
            ax.set_xlim(-1, 1)

        self.fig.subplots_adjust(left=0.10, right=0.90, top=0.90, bottom=0.10, wspace=1.0)  # Add padding around the figure
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.parent)
        self.canvas.draw()
        self.canvas_widget = self.canvas.get_tk_widget()
        self.canvas_widget.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

    def get_color(self, temperature):
        norm = Normalize(vmin=20, vmax=100)
        cmap = plt.get_cmap('coolwarm')
        return cmap(norm(temperature))

    def update_temperatures(self):
        for i, name in enumerate(self.thermometers):
            offset = 30 if 'Solenoid' in name else 0
            new_temp = random.uniform(30 + offset, 33 + offset)
            self.temperatures[name] = new_temp
            self.bars[i][0].set_height(new_temp)

            # Update the color of the bar based on the temperature
            self.bars[i][0].set_color(self.get_color(new_temp))

        self.canvas.draw()
        self.parent.after(1000, self.update_temperatures)


class ArgonBleedControlSubsystem:
    def __init__(self, parent, serial_port='COM8', baud_rate=19200):
        self.parent = parent
        self.controller = ApexMassFlowController(serial_port, baud_rate)
        self.setup_gui()

    def configure_controller(self):
        # Open serial connection
        self.controller.open_serial_connection()
        
        # Configure unit ID
        self.controller.configure_unit_id('A', 'B')

        # Close serial connection when done
        self.controller.close_serial_connection()
        
    def setup_gui(self):

        # Add "Tare Flow" button
        self.tare_flow_button = tk.Button(self.parent, text="Tare Flow", command=self.tare_flow)
        self.tare_flow_button.pack()

        # Add "Tare Absolute Pressure" button
        self.tare_pressure_button = tk.Button(self.parent, text="Tare Absolute Pressure", command=self.tare_absolute_pressure)
        self.tare_pressure_button.pack()

    def tare_flow(self):
        # Perform taring flow action when "Tare Flow" button is pressed
        self.controller.tare_flow()
        print("Apex MF Ctrl:Taring flow performed successfully.")

        # Update GUI or perform any other necessary actions

    def tare_absolute_pressure(self):
        # Perform taring absolute pressure action when "Tare Absolute Pressure" button is pressed
        self.controller.tare_absolute_pressure()
        print("Apex MF Ctrl:Taring absolute pressure performed successfully.")

        # Update GUI or perform any other necessary actions

    def start_simulation(self):
        # Start a simulation to update the GUI periodically
        self.update_gui()

    def update_gui(self):
        # Update GUI elements with simulated data
        # Replace this with actual functionality
        # For example, updating labels, graphs, etc.
        print("Updating GUI...")

        # Schedule the next update after a delay (in milliseconds)
        self.parent.after(1000, self.update_gui)

class InterlocksSubsystem:
    def __init__(self, parent):
        self.parent = parent
        self.interlock_status = {
            "Vacuum": True, "Water": False, "Door": False, "Timer": True,
            "Oil High": False, "Oil Low": False, "E-stop Ext": True,
            "E-stop Int": True, "G9SP Active": True
        }
        self.setup_gui()

    def setup_gui(self):
        self.interlocks_frame = tk.Frame(self.parent)
        self.interlocks_frame.pack(fill=tk.BOTH, expand=True)

        interlock_labels = [
            "Vacuum", "Water", "Door", "Timer", "Oil High",
            "Oil Low", "E-stop Ext", "E-stop Int", "G9SP Active"
        ]
        self.indicators = {
            'active': tk.PhotoImage(file="media/off_orange.png"),
            'inactive': tk.PhotoImage(file="media/on.png")
        }

        for label in interlock_labels:
            frame = tk.Frame(self.interlocks_frame)
            frame.pack(side=tk.LEFT, expand=True, padx=5)

            lbl = tk.Label(frame, text=label, font=("Helvetica", 8))
            lbl.pack(side=tk.LEFT)
            status = self.interlock_status[label]
            indicator = tk.Label(frame, image=self.indicators['active'] if status else self.indicators['inactive'])
            indicator.pack(side=tk.RIGHT, pady=1)
            frame.indicator = indicator  # Store reference to the indicator for future updates

    def update_interlock(self, name, status):
        if name in self.parent.children:
            frame = self.parent.children[name]
            indicator = frame.indicator
            new_image = self.indicators['active'] if status else self.indicators['inactive']
            indicator.config(image=new_image)
            indicator.image = new_image  # Keep a reference

    def update_pressure_dependent_locks(self, pressure):
        # Disable the Vacuum lock if pressure is below 2 mbar
        self.update_interlock("Vacuum", pressure >= 2)

class OilSystem:
    def __init__(self, parent):
        self.parent = parent
        self.setup_gui()

    def setup_gui(self):
        self.frame = tk.Frame(self.parent)
        self.frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Create and configure the dial
        self.oil_dial = Meter(
            self.frame, 
            start=0,             # Start value of the meter
            end=10,              # End value of the meter
            radius=150,          # Radius of the dial
            width=300,           # Width of the widget
            height=200,          # Height of the widget
            start_angle=180,     # Start angle for the half-circle
            end_angle=-180,      # End angle for the half-circle (full sweep of 180 degrees)
            text=" Oil Press", # Text displayed on the dial
            text_color="black",  # Color of the text
            major_divisions=10,  # Major divisions in the dial
            minor_divisions=1,   # Minor divisions between major divisions
            scale_color="black", # Color of the scale markings
            needle_color="red",  # Color of the needle
            bg='white',          # Background color
            fg='light grey',      # Foreground color of the dial face
            text_font=tkFont.Font(family="Helvetica", size=8, weight="bold")
        )
        self.oil_dial.pack(padx=1, pady=1)


    def update_oil_pressure(self, new_pressure):
        """Update the dial to reflect new oil pressure readings."""
        if 0 <= new_pressure <= 10:  # Ensure the value is within the valid range
            self.oil_dial.set(new_pressure)
        else:
            print("Received out-of-range oil pressure value:", new_pressure)

    def read_sensor_data(self):
        """Simulate reading from a sensor."""
        # TODO: Implement this
        import random
        new_pressure = random.randint(0, 100)  # Random pressure value for demonstration
        self.update_oil_pressure(new_pressure)
        self.parent.after(1000, self.update_oil_pressure, new_pressure)  # Schedule the update