import sys
import os
import subsystem
import tkinter as tk
from tkinter import ttk
from instrumentctl.laser_monitor import LaserMonitorDriver
from subsystem.main_control import MainControlPanel
from utils import MessagesFrame, MachineStatus
from usr.com_port_config import get_beam_pulse_com_port
from usr.panel_config import save_pane_states, load_pane_states
import serial.tools.list_ports

def resource_path(relative_path):
    """Get absolute path to resource for PyInstaller."""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


# Total row width = 1916. Vertical guides (from left):
#   x = w_be     — Oil | Process Monitor  lines up with  Beam Energy | Cathode Heating
#   x = w_bp     — Process Monitor | Messages  lines up with  Beam Pulse | Main Control
# Top-row slice widths: Vacuum+Oil = w_be; ProcessMonitor+Messages = w_ch; PM width = w_bp - w_be.
frames_config = [
    # Row 0 — safety strip (full width)
    ("Interlocks", 0, 1916, 41),

    # Row 1 — Vacuum | Oil | Process Monitor | Messages (left → right)
    ("Vacuum System", 1, 350, 400),
    ("Oil System", 1, 350, 400),
    ("Process Monitor", 1, 258, 400),
    ("Messages Frame", 1, 958, 400),

    # Row 2 — Beam Energy | Cathode Heating  (w_be + w_ch = 1916)
    ("Beam Energy", 2, 700, 400),
    ("Cathode Heating", 2, 1216, 400),

    # Row 3 — Beam Pulse | Main Control  (w_bp + w_mc = 1916)
    ("Beam Pulse", 3, 958, 450),
    ("Main Control", 3, 958, 450),

    # Row 4 — machine status
    ("Machine Status", 4, 1916, 38),
]


