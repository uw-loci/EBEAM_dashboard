import subprocess
import sys
import os
import subsystem
import tkinter as tk
from tkinter import ttk
from tkinter import messagebox
from utils import MessagesFrame, SetupScripts, LogLevel, MachineStatus
from usr.panel_config import save_pane_states, load_pane_states, saveFileExists
import serial.tools.list_ports

frames_config = [
    # Row 0
    ("Interlocks", 0, None, 2),
    
    # Row 1
    ("Oil System", 1, 50, 150),
    ("Visualization Gas Control", 2, 50, 150),
    ("System Checks", 1, None, None),
    
    # Row 2
    ("Beam Extraction", 1, None, None),
    ("Vacuum System", 2, 150, 300),
    ("Deflection Monitor", 2, None, None),
    ("Beam Pulse", 2, None, None),
    ("Main Control", 2, 50, 300),
    
    # Row 3
    ("Setup Script", 3, None, 25),
    ("High Voltage Warning", 3, None, 25),
    
    # Row 4
    ("Process Monitor", 4, 250, 450),
    ("Cathode Heating", 4, 980, 450),

    # Row 5
    ("Machine Status", 5, None, 50)
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
        """Initialize the main layout pane and its rows for subsystem organization."""
        self.main_pane = tk.PanedWindow(self.root, orient='vertical', sashrelief=tk.RAISED)
        self.main_pane.grid(row=0, column=0, sticky='nsew')
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(0, weight=1)
        self.rows = [tk.PanedWindow(self.main_pane, orient='horizontal', sashrelief=tk.RAISED) for _ in range(6)]
        for row_pane in self.rows:
            self.main_pane.add(row_pane, stretch='always')

    def create_frames(self):
        """
        Create and configure frames for all subsystems based on frames_config.
        Each frame is added to its designated row in the main pane.
        """
        global frames_config

        for title, row, width, height in frames_config:
            if width and height and title:
                frame = tk.Frame( borderwidth=1, relief="solid", width=width, height=height)
                frame.pack_propagate(False)
            else:
                frame = tk.Frame(borderwidth=1, relief="solid")
            self.rows[row].add(frame, stretch='always')
            if title not in ["Interlocks", "Machine Status"]:
                self.add_title(frame, title)
            self.frames[title] = frame
            if title == "Setup Script":
                SetupScripts(frame)
            if title == "Main Control":
                self.create_main_control_notebook(frame)

        self.rows[4].add(self.messages_frame.frame, stretch='always')

    def create_main_control_notebook(self, frame):
        notebook = ttk.Notebook(frame)
        notebook.pack(expand=True, fill='both')

        main_tab = ttk.Frame(notebook)
        config_tab = ttk.Frame(notebook)

        notebook.add(main_tab, text='Main')
        notebook.add(config_tab, text='Config')

        # TODO: add main control buttons to main tab here

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

        for i in range(len(frames_config)):
            if frames_config[i][0] in savedData:
                frames_config[i] = (frames_config[i][0], frames_config[i][1], savedData[frames_config[i][0]][0],savedData[frames_config[i][0]][1])
        savedData = load_pane_states()

        for i in range(len(frames_config)):
            if frames_config[i][0] in savedData:
                frames_config[i] = (frames_config[i][0], frames_config[i][1], savedData[frames_config[i][0]][0],savedData[frames_config[i][0]][1])

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
            'ProcessMonitors': subsystem.ProcessMonitorSubsystem(
                self.frames['Process Monitor'],
                com_port=self.com_ports['ProcessMonitors'],
                logger=self.logger,
                active = self.machine_status_frame.MACHINE_STATUS
            ),
            'Visualization Gas Control': subsystem.VisualizationGasControlSubsystem(
                self.frames['Visualization Gas Control'],
                logger=self.logger
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

        # Updates machine status progress bar
        self.machine_status_frame.update_status(self.machine_status_frame.MACHINE_STATUS)

    def create_messages_frame(self):
        """Create a scrollable frame for displaying system messages and errors."""
        self.messages_frame = MessagesFrame(self.rows[4])
        self.logger = self.messages_frame.logger

    def create_machine_status_frame(self):
        """Create a frame for displaying machine status information."""
        self.machine_status_frame = MachineStatus(self.frames['Machine Status'])

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
        self.logger.info(available_ports)
        for dropdown in self.port_dropdowns.values():
            current_value = dropdown.get()
            dropdown['values'] = available_ports
            if current_value in available_ports:
                dropdown.set(current_value)
            else:
                dropdown.set('')

    def apply_com_port_changes(self):
        new_com_ports = {subsystem: var.get() for subsystem, var in self.port_selections.items()}
        for sub, port in new_com_ports.items():
            if port:
                self._update_com_ports(sub, port)

        self.toggle_com_port_menu()

    # def update_com_ports(self, new_com_ports):
    #     self.com_ports = new_com_ports
    #     # TODO: update the COM ports for each subsystem

    #     self.logger.info(f"________________________________ here : {new_com_ports=}")

    #     for subsystem_name, subsystem in self.subsystems.items():
    #         if hasattr(subsystem, 'update_com_port'):
    #             if subsystem_name == 'Vacuum System':
    #                 subsystem.update_com_port(new_com_ports.get('VTRXSubsystem'))
    #             elif subsystem_name == 'Cathode Heating':
    #                 subsystem.update_com_ports(new_com_ports)
    #         else:
    #             self.logger.warning(f"Subsystem {subsystem_name} does not have an update_com_port method")
    #     self.logger.info(f"COM ports updated: {self.com_ports}")


    def _check_ports(self):
        """
        Compares the current available comports to the last set

        Finally:
            Calls itself to be check again
        """
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
        
        # if subsystem_str is None:
        #     raise ValueError("_update_com_ports was called with invalid args")
        if not isinstance(port, str):
            str_port = port.device if port is not None else None
        else:
            str_port = port

        self.logger.info(f"{subsystem_str=} : {port=} ________________________________")
        if subsystem_str in self.subsystems:
            if subsystem_str in set(["Interlocks", 'Vacuum System', 'ProcessMonitors']):
                self.subsystems[subsystem_str].update_com_port(str_port)
            # elif subsystem_str == 'Cathode Heating':
            #         self.subsystems[subsystem_str].update_com_ports(new_com_ports)
            #TODO: Need to add Vacuum system and Cathode Heating

        self.logger.info(f"COM ports updated: {self.com_ports}")
