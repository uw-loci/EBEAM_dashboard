# cathode_heating.py
import tkinter as tk
from tkinter import ttk
import tkinter.messagebox as msgbox
import datetime
import threading
import time
from queue import Queue, Empty, Full
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator
from matplotlib.dates import DateFormatter
from instrumentctl.ES440_cathode.ES440_cathode import ES440_cathode
from instrumentctl.power_supply_9104.power_supply_9104 import PowerSupply9104
from instrumentctl.E5CN_modbus.E5CN_modbus import E5CNModbus
from utils import ToolTip
import os, sys
import numpy as np
import pandas as pd
from utils import LogLevel
from decimal import Decimal

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
    def _init_ocl_live_values(self):
        self.ocl_live_values = [None, None, None]

    def _init_ovl_live_values(self):
        self.ovl_live_values = [None, None, None]

    TEMPERATURE_GRAPHS_ENABLED = False  # Flip to True to restore the CCS temperature graphs.
    MAX_POINTS = 60  # Maximum number of points to display on the plot
    OVERTEMP_THRESHOLD = 200.0 # Overtemperature threshold in C
    POLL_ERROR_LOG_INTERVAL_SECONDS = 10.0
    WORKER_LOG_QUEUE_MAXSIZE = 1000
    # Failed deferred 9104 setup is retried by the poller, but not on every poll cycle.
    POWER_SUPPLY_CONFIG_RETRY_COOLDOWN_SECONDS = 10.0

    # Prediction model constants.
    # LUT beam_current values are in mA, and the system convention is that
    # 72% of total emitted current reaches the beam/target.
    BEAM_CURRENT_FRACTION_OF_EMISSION = 0.72
    RICHARDSON_CATHODE_DIAMETER_MM = 1.78
    RICHARDSON_CONSTANT_A_PER_CM2_K2 = 80.0
    RICHARDSON_WORK_FUNCTION_EV = 2.69
    BOLTZMANN_CONSTANT_EV_PER_K = 8.617333262145e-5
    
    # Outside-LUT calibration is dataset-specific. Add future LUT calibrations
    # here rather than changing the ES440 reference data or prediction logic.
    # Unlisted datasets retain the raw ES440/Richardson fallback (zero offsets).
    PREDICTION_MODEL_DEFAULT_CALIBRATION = {
        "heater_iv_voltage_offset_v": 0.0,
        "voltage_mode_model_offset_v": 0.0,
        "current_mode_temperature_offset_k": 0.0,
    }
    PREDICTION_MODEL_DATASET_CALIBRATIONS = {
        "Cbmark_Beam_A_07_2025.csv": {
            # Physical I-V alignment: 6.03 A -> 0.81 V at the LUT boundary.
            "heater_iv_voltage_offset_v": 0.2926,
            # Internal beam-model calibration used only when voltage binds.
            "voltage_mode_model_offset_v": 0.0914943979,
            # Internal beam-model calibration used only when current binds.
            "current_mode_temperature_offset_k": 511.0,
        },
    }

    OUTPUT_MODE_LABEL_TO_VALUE = {
        'Ramp Current': 'ramp_current',
        'Ramp Voltage': 'ramp_voltage',
        'Immediate Set': 'immediate'
    }
    OUTPUT_MODE_VALUE_TO_LABEL = {value: label for label, value in OUTPUT_MODE_LABEL_TO_VALUE.items()}
    ERROR_COLORS = {
        'normal': 'blue',         # Normal operation
        'overtemp': 'red',        # Overtemperature condition
        'ERROR': '#FFA500',       # Communication error
        'DISCONNECTED': '#808080'
    }
    
    def __init__(self, parent, com_ports, active, logger=None, cathode_datasets=None):
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
        self._main_thread_ident = threading.get_ident()
        self._log_queue = Queue(maxsize=self.WORKER_LOG_QUEUE_MAXSIZE)
        self._dropped_worker_log_count = 0
        self._dropped_worker_log_lock = threading.Lock()
        self.disable_logging_when_ccs_power_off = False
        self.ccs_power_on_provider = None
        self.active = active
        self.cathode_datasets = cathode_datasets or {}

        lut_rel = os.path.join('data', 'lut', 'power_supply')
        lut_dir = resource_path(lut_rel)
        self.lut_dir = lut_dir
        self.current_options = {}

        def has_valid_lut_columns(columns):
            required_cols = ['beam_current', 'voltage', 'heater_current']
            normalized = [str(col).strip() for col in columns]
            return len(normalized) == len(required_cols) and set(normalized) == set(required_cols)

        def validate_lut(df):
            required_cols = ['beam_current', 'voltage', 'heater_current']
            if not all(col in df.columns for col in required_cols):
                return False
            if df[required_cols].isnull().any().any():
                return False
            if len(df) == 0:
                return False
            return True

        if os.path.exists(lut_dir):
            for filename in os.listdir(lut_dir):
                if filename.lower().endswith('.csv'):
                    file_path = os.path.join(lut_dir, filename)
                    try:
                        # Fast eligibility check at startup from header/first row shape.
                        preview_df = pd.read_csv(file_path, nrows=1)
                        if not has_valid_lut_columns(preview_df.columns):
                            self.log(
                                f"LUT {filename} has invalid columns; expected beam_current, voltage, heater_current.",
                                LogLevel.WARNING,
                            )
                            self.current_options[filename] = None
                            continue

                        df = pd.read_csv(file_path)
                        if validate_lut(df):
                            self.current_options[filename] = df
                        else:
                            self.log(
                                f"LUT {filename} has invalid or empty data; disabling it for predictions.",
                                LogLevel.WARNING,
                            )
                            self.current_options[filename] = None
                    except Exception as e:
                        self.log(
                            f"Failed to load LUT {filename}: {e}",
                            LogLevel.ERROR,
                        )
                        self.current_options[filename] = None
        else:
            self.log(
                f"LUT directory not found: {lut_dir}",
                LogLevel.WARNING,
            )

        self.valid_lut_keys = sorted(
            [name for name, table in self.current_options.items() if isinstance(table, pd.DataFrame)],
            key=str.lower,
        )

        self.selected_lut_files = [None, None, None]
        if self.valid_lut_keys:
            initial_lut_key = self.valid_lut_keys[0]
        else:
            initial_lut_key = sorted(self.current_options.keys(), key=str.lower)[0] if self.current_options else None
        initial_lut = self.current_options.get(initial_lut_key, None) if initial_lut_key else None
        self.lookup_table_setting = [initial_lut, initial_lut, initial_lut]

        # Power supply state tracking
        self.power_supply_status = [False, False, False]
        self.power_supplies_initialized = False
        self.voltage_set = [False, False, False]
        self.current_set = [False, False, False]
        self.power_supplies = []
        self.toggle_states = [False for _ in range(3)]
        self.power_supply_poll_interval = 0.5
        self.power_supply_poll_thread = None
        self.power_supply_poll_stop_event = threading.Event()
        self.power_supply_poll_stop = self.power_supply_poll_stop_event
        self.disable_ccs_output_on_bcon_disconnect = True
        self.bcon_is_connected = None
        self.vtrx_ccs_pressure_allows_output = None
        # Tells the long-lived poller to pause while COM-port updates swap driver objects.
        self.power_supply_reconfiguring = threading.Event()
        self.power_supply_readback_lock = threading.Lock()
        self.power_supply_readbacks = [self._empty_power_supply_readback() for _ in range(3)]
        self.power_supply_valid_connections = [False, False, False]
        self.power_supply_last_logged_errors = [None, None, None]
        self.power_supply_last_error_log_times = [0.0, 0.0, 0.0]
        # Driver handles can exist before the 9104 has proven it can be read from
        # and configured with safety limits.
        # This state tracks that second step so operator commands stay disabled until it succeeds.
        self.power_supply_config_lock = threading.Lock()
        self.power_supply_configured = [False, False, False]
        self.power_supply_config_last_attempt = [0.0, 0.0, 0.0]
        self.power_supply_config_confirmed_limits = [{"ovp": None, "ocp": None} for _ in range(3)]
        self.power_supply_desired_limits = [{"ovp": None, "ocp": None} for _ in range(3)]
        self.temperature_valid_connections = [False, False, False]
        self.poll_error_last_log_times = {}
        self.poll_error_log_lock = threading.Lock()

        # GUI element references
        self.toggle_buttons = []
        self.stop_ramp_buttons = []
        self.ramp_toggle_buttons = []
        self.entry_fields = []
        self.user_set_voltages = [None, None, None]
        self.user_set_currents = [None, None, None]
        self.vlt_slew_rate = [0.02, 0.02, 0.02] # Default slew rates in V/s, 0.02 is mimimum ps resolution
        self.curr_slew_rate = [0.01, 0.01, 0.01] # Default slew rates in A/s, 0.01 is mimimum ps resolution
        self.ramp_status = [False, False, False]
        self.ramp_control_mode = ["current", "current", "current"] # "current" | "voltage"
        self.log_power_settings_buttons = []
        self.lookup_table_comboboxes = []
        self.curr_adjustment_buttons = []  # Track current +/- buttons 
        self.vlt_adjustment_buttons = []  # Track voltage +/- buttons 
        self.set_button_states = [] # Track both voltage and current set button states to disable during ramp
        self.power_supply_comms_indicators = []
        self.temperature_comms_indicators = []


        # Temperature controller state tracking
        self.temp_controllers_connected = False
        self.temperature_controller = None
        self.last_no_conn_log_time = [datetime.datetime.min for _ in range(3)]
        self.log_interval = datetime.timedelta(seconds=self.POLL_ERROR_LOG_INTERVAL_SECONDS) # E5CN timeout message interval

        # Reconnection backoff tracking — avoid hammering dead ports every 500 ms
        self.RECONNECT_COOLDOWN = datetime.timedelta(seconds=10)
        self.last_reconnect_attempt = [datetime.datetime.min for _ in range(3)]

        # Initialize GUI variables
        self._init_prediction_variables()    # Predicted values for cathode behavior
        self._init_measurement_variables()   # Real-time hardware measurements
        self._init_config_variables()        # Configuration and safety settings
        self._snapshot_desired_power_supply_limits()

        # System initialization sequence
        self.setup_gui()                            # Set up graphical interface
        self.initialize_temperature_controllers()   # Connect to temperature controllers
        self.initialize_power_supplies()            # Connect to power supplies
        self.start_power_supply_polling()           # Poll 9104 readbacks off the Tk thread
        self.after_id = None
        self._updates_cancelled = False
        self.update_data()                          # Start the data update loop

    def _style_lut_dropdown_items(self, combobox, options, retries=4):
        """Dim invalid LUT filenames in dropdown when Tk listbox styling is available."""
        try:
            popdown = combobox.tk.eval(f'ttk::combobox::PopdownWindow {str(combobox)}')
            listbox = f"{popdown}.f.l"
            if int(combobox.tk.call('winfo', 'exists', listbox)) != 1:
                raise RuntimeError("Combobox popdown listbox not ready")
            valid_set = set(self.valid_lut_keys)
            for idx, name in enumerate(options):
                color = '#404040' if name in valid_set else '#9a9a9a'
                combobox.tk.call(listbox, 'itemconfigure', idx, '-foreground', color)
        except Exception:
            if retries > 0:
                # First open can race popdown creation; retry shortly.
                combobox.after(30, lambda: self._style_lut_dropdown_items(combobox, options, retries=retries - 1))

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
        # Emission current predictions and ideal values (mA). None means unknown.
        self.ideal_cathode_emission_currents = [None for _ in range(3)]
        self.predicted_emission_current_vars = [tk.StringVar(value='--') for _ in range(3)]
        
        # Grid current predictions - expect to intercept 28% of emission current
        self.predicted_grid_current_vars = [tk.StringVar(value='--') for _ in range(3)]
        
        # Heater current predictions - used for power supply control
        self.predicted_heater_current_vars = [tk.StringVar(value='--') for _ in range(3)]

        # Heater voltage predictions - used for power supply control
        self.predicted_heater_voltage_vars = [tk.StringVar(value='--') for _ in range(3)]
        
        # Temperature predictions are currently unavailable for direct setpoint control.
        self.predicted_temperature_vars = [tk.StringVar(value='--') for _ in range(3)]

    def _set_predicted_emission_current_ma(self, index, value_ma=None):
        """Set or clear the numeric predicted emission current and display label."""
        if value_ma is None:
            self.ideal_cathode_emission_currents[index] = None
            self.predicted_emission_current_vars[index].set('--')
            return

        try:
            numeric_value = float(value_ma)
        except (TypeError, ValueError):
            numeric_value = None
        if numeric_value is None or not np.isfinite(numeric_value) or numeric_value < 0:
            self.ideal_cathode_emission_currents[index] = None
            self.predicted_emission_current_vars[index].set('--')
            return
        # Keep the machine-readable value and the operator-facing label in sync.
        self.ideal_cathode_emission_currents[index] = numeric_value
        self.predicted_emission_current_vars[index].set(f'{numeric_value:.2f} mA')

    def get_predicted_emission_currents_ma(self):
        """Return predicted cathode emission currents for A/B/C in mA.

        Each value is either a non-negative finite float or None when the
        prediction is unknown/unavailable.
        """
        currents = []
        for value in self.ideal_cathode_emission_currents[:3]:
            try:
                numeric_value = float(value)
            except (TypeError, ValueError):
                numeric_value = None
            currents.append(
                numeric_value
                if numeric_value is not None and np.isfinite(numeric_value) and numeric_value >= 0
                else None
            )
        return currents
    
    def _init_measurement_variables(self):
        """
        Initialize GUI variables for actual hardware measurements.
        
        Sets up StringVar objects for displaying real-time measurements including:
        - Heater voltages and currents
        - Clamp temperatures
        
        Also initializes timing variables for data collection and plotting.
        """
        # Heater control and monitoring variables
        self.heater_voltage_vars = [tk.StringVar(value='--') for _ in range(3)]  # Goal voltage
        self.heater_current_vars = [tk.StringVar(value='--') for _ in range(3)]  # Goal current
        self.sent_heater_voltage_vars = [tk.StringVar(value='--') for _ in range(3)]  # Sent voltage (not implemented)
        self.sent_heater_current_vars = [tk.StringVar(value='--') for _ in range(3)]  # Sent current (not implemented)
        self.actual_heater_voltage_vars = [tk.StringVar(value='--') for _ in range(3)]  # Measured voltage
        self.actual_heater_current_vars = [tk.StringVar(value='--') for _ in range(3)]  # Measured current
        
        # Temperature monitoring
        self.clamp_temperature_vars = [tk.StringVar(value='--') for _ in range(3)]  # Measured temperatures
        self.clamp_temp_labels = []  # Labels for temperature display
        
        # Plotting and timing variables
        self.last_plot_time = datetime.datetime.now()
        self.plot_interval = datetime.timedelta(seconds=5)  # Time between plot updates
        self.time_data = [[] for _ in range(3)]  # Timestamp arrays for plotting
        self.temperature_data = [[] for _ in range(3)]  # Temperature arrays for plotting
        self.plot_color_states = [None for _ in range(3)]  # Current plot color/error state

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
        self.operation_mode_var   = [tk.StringVar(value='Mode: --') for _ in range(3)]  # CV/CC mode
        
        # Safety limit variables
        ## Temperature protection
        self.overtemp_limit_vars  = [tk.DoubleVar(value=self.OVERTEMP_THRESHOLD) for _ in range(3)]
        self.overtemp_status_vars = [tk.StringVar(value='Normal') for _ in range(3)]
        
        ## Power supply protection
        self.overvoltage_limit_vars = [tk.DoubleVar(value=1.0) for _ in range(3)]  # Default 1.0V limit (volts)
        self.overcurrent_limit_vars = [tk.DoubleVar(value=9.0) for _ in range(3)]  # Default 9.0A limit (1.0V -> 9.0A per ES440 cathode, not 8.5A)
        self.ovl_readback_vars = [tk.StringVar(value='N/A') for _ in range(3)]
        self.ocl_readback_vars = [tk.StringVar(value='N/A') for _ in range(3)]

    def setup_gui(self):
        self._init_ocl_live_values()
        self._init_ovl_live_values()
        cathode_labels = ['A', 'B', 'C']
        style = ttk.Style()
        style.configure('Flat.TButton', padding=(0, 0, 0, 0), relief='flat', borderwidth=0)
        style.configure('Compact.TButton', font=('Segoe UI', 8), padding=(2, 0))
        style.configure('Bold.TLabel', font=('Segoe UI', 8, 'bold'))
        style.configure('SubpanelTitle.TLabel', font=('Segoe UI', 8, 'bold'))
        style.configure('Subpanel.TLabelframe', padding=(3, 2))
        style.configure('Subpanel.TLabelframe.Label', font=('Segoe UI', 8, 'bold'))
        style.configure('RightAlign.TLabel', font=('Segoe UI', 8), anchor='e')
        style.configure('Small.TLabel', font=('Segoe UI', 8))
        style.configure('OverTemp.TLabel', foreground='red', font=('Segoe UI', 8, 'bold'))  # Overtemperature style
        style.configure('RampOn.TButton', background='green', foreground='black', font=('Segoe UI', 8, 'bold'), padding=(2, 0))
        style.configure('RampOff.TButton', background='red', foreground='black', font=('Segoe UI', 8, 'bold'), padding=(2, 0)) # Ramp button style
        style.configure('StopInactive.TButton', foreground='grey', font=('Segoe UI', 8), padding=(2, 0))
        style.configure('StopActive.TButton',  foreground='red', font=('Segoe UI', 8), padding=(2, 0))

        # Load toggle images
        self.toggle_on_image = tk.PhotoImage(file=resource_path("media/toggle_on.png"))
        self.toggle_off_image = tk.PhotoImage(file=resource_path("media/toggle_off.png"))

        # Create main frame
        self.main_frame = ttk.Frame(self.parent)
        self.main_frame.pack(fill='both', expand=True)

        # Create a canvas and scrollbar for scrolling
        self.canvas = tk.Canvas(self.main_frame, highlightthickness=0)
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
        self.ramp_mode_dropdowns = []
        self.cv_cc_labels: list[tuple[tk.Label, tk.Label]] = []   # (cv_label, cc_label) per cathode
        self.slew_rate_vars = []
        for i in range(3):
            frame = ttk.LabelFrame(self.scrollable_frame, text=f'Cathode {cathode_labels[i]}', padding=(2, 2))
            frame.grid(row=0, column=i, padx=5, pady=0, sticky='nsew')
            self.cathode_frames.append(frame)

            frame.columnconfigure(1, weight=1)  # Allow notebook to expand
            frame.columnconfigure(2, weight=0)

            notebook = ttk.Notebook(frame)
            notebook.grid(row=0, column=0, columnspan=2, sticky='w', pady=0)

            # Create the main tab
            main_tab = ttk.Frame(notebook)
            notebook.add(main_tab, text='Main')
            main_tab.columnconfigure(0, weight=1)

            comms_frame = ttk.Frame(main_tab)
            comms_frame.grid(row=0, column=0, sticky='w', pady=(2, 2))
            ttk.Label(comms_frame, text="Comms:", font=("Segoe UI", 8, "bold")).grid(
                row=0,
                column=0,
                sticky='w',
                padx=(2, 8),
            )
            self.power_supply_comms_indicators.append(
                self._create_comms_indicator(comms_frame, "9104 Cathode Heater", row=0, column=1)
            )
            self.temperature_comms_indicators.append(
                self._create_comms_indicator(comms_frame, "E5CN Temp Sensor", row=0, column=2)
            )

            # Create the config tab
            config_tab = ttk.Frame(notebook)
            notebook.add(config_tab, text='Config')

            config_tab.columnconfigure(1, minsize=70)
            config_tab.columnconfigure(2, minsize=20)

            # ======Main Control Menu=====
            control_frame = ttk.Frame(main_tab)
            control_frame.grid(row=1, column=0, sticky='ew', padx=2, pady=(2, 1))
            control_frame.columnconfigure(0, weight=1)
            control_frame.rowconfigure(0, weight=0)
            control_frame.rowconfigure(1, weight=0)

            heater_controls_frame = ttk.Frame(control_frame)
            heater_controls_frame.grid(row=0, column=0, sticky='ew')
            heater_controls_frame.columnconfigure(0, weight=1, uniform='heater_controls')
            heater_controls_frame.columnconfigure(1, weight=1, uniform='heater_controls')

            # Create current control section
            current_control_frame = ttk.LabelFrame(heater_controls_frame, text='Heater Current Control', padding=(3, 2), style='Subpanel.TLabelframe')
            current_control_frame.grid(row=0, column=1, sticky='ew', padx=(4, 0))

            # Set target current entry box
            current_entry_frame = ttk.Frame(current_control_frame)
            current_entry_frame.grid(row=0, column=0, sticky='w')

            ttk.Label(current_entry_frame, text='Sent', style='RightAlign.TLabel').grid(row=0, column=0, sticky='w', padx=(0, 3))
            ttk.Label(current_entry_frame, text='Goal', style='RightAlign.TLabel').grid(row=1, column=0, sticky='w', padx=(0, 3), pady=(1, 0))
            ttk.Label(current_entry_frame, text='Entry', style='RightAlign.TLabel').grid(row=2, column=0, sticky='w', padx=(0, 3), pady=(1, 0))

            target_current = tk.DoubleVar(value=0.0)
            current_entry_field = ttk.Entry(current_entry_frame, textvariable=target_current, width=5)
            current_entry_field.grid(row=2, column=1, sticky='w', padx=(0, 2), pady=(1, 0))
            self.entry_fields.append(current_entry_field)

            set_current_button = ttk.Button(
                current_entry_frame,
                text="Set",
                width=4,
                style='Compact.TButton',
                state='disabled',
                command=lambda i=i, entry_field=current_entry_field: self.handle_current_entry_set(i, entry_field),
            )
            set_current_button.grid(row=2, column=2, sticky='w', padx=(2, 0), pady=(1, 0))

            current_display_frame = tk.Frame(current_entry_frame, bd=1, relief='groove', padx=1, pady=0)
            current_display_frame.configure(bg='#d9d9d9')
            current_display_frame.grid(row=0, column=1, sticky='w')
            current_label = ttk.Label(current_display_frame, textvariable=self.sent_heater_current_vars[i], style='Bold.TLabel')
            current_label.pack(side='left')
            unit_label = ttk.Label(current_display_frame, text=" A", style="Bold.TLabel")
            unit_label.pack(side='left')

            current_display_frame_secondary = tk.Frame(current_entry_frame, bd=1, relief='groove', padx=1, pady=0)
            current_display_frame_secondary.configure(bg='#d9d9d9')
            current_display_frame_secondary.grid(row=1, column=1, sticky='w', pady=(1, 0))
            current_label_secondary = ttk.Label(current_display_frame_secondary, textvariable=self.heater_current_vars[i], style='Bold.TLabel')
            current_label_secondary.pack(side='left')
            unit_label_secondary = ttk.Label(current_display_frame_secondary, text=" A", style="Bold.TLabel")
            unit_label_secondary.pack(side='left')

            inc_current_button = ttk.Button(
                current_entry_frame,
                text="+0.01",
                width=5,
                style='Compact.TButton',
                state='disabled',
                command=lambda i=i: self.adjust_current(i, 0.01),
            )
            inc_current_button.grid(row=3, column=1, sticky='w', pady=(1, 0))
            dec_current_button = ttk.Button(
                current_entry_frame,
                text="-0.01",
                width=5,
                style='Compact.TButton',
                state='disabled',
                command=lambda i=i: self.adjust_current(i, -0.01),
            )
            dec_current_button.grid(row=3, column=2, sticky='w', padx=(2, 0), pady=(1, 0))

            # Create voltage control section
            voltage_control_frame = ttk.LabelFrame(heater_controls_frame, text='Heater Voltage Control', padding=(3, 2), style='Subpanel.TLabelframe')
            voltage_control_frame.grid(row=0, column=0, sticky='ew')

            voltage_entry_frame = ttk.Frame(voltage_control_frame)
            voltage_entry_frame.grid(row=0, column=0, sticky='w')

            ttk.Label(voltage_entry_frame, text='Sent', style='RightAlign.TLabel').grid(row=0, column=0, sticky='w', padx=(0, 3))
            ttk.Label(voltage_entry_frame, text='Goal', style='RightAlign.TLabel').grid(row=1, column=0, sticky='w', padx=(0, 3), pady=(1, 0))
            ttk.Label(voltage_entry_frame, text='Entry', style='RightAlign.TLabel').grid(row=2, column=0, sticky='w', padx=(0, 3), pady=(1, 0))

            target_voltage = tk.DoubleVar(value=0.0)
            voltage_entry_field = ttk.Entry(voltage_entry_frame, textvariable=target_voltage, width=5)
            voltage_entry_field.grid(row=2, column=1, sticky='w', padx=(0, 2), pady=(1, 0))
            self.entry_fields.append(voltage_entry_field)

            set_voltage_button = ttk.Button(
                voltage_entry_frame,
                text="Set",
                width=4,
                style='Compact.TButton',
                state='disabled',
                command=lambda i=i, entry_field=voltage_entry_field: self.handle_voltage_entry_set(i, entry_field),
            )
            set_voltage_button.grid(row=2, column=2, sticky='w', padx=(2, 0), pady=(1, 0))

            self.set_button_states.append([set_voltage_button, set_current_button])

            voltage_display_frame = tk.Frame(voltage_entry_frame, bd=1, relief='groove', padx=1, pady=0)
            voltage_display_frame.configure(bg='#d9d9d9')
            voltage_display_frame.grid(row=0, column=1, sticky='w')
            voltage_label = ttk.Label(voltage_display_frame, textvariable=self.sent_heater_voltage_vars[i], style='Bold.TLabel')
            voltage_label.pack(side='left')
            unit_label = ttk.Label(voltage_display_frame, text=" V", style="Bold.TLabel")
            unit_label.pack(side='left')

            voltage_display_frame_secondary = tk.Frame(voltage_entry_frame, bd=1, relief='groove', padx=1, pady=0)
            voltage_display_frame_secondary.configure(bg='#d9d9d9')
            voltage_display_frame_secondary.grid(row=1, column=1, sticky='w', pady=(1, 0))
            voltage_label_secondary = ttk.Label(voltage_display_frame_secondary, textvariable=self.heater_voltage_vars[i], style='Bold.TLabel')
            voltage_label_secondary.pack(side='left')
            unit_label_secondary = ttk.Label(voltage_display_frame_secondary, text=" V", style="Bold.TLabel")
            unit_label_secondary.pack(side='left')

            inc_voltage_button = ttk.Button(
                voltage_entry_frame,
                text="+0.02",
                width=5,
                style='Compact.TButton',
                state='disabled',
                command=lambda i=i: self.adjust_voltage(i, 0.02),
            )
            inc_voltage_button.grid(row=3, column=1, sticky='w', pady=(1, 0))
            dec_voltage_button = ttk.Button(
                voltage_entry_frame,
                text="-0.02",
                width=5,
                style='Compact.TButton',
                state='disabled',
                command=lambda i=i: self.adjust_voltage(i, -0.02),
            )
            dec_voltage_button.grid(row=3, column=2, sticky='w', padx=(2, 0), pady=(1, 0))

            # Store adjustment buttons for enabling/disabling during ramps
            self.curr_adjustment_buttons.append([inc_current_button, dec_current_button])
            self.vlt_adjustment_buttons.append([inc_voltage_button, dec_voltage_button])

            # Create entries and display labels
            output_control_frame = ttk.LabelFrame(control_frame, text=f'Output {cathode_labels[i]}', padding=(3, 2), style='Subpanel.TLabelframe')
            output_control_frame.grid(row=1, column=0, sticky='ew', pady=(2, 0))
            output_control_frame.columnconfigure(0, weight=0)
            output_control_frame.columnconfigure(1, weight=0)

            # Create a label frame for output mode selector
            ramp_frame = ttk.Frame(output_control_frame)
            ramp_frame.grid(row=0, column=1, sticky='w', padx=(10, 0), pady=(0, 0))

            ttk.Label(ramp_frame, text='Output Mode', style='Small.TLabel').grid(row=0, column=0, sticky='w', padx=(0, 4), pady=(0, 0))

            ramp_var = tk.StringVar(value=self.OUTPUT_MODE_VALUE_TO_LABEL["immediate"])
            self.set_ramp_mode(i, "immediate") # Default to immediate set
            ramp_dropdown = ttk.Combobox(
                ramp_frame,
                textvariable=ramp_var,
                values=list(self.OUTPUT_MODE_LABEL_TO_VALUE.keys()),
                state='readonly',
                width=14
            )
            ramp_dropdown.bind(
                '<<ComboboxSelected>>',
                lambda _event, i=i, v=ramp_var: self.set_ramp_mode(
                    i,
                    self.OUTPUT_MODE_LABEL_TO_VALUE.get(v.get(), 'immediate')
                )
            )
            ramp_dropdown.grid(row=0, column=1, sticky='w', pady=(0, 0))

            self.ramp_mode_vars.append(ramp_var)
            self.ramp_mode_dropdowns.append(ramp_dropdown)

            # Create frame for output buttons
            output_button_frame = ttk.Frame(output_control_frame)
            output_button_frame.grid(row=0, column=0, sticky='w')

            # Create toggle switch for output
            toggle_button = ttk.Button(output_button_frame, image=self.toggle_off_image, style='Flat.TButton', 
                                       command=lambda i=i: self.toggle_output(i, self.ramp_control_mode[i]))
            toggle_button.grid(row=0, column=0, sticky='w')

            self.toggle_buttons.append(toggle_button)

            # Create stop ramp button
            stop_ramp_btn = ttk.Button(
                output_button_frame,
                text='STOP RAMP',
                width=10,
                state='disabled',                   # greyed‑out by default
                style='StopInactive.TButton',
                command=lambda i=i: self.stop_ramp(i)
            )
            stop_ramp_btn.grid(row=0, column=1, sticky='w', padx=(6, 0))
            self.stop_ramp_buttons.append(stop_ramp_btn)

            # Predicted Values
            predictions_frame = ttk.LabelFrame(main_tab, text='Predicted Output', padding=(3, 2), style='Subpanel.TLabelframe')
            predictions_frame.grid(row=2, column=0, sticky='ew', pady=(2, 0), padx=2)
            predictions_frame.columnconfigure(0, weight=0)
            predictions_frame.columnconfigure(1, weight=1)
            predictions_frame.columnconfigure(2, weight=0)
            predictions_frame.columnconfigure(3, weight=1)

            # LUT selector moved to Main tab so dataset toggling stays near predicted values.
            lut_selector_frame = ttk.Frame(predictions_frame)
            lut_selector_frame.grid(row=0, column=0, columnspan=4, sticky='ew', pady=(0, 2))
            lut_selector_frame.columnconfigure(1, weight=1)

            lookup_table_label = ttk.Label(lut_selector_frame, text='Lookup Table Dataset:', style='RightAlign.TLabel')
            lookup_table_label.grid(row=0, column=0, sticky='w')

            # Build options from loaded LUT CSV filenames.
            lookup_table_options = sorted(self.current_options.keys(), key=str.lower)

            lookup_table_box = ttk.Combobox(
                lut_selector_frame,
                values=lookup_table_options,
                state='readonly',
                width=30,
                postcommand=lambda box=None: self._style_lut_dropdown_items(lookup_table_box, lookup_table_options, retries=4)
            )
            lookup_table_box.grid(row=0, column=1, sticky='w', padx=(6, 0))
            self._style_lut_dropdown_items(lookup_table_box, lookup_table_options, retries=4)
            lookup_table_box.bind(
                '<Button-1>',
                lambda event, box=lookup_table_box, opts=lookup_table_options: self._style_lut_dropdown_items(box, opts, retries=4),
                add='+'
            )

            # Use any dataset specified by cathode_datasets; otherwise use first option.
            cfg_key = f'Cathode{cathode_labels[i]} PS'
            preferred = None
            if cfg_key in self.cathode_datasets:
                pref_path = self.cathode_datasets.get(cfg_key)
                if pref_path:
                    basename = os.path.basename(pref_path)
                    if basename in lookup_table_options and self.current_options.get(basename) is not None:
                        preferred = basename
                    else:
                        # try matching the absolute path
                        for opt in lookup_table_options:
                            candidate = os.path.join(self.lut_dir, opt)
                            try:
                                if os.path.normcase(os.path.abspath(candidate)) == \
                                   os.path.normcase(os.path.abspath(pref_path)):
                                    if self.current_options.get(opt) is not None:
                                        preferred = opt
                                        break
                            except Exception:
                                pass

            if preferred:
                lookup_table_box.set(preferred)
                self.selected_lut_files[i] = preferred
            else:
                first = self.valid_lut_keys[0] if self.valid_lut_keys else (lookup_table_options[0] if lookup_table_options else '')
                lookup_table_box.set(first)
                self.selected_lut_files[i] = first or None

            # finally record the active DataFrame
            self.lookup_table_setting[i] = self.current_options.get(self.selected_lut_files[i], None)

            # Bind LUT combobox to centralized class method
            def lut_selection_callback(event, idx=i, box=lookup_table_box):
                selected = box.get()
                if self.current_options.get(selected) is None:
                    previous = self.selected_lut_files[idx]
                    fallback = previous if previous and self.current_options.get(previous) is not None else (self.valid_lut_keys[0] if self.valid_lut_keys else '')
                    if fallback:
                        box.set(fallback)
                        self.selected_lut_files[idx] = fallback
                        self.lookup_table_setting[idx] = self.current_options.get(fallback, None)
                        self.log(
                            f"Dataset '{selected}' is invalid for LUT predictions. Reverted to '{fallback}'.",
                            LogLevel.WARNING,
                        )
                        self.refresh_predictions(idx)
                    return
                self.selected_lut_files[idx] = selected
                self.lookup_table_setting[idx] = self.current_options.get(selected, None)
                self.refresh_predictions(idx)
            lookup_table_box.bind("<<ComboboxSelected>>", lut_selection_callback)
            self.lookup_table_comboboxes.append(lookup_table_box)

            pred_emission_label = ttk.Label(predictions_frame, text='Emission (mA):', style='RightAlign.TLabel')
            pred_emission_label.grid(row=1, column=0, sticky='w')
            ttk.Label(predictions_frame, textvariable=self.predicted_emission_current_vars[i], style='Bold.TLabel').grid(row=1, column=1, sticky='w', padx=(2, 8))

            set_grid_label = ttk.Label(predictions_frame, text='Grid (mA):', style='RightAlign.TLabel')
            set_grid_label.grid(row=2, column=0, sticky='w')
            ToolTip(set_grid_label, "Grid expected to intercept 28% of cathode emission current")
            ttk.Label(predictions_frame, textvariable=self.predicted_grid_current_vars[i], style='Bold.TLabel').grid(row=2, column=1, sticky='w', padx=(2, 8))

            ttk.Label(predictions_frame, text='Heater Voltage (V):', style='RightAlign.TLabel').grid(row=1, column=2, sticky='w')
            ttk.Label(predictions_frame, textvariable=self.predicted_heater_voltage_vars[i], style='Bold.TLabel').grid(row=1, column=3, sticky='w', padx=(2, 0))

            ttk.Label(predictions_frame, text='Heater Current (A):', style='RightAlign.TLabel').grid(row=2, column=2, sticky='w')
            ttk.Label(predictions_frame, textvariable=self.predicted_heater_current_vars[i], style='Bold.TLabel').grid(row=2, column=3, sticky='w', padx=(2, 0))

            # Measured/Actual values
            measured_frame = ttk.LabelFrame(main_tab, text='Measured Output', padding=(3, 2), style='Subpanel.TLabelframe')
            measured_frame.grid(row=3, column=0, sticky='ew', pady=(2, 0), padx=2)
            
            # Voltage
            actual_voltage_frame = tk.Frame(measured_frame, bd=1, relief='groove', padx=1, pady=0)
            actual_voltage_frame.configure(bg='#d9d9d9')
            actual_voltage_frame.grid(row=0, column=0, sticky='w', padx=(0, 6))
            actual_voltage_label = ttk.Label(actual_voltage_frame, textvariable=self.actual_heater_voltage_vars[i], style='Bold.TLabel') 
            actual_voltage_label.pack(side='left')
            unit_label = ttk.Label(actual_voltage_frame, text=" V", style="Bold.TLabel")
            unit_label.pack(side='left')

            # Current
            actual_current_frame = tk.Frame(measured_frame, bd=1, relief='groove', padx=1, pady=0)
            actual_current_frame.configure(bg='#d9d9d9')
            actual_current_frame.grid(row=0, column=1, sticky='w', padx=(0, 8))
            actual_current_label = ttk.Label(actual_current_frame, textvariable=self.actual_heater_current_vars[i], style='Bold.TLabel') 
            actual_current_label.pack(side='left')
            unit_label = ttk.Label(actual_current_frame, text=" A", style="Bold.TLabel")
            unit_label.pack(side='left')
            
            # Temp
            ttk.Label(measured_frame, text='Temp', style='RightAlign.TLabel').grid(row=0, column=2, sticky='w', padx=(0, 2))
            actual_temp_frame = tk.Frame(measured_frame, bd=1, relief='groove', padx=1, pady=0)
            actual_temp_frame.configure(bg='#d9d9d9')
            actual_temp_frame.grid(row=0, column=3, sticky='w')
            actual_temp_label = ttk.Label(actual_temp_frame, textvariable=self.clamp_temperature_vars[i], style='Bold.TLabel') 
            actual_temp_label.pack(side='left')

            self.clamp_temp_labels.append(actual_temp_label)

            # CV / CC mode indicator
            indicator_frame = ttk.Frame(measured_frame)
            indicator_frame.grid(row=0, column=4, padx=(10, 0), sticky='e')

            cv_label = tk.Label(indicator_frame, text='CV', width=3,
                            fg='white', bg='grey', relief='ridge')
            cv_label.grid(row=0, column=0, padx=1)

            cc_label = tk.Label(indicator_frame, text='CC', width=3,
                            fg='white', bg='grey', relief='ridge')
            cc_label.grid(row=0, column=1, padx=1)

            self.cv_cc_labels.append((cv_label, cc_label))

            if self.TEMPERATURE_GRAPHS_ENABLED:
                # Create plot for each cathode
                fig, ax = plt.subplots(figsize=(2.8, 1.2))
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
                canvas.get_tk_widget().grid(row=4, column=0, sticky='ew', padx=2, pady=(4, 0))
            # ===== Config Tab =====
            ttk.Label(config_tab, text="Power Supply", style='Bold.TLabel').grid(row=0, column=0, columnspan=3, sticky="ew", pady=(2, 0))

            log_power_settings_button = ttk.Button(config_tab, text="Log Power Settings", width=18, command=lambda x=i: self.log_power_and_check_settings(x))
            log_power_settings_button.grid(row=0, column=1, sticky='w', padx=(184, 0))
            log_power_settings_button['state'] = 'disabled'
            self.log_power_settings_buttons.append(log_power_settings_button)

            # Overtemperature limit controls in a frame, with live value next to label
            otl_control_frame = ttk.Frame(config_tab)
            otl_control_frame.grid(row=11, column=0, columnspan=3, sticky='w', pady=(2, 2))

            # Frame to hold label and live value side-by-side
            otl_label_frame = ttk.Frame(otl_control_frame)
            otl_label_frame.grid(row=0, column=0, sticky='w')
            overtemp_label = ttk.Label(otl_label_frame, text='Overtemp Limit (C):', style='RightAlign.TLabel')
            overtemp_label.pack(side='left')
            # Live value display (styled box)
            otl_display_frame = tk.Frame(otl_label_frame, bd=2, relief='groove', padx=2, pady=1)
            otl_display_frame.configure(bg='#d9d9d9')
            otl_display_frame.pack(side='left', padx=(29, 0))
            # Bind live value to the actual overtemp_limit_vars[i]
            otl_live_label = ttk.Label(otl_display_frame, textvariable=self.overtemp_limit_vars[i], style='Bold.TLabel', width=6, anchor='e')
            otl_live_label.pack(side='left')
            otl_unit_label = ttk.Label(otl_display_frame, text=" C", style="Bold.TLabel")
            otl_unit_label.pack(side='left')

            temp_overtemp_var = tk.StringVar(value="")
            overtemp_entry = ttk.Entry(otl_control_frame, textvariable=temp_overtemp_var, width=7)
            overtemp_entry.grid(row=0, column=1, sticky='w', padx=(6, 2))
            set_overtemp_button = ttk.Button(otl_control_frame, text="Set", width=4, command=lambda i=i, var=temp_overtemp_var: self.set_overtemp_limit(i, var))
            set_overtemp_button.grid(row=0, column=2, sticky='w', padx=(2, 2))

            # Keep entry in sync with live value
            def sync_otl_entry(*args, idx=i, var=temp_overtemp_var):
                var.set(str(self.overtemp_limit_vars[idx].get()))
            self.overtemp_limit_vars[i].trace_add('write', sync_otl_entry)

            # Overvoltage limit controls in a frame, with live value next to label
            ovl_control_frame = ttk.Frame(config_tab)
            ovl_control_frame.grid(row=3, column=0, columnspan=3, sticky='w', pady=(2, 2))

            # Frame to hold label and live value side-by-side
            ovl_label_frame = ttk.Frame(ovl_control_frame)
            ovl_label_frame.grid(row=0, column=1, sticky='w')
            overvoltage_label = ttk.Label(ovl_label_frame, text='Overvoltage Limit (V):', style='RightAlign.TLabel')
            overvoltage_label.pack(side='left')
            # Live value display (styled box)
            ovl_display_frame = tk.Frame(ovl_label_frame, bd=2, relief='groove', padx=2, pady=1)
            ovl_display_frame.configure(bg='#d9d9d9')
            ovl_display_frame.pack(side='left', padx=(34, 0))
            ovl_readback = self.ovl_readback_vars[i]
            ovl_live_label = ttk.Label(ovl_display_frame, textvariable=ovl_readback, style='Bold.TLabel', width=4, anchor='e')
            ovl_live_label.pack(side='left')
            ovl_unit_label = ttk.Label(ovl_display_frame, text=" V", style="Bold.TLabel")
            ovl_unit_label.pack(side='left')

            # temp_overvoltage_var = self.overvoltage_limit_vars[i]
            temp_overvoltage_var = tk.StringVar(value="")  # Initialize with an empty string
            overvoltage_entry = ttk.Entry(ovl_control_frame, textvariable=temp_overvoltage_var, width=7)
            overvoltage_entry.grid(row=0, column=2, sticky='w', padx=(7, 2))
            set_overvoltage_button = ttk.Button(ovl_control_frame, text="Set", width=4)
            set_overvoltage_button.grid(row=0, column=3, sticky='w', padx=(1, 2))
            ToolTip(overvoltage_label, "OVP must be a value greater than 0.02 V and less than or equal to 84 V")

            def create_ovl_update_function(cathode_idx, readback_var):
                def update_ovl_live_box():
                    val = self.ovl_live_values[cathode_idx]
                    if val is not None:
                        readback_var.set(f"{val:.2f}")
                    else:
                        readback_var.set("N/A")
                return update_ovl_live_box
            update_ovl_live_box = create_ovl_update_function(i, ovl_readback)

            # Keep readback unknown until hardware confirms a value.
            self.ovl_live_values[i] = None
            update_ovl_live_box()

            def create_ovl_set_function(cathode_idx, update_func, entry_var):
                def set_and_update_ovl():
                    # First, validate the input value before updating anything
                    try:
                        entry_value = entry_var.get()
                        if entry_value.strip() == "":
                            self.log(f"Missing OVP input for Cathode {['A', 'B', 'C'][cathode_idx]}", LogLevel.ERROR)
                            msgbox.showerror("Error", "Please enter a value for overvoltage limit.")
                            return
                        new_value = float(entry_value)

                        # Validate range before updating any values
                        if new_value < 0.02 or new_value > 84:
                            self.log(
                                f"OVP input out of range for Cathode {['A', 'B', 'C'][cathode_idx]}: {new_value:.2f}V",
                                LogLevel.WARNING,
                            )
                            msgbox.showerror("Error", "OVP must be a value greater than 0.02 V and less than or equal to 84 V")
                            return

                        # Only commit UI values after hardware readback confirmation.
                        set_ok = self.set_overvoltage_limit(cathode_idx, requested_value=new_value)
                        update_func()
                        if set_ok:
                            entry_var.set("")  # Clear only after successful confirmation
                        else:
                            msgbox.showwarning("OVP Not Confirmed", "OVP could not be confirmed from power supply readback.")

                    except ValueError:
                        self.log(f"Invalid OVP input for Cathode {['A', 'B', 'C'][cathode_idx]}", LogLevel.ERROR)
                        msgbox.showerror("Error", "Please enter a valid number for overvoltage limit.")
                        return
                return set_and_update_ovl

            set_and_update_ovl = create_ovl_set_function(i, update_ovl_live_box, temp_overvoltage_var)
            set_overvoltage_button.configure(command=set_and_update_ovl)

            # Over Current Limit controls in a frame, with live value next to entry
            ocl_control_frame = ttk.Frame(config_tab)
            ocl_control_frame.grid(row=4, column=0, columnspan=3, sticky='w', pady=(2, 2))

            # Frame to hold label and live value side-by-side
            ocl_label_frame = ttk.Frame(ocl_control_frame)
            ocl_label_frame.grid(row=0, column=1, sticky='w')
            ocl_label = ttk.Label(ocl_label_frame, text='Overcurrent Limit (A):', style='RightAlign.TLabel')
            ocl_label.pack(side='left')
            # Live value display (styled box)
            ocl_display_frame = tk.Frame(ocl_label_frame, bd=2, relief='groove', padx=2, pady=1)
            ocl_display_frame.configure(bg='#d9d9d9')
            ocl_display_frame.pack(side='left', padx=(34, 0))
            ocl_readback = self.ocl_readback_vars[i]
            ocl_live_label = ttk.Label(ocl_display_frame, textvariable=ocl_readback, style='Bold.TLabel', width=4, anchor='e')
            ocl_live_label.pack(side='left')
            ocl_unit_label = ttk.Label(ocl_display_frame, text=" A", style="Bold.TLabel")
            ocl_unit_label.pack(side='left')

            # temp_overcurrent_var = self.overcurrent_limit_vars[i]
            temp_overcurrent_var = tk.StringVar(value="")
            ocl_entry = ttk.Entry(ocl_control_frame, textvariable=temp_overcurrent_var, width=7)
            ocl_entry.grid(row=0, column=2, sticky='w', padx=(7, 2))
            set_ocl_button = ttk.Button(ocl_control_frame, text="Set", width=4)
            set_ocl_button.grid(row=0, column=3, sticky='w', padx=(1, 2))
            ToolTip(ocl_label, "Over Current Limit must be a value greater than 0.1 A and less than or equal to 10 A")

            def create_ocl_update_function(cathode_idx, readback_var):
                def update_ocl_live_box():
                    val = self.ocl_live_values[cathode_idx]
                    if val is not None:
                        readback_var.set(f"{val:.2f}")
                    else:
                        readback_var.set("N/A")
                return update_ocl_live_box
            update_ocl_live_box = create_ocl_update_function(i, ocl_readback)

            # Keep readback unknown until hardware confirms a value.
            self.ocl_live_values[i] = None
            update_ocl_live_box()

            # Create set function with proper closure
            def create_ocl_set_function(cathode_idx, update_func, entry_var):
                def set_and_update_ocl():
                    # First, validate the input value before updating anything
                    try:
                        entry_value = entry_var.get()
                        if entry_value.strip() == "":
                            self.log(f"Missing OCP input for Cathode {['A', 'B', 'C'][cathode_idx]}", LogLevel.ERROR)
                            msgbox.showerror("Error", "Please enter a value for overcurrent limit.")
                            return
                        new_value = float(entry_value)

                        # Validate range before updating any values
                        if new_value < 0.1 or new_value > 10:
                            self.log(
                                f"OCP input out of range for Cathode {['A', 'B', 'C'][cathode_idx]}: {new_value:.2f}A",
                                LogLevel.WARNING,
                            )
                            msgbox.showerror("Error", "Over Current Limit must be a value greater than 0.1 A and less than or equal to 10 A")
                            return

                        # Only commit UI values after hardware readback confirmation.
                        set_ok = self.set_overcurrent_limit(cathode_idx, requested_value=new_value)
                        update_func()
                        if set_ok:
                            entry_var.set("")  # Clear only after successful confirmation
                        else:
                            msgbox.showwarning("OCP Not Confirmed", "OCP could not be confirmed from power supply readback.")

                    except ValueError:
                        self.log(f"Invalid OCP input for Cathode {['A', 'B', 'C'][cathode_idx]}", LogLevel.ERROR)
                        msgbox.showerror("Error", "Please enter a valid number for overcurrent limit.")
                        return
                return set_and_update_ocl

            set_and_update_ocl = create_ocl_set_function(i, update_ocl_live_box, temp_overcurrent_var)
            set_ocl_button.configure(command=set_and_update_ocl)

            # Current slew rate controls in a frame, with live value next to label
            csr_control_frame = ttk.Frame(config_tab)
            csr_control_frame.grid(row=5, column=0, columnspan=3, sticky='w', pady=(2, 2))

            csr_label_frame = ttk.Frame(csr_control_frame)
            csr_label_frame.grid(row=0, column=0, sticky='w')
            current_slew_rate_label = ttk.Label(csr_label_frame, text='Current Slew Rate (A/s):', style='RightAlign.TLabel')
            current_slew_rate_label.pack(side='left')
            csr_display_frame = tk.Frame(csr_label_frame, bd=2, relief='groove', padx=2, pady=1)
            csr_display_frame.configure(bg='#d9d9d9')
            csr_display_frame.pack(side='left', padx=(8, 0))
            # Bind live value to the actual curr_slew_rate
            csr_var = tk.StringVar(value=f"{self.curr_slew_rate[i]:.2f}")
            csr_live_label = ttk.Label(csr_display_frame, textvariable=csr_var, style='Bold.TLabel', width=4, anchor='e')
            csr_live_label.pack(side='left')
            csr_unit_label = ttk.Label(csr_display_frame, text=" A/s", style="Bold.TLabel")
            csr_unit_label.pack(side='left')

            current_slew_rate_var = tk.StringVar(value="")

            def current_slew_command(idx=i, entry_var=current_slew_rate_var):
                # Called when spinbox arrows are clicked
                current_val = entry_var.get()
                if current_val == "" or current_val.strip() == "":
                    # If empty, populate with current slew rate + increment
                    new_val = self.curr_slew_rate[idx] + 0.01
                    entry_var.set(f"{new_val:.2f}")
                else:
                    try:
                        val = float(current_val)
                        if val <= 0:
                            entry_var.set("0.01")
                    except ValueError:
                        entry_var.set(f"{self.curr_slew_rate[idx]:.2f}")

            current_slew_rate_spinbox = ttk.Spinbox(csr_control_frame, textvariable=current_slew_rate_var,
                                                  width=5, from_=0.01, to=10.0, increment=0.01,
                                                  format="%.2f", command=current_slew_command)
            current_slew_rate_spinbox.grid(row=0, column=1, sticky='w', padx=(5, 2))

            set_current_slew_rate_button = ttk.Button(csr_control_frame, text="Set", width=4, command=lambda i=i, var=current_slew_rate_var: self.set_slew_rate(i, var, control_mode='current'))
            set_current_slew_rate_button.grid(row=0, column=2, sticky='w', padx=(2, 2))
            ToolTip(current_slew_rate_label, "Rate of change for current output")

            # Keep entry and live label in sync with value
            def sync_csr(*args, idx=i, var=csr_var, entry_var=current_slew_rate_var):
                val = self.curr_slew_rate[idx]
                var.set(f"{val:.2f}")
                # Don't update entry_var during sync - only update live display
            sync_csr()

            if not hasattr(self, '_sync_csr_funcs'):
                self._sync_csr_funcs = []
            self._sync_csr_funcs.append(sync_csr)

            # Voltage slew rate controls in a frame, with live value next to label
            vsr_control_frame = ttk.Frame(config_tab)
            vsr_control_frame.grid(row=6, column=0, columnspan=3, sticky='w', pady=(2, 2))

            vsr_label_frame = ttk.Frame(vsr_control_frame)
            vsr_label_frame.grid(row=0, column=0, sticky='w')
            slew_rate_label = ttk.Label(vsr_label_frame, text='Voltage Slew Rate (V/s):', style='RightAlign.TLabel')
            slew_rate_label.pack(side='left')
            vsr_display_frame = tk.Frame(vsr_label_frame, bd=2, relief='groove', padx=2, pady=1)
            vsr_display_frame.configure(bg='#d9d9d9')
            vsr_display_frame.pack(side='left', padx=(8, 0))
            # Bind live value to the actual vlt_slew_rate
            vsr_var = tk.StringVar(value=f"{self.vlt_slew_rate[i]:.2f}")
            vsr_live_label = ttk.Label(vsr_display_frame, textvariable=vsr_var, style='Bold.TLabel', width=4, anchor='e')
            vsr_live_label.pack(side='left')
            vsr_unit_label = ttk.Label(vsr_display_frame, text=" V/s", style="Bold.TLabel")
            vsr_unit_label.pack(side='left')

            slew_rate_var = tk.StringVar(value="")

            def voltage_slew_command(idx=i, entry_var=slew_rate_var):
                # Called when spinbox arrows are clicked
                current_val = entry_var.get()
                if current_val == "" or current_val.strip() == "":
                    # If empty, populate with current slew rate + increment
                    new_val = self.vlt_slew_rate[idx] + 0.02
                    entry_var.set(f"{new_val:.2f}")
                else:
                    try:
                        val = float(current_val)
                        if val <= 0:
                            entry_var.set("0.02")
                    except ValueError:
                        entry_var.set(f"{self.vlt_slew_rate[idx]:.2f}")

            slew_rate_spinbox = ttk.Spinbox(vsr_control_frame, textvariable=slew_rate_var,
                                          width=5, from_=0.02, to=0.06, increment=0.02,
                                          format="%.2f", command=voltage_slew_command)
            slew_rate_spinbox.grid(row=0, column=1, sticky='w', padx=(5, 2))

            set_slew_rate_button = ttk.Button(vsr_control_frame, text="Set", width=4, command=lambda i=i, var=slew_rate_var: self.set_slew_rate(i, var, control_mode='voltage'))
            set_slew_rate_button.grid(row=0, column=2, sticky='w', padx=(2, 2))
            ToolTip(slew_rate_label, "Rate of change for voltage output")

            # Keep entry and live label in sync with value
            def sync_vsr(*args, idx=i, var=vsr_var, entry_var=slew_rate_var):
                val = self.vlt_slew_rate[idx]
                var.set(f"{val:.2f}")
                # Don't update entry_var during sync - only update live display
            sync_vsr()

            if not hasattr(self, '_sync_vsr_funcs'):
                self._sync_vsr_funcs = []
            self._sync_vsr_funcs.append(sync_vsr)
            # Add label for Temperature Controller
            ttk.Label(config_tab, text="\nTemperature Controller", style='Bold.TLabel').grid(row=9, column=0, columnspan=3, sticky="ew")

            # Overtemperature status display in its own frame
            overtemp_status_frame = ttk.Frame(config_tab)
            overtemp_status_frame.grid(row=10, column=0, columnspan=3, sticky='w', pady=(2, 2))
            overtemp_status_label = ttk.Label(overtemp_status_frame, text='Overtemp Status:', style='LeftAlign.TLabel')
            overtemp_status_label.pack(side='left')
            ttk.Label(overtemp_status_frame, textvariable=self.overtemp_status_vars[i], style='Bold.TLabel').pack(side='left', padx=(8, 0))

        # Ensure the grid layout of config_tab accommodates the new buttons
        config_tab.columnconfigure(0, weight=1)
        config_tab.columnconfigure(1, weight=1)

        self.init_time = datetime.datetime.now()

    def _create_comms_indicator(self, parent, label_text, row, column):
        row_frame = ttk.Frame(parent)
        row_frame.grid(row=row, column=column, sticky='w', padx=(0, 20))

        ttk.Label(row_frame, text=label_text, font=("Segoe UI", 8)).pack(side=tk.LEFT)
        canvas = tk.Canvas(row_frame, width=15, height=15, highlightthickness=0)
        canvas.pack(side=tk.LEFT, padx=(4, 0))
        oval = canvas.create_oval(2, 2, 13, 13, fill="red", outline="black")
        return canvas, oval

    def _update_cathode_comms_indicators(self, index):
        if not 0 <= index < 3:
            return

        with self.power_supply_config_lock:
            power_supply_ready = self.power_supply_configured[index]
        temperature_ready = self.temperature_valid_connections[index]

        if index < len(self.power_supply_comms_indicators):
            canvas, oval = self.power_supply_comms_indicators[index]
            canvas.itemconfig(oval, fill="green" if power_supply_ready else "red")

        if index < len(self.temperature_comms_indicators):
            canvas, oval = self.temperature_comms_indicators[index]
            canvas.itemconfig(oval, fill="green" if temperature_ready else "red")

    def refresh_predictions(self, cathode_idx):
        """
        Refresh predicted values for the specified cathode index after LUT change.

        Recomputes from the currently requested heater setpoint(s) when available,
        so switching datasets does not overwrite predictions with an unrelated LUT row.
        """
        lut_df = self.lookup_table_setting[cathode_idx]
        if lut_df is None or lut_df.empty:
            self.clear_prediction_variables(cathode_idx)
            return

        has_current_setpoint = (
            self.current_set[cathode_idx] and self.user_set_currents[cathode_idx] is not None
        )
        has_voltage_setpoint = (
            self.voltage_set[cathode_idx] and self.user_set_voltages[cathode_idx] is not None
        )

        # Recompute predictions from active setpoints so dataset switch reflects current request.
        if has_current_setpoint:
            self.update_predictions_from_current(cathode_idx, self.user_set_currents[cathode_idx])
        elif has_voltage_setpoint:
            self.update_predictions_from_voltage(cathode_idx, self.user_set_voltages[cathode_idx])
        else:
            self.clear_prediction_variables(cathode_idx)

    def set_logging_suppression(self, disable_when_ccs_power_off, ccs_power_on_provider=None):
        self.disable_logging_when_ccs_power_off = bool(disable_when_ccs_power_off)
        self.ccs_power_on_provider = ccs_power_on_provider if callable(ccs_power_on_provider) else None
        self._apply_ccs_logging_suppression_to_drivers()

    def _apply_ccs_logging_suppression_to_drivers(self):
        for power_supply in getattr(self, "power_supplies", []):
            if power_supply is not None:
                power_supply.disable_logging_when_ccs_power_off = self.disable_logging_when_ccs_power_off
                power_supply.ccs_power_on_provider = self.ccs_power_on_provider
        controller = getattr(self, "temperature_controller", None)
        if controller is not None:
            controller.disable_logging_when_ccs_power_off = self.disable_logging_when_ccs_power_off
            controller.ccs_power_on_provider = self.ccs_power_on_provider

    def _logging_suppressed(self):
        if not self.disable_logging_when_ccs_power_off or self.ccs_power_on_provider is None:
            return False
        try:
            return not bool(self.ccs_power_on_provider())
        except Exception:
            return False

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

        # Keep the poller thread alive, but make it ignore the supply list while we replace it.
        self.power_supply_reconfiguring.set()
        try:
            self._disconnect_existing_connections()
            self._update_com_ports_dictionary(new_com_ports)

            ps_update_success = self._update_power_supply_ports(new_com_ports)
            if not ps_update_success:
                self.log("Some power supply port updates failed", LogLevel.WARNING)
            
            tc_update_success = self._update_temperature_controller_port(new_com_ports)
            if not tc_update_success:
                self.log("Temperature controller port update failed", LogLevel.WARNING)

            update_success = ps_update_success and tc_update_success
            if update_success:
                self.initialize_power_supplies()
                if self.power_supplies_initialized:
                    self.log("Power supply handles reinitialized; configuration pending valid readback", LogLevel.INFO)
                else:
                    self.log("Power supplies reinitialization failed", LogLevel.ERROR)
                    update_success = False
            
            return update_success
            
        except Exception as e:
            self.log(f"Unexpected error during COM port update: {str(e)}", LogLevel.ERROR)
            return False
        finally:
            # Always let the poller resume, even after a partial or failed reconfiguration.
            self.power_supply_reconfiguring.clear()
            if not self.start_power_supply_polling():
                self.log("9104 polling is not running after COM port update", LogLevel.WARNING)
            
    def _disconnect_existing_connections(self):
        # Disconnect power supplies
        old_power_supplies = list(self.power_supplies)
        # Detach old drivers before close so the poller cannot pick them up again.
        self.power_supplies = [None, None, None]
        self.power_supplies_initialized = False
        self._reset_power_supply_runtime_state()
        for idx in range(3):
            self._set_power_supply_command_ready(idx, False)

        for idx, ps in enumerate(old_power_supplies):
            if ps is not None:
                try:
                    if hasattr(ps, 'close'):
                        ps.close(ramp_join_timeout=2.0)
                    elif hasattr(ps, 'disconnect'):
                        ps.disconnect()
                    self.log(f"Disconnected power supply {idx + 1}", LogLevel.DEBUG)
                except Exception as e:
                    self.log(f"Error disconnecting power supply {idx + 1}: {str(e)}", LogLevel.WARNING)
        
        # Disconnect temperature controller
        if self.temperature_controller:
            try:
                closed = self.temperature_controller.stop_reading()
                self.temp_controllers_connected = False
                self.temperature_valid_connections = [False, False, False]
                if closed:
                    self.temperature_controller = None
                    self.log("Disconnected temperature controller", LogLevel.DEBUG)
                else:
                    self.log(
                        "Temperature controller did not close cleanly; keeping old handle until cleanup succeeds",
                        LogLevel.WARNING,
                    )
            except Exception as e:
                self.log(f"Error disconnecting temperature controller: {str(e)}", LogLevel.WARNING)

    def _update_power_supply_ports(self, new_com_ports):
        """
        Verify requested power supply COM ports before reinitialization.
        
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
                    
                self.log(f"Verified {cathode} port {new_port}", LogLevel.INFO)
                
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

    def _snapshot_desired_power_supply_limits(self):
        """Copy Tk-backed limit settings into plain values for worker-thread use."""
        limits = []
        for idx in range(3):
            try:
                ovp = float(self.overvoltage_limit_vars[idx].get())
            except Exception:
                ovp = None
            try:
                ocp = float(self.overcurrent_limit_vars[idx].get())
            except Exception:
                ocp = None
            limits.append({"ovp": ovp, "ocp": ocp})

        with self.power_supply_config_lock:
            self.power_supply_desired_limits = limits

    def _reset_power_supply_config_state(self, index=None):
        """Mark one or all 9104 supplies as needing preset/OVP/OCP confirmation."""
        indexes = range(3) if index is None else [index]
        with self.power_supply_config_lock:
            for idx in indexes:
                if not 0 <= idx < 3:
                    continue
                self.power_supply_configured[idx] = False
                self.power_supply_config_last_attempt[idx] = 0.0
                self.power_supply_config_confirmed_limits[idx] = {"ovp": None, "ocp": None}

    def _set_power_supply_command_ready(self, index, ready):
        """Gate operator commands on confirmed readback plus completed 9104 configuration."""
        if not 0 <= index < 3:
            return

        self.power_supply_status[index] = bool(ready)
        state = 'normal' if ready else 'disabled'
        if index < len(self.toggle_buttons):
            self.toggle_buttons[index]['state'] = state
        if index < len(self.log_power_settings_buttons):
            self.log_power_settings_buttons[index]['state'] = state
        self._refresh_heater_setpoint_controls(index)
        self._update_cathode_comms_indicators(index)

    def initialize_power_supplies(self):
        # Build a complete replacement list locally, then publish it in one assignment.
        # Opening a serial port is not enough to trust a 9104; configuration is deferred
        # until the polling thread gets a valid voltage/current readback from the device.
        new_power_supplies = [None, None, None]
        self._reset_power_supply_connection_tracking()
        self._snapshot_desired_power_supply_limits()
        self._reset_power_supply_config_state()

        cathode_ports = {
            'CathodeA PS': self.com_ports.get('CathodeA PS'),
            'CathodeB PS': self.com_ports.get('CathodeB PS'),
            'CathodeC PS': self.com_ports.get('CathodeC PS')
        }

        for idx, (cathode, port) in enumerate(cathode_ports.items()):
            if port:
                ps = None
                try:
                    ps = PowerSupply9104(
                        port=port,
                        logger=self.logger,
                        disable_logging_when_ccs_power_off=self.disable_logging_when_ccs_power_off,
                        ccs_power_on_provider=self.ccs_power_on_provider,
                        supply_name=f"Cathode {chr(65 + idx)} power supply",
                    )
                    new_power_supplies[idx] = ps
                    self.log(f"Created {cathode} power supply handle on port {port}; configuration pending valid readback.", LogLevel.INFO)
                except Exception as e:
                    if ps is not None and hasattr(ps, 'close'):
                        try:
                            ps.close(ramp_join_timeout=2.0)
                        except Exception:
                            pass
                    self.log(f"Failed to initialize {cathode} on port {port}: {str(e)}", LogLevel.ERROR)
            else:
                self.log(f"No COM port specified for {cathode}", LogLevel.ERROR)

        self.power_supplies = new_power_supplies

        # Controls remain disabled until the poller confirms preset/OVP/OCP.
        for idx, ps in enumerate(self.power_supplies):
            self._set_power_supply_command_ready(idx, False)
            if idx >= len(self.toggle_buttons):
                self.log(f"Toggle button {idx+1} has not been initialized yet.", LogLevel.VERBOSE)
            elif ps is None:
                self.log(f"Power supply {idx+1} not initialized. Button disabled.", LogLevel.DEBUG)

        self.power_supplies_initialized = any(ps is not None for ps in self.power_supplies)
        if not self.power_supplies_initialized:
            self.log("No power supply handles were created.", LogLevel.ERROR)
        
        self.update_log_power_settings_button_states()

    def retry_connection(self, index):
        """Single lightweight reconnect attempt — no retries, no full reconfiguration."""
        try:
            port = self.com_ports[f'Cathode{chr(65+index)} PS']
            new_ps = PowerSupply9104(
                port=port,
                logger=self.logger,
                disable_logging_when_ccs_power_off=self.disable_logging_when_ccs_power_off,
                ccs_power_on_provider=self.ccs_power_on_provider,
                supply_name=f"Cathode {chr(65 + index)} power supply",
            )
            if not new_ps.is_connected():
                return False
            self.power_supplies[index] = new_ps
            self.power_supplies_initialized = any(ps is not None for ps in self.power_supplies)
            # The reconnect succeeded at the handle level; command controls wait for the poller
            # to verify readback and re-apply preset/OVP/OCP.
            self._reset_power_supply_config_state(index)
            self._set_power_supply_command_ready(index, False)

            self.log(f"Reconnected to power supply on port {port}; configuration pending valid readback.", LogLevel.INFO)
            self.update_log_power_settings_button_states()
            return True
        except Exception as e:
            self.log(f"Reconnect attempt failed for cathode {chr(65+index)}: {str(e)}", LogLevel.ERROR)
            return False
    
    def set_slew_rate(self, index, var, control_mode="current"):
        """
        Set the voltage slew rate for a 9104 power supply.

        Args:
            index (int): Index of the power supply (0-2)
            var (tk.StringVar): Variable containing the new slew rate in V/s

        Raises:
            ValueError: If slew rate is invalid or negative
        """
        try:
            # Check if entry box is empty
            entry_value = var.get().strip()
            if not entry_value:
                self.log(f"Please enter a value for slew rate for Cathode {['A', 'B', 'C'][index]}", LogLevel.WARNING)
                msgbox.showwarning("Empty Input", "Please enter a value for the slew rate.")
                return

            new_slew_rate = float(entry_value)
            if new_slew_rate <= 0:
                raise ValueError("Slew rate must be positive.")
            if control_mode == "current":
                self.curr_slew_rate[index] = round(new_slew_rate, 2)
                self.log(f"Set slew rate for Cathode {['A', 'B', 'C'][index]} to {self.curr_slew_rate[index]:.2f} A/s", LogLevel.INFO)
                # Update live label and clear entry box
                if hasattr(self, '_sync_csr_funcs') and self._sync_csr_funcs[index]:
                    self._sync_csr_funcs[index]()
                var.set("")  # Clear the entry box
            else:  # control_mode == "voltage"
                self.vlt_slew_rate[index] = round(new_slew_rate, 2)
                self.log(f"Set slew rate for Cathode {['A', 'B', 'C'][index]} to {self.vlt_slew_rate[index]:.2f} V/s", LogLevel.INFO)
                # Update live label and clear entry box
                if hasattr(self, '_sync_vsr_funcs') and self._sync_vsr_funcs[index]:
                    self._sync_vsr_funcs[index]()
                var.set("")  # Clear the entry box
            self.parent.update()
        except ValueError as e:
            self.log(f"Invalid input for slew rate for Cathode {['A', 'B', 'C'][index]}: {str(e)}", LogLevel.ERROR)
            msgbox.showerror("Invalid Input", f"Invalid input for slew rate: {str(e)}")

    def set_ramp_mode(self, index: int, mode: str):
        """
        Set the ramping mode for the specified power supply.
        
        Args:
            index (int): Index of the cathode (0-2)
            mode (str): string containing ramp mode, either "ramp_current", "ramp_voltage", or "immediate"
        """
        if mode == "ramp_current":
            self.ramp_status[index] = True
            self.ramp_control_mode[index] = "current"
            mode_str = "gradual current."
        elif mode == "ramp_voltage":
            self.ramp_status[index] = True
            self.ramp_control_mode[index] = "voltage"
            mode_str = "gradual voltage."
        else: # immediate
            self.ramp_status[index] = False
            mode_str = "immediate set."

        self._refresh_heater_setpoint_controls(index)
        self.log(f"Set voltage mode for Cathode {['A', 'B', 'C'][index]} to {mode_str}", LogLevel.INFO)

    def set_overvoltage_limit(self, index, requested_value=None):
        if not self.power_supply_status[index]:
            self.log(f"Power supply {index + 1} is not initialized. Cannot set OVP.", LogLevel.ERROR)
            msgbox.showerror("Error", f"Power supply {index + 1} is not initialized. Cannot set OVP.")
            return

        try:
            ovp_value = float(requested_value) if requested_value is not None else float(self.overvoltage_limit_vars[index].get())

            # Backend safety validation (do not rely only on GUI-bound checks)
            if ovp_value < 0.02 or ovp_value > 84:
                raise ValueError("OVP must be a value greater than 0.02 V and less than or equal to 84 V")

            self.log(f"Setting OVP for Cathode {['A', 'B', 'C'][index]} to: {ovp_value:.2f}", LogLevel.DEBUG)
            ovp_set = Decimal(str(ovp_value)).quantize(Decimal('0.01'))  # Round to 2 decimal places
            ovp_set_response = self.power_supplies[index].set_over_voltage_protection(ovp_set)
            if not ovp_set_response:
                self.log(f"Failed to set OVP for Cathode {['A', 'B', 'C'][index]}. Response: {ovp_set_response}", LogLevel.ERROR)
                return

            # Verify the set value
            ovp_get_response = self.power_supplies[index].get_over_voltage_protection()
            if ovp_get_response is None:
                self.ovl_live_values[index] = None
                self.ovl_readback_vars[index].set("N/A")
                self.log("OVP readback is None--possible comm issue", LogLevel.WARNING)
            else:
                self.ovl_live_values[index] = float(ovp_get_response)
                self.overvoltage_limit_vars[index].set(float(ovp_get_response))
                self.ovl_readback_vars[index].set(f"{float(ovp_get_response):.2f}")
                if abs(ovp_get_response - ovp_value) > 0.01:
                    self.log(
                        f"OVP mismatch for Cathode {['A','B','C'][index]}. "
                        f"Set: {ovp_value:.2f}, Got: {ovp_get_response:.2f}",
                        LogLevel.WARNING
                    )
                else:
                    self.log(
                        f"OVP successfully set and confirmed for Cathode {['A','B','C'][index]}: "
                        f"{ovp_value:.2f} V", LogLevel.INFO
                    )
                    with self.power_supply_config_lock:
                        self.power_supply_desired_limits[index]["ovp"] = float(ovp_get_response)
                        self.power_supply_config_confirmed_limits[index]["ovp"] = float(ovp_get_response)
                    return True

        except ValueError as e:
            self.log(f"Invalid input for OVP limit for Cathode {['A', 'B', 'C'][index]}: {str(e)}", LogLevel.ERROR)
            msgbox.showerror("Error", f"Invalid input for OVP limit: {str(e)}")
            return False

        except Exception as e:
            self.log(f"Unexpected error setting OVP for Cathode {['A', 'B', 'C'][index]}: {str(e)}", LogLevel.ERROR)
            msgbox.showerror("Error", f"Unexpected error setting OVP: {str(e)}")
            return False

        return False

    def set_overcurrent_limit(self, index, requested_value=None):
        if not self.power_supply_status[index]:
            self.log(f"Power supply {index + 1} is not initialized. Cannot set OCP.", LogLevel.ERROR)
            msgbox.showerror("Error", f"Power supply {index + 1} is not initialized. Cannot set OCP.")
            return

        try:
            raw_value = float(requested_value) if requested_value is not None else float(self.overcurrent_limit_vars[index].get())

            # Backend safety validation (do not rely only on GUI-bound checks)
            if raw_value < 0.1 or raw_value > 10:
                raise ValueError("Over Current Limit must be a value greater than 0.1 A and less than or equal to 10 A")

            ocp_set   = Decimal(str(raw_value)).quantize(Decimal('0.01'))  # Round to 2 decimal places
            
            self.log(f"Setting OCP for Cathode {['A', 'B', 'C'][index]} to: {raw_value:.2f}", LogLevel.DEBUG)
            ocp_set_response = self.power_supplies[index].set_over_current_protection(ocp_set)
            if not ocp_set_response:
                self.log(f"Failed to set OCP for Cathode {['A', 'B', 'C'][index]}. Response: {ocp_set_response}", LogLevel.ERROR)
                return

            # Verify the set value
            ocp_get_response = self.power_supplies[index].get_over_current_protection()
            if ocp_get_response is not None:
                self.ocl_live_values[index] = float(ocp_get_response)
                self.overcurrent_limit_vars[index].set(float(ocp_get_response))
                self.ocl_readback_vars[index].set(f"{float(ocp_get_response):.2f}")
            else:
                self.ocl_live_values[index] = None
                self.ocl_readback_vars[index].set("N/A")
            if ocp_get_response is None or abs(ocp_get_response - raw_value) > 0.01:
                self.log(f"OCP mismatch for Cathode {['A', 'B', 'C'][index]}. Set: {raw_value:.2f}, Got: {ocp_get_response}", LogLevel.WARNING)
            else:
                self.log(f"OCP successfully set and confirmed for Cathode {['A', 'B', 'C'][index]}: {raw_value:.2f}A", LogLevel.INFO)
                with self.power_supply_config_lock:
                    self.power_supply_desired_limits[index]["ocp"] = float(ocp_get_response)
                    self.power_supply_config_confirmed_limits[index]["ocp"] = float(ocp_get_response)
                return True  # Return True to indicate success

        except ValueError as e:
            self.log(f"Invalid input for OCP limit for Cathode {['A', 'B', 'C'][index]}: {str(e)}", LogLevel.ERROR)
            msgbox.showerror("Error", f"Invalid input for OCP limit: {str(e)}")
            return False  # Return False to indicate failure

        except Exception as e:
            self.log(f"Unexpected error setting OCP for Cathode {['A', 'B', 'C'][index]}: {str(e)}", LogLevel.ERROR)
            msgbox.showerror("Error", f"Unexpected error setting OCP: {str(e)}")
            return False

        return False  # Return False if we get here without success

    def update_log_power_settings_button_states(self):
        for i, power_supply in enumerate(self.power_supplies):
            if i < len(self.log_power_settings_buttons):
                ready = bool(power_supply and i < len(self.power_supply_status) and self.power_supply_status[i])
                self.log_power_settings_buttons[i]['state'] = 'normal' if ready else 'disabled'

    def log_power_and_check_settings(self, index):
        if not self.power_supply_status[index]:
            self.log(f"Power supply {index} not initialized.", LogLevel.ERROR)
            return

        voltage, current = self.power_supplies[index].get_settings(3)  # Get settings for preset 3 (normal mode)
        self.log(f"Raw settings response for Cathode {['A', 'B', 'C'][index]}", LogLevel.DEBUG)
        if voltage is None or current is None:
            self.log(f"Failed to retrieve settings for Cathode {['A', 'B', 'C'][index]}", LogLevel.ERROR)
            return

        try:
            expected_voltage = self.user_set_voltages[index]
            if expected_voltage is None:
                self.log(f"Cathode {['A', 'B', 'C'][index]} settings - Voltage{voltage:.2f}V, Current: {current:.2f}A", LogLevel.INFO)
            elif abs(voltage - expected_voltage) > 0.1:
                self.log(f"Voltage mismatch for Cathode {['A', 'B', 'C'][index]}: Set: {expected_voltage:.2f}V, Actual: {voltage:.2f}V", LogLevel.WARNING)
            else:
                self.log(f"Cathode {['A', 'B', 'C'][index]} voltage matches set value. Voltage: {voltage:.2f}V, Current: {current:.2f}A", LogLevel.INFO)

        except Exception as e:
            self.log(f"Error checking settings for Cathode {['A', 'B', 'C'][index]}: {str(e)}", LogLevel.ERROR)

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
                closed = self.temperature_controller.stop_reading()
                if not closed:
                    self.temp_controllers_connected = False
                    self.temperature_valid_connections = [False, False, False]
                    self.log(
                        "Existing temperature controller did not close; "
                        "skipping reinitialization to avoid reopening an in-use COM port.",
                        LogLevel.WARNING,
                    )
                    return False
                self.temperature_controller = None
            except Exception as e:
                self.log(f"Error cleaning up existing controller: {str(e)}", LogLevel.ERROR)
                self.temp_controllers_connected = False
                self.temperature_valid_connections = [False, False, False]
                return False
                
        try:
            tc = E5CNModbus(
                port=port,
                logger=self.logger,
                disable_logging_when_ccs_power_off=self.disable_logging_when_ccs_power_off,
                ccs_power_on_provider=self.ccs_power_on_provider,
            )
            if tc.start_reading_temperatures():
                self.temperature_controller = tc
                self.temp_controllers_connected = True
                self.temperature_valid_connections = [False, False, False]
                self.log(f"Connected to all temperature controllers via Modbus on {port}", LogLevel.INFO)
                return True
            else:
                self.log(f"Failed to start temperature controllers at {port}", LogLevel.ERROR)
                self.temp_controllers_connected = False
                self.temperature_valid_connections = [False, False, False]
                return False
        except Exception as e:
            self.log(f"Exception while initializing temperature controllers at {port}: {str(e)}", LogLevel.ERROR)
            self.temp_controllers_connected = False
            self.temperature_valid_connections = [False, False, False]
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
        if not self.TEMPERATURE_GRAPHS_ENABLED or not self.temperature_data[index]:
            return

        state = error_type if error_type else 'normal'
        if self.plot_color_states[index] == state:
            return
        self.plot_color_states[index] = state

        ax = self.temperature_data[index][0].axes
        line = self.temperature_data[index][0]

        color = self.ERROR_COLORS.get(state)
        
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
                if isinstance(temperature, (int, float)):
                    temperature = float(temperature)
                    if temperature > E5CNModbus.MAX_VALID_TEMPERATURE_C:
                        self.temperature_valid_connections[index] = False
                        self.clamp_temperature_vars[index].set("ERR")
                        self.set_plot_color(index, 'ERROR')
                        self._log_poll_error_rate_limited(
                            ("invalid_temperature", index),
                            f"Invalid temperature for cathode {index+1}: {temperature:.2f} C "
                            f"exceeds hard maximum {E5CNModbus.MAX_VALID_TEMPERATURE_C:.2f} C",
                            LogLevel.ERROR
                        )
                        return None

                    self.clamp_temperature_vars[index].set(f"{temperature:.1f} C")

                    # Check for overtemperature condition
                    if temperature > self.overtemp_limit_vars[index].get():
                        self.set_plot_color(index, 'overtemp') # set plot to red for overtemp
                    else:
                        self.set_plot_color(index, None) # set plot to blue for normal

                    self._log_valid_temperature_connection(index, temperature)
                    return temperature
                elif isinstance(temperature, str):
                    self.temperature_valid_connections[index] = False
                    self.clamp_temperature_vars[index].set("ERR")
                    self.set_plot_color(index, 'ERROR')
                    self._log_poll_error_rate_limited(
                        ("temperature_error", index),
                        f"Reading temperature for cathode {index+1} returned an error: {temperature}",
                        LogLevel.ERROR,
                    )
                    return None
                else:
                    self.temperature_valid_connections[index] = False
                    self._log_poll_error_rate_limited(
                        ("temperature_no_data", index),
                        f"No temperature data for cathode {index+1}",
                        LogLevel.WARNING,
                    )
            except Exception as e:
                self._log_poll_error_rate_limited(
                    ("temperature_exception", index),
                    f"Error reading temperature for cathode {index+1}: {str(e)}",
                    LogLevel.ERROR,
                )
                self.set_plot_color(index, 'ERROR')  # Set plot to orange for no data
                self.temperature_valid_connections[index] = False
        else:
            if current_time - self.last_no_conn_log_time[index] >= self.log_interval:
                self.log(f"No connection to CCS temperature controller {index+1}", LogLevel.DEBUG)
                self.last_no_conn_log_time[index] = current_time
            else:
                self.log(f"No connection to CCS temperature controller {index+1}", LogLevel.VERBOSE)
            self.set_plot_color(index, 'DISCONNECTED')
            self.temperature_valid_connections[index] = False


        # Set temperature to zero as default
        self.clamp_temperature_vars[index].set("-- C")
        return None

    def _log_valid_temperature_connection(self, index, temperature):
        if not 0 <= index < len(self.temperature_valid_connections):
            return
        if self.temperature_valid_connections[index]:
            return
        self.temperature_valid_connections[index] = True
        cathode = ['A', 'B', 'C'][index]
        port = self.com_ports.get('TempControllers', 'unknown port')
        self.log(
            f"CCS temperature controller valid connection established for Cathode {cathode} "
            f"on {port}: {temperature:.2f} C readback.",
            LogLevel.INFO,
        )

    def _log_poll_error_rate_limited(self, key, message, level=LogLevel.ERROR):
        now = time.monotonic()
        with self.poll_error_log_lock:
            last_logged = self.poll_error_last_log_times.get(key)
            if last_logged is not None and now - last_logged < self.POLL_ERROR_LOG_INTERVAL_SECONDS:
                log_level = LogLevel.VERBOSE
            else:
                self.poll_error_last_log_times[key] = now
                log_level = level
        self.log(message, log_level)

    def _publish_cathode_power_readback(self, index, current, voltage):
        """Publish cathode heater readbacks, including None when the read is invalid."""
        if self.logger and hasattr(self.logger, "update_cathode_field"):
            cathode_label = ['A', 'B', 'C'][index]
            self.logger.update_cathode_field(cathode_label, "heater_current", current)
            self.logger.update_cathode_field(cathode_label, "heater_voltage", voltage)

    @staticmethod
    def _empty_power_supply_readback():
        return {
            "voltage": None,
            "current": None,
            "mode": None,
            "connected": False,
            "error": None,
            "updated_at": None,
        }

    def _set_power_supply_readback(self, index, voltage=None, current=None, mode=None, connected=False, error=None):
        if not 0 <= index < 3:
            return
        with self.power_supply_readback_lock:
            self.power_supply_readbacks[index] = {
                "voltage": voltage,
                "current": current,
                "mode": mode,
                "connected": connected,
                "error": error,
                "updated_at": datetime.datetime.now(),
            }

    def _get_power_supply_readback(self, index):
        if not 0 <= index < 3:
            return self._empty_power_supply_readback()
        with self.power_supply_readback_lock:
            return self.power_supply_readbacks[index].copy()

    def _reset_power_supply_runtime_state(self):
        """Reset cached 9104 readbacks, connection logs, error cadence, and config confirmation."""
        self._assert_power_supply_connection_tracking_main_thread()
        with self.power_supply_readback_lock:
            self.power_supply_readbacks = [self._empty_power_supply_readback() for _ in range(3)]
        self._reset_power_supply_connection_tracking()
        self.power_supply_last_logged_errors = [None, None, None]
        self.power_supply_last_error_log_times = [0.0, 0.0, 0.0]
        self._reset_power_supply_config_state()

    def _assert_power_supply_connection_tracking_main_thread(self):
        main_thread_ident = getattr(self, "_main_thread_ident", None)
        if main_thread_ident is None:
            raise RuntimeError("power_supply_valid_connections cannot be mutated before main thread ownership is initialized")
        if threading.get_ident() != main_thread_ident:
            raise RuntimeError("power_supply_valid_connections must only be mutated from the main Tk thread")

    def _reset_power_supply_connection_tracking(self, index=None):
        self._assert_power_supply_connection_tracking_main_thread()
        if index is None:
            self.power_supply_valid_connections = [False, False, False]
            return
        if 0 <= index < len(self.power_supply_valid_connections):
            self.power_supply_valid_connections[index] = False

    def _log_valid_power_supply_connection(self, index, voltage, current, mode):
        self._assert_power_supply_connection_tracking_main_thread()
        if not 0 <= index < len(self.power_supply_valid_connections):
            return
        if self.power_supply_valid_connections[index]:
            return
        self.power_supply_valid_connections[index] = True
        cathode = ['A', 'B', 'C'][index]
        port = self.com_ports.get(f'Cathode{cathode} PS', 'unknown port')
        self.log(
            f"CCS 9104 valid connection established for Cathode {cathode} on {port}: "
            f"{voltage:.2f}V, {current:.2f}A, {mode}.",
            LogLevel.INFO,
        )

    def _update_power_supply_connection_state_from_readback(self, index, readback):
        """Own 9104 connection transition logging from the Tk update loop."""
        self._assert_power_supply_connection_tracking_main_thread()
        if not 0 <= index < len(self.power_supply_valid_connections):
            return

        voltage = readback.get("voltage")
        current = readback.get("current")
        mode = readback.get("mode")

        if readback.get("connected") and voltage is not None and current is not None:
            self._log_valid_power_supply_connection(index, voltage, current, mode)
            return

        # A busy read means another command owns the serial lock temporarily; do not
        # turn a known-good connection into a recovery candidate for that case.
        if readback.get("error") != "busy":
            self._reset_power_supply_connection_tracking(index)

    def _log_power_supply_readback_state(self, index, error):
        """Log power-supply readback problems at an operator-level cadence, with DEBUG repeats."""
        if not 0 <= index < len(self.power_supply_last_logged_errors):
            return

        if not error:
            self.power_supply_last_logged_errors[index] = None
            return

        cathode = ['A', 'B', 'C'][index]
        if error == "busy":
            message = f"9104 readback skipped for Cathode {cathode}: serial interface busy"
            level = LogLevel.DEBUG
        elif error == "not_initialized":
            message = f"9104 readback unavailable for Cathode {cathode}: power supply not initialized"
            level = LogLevel.DEBUG
        elif error == "disconnected":
            message = f"9104 readback failed for Cathode {cathode}: power supply disconnected"
            level = LogLevel.ERROR
        elif error == "invalid_read":
            message = f"9104 readback failed for Cathode {cathode}: invalid voltage/current data"
            level = LogLevel.ERROR
        else:
            message = f"9104 readback failed for Cathode {cathode}: {error}"
            level = LogLevel.ERROR

        now = time.monotonic()
        last_error = self.power_supply_last_logged_errors[index]
        if (
            last_error == error
            and now - self.power_supply_last_error_log_times[index] < self.POLL_ERROR_LOG_INTERVAL_SECONDS
        ):
            self.log(message, LogLevel.VERBOSE)
            return

        self.power_supply_last_error_log_times[index] = now
        self.power_supply_last_logged_errors[index] = error
        self.log(message, level)

    def start_power_supply_polling(self):
        """Start the background 9104 readback poller if one is not already running."""
        thread = self.power_supply_poll_thread
        if thread and thread.is_alive():
            # A set stop event means an old poller is still exiting; do not start a duplicate.
            if self.power_supply_poll_stop_event.is_set():
                return False
            return True

        stop_event = threading.Event()
        try:
            thread = threading.Thread(
                target=self._power_supply_polling_loop,
                args=(stop_event,),
                name="Cathode9104Poller",
                daemon=True,
            )
            # Publish the event before start returns so a fast poller sees its own stop event.
            self.power_supply_poll_thread = thread
            self.power_supply_poll_stop_event = stop_event
            self.power_supply_poll_stop = stop_event
            thread.start()
        except Exception as exc:
            stop_event.set()
            self.power_supply_poll_thread = None
            self.power_supply_poll_stop_event = stop_event
            self.power_supply_poll_stop = stop_event
            self.log(f"Failed to start 9104 polling thread: {exc}", LogLevel.ERROR)
            return False

        return True

    def stop_power_supply_polling(self, timeout=5.0):
        """Stop the background 9104 readback poller without blocking indefinitely."""
        stop_event = self.power_supply_poll_stop_event
        stop_event.set()
        thread = self.power_supply_poll_thread
        # Avoid joining ourselves if shutdown is triggered from inside the poller.
        if thread and thread.is_alive() and threading.current_thread() is not thread:
            thread.join(timeout=timeout)
        if thread is None or not thread.is_alive():
            self.power_supply_poll_thread = None
            return True
        return False

    def _attempt_power_supply_reopen(self, index, ps):
        """Best-effort reopen for a disconnected existing 9104 object."""
        current_time = datetime.datetime.now()
        if (current_time - self.last_reconnect_attempt[index]) < self.RECONNECT_COOLDOWN:
            return

        self.last_reconnect_attempt[index] = current_time
        port = self.com_ports.get(f'Cathode{chr(65 + index)} PS')
        if not port:
            return

        try:
            ps.update_com_port(port)
        except Exception:
            # PowerSupply9104 logs serial failures itself; keep this worker quiet.
            pass

    def _configure_power_supply_after_readback(self, index, ps):
        """
        Apply preset/OVP/OCP after the 9104 has returned a valid live readback.

        The polling thread calls this because it already owns the hardware health check.
        Tk-backed limit values are snapshotted before entry so this worker does not read
        Tk variables directly.
        """
        if not 0 <= index < 3 or ps is None:
            return None

        now = time.monotonic()
        with self.power_supply_config_lock:
            if self.power_supply_configured[index]:
                return None
            last_attempt = self.power_supply_config_last_attempt[index]
            if (
                last_attempt
                and now - last_attempt < self.POWER_SUPPLY_CONFIG_RETRY_COOLDOWN_SECONDS
            ):
                return None

            # Copy desired limits and release the lock before doing slow serial I/O.
            desired_limits = self.power_supply_desired_limits[index].copy()
            self.power_supply_config_last_attempt[index] = now

        cathode = ['A', 'B', 'C'][index]
        cathode_name = f"Cathode{cathode} PS"
        try:
            ovp_value = desired_limits.get("ovp")
            ocp_value = desired_limits.get("ocp")
            if ovp_value is None or ocp_value is None:
                raise ValueError("desired OVP/OCP limits are unavailable")

            set_preset_response = ps.set_preset_selection(3)
            if set_preset_response:
                self.log(f"Set preset mode for {cathode_name} to 3 (normal mode).", LogLevel.INFO)
            else:
                self.log(
                    f"Failed to set preset mode for {cathode_name} to 3 (normal mode). "
                    f"Response: {set_preset_response}",
                    LogLevel.ERROR,
                )
                raise RuntimeError("failed to set preset mode 3")

            preset_response = ps.get_preset_selection()
            if preset_response is None:
                self.log(f"Failed to get preset mode for {cathode_name}", LogLevel.ERROR)
                raise RuntimeError("failed to confirm preset mode")
            if preset_response != 3:
                self.log(
                    f"Cathode {cathode_name} is not in preset mode 3 (normal mode). "
                    f"Current mode: {preset_response}",
                    LogLevel.WARNING,
                )
                raise RuntimeError(f"preset mode is {preset_response}, expected 3")
            self.log(
                f"Asserted preset mode 3 (normal mode) for cathode {cathode_name}. "
                f"Response: {preset_response}",
                LogLevel.INFO,
            )

            ovp_set = Decimal(str(float(ovp_value))).quantize(Decimal('0.01'))
            self.log(f"Setting OVP for cathode {cathode} to: {float(ovp_value):.2f}", LogLevel.DEBUG)
            if not ps.set_over_voltage_protection(ovp_set):
                self.log(f"Failed to set OVP for cathode {cathode}", LogLevel.ERROR)
                raise RuntimeError("failed to set OVP")
            self.log(f"Set OVP for cathode {cathode} to {float(ovp_value):.2f}V", LogLevel.INFO)

            confirmed_ovp = ps.get_over_voltage_protection()
            if confirmed_ovp is None:
                self.log(f"Failed to confirm OVP setting for cathode {cathode}", LogLevel.WARNING)
                raise RuntimeError("failed to confirm OVP")
            confirmed_ovp = float(confirmed_ovp)
            if abs(confirmed_ovp - float(ovp_value)) >= 0.1:
                self.log(
                    f"OVP mismatch for cathode {cathode}. "
                    f"Set: {float(ovp_value):.2f}V, Got: {confirmed_ovp:.2f}V",
                    LogLevel.WARNING,
                )
            else:
                self.log(f"OVP setting confirmed for cathode {cathode}: {confirmed_ovp:.2f}V", LogLevel.INFO)

            ocp_set = Decimal(str(float(ocp_value))).quantize(Decimal('0.01'))
            self.log(f"Setting OCP for cathode {cathode} to: {float(ocp_value):.2f}A", LogLevel.DEBUG)
            if not ps.set_over_current_protection(ocp_set):
                self.log(f"Failed to set OCP for cathode {cathode}", LogLevel.ERROR)
                raise RuntimeError("failed to set OCP")
            self.log(f"Set OCP for cathode {cathode} to {float(ocp_value):.2f}A", LogLevel.INFO)

            confirmed_ocp = ps.get_over_current_protection()
            if confirmed_ocp is None:
                self.log(f"Failed to confirm OCP setting for cathode {cathode}", LogLevel.WARNING)
                raise RuntimeError("failed to confirm OCP")
            confirmed_ocp = float(confirmed_ocp)
            if abs(confirmed_ocp - float(ocp_value)) >= 0.05:
                self.log(
                    f"OCP mismatch for cathode {cathode}. "
                    f"Set: {float(ocp_value):.2f}A, Got: {confirmed_ocp:.2f}A",
                    LogLevel.WARNING,
                )
            else:
                self.log(f"OCP setting confirmed for cathode {cathode}: {confirmed_ocp:.2f}A", LogLevel.INFO)

            # This flag is what lets the Tk thread enable buttons for this supply.
            with self.power_supply_config_lock:
                self.power_supply_configured[index] = True
                self.power_supply_config_confirmed_limits[index] = {
                    "ovp": confirmed_ovp,
                    "ocp": confirmed_ocp,
                }

            self.log(
                f"Configured Cathode {cathode} 9104 after valid readback: "
                f"preset 3, OVP {confirmed_ovp:.2f}V, OCP {confirmed_ocp:.2f}A.",
                LogLevel.INFO,
            )
            self.log(f"Initialized {cathode_name} on port {getattr(ps, 'port', 'unknown')}", LogLevel.INFO)
            return True
        except Exception as exc:
            error = str(exc)
            with self.power_supply_config_lock:
                self.power_supply_configured[index] = False
            self.log(f"Deferred 9104 configuration failed for Cathode {cathode}: {error}", LogLevel.WARNING)
            return False

    def _power_supply_polling_loop(self, stop_event=None):
        """Poll 9104 readbacks in the background and publish a cached snapshot."""
        stop_event = stop_event or self.power_supply_poll_stop_event

        while not stop_event.is_set():
            loop_start = time.monotonic()

            if self.power_supply_reconfiguring.is_set():
                # COM updates own the supply list briefly; wait without touching old drivers.
                stop_event.wait(self.power_supply_poll_interval)
                continue

            for index in range(3):
                # Re-check between cathodes so a COM update does not wait for a full cycle.
                if stop_event.is_set() or self.power_supply_reconfiguring.is_set():
                    break

                ps = self.power_supplies[index] if index < len(self.power_supplies) else None
                if ps is None:
                    self._reset_power_supply_config_state(index)
                    self._set_power_supply_readback(index, error="not_initialized")
                    continue

                try:
                    connected = ps.is_connected()
                    if connected is None:
                        # Another command owns the serial lock; keep the GUI responsive and retry later.
                        self._set_power_supply_readback(index, error="busy")
                        continue
                    if not connected:
                        self._reset_power_supply_config_state(index)
                        self._set_power_supply_readback(index, error="disconnected")
                        # Reconfiguration replaces objects itself, so only normal polling reconnects here.
                        if not self.power_supply_reconfiguring.is_set():
                            self._attempt_power_supply_reopen(index, ps)
                        continue

                    voltage, current, mode = ps.get_voltage_current_mode()
                    if voltage is None or current is None:
                        self._reset_power_supply_config_state(index)
                        self._set_power_supply_readback(index, error="invalid_read")
                    else:
                        self._set_power_supply_readback(
                            index,
                            voltage=voltage,
                            current=current,
                            mode=mode,
                            connected=True,
                        )
                        # A parsed readback proves the device is responsive; only then push
                        # preset/limit configuration and allow commands to become ready.
                        self._configure_power_supply_after_readback(index, ps)
                except Exception as exc:
                    self._reset_power_supply_config_state(index)
                    self._set_power_supply_readback(index, error=str(exc))

            elapsed = time.monotonic() - loop_start
            sleep_time = max(0.05, self.power_supply_poll_interval - elapsed)
            stop_event.wait(sleep_time)

    def _mark_power_supply_unavailable(self, index, *, mark_status_unavailable=True):
        """
        Clear one cathode's power-supply readbacks without skipping temperature updates.

        mark_status_unavailable should be true for non-busy readback failures
        that should clear command-ready state.
        """
        if mark_status_unavailable and index < len(self.power_supply_status):
            self._set_power_supply_command_ready(index, False)

        self.actual_heater_current_vars[index].set("--")
        self.actual_heater_voltage_vars[index].set("--")
        self.operation_mode_var[index].set("Mode: --")

        if index < len(self.cv_cc_labels):
            cv_lbl, cc_lbl = self.cv_cc_labels[index]
            cv_lbl.config(bg='grey')
            cc_lbl.config(bg='grey')

        self._publish_cathode_power_readback(index, None, None)

    
    def update_data(self):
        if getattr(self, "_updates_cancelled", False):
            return

        try:
            self._update_data_once()
        except Exception as e:
            message = f"Cathode heating update_data failed: {type(e).__name__}: {e}"
            try:
                self.log(message, LogLevel.ERROR)
            except Exception:
                pass
        finally:
            if not getattr(self, "_updates_cancelled", False):
                self.after_id = self.parent.after(500, self.update_data)

    def _update_data_once(self):
        current_time = datetime.datetime.now()
        plot_this_cycle = (
            self.TEMPERATURE_GRAPHS_ENABLED
            and (current_time - self.last_plot_time) >= self.plot_interval
        )

        self.flush_queued_logs()
        # Flush any queued logs from controllers to ensure log is up to date before processing new data
        if self.temperature_controller and hasattr(self.temperature_controller, "flush_queued_logs"):
            self.temperature_controller.flush_queued_logs()
        # Flush logs for each power supply as well to capture any recent communication issues or status changes before we read new data
        for power_supply in self.power_supplies:
            if power_supply and hasattr(power_supply, "flush_queued_logs"):
                power_supply.flush_queued_logs()

        for i in range(3):
            self.log(f"Processing Cathode {['A', 'B', 'C'][i]}", LogLevel.VERBOSE)

            voltage = None
            current = None
            mode = None
            temperature = None

            if self.power_supplies_initialized and self.power_supplies[i] is not None:
                readback = self._get_power_supply_readback(i)
                self._update_power_supply_connection_state_from_readback(i, readback)
                voltage = readback.get("voltage")
                current = readback.get("current")
                mode = readback.get("mode")

                if readback.get("connected") and voltage is not None and current is not None:
                    self._log_power_supply_readback_state(i, None)
                    # The poller owns hardware I/O. The Tk thread mirrors its cached
                    # configuration result into command state and readback labels.
                    with self.power_supply_config_lock:
                        power_supply_configured = self.power_supply_configured[i]
                        confirmed_limits = self.power_supply_config_confirmed_limits[i].copy()
                    self._set_power_supply_command_ready(i, power_supply_configured)

                    confirmed_ovp = confirmed_limits.get("ovp")
                    if confirmed_ovp is not None:
                        self.ovl_live_values[i] = float(confirmed_ovp)
                        self.overvoltage_limit_vars[i].set(float(confirmed_ovp))
                        self.ovl_readback_vars[i].set(f"{float(confirmed_ovp):.2f}")

                    confirmed_ocp = confirmed_limits.get("ocp")
                    if confirmed_ocp is not None:
                        self.ocl_live_values[i] = float(confirmed_ocp)
                        self.overcurrent_limit_vars[i].set(float(confirmed_ocp))
                        self.ocl_readback_vars[i].set(f"{float(confirmed_ocp):.2f}")

                    self.log(f"Power supply {i+1} readings - Voltage: {voltage:.2f}V, Current: {current:.2f}A, Mode: {mode}", LogLevel.VERBOSE)

                    self.actual_heater_current_vars[i].set(f"{current:.2f}")
                    self.actual_heater_voltage_vars[i].set(f"{voltage:.2f}")

                    self._publish_cathode_power_readback(i, current, voltage)

                    # Update mode display
                    cv_lbl, cc_lbl = self.cv_cc_labels[i]

                    if mode == "CV Mode":
                        cv_lbl.config(bg='green')
                        cc_lbl.config(bg='grey')
                    elif mode == "CC Mode":
                        cc_lbl.config(bg='green')
                        cv_lbl.config(bg='grey')
                    else: # supply off or error
                        cv_lbl.config(bg='grey')
                        cc_lbl.config(bg='grey')
                else:
                    # Busy readbacks are display-only. Any other readback error means
                    # command readiness should wait for a fresh configured readback.
                    error = readback.get("error")
                    self._log_power_supply_readback_state(i, error)
                    mark_status_unavailable = bool(error and error != "busy")
                    self._mark_power_supply_unavailable(
                        i,
                        mark_status_unavailable=mark_status_unavailable,
                    )
            else:
                self._reset_power_supply_connection_tracking(i)
                self._log_power_supply_readback_state(i, "not_initialized")
                self._mark_power_supply_unavailable(i)

            temperature = self.read_temperature(i)
            if self.logger and hasattr(self.logger, "update_cathode_field"):
                cathode_label = ['A', 'B', 'C'][i]
                self.logger.update_cathode_field(cathode_label, "clamp_temperature", temperature)

            if isinstance(temperature, float):
                self.clamp_temperature_vars[i].set(f"{temperature:.1f} C")

            self._update_cathode_comms_indicators(i)

            if plot_this_cycle:
                self.time_data[i] = np.append(self.time_data[i], current_time)
                self.temperature_data[i][0].set_data(self.time_data[i], np.append(self.temperature_data[i][0].get_data()[1], temperature))
                if len(self.time_data[i]) > self.MAX_POINTS:
                    self.time_data[i] = self.time_data[i][-self.MAX_POINTS:]
                    self.temperature_data[i][0].set_data(self.time_data[i], self.temperature_data[i][0].get_data()[1][-self.MAX_POINTS:])

                self.last_plot_time = current_time  # Reset the plot timer

            # Update Config page labels
            self.voltage_display_vars[i].set(f'Voltage: {voltage:.2f}' if voltage is not None else 'Voltage: --')
            self.current_display_vars[i].set(f'Current: {current:.2f}' if current is not None else 'Current: --')
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

    def cancel_updates(self):
        '''Cancel after() scheduled updates, to be called by dashboard when app is quit.'''
        self._updates_cancelled = True
        if hasattr(self, 'after_id') and self.after_id:
            try:
                self.parent.after_cancel(self.after_id)
                if self.logger:
                    self.log('Canceled scheduled cathode heating display update.', LogLevel.DEBUG)
            except Exception as e:
                if self.logger:
                    self.log('Failed to cancel scheduled cathode heating display update.', LogLevel.DEBUG)
            finally:
                self.after_id = None

    def update_plot(self, index):
        if (
            not self.TEMPERATURE_GRAPHS_ENABLED
            or len(self.time_data[index]) == 0
            or not self.temperature_data[index]
        ):
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
            self.log(f"Disabled voltage ramping for Cathode {['A', 'B', 'C'][index]} - voltage changes will be immediate", LogLevel.INFO)

    def toggle_output(self, index, control_mode: str = None):
        if not self.power_supplies_initialized or not self.power_supplies:
            self.log("Power supplies not properly initialized or list is empty.", LogLevel.ERROR)
            return
        
        if control_mode not in ("current", "voltage"):
            control_mode = self.ramp_control_mode[index]

        new_state = not self.toggle_states[index]

        if new_state:  # If turning output ON
            if self.disable_ccs_output_on_bcon_disconnect:
                bcon_is_connected = getattr(self, "bcon_is_connected", None)
                try:
                    bcon_connected = (
                        bool(bcon_is_connected()) if callable(bcon_is_connected) else False
                    )
                except Exception:
                    bcon_connected = False
                if not bcon_connected:
                    cathode = ['A', 'B', 'C'][index]
                    self.log(
                        f"CCS output enable blocked for Cathode {cathode}: BCON device not connected.",
                        LogLevel.WARNING,
                    )
                    return

            pressure_allows_output = getattr(
                self,
                "vtrx_ccs_pressure_allows_output",
                None,
            )
            if callable(pressure_allows_output):
                cathode = ['A', 'B', 'C'][index]
                pressure_block_reason = "VTRX pressure is above 1e-5 mbar."
                try:
                    pressure_guard_result = pressure_allows_output()
                except Exception as e:
                    self.log(
                        f"CCS output enable blocked for Cathode {cathode}: VTRX pressure check failed ({e}).",
                        LogLevel.WARNING,
                    )
                    return
                if isinstance(pressure_guard_result, tuple):
                    blocked_by_pressure = not bool(pressure_guard_result[0])
                    if len(pressure_guard_result) > 1 and pressure_guard_result[1]:
                        pressure_block_reason = str(pressure_guard_result[1])
                else:
                    blocked_by_pressure = not bool(pressure_guard_result)
                if blocked_by_pressure:
                    if not pressure_block_reason.endswith("."):
                        pressure_block_reason = f"{pressure_block_reason}."
                    self.log(
                        f"CCS output enable blocked for Cathode {cathode}: {pressure_block_reason}",
                        LogLevel.WARNING,
                    )
                    return

            # Retrieve target voltage and current
            target_voltage = self.user_set_voltages[index]
            if target_voltage is None:
                self.log(f"CCS output enable blocked for Cathode {['A', 'B', 'C'][index]}: target voltage is not set.", LogLevel.WARNING)
                msgbox.showwarning("Warning", f"Target voltage for Cathode {['A', 'B', 'C'][index]} is not set.")
                return
            
            ovp = self.get_ovp(index)

            if ovp is None:
                self.log(f"Could not retrieve OVP for Cathode {['A', 'B', 'C'][index]}. Cannot verify voltage limit.", LogLevel.ERROR)
                return
                
            if target_voltage > ovp:
                self.log(
                    f"CCS output enable blocked for Cathode {['A', 'B', 'C'][index]}: "
                    f"target voltage {target_voltage:.2f}V exceeds OVP {ovp:.2f}V.",
                    LogLevel.WARNING,
                )
                msgbox.showerror("Error", f"Target voltage {target_voltage:.2f}V exceeds OVP limit of {ovp:.2f}V for Cathode {['A', 'B', 'C'][index]}.")
                return

            target_current = self.user_set_currents[index]
            if target_current is None:
                self.log(f"CCS output enable blocked for Cathode {['A', 'B', 'C'][index]}: target current is not set.", LogLevel.WARNING)
                msgbox.showwarning("Warning", f"Target current for Cathode {['A', 'B', 'C'][index]} is not set.")
                return
            
            ocp = self.get_ocp(index)

            if ocp is None:
                self.log(f"Could not retrieve OCP for Cathode {['A', 'B', 'C'][index]}. Cannot verify current limit.", LogLevel.ERROR)
                return
            
            if target_current > ocp:
                self.log(
                    f"CCS output enable blocked for Cathode {['A', 'B', 'C'][index]}: "
                    f"target current {target_current:.2f}A exceeds OCP {ocp:.2f}A.",
                    LogLevel.WARNING,
                )
                msgbox.showerror("Error", f"Target current {target_current:.2f}A exceeds OCP limit of {ocp:.2f}A for Cathode {['A', 'B', 'C'][index]}.")
                return
            

            sent_current_callback = lambda sent_value, i=index: self.parent.after(0, lambda idx=i, val=sent_value: self._update_sent_current_display(idx, val))
            sent_voltage_callback = lambda sent_value, i=index: self.parent.after(0, lambda idx=i, val=sent_value: self._update_sent_voltage_display(idx, val))
            
            # Fault paths below use disable_output() so shutoff bypasses output-on validation
            # and failed shutoff attempts are logged as critical by the 9104 driver.
            if self.ramp_status[index]: # ramp is on; Gradual Set
                if target_current is not None and control_mode == "current":
                    # Set voltage first, then preset a safe low current before enabling output
                    # so the supply cannot energize with a stale higher stored current limit.
                    if not self.power_supplies[index].set_voltage(voltage=target_voltage, preset=3, sent_callback=sent_voltage_callback):
                        # Log and cancel ramp operation if voltage fails to be set 
                        self.log(f"Failed to set Cathode {['A', 'B', 'C'][index]} power supply to voltage: {target_voltage}; ramp cancelled", LogLevel.ERROR)
                        self.power_supplies[index].disable_output()
                        return

                    safe_start_current = 0.0
                    if not self.power_supplies[index].set_current(current=safe_start_current, preset=3, sent_callback=sent_current_callback):
                        self.log(f"Failed to preset safe start current for Cathode {['A', 'B', 'C'][index]}; ramp cancelled", LogLevel.ERROR)
                        self.power_supplies[index].disable_output()
                        return

                    if not self.power_supplies[index].set_output("1"):
                        self.log(f"Failed to enable output for Cathode {['A', 'B', 'C'][index]}", LogLevel.ERROR)
                        return
                    
                    # Ramp to target current
                    slew_rate = self.curr_slew_rate[index]
                    step_delay = 1.0  # seconds
                    step_size = slew_rate * step_delay

                    self.log(f"Starting current ramp for Cathode {['A', 'B', 'C'][index]} power supply with step size {step_size:.3f}A and delay {step_delay:.1f}s", LogLevel.INFO)
                    ramp_started = self.power_supplies[index].ramp_current(
                        target_current,
                        step_size=step_size,
                        step_delay=step_delay,
                        preset=3,
                        callback=lambda ok, i=index: self.parent.after(0, lambda idx=i, success=ok: self.handle_ramp_result(idx, success)),
                        sent_callback=sent_current_callback
                    )
                    if not ramp_started:
                        self.log(f"Failed to start current ramp for Cathode {['A', 'B', 'C'][index]}", LogLevel.ERROR)
                        self.power_supplies[index].disable_output()
                        return
                    self.on_ramp_start(index)
                elif target_voltage is not None and control_mode == "voltage":
                    # Set current first, then preset a safe low voltage before enabling output
                    # so the supply cannot energize with a stale higher stored voltage value.
                    if not self.power_supplies[index].set_current(current=target_current, preset=3, sent_callback=sent_current_callback):
                        self.log(f"Failed to set Cathode {['A', 'B', 'C'][index]} power supply to current: {target_current}; ramp cancelled", LogLevel.ERROR)
                        self.power_supplies[index].disable_output()
                        return
                    
                    safe_start_voltage = 0.0
                    if not self.power_supplies[index].set_voltage(voltage=safe_start_voltage, preset=3, sent_callback=sent_voltage_callback):
                        self.log(f"Failed to preset safe start voltage for Cathode {['A', 'B', 'C'][index]}; ramp cancelled", LogLevel.ERROR)
                        self.power_supplies[index].disable_output()
                        return

                    if not self.power_supplies[index].set_output("1"):
                        self.log(f"Failed to enable output for Cathode {['A', 'B', 'C'][index]}", LogLevel.ERROR)
                        return

                    # Ramp up to the target voltage
                    slew_rate = self.vlt_slew_rate[index]
                    step_delay = 1.0  # seconds
                    step_size = slew_rate * step_delay
                    
                    self.log(f"Starting voltage ramp for Cathode {['A', 'B', 'C'][index]} power supply with step size {step_size:.3f}V and delay {step_delay:.1f}s", LogLevel.INFO)
                    ramp_started = self.power_supplies[index].ramp_voltage(
                        target_voltage,
                        step_size=step_size,
                        step_delay=step_delay,
                        preset=3,
                        callback = lambda ok,
                        i=index: self.parent.after(0, lambda idx=i, success=ok: self.handle_ramp_result(idx, success)),
                        sent_callback=sent_voltage_callback
                    )
                    if not ramp_started:
                        self.log(f"Failed to start voltage ramp for Cathode {['A', 'B', 'C'][index]}", LogLevel.ERROR)
                        self.power_supplies[index].disable_output()
                        return
                    self.on_ramp_start(index)
            else: # ramp is off; Immediate Set both voltage and current
                if not self.power_supplies[index].set_current(current=target_current, preset=3, sent_callback=sent_current_callback):
                    self.log(f"Failed to set Cathode {['A', 'B', 'C'][index]} power supply to current: {target_current}; immediate set cancelled", LogLevel.ERROR)
                    return
                if not self.power_supplies[index].set_voltage(voltage=target_voltage, preset=3, sent_callback=sent_voltage_callback):
                    self.log(f"Failed to set Cathode {['A', 'B', 'C'][index]} power supply to voltage: {target_voltage}; immediate set cancelled", LogLevel.ERROR)
                    return
                if not self.power_supplies[index].set_output("1"):
                    self.log(f"Failed to enable output for Cathode {['A', 'B', 'C'][index]}", LogLevel.ERROR)
                    return
                
        else:
            # turning off the output
            output_disabled = self.power_supplies[index].disable_output()
            if output_disabled:
                self.log(f"Disabled output for Cathode {['A', 'B', 'C'][index]}", LogLevel.INFO)
            else:
                self.log(f"Failed to disable output for Cathode {['A', 'B', 'C'][index]}", LogLevel.ERROR)
            self.on_ramp_complete(index)

        # Update the toggle state and button image
        self.toggle_states[index] = new_state
        current_image = self.toggle_on_image if self.toggle_states[index] else self.toggle_off_image
        self.toggle_buttons[index].config(image=current_image)

    def turn_off_all_beams(self):
        """
        Redundantly turns off all cathode heaters by disabling power supply outputs.
        Side effects:
            - Disables output on all available power supply handles
            - Updates toggle button states and images
            - Logs actions and any errors
        """
        if not self.power_supplies:
            self.log("Power supply list is empty; cannot turn off heaters.", LogLevel.ERROR)
            return

        if not self.power_supplies_initialized:
            self.log("Power supplies are not marked initialized; attempting OFF for any available handles.", LogLevel.WARNING)

        for i, ps in enumerate(self.power_supplies):
            cathode_label = ['A', 'B', 'C'][i]
            if not ps:
                self.log(f"Power supply handle for Cathode {cathode_label} is unavailable; cannot turn off heater.", LogLevel.WARNING)
                continue

            try:
                if hasattr(ps, 'stop_ramp'):
                    ps.stop_ramp()

                if hasattr(ps, 'disable_output'):
                    output_disabled = ps.disable_output()
                else:
                    output_disabled = ps.set_output("0")

                if output_disabled:
                    self.log(f"Turned off heater for Cathode {cathode_label}", LogLevel.INFO)
                    # Update toggle state and button image
                    self.toggle_states[i] = False
                    self.toggle_buttons[i].config(image=self.toggle_off_image)
                else:
                    self.log(f"Failed to turn off heater for Cathode {cathode_label}", LogLevel.ERROR)
            except Exception as e:
                self.log(f"Error turning off heater for Cathode {cathode_label}: {str(e)}", LogLevel.ERROR)

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
        # Reset prediction values
        self._set_predicted_emission_current_ma(index)
        self.predicted_grid_current_vars[index].set('--')
        self.predicted_heater_current_vars[index].set('--')
        self.predicted_temperature_vars[index].set('--')

        # Clear UI setpoints
        self.heater_voltage_vars[index].set('--')
        self.heater_current_vars[index].set('--')

        # Reset state flags
        self.user_set_voltages[index] = None
        self.user_set_currents[index] = None
        self.voltage_set[index] = False
        self.current_set[index] = False        

    def clear_prediction_variables(self, index):
        """Clear only prediction display fields while preserving active setpoints/state."""
        self._set_predicted_emission_current_ma(index)
        self.predicted_grid_current_vars[index].set('--')
        self.predicted_heater_current_vars[index].set('--')
        self.predicted_heater_voltage_vars[index].set('--')
        self.predicted_temperature_vars[index].set('--')

    def _get_interpolation_axes(self, index: int, x_col: str, y_col: str):
        """Return sorted numeric (x, y) arrays for LUT interpolation."""
        table = self.lookup_table_setting[index]
        if table is None or table.empty:
            return None, None

        numeric = pd.DataFrame(
            {
                x_col: pd.to_numeric(table[x_col], errors="coerce"),
                y_col: pd.to_numeric(table[y_col], errors="coerce"),
            }
        ).dropna()
        if numeric.empty:
            return None, None

        # Collapse duplicate x-values to one functional value before interpolation.
        collapsed = (
            numeric.groupby(x_col, as_index=False)[y_col]
            .median()
            .sort_values(x_col)
        )

        x_vals = collapsed[x_col].to_numpy(dtype=float)
        y_vals = collapsed[y_col].to_numpy(dtype=float)
        return x_vals, y_vals

    def _is_above_lut_domain(self, index: int, x_value: float, x_col: str, y_col: str):
        """Return True only when x_value is above the available LUT domain."""
        x_vals, _ = self._get_interpolation_axes(index, x_col, y_col)
        if x_vals is None or len(x_vals) == 0:
            return False
        try:
            return float(x_value) > float(x_vals[-1])
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _linear_model_value(points, x_value, x_index=0, y_index=1):
        """
        Return a linear interpolation/extrapolation from static model points.

        This is intentionally separate from LUT interpolation. Operator LUT data is
        treated as authoritative and is never extrapolated. The ES440 characterization
        data is a fallback physics model, so when the requested setpoint is above the
        measured LUT domain we continue the nearest ES440 segment rather than clearing
        the prediction. That makes the output visibly model-derived instead of silently
        pretending the LUT contained the point.
        """
        try:
            x_target = float(x_value)
        except (TypeError, ValueError):
            return None

        numeric = pd.DataFrame(
            {
                "x": [float(point[x_index]) for point in points],
                "y": [float(point[y_index]) for point in points],
            }
        ).replace([np.inf, -np.inf], np.nan).dropna()
        if numeric.empty:
            return None

        collapsed = numeric.groupby("x", as_index=False)["y"].median().sort_values("x")
        x_vals = collapsed["x"].to_numpy(dtype=float)
        y_vals = collapsed["y"].to_numpy(dtype=float)
        if len(x_vals) == 1:
            return float(y_vals[0])

        if x_target <= x_vals[0]:
            x0, x1 = x_vals[0], x_vals[1]
            y0, y1 = y_vals[0], y_vals[1]
        elif x_target >= x_vals[-1]:
            x0, x1 = x_vals[-2], x_vals[-1]
            y0, y1 = y_vals[-2], y_vals[-1]
        else:
            return float(np.interp(x_target, x_vals, y_vals))

        if x1 == x0:
            return float(y1)
        return float(y0 + (x_target - x0) * (y1 - y0) / (x1 - x0))

    @classmethod
    def _richardson_cathode_area_cm2(cls):
        """Return circular emitting area in cm^2 from configured cathode diameter."""
        radius_cm = (cls.RICHARDSON_CATHODE_DIAMETER_MM / 10.0) / 2.0
        return float(np.pi * radius_cm * radius_cm)

    def _prediction_model_calibration(self, index):
        """Return the outside-LUT calibration for the selected dataset."""
        calibration = dict(self.PREDICTION_MODEL_DEFAULT_CALIBRATION)
        selected_files = getattr(self, "selected_lut_files", None)
        selected_filename = None
        if selected_files is not None and 0 <= index < len(selected_files):
            selected_filename = selected_files[index]

        if selected_filename:
            selected_key = str(selected_filename).lower()
            for filename, overrides in self.PREDICTION_MODEL_DATASET_CALIBRATIONS.items():
                if filename.lower() == selected_key:
                    calibration.update(overrides)
                    break
        return calibration

    def _estimate_heater_voltage_from_current_model(self, index, current):
        """Estimate physical heater voltage from the dataset-corrected I-V model."""
        voltage = self._linear_model_value(
            ES440_cathode.heater_voltage_current_data,
            current,
            x_index=0,
            y_index=1,
        )
        if voltage is None:
            return None
        calibration = self._prediction_model_calibration(index)
        return voltage + calibration["heater_iv_voltage_offset_v"]

    def _estimate_heater_current_from_voltage_model(self, index, voltage):
        """Estimate physical heater current from the dataset-corrected I-V model."""
        try:
            model_voltage = float(voltage)
        except (TypeError, ValueError):
            return None
        calibration = self._prediction_model_calibration(index)
        model_voltage -= calibration["heater_iv_voltage_offset_v"]
        return self._linear_model_value(
            ES440_cathode.heater_voltage_current_data,
            model_voltage,
            x_index=1,
            y_index=0,
        )

    def _estimate_true_temperature_from_current_model(self, current):
        """Estimate true emitting-surface temperature in K from heater current."""
        return self._linear_model_value(
            ES440_cathode.heater_current_true_temperature_data,
            current,
            x_index=0,
            y_index=1,
        )

    def _estimate_mode_aware_temperature(
        self,
        index,
        heater_voltage,
        heater_current,
        controlling_mode,
    ):
        """Return the effective temperature for the binding outside-LUT constraint.

        The physical heater I-V correction and the emission-model corrections are
        intentionally separate. Voltage control uses its voltage only as an
        internal coordinate in the raw ES440 model. Current control uses physical
        heater current and applies the dataset's temperature calibration.
        """
        calibration = self._prediction_model_calibration(index)
        if controlling_mode == "voltage":
            try:
                model_voltage = (
                    float(heater_voltage)
                    + calibration["voltage_mode_model_offset_v"]
                )
            except (TypeError, ValueError):
                return None
            model_heater_current = self._linear_model_value(
                ES440_cathode.heater_voltage_current_data,
                model_voltage,
                x_index=1,
                y_index=0,
            )
            if model_heater_current is None:
                return None
            temperature_k = self._estimate_true_temperature_from_current_model(
                model_heater_current
            )
            correction = "voltage-model offset"
        elif controlling_mode == "current":
            try:
                model_heater_current = float(heater_current)
            except (TypeError, ValueError):
                return None
            temperature_k = self._estimate_true_temperature_from_current_model(
                model_heater_current
            )
            if temperature_k is not None:
                temperature_k += calibration["current_mode_temperature_offset_k"]
            correction = "current-temperature offset"
        else:
            return None

        if temperature_k is None:
            return None
        return {
            "temperature_k": float(temperature_k),
            "model_heater_current": float(model_heater_current),
            "control_mode": controlling_mode,
            "correction": correction,
        }

    def _richardson_emission_current_a(self, temperature_k):
        """
        Predict total thermionic emission current with Richardson-Dushman.

        I = area * A * T^2 * exp(-phi / (k_B * T))

        - area is the configured circular LaB6 emitting area in cm^2.
        - A is the configured Richardson constant in A cm^-2 K^-2.
        - phi is the configured LaB6 work function in eV.
        - k_B is in eV/K, so phi / (k_B*T) is dimensionless.
        """
        try:
            temp_k = float(temperature_k)
        except (TypeError, ValueError):
            return None
        if not np.isfinite(temp_k) or temp_k <= 0:
            return None

        area_cm2 = self._richardson_cathode_area_cm2()
        exponent = -self.RICHARDSON_WORK_FUNCTION_EV / (self.BOLTZMANN_CONSTANT_EV_PER_K * temp_k)
        emission_a = area_cm2 * self.RICHARDSON_CONSTANT_A_PER_CM2_K2 * temp_k * temp_k * np.exp(exponent)
        if not np.isfinite(emission_a) or emission_a < 0:
            return None
        return float(emission_a)

    def _richardson_fallback_beam_current_ma(
        self,
        index,
        heater_voltage,
        target_heater_current=None,
        controlling_mode=None,
    ):
        """
        Predict beam current above the LUT domain using Richardson-Dushman.

        The dashboard's normal prediction source is the selected LUT. That table is
        based on system data and stores beam_current in mA, so it should remain the
        authority for all in-range points. This fallback is used only when the
        requested heater voltage/current is above the LUT range.

        The physics path is:
        1. Resolve the physical heater current from the requested limits and the
           dataset-corrected I-V relationship.
        2. Use the correction for the binding constraint to estimate effective
           emitting-surface temperature. This is a model temperature, not clamp
           temperature.
        3. Apply Richardson-Dushman to predict total emission current in amps.
        4. Convert total emission current to beam current in mA using the configured
           beam/emission fraction, matching the existing dashboard convention:
           emission_mA = beam_current_mA / 0.72.

        Because Richardson-Dushman is exponentially sensitive to temperature, this
        should be treated as an outside-LUT model estimate, not a measured value.
        """
        above_voltage_lut = self._is_above_lut_domain(index, heater_voltage, "voltage", "beam_current")

        heater_current = None
        try:
            if target_heater_current is not None:
                heater_current = float(target_heater_current)
        except (TypeError, ValueError):
            heater_current = None

        if heater_current is None:
            if not above_voltage_lut:
                return None
            heater_current = self._estimate_heater_current_from_voltage_model(
                index,
                heater_voltage,
            )
        else:
            above_current_lut = self._is_above_lut_domain(index, heater_current, "heater_current", "voltage")
            if not above_voltage_lut and not above_current_lut:
                return None

        if controlling_mode not in ("current", "voltage"):
            # Compatibility fallback for callers that have not resolved a binding
            # constraint: supplied current implies current control; otherwise use
            # voltage control.
            controlling_mode = "current" if target_heater_current is not None else "voltage"

        temperature_prediction = self._estimate_mode_aware_temperature(
            index,
            heater_voltage,
            heater_current,
            controlling_mode,
        )
        if temperature_prediction is None:
            return None
        temperature_k = temperature_prediction["temperature_k"]
        emission_current_a = self._richardson_emission_current_a(temperature_k)
        if emission_current_a is None:
            return None

        beam_current_ma = emission_current_a * 1000.0 * self.BEAM_CURRENT_FRACTION_OF_EMISSION
        return {
            "heater_current": float(heater_current),
            "model_heater_current": temperature_prediction["model_heater_current"],
            "temperature_k": float(temperature_k),
            "emission_current_a": float(emission_current_a),
            "beam_current_ma": float(beam_current_ma),
            "control_mode": controlling_mode,
            "correction": temperature_prediction["correction"],
        }

    def _log_richardson_fallback_prediction(self, index, heater_voltage, fallback, reason):
        """
        Log that prediction has left measured LUT data and is using ES440/RD data.

        Classification follows the dashboard logging policy:
        - WARNING: outside-LUT prediction is a degraded state. The dashboard can
          still provide a prediction, but it is model-derived rather than measured
          LUT-derived.
        - DEBUG: numeric model details are diagnostics. They are useful for
          validating the fallback and constants, but too detailed for normal
          operator-level INFO logs.
        """
        cathode_label = ['A', 'B', 'C'][index]
        self.log(
            (
                f"Cathode {cathode_label} emission prediction is above the selected LUT "
                f"domain ({reason}); using ES440 temperature data and Richardson-Dushman fallback."
            ),
            LogLevel.WARNING,
        )
        self.log(
            (
                f"Cathode {cathode_label} Richardson fallback details: "
                f"control_mode={fallback['control_mode']}, "
                f"heater_voltage={float(heater_voltage):.3f}V, "
                f"heater_current={fallback['heater_current']:.3f}A, "
                f"model_heater_current={fallback['model_heater_current']:.3f}A, "
                f"effective_temperature={fallback['temperature_k']:.1f}K, "
                f"emission={fallback['emission_current_a'] * 1000.0:.6f}mA, "
                f"beam={fallback['beam_current_ma']:.6f}mA, "
                f"diameter={self.RICHARDSON_CATHODE_DIAMETER_MM:.3f}mm, "
                f"A={self.RICHARDSON_CONSTANT_A_PER_CM2_K2:g}A/cm^2/K^2, "
                f"phi={self.RICHARDSON_WORK_FUNCTION_EV:g}eV."
            ),
            LogLevel.DEBUG,
        )

    def _interpolate_lut_value(self, index: int, x_value: float, x_col: str, y_col: str):
        """Linearly interpolate LUT value for x_value; return None when out of range."""
        x_vals, y_vals = self._get_interpolation_axes(index, x_col, y_col)
        if x_vals is None or y_vals is None or len(x_vals) == 0:
            return None

        if len(x_vals) == 1:
            return float(y_vals[0]) if abs(float(x_value) - float(x_vals[0])) < 1e-12 else None

        # No extrapolation: only interpolate inside LUT domain.
        if x_value < x_vals[0] or x_value > x_vals[-1]:
            return None

        return float(np.interp(float(x_value), x_vals, y_vals))

    def reset_power_supply(self, index):
        """
        Reset a power supply to zero voltage and current (UVL and UCL)

        Args:
            index (int): Index of the power supply to reset (0-2)

        Side effects:
            - Sets voltage to 0 and current to 0.0
            - Resets all prediction variables to '--'
            - Logs the reset action
        """
        if self.power_supply_status[index]:
            voltage_reset = self.power_supplies[index].set_voltage(3, 0.0, sent_callback=lambda v, i=index: self._update_sent_voltage_display(i, v))
            current_reset = self.power_supplies[index].set_current(3, 0.0, sent_callback=lambda c, i=index: self._update_sent_current_display(i, c))
            if voltage_reset and current_reset:
                self.log(f"Reset power supply settings for Cathode {['A', 'B', 'C'][index]}", LogLevel.INFO)
            else:
                self.log(f"Failed to reset power supply settings for Cathode {['A', 'B', 'C'][index]}", LogLevel.ERROR)
        self._set_predicted_emission_current_ma(index)
        self.predicted_grid_current_vars[index].set('--')
        self.predicted_heater_current_vars[index].set('--')
        self.predicted_temperature_vars[index].set('--')
        
        self.heater_voltage_vars[index].set('--')
        self.heater_current_vars[index].set('--')


    def handle_current_entry_set(self, index, current_entry):
        """
        Handle the Set button for the heater current entry.

        Args:
            index (int): Cathode index (0-2).
            current_entry (ttk.Entry): Entry widget containing the requested heater current.

        Clears the current goal when the entry is empty. Otherwise validates the
        entered current, updates predictions, and applies the requested output.
        """
        # Check for active ramping
        if self.is_ramping(index):
            self.log(f"Cannot set manual current for Cathode {['A', 'B', 'C'][index]} while ramping is enabled.", LogLevel.WARNING)
            msgbox.showwarning('Ramp in progress','Please wait for the ramp to finish or press STOP RAMP.') # add option in msg box to stop ramp
            return

        try:
            raw_value = str(current_entry.get()).strip()
            if raw_value == "":
                # Treat empty entry as a user request to clear the current goal.
                self.user_set_currents[index] = None
                self.current_set[index] = False
                self.heater_current_vars[index].set('--')
                self.sent_heater_current_vars[index].set('--')
                self.predicted_heater_current_vars[index].set('--')
                self.log(f"Cleared current goal for Cathode {['A', 'B', 'C'][index]}", LogLevel.INFO)
                self.refresh_predictions(index)
                return

            new_current = float(raw_value)
            valid_input = self.validate_current(index, new_current)
            if not valid_input:
                # Error message already shown in validate_current
                return
        except (tk.TclError, ValueError):
            self.log(f"Invalid manual current input for Cathode {['A', 'B', 'C'][index]}", LogLevel.WARNING)
            msgbox.showerror("Invalid Input", "Please enter a valid current value.")
            return

        prediction_success = self.update_predictions_from_current(index, new_current)
        if not prediction_success:
            self.log(f"Failed to predict output from current change for Cathode {['A', 'B', 'C'][index]}.", LogLevel.ERROR)

        set_success = self.update_output_from_current(index, new_current)
        if set_success:
            self.heater_current_vars[index].set(f"{new_current:.2f}")
            setattr(self, f"last_set_current_{index}", new_current)
            self.current_set[index] = True
        else:
            self.log(f"Failed to set manual current for Cathode {['A', 'B', 'C'][index]}.", LogLevel.ERROR)

    def handle_voltage_entry_set(self, index, voltage_entry):
        """
        Handle the Set button for the heater voltage entry.

        Args:
            index (int): Cathode index (0-2).
            voltage_entry (ttk.Entry): Entry widget containing the requested heater voltage.

        Clears the voltage goal when the entry is empty. Otherwise validates the
        entered voltage, updates predictions, and applies the requested output.
        """
        # Check for active ramping
        if self.is_ramping(index):
            self.log(f"Cannot set manual voltage for Cathode {['A', 'B', 'C'][index]} while ramping is enabled.", LogLevel.WARNING)
            msgbox.showwarning('Ramp in progress','Please wait for the ramp to finish or press STOP RAMP.') # add option in msg box to stop ramp
            return

        try:
            raw_value = str(voltage_entry.get()).strip()
            if raw_value == "":
                # Treat empty entry as a user request to clear the voltage goal.
                self.user_set_voltages[index] = None
                self.voltage_set[index] = False
                self.heater_voltage_vars[index].set('--')
                self.sent_heater_voltage_vars[index].set('--')
                self.predicted_heater_voltage_vars[index].set('--')
                self.log(f"Cleared voltage goal for Cathode {['A', 'B', 'C'][index]}", LogLevel.INFO)
                self.refresh_predictions(index)
                return

            new_voltage = float(raw_value)
            valid_input = self.validate_voltage(index, new_voltage)
            if not valid_input:
                # Error message already shown in validate_voltage
                return
        except (tk.TclError, ValueError):
            self.log(f"Invalid manual voltage input for Cathode {['A', 'B', 'C'][index]}", LogLevel.WARNING)
            msgbox.showerror("Invalid Input", "Please enter a valid voltage value.")
            return

        prediction_success = self.update_predictions_from_voltage(index, new_voltage)
        if not prediction_success:
            self.log(f"Failed to predict output from voltage change for Cathode {['A', 'B', 'C'][index]}.", LogLevel.ERROR)

        set_success = self.update_output_from_voltage(index, new_voltage)
        if set_success:
            self.heater_voltage_vars[index].set(f"{new_voltage:.2f}")
            setattr(self, f'last_set_voltage_{index}', new_voltage)
            self.voltage_set[index] = True
        else:
            self.log(f"Failed to set manual voltage for Cathode {['A', 'B', 'C'][index]}.", LogLevel.ERROR)

    def adjust_current(self, index: int, delta: float) -> None:
        """
        Increment / decrement the *requested* heater current by *delta* amps
        and push the change through the same pathway used for manual entry.
        Parameters
        ----------
        index : int
            Cathode index 0-2  (A, B, C).
        delta : float
            +0.01 → raise 10 mA   |   -0.01 → lower 10 mA.
        """
        # Check for active ramping
        if self.is_ramping(index):
                self.log(f"Cannot set manual current for Cathode {['A', 'B', 'C'][index]} while ramping is enabled.", LogLevel.WARNING)
                msgbox.showwarning('Ramp in progress','Please wait for the ramp to finish or press STOP RAMP.') # add option in msg box to stop ramp
                return
        # Pull whatever text is currently shown under “Set Heater (A)”.
        try:
            raw = self.heater_current_vars[index].get()
            current_a = float(raw)
        except (tk.TclError, ValueError):                       # label still ‘--’ or non-numeric
            current_a = 0.0

        new_current = round(current_a + delta, 2)      # keep two decimals for UI

        # Guard-rails
        valid_input = self.validate_current(index, new_current)
        if not valid_input:
            # Error message already shown in validate_current
            return

        prediction_success = self.update_predictions_from_current(index, new_current)
        if not prediction_success:
            self.log(f"Failed to predict output from current change for Cathode {['A', 'B', 'C'][index]}.", LogLevel.ERROR)

        set_success = self.update_output_from_current(index, new_current)
        if set_success:
            self.heater_current_vars[index].set(f"{new_current:.2f}")
            setattr(self, f"last_set_current_{index}", new_current)
            self.current_set[index] = True
        else:
            self.log(f"Failed to set manual current for Cathode {['A', 'B', 'C'][index]}.", LogLevel.ERROR)

    def adjust_voltage(self, index: int, delta: float) -> None:
        """
        Increment / decrement the *requested* heater voltage by *delta* volts
        and push the change through the same pathway used for manual entry.
        Parameters
        ----------
        index : int
            Cathode index 0-2  (A, B, C).
        delta : float
            +0.02 → raise 20 mV   |   -0.02 → lower 20 mV.
        """
        # Check for active ramping
        if self.is_ramping(index):
                self.log(f"Cannot set manual voltage for Cathode {['A', 'B', 'C'][index]} while ramping is enabled.", LogLevel.WARNING)
                msgbox.showwarning('Ramp in progress','Please wait for the ramp to finish or press STOP RAMP.') # add option in msg box to stop ramp
                return

        # Pull whatever text is currently shown under “Set Heater (V)”.
        try:
            raw = self.heater_voltage_vars[index].get()
            current_voltage = float(raw)
        except (tk.TclError, ValueError):                       # label still ‘--’ or non-numeric
            current_voltage = 0.0

        new_voltage = round(current_voltage + delta, 2)      # keep two decimals for UI

        # Guard-rails
        valid_input = self.validate_voltage(index, new_voltage)
        if not valid_input:
            # Error message already shown in validate_voltage
            return

        prediction_success = self.update_predictions_from_voltage(index, new_voltage)
        if not prediction_success:
            self.log(f"Failed to predict output from voltage change for Cathode {['A', 'B', 'C'][index]}.", LogLevel.ERROR)

        set_success = self.update_output_from_voltage(index, new_voltage)
        if set_success:
            self.heater_voltage_vars[index].set(f"{new_voltage:.2f}")
            setattr(self, f'last_set_voltage_{index}', new_voltage)
            self.voltage_set[index] = True
        else:
            self.log(f"Failed to set manual voltage for Cathode {['A', 'B', 'C'][index]}.", LogLevel.ERROR)

    def update_predictions_from_current(self, index, current):
        """
        Calculate and update predicted values based on a manually set current.

        Args:
            index (int): Index of cathode (0-2)
            current (float): Manually entered current value

        Returns:
            bool: True if update successful, False if failed
        """
        try:
            # If voltage is set we expect one value to limit the other
            if self.voltage_set[index]:
                limited_voltage = self._voltage_for_current(index, current)
                limited_current = self._current_for_voltage(index, self.user_set_voltages[index])
                if limited_voltage is None or limited_current is None:
                    # no data in LUT, return to update output without predictions
                    self.clear_prediction_variables(index)
                    return False

                if current >= limited_current:
                    # Current is limited by voltage and will not reach full set value
                    pred_heater_current = limited_current
                    pred_heater_voltage = self.user_set_voltages[index]
                    controlling_mode = "voltage"
                else:
                    # Voltage is potentially limited by current
                    pred_heater_current = current
                    pred_heater_voltage = min(self.user_set_voltages[index], limited_voltage)
                    controlling_mode = "current"
            else:
                # If no heater voltage is set we will predict the voltage produced by the new current and set it on the power supply
                pred_heater_voltage = self._voltage_for_current(index, current)
                pred_heater_current = current
                controlling_mode = "current"

            if pred_heater_voltage is None:
                self.clear_prediction_variables(index)
                self.log(
                    f"No lookup table voltage available at {current:.2f}A for Cathode {['A', 'B', 'C'][index]}",
                    LogLevel.WARNING,
                )
                return False

            # Predict beam current from the new voltage; may be reworked to use current for greater accuracy
            _,_, pred_beam_current = self.emission_cur_vlt_converter(
                index,
                pred_heater_voltage,
                target_heater_current=pred_heater_current,
                controlling_mode=controlling_mode,
            )

            # Check that LUT returned values, if not then reset predicted values
            if pred_beam_current == -1:
                self.clear_prediction_variables(index)
                self.log(f"No lookup table data available at {current:.2f}A for Cathode {['A', 'B', 'C'][index]}", LogLevel.WARNING)
                return False

            # Calculate dependent variables - beam_current is what hits the target, emission is total
            ideal_emission_current = pred_beam_current / self.BEAM_CURRENT_FRACTION_OF_EMISSION  # Convert beam current to emission current
            predicted_grid_current = 0.28 * ideal_emission_current

            # Update GUI with new values
            self.predicted_heater_current_vars[index].set(f'{pred_heater_current:.2f} A')
            self.predicted_heater_voltage_vars[index].set(f'{pred_heater_voltage:.2f} V')
            # Publish the derived emission value for both display and dashboard limit checks.
            self._set_predicted_emission_current_ma(index, ideal_emission_current)
            self.predicted_grid_current_vars[index].set(f'{predicted_grid_current:.2f} mA')
            if (
                self._is_above_lut_domain(index, pred_heater_current, "heater_current", "voltage")
                or self._is_above_lut_domain(index, pred_heater_voltage, "voltage", "beam_current")
            ):
                temperature_prediction = self._estimate_mode_aware_temperature(
                    index,
                    pred_heater_voltage,
                    pred_heater_current,
                    controlling_mode,
                )
                temp_k = (
                    temperature_prediction["temperature_k"]
                    if temperature_prediction is not None
                    else None
                )
                self.predicted_temperature_vars[index].set(f'{temp_k - 273.15:.0f} C' if temp_k is not None else '--')
            else:
                self.predicted_temperature_vars[index].set('--')

            return True

        except ValueError as e:
            self.clear_prediction_variables(index)
            self.log(f"Error processing manual current setting: {str(e)}", LogLevel.ERROR)
            return False
        except Exception as e:
            self.clear_prediction_variables(index)
            self.log(f"Unexpected error while processing manual current setting: {str(e)}", LogLevel.ERROR)
            return False

    def update_predictions_from_voltage(self, index, voltage):
        """
        Calculate and update predicted values based on a manually set voltage.

        Args:
            index (int): Index of cathode (0-2)
            voltage (float): Manually entered voltage value

        Returns:
            bool: True if update successful, False if failed
        """
        try:
            # If current is set we expect one value to limit the other
            if self.current_set[index]:
                limited_voltage = self._voltage_for_current(index, self.user_set_currents[index])
                limited_current = self._current_for_voltage(index, voltage)
                if limited_voltage is None or limited_current is None:
                    # no data in LUT, return to update output without predictions
                    self.clear_prediction_variables(index)
                    return False

                if voltage >= limited_voltage:
                    # Voltage is limited by current and will not reach full set value
                    pred_heater_voltage = limited_voltage
                    pred_heater_current = self.user_set_currents[index]
                    controlling_mode = "current"
                else:
                    # Current is potentially limited by voltage
                    pred_heater_voltage = voltage
                    pred_heater_current = min(self.user_set_currents[index], limited_current)
                    controlling_mode = "voltage"
            else:
                # If no heater current is set we will predict the current produced by the new voltage and set it on the power supply
                pred_heater_current = self._current_for_voltage(index, voltage)
                pred_heater_voltage = voltage
                controlling_mode = "voltage"

            if pred_heater_current is None or pred_heater_voltage is None:
                self.clear_prediction_variables(index)
                self.log(
                    f"No lookup table current available at {voltage:.2f}V for Cathode {['A', 'B', 'C'][index]}",
                    LogLevel.WARNING,
                )
                return False

            # Predict beam current from the new voltage; may be reworked to use current for greater accuracy
            _,_, pred_beam_current = self.emission_cur_vlt_converter(
                index,
                pred_heater_voltage,
                target_heater_current=pred_heater_current,
                controlling_mode=controlling_mode,
            )

            # Check that LUT returned values, if not then reset predicted values
            if pred_beam_current == -1:
                self.clear_prediction_variables(index)
                self.log(f"No lookup table data available at {voltage:.2f}V for Cathode {['A', 'B', 'C'][index]}", LogLevel.WARNING)
                return False

            # Calculate dependent variables - beam_current is what hits the target, emission is total
            ideal_emission_current = pred_beam_current / self.BEAM_CURRENT_FRACTION_OF_EMISSION  # Convert beam current to emission current
            predicted_grid_current = 0.28 * ideal_emission_current

            # Update GUI with new values
            self.predicted_heater_current_vars[index].set(f'{pred_heater_current:.2f} A')
            self.predicted_heater_voltage_vars[index].set(f'{pred_heater_voltage:.2f} V')
            # Publish the derived emission value for both display and dashboard limit checks.
            self._set_predicted_emission_current_ma(index, ideal_emission_current)
            self.predicted_grid_current_vars[index].set(f'{predicted_grid_current:.2f} mA')
            if (
                self._is_above_lut_domain(index, pred_heater_voltage, "voltage", "beam_current")
                or self._is_above_lut_domain(index, pred_heater_current, "heater_current", "voltage")
            ):
                temperature_prediction = self._estimate_mode_aware_temperature(
                    index,
                    pred_heater_voltage,
                    pred_heater_current,
                    controlling_mode,
                )
                temp_k = (
                    temperature_prediction["temperature_k"]
                    if temperature_prediction is not None
                    else None
                )
                self.predicted_temperature_vars[index].set(f'{temp_k - 273.15:.0f} C' if temp_k is not None else '--')
            else:
                self.predicted_temperature_vars[index].set('--')

            return True

        except Exception as e:
            self.clear_prediction_variables(index)
            self.log(f"Error processing manual voltage setting: {str(e)}", LogLevel.ERROR)
            return False

    def _current_for_voltage(self, index: int, voltage: float):
        """Return heater current for voltage using LUT interpolation, then ES440 above-LUT model."""
        heater_current = self._interpolate_lut_value(index, voltage, "voltage", "heater_current")
        if heater_current is not None:
            return heater_current
        if self._is_above_lut_domain(index, voltage, "voltage", "heater_current"):
            return self._estimate_heater_current_from_voltage_model(index, voltage)
        return None

    def _voltage_for_current(self, index: int, current: float):
        """Return heater voltage for current using LUT interpolation, then ES440 above-LUT model."""
        heater_voltage = self._interpolate_lut_value(index, current, "heater_current", "voltage")
        if heater_voltage is not None:
            return heater_voltage
        if self._is_above_lut_domain(index, current, "heater_current", "voltage"):
            return self._estimate_heater_voltage_from_current_model(index, current)
        return None

    def emission_cur_vlt_converter(
        self,
        index,
        val,
        target_heater_current=None,
        controlling_mode=None,
    ):
        """
        Convert between voltage and current using the DataFrame lookup.

        LUT data is treated as a function for voltage->(heater current, beam current)
        lookups. For a given voltage, there must be exactly one output pair.
        Above the LUT voltage/current domain, beam current falls back to a
        Richardson-Dushman estimate based on the ES440 temperature model.

        Args:
            index (int): Index of the cathode (0-2)
            val (float): Input value (voltage or current)
            target_heater_current (float | None): Resolved heater current from
                the active setpoint path. Used by the above-LUT Richardson
                fallback because temperature is estimated from heater current.
            controlling_mode (str | None): Binding physical constraint, either
                ``current`` or ``voltage``. Selects the dataset correction used
                by the outside-LUT temperature model.

        Returns:
            tuple: (heater_voltage, heater_current, beam_current)
        """
        if isinstance(self.lookup_table_setting[index], pd.DataFrame):
            above_voltage_lut = self._is_above_lut_domain(index, val, "voltage", "beam_current")
            above_current_lut = (
                target_heater_current is not None
                and self._is_above_lut_domain(index, target_heater_current, "heater_current", "voltage")
            )
            reason_parts = []
            if above_voltage_lut:
                reason_parts.append("heater voltage above LUT")
            if above_current_lut:
                reason_parts.append("heater current above LUT")
            reason = " and ".join(reason_parts) if reason_parts else "outside LUT"
            if above_voltage_lut or above_current_lut:
                fallback = self._richardson_fallback_beam_current_ma(
                    index,
                    val,
                    target_heater_current=target_heater_current,
                    controlling_mode=controlling_mode,
                )
                if fallback is not None:
                    self._log_richardson_fallback_prediction(index, val, fallback, reason)
                    return (
                        float(val),
                        float(fallback["heater_current"]),
                        float(fallback["beam_current_ma"]),
                    )

            heater_current = self._interpolate_lut_value(index, val, "voltage", "heater_current")
            beam_current = self._interpolate_lut_value(index, val, "voltage", "beam_current")
            if heater_current is None or beam_current is None:
                fallback = self._richardson_fallback_beam_current_ma(
                    index,
                    val,
                    target_heater_current=target_heater_current,
                    controlling_mode=controlling_mode,
                )
                if fallback is not None:
                    self._log_richardson_fallback_prediction(index, val, fallback, reason)
                    return (
                        float(val),
                        float(fallback["heater_current"]),
                        float(fallback["beam_current_ma"]),
                    )
                return (val, -1, -1)
            return (float(val), float(heater_current), float(beam_current))
        else:
            self.log("Lookup table not properly configured as DataFrame", LogLevel.ERROR)
            return (val, -1, -1)
        
    def update_output_from_current(self, index:int, new_current:float):
        """
        Updates the set current on the power supply. Assumes guard rails are checked prior to function call.
        Args:
            index(int): identifies correct power supply
            new_current(float): new target heater current to be set
        Returns:
            (bool): True is success, False if failed
        """
        try:

            if not self.power_supplies_initialized or not self.power_supplies:
                self.log("Power supplies not properly initialized or list is empty.", LogLevel.ERROR)
                return

            self.user_set_currents[index] = new_current
            sent_current_callback = lambda sent_value, i=index: self.parent.after(0, lambda idx=i, val=sent_value: self._update_sent_current_display(idx, val))
            sent_voltage_callback = lambda sent_value, i=index: self.parent.after(0, lambda idx=i, val=sent_value: self._update_sent_voltage_display(idx, val))

            # If the setup step before a cross-mode ramp fails, force the output off
            # through the driver's unconditional shutoff path.
            # Set current directly if output enabled
            if self.toggle_states[index]:
                if self.ramp_status[index] and self.ramp_control_mode[index] == "current":
                    # Ramp Current mode
                    ramp_started = self.power_supplies[index].ramp_current(
                        new_current,
                        step_size = self.curr_slew_rate[index],
                        step_delay = 1.0,
                        preset=3,
                        callback=lambda ok, i=index: self.parent.after(0, lambda idx=i, success=ok: self.handle_ramp_result(idx, success)),
                        sent_callback=sent_current_callback
                    )
                    if not ramp_started:
                        self.log(f"Failed to start current ramp for Cathode {['A', 'B', 'C'][index]}", LogLevel.ERROR)
                        return False
                    self.on_ramp_start(index)
                    self.current_set[index] = True
                elif self.ramp_status[index] and self.ramp_control_mode[index] == "voltage":
                    # Ramp Voltage Mode
                    #Immediate set new current
                    if not self.power_supplies[index].set_current(3, new_current, sent_callback=sent_current_callback):
                        # Log, disable output, and prevent ramp operation
                        self.log(f"Failed to set current for Cathode {['A', 'B', 'C'][index]} power supply prior to voltage ramp", LogLevel.ERROR)
                        self.power_supplies[index].disable_output()
                        self.toggle_states[index] = False
                        self.toggle_buttons[index].config(image=self.toggle_off_image)
                        return

                    # Ramp Voltage
                    ramp_started = self.power_supplies[index].ramp_voltage(
                        self.user_set_voltages[index],
                        step_size = self.vlt_slew_rate[index],
                        step_delay = 1.0,
                        preset=3,
                        callback=lambda ok, i=index: self.parent.after(0, lambda idx=i, success=ok: self.handle_ramp_result(idx, success)),
                        sent_callback=sent_voltage_callback
                    )
                    if not ramp_started:
                        self.log(f"Failed to start voltage ramp for Cathode {['A', 'B', 'C'][index]}", LogLevel.ERROR)
                        return False
                    self.on_ramp_start(index)
                    self.voltage_set[index] = True
                else: # Immediate set
                    if not self.power_supplies[index].set_current(3, new_current, sent_callback=sent_current_callback):
                        self.log(f"Failed to set current for Cathode {['A', 'B', 'C'][index]}", LogLevel.ERROR)
                        return
                    self.current_set[index] = True
            self.log(f"Set Cathode {['A', 'B', 'C'][index]} power supply to {new_current:.2f}A", LogLevel.INFO)

            return True
        except Exception as e:
            self.log(f"Error processing manual voltage setting: {str(e)}", LogLevel.ERROR)
            self.reset_related_variables(index)
            return False

    def update_output_from_voltage(self, index: int, new_voltage:float):
        """
        Updates the set voltage on the power supply. Assumes guard rails are checked prior to function call.
        Args:
            index(int): identifies correct power supply
            new_voltage(float): new target heater voltage to be set
        Returns:
            (bool): True is success, False if failed
        """
        try:

            if not self.power_supplies_initialized or not self.power_supplies:
                self.log("Power supplies not properly initialized or list is empty.", LogLevel.ERROR)
                return


            self.user_set_voltages[index] = new_voltage
            sent_current_callback = lambda sent_value, i=index: self.parent.after(0, lambda idx=i, val=sent_value: self._update_sent_current_display(idx, val))
            sent_voltage_callback = lambda sent_value, i=index: self.parent.after(0, lambda idx=i, val=sent_value: self._update_sent_voltage_display(idx, val))

            # If the setup step before a cross-mode ramp fails, force the output off
            # through the driver's unconditional shutoff path.
            # Set voltage directly if output enabled
            if self.toggle_states[index]:
                if self.ramp_status[index] and self.ramp_control_mode[index] == "voltage":
                    # Ramp Voltage mode
                    ramp_started = self.power_supplies[index].ramp_voltage(
                        new_voltage,
                        step_size = self.vlt_slew_rate[index],
                        step_delay = 1.0,
                        preset=3,
                        callback=lambda ok, i=index: self.parent.after(0, lambda idx=i, success=ok: self.handle_ramp_result(idx, success)),
                        sent_callback=sent_voltage_callback
                    )
                    if not ramp_started:
                        self.log(f"Failed to start voltage ramp for Cathode {['A', 'B', 'C'][index]}", LogLevel.ERROR)
                        return False
                    self.on_ramp_start(index)
                    self.voltage_set[index] = True
                elif self.ramp_status[index] and self.ramp_control_mode[index] == "current":
                    # Ramp Current mode
                    # Immediate set new voltage
                    if not self.power_supplies[index].set_voltage(3, new_voltage, sent_callback=sent_voltage_callback):
                        # Log, disable output, and prevent ramp operation
                        self.log(f"Failed to set voltage for Cathode {['A', 'B', 'C'][index]} power supply prior to current ramp", LogLevel.ERROR)
                        self.power_supplies[index].disable_output()
                        self.toggle_states[index] = False
                        self.toggle_buttons[index].config(image=self.toggle_off_image)
                        return

                    # Ramp Current
                    ramp_started = self.power_supplies[index].ramp_current(
                        self.user_set_currents[index],
                        step_size = self.curr_slew_rate[index],
                        step_delay = 1.0,
                        preset=3,
                        callback=lambda ok, i=index: self.parent.after(0, lambda idx=i, success=ok: self.handle_ramp_result(idx, success)),
                        sent_callback=sent_current_callback
                    )
                    if not ramp_started:
                        self.log(f"Failed to start current ramp for Cathode {['A', 'B', 'C'][index]}", LogLevel.ERROR)
                        return False
                    self.on_ramp_start(index)
                    self.current_set[index] = True
                else: # Immediate set
                    if not self.power_supplies[index].set_voltage(3, new_voltage, sent_callback=sent_voltage_callback):
                        self.log(f"Failed to set voltage for Cathode {['A', 'B', 'C'][index]}", LogLevel.ERROR)
                        return
                    self.voltage_set[index] = True
            self.log(f"Set Cathode {['A', 'B', 'C'][index]} power supply to {new_voltage:.2f}V", LogLevel.INFO)

            return True
        except Exception as e:
            self.log(f"Error processing manual voltage setting: {str(e)}", LogLevel.ERROR)
            self.reset_related_variables(index)
            return False
        
    def get_ocp(self, index):
        '''
        Get the current over-current protection setting.
        Args:
            index (int): Index of the power supply (0-2)
            
        Returns:
            float or None: Current OCP setting in amps, None if retrieval fails
        '''
        try: 
            ocp = self.power_supplies[index].get_over_current_protection()
            if ocp is not None:
                return ocp
            else:
                self.log(f"Failed to get OCP for Cathode {['A', 'B', 'C'][index]}", LogLevel.ERROR)
                return None
        except Exception as e:
            self.log(f"Error getting OCP for Cathode {['A', 'B', 'C'][index]}: {str(e)}", LogLevel.ERROR)
            return None
        
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
        if self._logging_suppressed():
            return
        if not self.logger:
            return

        # Tkinter-backed loggers must only be touched from the main GUI thread.
        # Queue logs from the 9104 poller/background paths and flush them from update_data().
        if threading.get_ident() == self._main_thread_ident:
            self.flush_queued_logs()
            self.logger.log(message, level, tag="CCS")
        else:
            self._enqueue_worker_log(message, level)

    def _enqueue_worker_log(self, message, level):
        """Queue one worker log without blocking if the UI drain is stalled."""
        try:
            self._log_queue.put_nowait((message, level))
            return
        except Full:
            pass

        try:
            self._log_queue.get_nowait()
            self._record_dropped_worker_log()
        except Empty:
            pass

        try:
            self._log_queue.put_nowait((message, level))
        except Full:
            self._record_dropped_worker_log()
            pass

    def _record_dropped_worker_log(self):
        with self._dropped_worker_log_lock:
            self._dropped_worker_log_count += 1

    def _pop_dropped_worker_log_count(self):
        with self._dropped_worker_log_lock:
            count = self._dropped_worker_log_count
            self._dropped_worker_log_count = 0
        return count

    def flush_queued_logs(self, max_messages=200):
        """Flush queued worker-thread log messages on the calling thread."""
        if not self.logger:
            return
        if self._logging_suppressed():
            self._pop_dropped_worker_log_count()
            while True:
                try:
                    self._log_queue.get_nowait()
                except Empty:
                    break
            return

        dropped_count = self._pop_dropped_worker_log_count()
        if dropped_count:
            self.logger.log(
                f"Dropped {dropped_count} queued CCS worker log message(s) because the log queue was full.",
                LogLevel.WARNING,
                tag="CCS",
            )

        processed = 0
        while processed < max_messages:
            try:
                message, level = self._log_queue.get_nowait()
            except Empty:
                break
            self.logger.log(message, level, tag="CCS")
            processed += 1

    # Voltage input validation
    def validate_voltage(self, index:int, new_voltage: float):
        """
        Checks new heater voltage is non-negative and does not exceed the OVP.
        
        """
        ovp = self.get_ovp(index)

        if ovp is None:
            self.log(f"Cannot validate voltage for Cathode {['A','B','C'][index]}: OCP unavailable (power supply disconnected or GOCP failed).", LogLevel.ERROR)
            return False
        
        if new_voltage is None or new_voltage < 0:
            self.log(f"Invalid voltage request for Cathode {['A', 'B', 'C'][index]}: requested voltage cannot be negative.", LogLevel.WARNING)
            msgbox.showwarning("Invalid Input", "Requested voltage cannot be negative.")
            return False
        
        remainder = new_voltage % 0.02
        if abs(remainder) > 1e-10 and abs(remainder - 0.02) > 1e-10:
            self.log(f"Calculated voltage ({new_voltage:.2f}V) is not divisible by 0.02 for Cathode {['A', 'B', 'C'][index]}. Aborting.", LogLevel.WARNING)
            msgbox.showwarning("Invalid Voltage", f"The voltage entered ({new_voltage:.2f}V) is invalid. Please enter a voltage that is a multiple of 0.02V.")
            return False

        if new_voltage > ovp:
            self.log(f"Calculated voltage ({new_voltage:.2f}V) exceeds OVP ({ovp:.2f}V) for Cathode {['A', 'B', 'C'][index]}. Aborting.", LogLevel.WARNING)
            msgbox.showwarning("Voltage Exceeds OVP", f"The calculated voltage ({new_voltage:.2f}V) exceeds the current OVP setting ({ovp:.2f}V). Please adjust the OVP or choose a lower target current.")
            return False
        
        return True
    
    # Current input validation
    def validate_current(self, index:int, new_current: float):
        """
        Checks new heater current is non-negative and does not exceed the OCP.
        
        """
        ocp = self.get_ocp(index)

        if new_current is None or new_current < 0:
            self.log(f"Invalid current request for Cathode {['A', 'B', 'C'][index]}: requested current cannot be negative.", LogLevel.WARNING)
            msgbox.showwarning("Invalid Input", "Requested current cannot be negative.")
            return False
        
        if ocp is None:
            self.log(f"Cannot validate current for Cathode {['A','B','C'][index]}: OCP unavailable (power supply disconnected or GOCP failed).", LogLevel.ERROR)
            return False

        if new_current > ocp:
            self.log(f"Calculated current ({new_current:.2f}A) exceeds OCP ({ocp:.2f}A) for Cathode {['A', 'B', 'C'][index]}. Aborting.", LogLevel.WARNING)
            msgbox.showwarning("Current Exceeds OCP", f"The calculated current ({new_current:.2f}A) exceeds the current OCP setting ({ocp:.2f}A). Please adjust the OCP or choose a lower target current.")
            return False
        
        return True
    
    # Ramping helper methods for GUI state changes
    def set_output_button_state(self, index:int, state:str):
        """Enable or disable the output mode dropdown for one cathode."""
        if index < len(self.ramp_mode_dropdowns):
            dropdown_state = 'readonly' if state == 'normal' else 'disabled'
            self.ramp_mode_dropdowns[index].config(state=dropdown_state)

    def _refresh_heater_setpoint_controls(self, index: int):
        """Apply CCS availability and ramp mode to Set and +/- controls."""
        ready = (
            0 <= index < len(self.power_supply_status)
            and self.power_supply_status[index]
        )
        if not ready or self.is_ramping(index):
            self.set_text_set_buttons_state(index, 'disabled')
            self.set_curr_adjustment_buttons_state(index, 'disabled')
            self.set_vlt_adjustment_buttons_state(index, 'disabled')
            return

        self.set_text_set_buttons_state(index, 'normal')
        if self.ramp_status[index] and self.ramp_control_mode[index] == "current":
            self.set_curr_adjustment_buttons_state(index, 'disabled')
            self.set_vlt_adjustment_buttons_state(index, 'normal')
        elif self.ramp_status[index] and self.ramp_control_mode[index] == "voltage":
            self.set_vlt_adjustment_buttons_state(index, 'disabled')
            self.set_curr_adjustment_buttons_state(index, 'normal')
        else:
            self.set_curr_adjustment_buttons_state(index, 'normal')
            self.set_vlt_adjustment_buttons_state(index, 'normal')

    def _update_sent_current_display(self, index: int, sent_current: float):
        if index < len(self.sent_heater_current_vars):
            self.sent_heater_current_vars[index].set(f"{sent_current:.2f}")

    def _update_sent_voltage_display(self, index: int, sent_voltage: float):
        if index < len(self.sent_heater_voltage_vars):
            self.sent_heater_voltage_vars[index].set(f"{sent_voltage:.2f}")

    def is_ramping(self, index:int) -> bool:
        ps = self.power_supplies[index] if index < len(self.power_supplies) else None
        return bool(ps and ps.ramp_thread and ps.ramp_thread.is_alive())

    def on_ramp_start(self, index:int):
        self.stop_ramp_buttons[index]['state'] = 'normal'
        self.stop_ramp_buttons[index].config(style='StopActive.TButton')
        self.set_output_button_state(index, 'disabled')
        self.set_vlt_adjustment_buttons_state(index, 'disabled')
        self.set_curr_adjustment_buttons_state(index, 'disabled')
        self.set_text_set_buttons_state(index, 'disabled')

    def on_ramp_complete(self, index:int):
        self.stop_ramp_buttons[index]['state'] = 'disabled'
        self.stop_ramp_buttons[index].config(style='StopInactive.TButton')
        self.set_output_button_state(index, 'normal')
        self._refresh_heater_setpoint_controls(index)

    def handle_ramp_result(self, index: int, ok: bool):
        self.on_ramp_complete(index)
        if ok:
            return

        ps = self.power_supplies[index] if index < len(self.power_supplies) else None
        if ps and ps.stop_event.is_set():
            return

        cathode = ['A', 'B', 'C'][index]
        self.log(
            f"Ramp for Cathode {cathode} aborted before reaching the requested setpoint. "
            "Verify the live readback before continuing.",
            LogLevel.WARNING
        )

    def stop_ramp(self, index:int):
        """
        UI callback - user pressed STOP RAMP.
        """
        ps = self.power_supplies[index]
        was_ramping = self.is_ramping(index)
        if ps:
            ps.stop_ramp()
        self.log(f'STOP RAMP pressed for Cathode {["A","B","C"][index]}', LogLevel.INFO)
        if not was_ramping:
            self.on_ramp_complete(index)

    def set_curr_adjustment_buttons_state(self, index: int, state: str):
        """Enable or disable the current +/- adjustment buttons for one cathode."""
        if index < len(self.curr_adjustment_buttons):
            for btn in self.curr_adjustment_buttons[index]:
                btn.config(state=state)

    def set_vlt_adjustment_buttons_state(self, index: int, state: str):
        """Enable or disable the current +/- adjustment buttons for one cathode."""  
        if index < len(self.vlt_adjustment_buttons):
            for btn in self.vlt_adjustment_buttons[index]:
                btn.config(state=state)

    def set_text_set_buttons_state(self, index:int, state: str):
        """Enable or disable textbox set buttons during ramp operations on one cathode."""
        if index < len(self.set_button_states):
            for btn in self.set_button_states[index]:
                btn.config(state=state)

    def close_com_ports(self):
        """
        Disables all power supply outputs and closes serial connections upon quitting the application.
        """
        # Stop Tk callbacks and the 9104 readback poller before touching serial
        # ports. Polling uses the same PowerSupply9104.serial_lock as commands,
        # so shutdown uses bounded waits below instead of blocking indefinitely.
        self.cancel_updates()
        if not self.stop_power_supply_polling():
            self.log("9104 polling thread did not stop before shutdown; continuing with bounded serial close", LogLevel.WARNING)

        if hasattr(self, 'power_supplies') and self.power_supplies:
            for i, ps in enumerate(self.power_supplies):
                try:
                    if hasattr(ps, 'stop_ramp'):
                        ps.stop_ramp()
                    if hasattr(ps, 'disable_output'):
                        # Try to turn output off, but continue closing if a dead serial transaction owns the lock.
                        self.log(f"Disabling output on cathode {chr(65 + i)} power supply", LogLevel.INFO)
                        ps.disable_output()
                except Exception as e:
                    self.log(f"Error disabling output on cathode {chr(65 + i)}: {e}", LogLevel.ERROR)
                if hasattr(ps, 'close'):
                    try:
                        ps.close(ramp_join_timeout=2.0)
                    except TypeError:
                        ps.close()

        # Local state must reflect that no supply is command-ready after the handles are closed.
        self.power_supplies_initialized = False
        self._reset_power_supply_runtime_state()
        for i in range(3):
            self._set_power_supply_command_ready(i, False)

        if hasattr(self, 'temperature_controller') and self.temperature_controller:
            try:
                closed = self.temperature_controller.stop_reading()
                if not closed:
                    self.log("Temperature controller did not close cleanly during shutdown", LogLevel.WARNING)
                self.temp_controllers_connected = False
                self.temperature_valid_connections = [False, False, False]
            except Exception as e:
                self.log(f"Error cleaning up existing controller: {str(e)}", LogLevel.ERROR)
