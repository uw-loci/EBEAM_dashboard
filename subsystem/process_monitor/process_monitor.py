import time
import tkinter as tk
from typing import Dict, List
from instrumentctl.DP16_process_monitor.DP16_process_monitor import DP16ProcessMonitor
from utils import LogLevel

class TemperatureBar(tk.Canvas):

    DISCONNECTED = -1
    SENSOR_ERROR = -2
    SCALE_LABELS = {
        'Solenoids': [20 , 120, 24], 
        'Chambers' : [20, 100, 20], 
        'Air': [20, 50, 10],
        None: [20, 100, 10]
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
            value_text = f'{value:.1f}°'

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
        
        if temp < 20:
            return '#0000FF'  # Blue for cold
        
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
    def __init__(self, parent, com_port, logger=None):
        self.parent = parent
        self.logger = logger
        self.last_error_time = 0
        self.error_count = 0
        self.update_interval = 500  # default update interval (ms)
        self.max_interval = 5000    # Maximum update interval (ms)

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
        try:
            if com_port:
                self.monitor = DP16ProcessMonitor(
                    port=com_port,
                    unit_numbers=list(self.thermometer_map.values()),
                    logger=logger
                )
                if not self.monitor.connect():
                    self.log("Failed to connect to DP16 Process Monitor", LogLevel.WARNING)
            else:
                self.monitor = None
                self.log("No COM port provided for ProcessMonitorSubsystem", LogLevel.WARNING)
                self._set_all_temps_error()
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
        """Update temperature readings with error handling and backoff"""
        current_time = time.time()
        try:
            if not self.monitor or not self.monitor.client.is_socket_open():
                if current_time - self.last_error_time > (self.update_interval / 1000):
                    self._set_all_temps_disconnected()
                    self.log("DP16 monitor not connected", LogLevel.WARNING)
                    self.last_error_time = current_time
                    self._adjust_update_interval(success=False)
            else:

                # Retrieve the last responses from all units
                temps = self.monitor.get_all_temperatures()

                if all(temp is None or temp == -1 for temp in temps.values()):
                    if current_time - self.last_error_time > (self.update_interval / 1000):
                        self._set_all_temps_error()
                        self.log("No temperature data available from DP16", LogLevel.ERROR)
                        self.last_error_time = current_time
                        self._adjust_update_interval(success=False)
                else:
                    # Update each temperature bar
                    for name, unit in self.thermometer_map.items():
                        temp = temps.get(unit)
                        if temp is not None and temp != -1:
                            self.temp_bars[name].update_value(name, temp)
                            self.log(f"Temperature update - {name}: {temp:.1f}C", LogLevel.DEBUG)
                        else:
                            self.temp_bars[name].update_value(name, -1)
                            self.log(f"Temperature error - {name}", LogLevel.WARNING)

                    self._adjust_update_interval(success=True)

        except Exception as e:
            if current_time - self.last_error_time > (self.update_interval / 1000):
                self.log(f"Unexpected error updating temperatures: {str(e)}", LogLevel.ERROR)
                self._set_all_temps_error()
                self.last_error_time = current_time
                self._adjust_update_interval(success=False)
                
        finally:
            # Schedule next update
            if self.monitor:
                self.parent.after(self.update_interval, self.update_temperatures)

    def _adjust_update_interval(self, success=True):
        """Adjust the polling interval based on connection success/failure"""
        if success:
            self.error_count = 0
            self.update_interval = 500  # Reset to default interval
        else:
            self.error_count = min(self.error_count + 1, 5)  # Cap error count
            self.update_interval = min(500 * (2 ** self.error_count), self.max_interval)

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