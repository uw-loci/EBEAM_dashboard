import tkinter as tk

class OilSubsystem:
    def __init__(self, parent, logger=None):
        """Initializes the OilSubsystem inside the given parent (Frame or Main Window)."""
        self.parent = parent
        self.logger = logger
        self.pressure = 0.0  
        self.temperature = 0.0  
        self.flow_rate = 0.0 
        self.pump_status = "OFF"  

        self.setup_gui()  
        self.update_display()  



    def setup_gui(self):
        """Creates and packs UI elements inside the given parent (horizontally)."""
        self.frame = tk.Frame(self.parent)
        self.frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        self.info_frame = tk.Frame(self.frame)
        self.info_frame.pack(fill=tk.X, expand=True)

        self.create_sensor_frame("Temperature", f"{self.temperature:.1f}°C", "temp_label")
        self.create_sensor_frame("Pressure", f"{self.pressure:.1f} PSI", "pressure_label")
        self.create_sensor_frame("Flow Rate", f"{self.flow_rate:.1f} GPM", "flow_label")
        self.create_sensor_frame("Pump Status", f"{self.pump_status}", "pumpStat")



    def create_sensor_frame(self, title, default_text, label_attr):
        """Creates a horizontally aligned sensor frame."""
        frame = tk.Frame(self.info_frame, padx=20)
        frame.pack(side=tk.LEFT, fill=tk.Y, expand=True)
        
        tk.Label(frame, text=title, font=("Helvetica", 10, "bold")).pack()
        label = tk.Label(frame, text=default_text, font=('Helvetica', 10), bg = "#d3d3d3", fg = "black", padx = 5, pady = 2)
        label.pack()
        
        setattr(self, label_attr, label)



    def update_display(self):
        """Updates the UI to reflect new sensor values."""
        self.temp_label.config(text=f"{self.temperature:.1f}°C")
        self.pressure_label.config(text=f"{self.pressure:.1f} PSI")
        self.flow_label.config(text=f"{self.flow_rate:.1f} GPM")
        self.pumpStat.config(text=f"{self.pump_status}")
        self.parent.after(200, self.update_display)  


