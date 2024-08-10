import subsystem
import tkinter as tk
from tkinter import ttk
from utils import MessagesFrame, SetupScripts, LogLevel
from usr.panel_config import save_pane_states, load_pane_states

class EBEAMSystemDashboard:
    def __init__(self, root, com_ports):
        self.root = root
        self.com_ports = com_ports
        self.root.title("EBEAM Control System Dashboard")

        # Initialize the frames dictionary to store various GUI components
        self.frames = {}
        
        # Set up the main pane using PanedWindow for flexible layout
        self.setup_main_pane()

        # Initialize all the frames within the main pane
        self.create_frames()

        # Set up a frame for displaying messages and errors
        self.create_messages_frame()

        # Set up different subsystems within their respective frames
        self.create_subsystems()

        # Load the saved state of the GUI pane layout if available
        # self.load_saved_pane_state()

    def setup_main_pane(self):
        """Initialize the main layout pane and its rows."""
        self.main_pane = tk.PanedWindow(self.root, orient='vertical', sashrelief=tk.RAISED)
        self.main_pane.grid(row=0, column=0, sticky='nsew')
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(0, weight=1)

        # Create horizontal paned windows for each row
        self.rows = [tk.PanedWindow(self.main_pane, orient='horizontal', sashrelief=tk.RAISED) for _ in range(5)]
        for row_pane in self.rows:
            self.main_pane.add(row_pane, stretch='always')

    def create_frames(self):
        """Create frames for different systems and controls within the dashboard."""
        frames_config = [
            ("Oil System", 0, 50, 150),
            ("Visualization Gas Control", 0, 50, 150),
            ("System Checks", 0, None, None),
            ("Beam Extraction", 0, None, None),
            ("Vacuum System", 1, 150, 300),
            ("Deflection Monitor", 1, None, None),
            ("Beam Pulse", 1, None, None),
            ("Main Control", 1, 50, 300),
            ("Setup Script", 2, None, 25),
            ("Interlocks", 2, None, 25),
            ("High Voltage Warning", 2, None, 25),
            ("Environmental", 3, 150, 450),
            ("Cathode Heating", 3, 960, 450),
        ]

        for title, row, width, height in frames_config:
            if width and height:
                frame = tk.Frame(borderwidth=1, relief="solid", width=width, height=height)
                frame.pack_propagate(False)
            else:
                frame = tk.Frame(borderwidth=1, relief="solid")

            self.rows[row].add(frame, stretch='always')
            self.add_title(frame, title)
            self.frames[title] = frame
            if title == "Setup Script":
                SetupScripts(frame)
            if title == "Main Control":
                save_layout_button = tk.Button(frame, text="Save Layout", command=self.save_current_pane_state)
                save_layout_button.pack(side=tk.BOTTOM, anchor='se', padx=1, pady=1)
                self.create_log_level_dropdown(frame)

    def add_title(self, frame, title):
        """Add a title label to a frame."""
        label = tk.Label(frame, text=title, font=("Helvetica", 10, "bold"))
        label.pack(pady=0, fill=tk.X)

    def save_current_pane_state(self):
        num_sashes = len(self.rows) - 1  # Assuming each row might have one sash
        save_pane_states(self.main_pane, num_sashes)

    def load_saved_pane_state(self):
        num_sashes = len(self.rows) - 1
        load_pane_states(self.main_pane, num_sashes)

    def create_log_level_dropdown(self, frame):
        log_level_frame = ttk.Frame(frame)
        log_level_frame.pack(side=tk.BOTTOM, anchor='sw', padx=1, pady=1)
        ttk.Label(log_level_frame, text="Log Level:").pack(side=tk.LEFT)

        self.log_level_var = tk.StringVar()
        log_levels = [level.name for level in LogLevel]
        log_level_dropdown = ttk.Combobox(log_level_frame, textvariable=self.log_level_var, values=log_levels, state="readonly")
        log_level_dropdown.pack(side=tk.LEFT, padx=(5, 0))
        log_level_dropdown.set(LogLevel.INFO.name) 
        log_level_dropdown.bind("<<ComboboxSelected>>", self.on_log_level_change)

    def on_log_level_change(self, event):
        selected_level = LogLevel[self.log_level_var.get()]
        self.messages_frame.set_log_level(selected_level)
        print(f"Log level changed to: {selected_level.name}")

    def create_subsystems(self):
        """Initialize subsystems in their designated frames using component settings."""
        self.subsystems = {
            'Vacuum System': subsystem.VTRXSubsystem(
                self.frames['Vacuum System'],
                serial_port=self.com_ports['VTRXSubsystem'], 
                logger=self.logger
            ),
            'Environmental [°C]': subsystem.EnvironmentalSubsystem(
                self.frames['Environmental'], 
                logger=self.logger
            ),
            'Visualization Gas Control': subsystem.VisualizationGasControlSubsystem(
                self.frames['Visualization Gas Control'], 
                logger=self.logger
            ),
            'Interlocks': subsystem.InterlocksSubsystem(
                self.frames['Interlocks'], 
                logger=self.logger
            ),
            'Oil System': subsystem.OilSubsystem(
                self.frames['Oil System'], 
                logger=self.logger
            ), 
            'Cathode Heating': subsystem.CathodeHeatingSubsystem(
                self.frames['Cathode Heating'],
                com_ports=self.com_ports,
                logger=self.logger
            )
        }

    def create_messages_frame(self):
        """Create a frame for displaying messages and errors."""
        self.messages_frame = MessagesFrame(self.rows[3])
        self.rows[3].add(self.messages_frame.frame, stretch='always')
        self.logger = self.messages_frame.logger
