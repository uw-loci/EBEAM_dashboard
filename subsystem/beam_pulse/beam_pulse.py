import time
import tkinter as tk
from tkinter import ttk
from typing import Optional, Dict
import os
import sys

from instrumentctl.E5CN_modbus.E5CN_modbus import E5CNModbus
from utils import LogLevel

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
    """Driver for the Beam Pulse subsystem (BCON) using the E5CN Modbus client.

    This class provides both the hardware driver functionality and GUI interface
    for the beam pulse control system.

    Contract:
      - Inputs: serial port and Modbus unit id (slave id)
      - Outputs: read/write access to BCON registers over Modbus
      - Error modes: connection failures return None/False and log errors

    This maps high-level methods to the register map provided in the project
    documentation. Registers are zero-based addresses matching the device map.
    """

    # Register addresses (zero-based)
    REGISTER = {
        "COMMAND": 0,
        "X_DIRECT_WRITE": 1,
        "Y_DIRECT_WRITE": 2,
        "PULSER_1_DUTY": 3,
        "PULSER_2_DUTY": 4,
        "PULSER_3_DUTY": 5,
        "PULSER_1_DURATION": 6,
        "PULSER_2_DURATION": 7,
        "PULSER_3_DURATION": 8,
        "SAMPLES_RATE": 9,
        # Following registers are sequential for beams 1..3: amplitude, phase, offset
        "BEAM_1_AMPLITUDE": 10,
        "BEAM_1_PHASE": 11,
        "BEAM_1_OFFSET": 12,
        "BEAM_2_AMPLITUDE": 13,
        "BEAM_2_PHASE": 14,
        "BEAM_2_OFFSET": 15,
        "BEAM_3_AMPLITUDE": 16,
        "BEAM_3_PHASE": 17,
        "BEAM_3_OFFSET": 18,
    }

    def __init__(self, parent_frame=None, port: str = None, unit: int = 1, baudrate: int = 115200, timeout: int = 1, logger=None, debug: bool = False):
        """Create the BeamPulseSubsystem.

        Parameters:
            parent_frame: tkinter frame for GUI components (if None, no GUI created)
            port: serial port (e.g. 'COM3')
            unit: Modbus slave id for the BCON device
            baudrate, timeout: serial parameters passed to E5CNModbus
            logger: optional logger object compatible with utils.LogLevel
            debug: enable debug logs
        """
        self.parent_frame = parent_frame
        self.unit = unit
        self.logger = logger
        self.debug = debug

        # GUI variables for controls
        self.wave_gen_enabled = tk.BooleanVar(value=False)
        self.wave_type = tk.StringVar(value="Triangle")
        self.frequency_hz = tk.DoubleVar(value=1000.0)
        self.wave_amplitude = tk.DoubleVar(value=5.0)
        self.expected_current = tk.DoubleVar(value=1.0)
        
        # Toggle state for wave gen
        self.wave_gen_toggle_state = False
        
        # Status indicators
        self.bop_amp_status = False
        self.sol1_temp_status = False  
        self.sol2_temp_status = False

        # Deflection stats variables
        self.deflection_est = tk.DoubleVar(value=5.0)
        self.scan_speed_est = tk.DoubleVar(value=1.5)
        self.peak_bfield_est = tk.DoubleVar(value=90.0)
        self.power_est = tk.DoubleVar(value=150.0)

        # Plot variables
        self._bp_fig = None
        self._bp_axes = None
        self._bp_canvas = None
        self._bp_stats = {}
        
        # Monitor plot variables
        self._monitor_fig = None
        self._monitor_ax = None
        self._monitor_canvas = None

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

        # Hardware connection (only if port is provided)
        self.modbus = None
        if port:
            self.modbus = E5CNModbus(port=port, baudrate=baudrate, timeout=timeout, logger=logger, debug_mode=debug)

        # Create GUI if parent frame is provided
        if parent_frame:
            self.setup_ui()

    def setup_ui(self):
        """Create the user interface with controls in a row at the top and plots below."""
        # Main container frame
        main_frame = ttk.Frame(self.parent_frame, padding="5")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Top control row frame
        control_row = ttk.Frame(main_frame)
        control_row.pack(fill=tk.X, pady=(0, 10))
        
        # Create control columns with labels on top and controls below
        self.create_wave_gen_control(control_row, 0)
        self.create_wave_type_control(control_row, 1)
        self.create_frequency_control(control_row, 2)
        self.create_wave_amplitude_control(control_row, 3)
        self.create_bop_amp_status(control_row, 4)
        self.create_expected_current_control(control_row, 5)
        self.create_sol1_temp_status(control_row, 6)
        self.create_sol2_temp_status(control_row, 7)
        
        # Configure column weights for responsive layout
        for i in range(8):
            control_row.grid_columnconfigure(i, weight=1)
        
        # Bottom section with three columns: deflection stats, monitor graph, print bed plots
        bottom_frame = ttk.Frame(main_frame)
        bottom_frame.pack(fill=tk.BOTH, expand=True)
        
        # Left side - Deflection Stats (30% width)
        deflection_frame = ttk.Frame(bottom_frame)
        deflection_frame.pack(side=tk.LEFT, fill=tk.BOTH, padx=(0, 5))
        self.create_deflection_stats(deflection_frame)
        
        # Middle - Current Driver Monitor graph (35% width)
        monitor_frame = ttk.Frame(bottom_frame)
        monitor_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5)
        self.create_current_driver_monitor(monitor_frame)
        
        # Right side - Print Bed label and plots (35% width)
        plots_container = ttk.Frame(bottom_frame)
        plots_container.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(5, 0))
        
        # Print Bed label above plots
        print_bed_label = ttk.Label(plots_container, text="Print Bed", font=("Arial", 12, "bold"))
        print_bed_label.pack(pady=(0, 10))
        
        # Plots frame
        plots_frame = ttk.Frame(plots_container)
        plots_frame.pack(fill=tk.BOTH, expand=True)
        
        # Create the plots
        self.create_plots(plots_frame)
        
        # Start live monitoring of deflection stats (optional demo)
        # Remove this line if you don't want the demo animation
        self.start_deflection_stats_monitoring()

    def create_wave_gen_control(self, parent, column):
        """Create Wave Gen toggle control."""
        frame = ttk.Frame(parent)
        frame.grid(row=0, column=column, padx=5, pady=2, sticky="ew")
        
        # Label
        ttk.Label(frame, text="Wave Gen", font=("Arial", 9, "bold")).pack()
        
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
        
        # Dropdown (Combobox)
        wave_types = ["Triangle", "Sine", "Square", "Sawtooth"]
        self.wave_type_combo = ttk.Combobox(
            frame,
            textvariable=self.wave_type,
            values=wave_types,
            state="readonly",
            width=10
        )
        self.wave_type_combo.pack(pady=(2, 0))
        self.wave_type_combo.bind("<<ComboboxSelected>>", self.on_wave_type_change)

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
            to=10000.0,
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
        ttk.Label(frame, text="Wave Amp (+-V)", font=("Arial", 9, "bold")).pack()
        
        # Spinbox
        self.wave_amp_spinbox = tk.Spinbox(
            frame,
            from_=0.0,
            to=50.0,
            increment=1.0,  # Changed from 0.1 to 1.0
            textvariable=self.wave_amplitude,
            command=self.on_wave_amplitude_change,
            width=8,
            format="%.1f"
        )
        self.wave_amp_spinbox.pack(pady=(2, 0))

    def create_bop_amp_status(self, parent, column):
        """Create BOP Amp status indicator."""
        frame = ttk.Frame(parent)
        frame.grid(row=0, column=column, padx=5, pady=2, sticky="ew")
        
        # Label
        ttk.Label(frame, text="BOP Amp", font=("Arial", 9, "bold")).pack()
        
        # Circular status indicator
        self.bop_amp_canvas = tk.Canvas(frame, width=20, height=20, highlightthickness=0)
        self.bop_amp_canvas.pack(pady=(2, 0))
        self.update_bop_amp_status()

    def create_expected_current_control(self, parent, column):
        """Create Expected Current (+- A) spinbox control."""
        frame = ttk.Frame(parent)
        frame.grid(row=0, column=column, padx=5, pady=2, sticky="ew")
        
        # Label
        ttk.Label(frame, text="Expected Current (+- A)", font=("Arial", 9, "bold")).pack()
        
        # Spinbox
        self.expected_current_spinbox = tk.Spinbox(
            frame,
            from_=0.0,
            to=100.0,
            increment=1.0,  # Changed from 0.1 to 1.0
            textvariable=self.expected_current,
            command=self.on_expected_current_change,
            width=8,
            format="%.1f"
        )
        self.expected_current_spinbox.pack(pady=(2, 0))

    def create_sol1_temp_status(self, parent, column):
        """Create Sol 1 Temp status indicator."""
        frame = ttk.Frame(parent)
        frame.grid(row=0, column=column, padx=5, pady=2, sticky="ew")
        
        # Label
        ttk.Label(frame, text="Sol 1 Temp", font=("Arial", 9, "bold")).pack()
        
        # Circular status indicator
        self.sol1_temp_canvas = tk.Canvas(frame, width=20, height=20, highlightthickness=0)
        self.sol1_temp_canvas.pack(pady=(2, 0))
        self.update_sol1_temp_status()

    def create_sol2_temp_status(self, parent, column):
        """Create Sol 2 Temp status indicator."""
        frame = ttk.Frame(parent)
        frame.grid(row=0, column=column, padx=5, pady=2, sticky="ew")
        
        # Label
        ttk.Label(frame, text="Sol 2 Temp", font=("Arial", 9, "bold")).pack()
        
        # Circular status indicator
        self.sol2_temp_canvas = tk.Canvas(frame, width=20, height=20, highlightthickness=0)
        self.sol2_temp_canvas.pack(pady=(2, 0))
        self.update_sol2_temp_status()

    def create_deflection_stats(self, parent):
        """Create the Deflection Stats section with four live status displays."""
        # Title frame
        title_frame = ttk.Frame(parent)
        title_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(title_frame, text="Deflection Stats", font=("Arial", 12, "bold")).pack()
        
        # Stats container with proper spacing
        stats_container = ttk.Frame(parent, padding="5")
        stats_container.pack(fill=tk.BOTH, expand=True)
        
        # Define the stats with their labels, variables, units, and default values
        stats_data = [
            ("Deflection Est.:", self.deflection_est, "cm", "5.0"),
            ("Scan Speed Est.:", self.scan_speed_est, "m/s", "1.5"),
            ("Peak B-field Est.:", self.peak_bfield_est, "G", "90"),
            ("Power Est:", self.power_est, "W", "150")
        ]
        
        # Store references for later updates
        if not hasattr(self, 'deflection_ui_elements'):
            self.deflection_ui_elements = {}
        
        # Create each stat display
        for i, (label_text, variable, unit, default_value) in enumerate(stats_data):
            # Individual stat frame
            stat_frame = ttk.Frame(stats_container)
            stat_frame.pack(fill=tk.X, pady=3)
            
            # Label
            ttk.Label(stat_frame, text=label_text, font=("Segoe UI", 8)).pack(anchor=tk.W)
            
            # Value display with units
            value_display = ttk.Label(
                stat_frame,
                text=f"{default_value} {unit}",
                font=("Arial", 11, "bold"),  # Changed from Consolas to Arial
                background="white",
                relief="sunken",
                width=12,
                anchor=tk.CENTER
            )
            value_display.pack(fill=tk.X, pady=(1, 0))
            
            # Store reference for updates
            self.deflection_ui_elements[f'stat_{i}'] = {
                'display': value_display,
                'variable': variable,
                'unit': unit,
                'default': default_value
            }

    def create_current_driver_monitor(self, parent):
        """Create the Current Driver Monitor graph with time vs oil temperature."""
        if not _HAS_MATPLOTLIB:
            lbl = ttk.Label(parent, text="matplotlib not available — install matplotlib to see plot")
            lbl.pack(fill=tk.BOTH, expand=True)
            return

        # Title label
        title_label = ttk.Label(parent, text="Current Driver Monitor (sync1)", font=("Arial", 12, "bold"))
        title_label.pack(pady=(0, 10))

        # Create matplotlib figure for the monitor graph
        # Adjusted figure size to be more compact and maintain better proportions
        monitor_fig = Figure(figsize=(3.5, 2.5), constrained_layout=True)
        monitor_ax = monitor_fig.add_subplot(1, 1, 1)
        
        # Configure the plot
        monitor_ax.set_xlabel('Time (HH:MM)', fontsize=9)
        monitor_ax.set_ylabel('Oil Temperature', fontsize=9)
        monitor_ax.tick_params(labelsize=8)
        monitor_ax.grid(True)
        
        # Set Y-axis limits and ticks (0 to 100 with ticks every 20)
        monitor_ax.set_ylim(0, 100)
        monitor_ax.set_yticks(range(0, 101, 20))  # 0, 20, 40, 60, 80, 100
        
        # Set aspect ratio to prevent stretching
        monitor_ax.set_aspect('auto')  # Let matplotlib handle aspect ratio automatically
        
        # Format time axis (placeholder for now)
        from matplotlib.dates import DateFormatter
        import matplotlib.dates as mdates
        monitor_ax.xaxis.set_major_formatter(DateFormatter('%H:%M'))
        
        # Store references
        self._monitor_fig = monitor_fig
        self._monitor_ax = monitor_ax
        
        # Create and pack the canvas with proper sizing
        self._monitor_canvas = FigureCanvasTkAgg(monitor_fig, master=parent)
        canvas_widget = self._monitor_canvas.get_tk_widget()
        canvas_widget.pack(fill=tk.BOTH, expand=True)
        
        # Set minimum size constraints to prevent over-stretching
        canvas_widget.configure(width=300, height=200)  # Set reasonable minimum dimensions

    def create_plots(self, parent):
        """Create the three beam plots similar to the original dashboard implementation."""
        if not _HAS_MATPLOTLIB:
            lbl = ttk.Label(parent, text="matplotlib not available — install matplotlib to see plots")
            lbl.pack(fill=tk.BOTH, expand=True)
            return

        # Create a matplotlib figure with 3 subplots laid out horizontally (1 row x 3 cols)
        # Make them smaller to fit in the right portion
        fig = Figure(figsize=(6, 2), constrained_layout=True)
        axs = [fig.add_subplot(1, 3, i + 1) for i in range(3)]
        
        # Add horizontal spacing between subplots
        try:
            fig.subplots_adjust(wspace=0.45)
        except Exception:
            pass
            
        for ax in axs:
            ax.set_xlabel('sample index', fontsize=7)
            ax.set_ylabel('value', fontsize=7)
            ax.tick_params(labelsize=6)
            ax.title.set_fontsize(8)
            ax.grid(True)

        self._bp_fig = fig
        self._bp_axes = axs
        self._bp_canvas = FigureCanvasTkAgg(fig, master=parent)
        self._bp_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # Stats panel under each subplot
        stats_frame = ttk.Frame(parent)
        stats_frame.pack(fill=tk.X, pady=(5, 0))
        
        for i in (1, 2, 3):
            f = ttk.Frame(stats_frame, padding=2, relief='groove')
            f.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=1, pady=1)
            ttk.Label(f, text=f'Beam {i} stats', font=('Helvetica', 8, 'bold')).pack(anchor='nw')
            last_lbl = ttk.Label(f, text='Last: N/A', font=('Helvetica', 7))
            last_lbl.pack(anchor='nw')
            mean_lbl = ttk.Label(f, text='Mean: N/A', font=('Helvetica', 7))
            mean_lbl.pack(anchor='nw')
            min_lbl = ttk.Label(f, text='Min: N/A', font=('Helvetica', 7))
            min_lbl.pack(anchor='nw')
            max_lbl = ttk.Label(f, text='Max: N/A', font=('Helvetica', 7))
            max_lbl.pack(anchor='nw')
            self._bp_stats[i] = {'last': last_lbl, 'mean': mean_lbl, 'min': min_lbl, 'max': max_lbl}

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
        
        self._log(f"Wave Gen {'enabled' if self.wave_gen_toggle_state else 'disabled'}", LogLevel.DEBUG)

    def on_wave_gen_change(self, value=None):
        """Handle wave generator slider change (legacy method for compatibility)."""
        self._log(f"Wave Gen changed to: {self.wave_gen_enabled.get()}", LogLevel.DEBUG)

    def on_wave_type_change(self, event=None):
        """Handle wave type dropdown change."""
        self._log(f"Wave Type changed to: {self.wave_type.get()}", LogLevel.DEBUG)

    def on_frequency_change(self):
        """Handle frequency spinbox change."""
        self._log(f"Frequency changed to: {self.frequency_hz.get()} Hz", LogLevel.DEBUG)

    def on_wave_amplitude_change(self):
        """Handle wave amplitude spinbox change."""
        self._log(f"Wave Amplitude changed to: {self.wave_amplitude.get()} V", LogLevel.DEBUG)

    def on_expected_current_change(self):
        """Handle expected current spinbox change."""
        self._log(f"Expected Current changed to: {self.expected_current.get()} A", LogLevel.DEBUG)

    # Status indicator update methods
    def update_bop_amp_status(self):
        """Update BOP Amp status indicator."""
        color = "green" if self.bop_amp_status else "red"
        self.bop_amp_canvas.delete("all")
        self.bop_amp_canvas.create_oval(2, 2, 18, 18, fill=color, outline="darkgray")

    def update_sol1_temp_status(self):
        """Update Sol 1 Temp status indicator."""
        color = "green" if self.sol1_temp_status else "red"
        self.sol1_temp_canvas.delete("all")
        self.sol1_temp_canvas.create_oval(2, 2, 18, 18, fill=color, outline="darkgray")

    def update_sol2_temp_status(self):
        """Update Sol 2 Temp status indicator."""
        color = "green" if self.sol2_temp_status else "red"
        self.sol2_temp_canvas.delete("all")
        self.sol2_temp_canvas.create_oval(2, 2, 18, 18, fill=color, outline="darkgray")

    # Status update methods for external use
    def set_bop_amp_status(self, status: bool):
        """Set BOP Amp status and update indicator."""
        self.bop_amp_status = status
        if hasattr(self, 'bop_amp_canvas'):
            self.update_bop_amp_status()

    def set_sol1_temp_status(self, status: bool):
        """Set Sol 1 Temp status and update indicator."""
        self.sol1_temp_status = status
        if hasattr(self, 'sol1_temp_canvas'):
            self.update_sol1_temp_status()

    def set_sol2_temp_status(self, status: bool):
        """Set Sol 2 Temp status and update indicator."""
        self.sol2_temp_status = status
        if hasattr(self, 'sol2_temp_canvas'):
            self.update_sol2_temp_status()

    # Deflection stats update methods
    def update_deflection_stats(self):
        """Update all deflection stats displays with current values."""
        if not hasattr(self, 'deflection_ui_elements'):
            return
            
        for key, element in self.deflection_ui_elements.items():
            try:
                current_value = element['variable'].get()
                unit = element['unit']
                element['display'].configure(text=f"{current_value} {unit}")
            except Exception as e:
                self._log(f"Error updating deflection stat {key}: {e}", LogLevel.WARNING)

    def set_deflection_est(self, value: float):
        """Set deflection estimate value and update display."""
        self.deflection_est.set(value)
        if hasattr(self, 'deflection_ui_elements') and 'stat_0' in self.deflection_ui_elements:
            unit = self.deflection_ui_elements['stat_0']['unit']
            self.deflection_ui_elements['stat_0']['display'].configure(text=f"{value} {unit}")

    def set_scan_speed_est(self, value: float):
        """Set scan speed estimate value and update display."""
        self.scan_speed_est.set(value)
        if hasattr(self, 'deflection_ui_elements') and 'stat_1' in self.deflection_ui_elements:
            unit = self.deflection_ui_elements['stat_1']['unit']
            self.deflection_ui_elements['stat_1']['display'].configure(text=f"{value} {unit}")

    def set_peak_bfield_est(self, value: float):
        """Set peak B-field estimate value and update display."""
        self.peak_bfield_est.set(value)
        if hasattr(self, 'deflection_ui_elements') and 'stat_2' in self.deflection_ui_elements:
            unit = self.deflection_ui_elements['stat_2']['unit']
            self.deflection_ui_elements['stat_2']['display'].configure(text=f"{value} {unit}")

    def set_power_est(self, value: float):
        """Set power estimate value and update display."""
        self.power_est.set(value)
        if hasattr(self, 'deflection_ui_elements') and 'stat_3' in self.deflection_ui_elements:
            unit = self.deflection_ui_elements['stat_3']['unit']
            self.deflection_ui_elements['stat_3']['display'].configure(text=f"{value} {unit}")

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
        """Start periodic updates of deflection stats (example of live updates)."""
        def update_loop():
            # Example: Update deflection stats based on some calculations or hardware readings
            # You can replace this with actual hardware readings or calculations
            
            # Example simulation - you would replace with real data
            import time
            import math
            
            # Simulate some varying values
            time_factor = time.time() % 10  # 10 second cycle
            
            # Example calculations (replace with real logic)
            deflection = 5.0 + 2.0 * math.sin(time_factor)
            scan_speed = 1.5 + 0.3 * math.cos(time_factor) 
            b_field = 90 + 10 * math.sin(time_factor * 0.5)
            power = 150 + 25 * math.cos(time_factor * 0.3)
            
            # Update the displays
            self.set_deflection_est(round(deflection, 1))
            self.set_scan_speed_est(round(scan_speed, 1))
            self.set_peak_bfield_est(round(b_field, 0))
            self.set_power_est(round(power, 0))
            
            # Schedule next update (every 1000ms = 1 second)
            if hasattr(self, 'parent_frame') and self.parent_frame:
                self.parent_frame.after(1000, update_loop)
        
        # Start the update loop
        if hasattr(self, 'parent_frame') and self.parent_frame:
            self.parent_frame.after(100, update_loop)  # Start after 100ms

    # --- connection management ---
    def connect(self) -> bool:
        """Open Modbus connection to the device."""
        if not self.modbus:
            self._log("No Modbus connection configured", LogLevel.ERROR)
            return False
        return self.modbus.connect()

    def disconnect(self) -> None:
        """Close Modbus connection."""
        if self.modbus:
            self.modbus.disconnect()

    # --- basic register primitives ---
    def read_register(self, name: str) -> Optional[int]:
        """Read a single holding register by name. Returns integer or None on error."""
        if not self.modbus:
            self._log("No Modbus connection configured", LogLevel.ERROR)
            return None
            
        if name not in self.REGISTER:
            self._log(f"Unknown register name: {name}", LogLevel.ERROR)
            return None

        addr = self.REGISTER[name]
        try:
            with self.modbus.modbus_lock:
                if not self.modbus.client.is_socket_open():
                    if not self.modbus.connect():
                        return None

                resp = self.modbus.client.read_holding_registers(address=addr, count=1, slave=self.unit)

            if resp and not resp.isError():
                return int(resp.registers[0])
            else:
                self._log(f"Read error for {name} (addr={addr}): {resp}", LogLevel.ERROR)
                return None

        except Exception as e:
            self._log(f"Exception reading register {name}: {e}", LogLevel.ERROR)
            return None

    def write_register(self, name: str, value: int) -> bool:
        """Write a single holding register by name. Returns True on success."""
        if not self.modbus:
            self._log("No Modbus connection configured", LogLevel.ERROR)
            return False
            
        if name not in self.REGISTER:
            self._log(f"Unknown register name: {name}", LogLevel.ERROR)
            return False

        addr = self.REGISTER[name]
        try:
            with self.modbus.modbus_lock:
                if not self.modbus.client.is_socket_open():
                    if not self.modbus.connect():
                        return False

                # write single 16-bit register
                resp = self.modbus.client.write_register(address=addr, value=int(value), slave=self.unit)

            if resp and not getattr(resp, 'isError', lambda: False)():
                return True
            else:
                self._log(f"Write error for {name} (addr={addr}, value={value}): {resp}", LogLevel.ERROR)
                return False

        except Exception as e:
            self._log(f"Exception writing register {name}: {e}", LogLevel.ERROR)
            return False

    # --- convenience helpers for BCON functionality ---
    def set_command(self, cmd: int) -> bool:
        """Write the COMMAND register (register 0)."""
        return self.write_register("COMMAND", cmd)

    def direct_write_x(self, value: int) -> bool:
        """Direct write to DAC X (register 1)."""
        return self.write_register("X_DIRECT_WRITE", value)

    def set_pulser_duty(self, pulser_index: int, duty: int) -> bool:
        """Set pulser duty (0..255) for pulser_index 1..3."""
        if pulser_index not in (1, 2, 3):
            self._log("pulser_index must be 1..3", LogLevel.ERROR)
            return False
        name = f"PULSER_{pulser_index}_DUTY"
        if duty < 0 or duty > 0xFF:
            self._log("duty must be 0..255", LogLevel.ERROR)
            return False
        return self.write_register(name, duty)

    def set_pulser_duration(self, pulser_index: int, duration_ms: int) -> bool:
        """Set pulser duration in milliseconds (Uint16) for pulser_index 1..3."""
        if pulser_index not in (1, 2, 3):
            self._log("pulser_index must be 1..3", LogLevel.ERROR)
            return False
        name = f"PULSER_{pulser_index}_DURATION"
        if duration_ms < 0 or duration_ms > 0xFFFF:
            self._log("duration_ms out of range 0..65535", LogLevel.ERROR)
            return False
        return self.write_register(name, duration_ms)

    def set_samples_rate(self, samples: int) -> bool:
        """Set SAMPLES_RATE (Uint16). Default device uses 8192."""
        if samples <= 0 or samples > 0xFFFF:
            self._log("samples out of range", LogLevel.ERROR)
            return False
        return self.write_register("SAMPLES_RATE", samples)

    def set_beam_parameters(self, beam_index: int, amplitude: Optional[int] = None, phase: Optional[int] = None, offset: Optional[int] = None) -> Dict[str, bool]:
        """Set amplitude/phase/offset for beam 1..3. Values are Uint16.

        Returns a dict of results per field.
        """
        if beam_index not in (1, 2, 3):
            self._log("beam_index must be 1..3", LogLevel.ERROR)
            return {}

        base = (beam_index - 1) * 3
        names = ["BEAM_{}_AMPLITUDE", "BEAM_{}_PHASE", "BEAM_{}_OFFSET"]
        results = {}
        mapping = {
            "amplitude": (names[0].format(beam_index), amplitude),
            "phase": (names[1].format(beam_index), phase),
            "offset": (names[2].format(beam_index), offset),
        }

        for key, (regname, val) in mapping.items():
            if val is None:
                results[key] = False
                continue
            if val < 0 or val > 0xFFFF:
                self._log(f"{key} value out of range 0..65535: {val}", LogLevel.ERROR)
                results[key] = False
                continue
            results[key] = self.write_register(regname, val)

        return results

    def read_all(self) -> Dict[str, Optional[int]]:
        """Read all defined registers and return a mapping name->value (or None on error)."""
        out = {}
        for name in sorted(self.REGISTER.keys(), key=lambda n: self.REGISTER[n]):
            out[name] = self.read_register(name)
            # small pause to avoid overwhelming the serial link
            time.sleep(0.01)
        return out

    # --- safety / shutdown helpers ---
    def safe_shutdown(self, reason: Optional[str] = None) -> bool:
        """Perform a safe shutdown of pulses/waveforms on the BCON device.

        This tries to set pulser duties and durations to zero and place the
        device in a safe command state. Returns True if all writes succeed.
        """
        self._log(f"Initiating safe shutdown: {reason}", LogLevel.INFO)
        ok = True
        try:
            # zero pulser duties
            for i in (1, 2, 3):
                try:
                    self.write_register(f"PULSER_{i}_DUTY", 0)
                except Exception:
                    ok = False

            # zero durations
            for i in (1, 2, 3):
                try:
                    self.write_register(f"PULSER_{i}_DURATION", 0)
                except Exception:
                    ok = False

            # set safe command (use 0 as default direct write mode which won't start waves)
            try:
                self.set_command(0)
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
    # Quick manual smoke test (won't run without a real device). Use for development.
    import argparse

    parser = argparse.ArgumentParser(description="BeamPulseSubsystem quick test")
    parser.add_argument("--port", default="COM1", help="Serial port for Modbus")
    parser.add_argument("--unit", type=int, default=1, help="Modbus slave id")
    parser.add_argument("--read-all", action="store_true", help="Read all registers")
    args = parser.parse_args()

    b = BeamPulseSubsystem(port=args.port, unit=args.unit, debug=True)
    if not b.connect():
        print("Could not connect to device; aborting smoke test")
    else:
        if args.read_all:
            vals = b.read_all()
            for k, v in vals.items():
                print(f"{k} ({b.REGISTER[k]}): {v}")
        b.disconnect()
