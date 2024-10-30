# interlocks.py
import tkinter as tk
import os, sys
import instrumentctl.g9_driver as g9_driv
from utils import LogLevel
import time

# the bit poistion for each interlock
INPUTS = {
    0 : "E-STOP Int", # Chassis Estop
    1 : "E-STOP Int", # Chassis Estop
    2 : "E-STOP Ext", # Peripheral Estop
    3 : "E-STOP Ext", # Peripheral Estop
    4 : "Door", # Door 
    5 : "Door", # Door Lock
    6 : "Vacuum Power", # Vacuum Power
    7 : "Vacuum Pressure", # Vacuum Pressure
    8 : "High Oil", # Oil High
    9 : "Low Oil", # Oil Low
    10 : "Water", # Water
    11 : "HVolt ON", # HVolt ON
    12 : "G9SP Active" # G9SP Active
    }

def handle_errors(self, data):
    try:
        response = g9_driv.read_response()
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
        self.indicators = None
        self.cycle_counter = 0  # Counter for adding delay in mock data flipping
        self.setup_gui()

    def update_com_port(self, com_port):
        if com_port:
            self.driver = g9_driv.G9Driver(com_port)

    def setup_gui(self):
        def create_indicator_circle(frame, color):
            canvas = tk.Canvas(frame, width=30, height=30, highlightthickness=0)
            canvas.grid(sticky='nsew')
            oval_id = canvas.create_oval(5, 5, 25, 25, fill=color, outline="black")
            return canvas, oval_id

        self.interlocks_frame = tk.Frame(self.parent)
        self.interlocks_frame.pack(fill=tk.BOTH, expand=True)

        self.parent.grid_rowconfigure(0, weight=1)
        self.parent.grid_columnconfigure(0, weight=1)

        self.interlocks_frame.grid_rowconfigure(0, weight=1)
        self.interlocks_frame.grid_columnconfigure(0, weight=1)
        self.interlocks_frame.grid(row=0, column=0, sticky='nsew')

        interlocks_frame = tk.Frame(self.interlocks_frame, highlightbackground="black")
        interlocks_frame.grid(row=0, column=0, padx=0, pady=0, sticky="nsew")

        num_columns = 22  
        for i in range(num_columns):
            interlocks_frame.grid_columnconfigure(i, weight=1)

        self.indicators = {
            'Door': None, 'Water': None, 'Vac Power': None, 
            'Vac Pressure': None, 'Low Oil': None, 'High Oil': None, 
            'E-STOP Int': None, 'E-STOP Ext' : None, 'All Interlocks': None, 
            'G9 Output': None, 'HVOLT ON': None
                      }
        
        # Makes all the inticators and labels
        for i, (k,v) in enumerate(self.indicators.items()):
            tk.Label(interlocks_frame, text=f"{k}", anchor="center").grid(row=0, column=i*2, sticky='ew')
            canvas, oval_id = create_indicator_circle(interlocks_frame, 'red')
            canvas.grid(row=0, column=i*2+1, sticky='nsew')
            self.indicators[k] = (canvas, oval_id)

    # logging the history of updates
    def update_interlock(self, name, safety, data):
        # means good
        if safety & data == 1:
            color = 'green'
        # Not good 
        else:
            color = 'red'

        if name in self.indicators:
            canvas, oval_id = self.indicators[name]
            canvas.itemconfig(oval_id, fill=color)

        # if name in self.parent.children:
        #     frame = self.parent.children[name]
        #     indicator = frame.indicator
        #     new_image = self.indicators['active'] if status == 1 else self.indicators['inactive']
        #     indicator.config(image=new_image)
        #     indicator.image = new_image  # Keep a reference

        #     # logging the update
        #     old_status = self.interlock_status.get(name, None)
        #     if old_status is not None and old_status != status:
        #         log_message = f"Interlock status of {name} changed from {old_status} to {status}"
        #         self.logger.info(log_message)
        #         self.interlock_status[name] = status # log the previous state, and update it to the new state


    def update_data(self):
        # Mock data for testing
        def mock_data():
            # Flip the bits for testing
            # This will alternate the state of each bit between 0 and 1 each cycle
            if self.cycle_counter % 10 == 0:
                for i in range(len(self.driver.SITDF)):
                    self.driver.SITDF[i] ^= 1  # XOR with 1 to flip between 0 and 1
                    self.driver.SITSF[i] ^= 1


        # Use mock data
        mock_data()  # Simulate changing data values
        self.cycle_counter += 1


        try:
            self.driver.send_command()
        except:
            # TODO: what to do here
            # if we are in here, we definity have to check
            pass

        # Updates all the the interlocks at each iteration
        # this could be more optimal if we only update the ones that change
        sitsf = self.driver.SITSF[-self.driver.NUMIN:]
        sitdf = self.driver.SITDF[-self.driver.NUMIN:]

        # this loop is for the 3 interlocks that have 2 inputs
        for i in range(3):
            self.update_interlock(self.indicators[INPUTS[i*2]], sitsf[-i*2] & sitsf[-i*2 + 1], sitdf[-i*2] & sitdf[-i*2 + 1])
        # this is for the rest of the interlocks with only one input
        for i in range(6, 13):
            self.update_interlock(self.indicators[INPUTS[i*2]], sitsf[-i], sitdf[-i])

        # Schedule next update
        self.parent.after(500, self.update_data)