def _messages_frame_layout():
    """Return (row, width, height) for the Messages Frame entry in frames_config."""
    for title, row, w, h in frames_config:
        if title == "Messages Frame":
            return row, w, h
    raise RuntimeError("frames_config must include 'Messages Frame'")

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

    CLEAR_MAP = {
        "Interlocks": [
        "safetyOutputDataFlags",
        "safetyInputDataFlags",
        "safetyOutputStatusFlags",
        "safetyInputStatusFlags"
    ]}

    def __init__(self, root, com_ports, logger=None):
        self.root = root
        self.com_ports = com_ports
        self.logger = logger
        self.root.title("EBEAM Control System Dashboard")

        self.set_com_ports = set(serial.tools.list_ports.comports())
        self.ports_after_id = None

        # Load toggle images
        try:
            self.toggle_on_image = tk.PhotoImage(file=resource_path("media/toggle_on.png"))
            self.toggle_off_image = tk.PhotoImage(file=resource_path("media/toggle_off.png"))
        except Exception as e:
            self.toggle_on_image = None
            self.toggle_off_image = None
            print(f"Could not load toggle images: {e}")

        # Restore saved pane state if one exists.
        if self.load_saved_pane_state():
            if self.logger is not None:
                self.logger.info("Pane-state restore result: restored saved pane state")
        elif self.logger is not None:
            self.logger.info("Pane-state restore result: no saved pane state applied")

        # Initialize the frames dictionary to store various GUI components
        self.frames = {}
        # Set up the main pane using PanedWindow for flexible layout
        self.setup_main_pane()

        # Set up a frame for displaying messages and errors
        self.create_messages_frame()

        # Initialize all the frames within the main pane
        self.create_frames()

        # Set up a frame for displaying machine status information
        self.create_machine_status_frame()

        # Set up different subsystems within their respective frames
        if self.logger is not None:
            self.logger.info("Subsystem initialization start")
        self.create_subsystems()

        self._check_ports()
        if self.logger is not None:
            self.logger.info("Dashboard ready")

    def cleanup(self):
        """Closes all open com ports before quitting the application."""

        print("Cleaning up com ports...")
        for subsystem_name, subsystem in self.subsystems.items():
            if hasattr(subsystem, 'close_com_ports'):
                try:
                    subsystem.close_com_ports()
                except Exception as e:
                    self.logger.error(f"Error closing COM ports for {subsystem_name}: {e}")
        print("Cleaned up com ports.")

        '''Cancels all scheduled Dashboard updates before quitting the application.'''
        # First cancel updates in each subsystem
        print("Cancelling scheduled Dashboard updates...")
        for subsystem_name, subsystem in self.subsystems.items():
            if hasattr(subsystem, 'cancel_updates'):
                try:
                    subsystem.cancel_updates()
                except Exception as e:
                    self.logger.error(f"Error cancelling updates for {subsystem_name}: {e}")
        # Now cancel com port checks
        if self.ports_after_id is not None:
            try:
                self.root.after_cancel(self.ports_after_id)
                self.ports_after_id = None
                self.logger.debug("Cancelled scheduled com port checks.")
            except Exception as e:
                self.logger.debug("Failed to cancel scheduled com port checks.")
        # Now cancel machine status updates
        if hasattr(self.machine_status_frame, 'cancel_updates'):
            try:
                self.machine_status_frame.cancel_updates()
            except Exception as e:
                self.logger.error(f"Error cancelling machine status updates: {e}")
        print("Dashboard upates cancelled.")

    def setup_main_pane(self):
        """Initialize the main layout pane and its rows for subsystem organization."""
        self.main_pane = tk.PanedWindow(self.root, orient='vertical', sashrelief=tk.RAISED)
        self.main_pane.grid(row=0, column=0, sticky='nsew')
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(0, weight=1)
        self.rows = [tk.PanedWindow(self.main_pane, orient='horizontal', sashrelief=tk.RAISED) for _ in range(5)]
        for row_pane in self.rows:
            self.main_pane.add(row_pane, stretch='always')

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
        """
        Create and configure frames for all subsystems based on frames_config.
        Each frame is added to its designated row in the main pane.
        """
        global frames_config

        for title, row, width, height in frames_config:
            if title == "Beam Pulse Spacer":
                continue

            if width and height and title:
                frame = tk.Frame(borderwidth=1, relief="solid", width=width, height=height)
                frame.pack_propagate(False)
            else:
                frame = tk.Frame(borderwidth=1, relief="solid")
            if title not in ["Interlocks", "Machine Status"]:
                self.add_title(frame, title)
            if title == "Messages Frame":
                continue
            self.frames[title] = frame
            self.rows[row].add(frame, stretch='always')
            if title == "Main Control":
                self.main_control = MainControlPanel(
                    parent_frame=frame,
                    root=self.root,
                    logger=self.logger,
                    messages_frame=self.messages_frame,
                    get_com_ports=lambda: self.com_ports,
                    save_layout_callback=self.save_current_pane_state,
                    update_com_ports_callback=self.update_com_ports,
                    toggle_on_image=self.toggle_on_image,
                    toggle_off_image=self.toggle_off_image,
                )

        _msg_row, _, _ = _messages_frame_layout()
        self.rows[_msg_row].add(self.messages_frame.frame, stretch='always')
        self.frames['Messages Frame'] = self.messages_frame.frame

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
        savedData = load_pane_states(logger=self.logger)
        if not savedData:
            return False
        for i in range(len(frames_config)):
            if frames_config[i][0] in savedData:
                frames_config[i] = (frames_config[i][0], frames_config[i][1], savedData[frames_config[i][0]][0],savedData[frames_config[i][0]][1])
        return True

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
            ),
            'Beam Energy': subsystem.BeamEnergySubsystem(
                self.frames['Beam Energy'],
                com_ports=self.com_ports,
                logger=self.logger
            )
        }

        if hasattr(self, "main_control"):
            self.main_control.subsystems = self.subsystems
            self.main_control.wire_beam_energy(self.subsystems.get('Beam Energy'))

        laser_monitor_port = str(self.com_ports.get('Laser Monitor', '') or '').strip()
        try:
            self.subsystems['Laser Monitor'] = LaserMonitorDriver(laser_monitor_port)
            self.logger.info(f"Laser Monitor driver started for port {laser_monitor_port}")
        except Exception as e:
                self.logger.error(f"Failed to start Laser Monitor driver on port {laser_monitor_port}: {e}")
        else:
            self.logger.info("Laser Monitor driver not started; no COM port configured")

        # Beam Pulse subsystem (BCON)
        try:
            bp_port = get_beam_pulse_com_port(self.com_ports)
            # Host Beam Pulse UI inside the merged pane
            parent = self.frames.get('Beam Steering/Pulse', self.frames.get('Beam Pulse'))
            beam_pulse_subsystem = subsystem.BeamPulseSubsystem(
                parent_frame=parent,
                port=bp_port if bp_port else None,
                unit=1,
                baudrate=115200,
                logger=self.logger
            )

            self.subsystems['Beam Pulse'] = beam_pulse_subsystem
            if hasattr(self, "main_control"):
                self.main_control.subsystems = self.subsystems
                self.main_control.wire_beam_pulse(beam_pulse_subsystem)
        except Exception as e:
            self.logger.error(f"Failed to initialize Beam Pulse subsystem: {e}")

    def create_messages_frame(self):
        """Create a scrollable frame for displaying system messages and errors."""
        _msg_row, _msg_w, _msg_h = _messages_frame_layout()
        self.messages_frame = MessagesFrame(self.rows[_msg_row], width=_msg_w, height=_msg_h, logger=self.logger)
        self.logger = self.messages_frame.logger

    def create_machine_status_frame(self):
        """Create a frame for displaying machine status information."""
        self.machine_status_frame = MachineStatus(self.frames['Machine Status'])

    def update_com_ports(self, new_com_ports):
        self.com_ports = new_com_ports
        # TODO: update the COM ports for each subsystem

        for subsystem_name, subsystem in self.subsystems.items():
            if hasattr(subsystem, 'update_com_port'):
                if subsystem_name == 'Vacuum System':
                    subsystem.update_com_port(new_com_ports.get('VTRXSubsystem'))
                elif subsystem_name == 'Cathode Heating':
                    subsystem.update_com_ports(new_com_ports)
                elif subsystem_name == 'Beam Energy':
                    subsystem.update_com_port(new_com_ports)
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
                    subsystem_name = self.PORT_INFO[port.serial_number]
                    self.logger.warning(
                        f"Lost connection to {subsystem_name} on {port}"
                    )
                    self._update_com_ports(subsystem_name, None)

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
            self.ports_after_id = self.root.after(500, self._check_ports)

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
        if str_port is None:
            for comp in self.CLEAR_MAP.get(subsystem_str, []):
                try:
                    self.logger.clear_value(comp)
                except KeyError:
                    self.logger.debug(f"Key {comp} not found in dict_logger (already cleared?)")

        self.logger.info(f"COM ports updated: {self.com_ports}")
