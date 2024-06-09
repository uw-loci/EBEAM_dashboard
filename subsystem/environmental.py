
# environmental.py
import tkinter as tk
import random
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize



class EnvironmentalSubsystem:
    def __init__(self, parent, messages_frame=None):
        self.parent = parent
        self.messages_frame = messages_frame
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
            ax.tick_params(axis='y', labelsize=6)
            self.bars.append(bar)

            # Set the x-axis limits to make sure bars are centered and skinny
            ax.set_xlim(-1, 1)

        #self.fig.subplots_adjust(left=0.10, right=0.90, top=0.90, bottom=0.10, wspace=1.0)  # Add padding around the figure
        self.fig.tight_layout()
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
        self.parent.after(500, self.update_temperatures)
