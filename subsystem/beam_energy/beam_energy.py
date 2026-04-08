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
        self.knob_box_connected_at = None
        
        # Main power supply configurations
        self.power_supplies = [
            {"name": "+1kV Matsusada PS", "type": "matsusada", "voltage": 1000},
            {"name": "-1kV Matsusada PS", "type": "matsusada", "voltage": -1000},
            {"name": "+20kV Bertran PS", "type": "bertran", "voltage": 20000},
            {"name": "+3kV Bertran PS", "type": "bertran", "voltage": 3000},
        ]

        # Global data storing each power supply's latest readings
        self.set_voltages = [tk.StringVar(value="-- V") for _ in range(len(self.power_supplies))]
        self.actual_voltages = [tk.StringVar(value="-- V") for _ in range(len(self.power_supplies))]
        self.actual_currents = [tk.StringVar(value="-- mA") for _ in range(len(self.power_supplies))]
        self.output_status = [tk.StringVar(value="DISABLED") for _ in range(len(self.power_supplies))]
        self.connection_status_colors = [tk.StringVar(value="red") for _ in range(len(self.power_supplies) )]
        self.reset_status_colors = [tk.StringVar(value="white") for _ in range(2)]
        self.forced_off_color = tk.StringVar(value="white")  # Only for 3kV Bertran

        # Indicator Panel -> not power supply specific
        self.glassman_interlock_var = tk.StringVar(value="UNARMED")
        self.arm_beams_var = tk.StringVar(value="UNARMED")
        self.ccs_power_var = tk.StringVar(value="OFF")
        self.logic_comms_color = tk.StringVar(value="red")  # red=Disconnected, blue=Connected
        self.interlocks_color = tk.StringVar(value="red")   # red=Fault, green=All Good

        self.overcurrent_flags = [False for _ in self.power_supplies]

        self.ui_elements = []  # To hold references to UI elements for updates

        self.data_lock = threading.Lock()
        self.stop_polling = threading.Event()
        self.poll_thread = None
        self.reconnect_in_progress = threading.Event()

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

                def update_circle(*args):
                    canvas.itemconfig(oval, fill=color_var.get())

                color_var.trace_add("write", update_circle)

                # Initialize with current value
                canvas.itemconfig(oval, fill=color_var.get())

        add_row("Arm Beams:",      self.arm_beams_var)
        add_row("CCS Power:",      self.ccs_power_var)
        add_row("Arm 80kV:",     self.glassman_interlock_var)
        add_row("Logic Comms:",    color_var=self.logic_comms_color)
        add_row("Interlocks:",     color_var=self.interlocks_color)        

    def create_power_supply_displays(self, frame, ps_config, index):
        """
        Create read-only displays for individual power supply.
        
        Args:
            frame: Frame to contain the displays
            ps_config: Power supply configuration dict
            index: Index of the power supply, 1 through 4
        """
        # Connection status indicator (at top left)
        top_row_frame = ttk.Frame(frame)
        top_row_frame.pack(fill=tk.X, pady=(0, 5))
        connection_label = ttk.Label(top_row_frame, text="Comms:", font=("Segoe UI", 8))
        connection_label.pack(side=tk.LEFT)
        connection_canvas, connection_oval = self.create_indicator_circle(
            top_row_frame, color=self.connection_status_colors[index].get()
        )
        connection_canvas.pack(side=tk.LEFT, padx=4)

        def update_connection_circle(*args):
            connection_canvas.itemconfig(connection_oval, fill=self.connection_status_colors[index].get())

        self.connection_status_colors[index].trace_add("write", update_connection_circle)
        connection_canvas.itemconfig(connection_oval, fill=self.connection_status_colors[index].get())

        # Matsusada reset status indicator (at top right)
        if index < 2:
            reset_canvas, reset_oval = self.create_indicator_circle(
                top_row_frame, color=self.reset_status_colors[index].get()
            )
            reset_canvas.pack(side=tk.RIGHT, padx=4)
            reset_label = ttk.Label(top_row_frame, text="Overcurrent:", font=("Segoe UI", 8))
            reset_label.pack(side=tk.RIGHT)

            def update_reset_circle(*args):
                reset_canvas.itemconfig(reset_oval, fill=self.reset_status_colors[index].get())

            self.reset_status_colors[index].trace_add("write", update_reset_circle)
            reset_canvas.itemconfig(reset_oval, fill=self.reset_status_colors[index].get())

        # 3kV Bertan "Forced Off" indicator (at top right)
        if index == 3:
            forced_off_canvas, forced_off_oval = self.create_indicator_circle(
                top_row_frame, color=self.forced_off_color.get()
            )
            forced_off_canvas.pack(side=tk.RIGHT, padx=4)
            forced_off_label = ttk.Label(top_row_frame, text="Forced Off:", font=("Segoe UI", 8))
            forced_off_label.pack(side=tk.RIGHT)

            def update_forced_off_circle(*args):
                forced_off_canvas.itemconfig(forced_off_oval, fill=self.forced_off_color.get())

            self.forced_off_color.trace_add("write", update_forced_off_circle)
            forced_off_canvas.itemconfig(forced_off_oval, fill=self.forced_off_color.get())
        
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
            width=15,
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
            self.knob_box_controller.disconnect()
            time.sleep(.2)
        
        try:
            self.log(f"Attempting to connect to KnobBox Modbus controller on port {port}...", LogLevel.DEBUG)
            knob_box_modbus = KnobBoxModbus(port=port, logger=self.logger)
            if knob_box_modbus.connect():  # Initializes connection with RS-485 in KnobBoxModbus class
                self.log(f"KnobBox Modbus controller CONNECTED on port {port}", LogLevel.DEBUG)
                self.knob_box_controller = knob_box_modbus
                self.knob_box_connected = True
                self.knob_box_connected_at = time.time()
                self.start_polling_thread()  # Start background thread to poll data
                return True
            else:
                self.log(f"Failed to connect to KnobBox Modbus controller on port {port}", LogLevel.ERROR)
                self.knob_box_connected = False
                self.knob_box_connected_at = None
                return False
        except Exception as e:
            self.log(f"Exception thrown when trying to connect to KnobBox on port {port}: {str(e)}", LogLevel.ERROR)
            self.knob_box_connected = False
            self.knob_box_connected_at = None
            return False
        
    def attempt_knob_box_reconnect(self):
        """Attempt to reconnect to the KnobBox Modbus controller."""
        if self.knob_box_controller:
            self.knob_box_controller.disconnect()
            time.sleep(.2)  # Brief pause before reconnecting
        return self.initialize_knob_box_modbus()
    
    def update_output_status(self, index, status):
        """Update output status indicators."""
        if index < len(self.ui_elements):
            if status:
                self.output_status[index].set("ENABLED")
                self.ui_elements[index]['status_label'].config(foreground="green")
            else:
                self.output_status[index].set("DISABLED")
                self.ui_elements[index]['status_label'].config(foreground="red")

    def update_reset_status(self, index, reset_state):
        if index < 2:  # Only Matsusada units have reset status
            if reset_state:
                self.reset_status_colors[index].set("yellow")
            else:
                self.reset_status_colors[index].set("white")

    def update_forced_off_status(self, index, timer_state_3k):
        if index == 3:  # Only 3kV Bertran has forced off status
            if timer_state_3k:
                self.forced_off_color.set("red") 
            else:
                self.forced_off_color.set("white")

    def update_connection_status(self, index, connected):
        """Update connection status indicators."""
        if index < len(self.ui_elements):
            if connected:
                self.connection_status_colors[index].set("blue")
            else:
                self.connection_status_colors[index].set("red")

    def update_indicators_panel(self, index, arm_beams, ccs_power, arm_80kv, logic_comms, interlocks):
        """Update system status indicators."""
        if index < len(self.ui_elements):
            self.arm_beams_var.set("ARMED" if arm_beams else "UNARMED")
            self.ccs_power_var.set("ON" if ccs_power else "OFF")
            self.glassman_interlock_var.set("ARMED" if arm_80kv else "UNARMED")
            self.logic_comms_color.set("blue" if logic_comms else "red")
            self.interlocks_color.set("red" if interlocks else "green")

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
                elif not self.reconnect_in_progress.is_set():
                    self._schedule_reconnect()
            except Exception:
                if not self.reconnect_in_progress.is_set():
                    self._schedule_reconnect()
            time.sleep(.2)  # Polling interval

    def _safe_reconnect(self):
        """Run reconnect in a background thread to keep the UI responsive."""
        def _worker():
            try:
                self.attempt_knob_box_reconnect()
            finally:
                self.reconnect_in_progress.clear()

        threading.Thread(target=_worker, daemon=True).start()

    def _schedule_reconnect(self):
        """Schedule reconnect on the UI thread and avoid stuck reconnect flags."""
        with self.data_lock:
            if self.reconnect_in_progress.is_set():
                return False
            self.reconnect_in_progress.set()

        try:
            self.parent_frame.after(0, self._safe_reconnect)
            return True
        except Exception as e:
            self.reconnect_in_progress.clear()
            self.log(f"Failed to schedule reconnect: {str(e)}", LogLevel.DEBUG)
            return False

    def update_readings(self):
        """
        Update voltage and current readings from hardware.
        This method should be called periodically to refresh displays.
        """
        # Update Knob Box data
        try:
            if self.knob_box_connected and self.knob_box_controller:
                knob_box = self.knob_box_controller
                any_connected = knob_box.any_unit_connected()
                if not any_connected:
                    # Allow a short grace period after connect before forcing reconnect.
                    if self.knob_box_connected_at and (time.time() - self.knob_box_connected_at) < knob_box.CONNECTION_TIMEOUT:
                        for index, _ in enumerate(self.power_supplies):
                            self.set_default_values(index)
                        self.after_id = self.parent_frame.after(500, self.update_readings)
                        return

                    self.knob_box_connected = False
                    self.knob_box_connected_at = None
                    for index, _ in enumerate(self.power_supplies):
                        self.set_default_values(index)
                    self._schedule_reconnect()
                    # Schedule next update and exit early
                    self.log(
                        "KnobBox controller unresponsive, using default values.",
                        LogLevel.DEBUG
                    )
                    self.after_id = self.parent_frame.after(500, self.update_readings)
                    return
            else:
                # KnobBox not connected, set all to default
                for index, _ in enumerate(self.power_supplies):
                    self.set_default_values(index)
                self._schedule_reconnect()
                # Schedule next update and exit early
                self.log(
                    f"KnobBox controller not connected, using default values.",
                    LogLevel.DEBUG
                )
                self.after_id = self.parent_frame.after(500, self.update_readings)
                return
            
            # Pull data snapshot from KnobBox controller
            data_snapshot = knob_box.get_data_snapshot()
            for index, _ in enumerate(self.power_supplies):
                
                # Unit IDs start at one. We may want to create a mapping later when we have the final values
                unit_id = index + 1
                comms = knob_box.get_unit_connection_status(unit_id)
                if not comms:
                    self.set_default_values(index)
                    continue

                data = data_snapshot.get(unit_id, None)
                
                if not data:
                    self.set_default_values(index)
                    continue

                v_set = data.get('set_voltage_V', None)
                v_read = data.get('actual_voltage_V', None)
                i_read = data.get('actual_current_mA', None)
                hv_enable = data.get('hv_enable', False)
                arm_beams = data.get('arm_beams', False)
                ccs_power = data.get('ccs_power', False)
                arm_80kV = data.get('arm_80kV', False)
                reset_state = data.get('reset_state_1kV', False)
                nomop_flag = data.get('nomop_flag', False)
                logic_alive = data.get('logic_alive', False)
                reset_counter_3kv = data.get('3kv_reset_count', 0)
                # TODO rest of flags for interlocks?

                # self.update_connection_status(index, True)

                # Update display values if data is valid
                if v_set is not None:
                    if unit_id == 2: # insert minus sign for -1kV Matsusada
                        self.set_voltages[index].set(f"-{v_set:.1f} V")
                    else:    
                        self.set_voltages[index].set(f"{v_set:.1f} V")
                else:
                    self.set_voltages[index].set("-- V")

                if v_read is not None:
                    if unit_id == 2: # insert minus sign for -1kV Matsusada
                        self.actual_voltages[index].set(f"-{v_read:.1f} V")
                    else:
                        self.actual_voltages[index].set(f"{v_read:.1f} V")
                else:
                    self.actual_voltages[index].set("-- V")

                if i_read is not None:
                    self.actual_currents[index].set(f"{i_read:.3f} mA")
                else:
                    self.actual_currents[index].set("-- mA")

                # Update indicators based on data
                interlocks = not nomop_flag # 1 for Nom Op, 0 for interlocks active
                self.update_indicators_panel(index, arm_beams, ccs_power, arm_80kV, logic_alive, interlocks)
                self.update_output_status(index, hv_enable)
                self.update_reset_status(index, reset_state)
                self.update_connection_status(index, comms)
                self.update_forced_off_status(index, reset_counter_3kv > 0)

        except Exception as e:  
            self.log(f"Error updating readings: {str(e)}", LogLevel.ERROR)
            for index, _ in enumerate(self.power_supplies): 
                self.set_default_values(index)
            self._schedule_reconnect()
            
        
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
        self.update_reset_status(index, False)
        self.update_indicators_panel(index, arm_beams=False, ccs_power=False, arm_80kv=False, logic_comms=False, interlocks=True)

    def update_com_port(self, new_com_ports):
        """Update COM port assignments and reinitialize power supplies."""
        new_port = new_com_ports.get('KnobBox', None)
        if not new_port:
            return False
        
        if new_port == self.com_ports.get('KnobBox', None):
            return True  # No change
        
        self.com_ports = new_com_ports

        # Close existing connections
        self.close_com_ports()
        
        # Reinitialize with new ports
        self.initialize_knob_box_modbus()

    def close_com_ports(self):
        # Close any open COM port connections
        if self.knob_box_controller:
            self.knob_box_controller.disconnect()
            self.knob_box_controller = None
            self.knob_box_connected = False
            self.knob_box_connected_at = None

        # Stop polling thread
        self._stop_polling_thread()

    def _stop_polling_thread(self):
        """Stop and join the polling thread if it is running."""
        self.stop_polling.set()
        if self.poll_thread and self.poll_thread.is_alive():
            self.poll_thread.join(timeout=2)
        self.poll_thread = None

    def close(self):
        """Cancel Dashboard updates and close COM ports."""
        self.cancel_updates()
        self.close_com_ports()

    def log(self, message, level=LogLevel.INFO):
        """Log a message with the specified level if a logger is configured."""
        if self.logger:
            self.logger.log(message, level)
        else:
            print(f"{level.name}: {message}")