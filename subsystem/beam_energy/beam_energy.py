import tkinter as tk
from tkinter import ttk
import math
import threading
import time
from instrumentctl.knob_box.knob_box_modbus import KnobBoxModbus
from utils import LogLevel
import tkinter.messagebox as messagebox
from usr.beam_energy_warning_config import (
    BEAMS_ESTOP_CURRENT_FIELD,
    DEFAULT_WARNING_LIMITS,
    POS20KV_SUPPLY_KEY,
    load_beam_energy_warning_limits,
    save_beam_energy_warning_limits,
)



class BeamEnergySubsystem:
    """
    Manages the beam energy system with four main power supplies:
    - +80kV Glassman (interlock only)
    - +1kV Matsusada
    - -1kV Matsusada 
    - +3kV Bertan
    - +20kV Bertan
    """

    displayFont = "Arial"
    ESTOP_TEXT_COLOR = "red"
    WARNING_TEXT_COLOR = "#FF8000"
    NORMAL_TEXT_COLOR = "black"

    RADIATION_INDICATOR_THRESHOLD_V = 10000.0

    warning_limit_fields = (
        ("max_voltage_v", "Max V", "V"),
        ("min_voltage_v", "Min V", "V"),
        ("max_current_ma", "Max I", "mA"),
    )
    supply_payload_map = (
        ("pos1kv", 1),
        ("neg1kv", 2),
        ("pos20kv", 3),
        ("pos3kv", 4),
    )
    supply_interlock_flag_map = {
        "pos1kv": ("vcomp_1k_flag", "icomp_1k_flag"),
        "neg1kv": ("neg_vcomp_1k_flag", "neg_icomp_1k_flag"),
        "pos20kv": ("vcomp_20k_flag", "icomp_20k_flag"),
        "pos3kv": ("vcomp_3k_flag", "icomp_3k_flag"),
    }
    interlock_log_entries = (
        ("vcomp_1k_flag", "+1kV Matsusada Voltage tripped"),
        ("icomp_1k_flag", "+1kV Matsusada Current tripped"),
        ("neg_vcomp_1k_flag", "-1kV Matsusada Voltage tripped"),
        ("neg_icomp_1k_flag", "-1kV Matsusada Current tripped"),
        ("vcomp_20k_flag", "+20kV Bertan Voltage tripped"),
        ("icomp_20k_flag", "+20kV Bertan Current tripped"),
        ("vcomp_3k_flag", "+3kV Bertan Voltage tripped"),
        ("icomp_3k_flag", "+3kV Bertan Current tripped"),
    )
    beam_energy_flag_keys = (
        "3kV_enable",
        "nomop_flag",
        "timer_state_3kV",
        "ccspower_flag",
        "armbeams_flag",
        "arm80kv_flag",
        "vcomp_1k_flag",
        "icomp_1k_flag",
        "neg_vcomp_1k_flag",
        "neg_icomp_1k_flag",
        "vcomp_20k_flag",
        "icomp_20k_flag",
        "vcomp_3k_flag",
        "icomp_3k_flag",
    )

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
            {"name": "+20kV Bertan PS", "type": "bertan", "voltage": 20000},
            {"name": "+3kV Bertan PS", "type": "bertan", "voltage": 3000},
        ]
        self.supply_keys = [supply_key for supply_key, _ in self.supply_payload_map]
        self.warning_limits = load_beam_energy_warning_limits(logger=self.logger)
        # Last numeric readings let limit edits immediately refresh colors/trips without waiting for a new poll.
        self.latest_actual_voltage_values = [None for _ in self.power_supplies]
        self.latest_actual_current_values = [None for _ in self.power_supplies]

        # Global data storing each power supply's latest readings
        self.set_voltages = [tk.StringVar(value="-- V") for _ in range(len(self.power_supplies))]
        self.actual_voltages = [tk.StringVar(value="-- V") for _ in range(len(self.power_supplies))]
        self.actual_currents = [tk.StringVar(value="-- mA") for _ in range(len(self.power_supplies))]
        self.output_status = [tk.StringVar(value="DISABLED") for _ in range(len(self.power_supplies))]
        self.connection_status_colors = [tk.StringVar(value="red") for _ in range(len(self.power_supplies) )]
        self.reset_status_colors = [tk.StringVar(value="white") for _ in range(2)]
        self.voltage_interlock_colors = [tk.StringVar(value="white") for _ in range(len(self.power_supplies))]
        self.current_interlock_colors = [tk.StringVar(value="white") for _ in range(len(self.power_supplies))]
        self.interlock_log_vars = [
            tk.StringVar(value="") for _flag_key, _message in self.interlock_log_entries
        ]
        self.interlock_log_var_by_flag = {
            flag_key: self.interlock_log_vars[index]
            for index, (flag_key, _message) in enumerate(self.interlock_log_entries)
        }
        self.forced_off_color = tk.StringVar(value="white")  # Only for 3kV Bertan

        # Indicator Panel -> not power supply specific
        self.glassman_interlock_var = tk.StringVar(value="UNARMED")
        self.arm_beams_var = tk.StringVar(value="UNARMED")
        self.ccs_power_var = tk.StringVar(value="OFF")
        self.logic_comms_color = tk.StringVar(value="red")  # red=Disconnected, blue=Connected
        self.interlocks_color = tk.StringVar(value="red")   # red=Fault, green=All Good
        # Beam Energy owns the +20kV threshold; Dashboard provides the actual stop handler.
        self.beams_estop_current_entry_var = tk.StringVar(value="")
        self.beams_estop_current_value_var = tk.StringVar(
            value=self._format_beams_estop_current_limit_setting()
        )
        self.beams_estop_callback = None
        # Dashboard wires this to LaserMonitorDriver.set_radiation_indicator().
        # The last-sent value prevents repeated sends during unchanged 500 ms polls.
        self.radiation_indicator_callback = None
        self._radiation_indicator_sent = None
        self.warning_limit_entry_vars = [
            {field: tk.StringVar(value="") for field, _label, _unit in self.warning_limit_fields}
            for _ in self.power_supplies
        ]
        self.warning_limit_value_vars = [
            {
                field: tk.StringVar(value=self._format_warning_limit_setting(index, field))
                for field, _label, _unit in self.warning_limit_fields
            }
            for index, _ps_config in enumerate(self.power_supplies)
        ]

        self.overcurrent_flags = [False for _ in self.power_supplies]

        self.ui_elements = []  # To hold references to UI elements for updates

        self.data_lock = threading.Lock()
        self.stop_polling = threading.Event()
        self.poll_thread = None
        self.reconnect_in_progress = threading.Event()
        self.reconnect_requested = threading.Event()

        self.power_supply_instances = []  # List of KnobBoxPowerSupply instances
        self.setup_ui()
        # self.initialize_power_supplies()
        self.initialize_knob_box_modbus()
        self.update_readings()
        
    def setup_ui(self):
        """Create the user interface with four vertical boxes for power supplies."""
        notebook = ttk.Notebook(self.parent_frame)
        notebook.pack(fill=tk.BOTH, expand=True)

        main_tab = ttk.Frame(notebook)
        config_tab = ttk.Frame(notebook)
        notebook.add(main_tab, text="Main")
        notebook.add(config_tab, text="Config")

        # Main container frame
        main_frame = ttk.Frame(main_tab, padding="2")
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
            
            # Configure grid weights for equal-width power supply panels.
            ps_container.grid_columnconfigure(i, weight=1, uniform="beam_energy_supply")

            self.ps_frames.append(ps_frame)
            self.create_power_supply_displays(ps_frame, ps_config, i)
        
        # Configure main grid
        ps_container.grid_rowconfigure(0, weight=1)

        # Right panel for status indicators
        right_panel = ttk.Frame(ps_container)
        right_panel.grid(row=0, column=len(self.ps_frames)+1, sticky="ns", padx=(10,0))
        self.create_indicators(right_panel)
        self.create_warning_config_tab(config_tab)

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

        self.create_interlock_log(parent_frame)

    def create_interlock_log(self, parent_frame):
        """Create the Beam Energy interlock warning log below the system status panel."""
        panel = ttk.LabelFrame(parent_frame, text="Interlock Log", padding=5)
        panel.pack(fill=tk.X, anchor=tk.N, pady=(8, 0))

        for index, (_flag_key, _message) in enumerate(self.interlock_log_entries):
            ttk.Label(
                panel,
                textvariable=self.interlock_log_vars[index],
                font=("Segoe UI", 7),
                foreground="red",
                width=24,
                wraplength=150,
                anchor=tk.W,
                justify=tk.LEFT,
            ).pack(fill=tk.X, anchor=tk.W, pady=1)

    def create_warning_config_tab(self, parent_frame):
        """Create configurable warning-limit controls for Beam Energy readbacks."""
        config_container = ttk.Frame(parent_frame, padding="2")
        config_container.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            config_container,
            text="Power Supply Warning Values",
            font=("Segoe UI", 9, "bold"),
            anchor=tk.CENTER
        ).pack(fill=tk.X, pady=(0, 6))

        supplies_container = ttk.Frame(config_container)
        supplies_container.pack(fill=tk.BOTH, expand=True)

        for i, ps_config in enumerate(self.power_supplies):
            ps_frame = ttk.LabelFrame(
                supplies_container,
                text=ps_config["name"],
                padding="5",
                labelanchor="n"
            )
            ps_frame.grid(row=0, column=i, sticky="nsew", padx=3, pady=3)
            supplies_container.grid_columnconfigure(i, weight=1, uniform="beam_energy_config_supply")
            self.create_warning_limit_controls(ps_frame, i)

        supplies_container.grid_rowconfigure(0, weight=1)

    def create_warning_limit_controls(self, frame, index):
        for field, label, unit in self.warning_limit_fields:
            row = ttk.Frame(frame)
            row.pack(fill=tk.X, pady=(2, 0))

            ttk.Label(row, text=f"{label}:", font=("Segoe UI", 8)).grid(row=0, column=0, sticky=tk.W)
            sign_text = "-" if self._get_supply_key(index) == "neg1kv" and field != "max_current_ma" else ""
            ttk.Label(row, text=sign_text, font=("Segoe UI", 8), width=1).grid(row=0, column=1, sticky=tk.E)
            entry = ttk.Entry(row, textvariable=self.warning_limit_entry_vars[index][field], width=7)
            entry.grid(row=0, column=2, sticky=tk.W, padx=(2, 2))
            ttk.Label(row, text=unit, font=("Segoe UI", 8)).grid(row=0, column=3, sticky=tk.W)
            ttk.Button(
                row,
                text="Set",
                width=4,
                command=lambda i=index, f=field: self.set_warning_limit(i, f)
            ).grid(row=0, column=4, sticky=tk.W, padx=(4, 0))

            ttk.Label(
                frame,
                textvariable=self.warning_limit_value_vars[index][field],
                font=("Segoe UI", 8),
                foreground="gray"
            ).pack(anchor=tk.W, padx=(2, 0), pady=(0, 4))

        if self._get_supply_key(index) == POS20KV_SUPPLY_KEY:
            # +20kV has an escalation threshold above Max I that triggers the full Beams E-STOP.
            self.create_beams_estop_limit_controls(frame)

        if self._get_supply_key(index) == "neg1kv":
            ttk.Label(
                frame,
                text="Warning limits use absolute values.",
                font=("Segoe UI", 8, "italic"),
                foreground="gray"
            ).pack(anchor=tk.W, pady=(2, 0))

    def create_beams_estop_limit_controls(self, frame):
        ttk.Separator(frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=(4, 4))
        ttk.Label(
            frame,
            text="Beams E-Stop Current Limit",
            font=("Segoe UI", 8, "bold"),
        ).pack(anchor=tk.W, pady=(0, 2))

        row = ttk.Frame(frame)
        row.pack(fill=tk.X, pady=(2, 0))

        ttk.Label(row, text="E-Stop Limit:", font=("Segoe UI", 8)).grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(row, textvariable=self.beams_estop_current_entry_var, width=7).grid(
            row=0,
            column=1,
            sticky=tk.W,
            padx=(2, 2),
        )
        ttk.Label(row, text="mA", font=("Segoe UI", 8)).grid(row=0, column=2, sticky=tk.W)
        ttk.Button(
            row,
            text="Set",
            width=4,
            command=self.set_beams_estop_current_limit,
        ).grid(row=0, column=3, sticky=tk.W, padx=(4, 0))

        ttk.Label(
            frame,
            textvariable=self.beams_estop_current_value_var,
            font=("Segoe UI", 8),
            foreground="gray",
        ).pack(anchor=tk.W, padx=(2, 0), pady=(0, 4))

    def _get_supply_key(self, index):
        return self.supply_keys[index]

    def _get_pos20kv_index(self):
        return self.supply_keys.index(POS20KV_SUPPLY_KEY)

    def _warning_limit_unit(self, field):
        return "mA" if field in ("max_current_ma", BEAMS_ESTOP_CURRENT_FIELD) else "V"

    def _format_warning_limit_setting(self, index, field):
        supply_key = self.supply_keys[index]
        value = self.warning_limits[supply_key][field]
        sign = "-" if supply_key == "neg1kv" and field != "max_current_ma" else ""
        return f"Limit set to: {sign}{value:g}{self._warning_limit_unit(field)}"

    def _format_beams_estop_current_limit_setting(self):
        value = self.warning_limits[POS20KV_SUPPLY_KEY][BEAMS_ESTOP_CURRENT_FIELD]
        return f"Limit set to: {value:g}mA"

    def _get_supply_name(self, index):
        if index < len(self.power_supplies):
            return self.power_supplies[index]["name"]
        return self._get_supply_key(index)

    def _warning_limit_label(self, field):
        if field == "max_current_ma":
            return "Max I current limit"
        if field == "max_voltage_v":
            return "Max V voltage limit"
        if field == "min_voltage_v":
            return "Min V voltage limit"
        return "warning limit"

    def _warning_limit_context(self, index, field):
        return f"{self._get_supply_name(index)} {self._warning_limit_label(field)}"

    def _beams_estop_current_limit_context(self):
        return f"{self._get_supply_name(self._get_pos20kv_index())} Beams E-Stop Current Limit"

    def _max_allowed_warning_limit(self, supply_key, field):
        defaults = DEFAULT_WARNING_LIMITS[supply_key]
        if field in ("max_current_ma", BEAMS_ESTOP_CURRENT_FIELD):
            return defaults[field]
        return defaults["max_voltage_v"]

    def _refresh_warning_limit_display(self, index, field=None):
        if not hasattr(self, "warning_limit_value_vars"):
            return

        fields = [field] if field else [item[0] for item in self.warning_limit_fields]
        for limit_field in fields:
            self.warning_limit_value_vars[index][limit_field].set(
                self._format_warning_limit_setting(index, limit_field)
            )

    def _refresh_beams_estop_current_display(self):
        if hasattr(self, "beams_estop_current_value_var"):
            self.beams_estop_current_value_var.set(
                self._format_beams_estop_current_limit_setting()
            )

    def set_warning_limit(self, index, field):
        """UI callback for committing one warning-limit entry."""
        raw_value = self.warning_limit_entry_vars[index][field].get()
        if self._set_warning_limit_from_raw(index, field, raw_value):
            self.warning_limit_entry_vars[index][field].set("")

    def _parse_warning_limit_value(self, raw_value, context, unit, show_dialogs=True):
        raw_text = str(raw_value).strip()
        if not raw_text:
            self._show_warning_limit_error(
                "Invalid Input",
                f"{context}: please enter a warning-limit value in {unit}.",
                show_dialogs,
            )
            return None

        try:
            new_value = float(raw_text)
        except ValueError:
            self._show_warning_limit_error(
                "Invalid Input",
                f"{context}: please enter a valid number in {unit}.",
                show_dialogs,
            )
            return None

        if not math.isfinite(new_value) or new_value < 0:
            self._show_warning_limit_error(
                "Invalid Input",
                f"{context}: value must be a finite, non-negative number in {unit}.",
                show_dialogs
            )
            return None

        return new_value

    def _set_warning_limit_from_raw(self, index, field, raw_value, show_dialogs=True, persist=True):
        context = self._warning_limit_context(index, field)
        unit = self._warning_limit_unit(field)
        new_value = self._parse_warning_limit_value(
            raw_value,
            context,
            unit,
            show_dialogs=show_dialogs,
        )
        if new_value is None:
            return False

        supply_key = self._get_supply_key(index)
        candidate = dict(self.warning_limits[supply_key])
        candidate[field] = new_value

        # For +20kV, show the operator the Max I/E-STOP relationship before generic range errors.
        if (
            supply_key == POS20KV_SUPPLY_KEY
            and candidate["max_current_ma"] > candidate[BEAMS_ESTOP_CURRENT_FIELD]
        ):
            self._show_warning_limit_error(
                "Invalid Current Range",
                f"{context}: must be at or below the Beams E-Stop Current "
                f"Limit ({candidate[BEAMS_ESTOP_CURRENT_FIELD]:g}mA).",
                show_dialogs,
            )
            return False

        max_allowed = self._max_allowed_warning_limit(supply_key, field)
        if new_value > max_allowed:
            self._show_warning_limit_error(
                "Invalid Input",
                f"{context}: value must be between 0{unit} and {max_allowed:g}{unit}.",
                show_dialogs
            )
            return False

        if candidate["max_voltage_v"] < candidate["min_voltage_v"]:
            self._show_warning_limit_error(
                "Invalid Voltage Range",
                f"{self._get_supply_name(index)} voltage limits: Max V must be greater "
                f"than or equal to Min V ({candidate['min_voltage_v']:g}V).",
                show_dialogs
            )
            return False

        self.warning_limits[supply_key] = candidate
        self._refresh_warning_limit_display(index, field)
        self.refresh_warning_indicators(index)

        if persist and not save_beam_energy_warning_limits(self.warning_limits, logger=self.logger):
            message = f"{context}: value was updated for this session but could not be saved."
            self.log(message, LogLevel.WARNING)
            if show_dialogs:
                messagebox.showwarning("Save Failed", message)

        return True

    def set_beams_estop_current_limit(self):
        """UI callback for committing the +20kV Beams E-STOP current limit."""
        raw_value = self.beams_estop_current_entry_var.get()
        if self._set_beams_estop_current_limit_from_raw(raw_value):
            self.beams_estop_current_entry_var.set("")

    def _set_beams_estop_current_limit_from_raw(self, raw_value, show_dialogs=True, persist=True):
        context = self._beams_estop_current_limit_context()
        unit = self._warning_limit_unit(BEAMS_ESTOP_CURRENT_FIELD)
        new_value = self._parse_warning_limit_value(
            raw_value,
            context,
            unit,
            show_dialogs=show_dialogs,
        )
        if new_value is None:
            return False

        max_allowed = DEFAULT_WARNING_LIMITS[POS20KV_SUPPLY_KEY][BEAMS_ESTOP_CURRENT_FIELD]
        if new_value > max_allowed:
            self._show_warning_limit_error(
                "Invalid Input",
                f"{context}: value must be between 0mA and {max_allowed:g}mA.",
                show_dialogs,
            )
            return False

        limits = self.warning_limits[POS20KV_SUPPLY_KEY]
        # Keep the warning threshold at or below the Estop threshold.
        if new_value < limits["max_current_ma"]:
            self._show_warning_limit_error(
                "Invalid Current Range",
                f"{context}: must be greater than or equal to the Max I current "
                f"limit ({limits['max_current_ma']:g}mA).",
                show_dialogs,
            )
            return False

        candidate = dict(limits)
        candidate[BEAMS_ESTOP_CURRENT_FIELD] = new_value
        self.warning_limits[POS20KV_SUPPLY_KEY] = candidate
        self._refresh_beams_estop_current_display()
        self.refresh_warning_indicators(self._get_pos20kv_index())

        if persist and not save_beam_energy_warning_limits(self.warning_limits, logger=self.logger):
            message = f"{context}: value was updated for this session but could not be saved."
            self.log(message, LogLevel.WARNING)
            if show_dialogs:
                messagebox.showwarning("Save Failed", message)

        return True

    def _show_warning_limit_error(self, title, message, show_dialogs):
        self.log(message, LogLevel.ERROR)
        if show_dialogs:
            messagebox.showerror(title, message)

    def _coerce_reading(self, value):
        if value is None:
            return None
        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(numeric_value):
            return None
        return numeric_value

    def _comparison_value(self, supply_key, value):
        if value is None:
            return None
        return abs(value) if supply_key == "neg1kv" else value

    def _trigger_beams_estop_current(self, current_ma, limit_ma):
        self.log(
            "+20kV Bertan automatic Beams E-STOP: actual current "
            f"{current_ma:.3f}mA exceeded E-STOP limit {limit_ma:g}mA.",
            LogLevel.CRITICAL,
        )

        callback = getattr(self, "beams_estop_callback", None)
        if not callable(callback):
            self.log("Automatic Beams E-STOP callback is not configured.", LogLevel.ERROR)
            return

        try:
            callback()
        except Exception as e:
            self.log(f"Automatic Beams E-STOP callback failed: {e}", LogLevel.ERROR)

    def set_beams_estop_callback(self, callback):
        """Register the dashboard's Beams E-STOP handler."""
        self.beams_estop_callback = callback
        pos20kv_index = self._get_pos20kv_index()

        def _recheck():
            self.refresh_warning_indicators(pos20kv_index)

        # A reading may already exist by the time Dashboard wires the callback.
        try:
            self.parent_frame.after(0, _recheck)
        except Exception:
            _recheck()

    def set_radiation_indicator_callback(self, callback):
        """Register callback(active) for the Laser Monitor radiation indicator."""
        self.radiation_indicator_callback = callback
        self._radiation_indicator_sent = None
        self._update_radiation_indicator(
            self.latest_actual_voltage_values[self._get_pos20kv_index()]
        )

    def _update_radiation_indicator(self, voltage):
        # Missing/invalid +20kV readback clears the indicator; valid readings
        # at or above the threshold assert it.
        voltage = self._coerce_reading(voltage)
        active = (
            voltage is not None
            and voltage >= self.RADIATION_INDICATOR_THRESHOLD_V
        )
        if active == getattr(self, "_radiation_indicator_sent", None):
            return

        callback = getattr(self, "radiation_indicator_callback", None)
        if not callable(callback):
            return

        try:
            callback(active)
            self._radiation_indicator_sent = active
        except Exception as e:
            self.log(f"Radiation indicator callback failed: {e}", LogLevel.ERROR)

    def _log_warning_breach(self, index, reading_type, value):
        if value is None:
            return

        supply_key = self._get_supply_key(index)
        supply_name = self.power_supplies[index]["name"]
        limits = self.warning_limits[supply_key]
        absolute_prefix = "absolute " if supply_key == "neg1kv" else ""

        if reading_type == "voltage":
            self.log(
                f"Beam Energy warning: {supply_name} {absolute_prefix}actual voltage "
                f"{value:.2f}V outside configured range "
                f"{limits['min_voltage_v']:g}V to {limits['max_voltage_v']:g}V.",
                LogLevel.WARNING,
            )
        else:
            self.log(
                f"Beam Energy warning: {supply_name} {absolute_prefix}actual current "
                f"{value:.3f}mA exceeds configured max "
                f"{limits['max_current_ma']:g}mA.",
                LogLevel.WARNING,
            )

    def _set_actual_display_color(self, index, element_name, color):
        if index < len(self.ui_elements) and self.ui_elements[index]:
            self.ui_elements[index][element_name].config(foreground=color)

    def apply_warning_indicators(self, index, voltage, current):
        """Update main-tab Actual Voltage/Current colors from numeric readings."""
        voltage = self._coerce_reading(voltage)
        current = self._coerce_reading(current)
        self.latest_actual_voltage_values[index] = voltage
        self.latest_actual_current_values[index] = current

        supply_key = self._get_supply_key(index)
        if supply_key == POS20KV_SUPPLY_KEY:
            self._update_radiation_indicator(voltage)

        limits = self.warning_limits[supply_key]
        voltage_value = self._comparison_value(supply_key, voltage)
        current_value = self._comparison_value(supply_key, current)

        voltage_warning = (
            voltage_value is not None
            and (
                voltage_value < limits["min_voltage_v"]
                or voltage_value >= limits["max_voltage_v"]
            )
        )
        current_warning = (
            current_value is not None
            and current_value >= limits["max_current_ma"]
        )
        current_estop = (
            supply_key == POS20KV_SUPPLY_KEY
            and current_value is not None
            and current_value >= limits[BEAMS_ESTOP_CURRENT_FIELD]
        )

        if voltage_warning:
            self._log_warning_breach(index, "voltage", voltage_value)
        # For 20kV: the E-STOP threshold takes priority over the Max I warning.
        if current_estop:
            self._trigger_beams_estop_current(
                current_value,
                limits[BEAMS_ESTOP_CURRENT_FIELD],
            )
        if current_warning and not current_estop:
            self._log_warning_breach(index, "current", current_value)

        voltage_color = (
            self.WARNING_TEXT_COLOR
            if voltage_warning
            else self.NORMAL_TEXT_COLOR
        )
        if current_estop:
            current_color = self.ESTOP_TEXT_COLOR
        elif current_warning:
            current_color = self.WARNING_TEXT_COLOR
        else:
            current_color = self.NORMAL_TEXT_COLOR
        self._set_actual_display_color(index, "voltage_display", voltage_color)
        self._set_actual_display_color(index, "current_display", current_color)

    def refresh_warning_indicators(self, index):
        self.apply_warning_indicators(
            index,
            self.latest_actual_voltage_values[index],
            self.latest_actual_current_values[index],
        )

    def create_power_supply_displays(self, frame, ps_config, index):
        """
        Create read-only displays for individual power supply.
        
        Args:
            frame: Frame to contain the displays
            ps_config: Power supply configuration dict
            index: Index of the power supply, 1 through 4
        """
        indicator_frame = ttk.Frame(frame)
        indicator_frame.pack(fill=tk.X, pady=(0, 5))
        indicator_frame.grid_columnconfigure(0, weight=1)

        def add_indicator_row(row_index, label_text, color_var):
            row_frame = ttk.Frame(indicator_frame)
            row_frame.grid(row=row_index, column=0, sticky="w")

            label = ttk.Label(row_frame, text=label_text, font=("Segoe UI", 8))
            label.pack(side=tk.LEFT)
            canvas, oval = self.create_indicator_circle(row_frame, color=color_var.get())
            canvas.pack(side=tk.LEFT, padx=(4, 0))

            def update_circle(*args):
                canvas.itemconfig(oval, fill=color_var.get())

            color_var.trace_add("write", update_circle)
            canvas.itemconfig(oval, fill=color_var.get())
            return label

        def add_indicator_spacer(row_index):    # 20kV Bertan filler spacer under Comms label
            row_frame = ttk.Frame(indicator_frame)
            row_frame.grid(row=row_index, column=0, sticky="w")
            ttk.Label(row_frame, text=" ", font=("Segoe UI", 8)).pack(side=tk.LEFT)
            spacer = ttk.Frame(row_frame, width=16, height=16)
            spacer.pack(side=tk.LEFT, padx=(4, 0))
            spacer.pack_propagate(False)

        def add_bottom_indicator_row(parent, row_index, label_text, color_var):
            row_frame = ttk.Frame(parent)
            row_frame.grid(row=row_index, column=0, sticky="w")

            ttk.Label(row_frame, text=label_text, font=("Segoe UI", 8)).pack(side=tk.LEFT)
            canvas, oval = self.create_indicator_circle(row_frame, color=color_var.get())
            canvas.pack(side=tk.LEFT, padx=(4, 0))

            def update_circle(*args):
                canvas.itemconfig(oval, fill=color_var.get())

            color_var.trace_add("write", update_circle)
            canvas.itemconfig(oval, fill=color_var.get())

        connection_label = add_indicator_row(0, "Comms:", self.connection_status_colors[index])

        if index < 2:   # For the Matsusadas
            add_indicator_row(1, "Overcurrent:", self.reset_status_colors[index])
        elif index == 3: #For the 3kV Bertan, show forced-off status
            add_indicator_row(1, "Forced Off:", self.forced_off_color)
        else:
            add_indicator_spacer(1)
        
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

        interlock_frame = ttk.Frame(frame)
        interlock_frame.pack(fill=tk.X, pady=(2, 0))
        interlock_frame.grid_columnconfigure(0, weight=1)

        add_bottom_indicator_row(
            interlock_frame,
            0,
            "Voltage Interlock:",
            self.voltage_interlock_colors[index],
        )
        add_bottom_indicator_row(
            interlock_frame,
            1,
            "Current Interlock:",
            self.current_interlock_colors[index],
        )
        
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

        controller = self.knob_box_controller
        if controller and getattr(controller, "port", None) != port:
            controller.disconnect()
            time.sleep(.2)
            controller = None

        if controller is None:
            controller = KnobBoxModbus(port=port, logger=self.logger)
            self.knob_box_controller = controller

        if time.time() < getattr(controller, "_next_connect_time", 0.0):
            return False

        try:
            self.log(f"Attempting to connect to KnobBox Modbus controller on port {port}...", LogLevel.DEBUG)
            if controller.connect():  # Initializes connection with RS-485 in KnobBoxModbus class
                self.log(f"KnobBox Modbus controller CONNECTED on port {port}", LogLevel.DEBUG)
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
        if index == 3:  # Only 3kV Bertan has forced off status
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

    def update_supply_interlock_status(self, index, voltage_flag=None, current_flag=None, connected=False):
        """Update per-supply voltage/current comparator interlock indicators."""
        if index >= len(self.power_supplies):
            return

        def flag_color(flag):
            if not connected or flag is None:
                return "white"
            return "red" if bool(flag) else "green"

        self.voltage_interlock_colors[index].set(flag_color(voltage_flag))
        self.current_interlock_colors[index].set(flag_color(current_flag))

    def update_supply_interlock_statuses(self, data_snapshot, knob_box):
        """Update all per-supply comparator interlock indicators from logic flags."""
        global_unit_id = 4
        global_data = (
            data_snapshot.get(global_unit_id)
            if knob_box.get_unit_connection_status(global_unit_id)
            else None
        )

        for index, supply_key in enumerate(self.supply_keys):
            unit_id = index + 1
            connected = (
                bool(knob_box.get_unit_connection_status(unit_id))
                and data_snapshot.get(unit_id) is not None
                and global_data is not None
            )
            voltage_flag_key, current_flag_key = self.supply_interlock_flag_map[supply_key]
            self.update_supply_interlock_status(
                index,
                global_data.get(voltage_flag_key) if global_data else None,
                global_data.get(current_flag_key) if global_data else None,
                connected=connected,
            )

        self.update_interlock_log(global_data)

    def update_interlock_log(self, data):
        """Append observed comparator interlock trips to the log display."""
        if not data:
            return

        if bool(data.get("nomop_flag", 0)):
            self.clear_interlock_log()
            return

        for flag_key, message in self.interlock_log_entries:
            if bool(data.get(flag_key, 0)):
                self.interlock_log_var_by_flag[flag_key].set(message)

    def clear_interlock_log(self):
        """Clear all displayed comparator interlock trip messages."""
        for interlock_log_var in self.interlock_log_vars:
            interlock_log_var.set("")

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
                # Disconnect and schedule a reconnect if any polling error.
                self.knob_box_connected = False
                self.knob_box_connected_at = None
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

    def _get_reconnect_wait_time(self):
        """Return remaining seconds until the next reconnect is allowed by controller backoff."""
        controller = self.knob_box_controller
        if not controller:
            return 0.0

        next_connect_time = getattr(controller, "_next_connect_time", 0.0) or 0.0
        return max(0.0, next_connect_time - time.time())

    def _process_reconnect_request(self):
        """
        Main-thread reconnect dispatcher; safe place to start reconnect workers.
        """
        if not self.reconnect_requested.is_set():
            return False

        wait_time = self._get_reconnect_wait_time()
        if wait_time > 0.0:
            return False

        with self.data_lock:
            if self.reconnect_in_progress.is_set():
                return False
            self.reconnect_requested.clear()
            self.reconnect_in_progress.set()

        self._safe_reconnect()
        return True

    def _schedule_reconnect(self):
        """Thread-safe reconnect request; actual dispatch runs on the Tk main loop."""
        if self.reconnect_in_progress.is_set():
            return False
        self.reconnect_requested.set()
        return True

    def _build_disconnected_beam_energy_payload(self):
        """Build a Web Monitor payload that explicitly clears every Beam Energy supply."""
        supplies = {
            supply_key: {
                "connected": False,
                "output": None,
                "set_v": None,
                "meas_v": None,
                "meas_i": None,
            }
            for supply_key, _unit_id in self.supply_payload_map
        }
        flags = {key: None for key in self.beam_energy_flag_keys}
        return {**supplies, "flags": flags}

    def _publish_disconnected_beam_energy_payload(self):
        """Publish disconnected Beam Energy state before leaving a communication-loss path."""
        if self.logger and hasattr(self.logger, "update_field"):
            try:
                self.logger.update_field(
                    "beam_energy",
                    self._build_disconnected_beam_energy_payload()
                )
            except Exception as e:
                self.log(
                    f"Failed to publish disconnected Beam Energy payload: {e}",
                    LogLevel.ERROR
                )

    def _format_power_supply_display_values(self, unit_id, v_set, v_read, i_read):
        """Format one power supply's readbacks for the dashboard display."""
        actual_current = f"{i_read:.2f} mA" if i_read is not None else "-- mA"

        match unit_id:
            case 1:  # +1kV Matsusada
                set_voltage = f"{v_set:.0f} V" if v_set is not None else "-- V"
                actual_voltage = f"{v_read:.0f} V" if v_read is not None else "-- V"
            case 2:  # -1kV Matsusada
                set_voltage = f"{-abs(v_set):.0f} V" if v_set is not None else "-- V"
                actual_voltage = f"{-abs(v_read):.0f} V" if v_read is not None else "-- V"
            case 3:  # +20kV Bertan
                set_voltage = f"{v_set / 1000:.2f} kV" if v_set is not None else "-- kV"
                actual_voltage = f"{v_read / 1000:.2f} kV" if v_read is not None else "-- kV"
                actual_current = f"{i_read:.3f} mA" if i_read is not None else "-- mA"
            case 4:  # +3kV Bertan
                set_voltage = f"{v_set:.0f} V" if v_set is not None else "-- V"
                actual_voltage = f"{v_read:.0f} V" if v_read is not None else "-- V"
            case _:
                set_voltage = f"{v_set:.0f} V" if v_set is not None else "-- V"
                actual_voltage = f"{v_read:.0f} V" if v_read is not None else "-- V"

        return set_voltage, actual_voltage, actual_current

    def _build_supplies_payload(self, knob_box, data_snapshot):
        """Build a structured payload of 4 power supply statuses for the Web Monitor."""
        supplies = {}

        for supply_key, unit_id in self.supply_payload_map:
            connected = bool(knob_box.get_unit_connection_status(unit_id))
            data = data_snapshot.get(unit_id) if connected else None
            sign = -1.0 if unit_id == 2 else 1.0  # make -1kV supply signed

            output = bool(data_snapshot.get(unit_id, {}).get("hv_enable", False)) if data else None

            set_v = data.get("set_voltage_V") if data else None
            meas_v = data.get("actual_voltage_V") if data else None
            meas_i = data.get("actual_current_mA") if data else None

            supplies[supply_key] = {
                "connected": connected,
                "output": output,
                "set_v": (sign * float(set_v)) if set_v is not None else None,
                "meas_v": (sign * float(meas_v)) if meas_v is not None else None,
                "meas_i": float(meas_i) if meas_i is not None else None,
            }

        return supplies

    def update_readings(self):
        """
        Update voltage and current readings from hardware.
        This method should be called periodically to refresh displays.
        """
        # Drain reconnect requests on the Tk main thread.
        self._process_reconnect_request()

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
                    self._publish_disconnected_beam_energy_payload()
                    self._schedule_reconnect()
                    self._process_reconnect_request()
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
                self._publish_disconnected_beam_energy_payload()
                self._schedule_reconnect()
                self._process_reconnect_request()
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
                set_voltage, actual_voltage, actual_current = self._format_power_supply_display_values(
                    unit_id, v_set, v_read, i_read
                )
                self.set_voltages[index].set(set_voltage)
                self.actual_voltages[index].set(actual_voltage)
                self.actual_currents[index].set(actual_current)

                self.apply_warning_indicators(index, v_read, i_read)

                # Update indicators based on data 
                interlocks = not nomop_flag # 1 for Nom Op, 0 for interlocks active
                self.update_indicators_panel(index, arm_beams, ccs_power, arm_80kV, logic_alive, interlocks)
                self.update_output_status(index, hv_enable)
                self.update_reset_status(index, reset_state)
                self.update_connection_status(index, comms)
                self.update_forced_off_status(index, reset_counter_3kv > 0)

            self.update_supply_interlock_statuses(data_snapshot, knob_box)
            
            # Build a web monitor log payload
            if self.logger and hasattr(self.logger, "update_field"):

                # Build keyed per-supply payload entries.
                supply_payload = self._build_supplies_payload(knob_box, data_snapshot)

                # All flags come from the 3kV monitoring arduino
                global_unit_id = 4
                global_data = (
                    data_snapshot.get(global_unit_id)
                    if knob_box.get_unit_connection_status(global_unit_id)
                    else None
                )
                flags = {
                    key: (int(bool(global_data.get(key, 0))) if global_data else None)
                    for key in self.beam_energy_flag_keys
                }

                # Update the Web Monitor log with the latest data and flags.
                self.logger.update_field("beam_energy", {**supply_payload, "flags": flags})


        except Exception as e:  
            self.log(f"Error updating readings: {str(e)}", LogLevel.ERROR)
            for index, _ in enumerate(self.power_supplies): 
                self.set_default_values(index)
            self._publish_disconnected_beam_energy_payload()
            self._schedule_reconnect()
            self._process_reconnect_request()
            
        
        # Schedule next update after 500 ms
        self.after_id = self.parent_frame.after(500, self.update_readings) 

    def cancel_updates(self):
        """Cancel scheduled updates when closing the application."""
        if hasattr(self, 'after_id'):
            self.parent_frame.after_cancel(self.after_id)

    def set_default_values(self, index):
        """Set display values to default '--'."""
        unit_id = index + 1
        set_voltage, actual_voltage, actual_current = self._format_power_supply_display_values(
            unit_id, None, None, None
        )
        self.set_voltages[index].set(set_voltage)
        self.actual_voltages[index].set(actual_voltage)
        self.actual_currents[index].set(actual_current)
        self.apply_warning_indicators(index, None, None)
        self.update_connection_status(index, False)
        self.update_output_status(index, False)
        self.update_reset_status(index, False)
        self.update_supply_interlock_status(index, connected=False)
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
