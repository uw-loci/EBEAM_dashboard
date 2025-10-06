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
        self.com_ports = com_ports
        self.logger = logger
        
        # Main power supply configurations
        self.power_supplies = [
            {"name": "+1kV Matsusada", "type": "matsusada", "voltage": 1000},
            {"name": "-1kV Matsusada", "type": "matsusada", "voltage": -1000},
            {"name": "+3kV Bertran", "type": "bertran", "voltage": 3000},
            {"name": "+20kV Bertran", "type": "bertran", "voltage": 20000}
        ]
        
        # Hardware communication
        self.knob_box = None
        self.glassman_thread = None
        self.glassman_stop_event = threading.Event()
        self.is_hardware_connected = False
        
        # Connection status tracking
        self.connection_status = {
            'knob_box': False,      # Main 4 power supplies only (Matsusada + Bertran)
            'glassman': False,      # Glassman power supply (separate driver)
        }
        
        # Data storage for latest readings
        self.latest_data = {
            'ps_data': [None, None, None, None],  # Data for 4 power supplies
            'glassman_status': False
        }
        self.data_lock = threading.Lock()

        self.power_supply_instances = []  # Instances of KnobBoxPowerSupply
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
        self.power_supply_instances = []
        for i, ps_config in enumerate(self.power_supplies):
            port = com_ports.get(ps_config["name"]) # adjust for incoming COMPORT format
            if port:
                ps_instance = KnobBoxPowerSupply(
                    port=port,
                    power_supply_id=i+1,  # IDs are 1-based
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

    def start_glassman_polling(self):
        """
        Start separate polling thread for Glassman power supply.
        This runs independently from the KnobBox polling.
        """
        if self.glassman_thread and self.glassman_thread.is_alive():
            return  # Already running
            
        self.glassman_stop_event.clear()
        self.glassman_thread = threading.Thread(target=self._glassman_polling_loop, daemon=True)
        self.glassman_thread.start()
        
        # Update connection status
        self.update_connection_status('glassman', True)
        
        if self.logger:
            self.logger.info("Started Glassman polling thread")
            
    def _glassman_polling_loop(self):
        """
        Internal polling loop for Glassman power supply.
        Runs in separate thread.
        """
        while not self.glassman_stop_event.is_set():
            try:
                # TODO: Implement actual Glassman communication
                # For now, simulate some data
                with self.data_lock:
                    # Placeholder - replace with actual Glassman reading
                    self.latest_data['glassman_status'] = False
                    
                time.sleep(1.0)  # Poll every second
                
            except Exception as e:
                if self.logger:
                    self.logger.error(f"Error in Glassman polling: {str(e)}")
                time.sleep(2.0)  # Wait longer on error

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
    
    def update_glassman_status(self, output_status):
        """
        Update the Glassman power supply output status.
        
        Args:
            output_status: True for ON, False for OFF
        """
        if output_status:
            self.glassman_status_label.config(text="ON", foreground="green")
        else:
            self.glassman_status_label.config(text="OFF", foreground="red")
    
    def update_connection_status(self, device, connected):
        """
        Update connection status indicators for power supplies.
        
        Args:
            device: 'knob_box' for main 4 power supplies (Matsusada + Bertran), 
                   'glassman' for Glassman power supply (separate driver)
            connected: True if connected, False if disconnected
        """
        self.connection_status[device] = connected
        
        if device == 'knob_box':
            # Update all 4 main power supply connection indicators
            for i in range(min(4, len(self.ui_elements))):
                element = self.ui_elements[i]
                if connected:
                    element['connection_label'].config(
                        text="CONNECTED", 
                        foreground="green"
                    )
                else:
                    element['connection_label'].config(
                        text="DISCONNECTED", 
                        foreground="red"
                    )
                    
        elif device == 'glassman':
            # Update Glassman connection indicator
            if hasattr(self, 'glassman_connection_label'):
                if connected:
                    self.glassman_connection_label.config(
                        text="CONNECTED", 
                        foreground="green"
                    )
                else:
                    self.glassman_connection_label.config(
                        text="DISCONNECTED", 
                        foreground="red"
                    )
    
    def update_all_connection_status(self):
        """
        Update connection status for all devices based on current hardware state.
        """
        # Check KnobBox connection
        knob_box_connected = (self.knob_box is not None and 
                             hasattr(self.knob_box, 'connected') and 
                             self.knob_box.connected)
        self.update_connection_status('knob_box', knob_box_connected)
        
        # Check Glassman connection (will use separate driver when implemented)
        glassman_connected = (self.glassman_thread is not None and 
                             self.glassman_thread.is_alive())
        self.update_connection_status('glassman', glassman_connected)
    
    def update_readings(self):
        """
        Update voltage and current readings from hardware.
        This method should be called periodically to refresh displays.
        """
        # Update connection status for all devices
        self.update_all_connection_status()
        
        if not self.is_hardware_connected or not self.knob_box:
            # No hardware connected, use placeholder data for testing
            return
            
        try:
            # Get data from KnobBox for the 4 main power supplies
            with self.knob_box.voltages_lock:
                voltages = self.knob_box.voltages.copy()
            with self.knob_box.currents_lock:
                currents = self.knob_box.currents.copy()
            with self.knob_box.statuses_lock:
                statuses = self.knob_box.output_statuses.copy()
                
            # Update each power supply display
            for i in range(min(4, len(voltages))):
                if voltages[i] is not None or currents[i] is not None or statuses[i] is not None:
                    self.update_power_supply_display(
                        ps_index=i,
                        set_voltage=None,  # TODO: Add set voltage reading if available
                        actual_voltage=voltages[i],
                        actual_current=currents[i],
                        output_status=statuses[i]
                    )
                    
            # Update Glassman status from separate polling
            with self.data_lock:
                glassman_status = self.latest_data['glassman_status']
            self.update_glassman_status(glassman_status)
            
        except Exception as e:
            if self.logger:
                self.logger.error(f"Error updating readings: {str(e)}")
        
    def close_com_ports(self):
        """Close any open communication ports and stop all polling threads."""
        if self.logger:
            self.logger.info("Beam Energy subsystem: Closing communication ports")
            
        # Stop Glassman polling thread
        if self.glassman_thread and self.glassman_thread.is_alive():
            self.glassman_stop_event.set()
            self.glassman_thread.join(timeout=3.0)
            self.update_connection_status('glassman', False)
            if self.logger:
                self.logger.info("Glassman polling thread stopped")
                
        # Stop KnobBox communication
        if self.knob_box:
            try:
                self.knob_box.stop_reading()
                self.update_connection_status('knob_box', False)
                if self.logger:
                    self.logger.info("KnobBox communication stopped")
            except Exception as e:
                if self.logger:
                    self.logger.error(f"Error stopping KnobBox: {str(e)}")
                    
        self.is_hardware_connected = False