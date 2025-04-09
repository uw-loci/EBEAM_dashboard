# cathode_heating.py
import tkinter as tk
from tkinter import ttk
import tkinter.simpledialog as tksd
import tkinter.messagebox as msgbox
import datetime
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator
from matplotlib.dates import DateFormatter
from instrumentctl.ES440_cathode.ES440_cathode import ES440_cathode
from instrumentctl.power_supply_9104.power_supply_9104 import PowerSupply9104
from instrumentctl.E5CN_modbus.E5CN_modbus import E5CNModbus
from utils import ToolTip
import os, sys
import pandas as pd
import numpy as np
from utils import LogLevel

def resource_path(relative_path):
    """
    Get the absolute path to a resource file for both development and bundled executable environments.
    
    When running as a bundled executable, resources are stored in a temporary directory specified by
    sys._MEIPASS. In development, resources are relative to the current directory.
    
    Args:
        relative_path (str): Path to the resource relative to the base directory
        
    Returns:
        str: Absolute path to the resource
    """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS # type: ignore
    except AttributeError:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

class CathodeHeatingSubsystem:
    MAX_POINTS = 60  # Maximum number of points to display on the plot
    OVERTEMP_THRESHOLD = 200.0 # Overtemperature threshold in C
    ERROR_COLORS = {
        'normal': 'blue',         # Normal operation
        'overtemp': 'red',        # Overtemperature condition
        'ERROR': '#FFA500',       # Communication error
        'DISCONNECTED': '#808080'
    }

    
    
    def __init__(self, parent, com_ports, active, logger=None):
        """
        Initialize the cathode heating subsystem.
        
        Args:
            parent: Parent Tkinter widget for GUI elements
            com_ports (dict): Dictionary mapping device names to COM ports
                Format: {
                    'CathodeA PS': 'COM1',
                    'CathodeB PS': 'COM2',
                    'CathodeC PS': 'COM3',
                    'TempControllers': 'COM4'
                }
            logger: Optional logger instance for system events
        """
        self.parent = parent
        self.com_ports = com_ports
        self.logger = logger
        self.active = active

        # Power supply state tracking
        self.power_supplies_initialized = False
        self.voltage_set = [False, False, False]
        self.power_supplies = []
        self.toggle_states = [False for _ in range(3)]
        self.toggle_buttons = []
        self.ramp_toggle_buttons = []
        self.entry_fields = []
        self.user_set_voltages = [None, None, None]
        self.slew_rates = [0.01, 0.01, 0.01] # Default slew rates in V/s
        self.ramp_status = [True, True, True]
        self.current_options = {
            "Cathode A" : pd.read_csv('./subsystem/cathode_heating/powersupply_A.csv').to_dict(),
            "Cathode B" : pd.read_csv('./subsystem/cathode_heating/powersupply_B.csv').to_dict(),
            "Cathode C" : pd.read_csv('./subsystem/cathode_heating/powersupply_C.csv').to_dict(),
            "Interpolate" : self.interpolate
        }
        self.interpolate_setting = [self.current_options["Cathode A"], 
                                    self.current_options["Cathode B"], 
                                    self.current_options["Cathode C"],
                                    self.current_options["Interpolate"]]
        self.query_settings_buttons = []
        self.interpolate_comboboxes = []

        # Temperature controller state tracking
        self.temp_controllers_connected = False
        self.temperature_controller = None
        self.last_no_conn_log_time = [datetime.datetime.min for _ in range(3)]
        self.log_interval = datetime.timedelta(seconds=3) # E5CN timeout message interval

        # Initialize GUI variables
        self._init_prediction_variables()    # Predicted values for cathode behavior
        self._init_measurement_variables()   # Real-time hardware measurements
        self._init_config_variables()        # Configuration and safety settings

        # System initialization sequence
        self.init_cathode_model()                   # Initialize cathode physics models
        self.setup_gui()                            # Set up graphical interface
        self.initialize_temperature_controllers()   # Connect to temperature controllers
        self.initialize_power_supplies()            # Connect to power supplies
        self.update_data()                          # Start the data update loop

    def _init_prediction_variables(self):
        """
        Initialize GUI variables for predicted cathode behavior.
        
        Sets up StringVar objects for displaying predicted values including:
        - Emission currents
        - Grid currents
        - Heater currents 
        - Cathode temperatures
        
        All variables are initialized with '--' to indicate no data available.
        Each cathode (A, B, C) has its own set of prediction variables.
        """
        # Emission current predictions and ideal values (mA)
        self.ideal_cathode_emission_currents = [0.0 for _ in range(3)]
        self.predicted_emission_current_vars = [tk.StringVar(value='--') for _ in range(3)]
        
        # Grid current predictions - expect to intercept 28% of emission current
        self.predicted_grid_current_vars = [tk.StringVar(value='--') for _ in range(3)]
        
        # Heater current predictions - used for power supply control
        self.predicted_heater_current_vars = [tk.StringVar(value='--') for _ in range(3)]
        
        # Temperature predictions from heater current model
        self.predicted_temperature_vars = [tk.StringVar(value='--') for _ in range(3)]
    
    def _init_measurement_variables(self):
        """
        Initialize GUI variables for actual hardware measurements.
        
        Sets up StringVar objects for displaying real-time measurements including:
        - Heater voltages and currents
        - Target currents
        - Grid currents
        - Clamp temperatures
        
        Also initializes timing variables for data collection and plotting.
        """
        # Heater control and monitoring variables
        self.heater_voltage_vars = [tk.StringVar(value='--') for _ in range(3)]  # Set voltage
        self.actual_heater_voltage_vars = [tk.StringVar(value='-- V') for _ in range(3)]  # Measured voltage
        self.actual_heater_current_vars = [tk.StringVar(value='-- A') for _ in range(3)]  # Measured current
        
        # Beam current monitoring
        self.e_beam_current_vars = [tk.StringVar(value='--') for _ in range(3)]  # Total emission
        self.target_current_vars = [tk.StringVar(value='--') for _ in range(3)]  # Current hitting target
        self.grid_current_vars = [tk.StringVar(value='--') for _ in range(3)]  # Current intercepted by grid
        self.actual_target_current_vars = [tk.StringVar(value='-- mA') for _ in range(3)] # Measured target current

        # Temperature monitoring
        self.clamp_temperature_vars = [tk.StringVar(value='--') for _ in range(3)]  # Measured temperatures
        self.clamp_temp_labels = []  # Labels for temperature display
        
        # Plotting and timing variables
        self.last_plot_time = datetime.datetime.now()
        self.plot_interval = datetime.timedelta(seconds=5)  # Time between plot updates
        self.time_data = [[] for _ in range(3)]  # Timestamp arrays for plotting
        self.temperature_data = [[] for _ in range(3)]  # Temperature arrays for plotting

    def _init_config_variables(self):
        """
        Initialize GUI variables for configuration settings.
        
        Sets up variables for:
        - Power supply status display
        - Safety limit settings
        - Operating mode indicators
        - Protection status monitoring
        
        Implements system defaults and safety thresholds.
        """
        # Power supply status display variables
        self.current_display_vars = [tk.StringVar(value='--') for _ in range(3)]  # Current readings
        self.voltage_display_vars = [tk.StringVar(value='--') for _ in range(3)]  # Voltage readings
        self.operation_mode_var = [tk.StringVar(value='Mode: --') for _ in range(3)]  # CV/CC mode
        
        # Safety limit variables
        ## Temperature protection
        self.overtemp_limit_vars = [tk.DoubleVar(value=self.OVERTEMP_THRESHOLD) for _ in range(3)]
        self.overtemp_status_vars = [tk.StringVar(value='Normal') for _ in range(3)]
        
        ## Power supply protection
        self.overvoltage_limit_vars = [tk.StringVar(value=1.0) for _ in range(3)]  # Default 1.0V limit (centivolts)
        self.overcurrent_limit_vars = [tk.StringVar(value=8.5) for _ in range(3)]  # Default 8.5A limit (centiamps)

    def setup_gui(self):
        cathode_labels = ['A', 'B', 'C']
        style = ttk.Style()
        style.configure('Flat.TButton', padding=(0, 0, 0, 0), relief='flat', borderwidth=0)
        style.configure('Bold.TLabel', font=('Helvetica', 10, 'bold'))
        style.configure('RightAlign.TLabel', font=('Helvetica', 9), anchor='e')
        style.configure('OverTemp.TLabel', foreground='red', font=('Helvetica', 10, 'bold'))  # Overtemperature style
        style.configure('RampOn.TButton', background='green', foreground='black', font=('Helvetica', 8, 'bold'))
        style.configure('RampOff.TButton', background='red', foreground='black', font=('Helvetica', 8, 'bold')) # Ramp button style

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
        self.ramp_mode_vars = []
        self.slew_rate_vars = []
        heater_labels = ['Heater A output:', 'Heater B output:', 'Heater C output:']
        ramp_labels = ['Ramp status A:', 'Ramp Status B:', 'Ramp Status C:']
        for i in range(3):
            frame = ttk.LabelFrame(self.scrollable_frame, text=f'Cathode {cathode_labels[i]}', padding=(10, 5))
            frame.grid(row=0, column=i, padx=5, pady=0.1, sticky='nsew')
            self.cathode_frames.append(frame)

            frame.columnconfigure(1, weight=1)  # Allow notebook to expand
            frame.columnconfigure(2, weight=0)

            notebook = ttk.Notebook(frame)
            notebook.grid(row=0, column=0, columnspan=2, sticky='w', padx=5, pady=2)

            # toggle_button = tk.Button(frame, text="Ramp", background="green", command=lambda i=i: self.toggle_ramp(i))
            # toggle_button.grid(row=0, column=1, sticky='ne', padx=5, pady=0)
            # self.ramp_toggle_buttons.append(toggle_button)

            # Create the main tab
            main_tab = ttk.Frame(notebook)
            notebook.add(main_tab, text='Main')

            # Create the config tab
            config_tab = ttk.Frame(notebook)
            notebook.add(config_tab, text='Config')

            config_tab.columnconfigure(1, minsize=70)
            config_tab.columnconfigure(2, minsize=20)

            # Create target current (mA) and heater voltage labels
            
            # Set target current (mA) label
            set_target_label = ttk.Label(main_tab, text='Set Target Current (mA):', style='RightAlign.TLabel')
            set_target_label.grid(row=0, column=0, sticky='e')
            ToolTip(set_target_label, "Target current is predicted to be 72% of cathode emission current")
            entry_field = ttk.Entry(main_tab, width=7)
            entry_field.grid(row=0, column=1, sticky='w')
            self.entry_fields.append(entry_field)
            set_button = ttk.Button(main_tab, text="Set", width=4, command=lambda i=i, entry_field=entry_field: self.set_target_current(i, entry_field))
            set_button.grid(row=0, column=1, sticky='e')

            # Set heater voltage (V) label
            ttk.Label(main_tab, text='Set Heater (V):', style='RightAlign.TLabel').grid(row=1, column=0, sticky='e')
            voltage_label = ttk.Label(main_tab, textvariable=self.heater_voltage_vars[i], style='Bold.TLabel')
            voltage_label.grid(row=1, column=1, sticky='w')
            voltage_label.bind("<Button-1>", lambda e, i=i: self.on_voltage_label_click(i))
            ToolTip(voltage_label, plot_data=ES440_cathode.heater_voltage_current_data, voltage_var=self.predicted_heater_current_vars[i], current_var=self.heater_voltage_vars[i])

            # Create labels for predicted values
            
            # Predicted emission current (mA)
            pred_emission_label = ttk.Label(main_tab, text='Pred Emission Current (mA):', style='RightAlign.TLabel')
            pred_emission_label.grid(row=2, column=0, sticky='e')
            ttk.Label(main_tab, textvariable=self.predicted_emission_current_vars[i], style='Bold.TLabel').grid(row=2, column=1, sticky='w')

            # Predicted grid current (mA)
            set_grid_label = ttk.Label(main_tab, text='Pred Grid Current (mA):', style='RightAlign.TLabel')
            set_grid_label.grid(row=3, column=0, sticky='e')
            ToolTip(set_grid_label, "Grid expected to intercept 28% of cathode emission current")
            ttk.Label(main_tab, textvariable=self.predicted_grid_current_vars[i], style='Bold.TLabel').grid(row=3, column=1, sticky='w')
            
            # Predicted heater current (A)
            ttk.Label(main_tab, text='Pred Heater Current (A):', style='RightAlign.TLabel').grid(row=4, column=0, sticky='e')
            ttk.Label(main_tab, textvariable=self.predicted_heater_current_vars[i], style='Bold.TLabel').grid(row=4, column=1, sticky='w')

            # Predicted cathode temperature (C)
            ttk.Label(main_tab, text='Pred CathTemp (C):', style='RightAlign.TLabel').grid(row=5, column=0, sticky='e')
            ttk.Label(main_tab, textvariable=self.predicted_temperature_vars[i], style='Bold.TLabel').grid(row=5, column=1, sticky='w')

            # Create entries and display labels
            heater_label = ttk.Label(main_tab, text=heater_labels[i], style='Bold.TLabel')
            heater_label.grid(row=6, column=0, sticky='e', padx=(0, 5))

            control_frame = ttk.Frame(main_tab)
            control_frame.grid(row=6, column=1, sticky='w')

            # Create a label frame for radio buttons with title
            ramp_frame = ttk.Frame(control_frame)
            ramp_frame.grid(row=0, column=0, padx=(0, 10))

            ramp_var = tk.StringVar(value="gradual" if self.ramp_status[i] else "immediate")
            gradual_radio = ttk.Radiobutton(
                ramp_frame, 
                text="Ramp Mode",
                value="gradual",
                variable=ramp_var,
                command=lambda i=i, v=ramp_var: self.set_ramp_mode(i, True)
            )
            immediate_radio = ttk.Radiobutton(
                ramp_frame,
                text="Immediate Set",
                value="immediate",
                variable=ramp_var,
                command=lambda i=i, v=ramp_var: self.set_ramp_mode(i, False)
            )
            gradual_radio.grid(row=0, column=0, sticky='w', padx=1, pady=1)
            immediate_radio.grid(row=1, column=0, sticky='w', padx=1, pady=1)
            
            self.ramp_mode_vars.append(ramp_var)

            # Create toggle switch for output
            toggle_button = ttk.Button(control_frame, image=self.toggle_off_image, style='Flat.TButton', 
                                       command=lambda i=i: self.toggle_output(i))
            toggle_button.grid(row=0, column=1)

            self.toggle_buttons.append(toggle_button)
            
            ToolTip(ramp_frame, f"Slow Ramp Mode: Increases output voltage to set point at 0.1V/s\nImmediate: direct set voltage application")

            # Create measured values labels
            
            # Actual heater current (A)
            ttk.Label(main_tab, text='Act Heater (A):', style='RightAlign.TLabel').grid(row=7, column=0, sticky='e')
            ttk.Label(main_tab, textvariable=self.actual_heater_current_vars[i], style='Bold.TLabel').grid(row=7, column=1, sticky='w')
            
            # Actual heater voltage (V)
            ttk.Label(main_tab, text='Act Heater (V):', style='RightAlign.TLabel').grid(row=8, column=0, sticky='e')
            ttk.Label(main_tab, textvariable=self.actual_heater_voltage_vars[i], style='Bold.TLabel').grid(row=8, column=1, sticky='w')
            
            # Actual target current (mA)
            ttk.Label(main_tab, text='Act Target (mA):', style='RightAlign.TLabel').grid(row=9, column=0, sticky='e')
            ttk.Label(main_tab, textvariable=self.actual_target_current_vars[i], style='Bold.TLabel').grid(row=9, column=1, sticky='w')
            
            # Temperature monitoring (C)
            ttk.Label(main_tab, text='Act ClampTemp (C):', style='RightAlign.TLabel').grid(row=10, column=0, sticky='e')
            clamp_temp_label = ttk.Label(main_tab, textvariable=self.clamp_temperature_vars[i], style='Bold.TLabel')
            clamp_temp_label.grid(row=10, column=1, sticky='w')
            self.clamp_temp_labels.append(clamp_temp_label)

            # Create plot for each cathode
            fig, ax = plt.subplots(figsize=(2.8, 1.3))
            line, = ax.plot([], [])
            self.temperature_data[i].append(line)
            ax.set_xlabel('Time', fontsize=8)
            ax.set_ylim(15, 80)
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
            overtemp_label = ttk.Label(config_tab, text='Overtemp Limit (C):', style='RightAlign.TLabel')
            overtemp_label.grid(row=1, column=0, sticky='e')

            temp_overtemp_var = tk.StringVar(value=str(self.OVERTEMP_THRESHOLD))
            overtemp_entry = ttk.Entry(config_tab, textvariable=temp_overtemp_var, width=7)
            overtemp_entry.grid(row=1, column=1, sticky='w')
            
            set_overtemp_button = ttk.Button(config_tab, text="Set", width=4, command=lambda i=i, var=temp_overtemp_var: self.set_overtemp_limit(i, var))
            set_overtemp_button.grid(row=1, column=2, sticky='e')

            # Overvoltage limit entry
            overvoltage_label = ttk.Label(config_tab, text='Overvoltage Limit (V):', style='RightAlign.TLabel')
            overvoltage_label.grid(row=2, column=0, sticky='e')

            temp_overvoltage_var = self.overvoltage_limit_vars[i]
            overvoltage_entry = ttk.Entry(config_tab, textvariable=temp_overvoltage_var, width=7)
            overvoltage_entry.grid(row=2, column=1, sticky='w')

            set_overvoltage_button = ttk.Button(config_tab, text="Set", width=4, command=lambda i=i: self.set_overvoltage_limit(i))
            set_overvoltage_button.grid(row=2, column=2, sticky='e')
            ToolTip(overvoltage_label, "OVP must be a value greater than 0.02 V and less than or equal to 84 V")

            # Overcurrent limit entry
            overcurrent_label = ttk.Label(config_tab, text='Overcurrent Limit (A):', style='RightAlign.TLabel')
            overcurrent_label.grid(row=3, column=0, sticky='e')

            temp_overcurrent_var = self.overcurrent_limit_vars[i]
            overcurrent_entry = ttk.Entry(config_tab, textvariable=temp_overcurrent_var, width=7)
            overcurrent_entry.grid(row=3, column=1, sticky='w')
            set_overcurrent_button = ttk.Button(config_tab, text="Set", width=4, command=lambda i=i: self.set_overcurrent_limit(i))
            set_overcurrent_button.grid(row=3, column=2, sticky='e')
            ToolTip(overcurrent_label, "OCP must be a value greater than 0.1 A and less than or equal to 10 A")

            # Slew Rate setting
            slew_rate_label = ttk.Label(config_tab, text='Slew Rate (V/s):', style='RightAlign.TLabel')
            slew_rate_label.grid(row=4, column=0, sticky='e')
            
            slew_rate_var = tk.StringVar(value='0.01')  # Default value
            slew_rate_entry = ttk.Entry(config_tab, textvariable=slew_rate_var, width=7)
            slew_rate_entry.grid(row=4, column=1, sticky='w')
            set_slew_rate_button = ttk.Button(config_tab, text="Set", width=4, command=lambda i=i, var=slew_rate_var: self.set_slew_rate(i, var))
            set_slew_rate_button.grid(row=4, column=2, sticky='e')
            ToolTip(slew_rate_label, "Rate of change for voltage output")
            
            # Slew Rate setting
            # ttk.Label(config_tab, text='Slew Rate (V/s):', style='RightAlign.TLabel').grid(row=4, column=0, sticky='e')
            # slew_rate_var = tk.StringVar(value='0.01')  # Default value
            # slew_rate_entry = ttk.Entry(config_tab, textvariable=slew_rate_var, width=7)
            # slew_rate_entry.grid(row=4, column=1, sticky='w')
            # set_slew_rate_button = ttk.Button(config_tab, text="Set", width=4, command=lambda i=i, var=slew_rate_var: self.set_slew_rate(i, var))
            # set_slew_rate_button.grid(row=4, column=2, sticky='e')
            # self.slew_rate_vars.append(slew_rate_var) # store user variable
            # ToolTip(slew_rate_label, "Rate of change for voltage output")

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

            # Add dropdown for interpolate_setting
            interpolate_label = ttk.Label(config_tab, text='Select Interpolation Setting:', style='RightAlign.TLabel')
            interpolate_label.grid(row=5, column=0, sticky='e')

            interpolate_options = list(self.current_options.keys())
            interp_box = ttk.Combobox(config_tab, values=interpolate_options, state='readonly')
            interp_box.grid(row=5, column=1, sticky='w')
            interp_box.set(f"Cathode {['A', 'B', 'C'][i]}")
            interp_box.bind("<<ComboboxSelected>>", lambda event, idx=i: self.on_interp_change(event, idx))

            self.interpolate_comboboxes.append(interp_box)

        # Ensure the grid layout of config_tab accommodates the new buttons
        config_tab.columnconfigure(0, weight=1)
        config_tab.columnconfigure(1, weight=1)

        self.init_time = datetime.datetime.now()

    def update_com_ports(self, new_com_ports):
        """
        Update COM port assignments for power supplies and temperature controllers.
        
        Args:
            new_com_ports (dict): Dictionary containing new COM port assignments
            
        Returns:
            bool: True if all updates were successful, False otherwise
        """
        self.log("Beginning COM port update procedure", LogLevel.INFO)
        
        # Validate input
        required_ports = {'CathodeA PS', 'CathodeB PS', 'CathodeC PS', 'TempControllers'}
        if not all(port in new_com_ports for port in required_ports):
            self.log("Missing required COM port assignments", LogLevel.ERROR)
            return False

        update_success = True
        
        self._disconnect_existing_connections()
        
        try:
            # Update power supply ports
            ps_update_success = self._update_power_supply_ports(new_com_ports)
            if not ps_update_success:
                self.log("Some power supply port updates failed", LogLevel.WARNING)
                update_success = False
            
            # Update temperature controller port
            tc_update_success = self._update_temperature_controller_port(new_com_ports)
            if not tc_update_success:
                self.log("Temperature controller port update failed", LogLevel.WARNING)
                update_success = False
                
            # Update internal COM ports dictionary
            self._update_com_ports_dictionary(new_com_ports)
            
            # Reinitialize connections with new ports
            if update_success:
                self.initialize_power_supplies()
                if self.power_supplies_initialized:
                    self.log("Power supplies reinitialized successfully", LogLevel.INFO)
                else:
                    self.log("Power supplies reinitialization failed", LogLevel.ERROR)
                    update_success = False
            
            return update_success
            
        except Exception as e:
            self.log(f"Unexpected error during COM port update: {str(e)}", LogLevel.ERROR)
            return False
            
    def _disconnect_existing_connections(self):
        # Disconnect power supplies
        for idx, ps in enumerate(self.power_supplies):
            if ps is not None:
                try:
                    ps.disconnect()
                    self.log(f"Disconnected power supply {idx + 1}", LogLevel.DEBUG)
                except Exception as e:
                    self.log(f"Error disconnecting power supply {idx + 1}: {str(e)}", LogLevel.WARNING)
        
        # Disconnect temperature controller
        if self.temperature_controller:
            try:
                self.temperature_controller.stop_reading()
                self.temperature_controller.disconnect()
                self.log("Disconnected temperature controller", LogLevel.DEBUG)
            except Exception as e:
                self.log(f"Error disconnecting temperature controller: {str(e)}", LogLevel.WARNING)

    def _update_power_supply_ports(self, new_com_ports):
        """
        Update power supply COM ports.
        
        Returns:
            bool: True if all critical updates succeeded
        """
        success = True
        cathode_ports = {
            'CathodeA PS': new_com_ports.get('CathodeA PS'),
            'CathodeB PS': new_com_ports.get('CathodeB PS'),
            'CathodeC PS': new_com_ports.get('CathodeC PS')
        }
        
        for idx, (cathode, new_port) in enumerate(cathode_ports.items()):
            if not new_port:
                self.log(f"No port specified for {cathode}", LogLevel.WARNING)
                continue
                
            if idx >= len(self.power_supplies):
                self.log(f"Cannot update {cathode}. Power supply index out of range.", LogLevel.ERROR)
                success = False
                continue
                
            try:
                # Verify port exists and is available
                if not self._verify_port_available(new_port):
                    self.log(f"Port {new_port} for {cathode} is not available", LogLevel.ERROR)
                    success = False
                    continue
                    
                # Update or create power supply instance
                if self.power_supplies[idx] is not None:
                    self.power_supplies[idx].update_com_port(new_port)
                else:
                    self.power_supplies[idx] = PowerSupply9104(port=new_port, logger=self.logger)
                    
                self.log(f"Successfully updated {cathode} to port {new_port}", LogLevel.INFO)
                
            except Exception as e:
                self.log(f"Failed to update {cathode} to port {new_port}: {str(e)}", LogLevel.ERROR)
                self.power_supplies[idx] = None
                success = False
        
        return success

    def _update_temperature_controller_port(self, new_com_ports):
        """
        Update temperature controller COM port.
        
        Returns:
            bool: True if update succeeded
        """
        new_port = new_com_ports.get('TempControllers')
        if not new_port:
            self.log("No port specified for temperature controllers", LogLevel.ERROR)
            return False
            
        try:
            if not self._verify_port_available(new_port):
                self.log(f"Port {new_port} for temperature controllers is not available", LogLevel.ERROR)
                return False
                
            self.initialize_temperature_controllers()
            if not self.temp_controllers_connected:
                self.log("Failed to initialize temperature controllers with new port", LogLevel.ERROR)
                self.active["Cathode Heating"] = False
                return False
                
            self.log(f"Successfully updated temperature controllers to port {new_port}", LogLevel.INFO)
            self.active["Cathode Heating"] = True # Update machine status bar
            return True
            
        except Exception as e:
            self.log(f"Error updating temperature controller port: {str(e)}", LogLevel.ERROR)
            return False

    def _update_com_ports_dictionary(self, new_com_ports):
        """Update internal COM ports dictionary with new assignments."""
        for port_name, port_value in new_com_ports.items():
            if port_value:  # Only update if port is specified
                self.com_ports[port_name] = port_value

    def _verify_port_available(self, port):
        """
        Verify if a COM port exists and is available.
        
        Returns:
            bool: True if port is available
        """
        try:
            import serial.tools.list_ports
            available_ports = [p.device for p in serial.tools.list_ports.comports()]
            return port in available_ports
        except Exception as e:
            self.log(f"Error verifying port availability: {str(e)}", LogLevel.ERROR)
            return False

    def initialize_power_supplies(self):
        if not self.power_supplies:
            self.power_supplies = [None, None, None]
        self.power_supply_status = [False, False, False]

        cathode_ports = {
            'CathodeA PS': self.com_ports.get('CathodeA PS'),
            'CathodeB PS': self.com_ports.get('CathodeB PS'),
            'CathodeC PS': self.com_ports.get('CathodeC PS')
        }

        for idx, (cathode, port) in enumerate(cathode_ports.items()):
            if port:
                try:
                    if self.power_supplies[idx] is None:
                        self.power_supplies[idx] = PowerSupply9104(port=port, logger=self.logger)
                    elif not self.power_supplies[idx].is_connected():
                        self.power_supplies[idx].update_com_port(port)

                    ps = self.power_supplies[idx]

                    # Set preset mode to 3
                    set_preset_response = ps.set_preset_selection(3)
                    if set_preset_response:
                        self.log(f"Set preset mode for {cathode} to 3.", LogLevel.INFO)
                    else:
                        self.log(f"Failed to set preset mode for {cathode} to 3. Response: {set_preset_response}", LogLevel.WARNING)
                    
                    # Confirm preset mode
                    get_preset_response = ps.get_preset_selection()
                    if get_preset_response is None:
                        self.log(f"Failed to get preset mode for {cathode}", LogLevel.ERROR)
                    elif get_preset_response != 3:
                        self.log(f"Cathode {cathode} is not in preset mode 3 (normal mode). Current mode: {get_preset_response}", LogLevel.WARNING)
                    else:
                        self.log(f"Asserted preset mode 3 for cathode {cathode}. Response: {get_preset_response}", LogLevel.INFO)

                    # Set and confirm OVP
                    ovp_value = float(self.overvoltage_limit_vars[idx].get())
                    self.log(f"Setting OVP for cathode {cathode} to: {ovp_value:.2f}", LogLevel.DEBUG)
                    if ps.set_over_voltage_protection(ovp_value):
                        self.log(f"Set OVP for cathode {cathode} to {ovp_value:.2f}V", LogLevel.INFO)
                        
                        # Confirm the OVP setting
                        confirmed_ovp = ps.get_over_voltage_protection()
                        if confirmed_ovp is not None:
                            if abs(confirmed_ovp - ovp_value) < 0.1:  # 0.1V tolerance
                                self.log(f"OVP setting confirmed for cathode {cathode}: {confirmed_ovp:.2f}V", LogLevel.INFO)
                            else:
                                self.log(f"OVP mismatch for cathode {cathode}. Set: {ovp_value:.2f}V, Got: {confirmed_ovp:.2f}V", LogLevel.WARNING)
                        else:
                            self.log(f"Failed to confirm OVP setting for cathode {cathode}", LogLevel.WARNING)
                    else:
                        self.log(f"Failed to set OVP for cathode {cathode}", LogLevel.WARNING)

                    # Set and confirm OCP
                    ocp_value = float(self.overcurrent_limit_vars[idx].get())
                    self.log(f"Setting OCP for cathode {cathode} to: {ocp_value:.2f}A", LogLevel.DEBUG)
                    if ps.set_over_current_protection(ocp_value):
                        self.log(f"Set OCP for cathode {cathode} to {ocp_value:.2f}A", LogLevel.INFO)
                        
                        # Confirm the OCP setting
                        confirmed_ocp = ps.get_over_current_protection()
                        if confirmed_ocp is not None:
                            if abs(confirmed_ocp - ocp_value) < 0.05:  # 0.05A tolerance
                                self.log(f"OCP setting confirmed for cathode {cathode}: {confirmed_ocp:.2f}A", LogLevel.INFO)
                            else:
                                self.log(f"OCP mismatch for cathode {cathode}. Set: {ocp_value:.2f}A, Got: {confirmed_ocp:.2f}A", LogLevel.WARNING)
                        else:
                            self.log(f"Failed to confirm OCP setting for cathode {cathode}", LogLevel.WARNING)
                    else:
                        self.log(f"Failed to set OCP for cathode {cathode}", LogLevel.WARNING)

                    self.power_supply_status[idx] = True
                    self.log(f"Initialized {cathode} on port {port}", LogLevel.INFO)
                except Exception as e:
                    self.power_supplies[idx] = None
                    self.power_supply_status[idx] = False  
                    self.log(f"Failed to initialize {cathode} on port {port}: {str(e)}", LogLevel.ERROR)
            else:
                self.power_supplies[idx] = None
                self.power_supply_status[idx] = False
                self.log(f"No COM port specified for {cathode}", LogLevel.ERROR)

        # Update button states based on individual power supply status
        for idx, status in enumerate(self.power_supply_status):
            if idx < len(self.toggle_buttons):
                self.toggle_buttons[idx]['state'] = 'normal' if status else 'disabled'
                if not status:
                    self.log(f"Power supply {idx+1} not initialized. Button disabled.", LogLevel.DEBUG)
            else:
                self.log(f"Toggle button {idx+1} has not been initialized yet.", LogLevel.VERBOSE)

        self.power_supplies_initialized = any(self.power_supply_status)
        if not self.power_supplies_initialized:
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
                return True
            except Exception as e:
                self.log(f"Retry {attempt+1} failed: {str(e)}", LogLevel.ERROR)
        
        self.log(f"Failed to reconnect after {max_retries} attempts", LogLevel.ERROR)
        return False
    
    def set_slew_rate(self, index, var):
        """
        Set the voltage slew rate for a 9104 power supply.

        Args:
            index (int): Index of the power supply (0-2)
            var (tk.StringVar): Variable containing the new slew rate in V/s

        Raises:
            ValueError: If slew rate is invalid or negative
        """
        try:
            new_slew_rate = float(var.get())
            if new_slew_rate <= 0:
                raise ValueError("Slew rate must be positive.")
            self.slew_rates[index] = new_slew_rate
            self.log(f"Set slew rate for Cathode {['A', 'B', 'C'][index]} to {new_slew_rate:.2f} V/s", LogLevel.INFO)
        except ValueError as e:
            self.log(f"Invalid input for slew rate for Cathode {['A', 'B', 'C'][index]}: {str(e)}", LogLevel.ERROR)
            msgbox.showerror("Invalid Input", f"Invalid input for slew rate: {str(e)}")

    def set_ramp_mode(self, index, is_gradual):
        """
        Set the ramping mode for the specified power supply.
        
        Args:
            index (int): Index of the cathode (0-2)
            is_gradual (bool): True for gradual ramping, False for immediate changes
        """
        self.ramp_status[index] = is_gradual
        
        mode_str = "Gradual" if is_gradual else "Immediate"
        self.log(f"Set voltage mode for Cathode {['A', 'B', 'C'][index]} to {mode_str}", LogLevel.INFO)
        
        if not is_gradual:
            self.log(f"Immediate set voltage change mode for Cathode {index}", LogLevel.WARNING)

    def set_overvoltage_limit(self, index):
        if not self.power_supply_status[index]:
            self.log(f"Power supply {index + 1} is not initialized. Cannot set OVP.", LogLevel.ERROR)
            msgbox.showerror("Error", f"Power supply {index + 1} is not initialized. Cannot set OVP.")
            return

        try:
            raw_value = float(self.overvoltage_limit_vars[index].get())
            if raw_value < 0 or raw_value > 60:
                raise ValueError("OVP out of valid range (0-60 V).")
            
            self.log(f"Setting OVP for Cathode {['A', 'B', 'C'][index]} to: {raw_value:.2f}", LogLevel.DEBUG)
            ovp_set_response = self.power_supplies[index].set_over_voltage_protection(raw_value)
            if not ovp_set_response:
                self.log(f"Failed to set OVP for Cathode {['A', 'B', 'C'][index]}. Response: {ovp_set_response}", LogLevel.WARNING)
                return

            # Verify the set value
            ovp_get_response = self.power_supplies[index].get_over_voltage_protection()
            if ovp_get_response is None:
                self.log("OVP readback is None--possible comm issue", LogLevel.WARNING)
            else:
                # compare with actual float value
                if abs(ovp_get_response - raw_value) > 0.01:
                    self.log(
                        f"OVP mismatch for Cathode {['A','B','C'][index]}. "
                        f"Set: {raw_value:.2f}, Got: {ovp_get_response:.2f}",
                        LogLevel.WARNING
                    )
                else:
                    self.log(
                        f"OVP successfully set and confirmed for Cathode {['A','B','C'][index]}: "
                        f"{raw_value:.2f} V", LogLevel.INFO
                    )
                    msgbox.showinfo("Success", f"OVP set to {raw_value:.2f} V for Cathode {['A','B','C'][index]}")

        except ValueError as e:
            self.log(f"Invalid input for OVP limit for Cathode {['A', 'B', 'C'][index]}: {str(e)}", LogLevel.ERROR)
            msgbox.showerror("Error", f"Invalid input for OVP limit: {str(e)}")

    def set_overcurrent_limit(self, index):
        if not self.power_supply_status[index]:
            self.log(f"Power supply {index + 1} is not initialized. Cannot set OCP.", LogLevel.ERROR)
            msgbox.showerror("Error", f"Power supply {index + 1} is not initialized. Cannot set OCP.")
            return

        try:
            raw_value = float(self.overcurrent_limit_vars[index].get())
            if raw_value < 0 or raw_value > 10:
                raise ValueError("OCP out of valid range (0-10 A).")
            
            self.log(f"Setting OCP for Cathode {['A', 'B', 'C'][index]} to: {raw_value:.2f}", LogLevel.DEBUG)
            ocp_set_response = self.power_supplies[index].set_over_current_protection(raw_value)
            if not ocp_set_response:
                self.log(f"Failed to set OCP for Cathode {['A', 'B', 'C'][index]}. Response: {ocp_set_response}", LogLevel.WARNING)
                return

            # Verify the set value
            ocp_get_response = self.power_supplies[index].get_over_current_protection()
            if ocp_get_response is None or abs(ocp_get_response - raw_value) > 0.01:
                self.log(f"OCP mismatch for Cathode {['A', 'B', 'C'][index]}. Set: {raw_value:.2f}, Got: {ocp_get_response}", LogLevel.WARNING)
            else:
                self.log(f"OCP successfully set and confirmed for Cathode {['A', 'B', 'C'][index]}: {raw_value:.2f}A", LogLevel.INFO)
                msgbox.showinfo("Success", f"OCP set to {raw_value:.2f}A for Cathode {['A', 'B', 'C'][index]}")

        except ValueError:
            self.log(f"Invalid input for OCP limit for Cathode {['A', 'B', 'C'][index]}", LogLevel.ERROR)
            msgbox.showerror("Error", "Invalid input for OCP limit. Please enter a valid number.")

    def update_query_settings_button_states(self):
        for i, power_supply in enumerate(self.power_supplies):
            if i < len(self.query_settings_buttons):
                self.query_settings_buttons[i]['state'] = 'normal' if power_supply else 'disabled'

    def query_and_check_settings(self, index):
        if not self.power_supply_status[index]:
            self.log(f"Power supply {index} not initialized.", LogLevel.ERROR)
            return

        voltage, current = self.power_supplies[index].get_settings(3)  # Get settings for preset 3
        self.log(f"Raw settings response for Cathode {['A', 'B', 'C'][index]}", LogLevel.DEBUG)
        if voltage is None or current is None:
            self.log(f"Failed to retrieve settings for Cathode {['A', 'B', 'C'][index]}", LogLevel.ERROR)
            return

        try:
            expected_voltage = self.user_set_voltages[index]
            if expected_voltage is None:
                self.log(f"Cathode {['A', 'B', 'C'][index]} settings - Voltage{voltage:.2f}V, Current: {current:.2f}A", LogLevel.INFO)
            elif abs(voltage - expected_voltage) > 0.1:
                self.log(f"Voltage mismatch for Cathode {['A', 'B', 'C'][index]}: Set: {expected_voltage:.2f}V, Actual: {voltage:.2f}V", LogLevel.ERROR)
            else:
                self.log(f"Cathode {['A', 'B', 'C'][index]} voltage matches set value. Voltage: {voltage:.2f}V, Current: {current:.2f}A", LogLevel.INFO)

        except Exception as e:
            self.log(f"Error checking settings for Cathode {['A', 'B', 'C'][index]}: {str(e)}", LogLevel.ERROR)

    def init_cathode_model(self):
        """
        Initialize the physics model for cathode behavior prediction.

        Sets up three interedependent models:
        1. Heater voltage Model: Maps current to required voltage
        2. Emission current model: Predicts emission based on heater current 
        3. Temperature Model: Estimates cathode temperature
        """
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
        Initialize the connection to the E5CN Temperature controllers over Modbus.

        Attempts to:
        1. close any existing controller connections
        2. Establishes a new connection on configured port
        3. Starts a tempeature polling thread
        4. Verify communication with all controllers

        Returns:
            bool: True if initialization succeeded, False otherwise
        """
        port = self.com_ports.get('TempControllers', None)
        if not port:
            self.log("No port configured for temperature controllers", LogLevel.ERROR)
            return False
            
        # Ensure any existing controller is properly cleaned up
        if hasattr(self, 'temperature_controller') and self.temperature_controller:
            try:
                self.temperature_controller.stop_reading()
            except Exception as e:
                self.log(f"Error cleaning up existing controller: {str(e)}", LogLevel.ERROR)
                
        try:
            tc = E5CNModbus(port=port, logger=self.logger)
            if tc.start_reading_temperatures():
                self.temperature_controller = tc
                self.temp_controllers_connected = True
                self.log(f"Connected to all temperature controllers via Modbus on {port}", LogLevel.INFO)
                return True
            else:
                self.log(f"Failed to start temperature controllers at {port}", LogLevel.ERROR)
                self.temp_controllers_connected = False
                return False
        except Exception as e:
            self.log(f"Exception while initializing temperature controllers at {port}: {str(e)}", LogLevel.ERROR)
            self.temp_controllers_connected = False
            return False

    def set_plot_color(self, index, error_type=None):
        """
        Update plot colors based on system state.
        
        Args:
            index (int): Index of the plot to update (0-2)
            error_type (str, optional): Type of error condition
                - 'ERROR': Orange for communication errors
                - 'DISCONNECTED': Black getting/recieving packets
                - 'overtemp': Red for over-temperature condition
                - None: Blue for normal operation
        """
        ax = self.temperature_data[index][0].axes
        line = self.temperature_data[index][0]
        
        color = self.ERROR_COLORS.get(error_type if error_type else 'normal')
        
        # Update plot elements
        for spine in ax.spines.values():
            spine.set_color(color)
        ax.xaxis.label.set_color(color)
        ax.yaxis.label.set_color(color)
        ax.tick_params(axis='both', colors=color)
        line.set_color(color)
        ax.figure.canvas.draw()

    def read_temperature(self, index):
        """
        Read temperature from the temperature controller or set to zero if the controller is not initialized or fails.
        Index corresponds to the cathode index (0-based).
        """
        current_time = datetime.datetime.now()
        if self.temperature_controller and self.temperature_controller.connected:
            try:
                # Attempt to read temperature from the connected temperature controller
                temperature = self.temperature_controller.temperatures[index]
                if isinstance(temperature, float):
                    self.clamp_temperature_vars[index].set(f"{temperature:.2f} C")

                    # Check for overtemperature condition
                    if temperature > self.overtemp_limit_vars[index].get():
                        self.set_plot_color(index, 'overtemp') # set plot to red for overtemp
                    else:
                        self.set_plot_color(index, None) # set plot to blue for normal

                    return temperature
                elif isinstance(temperature, str):
                    self.clamp_temperature_vars[index].set("-- C")
                    self.set_plot_color(index, 'ERROR')
                    self.log(f"Reading temperature for cathode {index+1} returned an error",
                              LogLevel.ERROR)
                else:
                    self.log(f"No temperature data for cathode {index+1}", LogLevel.WARNING)
            except Exception as e:
                self.log(f"Error reading temperature for cathode {index+1}: {str(e)}",
                          LogLevel.ERROR)
                self.set_plot_color(index, 'ERROR')  # Set plot to orange for no data
        else:
            # if current_time - self.last_no_conn_log_time[index] >= self.log_interval:
            self.log(f"No connection to CCS temperature controller {index+1}", LogLevel.DEBUG)
            self.last_no_conn_log_time[index] = current_time
            self.set_plot_color(index, 'DISCONNECTED')


        # Set temperature to zero as default
        self.clamp_temperature_vars[index].set("-- C")
        return None

    
    def update_data(self):
        current_time = datetime.datetime.now()
        plot_this_cycle = (current_time - self.last_plot_time) >= self.plot_interval

        for i in range(3):
            self.log(f"Processing Cathode {['A', 'B', 'C'][i]}", LogLevel.VERBOSE)

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
                            continue
                    
                    voltage, current, mode = self.power_supplies[i].get_voltage_current_mode()
                    self.log(f"Power supply {i+1} readings - Voltage: {voltage:.2f}V, Current: {current:.2f}A, Mode: {mode}", LogLevel.DEBUG)
                    
                    self.actual_heater_current_vars[i].set(f"{current:.2f} A" if current is not None else "-- A")
                    self.actual_heater_voltage_vars[i].set(f"{voltage:.2f} V" if voltage is not None else "-- V")
                    
                    # Update heater voltage display
                    if self.voltage_set[i] and hasattr(self, f'last_set_voltage_{i}'):
                        last_set_voltage = getattr(self, f'last_set_voltage_{i}')
                        self.heater_voltage_vars[i].set(f"{last_set_voltage:.2f} V")
                    elif voltage is not None:
                        self.heater_voltage_vars[i].set(f"{voltage:.2f} V")
                    else:
                        self.heater_voltage_vars[i].set("-- V")

                    # Update mode display
                    if mode in ["CV Mode", "CC Mode"]:
                        self.operation_mode_var[i].set(f'Mode: {mode}')
                    else:
                        self.operation_mode_var[i].set('Mode: --')
    
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

            if isinstance(temperature, float):
                self.clamp_temperature_vars[i].set(f"{temperature:.2f} C")
            elif isinstance(temperature, str):
                self.clamp_temperature_vars[i].set("-- C")
                self.clamp_temp_labels[i].config(foreground='oragne')
            else:
                self.clamp_temperature_vars[i].set("-- C")
                self.clamp_temp_labels[i].config(foreground='black')

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
            if mode in ["CV Mode", "CC Mode"]:
                self.operation_mode_var[i].set(f'Mode: {mode}')
            else:
                self.operation_mode_var[i].set('Mode: --')

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

    def update_plot(self, index):
        if len(self.time_data[index]) == 0:
            return
        
        time_data = self.time_data[index]
        temperature_data = self.temperature_data[index][0].get_data()[1]

        # Update the data points
        self.temperature_data[index][0].set_data(time_data, temperature_data)
        ax = self.temperature_data[index][0].axes
        
        DEFAULT_MIN = 15
        DEFAULT_MAX = 80
        MIN_SPAN = 10
        PADDING_FACTOR = 0.1

        valid_temps = [t for t in temperature_data if t is not None]
        if not valid_temps:
            ax.set_ylim(DEFAULT_MIN, DEFAULT_MAX)
        else:
            temp_min = min(valid_temps)
            temp_max = max(valid_temps)

            # Ensure minimum span and padding
            if temp_max - temp_min < MIN_SPAN:
                mid = (temp_max + temp_min) / 2
                temp_min = mid - MIN_SPAN/2
                temp_max = mid + MIN_SPAN/2

                padding = (temp_max - temp_min) * PADDING_FACTOR
                ax.set_ylim(temp_min - padding, temp_max + padding)


        # Adjust plot to new data
        ax.relim()
        ax.autoscale_view(scaley=False)  # Only autoscale x-axis
        ax.figure.canvas.draw()
        
    def toggle_ramp(self, index):
        """
        Toggle ramping mode for voltage changes.
        
        When enabled (default), voltage changes occur gradually at the configured slew rate.
        When disabled, voltage changes occur immediately.
        
        Args:
            index (int): Index of the cathode (0-2)
        """
        if not self.power_supplies_initialized or not self.power_supplies:
            self.log("Power supplies not properly initialized or list is empty.", LogLevel.ERROR)
            return

        self.ramp_status[index] =  not self.ramp_status[index] # flips status

        if self.ramp_status[index]:
            self.ramp_toggle_buttons[index].config(text="RAMP", style='RampOn.TButton')
            self.log(f"Enabled voltage ramping for Cathode {['A', 'B', 'C'][index]}", LogLevel.INFO)
        else:
            self.ramp_toggle_buttons[index].config(text="RAMP OFF", style='RampOff.TButton')
            self.log(f"Disabled voltage ramping for Cathode {['A', 'B', 'C'][index]} - voltage changes will be immediate", LogLevel.WARNING)

    def toggle_output(self, index):
        if not self.power_supplies_initialized or not self.power_supplies:
            self.log("Power supplies not properly initialized or list is empty.", LogLevel.ERROR)
            return

        new_state = not self.toggle_states[index]

        if new_state:  # If turning output ON
            if not self.power_supplies[index].set_output("1"):
                self.log(f"Failed to enable output for Cathode {['A', 'B', 'C'][index]}", LogLevel.ERROR)
                return
            target_voltage = self.user_set_voltages[index]
            if self.ramp_status[index]:
                if target_voltage is not None:
                    slew_rate = self.slew_rates[index]
                    step_delay = 1.0  # seconds
                    step_size = slew_rate * step_delay
                    
                    self.log(f"Starting voltage ramp with step size {step_size:.3f}V and delay {step_delay:.1f}s", LogLevel.INFO)
                    self.power_supplies[index].ramp_voltage(
                        target_voltage,
                        step_size=step_size,
                        step_delay=step_delay,
                        preset=3
                    )
            else: # ramp is off; just set output voltage
                if not self.power_supplies[index].set_voltage(voltage=target_voltage, preset=3):
                    self.log(f"Failed to set power supply {index} to voltage: {target_voltage}; ramp toggle off")
                    msgbox.showerror("Error", f"Failed to set voltage for Cathode {['A', 'B', 'C'][index]}")
                
        else:
            # turning off the output
            self.power_supplies[index].set_output("0")

        # Update the toggle state and button image
        self.toggle_states[index] = new_state
        current_image = self.toggle_on_image if self.toggle_states[index] else self.toggle_off_image
        self.toggle_buttons[index].config(image=current_image)
        
    def set_target_current(self, index, entry_field):
        """
        Set target beam current for a cathode and calculate required heater settings.

        Uses the target beam current to calculate ideal emission current, then determines
        the appropritate heater voltage and current using the ES440 cathode data model.

        Args:
            index (int): Index of the cathode (0-2)
            entry_field (ttk.Entry): Entry widget containing target current value

        Raises:
            ValueError: If target current is negative or invalid

        Side effects:
            - programs power supply voltage and current settings
            - updates predicted values displays (emission, grid current, temperature)
            - Updates heater voltage display
            - Logs actions and any errors
        """
        if self.toggle_states[index]:
            # if the output toggle is enabled, show a warning message
            msgbox.showwarning("Warning", "Disable the output before setting a new target current.")
            return

        if not self.power_supply_status[index]:
            self.log(f"Power supply {index + 1} is not initialized. Cannot set target current.", LogLevel.ERROR)
            msgbox.showerror("Error", f"Power supply {index + 1} is not initialized. Cannot set target current.")
            return
        
        if entry_field is None:
            self.log("Target current entry field is missing", LogLevel.ERROR)
            return

        try:
            target_current_mA = float(entry_field.get())
            ideal_emission_current = target_current_mA / 0.72 # this is from CCS Software Dev Spec _2024-06-07A
            if ideal_emission_current < 0:
                raise ValueError("Target current must be positive")
            
            log_ideal_emission_current = np.log10(ideal_emission_current / 1000)
            self.log(f"Calculated ideal emission current for Cathode {['A', 'B', 'C'][index]}: {ideal_emission_current:.3f}mA", LogLevel.INFO)
            
            if ideal_emission_current == 0:
                # Set all related variables to zero
                self.reset_power_supply(index)
                return

            # Ensure current is within the data range
            if ideal_emission_current < min(self.emission_current_model.y_data) * 1000 or ideal_emission_current > max(self.emission_current_model.y_data) * 1000:
                self.log("Desired emission current is below the minimum range of the model.", LogLevel.DEBUG)
                self.predicted_emission_current_vars[index].set('0.00')
                self.predicted_grid_current_vars[index].set('0.00')
                self.predicted_heater_current_vars[index].set('0.00')
                self.heater_voltage_vars[index].set('0.00')
                self.predicted_temperature_vars[index].set('0.00')
            else:
                # Calculate heater current from the ES440 model
                heater_current = self.emission_current_model.interpolate(log_ideal_emission_current, inverse=True)
                heater_voltage = self.heater_voltage_model.interpolate(heater_current)

                self.log(f"Interpolated heater current for Cathode {['A', 'B', 'C'][index]}: {heater_current:.3f}A", LogLevel.INFO)
                self.log(f"Interpolated heater voltage for Cathode {['A', 'B', 'C'][index]}: {heater_voltage:.3f}V", LogLevel.INFO)

                current_ovp = self.get_ovp(index)
                if current_ovp is None:
                    self.log(f"Unable to get current OVP for Cathode {['A', 'B', 'C'][index]}. Aborting voltage set.", LogLevel.ERROR)
                    return

                if heater_voltage > current_ovp:
                    self.log(f"Calculated voltage ({heater_voltage:.2f}V) exceeds OVP ({current_ovp:.2f}V) for Cathode {['A', 'B', 'C'][index]}. Aborting.", LogLevel.WARNING)
                    msgbox.showwarning("Voltage Exceeds OVP", f"The calculated voltage ({heater_voltage:.2f}V) exceeds the current OVP setting ({current_ovp:.2f}V). Please adjust the OVP or choose a lower target current.")
                    return

                # Set Upper Voltage Limit and Upper Current Limit on the power supply
                if self.power_supplies and len(self.power_supplies) > index:
                    self.log(f"Setting voltage: {heater_voltage:.2f}V and current: {heater_current:.2f}A", LogLevel.DEBUG)
                    voltage_set_success = self.power_supplies[index].set_voltage(3, heater_voltage)
                    current_set_success = self.power_supplies[index].set_current(3, heater_current)
                    
                    if voltage_set_success and current_set_success:
                        self.user_set_voltages[index] = heater_voltage
                        # Confirm the set values
                        set_voltage, set_current = self.power_supplies[index].get_settings(3)
                        if set_voltage is not None and set_current is not None:
                            voltage_mismatch = abs(set_voltage - heater_voltage) > 0.01  # 0.01V tolerance
                            current_mismatch = abs(set_current - heater_current) > 0.01  # 0.01A tolerance
                            
                            if voltage_mismatch or current_mismatch:
                                self.log(f"Mismatch in set values for Cathode {['A', 'B', 'C'][index]}:", LogLevel.WARNING)
                                if voltage_mismatch:
                                    self.log(f"  Voltage - Intended: {heater_voltage:.2f}V, Actual: {set_voltage:.2f}V", LogLevel.WARNING)
                                if current_mismatch:
                                    self.log(f"  Current - Intended: {heater_current:.2f}A, Actual: {set_current:.2f}A", LogLevel.WARNING)
                                # GUI is updated with actual voltage
                                self.heater_voltage_vars[index].set(f"{set_voltage:.2f}")
                            else:
                                self.log(f"Values confirmed for Cathode {['A', 'B', 'C'][index]}: {set_voltage:.2f}V, {set_current:.2f}A", LogLevel.INFO)
                        else:
                            self.log(f"Failed to confirm set values for Cathode {['A', 'B', 'C'][index]}. No response received.", LogLevel.ERROR)
                        
                        predicted_temperature_K = self.true_temperature_model.interpolate(heater_current)
                        predicted_temperature_C = predicted_temperature_K - 273.15  # Convert Kelvin to Celsius

                        predicted_grid_current = 0.28 * ideal_emission_current # display in milliamps
                        self.predicted_emission_current_vars[index].set(f'{ideal_emission_current:.2f} mA')
                        self.predicted_grid_current_vars[index].set(f'{predicted_grid_current:.2f} mA')
                        self.predicted_heater_current_vars[index].set(f'{heater_current:.2f} A')
                        self.predicted_temperature_vars[index].set(f'{predicted_temperature_C:.0f} C')
                        self.heater_voltage_vars[index].set(f'{heater_voltage:.2f}')
                        setattr(self, f'last_set_voltage_{index}', heater_voltage)
                        self.voltage_set[index] = True
                        self.log(f"Set Cathode {['A', 'B', 'C'][index]} power supply to {heater_voltage:.2f}V, targetting {heater_current:.2f}A heater current", LogLevel.INFO)
                    else:
                        self.reset_related_variables(index)
                        self.log(f"Failed to set voltage/current for Cathode {['A', 'B', 'C'][index]}.", LogLevel.ERROR)

        except ValueError as e:
            self.log("Invalid input for target current", LogLevel.ERROR)
            msgbox.showerror("Invalid Input", str(e))
            return

    def reset_related_variables(self, index):
        """
        Reset display variables when configuration action fails.

        Args:
            index (int): Index of the cathode power supply (0-2)

        Resets the following variables to '--':
            - Predicted emission current
            - Predicted grid current
            - Predicted heater current
            - Predicted temperature
            - Heater voltage (if not previously set)
        """
        self.predicted_emission_current_vars[index].set('--')
        self.predicted_grid_current_vars[index].set('--')
        self.predicted_heater_current_vars[index].set('--')
        self.predicted_temperature_vars[index].set('--')
        if not self.voltage_set[index]:
            self.heater_voltage_vars[index].set('--')

    def reset_power_supply(self, index):
        """
        Reset a power supply to zero voltage and current (UVL and UCL)

        Args:
            index (int): Index of the power supply to reset (0-2)

        Side effects:
            - Sets voltage and current to 0
            - Resets all prediction variables to '--'
            - Logs the reset action
        """
        if self.power_supply_status[index]:
            self.power_supplies[index].set_voltage(3, 0.0)
            self.power_supplies[index].set_current(3, 0.0)
            self.log(f"Reset power supply settings for Cathode {['A', 'B', 'C'][index]}", LogLevel.INFO)
        self.predicted_emission_current_vars[index].set('--')
        self.predicted_grid_current_vars[index].set('--')
        self.predicted_heater_current_vars[index].set('--')
        self.heater_voltage_vars[index].set('--')
        self.predicted_temperature_vars[index].set('--')

    def on_voltage_label_click(self, index):
        """ 
        Handler for user clicks on heater voltage label for manual voltage setting

        Args:
            index (int): Index of the clicked voltage label (0-2)

        Shows a dialog for voltage input if output is disabled. 
        Updates predictions and display values based on entered voltage.
        """
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
        """
        Calculate and update predicted values based on a manually set voltage.

        Args:
            index (int): Index of cathode (0-2)
            voltage (float): Manually entered voltage value

        Returns:
            bool: True if update successful, False if failed

        Updates:
            - Heater current prediction
            - Emission current prediction
            - Temperature prediction
            - Power supply settings
        """

        try:
            current_ovp = self.get_ovp(index)
            if current_ovp is None:
                self.log(f"Unable to get current OVP for Cathode {['A', 'B', 'C'][index]}. Aborting voltage set.", LogLevel.ERROR)
                return False

            if voltage > current_ovp:
                self.log(f"Requested voltage ({voltage:.2f}V) exceeds OVP ({current_ovp:.2f}V) for Cathode {['A', 'B', 'C'][index]}. Aborting.", LogLevel.WARNING)
                msgbox.showwarning("Voltage Exceeds OVP", f"The requested voltage ({voltage:.2f}V) exceeds the current OVP setting ({current_ovp:.2f}V). Please adjust the OVP or choose a lower voltage.")
                return False

            # Use the ES440_cathode model to interpolate current from voltage
            cathode_model = ES440_cathode([data[1] for data in ES440_cathode.heater_voltage_current_data], 
                                        [data[0] for data in ES440_cathode.heater_voltage_current_data], 
                                        log_transform=False)
            # heater_current = cathode_model.interpolate(voltage, inverse=True)
            heater_current = self.current_finder(index, voltage)
            # heater_current = self.heater_current(index, voltage)


            # Check if the interpolated current is within the model's range
            if not min(cathode_model.x_data) <= heater_current <= max(cathode_model.x_data):
                self.log(f"Heater current {heater_current:.3f} is out of range [{min(cathode_model.x_data):.3f}, {max(cathode_model.x_data):.3f}]", LogLevel.WARNING)

            # Set voltage and current on the power supply
            if self.power_supplies and len(self.power_supplies) > index:
                voltage_set_success = self.power_supplies[index].set_voltage(3, voltage)
                current_set_success = self.power_supplies[index].set_current(3, heater_current)
                if not voltage_set_success or not current_set_success:
                    self.log(f"Unable to set voltage: {voltage} or current: {heater_current} for Cathode {['A', 'B', 'C'][index]}", LogLevel.ERROR)
                    return False
                
                # Confirm the set values
                set_voltage, set_current = self.power_supplies[index].get_settings(3)
                if set_voltage is not None and set_current is not None:    
                    voltage_mismatch = abs(set_voltage - voltage) > 0.01  # 0.01V tolerance
                    current_mismatch = abs(set_current - heater_current) > 0.01  # 0.01A tolerance
                    
                    if voltage_mismatch or current_mismatch:
                        self.log(f"Mismatch in set values for Cathode {['A', 'B', 'C'][index]}:", LogLevel.WARNING)
                        if voltage_mismatch:
                            self.log(f"  Voltage - Intended: {voltage:.2f}V, Actual: {set_voltage:.2f}V", LogLevel.WARNING)
                        if current_mismatch:
                            self.log(f"  Current - Intended: {heater_current:.2f}A, Actual: {set_current:.2f}A", LogLevel.WARNING)
                        return False
                    else:
                        self.log(f"Values confirmed for Cathode {['A', 'B', 'C'][index]}: {set_voltage:.2f}V, {set_current:.2f}A", LogLevel.INFO)
                else:
                    self.log(f"Failed to confirm set values for Cathode {['A', 'B', 'C'][index]}. No valid response received", LogLevel.ERROR)
                    return False
                
                self.user_set_voltages[index] = voltage

            # Calculate dependent variables
            ideal_emission_current = self.emission_current_model.interpolate(np.log10(heater_current), inverse=True)
            predicted_grid_current = 0.28 * ideal_emission_current
            predicted_temperature_K = self.true_temperature_model.interpolate(heater_current)
            predicted_temperature_C = predicted_temperature_K - 273.15

            # Update GUI with new values
            self.predicted_heater_current_vars[index].set(f'{heater_current:.2f} A')
            self.predicted_emission_current_vars[index].set("--")
            self.predicted_grid_current_vars[index].set("--")
            self.predicted_temperature_vars[index].set("--")

            self.log(f"Updated manual settings for Cathode {['A', 'B', 'C'][index]}: {voltage:.2f}V, {heater_current:.2f}A", LogLevel.INFO)
            return True
        except ValueError as e:
            self.log(f"Error processing manual voltage setting: {str(e)}", LogLevel.ERROR)
            self.reset_related_variables(index)
            return False

    def get_ovp(self, index):
        """
        Get the current over-voltage protection setting.
        
        Args:
            index (int): Index of the power supply (0-2)
            
        Returns:
            float or None: Current OVP setting in volts, None if retrieval fails
        """
        try:
            ovp = self.power_supplies[index].get_over_voltage_protection()
            if ovp is not None:
                return ovp
            else:
                self.log(f"Failed to get OVP for Cathode {['A', 'B', 'C'][index]}", LogLevel.ERROR)
                return None
        except Exception as e:
            self.log(f"Error getting OVP for Cathode {['A', 'B', 'C'][index]}: {str(e)}", LogLevel.ERROR)
            return None

    def set_overtemp_limit(self, index, temp_var):
        try:
            new_limit = float(temp_var.get())
            self.overtemp_limit_vars[index].set(new_limit)
            self.log(f"Set overtemperature limit for Cathode {['A', 'B', 'C'][index]} to {new_limit:.2f}C", LogLevel.INFO)
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
            if not self.temperature_controller:
                raise ValueError(f"Temperature Controller is not connected or initialized.")

            # Perform the echoback test
            result = self.temperature_controller.perform_echoback_test(unit=unit)
            self.log(f"Echoback test result for Unit {unit}: {result}", LogLevel.INFO)
        except Exception as e:
            self.log(f"Failed to perform echoback test on Unit {unit}: {str(e)}", LogLevel.ERROR)
            msgbox.showerror("Echoback Test Error", f"Failed to perform echoback test on Unit {unit}: {str(e)}")

    def read_and_log_temperature(self, unit):
        """
        Read the temperature from the specified unit and log the result.
        Ensures the unit is connected before attempting to read.
        """
        try:
            if not self.temperature_controller:
                raise ValueError(f"Temperature Controller is not connected or initialized.")

            temperature = self.temperature_controller.read_temperature(unit=unit)
            if temperature is not None:
                message = f"Temperature from Unit {unit}: {temperature:.2f} C"
                self.log(message, LogLevel.VERBOSE)
            else:
                raise Exception("Failed to read temperature")
        except Exception as e:
            self.log(f"Error reading temperature from Unit {unit}: {str(e)}", LogLevel.ERROR)
            msgbox.showerror("Temperature Read Error", f"Error reading temperature from Unit {unit}: {str(e)}")
    
    def close_com_ports(self):
        """
        Closes the serial port connection and stops the serial thread upon quitting the application.
        """
        if hasattr(self, 'power_supplies') and self.power_supplies:
            for ps in self.power_supplies:
                if hasattr(ps, 'close'):
                    ps.close()

        if hasattr(self, 'temperature_controller') and self.temperature_controller:
            try:
               # self.temperature_controller.stop_reading()
                self.temperature_controller.disconnect()
            except Exception as e:
                self.log(f"Error cleaning up existing controller: {str(e)}", LogLevel.ERROR)

    def on_interp_change(self, event, index):
        """
        Handle changes in the interpolation setting dropdown.

        Args:
            event: The event triggered by changing the selection in the combobox.
            index: The index of the power supply to update.
        """
        selected_value = self.interpolate_comboboxes[index].get()

        if selected_value in self.current_options:
            self.log(f"Updating interpolation setting for Cathode {['A', 'B', 'C'][index]} to {selected_value}")
            self.interpolate_setting[index] = self.current_options[selected_value]
        else:
            self.log(f"Invalid selection: {selected_value}", LogLevel.WARNING)

    def current_finder(self, index, volt):
        assert 0 <= index <= 3

        if isinstance(self.interpolate_setting[index], dict):
            current =  self.interpolate_setting[index][volt]
        else:
           current = self.interpolate(volt)

        msgbox.showinfo("Current Value", f"The current for index {index} at voltage {volt} is: {current:.2f} A")

        return current

    def interpolate(self, voltage):
        """
        Interpolate the heater current based on the provided voltage.

        Args:
            voltage (float): The voltage to interpolate.

        Returns:
            float: The interpolated heater current.
        """
        try:
            # Use the existing heater_voltage_model
            if hasattr(self, 'heater_voltage_model'):
                return self.heater_voltage_model.interpolate(voltage, inverse=True)
            else:
                self.log("Heater voltage model not initialized", LogLevel.ERROR)
                return None
        except Exception as e:
            self.log(f"Interpolation error: {str(e)}", LogLevel.ERROR)
            return None