# interlocks.py
import tkinter as tk
import os, sys
from ..instrumentctl import g9_driver as g9_driv
# import instrumentctl.g9_driver as g9_driv
# from logging import LogLevel



    
def handle_errors(self, data):
    try:
        response = g9_driv.response()
        g9_driv.safetyInTerminalError(response)
        g9_driv.safetyOutTerminalError(response)
        g9_driv.unitStateError(response)
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
    def __init__(self, parent, logger=None):
        self.parent = parent
        self.logger = logger
        self.interlock_status = {
            "Vacuum": True, "Water": False, "Door&Lock": False, "Timer": True,
            "Oil High": False, "Oil Low": False, "E-stop Ext": True,
            "E-stop Int": True, "G9SP Active": True
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
            'active': tk.PhotoImage(file=resource_path("media/off_orange.png")),
            'inactive': tk.PhotoImage(file=resource_path("media/on.png"))
        }

        for label in interlock_labels:
            frame = tk.Frame(self.interlocks_frame)
            frame.pack(side=tk.LEFT, expand=True, padx=5)

            lbl = tk.Label(frame, text=label, font=("Helvetica", 8))
            lbl.pack(side=tk.LEFT)
            status = self.interlock_status[label]
            if not status:
                self.highlight_frame(label)
            else:
                self.reset_frame_highlights()
            indicator = tk.Label(frame, image=self.indicators['active'] if status else self.indicators['inactive'])
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

    def update_pressure_dependent_locks(self, pressure):
        # Disable the Vacuum lock if pressure is below 2 mbar
        self.update_interlock("Vacuum", pressure >= 2)


    def reset_frame_highlights(self):
        for frame in self.frame.values:
            print(self.frame.values)
            frame.config(bg=self.parent.cget('bg'))



    def highlight_frame(self, label):
        if label in self.frames:
            self.frames[label].config(bg="red")

