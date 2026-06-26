import math
import os
import subprocess
import sys
import time
import tkinter as tk
from tkinter import messagebox, ttk

import serial.tools.list_ports

from usr.main_control_config import (
    BEAMS_ESTOP_CURRENT_LIMIT_MAX_MA,
    BEAMS_ESTOP_CURRENT_LIMIT_MIN_MA,
    DEFAULT_VTRX_CCS_DISABLE_GRACE_PERIOD_S,
    load_beams_estop_current_limit_ma,
    load_total_max_emission_current,
    load_vtrx_ccs_disable_grace_period_s,
    save_beams_estop_current_limit_ma,
    save_total_max_emission_current,
    save_vtrx_ccs_disable_grace_period_s,
)
from utils import LogLevel, SetupScripts


CHANNEL_LABELS = ("A", "B", "C")
BEAM_OUTPUT_ON_COLOR = "green"
BEAM_OUTPUT_LOW_COLOR = "#70A070"
BEAM_OUTPUT_OFF_COLOR = "#383838"
BEAM_ACTION_FAILURE_COLOR = "red"
BEAM_ACTION_NEUTRAL_COLOR = "#383838"
PULSE_TRAIN_OUTPUT_ALIAS_MIN_DURATION_MS = 1000
VTRX_BEAM_DISABLE_PRESSURE_LIMIT_MBAR = 1e-5
VTRX_CCS_DISABLE_PRESSURE_LIMIT_MBAR = 1e-5
VTRX_CCS_DISABLE_WARNING_INTERVAL_S = 10.0


def channel_label(index: int) -> str:
    """Return the UI-facing pulser channel label for a 0-based index."""
    if 0 <= index < len(CHANNEL_LABELS):
        return CHANNEL_LABELS[index]
    return str(index + 1)


def channel_name(index: int) -> str:
    """Return a verbose UI-facing pulser channel name for a 0-based index."""
    return f"Channel {channel_label(index)}"


def _safe_widget_config(widget, **kwargs):
    """Best-effort Tk widget config for optional or test-created widgets."""
    if widget is None:
        return
    try:
        widget.config(**kwargs)
    except Exception:
        pass


