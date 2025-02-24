# utils.py
import sys
import subprocess
import os
import tkinter as tk
from tkinter import messagebox, ttk, filedialog
import datetime
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import enum


class LogLevel(enum.IntEnum):
    VERBOSE = 0
    DEBUG = 1
    INFO = 2
    WARNING = 3
    ERROR = 4
    CRITICAL = 5

class Logger:
    def __init__(self, text_widget, log_level=LogLevel.INFO, log_to_file=False):
        self.text_widget = text_widget
        self.log_level = log_level
        self.log_to_file = log_to_file
        self.log_file = None
        if log_to_file:
            self.setup_log_file()

    def setup_log_file(self):
        """Setup a new log file in the 'EBEAM_dashboard/EBEAM-Dashboard-Logs/' directory."""
        try:
            # Use the EBEAM_dashboard directory
            base_path = os.path.abspath(os.path.join(os.path.expanduser("~"), "EBEAM_dashboard"))
            log_dir = os.path.join(base_path, "EBEAM-Dashboard-Logs")
            os.makedirs(log_dir, exist_ok=True)
            
            # Create the log file with the old naming pattern
            log_file_name = f"log_{datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.txt"
            self.log_file = open(os.path.join(log_dir, log_file_name), 'w')
            print(f"Log file created at {os.path.join(log_dir, log_file_name)}")
        except Exception as e:
            print(f"Error creating log file: {str(e)}")
        
    def log(self, msg, level=LogLevel.INFO):
        """ Log a message to the text widget and optionally to local file """
        if level >= self.log_level:
            timestamp = datetime.datetime.now().strftime("%H:%M:%S")
            formatted_message = f"[{timestamp}] - {level.name}: {msg}\n"
            
            # Write to text widget
            self.text_widget.insert(tk.END, formatted_message)
            self.text_widget.see(tk.END)

            # write to log flie if enabled
            if self.log_to_file and self.log_file:
                try:
                    self.log_file.write(formatted_message)
                    self.log_file.flush()
                except Exception as e:
                    print(f"Error writing to log file: {str(e)}")

    def debug(self, message):
        self.log(message, LogLevel.DEBUG)

    def info(self, message):
        self.log(message, LogLevel.INFO)

    def warning(self, message):
        self.log(message, LogLevel.WARNING)
    
    def error(self, message):
        self.log(message, LogLevel.ERROR)

    def critical(self, message):
        self.log(message, LogLevel.CRITICAL)

    def set_log_level(self, level):
        self.log_level = level

    def close(self):
        if self.log_file:
            try:
                self.log_file.close()
                self.log_file = None
            except Exception as e:
                print(f"Error closing log file {str(e)}")

