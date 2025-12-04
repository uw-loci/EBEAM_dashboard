import subprocess
import sys
import os
import subsystem
import tkinter as tk
from tkinter import ttk
from tkinter import messagebox
import time
from utils import MessagesFrame, SetupScripts, LogLevel, MachineStatus
from usr.panel_config import save_pane_states, load_pane_states, saveFileExists
import serial.tools.list_ports
try:
    from subsystem.beam_pulse.beam_pulse import BeamPulseSubsystem
    from instrumentctl.BCON_modbus.BCON_modbus import BCONModbus
except Exception:
    BeamPulseSubsystem = None
    BCONModbus = None

try:
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    _HAS_MATPLOTLIB = True
except Exception:
    _HAS_MATPLOTLIB = False

frames_config = [
    # Row 0
    ("Interlocks", 0, 1920, 30),
    
    # Row 1
    ("Oil System", 1, 520, 120),
    ("Beam Energy", 1, 1400, 120),
    
    # Row 2
    ("Vacuum System", 2, 550, 410),
    ("Beam Pulse", 2, 1020, 410),
    ("Main Control", 2, 350, 410),
    
    # Row 4
    ("Process Monitor", 3, 280, 465),
    ("Cathode Heating", 3, 1200, 465),
    ("Messages Frame", 3, 440, 465),

    # Row 5
    ("Machine Status", 4, 1920, 35)
]