class MainControlPanel:
    """Main Control subpanel and coordinator for beam-related dashboard actions."""

    def __init__(
        self,
        parent_frame,
        root,
        logger,
        messages_frame,
        get_com_ports,
        save_layout_callback,
        update_com_ports_callback,
        toggle_on_image=None,
        toggle_off_image=None,
    ):
        self.parent_frame = parent_frame
        self.root = root
        self.logger = logger
        self.messages_frame = messages_frame
        self._get_com_ports_callback = get_com_ports
        self.save_layout_callback = save_layout_callback
        self.update_com_ports_callback = update_com_ports_callback
        self.toggle_on_image = toggle_on_image
        self.toggle_off_image = toggle_off_image
        self.subsystems = {}
        self.com_ports = self._get_com_ports()
        self.disable_ccs_output_on_bcon_disconnect = True
        self.disable_beams_on_vtrx_pressure_exceeded = True
        # Treat startup as already disabled until VTRX reports a safe pressure.
        self._vtrx_pressure_beam_disable_latched = True
        self._last_vtrx_pressure_mbar = None
        self.pressure_reading_is_fresh = False
        self.vtrx_ccs_disable_grace_period_s = self._coerce_vtrx_ccs_disable_grace_period_s(
            load_vtrx_ccs_disable_grace_period_s(logger=self.logger)
        )
        self._vtrx_ccs_disable_timer_started_at = None
        self._vtrx_ccs_disable_last_warning_at = None
        self.disable_knob_box_logging_when_hvolt_off = True
        self.disable_bcon_logging_when_hvolt_off = True
        self.disable_ccs_logging_when_ccs_power_off = True
        self._setting_checkbutton_vars = {}
        self._value_setting_controls = {}
        self.vtrx_ccs_pressure_shutdown_enabled = True
        self.total_max_emission_current_limit_enabled = True
        self.beams_estop_current_limit_enabled = True

        self.total_max_emission_current_ma = load_total_max_emission_current(logger=self.logger)
        self.total_max_emission_current_entry_var = tk.StringVar(value="")
        self.total_max_emission_current_value_var = tk.StringVar(
            value=f"{self.total_max_emission_current_ma:g}"
        )
        self.beams_estop_current_limit_ma = load_beams_estop_current_limit_ma(logger=self.logger)
        self.beams_estop_current_entry_var = tk.StringVar(value="")
        self.beams_estop_current_value_var = tk.StringVar(
            value=f"{self.beams_estop_current_limit_ma:g}"
        )
        self.total_max_emission_current_title_var = tk.StringVar(value="")
        self.beams_estop_current_limit_title_var = tk.StringVar(value="")
        self.vtrx_ccs_disable_grace_period_entry_var = tk.StringVar(value="")
        self.vtrx_ccs_disable_grace_period_title_var = tk.StringVar(value="")
        self.vtrx_ccs_disable_grace_period_value_var = tk.StringVar(
            value=f"{self.vtrx_ccs_disable_grace_period_s:g}"
        )
        self.refresh_value_setting_displays()
        self._initialize_main_control_beam_status_state()
        self.create_main_control_notebook(parent_frame)

    def _get_com_ports(self):
        if callable(getattr(self, "_get_com_ports_callback", None)):
            try:
                return self._get_com_ports_callback() or {}
            except Exception:
                return {}
        return getattr(self, "com_ports", {})

    def save_current_pane_state(self):
        if callable(self.save_layout_callback):
            self.save_layout_callback()

    def _log_info(self, message):
        self.logger.info(message, tag="Main Control")

    def _log_warning(self, message):
        self.logger.warning(message, tag="Main Control")

    def _log_error(self, message):
        self.logger.error(message, tag="Main Control")

    def _log_critical(self, message):
        self.logger.critical(message, tag="Main Control")

    def update_com_ports(self, new_com_ports):
        self.com_ports = new_com_ports
        if callable(self.update_com_ports_callback):
            self.update_com_ports_callback(new_com_ports)

    def wire_beam_energy(self, beam_energy):
        """Register the Beam Energy +20kV current E-stop callback."""
        if beam_energy is not None and hasattr(beam_energy, "set_beams_estop_callback"):
            beam_energy.set_beams_estop_callback(
                lambda: self.handle_beams_off(
                    "20kV E-Stop Current Limit exceeded: All Beams Disabled"
                )
            )
        self._apply_beams_estop_current_limit_to_beam_energy(beam_energy)
        self.refresh_beams_estop_current_limit_display()
        self._apply_logging_suppression_settings()

    def wire_vtrx(self, vtrx):
        """Register the VTRX pressure update callback."""
        if vtrx is None:
            return

        setter = getattr(vtrx, "set_pressure_update_callback", None)
        if callable(setter):
            setter(self._handle_vtrx_pressure_update)
        else:
            self._log_error("VTRX pressure update callback was not wired: API not available")

    def wire_beam_pulse(self, beam_pulse):
        """Wire Beam Pulse callbacks and providers."""
        if beam_pulse is None:
            return

        if hasattr(beam_pulse, "set_channel_status_callback"):
            beam_pulse.set_channel_status_callback(self._on_channel_status_update)
        if hasattr(beam_pulse, "set_action_feedback_callback"):
            beam_pulse.set_action_feedback_callback(self._handle_action_feedback)
        if hasattr(beam_pulse, "set_channel_enable_status_callback"):
            beam_pulse.set_channel_enable_status_callback(self._on_channel_enable_status_update)
        if hasattr(beam_pulse, "set_armed_status_callback"):
            beam_pulse.set_armed_status_callback(self._on_armed_status_update)
        if hasattr(beam_pulse, "set_emission_limit_providers"):
            beam_pulse.set_emission_limit_providers(
                lambda: self.total_max_emission_current_ma,
                self._get_predicted_emission_currents_for_beam_pulse,
                lambda: self.total_max_emission_current_limit_enabled,
            )
        else:
            self._log_error("Beam Pulse emission limit providers were not wired: API not available")
        if hasattr(beam_pulse, "set_vtrx_pressure_guard_providers"):
            beam_pulse.set_vtrx_pressure_guard_providers(
                lambda: self.disable_beams_on_vtrx_pressure_exceeded,
                lambda: self._last_vtrx_pressure_mbar,
                lambda: VTRX_BEAM_DISABLE_PRESSURE_LIMIT_MBAR,
                lambda: self.pressure_reading_is_fresh,
            )
        else:
            self._log_error("Beam Pulse VTRX pressure guard providers were not wired: API not available")
        if hasattr(beam_pulse, "set_manual_disconnect_callback"):
            beam_pulse.set_manual_disconnect_callback(self._confirm_manual_bcon_disconnect)
        else:
            self._log_error("Beam Pulse manual disconnect callback was not wired: API not available")
        if hasattr(beam_pulse, "set_disconnect_callback"):
            beam_pulse.set_disconnect_callback(self._handle_bcon_disconnected)
        else:
            self._log_error("Beam Pulse disconnect callback was not wired: API not available")
        cathode = getattr(self, "subsystems", {}).get("Cathode Heating")
        if cathode is not None:
            cathode.disable_ccs_output_on_bcon_disconnect = (
                self.disable_ccs_output_on_bcon_disconnect
            )
            cathode.vtrx_ccs_pressure_allows_output = (
                self._vtrx_ccs_pressure_output_status
            )
            if callable(getattr(beam_pulse, "is_connected", None)):
                cathode.bcon_is_connected = beam_pulse.is_connected
        self._apply_logging_suppression_settings()

    def _get_predicted_emission_currents_for_beam_pulse(self):
        cathode = getattr(self, "subsystems", {}).get("Cathode Heating")
        getter = getattr(cathode, "get_predicted_emission_currents_ma", None)
        if not callable(getter):
            raise RuntimeError("Cathode Heating predicted emission current provider unavailable")
        return getter()

    def _get_hvolt_on(self):
        interlocks = getattr(self, "subsystems", {}).get("Interlocks")
        return bool(getattr(interlocks, "hvolt_on", False))

    def _get_ccs_power_on(self):
        beam_energy = getattr(self, "subsystems", {}).get("Beam Energy")
        return bool(getattr(beam_energy, "ccs_power_on", False))

    def _apply_logging_suppression_settings(self):
        subsystems = getattr(self, "subsystems", {})
        beam_energy = subsystems.get("Beam Energy")
        if beam_energy is not None and hasattr(beam_energy, "set_logging_suppression"):
            beam_energy.set_logging_suppression(
                self.disable_knob_box_logging_when_hvolt_off,
                self._get_hvolt_on,
            )

        beam_pulse = subsystems.get("Beam Pulse")
        if beam_pulse is not None and hasattr(beam_pulse, "set_logging_suppression"):
            beam_pulse.set_logging_suppression(
                self.disable_bcon_logging_when_hvolt_off,
                self._get_hvolt_on,
            )

        cathode = subsystems.get("Cathode Heating")
        if cathode is not None and hasattr(cathode, "set_logging_suppression"):
            cathode.set_logging_suppression(
                self.disable_ccs_logging_when_ccs_power_off,
                self._get_ccs_power_on,
            )

    def create_main_control_notebook(self, frame):
        notebook = ttk.Notebook(frame)
        notebook.pack(expand=True, fill='both')

        main_tab = ttk.Frame(notebook)
        config_tab = ttk.Frame(notebook)

        notebook.add(main_tab, text='Main')
        notebook.add(config_tab, text='Config')

        main_frame = ttk.Frame(main_tab, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Add safety beams off button (bottom)
        beams_off_button = tk.Button(
            main_frame,
            text="E-STOP: BEAMS & CCS",
            bg="red",
            fg="white",
            font=("Helvetica",14,"bold"),
            command=self.handle_beams_off
        )
        beams_off_button.pack(side="bottom", fill="x", padx=10, pady=2)

        # Script dropdown
        self.create_script_dropdown(main_frame)

        manual_panel = tk.Frame(main_frame)
        manual_panel.pack(side="top", fill="x", padx=10, pady=(10, 0))

        # Beam ON/OFF row.
        buttons_frame = tk.Frame(manual_panel)
        buttons_frame.pack(side="top", fill="x")
        for i in range(3):
            buttons_frame.grid_columnconfigure(i, weight=1, uniform="button")

        self.beam_toggle_buttons = []
        beam_names = ["Beam A OFF", "Beam B OFF", "Beam C OFF"]
        for i, beam_name in enumerate(beam_names):
            btn = tk.Button(
                buttons_frame,
                text=beam_name,
                bg="gray",
                fg="white",
                font=("Helvetica", 10, "bold"),
                state="disabled",  # disabled until armed AND channel enabled
                command=lambda idx=i: self.toggle_individual_beam_with_status(idx)
            )
            btn.grid(row=0, column=i, sticky="ew", padx=2)
            self.beam_toggle_buttons.append(btn)

        # CH Enable/Disable row
        enable_toggle_frame = tk.Frame(manual_panel)
        enable_toggle_frame.pack(side="top", fill="x", pady=(4, 0))
        for i in range(3):
            enable_toggle_frame.grid_columnconfigure(i, weight=1, uniform="button")
        self.enable_toggle_buttons = []
        self._ch_enable_states = [False, False, False]  # dashboard mirror of firmware enable state
        for i in range(3):
            btn = tk.Button(
                enable_toggle_frame,
                text=f"CH {channel_label(i)}: Disabled",
                bg="#888888",
                fg="white",
                font=("Helvetica", 9),
                state="disabled",  # Initially disabled until armed
                command=lambda idx=i: self._toggle_channel_enable(idx)
            )
            btn.grid(row=0, column=i, sticky="ew", padx=2)
            self.enable_toggle_buttons.append(btn)

        beam_action_control_frame = tk.Frame(manual_panel)
        beam_action_control_frame.pack(side="top", fill="x", pady=(4, 0))
        beam_action_control_frame.grid_columnconfigure(0, weight=1, uniform="beam_action")
        beam_action_control_frame.grid_columnconfigure(1, weight=1, uniform="beam_action")

        self.activate_enabled_beams_button = tk.Button(
            beam_action_control_frame,
            text="Activate Enabled Beams",
            bg="#1565C0",
            fg="white",
            font=("Helvetica", 9, "bold"),
            state="disabled",
            command=self.handle_activate_enabled_beams,
        )
        self.activate_enabled_beams_button.grid(row=0, column=0, sticky="ew", padx=(2, 1))

        self.disable_all_beams_button = tk.Button(
            beam_action_control_frame,
            text="Disable All Beams",
            bg="#B71C1C",
            fg="white",
            font=("Helvetica", 9, "bold"),
            state="normal",
            command=self.handle_disable_all_beams,
        )
        self.disable_all_beams_button.grid(row=0, column=1, sticky="ew", padx=(1, 2))

        # Add beams armed toggle
        beams_armed_control_frame = tk.Frame(main_frame)
        beams_armed_control_frame.pack(side="bottom", fill="x", padx=10, pady=(8, 4))

        beams_armed_button_frame = tk.Frame(beams_armed_control_frame)
        beams_armed_button_frame.pack(side=tk.LEFT, anchor=tk.W, padx=(0, 14))

        beams_armed_label_frame = ttk.Frame(beams_armed_button_frame)
        beams_armed_label_frame.pack(anchor=tk.CENTER, pady=(0, 2))
        ttk.Label(beams_armed_label_frame, text="BEAMS ARMED", font=("Helvetica", 12, "bold")).pack()

        if self.toggle_on_image and self.toggle_off_image:
            self.beams_ready_button = tk.Button(
                beams_armed_button_frame,
                image=self.toggle_off_image,
                command=self.handle_arm_beams,
                relief=tk.FLAT,
                bd=0,
                bg="white"
            )
        else:
            self.beams_ready_button = tk.Button(
                beams_armed_button_frame,
                text="ARM BEAMS",
                bg="sky blue",
                fg="white",
                font=("Helvetica",16,"bold"),
                command=self.handle_arm_beams
            )
        self.beams_ready_button.pack(anchor=tk.CENTER)

        self.create_beam_output_status_panel(beams_armed_control_frame)

        config_frame = ttk.Frame(config_tab, padding="10")
        config_frame.pack(fill=tk.BOTH, expand=True)

        section_frame = ttk.Frame(config_frame)
        section_frame.pack(side=tk.TOP, anchor='nw', fill=tk.X)

        general_frame = ttk.LabelFrame(section_frame, text="General", padding=2)
        general_frame.pack(side=tk.LEFT, anchor='nw', padx=(0, 12))

        log_settings_frame = ttk.LabelFrame(
            section_frame,
            text="Log Settings",
            padding= 2,
        )

        beam_cathode_frame = ttk.LabelFrame(
            section_frame,
            text="Beam and Cathode Shutoff Settings",
            padding= 2,
        )
        beam_cathode_frame.pack(side=tk.LEFT, anchor='nw', padx=(0, 12))
        log_settings_frame.pack(side=tk.LEFT, anchor='nw',)

        self.create_com_port_frame(general_frame)

        save_layout_frame = ttk.Frame(general_frame)
        save_layout_frame.pack(side=tk.TOP, anchor='nw', pady=5)
        ttk.Button(
            save_layout_frame,
            text="Save Layout",
            command=self.save_current_pane_state
        ).pack(side=tk.LEFT, padx=5)

        self.create_post_processor_button(general_frame)

        self.create_log_level_dropdown(log_settings_frame)
        self.file_create_log_level_dropdown(log_settings_frame)
        self.create_logging_suppression_toggles(log_settings_frame)

        self._create_setting_checkbutton(
            beam_cathode_frame,
            "Disable CCS Output on BCON Disconnect",
            "disable_ccs_output_on_bcon_disconnect",
            self.toggle_disable_ccs_output_on_bcon_disconnect,
        )
        self._create_setting_checkbutton(
            beam_cathode_frame,
            f"Disable Beams if pressure exceeds {VTRX_BEAM_DISABLE_PRESSURE_LIMIT_MBAR} mbar",
            "disable_beams_on_vtrx_pressure_exceeded",
            self.toggle_disable_beams_on_vtrx_pressure_exceeded,
        )
        self._create_value_setting_controls(
            beam_cathode_frame,
            title_var=self.vtrx_ccs_disable_grace_period_title_var,
            label_text="Grace Period:",
            entry_var=self.vtrx_ccs_disable_grace_period_entry_var,
            unit_text="s",
            command=self.set_vtrx_ccs_disable_grace_period,
            value_var=self.vtrx_ccs_disable_grace_period_value_var,
            enable_setting_attr="vtrx_ccs_pressure_shutdown_enabled",
            enable_command=lambda: self._toggle_value_setting_enabled("vtrx_ccs_pressure_shutdown_enabled"),
        )
        self._create_value_setting_controls(
            beam_cathode_frame,
            title_var=self.total_max_emission_current_title_var,
            label_text="Max Emission I:",
            entry_var=self.total_max_emission_current_entry_var,
            unit_text="mA",
            command=self.set_total_max_emission_current_limit,
            value_var=self.total_max_emission_current_value_var,
            enable_setting_attr="total_max_emission_current_limit_enabled",
            enable_command=lambda: self._toggle_value_setting_enabled("total_max_emission_current_limit_enabled"),
        )
        self._create_value_setting_controls(
            beam_cathode_frame,
            title_var=self.beams_estop_current_limit_title_var,
            label_text="Max 20kV I:",
            entry_var=self.beams_estop_current_entry_var,
            unit_text="mA",
            command=self.set_beams_estop_current_limit,
            value_var=self.beams_estop_current_value_var,
            enable_setting_attr="beams_estop_current_limit_enabled",
            enable_command=lambda: self._toggle_value_setting_enabled("beams_estop_current_limit_enabled"),
        )

        # Add F1 help hint
        help_label = ttk.Label(
            config_frame,
            text="Press F1 for keyboard shortcuts",
            font=("Helvetica", 8, "italic"),
            foreground="gray"
        )
        help_label.pack(side=tk.BOTTOM, anchor='se', padx=5, pady=(10, 5))

    def create_beam_output_status_panel(self, parent_frame):
        """Create compact Beam A/B/C output and latest action status labels."""
        self._initialize_main_control_beam_status_state()
        if not hasattr(self, "beam_output_status_vars"):
            self.beam_output_status_vars = [
                tk.StringVar(value=self._beam_output_status_text[i])
                for i in range(3)
            ]
        if not hasattr(self, "beam_action_status_var"):
            self.beam_action_status_var = tk.StringVar(value=self._beam_action_status_text)
        if not hasattr(self, "beam_action_status_prefix_var"):
            self.beam_action_status_prefix_var = tk.StringVar(value=self._beam_action_status_prefix_text)

        status_frame = ttk.Frame(parent_frame)
        status_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, anchor=tk.W)

        self.beam_output_status_labels = []
        for i, status_var in enumerate(self.beam_output_status_vars):
            label = ttk.Label(
                status_frame,
                textvariable=status_var,
                font=("Segoe UI", 8),
                foreground=self._beam_output_status_colors[i],
                anchor=tk.W,
            )
            label.pack(anchor=tk.W, fill=tk.X)
            self.beam_output_status_labels.append(label)

        self.beam_action_status_frame = ttk.Frame(status_frame)
        self.beam_action_status_frame.pack(anchor=tk.W, fill=tk.X, pady=(2, 0))

        self.beam_action_status_prefix_label = ttk.Label(
            self.beam_action_status_frame,
            textvariable=self.beam_action_status_prefix_var,
            font=("Segoe UI", 8, "bold"),
            foreground=BEAM_ACTION_FAILURE_COLOR,
            anchor=tk.W,
        )
        if self._beam_action_status_prefix_text:
            self.beam_action_status_prefix_label.pack(side=tk.LEFT, anchor=tk.W)

        self.beam_action_status_label = ttk.Label(
            self.beam_action_status_frame,
            textvariable=self.beam_action_status_var,
            font=("Segoe UI", 8, "bold"),
            foreground=self._beam_action_status_color,
            anchor=tk.W,
        )
        self.beam_action_status_label.pack(side=tk.LEFT, anchor=tk.W, fill=tk.X, expand=True)

    def _initialize_main_control_beam_status_state(self):
        """Initialize non-Tk state for Main Control beam status displays."""
        if not hasattr(self, "_beam_output_status_text"):
            self._beam_output_status_text = [
                self._format_beam_output_status(index, None)
                for index in range(3)
            ]
        if not hasattr(self, "_beam_output_status_colors"):
            self._beam_output_status_colors = [BEAM_OUTPUT_OFF_COLOR for _ in range(3)]
        if not hasattr(self, "_beam_action_status_text"):
            self._beam_action_status_text = ""
        if not hasattr(self, "_beam_action_status_prefix_text"):
            self._beam_action_status_prefix_text = ""
        if not hasattr(self, "_beam_action_status_color"):
            self._beam_action_status_color = BEAM_ACTION_NEUTRAL_COLOR
        if not hasattr(self, "_beam_action_status_outcome"):
            self._beam_action_status_outcome = "neutral"

    def _coerce_beam_config(self, config):
        """Normalize a BCON channel config dict for display/state storage."""
        if not isinstance(config, dict):
            return {"mode": "OFF", "duration_ms": 0, "count": 1, "remaining": 0,  "output_level": None}

        mode = str(config.get("mode", "OFF")).strip().upper()
        # Unknown modes are displayed as OFF because they should not imply output.
        if mode not in ("OFF", "DC", "PULSE", "PULSE_TRAIN"):
            mode = "OFF"

        try:
            duration = int(float(config.get("duration_ms", 0) or 0))
        except (TypeError, ValueError):
            duration = 0

        try:
            count = int(float(config.get("count", 1) or 1))
        except (TypeError, ValueError):
            count = 1

        output_level = config.get("output_level", None)
        try:
            output_level_value = float(output_level)
        except (TypeError, ValueError):
            output_level_value = None
        if output_level_value in (0.0, 1.0):
            output_level = int(output_level_value)
        else:
            output_level = None

        remaining = config.get("remaining", config.get("remaining_pulses", None))
        try:
            remaining = None if remaining is None else int(float(remaining))
        except (TypeError, ValueError):
            remaining = None

        if mode in ("OFF", "DC"):
            duration = 0
            count = 1
            remaining = 0
        elif mode == "PULSE":
            # Firmware treats a single pulse as count=1 regardless of GUI input.
            count = 1
        elif mode == "PULSE_TRAIN" and count < 2:
            # Keep status text valid even if a stale or malformed payload arrives.
            count = 2

        if mode == "PULSE_TRAIN":
            if remaining is None:
                remaining = count
            elif remaining < 0:
                remaining = 0

        return {"mode": mode, "duration_ms": duration, "count": count, "remaining": remaining, "output_level": output_level}

    def _beam_on_description(self, config, include_remaining=True):
        """Return the mode-specific phrase used in ON status lines."""
        config = self._coerce_beam_config(config)
        mode = config["mode"]
        if mode == "DC":
            return "running DC"
        if mode == "PULSE":
            return f"running PULSE for {config['duration_ms']}ms"
        if mode == "PULSE_TRAIN":
            text = (
                f"running PULSE_TRAIN: set to {config['count']} pulses"
                f", {config['duration_ms']}ms each"
            )
            if include_remaining: #for lines 1-3, show remaining count if available
                text = f"{text}. Remaining: {config['remaining']}"
                if self._shows_live_pulse_waveform(config):
                    waveform = "high" if config["output_level"] == 1 else "low"
                    text = f"{text} | Pulse waveform={waveform}"
            return text
        return "OFF"

    def _shows_live_pulse_waveform(self, config):
        config = self._coerce_beam_config(config)
        return (
            config["mode"] == "PULSE_TRAIN"
            and config["duration_ms"] >= PULSE_TRAIN_OUTPUT_ALIAS_MIN_DURATION_MS
            and config["output_level"] is not None
        )

    def _beam_output_status_color(self, config, is_output_on):
        if not is_output_on:
            return BEAM_OUTPUT_OFF_COLOR
        config = self._coerce_beam_config(config)
        if self._shows_live_pulse_waveform(config) and config["output_level"] == 0:
            return BEAM_OUTPUT_LOW_COLOR
        return BEAM_OUTPUT_ON_COLOR

    def _is_beam_channel_enabled(self, beam_index):
        states = getattr(self, "_ch_enable_states", None)
        return bool(states and 0 <= beam_index < len(states) and states[beam_index])

    def _format_beam_output_off_status(self, beam_index):
        label = channel_label(beam_index)
        enable_text = "ENABLED" if self._is_beam_channel_enabled(beam_index) else "DISABLED"
        return f"Beam {label} {enable_text}, Output OFF"

    def _beam_output_display_is_on(self, beam_index):
        if not 0 <= beam_index < len(getattr(self, "_beam_output_status_colors", [])):
            return False
        return self._beam_output_status_colors[beam_index] in (
            BEAM_OUTPUT_ON_COLOR,
            BEAM_OUTPUT_LOW_COLOR,
        )

    def _format_beam_output_status(self, beam_index, config=None):
        """Format one Beam A/B/C output line from a normalized sent config."""
        label = channel_label(beam_index)
        config = self._coerce_beam_config(config)
        if config["mode"] == "OFF":
            return self._format_beam_output_off_status(beam_index)
        return f"Beam {label} Output: ON, {self._beam_on_description(config)}"

    def _set_beam_output_display(self, beam_index, config=None, is_on=False):
        """Update one Beam A/B/C output line."""
        self._initialize_main_control_beam_status_state()
        if not 0 <= beam_index < 3:
            return

        config = self._coerce_beam_config(config)
        is_output_on = bool(is_on) and config["mode"] != "OFF"
        text = self._format_beam_output_status(beam_index, config if is_output_on else None)
        color = self._beam_output_status_color(config, is_output_on)

        self._beam_output_status_text[beam_index] = text
        self._beam_output_status_colors[beam_index] = color

        vars_list = getattr(self, "beam_output_status_vars", None)
        if vars_list and beam_index < len(vars_list):
            try:
                vars_list[beam_index].set(text)
            except Exception:
                pass

        labels = getattr(self, "beam_output_status_labels", None)
        if labels and beam_index < len(labels):
            _safe_widget_config(labels[beam_index], foreground=color)

    def _clear_beam_output_display(self, beam_index):
        """Mark one beam output line OFF."""
        self._set_beam_output_display(beam_index, None, is_on=False)

    def _clear_all_beam_output_displays(self):
        """Mark all Beam A/B/C output lines OFF."""
        for beam_index in range(3):
            self._clear_beam_output_display(beam_index)

    def _set_beam_action_status(self, message, outcome="neutral"):
        """Update line 4 with an outcome-colored Main Control action message."""
        self._initialize_main_control_beam_status_state()
        outcome_key = str(outcome).strip().lower()
        message_text = str(message or "")
        is_failure = outcome_key in ("failure", "error")
        is_20kv_estop = (
            outcome_key == "estop"
            and "20kv" in message_text.lower()
            and "current limit" in message_text.lower()
        )
        prefix = "FAILURE: " if is_failure else ""
        color = BEAM_ACTION_FAILURE_COLOR if is_20kv_estop else BEAM_ACTION_NEUTRAL_COLOR

        self._beam_action_status_prefix_text = prefix
        self._beam_action_status_text = message_text
        self._beam_action_status_color = color
        self._beam_action_status_outcome = outcome_key

        action_var = getattr(self, "beam_action_status_var", None)
        if action_var is not None:
            try:
                action_var.set(self._beam_action_status_text)
            except Exception:
                pass

        prefix_var = getattr(self, "beam_action_status_prefix_var", None)
        if prefix_var is not None:
            try:
                prefix_var.set(prefix)
            except Exception:
                pass

        prefix_label = getattr(self, "beam_action_status_prefix_label", None)
        _safe_widget_config(prefix_label, foreground=BEAM_ACTION_FAILURE_COLOR)

        action_label = getattr(self, "beam_action_status_label", None)
        _safe_widget_config(action_label, foreground=color)

        try:
            if prefix_label is not None:
                prefix_label.pack_forget()
            if action_label is not None:
                action_label.pack_forget()
            if prefix and prefix_label is not None:
                prefix_label.pack(side=tk.LEFT, anchor=tk.W)
            if action_label is not None:
                action_label.pack(side=tk.LEFT, anchor=tk.W, fill=tk.X, expand=True)
        except Exception:
            pass

    def _beam_success_message(self, beam_index, config):
        """Build line 4 success text for a beam ON command."""
        return (
            f"Beam {channel_label(beam_index)} successfully set to ON, "
            f"{self._beam_on_description(config, include_remaining=False)}"
        )

    def _format_activate_enabled_beams_message(self, configs):
        parts = []
        for config in configs or []:
            try:
                index = int(config.get("ch")) - 1
            except (TypeError, ValueError, AttributeError):
                continue
            label = channel_label(index)
            mode = str(config.get("mode", "")).strip().upper()
            if mode == "DC":
                parts.append(f"{label}=DC")
            elif mode == "PULSE":
                parts.append(f"{label}=PULSE({config.get('duration_ms')}ms)")
            else:
                parts.append(
                    f"{label}={mode}({config.get('duration_ms')}ms x{config.get('count')})"
                )
        return "Activate Enabled Beams: " + ", ".join(parts) if parts else "Activate Enabled Beams"

    def _handle_action_feedback(self, event_type, message="", outcome="neutral", configs=None):
        """Handle Beam Pulse action feedback for Main Control status displays."""
        if event_type == "beams_sent":
            for config in configs or []:
                try:
                    beam_index = int(config.get("ch")) - 1
                except (TypeError, ValueError, AttributeError):
                    continue
                self._set_beam_output_display(beam_index, config, is_on=True)
            if not message:
                message = self._format_activate_enabled_beams_message(configs)
        elif event_type == "all_off":
            self._clear_all_beam_output_displays()
        elif event_type == "firmware_ack":
            current = getattr(self, "_beam_action_status_text", "")
            current_outcome = getattr(self, "_beam_action_status_outcome", "neutral")
            if current and message:
                message = f"{current} | {message}"
                if current_outcome in ("failure", "error"):
                    outcome = "failure"
                elif current_outcome == "estop":
                    outcome = "estop"
                elif current_outcome == "neutral":
                    outcome = "neutral"

        if message:
            self._set_beam_action_status(message, outcome)

    def create_script_dropdown(self, parent_frame):
        SetupScripts(parent_frame, logger=self.logger)

    def _create_value_setting_controls(
        self,
        parent_frame,
        *,
        label_text,
        entry_var,
        unit_text,
        command,
        value_var,
        title_text=None,
        title_var=None,
        enable_setting_attr=None,
        enable_command=None,
    ):
        section = ttk.Frame(parent_frame)
        section.pack(
            side=tk.TOP,
            anchor='nw',
            fill=tk.X,
            padx=0 if enable_setting_attr is not None else 5,
            pady=2,
        )

        title_row = ttk.Frame(section)
        title_row.pack(anchor=tk.W)

        title_text_options = {}
        if title_var is not None:
            title_text_options["textvariable"] = title_var
        else:
            title_text_options["text"] = title_text or ""

        if enable_setting_attr is not None:
            if not hasattr(self, "_setting_checkbutton_vars"):
                self._setting_checkbutton_vars = {}
            variable = tk.BooleanVar(
                value=bool(getattr(self, enable_setting_attr, True))
            )
            self._setting_checkbutton_vars[enable_setting_attr] = variable
            ttk.Checkbutton(
                title_row,
                variable=variable,
                command=enable_command,
                **title_text_options,
            ).pack(side=tk.LEFT)
        else:
            ttk.Label(
                title_row,
                font=("Segoe UI", 8, "bold"),
                **title_text_options,
            ).pack(side=tk.LEFT)

        row = ttk.Frame(section)
        row.pack(fill=tk.X, padx=(25, 0))

        ttk.Label(row, text=label_text, font=("Segoe UI", 8)).grid(
            row=0,
            column=0,
            sticky=tk.W,
        )
        entry = ttk.Entry(
            row,
            textvariable=entry_var,
            width=7,
        )
        entry.grid(row=0, column=1, sticky=tk.W, padx=(2, 0))
        ttk.Label(row, text=unit_text, font=("Segoe UI", 8)).grid(row=0, column=2, sticky=tk.W)
        button = ttk.Button(
            row,
            text="Set",
            width=4,
            command=command,
        )
        button.grid(row=0, column=3, sticky=tk.W, padx=(4, 0))

        value_frame = tk.Frame(row, bd=1, relief='groove', padx=1, pady=0)
        value_frame.configure(bg='#d9d9d9')
        value_frame.grid(row=0, column=4, sticky=tk.W, padx=(8, 0))
        ttk.Label(
            value_frame,
            textvariable=value_var,
            font=("Segoe UI", 8),
        ).pack(side=tk.LEFT)
        ttk.Label(
            value_frame,
            text=unit_text,
            font=("Segoe UI", 8),
        ).pack(side=tk.LEFT)

        if enable_setting_attr is not None:
            if not hasattr(self, "_value_setting_controls"):
                self._value_setting_controls = {}
            self._value_setting_controls[enable_setting_attr] = (entry, button)
            self._refresh_value_setting_control_state(enable_setting_attr)

    def _coerce_vtrx_ccs_disable_grace_period_s(self, value):
        try:
            duration_s = float(value)
        except (TypeError, ValueError):
            return DEFAULT_VTRX_CCS_DISABLE_GRACE_PERIOD_S

        if not math.isfinite(duration_s) or duration_s < 0:
            return DEFAULT_VTRX_CCS_DISABLE_GRACE_PERIOD_S

        return duration_s

    def _format_beams_estop_current_limit_ma(self, value):
        try:
            limit_ma = float(value)
        except (TypeError, ValueError):
            return "--"

        if not math.isfinite(limit_ma):
            return "--"

        return f"{limit_ma:g}"

    def _apply_beams_estop_current_limit_to_beam_energy(self, beam_energy=None):
        if beam_energy is None:
            beam_energy = getattr(self, "subsystems", {}).get("Beam Energy")
        setter = getattr(beam_energy, "set_beams_estop_current_limit_ma", None)
        if not callable(setter):
            return False

        try:
            setter(self.beams_estop_current_limit_ma)
        except Exception as e:
            self._log_warning(
                f"20kV Bertan Current Limit for E-Stop Trigger: Beam Energy update failed ({e})."
            )
            return False

        enabled_setter = getattr(beam_energy, "set_beams_estop_current_limit_enabled", None)
        if callable(enabled_setter):
            try:
                enabled_setter(bool(getattr(self, "beams_estop_current_limit_enabled", True)))
            except Exception as e:
                self._log_warning(
                    f"20kV Bertan Current Limit for E-Stop Trigger: Beam Energy enable update failed ({e})."
                )
        return True

    def refresh_value_setting_displays(self):
        def _set_var(name, value):
            variable = getattr(self, name, None)
            if variable is not None:
                variable.set(value)

        grace_period_s = self._coerce_vtrx_ccs_disable_grace_period_s(
            getattr(self, "vtrx_ccs_disable_grace_period_s", None)
        )
        total_emission_ma = self._format_beams_estop_current_limit_ma(
            getattr(self, "total_max_emission_current_ma", None)
        )
        beams_estop_ma = self._format_beams_estop_current_limit_ma(
            getattr(self, "beams_estop_current_limit_ma", None)
        )

        _set_var("vtrx_ccs_disable_grace_period_title_var", self._vtrx_ccs_shutdown_title())
        _set_var(
            "vtrx_ccs_disable_grace_period_value_var",
            f"{grace_period_s:g}",
        )
        _set_var("total_max_emission_current_title_var", self._emission_activation_title())
        _set_var(
            "total_max_emission_current_value_var",
            total_emission_ma,
        )
        _set_var("beams_estop_current_limit_title_var", self._beams_estop_title())
        _set_var(
            "beams_estop_current_value_var",
            beams_estop_ma,
        )

    def refresh_beams_estop_current_limit_display(self):
        self.refresh_value_setting_displays()

    def _vtrx_ccs_shutdown_title(self):
        duration_s = self._coerce_vtrx_ccs_disable_grace_period_s(
            getattr(self, "vtrx_ccs_disable_grace_period_s", None)
        )
        return (
            f"Disable CCS Output if pressure exceeds "
            f"{VTRX_CCS_DISABLE_PRESSURE_LIMIT_MBAR:g} mbar for {duration_s:g}s"
        )

    def _emission_activation_title(self):
        limit_ma = self._format_beams_estop_current_limit_ma(
            getattr(self, "total_max_emission_current_ma", None)
        )
        return f"Do not activate Beams if Predicted Emission Current exceeds {limit_ma}mA"

    def _beams_estop_title(self):
        limit_ma = self._format_beams_estop_current_limit_ma(
            getattr(self, "beams_estop_current_limit_ma", None)
        )
        return f"Trigger E-Stop if 20kV Bertan exceeds {limit_ma}mA"

    def _value_setting_title(self, setting_attr):
        if setting_attr == "vtrx_ccs_pressure_shutdown_enabled":
            return self._vtrx_ccs_shutdown_title()
        if setting_attr == "total_max_emission_current_limit_enabled":
            return self._emission_activation_title()
        if setting_attr == "beams_estop_current_limit_enabled":
            return self._beams_estop_title()
        return str(setting_attr)

    def _create_setting_checkbutton(self, parent_frame, label, setting_attr, command):
        if not hasattr(self, "_setting_checkbutton_vars"):
            self._setting_checkbutton_vars = {}
        variable = tk.BooleanVar(value=bool(getattr(self, setting_attr)))
        self._setting_checkbutton_vars[setting_attr] = variable

        button = ttk.Checkbutton(
            parent_frame,
            text=label,
            variable=variable,
            command=command,
        )
        button.pack(side=tk.TOP, anchor='nw', pady=2)

    def _toggle_setting_value(self, setting_attr):
        current = bool(getattr(self, setting_attr))
        variable = getattr(self, "_setting_checkbutton_vars", {}).get(setting_attr)
        if variable is None:
            enabled = not current
        else:
            variable_value = bool(variable.get())
            enabled = variable_value if variable_value != current else not current
            variable.set(enabled)

        setattr(self, setting_attr, enabled)
        return enabled

    def _refresh_value_setting_control_state(self, setting_attr):
        controls = getattr(self, "_value_setting_controls", {}).get(setting_attr)
        if not controls:
            return
        state = "normal" if bool(getattr(self, setting_attr, True)) else "disabled"
        for widget in controls:
            _safe_widget_config(widget, state=state)

    def _clear_vtrx_ccs_disable_timer(self):
        self._vtrx_ccs_disable_timer_started_at = None
        self._vtrx_ccs_disable_last_warning_at = None

    def _vtrx_ccs_pressure_output_status(self):
        if not bool(getattr(self, "vtrx_ccs_pressure_shutdown_enabled", True)):
            return True, ""
        if not bool(getattr(self, "pressure_reading_is_fresh", False)):
            return False, "VTRX pressure reading is stale."
        try:
            pressure = float(getattr(self, "_last_vtrx_pressure_mbar", None))
        except (TypeError, ValueError):
            return False, "VTRX pressure unavailable."
        if not math.isfinite(pressure):
            return False, "VTRX pressure unavailable."
        if pressure > VTRX_CCS_DISABLE_PRESSURE_LIMIT_MBAR:
            return False, "VTRX pressure is above 1e-5 mbar."
        if getattr(self, "_vtrx_ccs_disable_timer_started_at", None) is not None:
            return False, "VTRX pressure shutdown timer is active."
        return True, ""

    def _vtrx_ccs_pressure_allows_output(self):
        allowed, _reason = self._vtrx_ccs_pressure_output_status()
        return allowed

    def _toggle_value_setting_enabled(self, setting_attr):
        enabled = self._toggle_setting_value(setting_attr)
        if setting_attr == "vtrx_ccs_pressure_shutdown_enabled" and not enabled:
            self._clear_vtrx_ccs_disable_timer()
        self._refresh_value_setting_control_state(setting_attr)
        if setting_attr == "beams_estop_current_limit_enabled":
            self._apply_beams_estop_current_limit_to_beam_energy()
        state = "enabled" if enabled else "disabled"
        self._log_info(f"{self._value_setting_title(setting_attr)} {state}")

    def toggle_disable_ccs_output_on_bcon_disconnect(self):
        enabled = self._toggle_setting_value("disable_ccs_output_on_bcon_disconnect")
        cathode = getattr(self, "subsystems", {}).get("Cathode Heating")
        if cathode is not None:
            cathode.disable_ccs_output_on_bcon_disconnect = enabled
        # When turning this setting on, immediately check BCON connection and update 
        # CCS output to off if needed so the UI state is consistent with the setting.
        if enabled:
            beam_pulse = getattr(self, "subsystems", {}).get("Beam Pulse")
            is_connected = getattr(beam_pulse, "is_connected", None)
            try:
                bcon_connected = bool(is_connected()) if callable(is_connected) else False
            except Exception:
                bcon_connected = False
            if not bcon_connected:
                self._handle_bcon_disconnected()
        state = "enabled" if enabled else "disabled"
        self._log_info(f"Disable CCS Output on BCON Disconnect {state}")

    def toggle_disable_beams_on_vtrx_pressure_exceeded(self):
        enabled = self._toggle_setting_value("disable_beams_on_vtrx_pressure_exceeded")
        if not enabled:
            self._vtrx_pressure_beam_disable_latched = False
        state = "enabled" if enabled else "disabled"
        self._log_info(f"Disable Beams if pressure exceeds {VTRX_BEAM_DISABLE_PRESSURE_LIMIT_MBAR} mbar {state}")

    def create_logging_suppression_toggles(self, parent_frame):
        for label, setting_attr, command in (
            (
                "Disable Knob Box logging when HV subpanel is off",
                "disable_knob_box_logging_when_hvolt_off",
                self.toggle_disable_knob_box_logging_when_hvolt_off,
            ),
            (
                "Disable BCON logging when HV subpanel is off",
                "disable_bcon_logging_when_hvolt_off",
                self.toggle_disable_bcon_logging_when_hvolt_off,
            ),
            (
                "Disable CCS logging when CCS power is off",
                "disable_ccs_logging_when_ccs_power_off",
                self.toggle_disable_ccs_logging_when_ccs_power_off,
            ),
        ):
            self._create_setting_checkbutton(parent_frame, label, setting_attr, command)

    def _toggle_logging_suppression_setting(self, setting_attr, label):
        enabled = self._toggle_setting_value(setting_attr)
        self._apply_logging_suppression_settings()
        state = "enabled" if enabled else "disabled"
        self._log_info(f"{label} {state}")

    def toggle_disable_knob_box_logging_when_hvolt_off(self):
        self._toggle_logging_suppression_setting(
            "disable_knob_box_logging_when_hvolt_off",
            "Disable Knob Box logging when HV subpanel is off",
        )

    def toggle_disable_bcon_logging_when_hvolt_off(self):
        self._toggle_logging_suppression_setting(
            "disable_bcon_logging_when_hvolt_off",
            "Disable BCON logging when HV subpanel is off",
        )

    def toggle_disable_ccs_logging_when_ccs_power_off(self):
        self._toggle_logging_suppression_setting(
            "disable_ccs_logging_when_ccs_power_off",
            "Disable CCS logging when CCS power is off",
        )

    def _read_non_negative_setting_value(
        self,
        entry_var,
        context,
        value_name,
        unit_name,
    ):
        raw_text = str(entry_var.get()).strip()
        if not raw_text:
            message = f"{context}: please enter a {value_name} value in {unit_name}."
            self._log_warning(message)
            messagebox.showerror("Invalid Input", message)
            return None

        try:
            value = float(raw_text)
        except ValueError:
            message = f"{context}: please enter a valid number in {unit_name}."
            self._log_warning(message)
            messagebox.showerror("Invalid Input", message)
            return None

        if not math.isfinite(value) or value < 0:
            message = f"{context}: value must be a finite, non-negative number in {unit_name}."
            self._log_warning(message)
            messagebox.showerror("Invalid Input", message)
            return None

        return value

    def set_total_max_emission_current_limit(self):
        """UI callback for committing the Main Control total emission limit."""
        context = "Do not activate Beams if Predicted Emission Current"
        new_value = self._read_non_negative_setting_value(
            self.total_max_emission_current_entry_var,
            context,
            "limit",
            "mA",
        )
        if new_value is None:
            return

        self.total_max_emission_current_ma = new_value
        self.total_max_emission_current_entry_var.set("")
        self.refresh_value_setting_displays()

        # Runtime updates still apply even if persisting to disk fails.
        if not save_total_max_emission_current(new_value, logger=self.logger):
            message = f"{context}: value was updated for this session but could not be saved."
            self._log_warning(message)
            messagebox.showwarning("Save Failed", message)
        else:
            self._log_info(
                f"{self._emission_activation_title()}: setting successfully changed."
            )

    def set_vtrx_ccs_disable_grace_period(self):
        """UI callback for committing the CCS VTRX pressure grace period."""
        context = "Disable CCS Output if pressure exceeds VTRX limit"
        new_value = self._read_non_negative_setting_value(
            self.vtrx_ccs_disable_grace_period_entry_var,
            context,
            "duration",
            "seconds",
        )
        if new_value is None:
            return

        self.vtrx_ccs_disable_grace_period_s = new_value
        self.vtrx_ccs_disable_grace_period_entry_var.set("")
        self.refresh_value_setting_displays()

        if not save_vtrx_ccs_disable_grace_period_s(new_value, logger=self.logger):
            message = f"{context}: value was updated for this session but could not be saved."
            self._log_warning(message)
            messagebox.showwarning("Save Failed", message)
        else:
            self._log_info(
                f"{self._vtrx_ccs_shutdown_title()}: setting successfully changed."
            )

    def set_beams_estop_current_limit(self):
        """UI callback for committing the Beam Energy +20kV Beams E-STOP current limit."""
        context = "Trigger E-Stop if 20kV Bertan exceeds"
        new_value = self._read_non_negative_setting_value(
            self.beams_estop_current_entry_var,
            context,
            "limit",
            "mA",
        )
        if new_value is None:
            return

        if not BEAMS_ESTOP_CURRENT_LIMIT_MIN_MA <= new_value <= BEAMS_ESTOP_CURRENT_LIMIT_MAX_MA:
            message = (
                f"{context}: value must be between {BEAMS_ESTOP_CURRENT_LIMIT_MIN_MA:g}mA "
                f"and {BEAMS_ESTOP_CURRENT_LIMIT_MAX_MA:g}mA."
            )
            self._log_warning(message)
            messagebox.showerror("Invalid Input", message)
            return

        self.beams_estop_current_limit_ma = new_value
        self.beams_estop_current_entry_var.set("")
        self.refresh_value_setting_displays()
        beam_energy_updated = self._apply_beams_estop_current_limit_to_beam_energy()

        if not save_beams_estop_current_limit_ma(new_value, logger=self.logger):
            message = f"{context}: value was updated for this session but could not be saved."
            self._log_warning(message)
            messagebox.showwarning("Save Failed", message)
            return

        if not beam_energy_updated:
            self._log_warning(f"{context}: setting saved but Beam Energy is not available.")
            return

        self._log_info(
            f"{self._beams_estop_title()}: setting successfully changed."
        )

    def create_post_processor_button(self, parent_frame):
        """Create a button to launch the standalone post-processor application"""
        post_processor_frame = ttk.Frame(parent_frame)
        post_processor_frame.pack(side=tk.TOP, anchor='nw', pady=5)

        ttk.Button(
            post_processor_frame,
            text="Launch Log Post-processor",
            command=self.launch_post_processor
        ).pack(side=tk.LEFT, padx=5)

    def launch_post_processor(self):
        """Launch the post-processor as a separate process"""
        try:
            # Get the directory where the current script is located
            if getattr(sys, 'frozen', False):
                # If running as a bundled executable
                base_path = sys._MEIPASS # type: ignore
            else:
                # If running as a script
                base_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

            # Path to the post processor script
            post_processor_path = os.path.join(base_path, 'scripts/post-process/post_process_gui.py')

            # Launch the post-processor script
            if sys.platform.startswith('win'):
                # On Windows, use pythonw to avoid console window
                subprocess.Popen([sys.executable, post_processor_path],
                            creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                # On other platforms
                subprocess.Popen([sys.executable, post_processor_path])

            self._log_info("Log post-processor launched successfully")
        except Exception as e:
            self._log_error(f"Failed to launch log post-processor: {str(e)}")
            messagebox.showerror("Error",
                            f"Failed to launch log post-processor:\n{str(e)}")

    def create_log_level_dropdown(self, parent_frame):
        log_level_frame = ttk.Frame(parent_frame)
        log_level_frame.pack(side=tk.TOP, anchor='nw', padx=5, pady=5)
        ttk.Label(log_level_frame, text="Log Level:").pack(side=tk.LEFT)

        self.log_level_var = tk.StringVar()
        log_levels = [level.name for level in LogLevel]
        log_level_dropdown = ttk.Combobox(
            log_level_frame,
            textvariable=self.log_level_var,
            values=log_levels,
            state="readonly",
            width=15
        )
        log_level_dropdown.pack(side=tk.LEFT, padx=(5, 0))

        current_level = self.messages_frame.get_log_level()
        log_level_dropdown.set(current_level.name)
        log_level_dropdown.bind("<<ComboboxSelected>>", self.on_log_level_change)

    def file_create_log_level_dropdown(self, parent_frame):
        file_log_frame = ttk.Frame(parent_frame)
        file_log_frame.pack(side=tk.TOP, anchor='nw', padx=5, pady=5)
        ttk.Label(file_log_frame, text="File Log Level:").pack(side=tk.LEFT)

        self.file_log_level_var = tk.StringVar()
        file_log_levels = ["DEBUG", "VERBOSE"]
        self.file_log_level_dropdown = ttk.Combobox(
            file_log_frame,
            textvariable=self.file_log_level_var,
            values=file_log_levels,
            state="readonly",
            width=15
        )
        self.file_log_level_dropdown.pack(side=tk.LEFT, padx=(5, 0))

        current_file_level = self.messages_frame.get_file_log_level()
        self.file_log_level_dropdown.set(current_file_level.name)
        self.file_log_level_dropdown.bind("<<ComboboxSelected>>", self.on_file_log_level_change)

    def on_log_level_change(self, event):
        selected_level = LogLevel[self.log_level_var.get()]
        self.messages_frame.set_log_level(selected_level)

    def on_file_log_level_change(self, event):
        selected_level = self.file_log_level_var.get()
        if selected_level == "DEBUG":
            self.messages_frame.logger.file_log_level = LogLevel.DEBUG
        elif selected_level == "VERBOSE":
            self.messages_frame.logger.file_log_level = LogLevel.VERBOSE

    def _update_activate_enabled_beams_control_state(self, armed=False):
        if hasattr(self, "activate_enabled_beams_button"):
            _safe_widget_config(self.activate_enabled_beams_button, state="normal" if armed else "disabled")

    def _get_beam_pulse_or_fail(self, action_text):
        beam_pulse = getattr(self, "subsystems", {}).get("Beam Pulse")
        if beam_pulse is not None:
            return beam_pulse
        self._log_error("Beam Pulse subsystem not available")
        self._set_beam_action_status(
            f"Failed to {action_text}, Beam Pulse subsystem not available",
            "failure",
        )
        return None

    def _ask_bcon_disconnect_confirmation(self):
        return messagebox.askokcancel(
            "Disconnect BCON",
            (
                "CCS output will be disabled if BCON is disconnected. "
                "Click 'OK' if you still want to disconnect."
            ),
            parent=self.root,
        )

    def _confirm_manual_bcon_disconnect(self):
        cathode = getattr(self, "subsystems", {}).get("Cathode Heating")
        ccs_output_active = bool(cathode and any(getattr(cathode, "toggle_states", [])))
        if self.disable_ccs_output_on_bcon_disconnect:
            if ccs_output_active and not self._ask_bcon_disconnect_confirmation():
                self._log_info("BCON disconnect canceled; CCS output remains enabled")
                return False
            turn_off = getattr(cathode, "turn_off_all_beams", None)
            if callable(turn_off):
                self.logger.warning("BCON manual disconnect requested; disabling CCS output")
                turn_off()
        return True

    def _handle_bcon_disconnected(self):
        if not self.disable_ccs_output_on_bcon_disconnect:
            return
        cathode = getattr(self, "subsystems", {}).get("Cathode Heating")
        if not cathode:
            self._log_warning("BCON disconnected but Cathode Heating subsystem is unavailable; CCS output may remain enabled")
            return
        turn_off = getattr(cathode, "turn_off_all_beams", None)
        if callable(turn_off):
            self._log_warning("BCON disconnected; disabling CCS output")
            turn_off()
        else:
            self._log_critical("BCON disconnected but Cathode Heating turn_off_all_beams API is unavailable; CCS output may remain enabled")

    def _handle_vtrx_ccs_pressure_update(self, pressure, pressure_reading_is_fresh):
        if not bool(getattr(self, "vtrx_ccs_pressure_shutdown_enabled", True)):
            self._clear_vtrx_ccs_disable_timer()
            return

        if pressure_reading_is_fresh and pressure <= VTRX_CCS_DISABLE_PRESSURE_LIMIT_MBAR:
            self._clear_vtrx_ccs_disable_timer()
            return

        pressure_is_stale = not bool(pressure_reading_is_fresh)

        now = float(getattr(self, "_time_monotonic", time.monotonic)())
        cathode = getattr(self, "subsystems", {}).get("Cathode Heating")
        ccs_output_active = bool(cathode and any(getattr(cathode, "toggle_states", [])))
        if not ccs_output_active:
            self._clear_vtrx_ccs_disable_timer()
            return

        duration_s = self._coerce_vtrx_ccs_disable_grace_period_s(
            getattr(self, "vtrx_ccs_disable_grace_period_s", None)
        )
        duration_display_s = round(duration_s)
        started_at = getattr(self, "_vtrx_ccs_disable_timer_started_at", None)

        if started_at is None:
            started_at = now
            self._vtrx_ccs_disable_timer_started_at = started_at
            self._vtrx_ccs_disable_last_warning_at = now
            if pressure_is_stale:
                self._log_critical(
                    "VTRX pressure reading is stale; CCS output will be disabled after "
                    f"{duration_display_s} seconds."
                )
            else:
                self._log_critical(
                    f"VTRX pressure exceeded {VTRX_CCS_DISABLE_PRESSURE_LIMIT_MBAR} mbar "
                    f"({pressure:g} mbar); CCS output will be disabled after "
                    f"{duration_display_s} seconds."
                )

        elapsed_s = max(0.0, float(now) - float(started_at))
        if elapsed_s < duration_s:
            last_warning_at = getattr(self, "_vtrx_ccs_disable_last_warning_at", None)
            if (
                last_warning_at is None
                or now - float(last_warning_at) >= VTRX_CCS_DISABLE_WARNING_INTERVAL_S
            ):
                seconds_left = max(0.0, duration_s - elapsed_s)
                seconds_left_display = round(seconds_left)
                if pressure_is_stale:
                    self._log_warning(
                        f"CCS output will be disabled in {seconds_left_display} seconds because "
                        "the VTRX pressure reading is stale"
                    )
                else:
                    self._log_warning(
                        f"CCS output will be disabled in {seconds_left_display} seconds due to VTRX pressure "
                        f"being above {VTRX_CCS_DISABLE_PRESSURE_LIMIT_MBAR} mbar"
                    )
                self._vtrx_ccs_disable_last_warning_at = now
            return

        if pressure_is_stale:
            self._log_critical(
                f"VTRX pressure reading remained stale for {duration_display_s} seconds; "
                "disabling CCS output."
            )
        else:
            self._log_critical(
                f"VTRX pressure remained above {VTRX_CCS_DISABLE_PRESSURE_LIMIT_MBAR} mbar "
                f"for {duration_display_s} seconds; disabling CCS output."
            )
        self._vtrx_ccs_disable_last_warning_at = now
        turn_off = getattr(cathode, "turn_off_all_beams", None)
        if callable(turn_off):
            try:
                turn_off()
            except Exception as e:
                self._log_critical(f"VTRX pressure CCS disable failed: {e}")
        else:
            self._log_critical("VTRX pressure CCS disable failed: Cathode Heating turn_off_all_beams API is unavailable")

    def _handle_vtrx_bcon_pressure_update(self, pressure, pressure_reading_is_fresh):
        if not self.disable_beams_on_vtrx_pressure_exceeded:
            return

        if pressure_reading_is_fresh and pressure <= VTRX_BEAM_DISABLE_PRESSURE_LIMIT_MBAR:
            self._vtrx_pressure_beam_disable_latched = False
            return

        if self._vtrx_pressure_beam_disable_latched:
            return

        self._vtrx_pressure_beam_disable_latched = True
        if pressure_reading_is_fresh:
            self._log_critical(
                f"VTRX pressure exceeded 1e-5 mbar ({pressure:g} mbar); disabling all beams."
            )
        else:
            self._log_critical("VTRX pressure reading is stale; disabling all beams.")

        beam_pulse = getattr(self, "subsystems", {}).get("Beam Pulse")
        disable_all_beams = getattr(beam_pulse, "disable_all_beams", None)
        if callable(disable_all_beams):
            try:
                disable_all_beams()
            except Exception as e:
                self._log_critical(f"VTRX pressure beam disable failed: {e}")
        else:
            self._log_critical(
                "VTRX pressure unsafe but Beam Pulse disable_all_beams API is unavailable"
            )

    def _handle_vtrx_pressure_update(self, pressure_mbar, pressure_reading_is_fresh=False):
        pressure_is_valid = False
        pressure = None
        try:
            pressure = float(pressure_mbar)
        except (TypeError, ValueError):
            self._last_vtrx_pressure_mbar = None
        else:
            pressure_is_valid = math.isfinite(pressure)

        if pressure_is_valid:
            self._last_vtrx_pressure_mbar = pressure
        else:
            self._last_vtrx_pressure_mbar = None

        self.pressure_reading_is_fresh = bool(pressure_reading_is_fresh) and pressure_is_valid

        self._handle_vtrx_ccs_pressure_update(pressure, self.pressure_reading_is_fresh)
        self._handle_vtrx_bcon_pressure_update(pressure, self.pressure_reading_is_fresh)

    def _set_armed_ui(self, armed, reset=False):
        if hasattr(self, "beams_ready_button"):
            toggle_on_image = getattr(self, "toggle_on_image", None)
            toggle_off_image = getattr(self, "toggle_off_image", None)
            if toggle_on_image and toggle_off_image:
                _safe_widget_config(
                    self.beams_ready_button,
                    image=toggle_on_image if armed else toggle_off_image
                )
            else:
                _safe_widget_config(
                    self.beams_ready_button,
                    text="BEAMS ARMED" if armed else "ARM BEAMS",
                    bg="navy" if armed else "sky blue",
                )
        self.update_beam_toggle_states(enabled=armed, reset=reset)
        self._update_enable_toggle_states(enabled=armed)
        self._update_activate_enabled_beams_control_state(armed=armed)
        if reset:
            self._clear_all_beam_output_displays()

    def _on_armed_status_update(self, armed):
        """Mirror Beam Pulse software armed state without changing line 4."""
        self._set_armed_ui(bool(armed), reset=not bool(armed))

    def handle_activate_enabled_beams(self):
        beam_pulse = self._get_beam_pulse_or_fail("activate enabled beams")
        if beam_pulse is None:
            return
        activate_enabled_beams = getattr(beam_pulse, "activate_enabled_beams", None)
        if not callable(activate_enabled_beams):
            self._set_beam_action_status("Failed to activate enabled beams, Beam Pulse API not available", "failure")
            return
        activate_enabled_beams()

    def handle_disable_all_beams(self):
        beam_pulse = self._get_beam_pulse_or_fail("disable all beams")
        if beam_pulse is None:
            return
        disable_all_beams = getattr(beam_pulse, "disable_all_beams", None)
        if not callable(disable_all_beams):
            self._set_beam_action_status("Failed to disable all beams, Beam Pulse API not available", "failure")
            return
        disable_all_beams()

    def handle_arm_beams(self):
        """Handle ARM BEAMS toggle press with state management."""
        try:
            beam_pulse = self._get_beam_pulse_or_fail("arm beams")
            if beam_pulse is None:
                return

            get_armed = getattr(beam_pulse, "get_beams_armed_status", None)
            is_armed = bool(get_armed()) if callable(get_armed) else False

            if is_armed:
                disarm_beams = getattr(beam_pulse, "disarm_beams", None)
                if callable(disarm_beams) and disarm_beams():
                    self._set_armed_ui(False, reset=True)
                    self._set_beam_action_status("Beams disarmed", "neutral")
                    self._log_info("Beams disarmed via dashboard button")
                else:
                    self._log_error("Failed to disarm beams")
                    self._set_beam_action_status("Failed to disarm beams", "failure")
            else:
                arm_beams = getattr(beam_pulse, "arm_beams", None)
                if callable(arm_beams) and arm_beams():
                    self._set_armed_ui(True)
                    self._set_beam_action_status("Beams armed", "success")
                    self._log_info("Beams armed via dashboard button")
                else:
                    self._log_error("Failed to arm beams")
                    self._set_beam_action_status("Failed to arm beams", "failure")

        except Exception as e:
            self._log_error(f"Error in handle_arm_beams: {str(e)}")
            self._set_beam_action_status(f"Failed to arm beams: {str(e)}", "failure")

    def handle_beams_off(self, reason=None):
        """Handle Beams E-stop button press — force stop all BCON channels,
        turn off cathode heating, and disarm beams."""
        try:
            first_error = None

            def record_error(message, error):
                nonlocal first_error
                if first_error is None:
                    first_error = error
                self._log_critical(f"{message}: {str(error)}")

            # Force stop all BCON channels immediately
            beam_pulse = self.subsystems.get('Beam Pulse')
            try:
                if beam_pulse is not None:
                    stop_all_channels = getattr(beam_pulse, 'stop_all_channels', None)
                    if callable(stop_all_channels):
                        self._log_info("Beams E-STOP requesting all BCON channels stop")
                        if not stop_all_channels():
                            self._log_critical("Beams E-STOP failed to stop all BCON channels")
                    else:
                        self._log_critical("Beams E-STOP cannot stop BCON channels: Beam Pulse stop_all_channels API is unavailable")
                else:
                    self._log_critical("Beams E-STOP cannot stop BCON channels: Beam Pulse subsystem is unavailable")
            except Exception as e:
                record_error("Beams E-STOP BCON channel stop failed", e)

            # Disarm beams
            try:
                if beam_pulse is not None:
                    get_beams_armed_status = getattr(beam_pulse, 'get_beams_armed_status', None)
                    if callable(get_beams_armed_status):
                        beams_armed = bool(get_beams_armed_status())
                    else:
                        beams_armed = False
                        self._log_critical("Beams E-STOP cannot verify armed state: Beam Pulse get_beams_armed_status API is unavailable")
                    if beams_armed:
                        disarm_beams = getattr(beam_pulse, 'disarm_beams', None)
                        if callable(disarm_beams) and disarm_beams():
                            self._set_armed_ui(False)
                            self._log_info("Beams disarmed via Beams E-stop button")
                        else:
                            self._log_critical("Failed to disarm beams via Beams E-stop")
                    self.update_beam_toggle_states(enabled=False, reset=True)
                    self._update_enable_toggle_states(enabled=False)
                    self._update_activate_enabled_beams_control_state(armed=False)
                self._clear_all_beam_output_displays()
            except Exception as e:
                record_error("Beams E-STOP disarm/UI update failed", e)

            # Turn off cathode heating power supplies
            try:
                cathode = self.subsystems.get('Cathode Heating')
                if cathode is not None:
                    turn_off_all_beams = getattr(cathode, 'turn_off_all_beams', None)
                    if callable(turn_off_all_beams):
                        self._log_info("Beams E-STOP requesting cathode heating shutdown")
                        turn_off_all_beams()
                    else:
                        self._log_critical("Beams E-STOP cannot disable cathode heating: Cathode Heating turn_off_all_beams API is unavailable")
                else:
                    self._log_critical("Beams E-STOP cannot disable cathode heating: Cathode Heating subsystem is unavailable")
            except Exception as e:
                record_error("Beams E-STOP cathode heating shutdown failed", e)

            if first_error is not None:
                self._set_beam_action_status(f"Failed to stop beams: {str(first_error)}", "failure")
            elif reason:
                self._set_beam_action_status(str(reason), "estop")
            else:
                self._set_beam_action_status("Beams E-STOP pressed: All Beams Disabled", "estop")
        except Exception as e:
            self._log_critical(f"Error in handle_beams_off: {str(e)}")
            self._set_beam_action_status(f"Failed to stop beams: {str(e)}", "failure")

    def _toggle_channel_enable(self, ch_index: int):
        """Toggle one BCON channel enable and mirror the returned state."""
        try:
            beam_pulse = self._get_beam_pulse_or_fail("toggle channel enable")
            if beam_pulse is None:
                return
            toggler = getattr(beam_pulse, "toggle_channel_enable", None)
            if not callable(toggler):
                self._set_beam_action_status(
                    "Failed to toggle channel enable, Beam Pulse API not available",
                    "failure",
                )
                return

            ok, enabled, detail = toggler(ch_index)
            if not ok:
                detail_text = str(detail)
                error_failure = (
                    "bcon driver not available" in detail_text.lower()
                    or "bcon device not connected" in detail_text.lower()
                    or "failed to set" in detail_text.lower()
                )
                if error_failure:
                    self._log_error(detail_text)
                else:
                    self._log_warning(detail_text)
                self._set_beam_action_status(
                    f"Failed to toggle Channel {channel_label(ch_index)} enable: {detail_text}",
                    "failure",
                )
                return

            self._on_channel_enable_status_update(ch_index, enabled)
            self._log_info(f"{channel_name(ch_index)} enable -> {'Enabled' if enabled else 'Disabled'}")
            self._set_beam_action_status(
                f"Channel {channel_label(ch_index)} successfully {'enabled' if enabled else 'disabled'}",
                "success",
            )
            if not enabled and ch_index < len(self.beam_toggle_buttons):
                _safe_widget_config(
                    self.beam_toggle_buttons[ch_index],
                    bg="gray", text=f"Beam {channel_label(ch_index)} OFF")
        except Exception as e:
            self._log_error(f"Error toggling {channel_name(ch_index)} enable: {e}")
            self._set_beam_action_status(f"Failed to toggle Channel {channel_label(ch_index)} enable: {e}", "failure")

    def toggle_individual_beam_with_status(self, beam_index):
        """Toggle individual beam on/off.

        ON  = read channel config from Beam Pulse panel and send to BCON.
        OFF = send OFF command for the channel.
        """
        try:
            beam_pulse = self._get_beam_pulse_or_fail("toggle beam")
            if beam_pulse is None:
                return

            current_status = beam_pulse.get_beam_status(beam_index)
            btn = self.beam_toggle_buttons[beam_index]

            if current_status:
                # Currently ON -> turn OFF
                if beam_pulse.send_channel_off(beam_index):
                    _safe_widget_config(btn, bg="gray", text=f"Beam {channel_label(beam_index)} OFF")
                    self._clear_beam_output_display(beam_index)
                    self._set_beam_action_status(
                        f"Beam {channel_label(beam_index)} successfully set to OFF",
                        "success",
                    )
                    self._log_info(f"Beam {channel_label(beam_index)} turned OFF")
                else:
                    self._set_beam_action_status(
                        f"Failed to set Beam {channel_label(beam_index)} OFF",
                        "failure",
                    )
                    self._log_error(f"Failed to set Beam {channel_label(beam_index)} OFF")
            else:
                # Currently OFF -> send channel config to BCON
                config = (
                    beam_pulse.get_channel_config(beam_index)
                    if hasattr(beam_pulse, 'get_channel_config')
                    else {'mode': 'PULSE'}
                )
                ok = beam_pulse.send_channel_config(beam_index)
                if ok:
                    self._set_beam_output_display(beam_index, config, is_on=True)
                    self._set_beam_action_status(
                        self._beam_success_message(beam_index, config),
                        "success",
                    )
                    _safe_widget_config(btn, bg="green", text=f"Beam {channel_label(beam_index)} ON")
                    self._log_info(f"Beam {channel_label(beam_index)} config sent to BCON")
                else:
                    # Prefer Beam Pulse's exact reason so line 4 explains why nothing was sent.
                    failure_message = ""
                    getter = getattr(beam_pulse, "get_last_send_failure_message", None)
                    if callable(getter):
                        try:
                            failure_message = getter()
                        except Exception:
                            failure_message = ""
                    if failure_message:
                        if not str(failure_message).lower().startswith("failed "):
                            failure_message = (
                                f"Failed to send Beam {channel_label(beam_index)} config: "
                                f"{failure_message}"
                            )
                    else:
                        failure_message = f"Failed to send Beam {channel_label(beam_index)} config"
                    self._set_beam_action_status(failure_message,"failure",)
                    self._log_error(failure_message)

        except Exception as e:
            self._log_error(f"Error toggling beam {beam_index}: {str(e)}")
            self._set_beam_action_status(
                f"Failed to toggle Beam {channel_label(beam_index)}: {str(e)}",
                "failure",
            )

    def _on_channel_status_update(self, ch: int, mode_code: int, remaining: int, status_config=None):
        """Mirror live BCON register state onto Main Control beam displays.

        Called on every register-poll cycle by BeamPulseSubsystem.
        mode_code=0 means OFF; remaining=0 means all pulses delivered.
        """
        if not hasattr(self, 'beam_toggle_buttons'):
            self._log_error("Invalid channel status update: beam toggle buttons are not initialized")
            return
        if not isinstance(ch, int) or not 0 <= ch < len(self.beam_toggle_buttons):
            self._log_error(f"Invalid channel status update for channel {ch}")
            return
        btn = self.beam_toggle_buttons[ch]
        # DC mode never counts down, so remaining is always 0 in hardware.
        # Treat DC as running whenever mode != OFF to prevent button glitching.
        MODE_DC = 1
        is_running = (mode_code != 0) and (remaining > 0 or mode_code == MODE_DC)
        try:
            if is_running:
                _safe_widget_config(btn, bg="green", text=f"Beam {channel_label(ch)} ON")
                if status_config is not None:
                    self._set_beam_output_display(ch, status_config, is_on=True)
            else:
                if str(btn.cget('bg')) == 'green':
                    _safe_widget_config(btn, bg="gray", text=f"Beam {channel_label(ch)} OFF")
                self._clear_beam_output_display(ch)
        except Exception:
            pass

    def _on_channel_enable_status_update(self, ch: int, enabled: bool):
        """Mirror firmware-backed channel enable state onto dashboard controls."""
        try:
            if hasattr(self, '_ch_enable_states') and ch < len(self._ch_enable_states):
                self._ch_enable_states[ch] = bool(enabled)

            if hasattr(self, 'enable_toggle_buttons') and ch < len(self.enable_toggle_buttons):
                _safe_widget_config(
                    self.enable_toggle_buttons[ch],
                    bg="#2e7d32" if enabled else "#888888",
                    text=f"CH {channel_label(ch)}: {'Enabled' if enabled else 'Disabled'}",
                )

            if not enabled or not self._beam_output_display_is_on(ch):
                self._clear_beam_output_display(ch)

            beam_pulse = self.subsystems.get('Beam Pulse')
            armed = bool(
                beam_pulse
                and hasattr(beam_pulse, 'get_beams_armed_status')
                and beam_pulse.get_beams_armed_status()
            )

            if hasattr(self, 'enable_toggle_buttons') and ch < len(self.enable_toggle_buttons):
                _safe_widget_config(
                    self.enable_toggle_buttons[ch],
                    state="normal" if armed else "disabled",
                )

            self.update_beam_toggle_states(enabled=armed)
            self._update_activate_enabled_beams_control_state(armed=armed)
        except Exception as e:
            self._log_error(f"Error updating {channel_name(ch)} enable status: {str(e)}")

    def update_beam_toggle_states(self, enabled=True, reset=False):
        """Update the state of beam toggle buttons."""
        try:
            if not hasattr(self, 'beam_toggle_buttons'):
                return

            for i, btn in enumerate(self.beam_toggle_buttons):
                if enabled:
                    # Only allow beam ON/OFF when the channel hardware enable is also ON
                    ch_enabled = (
                        hasattr(self, '_ch_enable_states')
                        and i < len(self._ch_enable_states)
                        and self._ch_enable_states[i]
                    )
                    _safe_widget_config(btn, state="normal" if ch_enabled else "disabled")
                    if reset:
                        _safe_widget_config(btn, bg="gray", text=f"Beam {channel_label(i)} OFF")
                        self._clear_beam_output_display(i)
                else:
                    _safe_widget_config(btn,state="disabled",bg="gray",text=f"Beam {channel_label(i)} OFF",)
                    if reset:
                        self._clear_beam_output_display(i)

        except Exception as e:
            self._log_error(f"Error updating beam toggle states: {str(e)}")

    def _update_enable_toggle_states(self, enabled=True):
        """Enable or disable the CH Enable toggle buttons based on armed status.
        When disabling, mirror the firmware safety contract: all channel
        enable latches are cleared by STOP/disconnect paths.
        """
        try:
            if not hasattr(self, 'enable_toggle_buttons'):
                return
            for i, btn in enumerate(self.enable_toggle_buttons):
                if enabled:
                    _safe_widget_config(btn, state="normal")
                else:
                    # Disarmed — force all to Disabled appearance and reset tracking
                    if hasattr(self, '_ch_enable_states') and i < len(self._ch_enable_states):
                        self._ch_enable_states[i] = False
                    _safe_widget_config(btn,state="disabled",bg="#888888",text=f"CH {channel_label(i)}: Disabled",)
        except Exception as e:
            self._log_error(f"Error updating enable toggle states: {str(e)}")

    def create_com_port_frame(self, parent_frame):
        """
        Create the COM port configuration interface.
        Allows dynamic assignment of COM ports to different subsystems.
        """
        self.com_port_frame = ttk.Frame(parent_frame)
        self.com_port_frame.pack(side=tk.TOP, fill=tk.X, padx=5, pady=5)

        self.com_port_button = ttk.Button(self.com_port_frame, text="Configure COM Ports", command=self.toggle_com_port_menu)
        self.com_port_button.pack(side=tk.TOP, anchor='w')

        self.com_port_menu = ttk.Frame(self.com_port_frame)
        self.com_port_menu.pack(side=tk.TOP, fill=tk.X, expand=True)
        self.com_port_menu.pack_forget()  # Initially hidden

        self.port_selections = {}
        self.port_dropdowns = {}

        for subsystem in [
            'VTRXSubsystem', 'CathodeA PS', 'CathodeB PS', 'CathodeC PS', 
            'TempControllers', 'Interlocks', 'ProcessMonitors', 'KnobBox',
            'Laser Monitor']:
            frame = ttk.Frame(self.com_port_menu)
            frame.pack(fill=tk.X, padx=5, pady=2)
            ttk.Label(frame, text=f"{subsystem}:").pack(side=tk.LEFT)
            port_var = tk.StringVar(value=self.com_ports.get(subsystem, ''))
            self.port_selections[subsystem] = port_var
            dropdown = ttk.Combobox(frame, textvariable=port_var)
            dropdown.pack(side=tk.RIGHT)
            self.port_dropdowns[subsystem] = dropdown

        # Ensure Beam Pulse is stored under the canonical config key.
        if 'BeamPulse' not in self.port_selections:
            frame = ttk.Frame(self.com_port_menu)
            frame.pack(fill=tk.X, padx=5, pady=2)
            ttk.Label(frame, text="Beam Pulse:").pack(side=tk.LEFT)
            port_var = tk.StringVar(value=self.com_ports.get('BeamPulse', ''))
            self.port_selections['BeamPulse'] = port_var
            dropdown = ttk.Combobox(frame, textvariable=port_var)
            dropdown.pack(side=tk.RIGHT)
            self.port_dropdowns['BeamPulse'] = dropdown

        ttk.Button(self.com_port_menu, text="Apply", command=self.apply_com_port_changes).pack(pady=5)

    def toggle_com_port_menu(self):
        if self.com_port_menu.winfo_viewable():
            self.com_port_menu.pack_forget()
            _safe_widget_config(self.com_port_button, text="Configure COM Ports")
        else:
            self.update_available_ports()
            self.com_port_menu.pack(after=self.com_port_button, fill=tk.X, expand=True)
            _safe_widget_config(self.com_port_button, text="Hide COM Port Configuration")

    def update_available_ports(self):
        """Scan for available COM ports and update dropdown menus."""
        available_ports = [port.device for port in serial.tools.list_ports.comports()]
        for dropdown in self.port_dropdowns.values():
            current_value = dropdown.get()
            dropdown['values'] = available_ports
            if current_value in available_ports:
                dropdown.set(current_value)
            elif available_ports:
                dropdown.set(available_ports[0])
            else:
                dropdown.set('')

    def apply_com_port_changes(self):
        new_com_ports = {subsystem: var.get() for subsystem, var in self.port_selections.items()}
        self.update_com_ports(new_com_ports)
        self.toggle_com_port_menu()

