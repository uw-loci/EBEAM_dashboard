# subsystem.py
import tkinter as tk
import serial
import threading
import random
from utils import ApexMassFlowController
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize

class VTRXSubsystem: # TODO: handling lack of pressure response -- reset live plot
    def __init__(self, parent, serial_port='COM7', baud_rate=9600):
        self.parent = parent
        self.serial_port = serial_port
        self.baud_rate = baud_rate
        self.x_data = []
        self.y_data = []

        self.setup_serial()
        self.setup_gui()
        if self.ser is not None:
            self.start_serial_thread()

    def setup_serial(self):
        try:
            self.ser = serial.Serial(self.serial_port, self.baud_rate)
        except serial.SerialException as e:
            print(f"Error opening serial port {self.serial_port}: {e}")
            self.ser = None

    def read_serial(self):
        while True:
            data = self.ser.readline().decode('utf-8').strip()
            if data:
                self.handle_serial_data(data)

    def handle_serial_data(self, data):
        data_parts = data.split(';')
        if len(data_parts) == 9:
            try:
                pressure = float(data_parts[0])
                switch_states = list(map(int, data_parts[1:]))
                self.parent.after(0, lambda: self.update_gui(pressure, switch_states))
            except ValueError:
                pass  # Skip update if conversion fails

    def update_gui(self, pressure, switch_states):
        self.label_pressure.config(text=f"Press: {pressure} mbar")
        for idx, state in enumerate(switch_states):
            label = self.labels[idx]
            label.config(image=self.indicators[state])

        # Update plot
        self.x_data.append(self.x_data[-1] + 1 if self.x_data else 0)  # Increment x value
        self.y_data.append(pressure)  # Append new pressure value
        self.update_plot()

    def update_plot(self):
        self.line.set_data(self.x_data, self.y_data)
        self.ax.relim()
        self.ax.autoscale_view()
        self.canvas.draw()

    def start_serial_thread(self):
        thread = threading.Thread(target=self.read_serial)
        thread.daemon = True
        thread.start()

    def setup_gui(self):
        layout_frame = tk.Frame(self.parent)
        layout_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Formatting status indicators
        switches_frame = tk.Frame(layout_frame, width=150)
        switches_frame.pack(side=tk.LEFT, fill=tk.Y, padx=10) 

        self.indicators = [tk.PhotoImage(file="media/off.png"), tk.PhotoImage(file="media/on.png")]

        # Setup labels for each switch
        switch_labels = [
            "Pumps Power On ", "Turbo Rotor ON ", "Turbo Vent Open ",
            "Pressure Gauge Power On ", "Turbo Gate Valve Open ",
            "Turbo Gate Valve Closed ", "Argon Gate Valve Closed ", "Argon Gate Valve Open "
        ]
        self.labels = []
        label_width = 15
        for switch in switch_labels:
            label = tk.Label(switches_frame, text=switch, image=self.indicators[0], compound='right', anchor='e', width=label_width)
            label.pack(anchor="e", pady=2, fill='x')
            self.labels.append(label)

        # Pressure label setup
        # Increase font size and make it bold
        self.label_pressure = tk.Label(switches_frame, text="Waiting for pressure data...", anchor='e', width=label_width,
                                    font=('Helvetica', 14, 'bold'))
        self.label_pressure.pack(anchor="e", pady=10, fill='x')

        # Plot frame
        plot_frame = tk.Frame(layout_frame)
        plot_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=15) 

        self.fig, self.ax = plt.subplots()
        self.line, = self.ax.plot(self.x_data, self.y_data, 'g-')
        self.ax.set_xlabel('Time')
        self.ax.set_ylabel('Pressure [mbar]')
        self.ax.set_title('Live Pressure Readout')
        self.canvas = FigureCanvasTkAgg(self.fig, master=plot_frame)
        self.canvas.draw()
        self.canvas_widget = self.canvas.get_tk_widget()
        self.canvas_widget.pack(fill=tk.BOTH, expand=True)

