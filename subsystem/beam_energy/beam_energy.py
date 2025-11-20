import tkinter as tk
from tkinter import ttk
import threading
import time
from instrumentctl.knob_box.knob_box_modbus import KnobBoxModbus
from utils import LogLevel
import tkinter.messagebox as messagebox



class BeamEnergySubsystem:
    """
    Manages the beam energy system with four main power supplies:
    - +80kV Glassman (interlock only)
    - +1kV Matsusada
    - -1kV Matsusada 
    - +3kV Bertran
    - +20kV Bertran
    """

    displayFont = "Arial"

    def __init__(self, parent_frame, com_ports, logger=None):
        """
        Initialize the Beam Energy subsystem interface.
        
        Args:
            parent_frame: The tkinter frame where this subsystem will be displayed
            logger: Logger instance for system messages
        """
        self.parent_frame = parent_frame
        self.com_ports = com_ports
        self.logger = logger

        self.knob_box_controller = None
        self.knob_box_connected = False
        
        # Main power supply configurations
        self.power_supplies = [
            {"name": "+1kV Matsusada PS", "type": "matsusada", "voltage": 1000},
            {"name": "-1kV Matsusada PS", "type": "matsusada", "voltage": -1000},
            {"name": "+3kV Bertran PS", "type": "bertran", "voltage": 3000},
            {"name": "+20kV Bertran PS", "type": "bertran", "voltage": 20000},
        ]

        # Global data storing each power supply's latest readings
        self.set_voltages = [tk.StringVar(value="-- V") for _ in range(len(self.power_supplies))]
        self.actual_voltages = [tk.StringVar(value="-- V") for _ in range(len(self.power_supplies))]
        self.actual_currents = [tk.StringVar(value="-- mA") for _ in range(len(self.power_supplies))]
        self.output_status = [tk.StringVar(value="OFF") for _ in range(len(self.power_supplies))]
        self.connection_status_vars = [tk.StringVar(value="DISCONNECTED") for _ in range(len(self.power_supplies))]
        self.glassman_interlock_var = tk.StringVar(value="ACTIVE")
        self.arm_beams_var = tk.StringVar(value="UNARMED")
        self.ccs_power_var = tk.StringVar(value="OFF")
        self.logic_comms_color = tk.StringVar(value="red")  # red=Disconnected, blue=Connected
        self.interlocks_color = tk.StringVar(value="red")   # red=Fault, green=All Good

        self.overcurrent_flags = [False for _ in self.power_supplies]

        self.ui_elements = []  # To hold references to UI elements for updates

        self.data_lock = threading.Lock()
        self.stop_polling = threading.Event()
        self.poll_thread = None

        self.power_supply_instances = []  # List of KnobBoxPowerSupply instances
        self.setup_ui()
        # self.initialize_power_supplies()
        self.initialize_knob_box_modbus()
        self.update_readings()
        
    def setup_ui(self):
        """Create the user interface with four vertical boxes for power supplies."""
        # Main container frame
        main_frame = ttk.Frame(self.parent_frame, padding="2")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Initialize ui_elements list, one for each power supply
        self.ui_elements = [None] * len(self.power_supplies)  
                
        # Power supplies container frame
        ps_container = ttk.Frame(main_frame)
        ps_container.pack(fill=tk.BOTH, expand=True)
        
        # Create four vertical boxes arranged horizontally
        self.ps_frames = []

        for i, ps_config in enumerate(self.power_supplies): # Exclude Glassman
            # Individual power supply frame
            ps_frame = ttk.LabelFrame(
                ps_container, 
                text=ps_config["name"], 
                padding="5",
                labelanchor="n"  # Center the title at the top
            )
            ps_frame.grid(row=0, column=i, sticky="nsew", padx=3, pady=3)
            
            # Configure grid weights for responsive layout
            ps_container.grid_columnconfigure(i, weight=1)

            self.ps_frames.append(ps_frame)
            self.create_power_supply_displays(ps_frame, ps_config, i)
        
        # Configure main grid
        ps_container.grid_rowconfigure(0, weight=1)

        # Right panel for status indicators
        right_panel = ttk.Frame(ps_container)
        right_panel.grid(row=0, column=len(self.ps_frames)+1, sticky="ns", padx=(10,0))
        self.create_indicators(right_panel)

    def create_indicator_circle(self, parent, color="gray"):
        """Helper function, used to create indicators for system status panel."""
        canvas = tk.Canvas(parent, width=16, height=16, highlightthickness=0)
        oval = canvas.create_oval(2, 2, 14, 14, fill=color, outline="")
        return canvas, oval

    def create_indicators(self, parent_frame):
        """
        Create a vertical list of indicators on the right side of power supply displays:
            Arms Beams Status (Armed/Unarmed)
            CCS Power Status (On/Off)
            +80kV Interlock Status (Active/Bypassed)
            Logic Comms (Connected/Disconnected)
            Interlocks: All Good/Fault
        """
        panel = ttk.LabelFrame(parent_frame, text="System Status", padding=5)
        panel.pack(fill=tk.Y, anchor=tk.N)

        def add_row(label_text, var=None, color_var=None):
            row = ttk.Frame(panel)
            row.pack(fill=tk.X, pady=2)

            ttk.Label(row, text=label_text, font=("Segoe UI", 9)).pack(side=tk.LEFT)

            if var:
                ttk.Label(row, textvariable=var, font=("Segoe UI", 9, "bold")).pack(side=tk.RIGHT)

            if color_var:
                canvas, oval = self.create_indicator_circle(row)
                canvas.pack(side=tk.RIGHT, padx=4)

                # Store reference for later color updates
                if not hasattr(self, "indicator_circles"):
                    self.indicator_circles = []
                self.indicator_circles.append((canvas, oval, color_var))

        add_row("Arm Beams:",      self.arm_beams_var)
        add_row("CCS Power:",      self.ccs_power_var)
        add_row("+80kV Interlock:",     self.glassman_interlock_var)
        add_row("Logic Comms:",    color_var=self.logic_comms_color)
        add_row("Interlocks:",     color_var=self.interlocks_color)        

    def create_power_supply_displays(self, frame, ps_config, index):
        """
        Create read-only displays for individual power supply.
        
        Args:
            frame: Frame to contain the displays
            ps_config: Power supply configuration dict
            index: Index of the power supply (1-4, since 0 is Glassman)
        """
        # Connection status indicator (at top)
        connection_frame = ttk.Frame(frame)
        connection_frame.pack(fill=tk.X, pady=(0, 5))
        
        connection_label = ttk.Label(
            connection_frame, 
            textvariable=self.connection_status_vars[index], 
            foreground="red",
            font=(self.displayFont, 8, "bold"),
            background="white",
            relief="sunken",
            width=15,
            anchor=tk.CENTER
        )
        connection_label.pack(anchor=tk.CENTER)
        
        # Output status indicator
        status_frame = ttk.Frame(frame)
        status_frame.pack(fill=tk.X, pady=(0, 8))
        
        # Create a centered layout with consistent spacing
        output_label = ttk.Label(status_frame, text="Output:", font=("Segoe UI", 8))
        output_label.pack(anchor=tk.CENTER)
        
        status_label = ttk.Label(
            status_frame, 
            textvariable=self.output_status[index], 
            foreground="red",
            font=(self.displayFont, 9, "bold"),
            background="white",
            relief="sunken",
            width=5,
            anchor=tk.CENTER
        )
        status_label.pack(anchor=tk.CENTER, pady=(2, 0))
        
        # Set voltage display
        setpoint_frame = ttk.Frame(frame)
        setpoint_frame.pack(fill=tk.X, pady=(0, 5))
        
        ttk.Label(setpoint_frame, text="Set Voltage:", font=("Segoe UI", 8)).pack(anchor=tk.W)
        setpoint_display = ttk.Label(
            setpoint_frame, 
            textvariable=self.set_voltages[index], 
            font=(self.displayFont, 12, "bold"),
            background="lightgray",
            relief="sunken",
            width=10,
            anchor=tk.CENTER
        )
        setpoint_display.pack(fill=tk.X, pady=(1, 0))
        
        # Actual voltage display
        voltage_frame = ttk.Frame(frame)
        voltage_frame.pack(fill=tk.X, pady=(0, 5))
        
        ttk.Label(voltage_frame, text="Actual Voltage:", font=("Segoe UI", 8)).pack(anchor=tk.W)
        voltage_display = ttk.Label(
            voltage_frame, 
            textvariable=self.actual_voltages[index], 
            font=(self.displayFont, 12, "bold"),
            background="white",
            relief="sunken",
            width=10,
            anchor=tk.CENTER
        )
        voltage_display.pack(fill=tk.X, pady=(1, 0))
        
        # Actual current display
        current_frame = ttk.Frame(frame)
        current_frame.pack(fill=tk.X, pady=(0, 5))
        
        ttk.Label(current_frame, text="Actual Current:", font=("Segoe UI", 8)).pack(anchor=tk.W)
        current_display = ttk.Label(
            current_frame, 
            textvariable=self.actual_currents[index], 
            font=(self.displayFont, 12, "bold"),
            background="white",
            relief="sunken",
            width=10,
            anchor=tk.CENTER
        )
        current_display.pack(fill=tk.X, pady=(1, 0))
        
        # Store references for later use
        if not hasattr(self, 'ui_elements'):
            self.ui_elements = []

        self.ui_elements[index] = {
            'connection_label': connection_label, # label and display variables used for updating colors
            'status_label': status_label,
            'setpoint_display': setpoint_display,
            'voltage_display': voltage_display,
            'current_display': current_display
        }

    def initialize_knob_box_modbus(self):
        """
        Initialize the hardware communication with KnobBox power supplies using Modbus protocol.
        Starts polling thread for data collection.
        Returns True if successful, False otherwise.
        """
        port = self.com_ports.get('KnobBox', None)
        if not port:
            return False
        
        # Ensure any existing controller is properly closed
        if hasattr(self, 'knob_box_controller') and self.knob_box_controller:
            self.knob_box_controller.close()
            time.sleep(.2)
        
        try:
            knob_box_modbus = KnobBoxModbus(port=port, logger=self.logger)
            if knob_box_modbus.connect():  # Initializes connection with RS-485 in KnobBoxModbus class
                self.knob_box_controller = knob_box_modbus
                self.knob_box_connected = True
                return True
            else:
                self.knob_box_connected = False
                return False
        except Exception as e:
            self.knob_box_connected = False
            return False
        
    def attempt_knob_box_reconnect(self):
        """Attempt to reconnect to the KnobBox Modbus controller."""
        if self.knob_box_controller:
            self.knob_box_controller.close()
            time.sleep(.2)  # Brief pause before reconnecting
        return self.initialize_knob_box_modbus()
    
    def update_connection_status(self, index, connected):
        """Update connection status indicators."""
        if index < len(self.ui_elements):
            if connected:
                self.connection_status_vars[index].set("CONNECTED")
                self.ui_elements[index]['connection_label'].config(foreground="green")
            else:
                self.connection_status_vars[index].set("DISCONNECTED")
                self.ui_elements[index]['connection_label'].config(foreground="red")
    
    def update_output_status(self, index, status):
        """Update output status indicators."""
        if index < len(self.ui_elements):
            if status:
                self.output_status[index].set("ON")
                self.ui_elements[index]['status_label'].config(foreground="green")
            else:
                self.output_status[index].set("OFF")
                self.ui_elements[index]['status_label'].config(foreground="red")

    

    def start_polling_thread(self):
        """Start a background thread to poll power supply data periodically."""
        if self.poll_thread and self.poll_thread.is_alive():
            return  # Polling thread already running
        
        self.stop_polling.clear()
        self.poll_thread = threading.Thread(target=self.polling_loop, daemon=True)
        self.poll_thread.start()

    def polling_loop(self):
        """Background thread function to poll power supply data."""
        while not self.stop_polling.is_set():
            try:
                if self.knob_box_connected and self.knob_box_controller:
                    self.knob_box_controller.poll_all()
                else:
                    self.attempt_knob_box_reconnect()
            except Exception as e:
                self.attempt_knob_box_reconnect()
            time.sleep(.2)  # Polling interval

    def update_readings(self):
        """
        Update voltage and current readings from hardware.
        This method should be called periodically to refresh displays.
        """
        # Update Knob Box data
        try:
            if self.knob_box_connected and self.knob_box_controller:
                knob_box = self.knob_box_controller
            else:
                # KnobBox not connected, set all to default
                for index, _ in enumerate(self.power_supplies):
                    self.set_default_values(index)
                self.attempt_knob_box_reconnect()
            
            # Pull data snapshot from KnobBox controller
            data_snapshot = knob_box.get_data_snapshot()
            for index, _ in enumerate(self.power_supplies):
                
                # Unit IDs start at one. We may want to create a mapping later when we have the final values
                unit_id = index
                data = data_snapshot.get(unit_id, None)
                
                if data:
                    v_set = data.get('set_voltage_V', None)
                    v_read = data.get('actual_voltage_V', None)
                    i_read = data.get('actual_current_mA', None)
                    overcurrent = data.get('overcurrent', None)
                    mode_val = data.get('mode', 255)
                    # Map mode integer to human-readable label for logging
                    mode_map = {0: "3kV Bertan", 1: "20kV Bertan", 2: "1kV Matsusada", 255: "error"}
                    mode_text = mode_map.get(mode_val, str(mode_val))

                    # Overcurrent Handling:
                    if overcurrent:
                        # Log once when overcurrent condition is first detected
                        if not self.overcurrent_flags[index]:
                            self.log(f"Overcurrent detected on Power Supply {unit_id}!", LogLevel.WARNING)
                            
                            messagebox.showwarning(
                                title="Overcurrent Warning",
                                message=f"Overcurrent detected on Power Supply {unit_id}.\n"
                                        f"The hardware system has taken protective action.\n\n"
                                        f"Press OK to acknowledge.")

                        self.overcurrent_flags[index] = True

                    else:
                        # Clear flag and log recovery from overcurrent state
                        if self.overcurrent_flags[index]:
                            self.log(f"Power Supply {unit_id} recovered from overcurrent.", LogLevel.INFO)
                        self.overcurrent_flags[index] = False

                    # print structured DEBUG log line per unit when measurements are present
                    if (v_read is not None) and (i_read is not None):
                        try:
                            voltage_V = float(v_read)
                            current_A = float(i_read) / 1000.0  # mA -> A
                            ps_number = unit_id  # keep 1-5 numbering aligned with UNIT_IDS
                            self.log(
                                f"Power supply {ps_number} readings - Voltage: {voltage_V:.3f}V, Current: {current_A:.6f}A, Mode: {mode_text}",
                                LogLevel.DEBUG
                            )
                        except Exception:
                            pass # If conversion fails, skip logging

                    self.update_connection_status(index, True)
                else:
                    self.set_default_values(index)

                # Update display values if data is valid
                if v_set is not None:
                    self.set_voltages[index].set(f"{v_set:.1f} V")
                else:
                    self.set_voltages[index].set("-- V")

                if v_read is not None:
                    self.actual_voltages[index].set(f"{v_read:.1f} V")
                else:
                    self.actual_voltages[index].set("-- V")

                if i_read is not None:
                    self.actual_currents[index].set(f"{i_read:.3f} mA")
                else:
                    self.actual_currents[index].set("-- mA")

        except Exception as e:  
            self.log(f"Error updating readings: {str(e)}", LogLevel.ERROR)
            for index, _ in enumerate(self.power_supplies): 
                self.set_default_values(index)
            self.attempt_knob_box_reconnect()
            
        
        # Schedule next update after 500 ms
        self.after_id = self.parent_frame.after(500, self.update_readings) 

    def cancel_updates(self):
        """Cancel scheduled updates when closing the application."""
        if hasattr(self, 'after_id'):
            self.parent_frame.after_cancel(self.after_id)

    def set_default_values(self, index):
        """Set display values to default '--'."""
        self.set_voltages[index].set("-- V")
        self.actual_voltages[index].set("-- V")
        self.actual_currents[index].set("-- A")
        self.update_connection_status(index, False)
        self.update_output_status(index, False)

    def update_com_ports(self, new_com_ports):
        """Update COM port assignments and reinitialize power supplies."""
        new_port = new_com_ports.get('KnobBox', None)
        if not new_port:
            return False
        
        if new_port == self.com_ports.get('KnobBox', None):
            return True  # No change
        
        self.com_ports = new_port

        # Close existing connections
        self.close_com_ports()
        
        # Reinitialize with new ports
        self.initialize_knob_box_modbus()

    def close_com_ports(self):
        """Close any open communication ports and stop all polling threads."""
        # if self.logger:
        #     self.logger.info("Beam Energy subsystem: Closing communication ports")
        if self.knob_box_controller:
            self.knob_box_controller.disconnect()
            self.knob_box_controller = None
            self.knob_box_connected = False

    def close(self):
        """Close the subsystem and clean up resources."""
        self.stop_polling().set()
        if self.poll_thread and self.poll_thread.is_alive():
            self.poll_thread.join(timeout=2)
            self.poll_thread = None

        self.cancel_updates()
        self.close_com_ports()

    def log(self, message, level=LogLevel.INFO):
        """Log a message with the specified level if a logger is configured."""
        if self.logger:
            self.logger.log(message, level)
        else:
            print(f"{level.name}: {message}")

# TODO: Add output status, interlock status updating when supported by firmware
# TODO: Update for finalized unit ID assignments and expected voltage/current units
# TODO: Add function to update indicators in system status panel