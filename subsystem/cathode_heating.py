# subsystem.py
import tkinter as tk
from tkinter import ttk
import tkinter.simpledialog as tksd
import tkinter.messagebox as msgbox
import datetime
import random
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator
from matplotlib.dates import DateFormatter
from instrumentctl.ES440_cathode import ES440_cathode
from instrumentctl.power_supply_9014 import PowerSupply9014
from instrumentctl.ES5CN_modbus import ES5CNModbus
from utils import ToolTip
import os, sys
import numpy as np

def resource_path(relative_path):
    """ Magic needed for paths to work for development and when running as bundled executable"""
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

class CathodeHeatingSubsystem:
    MAX_POINTS = 60  # Maximum number of points to display on the plot
    OVERTEMP_THRESHOLD = 200.0 # Overtemperature threshold in °C
    
    def __init__(self, parent, com_ports, messages_frame=None):
        self.parent = parent
        self.com_ports = com_ports
        self.power_supplies_initialized = False
        self.temp_controllers_connected = False
        self.last_no_conn_log_time = [datetime.datetime.min for _ in range(3)]
        self.log_interval = datetime.timedelta(seconds=10) # used for E5CN timeout msg
        self.ideal_cathode_emission_currents = [0.0 for _ in range(3)]
        self.predicted_emission_current_vars = [tk.StringVar(value='0.0') for _ in range(3)]
        self.predicted_grid_current_vars = [tk.StringVar(value='0.0') for _ in range(3)]
        self.predicted_heater_current_vars = [tk.StringVar(value='0.0') for _ in range(3)]
        self.predicted_temperature_vars = [tk.StringVar(value='0.0') for _ in range(3)]
        self.heater_voltage_vars = [tk.StringVar(value='0.0') for _ in range(3)]
        self.e_beam_current_vars = [tk.StringVar(value='0.0') for _ in range(3)]
        self.target_current_vars = [tk.StringVar(value='0.0') for _ in range(3)]
        self.grid_current_vars = [tk.StringVar(value='0.0') for _ in range(3)]
        
        self.actual_heater_current_vars = [tk.StringVar(value='0.0 A') for _ in range(3)]
        self.actual_heater_voltage_vars = [tk.StringVar(value='0.0 V') for _ in range(3)]
        self.actual_target_current_vars = [tk.StringVar(value='0.0 mA') for _ in range(3)]
        self.clamp_temperature_vars = [tk.StringVar(value='0.0') for _ in range(3)]
        self.clamp_temp_labels = []
        self.previous_temperature = 20 # PLACEHOLDER
        self.last_plot_time = datetime.datetime.now()
        self.plot_interval = datetime.timedelta(seconds=5)

        # Config tab
        self.current_display_vars = [tk.StringVar(value='0.0') for _ in range(3)]
        self.voltage_display_vars = [tk.StringVar(value='0.0') for _ in range(3)]
        self.operation_mode_var = [tk.StringVar(value='Mode: --') for _ in range(3)]
        
        self.overtemp_limit_vars = [tk.DoubleVar(value=self.OVERTEMP_THRESHOLD) for _ in range(3)]
        self.overvoltage_limit_vars= [tk.DoubleVar(value=50.0) for _ in range(3)]  
        self.overcurrent_limit_vars = [tk.DoubleVar(value=10.0) for _ in range(3)]
        self.overtemp_status_vars = [tk.StringVar(value='Normal') for _ in range(3)]

        self.toggle_states = [False for _ in range(3)]
        self.toggle_buttons = []
        self.entry_fields = []
        self.power_supplies = []
        self.temperature_controllers = []
        self.time_data = [[] for _ in range(3)]
        self.temperature_data = [[] for _ in range(3)]
        self.messages_frame = messages_frame
        
        self.init_cathode_model()
        self.setup_gui()

        self.initialize_temperature_controllers()
        self.initialize_power_supplies()
        self.update_data()

    def setup_gui(self):
        cathode_labels = ['A', 'B', 'C']
        style = ttk.Style()
        style.configure('Flat.TButton', padding=(0, 0, 0, 0), relief='flat', borderwidth=0)
        style.configure('Bold.TLabel', font=('Helvetica', 10, 'bold'))
        style.configure('RightAlign.TLabel', font=('Helvetica', 9), anchor='e')
        style.configure('OverTemp.TLabel', foreground='red', font=('Helvetica', 10, 'bold'))  # Overtemperature style

        # Load toggle images
        self.toggle_on_image = tk.PhotoImage(file=resource_path("media/toggle_on.png"))
        self.toggle_off_image = tk.PhotoImage(file=resource_path("media/toggle_off.png"))

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
            frame.grid(row=0, column=i, padx=5, pady=0.1, sticky='nsew')
            self.cathode_frames.append(frame)
            
            # Create a notebook for each cathode
            notebook = ttk.Notebook(frame)
            notebook.grid(row=0, column=0, columnspan=2, sticky='nsew')
            # Create the main tab
            main_tab = ttk.Frame(notebook)
            notebook.add(main_tab, text='Main')

            # Create the config tab
            config_tab = ttk.Frame(notebook)
            notebook.add(config_tab, text='Config')

            config_tab.columnconfigure(1, minsize=70)
            config_tab.columnconfigure(2, minsize=20)

            # Create voltage and current labels
            set_target_label = ttk.Label(main_tab, text='Set Target Current (mA):', style='RightAlign.TLabel')
            
            set_target_label.grid(row=0, column=0, sticky='e')
            ToolTip(set_target_label, "Target current is predicted to be 72% of cathode emission current")
            entry_field = ttk.Entry(main_tab, width=7)
            entry_field.grid(row=0, column=1, sticky='w')
            self.entry_fields.append(entry_field)
            set_button = ttk.Button(main_tab, text="Set", width=4, command=lambda i=i, entry_field=entry_field: self.set_target_current(i, entry_field))
            set_button.grid(row=0, column=1, sticky='e')

            ttk.Label(main_tab, text='Set Heater (V):', style='RightAlign.TLabel').grid(row=1, column=0, sticky='e')
            voltage_label = ttk.Label(main_tab, textvariable=self.heater_voltage_vars[i], style='Bold.TLabel')
            voltage_label.grid(row=1, column=1, sticky='w')
            voltage_label.bind("<Button-1>", lambda e, i=i: self.on_voltage_label_click(i))
            ToolTip(voltage_label, plot_data=ES440_cathode.heater_voltage_current_data, voltage_var=self.predicted_heater_current_vars[i], current_var=self.heater_voltage_vars[i])

            pred_emission_label = ttk.Label(main_tab, text='Pred Emission Current (mA):', style='RightAlign.TLabel')
            pred_emission_label.grid(row=2, column=0, sticky='e')
            ttk.Label(main_tab, textvariable=self.predicted_emission_current_vars[i], style='Bold.TLabel').grid(row=2, column=1, sticky='w')

            set_grid_label = ttk.Label(main_tab, text='Pred Grid Current (mA):', style='RightAlign.TLabel')
            set_grid_label.grid(row=3, column=0, sticky='e')
            ToolTip(set_grid_label, "Grid expected to intercept 28% of cathode emission current")
            ttk.Label(main_tab, textvariable=self.predicted_grid_current_vars[i], style='Bold.TLabel').grid(row=3, column=1, sticky='w')
            
            ttk.Label(main_tab, text='Pred Heater Current (A):', style='RightAlign.TLabel').grid(row=4, column=0, sticky='e')
            ttk.Label(main_tab, textvariable=self.predicted_heater_current_vars[i], style='Bold.TLabel').grid(row=4, column=1, sticky='w')

            ttk.Label(main_tab, text='Pred CathTemp (°C):', style='RightAlign.TLabel').grid(row=5, column=0, sticky='e')
            ttk.Label(main_tab, textvariable=self.predicted_temperature_vars[i], style='Bold.TLabel').grid(row=5, column=1, sticky='w')

            # Create entries and display labels
            ttk.Label(main_tab, text=heater_labels[i], style='Bold.TLabel').grid(row=6, column=0, sticky='w')

            # Create toggle switch
            toggle_button = ttk.Button(main_tab, image=self.toggle_off_image, style='Flat.TButton', command=lambda i=i: self.toggle_output(i))
            toggle_button.grid(row=6, column=1, columnspan=1)
            self.toggle_buttons.append(toggle_button)

            # Create measured values labels
            ttk.Label(main_tab, text='Act Heater (A):', style='RightAlign.TLabel').grid(row=7, column=0, sticky='e')
            ttk.Label(main_tab, textvariable=self.actual_heater_current_vars[i], style='Bold.TLabel').grid(row=7, column=1, sticky='w')
            ttk.Label(main_tab, text='Act Heater (V):', style='RightAlign.TLabel').grid(row=8, column=0, sticky='e')
            ttk.Label(main_tab, textvariable=self.actual_heater_voltage_vars[i], style='Bold.TLabel').grid(row=8, column=1, sticky='w')
            ttk.Label(main_tab, text='Act Target (mA):', style='RightAlign.TLabel').grid(row=9, column=0, sticky='e')
            ttk.Label(main_tab, textvariable=self.actual_target_current_vars[i], style='Bold.TLabel').grid(row=9, column=1, sticky='w')
            ttk.Label(main_tab, text='Act ClampTemp (°C):', style='RightAlign.TLabel').grid(row=10, column=0, sticky='e')
            clamp_temp_label = ttk.Label(main_tab, textvariable=self.clamp_temperature_vars[i], style='Bold.TLabel')
            clamp_temp_label.grid(row=10, column=1, sticky='w')
            self.clamp_temp_labels.append(clamp_temp_label)

            # Create plot for each cathode
            fig, ax = plt.subplots(figsize=(2.8, 1.3))
            line, = ax.plot([], [])
            self.temperature_data[i].append(line)
            ax.set_xlabel('Time', fontsize=8)
            # ax.set_ylabel('Temp (°C)', fontsize=8)
            ax.xaxis.set_major_formatter(DateFormatter('%H:%M:%S'))
            ax.xaxis.set_major_locator(MaxNLocator(4))
            ax.tick_params(axis='x', labelsize=6)
            ax.tick_params(axis='y', labelsize=6)
            fig.tight_layout(pad=0.01)
            fig.subplots_adjust(left=0.14, right=0.99, top=0.99, bottom=0.15)
            canvas = FigureCanvasTkAgg(fig, master=main_tab)
            canvas.draw()
            canvas.get_tk_widget().grid(row=11, column=0, columnspan=3, pady=0.1)

            ttk.Label(config_tab, text="\nPower Supply Configuration", style='Bold.TLabel').grid(row=0, column=0, columnspan=3, sticky="ew")
            # Overtemperature limit entry
            overtemp_label = ttk.Label(config_tab, text='Overtemp Limit (°C):', style='RightAlign.TLabel')
            overtemp_label.grid(row=1, column=0, sticky='e')

            temp_overtemp_var = tk.StringVar(value=str(self.OVERTEMP_THRESHOLD))
            overtemp_entry = ttk.Entry(config_tab, textvariable=temp_overtemp_var, width=7)
            overtemp_entry.grid(row=1, column=1, sticky='w')
            
            set_overtemp_button = ttk.Button(config_tab, text="Set", width=4, command=lambda i=i, var=temp_overtemp_var: self.set_overtemp_limit(i, var))
            set_overtemp_button.grid(row=1, column=2, sticky='e')

            # Overvoltage limit entry
            overvoltage_label = ttk.Label(config_tab, text='Overvoltage Limit (V):', style='RightAlign.TLabel')
            overvoltage_label.grid(row=2, column=0, sticky='e')
            overvoltage_entry = ttk.Entry(config_tab, textvariable=self.overvoltage_limit_vars[i], width=7)
            overvoltage_entry.grid(row=2, column=1, sticky='w')
            set_overvoltage_button = ttk.Button(config_tab, text="Set", width=4, command=lambda i=i: self.set_overvoltage_limit(i))
            set_overvoltage_button.grid(row=2, column=2, sticky='e')

            # Overcurrent limit entry
            overcurrent_label = ttk.Label(config_tab, text='Overcurrent Limit (A):', style='RightAlign.TLabel')
            overcurrent_label.grid(row=3, column=0, sticky='e')
            overcurrent_entry = ttk.Entry(config_tab, textvariable=self.overcurrent_limit_vars[i], width=7)
            overcurrent_entry.grid(row=3, column=1, sticky='w')
            set_overcurrent_button = ttk.Button(config_tab, text="Set", width=4, command=lambda i=i: self.set_overcurrent_limit(i))
            set_overcurrent_button.grid(row=3, column=2, sticky='e')

            # Slew Rate setting
            ttk.Label(config_tab, text='Slew Rate (V/s):', style='RightAlign.TLabel').grid(row=4, column=0, sticky='e')
            slew_rate_var = tk.StringVar(value='0.01')  # Default value
            slew_rate_entry = ttk.Entry(config_tab, textvariable=slew_rate_var, width=7)
            slew_rate_entry.grid(row=4, column=1, sticky='w')
            set_slew_rate_button = ttk.Button(config_tab, text="Set", width=4, command=lambda i=i, var=slew_rate_var: self.set_slew_rate(i, var))
            set_slew_rate_button.grid(row=4, column=2, sticky='e')

            # Get buttons and output labels
            #ttk.Label(config_tab, text='Output Status:', style='RightAlign.TLabel').grid(row=3, column=0, sticky='e')
            output_status_button = ttk.Button(config_tab, text="Output Status:", width=18, command=lambda x=i: self.show_output_status(x))
            output_status_button.grid(row=5, column=0, sticky='w')
            ttk.Label(config_tab, textvariable=self.overtemp_status_vars[i], style='Bold.TLabel').grid(row=5, column=1, sticky='w')
            output_status_button['state'] = 'disabled' if not self.power_supplies_initialized else 'normal'

            # Add labels for power supply readings
            display_label = ttk.Label(config_tab, text='\nProtection Settings:')
            display_label.grid(row=6, column=0, columnspan=1, sticky='ew')

            voltage_display_var = tk.StringVar(value='Voltage: -- V')
            current_display_var = tk.StringVar(value='Current: -- A')
            operation_mode_var = tk.StringVar(value='Mode: --')

            voltage_label = ttk.Label(config_tab, textvariable=voltage_display_var, style='Bold.TLabel')
            voltage_label.grid(row=7, column=0, sticky='w')
            # current_label = ttk.Label(config_tab, textvariable=current_display_var, style='Bold.TLabel')
            # current_label.grid(row=6, column=1, sticky='w')
            mode_label = ttk.Label(config_tab, textvariable=operation_mode_var, style='Bold.TLabel')
            mode_label.grid(row=7, column=1, sticky='w')

            # Store variables for later updates
            self.voltage_display_vars.append(voltage_display_var)
            self.current_display_vars.append(current_display_var)

            # Add label for Temperature Controller
            ttk.Label(config_tab, text="\nTemperature Controller", style='Bold.TLabel').grid(row=8, column=0, columnspan=3, sticky="ew")

            # Place echoback and temperature buttons on the config tab
            echoback_button = ttk.Button(config_tab, text=f"Perform Echoback Test Unit {i+1}",
                                        command=lambda unit=i+1: self.perform_echoback_test(unit))
            echoback_button.grid(row=10, column=0, columnspan=2, sticky='ew', padx=5, pady=2)
            read_temp_button = ttk.Button(config_tab, text=f"Read Temperature Unit {i+1}",
                                        command=lambda unit=i+1: self.read_and_log_temperature(unit))
            read_temp_button.grid(row=11, column=0, columnspan=2, sticky='ew', padx=5, pady=2)

        # Ensure the grid layout of config_tab accommodates the new buttons
        config_tab.columnconfigure(0, weight=1)
        config_tab.columnconfigure(1, weight=1)

        self.init_time = datetime.datetime.now()

    
    def initialize_power_supplies(self):
        self.power_supplies = []
        self.power_supply_status = []

        for port_label, port in self.com_ports.items():
            try:
                ps = PowerSupply9014(port=port, messages_frame=self.messages_frame)
                self.power_supplies.append(ps)
                self.power_supply_status.append(True)
                self.log_message(f"Initialized power supply on port {port}")
            except Exception as e:
                self.power_supplies.append(None)
                self.power_supply_status.append(False)
                self.log_message(f"Failed to initialize power supply on port {port}: {str(e)}")

        # Update button states based on individual power supply status
        for idx, status in enumerate(self.power_supply_status):
            if idx < len(self.toggle_buttons): # Check if index is valid    
                if status:
                    self.toggle_buttons[idx]['state'] = 'normal'
                else:
                    self.toggle_buttons[idx]['state'] = 'disabled'
                    self.log_message(f"Power supply {idx+1} not initialized. Button disabled.")
            else:
                self.log_message(f"Toggle button {idx+1} has not been initialized yet.")

        if all(self.power_supply_status):
            self.power_supplies_initialized = True
        else:
            self.power_supplies_initialized = False
            self.log_message("Some power supplies were not initialized properly.")

    def show_output_status(self, index):
        if not self.power_supplies_initialized:
            self.log_message("Power supplies not initialized.")
            return
        
        status = self.power_supplies[index].get_output_status()
        self.log_message(f"Heater {['A', 'B', 'C'][index]} output status: {status}")

    def init_cathode_model(self):
        try:
            # initialize heater voltage model
            heater_current = [data[0] for data in ES440_cathode.heater_voltage_current_data]
            heater_voltage = [data[1] for data in ES440_cathode.heater_voltage_current_data]
            self.heater_voltage_model = ES440_cathode(heater_current, heater_voltage, log_transform=False)

            # initialize emission current model
            heater_current_emission = [data[0] for data in ES440_cathode.heater_current_emission_current_data]
            emission_current = [data[1] for data in ES440_cathode.heater_current_emission_current_data]
            self.emission_current_model = ES440_cathode(heater_current_emission, emission_current, log_transform=True)
        
            # Initialize true temperature model
            heater_current_temp = [data[0] for data in ES440_cathode.heater_current_true_temperature_data]
            true_temperature = [data[1] for data in ES440_cathode.heater_current_true_temperature_data]
            self.true_temperature_model = ES440_cathode(heater_current_temp, true_temperature, log_transform=False)

        except Exception as e:
            self.log_message(f"Failed to initialize cathode models: {str(e)}")

    def initialize_temperature_controllers(self):
        """
        Initialize the connection to the Modbus devices.
        """
        port = self.com_ports.get('TempControllers', None)
        if port:
            try:
                # Assuming only one Modbus controller object for all units
                tc = ES5CNModbus(port=port, messages_frame=self.messages_frame)
                if tc.connect():
                    self.temperature_controllers = [tc]  # Store it in a list for compatibility with existing code structure
                    self.temp_controllers_connected = True
                    self.log_message("Connected to all temperature controllers via Modbus on " + port)
                else:
                    self.log_message("Failed to connect to temperature controllers at " + port)
                    self.temperature_controllers_connected = False
            except Exception as e:
                self.log_message(f"Exception while initializing temperature controllers at {port}: {str(e)}")
                self.temp_controllers_connected = False

    def read_current_voltage(self):
        # Placeholder method to read current and voltage from power supplies
        return random.uniform(2, 4), random.uniform(0.5, 0.9)

    
    def read_temperature(self, index):
        """
        Read temperature from the temperature controller or set to zero if the controller is not initialized or fails.
        Index corresponds to the cathode index (0-based).
        """
        current_time = datetime.datetime.now()
        if self.temperature_controllers and self.temp_controllers_connected:
            try:
                # Attempt to read temperature from the connected temperature controller
                temperature = self.temperature_controllers[index].read_temperature(index + 1)
                if temperature is not None:
                    self.clamp_temperature_vars[index].set(f"{temperature:.2f} °C")
                    self.set_plot_alert(index, alert_status=False)
                    return temperature
                else:
                    raise Exception("No temperature data received")
            except Exception as e:
                self.log_message(f"Error reading temperature for cathode {index+1}: {str(e)}")
                self.set_plot_alert(index, alert_status=True)  # Set plot border to red
        else:
            if current_time - self.last_no_conn_log_time[index] >= self.log_interval:
                self.log_message(f"No connection to CCS temperature controller {index+1}")
                self.last_no_conn_log_time[index] = current_time
            self.set_plot_alert(index, alert_status=True)
        # Set temperature to zero as default
        self.clamp_temperature_vars[index].set("0.00 °C")
        return 0.0

    def update_data(self):
        current_time = datetime.datetime.now()
        plot_this_cycle = (current_time - self.last_plot_time) >= self.plot_interval

        for i in range(3):
            if self.power_supplies_initialized and self.power_supplies[i] is not None:
                voltage, current, mode = self.power_supplies[i].get_voltage_current_mode()
                self.actual_heater_current_vars[i].set(f"{current:.2f} A")
                self.actual_heater_voltage_vars[i].set(f"{voltage:.2f} V")
                # Assuming the target current should be calculated or retrieved similarly
                # self.actual_target_current_vars[i].set(f"{calculated_target_current:.2f} mA")
            else:
                voltage, current, mode = 0.0, 0.0, "Err"  # Default values if not initialized or out of index
                self.actual_heater_current_vars[i].set("0.00 A")
                self.actual_heater_voltage_vars[i].set("0.00 V")
                self.actual_target_current_vars[i].set("0.00 mA")

            temperature = self.read_temperature(i)
            self.clamp_temperature_vars[i].set(f"{temperature:.2f} °C")

            if plot_this_cycle:
                self.time_data[i] = np.append(self.time_data[i], current_time)
                self.temperature_data[i][0].set_data(self.time_data[i], np.append(self.temperature_data[i][0].get_data()[1], temperature))
                if len(self.time_data[i]) > self.MAX_POINTS:
                    self.time_data[i] = self.time_data[i][-self.MAX_POINTS:]
                    self.temperature_data[i][0].set_data(self.time_data[i], self.temperature_data[i][0].get_data()[1][-self.MAX_POINTS:])

                self.last_plot_time = current_time  # Reset the plot timer

            # Update Main Page labels for voltage and current
            self.heater_voltage_vars[i].set(f"{voltage:.2f} V")
            self.e_beam_current_vars[i].set(f"{current:.2f} A")
            self.clamp_temperature_vars[i].set(f"{temperature:.2f} °C")

            # Update Config page labels
            self.voltage_display_vars[i].set(f'Voltage: {voltage:.2f} V')
            self.current_display_vars[i].set(f'Current: {current:.2f} A')
            mode_text = 'CV Mode' if mode == 0 else 'CC Mode' if mode == 1 else '--'
            self.operation_mode_var[i].set(f'Mode: {mode_text}')

            # Overtemperature check and update label style
            if temperature > self.overtemp_limit_vars[i].get():
                self.overtemp_status_vars[i].set("OVERTEMP!")
                self.log_message(f"Cathode {['A', 'B', 'C'][i]} OVERTEMP!")
                self.clamp_temp_labels[i].config(style='OverTemp.TLabel')  # Change to red style
            else:
                self.overtemp_status_vars[i].set('Normal')
                self.clamp_temp_labels[i].config(style='Bold.TLabel')  # Revert to normal style

            # Update the plot for current cathode
            if plot_this_cycle:  # Ensure plots are updated only when new data is plotted
                self.update_plot(i)

        # Schedule next update
        self.parent.after(500, self.update_data)

    def set_plot_alert(self, index, alert_status):
        """
        Change the plot border color to red if there is a communication error, else reset to default.
        """
        ax = self.temperature_data[index][0].axes
        line = self.temperature_data[index][0]
        color = 'red' if alert_status else 'blue'  # Red for error, blue for normal operation

        for spine in ax.spines.values():
            spine.set_color(color)
        ax.xaxis.label.set_color(color)
        ax.yaxis.label.set_color(color)
        ax.tick_params(axis='both', colors=color)
        line.set_color(color)
        ax.figure.canvas.draw()

    def update_plot(self, index):
        time_data = self.time_data[index]
        temperature_data = self.temperature_data[index][0].get_data()[1]

        # Update the data points for the plot
        self.temperature_data[index][0].set_data(time_data, temperature_data)
        ax = self.temperature_data[index][0].axes

        # Adjust color based on temperature status
        if self.overtemp_status_vars[index].get() == "OVERTEMP!":
            for spine in ax.spines.values():
                spine.set_color('red')
            ax.xaxis.label.set_color('red')
            ax.yaxis.label.set_color('red')
            ax.tick_params(axis='both', colors='red')
            self.temperature_data[index][0].set_color('red')
        else:
            color = 'blue'  # Default color
            for spine in ax.spines.values():
                spine.set_color(color)
            ax.xaxis.label.set_color(color)
            ax.yaxis.label.set_color(color)
            ax.tick_params(axis='both', colors=color)
            self.temperature_data[index][0].set_color(color)

        # Adjust plot to new data
        ax.relim()
        ax.autoscale_view()

        ax.figure.canvas.draw()

    def toggle_output(self, index):
        if not self.power_supplies_initialized or not self.power_supplies:
            self.log_message("Power supplies not properly initialized or list is empty.")
            return
        
        self.toggle_states[index] = not self.toggle_states[index]
        current_image = self.toggle_on_image if self.toggle_states[index] else self.toggle_off_image
        self.toggle_buttons[index].config(image=current_image)  # Update the correct toggle button's image
        if self.toggle_states[index]:
            response = self.power_supplies[index].set_output("1") # ON
        else:
            response = self.power_supplies[index].set_output("0") # OFF
        if response:
            self.log_message(f"Heater {['A', 'B', 'C'][index]} output {'ON' if self.toggle_states[index] else 'OFF'}")
        else:
            self.log_message(f"No response: toggling heater {['A', 'B', 'C'][index]} output {'ON' if self.toggle_states[index] else 'OFF'}")
    
    def set_target_current(self, index, entry_field):
        if self.toggle_states[index]:
            # if the output toggle is enabled, show a warning message
            msgbox.showwarning("Warning", "Disable the output before setting a new target current.")
            return

        if not self.power_supplies[index]:
            self.log_message(f"Power supply {index + 1} is not initialized. Cannot set target current.")
            msgbox.showerror("Error", f"Power supply {index + 1} is not initialized. Cannot set target current.")
            return

        try:
            target_current_mA = float(entry_field.get())
            ideal_emission_current = target_current_mA / 0.72 # this is from CCS Software Dev Spec _2024-06-07A
            log_ideal_emission_current = np.log10(ideal_emission_current / 1000)
            self.log_message(f"Calculated ideal emission current for Cathode {['A', 'B', 'C'][index]}: {ideal_emission_current:.3f}mA")
            
            if ideal_emission_current == 0:
                # Set all related variables to zero
                self.reset_power_supply(index)
                return

            # Ensure current is within the data range
            if ideal_emission_current < min(self.emission_current_model.y_data) * 1000 or ideal_emission_current > max(self.emission_current_model.y_data) * 1000:
                self.log_message("Desired emission current is below the minimum range of the model.")
                self.predicted_emission_current_vars[index].set('0.00')
                self.predicted_grid_current_vars[index].set('0.00')
                self.predicted_heater_current_vars[index].set('0.00')
                self.heater_voltage_vars[index].set('0.00')
                self.predicted_temperature_vars[index].set('0.00')
            else:
                # Calculate heater current from the ES440 model
                heater_current = self.emission_current_model.interpolate(log_ideal_emission_current, inverse=True)
                heater_voltage = self.heater_voltage_model.interpolate(heater_current)

                self.log_message(f"Interpolated heater current for Cathode {['A', 'B', 'C'][index]}: {heater_current:.3f}A")
                self.log_message(f"Interpolated heater voltage for Cathode {['A', 'B', 'C'][index]}: {heater_voltage:.3f}V")

                # Set voltage and current on the power supply
                if self.power_supplies and len(self.power_supplies) > index:
                    voltage_set_success = self.power_supplies[index].set_voltage(1, heater_voltage)  # Preset 1 for voltage
                    current_set_success = self.power_supplies[index].set_current(1, heater_current)  # Preset 1 for current

                    if voltage_set_success and current_set_success:
                        predicted_temperature_K = self.true_temperature_model.interpolate(heater_current)
                        predicted_temperature_C = predicted_temperature_K - 273.15  # Convert Kelvin to Celsius

                        predicted_grid_current = 0.28 * ideal_emission_current # display in milliamps
                        self.predicted_emission_current_vars[index].set(f"{ideal_emission_current:.2f}")
                        self.predicted_grid_current_vars[index].set(f'{predicted_grid_current:.2f}')
                        self.predicted_heater_current_vars[index].set(f'{heater_current:.2f}')
                        self.predicted_temperature_vars[index].set(f"{predicted_temperature_C:.0f}")
                        self.heater_voltage_vars[index].set(f'{heater_voltage:.2f}')

                        self.log_message(f"Set Cathode {['A', 'B', 'C'][index]} power supply to {heater_voltage:.2f}V, targetting {heater_current:.2f}A heater current")
                    else:
                        self.reset_related_variables(index)
                        self.log_message(f"Failed to set voltage/current for Cathode {['A', 'B', 'C'][index]}.")

        except ValueError:
            self.log_message("Invalid input for target current")

    def reset_related_variables(self, index):
        """ Resets display variables when setting voltage/current fails. """
        self.predicted_emission_current_vars[index].set('0.00')
        self.predicted_grid_current_vars[index].set('0.00')
        self.predicted_heater_current_vars[index].set('0.00')
        self.heater_voltage_vars[index].set('0.00')
        self.predicted_temperature_vars[index].set('0.00')

    def reset_power_supply(self, index):
        """ Helper function to reset power supply voltage and current to zero """
        if self.power_supplies and len(self.power_supplies) > index:
            self.power_supplies[index].set_voltage(1, 0.0)
            self.power_supplies[index].set_voltage(1, 0.0)
            self.log_message(f"Reset power supply settings for Cathode {['A', 'B', 'C'][index]}")
        self.predicted_emission_current_vars[index].set('0.00')
        self.predicted_grid_current_vars[index].set('0.00')
        self.predicted_heater_current_vars[index].set('0.00')
        self.heater_voltage_vars[index].set('0.00')
        self.predicted_temperature_vars[index].set('0.00')

    def on_voltage_label_click(self, index):
        """ Handle clicks on heater voltage label to manually set heater voltage """
        new_voltage = tksd.askfloat("Set Heater Voltage", "Enter new heater voltage (V):", parent=self.parent)
        if new_voltage is not None:
            success = self.update_predictions_from_voltage(index, new_voltage)
            if success:
                self.heater_voltage_vars[index].set(f"{new_voltage:.2f}")
                self.entry_fields[index].delete(0, tk.END)
            else:
                self.log_message(f"Failed to set manual voltage for Cathode {['A', 'B', 'C'][index]}.")

    def update_predictions_from_voltage(self, index, voltage):
        """Update predictions based on manually entered voltage."""

        try:
            # Use the ES440_cathode model to interpolate current from voltage
            cathode_model = ES440_cathode([data[1] for data in ES440_cathode.heater_voltage_current_data], 
                                        [data[0] for data in ES440_cathode.heater_voltage_current_data], 
                                        log_transform=False)
            heater_current = cathode_model.interpolate(voltage, inverse=True)


            # Check if the interpolated current is within the model's range
            if not min(cathode_model.x_data) <= heater_current <= max(cathode_model.x_data):
                self.log_message("Heater current is out of the emission model's range.")
                return False

            # Set voltage and current on the power supply
            if self.power_supplies and len(self.power_supplies) > index:
                voltage_set_success = self.power_supplies[index].set_voltage(1, voltage)
                current_set_success = self.power_supplies[index].set_current(1, heater_current)
                if not voltage_set_success or not current_set_success:
                    return False

            # Calculate dependent variables
            ideal_emission_current = self.emission_current_model.interpolate(np.log10(heater_current), inverse=True)
            predicted_grid_current = 0.28 * ideal_emission_current
            predicted_temperature_K = self.true_temperature_model.interpolate(heater_current)
            predicted_temperature_C = predicted_temperature_K - 273.15

            # Update GUI with new values
            self.predicted_emission_current_vars[index].set(f"{ideal_emission_current:.2f}")
            self.predicted_grid_current_vars[index].set(f'{predicted_grid_current:.2f}')
            self.predicted_temperature_vars[index].set(f"{predicted_temperature_C:.0f}")

            self.log_message(f"Updated manual settings for Cathode {['A', 'B', 'C'][index]}: {voltage:.2f}V, {heater_current:.2f}A")
            return True
        except ValueError as e:
            self.log_message(f"Error processing manual voltage setting: {str(e)}")
            self.reset_related_variables(index)
            return False

    def set_overtemp_limit(self, index, temp_var):
        try:
            new_limit = float(temp_var.get())
            self.overtemp_limit_vars[index].set(new_limit)
            self.log_message(f"Set overtemperature limit for Cathode {['A', 'B', 'C'][index]} to {new_limit:.2f}°C")
        except ValueError:
            self.log_message("Invalid input for overtemperature limit")

    def log_message(self, message):
        if hasattr(self, 'messages_frame') and self.messages_frame:
            self.parent.after (0, lambda: self.messages_frame.log_message(message))
        else:
            print(message)

    def perform_echoback_test(self, unit):
        """
        Perform an echoback test on the specified unit.
        This method checks if the temperature controllers are connected before proceeding.
        """
        try:
            # Ensure that the unit index is within the range of connected controllers
            if unit - 1 >= len(self.temperature_controllers):
                raise ValueError(f"Temperature Controller Unit {unit} is not connected or initialized.")

            # Perform the echoback test
            controller = self.temperature_controllers[unit - 1]
            result = controller.perform_echoback_test()
            self.log_message(f"Echoback test result for Unit {unit}: {result}")
        except Exception as e:
            self.log_message(f"Failed to perform echoback test on Unit {unit}: {str(e)}")
            msgbox.showerror("Echoback Test Error", f"Failed to perform echoback test on Unit {unit}: {str(e)}")


    def read_and_log_temperature(self, unit):
        """
        Read the temperature from the specified unit and log the result.
        Ensures the unit is connected before attempting to read.
        """
        try:
            if unit - 1 >= len(self.temperature_controllers):
                raise ValueError(f"Temperature Controller Unit {unit} is not connected or initialized.")

            controller = self.temperature_controllers[unit - 1]
            temperature = controller.read_temperature()
            if temperature is not None:
                message = f"Temperature from Unit {unit}: {temperature:.2f} °C"
                self.log_message(message)
            else:
                raise Exception("Failed to read temperature")
        except Exception as e:
            self.log_message(f"Error reading temperature from Unit {unit}: {str(e)}")
            msgbox.showerror("Temperature Read Error", f"Error reading temperature from Unit {unit}: {str(e)}")
