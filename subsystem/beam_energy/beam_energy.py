import tkinter as tk
from tkinter import ttk
import threading
import time
from instrumentctl.knob_box.knob_box import KnobBoxPowerSupply


class BeamEnergySubsystem:
    """
    Manages the beam energy system with four main power supplies plus Glassman:
    - +1kV Matsusada
    - -1kV Matsusada  
    - +3kV Bertran
    - +20kV Bertran
    - +80kV Glassman (indicator only)
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
            #"+20kV Bertran": "COM6", removed for testing
            #"+80kV Glassman": "COM7"
        }
        self.logger = logger
        
        # Main power supply configurations
        self.power_supplies = [
            {"name": "+1kV Matsusada", "type": "matsusada", "voltage": 1000},
            {"name": "-1kV Matsusada", "type": "matsusada", "voltage": -1000},
            {"name": "+3kV Bertran", "type": "bertran", "voltage": 3000},
            # {"name": "+20kV Bertran", "type": "bertran", "voltage": 20000}, removed for testing
            # {"name": "+80kV Glassman", "type": "glassman", "voltage": 80000}  # Indicator only
        ]
        
        # Connection status tracking
        self.connection_status = {
            'matsusada_pos1kV': False,      
            'matsusada_neg1kV': False,
            'bertran_pos3kV': False,      
            # 'bertran_pos20kV': False,
            # 'glassman_pos80kV': False
        }

        # Global data storing each power supply's latest readings
        self.latest_power_supply_data = {
            'matsusada_pos1kV': {'output_status': 'OFF', 'set_voltage': 0.0, 'meas_voltage': 0.0, 'meas_current': 0.0},
            'matsusada_neg1kV': {'output_status': 'OFF', 'set_voltage': 0.0, 'meas_voltage': 0.0, 'meas_current': 0.0},
            'bertran_pos3kV': {'output_status': 'OFF', 'set_voltage': 0.0, 'meas_voltage': 0.0, 'meas_current': 0.0},
            # 'bertran_pos20kV': {},
            # 'glassman_pos80kV': {}
        }

        self.data_lock = threading.Lock()
        self.stop_monitoring_event = threading.Event()

        self.power_supply_instances = []  # List of KnobBoxPowerSupply instances
        self.initialize_power_supplies(com_ports)

        self.setup_ui()
        
    def setup_ui(self):
        """Create the user interface with four vertical boxes for power supplies plus Glassman indicator."""
        # Main container frame
        main_frame = ttk.Frame(self.parent_frame, padding="2")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Glassman power supply indicator (centered, below title)
        glassman_container = ttk.Frame(main_frame)
        glassman_container.pack(fill=tk.X, pady=(0, 5))
        self.create_glassman_indicator(glassman_container)
        
        # Power supplies container frame
        ps_container = ttk.Frame(main_frame)
        ps_container.pack(fill=tk.BOTH, expand=True)
        
        # Create four vertical boxes arranged horizontally
        self.ps_frames = []
        
        for i, ps_config in enumerate(self.power_supplies):
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
            text="DISCONNECTED",
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
            text="OFF", 
            foreground="red",
            font=(self.displayFont, 9, "bold"),
            background="white",
            relief="sunken",
            width=5,
            anchor=tk.CENTER
        )
        self.glassman_status_label.pack(side=tk.LEFT)

    def initialize_power_supplies(self, com_ports):
        """Initialize hardware communication with KnobBox power supplies and create a KnobBoxPowerSupply instance for each."""
        self.power_supply_instances = [] # Reset list

        for i, ps_config in enumerate(self.power_supplies):
            port = com_ports.get(ps_config["name"]) # coordinate com ports with main app
            if port:
                ps_instance = KnobBoxPowerSupply(
                    port=port,
                    power_supply_id=i, # Use index as ID
                    baudrate=9600,
                    timeout=1,
                    logger=self.logger,
                    debug_mode=False
                )
                self.power_supply_instances.append(ps_instance)
                self.logger.info(f"Initialized {ps_config['name']} on port {port}")
            else:
                self.logger.warning(f"No COM port specified for {ps_config['name']}, skipping initialization")
                self.power_supply_instances.append(None)

    # def start_glassman_polling(self):
    #     """
    #     Start separate polling thread for Glassman power supply.
    #     This runs independently from the KnobBox polling.
    #     """
    #     if self.glassman_thread and self.glassman_thread.is_alive():
    #         return  # Already running
            
    #     self.glassman_stop_event.clear()
    #     self.glassman_thread = threading.Thread(target=self._glassman_polling_loop, daemon=True)
    #     self.glassman_thread.start()
        
    #     # Update connection status
    #     self.update_connection_status('glassman', True)
        
    #     if self.logger:
    #         self.logger.info("Started Glassman polling thread")
            
    # def _glassman_polling_loop(self):
    #     """
    #     Internal polling loop for Glassman power supply.
    #     Runs in separate thread.
    #     """
    #     while not self.glassman_stop_event.is_set():
    #         try:
    #             # TODO: Implement actual Glassman communication
    #             # For now, simulate some data
    #             with self.data_lock:
    #                 # Placeholder - replace with actual Glassman reading
    #                 self.latest_data['glassman_status'] = False
                    
    #             time.sleep(1.0)  # Poll every second
                
    #         except Exception as e:
    #             if self.logger:
    #                 self.logger.error(f"Error in Glassman polling: {str(e)}")
    #             time.sleep(2.0)  # Wait longer on error

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
            text="DISCONNECTED", 
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
            text="OFF", 
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
            text="0.0 V", 
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
            text="0.0 V", 
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
            text="0.0 mA", 
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
            'connection_label': connection_label,
            'status_label': status_label,
            'setpoint_display': setpoint_display,
            'voltage_display': voltage_display,
            'current_display': current_display
        })
        
    def update_power_supply_display(self, ps_index, set_voltage=None, actual_voltage=None, actual_current=None, output_status=None):
        """
        Update the display values for a specific power supply.
        
        Args:
            ps_index: Index of the power supply (0-3)
            set_voltage: Set voltage value (V)
            actual_voltage: Actual voltage reading (V)  
            actual_current: Actual current reading (mA)
            output_status: Output status (True for ON, False for OFF)
        """
        if ps_index < 0 or ps_index >= len(self.ui_elements):
            return
            
        element = self.ui_elements[ps_index]
        
        if set_voltage is not None:
            element['setpoint_display'].config(text=f"{set_voltage:.1f} V")
            
        if actual_voltage is not None:
            element['voltage_display'].config(text=f"{actual_voltage:.1f} V")
            
        if actual_current is not None:
            element['current_display'].config(text=f"{actual_current:.2f} mA")
            
        if output_status is not None:
            if output_status:
                element['status_label'].config(text="ON", foreground="green")
            else:
                element['status_label'].config(text="OFF", foreground="red")
    
    # def update_glassman_status(self, output_status):
    #     """
    #     Update the Glassman power supply output status.
        
    #     Args:
    #         output_status: True for ON, False for OFF
    #     """
    #     if output_status:
    #         self.glassman_status_label.config(text="ON", foreground="green")
    #     else:
    #         self.glassman_status_label.config(text="OFF", foreground="red")
    
    def update_connection_status(self, index, connected):
        """
        Update connection status indicators for power supplies.
        
        Args:
                index: index of the power supply (0-3) or 'glassman' for Glassman
            connected: True if connected, False if disconnected
        """
        self.connection_status[self.power_supplies['name'][index]] = connected

        # TODO Update UI indicators based on index for each individual power supply
        # if index < 4:
        #     # Update all 4 main power supply connection indicators
        #     for i in range(min(4, len(self.ui_elements))):
        #         element = self.ui_elements[i]
        #         if connected:
        #             element['connection_label'].config(
        #                 text="CONNECTED", 
        #                 foreground="green"
        #             )
        #         else:
        #             element['connection_label'].config(
        #                 text="DISCONNECTED", 
        #                 foreground="red"
        #             )  
        # elif device == 'glassman':
        #     # Update Glassman connection indicator
        #     if hasattr(self, 'glassman_connection_label'):
        #         if connected:
        #             self.glassman_connection_label.config(
        #                 text="CONNECTED", 
        #                 foreground="green"
        #             )
        #         else:
        #             self.glassman_connection_label.config(
        #                 text="DISCONNECTED", 
        #                 foreground="red"
        #             )
    
    def update_all_connection_status(self):
        """
        Update connection status for all devices based on current hardware state.
        """
        for i, ps in enumerate(self.power_supply_instances):
            if ps is not None:
                try:
                    is_connected = ps.is_connected()
                    self.update_connection_status(self.power_supplies['name'][i], is_connected)
                except Exception as e:
                    if self.logger:
                        self.logger.error(f"Error checking connection for power supply {i}: {str(e)}")
                    self.update_connection_status(self.power_supplies['name'][i], False)
            else:
                self.update_connection_status(self.power_supplies['name'][i], False)
    
    def update_readings(self):
        """
        Update voltage and current readings from hardware.
        This method should be called periodically to refresh displays.
        """
        # Update connection status for all devices
        self.update_all_connection_status()

        for i, ps in enumerate(self.power_supply_instances):
            if ps is not None and self.connection_status[self.power_supplies['name'][i]]:
                try:
                    set_voltage = self.get_set_voltage(index=i)
                    actual_voltage = self.get_measured_voltage(index=i)
                    actual_current = self.get_measured_current(index=i)
                    # output_status = self.get_output_status(index=i)

                    self.update_power_supply_display(
                        ps_index=i,
                        set_voltage=set_voltage,
                        actual_voltage=actual_voltage,
                        actual_current=actual_current,
                        # output_status=output_status
                    )
                except Exception as e:
                    if self.logger:
                        self.logger.error(f"Error updating readings for power supply {i}: {str(e)}")
            else:
                # Power supply not connected, set displays to default
                self.update_power_supply_display(
                    ps_index=i,
                    set_voltage=0.0,
                    actual_voltage=0.0,
                    actual_current=0.0,
                    output_status=False
                )

    def get_set_voltage(self, ps_index):
        """
        Get the set voltage for a specific power supply.
        
        Args:
            ps_index: Index of the power supply (0-3)
        Returns:
            Set voltage in volts, or None if unavailable
        """
        if ps_index < 0 or ps_index >= len(self.power_supply_instances):
            return None
        
        ps = self.power_supply_instances[ps_index]
        if ps is not None and self.connection_status[self.power_supplies['name'][ps_index]]:
            try:
                data = ps.power_supply_data
                return data['set_voltage'] if 'set_voltage' in data else None
            except Exception as e:
                if self.logger:
                    self.logger.error(f"Error getting set voltage for power supply {ps_index}: {str(e)}")
                return None
        return None
    
    def get_measured_voltage(self, ps_index):
        """
        Get the measured voltage for a specific power supply.
        
        Args:
            ps_index: Index of the power supply (0-3)
        Returns:
            Measured voltage in volts, or None if unavailable
        """
        if ps_index < 0 or ps_index >= len(self.power_supply_instances):
            return None
        
        ps = self.power_supply_instances[ps_index]
        if ps is not None and self.connection_status[self.power_supplies['name'][ps_index]]:
            try:
                data = ps.power_supply_data
                return data['meas_voltage'] if 'meas_voltage' in data else None
            except Exception as e:
                if self.logger:
                    self.logger.error(f"Error getting measured voltage for power supply {ps_index}: {str(e)}")
                return None
        return None
    
    def get_measured_current(self, ps_index):
        """
        Get the measured current for a specific power supply.
        
        Args:
            ps_index: Index of the power supply (0-3)
        Returns:
            Measured current in milliamps, or None if unavailable
        """
        if ps_index < 0 or ps_index >= len(self.power_supply_instances):
            return None
        
        ps = self.power_supply_instances[ps_index]
        if ps is not None and self.connection_status[self.power_supplies['name'][ps_index]]:
            try:
                data = ps.power_supply_data
                return data['meas_current'] if 'meas_current' in data else None
            except Exception as e:
                if self.logger:
                    self.logger.error(f"Error getting measured current for power supply {ps_index}: {str(e)}")
                return None
        return None


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