# subsystem.py
import tkinter as tk
from tkinter import ttk
from tkinter import font as tkFont
from tkdial import Meter
import datetime
import serial
import threading
import random
from instrumentctl import ApexMassFlowController
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
import matplotlib.dates as mdates
from matplotlib.dates import DateFormatter


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
        self.indicators = {0: tk.PhotoImage(file="media/off.png"),
                           1: tk.PhotoImage(file="media/on.png")}
        self.error_state = False
        self.setup_serial()
        self.setup_gui()

        self.time_window = 300 # Time window in seconds
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
                # Try to decode the bytes. Ignore or replace erroneous bytes to prevent crashes.
                data = data_bytes.decode('utf-8', errors='replace').strip()  # 'replace' will insert a � for bad bytes
                if data:
                    self.handle_serial_data(data)
            except serial.SerialException as e:
                self.log_message(f"Serial read error: {e}")
            except UnicodeDecodeError as e:
                self.log_message(f"Unicode decode error: {e}")

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
            self.label_pressure = tk.Label(switches_frame, text="Waiting for pressure data...", anchor='e', width=label_width,
                                        font=('Helvetica', 11, 'bold'))
            self.label_pressure.pack(anchor="e", pady=10, fill='x')

            # Add button to clear display output
            #self.btn_clear_graph = tk.Button(switches_frame, text="Clear Plot", command=self.confirm_clear)
            #self.btn_clear_graph.pack(pady=10)

            # Plot frame
            plot_frame = tk.Frame(layout_frame)
            plot_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=1) 
            self.fig, self.ax = plt.subplots()
            self.line, = self.ax.plot(self.x_data, self.y_data, 'g-')
            self.ax.set_xlabel('Time', fontsize=8)
            self.ax.set_ylabel('Pressure [mbar]', fontsize=8)
            title_color = "red" if self.error_state else "green"
            self.ax.set_title('Live Pressure Readout', fontsize=10)
            self.ax.set_yscale('log')
            self.ax.set_ylim(1e-6, 1200.0)
            self.ax.tick_params(axis='x', labelsize=6)
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
    
    def confirm_clear(self):
        if tk.messagebox.askyesno("Confirm Clear", "Do you really want to clear the graph?"):
            self.clear_graph()

    def clear_graph(self):
        # Clear the data lists
        self.x_data.clear()
        self.y_data.clear()
        
        # Reset the line data to an empty state
        self.line.set_data([], [])
        
        # Reset the axes to prepare for new data
        self.ax.cla()  # Clear the axis to remove old lines and texts
        self.ax.set_xlabel('Time', fontsize=8)
        self.ax.set_ylabel('Pressure [mbar]', fontsize=8)
        self.ax.set_yscale('log')
        self.ax.set_ylim(1e-6, 1200.0)
        now = datetime.datetime.now()
        self.ax.set_xlim(mdates.date2num(now), mdates.date2num(now + datetime.timedelta(seconds=self.time_window)))
        self.ax.set_title('Live Pressure Readout', fontsize=10, color='black' if not self.error_state else 'red')
        self.line, = self.ax.plot([], [], 'g-')

        # Redraw the canvas to reflect the cleared state
        self.canvas.draw()
        self.init_time = now
        # Since the data lists are empty now, reinitialize them when new data is added or received
        self.x_data = [now + datetime.timedelta(seconds=i) for i in range(self.time_window)]
        self.y_data = [0] * len(self.x_data)

    

class EnvironmentalSubsystem:
    def __init__(self, parent, messages_frame=None):
        self.parent = parent
        self.messages_frame = messages_frame
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
        self.parent.after(500, self.update_temperatures)


