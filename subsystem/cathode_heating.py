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
from instrumentctl.power_supply_9104 import PowerSupply9104
from instrumentctl.E5CN_modbus import E5CNModbus
from utils import ToolTip
import os, sys
import numpy as np
from utils import LogLevel

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
    
    def __init__(self, parent, com_ports, logger=None):
        self.parent = parent
        self.com_ports = com_ports
        self.power_supplies_initialized = False
        self.voltage_set = [False, False, False]
        self.temp_controllers_connected = False
        self.last_no_conn_log_time = [datetime.datetime.min for _ in range(3)]
        self.log_interval = datetime.timedelta(seconds=10) # used for E5CN timeout msg
        self.voltage_check_interval = 5
        self.last_voltage_check = [0, 0, 0]  # Last check time for each power supply
        self.user_set_voltages = [None, None, None]  # Store user-set voltages
        self.query_settings_buttons = []
        self.ideal_cathode_emission_currents = [0.0 for _ in range(3)]
        self.predicted_emission_current_vars = [tk.StringVar(value='--') for _ in range(3)]
        self.predicted_grid_current_vars = [tk.StringVar(value='--') for _ in range(3)]
        self.predicted_heater_current_vars = [tk.StringVar(value='--') for _ in range(3)]
        self.predicted_temperature_vars = [tk.StringVar(value='--') for _ in range(3)]
        self.heater_voltage_vars = [tk.StringVar(value='--') for _ in range(3)]
        self.e_beam_current_vars = [tk.StringVar(value='--') for _ in range(3)]
        self.target_current_vars = [tk.StringVar(value='--') for _ in range(3)]
        self.grid_current_vars = [tk.StringVar(value='--') for _ in range(3)]
        
        self.actual_heater_current_vars = [tk.StringVar(value='-- A') for _ in range(3)]
        self.actual_heater_voltage_vars = [tk.StringVar(value='-- V') for _ in range(3)]
        self.actual_target_current_vars = [tk.StringVar(value='-- mA') for _ in range(3)]
        self.clamp_temperature_vars = [tk.StringVar(value='--') for _ in range(3)]
        self.clamp_temp_labels = []
        self.previous_temperature = 20 # PLACEHOLDER
        self.last_plot_time = datetime.datetime.now()
        self.plot_interval = datetime.timedelta(seconds=5)

        # Config tab
        self.current_display_vars = [tk.StringVar(value='--') for _ in range(3)]
        self.voltage_display_vars = [tk.StringVar(value='--') for _ in range(3)]
        self.operation_mode_var = [tk.StringVar(value='Mode: --') for _ in range(3)]
        
        self.overtemp_limit_vars = [tk.DoubleVar(value=self.OVERTEMP_THRESHOLD) for _ in range(3)]
        self.overvoltage_limit_vars= [tk.DoubleVar(value=1.0) for _ in range(3)]  
        self.overcurrent_limit_vars = [tk.DoubleVar(value=8.5) for _ in range(3)]
        self.overtemp_status_vars = [tk.StringVar(value='Normal') for _ in range(3)]

        self.toggle_states = [False for _ in range(3)]
        self.toggle_buttons = []
        self.entry_fields = []
        self.power_supplies = []
        self.temperature_controllers = []
        self.time_data = [[] for _ in range(3)]
        self.temperature_data = [[] for _ in range(3)]
        self.logger = logger
        
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
            query_settings_button = ttk.Button(config_tab, text="Query Settings:", width=18, command=lambda x=i: self.query_and_check_settings(x))
            query_settings_button.grid(row=5, column=0, sticky='w')
            ttk.Label(config_tab, textvariable=self.overtemp_status_vars[i], style='Bold.TLabel').grid(row=5, column=1, sticky='w')
            query_settings_button['state'] = 'disabled'
            self.query_settings_buttons.append(query_settings_button)

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

        cathode_ports = {
            'CathodeA PS': self.com_ports.get('CathodeA PS'),
            'CathodeB PS': self.com_ports.get('CathodeB PS'),
            'CathodeC PS': self.com_ports.get('CathodeC PS')
        }

        for idx, (cathode, port) in enumerate(cathode_ports.items()):
            if port:
                try:
                    ps = PowerSupply9104(port=port, logger=self.logger)
                    self.power_supplies.append(ps)
                    self.power_supply_status.append(True)
                    self.log(f"Initialized {cathode} on port {port}", LogLevel.INFO)
                    
                    # start the initialization chain
                    self._initialize_power_supply_settings(idx, cathode)

                except Exception as e:
                    self.power_supplies.append(None)
                    self.power_supply_status.append(False)
                    self.log(f"Failed to initialize {cathode} on port {port}: {str(e)}", LogLevel.ERROR)
            else:
                self.power_supplies.append(None)
                self.power_supply_status.append(False)
                self.log(f"No COM port specified for {cathode}", LogLevel.ERROR)

        # Update button states based on individual power supply status
        for idx, status in enumerate(self.power_supply_status):
            if idx < len(self.toggle_buttons): # Check if index is valid    
                if status:
                    self.toggle_buttons[idx]['state'] = 'normal'
                else:
                    self.toggle_buttons[idx]['state'] = 'disabled'
                    self.log(f"Power supply {idx+1} not initialized. Button disabled.", LogLevel.DEBUG)
            else:
                self.log(f"Toggle button {idx+1} has not been initialized yet.", LogLevel.VERBOSE)

        if any(self.power_supply_status):
            self.power_supplies_initialized = True
        else:
            self.power_supplies_initialized = False
            self.log("No power supplies were initialized properly.", LogLevel.DEBUG)
        
        self.update_query_settings_button_states()

    def retry_connection(self, index):
        max_retries = 3
        for attempt in range(max_retries):
            try:
                port = self.com_ports[f'Cathode{chr(65+index)} PS']
                new_ps = PowerSupply9104(port=port, logger=self.logger)
                self.power_supplies[index] = new_ps
                self.power_supply_status[index] = True
                self.toggle_buttons[index]['state'] = 'normal'
                self.log(f"Reconnected to power supply on port {port}", LogLevel.DEBUG)
                self.update_query_settings_button_states()
                self._initialize_power_supply_settings(index, ['A', 'B', 'C'][index])
                return True
            except Exception as e:
                self.log(f"Retry {attempt+1} failed: {str(e)}", LogLevel.ERROR)
        
        self.log(f"Failed to reconnect after {max_retries} attempts", LogLevel.ERROR)
        return False

    def _initialize_power_supply_settings(self, idx, cathode):
        ps = self.power_supplies[idx]
        
        # Set preset mode to 3
        self.log(f"Setting preset selection for cathode {cathode} to: 3", LogLevel.DEBUG)
        ps.enqueue_command('set_preset_selection', 3, 
                           callback=lambda response: self._preset_callback(response, idx, cathode))

    def _preset_callback(self, response, idx, cathode):
        if response != "OK":
            self.log(f"Failed to set preset mode to 3. Response: {response}", LogLevel.WARNING)
        else:
            self.log("Successfully set preset mode to 3", LogLevel.INFO)
        
        # confirm preset mode
        self.power_supplies[idx].enqueue_command('get_preset_selection',
                                             callback=lambda response: self._confirm_preset_callback(response, idx, cathode))

    def _confirm_preset_callback(self, response, idx, cathode):
        if response != "3":
            self.log(f"{cathode} is not in preset mode 3 (normal mode). Current mode: {response}", LogLevel.WARNING)
        else:
            self.log(f"{cathode} successfully set to preset mode 3", LogLevel.INFO)
        
        # Set OVP
        ovp_value = int(self.overvoltage_limit_vars[idx].get() * 100) # convert to centivolts
        self._set_ovp(idx, cathode, ovp_value)

    def _set_ovp(self, idx, cathode, ovp_value):
        self.log(f"Setting OVP for cathode {cathode} to: {ovp_value:04d}", LogLevel.DEBUG)
        self.power_supplies[idx].enqueue_command('set_over_voltage_protection', f"{ovp_value:04d}",
                                             callback=lambda response: self._ovp_callback(response, idx, cathode, ovp_value))

    def _ovp_callback(self, response, idx, cathode, ovp_value):
        if response != "OK":
            self.log(f"Failed to set OVP. Response: {response}", LogLevel.ERROR)
            msgbox.showerror("Error", f"Failed to set OVP for Cathode {cathode}")
        else:
            self.log("Successfully set OVP", LogLevel.INFO)
            self._confirm_ovp(idx, cathode, ovp_value)

    def _confirm_ovp(self, idx, cathode, ovp_value):
        self.power_supplies[idx].enqueue_command('get_over_voltage_protection',
                                             callback=lambda response: self._confirm_ovp_callback(response, idx, cathode, ovp_value))

    def _confirm_ovp_callback(self, response, idx, cathode, ovp_value):
        if response.strip() != f"{ovp_value:04d}":
            self.log(f"OVP mismatch for {cathode}. Set: {ovp_value:04d}, Got: {response.strip()}", LogLevel.WARNING)
        else:
            self.log(f"OVP successfully set and confirmed for {cathode}: {ovp_value/100:.2f}V", LogLevel.INFO)

    def _set_ocp(self, idx, cathode, ocp_value):
        self.log(f"Setting OCP for cathode {cathode} to: {ocp_value:04d}", LogLevel.DEBUG)
        self.power_supplies[idx].enqueue_command('set_over_current_protection', f"{ocp_value:04d}",
                                                callback=lambda response: self._ocp_callback(response, idx, cathode, ocp_value))

    def _ocp_callback(self, response, idx, cathode, ocp_value):
        if response != "OK":
            self.log(f"Failed to set OCP for {cathode}. Response: {response}", LogLevel.ERROR)
        else:
            self.log(f"Successfully set OCP for {cathode}", LogLevel.INFO)
            self._confirm_ocp(idx, cathode, ocp_value)
    
    def _confirm_ocp(self, idx, cathode, ocp_value):
        self.power_supplies[idx].enqueue_command('get_over_current_protection',
                                                 callback=lambda response: self._confirm_ocp_callback(response, idx, cathode, ocp_value))

    def _confirm_ocp_callback(self, response, idx, cathode, ocp_value):
        if response.strip() != f"{ocp_value:04d}":
            self.log(f"OCP mismatch for {cathode}. Set: {ocp_value:04d}, Got: {response.strip()}", LogLevel.WARNING)
        else:
            self.log(f"OCP successfully set and confirmed for {cathode}: {ocp_value/100:.2f}A", LogLevel.INFO)
        self.log(f"Initialization complete for {cathode}", LogLevel.INFO)
    
        if all(self.power_supply_status):
            self.power_supplies_initialized = True
            self.log("All power supplies initialized", LogLevel.INFO)
    
    def set_overvoltage_limit(self, index):
        if not self.power_supply_status[index]:
            self.log(f"Power supply {index + 1} is not initialized. Cannot set OVP.", LogLevel.ERROR)
            msgbox.showerror("Error", f"Power supply {index + 1} is not initialized. Cannot set OVP.")
            return
        try:
            ovp_value = int(self.overvoltage_limit_vars[index].get() * 100)  # Convert to centivolts
            cathode = ['A', 'B', 'C'][index]
            self._set_ovp(index, cathode, ovp_value)
        except ValueError:
            self.log(f"Invalid input for OVP limit for Cathode {['A', 'B', 'C'][index]}", LogLevel.ERROR)
            msgbox.showerror("Error", "Invalid input for OVP limit. Please enter a valid number.")

    def set_overcurrent_limit(self, index):
        if not self.power_supply_status[index]:
            self.log(f"Power supply {index + 1} is not initialized. Cannot set OCP.", LogLevel.ERROR)
            msgbox.showerror("Error", f"Power supply {index + 1} is not initialized. Cannot set OCP.")
            return

        try:
            ocp_value = int(self.overcurrent_limit_vars[index].get() * 100)  # Convert to centiamps
            self.log(f"Setting OCP for Cathode {['A', 'B', 'C'][index]} to: {ocp_value:04d}", LogLevel.DEBUG)
            cathode = ['A', 'B', 'C'][index]
            self._set_ocp(index, cathode, ocp_value)
        except ValueError:
            self.log(f"Invalid input for OCP limit for Cathode {['A', 'B', 'C'][index]}", LogLevel.ERROR)
            msgbox.showerror("Error", "Invalid input for OCP limit. Please enter a valid number.")

    def show_output_status(self, index):
        if not self.power_supply_status[index]:
            self.log(f"Power supply {index} not initialized.", LogLevel.ERROR)
            return
        
        self.power_supplies[index].enqueue_command('get_output_status', 
                                               callback=lambda response: self._output_status_callback(response, index))

    def _output_status_callback(self, response, index):
        self.log(f"Heater {['A', 'B', 'C'][index]} output status: {response}", LogLevel.INFO)
        self.verify_voltage(index)

    def verify_voltage(self, index):
        self.power_supplies[index].enqueue_command('get_voltage', 
                                                callback=lambda response: self._verify_voltage_callback(response, index))

    def _verify_voltage_callback(self, response, index):
        actual_voltage = float(response)
        expected_voltage = self.user_set_voltages[index]
        if abs(actual_voltage - expected_voltage) > 0.1:  # 0.1V tolerance
            mismatch = f"Voltage mismatch for Cathode {['A', 'B', 'C'][index]}: Set: {expected_voltage:.2f}V, Actual: {actual_voltage:.2f}V"
            self.log(mismatch, LogLevel.CRITICAL)
        else:
            self.log(f"Voltage for Cathode {['A', 'B', 'C'][index]} matches set value.", LogLevel.INFO)

    def update_query_settings_button_states(self):
        for i, power_supply in enumerate(self.power_supplies):
            if i < len(self.query_settings_buttons):
                self.query_settings_buttons[i]['state'] = 'normal' if power_supply else 'disabled'

    def query_and_check_settings(self, index):
        if not self.power_supply_status[index]:
            self.log(f"Power supply {index} not initialized.", LogLevel.ERROR)
            return
        self.power_supplies[index].enqueue_command('get_settings', 3, 
                                                   callback=lambda response: self._check_settings_callback(response, index))

    def _check_settings_callback(self, response, index):
        self.log(f"Raw settings response for Cathode {['A', 'B', 'C'][index]}: {response}", LogLevel.DEBUG)
        if not response or "OK" not in response:
            self.log(f"Failed to retrieve settings for Cathode {['A', 'B', 'C'][index]}", LogLevel.ERROR)
            return

        try:
            settings_value = response.split('OK')[0].strip()
            
            if len(settings_value) != 8:
                raise ValueError(f"Unexpected settings format: {settings_value}")

            voltage_cv, current_cv = int(settings_value[:4]), int(settings_value[4:])
            voltage = voltage_cv / 100.0
            current = current_cv / 100.0

            expected_voltage = self.user_set_voltages[index]
            if expected_voltage is None:
                self.log(f"Cathode {['A', 'B', 'C'][index]} settings - Voltage: {voltage:.2f}V, Current: {current:.2f}A", LogLevel.INFO)
            elif abs(voltage - expected_voltage) > 0.1:  # 0.1V tolerance
                self.log(f"Voltage mismatch for Cathode {['A', 'B', 'C'][index]}: Set: {expected_voltage:.2f}V, Actual: {voltage:.2f}V", LogLevel.ERROR)
            else:
                self.log(f"Cathode {['A', 'B', 'C'][index]} voltage matches set value. Voltage: {voltage:.2f}V, Current: {current:.2f}A", LogLevel.INFO)

        except ValueError as e:
            self.log(f"Failed to parse settings for Cathode {['A', 'B', 'C'][index]}: {str(e)}", LogLevel.ERROR)

    def parse_voltage_from_settings(self, settings):
        try:
            # Format: VVVVIIII" where VVVV is voltage in centivolts
            voltage_cv = int(settings[:4])
            return voltage_cv / 100.0 # Convert to volts
        except ValueError:
            self.log("Failed to parse set voltage from settings", LogLevel.ERROR)
            return None

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
            self.log(f"Failed to initialize cathode models: {str(e)}", LogLevel.ERROR)

    def initialize_temperature_controllers(self):
        """
        Initialize the connection to the Modbus devices.
        """
        port = self.com_ports.get('TempControllers', None)
        if port:
            try:
                # Assuming only one Modbus controller object for all units
                tc = E5CNModbus(port=port, logger=self.logger)
                if tc.connect():
                    self.temperature_controllers = [tc]  # Store it in a list for compatibility with existing code structure
                    self.temp_controllers_connected = True
                    self.log(f"Connected to all temperature controllers via Modbus on {port}", LogLevel.INFO)
                else:
                    self.log(f"Failed to connect to temperature controllers at {port}", LogLevel.ERROR)
                    self.temperature_controllers_connected = False
            except Exception as e:
                self.log(f"Exception while initializing temperature controllers at {port}: {str(e)}", LogLevel.ERROR)
                self.temp_controllers_connected = False

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
                self.log(f"Error reading temperature for cathode {index+1}: {str(e)}", LogLevel.ERROR)
                self.set_plot_alert(index, alert_status=True)  # Set plot border to red
        else:
            if current_time - self.last_no_conn_log_time[index] >= self.log_interval:
                self.log(f"No connection to CCS temperature controller {index+1}", LogLevel.DEBUG)
                self.last_no_conn_log_time[index] = current_time
            self.set_plot_alert(index, alert_status=True)
        # Set temperature to zero as default
        self.clamp_temperature_vars[index].set("-- °C")
        return None

    def update_data(self):
        current_time = datetime.datetime.now()
        plot_this_cycle = (current_time - self.last_plot_time) >= self.plot_interval

        for i in range(3):
            self.log(f"Processing Cathode {['A', 'B', 'C'][i]}", LogLevel.DEBUG)

            voltage = None
            current = None
            mode = None
            temperature = None

            if self.power_supplies_initialized and self.power_supplies[i] is not None:
                try:
                    if not self.power_supplies[i].is_connected():
                        self.log(f"Power supply {i+1} disconnected, attempting reconnection", LogLevel.WARNING)
                        if self.retry_connection(i):
                            self.log(f"Reconnected to power supply {i+1}", LogLevel.INFO)
                        else:
                            self.log(f"Failed to reconnect to power supply {i+1}", LogLevel.ERROR)
                            self._reset_display_values(i)
                            continue
                    
                    self.power_supplies[i].enqueue_command('get_voltage_current_mode', 
                                        callback=lambda response, index=i: self._update_power_supply_data(response, index, current_time, plot_this_cycle))
                except Exception as e:
                    self.log(f"Error updating data for power supply {i+1}: {str(e)}", LogLevel.ERROR)
                    self.actual_heater_current_vars[i].set("-- A")
                    self.actual_heater_voltage_vars[i].set("-- V")
                    self.operation_mode_var[i].set("Mode: --")
            else:
                self.actual_heater_current_vars[i].set("-- A")
                self.actual_heater_voltage_vars[i].set("-- V")
                self.actual_target_current_vars[i].set("-- mA")

            temperature = self.read_temperature(i)

            if temperature is not None:
                self.clamp_temperature_vars[i].set(f"{temperature:.2f} °C")
            else:
                self.clamp_temperature_vars[i].set("-- °C")

            if plot_this_cycle:
                self.time_data[i] = np.append(self.time_data[i], current_time)
                self.temperature_data[i][0].set_data(self.time_data[i], np.append(self.temperature_data[i][0].get_data()[1], temperature))
                if len(self.time_data[i]) > self.MAX_POINTS:
                    self.time_data[i] = self.time_data[i][-self.MAX_POINTS:]
                    self.temperature_data[i][0].set_data(self.time_data[i], self.temperature_data[i][0].get_data()[1][-self.MAX_POINTS:])

                self.last_plot_time = current_time  # Reset the plot timer

            # Update Main Page labels for voltage and current
            self.e_beam_current_vars[i].set(f"{current:.2f} A" if current is not None else "-- A")

            # Update Config page labels
            self.voltage_display_vars[i].set(f'Voltage: {voltage:.2f} V' if voltage is not None else 'Voltage: -- V')
            self.current_display_vars[i].set(f'Current: {current:.2f} A' if current is not None else 'Current: -- A')
            mode_text = 'CV Mode' if mode == 0 else 'CC Mode' if mode == 1 else '--'
            self.operation_mode_var[i].set(f'Mode: {mode_text}')

            # Overtemperature check and update label style
            if temperature is not None:
                if temperature > self.overtemp_limit_vars[i].get():
                    self.overtemp_status_vars[i].set("OVERTEMP!")
                    self.log(f"Cathode {['A', 'B', 'C'][i]} OVERTEMP!", LogLevel.CRITICAL)
                    self.clamp_temp_labels[i].config(style='OverTemp.TLabel')  # Change to red style
                else:
                    self.overtemp_status_vars[i].set('Normal')
                    self.clamp_temp_labels[i].config(style='Bold.TLabel')  # Revert to normal style
            else:
                self.overtemp_status_vars[i].set('N/A')
                self.clamp_temp_labels[i].config(style='Bold.TLabel')

            # Update the plot for current cathode
            if plot_this_cycle:  # Ensure plots are updated only when new data is plotted
                self.update_plot(i)

        # Schedule next update
        self.parent.after(500, self.update_data)

    def _update_power_supply_data(self, response, index, current_time, plot_this_cycle):
        if response:
            voltage, current, mode = response
            self.log(f"Power supply {index+1} readings - Voltage: {voltage:.2f}V, Current: {current:.2f}A, Mode: {mode}", LogLevel.DEBUG)
            
            self.actual_heater_current_vars[index].set(f"{current:.2f} A" if current is not None else "-- A")
            self.actual_heater_voltage_vars[index].set(f"{voltage:.2f} V" if voltage is not None else "-- V")
            
            # Update heater voltage display
            if self.voltage_set[index] and hasattr(self, f'last_set_voltage_{index}'):
                last_set_voltage = getattr(self, f'last_set_voltage_{index}')
                self.heater_voltage_vars[index].set(f"{last_set_voltage:.2f} V")
            elif voltage is not None:
                self.heater_voltage_vars[index].set(f"{voltage:.2f} V")
            else:
                self.heater_voltage_vars[index].set("-- V")

            # Update mode display
            mode_text = 'CV Mode' if mode == 0 else 'CC Mode' if mode == 1 else '--'
            self.operation_mode_var[index].set(f'Mode: {mode_text}')

            # Update Main Page labels for voltage and current
            self.e_beam_current_vars[index].set(f"{current:.2f} A" if current is not None else "-- A")

            # Update Config page labels
            self.voltage_display_vars[index].set(f'Voltage: {voltage:.2f} V' if voltage is not None else 'Voltage: -- V')
            self.current_display_vars[index].set(f'Current: {current:.2f} A' if current is not None else 'Current: -- A')

            if plot_this_cycle:
                self.update_plot(index)
        else:
            self._reset_display_values(index)

    def _reset_display_values(self, index):
        self.actual_heater_current_vars[index].set("-- A")
        self.actual_heater_voltage_vars[index].set("-- V")
        self.actual_target_current_vars[index].set("-- mA")
        self.heater_voltage_vars[index].set("-- V")
        self.operation_mode_var[index].set("Mode: --")
        self.e_beam_current_vars[index].set("-- A")
        self.voltage_display_vars[index].set('Voltage: -- V')
        self.current_display_vars[index].set('Current: -- A')

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
            self.log("Power supplies not properly initialized or list is empty.", LogLevel.ERROR)
            return
        
        new_state = not self.toggle_states[index]
        
        if new_state:  # If we're trying to turn the output ON
            self.power_supplies[index].enqueue_command('get_settings', 3, 
                                                   callback=lambda response: self._toggle_output_check_settings(response, index, new_state))
        else:
            self._perform_toggle(index, new_state)

    def _toggle_output_check_settings(self, response, index, new_state):
        if response:
            settings_values = response.split('\n')[0].strip()
            if len(settings_values) == 8:
                set_voltage = int(settings_values[:4]) / 100.0
                set_current = int(settings_values[4:]) / 100.0
                
                expected_voltage = self.user_set_voltages[index]
                expected_current = float(self.predicted_heater_current_vars[index].get().split()[0])
                
                voltage_mismatch = abs(set_voltage - expected_voltage) > 0.02
                current_mismatch = abs(set_current - expected_current) > 0.01
                
                if voltage_mismatch or current_mismatch:
                    mismatch_message = f"Mismatch in set values for Cathode {['A', 'B', 'C'][index]}:\n"
                    if voltage_mismatch:
                        mismatch_message += f"UVL Preset Expected: {expected_voltage:.2f}V, Actual: {set_voltage:.2f}V\n"
                    if current_mismatch:
                        mismatch_message += f"UCL Preset Expected: {expected_current:.2f}A, Actual: {set_current:.2f}A\n"
                    mismatch_message += "Do you want to proceed with turning on the output?"
                    
                    if not msgbox.askyesno("Value Mismatch", mismatch_message):
                        self.log(f"Output activation cancelled due to set value mismatch for Cathode {['A', 'B', 'C'][index]}", LogLevel.WARNING)
                        return
                else:
                    self.log(f"Set values confirmed for Cathode {['A', 'B', 'C'][index]}: {set_voltage:.2f}V, {set_current:.2f}A")
            else:
                self.log(f"Invalid settings format for Cathode {['A', 'B', 'C'][index]}. Received: {settings_values}", LogLevel.ERROR)
                return
        else:
            self.log(f"Failed to confirm set values for Cathode {['A', 'B', 'C'][index]}. No response received.", LogLevel.ERROR)
            return
        
        self._perform_toggle(index, new_state)

    def _perform_toggle(self, index, new_state):
        self.toggle_states[index] = new_state
        current_image = self.toggle_on_image if new_state else self.toggle_off_image
        self.toggle_buttons[index].config(image=current_image)
        
        self.power_supplies[index].enqueue_command('set_output', "1" if new_state else "0", 
                                                callback=lambda response: self._toggle_output_callback(response, index, new_state))

    def _toggle_output_callback(self, response, index, new_state):
        if response == "OK":
            self.log(f"Heater {['A', 'B', 'C'][index]} output {'ON' if new_state else 'OFF'}", LogLevel.INFO)
        else:
            self.log(f"Failed to toggle heater {['A', 'B', 'C'][index]} output {'ON' if new_state else 'OFF'}", LogLevel.CRITICAL)
            # Revert the toggle state and button image if the operation failed
            self.toggle_states[index] = not new_state
            current_image = self.toggle_on_image if self.toggle_states[index] else self.toggle_off_image
            self.toggle_buttons[index].config(image=current_image)

    def set_target_current(self, index, entry_field):
        if self.toggle_states[index]:
            # if the output toggle is enabled, show a warning message
            msgbox.showwarning("Warning", "Disable the output before setting a new target current.")
            return

        if not self.power_supply_status[index]:
            self.log(f"Power supply {index + 1} is not initialized. Cannot set target current.", LogLevel.ERROR)
            msgbox.showerror("Error", f"Power supply {index + 1} is not initialized. Cannot set target current.")
            return

        try:
            target_current_mA = float(entry_field.get())
            ideal_emission_current = target_current_mA / 0.72 # this is from CCS Software Dev Spec _2024-06-07A
            log_ideal_emission_current = np.log10(ideal_emission_current / 1000)
            self.log(f"Calculated ideal emission current for Cathode {['A', 'B', 'C'][index]}: {ideal_emission_current:.3f}mA", LogLevel.INFO)
            
            if ideal_emission_current == 0:
                # Set all related variables to zero
                self.reset_power_supply(index)
                return

            # Ensure current is within the data range
            if ideal_emission_current < min(self.emission_current_model.y_data) * 1000 or ideal_emission_current > max(self.emission_current_model.y_data) * 1000:
                self.log("Desired emission current is below the minimum range of the model.", LogLevel.DEBUG)
                self.reset_related_variables(index)
            else:
                # Calculate heater current from the ES440 model
                heater_current = self.emission_current_model.interpolate(log_ideal_emission_current, inverse=True)
                heater_voltage = self.heater_voltage_model.interpolate(heater_current)

                self.log(f"Interpolated heater current for Cathode {['A', 'B', 'C'][index]}: {heater_current:.3f}A", LogLevel.INFO)
                self.log(f"Interpolated heater voltage for Cathode {['A', 'B', 'C'][index]}: {heater_voltage:.3f}V", LogLevel.INFO)

                # Set Upper Voltage Limit and Upper Current Limit on the power supply
                if self.power_supplies and len(self.power_supplies) > index:
                    self.log(f"Setting voltage: {heater_voltage:.2f}", LogLevel.DEBUG)
                    self.power_supplies[index].enqueue_command('set_voltage', 3, heater_voltage,
                                                               callback=lambda response: self._set_voltage_callback(response, index, heater_voltage, heater_current))
        except ValueError:
            self.log("Invalid input for target current", LogLevel.ERROR)

    def _set_voltage_callback(self, response, index, heater_voltage, heater_current):
        if response == "OK":
            self.power_supplies[index].enqueue_command('set_current', 3, heater_current, 
                                                    callback=lambda response: self._set_current_callback(response, index, heater_voltage, heater_current))
        else:
            self.log(f"Failed to set voltage for Cathode {['A', 'B', 'C'][index]}.", LogLevel.ERROR)
            self.reset_related_variables(index)

    def _set_current_callback(self, response, index, heater_voltage, heater_current):
        if response == "OK":
            self.user_set_voltages[index] = heater_voltage
            self.power_supplies[index].enqueue_command('get_settings', 3, 
                                                    callback=lambda response: self._confirm_settings_callback(response, index, heater_voltage, heater_current))
        else:
            self.log(f"Failed to set current for Cathode {['A', 'B', 'C'][index]}.", LogLevel.ERROR)
            self.reset_related_variables(index)

    def _confirm_settings_callback(self, response, index, heater_voltage, heater_current):
        if response:
            settings_values = response.split('\n')[0].strip()
            if len(settings_values) == 8:
                set_voltage = int(settings_values[:4]) / 100.0
                set_current = int(settings_values[4:]) / 100.0
                
                voltage_mismatch = abs(set_voltage - heater_voltage) > 0.01
                current_mismatch = abs(set_current - heater_current) > 0.01
                
                if voltage_mismatch or current_mismatch:
                    self.log(f"Mismatch in set values for Cathode {['A', 'B', 'C'][index]}:", LogLevel.CRITICAL)
                    if voltage_mismatch:
                        self.log(f"  Voltage - Intended: {heater_voltage:.2f}V, Actual: {set_voltage:.2f}V", LogLevel.CRITICAL)
                    if current_mismatch:
                        self.log(f"  Current - Intended: {heater_current:.2f}A, Actual: {set_current:.2f}A", LogLevel.CRITICAL)
                    self.heater_voltage_vars[index].set(f"{set_voltage:.2f}")
                else:
                    self.log(f"Values confirmed for Cathode {['A', 'B', 'C'][index]}: {set_voltage:.2f}V, {set_current:.2f}A", LogLevel.INFO)
                    self._update_predictions(index, heater_voltage, heater_current)
            else:
                self.log(f"Invalid settings format for Cathode {['A', 'B', 'C'][index]}. Received: {settings_values}", LogLevel.ERROR)
        else:
            self.log(f"Failed to confirm set values for Cathode {['A', 'B', 'C'][index]}. No response received.", LogLevel.ERROR)

    def reset_related_variables(self, index):
        """ Resets display variables when setting voltage/current fails. """
        self.predicted_emission_current_vars[index].set('--')
        self.predicted_grid_current_vars[index].set('--')
        self.predicted_heater_current_vars[index].set('--')
        self.predicted_temperature_vars[index].set('--')
        if not self.voltage_set[index]:
            self.heater_voltage_vars[index].set('--')

    def reset_power_supply(self, index):
        """ Helper function to reset power supply voltage and current to zero """
        if self.power_supply_status[index]:
            self.power_supplies[index].enqueue_command('set_voltage', 3, 0.0,
                                                   callback=lambda response: self._reset_voltage_callback(response, index))
        else:
            self.predicted_emission_current_vars[index].set('--')
            self.predicted_grid_current_vars[index].set('--')
            self.predicted_heater_current_vars[index].set('--')
            self.heater_voltage_vars[index].set('--')
            self.predicted_temperature_vars[index].set('--')

    def _reset_voltage_callback(self, response, index):
        if response == "OK":
            self.power_supplies[index].enqueue_command('set_current', 3, 0.0,
                                                    callback=lambda response: self._reset_current_callback(response, index))
        else:
            self.log(f"Failed to reset voltage for Cathode {['A', 'B', 'C'][index]}.", LogLevel.ERROR)

    def _reset_current_callback(self, response, index):
        if response == "OK":
            self.log(f"Reset power supply settings for Cathode {['A', 'B', 'C'][index]}", LogLevel.INFO)
        else:
            self.log(f"Failed to reset current for Cathode {['A', 'B', 'C'][index]}.", LogLevel.ERROR)
        self.predicted_emission_current_vars[index].set('--')
        self.predicted_grid_current_vars[index].set('--')
        self.predicted_heater_current_vars[index].set('--')
        self.heater_voltage_vars[index].set('--')
        self.predicted_temperature_vars[index].set('--')

    def on_voltage_label_click(self, index):
        """ Handle clicks on heater voltage label to manually set heater voltage """
        if self.toggle_states[index]:
            msgbox.showwarning("Warning", "Disable the output before setting a new voltage.")
            return # exit the method if the output is already on

        new_voltage = tksd.askfloat("Set Heater Voltage", "Enter new heater voltage (V):", parent=self.parent)
        if new_voltage is not None:
            success = self.update_predictions_from_voltage(index, new_voltage)
            if success:
                self.heater_voltage_vars[index].set(f"{new_voltage:.2f}")
                setattr(self, f'last_set_voltage_{index}', new_voltage)
                self.voltage_set[index] = True
                self.entry_fields[index].delete(0, tk.END)
            else:
                self.log(f"Failed to set manual voltage for Cathode {['A', 'B', 'C'][index]}.", LogLevel.ERROR)

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
                self.log(f"Heater current {heater_current:.3f} is out of range [{min(cathode_model.x_data):.3f}, {max(cathode_model.x_data):.3f}]", LogLevel.WARNING)

            # Set voltage and current on the power supply
            if self.power_supplies and len(self.power_supplies) > index:
                self.power_supplies[index].enqueue_command('set_voltage', 3, voltage,
                                                       callback=lambda response: self._update_voltage_callback(response, index, voltage, heater_current))
                return True
            else:
                return False
        except ValueError as e:
            self.log(f"Error processing manual voltage setting: {str(e)}", LogLevel.ERROR)
            self.reset_related_variables(index)
            return False

    def _update_voltage_callback(self, response, index, voltage, heater_current):
        if response == "OK":
            self.power_supplies[index].enqueue_command('set_current', 3, heater_current,
                                                    callback=lambda response: self._update_current_callback(response, index, voltage, heater_current))
        else:
            self.log(f"Failed to set voltage for Cathode {['A', 'B', 'C'][index]}.", LogLevel.ERROR)
            self.reset_related_variables(index)

    def _update_current_callback(self, response, index, voltage, heater_current):
        if response == "OK":
            self.power_supplies[index].enqueue_command('get_settings', 3,
                                                    callback=lambda response: self._update_confirm_settings_callback(response, index, voltage, heater_current))
        else:
            self.log(f"Failed to set current for Cathode {['A', 'B', 'C'][index]}.", LogLevel.ERROR)
            self.reset_related_variables(index)

    def _update_confirm_settings_callback(self, response, index, voltage, heater_current):
        if response:
            settings_values = response.split('\n')[0].strip()
            if len(settings_values) == 8:
                set_voltage = int(settings_values[:4]) / 100.0
                set_current = int(settings_values[4:]) / 100.0
                
                voltage_mismatch = abs(set_voltage - voltage) > 0.01
                current_mismatch = abs(set_current - heater_current) > 0.01
                
                if voltage_mismatch or current_mismatch:
                    self.log(f"Mismatch in set values for Cathode {['A', 'B', 'C'][index]}:", LogLevel.CRITICAL)
                    if voltage_mismatch:
                        self.log(f"  Voltage - Intended: {voltage:.2f}V, Actual: {set_voltage:.2f}V", LogLevel.CRITICAL)
                    if current_mismatch:
                        self.log(f"  Current - Intended: {heater_current:.2f}A, Actual: {set_current:.2f}A", LogLevel.CRITICAL)
                else:
                    self.log(f"Values confirmed for Cathode {['A', 'B', 'C'][index]}: {set_voltage:.2f}V, {set_current:.2f}A", LogLevel.INFO)
                    self._update_predictions(index, voltage, heater_current)
            else:
                self.log(f"Invalid settings format for Cathode {['A', 'B', 'C'][index]}. Received: {settings_values}", LogLevel.ERROR)
        else:
            self.log(f"Failed to confirm set values for Cathode {['A', 'B', 'C'][index]}. No response received.", LogLevel.ERROR)

    def _update_predictions(self, index, voltage, heater_current):
        ideal_emission_current = self.emission_current_model.interpolate(np.log10(heater_current), inverse=True)
        predicted_grid_current = 0.28 * ideal_emission_current
        predicted_temperature_K = self.true_temperature_model.interpolate(heater_current)
        predicted_temperature_C = predicted_temperature_K - 273.15

        self.predicted_heater_current_vars[index].set(f'{heater_current:.2f} A')
        self.predicted_emission_current_vars[index].set(f'{ideal_emission_current * 1000:.2f} mA')
        self.predicted_grid_current_vars[index].set(f'{predicted_grid_current * 1000:.2f} mA')
        self.predicted_temperature_vars[index].set(f'{predicted_temperature_C:.0f} °C')
        self.heater_voltage_vars[index].set(f'{voltage:.2f}')
        self.user_set_voltages[index] = voltage

        self.log(f"Updated manual settings for Cathode {['A', 'B', 'C'][index]}: {voltage:.2f}V, {heater_current:.2f}A", LogLevel.INFO)

    def set_overtemp_limit(self, index, temp_var):
        try:
            new_limit = float(temp_var.get())
            self.overtemp_limit_vars[index].set(new_limit)
            self.log(f"Set overtemperature limit for Cathode {['A', 'B', 'C'][index]} to {new_limit:.2f}°C", LogLevel.INFO)
        except ValueError:
            self.log("Invalid input for overtemperature limit", LogLevel.ERROR)

    def log(self, message, level=LogLevel.INFO):
        if self.logger:
            self.logger.log(message, level)
        else:
            print(f"{level.name}: {message}")

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
            self.log(f"Echoback test result for Unit {unit}: {result}", LogLevel.ERROR)
        except Exception as e:
            self.log(f"Failed to perform echoback test on Unit {unit}: {str(e)}", LogLevel.ERROR)
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
                self.log(message, LogLevel.VERBOSE)
            else:
                raise Exception("Failed to read temperature")
        except Exception as e:
            self.log(f"Error reading temperature from Unit {unit}: {str(e)}", LogLevel.ERROR)
            msgbox.showerror("Temperature Read Error", f"Error reading temperature from Unit {unit}: {str(e)}")
