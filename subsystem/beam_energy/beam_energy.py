import tkinter as tk
from tkinter import ttk
import threading
import time
from instrumentctl.knob_box.knob_box import KnobBoxPowerSupply


class BeamEnergySubsystem:
    """
    Manages the beam energy system with four main power supplies:
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
        #self.com_ports = com_ports # temporarily overwrite for testing
        self.com_ports = {
            "+1kV Matsusada": "COM3", 
            "-1kV Matsusada": "COM6", 
            "+3kV Bertran": "COM7", 
            "+20kV Bertran": "COM9",
            # "+80kV Glassman": "COM7"  # Indicator only
        }
        self.logger = logger
        
        # Main power supply configurations
        self.power_supplies = [
            {"name": "+1kV Matsusada", "type": "matsusada", "voltage": 1000},
            {"name": "-1kV Matsusada", "type": "matsusada", "voltage": -1000},
            {"name": "+3kV Bertran", "type": "bertran", "voltage": 3000},
            {"name": "+20kV Bertran", "type": "bertran", "voltage": 20000},
            # {"name": "+80kV Glassman", "type": "glassman", "voltage": 80000}  # Indicator only
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
        self.initialize_power_supplies()
        self.update_readings()
        
    def setup_ui(self):
        """Create the user interface with four vertical boxes for power supplies."""
        # Main container frame
        main_frame = ttk.Frame(self.parent_frame, padding="2")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Glassman power supply container
        # glassman_container = ttk.Frame(main_frame)
        # glassman_container.pack(fill=tk.X, pady=(0, 5))
        # self.create_glassman_indicator(glassman_container)
        
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
        
    # def create_glassman_indicator(self, parent_frame):
    #     """Create a small Glassman power supply output indicator, centered below title."""
    #     glassman_frame = ttk.LabelFrame(
    #         parent_frame, 
    #         text="+80kV Glassman", 
    #         padding="5",
    #         labelanchor="n"  # Center the title at the top
    #     )
    #     # Center the frame horizontally
    #     glassman_frame.pack(anchor=tk.CENTER)

    #     # Combined connection and output status indicator (same line to save vertical space)
    #     status_frame = ttk.Frame(glassman_frame)
    #     status_frame.pack(fill=tk.X)
        
    #     # Connection status (left side)
    #     self.glassman_connection_label = ttk.Label(
    #         status_frame,
    #         textvariable=self.connection_status_vars[len(self.power_supplies)-1],  # Last index for Glassman
    #         foreground="red",
    #         font=(self.displayFont, 8, "bold"),
    #         background="white",
    #         relief="sunken",
    #         width=15,
    #         anchor=tk.CENTER
    #     )
    #     self.glassman_connection_label.pack(side=tk.LEFT)
        
    #     # Spacer label for consistent spacing
    #     ttk.Label(status_frame, text="  ", font=("Segoe UI", 8)).pack(side=tk.LEFT)
        
    #     # Output status (right side)
    #     ttk.Label(status_frame, text="Output:", font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=(0, 3))
    #     self.glassman_status_label = ttk.Label(
    #         status_frame, 
    #         textvariable=self.output_status[len(self.power_supplies)-1],  # Last index for Glassman
    #         foreground="red",
    #         font=(self.displayFont, 9, "bold"),
    #         background="white",
    #         relief="sunken",
    #         width=5,
    #         anchor=tk.CENTER
    #     )
    #     self.glassman_status_label.pack(side=tk.LEFT)

    def initialize_power_supplies(self):
        """Initialize hardware communication with KnobBox power supplies and create a KnobBoxPowerSupply instance for each."""
        self.power_supply_instances = [] # Reset list

        for ps_config in self.power_supplies:
            port = self.com_ports.get(ps_config["name"]) # coordinate com ports with main app
            if port:
                power_supply_instance = KnobBoxPowerSupply(
                    port=port,
                    power_supply_id=len(self.power_supply_instances), # Use index as ID
                    baudrate=9600,
                    timeout=1,
                    logger=self.logger,
                    debug_mode=False
                )
                self.power_supply_instances.append(power_supply_instance)

                try:
                    self.update_connection_status(len(self.power_supply_instances)-1, power_supply_instance.is_connected())
                    self.logger.info(f"Initialized {ps_config['name']} on port {port}")
                except Exception as e:
                    self.logger.error(f"Error initializing {ps_config['name']} on port {port}: {e}")
                    self.update_connection_status(len(self.power_supply_instances)-1, False)
            else:
                self.logger.warning(f"No COM port specified for {ps_config['name']}, skipping initialization")
                self.power_supply_instances.append(None)
                self.update_connection_status(len(self.power_supply_instances)-1, False)

    def attempt_reconnect(self, index):
        """Attempt to reconnect to a disconnected power supply."""
        port = self.com_ports.get(self.power_supplies[index]["name"])
        if port and self.power_supply_instances[index] is not None:
            try:
                power_supply_instance = KnobBoxPowerSupply(
                    port=port,
                    power_supply_id=index,
                    baudrate=9600,
                    timeout=1,
                    logger=self.logger,
                    debug_mode=False
                )
                self.power_supply_instances[index] = power_supply_instance

                try:
                    self.update_connection_status(index, power_supply_instance.is_connected())
                except Exception as e:
                    self.update_connection_status(index, False)
            except Exception as e:
                self.logger.error(f"Error reconnecting {self.power_supplies[index]['name']} on port {port}: {e}")
                self.update_connection_status(index, False)

    def create_power_supply_displays(self, frame, ps_config, index):
        """
        Create read-only displays for individual power supply.
        
        Args:
            frame: Frame to contain the displays
            ps_config: Power supply configuration dict
            index: Index of the power supply (0-3)
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
        
        self.ui_elements.append({
            'connection_label': connection_label, # label and display variables used for updating colors
            'status_label': status_label,
            'setpoint_display': setpoint_display,
            'voltage_display': voltage_display,
            'current_display': current_display
        })
    
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
        # Loop through each power supply and access the data via its "power_supply_data" dictionary
        for i, ps in enumerate(self.power_supply_instances):
            try:
                if ps and ps.is_connected():
                    try:
                        data = ps.get_power_supply_data()

                        # Extract relevant data with defaults
                        set_v = data.get('set_voltage', 0.0)
                        meas_v = data.get('meas_voltage', 0.0)
                        meas_c = data.get('meas_current', 0.0)

                        # Update display variables with formatted strings
                        self.set_voltages[i].set(f"{set_v:.1f} V" if set_v is not None else "-- V")
                        self.actual_voltages[i].set(f"{meas_v:.1f} V" if meas_v is not None else "-- V")
                        self.actual_currents[i].set(f"{meas_c:.3f} A" if meas_c is not None else "-- A")
                        
                        self.update_connection_status(i, True)
                        self.update_output_status(i, True)  # TODO Implement actual output status retrieval

                    except Exception as e:
                        if self.logger:
                            self.logger.error(f"Error updating readings for power supply {i}: {str(e)}")
                        self.set_default_values(i)
                else:
                    # Power supply not connected, set displays to default
                    self.set_default_values(i)
                    self.attempt_reconnect(i)  # Try to reconnect if disconnected
            except Exception as e:
                if self.logger:
                    self.logger.error(f"Error accessing power supply {i}: {str(e)}")
                self.set_default_values(i)

        self.parent_frame.after(500, self.update_readings)  # Schedule next update after 500 ms

    def set_default_values(self, index):
        """Set display values to default '--'."""
        self.set_voltages[index].set("-- V")
        self.actual_voltages[index].set("-- V")
        self.actual_currents[index].set("-- A")
        self.update_connection_status(index, False)
        self.update_output_status(index, False)

    def close_com_ports(self):
        """Close any open communication ports and stop all polling threads."""
        if self.logger:
            self.logger.info("Beam Energy subsystem: Closing communication ports")
        self.stop_monitoring_event.set()
        for ps in self.power_supply_instances:
            if ps is not None:
                try:
                    ps.close()
                except Exception as e:
                    if self.logger:
                        self.logger.error(f"Error closing power supply port: {str(e)}")

# TODO: Implement output status retrieval in KnobBoxPowerSupply and update_output_status method
# TODO: Readd Glassman
# TODO: Add config menu support for COM port selection
# TODO: Add error handling for power supply disconnect and reconnect (currently not working)