class MessagesFrame:
    MAX_LINES = 100  # Maximum number of lines to keep in the widget at a time

    def __init__(self, parent):
        self.frame = tk.Frame(parent, borderwidth=2, relief="solid")
        self.frame.pack(fill=tk.BOTH, expand=True) 

        # Add a title to the Messages & Errors frame
        label = tk.Label(self.frame, text="Messages & Errors", font=("Helvetica", 10, "bold"))
        label.grid(row=0, column=0, columnspan=4, sticky="ew", padx=10, pady=10)

        # Configure the grid layout to allow the text widget to expand
        self.frame.columnconfigure(0, weight=1)
        self.frame.columnconfigure(1, weight=1)
        self.frame.columnconfigure(2, weight=1)
        self.frame.columnconfigure(3, weight=0)
        self.frame.rowconfigure(1, weight=1)

        # Create a Text widget for logs
        self.text_widget = tk.Text(self.frame, wrap=tk.WORD, font=("Helvetica", 8))
        self.text_widget.grid(row=1, column=0, columnspan=4, sticky="nsew", padx=10, pady=0)

        # Create a button to clear the text widget
        self.clear_button = tk.Button(self.frame, text="Clear Messages", command=self.confirm_clear)
        self.clear_button.grid(row=2, column=0, sticky="ew", padx=5, pady=10)

        self.export_button = tk.Button(self.frame, text="Export", command=self.export_log)
        self.export_button.grid(row=2, column=1, sticky="ew", padx=5, pady=10)

        self.toggle_file_logging_button = tk.Button(self.frame, text="Record Log: ON", command=self.toggle_file_logging)
        self.toggle_file_logging_button.grid(row=2, column=2, sticky="ew", padx=5, pady=10)

        # circular indicator for log writing state
        self.logging_indicator_canvas = tk.Canvas(self.frame, width=16, height=16, highlightthickness=0)
        self.logging_indicator_canvas.grid(row=2, column=3, padx=(0, 10), pady=10)
        self.logging_indicator_circle = self.logging_indicator_canvas.create_oval(
            2, 2, 14, 14, fill="#00FF24", outline="black"
        )

        self.file_logging_enabled = True
        self.logger = Logger(self.text_widget, log_level=LogLevel.DEBUG, log_to_file=True)

        # Redirect stdout to the text widget
        sys.stdout = TextRedirector(self.text_widget, "stdout")

        # Ensure that the log directory exists
        self.ensure_log_directory()

    def write(self, msg):
        """ Write message to the text widget and trim if necessary. """
        self.text_widget.insert(tk.END, msg)
        self.trim_text()

    def toggle_file_logging(self):
        if self.file_logging_enabled:
            # Currently ON, turn it OFF
            self.logger.info("Log recording has been turned OFF.")
            self.file_logging_enabled = False
            self.logger.log_to_file = False
            if self.logger.log_file:
                try:
                    self.logger.log_file.close()
                except Exception as e:
                    print(f"Error closing log file: {e}")
                self.logger.log_file = None

            self.toggle_file_logging_button.config(text="Record Log: OFF")
            self.logging_indicator_canvas.itemconfig(self.logging_indicator_circle, fill="gray")
        else:
            # Currently OFF, turn it ON
            self.file_logging_enabled = True
            self.logger.log_to_file = True
            
            if not self.logger.log_file:  # if no file is open, set up a new one
                self.logger.setup_log_file()
            self.toggle_file_logging_button.config(text="Record Log: ON")
            self.logging_indicator_canvas.itemconfig(
                self.logging_indicator_circle, 
                fill="#00FF24"
            )
            self.logger.info("Log recording has been turned ON.")

    def set_log_level(self, level):
        self.logger.set_log_level(level)

    def get_log_level(self):
        return self.logger.log_level

    def flush(self):
        """ Flush method needed for stdout redirection compatibility. """
        pass

    def trim_text(self):
        ''' Remove the oldest lines to maintain a maximum number of lines in the text widget. '''
        line_count = int(self.text_widget.index('end-1c').split('.')[0])
        if line_count > self.MAX_LINES:
            line_diff = line_count - self.MAX_LINES
            self.text_widget.delete('1.0', f'{line_diff}.0')

    def ensure_log_directory(self):
        ''' Ensure the 'logs/' directory exists, even when running as an executable. '''
        try:
            # For PyInstaller, _MEIPASS is the path to the temporary folder where the app is unpacked.
            # os.path.abspath(".") gives the path to the current directory when running the script normally.
            if hasattr(sys, '_MEIPASS'):
                # If running as a bundled executable
                base_path = os.path.expanduser("~")  # Gets the home directory
            else:
                # If running as a script (e.g., python main.py)
                base_path = os.path.abspath(".")

            self.log_dir = os.path.join(base_path, "EBEAM-Dashboard-Logs")
            if not os.path.exists(self.log_dir):
                os.makedirs(self.log_dir)
        except Exception as e:
            print(f"Failed to create log directory: {str(e)}")

    def export_log(self):
        """ Export the current log contents to a user-specified file. """
        try:
            # Open a file dialog to let the user choose save location
            initial_name = f"log_export_{datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.txt"
            file_path = filedialog.asksaveasfilename(
                defaultextension=".txt",
                initialfile=initial_name,
                title="Export Log As...",
                filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")]
            )
            if file_path:
                with open(file_path, 'a') as file:
                    file.write(self.text_widget.get("1.0", tk.END))
                messagebox.showinfo("Export Successful", f"Log exported to {file_path}")
        except Exception as e:
            messagebox.showerror("Export Error", f"Failed to export log: {str(e)}")

    def confirm_clear(self):
        ''' Show a confirmation dialog before clearing the text widget '''
        if messagebox.askokcancel("Clear Messages", "Do you really want to clear all messages?"):
            self.text_widget.delete('1.0', tk.END)

class TextRedirector:
    def __init__(self, widget, tag="stdout"):
        self.widget = widget
        self.tag = tag

    def write(self, msg):
        self.widget.insert(tk.END, msg, (self.tag,))
        self.widget.see(tk.END)  # Scroll to the end

    def flush(self):
        pass  # Needed for compatibility

class SetupScripts:
    def __init__(self, parent):
        self.parent = parent
        self.setup_gui()

    def setup_gui(self):
        self.frame = tk.Frame(self.parent)
        self.frame.pack(pady=10, fill=tk.X)

        # Label
        tk.Label(self.frame, text="Select Config Script:").pack(side=tk.LEFT)

        # Dropdown Menu for selecting a script
        self.script_var = tk.StringVar()
        self.dropdown = ttk.Combobox(self.frame, textvariable=self.script_var)
        self.dropdown.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        self.populate_dropdown()

        # Execute Button
        self.execute_button = tk.Button(self.frame, text="Execute", command=self.execute_script)
        self.execute_button.pack(side=tk.RIGHT, padx=5)

    def populate_dropdown(self):
        script_dir = os.path.join(os.path.dirname(sys.executable), 'scripts')
        if os.path.exists(script_dir):
            script_dir = 'scripts/'
            # List all .py files in the 'scripts/' directory
            scripts = [file for file in os.listdir(script_dir) if file.endswith('.py')]
            self.dropdown['values'] = scripts
            if scripts:
                self.script_var.set(scripts[0])  # Set default selection

    def execute_script(self):
        script_name = self.script_var.get()
        if script_name:
            script_path = os.path.join('scripts', script_name)
            try:
                # Execute the script
                subprocess.run(['python', script_path], check=True)
                print(f"Script {script_name} executed successfully.")
            except subprocess.CalledProcessError as e:
                print(f"An error occurred while executing {script_name}: {e}")

