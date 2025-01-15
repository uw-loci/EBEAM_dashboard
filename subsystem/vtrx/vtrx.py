# vtrx.py
import tkinter as tk
from tkinter import messagebox
import datetime
import serial
import threading
from utils import LogLevel
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from tkinter import ttk
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import time
import os
import sys
import queue

def resource_path(relative_path):
    """ Get the absolute path to a resource, works for development and when running as bundled executable"""
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

class VTRXSubsystem: 
    ERROR_CODES = {
        0: "VALVE CONTENTION",
        1: "COLD CATHODE FAILURE",
        2: "MICROPIRANI FAILURE",
        3: "UNEXPECTED PRESSURE ERROR",
        4: "SAFETY RELAY ERROR",
        5: "ARGON GATE VALVE ERROR",
        6: "TURBO GATE VALVE ERROR",
        7: "VENT VALVE OPEN ERROR",
        8: "PRESSURE NACK ERROR",
        9: "PRESSURE SENSE ERROR",
        10: "PRESSURE UNIT ERROR",
        11: "USER TAG NACK ERROR",
        12: "RELAY NACK ERROR",
        13: "PRESSURE DOSE WARNING",
        14: "TURBO GATE VALVE WARNING",
        15: "TURBO ROTOR ON WARNING",
        16: "UNSAFE FOR HV WARNING"
    }

    def __init__(self, parent, serial_port='COM7', baud_rate=9600, logger=None):
        self.parent = parent
        self.serial_port = serial_port
        self.baud_rate = baud_rate
        self.logger = logger
        self.data_queue = queue.Queue()
        
        self.MAX_HISTORY_SECONDS = 36000 # 10 hours
        self.full_history_x = []    # Complete timestamp history
        self.full_history_y = []    # Complete pressure history
        self.x_data = []            # Display window data
        self.y_data = []            # Display window data
        self.display_window = 300   # Default 5 minutes

        self.circle_indicators = []
        self.error_state = False
        self.error_logged = False
        self.stop_event = threading.Event()
        self.last_data_received_time = time.time()
        self.last_gui_update_time = time.time()
        
        current_time = datetime.datetime.now()
        self.full_history_x = [current_time]
        self.full_history_y = [1e3]
        self.x_data = [current_time]
        self.y_data = [1e3]
        
        self.setup_serial()
        self.setup_gui()
        
        if self.ser is not None and self.ser.is_open:
            self.start_serial_thread()

    def update_com_port(self, new_port):
        self.log(f"Updating COM port from {self.serial_port} to {new_port}", LogLevel.INFO)
        
        # stop the existing serial thread
        self.stop_serial_thread()

        # close existing serial connection if it exists
        if self.ser and self.ser.is_open:
            self.ser.close()
            self.log(f"Closed serial port {self.serial_port}", LogLevel.INFO)

        self.serial_port = new_port
        self.setup_serial()

        # If the new connection is successful, restart the serial thread
        if self.ser and self.ser.is_open:
            self.start_serial_thread()
            self.log(f"Updated VTRX COM port to {new_port}", LogLevel.INFO)
        else:
            self.log(f"Failed to establish connection on new port {new_port}", LogLevel.ERROR)

    def setup_serial(self):
        """
        Attempt to establish serial connection with the VTRX hardware using the specified port and baud rate.

        Tries to open the serial port configured in `self.serial_port`. If successful, 
        updates the internal `self.ser` reference. If it fails, logs an error and sets 
        `self.ser` to None.

        Raises:
            serial.SerialException: If opening the serial port fails unexpectedly 
        """
        try:
            self.ser = serial.Serial(self.serial_port, self.baud_rate, timeout=1)
            self.log(f"Serial connection established on {self.serial_port}", LogLevel.INFO)
            self.error_logged = False # reset error flag on success
        except serial.SerialException as e:
            self.log(f"Error opening serial port {self.serial_port}: {e}", LogLevel.ERROR)
            self.ser = None
            self.error_logged = False

    def read_serial(self):
        """
        Continuously read data from the serial port and push it to the queue.

        This method runs in the dedicated "serial" thread. It checks if the serial port is open,
        reads a line of data, decodes it, and places the resulting string onto 
        `self.data_queue`. If any serial-related error occurs, logs the error once.

        This method exits if `self.stop_event` is set.
        """
        while not self.stop_event.is_set():
            if self.ser and self.ser.is_open:
                try:
                    data_bytes = self.ser.readline()
                    if data_bytes:
                        self.last_data_received_time = time.time()
                        data = data_bytes.decode('utf-8', errors='replace').strip()
                        if data:
                            self.data_queue.put(data)
                    else:
                        self.data_queue.put(None)
                except serial.SerialException as e:
                    if not self.error_logged:
                        self.log(f"VTRX Serial communication error: {e}", LogLevel.ERROR)
                        self.error_logged = True
                except UnicodeDecodeError as e:
                    if not self.error_logged:
                        self.log(f"VTRX Data decoding error: {e}", LogLevel.ERROR)
                        self.error_logged = True
                except Exception as e:
                    if not self.error_logged:
                        self.log(f"VTRX Unexpected error: {e}", LogLevel.ERROR)
                        self.error_logged = True
            else:
                if not self.error_logged:
                    self.log("VTRX Serial port is not open.", LogLevel.ERROR)
                    self.error_logged = True
                time.sleep(1)

    def _create_indicator_circle(self, parent_frame, color="grey"):
        canvas = tk.Canvas(parent_frame, width=30, height=30, highlightthickness=0)
        oval_id = canvas.create_oval(2, 2, 28, 28, fill=color, outline="black")
        canvas._oval_id = oval_id
        canvas.bind('<Configure>', lambda e: self._resize_indicator(canvas, e))
        return canvas, oval_id

    def _resize_indicator(self, canvas, event):
        width, height = event.width, event.height
        margin = min(width, height) // 4
        # Update the coordinates of the existing oval without deleting it.
        if hasattr(canvas, '_oval_id'):
            canvas.coords(canvas._oval_id, margin, margin, width - margin, height - margin)

    def process_queue(self):
        """
        Process all items in the data queue and update the GUI.

        This method is scheduled every 500ms. It fetches new items from 
        self.data_queue. If an item is None, it indicates no data is currently 
        available. If the item is valid data, it invokes the serial handler.

        After processing all items, reschedules itself to run again after 500 ms.
        """
        try:
            while True:
                data = self.data_queue.get_nowait()
                if data is None:
                    self.update_gui_with_error_state()
                else:
                    self.handle_serial_data(data)
        except queue.Empty:
            pass
        finally:
            self.parent.after(500, self.process_queue)

    def update_gui_with_error_state(self):
        """
        Update GUI elements to reflect error state.
        
        Sets indicators to red, updates pressure label, and changes plot appearance
        to indicate error condition.
        """
        self.label_pressure.config(text="No data...", fg="red")
        self.line.set_color('red')
        self.ax.set_title('(Error)', fontsize=10, color='red')
        for canvas, oval_id in self.circle_indicators:
            canvas.itemconfig(oval_id, fill='red')
        self.canvas.draw_idle()

    def handle_serial_data(self, data):
        """
        Parse and handle a single line of raw serial data from the VTRX system.

        The serial data is expected to be a semicolon-separated string containing 
        at least three fields:
            1) pressure value (float)
            2) raw pressure string (scientific notation)
            3) switch states in binary format
            4+) optional error messages

        If parsing is successful, updates the GUI with the new pressure value and 
        switch states, or sets the error state if anything is invalid.

        Args:
            data: The raw data string read from the serial port (e.g., "1.23;1.23E-01;10110010;972b ERR:...").

        Raises:
            ValueError: If the pressure value cannot be converted to float.
            IndexError: If the data string has fewer parts than expected.
        """
        data_parts = data.split(';')
        if len(data_parts) < 3:
            self.log("Incomplete data received.", LogLevel.WARNING)
            self.log(f"Literal data from VTRX: {data}", LogLevel.DEBUG)
            self.error_state = True
            self.update_gui_with_error_state()
            return
        
        try:
            pressure_value = float(data_parts[0])   # numerical pressure value
            pressure_raw = data_parts[1]            # raw string from 972b sensor
            switch_states_binary = data_parts[2]    # binary state switches
            switch_states = [int(bit) for bit in f"{int(switch_states_binary, 2):08b}"] # Ensures it's 8 bits long

            self.error_state = False # Assume no error unless found
            if len(data_parts) > 3: # Handle errors
                errors = data_parts[3:] # All subsequent parts are errors
                for error in errors:
                    if error.startswith("972b ERR:"):
                        error_code, error_message = error.split(":")[1:]
                        self.log(f"VTRX Err {error_code}: Actual:{error_message}", LogLevel.ERROR)
                        self.error_state = True
            
            if not self.error_state:    
                self.update_gui(pressure_value, pressure_raw, switch_states)
            else:
                self.update_gui_with_error_state()
            self.error_logged = False # reset error flag on successful data processing

        except ValueError as e:    
            self.log(f"VTRX Data processing error: {e}", LogLevel.ERROR)
            self.error_state = True
        except IndexError as e:
            self.log(f"VTRX Data processing error: Insufficient segments - {data}. Error: {e}", LogLevel.ERROR)
            self.error_state = True

    def log(self, message, level=LogLevel.INFO):
        if self.logger:
            self.logger.log(message, level)
        else:
            print(f"{level.name}: {message}")

    def setup_gui(self):
        """
        Initializes and configures the GUI components including status indicators and plot.
        
        Creates:
        - Status indicator frame with switch state indicators
        - Pressure label and control buttons
        - Real-time pressure plot with logarithmic scale
        """
        layout_frame = tk.Frame(self.parent)
        layout_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Formatting status indicators
        switches_frame = tk.Frame(layout_frame)
        switches_frame.pack(side=tk.LEFT, fill=tk.Y, expand=True, padx=5)

        # Distribute vertical space
        switches_frame.grid_rowconfigure(tuple(range(10)), weight=1)
        switches_frame.grid_columnconfigure(0, weight=3) # Label colunm
        switches_frame.grid_columnconfigure(1, weight=1) # indicator column 

        # Setup labels for each switch
        switch_labels = [
            "Pumps Power ON", 
            "Turbo Rotor ON", 
            "Turbo Vent OPEN",
            "972b Power ON", 
            "Turbo Gate CLOSED",
            "Turbo Gate OPEN", 
            "Argon Gate OPEN", 
            "Argon Gate CLOSED"
        ]
        label_width = 15

        for idx, switch in enumerate(switch_labels):
            label = tk.Label(switches_frame, text=switch, anchor='center', width=label_width)
            label.grid(row=idx, column=0, sticky='nsew', pady=2, padx=(0, 1))
            
            canvas, oval_id = self._create_indicator_circle(switches_frame, color='grey')
            canvas.grid(row=idx, column=1, sticky='nsew', pady=2, padx=(0, 1))
            self.circle_indicators.append((canvas, oval_id))

        # Pressure label setup
        pressure_frame = tk.Frame(switches_frame)
        pressure_frame.grid(row=len(switch_labels), column=0, columnspan=2, sticky='nsew', pady=1)
        # Configure columns to center the label
        pressure_frame.grid_columnconfigure(0, weight=1) 
        pressure_frame.grid_columnconfigure(2, weight=1) 
        pressure_frame.grid_columnconfigure(1, weight=0) 

        self.label_pressure = tk.Label(
            pressure_frame,
            text="No data...", 
            anchor='center',
            font=('Helvetica', 11, 'bold'), 
            relief='ridge', 
            bg='#0D006E', #007FFF
            fg='white', 
            padx=3, pady=2
        )
        self.label_pressure.grid(row=0, column=1, ipady=2)

        # Buttons frame
        button_frame = tk.Frame(switches_frame)
        button_frame.grid(row=len(switch_labels)+1, column=0, columnspan=2, sticky='nsew', pady=1)
        button_frame.bind("<Configure>", self._on_button_frame_resize)

        self.button_frame = button_frame
    
        timeframe_frame = tk.Frame(button_frame)
        timeframe_frame.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=5)
        
        times = [
            ("5 min", 300),
            ("15 min", 900),
            ("30 min", 1800),
            ("1 hour", 3600),
            ("5 hour", 18000),
            ("10 hour", 36000)
        ]
        
        self.time_window_var = tk.StringVar(value="5 min")
        time_dropdown = ttk.Combobox(
            timeframe_frame, 
            textvariable=self.time_window_var,
            values=[t[0] for t in times],
            state='readonly',
            width=6
        )
        time_dropdown.pack(fill=tk.X)
        time_dropdown.bind('<<ComboboxSelected>>', 
            lambda _: self.update_time_window(dict(times)[self.time_window_var.get()]))
        
        self.save_button = tk.Button(button_frame, text="Save Plot", command=self.save_plot)
        self.save_button.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=5)

        # Plot frame
        plot_frame = tk.Frame(layout_frame)
        plot_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=1) 
        self.fig, self.ax = plt.subplots()
        self.fig.subplots_adjust(left=0.15, right=0.99, top=0.99, bottom=0.05)
        self.line, = self.ax.plot(self.x_data, self.y_data, 'g-')
        self.ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
        self.fig.autofmt_xdate()  
        self.ax.set_title('')
        self.ax.set_xlabel('Time', fontsize=8)
        self.ax.set_ylabel('Pressure [mbar]', fontsize=8)
        self.ax.set_yscale('log')
        self.ax.set_ylim(1e-7, 1e3)  
        self.ax.tick_params(axis='x', labelsize=6, pad=1)
        self.ax.grid(True)

        self.canvas = FigureCanvasTkAgg(self.fig, master=plot_frame)
        self.canvas.draw()
        self.canvas_widget = self.canvas.get_tk_widget()
        self.canvas_widget.pack(fill=tk.BOTH, expand=True)
     
    def update_gui(self, pressure_value, pressure_raw, switch_states):
        """
        Update GUI labels, indicators, and plot with new pressure/switch data.
    
        Args:
            pressure_value (float): Current pressure reading
            pressure_raw (str): Raw pressure string from sensor (e.g. "1.23E-04)
            switch_states (list): List of 8 bits binary switch states
        """
        if self.error_state:
            return
        
        current_time = datetime.datetime.now()
        
        # Update full history
        self.full_history_x.append(current_time)
        self.full_history_y.append(pressure_value)
        
        # Trim history older than MAX_HISTORY_SECONDS
        cutoff_time = current_time - datetime.timedelta(seconds=self.MAX_HISTORY_SECONDS)
        while self.full_history_x and self.full_history_x[0] < cutoff_time:
            self.full_history_x.pop(0)
            self.full_history_y.pop(0)
        
        # Update display window data
        display_cutoff = current_time - datetime.timedelta(seconds=self.display_window)
        self.x_data = [x for x in self.full_history_x if x >= display_cutoff]
        self.y_data = self.full_history_y[-len(self.x_data):]
        
        if time.time() - self.last_gui_update_time > 0.5:
            self.last_gui_update_time = time.time()
            if not self.error_state:
                # Normal state
                self.label_pressure.config(
                    text=f"{pressure_raw} mbar",
                    bg="white",
                    fg="black"
                )
            else:
                # Error state
                self.label_pressure.config(
                    text="No data...",
                    bg="#FF0000",
                    fg="#FFB6B6"
                )
            self.line.set_color('green' if not self.error_state else 'red')
            self.ax.set_title(
                'VTRX Pressure Readout',
                fontsize=10,
                color='black' if not self.error_state else 'red'
            )
            self.update_plot()

            for idx, state in enumerate(switch_states):
                canvas, oval_id = self.circle_indicators[idx]
                canvas.itemconfig(oval_id, fill='#00FF24' if state == 1 else 'grey')
            
            self.log(f"GUI updated with pressure: {pressure_raw} mbar", LogLevel.DEBUG)

    def update_plot(self):
        """Update plot with current display window data."""
        # Update the data for the line
        self.line.set_data(self.x_data, self.y_data)
        self.ax.relim()
        self.ax.autoscale_view(True, True, False)

        if self.y_data:
            y_min = min(self.y_data)
            y_max = max(self.y_data)
            if y_min > 0 and y_max > 0:
                self.ax.set_ylim(y_min * 0.5, y_max * 2)

        if self.x_data:
            current_time = self.x_data[-1]
            start_time = current_time - datetime.timedelta(seconds=self.display_window)
            self.ax.set_xlim(start_time, current_time)

        self.canvas.draw_idle()
        self.canvas.flush_events()

    def start_serial_thread(self):
        self.stop_event.clear()
        self.serial_thread = threading.Thread(target=self.read_serial, daemon=True)
        self.serial_thread.start()
        self.parent.after(100, self.process_queue)

    def stop_serial_thread(self):
        self.stop_event.set()
        if hasattr(self, 'serial_thread') and self.serial_thread.is_alive():
            self.serial_thread.join()
    
    def update_time_window(self, seconds):
        current_time = datetime.datetime.now()
        self.display_window = seconds
        
        # Update display data from full history
        display_cutoff = current_time - datetime.timedelta(seconds=seconds)
        self.x_data = [x for x in self.full_history_x if x >= display_cutoff]
        self.y_data = self.full_history_y[-len(self.x_data):]
        
        self.update_plot()

    def save_plot(self):
        """
        Save the current plot as a PNG file in the EBEAM_dashboard_logs directory.
        """
        try:
            # Create logs directory if it doesn't exist
            log_dir = "EBEAM-Dashboard-Logs"
            if not os.path.exists(log_dir):
                os.makedirs(log_dir)
            
            # Generate timestamp for filename
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = os.path.join(log_dir, f"pressure_plot_{timestamp}.png")
            
            # Save the figure
            self.fig.savefig(filename, dpi=300, bbox_inches='tight')
            self.log(f"Plot saved to {filename}", LogLevel.INFO)
            messagebox.showinfo("Success", f"Plot saved to {filename}")
        except Exception as e:
            error_message = f"Failed to save plot: {str(e)}"
            messagebox.showerror("Error", error_message)
            self.log(error_message, LogLevel.ERROR)

    def _on_button_frame_resize(self, event):
        """
        Callback to adjust the font size of the Reset/Save buttons
        based on the current height of the parent frame.
        """
        base_height = 300 
        base_font_size = 16
        current_height = event.height

        scale_factor = max(0.5, min(2.0, current_height / base_height))
        new_font_size = int(base_font_size * scale_factor)
        self.save_button.config(font=("Helvetica", new_font_size))

    def __del__(self):
            # TBD ensure serial thread is stopped when the object is destroyed
            self.stop_serial_thread()
            if self.ser and self.ser.is_open:
                self.ser.close()
          