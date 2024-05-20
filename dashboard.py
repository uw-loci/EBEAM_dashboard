import tkinter as tk
from subsystem import VTRXSubsystem, EnvironmentalSubsystem, ArgonBleedControlSubsystem
from utils import MessagesFrame, SetupScripts
from usr.panel_config import save_pane_state, load_pane_state

class EBEAMSystemDashboard:
    def __init__(self, root, com_ports):
        self.root = root
        self.com_ports = com_ports
        self.root.title("EBEAM Control System Dashboard")

        # Initialize the frames dictionary to store various GUI components
        self.frames = {}
        
        # Set up the main pane using PanedWindow for a flexible layout
        self.setup_main_pane()

        # Initialize all the frames within the main pane
        self.create_frames()

        # Set up different subsystems within their respective frames
        self.create_subsystems()

        # Set up a frame for displaying messages and errors
        self.create_messages_frame()

        # Load the saved state of the GUI pane layout if available
        self.load_saved_pane_state()

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
            ("Oil System", 0),
            ("Argon Bleed Control", 0),
            ("System Checks", 0),
            ("Beam Extraction", 0),
            ("Vacuum System", 1),
            ("Deflection Monitor", 1),
            ("Main Control", 1),
            ("Interlocks", 2),
            ("High Voltage Warning", 2),
            ("Setup Script", 3),
            ("Beam Pulse", 3),
            ("Environmental", 4),
            ("Cathode Temp", 4),
        ]

        for title, row in frames_config:
            frame = tk.Frame(borderwidth=2, relief="solid")
            self.rows[row].add(frame, stretch='always')
            self.add_title(frame, title)
            self.frames[title] = frame
            if title == "Setup Script":
                SetupScripts(frame)
            if title == "Main Control":
                save_layout_button = tk.Button(frame, text="Save Layout", command=self.save_current_pane_state)
                save_layout_button.pack(side=tk.BOTTOM, anchor='se', padx=5, pady=5)

    def add_title(self, frame, title):
        """Add a title label to a frame."""
        label = tk.Label(frame, text=title, font=("Helvetica", 12, "bold"))
        label.pack(pady=1, fill=tk.X)

    def save_current_pane_state(self):
        num_sashes = len(self.rows) - 1  # Assuming each row might have one sash
        save_pane_state(self.main_pane, num_sashes)

    def load_saved_pane_state(self):
        num_sashes = len(self.rows) - 1
        load_pane_state(self.main_pane, num_sashes)

    def create_subsystems(self):
        """Initialize subsystems in their designated frames using component settings."""
        self.subsystems = {
            'Vacuum System': VTRXSubsystem(self.frames['Vacuum System'], serial_port=self.com_ports['VTRXSubsystem']),
            'Environmental': EnvironmentalSubsystem(self.frames['Environmental']),
            'Argon Bleed Control': ArgonBleedControlSubsystem(self.frames['Argon Bleed Control'], serial_port=self.com_ports['ApexMassFlowController'])
        }

    def create_messages_frame(self):
        """Create a frame for displaying messages and errors."""
        self.messages_frame = MessagesFrame(self.rows[4])
        self.rows[4].add(self.messages_frame.frame, stretch='always')