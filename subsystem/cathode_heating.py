# subsystem.py
import tkinter as tk
from tkinter import ttk
import datetime
import random
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.pyplot as plt
from matplotlib.dates import DateFormatter
from instrumentctl.ES440_cathode import ES440_cathode
from utils import ToolTip

class CathodeHeatingSubsystem:
    MAX_POINTS = 20  # Maximum number of points to display on the plot
    OVERTEMP_THRESHOLD = 200.0 # Overtemperature threshold in °C
    
    def __init__(self, parent, messages_frame=None):
        self.parent = parent
        self.ideal_cathode_emission_currents = [0.0 for _ in range(3)]
        self.predicted_grid_current_vars = [tk.StringVar(value='0.0') for _ in range(3)]
        self.predicted_heater_current_vars = [tk.StringVar(value='0.0') for _ in range(3)]
        self.heater_voltage_vars = [tk.StringVar(value='0.0') for _ in range(3)]
        self.e_beam_current_vars = [tk.StringVar(value='0.0') for _ in range(3)]
        self.target_current_vars = [tk.StringVar(value='0.0') for _ in range(3)]
        self.grid_current_vars = [tk.StringVar(value='0.0') for _ in range(3)]
        self.temperature_vars = [tk.StringVar(value='0.0') for _ in range(3)]
        self.overtemp_status_vars = [tk.StringVar(value='Normal') for _ in range(3)]
        self.toggle_states = [False for _ in range(3)]
        self.toggle_buttons = []
        self.time_data = [[] for _ in range(3)]
        self.temperature_data = [[] for _ in range(3)]
        self.messages_frame = messages_frame
        self.init_cathode_model()
        self.setup_gui()
        self.update_data()

    def setup_gui(self):
        cathode_labels = ['A', 'B', 'C']
        style = ttk.Style()
        style.configure('Flat.TButton', padding=(0, 0, 0, 0), relief='flat', borderwidth=0)
        style.configure('Bold.TLabel', font=('Helvetica', 10, 'bold'))
        style.configure('RightAlign.TLabel', font=('Helvetica', 9), anchor='e')

        # Load toggle images
        self.toggle_on_image = tk.PhotoImage(file="media/toggle_on.png")
        self.toggle_off_image = tk.PhotoImage(file="media/toggle_off.png")

        # Create main frame
        self.main_frame = ttk.Frame(self.parent)
        self.main_frame.pack(fill='both', expand=True)

        # Create a canvas and scrollbar for scrolling
        self.canvas = tk.Canvas(self.main_frame)
        self.scrollbar = ttk.Scrollbar(self.main_frame, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        # Pack the canvas and scrollbar
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        # Create a frame inside the canvas
        self.scrollable_frame = ttk.Frame(self.canvas)
        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(
                scrollregion=self.canvas.bbox("all")
            )
        )

        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")

        # Create frames for each cathode/power supply pair
        self.cathode_frames = []
        heater_labels = ['Heater A output:', 'Heater B output:', 'Heater C output:']
        for i in range(3):
            frame = ttk.LabelFrame(self.scrollable_frame, text=f'Cathode {cathode_labels[i]}', padding=(10, 5))
            frame.grid(row=0, column=i, padx=5, pady=0.1, sticky='nsew')
            self.cathode_frames.append(frame)

            # Create voltage, current, and power labels
            set_target_label = ttk.Label(frame, text='Set Target Current (mA):', style='RightAlign.TLabel')
            set_target_label.grid(row=0, column=0, sticky='e')
            ToolTip(set_target_label, "Target current is predicted to be 72% of cathode emission current")

            entry_field = ttk.Entry(frame, width=7)
            entry_field.grid(row=0, column=1, sticky='w')
            set_button = ttk.Button(frame, text="Set", width=4, command=lambda i=i, entry_field=entry_field: self.set_target_current(i, entry_field))
            set_button.grid(row=0, column=1, sticky='e')

            set_grid_label = ttk.Label(frame, text='Pred Grid Current (mA):', style='RightAlign.TLabel')
            set_grid_label.grid(row=1, column=0, sticky='e')
            ToolTip(set_grid_label, "Grid expected to intercept 28% of cathode emission current")
            ttk.Label(frame, textvariable=self.predicted_grid_current_vars[i], style='Bold.TLabel').grid(row=1, column=1, sticky='e')
            
            ttk.Label(frame, text='Pred Heater Current (A):', style='RightAlign.TLabel').grid(row=2, column=0, sticky='e')
            ttk.Label(frame, textvariable=self.predicted_heater_current_vars[i], style='Bold.TLabel').grid(row=2, column=1, sticky='e')

            ttk.Label(frame, text='Set Heater (V):', style='RightAlign.TLabel').grid(row=3, column=0, sticky='e')
            ttk.Label(frame, textvariable=self.heater_voltage_vars[i], style='Bold.TLabel').grid(row=3, column=1, sticky='e')

            # Create entries and display labels
            ttk.Label(frame, text=heater_labels[i], style='Bold.TLabel').grid(row=4, column=0, sticky='w')

            # Create toggle switch
            toggle_button = ttk.Button(frame, image=self.toggle_off_image, style='Flat.TButton', command=lambda i=i: self.toggle_output(i))
            toggle_button.grid(row=4, column=1, columnspan=1)
            self.toggle_buttons.append(toggle_button)

            # Create calculated values labels
            ttk.Label(frame, text='Act Heater (A):', style='RightAlign.TLabel').grid(row=5, column=0, sticky='e')
            ttk.Label(frame, text='Act Heater (V):', style='RightAlign.TLabel').grid(row=6, column=0, sticky='e')
            ttk.Label(frame, text='Act Target (mA):', style='RightAlign.TLabel').grid(row=7, column=0, sticky='e')
            ttk.Label(frame, text='CathTemp Pred (°C):', style='RightAlign.TLabel').grid(row=8, column=0, sticky='e')
            ttk.Label(frame, text='Act ClampTemp (°C):', style='RightAlign.TLabel').grid(row=9, column=0, sticky='e')

            # Create entries and display labels for calculated values
            ttk.Label(frame, textvariable=self.e_beam_current_vars[i], style='Bold.TLabel').grid(row=5, column=1, sticky='e')
            ttk.Label(frame, textvariable=self.target_current_vars[i], style='Bold.TLabel').grid(row=6, column=1, sticky='e')
            ttk.Label(frame, textvariable=self.grid_current_vars[i], style='Bold.TLabel').grid(row=7, column=1, sticky='e')
            ttk.Label(frame, textvariable=self.temperature_vars[i], style='Bold.TLabel').grid(row=8, column=1, sticky='e')
            ttk.Label(frame, textvariable=self.overtemp_status_vars[i], style='Bold.TLabel').grid(row=9, column=1, sticky='e')

            # Create plot for each cathode
            fig, ax = plt.subplots(figsize=(2.8, 1.3))
            line, = ax.plot([], [])
            self.temperature_data[i].append(line)
            ax.set_xlabel('Time', fontsize=8)
            ax.set_ylabel('Temp (°C)', fontsize=8)
            ax.xaxis.set_major_formatter(DateFormatter('%H:%M:%S'))
            ax.tick_params(axis='x', labelsize=6)
            ax.tick_params(axis='y', labelsize=6)
            fig.tight_layout(pad=0.01)
            fig.subplots_adjust(left=0.14, right=0.99, top=0.99, bottom=0.15)
            canvas = FigureCanvasTkAgg(fig, master=frame)
            canvas.draw()
            canvas.get_tk_widget().grid(row=10, column=0, columnspan=3, pady=0.1)

        self.init_time = datetime.datetime.now()

    def init_cathode_model(self):
        try:
            heater_current = [data[0] for data in ES440_cathode.heater_voltage_current_data]
            heater_voltage = [data[1] for data in ES440_cathode.heater_voltage_current_data]

            self.heater_voltage_model = ES440_cathode(heater_current, heater_voltage)

            heater_current_emission = [data[0] for data in ES440_cathode.heater_current_emission_current_data]
            emission_current = [data[1] for data in ES440_cathode.heater_current_emission_current_data]

            self.emission_current_model = ES440_cathode(heater_current_emission, emission_current)
        except Exception as e:
            self.log_message(f"Failed to initialize cathode models: {str(e)}")

    def read_current_voltage(self):
        # Placeholder method to read current and voltage from power supplies
        return random.uniform(2, 4), random.uniform(0.5, 0.9)
    
    def read_temperature(self):
        # Placeholder method to read temperature from cathodes
        return float(random.uniform(20, 22))  # Ensure this returns a float

    def update_data(self):
        current_time = datetime.datetime.now()
        for i in range(3):
            voltage, current = self.read_current_voltage()
            temperature = self.read_temperature()  # Ensure this returns a float or numeric type
            self.temperature_vars[i].set(f'{temperature:.2f}')  # Ensure temperature is numeric and correctly formatted
            
            # use the set cathode emission currnet if available
            e_beam_current = self.ideal_cathode_emission_currents[i]
            target_current = 0.72 * e_beam_current if e_beam_current > 0 else 0
            grid_current = 0.28 * e_beam_current if e_beam_current > 0 else 0
            self.e_beam_current_vars[i].set(f'{e_beam_current:.2f}')
            self.target_current_vars[i].set(f'{target_current:.2f}')
            self.grid_current_vars[i].set(f'{grid_current:.2f}')

            # Update temperature data for plot
            self.time_data[i].append(current_time)
            temperature_data = list(self.temperature_data[i][0].get_data()[1])
            temperature_data.append(temperature)
            if len(self.time_data[i]) > self.MAX_POINTS:
                self.time_data[i].pop(0)
                temperature_data.pop(0)

            self.temperature_data[i][0].set_data(self.time_data[i], temperature_data)  # Ensure data is set correctly
            
            self.update_plot(i)

            # Check for overtemperature
            if temperature > self.OVERTEMP_THRESHOLD:
                self.overtemp_status_vars[i].set("OVERTEMP!")
                self.log_message(f"Cathode {['A', 'B', 'C'][i]} OVERTEMP!")
            else:
                self.overtemp_status_vars[i].set('OK')

        # Schedule next update
        self.parent.after(500, self.update_data)

    def update_plot(self, index):
        time_data = self.time_data[index]
        temperature_data = self.temperature_data[index][0].get_data()[1]
        self.temperature_data[index][0].set_data(time_data, temperature_data)

        ax = self.temperature_data[index][0].axes
        ax.relim()
        ax.autoscale_view()
        ax.figure.canvas.draw()

    def toggle_output(self, index):
        self.toggle_states[index] = not self.toggle_states[index]
        current_image = self.toggle_on_image if self.toggle_states[index] else self.toggle_off_image
        self.toggle_buttons[index].config(image=current_image)  # Update the correct toggle button's image
        self.log_message(f"Heater {['A', 'B', 'C'][index]} output {'ON' if self.toggle_states[index] else 'OFF'}")

    def set_target_current(self, index, entry_field):
        try:
            target_current_mA = float(entry_field.get())
            ideal_emission_current = target_current_mA / 0.72
            self.log_message(f"Calculated ideal emission current for Cathode {['A', 'B', 'C'][index]}: {ideal_emission_current:.2f}mA")

            # Ensure current is within the data range
            if ideal_emission_current < min(self.emission_current_model.y_data) * 1000:
                self.log_message("Desired emission current is below the minimum range of the model.")
                ideal_emission_current = min(self.emission_current_model.y_data) * 1000
            elif ideal_emission_current > max(self.emission_current_model.y_data) * 1000:
                self.log_message("Desired emission current is above the maximum range of the model.")
                ideal_emission_current = max(self.emission_current_model.y_data) * 1000

            heater_current = self.emission_current_model.interpolate(ideal_emission_current / 1000, inverse=True)
            self.log_message(f"Interpolated heater current for Cathode {['A', 'B', 'C'][index]}: {heater_current:.2f}A")

            heater_voltage = self.heater_voltage_model.interpolate(heater_current)
            self.log_message(f"Interpolated heater voltage for Cathode {['A', 'B', 'C'][index]}: {heater_voltage:.2f}V")

            predicted_grid_current = 0.28 * ideal_emission_current # display in milliamps
            self.predicted_grid_current_vars[index].set(f'{predicted_grid_current:.2f}')
            self.predicted_heater_current_vars[index].set(f'{heater_current:.2f}')
            self.heater_voltage_vars[index].set(f'{heater_voltage:.2f}')

            self.log_message(f"Set ideal cathode emission current for Cathode {['A', 'B', 'C'][index]} to {ideal_emission_current:.2f}mA")
            self.log_message(f"Set Cathode {['A', 'B', 'C'][index]} power supply to {heater_voltage:.2f}V, targetting {heater_current:.2f}A heater current")

        except ValueError:
            self.log_message("Invalid input for target current")
        
    def log_message(self, message):
        if hasattr(self, 'messages_frame') and self.messages_frame:
            self.messages_frame.log_message(message)
        else:
            print(message)
