import time
import tkinter as tk
from tkinter import ttk
from typing import Optional, Dict
import os
import sys
import math
import csv

from instrumentctl.E5CN_modbus.E5CN_modbus import E5CNModbus
from utils import LogLevel

# Check for numpy availability
try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False

# Check for matplotlib availability
try:
    import matplotlib.pyplot as plt
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    _HAS_MATPLOTLIB = True
except ImportError:
    _HAS_MATPLOTLIB = False

def resource_path(relative_path):
    """Get absolute path to resource for PyInstaller."""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


class BeamPulseSubsystem:
    """Beam Pulse subsystem (BCON) with GUI interface and physics calculations.

    This class provides the GUI interface and high-level control logic for the beam
    pulse control system with ENERGY-AWARE LUT CALIBRATION. Hardware communication
    uses the project's E5CNModbus wrapper for serial/Modbus I/O.

    Contract:
      - Inputs: E5CNModbus-based driver instance for hardware communication
      - Outputs: GUI controls and physics calculations (B-field, power, deflection)
      - Error modes: hardware failures are handled by the underlying driver

    Physics calculations include B-field, power dissipation, beam deflection,
    and scan speed using empirical formulas and lookup tables.
    """

    # Physics constants for B-field and power calculations
    # B-field linear approximation constants (empirically derived)
    # Source: "2019-09-26 field measurements - 2 solenoids no covers.xlsx"
    # From "Avg" column at position 0 in "Coil A" and "Coil B" tabs
    # Measured at I = 1.6 A: B_center = 62.2 G, B_off-axis = 61.2 G
    B_FIELD_SLOPE_CENTER = 38.875      # G/A - for Beam B (center beam)
    B_FIELD_SLOPE_OFF_AXIS = 38.25     # G/A - for Beams A and C (off-axis)

    # Power calculation now uses empirical formula P = 14.810*I + 0.793
    # This constant kept for reference/legacy compatibility
    SOLENOID_RESISTANCE = 12.0         # ohms - LEGACY: no longer used in power calc

    # Register addresses for BCON hardware (see README.md for register map)

    def __init__(self, parent_frame=None, port=None, unit=1, baudrate=115200,
                 logger=None, debug: bool = False):
        """Create the BeamPulseSubsystem.

        Parameters:
            parent_frame: tkinter frame for GUI components (if None, no GUI created)
            port: Serial port for BCON hardware (e.g., 'COM3')
            unit: Modbus unit/slave address (default: 1)
            baudrate: Serial baudrate for Modbus RTU communication (default: 115200)
            logger: optional logger object compatible with utils.LogLevel
            debug: enable debug logs
        """
        self.parent_frame = parent_frame
        self.logger = logger
        self.debug = debug
        
        # Instantiate E5CNModbus driver if port is provided
        if port:
            from instrumentctl.E5CN_modbus.E5CN_modbus import E5CNModbus
            self.bcon_driver = E5CNModbus(
                port=port,
                unit=unit,
                baudrate=baudrate,
                timeout=1.0,
                debug=debug
            )
        else:
            self.bcon_driver = None

        # Initialize GUI variables only if GUI is being created
        if parent_frame:
            # GUI variables for controls
            self.wave_gen_enabled = tk.BooleanVar(value=False)
            self.wave_type = tk.StringVar(value="Sine")  # Default to Sine
            self.pulsing_behavior = tk.StringVar(value="DC")  # Default to DC mode
            self.frequency_hz = tk.DoubleVar(value=10.0)
            self.wave_amplitude = tk.DoubleVar(value=5.0)

            # Pulse duration variables for each beam (A, B, C)
            self.beam_a_duration = tk.DoubleVar(value=50.0)
            self.beam_b_duration = tk.DoubleVar(value=50.0)
            self.beam_c_duration = tk.DoubleVar(value=50.0)

            # Config tab variables
            self.deflection_lower_bound = tk.DoubleVar(value=-10.0)
            self.deflection_upper_bound = tk.DoubleVar(value=10.0)

            # Config tab variables
            self.frequency_lower_bound = tk.DoubleVar(value=0.0)
            self.frequency_upper_bound = tk.DoubleVar(value=45.0)
        else:
            # Non-GUI mode: use simple values
            self.wave_gen_enabled = False
            self.wave_type = "Sine"
            self.pulsing_behavior = "DC"
            self.frequency_hz = 10.0
            self.wave_amplitude = 5.0
            self.beam_a_duration = 50.0
            self.beam_b_duration = 50.0
            self.beam_c_duration = 50.0
            self.deflection_lower_bound = -10.0
            self.deflection_upper_bound = 10.0
            self.frequency_lower_bound = 0.0
            self.frequency_upper_bound = 45.0

        # Toggle state for wave gen
        self.wave_gen_toggle_state = False

        # Status indicators
        self.bcon_connection_status = False  # BCON connected status
        self.beams_armed_status = False  # Beams armed status

        # Beam on/off status for each beam (A, B, C)
        self.beam_on_status = [False, False, False]  # [Beam A, Beam B, Beam C]

        # Store references to duration spinboxes for enable/disable control
        self.duration_spinboxes = []

        # Beam position tracking for plotting
        self.beam_history = [[], [], []]  # [Beam A, Beam B, Beam C] - completed positions
        self.beam_current = [None, None, None]  # Current/projected positions
        self.beam_plot_objects = [[], [], []]  # Store plot objects for updating

        # Deflection stats variables
        if parent_frame:
            self.deflection_est = tk.DoubleVar(value=5.0)
            self.scan_speed_est = tk.DoubleVar(value=1.5)
            self.peak_bfield_est = tk.DoubleVar(value=28.0)  # Gauss
            self.power_est = tk.DoubleVar(value=150.0)
        else:
            self.deflection_est = 5.0
            self.scan_speed_est = 1.5
            self.peak_bfield_est = 28.0  # Gauss
            self.power_est = 150.0

        # Plot variables
        self._bp_fig = None
        self._bp_axes = None
        self._bp_canvas = None
        self._bp_stats = {}

        # Load toggle images if GUI is being created
        if parent_frame:
            try:
                self.toggle_on_image = tk.PhotoImage(file=resource_path("media/toggle_on.png"))
                self.toggle_off_image = tk.PhotoImage(file=resource_path("media/toggle_off.png"))
            except Exception as e:
                # Fallback if images can't be loaded
                self.toggle_on_image = None
                self.toggle_off_image = None
                if logger:
                    logger.log(f"Could not load toggle images: {e}", LogLevel.WARNING)

        # LUT Dataset variables
        if parent_frame:
            self.lut_dataset_var = tk.StringVar(value="None")
        else:
            self.lut_dataset_var = "None"
        self.lut_data = None

        # Deflection Stats LUT variables - two lookup tables, two formulas
        # ENERGY-AWARE LUT SYSTEM:
        # The deflection and scan speed LUTs are now energy-specific because
        # the same algorithm won't work if the e-beam is at 20 keV vs 50 keV.
        # Each energy level requires its own calibration data for accurate
        # deflection calculations.
        if parent_frame:
            self.beam_deflection_lut_var = tk.StringVar(value="None")
            self.scan_speed_lut_var = tk.StringVar(value="None")
        else:
            self.beam_deflection_lut_var = "None"
            self.scan_speed_lut_var = "None"

        # Stored LUT data for deflection stats (beam deflection and scan speed)
        # B-field and power are calculated using physics formulas and don't need LUTs
        self.beam_deflection_lut_data = None
        self.scan_speed_lut_data = None

        # Energy from currently selected LUT datasets (extracted from filenames)
        # These show which beam energy the selected LUT files were calibrated for
        if parent_frame:
            self.selected_deflection_energy = tk.DoubleVar(value=0.0)  # keV deflection
            self.selected_scan_speed_energy = tk.DoubleVar(value=0.0)   # keV scan speed
            # Current beam energy tracking (calculated from power supplies)
            # This displays the total beam energy from all power supply voltages
            # and validates that LUT data matches the current operating energy
            self.current_beam_energy_keV = tk.DoubleVar(value=0.0)
        else:
            self.selected_deflection_energy = 0.0  # keV deflection
            self.selected_scan_speed_energy = 0.0   # keV scan speed
            # Current beam energy tracking (calculated from power supplies)
            # This displays the total beam energy from all power supply voltages
            # and validates that LUT data matches the current operating energy
            self.current_beam_energy_keV = 0.0
        self.beam_energy_subsystem_ref = None  # Reference to beam energy subsystem for data access

        # Available energies for spinbox controls
        self.available_energies = []
        self.current_energy_index = 0

        # Shared energy variable for synchronization between tabs
        if parent_frame:
            self.shared_energy = tk.StringVar(value="20 keV")
        else:
            self.shared_energy = "20 keV"

        # Graph visibility control
        self.graph_history_visible = True

        # Dashboard integration callback
        self._dashboard_beam_callback = None

        # Hardware connection through BCON driver
        # Driver should be initialized externally and passed in

        # Create GUI if parent frame is provided
        if parent_frame:
            self.setup_ui()

    def setup_ui(self):
        """Create the user interface with Main and Config tabs."""
        # Create notebook for tabs
        self.notebook = ttk.Notebook(self.parent_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Create Main tab
        self.main_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.main_tab, text="Main")

        # Create Config tab
        self.config_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.config_tab, text="Config")

        # Setup Main tab content
        self.setup_main_tab()

        # Setup Config tab content
        self.setup_config_tab()

        # Start live monitoring of deflection stats (optional demo)
        # Remove this line if you don't want the demo animation
        self.start_deflection_stats_monitoring()

    def setup_main_tab(self):
        """Setup the Main tab with all the main controls and displays."""
        # Main container frame
        main_frame = ttk.Frame(self.main_tab, padding="5")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Top control row frame
        control_row = ttk.Frame(main_frame)
        control_row.pack(fill=tk.X, pady=(0, 5))

        # Create control columns with labels on top and controls below
        self.create_wave_gen_control(control_row, 0)
        self.create_wave_type_control(control_row, 1)
        self.create_pulsing_behavior_control(control_row, 2)
        self.create_frequency_control(control_row, 3)
        self.create_wave_amplitude_control(control_row, 4)
        self.create_bcon_connection_status(control_row, 5)

        # Configure column weights for responsive layout (now 6 columns)
        for i in range(6):
            control_row.grid_columnconfigure(i, weight=1)

        # Second control row for pulse duration controls
        pulse_row = ttk.Frame(main_frame)
        pulse_row.pack(fill=tk.X, pady=(0, 10))

        # Create pulse duration controls for beams A, B, C (centered with less spacing)
        # Use columns 1, 2, 3 with spacer columns 0 and 4 for centering
        self.create_beam_duration_control(pulse_row, 1, "Beam A Duration (ms)",
                                           self.beam_a_duration)
        self.create_beam_duration_control(pulse_row, 2, "Beam B Duration (ms)",
                                           self.beam_b_duration)
        self.create_beam_duration_control(pulse_row, 3, "Beam C Duration (ms)",
                                           self.beam_c_duration)

        # Configure column weights for pulse row (5 columns total)
        # Columns 0 and 4 are spacers with higher weight to center the controls
        pulse_row.grid_columnconfigure(0, weight=2)  # Left spacer
        pulse_row.grid_columnconfigure(1, weight=0)  # Beam A (no expansion)
        pulse_row.grid_columnconfigure(2, weight=0)  # Beam B (no expansion)
        pulse_row.grid_columnconfigure(3, weight=0)  # Beam C (no expansion)
        pulse_row.grid_columnconfigure(4, weight=2)  # Right spacer

        # Set initial state of frequency spinbox based on default wave type
        self.update_frequency_spinbox_state()

        # Bottom section with two columns: deflection stats and print bed plots
        bottom_frame = ttk.Frame(main_frame)
        bottom_frame.pack(fill=tk.BOTH, expand=True)

        # Left side - Deflection Stats (45% width - increased for table)
        deflection_frame = ttk.Frame(bottom_frame, width=180)  # Fixed width for table
        deflection_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 8))
        deflection_frame.pack_propagate(False)  # Maintain fixed width
        self.create_deflection_stats(deflection_frame)

        # Right side - Print Bed label and plots (55% width)
        plots_container = ttk.Frame(bottom_frame)
        plots_container.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(0, 0))

        # Print Bed label and Clear Graph button frame
        header_frame = ttk.Frame(plots_container)
        header_frame.pack(fill=tk.X, pady=(0, 10))

        # Left spacer to help center the title
        left_spacer = ttk.Frame(header_frame)
        left_spacer.pack(side=tk.LEFT, expand=True)

        # Print Bed label centered
        print_bed_label = ttk.Label(header_frame, text="Print Bed", font=("Arial", 10, "bold"))
        print_bed_label.pack(side=tk.LEFT)

        # Right spacer to balance the layout
        right_spacer = ttk.Frame(header_frame)
        right_spacer.pack(side=tk.LEFT, expand=True)

        # Clear Graph / Show All button on the far right
        self.clear_graph_button = ttk.Button(
            header_frame,
            text="Clear Graph",
            command=self.toggle_graph_visibility,
            width=12
        )
        self.clear_graph_button.pack(side=tk.RIGHT)

        # Plots frame
        plots_frame = ttk.Frame(plots_container)
        plots_frame.pack(fill=tk.BOTH, expand=True)

        # Create the plots
        self.create_plots(plots_frame)

        # Start BCON connection monitoring
        self.start_bcon_connection_monitoring()

    def start_bcon_connection_monitoring(self):
        """Start periodic monitoring of BCON connection status."""
        def check_connection():
            # Check if we have a BCON driver and if it's connected
            if self.bcon_driver:
                try:
                    # Use the BCON driver's connection status check
                    self.set_bcon_connection_status(
                        self.bcon_driver.is_connected())
                except Exception:
                    self.set_bcon_connection_status(False)
            else:
                # No BCON driver configured
                self.set_bcon_connection_status(False)

            # Schedule next check (every 5000ms = 5 seconds)
            if hasattr(self, 'parent_frame') and self.parent_frame:
                self.parent_frame.after(5000, check_connection)

        # Start the monitoring loop
        if hasattr(self, 'parent_frame') and self.parent_frame:
            self.parent_frame.after(1000, check_connection)  # Start after 1 second

    def setup_config_tab(self):
        """Setup the Config tab with deflection amplitude bounds settings."""
        # Main container frame (reduced padding)
        config_frame = ttk.Frame(self.config_tab, padding="5")  # Reduced padding
        config_frame.pack(fill=tk.BOTH, expand=True)

        # Title (smaller font and less padding)
        title_label = ttk.Label(config_frame, text="Deflection Configuration",
                               font=("Arial", 12, "bold"))  # Reduced font size
        title_label.pack(pady=(0, 5))  # Reduced padding

        # Deflection bounds frame (reduced padding)
        bounds_frame = ttk.LabelFrame(config_frame, text="Deflection Amplitude Bounds",
                                     padding="5", labelanchor="n")  # Reduced padding
        bounds_frame.pack(fill=tk.X, pady=(0, 5))  # Reduced spacing

        # Lower bound setting
        lower_frame = ttk.Frame(bounds_frame)
        lower_frame.pack(fill=tk.X, pady=2)  # Reduced padding

        ttk.Label(lower_frame, text="Lower Bound (A):", font=("Arial", 9)).pack(side=tk.LEFT)  # Smaller font
        self.lower_bound_spinbox = tk.Spinbox(
            lower_frame,
            from_=-50.0,
            to=50.0,
            increment=0.1,
            textvariable=self.deflection_lower_bound,  # Link to class variable
            width=8,
            format="%.1f"
        )
        self.lower_bound_spinbox.pack(side=tk.RIGHT)

        # Upper bound setting
        upper_frame = ttk.Frame(bounds_frame)
        upper_frame.pack(fill=tk.X, pady=2)  # Reduced padding

        ttk.Label(upper_frame, text="Upper Bound (A):", font=("Arial", 9)).pack(side=tk.LEFT)  # Smaller font
        self.upper_bound_spinbox = tk.Spinbox(
            upper_frame,
            from_=-50.0,
            to=50.0,
            increment=0.1,
            textvariable=self.deflection_upper_bound,  # Link to class variable
            width=8,
            format="%.1f"
        )
        self.upper_bound_spinbox.pack(side=tk.RIGHT)

        # Deflection Frequency bounds frame (reduced padding)
        frequency_frame = ttk.LabelFrame(config_frame, text="Deflection Frequency Bounds",
                                     padding="5", labelanchor="n")  # Reduced padding
        frequency_frame.pack(fill=tk.X, pady=(0, 5))  # Reduced spacing

        # Lower bound setting
        frequency_lower_frame = ttk.Frame(frequency_frame)
        frequency_lower_frame.pack(fill=tk.X, pady=2)  # Reduced padding

        ttk.Label(frequency_lower_frame, text="Lower Bound (Hz):", font=("Arial", 9)).pack(side=tk.LEFT)  # Smaller font
        self.frequency_lower_bound_spinbox = tk.Spinbox(
            frequency_lower_frame,
            from_=0.0,
            to=45.0,
            increment=0.1,
            textvariable=self.frequency_lower_bound,  # Link to class variable
            width=8,
            format="%.1f"
        )
        self.frequency_lower_bound_spinbox.pack(side=tk.RIGHT)

        # Upper bound setting
        frequency_upper_frame = ttk.Frame(frequency_frame)
        frequency_upper_frame.pack(fill=tk.X, pady=2)  # Reduced padding

        ttk.Label(frequency_upper_frame, text="Upper Bound (Hz):", font=("Arial", 9)).pack(side=tk.LEFT)  # Smaller font
        self.frequency_upper_bound_spinbox = tk.Spinbox(
            frequency_upper_frame,
            from_=0.0,
            to=45.0,
            increment=0.1,
            textvariable=self.frequency_upper_bound,  # Link to class variable
            width=8,
            format="%.1f"
        )
        self.frequency_upper_bound_spinbox.pack(side=tk.RIGHT)

        # Apply button (positioned above LUT configuration)
        apply_button = ttk.Button(config_frame, text="Apply Settings",
                                 command=self.apply_deflection_bounds)
        apply_button.pack(pady=(5, 0))

        # Status display
        self.config_status_label = ttk.Label(config_frame, text="Settings ready to apply",
                                           font=("Arial", 8), foreground="blue")
        self.config_status_label.pack(pady=(2, 5))

        # Deflection Stats LUT Configuration frame
        deflection_stats_lut_frame = ttk.LabelFrame(config_frame, text="Configure Deflection Stats LUTs",
                                                   padding="5", labelanchor="n")
        deflection_stats_lut_frame.pack(fill=tk.X, pady=(5, 0))

        # Create four rows for the four deflection stats LUTs
        self.create_deflection_stats_lut_dropdowns(deflection_stats_lut_frame)

    def apply_deflection_bounds(self):
        """Apply the deflection amplitude bounds settings."""
        try:
            lower_bound = float(self.lower_bound_spinbox.get())
            upper_bound = float(self.upper_bound_spinbox.get())
            frequency_lower_bound = float(self.frequency_lower_bound_spinbox.get())
            frequency_upper_bound = float(self.frequency_upper_bound_spinbox.get())

            # Validate bounds
            if lower_bound >= upper_bound:
                self.config_status_label.configure(text="Error: Lower bound must be less than upper bound",
                                                 foreground="red")
                return
            if frequency_lower_bound >= frequency_upper_bound:
                self.config_status_label.configure(text="Error: Frequency lower bound must be less than upper bound",
                                                 foreground="red")
                return

            # Store the bounds
            self.deflection_lower_bound.set(lower_bound)
            self.deflection_upper_bound.set(upper_bound)
            self.frequency_lower_bound.set(frequency_lower_bound)
            self.frequency_upper_bound.set(frequency_upper_bound)

            # Update status with compact display
            self.config_status_label.configure(
                text=(f"Applied: Amp={lower_bound:.1f}-{upper_bound:.1f}A, "
                      f"Freq={frequency_lower_bound:.1f}-{frequency_upper_bound:.1f}Hz"),
                foreground="green"
            )

            # Log the change
            self._log(f"Settings applied - Deflection bounds: "
                     f"{lower_bound:.1f}-{upper_bound:.1f}A, "
                     f"Frequency: {frequency_lower_bound:.1f}-{frequency_upper_bound:.1f}Hz",
                     LogLevel.INFO)

        except ValueError as e:
            self.config_status_label.configure(text="Error: Invalid number format",
                                             foreground="red")
            self._log(f"Error applying deflection bounds: {e}", LogLevel.ERROR)

    def create_deflection_stats_lut_dropdowns(self, parent_frame):
        """Create two dropdown sections for deflection stats LUTs (beam deflection and scan speed).

        ENERGY-AWARE LUT CONFIGURATION UI:
        This method creates the Config tab interface for selecting LUT files with
        energy awareness. Key features:

        1. Lookups based on Beam Energy: Shows real-time total energy from power supplies
        2. LUT File Selection: Dropdowns for beam deflection and scan speed LUTs
        3. Energy Validation: Automatic warnings when LUT energy ≠ current energy
        4. File Naming Guidance: Recommendations for energy-specific naming

        The interface helps users ensure they're using the correct calibration data
        for their current beam energy, preventing measurement errors.
        """

        # Add beam energy display at the top
        energy_info_frame = ttk.Frame(parent_frame)
        energy_info_frame.pack(fill=tk.X, pady=(0, 8))

        # Current beam energy spinbox
        energy_label_frame = ttk.Frame(energy_info_frame)
        energy_label_frame.pack(fill=tk.X)

        ttk.Label(energy_label_frame, text="Lookups based on Beam Energy:", font=("Arial", 9, "bold")).pack(side=tk.LEFT)

        # Available energies (automatically detected from files)
        self.available_energies = [20.0, 30.0, 50.0]  # Default, will be updated from files
        self.current_energy_index = 0  # Start with first energy (20keV)

        self.beam_energy_spinbox = tk.Spinbox(
            energy_label_frame,
            values=[f"{e:.0f} keV" for e in self.available_energies],
            state="readonly",
            width=10,
            font=("Arial", 9, "bold"),
            fg="blue",
            textvariable=self.shared_energy,
            command=self.on_energy_spinbox_change,
            wrap=True
        )
        self.beam_energy_spinbox.pack(side=tk.RIGHT, padx=(5, 0))

        # Warning label for energy mismatch
        self.energy_warning_label = ttk.Label(
            energy_info_frame,
            text="⚠️ Ensure LUT data matches current beam energy for accurate results",
            font=("Arial", 8),
            foreground="orange"
        )
        self.energy_warning_label.pack(pady=(2, 0))

        # Define the two LUT configurations (B-field and power will use formulas)
        lut_configs = [
            {
                'label': 'Beam Deflection LUT:',
                'variable': self.beam_deflection_lut_var,
                'expected_file': 'beam_deflection_20keV.csv',  # Default to 20keV
                'description': '(current_amplitude_A → beam_deflection_cm)'
            },
            {
                'label': 'Scan Speed LUT:',
                'variable': self.scan_speed_lut_var,
                'expected_file': 'scan_speed_20keV.csv',  # Default to 20keV
                'description': '(frequency_hz → scan_speed_mps)'
            }
        ]

        # Store dropdown references for later updates
        self.deflection_stats_dropdowns = []

        for config in lut_configs:
            # Create frame for this LUT selection
            lut_selection_frame = ttk.Frame(parent_frame)
            lut_selection_frame.pack(fill=tk.X, pady=1)

            # Label with description
            label_text = f"{config['label']} {config['description']}"
            ttk.Label(lut_selection_frame, text=label_text, font=("Arial", 8)).pack(side=tk.LEFT)

            # Dropdown with filtered file list
            filtered_files = self.get_filtered_lut_files_by_type(config['label'])

            dropdown = ttk.Combobox(
                lut_selection_frame,
                textvariable=config['variable'],
                values=filtered_files,
                state="readonly",
                width=18
            )
            dropdown.pack(side=tk.RIGHT, padx=(5, 0))

            # Set default to expected file if it exists
            if config['expected_file'] in filtered_files:
                config['variable'].set(config['expected_file'])

            # Bind change event
            dropdown.bind("<<ComboboxSelected>>",
                         lambda event, var=config['variable']: self.on_deflection_stats_lut_change(event, var))

            # Store dropdown with type info for later filtering
            dropdown.lut_type = config['label']
            self.deflection_stats_dropdowns.append(dropdown)

        # Concise help text
        info_frame = ttk.Frame(parent_frame)
        info_frame.pack(fill=tk.X, pady=(3, 0))

        ttk.Label(info_frame,
                  text="Use energy-specific CSV files: 'beam_deflection_20keV.csv', "
                       "'scan_speed_30keV.csv'",
                 font=("Arial", 8), foreground="gray").pack()

        # Detect available energies from files and update spinboxes
        self.detect_available_energies()

        # Load initial LUT data
        self.load_all_deflection_stats_luts()

        # Start beam energy monitoring
        self.start_beam_energy_monitoring()

    def get_available_deflection_stats_lut_files(self):
        """Get list of available CSV files specifically for deflection stats LUTs."""
        try:
            # Get the current beam_pulse directory
            beam_pulse_dir = os.path.dirname(__file__)

            if not os.path.exists(beam_pulse_dir):
                return ["None"]

            csv_files = []
            for file in os.listdir(beam_pulse_dir):
                if file.endswith('.csv'):
                    csv_files.append(file)

            if not csv_files:
                return ["None"]

            # Add "None" option at the beginning
            return ["None"] + sorted(csv_files)

        except Exception as e:
            self._log(f"Error scanning for deflection stats LUT files: {e}", LogLevel.ERROR)
            return ["None"]

    def get_filtered_lut_files_by_type(self, lut_type):
        """Get LUT files filtered by type (deflection or scan speed).

        Args:
            lut_type: Type label like 'Beam Deflection LUT:' or 'Scan Speed LUT:'

        Returns:
            list: Filtered list of CSV filenames for the specified type
        """
        try:
            all_files = self.get_available_deflection_stats_lut_files()

            # Remove "None" from filtering
            csv_files = [f for f in all_files if f != "None" and f.endswith('.csv')]

            # Filter by type
            if 'Beam Deflection' in lut_type:
                # Only show beam deflection files
                filtered = [f for f in csv_files if 'beam_deflection' in f.lower()]
            elif 'Scan Speed' in lut_type:
                # Only show scan speed files
                filtered = [f for f in csv_files if 'scan_speed' in f.lower()]
            else:
                # Unknown type, return all CSV files
                filtered = csv_files

            # Always include "None" option at the beginning
            return ["None"] + sorted(filtered)

        except Exception as e:
            self._log(f"Error filtering LUT files by type '{lut_type}': {e}", LogLevel.ERROR)
            return ["None"]

    def detect_available_energies(self):
        """Detect available beam energies from LUT filenames and update spinboxes."""
        try:
            all_files = self.get_available_deflection_stats_lut_files()
            detected_energies = set()

            # Extract energies from all CSV filenames
            for filename in all_files:
                if filename != "None":
                    energy = self.extract_energy_from_filename(filename)
                    if energy is not None:
                        detected_energies.add(energy)

            # Update available energies list
            if detected_energies:
                self.available_energies = sorted(list(detected_energies))
                self._log(f"Detected available beam energies: {self.available_energies} keV", LogLevel.INFO)
            else:
                # Fallback to defaults if no energies detected
                self.available_energies = [20.0, 30.0, 50.0]
                self._log("No energies detected from files, using default energies", LogLevel.WARNING)

            # Update spinbox values
            energy_labels = [f"{e:.0f} keV" for e in self.available_energies]

            if hasattr(self, 'beam_energy_spinbox'):
                self.beam_energy_spinbox.config(values=energy_labels)

            if hasattr(self, 'main_beam_energy_spinbox'):
                self.main_beam_energy_spinbox.config(values=energy_labels)

            # Set shared variable to first energy if available
            if energy_labels:
                self.shared_energy.set(energy_labels[0])

        except Exception as e:
            self._log(f"Error detecting available energies: {e}", LogLevel.ERROR)

        return self.available_energies

    def on_deflection_stats_lut_change(self, event, variable):
        """Handle deflection stats LUT selection change and update displays."""
        selected_file = variable.get()

        if selected_file == "None":
            # Clear the corresponding LUT data
            if variable == self.beam_deflection_lut_var:
                self.beam_deflection_lut_data = None
            elif variable == self.scan_speed_lut_var:
                self.scan_speed_lut_data = None

            self._log(f"Deflection stats LUT cleared: {selected_file}", LogLevel.INFO)
        else:
            # Load the selected LUT
            self.load_deflection_stats_lut(variable, selected_file)

        # Update deflection stats display with new LUT data
        self.update_deflection_stats()

        # Update energy spinbox to reflect the energy from selected LUT
        self.update_energy_spinbox_from_lut_selection()

    def load_deflection_stats_lut(self, variable, filename):
        """Load a specific deflection stats LUT file.

        ENERGY-AWARE LUT LOADING PROCESS:
        1. Attempts to load CSV file from beam_pulse directory
        2. Validates column headers match expected format
        3. Extracts energy value from filename if present
        4. Logs loading success with energy information
        5. Stores data for real-time interpolation during operation

        The system automatically detects energy from filename and logs it,
        making it easy to track which calibration data is currently loaded.
        """
        try:
            beam_pulse_dir = os.path.dirname(__file__)
            file_path = os.path.join(beam_pulse_dir, filename)

            lut_data = self.load_deflection_stats_csv(file_path, filename)

            # Store the data in the appropriate variable
            if variable == self.beam_deflection_lut_var:
                self.beam_deflection_lut_data = lut_data
            elif variable == self.scan_speed_lut_var:
                self.scan_speed_lut_data = lut_data

            if lut_data:
                row_count = len(lut_data)
                file_energy = self.extract_energy_from_filename(filename)
                energy_info = f" (for {file_energy} keV)" if file_energy else " (energy not specified)"
                self._log(f"Deflection stats LUT loaded: {filename} with {row_count} data points{energy_info}", LogLevel.INFO)
            else:
                self._log(f"Error: Failed to load deflection stats LUT {filename}", LogLevel.ERROR)

        except Exception as e:
            self._log(f"Error loading deflection stats LUT {filename}: {e}", LogLevel.ERROR)

    def load_deflection_stats_csv(self, file_path, filename):
        """Load CSV file for deflection stats with single-energy format.

        ENERGY-SPECIFIC LUT FILE LOADING:
        This method loads individual energy-specific CSV files (e.g., beam_deflection_20keV.csv).
        Each file contains calibration data for a specific beam energy, making it easy to
        switch between different energy datasets and see which energy is currently selected.

        Single-energy file format example:
        current_amplitude_A,deflection_cm
        0.0,0.0
        0.5,0.2
        1.0,0.8
        """
        try:
            lut_data = []

            with open(file_path, 'r', newline='') as csvfile:
                reader = csv.DictReader(csvfile)

                # Get expected input/output columns for this file type
                expected_columns = self.get_expected_columns_for_file(filename)
                if not expected_columns:
                    self._log(f"Unknown deflection stats LUT file format: {filename}", LogLevel.ERROR)
                    return None

                input_col, output_col = expected_columns

                # Verify required columns exist
                if input_col not in reader.fieldnames:
                    self._log(f"Required input column '{input_col}' not found in {filename}", LogLevel.ERROR)
                    return None

                if output_col not in reader.fieldnames:
                    self._log(f"Required output column '{output_col}' not found in {filename}", LogLevel.ERROR)
                    return None

                # Load the single-energy data
                for row in reader:
                    try:
                        input_val = float(row[input_col])
                        output_val = float(row[output_col])
                        lut_data.append({
                            'input': input_val,
                            'output': output_val
                        })
                    except ValueError as e:
                        self._log(f"Skipping invalid row in {filename}: {row} - {e}", LogLevel.WARNING)
                        continue

            # Sort by input value for interpolation
            lut_data.sort(key=lambda x: x['input'])

            # Extract energy from filename and log it
            energy = self.extract_energy_from_filename(filename)
            energy_text = f"{energy:.0f} keV" if energy is not None else "energy not specified"

            self._log(f"Deflection stats LUT loaded: {filename} with {len(lut_data)} data points ({energy_text})", LogLevel.INFO)

            return lut_data

        except Exception as e:
            self._log(f"Error reading deflection stats CSV file {file_path}: {e}", LogLevel.ERROR)
            return None

    def extract_energy_from_column_name(self, column_name):
        """Extract energy value from column name like 'deflection_20keV' or 'speed_50keV'.

        Returns:
            float: Energy in keV, or None if not found
        """
        try:
            import re
            # Look for patterns like 'deflection_20keV', 'speed_50keV', etc.
            match = re.search(r'(\d+(?:\.\d+)?)keV', column_name)
            if match:
                return float(match.group(1))
        except Exception:
            pass
        return None

    def get_expected_columns_for_file(self, filename):
        """Get expected input and output column names for energy-specific LUT files.

        ENERGY-SPECIFIC LUT FILE FORMAT:
        Each file contains calibration data for a single beam energy with simple two-column format.
        This makes it easy to switch between energy datasets and clearly see which energy is selected.

        Supported formats:

        Beam Deflection Files:
        - beam_deflection_20keV.csv: current_amplitude_A,deflection_cm
        - beam_deflection_30keV.csv: current_amplitude_A,deflection_cm
        - beam_deflection_50keV.csv: current_amplitude_A,deflection_cm

        Scan Speed Files:
        - scan_speed_20keV.csv: frequency_hz,scan_speed_mps
        - scan_speed_30keV.csv: frequency_hz,scan_speed_mps
        - scan_speed_50keV.csv: frequency_hz,scan_speed_mps

        The beam energy is extracted from the filename (e.g., _20keV, _30keV, _50keV)
        and displayed in the energy indicators to show which calibration is active.
        """
        # Match energy-specific deflection files
        if 'beam_deflection' in filename and filename.endswith('.csv'):
            return ('current_amplitude_A', 'deflection_cm')

        # Match energy-specific scan speed files
        elif 'scan_speed' in filename and filename.endswith('.csv'):
            return ('frequency_hz', 'scan_speed_mps')

        # No match found
        return None

    def extract_energy_from_filename(self, filename):
        """Extract beam energy value from filename if present.

        ENERGY EXTRACTION RULES:
        Looks for patterns like '_20keV', '_50keV', '_25.5keV' in filenames.
        This allows the system to automatically detect which beam energy
        a LUT file was calibrated for and compare it to the current energy.

        Examples:
        - 'beam_deflection_20keV.csv' -> 20.0 keV
        - 'scan_speed_50keV.csv'      -> 50.0 keV
        - 'beam_deflection.csv'       -> None (energy not specified)
        - 'custom_data_25.5keV.csv'   -> 25.5 keV

        Args:
            filename: CSV filename (e.g., 'beam_deflection_20keV.csv')

        Returns:
            float: Energy value in keV, or None if not found
        """
        try:
            # Look for pattern like '_20keV' or '_50keV' in filename
            import re
            match = re.search(r'_(\d+(?:\.\d+)?)keV', filename)
            if match:
                return float(match.group(1))
        except Exception as e:
            self._log(f"Error extracting energy from filename {filename}: {e}", LogLevel.DEBUG)
        return None

    def start_beam_energy_monitoring(self):
        """Start periodic monitoring of LUT energy displays."""
        def update_energy_display():
            try:
                # Extract energies from currently selected LUT filenames
                deflection_energy = self.extract_energy_from_filename(self.beam_deflection_lut_var.get())
                scan_speed_energy = self.extract_energy_from_filename(self.scan_speed_lut_var.get())

                # Update stored energy values
                if deflection_energy is not None:
                    self.selected_deflection_energy.set(deflection_energy)
                if scan_speed_energy is not None:
                    self.selected_scan_speed_energy.set(scan_speed_energy)

                # The spinboxes now handle energy display instead of labels
                # This monitoring function still updates the stored values for calculations

                # Schedule next update (every 2 seconds)
                if hasattr(self, 'parent_frame') and self.parent_frame:
                    self.parent_frame.after(2000, update_energy_display)
            except Exception as e:
                self._log(f"Error updating LUT energy monitoring: {e}", LogLevel.ERROR)

        # Start the monitoring loop
        if hasattr(self, 'parent_frame') and self.parent_frame:
            self.parent_frame.after(1000, update_energy_display)  # Start after 1 second

    def on_energy_spinbox_change(self):
        """Handle energy spinbox change and auto-update LUT selections."""
        try:
            # Get the current energy from the shared variable
            energy_text = self.shared_energy.get()

            if energy_text:
                selected_energy = float(energy_text.replace(' keV', ''))

                # Update the current energy index
                if selected_energy in self.available_energies:
                    self.current_energy_index = self.available_energies.index(selected_energy)

                # Auto-update LUT file selections to match the new energy
                self.auto_update_lut_files_for_energy(selected_energy)

                self._log(f"Energy changed to {selected_energy:.0f} keV - auto-updating LUT files", LogLevel.INFO)

        except Exception as e:
            self._log(f"Error handling energy spinbox change: {e}", LogLevel.ERROR)

    def auto_update_lut_files_for_energy(self, energy):
        """Automatically update LUT file selections to match the specified energy."""
        try:
            # Generate expected filenames for this energy
            expected_deflection = f"beam_deflection_{energy:.0f}keV.csv"
            expected_scan_speed = f"scan_speed_{energy:.0f}keV.csv"

            # Get available files
            available_files = self.get_available_deflection_stats_lut_files()

            # Update deflection LUT if the file exists
            if expected_deflection in available_files:
                old_deflection = self.beam_deflection_lut_var.get()
                self.beam_deflection_lut_var.set(expected_deflection)
                self.load_deflection_stats_lut(self.beam_deflection_lut_var, expected_deflection)
                self._log(f"Auto-updated deflection LUT: {old_deflection} -> {expected_deflection}", LogLevel.INFO)
            else:
                self._log(f"Deflection file not found: {expected_deflection}", LogLevel.WARNING)

            # Update scan speed LUT if the file exists
            if expected_scan_speed in available_files:
                old_scan_speed = self.scan_speed_lut_var.get()
                self.scan_speed_lut_var.set(expected_scan_speed)
                self.load_deflection_stats_lut(self.scan_speed_lut_var, expected_scan_speed)
                self._log(f"Auto-updated scan speed LUT: {old_scan_speed} -> {expected_scan_speed}", LogLevel.INFO)
            else:
                self._log(f"Scan speed file not found: {expected_scan_speed}", LogLevel.WARNING)

            # Update deflection stats display
            self.update_deflection_stats()

        except Exception as e:
            self._log(f"Error auto-updating LUT files for {energy:.0f} keV: {e}", LogLevel.ERROR)

    def update_energy_spinbox_from_lut_selection(self):
        """Update energy spinbox based on currently selected LUT files."""
        try:
            # Get energy from deflection LUT (primary energy indicator)
            deflection_file = self.beam_deflection_lut_var.get()
            if deflection_file != "None":
                energy = self.extract_energy_from_filename(deflection_file)
                if energy is not None and energy in self.available_energies:
                    energy_text = f"{energy:.0f} keV"

                    # Update shared variable (automatically syncs both spinboxes)
                    self.shared_energy.set(energy_text)

                    # Update current energy index
                    self.current_energy_index = self.available_energies.index(energy)

        except Exception as e:
            self._log(f"Error updating energy spinbox from LUT selection: {e}", LogLevel.ERROR)

    def check_energy_lut_compatibility(self):
        """Check if loaded LUT files match current beam energy and update warnings.

        ENERGY VALIDATION SYSTEM:
        This method continuously monitors for energy mismatches between:
        1. Current beam energy (from power supply readings)
        2. Energy specified in loaded LUT filenames

        WARNING CONDITIONS:
        - Red warning: LUT file energy differs from current energy by >5 keV
        - Green confirmation: LUT file energy matches current energy (within tolerance)
        - Orange reminder: Always shown to remind users about energy importance

        Why this matters:
        Using a 20 keV LUT file when operating at 50 keV will give completely
        wrong deflection calculations and could damage the system or sample.
        """
        try:
            current_energy = self.current_beam_energy_keV.get()
            warnings = []

            # Check beam deflection LUT
            deflection_file = self.beam_deflection_lut_var.get()
            if deflection_file != "None":
                file_energy = self.extract_energy_from_filename(deflection_file)
                if file_energy and abs(current_energy - file_energy) > 5.0:  # 5 keV tolerance
                    warnings.append(f"Deflection LUT is for {file_energy} keV")

            # Check scan speed LUT
            scan_speed_file = self.scan_speed_lut_var.get()
            if scan_speed_file != "None":
                file_energy = self.extract_energy_from_filename(scan_speed_file)
                if file_energy and abs(current_energy - file_energy) > 5.0:  # 5 keV tolerance
                    warnings.append(f"Scan Speed LUT is for {file_energy} keV")

            # Update warning display
            if hasattr(self, 'energy_warning_label'):
                if warnings:
                    warning_text = "⚠️ Energy Mismatch: " + ", ".join(warnings)
                    self.energy_warning_label.configure(text=warning_text, foreground="red")
                else:
                    self.energy_warning_label.configure(
                        text="✓ LUT energy matches current beam energy",
                        foreground="green"
                    )

        except Exception as e:
            self._log(f"Error checking energy compatibility: {e}", LogLevel.DEBUG)

    def load_all_deflection_stats_luts(self):
        """Load all deflection stats LUTs on initialization."""
        lut_mappings = [
            (self.beam_deflection_lut_var, 'beam_deflection_20keV.csv'),
            (self.scan_speed_lut_var, 'scan_speed_20keV.csv')
        ]

        for variable, filename in lut_mappings:
            if variable.get() != "None":
                self.load_deflection_stats_lut(variable, variable.get())

    def interpolate_lut_value(self, lut_data, input_value, current_energy=None):
        """Interpolate value from single-energy LUT data.

        SINGLE-ENERGY INTERPOLATION:
        This method performs simple linear interpolation on single-energy LUT files.
        Each file contains calibration data for one specific beam energy, making
        interpolation straightforward and energy selection explicit.

        Args:
            lut_data: LUT data from CSV file with 'input' and 'output' keys
            input_value: Input parameter value (current or frequency)
            current_energy: Unused (kept for compatibility)
        """
        if not lut_data or len(lut_data) == 0:
            return None

        try:
            # Simple linear interpolation on single-energy data
            return self._interpolate_single_energy(lut_data, input_value)

        except Exception as e:
            self._log(f"Error interpolating LUT data: {e}", LogLevel.ERROR)
            return None

    def _interpolate_single_energy(self, lut_data, input_value):
        """Look up exact match in single-energy LUT data.
        
        Returns the output value only if input_value exactly matches an entry in the LUT.
        Returns None if no exact match is found.
        """
        # Search for exact match in LUT
        for entry in lut_data:
            if abs(entry['input'] - input_value) < 1e-9:  # Float comparison with small tolerance
                return entry['output']
        
        # No exact match found
        return None



    def calculate_b_field_from_current(self, current_amplitude, beam_number=None):
        """Calculate B-field (Gauss) from current amplitude using linear approximations.

        Linear relationships derived from experimental data:

        B = k * I

        where k is the proportionality constant (G/A) and I is current (A).

        From measured data at I = 1.6 A:
        - B_center = 62.2 G  →  k_center = 38.875 G/A
        - B_off-axis = 61.2 G  →  k_off-axis = 38.25 G/A

        Linear equations:
        - B_center(I) = 38.875 * I [G]     (for Beam B - center)
        - B_off-axis(I) = 38.25 * I [G]    (for Beams A and C - off-axis)

        Source: "2019-09-26 field measurements - 2 solenoids no covers.xlsx"
        Data from "Avg" column at position 0 in "Coil A" and "Coil B" tabs.
        Valid within tested current range (up to 1.6 A). Extrapolation beyond
        this range should be treated with caution.

        Args:
            current_amplitude: Solenoid current in amperes
            beam_number: Beam number (1=A, 2=B, 3=C). If None, assumes off-axis.

        Returns:
            Magnetic field in Gauss
        """
        try:
            # Use absolute value of current - magnetic field strength depends on magnitude, not direction
            current_magnitude = abs(current_amplitude)

            if current_magnitude == 0:
                return 0.0

            # Determine which linear approximation to use based on beam position
            if beam_number == 2:
                # Beam B (center beam) - use center approximation
                k_slope = self.B_FIELD_SLOPE_CENTER  # 38.875 G/A
                beam_position = "center"
            else:
                # Beams A and C (off-axis beams) - use off-axis approximation
                k_slope = self.B_FIELD_SLOPE_OFF_AXIS  # 38.25 G/A
                beam_position = "off-axis"

            # Linear B-field calculation: B = k * |I|
            b_field_gauss = k_slope * current_magnitude

            # Debug logging
            if hasattr(self, '_log'):
                self._log(f"B-field calc: Beam {beam_number} ({beam_position}): "
                         f"{current_amplitude:.3f} A (|{current_magnitude:.3f}|) -> {b_field_gauss:.1f} G",
                         LogLevel.DEBUG)

            return b_field_gauss

        except Exception as e:
            if hasattr(self, '_log'):
                self._log(f"Error calculating B-field: {e}", LogLevel.ERROR)
            return 0.0

    def calculate_solenoid_power_from_current(self, current_amplitude):
        """Calculate solenoid power dissipation (Watts) from current amplitude using empirical formula.

        Formula derived from experimental data using linear regression:
        P = 14.810 * I + 0.793

        Source: "Copy of SA-ATEST-100 110 Plots" Google Sheet
        Method: OLS regression on 44 data points (R² = 0.9874)
        Data collected: 2024-12-30 under controlled conditions
        """
        try:
            # Use absolute value of current - power dissipation depends on magnitude, not direction
            current_magnitude = abs(current_amplitude)

            # Empirical power-current relationship from experimental data
            # P = 14.810 * |I| + 0.793 (Watts)
            power = 14.810 * current_magnitude + 0.793

            return max(0.0, power)

        except Exception as e:
            self._log(f"Error calculating solenoid power: {e}", LogLevel.ERROR)
            return 0.0

    def calculate_beam_deflection_from_amplitude(self, current_amplitude):
        """Calculate beam deflection from current amplitude using selected LUT dataset from Config tab.

        DEFLECTION CALCULATION:
        Uses the beam deflection LUT dataset selected in the Config tab dropdown.
        If no LUT is selected or loaded, falls back to a simple linear relationship.

        Args:
            current_amplitude: Current amplitude in amperes

        Returns:
            float: Deflection in centimeters
        """
        try:
            # Check if a beam deflection LUT is selected and loaded from Config tab
            selected_file = self.beam_deflection_lut_var.get()
            if selected_file != "None" and self.beam_deflection_lut_data:
                deflection = self.interpolate_lut_value(
                    self.beam_deflection_lut_data,
                    current_amplitude
                )
                if deflection is not None:
                    self._log(f"Using deflection LUT '{selected_file}': {current_amplitude} A -> {deflection:.1f} cm", LogLevel.DEBUG)
                    return deflection
                else:
                    # Value is outside LUT range
                    self._log(f"Deflection value out of range: {current_amplitude} A not in LUT '{selected_file}'", LogLevel.WARNING)
                    return None

            # No LUT selected - return None to show dashes
            self._log(f"No deflection LUT selected", LogLevel.DEBUG)
            return None

        except Exception as e:
            self._log(f"Error calculating beam deflection: {e}", LogLevel.ERROR)
            return 0.0

    def calculate_scan_speed_from_frequency(self, frequency_hz):
        """Calculate scan speed from frequency using selected LUT dataset from Config tab.

        SCAN SPEED CALCULATION:
        Uses the scan speed LUT dataset selected in the Config tab dropdown.
        The same frequency applies to all three beams - they all scan at the same speed.
        If no LUT is selected or loaded, falls back to a simple linear relationship.

        Args:
            frequency_hz: Frequency in Hz

        Returns:
            float: Scan speed in meters per second
        """
        try:
            # Check if a scan speed LUT is selected and loaded from Config tab
            selected_file = self.scan_speed_lut_var.get()
            if selected_file != "None" and self.scan_speed_lut_data:
                scan_speed = self.interpolate_lut_value(
                    self.scan_speed_lut_data,
                    frequency_hz
                )
                if scan_speed is not None:
                    self._log(f"Using scan speed LUT '{selected_file}': {frequency_hz} Hz -> {scan_speed:.2f} m/s", LogLevel.DEBUG)
                    return scan_speed
                else:
                    # Value is outside LUT range
                    self._log(f"Scan speed value out of range: {frequency_hz} Hz not in LUT '{selected_file}'", LogLevel.WARNING)
                    return None

            # No LUT selected - return None to show dashes
            self._log(f"No scan speed LUT selected", LogLevel.DEBUG)
            return None

        except Exception as e:
            self._log(f"Error calculating scan speed: {e}", LogLevel.ERROR)
            return 0.0

    def calculate_current_beam_energy(self):
        """Calculate current beam energy in keV from power supply voltages.

        ENERGY-AWARE LUT SYSTEM:
        This method calculates the total beam energy by summing all power supply voltages
        from the beam energy subsystem. The energy is displayed in the Config tab and
        used to validate that LUT files match the current operating conditions.

        Why this matters:
        - Deflection sensitivity changes dramatically with beam energy
        - 20 keV vs 50 keV beams require completely different LUT calibration data
        - Using wrong energy LUT data will result in incorrect deflection calculations

        Integration: Call set_beam_energy_subsystem_reference() from main dashboard
        to connect this subsystem to the beam energy subsystem for live energy tracking.

        Returns:
            float: Total beam energy in keV, or 0.0 if no beam energy data available
        """
        try:
            total_energy_keV = 0.0

            # If we have a reference to the beam energy subsystem, use its data
            if self.beam_energy_subsystem_ref:
                # Access the actual voltage readings from beam energy subsystem
                for i, voltage_var in enumerate(self.beam_energy_subsystem_ref.actual_voltages):
                    voltage_str = voltage_var.get()
                    if voltage_str and voltage_str != "-- V":
                        try:
                            # Extract numeric value from "1000.0 V" format
                            voltage_V = float(voltage_str.replace(" V", ""))
                            total_energy_keV += abs(voltage_V) / 1000.0  # Convert V to keV
                        except ValueError:
                            continue
            else:
                # Fallback: use default placeholder value when no beam energy connection
                total_energy_keV = 20.0  # Default assumption for demonstration

            self.current_beam_energy_keV.set(total_energy_keV)
            return total_energy_keV

        except Exception as e:
            self._log(f"Error calculating beam energy: {e}", LogLevel.ERROR)
            return 0.0

    def set_beam_energy_subsystem_reference(self, beam_energy_subsystem):
        """Set reference to beam energy subsystem for accessing voltage data.

        INTEGRATION INSTRUCTIONS FOR MAIN DASHBOARD:
        Call this method during dashboard initialization to connect the beam pulse
        subsystem to the beam energy subsystem. Example:

            # In main dashboard setup:
            beam_energy = BeamEnergySubsystem(...)
            beam_pulse = BeamPulseSubsystem(...)
            beam_pulse.set_beam_energy_subsystem_reference(beam_energy)

        This enables:
        - Real-time beam energy display in beam pulse Config tab
        - Automatic validation of LUT file energy vs current beam energy
        - Warning messages when energy mismatch is detected

        Args:
            beam_energy_subsystem: Instance of BeamEnergySubsystem class
        """
        self.beam_energy_subsystem_ref = beam_energy_subsystem
        self.calculate_current_beam_energy()  # Update energy on connection
        self._log("Beam energy subsystem connected to beam pulse LUT system", LogLevel.INFO)

    def set_dashboard_beam_callback(self, callback):
        """Set callback function for dashboard beam status changes.
        
        The callback should accept (beam_index, status) parameters and handle
        pulse animations when pulsing behavior is set to 'Pulsed'.
        
        Args:
            callback: Function with signature callback(beam_index: int, status: bool)
        """
        self._dashboard_beam_callback = callback
        self._log("Dashboard beam callback registered", LogLevel.DEBUG)

    def get_integration_status(self):
        """Get status of beam energy integration for debugging.

        Returns:
            dict: Integration status information
        """
        return {
            'beam_energy_connected': self.beam_energy_subsystem_ref is not None,
            'current_energy_keV': self.current_beam_energy_keV.get(),
            'deflection_lut_loaded': self.beam_deflection_lut_data is not None,
            'scan_speed_lut_loaded': self.scan_speed_lut_data is not None,
            'deflection_lut_file': self.beam_deflection_lut_var.get(),
            'scan_speed_lut_file': self.scan_speed_lut_var.get()
        }

    def get_deflection_bounds(self):
        return {
            'lower': self.deflection_lower_bound.get(),
            'upper': self.deflection_upper_bound.get()
        }

    def is_deflection_within_bounds(self, value):
        """Check if a deflection value is within the configured bounds."""
        bounds = self.get_deflection_bounds()
        return bounds['lower'] <= value <= bounds['upper']

    def get_available_lut_files(self):
        """Get list of available CSV files from the beam_pulse folder."""
        try:
            # Get the current beam_pulse directory
            beam_pulse_dir = os.path.dirname(__file__)

            if not os.path.exists(beam_pulse_dir):
                self._log(f"LUT directory not found: {beam_pulse_dir}", LogLevel.WARNING)
                return ["None"]

            csv_files = []
            for file in os.listdir(beam_pulse_dir):
                if file.endswith('.csv'):
                    csv_files.append(file)

            if not csv_files:
                return ["None"]

            # Add "None" option at the beginning
            return ["None"] + sorted(csv_files)

        except Exception as e:
            self._log(f"Error scanning for LUT files: {e}", LogLevel.ERROR)
            return ["None"]

    def on_lut_dataset_change(self, event=None):
        """Handle LUT dataset selection change."""
        selected_file = self.lut_dataset_var.get()

        if selected_file == "None":
            self.lut_data = None
            self._log("LUT dataset cleared", LogLevel.INFO)
            return

        try:
            # Load the CSV file
            beam_pulse_dir = os.path.dirname(__file__)
            file_path = os.path.join(beam_pulse_dir, selected_file)

            self.lut_data = self.load_lut_csv(file_path)

            if self.lut_data:
                row_count = len(self.lut_data)
                self._log(f"LUT dataset loaded: {selected_file} with {row_count} data points", LogLevel.INFO)
            else:
                self._log(f"Error: Failed to load dataset {selected_file}", LogLevel.ERROR)

        except Exception as e:
            self._log(f"Error loading LUT dataset {selected_file}: {e}", LogLevel.ERROR)

    def load_lut_csv(self, file_path):
        """Load CSV file with deflection_distance and current_amplitude columns."""
        try:
            lut_data = []

            with open(file_path, 'r', newline='') as csvfile:
                reader = csv.DictReader(csvfile)

                # Check if required columns exist
                if 'deflection_distance' not in reader.fieldnames or 'current_amplitude' not in reader.fieldnames:
                    raise ValueError(f"CSV file must contain 'deflection_distance' and 'current_amplitude' columns. Found: {reader.fieldnames}")

                for row in reader:
                    try:
                        deflection_distance = float(row['deflection_distance'])
                        current_amplitude = float(row['current_amplitude'])
                        lut_data.append({
                            'deflection_distance': deflection_distance,
                            'current_amplitude': current_amplitude
                        })
                    except ValueError as e:
                        self._log(f"Skipping invalid row in LUT file: {row} - {e}", LogLevel.WARNING)
                        continue

            # Sort by deflection distance for interpolation
            lut_data.sort(key=lambda x: x['deflection_distance'])
            return lut_data

        except Exception as e:
            self._log(f"Error reading LUT CSV file {file_path}: {e}", LogLevel.ERROR)
            return None

    def get_current_amplitude_for_distance(self, deflection_distance):
        """Get current amplitude for given deflection distance using LUT interpolation."""
        if not self.lut_data or len(self.lut_data) == 0:
            return None

        # Simple linear interpolation
        try:
            # If distance is outside bounds, return boundary values
            if deflection_distance <= self.lut_data[0]['deflection_distance']:
                return self.lut_data[0]['current_amplitude']

            if deflection_distance >= self.lut_data[-1]['deflection_distance']:
                return self.lut_data[-1]['current_amplitude']

            # Find surrounding points for interpolation
            for i in range(len(self.lut_data) - 1):
                if (self.lut_data[i]['deflection_distance'] <= deflection_distance <=
                    self.lut_data[i + 1]['deflection_distance']):

                    # Linear interpolation
                    x0, y0 = self.lut_data[i]['deflection_distance'], self.lut_data[i]['current_amplitude']
                    x1, y1 = self.lut_data[i + 1]['deflection_distance'], self.lut_data[i + 1]['current_amplitude']

                    # Interpolate
                    if x1 - x0 == 0:  # Avoid division by zero
                        return y0

                    interpolated_amplitude = y0 + (y1 - y0) * (deflection_distance - x0) / (x1 - x0)
                    return interpolated_amplitude

            return None

        except Exception as e:
            self._log(f"Error interpolating LUT data: {e}", LogLevel.ERROR)
            return None

    def refresh_lut_dropdown(self):
        """Refresh the LUT dropdown with current available CSV files."""
        if hasattr(self, 'lut_dropdown'):
            try:
                current_files = self.get_available_lut_files()
                self.lut_dropdown['values'] = current_files

                # If current selection is no longer available, reset to "None"
                current_selection = self.lut_dataset_var.get()
                if current_selection not in current_files:
                    self.lut_dataset_var.set("None")
                    self.lut_data = None

                self._log("LUT dropdown refreshed", LogLevel.DEBUG)
            except Exception as e:
                self._log(f"Error refreshing LUT dropdown: {e}", LogLevel.ERROR)

    def create_wave_gen_control(self, parent, column):
        """Create Wave Gen toggle control."""
        frame = ttk.Frame(parent)
        frame.grid(row=0, column=column, padx=5, pady=2, sticky="ew")

        # Label
        ttk.Label(frame, text="Deflect Beam", font=("Arial", 9, "bold")).pack()

        # Toggle button
        if self.toggle_off_image and self.toggle_on_image:
            self.wave_gen_toggle = ttk.Button(
                frame,
                image=self.toggle_off_image,
                style='Flat.TButton',
                command=self.toggle_wave_gen
            )
        else:
            # Fallback if images not available
            self.wave_gen_toggle = ttk.Button(
                frame,
                text="OFF",
                command=self.toggle_wave_gen,
                width=6
            )
        self.wave_gen_toggle.pack(pady=(2, 0))

    def create_wave_type_control(self, parent, column):
        """Create Wave Type dropdown control."""
        frame = ttk.Frame(parent)
        frame.grid(row=0, column=column, padx=5, pady=2, sticky="ew")

        # Label
        ttk.Label(frame, text="Wave Type", font=("Arial", 9, "bold")).pack()

        # Dropdown (Combobox) with three wave type options (Pulse functionality moved to Pulsing Behavior)
        wave_types = ["Sine", "Triangle", "Fixed"]
        self.wave_type_combo = ttk.Combobox(
            frame,
            textvariable=self.wave_type,
            values=wave_types,
            state="readonly",
            width=10
        )
        self.wave_type_combo.pack(pady=(2, 0))
        self.wave_type_combo.bind("<<ComboboxSelected>>", self.on_wave_type_change)

    def create_pulsing_behavior_control(self, parent, column):
        """Create Pulsing Behavior dropdown control."""
        frame = ttk.Frame(parent)
        frame.grid(row=0, column=column, padx=5, pady=2, sticky="ew")

        # Label
        ttk.Label(frame, text="Pulsing Behavior", font=("Arial", 9, "bold")).pack()

        # Dropdown (Combobox) with DC and Pulsed options
        pulsing_types = ["DC", "Pulsed"]
        self.pulsing_behavior_combo = ttk.Combobox(
            frame,
            textvariable=self.pulsing_behavior,
            values=pulsing_types,
            state="readonly",
            width=10
        )
        self.pulsing_behavior_combo.pack(pady=(2, 0))
        self.pulsing_behavior_combo.bind("<<ComboboxSelected>>", self.on_pulsing_behavior_change)

    def create_frequency_control(self, parent, column):
        """Create Freq (Hz) spinbox control."""
        frame = ttk.Frame(parent)
        frame.grid(row=0, column=column, padx=5, pady=2, sticky="ew")

        # Label
        ttk.Label(frame, text="Freq (Hz)", font=("Arial", 9, "bold")).pack()

        # Spinbox
        self.frequency_spinbox = tk.Spinbox(
            frame,
            from_=0.1,
            to=45.0,
            increment=1.0,  # Changed from 0.1 to 1.0
            textvariable=self.frequency_hz,
            command=self.on_frequency_change,
            width=8,
            format="%.1f"
        )
        self.frequency_spinbox.pack(pady=(2, 0))

    def create_wave_amplitude_control(self, parent, column):
        """Create Wave Amp (+-V) spinbox control."""
        frame = ttk.Frame(parent)
        frame.grid(row=0, column=column, padx=5, pady=2, sticky="ew")

        # Label
        ttk.Label(frame, text="Wave Amp (±A)", font=("Arial", 9, "bold")).pack()

        # Spinbox - updated range to fit 5cm graph better
        self.wave_amp_spinbox = tk.Spinbox(
            frame,
            from_=-2.5,
            to=2.5,  # Max amplitude to fit in graph range
            increment=0.1,  # Smaller increment for precision
            textvariable=self.wave_amplitude,
            command=self.on_wave_amplitude_change,
            width=8,
            format="%.1f"
        )
        self.wave_amp_spinbox.pack(pady=(2, 0))

    def create_bcon_connection_status(self, parent, column):
        """Create BCON Connection status indicator."""
        frame = ttk.Frame(parent)
        frame.grid(row=0, column=column, padx=5, pady=2, sticky="ew")

        # Label
        ttk.Label(frame, text="BCON Connected", font=("Arial", 9, "bold")).pack()

        # Circular status indicator
        self.bcon_connection_canvas = tk.Canvas(frame, width=20, height=20, highlightthickness=0)
        self.bcon_connection_canvas.pack(pady=(2, 0))
        self.update_bcon_connection_status()

    def create_beam_duration_control(self, parent, column, label_text, duration_var):
        """Create Beam Duration spinbox control."""
        frame = ttk.Frame(parent)
        frame.grid(row=0, column=column, padx=2, pady=2, sticky="")

        # Label
        ttk.Label(frame, text=label_text, font=("Arial", 9, "bold")).pack()

        # Spinbox
        duration_spinbox = tk.Spinbox(
            frame,
            from_=1.0,
            to=1000.0,
            increment=1.0,
            textvariable=duration_var,
            command=lambda: self.on_duration_change(duration_var),
            width=8,
            format="%.1f"
        )
        duration_spinbox.pack(pady=(2, 0))

        # Store reference for enable/disable control
        self.duration_spinboxes.append(duration_spinbox)

    def update_frequency_spinbox_state(self):
        """Update the frequency, amplitude, and duration spinbox states based on current wave type and pulsing behavior."""
        if hasattr(self, 'frequency_spinbox'):
            wave_type = self.wave_type.get()
            if wave_type.lower() == "fixed":
                self.frequency_spinbox.configure(state="disabled")
            else:
                self.frequency_spinbox.configure(state="normal")

        # Update wave gen button state
        # Wave gen toggle is always enabled since pulse functionality is now separate
        if hasattr(self, 'wave_gen_toggle'):
            self.wave_gen_toggle.configure(state="normal")

        # Update duration spinboxes state based on pulsing behavior
        if hasattr(self, 'duration_spinboxes'):
            pulsing_behavior = self.pulsing_behavior.get()
            if pulsing_behavior == "Pulsed":
                # Enable duration spinboxes for Pulsed mode
                for spinbox in self.duration_spinboxes:
                    spinbox.configure(state="normal")
            else:
                # Disable duration spinboxes for DC mode
                for spinbox in self.duration_spinboxes:
                    spinbox.configure(state="disabled")

    def create_deflection_stats(self, parent):
        """Create the Deflection Stats section with vertical layout and column shading."""
        try:
            # Title frame
            title_frame = ttk.Frame(parent)
            title_frame.pack(fill=tk.X, pady=(0, 8))

            ttk.Label(title_frame, text="Deflection Stats", font=("Arial", 10, "bold")).pack()

            # Current beam energy spinbox (moved from Config tab for better visibility)
            energy_frame = ttk.Frame(title_frame)
            energy_frame.pack(fill=tk.X, pady=(2, 0))

            ttk.Label(energy_frame, text="Based on Beam Energy:", font=("Arial", 8)).pack(side=tk.LEFT)

            self.main_beam_energy_spinbox = tk.Spinbox(
                energy_frame,
                values=[f"{e:.0f} keV" for e in self.available_energies],
                state="readonly",
                width=10,
                font=("Arial", 8, "bold"),
                fg="blue",
                textvariable=self.shared_energy,
                command=self.on_energy_spinbox_change,
                wrap=True
            )
            self.main_beam_energy_spinbox.pack(side=tk.RIGHT)

            # Stats container with vertical spacing
            stats_container = tk.Frame(parent)
            stats_container.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

            # Configure columns for equal distribution (3 beams)
            for i in range(3):
                stats_container.grid_columnconfigure(i, weight=1)

            # Beam headers with vertical spacing and background colors
            header_row = 0
            beam_a_label = tk.Label(stats_container, text="Beam A", font=("Arial", 9, "bold"),
                                    bg="#f0f0f0", relief="flat", padx=5, pady=2)
            beam_a_label.grid(row=header_row, column=0, pady=(0, 8), padx=2, sticky="ew")

            beam_b_label = tk.Label(stats_container, text="Beam B", font=("Arial", 9, "bold"),
                                    relief="flat", padx=5, pady=2)
            beam_b_label.grid(row=header_row, column=1, pady=(0, 8), padx=2, sticky="ew")

            beam_c_label = tk.Label(stats_container, text="Beam C", font=("Arial", 9, "bold"),
                                    bg="#f0f0f0", relief="flat", padx=5, pady=2)
            beam_c_label.grid(row=header_row, column=2, pady=(0, 8), padx=2, sticky="ew")

            # Define stats with labels and defaults
            stats_sections = [
                ("Max Deflection (cm)", "deflection", ["5.0", "5.0", "5.0"]),
                ("Scan Speed (m/s)", "scan_speed", ["1.5", "1.5", "1.5"]),
                ("B-field (G)", "bfield", ["28.0", "28.0", "28.0"])
            ]

            # Store references for later updates
            if not hasattr(self, 'deflection_table_elements'):
                self.deflection_table_elements = {}

            current_row = 1

            # Create each stats section
            for section_label, stat_type, default_values in stats_sections:
                # Section label spanning all columns
                section_label_widget = tk.Label(
                    stats_container,
                    text=section_label,
                    font=("Arial", 8, "bold"),
                    anchor=tk.CENTER
                )
                section_label_widget.grid(row=current_row, column=0, columnspan=3, pady=(3, 2), sticky="ew")
                current_row += 1

                # Value displays for each beam with appropriate backgrounds
                for beam_idx in range(3):
                    # Determine background color based on column (A and C get shading)
                    if beam_idx == 0:  # Beam A (column 0)
                        bg_color = "#f8f8f8"  # Slightly lighter shade for value boxes
                    elif beam_idx == 1:  # Beam B (column 1)
                        bg_color = "white"
                    else:  # Beam C (column 2)
                        bg_color = "#f8f8f8"  # Slightly lighter shade for value boxes

                    value_display = tk.Label(
                        stats_container,
                        text=default_values[beam_idx],
                        font=("Arial", 10, "bold"),
                        background=bg_color,
                        relief="sunken",
                        width=10,
                        anchor=tk.CENTER,
                        bd=1
                    )
                    value_display.grid(row=current_row, column=beam_idx, padx=3, pady=(0, 4), sticky="ew")

                    # Store reference for updates
                    self.deflection_table_elements[f'{stat_type}_beam_{beam_idx + 1}'] = {
                        'display': value_display,
                        'stat_type': stat_type,
                        'beam': beam_idx + 1,
                        'default': default_values[beam_idx]
                    }

                current_row += 1

            # Add power estimate section (individual per beam like other stats)
            power_label_widget = tk.Label(
                stats_container,
                text="Power Estimate (W)",
                font=("Arial", 8, "bold"),
                anchor=tk.CENTER
            )
            power_label_widget.grid(row=current_row, column=0, columnspan=3, pady=(3, 2), sticky="ew")

            current_row += 1

            # Power displays for each beam with appropriate backgrounds (matching other stats)
            power_defaults = ["150", "150", "150"]  # Default power values for each beam
            for beam_idx in range(3):
                # Determine background color based on column (A and C get shading)
                if beam_idx == 0:  # Beam A (column 0)
                    bg_color = "#f8f8f8"  # Slightly lighter shade for value boxes
                elif beam_idx == 1:  # Beam B (column 1)
                    bg_color = "white"
                else:  # Beam C (column 2)
                    bg_color = "#f8f8f8"  # Slightly lighter shade for value boxes

                power_display = tk.Label(
                    stats_container,
                    text=power_defaults[beam_idx],
                    font=("Arial", 10, "bold"),
                    background=bg_color,
                    relief="sunken",
                    width=10,
                    anchor=tk.CENTER,
                    bd=1
                )
                power_display.grid(row=current_row, column=beam_idx, padx=3, pady=(0, 4), sticky="ew")

                # Store reference for updates (individual power per beam)
                self.deflection_table_elements[f'power_beam_{beam_idx + 1}'] = {
                    'display': power_display,
                    'stat_type': 'power',
                    'beam': beam_idx + 1,
                    'default': power_defaults[beam_idx]
                }

        except Exception as e:
            # If deflection stats creation fails, create a simple fallback
            self._log(f"Error creating deflection stats: {e}", LogLevel.ERROR)
            error_label = tk.Label(parent, text=f"Deflection Stats Error: {str(e)}",
                                 fg="red", font=("Arial", 8))
            error_label.pack(pady=10)

    def create_plots(self, parent):
        """Create the three beam plots side by side with no gaps between them."""
        if not _HAS_MATPLOTLIB:
            lbl = ttk.Label(parent, text="matplotlib not available — install matplotlib to see plots")
            lbl.pack(fill=tk.BOTH, expand=True)
            return

        # Create a matplotlib figure with 3 subplots laid out horizontally (1 row x 3 cols)
        # Add minimal spacing between subplots - just enough to prevent label overlap
        fig = Figure(figsize=(6, 2), constrained_layout=False)
        axs = [fig.add_subplot(1, 3, i + 1) for i in range(3)]

        # Remove all spacing between subplots to make them touch
        fig.subplots_adjust(left=0.08, right=0.98, bottom=0.2, top=0.9, wspace=0)

        # Configure each subplot with grid lines and labels
        section_labels = ['Beam A (x-dir)', 'Beam B (x-dir)', 'Beam C (x-dir)']
        for i, ax in enumerate(axs):
            ax.set_xlabel(section_labels[i], fontsize=6)
            ax.tick_params(labelsize=6)
            ax.title.set_fontsize(8)

            # Set axis limits to accommodate all grid lines
            ax.set_xlim(-2.5, 2.5)
            ax.set_ylim(-2.5, 2.5)

            # Set major ticks for labels: -2, -1, 0, 1, 2 (increments of 1)
            ax.set_xticks([-2, -1, 0, 1, 2])
            ax.set_yticks([-2, -1, 0, 1, 2])

            # Set minor ticks for grid lines: -2.5 to 2.5 with increments of 0.5
            ax.set_xticks([-2.5, -2, -1.5, -1, -0.5, 0, 0.5, 1, 1.5, 2, 2.5], minor=True)
            ax.set_yticks([-2.5, -2, -1.5, -1, -0.5, 0, 0.5, 1, 1.5, 2, 2.5], minor=True)

            # Enable grid at minor tick positions (for 0.5 increment grid lines)
            ax.grid(True, which='minor', alpha=0.7)
            # Also enable grid at major tick positions (for labels)
            ax.grid(True, which='major', alpha=0.9)

            # Set y-axis label
            ax.set_ylabel('All Beams (y-dir)', fontsize=6)

            if i == 1:
                ax.set_ylabel('')
                ax.set_yticklabels([])  # Hide y-tick labels on Beam B
            elif i == 2:
                ax.set_ylabel('')
                ax.set_yticklabels([])  # Hide y-tick labels on Beam C
                
                # Add legend to the rightmost graph (Beam C)
                # Create dummy plot objects for legend entries
                from matplotlib.lines import Line2D
                legend_elements = [
                    Line2D([0], [0], color='red', linewidth=2, label='Current step'),
                    Line2D([0], [0], color='blue', linewidth=1, alpha=0.7, label='Past step')
                ]
                ax.legend(handles=legend_elements, loc='upper right', fontsize=7, framealpha=0.9)


        # Beam status LED indicators above graphs (LED left of label, compact row)
        led_frame = ttk.Frame(parent)
        led_frame.pack(fill=tk.X, pady=(0, 10), padx=(100, 0))

        self.beam_led_canvases = []
        beam_names = ['Beam A ON', 'Beam B ON', 'Beam C ON']

        for i in range(3):
            # Container for each beam indicator (horizontal row)
            beam_container = ttk.Frame(led_frame)
            beam_container.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=1)

            # LED indicator (left)
            led_canvas = tk.Canvas(beam_container, width=16, height=16, highlightthickness=0)
            led_canvas.pack(side=tk.LEFT, padx=(0, 4), pady=0)
            self.beam_led_canvases.append(led_canvas)

            # Label (right)
            ttk.Label(beam_container, text=beam_names[i], font=('Helvetica', 8, 'bold')).pack(side=tk.LEFT, padx=(0, 2))

        # Initialize LED states
        self.update_beam_led_indicators()

        self._bp_fig = fig
        self._bp_axes = axs
        self._bp_canvas = FigureCanvasTkAgg(fig, master=parent)
        self._bp_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    # Event handlers for controls
    def toggle_wave_gen(self):
        """Handle wave generator toggle button press."""
        self.wave_gen_toggle_state = not self.wave_gen_toggle_state
        self.wave_gen_enabled.set(self.wave_gen_toggle_state)

        # Update button appearance
        if hasattr(self, 'wave_gen_toggle'):
            if self.toggle_on_image and self.toggle_off_image:
                if self.wave_gen_toggle_state:
                    self.wave_gen_toggle.configure(image=self.toggle_on_image)
                else:
                    self.wave_gen_toggle.configure(image=self.toggle_off_image)
            else:
                # Fallback text button
                self.wave_gen_toggle.configure(text="ON" if self.wave_gen_toggle_state else "OFF")

        # When Deflect Beam is turned ON, check wave type
        # For Fixed, Sine, and Triangle: create graphs for all beams that are currently ON
        if self.wave_gen_toggle_state:
            wave_type = self.wave_type.get().lower()
            if wave_type in ["fixed", "sine", "triangle"]:
                # Check each beam and create graph if beam is ON
                for beam_index in range(3):
                    if self.beam_on_status[beam_index]:
                        self.add_beam_position_to_plot(beam_index)
                        beam_names = ['A', 'B', 'C']
                        self._log(f"Deflection started for Beam {beam_names[beam_index]} ({wave_type})", LogLevel.DEBUG)

        self._log(f"Wave Gen {'enabled' if self.wave_gen_toggle_state else 'disabled'}", LogLevel.DEBUG)

    def toggle_graph_visibility(self):
        """Toggle visibility of beam position history on graphs."""
        self.graph_history_visible = not self.graph_history_visible

        if self.graph_history_visible:
            # Show all history - redraw everything
            self.redraw_all_beam_plots()
            self.clear_graph_button.configure(text="Clear Graph")
            self._log("Beam position history shown", LogLevel.DEBUG)
        else:
            # Clear all visible plots but keep data
            self.clear_all_beam_plots_display()
            self.clear_graph_button.configure(text="Show All")
            self._log("Beam position history hidden", LogLevel.DEBUG)

    def on_wave_gen_change(self, value=None):
        """Handle wave generator slider change (legacy method for compatibility)."""
        self._log(f"Wave Gen changed to: {self.wave_gen_enabled.get()}", LogLevel.DEBUG)

    def on_wave_type_change(self, event=None):
        """Handle wave type dropdown change."""
        wave_type = self.wave_type.get()
        self._log(f"Wave Type changed to: {wave_type}", LogLevel.DEBUG)

        # Update all control states based on current wave type and pulsing behavior
        self.update_frequency_spinbox_state()

    def on_pulsing_behavior_change(self, event=None):
        """Handle pulsing behavior dropdown change."""
        pulsing_behavior = self.pulsing_behavior.get()
        self._log(f"Pulsing Behavior changed to: {pulsing_behavior}", LogLevel.DEBUG)

        # Update all control states based on current pulsing behavior
        self.update_frequency_spinbox_state()

    def on_frequency_change(self):
        """Handle frequency spinbox change and update scan speed for all beams."""
        frequency = self.frequency_hz.get()
        self._log(f"Frequency changed to: {frequency} Hz", LogLevel.DEBUG)

        # Update scan speed for all three beams based on new frequency
        # All beams use the same frequency -> same scan speed
        self.update_deflection_stats()

    def on_wave_amplitude_change(self):
        """Handle wave amplitude spinbox change and update deflection stats."""
        amplitude = self.wave_amplitude.get()
        self._log(f"Wave Amplitude changed to: {amplitude} A", LogLevel.DEBUG)

        # Update deflection, B-field, and power for all beams based on new amplitude
        self.update_deflection_stats()

    def on_duration_change(self, duration_var):
        """Handle beam duration spinbox change."""
        beam_name = "Unknown"
        if duration_var == self.beam_a_duration:
            beam_name = "A"
        elif duration_var == self.beam_b_duration:
            beam_name = "B"
        elif duration_var == self.beam_c_duration:
            beam_name = "C"
        self._log(f"Beam {beam_name} Duration changed to: {duration_var.get()} ms", LogLevel.DEBUG)

    # Status indicator update methods
    def update_bcon_connection_status(self):
        """Update BCON Connection status indicator."""
        color = "green" if self.bcon_connection_status else "red"
        self.bcon_connection_canvas.delete("all")
        self.bcon_connection_canvas.create_oval(2, 2, 18, 18, fill=color, outline="darkgray")

    # Status update methods for external use
    def set_bcon_connection_status(self, status: bool):
        """Set BCON Connection status and update indicator."""
        self.bcon_connection_status = status
        if hasattr(self, 'bcon_connection_canvas'):
            self.update_bcon_connection_status()

    def update_beam_led_indicators(self):
        """Update all beam LED indicators based on current beam status."""
        if not hasattr(self, 'beam_led_canvases'):
            return

        for i, canvas in enumerate(self.beam_led_canvases):
            color = "green" if self.beam_on_status[i] else "red"
            canvas.delete("all")
            canvas.create_oval(2, 2, 14, 14, fill=color, outline="darkgray")

    def set_beam_status(self, beam_index: int, status: bool):
        """Set beam on/off status and update LED indicator.

        Args:
            beam_index: Beam index (0=A, 1=B, 2=C)
            status: True for on, False for off
        """
        if 0 <= beam_index <= 2:
            self.beam_on_status[beam_index] = status
            self.update_beam_led_indicators()

            # Add position to plot if beam is turned on and wave generation is enabled
            if status and self.wave_gen_toggle_state:
                self.add_beam_position_to_plot(beam_index)

            beam_names = ['A', 'B', 'C']
            self._log(f"Beam {beam_names[beam_index]} status set to {'ON' if status else 'OFF'}", LogLevel.DEBUG)

            # Dashboard integration: trigger appropriate behavior based on pulsing mode
            if hasattr(self, '_dashboard_beam_callback') and self._dashboard_beam_callback:
                try:
                    pulsing_behavior = self.get_pulsing_behavior()
                    if status:
                        if pulsing_behavior == "Pulsed":
                            # Pulsed mode: trigger animation with duration
                            duration = self.get_beam_duration(beam_index)
                            self._dashboard_beam_callback(beam_index, status, duration)
                        else:
                            # DC mode: trigger solid bar with counter (duration = 0 indicates DC mode)
                            self._dashboard_beam_callback(beam_index, status, 0)
                    else:
                        # Always notify dashboard when beam is turned OFF
                        self._dashboard_beam_callback(beam_index, status, 0)
                except Exception as e:
                    self._log(f"Dashboard callback error: {e}", LogLevel.WARNING)

    def get_beam_status(self, beam_index: int) -> bool:
        """Get beam on/off status.

        Args:
            beam_index: Beam index (0=A, 1=B, 2=C)

        Returns:
            True if beam is on, False if off
        """
        if 0 <= beam_index <= 2:
            return self.beam_on_status[beam_index]
        return False

    def set_all_beams_status(self, status: bool):
        """Set all beams to the same status."""
        for i in range(3):
            self.beam_on_status[i] = status
        self.update_beam_led_indicators()

    def get_pulsing_behavior(self) -> str:
        """Get current pulsing behavior setting."""
        if hasattr(self, 'pulsing_behavior') and self.pulsing_behavior:
            return self.pulsing_behavior.get()
        return "DC"

    def get_beam_duration(self, beam_index: int) -> float:
        """Get beam duration in milliseconds for specific beam."""
        if beam_index == 0 and hasattr(self, 'beam_a_duration') and self.beam_a_duration:
            return self.beam_a_duration.get()
        elif beam_index == 1 and hasattr(self, 'beam_b_duration') and self.beam_b_duration:
            return self.beam_b_duration.get()
        elif beam_index == 2 and hasattr(self, 'beam_c_duration') and self.beam_c_duration:
            return self.beam_c_duration.get()
        return 100.0  # Default fallback

    def calculate_beam_position(self, beam_index: int):
        """Calculate beam position based on current wave type and parameters.

        Args:
            beam_index: Beam index (0=A, 1=B, 2=C)

        Returns:
            dict: Position data with 'type', 'x', 'y', and other relevant info
        """
        wave_type = self.wave_type.get().lower()
        amplitude = self.wave_amplitude.get()
        frequency = self.frequency_hz.get()

        if wave_type == "fixed":
            # Fixed position at amplitude
            return {
                'type': 'fixed',
                'x': amplitude,
                'y': 0,  # Fixed at center y
                'amplitude': amplitude
            }

        elif wave_type == "pulse":
            # Pulse at current amplitude position
            duration = self.get_pulse_duration(beam_index)
            return {
                'type': 'pulse',
                'x': amplitude,
                'y': 0,  # Pulse at center y
                'amplitude': amplitude,
                'duration': duration
            }

        elif wave_type in ["sine", "triangle"]:
            # Generate wave path points
            if _HAS_NUMPY:
                import numpy as np
                t = np.linspace(0, 2*np.pi, 100)  # One complete cycle

                if wave_type == "sine":
                    x = amplitude * np.cos(t)
                    y = 0 * t  # Placeholder for sine wave y
                    # y = amplitude * np.sin(t)
                else:  # triangle
                    # Create triangular wave pattern
                    x = amplitude * np.cos(t)
                    y = 0 * t  # Placeholder for triangle wave y
                    # y = amplitude * np.sign(np.sin(t)) * (1 - 2*np.abs(np.mod(t, np.pi) - np.pi/2) / (np.pi/2))
            else:
                # Fallback without numpy
                t_points = [i * 2 * math.pi / 99 for i in range(100)]

                if wave_type == "sine":
                    x = [amplitude * math.cos(t) for t in t_points]
                    y = [0 for t in t_points]  # Placeholder for sine wave y
                    # y = [amplitude * math.sin(t) for t in t_points]
                else:  # triangle
                    x = [amplitude * math.cos(t) for t in t_points]
                    y = [0 for t in t_points]  # Placeholder for triangle wave y
                    # y = [amplitude * (1 if math.sin(t) >= 0 else -1) *
                    #      (1 - 2*abs((t % math.pi) - math.pi/2) / (math.pi/2)) for t in t_points]

            return {
                'type': wave_type,
                'x': x,
                'y': y,
                'amplitude': amplitude,
                'frequency': frequency
            }

        return None

    def get_pulse_duration(self, beam_index: int):
        """Get pulse duration for specific beam."""
        if beam_index == 0:
            return self.beam_a_duration.get()
        elif beam_index == 1:
            return self.beam_b_duration.get()
        elif beam_index == 2:
            return self.beam_c_duration.get()
        return 100.0

    def add_beam_position_to_plot(self, beam_index: int):
        """Add current beam position to the plot and history."""
        if not hasattr(self, '_bp_axes') or self._bp_axes is None:
            return

        position_data = self.calculate_beam_position(beam_index)
        if position_data is None:
            return

        ax = self._bp_axes[beam_index]
        wave_type = position_data['type']

        # Always move previous current position to history (if it exists)
        if self.beam_current[beam_index] is not None:
            self.beam_history[beam_index].append(self.beam_current[beam_index])

        # Always create plot objects for data persistence, regardless of visibility
        # Colors: blue for history (completed), red for current
        history_color = 'blue'
        current_color = 'red'

        # Create the plot object based on wave type
        if wave_type == "fixed":
            # Plot single point
            x, y = position_data['x'], position_data['y']
            current_plot = ax.plot(x, y, 'o', color=current_color, markersize=8)[0]

        elif wave_type == "pulse":
            # Plot pulse as a larger dot
            x, y = position_data['x'], position_data['y']
            current_plot = ax.plot(x, y, 's', color=current_color, markersize=10)[0]

        elif wave_type in ["sine", "triangle"]:
            # Plot wave path
            x, y = position_data['x'], position_data['y']
            current_plot = ax.plot(x, y, '-', color=current_color, linewidth=2)[0]

        # Store the current plot object
        self.beam_current[beam_index] = current_plot

        # Handle visibility - if hidden, remove from display but keep object for history
        if not self.graph_history_visible:
            # Hide the current plot but keep the object for data persistence
            current_plot.remove()
        else:
            # Graphs are visible - redraw history to ensure proper colors
            self.redraw_beam_history(beam_index)

        # Always update canvas if graphs are visible
        if self.graph_history_visible and hasattr(self, '_bp_canvas'):
            self._bp_canvas.draw()

    def redraw_beam_history(self, beam_index: int):
        """Redraw beam history in blue color."""
        if not hasattr(self, '_bp_axes') or self._bp_axes is None:
            return

        ax = self._bp_axes[beam_index]
        history_color = 'blue'

        # Remove old history plot objects from display
        for obj in self.beam_plot_objects[beam_index]:
            try:
                obj.remove()
            except AttributeError:
                pass  # Already removed
        self.beam_plot_objects[beam_index].clear()

        # Only redraw if graphs should be visible
        if not self.graph_history_visible:
            return

        # Redraw all history items from stored data
        for hist_item in self.beam_history[beam_index]:
            if hist_item is not None:
                try:
                    # Create new plot object in history color
                    xdata, ydata = hist_item.get_data()
                    marker = hist_item.get_marker()
                    if marker == 'None' or marker is None:  # Line plot
                        new_obj = ax.plot(xdata, ydata, '-', color=history_color, alpha=0.7, linewidth=1)[0]
                    else:  # Point plot
                        new_obj = ax.plot(xdata, ydata, marker, color=history_color, alpha=0.7, markersize=6)[0]
                    self.beam_plot_objects[beam_index].append(new_obj)
                except Exception as e:
                    self._log(f"Error redrawing history item for beam {beam_index}: {e}", LogLevel.WARNING)

    def clear_all_beam_plots_display(self):
        """Clear all visible beam plots except the current position (last move)."""
        if not hasattr(self, '_bp_axes') or self._bp_axes is None:
            return

        for beam_index in range(3):
            ax = self._bp_axes[beam_index]

            # Keep the current position plot visible (the last move)
            # Only remove history plots, not the current position

            # Remove all history plot objects from display but keep references in beam_history
            for obj in self.beam_plot_objects[beam_index]:
                obj.remove()
            # Clear the display objects list but keep beam_history intact
            self.beam_plot_objects[beam_index].clear()

        # Update canvas
        if hasattr(self, '_bp_canvas'):
            self._bp_canvas.draw()

    def redraw_all_beam_plots(self):
        """Redraw all beam plots (history and current positions)."""
        if not hasattr(self, '_bp_axes') or self._bp_axes is None:
            return

        for beam_index in range(3):
            # Redraw history for this beam
            self.redraw_beam_history(beam_index)

            # If there's a current beam position, redraw it in the correct color
            if self.beam_current[beam_index] is not None:
                # The current position object exists but was removed from display
                # We need to recreate it on the axes
                try:
                    # Get the data from the existing plot object
                    xdata, ydata = self.beam_current[beam_index].get_data()
                    marker = self.beam_current[beam_index].get_marker()

                    # Create new current position plot in red on the correct axes
                    ax = self._bp_axes[beam_index]
                    if marker and marker != 'None':  # Point plot
                        if marker == 'o':
                            new_plot = ax.plot(xdata, ydata, 'o', color='red', markersize=8)[0]
                        elif marker == 's':
                            new_plot = ax.plot(xdata, ydata, 's', color='red', markersize=10)[0]
                        else:
                            new_plot = ax.plot(xdata, ydata, marker, color='red', markersize=8)[0]
                    else:  # Line plot
                        new_plot = ax.plot(xdata, ydata, '-', color='red', linewidth=2)[0]

                    # Replace the old object with the new one
                    self.beam_current[beam_index] = new_plot

                except Exception as e:
                    # If there's any issue, just log it and continue
                    self._log(f"Error redrawing current beam position {beam_index}: {e}", LogLevel.WARNING)

        # Update canvas
        if hasattr(self, '_bp_canvas'):
            self._bp_canvas.draw()

    # Deflection stats update methods for 3x3 table
    def update_deflection_stats(self):
        """Update all deflection stats displays with current values."""
        if not hasattr(self, 'deflection_table_elements'):
            return

        # Update each beam's deflection, scan speed, and B-field values
        try:
            for beam_num in [1, 2, 3]:
                beam_index = beam_num - 1  # Convert to 0-based index
                
                # Check if beam is ON - only show values if beam is ON, otherwise show dashes
                if self.beam_on_status[beam_index]:
                    # Beam is ON - calculate and display values
                    amplitude = self.get_beam_amplitude(beam_index)
                    
                    # Get frequency, handling both tkinter Variable and plain float
                    if hasattr(self, 'frequency_hz'):
                        if isinstance(self.frequency_hz, tk.Variable):
                            frequency = self.frequency_hz.get()
                        else:
                            frequency = float(self.frequency_hz)
                    else:
                        frequency = 10.0

                    # Debug logging to see actual values
                    self._log(f"Beam {beam_num}: amplitude={amplitude:.2f}A, frequency={frequency:.1f}Hz", LogLevel.DEBUG)

                    # Calculate stats for this beam (may return None if out of LUT range)
                    deflection = self.calculate_beam_deflection_from_amplitude(amplitude)
                    scan_speed = self.calculate_scan_speed_from_frequency(frequency)
                    bfield = self.calculate_b_field_from_current(amplitude, beam_num)  # Pass beam number
                    power = self.calculate_solenoid_power_from_current(amplitude)

                    # Update table cells - show dashes if LUT lookup failed (returned None)
                    self.update_table_cell('deflection', beam_num, f"{deflection:.1f}" if deflection is not None else "--")
                    self.update_table_cell('scan_speed', beam_num, f"{scan_speed:.2f}" if scan_speed is not None else "--")
                    self.update_table_cell('bfield', beam_num, f"{bfield:.0f}" if bfield is not None else "--")
                    self.update_table_cell('power', beam_num, f"{power:.0f}" if power is not None else "--")
                else:
                    # Beam is OFF - display dashes
                    self.update_table_cell('deflection', beam_num, "--")
                    self.update_table_cell('scan_speed', beam_num, "--")
                    self.update_table_cell('bfield', beam_num, "--")
                    self.update_table_cell('power', beam_num, "--")

        except Exception as e:
            self._log(f"Error updating deflection table: {e}", LogLevel.WARNING)

    def update_table_cell(self, stat_type: str, beam: int, value: str):
        """Update a specific cell in the deflection stats table."""
        if not hasattr(self, 'deflection_table_elements'):
            return

        # All stats now use individual beam format
        key = f'{stat_type}_beam_{beam}'

        if key in self.deflection_table_elements:
            self.deflection_table_elements[key]['display'].configure(text=value)

    def set_deflection_est(self, value: float, beam: int = 1):
        """Set deflection estimate value for a specific beam and update display."""
        self.deflection_est.set(value)  # Keep for backward compatibility
        self.update_table_cell('deflection', beam, f"{value:.1f}")

    def set_scan_speed_est(self, value: float, beam: int = 1):
        """Set scan speed estimate value for a specific beam and update display."""
        self.scan_speed_est.set(value)  # Keep for backward compatibility
        self.update_table_cell('scan_speed', beam, f"{value:.2f}")

    def set_peak_bfield_est(self, value: float, beam: int = 1):
        """Set peak B-field estimate value for a specific beam and update display.

        Note: This method sets a manual override value. For automatic calculation
        based on current amplitude and beam position (center vs off-axis), use
        calculate_b_field_from_current() instead.
        """
        self.peak_bfield_est.set(value)  # Keep for backward compatibility
        self.update_table_cell('bfield', beam, f"{value:.0f}")

    def set_power_est(self, value: float, beam: int = 1):
        """Set power estimate value for a specific beam and update display."""
        self.power_est.set(value)  # Keep for backward compatibility
        self.update_table_cell('power', beam, f"{value:.0f}")

    def set_all_beams_power_est(self, value: float):
        """Set power estimate value for all beams and update displays."""
        self.power_est.set(value)  # Keep for backward compatibility
        for beam_num in [1, 2, 3]:
            self.update_table_cell('power', beam_num, f"{value:.0f}")

    def get_beam_amplitude(self, beam_index: int) -> float:
        """Get the amplitude for a specific beam (0-based index)."""
        try:
            # Try to read from hardware registers first (via bcon_driver)
            if hasattr(self, 'bcon_driver') and self.bcon_driver and self.bcon_driver.is_connected():
                register_name = f"BEAM_{beam_index + 1}_AMPLITUDE"
                result = self.read_register(register_name)
                if result is not None:
                    return float(result)
        except Exception as e:
            self._log(f"Error reading beam {beam_index + 1} amplitude from hardware: {e}", LogLevel.DEBUG)

        # Fallback to shared amplitude control
        if hasattr(self, 'wave_amplitude'):
            if isinstance(self.wave_amplitude, tk.Variable):
                return self.wave_amplitude.get()
            else:
                return float(self.wave_amplitude)
        return 5.0

    def get_deflection_est(self) -> float:
        """Get current deflection estimate value."""
        return self.deflection_est.get()

    def get_scan_speed_est(self) -> float:
        """Get current scan speed estimate value."""
        return self.scan_speed_est.get()

    def get_peak_bfield_est(self) -> float:
        """Get current peak B-field estimate value."""
        return self.peak_bfield_est.get()

    def get_power_est(self) -> float:
        """Get current power estimate value."""
        return self.power_est.get()

    def start_deflection_stats_monitoring(self):
        """Start periodic updates of deflection stats table using LUT data and formulas."""
        def update_loop():
            try:
                # Update the complete deflection stats table
                self.update_deflection_stats()
            except Exception as e:
                self._log(f"Error in deflection stats monitoring: {e}", LogLevel.WARNING)

            # Schedule next update (every 500ms for responsive updates)
            if hasattr(self, 'parent_frame') and self.parent_frame:
                self.parent_frame.after(500, update_loop)

        # Start the update loop
        if hasattr(self, 'parent_frame') and self.parent_frame:
            self.parent_frame.after(100, update_loop)  # Start after 100ms

    # --- Hardware Driver Interface ---
    # These methods delegate to the E5CNModbus-based driver for hardware communication

    def connect(self) -> bool:
        """Connect to BCON hardware via E5CNModbus driver."""
        if not self.bcon_driver:
            self._log("No BCON driver configured", LogLevel.ERROR)
            return False
        return self.bcon_driver.connect()

    def disconnect(self) -> None:
        """Disconnect from BCON hardware via driver."""
        if self.bcon_driver:
            self.bcon_driver.disconnect()

    def is_connected(self) -> bool:
        """Check if BCON hardware is connected via driver."""
        if self.bcon_driver:
            return self.bcon_driver.is_connected()
        return False

    def read_register(self, name: str) -> Optional[int]:
        """Read a register via BCON driver."""
        if not self.bcon_driver:
            self._log("No BCON driver configured", LogLevel.ERROR)
            return None
        return self.bcon_driver.read_register(name)

    def write_register(self, name: str, value: int) -> bool:
        """Write a register via BCON driver."""
        if not self.bcon_driver:
            self._log("No BCON driver configured", LogLevel.ERROR)
            return False
        return self.bcon_driver.write_register(name, value)

    def set_command(self, cmd: int) -> bool:
        """Set BCON command via driver."""
        if not self.bcon_driver:
            return False
        return self.bcon_driver.set_command(cmd)

    def direct_write_x(self, value: int) -> bool:
        """Direct write X via BCON driver."""
        if not self.bcon_driver:
            return False
        return self.bcon_driver.direct_write_x(value)

    def direct_write_y(self, value: int) -> bool:
        """Direct write Y via BCON driver."""
        if not self.bcon_driver:
            return False
        return self.bcon_driver.direct_write_y(value)

    def set_pulser_duty(self, pulser_index: int, duty: int) -> bool:
        """Set pulser duty via BCON driver."""
        if not self.bcon_driver:
            return False
        return self.bcon_driver.set_pulser_duty(pulser_index, duty)

    def set_pulser_duration(self, pulser_index: int, duration_ms: int) -> bool:
        """Set pulser duration via BCON driver."""
        if not self.bcon_driver:
            return False
        return self.bcon_driver.set_pulser_duration(pulser_index, duration_ms)

    def set_samples_rate(self, samples: int) -> bool:
        """Set samples rate via BCON driver."""
        if not self.bcon_driver:
            return False
        return self.bcon_driver.set_samples_rate(samples)

    def set_beam_parameters(self, beam_index: int, amplitude: Optional[int] = None, phase: Optional[int] = None, offset: Optional[int] = None) -> Dict[str, bool]:
        """Set beam parameters via BCON driver."""
        if not self.bcon_driver:
            return {}
        return self.bcon_driver.set_beam_parameters(beam_index, amplitude, phase, offset)

    def read_all(self) -> Dict[str, Optional[int]]:
        """Read all registers via BCON driver."""
        if not self.bcon_driver:
            return {}
        return self.bcon_driver.read_all()

    # --- Safety / Shutdown Helpers ---
    def arm_beams(self) -> bool:
        """Arm the beam system for operation.

        This method prepares the beam system for operation by performing necessary
        initialization and safety checks. Returns True if arming is successful.

        NOTE: Currently configured for demonstration - always returns success.
        """
        try:
            # DEMONSTRATION MODE: Always show successful arming
            # TODO: Replace with actual beam arming logic when hardware is integrated

            # Simulate arming sequence
            self._log("Initiating beam arming sequence...", LogLevel.INFO)

            # For demonstration purposes, always succeed
            # TODO: Add actual hardware initialization commands here
            # Example: Check BCON driver connection, set initial parameters, verify safety interlocks, etc.

            # Set armed status
            self.beams_armed_status = True

            # Keep beams off when armed - they need to be manually toggled
            # (LEDs will remain red until individual beams are turned on)

            self._log("Beams successfully armed and ready for operation", LogLevel.INFO)

            return True

        except Exception as e:
            self._log(f"Failed to arm beams: {str(e)}", LogLevel.ERROR)
            self.beams_armed_status = False
            return False

    def disarm_beams(self) -> bool:
        """Disarm the beam system.

        This method safely disarms the beam system and returns it to a safe state.
        Returns True if disarming is successful.
        """
        try:
            self._log("Disarming beam system...", LogLevel.INFO)

            # TODO: Add actual beam disarming logic here
            # Example: Turn off outputs, reset parameters, etc.

            # Set armed status
            self.beams_armed_status = False

            # Turn off all beam LEDs when disarmed
            self.set_all_beams_status(False)

            self._log("Beams successfully disarmed", LogLevel.INFO)

            return True

        except Exception as e:
            self._log(f"Failed to disarm beams: {str(e)}", LogLevel.ERROR)
            return False

    def get_beams_armed_status(self) -> bool:
        """Get current beams armed status."""
        return self.beams_armed_status

    def safe_shutdown(self, reason: Optional[str] = None) -> bool:
        """Perform a safe shutdown of pulses/waveforms on the BCON device.

        This tries to set pulser duties and durations to zero and place the
        device in a safe command state via the BCON driver. Returns True if
        all writes succeed.
        """
        self._log(f"Initiating safe shutdown: {reason}", LogLevel.INFO)

        if not self.bcon_driver:
            self._log("No BCON driver available for safe shutdown", LogLevel.ERROR)
            return False

        ok = True
        try:
            # zero pulser duties via BCON driver
            for i in (1, 2, 3):
                try:
                    if not self.bcon_driver.set_pulser_duty(i, 0):
                        ok = False
                except Exception:
                    ok = False

            # zero durations via BCON driver
            for i in (1, 2, 3):
                try:
                    if not self.bcon_driver.set_pulser_duration(i, 0):
                        ok = False
                except Exception:
                    ok = False

            # set safe command (use 0 as default direct write mode which won't start waves)
            try:
                if not self.bcon_driver.set_command(0):
                    ok = False
            except Exception:
                ok = False

        except Exception as e:
            self._log(f"Exception during safe_shutdown: {e}", LogLevel.ERROR)
            return False

        if ok:
            self._log("Safe shutdown completed", LogLevel.INFO)
        else:
            self._log("Safe shutdown encountered errors", LogLevel.WARNING)
        return ok

    # --- internal helpers ---
    def _log(self, msg: str, level: LogLevel = LogLevel.INFO) -> None:
        if self.logger:
            self.logger.log(msg, level)
        else:
            print(f"{level.name}: {msg}")


if __name__ == "__main__":
    # Quick manual smoke test. Use for development.
    import argparse

    parser = argparse.ArgumentParser(description="BeamPulseSubsystem quick test")
    parser.add_argument("--port", default="COM1", help="Serial port for Modbus")
    parser.add_argument("--unit", type=int, default=1, help="Modbus slave id")
    parser.add_argument("--read-all", action="store_true", help="Read all registers")
    args = parser.parse_args()

    # Create BeamPulseSubsystem - it will instantiate E5CNModbus internally
    b = BeamPulseSubsystem(
        port=args.port,
        unit=args.unit,
        baudrate=115200,
        debug=True
    )

    if not b.connect():
        print("Could not connect to device; aborting smoke test")
    else:
        if args.read_all:
            vals = b.read_all()
            for k, v in vals.items():
                print(f"{k}: {v}")
        b.disconnect()
