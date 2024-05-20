# dashboard.py
import tkinter as tk
from subsystem import VTRXSubsystem, EnvironmentalSubsystem

class EBEAMSystemDashboard:
    def __init__(self, root):
        self.root = root
        self.root.title("EBEAM Control System Dashboard")

        # Create frames for each subsystem
        self.create_frames()
        self.create_subsystems()

    def create_frames(self):
        # Define frame titles and their positions in the grid
        frames_config = [
            ("Oil System", 0, 0),
            ("Solenoid 1 Temp", 0, 1),
            ("Solenoid 2 Temp", 0, 2),
            ("System Checks", 0, 3),
            ("Beam Extraction", 0, 4),
            ("Vacuum System", 1, 0),
            ("Approve High Voltage & Radiation Operation", 1, 1, 1, 3),  # Span 3 columns
            ("Main Control", 1, 4),
            ("Interlocks", 2, 0),
            ("Solenoid deflection", 2, 1),
            ("Setup Script", 3, 0),
            ("Beam Pulse", 3, 1),
            ("Environmental", 4, 0),
            ("Cathode Temp", 4, 1),
            ("Messages & Errors", 4, 4)
        ]

        self.frames = {}

        for frame_config in frames_config:
            title, row, col = frame_config[:3]
            rowspan = frame_config[3] if len(frame_config) > 3 else 1
            colspan = frame_config[4] if len(frame_config) > 4 else 1

            frame = tk.Frame(self.root, borderwidth=2, relief="solid")
            frame.grid(row=row, column=col, rowspan=rowspan, columnspan=colspan, sticky="nsew")
            self.add_title(frame, title)
            self.frames[title] = frame

        # Configure grid to be resizable
        for i in range(5):
            self.root.grid_columnconfigure(i, weight=1)
            self.root.grid_rowconfigure(i, weight=1)

    def add_title(self, frame, title):
        label = tk.Label(frame, text=title, font=("Helvetica", 16, "bold"))
        label.pack(pady=10)

    def create_subsystems(self):
        self.subsystems = {
            'Vacuum System': VTRXSubsystem(self.frames['Vacuum System']),
            'Environmental': EnvironmentalSubsystem(self.frames['Environmental'])
            # Add other subsystems when implemented
        }