class ToolTip(object):
    def __init__(self, widget, text=None, plot_data=None, voltage_var=None, current_var=None, messages_frame=None):
        self.widget = widget
        self.text = text
        self.plot_data = plot_data
        self.voltage_var = voltage_var
        self.current_var = current_var
        self.messages_frame = messages_frame
        self.widget.bind("<Enter>", self.enter)
        self.widget.bind("<Leave>", self.leave)
        self.tip_window = None

    def enter(self, event=None):
        self.show_tip()

    def leave(self, event=None):
        self.hide_tip()

    def show_tip(self):
        x, y, _cx, cy = self.widget.bbox("insert")
        x += self.widget.winfo_rootx() + 25
        y += self.widget.winfo_rooty() + 25
        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        
        if self.plot_data:
            fig, ax = plt.subplots(figsize=(2, 1.25))
            fig.patch.set_facecolor('#ffffe0')
            x_data, y_data = zip(*self.plot_data)
            ax.plot(x_data, y_data)
            ax.set_facecolor('#ffffe0')
            ax.set_xlabel('Heater Current (A)', fontsize=8)
            ax.set_ylabel('Heater Voltage (V)', fontsize=8)
            ax.tick_params(axis='both', which='major', labelsize=6)
            fig.tight_layout(pad=0.1)
            canvas = FigureCanvasTkAgg(fig, master=tw)
            canvas.draw()
            canvas.get_tk_widget().pack()

            # Close the figure when tooltip is closed to manage memory
            self.tip_window.bind("<Destroy>", lambda e, fig=fig: plt.close(fig))

            # Add vertical and horizontal lines if values are provided
            if self.voltage_var and self.current_var:

                try:
                    voltage = float(self.voltage_var.get().replace(' V', ''))
                    current = float(self.current_var.get().replace(' A', ''))
                    ax.axvline(voltage, color='red', linestyle='--')
                    ax.axhline(current, color='red', linestyle='--')
                except ValueError as e:
                    if self.messages_frame and hasattr(self.messages_frame, 'log_message'):
                        self.messages_frame.log_message(f"Error parsing tooltip values: {str(e)}")
        else:
            label = tk.Label(tw, text=self.text, justify='left',
                             background="#ffffe0", relief='solid', borderwidth=1,
                             font=("tahoma", "8", "normal"))
            label.pack(ipadx=1)

    def hide_tip(self):
        if self.tip_window:
            self.tip_window.destroy()
            self.tip_window = None

class MachineStatus():
     
    MACHINE_STATUS = {
        'Machine Status': None,
        'Script Status' : None,
        'Environment Pass': None,
        'Interlocks Pass': None,
        'High Voltage Permitted': None, 
        'Solenoids Pass': None,
        'Beam Extraction': None,
        'Cathode Heathing': None,
        'Focus Voltage': None,
        'Shield Voltage': None,
        'Target Voltage': None,
        'Preparing Beamlines': None,
        'Beamlines Ready': None,
        'Running Experiment': None,
     }

    def __init__(self, parent):
        self.parent = parent
        self.status_labels = {}  # Store labels for updates
        self.setup_gui()

    def setup_gui(self):
        """Setup the GUI for the Machine Status Panel"""
        self.machine_status_frame = tk.Frame(self.parent, bg="#dbd9d9")
        self.machine_status_frame.pack(fill=tk.BOTH, expand=True)

        # Configure columns for each individual machine status
        num_columns = len(self.MACHINE_STATUS)
        for i in range(num_columns):
            self.machine_status_frame.grid_columnconfigure(i * 2, weight=1)  # Status box
            self.machine_status_frame.grid_columnconfigure(i * 2 + 1, weight=0)  # Thin separator line
        
        for i, (name, _) in enumerate(self.MACHINE_STATUS.items()):
            bg_color = "black" if name == "Machine Status" else "#dbd9d9"
            fg_color = "white" if name == "Machine Status" else "black"

            label = tk.Label(
                self.machine_status_frame, text=name, anchor="w", padx=5,
                bg=bg_color, fg=fg_color, width=12, height=2,
                wraplength=80, justify="left"
            )
            label.grid(row=0, column=i * 2, sticky='ew')

            self.status_labels[name] = label

            # Add a **very thin** black separator frame (1px wide)
            if i < len(self.MACHINE_STATUS) - 1:
                separator = tk.Frame(self.machine_status_frame, bg="black", width=1)  # 1px width black separator
                separator.grid(row=0, column=i * 2 + 1, sticky="ns")

    def update_status(self, status_dict=None):
        """
        Update the status of each machine indicator.
        :param status_dict: Dictionary with status names and their boolean state.
        """
        if status_dict is None:
            status_dict = self.MACHINE_STATUS

        def update_labels():
            for name, is_active in status_dict.items():
                if name in self.status_labels and name != "Machine Status":  # Don't change main label
                    new_color = "#57cce7" if is_active else "#dbd9d9"
                    self.status_labels[name].config(bg=new_color)

        self.parent.after(500, update_labels)