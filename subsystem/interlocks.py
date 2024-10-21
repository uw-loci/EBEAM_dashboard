# interlocks.py
import tkinter as tk
import os, sys
import instrumentctl.g9_driver as g9_driv
from utils import LogLevel
import time

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
        self.driver = g9_driv.G9Driver(None)
        self.parent = parent
        self.logger = logger
        self.frames = frames
        self.interlock_status = {
            "Door":  1, "Water": 0, "Vacuum Power": 0, "Vacuum Pressure": 1,
            "Oil High": 0, "Oil Low": 0, "Chassis Estop": 1,
            "Chassis Estop": 1, "All Interlocks" : 0, "G9SP Active": 1, "HVOLT ON" : 0 
        }
        self.setup_gui()

    def update_com_port(self, com_port):
        if com_port:
            self.driver = g9_driv.G9Driver(com_port)

    def setup_gui(self):
        def create_indicator_circle(frame, color):
            canvas = tk.Canvas(frame, width=30, height=30, highlightthickness=0)
            canvas.create_oval(2, 2, 18, 18, fill=color, outline="black")
            return canvas
        
        def create_indicator_square(frame, color):
            canvas = tk.Canvas(frame, width=30, height=30, highlightthickness=0)
            canvas.create_rectangle(2, 2, 18, 18, fill=color, outline="black")
            return canvas
        
        # self.interlocks_frame = tk.Frame(self.parent)
        # self.interlocks_frame.pack(fill=tk.BOTH, expand=True)
        # self.interlocks_frame.grid_rowconfigure(0, weight=1)
        # self.interlocks_frame.grid_columnconfigure(0, weight=1)
        # self.interlocks_frame.grid_columnconfigure(1, weight=1)

        self.interlocks_frame = tk.Frame(self.parent)
        self.interlocks_frame.pack(fill=tk.BOTH, expand=True)
        self.interlocks_frame.grid_rowconfigure(0, weight=1)
        self.interlocks_frame.grid_columnconfigure(0, weight=1)
        self.interlocks_frame.grid_columnconfigure(1, weight=1)

        interlocks_frame = tk.Frame(self.interlocks_frame, highlightthickness=0.75, highlightbackground="black")
        interlocks_frame.grid(row=0, column=0, padx=0, pady=0)

        interlocks_frame = tk.Frame(self.interlocks_frame, highlightthickness=0.75, highlightbackground="black")
        interlocks_frame.grid(row=0, column=0, padx=0, pady=0)

        indicators = {'DOOR': [], 
                      'WATER': [], 
                      'VACUUM': [], 
                      'OIL': [], 
                      'E-STOP': [], 
                      'ALL INTERLOCKS': []
                      }
        
        for i, k in enumerate(indicators.keys()):
            tk.Label(interlocks_frame, text=k, font=("Arial", 10, "bold")).grid(row=0, column=i)
            curr_frame = tk.Frame(interlocks_frame)
            curr_frame.grid(row=1, column=i, padx = 0, pady = 0)
            if k == "VACUUM":
                tk.Label(curr_frame, text="Power").grid(row=1, column=0, sticky='ew')
                tk.Label(curr_frame, text="Pressure").grid(row=1, column=1, sticky = 'ew')
                for col in range(2):
                    indicators[k].append(create_indicator_square(curr_frame, 'green'))
                    indicators[k][-1].grid(row=2, column=col, padx=10, pady=10)
            elif k == "OIL":
                tk.Label(curr_frame, text="Low").grid(row=1, column=0, sticky='ew')
                tk.Label(curr_frame, text="High").grid(row=1, column=1, sticky='ew')
                for col in range(2):
                    indicators[k].append(create_indicator_square(curr_frame, 'green'))
                    indicators[k][-1].grid(row=2, column=col, padx=10, pady=10)
            else:
                tk.Label(curr_frame, text=" ").grid(row=1, column=0, sticky='ew')
                indicators[k].append(create_indicator_circle(curr_frame, 'green'))
                indicators[k][-1].grid(row=2, column=0, columnspan=2, padx=0, pady=0, sticky = 'nsew')

        # HV Status Section
        hv_frame = tk.Frame(self.interlocks_frame, highlightthickness=2, highlightbackground="black")
        hv_frame.grid(row=0, column=1, padx=0, pady=0)

        # tk.Label(hv_frame, text="HV STATUS", font=("Arial", 10, "bold")).grid(row=0, column=0, columnspan=2)

        # HV Output On and HVOLT On indicators
        tk.Label(hv_frame, text="G9 OUTPUT ON").grid(row=1, column=0, padx=(0,12))
        tk.Label(hv_frame, text="HVOLT ON").grid(row=1, column=1, padx=(12,0))

        indicators["G9 OUTPUT ON"] = [create_indicator_circle(hv_frame, 'red')]
        indicators["G9 OUTPUT ON"][-1].grid(row=2, column=0, padx=0, pady=0, sticky = 'nsew')

        indicators["HVOLT ON"] = [create_indicator_circle(hv_frame, 'red')]
        indicators["HVOLT ON"][-1].grid(row=2, column=1, padx=0, pady=0, sticky = 'nsew')

        # for label in interlock_labels:
        #     frame = tk.Frame(self.interlocks_frame)
        #     frame.pack(side=tk.LEFT, expand=True, padx=5)

        #     lbl = tk.Label(frame, text=label, font=("Helvetica", 8))
        #     lbl.pack(side=tk.LEFT)
        #     status = self.interlock_status[label]
        #     #  for later to add frames being highlighted with red
        #     # # TODO: this currently does not work make because of frame keys not matching the interlock_status keys
        #     # # also flashing method only turns red, make flash
        #     # if status == 0:
        #     #     self.highlight_frame('Vacuum System', flashes=5, interval=500)
        #     # # else:
        #     # #     self.reset_frame_highlights()

        #     indicator = tk.Label(frame, image=self.indicators['active'] if status == 1 else self.indicators['inactive'])
        #     indicator.pack(side=tk.RIGHT, pady=1)
        #     frame.indicator = indicator  # Store reference to the indicator for future updates

    # logging the history of updates
    def update_interlock(self, name, status):
        if name in self.parent.children:
            frame = self.parent.children[name]
            indicator = frame.indicator
            new_image = self.indicators['active'] if status == 1 else self.indicators['inactive']
            indicator.config(image=new_image)
            indicator.image = new_image  # Keep a reference

            # logging the update
            old_status = self.interlock_status.get(name, None)
            if old_status is not None and old_status != status:
                log_message = f"Interlock status of {name} changed from {old_status} to {status}"
                self.logger.info(log_message)
                self.interlock_status[name] = status # log the previous state, and update it to the new state


    # the bit poistion for each interlock
    inputs = {
        0 : "Chassis Estop",
        1 : "Chassis Estop",
        2 : "Peripheral Estop",
        3 : "Peripheral Estop",
        4 : "Door",
        5 : "Door Lock",
        6 : "Vacuum Power",
        7 : "Vacuum Pressure",
        8 : "Oil High",
        9 : "Oil Low",
        10 : "Water",
        11 : "HVolt ON",
        12 : "G9SP Active"
    }

    def update_data(self):
        # this is a point of dicussion, should be always be checking or only when we have an error
        # one point of view is that we check very throughly in the driver file so if nothing is being thrown everything must be working
        # the other end would be it is the safety controller it should always be checked

        # i think it should be the second, not only becuase this hardware is for safety but the interlocks on the screen will need to be updated,
        # when an error is no longer being thrown

        # if no error is thrown we should not need to check anything technically
        try:
            self.driver.send_command()
        except:
            # if we are in here, we definity have to check
            pass

        # Updates all the the interlocks at each iteration
        # this could be more optimal if we only update the ones that change
        input_err = self.driver.input_flags
        for i in range(self.driver.NUMIN):
            self.update_interlock(map[0], input_err[-i + 1] =="1")

        # Schedule next update
        self.parent.after(500, self.update_data)


    def update_pressure_dependent_locks(self, pressure):
        # Disable the Vacuum lock if pressure is below 2 mbar
        self.update_interlock("Vacuum", pressure >= 2)


    # first trying to get the highlight method to work first
    # def reset_frame_highlights(self):
    #     for frame in self.frame.values:
    #         print(self.frame.values)
    #         frame.config(bg=self.parent.cget('bg'))


    # # this method right now only sets the frame boarder to be red TODO: make it flash
    # def highlight_frame(self, label, flashes=5, interval=500):
    #     if label in self.frames:
    #         frame = self.frames[label]
    #         reg = frame.cget('highlightbackground')
    #         new_color = 'red'

    #         frame.config(highlightbackground=new_color, highlightthickness=5, relief='solid')





