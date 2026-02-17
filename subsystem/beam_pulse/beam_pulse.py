import time
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional, Dict
import os
import sys

from instrumentctl.E5CN_modbus.E5CN_modbus import E5CNModbus
from utils import LogLevel

def resource_path(relative_path):
    """Get absolute path to resource for PyInstaller."""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


class BeamPulseSubsystem:
    """Beam Pulse subsystem (BCON) with GUI interface for pulser controls.

    This class provides the GUI interface and high-level control logic for the beam
    pulse control system (pulser controls only). Hardware communication
    uses the project's E5CNModbus wrapper for serial/Modbus I/O.

    Contract:
      - Inputs: E5CNModbus-based driver instance for hardware communication
      - Outputs: GUI controls for pulsing behavior and beam durations
      - Error modes: hardware failures are handled by the underlying driver
    """

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
            # GUI variables for controls - only pulsing behavior
            self.pulsing_behavior = tk.StringVar(value="DC")  # Default to DC mode

            # Pulse duration variables for each beam (A, B, C)
            self.beam_a_duration = tk.DoubleVar(value=50.0)
            self.beam_b_duration = tk.DoubleVar(value=50.0)
            self.beam_c_duration = tk.DoubleVar(value=50.0)
        else:
            # Non-GUI mode: use simple values
            self.pulsing_behavior = "DC"
            self.beam_a_duration = 50.0
            self.beam_b_duration = 50.0
            self.beam_c_duration = 50.0

        # Status indicators
        self.bcon_connection_status = False  # BCON connected status
        self.beams_armed_status = False  # Beams armed status

        # Beam on/off status for each beam (A, B, C)
        self.beam_on_status = [False, False, False]  # [Beam A, Beam B, Beam C]

        # Store references to duration spinboxes for enable/disable control
        self.duration_spinboxes = []

        # Dashboard integration callback
        self._dashboard_beam_callback = None

        # Hardware connection through BCON driver
        # Driver should be initialized externally and passed in

        # Create GUI if parent frame is provided
        if parent_frame:
            self.setup_ui()

    def setup_ui(self):
        """Create the user interface with Main tab."""
        # Create notebook for tabs
        self.notebook = ttk.Notebook(self.parent_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Create Main tab
        self.main_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.main_tab, text="Main")

        # Setup Main tab content
        self.setup_main_tab()

        # Start BCON connection monitoring
        self.start_bcon_connection_monitoring()

    def setup_main_tab(self):
        """Setup the Main tab with pulser controls."""
        # Main container frame
        main_frame = ttk.Frame(self.main_tab, padding="5")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Top control row frame for BCON connection status
        control_row = ttk.Frame(main_frame)
        control_row.pack(fill=tk.X, pady=(0, 5))

        # BCON connection status
        self.create_bcon_connection_status(control_row, 0)

        # Configure column weights for responsive layout
        control_row.grid_columnconfigure(0, weight=1)

        # Second control row for Pulsing Behavior and pulse duration controls
        pulse_row = ttk.Frame(main_frame)
        pulse_row.pack(fill=tk.X, pady=(0, 10))

        # Create Pulsing Behavior and pulse duration controls
        # Use columns 1-4 with spacer columns 0 and 5 for centering
        self.create_pulsing_behavior_control(pulse_row, 1)
        self.create_beam_duration_control(pulse_row, 2, "Beam A Duration (ms)",
                                           self.beam_a_duration)
        self.create_beam_duration_control(pulse_row, 3, "Beam B Duration (ms)",
                                           self.beam_b_duration)
        self.create_beam_duration_control(pulse_row, 4, "Beam C Duration (ms)",
                                           self.beam_c_duration)

        # Configure column weights for pulse row (6 columns total)
        pulse_row.grid_columnconfigure(0, weight=1)  # Left spacer
        pulse_row.grid_columnconfigure(1, weight=0)  # Pulsing Behavior (no expansion)
        pulse_row.grid_columnconfigure(2, weight=0)  # Beam A (no expansion)
        pulse_row.grid_columnconfigure(3, weight=0)  # Beam B (no expansion)
        pulse_row.grid_columnconfigure(4, weight=0)  # Beam C (no expansion)
        pulse_row.grid_columnconfigure(5, weight=1)  # Right spacer

        # Set initial state of duration spinboxes based on default pulsing behavior
        self.update_duration_spinbox_state()

    def start_bcon_connection_monitoring(self):
        """Start periodic monitoring of BCON connection status."""
        def check_connection():
            # Check BCON driver connection status
            if self.bcon_driver:
                is_connected = self.bcon_driver.is_connected()
                self.set_bcon_connection_status(is_connected)
            else:
                self.set_bcon_connection_status(False)
            
            # Schedule next check
            if hasattr(self, 'parent_frame') and self.parent_frame:
                self.parent_frame.after(2000, check_connection)
        
        # Start the monitoring loop
        if hasattr(self, 'parent_frame') and self.parent_frame:
            self.parent_frame.after(1000, check_connection)  # Start after 1 second

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

    def update_duration_spinbox_state(self):
        """Update duration spinboxes state based on pulsing behavior."""
        if hasattr(self, 'duration_spinboxes'):
            pulsing_behavior = self.pulsing_behavior.get() if hasattr(self.pulsing_behavior, 'get') else self.pulsing_behavior
            if pulsing_behavior == "Pulsed":
                # Enable duration spinboxes for Pulsed mode
                for spinbox in self.duration_spinboxes:
                    spinbox.configure(state="normal")
            else:
                # Disable duration spinboxes for DC mode
                for spinbox in self.duration_spinboxes:
                    spinbox.configure(state="disabled")

    # Event handlers for controls
    def on_pulsing_behavior_change(self, event=None):
        """Handle pulsing behavior change."""
        self.update_duration_spinbox_state()

    def on_duration_change(self, duration_var):
        """Handle beam duration change."""
        # This can be used to update hardware or trigger callbacks
        pass

    # Status indicator update methods
    def update_bcon_connection_status(self):
        """Update the BCON connection status indicator."""
        if hasattr(self, 'bcon_connection_canvas'):
            color = "green" if self.bcon_connection_status else "red"
            self.bcon_connection_canvas.create_oval(2, 2, 18, 18, fill=color, outline="black")

    # Status update methods for external use
    def set_bcon_connection_status(self, status: bool):
        """Set the BCON connection status."""
        self.bcon_connection_status = status
        self.update_bcon_connection_status()

    def set_beam_status(self, beam_index: int, status: bool):
        """Set the status of a specific beam (on/off).
        
        Args:
            beam_index: Index of beam (0=A, 1=B, 2=C)
            status: True for ON, False for OFF
        """
        if 0 <= beam_index < 3:
            self.beam_on_status[beam_index] = status
            self._log(f"Beam {chr(65 + beam_index)} set to {'ON' if status else 'OFF'}", LogLevel.INFO)
            
            # Call dashboard callback if registered
            if self._dashboard_beam_callback:
                try:
                    self._dashboard_beam_callback(beam_index, status)
                except Exception as e:
                    self._log(f"Dashboard callback error: {e}", LogLevel.ERROR)

    def get_beam_status(self, beam_index: int) -> bool:
        """Get the status of a specific beam.
        
        Args:
            beam_index: Index of beam (0=A, 1=B, 2=C)
            
        Returns:
            True if beam is ON, False if OFF
        """
        if 0 <= beam_index < 3:
            return self.beam_on_status[beam_index]
        return False

    def set_all_beams_status(self, status: bool):
        """Set all beams to the same status."""
        for i in range(3):
            self.set_beam_status(i, status)

    def get_pulsing_behavior(self) -> str:
        """Get the current pulsing behavior setting."""
        if hasattr(self.pulsing_behavior, 'get'):
            return self.pulsing_behavior.get()
        return self.pulsing_behavior

    def get_beam_duration(self, beam_index: int) -> float:
        """Get the pulse duration for a specific beam."""
        if beam_index == 0:
            return self.beam_a_duration.get() if hasattr(self.beam_a_duration, 'get') else self.beam_a_duration
        elif beam_index == 1:
            return self.beam_b_duration.get() if hasattr(self.beam_b_duration, 'get') else self.beam_b_duration
        elif beam_index == 2:
            return self.beam_c_duration.get() if hasattr(self.beam_c_duration, 'get') else self.beam_c_duration
        return 50.0  # Default

    def set_dashboard_beam_callback(self, callback):
        """Register a callback function for beam status changes.
        
        Args:
            callback: Function(beam_index: int, enabled: bool) to call on beam status change
        """
        self._dashboard_beam_callback = callback
        self._log("Dashboard beam callback registered", LogLevel.DEBUG)

    def get_integration_status(self) -> dict:
        """Get dashboard integration status."""
        return {
            'has_dashboard_callback': self._dashboard_beam_callback is not None,
            'bcon_connected': self.bcon_connection_status
        }

    # --- Hardware Driver Interface ---
    # These methods delegate to the E5CNModbus-based driver for hardware communication

    def connect(self) -> bool:
        """Connect to BCON hardware."""
        if self.bcon_driver:
            return self.bcon_driver.connect()
        return False

    def disconnect(self) -> None:
        """Disconnect from BCON hardware."""
        if self.bcon_driver:
            self.bcon_driver.disconnect()

    def is_connected(self) -> bool:
        """Check if connected to BCON hardware."""
        if self.bcon_driver:
            return self.bcon_driver.is_connected()
        return False

    def read_register(self, name: str) -> Optional[int]:
        """Read a single register from BCON hardware."""
        if self.bcon_driver:
            return self.bcon_driver.read_register(name)
        return None

    def write_register(self, name: str, value: int) -> bool:
        """Write a single register to BCON hardware."""
        if self.bcon_driver:
            return self.bcon_driver.write_register(name, value)
        return False

    def set_command(self, cmd: int) -> bool:
        """Set command register."""
        return self.write_register('COMMAND', cmd)

    def direct_write_x(self, value: int) -> bool:
        """Direct write to X DAC."""
        return self.write_register('X_DIRECT_WRITE', value)

    def direct_write_y(self, value: int) -> bool:
        """Direct write to Y DAC."""
        return self.write_register('Y_DIRECT_WRITE', value)

    def set_pulser_duty(self, pulser_index: int, duty: int) -> bool:
        """Set pulser duty cycle (0-255)."""
        if self.bcon_driver:
            return self.bcon_driver.set_pulser_duty(pulser_index, duty)
        return False

    def set_pulser_duration(self, pulser_index: int, duration_ms: int) -> bool:
        """Set pulser duration in milliseconds."""
        if self.bcon_driver:
            return self.bcon_driver.set_pulser_duration(pulser_index, duration_ms)
        return False

    def set_samples_rate(self, samples: int) -> bool:
        """Set samples per period."""
        return self.write_register('SAMPLES_RATE', samples)

    def set_beam_parameters(self, beam_index: int, amplitude: Optional[int] = None, 
                           phase: Optional[int] = None, offset: Optional[int] = None) -> Dict[str, bool]:
        """Set beam parameters (amplitude, phase, offset)."""
        if self.bcon_driver:
            return self.bcon_driver.set_beam_parameters(beam_index, amplitude, phase, offset)
        return {'amplitude': False, 'phase': False, 'offset': False}

    def read_all(self) -> Dict[str, Optional[int]]:
        """Read all registers."""
        if self.bcon_driver:
            return self.bcon_driver.read_all()
        return {}

    # --- Safety / Shutdown Helpers ---
    def arm_beams(self) -> bool:
        """Enable beam operations (safety feature)."""
        self.beams_armed_status = True
        self._log("Beams ARMED", LogLevel.INFO)
        return True

    def disarm_beams(self) -> bool:
        """Disable beam operations (safety feature)."""
        self.beams_armed_status = False
        self.set_all_beams_status(False)
        self._log("Beams DISARMED", LogLevel.INFO)
        return True

    def get_beams_armed_status(self) -> bool:
        """Check if beams are armed."""
        return self.beams_armed_status

    def get_deflect_beam_status(self) -> bool:
        """Get deflect beam status (compatibility method)."""
        return any(self.beam_on_status)

    def set_deflect_beam_status(self, enable: bool) -> bool:
        """Set deflect beam status for all beams."""
        if enable:
            if not self.beams_armed_status:
                self._log("Cannot enable deflect beam - beams not armed", LogLevel.WARNING)
                return False
            self.set_all_beams_status(True)
        else:
            self.set_all_beams_status(False)
        return True

    def safe_shutdown(self, reason: Optional[str] = None) -> bool:
        """Safely shutdown all beam operations."""
        self._log(f"Safe shutdown initiated: {reason or 'No reason provided'}", LogLevel.WARNING)
        
        # Disarm beams
        self.disarm_beams()
        
        # Turn off all beams
        self.set_all_beams_status(False)
        
        self._log("Safe shutdown complete", LogLevel.INFO)
        return True

    # --- internal helpers ---
    def _log(self, msg: str, level: LogLevel = LogLevel.INFO) -> None:
        """Log a message."""
        if self.logger:
            self.logger.log(msg, level)
        elif self.debug:
            print(f"[{level.name}] {msg}")


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
        print("Could not connect to BCON device")
    else:
        print(f"Connected to BCON on {args.port}")
        
        if args.read_all:
            result = b.read_all()
            print("All registers:")
            for k, v in result.items():
                print(f"  {k}: {v}")
        
        b.disconnect()