class EBEAMSystemDashboard:
    """
    Main dashboard class that manages the EBEAM System Control Dashboard interface.

    Manages the layout and visualization of multiple hardware subsystems including:
    - Interlocks and safety systems
    - Vacuum and pressure monitoring
    - Temperature monitoring
    - Cathode heating control
    - System status monitoring and logging

    Attributes:
        root: tkinter root window
        com_ports: Dictionary mapping subsystem names to serial COM port assignments
        frames: Dictionary of tkinter frames for each subsystem
        subsystems: Dictionary of initialized subsystem objects
    """

    PORT_INFO = {
        "AG0KLEQ8A" : "Interlocks"
    }

    def __init__(self, root, com_ports):
        self.root = root
        self.com_ports = com_ports
        self.root.title("EBEAM Control System Dashboard")

        self.set_com_ports = set(serial.tools.list_ports.comports())
        
        
        # if save file exists call it and open it
        if saveFileExists():
            self.load_saved_pane_state()

        # Initialize the frames dictionary to store various GUI components
        self.frames = {}
        # Optional Beam Pulse UI attributes (only used if dashboard-managed plotting is enabled)
        self.beam_pulse = None
        self._bp_axes = []
        self._bp_canvas = None
        self._bp_data = {1: {'past': [], 'future': []}, 2: {'past': [], 'future': []}, 3: {'past': [], 'future': []}}
        self._bp_history_len = 120
        self._bp_future_len = 30
        self._bp_stats = {}
        self._bp_update_interval_ms = 1000
        
        # Set up the main pane using PanedWindow for flexible layout
        self.setup_main_pane()

        # Set up a frame for displaying messages and errors
        self.create_messages_frame()

        # Initialize all the frames within the main pane
        self.create_frames()

        # Set up a frame for displaying machine status information
        self.create_machine_status_frame()

        # Set up different subsystems within their respective frames
        self.create_subsystems()

        self._check_ports()

    def cleanup(self):
        """Closes all open com ports before quitting the application."""

        print("Cleaning up com ports...")
        for subsystem in self.subsystems.values():
            if hasattr(subsystem, 'close_com_ports'):
                subsystem.close_com_ports()
        print("Cleaned up com ports.")

    def setup_main_pane(self):
        """Initialize the main container for absolute layout using place()."""
        self.main_pane = tk.Frame(self.root)
        self.main_pane.grid(row=0, column=0, sticky='nsew')
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(0, weight=1)
        # No self.rows in absolute layout
        # Sash and grip overlays
        self._sashes = []  # list of dicts with widgets and placement meta
        self._grips = []   # bottom resize grips per frame

    def _compute_row_layout(self):
        """Return structures for layout: row_max_heights, sorted_rows, row_to_y, row_x_offsets."""
        row_max_heights = {}
        for _, row, _w, h in frames_config:
            row_max_heights[row] = max(row_max_heights.get(row, 0), h or 0)
        sorted_rows = sorted(row_max_heights.keys())
        row_to_y = {}
        y_accum = 0
        for r in sorted_rows:
            row_to_y[r] = y_accum
            y_accum += row_max_heights[r]
        # initial x offsets per row
        row_x_offsets = {r: 0 for r in sorted_rows}
        return row_max_heights, sorted_rows, row_to_y, row_x_offsets

    def _reflow_all(self):
        """Re-place frames, sashes and grips after a resize change."""
        # Clear overlays
        for s in self._sashes:
            s['widget'].place_forget()
        for g in self._grips:
            g['widget'].place_forget()
        self._sashes.clear()
        self._grips.clear()
        # Recreate placements
        self._place_frames_and_overlays()

    def _place_frames_and_overlays(self):
        row_max_heights, sorted_rows, row_to_y, row_x_offsets = self._compute_row_layout()
        # Place frames
        row_members = {}
        for title, row, width, height in frames_config:
            row_members.setdefault(row, []).append((title, width, height))

        # Ensure frame objects exist
        for title, row, width, height in frames_config:
            frame = self.frames.get(title)
            x = row_x_offsets.get(row, 0)
            y = row_to_y.get(row, 0)
            if frame:
                frame.place(x=x, y=y, width=width, height=height)
            # Always advance offset, even for spacer/non-rendered entries
            row_x_offsets[row] = x + (width or 0)

        # Add vertical sashes between neighbors in each row
        for row, members in row_members.items():
            # Recalculate X running sum for sash positions
            x = 0
            y = row_to_y[row]
            for idx in range(len(members) - 1):
                left_title, left_w, left_h = members[idx]
                right_title, right_w, right_h = members[idx + 1]
                x += left_w
                sash = tk.Frame(self.main_pane, cursor='sb_h_double_arrow', bg='#CCCCCC')
                sash_w = 5
                sash.place(x=x - sash_w // 2, y=y, width=sash_w, height=row_max_heights[row])
                self._attach_sash_handlers(sash, row, idx)
                self._sashes.append({'widget': sash, 'row': row, 'index': idx})

        # Add bottom grips for vertical resize per frame
        for title, row, width, height in frames_config:
            frame = self.frames.get(title)
            if not frame:
                continue
            y = 0
            for r in sorted_rows:
                if r == row:
                    break
                y += row_max_heights[r]
            x = 0
            for t2, r2, w2, _ in frames_config:
                if r2 != row:
                    continue
                if t2 == title:
                    break
                x += w2
            grip = tk.Frame(self.main_pane, cursor='sb_v_double_arrow', bg='#CCCCCC')
            grip_h = 5
            grip.place(x=x, y=y + height - grip_h // 2, width=width, height=grip_h)
            self._attach_grip_handlers(grip, row, title)
            self._grips.append({'widget': grip, 'row': row, 'title': title})

    def _attach_sash_handlers(self, sash, row, idx_in_row):
        # Track state
        state = {'start_x': 0, 'row': row, 'idx': idx_in_row}
        def on_press(event):
            state['start_x'] = event.x_root
        def on_drag(event):
            dx = event.x_root - state['start_x']
            self._resize_horizontal(row, idx_in_row, dx)
            state['start_x'] = event.x_root
        sash.bind('<Button-1>', on_press)
        sash.bind('<B1-Motion>', on_drag)

    def _attach_grip_handlers(self, grip, row, title):
        state = {'start_y': 0, 'row': row, 'title': title}
        def on_press(event):
            state['start_y'] = event.y_root
        def on_drag(event):
            dy = event.y_root - state['start_y']
            self._resize_vertical(row, title, dy)
            state['start_y'] = event.y_root
        grip.bind('<Button-1>', on_press)
        grip.bind('<B1-Motion>', on_drag)

    def _resize_horizontal(self, row, idx_in_row, dx):
        # Collect indices of frames in this row
        indices = [i for i, (_t, r, _w, _h) in enumerate(frames_config) if r == row]
        if idx_in_row >= len(indices) - 1:
            return
        left_i = indices[idx_in_row]
        right_i = indices[idx_in_row + 1]
        left_title, _r, left_w, left_h = frames_config[left_i]
        right_title, _r2, right_w, right_h = frames_config[right_i]
        # Apply delta with clamps
        min_w = 80
        new_left = max(min_w, left_w + dx)
        delta = new_left - left_w
        new_right = max(min_w, right_w - delta)
        # If right clamped, adjust back left accordingly
        if right_w - delta < min_w:
            delta = right_w - min_w
            new_left = left_w + delta
            new_right = min_w
        frames_config[left_i] = (left_title, row, new_left, left_h)
        frames_config[right_i] = (right_title, row, new_right, right_h)

        # Keep merged column width in sync across rows
        if left_title in ("Beam Pulse", "Beam Steering/Pulse", "Beam Pulse Spacer"):
            self._sync_merged_column_width(new_left)
        if right_title in ("Beam Pulse", "Beam Steering/Pulse", "Beam Pulse Spacer"):
            self._sync_merged_column_width(new_right)

        self._reflow_all()

    def _sync_merged_column_width(self, new_width):
        """Ensure the merged middle column keeps the same width in all rows."""
        for i, (t, r, w, h) in enumerate(frames_config):
            if t in ("Beam Pulse", "Beam Steering/Pulse", "Beam Pulse Spacer"):
                frames_config[i] = (t, r, int(new_width), h)

    def _resize_vertical(self, row, title, dy):
        # Change height of a single frame in the row, row stack height follows max of row
        min_h = 10
        # Find the target frame index
        for i, (t, r, w, h) in enumerate(frames_config):
            if r == row and t == title:
                new_h = max(min_h, h + dy)
                frames_config[i] = (t, r, w, int(new_h))
                break
        self._reflow_all()

    def create_frames(self):
        """Create and place frames absolutely using frames_config (title, row, width, height)."""
        global frames_config
        # Initial creation of frame widgets and titles
        for title, row, width, height in frames_config:
            # Skip creating a real frame for spacer entries (still used for layout math)
            if title == "Beam Pulse Spacer":
                continue

            if width and height and title:
                frame = tk.Frame(self.main_pane, borderwidth=1, relief="solid", width=width, height=height)
                frame.pack_propagate(False)
            else:
                frame = tk.Frame(self.main_pane, borderwidth=1, relief="solid")

            # Skip adding title for certain frames
            if title not in ["Interlocks", "Machine Status", "Messages Frame"]:
                self.add_title(frame, title)

            # Adopt the Messages Frame container, else use created frame
            if title == 'Messages Frame' and hasattr(self, 'messages_frame') and hasattr(self.messages_frame, 'frame'):
                self.frames[title] = self.messages_frame.frame
            else:
                self.frames[title] = frame

            if title == "Main Control":
                self.create_main_control_notebook(frame)

        # Place frames and create overlays
        self._place_frames_and_overlays()

    def create_main_control_notebook(self, frame):
        notebook = ttk.Notebook(frame)
        notebook.pack(expand=True, fill='both')

        main_tab = ttk.Frame(notebook)
        config_tab = ttk.Frame(notebook)

        notebook.add(main_tab, text='Main')
        notebook.add(config_tab, text='Config')

        # TODO: add main control buttons to main tab here
        main_frame = ttk.Frame(main_tab, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Add safety beams off button (bottom)
        beams_off_button = tk.Button(
            main_frame,
            text="BEAMS OFF",
            bg="red",
            fg="white",
            font=("Helvetica",14,"bold"),
            command=self.handle_beams_off
        )
        beams_off_button.pack(side="bottom", fill="x", padx=10, pady=(4, 8))

        # Script dropdown
        self.create_script_dropdown(main_frame)

        # Add individual beam toggle buttons (below script dropdown)
        beam_toggles_frame = tk.Frame(main_frame)
        beam_toggles_frame.pack(side="top", fill="x", padx=10, pady=(10, 0))
        
        # Create status bars above beam buttons using grid for precise alignment
        status_bars_frame = tk.Frame(beam_toggles_frame)
        status_bars_frame.pack(side="top", fill="x", pady=(0, 2))
        
        self.beam_status_bars = []
        self.beam_status_timers = []  # For managing progress animations
        self.dc_mode_timers = []  # For DC mode runtime counters
        self.dc_mode_start_times = []  # Track when DC mode started
        
        # Configure grid columns to have equal weight
        for i in range(3):
            status_bars_frame.grid_columnconfigure(i, weight=1, uniform="status_bar")
        
        for i in range(3):
            # Create thin status bar canvas using grid for proper width distribution
            status_bar = tk.Canvas(
                status_bars_frame,
                height=12,
                bg="lightgray",
                highlightthickness=0
            )
            status_bar.grid(row=0, column=i, sticky="ew", padx=2)
            self.beam_status_bars.append(status_bar)
            self.beam_status_timers.append(None)
            self.dc_mode_timers.append(None)
            self.dc_mode_start_times.append(None)
        
        # Create toggle buttons for each beam using matching grid system
        buttons_frame = tk.Frame(beam_toggles_frame)
        buttons_frame.pack(side="top", fill="x")
        
        # Configure grid columns to match status bars
        for i in range(3):
            buttons_frame.grid_columnconfigure(i, weight=1, uniform="button")
        
        self.beam_toggle_buttons = []
        beam_names = ["Beam A OFF", "Beam B OFF", "Beam C OFF"]
        
        for i, beam_name in enumerate(beam_names):
            btn = tk.Button(
                buttons_frame,
                text=beam_name,
                bg="gray",
                fg="white",
                font=("Helvetica", 10, "bold"),
                state="disabled",  # Initially disabled until armed
                command=lambda idx=i: self.toggle_individual_beam_with_status(idx)
            )
            btn.grid(row=0, column=i, sticky="ew", padx=2)
            self.beam_toggle_buttons.append(btn)
        
        # Schedule status bar width synchronization after layout is complete
        self.root.after(100, self.sync_status_bar_widths)

        # Add beams ready button (above beams off)
        self.beams_ready_button = tk.Button(
            main_frame,
            text="ARM BEAMS",
            bg="sky blue",
            fg="white",
            font=("Helvetica",16,"bold"),
            command=self.handle_arm_beams
        )
        self.beams_ready_button.pack(side="bottom", fill="x", padx=10, pady=(8, 4))

        config_frame = ttk.Frame(config_tab, padding="10")
        config_frame.pack(fill=tk.BOTH, expand=True)

        # 1. COM Port Configuration
        self.create_com_port_frame(config_frame)

        # 2. Save Layout button
        save_layout_frame = ttk.Frame(config_frame)
        save_layout_frame.pack(side=tk.TOP, anchor='nw', padx=5, pady=5)
        ttk.Button(
            save_layout_frame,
            text="Save Layout",
            command=self.save_current_pane_state
        ).pack(side=tk.LEFT, padx=5)

        # 3. Post Processor button
        self.create_post_processor_button(config_frame)

        # 4. Log Level dropdown
        self.create_log_level_dropdown(config_frame)

        # Add F1 help hint
        help_label = ttk.Label(
            config_frame,
            text="Press F1 for keyboard shortcuts",
            font=("Helvetica", 8, "italic"),
            foreground="gray"
        )
        help_label.pack(side=tk.BOTTOM, anchor='se', padx=5, pady=(10, 5))

    def create_script_dropdown(self, parent_frame):
        SetupScripts(parent_frame)

    def create_post_processor_button(self, parent_frame):
        """Create a button to launch the standalone post-processor application"""
        post_processor_frame = ttk.Frame(parent_frame)
        post_processor_frame.pack(side=tk.TOP, anchor='nw', padx=5, pady=5)
        
        ttk.Button(
            post_processor_frame,
            text="Launch Log Post-processor",
            command=self.launch_post_processor
        ).pack(side=tk.LEFT, padx=5)

    def launch_post_processor(self):
        """Launch the post-processor as a separate process"""
        try:
            # Get the directory where the current script is located
            if getattr(sys, 'frozen', False):
                # If running as a bundled executable
                base_path = sys._MEIPASS # type: ignore
            else:
                # If running as a script
                base_path = os.path.dirname(os.path.abspath(__file__))

            # Path to the post processor script
            post_processor_path = os.path.join(base_path, 'scripts/post-process/post_process_gui.py')

            # Launch the post-processor script
            if sys.platform.startswith('win'):
                # On Windows, use pythonw to avoid console window
                subprocess.Popen([sys.executable, post_processor_path], 
                            creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                # On other platforms
                subprocess.Popen([sys.executable, post_processor_path])
                
            self.logger.info("Log post-processor launched successfully")
        except Exception as e:
            self.logger.error(f"Failed to launch log post-processor: {str(e)}")
            messagebox.showerror("Error", 
                            f"Failed to launch log post-processor:\n{str(e)}")

    def add_title(self, frame, title):
        """
        Add a formatted title label to a frame.
        
        Args:
            frame: Frame to add title to
            title: Title text to display
        """
        label = tk.Label(frame, text=title, font=("Helvetica", 10, "bold"))
        label.pack(pady=0, fill=tk.X)

    # saves data to file when button is pressed
    def save_current_pane_state(self):
        save_pane_states(frames_config, self.frames, self.main_pane)

    # gets data in save config file (as dict) and updates the global var of frames_config
    def load_saved_pane_state(self):
        savedData = load_pane_states()
        if not savedData:
            return
        for i in range(len(frames_config)):
            title = frames_config[i][0]
            if title in savedData and savedData[title]:
                dims = savedData[title]
                if isinstance(dims, (list, tuple)) and len(dims) >= 2:
                    frames_config[i] = (title, frames_config[i][1], dims[0], dims[1])

    def create_log_level_dropdown(self, parent_frame):
        log_level_frame = ttk.Frame(parent_frame)
        log_level_frame.pack(side=tk.TOP, anchor='nw', padx=5, pady=5)
        ttk.Label(log_level_frame, text="Log Level:").pack(side=tk.LEFT)

        self.log_level_var = tk.StringVar()
        log_levels = [level.name for level in LogLevel]
        log_level_dropdown = ttk.Combobox(
            log_level_frame, 
            textvariable=self.log_level_var, 
            values=log_levels, 
            state="readonly", 
            width=15
        )
        log_level_dropdown.pack(side=tk.LEFT, padx=(5, 0))
        
        current_level = self.messages_frame.get_log_level()
        log_level_dropdown.set(current_level.name) 
        log_level_dropdown.bind("<<ComboboxSelected>>", self.on_log_level_change)

    def on_log_level_change(self, event):
        selected_level = LogLevel[self.log_level_var.get()]
        self.messages_frame.set_log_level(selected_level)
        print(f"Log level changed to: {selected_level.name}")

    def handle_arm_beams(self):
        """Handle ARM BEAMS button press with state management."""
        try:
            # Check if Beam Pulse subsystem is available
            if 'Beam Pulse' not in self.subsystems or self.subsystems['Beam Pulse'] is None:
                self.logger.error("Beam Pulse subsystem not available")
                messagebox.showerror("Error", "Beam Pulse subsystem not available")
                return
            
            beam_pulse = self.subsystems['Beam Pulse']
            
            # Check current armed state
            if hasattr(beam_pulse, 'get_beams_armed_status') and beam_pulse.get_beams_armed_status():
                # Beams are already armed, so disarm them
                if hasattr(beam_pulse, 'disarm_beams') and beam_pulse.disarm_beams():
                    # Successfully disarmed
                    self.beams_ready_button.config(
                        text="ARM BEAMS",
                        bg="sky blue"
                    )
                    # Disable beam toggle buttons and reset their states
                    self.update_beam_toggle_states(enabled=False, reset=True)
                    self.logger.info("Beams disarmed via dashboard button")
                else:
                    self.logger.error("Failed to disarm beams")
                    messagebox.showerror("Error", "Failed to disarm beams")
            else:
                # Beams are not armed, so arm them
                if hasattr(beam_pulse, 'arm_beams') and beam_pulse.arm_beams():
                    # Successfully armed
                    self.beams_ready_button.config(
                        text="BEAMS ARMED",
                        bg="navy"  # Darker shade of blue
                    )
                    # Enable beam toggle buttons
                    self.update_beam_toggle_states(enabled=True)
                    self.logger.info("Beams armed via dashboard button")
                else:
                    self.logger.error("Failed to arm beams")
                    messagebox.showerror("Error", "Failed to arm beams")
                    
        except Exception as e:
            self.logger.error(f"Error in handle_arm_beams: {str(e)}")
            messagebox.showerror("Error", f"Error handling beam arming: {str(e)}")

    def handle_beams_off(self):
        """Handle BEAMS OFF button press - turn off cathode heating and disarm beams if armed."""
        try:
            # Turn off cathode heating power supplies
            if 'Cathode Heating' in self.subsystems and self.subsystems['Cathode Heating'] is not None:
                cathode = self.subsystems['Cathode Heating']
                if hasattr(cathode, 'turn_off_all_beams'):
                    cathode.turn_off_all_beams()
                    self.logger.info("Cathode heating turned off via BEAMS OFF button")
            
            # Check if beams are armed and disarm them
            if 'Beam Pulse' in self.subsystems and self.subsystems['Beam Pulse'] is not None:
                beam_pulse = self.subsystems['Beam Pulse']
                if hasattr(beam_pulse, 'get_beams_armed_status') and beam_pulse.get_beams_armed_status():
                    # Beams are armed, so disarm them
                    if hasattr(beam_pulse, 'disarm_beams') and beam_pulse.disarm_beams():
                        # Update the ARM BEAMS button state
                        self.beams_ready_button.config(
                            text="ARM BEAMS",
                            bg="sky blue"
                        )
                        # Disable beam toggle buttons and reset their states
                        self.update_beam_toggle_states(enabled=False, reset=True)
                        self.logger.info("Beams disarmed via BEAMS OFF button")
                    else:
                        self.logger.error("Failed to disarm beams via BEAMS OFF")
        except Exception as e:
            self.logger.error(f"Error in handle_beams_off: {str(e)}")

    def toggle_individual_beam_with_status(self, beam_index):
        """Toggle individual beam on/off with status bar animation."""
        try:
            if 'Beam Pulse' not in self.subsystems or self.subsystems['Beam Pulse'] is None:
                self.logger.error("Beam Pulse subsystem not available")
                return
            
            beam_pulse = self.subsystems['Beam Pulse']
            beam_names = ["A", "B", "C"]
            
            # Get current beam status
            if hasattr(beam_pulse, 'get_beam_status'):
                current_status = beam_pulse.get_beam_status(beam_index)
                new_status = not current_status
                
                # Set new beam status
                if hasattr(beam_pulse, 'set_beam_status'):
                    beam_pulse.set_beam_status(beam_index, new_status)
                    
                    # Update button appearance and text
                    btn = self.beam_toggle_buttons[beam_index]
                    if new_status:
                        btn.config(bg="green", text=f"Beam {beam_names[beam_index]} ON")
                        
                        # Animation handled by beam pulse callback if in Pulsed mode
                        self.logger.info(f"Beam {beam_names[beam_index]} turned ON")
                    else:
                        btn.config(bg="gray", text=f"Beam {beam_names[beam_index]} OFF")
                        # Clear any running status bar animation
                        self.clear_beam_status_bar(beam_index)
                        self.logger.info(f"Beam {beam_names[beam_index]} turned OFF")
                    
        except Exception as e:
            self.logger.error(f"Error toggling beam {beam_index}: {str(e)}")
    
    def toggle_individual_beam(self, beam_index):
        """Legacy method - redirects to new method with status bar."""
        self.toggle_individual_beam_with_status(beam_index)

    def get_beam_pulse_duration(self, beam_index):
        """Get the pulse duration for a specific beam."""
        try:
            if 'Beam Pulse' not in self.subsystems or self.subsystems['Beam Pulse'] is None:
                return 0
            
            beam_pulse = self.subsystems['Beam Pulse']
            
            # Get duration from the beam pulse subsystem
            if beam_index == 0 and hasattr(beam_pulse, 'beam_a_duration'):
                return beam_pulse.beam_a_duration.get()
            elif beam_index == 1 and hasattr(beam_pulse, 'beam_b_duration'):
                return beam_pulse.beam_b_duration.get()
            elif beam_index == 2 and hasattr(beam_pulse, 'beam_c_duration'):
                return beam_pulse.beam_c_duration.get()
            
            return 100.0  # Default fallback
        except Exception as e:
            self.logger.error(f"Error getting beam {beam_index} duration: {str(e)}")
            return 100.0

    def auto_turn_off_beam(self, beam_index):
        """Automatically turn off a beam after pulse duration."""
        try:
            if 'Beam Pulse' not in self.subsystems or self.subsystems['Beam Pulse'] is None:
                return
            
            beam_pulse = self.subsystems['Beam Pulse']
            beam_names = ["A", "B", "C"]
            
            # Check if beam is still on before turning off
            if hasattr(beam_pulse, 'get_beam_status') and beam_pulse.get_beam_status(beam_index):
                # Turn off the beam
                if hasattr(beam_pulse, 'set_beam_status'):
                    beam_pulse.set_beam_status(beam_index, False)
                    
                    # Update button appearance
                    btn = self.beam_toggle_buttons[beam_index]
                    btn.config(bg="gray", text=f"Beam {beam_names[beam_index]} OFF")
                    
                    self.logger.info(f"Beam {beam_names[beam_index]} automatically turned OFF after pulse duration")
                    
        except Exception as e:
            self.logger.error(f"Error auto-turning off beam {beam_index}: {str(e)}")
    
    def animate_beam_status_bar(self, beam_index, duration_ms):
        """Animate status bar to show pulse progress with consistent visual feedback."""
        try:
            status_bar = self.beam_status_bars[beam_index]
            beam_names = ["A", "B", "C"]
            
            # Clear any existing animation
            if self.beam_status_timers[beam_index]:
                self.root.after_cancel(self.beam_status_timers[beam_index])
            
            # Consistent behavior: always show progress during actual duration + green confirmation
            actual_duration = duration_ms
            completion_display_time = 750  # Always show green completion for 750ms
            
            # Clear and setup status bar
            status_bar.delete("all")
            # Force update to get accurate dimensions
            status_bar.update_idletasks()
            bar_width = status_bar.winfo_width()
            if bar_width <= 1:  # Widget not yet sized properly
                # Get button width as fallback
                try:
                    btn_width = self.beam_toggle_buttons[beam_index].winfo_width()
                    if btn_width > 1:
                        bar_width = btn_width - 4  # Account for padding
                    else:
                        bar_width = 120  # Reasonable default
                except:
                    bar_width = 120
            bar_height = 12
            
            # Animation parameters
            start_time = time.time() * 1000  # Current time in ms
            steps = max(20, int(actual_duration / 10))  # More steps for longer durations
            step_duration = actual_duration / steps
            
            def update_progress():
                current_time = time.time() * 1000
                elapsed = current_time - start_time
                
                if elapsed >= actual_duration:
                    # Pulse complete - show green confirmation
                    status_bar.delete("all")
                    status_bar.create_rectangle(0, 0, bar_width, bar_height, fill="lightgreen", outline="")
                    status_bar.create_text(bar_width//2, bar_height//2, 
                                         text=f"Beam {beam_names[beam_index]}: {actual_duration}ms completed", 
                                         font=("Arial", 8), fill="darkgreen")
                    
                    # Clear after completion display time
                    self.beam_status_timers[beam_index] = self.root.after(completion_display_time, 
                                                                           lambda: self.clear_beam_status_bar(beam_index))
                    return
                
                # Calculate progress during active pulse
                progress = elapsed / actual_duration
                color = "orange"  # Active pulse color
                status_text = f"Beam {beam_names[beam_index]}: {actual_duration}ms active"
                
                # Update progress bar
                status_bar.delete("all")
                fill_width = int(bar_width * progress)
                
                # Background
                status_bar.create_rectangle(0, 0, bar_width, bar_height, fill="lightgray", outline="")
                
                # Progress fill
                if fill_width > 0:
                    status_bar.create_rectangle(0, 0, fill_width, bar_height, fill=color, outline="")
                
                # Text overlay
                status_bar.create_text(bar_width//2, bar_height//2, text=status_text, 
                                     font=("Arial", 7), fill="black")
                
                # Schedule next update
                self.beam_status_timers[beam_index] = self.root.after(int(step_duration), update_progress)
            
            # Start animation
            update_progress()
            
        except Exception as e:
            self.logger.error(f"Error animating status bar for beam {beam_index}: {str(e)}")
    
    def clear_beam_status_bar(self, beam_index):
        """Clear beam status bar and cancel any running animation."""
        try:
            if beam_index < len(self.beam_status_bars):
                # Cancel any running timer
                if self.beam_status_timers[beam_index]:
                    self.root.after_cancel(self.beam_status_timers[beam_index])
                    self.beam_status_timers[beam_index] = None
                
                # Clear status bar
                status_bar = self.beam_status_bars[beam_index]
                status_bar.delete("all")
                status_bar.update_idletasks()
                bar_width = status_bar.winfo_width()
                if bar_width <= 1:
                    bar_width = 120  # Default fallback
                status_bar.create_rectangle(0, 0, bar_width, 12, 
                                           fill="lightgray", outline="")
        except Exception as e:
            self.logger.error(f"Error clearing status bar for beam {beam_index}: {str(e)}")

    def handle_beam_pulse_callback(self, beam_index, status, duration=0):
        """Handle beam pulse callback for animation control.
        
        This method is called by the beam pulse subsystem when beam status changes
        and handles pulse animations based on pulsing behavior setting.
        """
        try:
            beam_names = ["A", "B", "C"]
            
            if status and duration > 0:
                # Beam turned ON in Pulsed mode - animate and schedule auto turn-off
                self.animate_beam_status_bar(beam_index, duration)
                # Delay auto turn-off to allow completion display to show (750ms + small buffer)
                self.root.after(int(duration + 800), lambda: self.auto_turn_off_beam(beam_index))
                self.logger.info(f"Beam {beam_names[beam_index]} pulsed for {duration}ms")
            elif status and duration == 0:
                # Beam turned ON in DC mode - show solid bar with runtime counter
                self.start_dc_mode_counter(beam_index)
                self.logger.info(f"Beam {beam_names[beam_index]} turned ON in DC mode")
            elif not status:
                # Beam turned OFF - clear animation and stop DC counter
                self.clear_beam_status_bar(beam_index)
                self.stop_dc_mode_counter(beam_index)
                
        except Exception as e:
            self.logger.error(f"Error in beam pulse callback for beam {beam_index}: {str(e)}")

    def start_dc_mode_counter(self, beam_index):
        """Start DC mode runtime counter for a beam."""
        try:
            if not hasattr(self, 'dc_mode_start_times'):
                return
                
            import time
            self.dc_mode_start_times[beam_index] = time.time()
            self.update_dc_mode_display(beam_index)
            
        except Exception as e:
            self.logger.error(f"Error starting DC mode counter for beam {beam_index}: {str(e)}")
    
    def stop_dc_mode_counter(self, beam_index):
        """Stop DC mode runtime counter for a beam."""
        try:
            if hasattr(self, 'dc_mode_timers') and beam_index < len(self.dc_mode_timers):
                if self.dc_mode_timers[beam_index]:
                    self.root.after_cancel(self.dc_mode_timers[beam_index])
                    self.dc_mode_timers[beam_index] = None
            if hasattr(self, 'dc_mode_start_times') and beam_index < len(self.dc_mode_start_times):
                self.dc_mode_start_times[beam_index] = None
                
        except Exception as e:
            self.logger.error(f"Error stopping DC mode counter for beam {beam_index}: {str(e)}")
    def format_beam_duration(self, total_seconds):
        """Format beam duration display based on time elapsed.
        
        Args:
            total_seconds (int): Total elapsed time in seconds
            
        Returns:
            str: Formatted time string
                - Under 60s: "42s"
                - 60s to 3600s: "5m 42s" 
                - Over 3600s: "2h 5m 42s"
        """
        if total_seconds < 60:
            # Under 60 seconds: show just seconds
            return f"{total_seconds}s"
        elif total_seconds < 3600:
            # Between 60 seconds and 1 hour: show minutes and seconds
            minutes = total_seconds // 60
            seconds = total_seconds % 60
            return f"{minutes}m {seconds}s"
        else:
            # Over 1 hour: show hours, minutes, and seconds
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            seconds = total_seconds % 60
            return f"{hours}h {minutes}m {seconds}s"
    
    def update_dc_mode_display(self, beam_index):
        """Update DC mode display with runtime counter."""
        try:
            if (not hasattr(self, 'dc_mode_start_times') or 
                beam_index >= len(self.dc_mode_start_times) or
                self.dc_mode_start_times[beam_index] is None):
                return
                
            import time
            beam_names = ["A", "B", "C"]
            status_bar = self.beam_status_bars[beam_index]
            
            # Calculate runtime in seconds
            runtime_seconds = int(time.time() - self.dc_mode_start_times[beam_index])
            
            # Update status bar with solid yellow background and runtime text
            status_bar.delete("all")
            # Force update to get accurate dimensions
            status_bar.update_idletasks()
            bar_width = status_bar.winfo_width()
            if bar_width <= 1:
                bar_width = 100  # Fallback width
            bar_height = 12
            
            # Solid yellow background
            status_bar.create_rectangle(0, 0, bar_width, bar_height, fill="gold", outline="")
            
            # Format time based on duration
            formatted_time = self.format_beam_duration(runtime_seconds)
            
            # Runtime text overlay
            runtime_text = f"Beam {beam_names[beam_index]}: {formatted_time}"
            status_bar.create_text(
                bar_width // 2, bar_height // 2,
                text=runtime_text,
                fill="black",
                font=("Arial", 8, "bold")
            )
            
            # Schedule next update in 1 second
            self.dc_mode_timers[beam_index] = self.root.after(1000, lambda: self.update_dc_mode_display(beam_index))
            
        except Exception as e:
            self.logger.error(f"Error updating DC mode display for beam {beam_index}: {str(e)}")

    def sync_status_bar_widths(self):
        """Synchronize status bar widths with button widths after layout changes."""
        try:
            # Force layout update
            self.root.update_idletasks()
            
            for i, (status_bar, button) in enumerate(zip(self.beam_status_bars, self.beam_toggle_buttons)):
                try:
                    # Get button width
                    btn_width = button.winfo_width()
                    if btn_width > 1:
                        # Configure status bar to match button width
                        status_bar.configure(width=btn_width - 4)  # Account for padding
                        # Clear and redraw background
                        status_bar.delete("all")
                        status_bar.create_rectangle(0, 0, btn_width - 4, 12, 
                                                   fill="lightgray", outline="")
                except Exception as e:
                    self.logger.error(f"Error syncing status bar {i} width: {str(e)}")
        except Exception as e:
            self.logger.error(f"Error syncing status bar widths: {str(e)}")

    def update_beam_toggle_states(self, enabled=True, reset=False):
        """Update the state of beam toggle buttons."""
        try:
            if not hasattr(self, 'beam_toggle_buttons'):
                return
                
            beam_names = ["A", "B", "C"]
            
            for i, btn in enumerate(self.beam_toggle_buttons):
                if enabled:
                    btn.config(state="normal")
                    if reset:
                        # Reset to OFF state
                        btn.config(bg="gray", text=f"Beam {beam_names[i]} OFF")
                        # Also reset the beam status in the subsystem
                        if 'Beam Pulse' in self.subsystems and self.subsystems['Beam Pulse'] is not None:
                            beam_pulse = self.subsystems['Beam Pulse']
                            if hasattr(beam_pulse, 'set_beam_status'):
                                beam_pulse.set_beam_status(i, False)
                else:
                    btn.config(state="disabled", bg="gray", text=f"Beam {beam_names[i]} OFF")
                    if reset:
                        # Reset beam status in subsystem
                        if 'Beam Pulse' in self.subsystems and self.subsystems['Beam Pulse'] is not None:
                            beam_pulse = self.subsystems['Beam Pulse']
                            if hasattr(beam_pulse, 'set_beam_status'):
                                beam_pulse.set_beam_status(i, False)
                                
        except Exception as e:
            self.logger.error(f"Error updating beam toggle states: {str(e)}")

    def create_subsystems(self):
        """
        Initialize all subsystem objects with their respective frames and settings.
        Each subsystem is configured with appropriate COM ports and logging.
        """
        self.subsystems = {
            'Vacuum System': subsystem.VTRXSubsystem(
                self.frames['Vacuum System'],
                serial_port=self.com_ports['VTRXSubsystem'], 
                logger=self.logger
            ),
            'Process Monitor [°C]': subsystem.ProcessMonitorSubsystem(
                self.frames['Process Monitor'], 
                com_port=self.com_ports['ProcessMonitors'],
                logger=self.logger,
                active = self.machine_status_frame.MACHINE_STATUS
            ),
            'Interlocks': subsystem.InterlocksSubsystem(
                self.frames['Interlocks'],
                com_ports = self.com_ports['Interlocks'],
                logger=self.logger,
                frames = self.frames,
                active = self.machine_status_frame.MACHINE_STATUS
            ),
            'Oil System': subsystem.OilSubsystem(
                self.frames['Oil System'],
                logger=self.logger,
            ), 
            'Cathode Heating': subsystem.CathodeHeatingSubsystem(
                self.frames['Cathode Heating'],
                com_ports=self.com_ports,
                logger=self.logger,
                active = self.machine_status_frame.MACHINE_STATUS
            )
        }

        # Beam Pulse subsystem (BCON)
        try:
            bp_port = self.com_ports.get('BeamPulse', self.com_ports.get('Beam Pulse', ''))
            if BeamPulseSubsystem is not None and BCONModbus is not None:
                # Create BCON driver
                bcon_driver = None
                if bp_port:  # Only create driver if port is configured
                    bcon_driver = BCONModbus(
                        port=bp_port,
                        unit=1,
                        logger=self.logger
                    )
                
                # Host Beam Pulse UI inside the merged pane
                parent = self.frames.get('Beam Steering/Pulse', self.frames.get('Beam Pulse'))
                beam_pulse_subsystem = BeamPulseSubsystem(
                    parent_frame=parent,
                    bcon_driver=bcon_driver,
                    logger=self.logger
                )
                
                # Set up dashboard callback for pulse animations
                beam_pulse_subsystem.set_dashboard_beam_callback(self.handle_beam_pulse_callback)
                
                self.subsystems['Beam Pulse'] = beam_pulse_subsystem
            else:
                # placeholder if module not importable
                container = self.frames.get('Beam Steering/Pulse', self.frames['Process Monitor'])
                container.pack_propagate(True)
                lbl = ttk.Label(container, text="BeamPulse subsystem not installed")
                lbl.pack(fill=tk.BOTH, expand=True)
        except Exception as e:
            self.logger.error(f"Failed to initialize Beam Pulse subsystem: {e}")

        # Updates machine status progress bar
        self.machine_status_frame.update_status(self.machine_status_frame.MACHINE_STATUS)

    def create_messages_frame(self):
        """Create a scrollable frame for displaying system messages and errors."""
        # Determine configured width/height for the Messages Frame from frames_config
        msg_width = 440
        msg_height = 465
        for title, _row, w, h in frames_config:
            if title == 'Messages Frame':
                msg_width = w
                msg_height = h
                break
        # Parent to main_pane in absolute layout; placement handled in create_frames
        self.messages_frame = MessagesFrame(self.main_pane, width=msg_width, height=msg_height)
        self.logger = self.messages_frame.logger

    def create_machine_status_frame(self):
        """Create a frame for displaying machine status information."""
        self.machine_status_frame = MachineStatus(self.frames['Machine Status'])

    def update_beam_pulse(self):
        """Poll beam_pulse subsystem for new values and update plots."""
        try:
            # Read amplitude registers for beams as a proxy for current waveform
            # (Amplitude/phase/offset can be combined to synthesize a waveform; for now plot amplitude)
            if not hasattr(self, 'beam_pulse') or self.beam_pulse is None:
                return

            for i in (1, 2, 3):
                regname = f'BEAM_{i}_AMPLITUDE'
                val = self.beam_pulse.read_register(regname)
                if val is None:
                    val = 0
                # push to history
                buf = self._bp_data[i]['past']
                buf.append(val)
                if len(buf) > self._bp_history_len:
                    buf.pop(0)

                # naive future prediction: repeat last value (placeholder for real predictive model)
                fut = [buf[-1]] * self._bp_future_len
                self._bp_data[i]['future'] = fut

                # update stats
                try:
                    last = buf[-1]
                    mean = sum(buf) / len(buf)
                    vmin = min(buf)
                    vmax = max(buf)
                    stats = self._bp_stats.get(i)
                    if stats:
                        stats['last'].config(text=f'Last: {last}')
                        stats['mean'].config(text=f'Mean: {mean:.1f}')
                        stats['min'].config(text=f'Min: {vmin}')
                        stats['max'].config(text=f'Max: {vmax}')
                except Exception:
                    pass

            # redraw plots
            for idx, ax in enumerate(self._bp_axes, start=1):
                ax.cla()
                past = self._bp_data[idx]['past']
                future = self._bp_data[idx]['future']
                ax.plot(range(-len(past), 0), past, label='past')
                ax.plot(range(0, len(future)), future, linestyle='--', label='predicted')
                ax.set_title(f'Beam {idx} amplitude')
                ax.legend()

            if self._bp_canvas:
                self._bp_canvas.draw()

        except Exception as e:
            self.logger.error(f'Error updating Beam Pulse UI: {e}')

        finally:
            # schedule next update
            interval = getattr(self, '_bp_update_interval_ms', 1000)
            self.root.after(interval, self.update_beam_pulse)

    def create_com_port_frame(self, parent_frame):
        """
        Create the COM port configuration interface.
        Allows dynamic assignment of COM ports to different subsystems.
        """
        self.com_port_frame = ttk.Frame(parent_frame)
        self.com_port_frame.pack(side=tk.TOP, fill=tk.X, padx=5, pady=5)

        self.com_port_button = ttk.Button(self.com_port_frame, text="Configure COM Ports", command=self.toggle_com_port_menu)
        self.com_port_button.pack(side=tk.TOP, anchor='w')

        self.com_port_menu = ttk.Frame(self.com_port_frame)
        self.com_port_menu.pack(side=tk.TOP, fill=tk.X, expand=True)
        self.com_port_menu.pack_forget()  # Initially hidden

        self.port_selections = {}
        self.port_dropdowns = {}

        for subsystem in ['VTRXSubsystem', 'CathodeA PS', 'CathodeB PS', 'CathodeC PS', 'TempControllers', 'Interlocks', 'ProcessMonitors']:
            frame = ttk.Frame(self.com_port_menu)
            frame.pack(fill=tk.X, padx=5, pady=2)
            ttk.Label(frame, text=f"{subsystem}:").pack(side=tk.LEFT)
            port_var = tk.StringVar(value=self.com_ports.get(subsystem, ''))
            self.port_selections[subsystem] = port_var
            dropdown = ttk.Combobox(frame, textvariable=port_var)
            dropdown.pack(side=tk.RIGHT)
            self.port_dropdowns[subsystem] = dropdown

        # ensure Beam Pulse key is present for users
        if 'Beam Pulse' not in self.port_selections:
            frame = ttk.Frame(self.com_port_menu)
            frame.pack(fill=tk.X, padx=5, pady=2)
            ttk.Label(frame, text="Beam Pulse:").pack(side=tk.LEFT)
            port_var = tk.StringVar(value=self.com_ports.get('Beam Pulse', ''))
            self.port_selections['Beam Pulse'] = port_var
            dropdown = ttk.Combobox(frame, textvariable=port_var)
            dropdown.pack(side=tk.RIGHT)
            self.port_dropdowns['Beam Pulse'] = dropdown

        ttk.Button(self.com_port_menu, text="Apply", command=self.apply_com_port_changes).pack(pady=5)

    def toggle_com_port_menu(self):
        if self.com_port_menu.winfo_viewable():
            self.com_port_menu.pack_forget()
            self.com_port_button.config(text="Configure COM Ports")
        else:
            self.update_available_ports() 
            self.com_port_menu.pack(after=self.com_port_button, fill=tk.X, expand=True)
            self.com_port_button.config(text="Hide COM Port Configuration")

    def update_available_ports(self):
        """Scan for available COM ports and update dropdown menus."""
        available_ports = [port.device for port in serial.tools.list_ports.comports()]
        for dropdown in self.port_dropdowns.values():
            current_value = dropdown.get()
            dropdown['values'] = available_ports
            if current_value in available_ports:
                dropdown.set(current_value)
            elif available_ports:
                dropdown.set(available_ports[0])
            else:
                dropdown.set('')

    def apply_com_port_changes(self):
        new_com_ports = {subsystem: var.get() for subsystem, var in self.port_selections.items()}
        self.update_com_ports(new_com_ports)
        self.toggle_com_port_menu()

    def update_com_ports(self, new_com_ports):
        self.com_ports = new_com_ports
        # TODO: update the COM ports for each subsystem

        for subsystem_name, subsystem in self.subsystems.items():
            if hasattr(subsystem, 'update_com_port'):
                if subsystem_name == 'Vacuum System':
                    subsystem.update_com_port(new_com_ports.get('VTRXSubsystem'))
                elif subsystem_name == 'Cathode Heating':
                    subsystem.update_com_ports(new_com_ports)
            else:
                self.logger.warning(f"Subsystem {subsystem_name} does not have an update_com_port method")
        self.logger.info(f"COM ports updated: {self.com_ports}")


    def _check_ports(self):
        """
        Compares the current available comports to the last set

        Finally:
            Calls itself to be check again
        """
        self.logger.info("checking com ports")
        current_ports = set(serial.tools.list_ports.comports())

        dif = self.set_com_ports - current_ports
        added_ports = current_ports - self.set_com_ports

        try:
            # Process removed ports
            for port in dif:
                if port.serial_number in self.PORT_INFO:
                    self.logger.warning(
                        f"Lost connection to {self.PORT_INFO[port.serial_number]} on {port}")
                    self._update_com_ports(self.PORT_INFO[port.serial_number], None)

            # Process added ports
            for port in added_ports:
                if port.serial_number in self.PORT_INFO:
                    self.logger.info(
                        f"Attempting to connect {self.PORT_INFO[port.serial_number]} to {port}")
                    self._update_com_ports(self.PORT_INFO[port.serial_number], port)
        except Exception as e:
            self.logger.warning(f"Error was thrown when either removing or adding a comport: {e}")

        finally:
            self.set_com_ports = current_ports
            self.root.after(500, self._check_ports)

    def _update_com_ports(self, subsystem_str, port):
        """
        Calls to update subsystems with change in comport
        """
        print("here, updating com port")
        if subsystem_str is None:
            raise ValueError("_update_com_ports was called with invalid args")
        str_port = port.device if port is not None else None
        if subsystem_str in self.subsystems:
            if subsystem_str == "Interlocks":
                self.subsystems[subsystem_str].update_com_port(str_port)
            #TODO: Need to add Vacuum system and Cathode Heating

        self.logger.info(f"COM ports updated: {self.com_ports}")
