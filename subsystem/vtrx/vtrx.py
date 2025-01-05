# vtrx.py
import tkinter as tk
from tkinter import messagebox
import datetime
import serial
import threading
from utils import LogLevel
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
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
    MAX_POINTS = 20 # Maximum number of points to display on the plot
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
        self.x_data = []
        self.y_data = []
        self.circle_indicators = []
        self.error_state = False
        self.error_logged = False
        self.stop_event = threading.Event()
        self.setup_serial()
        self.setup_gui()

        self.time_window = 100 # Time window in seconds
        self.data_timeout = 1.5 # Seconds timeout for receiving data
        self.init_time = datetime.datetime.now()
        self.last_gui_update_time = time.time()
        self.x_data = [self.init_time + datetime.timedelta(seconds=i) for i in range(self.time_window)]
        self.y_data = [0] * self.time_window

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
        try:
            self.ser = serial.Serial(self.serial_port, self.baud_rate, timeout=1)
            self.log(f"Serial connection established on {self.serial_port}", LogLevel.INFO)
            self.error_logged = False # reset error flag on success
        except serial.SerialException as e:
            self.log(f"Error opening serial port {self.serial_port}: {e}", LogLevel.ERROR)
            self.ser = None
            self.error_logged = False

    def read_serial(self):
        while not self.stop_event.is_set():
            if self.ser and self.ser.is_open:
                try:
                    data_bytes = self.ser.readline()
                    if data_bytes:
                        self.last_data_received_time = time.time()  # Update last received time
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
        """ Switch state circular indicator on a canvas. """
        canvas = tk.Canvas(parent_frame, width=30, height=30, highlightthickness=0)
        oval_id = canvas.create_oval(5, 5, 25, 25, fill=color, outline="black")
        return canvas, oval_id

    def process_queue(self):
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
        """Update GUI elements to reflect error state.
        
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
        """Process raw serial data from VTRX system.
    
        Args:
            data (str): Semicolon-separated string containing:
                - pressure value (float)
                - raw pressure string
                - binary switch states
                - optional error messages
                
        Format: "pressure;raw_pressure;switch_states[;errors...]"
        """
        data_parts = data.split(';')
        if len(data_parts) < 3:
            self.log("Incomplete data received.", LogLevel.WARNING)
            self.log(f"Literal data from VTRX: {data}", LogLevel.VERBOSE)
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
        """Initialize and configure the GUI components including status indicators and plot.
        
        Creates:
        - Status indicator frame with switch state indicators
        - Pressure label and control buttons
        - Real-time pressure plot with logarithmic scale
        """
        layout_frame = tk.Frame(self.parent)
        layout_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Formatting status indicators
        switches_frame = tk.Frame(layout_frame, width=135)
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
        label_width = 17

        # switches_frame.grid_columnconfigure(0, weight=1)
        # switches_frame.grid_columnconfigure(1, weight=0)

        for idx, switch in enumerate(switch_labels):
            
            label = tk.Label(switches_frame, text=switch, anchor='center', width=label_width)
            label.grid(row=idx, column=0, sticky='nsew', pady=2)
            
            canvas, oval_id = self._create_indicator_circle(switches_frame, color='grey')
            canvas.grid(row=idx, column=1, sticky='nsew', pady=2, padx=(5,0))
            self.circle_indicators.append((canvas, oval_id))

        # Pressure label setup
        self.label_pressure = tk.Label(switches_frame, text="No data...", anchor='center', width=label_width,
                                font=('Helvetica', 11, 'bold'))
        self.label_pressure.grid(row=len(switch_labels), column=0, columnspan=2, sticky='nsew', pady=1)

        # Buttons frame with vertical expansion
        button_frame = tk.Frame(switches_frame)
        button_frame.grid(row=len(switch_labels)+1, column=0, columnspan=2, sticky='nsew', pady=1)
        
        self.reset_button = tk.Button(button_frame, text="Reset VTRX", command=self.confirm_reset)
        self.reset_button.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=5)
        
        self.clear_button = tk.Button(button_frame, text="Clear Plot", command=self.clear_graph)
        self.clear_button.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=5)

        # Plot frame
        plot_frame = tk.Frame(layout_frame)
        plot_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=1) 
        self.fig, self.ax = plt.subplots()
        self.fig.subplots_adjust(left=0.15, right=0.99, top=0.99, bottom=0.1) 
        self.line, = self.ax.plot(self.x_data, self.y_data, 'g-')
        self.ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
        self.fig.autofmt_xdate()  
        self.ax.set_title('')
        self.ax.set_xlabel('Time', fontsize=8)
        self.ax.set_ylabel('Pressure [mbar]', fontsize=8)
        self.ax.set_yscale('log')
        self.ax.set_ylim(1e-7, 3000.0)
        self.ax.tick_params(axis='x', labelsize=6)
        self.ax.grid(True)

        self.canvas = FigureCanvasTkAgg(self.fig, master=plot_frame)
        self.canvas.draw()
        self.canvas_widget = self.canvas.get_tk_widget()
        self.canvas_widget.pack(fill=tk.BOTH, expand=True)
    
    def update_gui(self, pressure_value, pressure_raw, switch_states):
        """Update GUI with new pressure and switch state data.
    
        Args:
            pressure_value (float): Current pressure reading
            pressure_raw (str): Raw pressure string from sensor
            switch_states (list): List of binary switch states
        """
        if self.error_state:
            return
        
        current_time = datetime.datetime.now()
        elapsed_time = (current_time - self.init_time).total_seconds()

        if elapsed_time > self.time_window:
            self.x_data.pop(0)
            self.y_data.pop(0)

        self.x_data.append(current_time)
        self.y_data.append(pressure_value)

        if time.time() - self.last_gui_update_time > 0.5:
            self.last_gui_update_time = time.time()
            self.label_pressure.config(text=f"Press: {pressure_raw} mbar", fg="black" if not self.error_state else "red")
            self.line.set_color('green' if not self.error_state else 'red')
            self.ax.set_title('Live Pressure Readout', fontsize=10, color='black' if not self.error_state else 'red')
            self.update_plot()

            for idx, state in enumerate(switch_states):
                canvas, oval_id = self.circle_indicators[idx]
                canvas.itemconfig(oval_id, fill='#00FF24' if state == 1 else 'grey')
            
            self.log(f"GUI updated with pressure: {pressure_raw} mbar", LogLevel.DEBUG)

    def update_plot(self):
        # Update the data for the line, rather than recreating it
        self.line.set_data(self.x_data, self.y_data)
        self.ax.relim()  # Recalculate limits based on the new data
        self.ax.autoscale_view(True, True, False)

        current_time = self.x_data[-1]
        start_time = current_time - datetime.timedelta(seconds=self.time_window)
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

    def confirm_reset(self):
        if messagebox.askyesno("Confirm Reset", "Do you really want to reset the VTRX System?"):
            self.send_reset_command()

    def send_reset_command(self):
        if self.ser and self.ser.is_open:
            try:
                self.ser.write("RESET\n".encode('utf-8')) # Send RESET command to Arduino
                self.log("Sent RESET command to VTRX.", LogLevel.INFO)
            except serial.SerialException as e:
                error_message = f"Failed to send reset command: {str(e)}"
                messagebox.showerror("Error", error_message)
                self.log(error_message, LogLevel.ERROR)
        else:
            error_message = "Cannot send RESET command. VTRX serial port is not open."
            messagebox.showerror("Error", error_message)
            self.log(error_message, LogLevel.ERROR)

    def clear_graph(self):
        # Clear the plot
        self.line.set_data([], [])
        self.ax.relim()
        self.ax.autoscale_view()
        self.canvas.draw()
        self.x_data = [datetime.datetime.now() + datetime.timedelta(seconds=i) for i in range(self.time_window)]
        self.y_data = [0] * len(self.x_data)
        self.init_time = self.x_data[0]
        self.log("VTRX Pressure Graph cleared", LogLevel.INFO)

    def __del__(self):
            # TBD ensure serial thread is stopped when the object is destroyed
            self.stop_serial_thread()
            if self.ser and self.ser.is_open:
                self.ser.close()
          