import tkinter as tk
from subsystem import VTRXSubsystem, EnvironmentalSubsystem, ArgonBleedControlSubsystem
from utils import MessagesFrame

class EBEAMSystemDashboard:
    def __init__(self, root):
        self.root = root
        self.root.title("EBEAM Control System Dashboard")

        # Set up the main pane using PanedWindow for a more flexible layout
        self.main_pane = tk.PanedWindow(self.root, orient='vertical', sashrelief=tk.RAISED)
        self.main_pane.grid(row=0, column=0, sticky='nsew')  # Ensuring that main_pane uses grid

        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(0, weight=1)

        # Initialize rows for PanedWindows
        self.rows = [tk.PanedWindow(self.main_pane, orient='horizontal', sashrelief=tk.RAISED) for _ in range(5)]
        for index, row_pane in enumerate(self.rows):
            self.main_pane.add(row_pane, stretch='always')

        self.frames = {}
        self.create_frames()
        self.create_subsystems()
        self.create_messages_frame()

    def create_frames(self):
        frames_config = [
            ("Oil System", 0),
            ("Argon Bleed Control", 0),
            ("Solenoid 2 Temp", 0),
            ("System Checks", 0),
            ("Beam Extraction", 0),
            ("Vacuum System", 1),
            ("Approve High Voltage & Radiation Operation", 1),
            ("Main Control", 1),
            ("Interlocks", 2),
            ("Solenoid deflection", 2),
            ("Setup Script", 3),
            ("Beam Pulse", 3),
            ("Environmental", 4),
            ("Cathode Temp", 4),
        ]

        for title, row in frames_config:
            frame = tk.Frame(borderwidth=2, relief="solid")
            self.rows[row].add(frame, stretch='always')
            self.add_title(frame, title)  # Add a title to each frame
            self.frames[title] = frame

    def add_title(self, frame, title):
        """Adds a title label to the frame"""
        label = tk.Label(frame, text=title, font=("Helvetica", 16, "bold"))
        label.pack(pady=10, fill=tk.X)

    def create_subsystems(self):
        self.subsystems = {
            'Vacuum System': VTRXSubsystem(self.frames['Vacuum System']),
            'Environmental': EnvironmentalSubsystem(self.frames['Environmental']),
            'Argon Bleed Control': ArgonBleedControlSubsystem(self.frames['Argon Bleed Control'])
        }

    def create_messages_frame(self):
        # Assuming Messages & Errors is correctly managed in row 4
        self.messages_frame = MessagesFrame(self.rows[4])
        self.rows[4].add(self.messages_frame.frame, stretch='always')
