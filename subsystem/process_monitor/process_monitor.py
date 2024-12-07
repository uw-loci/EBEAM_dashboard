import tkinter as tk
import random
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
from typing import Dict, List
from instrumentctl.DP16_process_monitor.DP16_process_monitor import DP16ProcessMonitor

class TemperatureBar(tk.Canvas):
    def __init__(self, parent, name: str, height: int = 400, width: int = 40):
        super().__init__(parent, height=height, width=width)
        self.name = name
        self.height = height
        self.width = width
        self.bar_width = 15
        self.value = 0
        
        # Create title
        self.create_text(
            width//2, 
            75, 
            text=name, 
            font=('Arial', 8, 'bold'), 
            anchor='n',
            angle=90  # Rotate text 90 degrees
        )
        
        # Create scale marks
        self.create_scale()
        
    def create_scale(self):
        # Scale line
        scale_x = self.width - 20
        top_y = 35
        bottom_y = self.height - 20
        scale_height = bottom_y - top_y
        
        self.create_line(scale_x, top_y, scale_x, bottom_y)
        
        # Scale marks and labels
        for i in range(0, 101, 20):
            y = bottom_y - (i/100) * scale_height
            self.create_line(scale_x-2, y, scale_x+2, y)
            self.create_text(
                scale_x-6, 
                y, 
                text=str(i), 
                anchor='w', 
                font=('Arial', 7),
                angle=90,
                tags='scale_labels'
            )
            
        self.scale_top = top_y
        self.scale_bottom = bottom_y
        
    def update_value(self, value: float):
        """Update the temperature bar with a new value."""
        self.delete('bar')
        
        # Calculate bar height
        bar_height = ((value/100) * (self.scale_bottom - self.scale_top))
        
        # Calculate color based on temperature
        color = self.get_temperature_color(value)
        
        # Draw bar
        self.create_rectangle(
            5,
            self.scale_bottom - bar_height,
            5 + self.bar_width,
            self.scale_bottom,
            fill=color,
            tags='bar',
            state='normal'
        )
        
        # ensure labels are on top
        self.tag_raise('scale_labels')

        # Update value label
        self.delete('value')
        self.create_text(
            self.width//2,
            self.height-5,
            text=f'{value:.1f}°',
            font=('Arial', 9, 'bold'),
            tags='value'
        )
        
    def get_temperature_color(self, temp: float) -> str:
        """Return a color based on temperature value."""
        if temp < 30:
            return '#0000FF'  # Blue for cold
        elif temp < 50:
            return '#00FF00'  # Green for normal
        elif temp < 70:
            return '#FFA500'  # Orange for warm
        else:
            return '#FF0000'  # Red for hot


class ProcessMonitorSubsystem:
    def __init__(self, parent, com_port, logger=None):
        self.parent = parent
        self.logger = logger
        self.thermometers = ['Solenoid 1', 'Solenoid 2', 'Chamber Top', 'Chamber Bot', 'Air temp']
        self.temperatures = {
            name: (random.uniform(60, 90) if 'Solenoid' in name else random.uniform(50, 70)) 
            for name in self.thermometers
        }

        self.thermometer_map = {
            'Solenoid 1': 1,
            'Solenoid 2': 2,
            'Chamber Top': 3,
            'Chamber Bot': 4,
            'Air temp': 5
        }
        
        # Initialize the DP16 monitor
        self.monitor = DP16ProcessMonitor(
            port=com_port,
            unit_numbers=list(self.thermometer_map.values()),
            logger=logger
        )
        if not self.monitor.connect():
            if self.logger:
                self.logger.warning("Failed to connect to DP16 Process Monitor")

        self.setup_gui()
        self.update_temperatures()

    def setup_gui(self):
        self.frame = tk.Frame(self.parent)
        self.frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        
        # Configure grid weights for responsive layout
        for i in range(len(self.thermometers)):
            self.frame.grid_columnconfigure(i, weight=1)
        
        # Create temperature bars
        self.temp_bars: Dict[str, TemperatureBar] = {}
        for i, name in enumerate(self.thermometers):
            bar = TemperatureBar(self.frame, name)
            bar.grid(row=0, column=i, padx=5, sticky='nsew')
            self.temp_bars[name] = bar

    def update_temperatures(self):
        try:
            # Read all temperatures
            temps = self.monitor.read_temperatures()
            
            # Update each temperature bar
            for name, unit in self.thermometer_map.items():
                temp = temps.get(unit)
                if temp is not None:
                    self.temp_bars[name].update_value(temp)
                    
        except Exception as e:
            if self.logger:
                self.logger.error(f"Error updating temperatures: {str(e)}")
                
        # Schedule next update
        self.parent.after(500, self.update_temperatures)
