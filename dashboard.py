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
except Exception:
    BeamPulseSubsystem = None

try:
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    _HAS_MATPLOTLIB = True
except Exception:
    _HAS_MATPLOTLIB = False

def resource_path(relative_path):
    """Get absolute path to resource for PyInstaller."""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

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
        
        # Load toggle images
        try:
            self.toggle_on_image = tk.PhotoImage(file=resource_path("media/toggle_on.png"))
            self.toggle_off_image = tk.PhotoImage(file=resource_path("media/toggle_off.png"))
        except Exception as e:
            self.toggle_on_image = None
            self.toggle_off_image = None
            print(f"Could not load toggle images: {e}")
        
        
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

        # Bind adaptive resize AFTER all frames are created so that
        # Configure events fired during construction are ignored.
        self.root.bind('<Configure>', self._on_window_resize)

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

        # Adaptive layout: compute design reference dimensions from frames_config.
        # _last_w/_last_h start at 0 (sentinel = "not yet seen a real window size").
        # On the first <Configure> event with a real size we scale from the design
        # reference to the actual window; subsequent events scale incrementally.
        _row_heights = {}
        _row_widths = {}
        for _, row, w, h in frames_config:
            _row_heights[row] = max(_row_heights.get(row, 0), h or 0)
            _row_widths[row] = _row_widths.get(row, 0) + (w or 0)
        self._design_w = max(_row_widths.values()) if _row_widths else 1920
        self._design_h = sum(_row_heights.values()) if _row_heights else 1060
        self._last_w = 0   # 0 = not yet initialised
        self._last_h = 0
        self._resize_pending = None  # after() id for debounced reflow

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

    def _on_window_resize(self, event):
        """Handle window <Configure> events and scale frames proportionally."""
        if event.widget is not self.root:
            return
        new_w = self.root.winfo_width()
        new_h = self.root.winfo_height()
        # Skip spurious pre-render events where Tk reports the window as tiny.
        if new_w < 50 or new_h < 50:
            return
        if new_w == self._last_w and new_h == self._last_h:
            return
        # Determine the reference to scale FROM:
        # - First real event  → scale from original design reference
        # - Subsequent events → scale incrementally from previous size
        ref_w = self._design_w if self._last_w == 0 else self._last_w
        ref_h = self._design_h if self._last_h == 0 else self._last_h
        if ref_w > 0 and ref_h > 0:
            scale_x = new_w / ref_w
            scale_y = new_h / ref_h
            for i, (title, row, w, h) in enumerate(frames_config):
                frames_config[i] = (
                    title, row,
                    max(80, int(w * scale_x)),
                    max(10, int(h * scale_y)),
                )
        self._last_w = new_w
        self._last_h = new_h
        # Debounce: wait 50 ms after the last resize event before reflowing.
        if self._resize_pending is not None:
            self.root.after_cancel(self._resize_pending)
        self._resize_pending = self.root.after(50, self._do_resize_reflow)

    def _do_resize_reflow(self):
        """Perform the actual reflow after the debounce period."""
        self._resize_pending = None
        self._reflow_all()

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
            if frame and width > 0 and height > 0:
                frame.place(x=x, y=y, width=width, height=height)
            # Always advance offset, even for spacer/non-rendered entries
            row_x_offsets[row] = x + (width or 0)

        # Add vertical sashes between neighbors in each row
        for row, members in row_members.items():
            # Recalculate X running sum for sash positions
            x = 0
            y = row_to_y[row]
            sash_h = row_max_heights.get(row, 0)
            for idx in range(len(members) - 1):
                left_title, left_w, left_h = members[idx]
                right_title, right_w, right_h = members[idx + 1]
                x += left_w
                if sash_h <= 0:
                    continue  # skip zero-height sashes (would crash X11)
                sash = tk.Frame(self.main_pane, cursor='sb_h_double_arrow', bg='#CCCCCC')
                sash_w = 5
                sash.place(x=x - sash_w // 2, y=y, width=sash_w, height=sash_h)
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
            if width <= 0 or height <= 0:
                continue  # skip zero-dimension grips (would crash X11)
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
        # Save reference so beam_pulse subsystem can add its buttons here
        self.main_control_frame = main_frame

        # Add safety beams off button (bottom)
        beams_off_button = tk.Button(
            main_frame,
            text="BEAMS E-STOP",
            bg="red",
            fg="white",
            font=("Helvetica",14,"bold"),
            command=self.handle_beams_off
        )
        beams_off_button.pack(side="bottom", fill="x", padx=10, pady=(4, 8))

        # Script dropdown
        self.create_script_dropdown(main_frame)

        # Placeholder frame for CSV sequence buttons — populated by
        # BeamPulseSubsystem.create_csv_buttons() in create_subsystems().
        # Not packed here; shown only when the CSV Sequence tab is active.
        self.csv_buttons_frame = ttk.Frame(main_frame)

        # --- Manual-tab panel: Beam ON/OFF + CH Enable/Disable buttons --
        # Stored as self.bp_manual_panel so the beam_pulse subsystem can swap
        # it in/out when the Beam Pulse notebook tab changes.
        self.bp_manual_panel = tk.Frame(main_frame)
        self.bp_manual_panel.pack(side="top", fill="x", padx=10, pady=(10, 0))

        # Beam ON/OFF row — saved so the tab-change handler can show/hide it
        self.beam_on_off_frame = tk.Frame(self.bp_manual_panel)
        self.beam_on_off_frame.pack(side="top", fill="x")
        buttons_frame = self.beam_on_off_frame
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
                state="disabled",  # disabled until armed AND channel enabled
                command=lambda idx=i: self.toggle_individual_beam_with_status(idx)
            )
            btn.grid(row=0, column=i, sticky="ew", padx=2)
            self.beam_toggle_buttons.append(btn)

        # CH Enable/Disable row
        enable_toggle_frame = tk.Frame(self.bp_manual_panel)
        enable_toggle_frame.pack(side="top", fill="x", pady=(4, 0))
        for i in range(3):
            enable_toggle_frame.grid_columnconfigure(i, weight=1, uniform="button")
        self.enable_toggle_buttons = []
        self._ch_enable_states = [False, False, False]  # local tracked enable state
        for i in range(3):
            btn = tk.Button(
                enable_toggle_frame,
                text=f"CH{i+1}: Disabled",
                bg="#888888",
                fg="white",
                font=("Helvetica", 9),
                state="disabled",  # Initially disabled until armed
                command=lambda idx=i: self._toggle_channel_enable(idx)
            )
            btn.grid(row=0, column=i, sticky="ew", padx=2)
            self.enable_toggle_buttons.append(btn)

        # Add beams armed toggle
        beams_armed_control_frame = tk.Frame(main_frame)
        beams_armed_control_frame.pack(side="bottom", fill="x", padx=10, pady=(8, 4))
        
        beams_armed_label_frame = ttk.Frame(beams_armed_control_frame)
        beams_armed_label_frame.pack(pady=(0, 2))
        ttk.Label(beams_armed_label_frame, text="BEAMS ARMED", font=("Helvetica", 12, "bold")).pack()
        
        if self.toggle_on_image and self.toggle_off_image:
            self.beams_ready_button = tk.Button(
                beams_armed_control_frame,
                image=self.toggle_off_image,
                command=self.handle_arm_beams,
                relief=tk.FLAT,
                bd=0,
                bg="white"
            )
        else:
            self.beams_ready_button = tk.Button(
                beams_armed_control_frame,
                text="ARM BEAMS",
                bg="sky blue",
                fg="white",
                font=("Helvetica",16,"bold"),
                command=self.handle_arm_beams
            )
        self.beams_ready_button.pack()

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
        """Handle ARM BEAMS toggle press with state management."""
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
                    # Successfully disarmed - update toggle to OFF
                    if self.toggle_on_image and self.toggle_off_image:
                        self.beams_ready_button.config(image=self.toggle_off_image)
                    else:
                        self.beams_ready_button.config(
                            text="ARM BEAMS",
                            bg="sky blue"
                        )
                    # Disable beam toggle buttons, enable toggle buttons and reset states
                    self.update_beam_toggle_states(enabled=False, reset=True)
                    self._update_enable_toggle_states(enabled=False)
                    self.logger.info("Beams disarmed via dashboard button")
                else:
                    self.logger.error("Failed to disarm beams")
                    messagebox.showerror("Error", "Failed to disarm beams")
            else:
                # Beams are not armed, so arm them
                if hasattr(beam_pulse, 'arm_beams') and beam_pulse.arm_beams():
                    # Successfully armed - update toggle to ON
                    if self.toggle_on_image and self.toggle_off_image:
                        self.beams_ready_button.config(image=self.toggle_on_image)
                    else:
                        self.beams_ready_button.config(
                            text="BEAMS ARMED",
                            bg="navy"  # Darker shade of blue
                        )
                    # Enable beam toggle buttons and enable toggle buttons
                    self.update_beam_toggle_states(enabled=True)
                    self._update_enable_toggle_states(enabled=True)
                    self.logger.info("Beams armed via dashboard button")
                else:
                    self.logger.error("Failed to arm beams")
                    messagebox.showerror("Error", "Failed to arm beams")
                    
        except Exception as e:
            self.logger.error(f"Error in handle_arm_beams: {str(e)}")
            messagebox.showerror("Error", f"Error handling beam arming: {str(e)}")

    def handle_beams_off(self):
        """Handle Beams E-stop button press — force stop all BCON channels,
        turn off cathode heating, and disarm beams."""
        try:
            # Force stop all BCON channels immediately
            if 'Beam Pulse' in self.subsystems and self.subsystems['Beam Pulse'] is not None:
                beam_pulse = self.subsystems['Beam Pulse']
                if hasattr(beam_pulse, 'stop_all_channels'):
                    beam_pulse.stop_all_channels()
                    self.logger.info("All BCON channels force-stopped via E-STOP")

            # Turn off cathode heating power supplies
            if 'Cathode Heating' in self.subsystems and self.subsystems['Cathode Heating'] is not None:
                cathode = self.subsystems['Cathode Heating']
                if hasattr(cathode, 'turn_off_all_beams'):
                    cathode.turn_off_all_beams()
                    self.logger.info("Cathode heating turned off via Beams E-stop button")
            
            # Disarm beams
            if 'Beam Pulse' in self.subsystems and self.subsystems['Beam Pulse'] is not None:
                beam_pulse = self.subsystems['Beam Pulse']
                if hasattr(beam_pulse, 'get_beams_armed_status') and beam_pulse.get_beams_armed_status():
                    if hasattr(beam_pulse, 'disarm_beams') and beam_pulse.disarm_beams():
                        # Update the ARM BEAMS toggle state to OFF
                        if self.toggle_on_image and self.toggle_off_image:
                            self.beams_ready_button.config(image=self.toggle_off_image)
                        else:
                            self.beams_ready_button.config(
                                text="ARM BEAMS",
                                bg="sky blue"
                            )
                        # Disable beam toggle buttons, enable toggle buttons and reset states
                        self.update_beam_toggle_states(enabled=False, reset=True)
                        self._update_enable_toggle_states(enabled=False)
                        self.logger.info("Beams disarmed via Beams E-stop button")
                    else:
                        self.logger.error("Failed to disarm beams via Beams E-stop")
        except Exception as e:
            self.logger.error(f"Error in handle_beams_off: {str(e)}")

    def _toggle_channel_enable(self, ch_index: int):
        """Toggle the hardware enable for a BCON channel (0-based index).

        Only allowed when beams are armed.  When the channel is being
        disabled (enabled -> disabled), also send OFF to ensure the
        channel stops outputting.  Button reflects ON (green) / OFF (gray).
        """
        try:
            beam_pulse = self.subsystems.get('Beam Pulse')
            if not beam_pulse or not hasattr(beam_pulse, 'get_beams_armed_status'):
                self.logger.warning("Beam Pulse subsystem not available")
                return
            if not beam_pulse.get_beams_armed_status():
                self.logger.warning("Cannot toggle enable — beams not armed")
                return
            if beam_pulse.bcon_driver:
                # Use local tracked state as the primary source of truth so the
                # toggle is always reliable regardless of hardware query timing.
                was_enabled = self._ch_enable_states[ch_index]
                new_enabled = not was_enabled
                self._ch_enable_states[ch_index] = new_enabled
                beam_pulse.bcon_driver.toggle_channel_enable(ch_index + 1)
                self.logger.info(
                    f"CH{ch_index + 1} enable -> {'Enabled' if new_enabled else 'Disabled'}")
                # Update enable button appearance
                if ch_index < len(self.enable_toggle_buttons):
                    btn = self.enable_toggle_buttons[ch_index]
                    if new_enabled:
                        btn.config(bg="#2e7d32", text=f"CH{ch_index+1}: Enabled")   # dark green
                    else:
                        btn.config(bg="#888888", text=f"CH{ch_index+1}: Disabled")  # gray
                # Enable/disable the beam ON/OFF button to match channel enable state
                if ch_index < len(self.beam_toggle_buttons):
                    self.beam_toggle_buttons[ch_index].config(
                        state="normal" if new_enabled else "disabled")
                # If we just disabled the channel, force it OFF
                if was_enabled:
                    beam_pulse.send_channel_off(ch_index)
                    beam_names = ["A", "B", "C"]
                    if ch_index < len(self.beam_toggle_buttons):
                        self.beam_toggle_buttons[ch_index].config(
                            bg="gray", text=f"Beam {beam_names[ch_index]} OFF")
            else:
                self.logger.warning("BCON driver not available for enable toggle")
        except Exception as e:
            self.logger.error(f"Error toggling CH{ch_index + 1} enable: {e}")

    def toggle_individual_beam_with_status(self, beam_index):
        """Toggle individual beam on/off.

        ON  = read channel config from Beam Pulse panel and send to BCON.
        OFF = send OFF command for the channel.
        """
        try:
            if 'Beam Pulse' not in self.subsystems or self.subsystems['Beam Pulse'] is None:
                self.logger.error("Beam Pulse subsystem not available")
                return
            
            beam_pulse = self.subsystems['Beam Pulse']
            beam_names = ["A", "B", "C"]
            
            # Get current beam status
            current_status = beam_pulse.get_beam_status(beam_index)
            btn = self.beam_toggle_buttons[beam_index]

            if current_status:
                # Currently ON -> turn OFF
                beam_pulse.send_channel_off(beam_index)
                btn.config(bg="gray", text=f"Beam {beam_names[beam_index]} OFF")
                self.logger.info(f"Beam {beam_names[beam_index]} turned OFF")
            else:
                # Currently OFF -> send channel config to BCON
                ok = beam_pulse.send_channel_config(beam_index)
                if ok:
                    btn.config(bg="green", text=f"Beam {beam_names[beam_index]} ON")
                    self.logger.info(f"Beam {beam_names[beam_index]} config sent to BCON")
                else:
                    self.logger.error(f"Failed to send Beam {beam_names[beam_index]} config")
                    
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
    
    def handle_beam_pulse_callback(self, beam_index, status, duration=0):
        """Handle beam pulse callback for button updates.
        
        This method is called by the beam pulse subsystem when beam status changes.
        """
        try:
            beam_names = ["A", "B", "C"]
            
            if status:
                # Beam turned ON - update button display
                if beam_index < len(self.beam_toggle_buttons):
                    self.beam_toggle_buttons[beam_index].config(bg="green", text=f"Beam {beam_names[beam_index]} ON")
                
                if duration > 0:
                    self.logger.info(f"Beam {beam_names[beam_index]} pulsed for {duration}ms")
                    # Schedule auto turn-off after pulse duration
                    self.root.after(int(duration), lambda: self.auto_turn_off_beam(beam_index))
                else:
                    self.logger.info(f"Beam {beam_names[beam_index]} turned ON in DC mode")
            else:
                # Beam turned OFF - update button display
                if beam_index < len(self.beam_toggle_buttons):
                    self.beam_toggle_buttons[beam_index].config(bg="gray", text=f"Beam {beam_names[beam_index]} OFF")
                
        except Exception as e:
            self.logger.error(f"Error in beam pulse callback for beam {beam_index}: {str(e)}")

    def _on_channel_status_update(self, ch: int, mode_code: int, remaining: int):
        """Mirror live BCON register state onto the Beam A/B/C toggle button.

        Called on every register-poll cycle by BeamPulseSubsystem.
        mode_code=0 means OFF; remaining=0 means all pulses delivered.
        """
        beam_names = ["A", "B", "C"]
        if not hasattr(self, 'beam_toggle_buttons') or ch >= len(self.beam_toggle_buttons):
            return
        btn = self.beam_toggle_buttons[ch]
        # DC mode never counts down, so remaining is always 0 in hardware.
        # Treat DC as running whenever mode != OFF to prevent button glitching.
        MODE_DC = 1
        is_running = (mode_code != 0) and (remaining > 0 or mode_code == MODE_DC)
        try:
            if is_running:
                btn.config(bg="green", text=f"Beam {beam_names[ch]} ON")
                if 'Beam Pulse' in self.subsystems and self.subsystems['Beam Pulse'] is not None:
                    self.subsystems['Beam Pulse'].beam_on_status[ch] = True
            else:
                # Only reset to gray when the button is currently green
                # (avoids overwriting a manually-initiated OFF state)
                if str(btn.cget('bg')) == 'green':
                    btn.config(bg="gray", text=f"Beam {beam_names[ch]} OFF")
                    if 'Beam Pulse' in self.subsystems and self.subsystems['Beam Pulse'] is not None:
                        self.subsystems['Beam Pulse'].beam_on_status[ch] = False
        except Exception:
            pass

    def update_beam_toggle_states(self, enabled=True, reset=False):
        """Update the state of beam toggle buttons."""
        try:
            if not hasattr(self, 'beam_toggle_buttons'):
                return
                
            beam_names = ["A", "B", "C"]
            
            for i, btn in enumerate(self.beam_toggle_buttons):
                if enabled:
                    # Only allow beam ON/OFF when the channel hardware enable is also ON
                    ch_enabled = (
                        hasattr(self, '_ch_enable_states')
                        and i < len(self._ch_enable_states)
                        and self._ch_enable_states[i]
                    )
                    btn.config(state="normal" if ch_enabled else "disabled")
                    if reset:
                        btn.config(bg="gray", text=f"Beam {beam_names[i]} OFF")
                        if 'Beam Pulse' in self.subsystems and self.subsystems['Beam Pulse'] is not None:
                            beam_pulse = self.subsystems['Beam Pulse']
                            if hasattr(beam_pulse, 'set_beam_status'):
                                beam_pulse.set_beam_status(i, False)
                else:
                    btn.config(state="disabled", bg="gray", text=f"Beam {beam_names[i]} OFF")
                    if reset:
                        if 'Beam Pulse' in self.subsystems and self.subsystems['Beam Pulse'] is not None:
                            beam_pulse = self.subsystems['Beam Pulse']
                            if hasattr(beam_pulse, 'set_beam_status'):
                                beam_pulse.set_beam_status(i, False)
                                
        except Exception as e:
            self.logger.error(f"Error updating beam toggle states: {str(e)}")

    def _update_enable_toggle_states(self, enabled=True):
        """Enable or disable the CH Enable toggle buttons based on armed status.
        When disabling (disarmed / E-STOP), also resets all buttons to OFF appearance.
        """
        try:
            if not hasattr(self, 'enable_toggle_buttons'):
                return
            for i, btn in enumerate(self.enable_toggle_buttons):
                if enabled:
                    btn.config(state="normal")
                    # Keep current Enabled/Disabled appearance; don't forcibly reset visual
                else:
                    # Disarmed — force all to Disabled appearance and reset tracking
                    btn.config(state="disabled", bg="#888888", text=f"CH{i+1}: Disabled")
                    if hasattr(self, '_ch_enable_states') and i < len(self._ch_enable_states):
                        self._ch_enable_states[i] = False
        except Exception as e:
            self.logger.error(f"Error updating enable toggle states: {str(e)}")

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
            if BeamPulseSubsystem is not None:
                # Host Beam Pulse UI inside the merged pane
                parent = self.frames.get('Beam Steering/Pulse', self.frames.get('Beam Pulse'))
                beam_pulse_subsystem = BeamPulseSubsystem(
                    parent_frame=parent,
                    port=bp_port if bp_port else None,
                    unit=1,
                    baudrate=115200,
                    logger=self.logger
                )
                
                # Set up dashboard callback for pulse animations
                beam_pulse_subsystem.set_dashboard_beam_callback(self.handle_beam_pulse_callback)

                # Add Sync Start/Stop and wire tab-aware panel visibility.
                if hasattr(self, 'main_control_frame'):
                    manual_panel = getattr(self, 'bp_manual_panel', None)
                    beam_pulse_subsystem.create_external_control_buttons(
                        self.main_control_frame,
                        manual_panel_override=manual_panel,
                        beam_on_off_frame=getattr(self, 'beam_on_off_frame', None),
                        csv_frame=getattr(self, 'csv_buttons_frame', None),
                    )

                # CSV sequence buttons below the script-selection dropdown
                if hasattr(self, 'csv_buttons_frame'):
                    beam_pulse_subsystem.create_csv_buttons(self.csv_buttons_frame)

                # Mirror live BCON register state onto the Beam toggle buttons
                beam_pulse_subsystem.set_channel_status_callback(
                    self._on_channel_status_update
                )

                # Let Sync Start know which channels are hardware-enabled
                beam_pulse_subsystem.set_channel_enable_getter(
                    lambda: list(getattr(self, '_ch_enable_states', [True, True, True]))
                )

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
