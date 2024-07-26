# oil_system.py
import tkinter as tk
from tkinter import font as tkFont
from tkdial import Meter
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize

class OilSubsystem:
    def __init__(self, parent, logger=None):
        self.parent = parent
        self.logger = logger
        self.setup_gui()

    def setup_gui(self):
        self.frame = tk.Frame(self.parent)
        self.frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Frame for the temperature gauge
        temp_frame = tk.Frame(self.frame, width=90)
        temp_frame.pack(side=tk.LEFT, fill=tk.Y, expand=False)

        # Create a vertical temperature gauge
        self.fig, self.ax = plt.subplots(figsize=(0.8, 6))  # Adjust size for vertical layout
        self.temperature = 50  # Initial temperature
        self.bar = plt.bar(1, self.temperature, width=0.4)
        self.ax.set_ylim(0, 100)
        self.ax.set_xlim(0.5, 1.5)
        self.ax.set_xticks([])
        self.ax.set_yticks(range(0, 101, 20))
        self.ax.set_ylabel('', fontsize=10)
        self.ax.set_title("Oil Temp [C]", fontsize=8)
        self.fig.subplots_adjust(left=0.45, right=0.65, top=0.9, bottom=0.1)

        # Color mapping for temperature ranges
        norm = Normalize(vmin=20, vmax=100)
        cmap = plt.get_cmap('coolwarm')
        self.bar[0].set_color(cmap(norm(self.temperature)))

        self.canvas = FigureCanvasTkAgg(self.fig, master=temp_frame)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(side=tk.TOP, padx=15, fill=tk.BOTH, expand=True)

        # Frame for the oil pressure dial
        dial_frame = tk.Frame(self.frame)
        dial_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Create and configure the dial
        self.oil_dial = Meter(
            self.frame, 
            start=0,             # Start value of the meter
            end=10,              # End value of the meter
            radius=150,          # Radius of the dial
            width=300,           # Width of the widget
            height=200,          # Height of the widget
            start_angle=180,     # Start angle for the half-circle
            end_angle=-180,      # End angle for the half-circle (full sweep of 180 degrees)
            text=" Oil Press", # Text displayed on the dial
            text_color="black",  # Color of the text
            major_divisions=10,  # Major divisions in the dial
            minor_divisions=1,   # Minor divisions between major divisions
            scale_color="black", # Color of the scale markings
            needle_color="red",  # Color of the needle
            bg='white',          # Background color
            fg='light grey',      # Foreground color of the dial face
            text_font=tkFont.Font(family="Helvetica", size=8, weight="bold")
        )
        self.oil_dial.pack(padx=1, pady=5)

    def update_oil_pressure(self, new_pressure):
        """Update the dial to reflect new oil pressure readings."""
        if 0 <= new_pressure <= 10:  # Ensure the value is within the valid range
            self.oil_dial.set(new_pressure)
        else:
            print("Received out-of-range oil pressure value:", new_pressure)

    def update_oil_temperature(self, new_temperature):
        """Update the temperature gauge to reflect new oil temperature readings."""
        self.temperature_bar[0].set_width(new_temperature)
        self.bar[0].set_height(self.temperature)
        norm = Normalize(vmin=20, vmax=100)
        cmap = plt.get_cmap('afmhot')
        self.bar[0].set_color(cmap(norm(self.temperature)))
        self.canvas.draw()

    def read_sensor_data(self):
        """Simulate reading from a sensor."""
        # TODO: Implement this
        import random
        new_pressure = random.randint(0, 10)  # Random pressure value for demonstration
        new_temperature = random.randint(50, 90)
        self.update_oil_temperature(new_temperature)
        self.update_oil_pressure(new_pressure)

        #self.canvas.draw()
        self.parent.after(500, self.read_sensor_data)  # Schedule the update