class VisualizationGasControlSubsystem:
    def __init__(self, parent, serial_port='COM8', baud_rate=19200, messages_frame=None):
        self.parent = parent
        self.controller = ApexMassFlowController(serial_port, baud_rate, messages_frame=messages_frame)
        self.messages_frame = messages_frame
        self.setup_gui()

    def configure_controller(self): # TODO write this
        # Open serial connection
        self.controller.open_serial_connection()
        
        # Configure unit ID
        self.controller.configure_unit_id('A', 'B')

        # Close serial connection when done
        self.controller.close_serial_connection()
        
    def setup_gui(self):
        self.notebook = ttk.Notebook(self.parent)
        self.notebook.pack(fill='both', expand=True)

        # Setup Tab
        self.setup_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.setup_tab, text='Setup')
        self.setup_setup_tab()

        # Tare Tab
        self.tare_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.tare_tab, text='Tare')
        self.setup_tare_tab()

        # Control Tab
        self.control_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.control_tab, text='Control')
        self.setup_control_tab()

        # COMPOSER Tab
        self.composer_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.composer_tab, text='GAS COMPOSER')
        self.setup_composer_tab()

        # Misc Tab
        self.misc_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.misc_tab, text='Misc')
        self.setup_misc_tab()
    
    def update_gui(self):
            # Schedule the next update after a delay (in milliseconds)
            self.parent.after(500, self.update_gui)

    def tare_flow(self):
        # Perform taring flow action when "Tare Flow" button is pressed
        self.controller.tare_flow()
        self.messages_frame.log_message("Apex MassFlow:Tare flow success.")

        # Update GUI or perform any other necessary actions

    def tare_absolute_pressure(self):
        # Perform taring absolute pressure action when "Tare Absolute Pressure" button is pressed
        self.controller.tare_absolute_pressure()
        self.messages_frame.log_message("Apex MassFlow:Tar abs pressure success.")

    def setup_setup_tab(self):
        ttk.Label(self.setup_tab, text="Apex Mass Flow Controller Setup").grid(row=0, column=0, columnspan=2, padx=10, pady=10)

        # Frame for buttons
        button_frame = ttk.Frame(self.setup_tab)
        button_frame.grid(row=1, column=0, padx=10, pady=5, sticky='n')

        # Frame for dropdown and live data
        input_frame = ttk.Frame(self.setup_tab)
        input_frame.grid(row=1, column=1, padx=1, pady=5, sticky='n')

        # Add buttons to the button frame
        self.unit_id_button = ttk.Button(button_frame, text="Change Unit ID", command=self.set_unit_id)
        self.unit_id_button.pack(padx=5, pady=5, anchor='w')

        self.poll_data_button = ttk.Button(button_frame, text="Poll Live Data Frame", command=self.poll_live_data)
        self.poll_data_button.pack(padx=5, pady=5, anchor='w')

        # Add dropdown and live data text to the input frame
        self.unit_id_var = tk.StringVar()
        self.unit_id_dropdown = ttk.Combobox(input_frame, textvariable=self.unit_id_var, values=[chr(i) for i in range(65, 91)], width=5)  # A-Z
        self.unit_id_dropdown.pack(padx=5, pady=7, anchor='w')

        self.live_data_var = tk.StringVar()
        self.live_data_label = ttk.Label(input_frame, textvariable=self.live_data_var)
        self.live_data_label.pack(padx=5, pady=7, anchor='w')

        # Add button and text entry to set streaming interval
        self.set_interval_button = ttk.Button(button_frame, text="Set Streaming Interval", command=self.set_streaming_interval)
        self.set_interval_button.pack(padx=5, pady=5, anchor='w')

        self.streaming_interval_var = tk.StringVar()
        self.streaming_interval_entry = ttk.Entry(input_frame, textvariable=self.streaming_interval_var, width=10)
        self.streaming_interval_entry.pack(padx=5, pady=7, anchor='w')


    def set_unit_id(self):
        current_id = 'A'  # default ID is 'A'
        new_id = self.unit_id_var.get()
        if new_id:
            self.controller.configure_unit_id(current_id, new_id)
            self.messages_frame.log_message(f"Set new unit ID to {new_id}")

    def poll_live_data(self):
        unit_id = 'A'  # assuming current unit ID is 'A', change as needed
        result = self.controller.poll_live_data_frame(unit_id)
        self.live_data_var.set(result)
        self.messages_frame.log_message(f"Polled live data frame: {result}")

    def set_streaming_interval(self):
        interval = self.streaming_interval_var.get()
        if interval:
            self.controller.set_streaming_interval('A', interval) # Assuming unit ID 'A'
            self.messages_frame.log_message(f"Set streaming interval to {interval} ms")

    def setup_tare_tab(self):
        self.tare_flow_button = tk.Button(self.tare_tab, text="Tare Flow", command=self.tare_flow)
        self.tare_flow_button.pack(padx=10, pady=10)
        
        self.tare_pressure_button = tk.Button(self.tare_tab, text="Tare Absolute Pressure", command=self.tare_absolute_pressure)
        self.tare_pressure_button.pack(padx=10, pady=10)

    def setup_control_tab(self):
        ttk.Label(self.control_tab, text="Control configurations go here").pack(padx=10, pady=10)

    def setup_composer_tab(self):
        ttk.Label(self.composer_tab, text="COMPOSER configurations go here").pack(padx=10, pady=10)

    def setup_misc_tab(self):
        ttk.Label(self.misc_tab, text="Miscellaneous configurations go here").pack(padx=10, pady=10)

    

