import tkinter as tk
from tkinter import ttk
import threading
import time
from instrumentctl.glassman_power_supply.glassman import GlassmanPowerSupply
from instrumentctl.knob_box.knob_box_modbus import KnobBoxModbus



class BeamEnergySubsystem:
    """
    Manages the beam energy system with four main power supplies:
    - +80kV Glassman (indicator only)
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

        self.glassman_ps = None
        self.glassman_connected = False
        self.knob_box_controller = None
        self.knob_box_connected = False
        
        # Main power supply configurations
        self.power_supplies = [
            {"name": "+80kV Glassman PS", "type": "glassman", "voltage": 80000},  # Indicator only
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

        self.ui_elements = []  # To hold references to UI elements for updates

        self.data_lock = threading.Lock()
        self.stop_monitoring_event = threading.Event()

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

        # Glassman power supply container
        glassman_container = ttk.Frame(main_frame)
        glassman_container.pack(fill=tk.X, pady=(0, 5))
        self.create_glassman_indicator(glassman_container)
                
        # Power supplies container frame
        ps_container = ttk.Frame(main_frame)
        ps_container.pack(fill=tk.BOTH, expand=True)
        
        # Create four vertical boxes arranged horizontally
        self.ps_frames = []

        for i, ps_config in enumerate(self.power_supplies[1:], 1): # Exclude Glassman
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
        
    def create_glassman_indicator(self, parent_frame):
        """Create a small Glassman power supply output indicator, centered below title."""
        glassman_frame = ttk.LabelFrame(
            parent_frame, 
            text="+80kV Glassman", 
            padding="5",
            labelanchor="n"  # Center the title at the top
        )
        # Center the frame horizontally
        glassman_frame.pack(anchor=tk.CENTER)

        # Combined connection and output status indicator (same line to save vertical space)
        status_frame = ttk.Frame(glassman_frame)
        status_frame.pack(fill=tk.X)
        
        # Connection status (left side)
        self.glassman_connection_label = ttk.Label(
            status_frame,
            textvariable=self.connection_status_vars[-1],  # Last index for Glassman
            foreground="red",
            font=(self.displayFont, 8, "bold"),
            background="white",
            relief="sunken",
            width=15,
            anchor=tk.CENTER
        )
        self.glassman_connection_label.pack(side=tk.LEFT)
        
        # Spacer label for consistent spacing
        ttk.Label(status_frame, text="  ", font=("Segoe UI", 8)).pack(side=tk.LEFT)
        
        # Output status (right side)
        ttk.Label(status_frame, text="Output:", font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=(0, 3))
        self.glassman_status_label = ttk.Label(
            status_frame, 
            textvariable=self.output_status[-1],  # Last index for Glassman
            foreground="red",
            font=(self.displayFont, 9, "bold"),
            background="white",
            relief="sunken",
            width=5,
            anchor=tk.CENTER
        )
        self.glassman_status_label.pack(side=tk.LEFT)

        self.ui_elements[0] = {
            "connection_label": self.glassman_connection_label,
            "status_label": self.glassman_status_label
        }

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
            if knob_box_modbus.start_reading_power_supply_data():
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
    
    def initialize_glassman_ps(self):
        '''Initialize the Glassman power supply communication.'''
        port = self.com_ports.get('Glassman', None)
        if not port:
            return False
        
        # Ensure any existing Glassman instance is properly closed
        if hasattr(self, 'glassman_ps') and self.glassman_ps:
            self.glassman_ps.close()
            time.sleep(.2)

        try:
            glassman_ps = GlassmanPowerSupply(port=port, power_supply_id=0, logger=self.logger)
            if glassman_ps.is_connected():
                self.glassman_ps = glassman_ps
                self.glassman_connected = True
                return True
            else:
                self.glassman_connected = False
                return False
        except Exception as e:
            self.glassman_connected = False
            return False

    def attempt_glassman_reconnect(self):
        """Attempt to reconnect to the Glassman power supply."""
        if self.glassman_ps:
            self.glassman_ps.close()
            time.sleep(.2)  # Brief pause before reconnecting
        return self.initialize_glassman_ps()
    
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

    def update_readings(self):
        """
        Update voltage and current readings from hardware.
        This method should be called periodically to refresh displays.
        """
        # Update Glassman data
        try:
            if self.glassman_connected and self.glassman_ps:
                # TODO: Implement actual data retrieval for Glassman
                data = self.glassman_ps.get_power_supply_data()
            else:
                self.glassman_connected = False
                self.set_default_values(0)
                self.attempt_glassman_reconnect()
        except Exception as e:
            self.glassman_connected = False
            self.set_default_values(0)
            self.attempt_glassman_reconnect()

        # Update Knob Box data
        try:
            if self.knob_box_connected and self.knob_box_controller:
                # Get latest data from KnobBoxModbus
                for index, unit in enumerate(self.knob_box_controller.UNIT_NUMBERS):
                    data = self.knob_box_controller.get_power_supply_data(index)
                        
                    # We use unit number to store data because Glassman is not part of KnobBox and stored at index 0
                    # 0 index is Glassman, so KnobBox units start from index 1
                    with self.data_lock:
                        if data:
                            self.set_voltages[unit].set(f"{data['set_voltage']} V")
                            self.actual_voltages[unit].set(f"{data['actual_voltage']} V")
                            self.actual_currents[unit].set(f"{data['actual_current']} A")
                            self.update_output_status(unit, data['output_status'])
                            self.update_connection_status(unit, True)
                        else:
                            self.set_default_values(unit)
            else:
                # KnobBox not connected, set all to default
                for index in enumerate(self.power_supplies[1:], 1): # Exclude Glassman
                    self.set_default_values(index)
                self.attempt_knob_box_reconnect()

        except Exception as e:  
            for index in enumerate(self.power_supplies[1:], 1): # Exclude Glassman
                self.set_default_values(index)
            self.attempt_knob_box_reconnect()

        self.parent_frame.after(500, self.update_readings)  # Schedule next update after 500 ms

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
        self.stop_monitoring_event.set()

        if self.knob_box_controller:
            self.knob_box_controller.stop_reading()
            self.knob_box_controller = None
            self.knob_box_connected = False

# TODO: Implement output status retrieval in KnobBoxPowerSupply and update_output_status method