# subsystem.py
import tkinter as tk
import serial
import threading
import random
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize

class VTRXSubsystem:
    def __init__(self, parent, serial_port='COM7', baud_rate=9600):
        self.parent = parent
        self.serial_port = serial_port
        self.baud_rate = baud_rate
        self.x_data = []
        self.y_data = []
        self.labels = []

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
                data_parts = data.split(';')
                if len(data_parts) == 9:
                    try:
                        pressure = float(data_parts[0])
                        self.x_data.append(self.x_data[-1] + 1 if self.x_data else 0)
                        self.y_data.append(pressure)
                        self.update_plot()
                    except ValueError:
                        continue

                    self.label_pressure.config(text=f"Pressure: {pressure} mbar")
                    for i, val in enumerate(data_parts[1:], start=1):
                        self.labels[i].config(text=f"{'ON' if val == '1' else 'OFF'}")

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
        # Set up matplotlib figure and axes
        self.fig, self.ax = plt.subplots()
        self.line, = self.ax.plot(self.x_data, self.y_data, 'r-')
        self.ax.set_xlabel('Time')
        self.ax.set_ylabel('Pressure [mbar]')
        self.ax.set_title('Live Pressure Data')
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.parent)
        self.canvas.draw()
        self.canvas_widget = self.canvas.get_tk_widget()
        self.canvas_widget.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # Set up pressure label
        self.label_pressure = tk.Label(self.parent, text="Waiting for pressure data...")
        self.label_pressure.pack(pady=20)

        # Set up labels for each switch
        switch_labels = [
            "Pumps Power On", "Turbo Rotor On", "Turbo Vent Open",
            "Pressure Gauge Power On", "Turbo Gate Valve Open",
            "Argon Gate Valve Closed", "Argon Gate Valve Closed",
            "Argon Gate Valve Open"
        ]

        self.labels = [self.label_pressure]
        for switch in switch_labels:
            label = tk.Label(self.parent, text=f"{switch}: Waiting for data...")
            label.pack()
            self.labels.append(label)

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
            ax.set_title(name)
            ax.set_ylim(0, 100)
            bar = ax.bar(name, self.temperatures[name], width=bar_width)
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
            offset = 15 if 'Solenoid' in name else 0
            new_temp = random.uniform(60 + offset, 70 + offset)
            self.temperatures[name] = new_temp
            self.bars[i][0].set_height(new_temp)

            # Update the color of the bar based on the temperature
            self.bars[i][0].set_color(self.get_color(new_temp))

        self.canvas.draw()
        self.parent.after(1000, self.update_temperatures)