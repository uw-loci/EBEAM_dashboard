import tkinter as tk
from tkinter import ttk, messagebox
import datetime
import random
import threading
import time

class OilSubsystem:
    def __init__(self, parent, logger=None):
        """Initializes the OilSubsystem inside the given parent (Frame or Main Window)."""
        self.parent = parent
        self.logger = logger
        self.pressure = 3.5  
        self.temperature = 50.0  
        self.flow_rate = 10.0  
        self.pump_status = False  
        self.stop_event = threading.Event()  

        self.setup_gui()  
        self.start_sensor_thread()  
        self.update_display()  



    def setup_gui(self):
        """Creates and packs UI elements inside the given parent (horizontally)."""
        self.frame = tk.Frame(self.parent)
        self.frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Frame for all sensor displays (Horizontal Layout)
        self.info_frame = tk.Frame(self.frame)
        self.info_frame.pack(fill=tk.X, expand=True)

        # self.info_frame = tk.Frame(self.frame, bg="yellow", bd=3)  
        # self.info_frame.pack(fill=tk.X, expand=True, padx=5, pady=5)

        # Create labels inside individual frames for proper alignment
        self.create_sensor_frame("Temperature", f"{self.temperature:.1f}°C", "temp_label")
        self.create_sensor_frame("Pressure", f"{self.pressure:.1f} PSI", "pressure_label")
        self.create_sensor_frame("Flow Rate", f"{self.flow_rate:.1f} L/min", "flow_label")
        self.create_sensor_frame("Pump Status", self.get_pump_status(), "pump_label")



    def create_sensor_frame(self, title, default_text, label_attr):
        """Creates a horizontally aligned sensor frame."""
        frame = tk.Frame(self.info_frame, padx=20)
        frame.pack(side=tk.LEFT, fill=tk.Y, expand=True)
        
        tk.Label(frame, text=title, font=("Helvetica", 10, "bold")).pack()
        label = tk.Label(frame, text=default_text, font=('Helvetica', 10), bg = "#d3d3d3", fg = "black", padx = 5, pady = 2)
        label.pack()
        
        # Dynamically assign label reference to update later
        setattr(self, label_attr, label)



    def generate_sensor_data(self):
        """Continuously generates new sensor data in a separate thread."""
        while not self.stop_event.is_set():
            self.pressure += random.uniform(-0.5, 0.5)  
            self.pressure = max(0, min(30, self.pressure))  
            
            self.temperature += random.uniform(-1.0, 1.0) 
            self.temperature = max(50, min(90, self.temperature))  

            self.flow_rate += random.uniform(-0.2, 0.2)  
            self.flow_rate = max(0, min(50, self.flow_rate))  
            
            self.pump_status = random.choice([True, False]) 

            time.sleep(0.1)  



    def update_display(self):
        """Updates the UI to reflect new sensor values."""
        self.temp_label.config(text=f"{self.temperature:.1f}°C")
        self.pressure_label.config(text=f"{self.pressure:.1f} PSI")
        self.flow_label.config(text=f"{self.flow_rate:.1f} GPM")
        self.pump_label.config(text=self.get_pump_status())
        self.parent.after(200, self.update_display)  



    def get_pump_status(self):
        """Returns 'ON' if pump_status is True, otherwise 'OFF'."""
        while not self.stop_event.is_set():
            return "OFF"
    


    def start_sensor_thread(self):
        """Starts a separate thread for continuous sensor data generation."""
        self.sensor_thread = threading.Thread(target=self.generate_sensor_data, daemon=True)
        self.sensor_thread.start()



    def stop_sensor_thread(self):
        """Stops the sensor thread safely."""
        self.stop_event.set()
        if hasattr(self, 'sensor_thread') and self.sensor_thread.is_alive():
            self.sensor_thread.join()



    # def save_plot(self):
    #     """Stub function for saving a plot (expandable)."""
    #     try:
    #         timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    #         filename = f"temperature_vs_pressure_{timestamp}.png"
    #         messagebox.showinfo("Success", f"Plot saved to {filename}")
    #     except Exception as e:
    #         messagebox.showerror("Error", f"Failed to save plot: {e}")



    def __del__(self):
        """Ensure the sensor thread stops when the object is deleted."""
        self.stop_sensor_thread()