class InterlocksSubsystem:
    def __init__(self, parent, messages_frame=None):
        self.parent = parent
        self.messages_frame = messages_frame
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
    def __init__(self, parent, messages_frame=None):
        self.parent = parent
        self.messages_frame = messages_frame
        self.setup_gui()

    def setup_gui(self):
        self.frame = tk.Frame(self.parent)
        self.frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Frame for the temperature gauge
        temp_frame = tk.Frame(self.frame, width=90)
        temp_frame.pack(side=tk.LEFT, fill=tk.Y, expand=False)

        # Create a vertical temperature gauge
        self.fig, self.ax = plt.subplots(figsize=(0.8, 6))  # Adjust size for vertical layout
        self.temperature = 50  # Initial temperature
        self.bar = plt.bar(1, self.temperature, width=0.4)
        self.ax.set_ylim(0, 100)
        self.ax.set_xlim(0.5, 1.5)
        self.ax.set_xticks([])
        self.ax.set_yticks(range(0, 101, 20))
        self.ax.set_ylabel('', fontsize=10)
        self.ax.set_title("Oil Temp [C]", fontsize=8)
        self.fig.subplots_adjust(left=0.45, right=0.65, top=0.9, bottom=0.1)

        # Color mapping for temperature ranges
        norm = Normalize(vmin=20, vmax=100)
        cmap = plt.get_cmap('coolwarm')
        self.bar[0].set_color(cmap(norm(self.temperature)))

        self.canvas = FigureCanvasTkAgg(self.fig, master=temp_frame)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(side=tk.TOP, padx=15, fill=tk.BOTH, expand=True)

        # Frame for the oil pressure dial
        dial_frame = tk.Frame(self.frame)
        dial_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

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
        self.oil_dial.pack(padx=1, pady=5)

    def update_oil_pressure(self, new_pressure):
        """Update the dial to reflect new oil pressure readings."""
        if 0 <= new_pressure <= 10:  # Ensure the value is within the valid range
            self.oil_dial.set(new_pressure)
        else:
            print("Received out-of-range oil pressure value:", new_pressure)

    def update_oil_temperature(self, new_temperature):
        """Update the temperature gauge to reflect new oil temperature readings."""
        self.temperature_bar[0].set_width(new_temperature)
        self.bar[0].set_height(self.temperature)
        norm = Normalize(vmin=20, vmax=100)
        cmap = plt.get_cmap('afmhot')
        self.bar[0].set_color(cmap(norm(self.temperature)))
        self.canvas.draw()

    def read_sensor_data(self):
        """Simulate reading from a sensor."""
        # TODO: Implement this
        import random
        new_pressure = random.randint(0, 10)  # Random pressure value for demonstration
        new_temperature = random.randint(50, 90)
        self.update_oil_temperature(new_temperature)
        self.update_oil_pressure(new_pressure)

        #self.canvas.draw()
        self.parent.after(500, self.read_sensor_data)  # Schedule the update


