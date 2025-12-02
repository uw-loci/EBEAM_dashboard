import time
import tkinter as tk
from typing import Dict, List
from instrumentctl.DP16_process_monitor.DP16_process_monitor import DP16ProcessMonitor
from utils import LogLevel


class ProcessMonitorSubsystem:
    # Error state constants
    DISCONNECTED = -1
    SENSOR_ERROR = -2

    # Temperature threshold definitions
    TEMP_THRESHOLDS = {
        'Solenoid': {'green': (20, 70), 'yellow': (70, 100), 'red': (100, float('inf'))},
        'Chamber': {'green': (20, 50), 'yellow': (50, 70), 'red': (70, float('inf'))},
        'Air': {'green': (20, 30), 'yellow': (30, 40), 'red': (40, float('inf'))},
        'Default': {'green': (0, 70), 'yellow': (70, 100), 'red': (100, float('inf'))}
    }

    # Background colors for temperature states
    STATE_COLORS = {
        'green': '#d4edda',
        'yellow': '#fff3cd',
        'red': '#f8d7da',
        'disconnected': '#e0e0e0',
        'error': '#ffe5cc'
    }

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

        # Create container with grid layout
        container = tk.Frame(self.frame)
        container.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Configure 2 columns with equal weight
        for i in range(2):
            container.grid_columnconfigure(i, weight=1, uniform='col')

        # Create sensor frames in 2x3 grid (2 columns, 3 rows)
        sensor_positions = [
            ('Solenoid 1', 0, 0), ('Solenoid 2', 0, 1),
            ('Chamber Top', 1, 0), ('Chamber Bot', 1, 1),
            ('Air temp', 2, 0), ('Unassigned', 2, 1)
        ]

        self.temp_labels: Dict[str, tk.Label] = {}
        for name, row, col in sensor_positions:
            frame = tk.Frame(container, bd=1, relief=tk.RIDGE, padx=5, pady=5)
            frame.grid(row=row, column=col, padx=5, pady=5, sticky='nsew')
            label = self.create_sensor_frame(frame, name, "---")
            self.temp_labels[name] = label

    def create_sensor_frame(self, parent, title, default_text):
        """Creates a label-value pair sensor frame."""
        frame = tk.Frame(parent, pady=3)
        frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(frame, text=title, font=("Helvetica", 10, "bold")).pack()
        label = tk.Label(frame, text=default_text, font=('Helvetica', 10), bg="#d3d3d3", fg="black", padx=5, pady=2)
        label.pack()

        return label

    def get_temperature_state(self, name, temp):
        """Determine temperature state (green/yellow/red) based on thresholds."""
        # Determine which threshold set to use
        if 'Solenoid' in name:
            thresholds = self.TEMP_THRESHOLDS['Solenoid']
        elif 'Chamber' in name:
            thresholds = self.TEMP_THRESHOLDS['Chamber']
        elif 'Air' in name:
            thresholds = self.TEMP_THRESHOLDS['Air']
        else:
            thresholds = self.TEMP_THRESHOLDS['Default']

        # Check temperature against thresholds
        if thresholds['green'][0] <= temp < thresholds['green'][1]:
            return 'green'
        elif thresholds['yellow'][0] <= temp < thresholds['yellow'][1]:
            return 'yellow'
        else:
            return 'red'

    def update_sensor_display(self, name, value):
        """Update sensor display with value and appropriate color coding."""
        label = self.temp_labels[name]

        if value == self.DISCONNECTED:
            label.config(
                text="---",
                bg=self.STATE_COLORS['disconnected'],
                fg='#808080'
            )
        elif value == self.SENSOR_ERROR:
            label.config(
                text="ERR",
                bg=self.STATE_COLORS['error'],
                fg='black'
            )
        else:
            # Normal temperature display
            color_state = self.get_temperature_state(name, value)
            label.config(
                text=f"{value:.1f}°C",
                bg=self.STATE_COLORS[color_state],
                fg='black'
            )

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
                            self.update_sensor_display(name, self.DISCONNECTED)
                            self.active['Environment Pass'] = False
                        elif temp == self.monitor.SENSOR_ERROR:
                            self.update_sensor_display(name, self.SENSOR_ERROR)
                            self.active['Environment Pass'] = False
                        elif temp == self.monitor.DISCONNECTED:
                            self.update_sensor_display(name, self.DISCONNECTED)
                            self.active['Environment Pass'] = False
                        elif isinstance(temp, (int, float)):
                            try:
                                temp_value = float(temp)
                                if -90 <= temp_value <= 500:  # Valid temperature range
                                    self.update_sensor_display(name, temp_value)
                                    self.active['Environment Pass'] = True # Update Machine Status Progress Bar
                                    self.log(f"Temperature update - {name}: {temp_value:.1f}C", LogLevel.VERBOSE)
                                else:
                                    self.update_sensor_display(name, self.SENSOR_ERROR)
                                    self.log(f"Temperature out of range - {name}: {temp_value}", LogLevel.WARNING)
                                    self.active['Environment Pass'] = False
                            except (ValueError, TypeError):
                                self.update_sensor_display(name, self.SENSOR_ERROR)
                                self.log(f"Invalid temperature value - {name}: {temp}", LogLevel.WARNING)
                                self.active['Environment Pass'] = False
                        else:
                            self.update_sensor_display(name, self.SENSOR_ERROR)
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
        """Set all temperature displays to error state"""
        if hasattr(self, 'temp_labels'):
            for name in self.temp_labels:
                self.update_sensor_display(name, self.SENSOR_ERROR)

    def _set_all_temps_disconnected(self):
        """Set all temperature displays to disconnected state"""
        if hasattr(self, 'temp_labels'):
            for name in self.temp_labels:
                self.update_sensor_display(name, self.DISCONNECTED)

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