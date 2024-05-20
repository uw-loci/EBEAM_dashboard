# dashboard.py
import tkinter as tk
from subsystem import Subsystem

class EBEAMSystemDashboard:
    def __init__(self, root):
        self.root = root
        self.root.title("EBEAM Control System Dashboard")

        # Create frames for each subsystem
        self.create_frames()
        self.create_subsystems()

    def create_frames(self):
        self.frames = {
            'Oil System': tk.Frame(self.root, borderwidth=2, relief="solid"),
            'System Checks': tk.Frame(self.root, borderwidth=2, relief="solid"),
            'Beam Extraction': tk.Frame(self.root, borderwidth=2, relief="solid"),
            'Vacuum System': tk.Frame(self.root, borderwidth=2, relief="solid"),
            'Cathode Heating': tk.Frame(self.root, borderwidth=2, relief="solid"),
            'Main Control': tk.Frame(self.root, borderwidth=2, relief="solid"),
            'Messages & Errors': tk.Frame(self.root, borderwidth=2, relief="solid")
        }

        for i, (title, frame) in enumerate(self.frames.items()):
            frame.grid(row=i//3, column=i%3, sticky="nsew")
            self.add_title(frame, title)

        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_columnconfigure(2, weight=1)
        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_rowconfigure(1, weight=1)
        self.root.grid_rowconfigure(2, weight=1)

    def add_title(self, frame, title):
        label = tk.Label(frame, text=title, font=("Helvetica", 16, "bold"))
        label.pack(pady=10)

    def create_subsystems(self):
        self.subsystems = {
            'Vacuum System': Subsystem(self.frames['Vacuum System']),
            # Add other subsystems when implemented
        }
