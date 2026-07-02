import math
import time
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Dict
from instrumentctl.DP16_process_monitor.DP16_process_monitor import DP16ProcessMonitor
from usr.process_monitor_config import (
    RANGE_FIELDS,
    load_process_monitor_config,
    save_process_monitor_config,
)
from utils import LogLevel

class TemperatureBar(tk.Canvas):

    DISCONNECTED = -1
    SENSOR_ERROR = -2
    DISABLED = -3
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

    def __init__(self, parent, name: str, height: int = 36, width: int = 580,
                 display_min=10.0, display_max=100.0,
                 warning_min=-90.0, warning_max=500.0):
        super().__init__(parent, height=height, width=width, highlightthickness=0)
        self.name = name
        self.height = height
        self.width = width
        self.bar_height = 11
        self.value = None
        self.temp_min = display_min
        self.temp_max = display_max
        self.warning_min = warning_min
        self.warning_max = warning_max

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

        temp_range = self.temp_max - self.temp_min

        # Scale marks and labels
        divisions = 5
        for step in range(divisions + 1):
            value = self.temp_min + (temp_range * step / divisions)
            relative_pos = step / divisions
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
                text=f"{value:g}",
                anchor='n',
                font=('Segoe UI', 6),
                tags='scale_labels'
            )
        
    def update_value(self, name, value: float):
        """Update the temperature bar with a new value. If value == -1 then this indicates an error"""
        self.value = value
        self._draw_bar()

    def set_ranges(self, display_min, display_max, warning_min, warning_max):
        self.temp_min = display_min
        self.temp_max = display_max
        self.warning_min = warning_min
        self.warning_max = warning_max
        self._redraw_all()

    def _draw_bar(self):
        self.delete('bar')
        self.delete('value')

        if self.value is None:
            return

        if self.value in (self.DISCONNECTED, self.DISABLED):
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
            value_text = "OFF" if self.value == self.DISABLED else "---"
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
        if temp < self.warning_min or temp > self.warning_max:
            return '#FFA500'

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
    MIN_VALID_TEMP = -90
    MAX_VALID_TEMP = 500
    WARNING_LOG_INTERVAL_SECONDS = 60.0

    def __init__(self, parent, com_port, active, logger=None):
        self.parent = parent
        self.logger = logger
        self.active = active
        self.last_error_time = 0
        self.error_count = 0
        self.com_port = com_port
        self.update_interval = 500  # default update interval (ms)
        self._monitor_missing_logged = False
        self._last_warning_log_times = {}
        self._latest_temperatures = {}

        self.thermometers = ['Solenoid 1', 'Solenoid 2', 'Chamber Top', 'Chamber Bot', 'Air temp', 'Unassigned']
        self.thermometer_map = {
            'Solenoid 1': 1,
            'Solenoid 2': 2,
            'Chamber Top': 3,
            'Chamber Bot': 4,
            'Air temp': 5,
            'Unassigned': 6
        }
        self.config = load_process_monitor_config(logger=self.logger)
        self.disabled_sensors = set(self.config["disabled_sensors"])

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
        notebook = ttk.Notebook(self.parent)
        notebook.pack(fill=tk.BOTH, expand=True)
        main_tab = ttk.Frame(notebook)
        config_tab = ttk.Frame(notebook)
        notebook.add(main_tab, text="Main")
        notebook.add(config_tab, text="Config")

        self.frame = tk.Frame(main_tab)
        self.frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        
        # Configure grid weights for responsive layout
        self.frame.grid_columnconfigure(0, weight=1)
        for i in range(len(self.thermometers)):
            self.frame.grid_rowconfigure(i, weight=1)
        
        # Create temperature bars
        self.temp_bars: Dict[str, TemperatureBar] = {}
        for i, name in enumerate(self.thermometers):
            limits = self.config["sensors"][name]
            bar = TemperatureBar(
                self.frame,
                name,
                display_min=limits["display_min_c"],
                display_max=limits["display_max_c"],
                warning_min=limits["warning_min_c"],
                warning_max=limits["warning_max_c"],
            )
            bar.grid(row=i, column=0, padx=4, pady=(1, 0), sticky='nsew')
            self.temp_bars[name] = bar
            if name in self.disabled_sensors:
                bar.update_value(name, TemperatureBar.DISABLED)

        self._create_config_tab(config_tab)

    def _create_config_tab(self, parent):
        container = ttk.Frame(parent, padding=4)
        container.pack(fill=tk.BOTH, expand=True)
        headers = ("Sensor", "Enabled", "Warn min °C", "Warn max °C", "Bar min °C", "Bar max °C", "")
        for column, text in enumerate(headers):
            ttk.Label(container, text=text, font=("Segoe UI", 8, "bold")).grid(
                row=0, column=column, padx=3, pady=(0, 4), sticky="w"
            )

        self.enabled_vars = {}
        self.config_entry_vars = {}
        for row, name in enumerate(self.thermometers, start=1):
            ttk.Label(container, text=name).grid(row=row, column=0, padx=3, pady=3, sticky="w")
            enabled_var = tk.BooleanVar(value=name not in self.disabled_sensors)
            self.enabled_vars[name] = enabled_var
            ttk.Checkbutton(
                container,
                variable=enabled_var,
                command=lambda sensor=name: self._set_sensor_enabled(sensor),
            ).grid(row=row, column=1)

            self.config_entry_vars[name] = {}
            limits = self.config["sensors"][name]
            for column, field in enumerate(RANGE_FIELDS, start=2):
                var = tk.StringVar(value=f"{limits[field]:g}")
                self.config_entry_vars[name][field] = var
                ttk.Entry(container, textvariable=var, width=9).grid(
                    row=row, column=column, padx=3, pady=3, sticky="ew"
                )
            ttk.Button(
                container,
                text="Set",
                width=5,
                command=lambda sensor=name: self._save_sensor_config(sensor),
            ).grid(row=row, column=6, padx=3, pady=3)

        container.grid_columnconfigure(0, weight=1)

    def _save_sensor_config(self, name, show_dialogs=True):
        candidate = {}
        try:
            for field in RANGE_FIELDS:
                candidate[field] = float(self.config_entry_vars[name][field].get().strip())
        except (TypeError, ValueError):
            return self._config_error(name, "All temperature limits must be valid numbers.", show_dialogs)

        if not all(math.isfinite(value) for value in candidate.values()):
            return self._config_error(name, "All temperature limits must be finite numbers.", show_dialogs)
        if candidate["warning_min_c"] >= candidate["warning_max_c"]:
            return self._config_error(name, "Warning minimum must be less than warning maximum.", show_dialogs)
        if candidate["display_min_c"] >= candidate["display_max_c"]:
            return self._config_error(name, "Bar minimum must be less than bar maximum.", show_dialogs)

        self.config["sensors"][name] = candidate
        self.temp_bars[name].set_ranges(
            candidate["display_min_c"], candidate["display_max_c"],
            candidate["warning_min_c"], candidate["warning_max_c"],
        )
        saved = save_process_monitor_config(self.config, logger=self.logger)
        if not saved:
            return self._config_error(name, "Settings changed for this session but could not be saved.", show_dialogs)
        self.log(f"{name} configuration updated.", LogLevel.INFO)
        return True

    def _set_sensor_enabled(self, name, show_dialogs=True):
        """Apply and persist a sensor checkbox change immediately."""
        enabled = bool(self.enabled_vars[name].get())
        if enabled:
            self.disabled_sensors.discard(name)
            self.temp_bars[name].update_value(name, TemperatureBar.DISCONNECTED)
        else:
            self.disabled_sensors.add(name)
            self._last_warning_log_times.pop(name, None)
            self.temp_bars[name].update_value(name, TemperatureBar.DISABLED)

        self.config["disabled_sensors"] = [
            sensor for sensor in self.thermometers if sensor in self.disabled_sensors
        ]

        if self._latest_temperatures:
            self._apply_temperature_snapshot(self._latest_temperatures)
        elif enabled:
            self.active["Environment Pass"] = False

        if not save_process_monitor_config(self.config, logger=self.logger):
            message = f"{name}: enabled state changed for this session but could not be saved."
            self.log(message, LogLevel.WARNING)
            if show_dialogs:
                messagebox.showwarning("Save Failed", message)
            return False

        state = "enabled" if enabled else "disabled"
        self.log(f"{name} sensor {state}.", LogLevel.INFO)
        return True

    def _config_error(self, name, message, show_dialogs):
        full_message = f"{name}: {message}"
        self.log(full_message, LogLevel.WARNING)
        if show_dialogs:
            messagebox.showerror("Invalid PMON Configuration", full_message)
        return False

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
                    self._apply_temperature_snapshot(temps)

        except Exception as e:
            self.log(f"DP16 exception details: {type(e).__name__}: {str(e)}", LogLevel.DEBUG)
            if current_time - self.last_error_time > (self.update_interval / 1000):
                self.log(f"Unexpected error updating temperatures: {str(e)}", LogLevel.ERROR)
                self.last_error_time = current_time
                
        finally:
            # Schedule next update, store after_id for cancellation if needed.
            if self.monitor:
                self.after_id = self.parent.after(self.update_interval, self.update_temperatures)

    def _unit_affects_environment_pass(self, unit):
        name = next((sensor for sensor, sensor_unit in self.thermometer_map.items() if sensor_unit == unit), None)
        return name not in self.disabled_sensors

    def _apply_temperature_snapshot(self, temps):
        self._latest_temperatures = dict(temps)
        environment_pass = True

        for name, unit in self.thermometer_map.items():
            temp = temps.get(unit)
            affects_environment_pass = self._unit_affects_environment_pass(unit)

            if name in self.disabled_sensors:
                self.temp_bars[name].update_value(name, TemperatureBar.DISABLED)
                continue

            if temp is None:
                self.temp_bars[name].update_value(name, TemperatureBar.DISCONNECTED)
                if affects_environment_pass:
                    environment_pass = False
            elif temp == self.monitor.SENSOR_ERROR:
                self.temp_bars[name].update_value(name, TemperatureBar.SENSOR_ERROR)
                if affects_environment_pass:
                    environment_pass = False
            elif temp == self.monitor.DISCONNECTED:
                self.temp_bars[name].update_value(name, TemperatureBar.DISCONNECTED)
                if affects_environment_pass:
                    environment_pass = False
            elif isinstance(temp, (int, float)):
                try:
                    temp_value = float(temp)
                    if not math.isfinite(temp_value):
                        raise ValueError("non-finite temperature")
                    self.temp_bars[name].update_value(name, temp_value)
                    limits = self.config["sensors"][name]
                    if temp_value < limits["warning_min_c"] or temp_value > limits["warning_max_c"]:
                        environment_pass = False
                        self._log_temperature_warning(name, temp_value, limits)
                    else:
                        self._last_warning_log_times.pop(name, None)
                except (ValueError, TypeError):
                    self.temp_bars[name].update_value(name, TemperatureBar.SENSOR_ERROR)
                    self.log(f"Invalid temperature value - {name}: {temp}", LogLevel.WARNING)
                    if affects_environment_pass:
                        environment_pass = False
            else:
                self.temp_bars[name].update_value(name, TemperatureBar.SENSOR_ERROR)
                self.log(f"Invalid temperature type - {name}: {type(temp)}", LogLevel.WARNING)
                if affects_environment_pass:
                    environment_pass = False

        self.active['Environment Pass'] = environment_pass

    def _log_temperature_warning(self, name, temperature, limits):
        now = time.monotonic()
        last_log = self._last_warning_log_times.get(name)
        if last_log is not None and now - last_log < self.WARNING_LOG_INTERVAL_SECONDS:
            return
        self._last_warning_log_times[name] = now
        self.log(
            f"Temperature warning - {name}: {temperature:.1f} C is outside "
            f"configured bounds [{limits['warning_min_c']:g}, {limits['warning_max_c']:g}] C",
            LogLevel.WARNING,
        )

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
                value = TemperatureBar.DISABLED if name in self.disabled_sensors else TemperatureBar.SENSOR_ERROR
                self.temp_bars[name].update_value(name, value)

    def _set_all_temps_disconnected(self):
        """Set all temperature bars to disconnected state"""
        if hasattr(self, 'temp_bars'):
            for name in self.temp_bars:
                value = TemperatureBar.DISABLED if name in self.disabled_sensors else TemperatureBar.DISCONNECTED
                self.temp_bars[name].update_value(name, value)

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
