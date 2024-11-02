# visualization_gas_control.py
import tkinter as tk
from tkinter import ttk
import instrumentctl

class VisualizationGasControlSubsystem:
    def __init__(self, parent, serial_port='COM8', baud_rate=19200, logger=None):
        self.parent = parent
        self.logger = logger
        self.setup_gui()
        
    def setup_gui(self):
        self.notebook = ttk.Notebook(self.parent)
        self.notebook.pack(fill='both', expand=True)

        # Setup Tab
        self.setup_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.setup_tab, text='Setup')

        # Tare Tab
        self.tare_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.tare_tab, text='Tare')

        # Control Tab
        self.control_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.control_tab, text='Control')

        # COMPOSER Tab
        self.composer_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.composer_tab, text='GAS COMPOSER')

        # Misc Tab
        self.misc_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.misc_tab, text='Misc')