class CathodeHeatingSubsystem:
    MAX_POINTS = 20  # Maximum number of points to display on the plot
    OVERTEMP_THRESHOLD = 29.0 # Overtemperature threshold in °C
    
    def __init__(self, parent, messages_frame=None):
        self.parent = parent
        self.voltage_vars = [tk.StringVar(value='0.0') for _ in range(3)]
        self.current_vars = [tk.StringVar(value='0.0') for _ in range(3)]
        self.power_vars = [tk.StringVar(value='0.0') for _ in range(3)]
        self.e_beam_current_vars = [tk.StringVar(value='0.0') for _ in range(3)]
        self.target_current_vars = [tk.StringVar(value='0.0') for _ in range(3)]
        self.grid_current_vars = [tk.StringVar(value='0.0') for _ in range(3)]
        self.temperature_vars = [tk.StringVar(value='0.0') for _ in range(3)]
        self.overtemp_status_vars = [tk.StringVar(value='Normal') for _ in range(3)]
        self.toggle_states = [False for _ in range(3)]
        self.toggle_buttons = []
        self.time_data = [[] for _ in range(3)]
        self.temperature_data = [[] for _ in range(3)]
        self.messages_frame = messages_frame
        self.setup_gui()
        self.update_data()

    def setup_gui(self):
        cathode_labels = ['A', 'B', 'C']
        style = ttk.Style()
        style.configure('Flat.TButton', padding=(0, 0, 0, 0), relief='flat', borderwidth=0)
        style.configure('Bold.TLabel', font=('Helvetica', 10, 'bold'))

        # Load toggle images
        self.toggle_on_image = tk.PhotoImage(file="media/toggle_on.png")
        self.toggle_off_image = tk.PhotoImage(file="media/toggle_off.png")

        # Create main frame
        self.main_frame = ttk.Frame(self.parent)
        self.main_frame.pack(fill='both', expand=True)

        # Create a canvas and scrollbar for scrolling
        self.canvas = tk.Canvas(self.main_frame)
        self.scrollbar = ttk.Scrollbar(self.main_frame, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        # Pack the canvas and scrollbar
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        # Create a frame inside the canvas
        self.scrollable_frame = ttk.Frame(self.canvas)
        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(
                scrollregion=self.canvas.bbox("all")
            )
        )

        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")

        # Create frames for each cathode/power supply pair
        self.cathode_frames = []
        heater_labels = ['Heater A output:', 'Heater B output:', 'Heater C output:']
        for i in range(3):
            frame = ttk.LabelFrame(self.scrollable_frame, text=f'Cathode {cathode_labels[i]}', padding=(10, 5))
            frame.grid(row=0, column=i, padx=5, pady=0.1, sticky='n')
            self.cathode_frames.append(frame)

            # Create voltage, current, and power labels
            ttk.Label(frame, text='Actual Voltage (V):').grid(row=0, column=0, sticky='w')
            ttk.Label(frame, text='Set Voltage:').grid(row=1, column=0, sticky='w')
            ttk.Label(frame, text='Current Output (A):').grid(row=2, column=0, sticky='w')
            ttk.Label(frame, text='Power Output (W):').grid(row=3, column=0, sticky='w')

            # Create entries and display labels
            ttk.Label(frame, textvariable=self.voltage_vars[i], style='Bold.TLabel').grid(row=0, column=1, sticky='e')
            entry_field = ttk.Entry(frame, width=7)
            entry_field.grid(row=1, column=1, sticky='e')
            set_button = ttk.Button(frame, text="Set", width=4, command=lambda i=i, entry_field=entry_field: self.set_voltage(i, entry_field))
            set_button.grid(row=1, column=2, sticky='w')
            ttk.Label(frame, textvariable=self.current_vars[i], style='Bold.TLabel').grid(row=2, column=1, sticky='e')
            ttk.Label(frame, textvariable=self.power_vars[i], style='Bold.TLabel').grid(row=3, column=1, sticky='e')
            ttk.Label(frame, text=heater_labels[i], style='Bold.TLabel').grid(row=4, column=0, sticky='w')

            # Create toggle switch
            toggle_button = ttk.Button(frame, image=self.toggle_off_image, style='Flat.TButton', command=lambda i=i: self.toggle_output(i))
            toggle_button.grid(row=4, column=1, columnspan=1)
            self.toggle_buttons.append(toggle_button)

            # Create calculated values labels
            ttk.Label(frame, text='E-beam Current Prediction (mA):').grid(row=5, column=0, sticky='w')
            ttk.Label(frame, text='Target Current Prediction (mA):').grid(row=6, column=0, sticky='w')
            ttk.Label(frame, text='Grid Current Prediction (mA):').grid(row=7, column=0, sticky='w')
            ttk.Label(frame, text='Temperature Prediction (°C):').grid(row=8, column=0, sticky='w')
            ttk.Label(frame, text='Overtemp Status:').grid(row=9, column=0, sticky='w')

            # Create entries and display labels for calculated values
            ttk.Label(frame, textvariable=self.e_beam_current_vars[i], style='Bold.TLabel').grid(row=5, column=1, sticky='e')
            ttk.Label(frame, textvariable=self.target_current_vars[i], style='Bold.TLabel').grid(row=6, column=1, sticky='e')
            ttk.Label(frame, textvariable=self.grid_current_vars[i], style='Bold.TLabel').grid(row=7, column=1, sticky='e')
            ttk.Label(frame, textvariable=self.temperature_vars[i], style='Bold.TLabel').grid(row=8, column=1, sticky='e')
            ttk.Label(frame, textvariable=self.overtemp_status_vars[i], style='Bold.TLabel').grid(row=9, column=1, sticky='e')

            # Create plot for each cathode
            fig, ax = plt.subplots(figsize=(2.8, 1.3))
            line, = ax.plot([], [])
            self.temperature_data[i].append(line)
            ax.set_xlabel('Time', fontsize=8)
            ax.set_ylabel('Temp (°C)', fontsize=8)
            ax.xaxis.set_major_formatter(DateFormatter('%H:%M:%S'))
            ax.tick_params(axis='x', labelsize=6)
            ax.tick_params(axis='y', labelsize=6)
            fig.tight_layout(pad=0.01)
            fig.subplots_adjust(left=0.14, right=0.99, top=0.99, bottom=0.15)
            canvas = FigureCanvasTkAgg(fig, master=frame)
            canvas.draw()
            canvas.get_tk_widget().grid(row=9, column=0, columnspan=3, pady=0.1)

        self.init_time = datetime.datetime.now()

    def read_current_voltage(self):
        # Placeholder method to read current and voltage from power supplies
        return random.uniform(2, 4), random.uniform(0.5, 0.9)
    
    def read_temperature(self):
        # Placeholder method to read temperature from cathodes
        return float(random.uniform(25, 30))  # Ensure this returns a float

    def update_data(self):
        current_time = datetime.datetime.now()
        for i in range(3):
            voltage, current = self.read_current_voltage()
            temperature = self.read_temperature()  # Ensure this returns a float or numeric type
            self.voltage_vars[i].set(f'{voltage:.2f}')
            self.current_vars[i].set(f'{current:.2f}')
            self.temperature_vars[i].set(f'{temperature:.2f}')  # Ensure temperature is numeric and correctly formatted
            power_output = voltage * current
            self.power_vars[i].set(f'{power_output:.2f}')
            e_beam_current = current
            target_current = 0.72 * e_beam_current
            grid_current = 0.28 * e_beam_current
            self.e_beam_current_vars[i].set(f'{e_beam_current:.2f}')
            self.target_current_vars[i].set(f'{target_current:.2f}')
            self.grid_current_vars[i].set(f'{grid_current:.2f}')

            # Update temperature data for plot
            self.time_data[i].append(current_time)
            temperature_data = list(self.temperature_data[i][0].get_data()[1])
            temperature_data.append(temperature)
            if len(self.time_data[i]) > self.MAX_POINTS:
                self.time_data[i].pop(0)
                temperature_data.pop(0)

            self.temperature_data[i][0].set_data(self.time_data[i], temperature_data)  # Ensure data is set correctly
            
            self.update_plot(i)

            # Check for overtemperature
            if temperature > self.OVERTEMP_THRESHOLD:
                self.overtemp_status_vars[i].set("OVERTEMP!")
                self.log_message(f"Cathode {['A', 'B', 'C'][i]} OVERTEMP!")
            else:
                self.overtemp_status_vars[i].set('OK')

        # Schedule next update
        self.parent.after(1000, self.update_data)

    def update_plot(self, index):
        time_data = self.time_data[index]
        temperature_data = self.temperature_data[index][0].get_data()[1]
        self.temperature_data[index][0].set_data(time_data, temperature_data)

        ax = self.temperature_data[index][0].axes
        ax.relim()
        ax.autoscale_view()
        ax.figure.canvas.draw()

    def toggle_output(self, index):
        self.toggle_states[index] = not self.toggle_states[index]
        current_image = self.toggle_on_image if self.toggle_states[index] else self.toggle_off_image
        self.toggle_buttons[index].config(image=current_image)  # Update the correct toggle button's image
        self.log_message(f"Heater {['A', 'B', 'C'][index]} output {'ON' if self.toggle_states[index] else 'OFF'}")

    def set_voltage(self, index, entry_field):
        value = entry_field.get()
        cathode_labels = ['A', 'B', 'C']
        self.log_message(f'Setting voltage for Cathode {cathode_labels[index]} to {value}V')
        # TODO: write actual logic to set voltage

    def log_message(self, message):
        if hasattr(self, 'messages_frame') and self.messages_frame:
            self.messages_frame.log_message(message)
        else:
            print(message)