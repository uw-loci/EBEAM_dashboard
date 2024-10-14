# interlocks.py
import tkinter as tk
import os, sys
import instrumentctl.g9_driver as g9_driv
from utils import LogLevel
import time
import random

def handle_errors(self, data):
    try:
        response = g9_driv.response()
        return {"status":"passes", "message":"No errors thrown at this time."}

    except ValueError as e:
        return {"status":"error", "message":str(e)}
    
def resource_path(relative_path):
    """ Get the absolute path to a resource, works for development and when running as bundled executable"""
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)



class InterlocksSubsystem:
    def __init__(self, parent, com_ports, logger=None, frames=None):
        self.parent = parent
        self.logger = logger
        self.com_ports = com_ports
        self.frames = frames
        self.interlock_status = {
            "Vacuum":  random.randint(0, 1), "Water": 0, "Door": 0, "Timer": 1,
            "Oil High": 0, "Oil Low": 0, "E-stop Ext": 1,
            "E-stop Int": 1, "G9SP Active": 1 
        }
        self.setup_gui()

    def setup_gui(self):
        self.interlocks_frame = tk.Frame(self.parent)
        self.interlocks_frame.pack(fill=tk.BOTH, expand=True)

        interlock_labels = [
            "Vacuum", "Water", "Door", "Timer", "Oil High",
            "Oil Low", "E-stop Ext", "E-stop Int", "G9SP Active"
        ]
        self.indicators = {
            'active': tk.PhotoImage(file=resource_path("media/on.png")),
            'inactive': tk.PhotoImage(file=resource_path("media/redOff.png"))
        }

        for label in interlock_labels:
            frame = tk.Frame(self.interlocks_frame)
            frame.pack(side=tk.LEFT, expand=True, padx=5)

            lbl = tk.Label(frame, text=label, font=("Helvetica", 8))
            lbl.pack(side=tk.LEFT)
            status = self.interlock_status[label]
            # if status == 0:
            #     self.highlight_frame('Vacuum System', flashes=5, interval=500)
            # else:
            #     self.reset_frame_highlights()

            indicator = tk.Label(frame, image=self.indicators['active'] if status == 1 else self.indicators['inactive'])
            indicator.pack(side=tk.RIGHT, pady=1)
            frame.indicator = indicator  # Store reference to the indicator for future updates

    # logging the history of updates
    def update_interlock(self, name, status):
        if name in self.parent.children:
            frame = self.parent.children[name]
            indicator = frame.indicator
            new_image = self.indicators['active'] if status else self.indicators['inactive']
            indicator.config(image=new_image)
            indicator.image = new_image  # Keep a reference

            # logging the update
            old_status = self.interlock_status.get(name, None)
            if old_status is not None and old_status != status:
                log_message = f"Interlock status of {name} changed from {old_status} to {status}"
                self.logger.info(log_message)
                self.interlock_status[name] = status # log the previous state, and update it to the new state

    def update_pressure_dependent_locks(self, pressure):
        # Disable the Vacuum lock if pressure is below 2 mbar
        self.update_interlock("Vacuum", pressure >= 2)


    # def reset_frame_highlights(self):
    #     for frame in self.frame.values:
    #         print(self.frame.values)
    #         frame.config(bg=self.parent.cget('bg'))


    # this method right now only sets the frame boarder to be red TODO: make it flash
    def highlight_frame(self, label, flashes=5, interval=500):
        if label in self.frames:
            frame = self.frames[label]
            reg = frame.cget('highlightbackground')
            new_color = 'red'

            frame.config(highlightbackground=new_color, highlightthickness=5, relief='solid')





