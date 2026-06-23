import time
import tkinter as tk
from typing import Dict, List
from instrumentctl.DP16_process_monitor.DP16_process_monitor import DP16ProcessMonitor
from utils import LogLevel

class TemperatureBar(tk.Canvas):

    DISCONNECTED = -1
    SENSOR_ERROR = -2
    TOP_PADDING = 1
    SCALE_LABELS = {
        'Solenoids': [10 , 120], 
        'Chambers' : [10, 100], 
        'Air': [10, 50],
        None: [10, 100]
    } 
    ERROR_COLORS = {
        DISCONNECTED: '#808080',  # Grey for disconnected state
        SENSOR_ERROR: '#FFA500',  # Keep orange for actual sensor errors
    }

    def __init__(self, parent, name: str, height: int = 36, width: int = 580):
        super().__init__(parent, height=height, width=width, highlightthickness=0)
        self.name = name
        self.height = height
        self.width = width
        self.bar_height = 11
        self.value = None

        self.bind('<Configure>', self._handle_resize)
        self._redraw_all()

    def _handle_resize(self, event):
        """Redraw the horizontal gauge when the canvas is resized."""
        if event.width == self.width and event.height == self.height:
            return
        self.width = event.width
        self.height = event.height
        self._redraw_all()

    def _redraw_all(self):
        self.delete('all')
        self.create_title()
        self.create_scale()
        self._draw_bar()

    def create_title(self):
        title_x = 6
        title_y = self.TOP_PADDING + (self.bar_height // 2)
        self.create_text(
            title_x,
            title_y,
            text=self.name, 
            font=('Segoe UI', 8, 'bold'), 
            anchor='w',
            tags='static'
        )
        
    def create_scale(self):
        # Scale line
        self.scale_left = 82
        self.scale_right = max(self.scale_left + 40, self.width - 44)
        self.bar_top = self.TOP_PADDING
        self.bar_bottom = self.bar_top + self.bar_height
        scale_width = self.scale_right - self.scale_left

        self.create_rectangle(
            self.scale_left,
            self.bar_top,
            self.scale_right,
            self.bar_bottom,
            outline='#5a5a5a',
            fill='#eeeeee',
            tags='static'
        )

        # Determine scale based on name
        if 'Solenoid' in self.name:
            scale_key = 'Solenoids'
        elif 'Chamber' in self.name:
            scale_key = 'Chambers'
        elif 'Air' in self.name:
            scale_key = 'Air'
        else:
            scale_key = None  # Default behavior if name does not match

        self.temp_min, self.temp_max = self.SCALE_LABELS.get(scale_key, self.SCALE_LABELS[None])
        temp_range = self.temp_max - self.temp_min

        # Scale marks and labels
        for i in range(self.temp_min, self.temp_max + 1, 10):    
            relative_pos = (i - self.temp_min) / temp_range
            x = self.scale_left + (relative_pos * scale_width)
            self.create_line(
                x,
                self.bar_bottom,
                x,
                self.bar_bottom + 3,
                fill='#333333',
                tags='scale_labels'
            )
            self.create_text(
                x,
                self.bar_bottom + 4,
                text=str(i), 
                anchor='n',
                font=('Segoe UI', 6),
                tags='scale_labels'
            )
        
    def update_value(self, name, value: float):
        """Update the temperature bar with a new value. If value == -1 then this indicates an error"""
        self.value = value
        self._draw_bar()

    def _draw_bar(self):
        self.delete('bar')
        self.delete('value')

        if self.value is None:
            return

        if self.value == self.DISCONNECTED:
            # grey out bar area with hatched pattern
            self.create_rectangle(
                self.scale_left,
                self.bar_top,
                self.scale_right,
                self.bar_bottom,
                fill='#E0E0E0',
                stipple='gray50', # hatched pattern
                tags='bar'
            )
            value_text = "---"
        elif self.value == self.SENSOR_ERROR:
            # Show orange bar for sensor error
            self.create_rectangle(
                self.scale_left,
                self.bar_top,
                self.scale_right,
                self.bar_bottom,
                fill=self.ERROR_COLORS[self.SENSOR_ERROR],
                tags='bar'
            )
            value_text = "ERR"
        else:
            # Normal temperature display
            relative_value = ((self.value - self.temp_min) / (self.temp_max - self.temp_min))
            bar_width = max(0, min(1, relative_value)) * (self.scale_right - self.scale_left)
            color = self.get_temperature_color(self.name, self.value)
            self.create_rectangle(
                self.scale_left,
                self.bar_top,
                self.scale_left + bar_width,
                self.bar_bottom,
                fill=color,
                tags='bar'
            )
            value_text = f'{self.value:.1f}'

        # ensure labels are on top
        self.tag_raise('scale_labels')

        # Update value label
        self.create_text(
            self.width - 6,
            self.TOP_PADDING + (self.bar_height // 2),
            text=value_text,
            font=('Segoe UI', 8, 'bold'),
            fill='#808080' if self.value == self.DISCONNECTED else 'black',
            anchor='e',
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
        self._monitor_missing_logged = False

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
        self.frame.grid_columnconfigure(0, weight=1)
        for i in range(len(self.thermometers)):
            self.frame.grid_rowconfigure(i, weight=1)
        
        # Create temperature bars
        self.temp_bars: Dict[str, TemperatureBar] = {}
        for i, name in enumerate(self.thermometers):
            bar = TemperatureBar(self.frame, name)
            bar.grid(row=i, column=0, padx=4, pady=(1, 0), sticky='nsew')
            self.temp_bars[name] = bar

    def update_temperatures(self):
        current_time = time.time()
        try:
            if not self.monitor:
                if not self._monitor_missing_logged:
                    self.log("DP16 monitor not connected", LogLevel.WARNING)
                    self._monitor_missing_logged = True
                if current_time - self.last_error_time > (self.update_interval / 1000):
                    self._set_all_temps_disconnected()
                    if self.logger and hasattr(self.logger, "clear_value"):
                        self.logger.clear_value("temperatures")
                    self.last_error_time = current_time
            else:
                if self._monitor_missing_logged:
                    self.log("DP16 monitor connection available", LogLevel.INFO)
                    self._monitor_missing_logged = False
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
                        
                self.log(f"PMON temps: {formatted_temps}", LogLevel.VERBOSE)
                if self.logger and hasattr(self.logger, "update_field"):
                    self.logger.update_field("temperatures", formatted_temps)

                if not temps:
                    if current_time - self.last_error_time > (self.update_interval / 1000):
                        self._set_all_temps_disconnected()
                        if self.logger and hasattr(self.logger, "clear_value"):
                            self.logger.clear_value("temperatures")
                        self.active['Environment Pass'] = False
                        self.log("No temperature data available from DP16", LogLevel.ERROR)
                        self.last_error_time = current_time
                else:
                    # Update each temperature bar
                    for name, unit in self.thermometer_map.items():
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
            # Schedule next update, store after_id for cancellation if needed.
            if self.monitor:
                self.after_id = self.parent.after(self.update_interval, self.update_temperatures)

    def cancel_updates(self):
        '''Cancel after() scheduled updates, to be called by dashboard when app is quit.'''
        if hasattr(self, 'after_id') and self.after_id:
            try:
                self.parent.after_cancel(self.after_id)
                self.after_id = None
                if self.logger:
                    self.log('Canceled scheduled temperature update.', LogLevel.DEBUG)
            except Exception as e:
                if self.logger:
                    self.log('Failed to cancel scheduled temperature update.', LogLevel.DEBUG)

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
            self.logger.log(message, level, tag="PMON")

    def close_com_ports(self):
        """
        Closes the serial port connection upon quitting the application.
        """
        if self.monitor and hasattr(self.monitor, 'disconnect'):
            self.monitor.disconnect()
            self.log(f"Closed serial port {self.com_port}", LogLevel.INFO)
        else:
            self.log("Connection to PMON already closed", LogLevel.INFO)
