import time
import tkinter as tk
from typing import Dict, List
from instrumentctl.DP16_process_monitor.DP16_process_monitor import DP16ProcessMonitor
from utils import LogLevel

class TemperatureBar(tk.Canvas):

    DISCONNECTED = -1
    SENSOR_ERROR = -2
    SCALE_LABELS = {
        'Solenoids': [15 , 120, 24], 
        'Chambers' : [15, 100, 20], 
        'Air': [15, 50, 10],
        None: [15, 100, 10]
    } 
    ERROR_COLORS = {
        DISCONNECTED: '#808080',  # Grey for disconnected state
        SENSOR_ERROR: '#FFA500',  # Keep orange for actual sensor errors
    }

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

        # Determine scale based on name
        if 'Solenoid' in self.name:
            scale_key = 'Solenoids'
        elif 'Chamber' in self.name:
            scale_key = 'Chambers'
        elif 'Air' in self.name:
            scale_key = 'Air'
        else:
            scale_key = None  # Default behavior if name does not match

        self.temp_min, self.temp_max, self.ticks = self.SCALE_LABELS.get(scale_key, self.SCALE_LABELS[None])
        temp_range = self.temp_max - self.temp_min

        # Scale marks and labels
        for i in range(self.temp_min, self.temp_max + 1, 10):    
            relative_pos = (i - self.temp_min) / temp_range
            y = bottom_y - (relative_pos * scale_height)
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
        
    def update_value(self, name, value: float):
        """Update the temperature bar with a new value. If value == -1 then this indicates an error"""
        self.delete('bar')

        if value == self.DISCONNECTED:
            # grey out bar area with hatched pattern
            self.create_rectangle(
                5,
                self.scale_top,
                5 + self.bar_width,
                self.scale_bottom,
                fill='#E0E0E0',
                stipple='gray50', # hatched pattern
                tags='bar'
            )
            value_text = "---"
        elif value == self.SENSOR_ERROR:
            # Show orange bar for sensor error
            self.create_rectangle(
                5,
                self.scale_bottom,
                5 + self.bar_width,
                self.scale_bottom,
                fill=self.ERROR_COLORS[self.SENSOR_ERROR],
                tags='bar'
            )
            value_text = "ERR"
        else:
            # Normal temperature display
            bar_height = (((value - self.temp_min) / (self.temp_max - self.temp_min)) * (self.scale_bottom - self.scale_top))
            color = self.get_temperature_color(name, value)
            self.create_rectangle(
                5,
                self.scale_bottom - bar_height,
                5 + self.bar_width,
                self.scale_bottom,
                fill=color,
                tags='bar'
            )
            value_text = f'{value:.1f}'

        # ensure labels are on top
        self.tag_raise('scale_labels')

        # Update value label
        self.delete('value')
        self.create_text(
            self.width//2,
            self.height-5,
            text=value_text,
            font=('Arial', 9, 'bold'),
            fill='#808080' if value == self.DISCONNECTED else 'black',
            tags='value'
        )
        
    def get_temperature_color(self, name, temp: float) -> str:
        """Return a color based on temperature value."""
        
        if name.startswith('Solenoid'): 
            if 20 <= temp < 70:
                return '#00FF00'  # Green for normal 
            elif 70 <= temp < 100:
                return '#FFFF00'  # Yellow for warm 
            else:
                return '#FF0000'  # Red for hot
            
        elif name.startswith('Chamber'): 
            if 20 <= temp < 50:
                return '#00FF00'  # Green for normal 
            elif 50 <= temp < 70:
                return '#FFFF00'  # Yellow for warm 
            else:
                return '#FF0000'  # Red for hot 
        elif name.startswith('Air'):
            if 20 <= temp < 30:
                return '#00FF00'  # Green for normal 
            elif 30 <= temp < 40:
                return '#FFFF00'  # Yellow for warm 
            else:
                return '#FF0000'  # Red for hot
        else:
            if temp < 70:
                return '#00FF00'  # Green for normal
            elif temp < 100:
                return '#FFFF00'  # Yellow for warm
            else:
                return '#FF0000'  # Red for hot 


