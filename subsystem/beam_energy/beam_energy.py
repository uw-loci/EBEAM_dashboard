import tkinter as tk
from tkinter import ttk


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

    def __init__(self, parent_frame, logger=None):
        """
        Initialize the Beam Energy subsystem interface.
        
        Args:
            parent_frame: The tkinter frame where this subsystem will be displayed
            logger: Logger instance for system messages
        """
        self.parent_frame = parent_frame
        self.logger = logger
        
        # Main power supply configurations
        self.power_supplies = [
            {"name": "+1kV Matsusada", "type": "matsusada", "voltage": 1000},
            {"name": "-1kV Matsusada", "type": "matsusada", "voltage": -1000},
            {"name": "+3kV Bertran", "type": "bertran", "voltage": 3000},
            {"name": "+20kV Bertran", "type": "bertran", "voltage": 20000}
        ]
        
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
                padding="5"
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
            padding="5"
        )
        # Center the frame horizontally
        glassman_frame.pack(anchor=tk.CENTER)
        
        # Output status indicator
        output_frame = ttk.Frame(glassman_frame)
        output_frame.pack()
        
        ttk.Label(output_frame, text="Output:", font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=(0, 3))
        self.glassman_status_label = ttk.Label(
            output_frame, 
            text="OFF", 
            foreground="red",
            font=(self.displayFont, 9, "bold"),
            background="white",
            relief="sunken",
            width=5,
            anchor=tk.CENTER
        )
        self.glassman_status_label.pack(side=tk.LEFT)

    def create_power_supply_displays(self, frame, ps_config, index):
        """
        Create read-only displays for individual power supply.
        
        Args:
            frame: Frame to contain the displays
            ps_config: Power supply configuration dict
            index: Index of the power supply (0-3)
        """
        # Output status indicator
        status_frame = ttk.Frame(frame)
        status_frame.pack(fill=tk.X, pady=(0, 8))
        
        ttk.Label(status_frame, text="Output:", font=("Segoe UI", 8)).pack(side=tk.LEFT)
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
        status_label.pack(side=tk.RIGHT)
        
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
    
    def update_readings(self):
        """
        Update voltage and current readings from hardware.
        This method should be called periodically to refresh displays.
        """
        # TODO: Implement actual hardware communication
        # Example placeholder data:
        # self.update_power_supply_display(0, set_voltage=1000.0, actual_voltage=999.8, actual_current=15.23, output_status=True)
        # self.update_glassman_status(True)
        pass
        
    def close_com_ports(self):
        """Close any open communication ports."""
        # TODO: Implement when hardware communication is added
        if self.logger:
            self.logger.info("Beam Energy subsystem: Closing communication ports")
        pass