class EnvironmentalSubsystem:
    def __init__(self, parent):
        self.parent = parent
        self.thermometers = ['Solenoid 1', 'Solenoid 2', 'Chmbr Bot', 'Chmbr Top', 'Air temp']
        self.temperatures = {name: (random.uniform(60, 90) if 'Solenoid' in name else random.uniform(50, 70)) for name in self.thermometers}

        self.setup_gui()
        self.update_temperatures()

    def setup_gui(self):
        self.fig, self.axs = plt.subplots(1, len(self.thermometers), figsize=(15, 5))
        self.bars = []

        bar_width = 0.5  # Make the bars skinnier

        for ax, name in zip(self.axs, self.thermometers):
            ax.set_title(name, fontsize=6)
            ax.set_ylim(0, 100)
            bar = ax.bar(name, self.temperatures[name], width=bar_width)
            ax.set_xticks([])
            ax.set_xticklabels([])
            self.bars.append(bar)

            # Set the x-axis limits to make sure bars are centered and skinny
            ax.set_xlim(-1, 1)

        self.fig.subplots_adjust(left=0.10, right=0.90, top=0.90, bottom=0.10, wspace=1.0)  # Add padding around the figure
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.parent)
        self.canvas.draw()
        self.canvas_widget = self.canvas.get_tk_widget()
        self.canvas_widget.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

    def get_color(self, temperature):
        norm = Normalize(vmin=20, vmax=100)
        cmap = plt.get_cmap('coolwarm')
        return cmap(norm(temperature))

    def update_temperatures(self):
        for i, name in enumerate(self.thermometers):
            offset = 30 if 'Solenoid' in name else 0
            new_temp = random.uniform(30 + offset, 33 + offset)
            self.temperatures[name] = new_temp
            self.bars[i][0].set_height(new_temp)

            # Update the color of the bar based on the temperature
            self.bars[i][0].set_color(self.get_color(new_temp))

        self.canvas.draw()
        self.parent.after(1000, self.update_temperatures)


class ArgonBleedControlSubsystem:
    def __init__(self, parent, serial_port='COM8', baud_rate=19200):
        self.parent = parent
        self.controller = ApexMassFlowController(serial_port, baud_rate)
        self.setup_gui()

    def configure_controller(self):
        # Open serial connection
        self.controller.open_serial_connection()
        
        # Configure unit ID
        self.controller.configure_unit_id('A', 'B')

        # Close serial connection when done
        self.controller.close_serial_connection()
        
    def setup_gui(self):
        #self.label = tk.Label(self.parent, text="Apex Mass Flow Controller", font=("Helvetica", 12, "bold"))
        #self.label.pack(pady=10)

        # Add "Tare Flow" button
        self.tare_flow_button = tk.Button(self.parent, text="Tare Flow", command=self.tare_flow)
        self.tare_flow_button.pack()

        # Add "Tare Absolute Pressure" button
        self.tare_pressure_button = tk.Button(self.parent, text="Tare Absolute Pressure", command=self.tare_absolute_pressure)
        self.tare_pressure_button.pack()

    def tare_flow(self):
        # Perform taring flow action when "Tare Flow" button is pressed
        self.controller.tare_flow()
        print("Apex MF Ctrl:Taring flow performed successfully.")

        # Update GUI or perform any other necessary actions

    def tare_absolute_pressure(self):
        # Perform taring absolute pressure action when "Tare Absolute Pressure" button is pressed
        self.controller.tare_absolute_pressure()
        print("Apex MF Ctrl:Taring absolute pressure performed successfully.")

        # Update GUI or perform any other necessary actions

    def start_simulation(self):
        # Start a simulation to update the GUI periodically
        self.update_gui()

    def update_gui(self):
        # Update GUI elements with simulated data
        # Replace this with actual functionality
        # For example, updating labels, graphs, etc.
        print("Updating GUI...")

        # Schedule the next update after a delay (in milliseconds)
        self.parent.after(1000, self.update_gui)