class ProcessMonitorSubsystem:
    def __init__(self, parent, com_port, active, logger=None):
        self.parent = parent
        self.logger = logger
        self.active = active
        self.last_error_time = 0
        self.error_count = 0
        self.com_port = com_port
        self.update_interval = 500  # default update interval (ms)

        self.thermometers = ['Solenoid 1', 'Solenoid 2', 'Chamber Top', 'Chamber Bot', 'Air temp', 'Unassigned']
        self.thermometer_map = {
            'Solenoid 1': 1,
            'Solenoid 2': 2,
            'Chamber Top': 3,
            'Chamber Bot': 4,
            'Air temp': 5,
            'Unassigned': 6
        }

        self.setup_gui()
        self.monitor = None
        try:
            if not com_port:
                raise ValueError("No COM port provided for ProcessMonitor")
            # Instantiate PMON driver
            self.monitor = DP16ProcessMonitor(
                port=com_port,
                unit_numbers=list(self.thermometer_map.values()),
                logger=logger
            )
        except Exception as e:
            self.monitor = None
            self.log(f"Failed to initialize DP16ProcessMonitor: {str(e)}", LogLevel.ERROR)
            self._set_all_temps_error()
        
        # start the callback method
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
        current_time = time.time()
        try:
            if not self.monitor:
                self.log("Checking DP16 monitor connection status", LogLevel.DEBUG)
                if current_time - self.last_error_time > (self.update_interval / 1000):
                    self._set_all_temps_disconnected()
                    self.log("DP16 monitor not connected", LogLevel.WARNING)
                    self.last_error_time = current_time
            else:
                temps = self.monitor.get_all_temperatures()
                
                # Format both valid readings and error states
                formatted_temps = {}
                for unit, value in temps.items():
                    if isinstance(value, float):
                        formatted_temps[unit] = f"{value:.2f}"
                    elif value == self.monitor.DISCONNECTED:
                        formatted_temps[unit] = "DISCONNECTED"
                    elif value == self.monitor.SENSOR_ERROR:
                        formatted_temps[unit] = "SENSOR_ERROR"
                    else:
                        formatted_temps[unit] = str(value)
                        
                self.log(f"PMON temps: {formatted_temps}", LogLevel.DEBUG)

                if not temps:
                    if current_time - self.last_error_time > (self.update_interval / 1000):
                        self._set_all_temps_disconnected()
                        self.active['Environment Pass'] = False
                        self.log("No temperature data available from DP16", LogLevel.ERROR)
                        self.last_error_time = current_time
                else:
                    # Update each temperature bar
                    for name, unit in self.thermometer_map.items():
                        temp = temps.get(unit)
                        self.log(f"Processing temperature for {name} (unit {unit}): {temp}", LogLevel.VERBOSE)
                        temp = temps.get(unit)
                        if temp is None:
                            self.temp_bars[name].update_value(name, TemperatureBar.DISCONNECTED)
                            self.active['Environment Pass'] = False
                        elif temp == self.monitor.SENSOR_ERROR:
                            self.temp_bars[name].update_value(name, TemperatureBar.SENSOR_ERROR)
                            self.active['Environment Pass'] = False
                        elif temp == self.monitor.DISCONNECTED:
                            self.temp_bars[name].update_value(name, TemperatureBar.DISCONNECTED)
                            self.active['Environment Pass'] = False
                        elif isinstance(temp, (int, float)):
                            try:
                                temp_value = float(temp)
                                if -90 <= temp_value <= 500:  # Valid temperature range
                                    self.temp_bars[name].update_value(name, temp_value)
                                    self.active['Environment Pass'] = True # Update Machine Status Progress Bar
                                    self.log(f"Temperature update - {name}: {temp_value:.1f}C", LogLevel.VERBOSE)
                                else:
                                    self.temp_bars[name].update_value(name, TemperatureBar.SENSOR_ERROR)
                                    self.log(f"Temperature out of range - {name}: {temp_value}", LogLevel.WARNING)
                                    self.active['Environment Pass'] = False
                            except (ValueError, TypeError):
                                self.temp_bars[name].update_value(name, TemperatureBar.SENSOR_ERROR)
                                self.log(f"Invalid temperature value - {name}: {temp}", LogLevel.WARNING)
                                self.active['Environment Pass'] = False
                        else:
                            self.temp_bars[name].update_value(name, TemperatureBar.SENSOR_ERROR)
                            self.log(f"Invalid temperature type - {name}: {type(temp)}", LogLevel.WARNING)
                            self.active['Environment Pass'] = False

        except Exception as e:
            self.log(f"DP16 exception details: {type(e).__name__}: {str(e)}", LogLevel.DEBUG)
            if current_time - self.last_error_time > (self.update_interval / 1000):
                self.log(f"Unexpected error updating temperatures: {str(e)}", LogLevel.ERROR)
                self.last_error_time = current_time
                
        finally:
            # Schedule next update
            if self.monitor:
                self.parent.after(self.update_interval, self.update_temperatures)

    def _set_all_temps_error(self):
        """Set all temperature bars to error state"""
        if hasattr(self, 'temp_bars'):
            for name in self.temp_bars:
                self.temp_bars[name].update_value(name, -1)

    def _set_all_temps_disconnected(self):
        """Set all temperature bars to disconnected state"""
        if hasattr(self, 'temp_bars'):
            for name in self.temp_bars:
                self.temp_bars[name].update_value(name, TemperatureBar.DISCONNECTED)

    def log(self, message, level=LogLevel.INFO):
        """Log a message with the specified level if a logger is configured."""
        if self.logger:
            self.logger.log(message, level)
        else:
            print(f"{level.name}: {message}")

    def close_com_ports(self):
        """
        Closes the serial port connection upon quitting the application.
        """
        if self.monitor and hasattr(self.monitor, 'disconnect'):
            self.monitor.disconnect()
            self.log(f"Closed serial port {self.com_port}", LogLevel.INFO)
        else:
            self.log("Connection to PMON already closed", LogLevel.INFO)