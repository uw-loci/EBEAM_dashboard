# visualization_gas_control.py
import tkinter as tk
from tkinter import ttk
import instrumentctl

class VisualizationGasControlSubsystem:
    def __init__(self, parent, serial_port='COM8', baud_rate=19200, messages_frame=None):
        self.parent = parent
        self.controller = instrumentctl.ApexMassFlowController(serial_port, baud_rate, messages_frame=messages_frame)
        self.messages_frame = messages_frame
        self.setup_gui()

    def configure_controller(self): # TODO write this
        # Open serial connection
        self.controller.open_serial_connection()
        
        # Configure unit ID
        self.controller.configure_unit_id('A', 'B')

        # Close serial connection when done
        self.controller.close_serial_connection()
        
    def setup_gui(self):
        self.notebook = ttk.Notebook(self.parent)
        self.notebook.pack(fill='both', expand=True)

        # Setup Tab
        self.setup_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.setup_tab, text='Setup')
        self.setup_setup_tab()

        # Tare Tab
        self.tare_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.tare_tab, text='Tare')
        self.setup_tare_tab()

        # Control Tab
        self.control_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.control_tab, text='Control')
        self.setup_control_tab()

        # COMPOSER Tab
        self.composer_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.composer_tab, text='GAS COMPOSER')
        self.setup_composer_tab()

        # Misc Tab
        self.misc_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.misc_tab, text='Misc')
        self.setup_misc_tab()
    
    def update_gui(self):
            # Schedule the next update after a delay (in milliseconds)
            self.parent.after(500, self.update_gui)

    def tare_flow(self):
        # Perform taring flow action when "Tare Flow" button is pressed
        self.controller.tare_flow()
        self.messages_frame.log_message("Apex MassFlow:Tare flow success.")

        # Update GUI or perform any other necessary actions

    def tare_absolute_pressure(self):
        # Perform taring absolute pressure action when "Tare Absolute Pressure" button is pressed
        self.controller.tare_absolute_pressure()
        self.messages_frame.log_message("Apex MassFlow:Tar abs pressure success.")

    def setup_setup_tab(self):
        ttk.Label(self.setup_tab, text="Apex Mass Flow Controller Setup").grid(row=0, column=0, columnspan=2, padx=10, pady=10)

        # Frame for buttons
        button_frame = ttk.Frame(self.setup_tab)
        button_frame.grid(row=1, column=0, padx=10, pady=5, sticky='n')

        # Frame for dropdown and live data
        input_frame = ttk.Frame(self.setup_tab)
        input_frame.grid(row=1, column=1, padx=1, pady=5, sticky='n')

        # Add buttons to the button frame
        self.unit_id_button = ttk.Button(button_frame, text="Change Unit ID", command=self.set_unit_id)
        self.unit_id_button.pack(padx=5, pady=5, anchor='w')

        self.poll_data_button = ttk.Button(button_frame, text="Poll Live Data Frame", command=self.poll_live_data)
        self.poll_data_button.pack(padx=5, pady=5, anchor='w')

        # Add dropdown and live data text to the input frame
        self.unit_id_var = tk.StringVar()
        self.unit_id_dropdown = ttk.Combobox(input_frame, textvariable=self.unit_id_var, values=[chr(i) for i in range(65, 91)], width=5)  # A-Z
        self.unit_id_dropdown.pack(padx=5, pady=7, anchor='w')

        self.live_data_var = tk.StringVar()
        self.live_data_label = ttk.Label(input_frame, textvariable=self.live_data_var)
        self.live_data_label.pack(padx=5, pady=7, anchor='w')

        # Add button and text entry to set streaming interval
        self.set_interval_button = ttk.Button(button_frame, text="Set Streaming Interval", command=self.set_streaming_interval)
        self.set_interval_button.pack(padx=5, pady=5, anchor='w')

        self.streaming_interval_var = tk.StringVar()
        self.streaming_interval_entry = ttk.Entry(input_frame, textvariable=self.streaming_interval_var, width=10)
        self.streaming_interval_entry.pack(padx=5, pady=7, anchor='w')

    def set_unit_id(self):
        current_id = 'A'  # default ID is 'A'
        new_id = self.unit_id_var.get()
        if new_id:
            self.controller.configure_unit_id(current_id, new_id)
            self.messages_frame.log_message(f"Set new unit ID to {new_id}")

    def poll_live_data(self):
        unit_id = 'A'  # assuming current unit ID is 'A', change as needed
        result = self.controller.poll_live_data_frame(unit_id)
        self.live_data_var.set(result)
        self.messages_frame.log_message(f"Polled live data frame: {result}")

    def set_streaming_interval(self):
        interval = self.streaming_interval_var.get()
        if interval:
            self.controller.set_streaming_interval('A', interval) # Assuming unit ID 'A'
            self.messages_frame.log_message(f"Set streaming interval to {interval} ms")

    def setup_tare_tab(self):
        self.tare_flow_button = tk.Button(self.tare_tab, text="Tare Flow", command=self.tare_flow)
        self.tare_flow_button.pack(padx=10, pady=10)
        
        self.tare_pressure_button = tk.Button(self.tare_tab, text="Tare Absolute Pressure", command=self.tare_absolute_pressure)
        self.tare_pressure_button.pack(padx=10, pady=10)

    def setup_control_tab(self):
        ttk.Label(self.control_tab, text="Control configurations go here").pack(padx=10, pady=10)

    def setup_composer_tab(self):
        ttk.Label(self.composer_tab, text="COMPOSER configurations go here").pack(padx=10, pady=10)

    def setup_misc_tab(self):
        ttk.Label(self.misc_tab, text="Miscellaneous configurations go here").pack(padx=10, pady=10)

    