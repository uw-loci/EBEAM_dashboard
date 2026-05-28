import math
import os
import subprocess
import sys
import tkinter as tk
from tkinter import messagebox, ttk

import serial.tools.list_ports

from usr.com_port_config import get_beam_pulse_com_port
from usr.main_control_config import (
    load_total_max_emission_current,
    save_total_max_emission_current,
)
from utils import LogLevel, SetupScripts


CHANNEL_LABELS = ("A", "B", "C")
BEAM_OUTPUT_ON_COLOR = "green"
BEAM_OUTPUT_OFF_COLOR = "gray"
BEAM_ACTION_SUCCESS_COLOR = "green"
BEAM_ACTION_FAILURE_COLOR = "red"
BEAM_ACTION_NEUTRAL_COLOR = "gray"


def channel_label(index: int) -> str:
    """Return the UI-facing pulser channel label for a 0-based index."""
    if 0 <= index < len(CHANNEL_LABELS):
        return CHANNEL_LABELS[index]
    return str(index + 1)


def channel_name(index: int) -> str:
    """Return a verbose UI-facing pulser channel name for a 0-based index."""
    return f"Channel {channel_label(index)}"


class MainControlPanel:
    """Main Control subpanel and coordinator for beam-related dashboard actions."""

    def __init__(
        self,
        parent_frame,
        root,
        logger,
        messages_frame,
        get_com_ports,
        get_subsystem,
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
        self._get_subsystem_callback = get_subsystem
        self.save_layout_callback = save_layout_callback
        self.update_com_ports_callback = update_com_ports_callback
        self.toggle_on_image = toggle_on_image
        self.toggle_off_image = toggle_off_image
        self.subsystems = {}
        self.com_ports = self._get_com_ports()

        self.total_max_emission_current_ma = load_total_max_emission_current(logger=self.logger)
        self.total_max_emission_current_entry_var = tk.StringVar(value="")
        self.total_max_emission_current_value_var = tk.StringVar(
            value=f"Limit set to: {self.total_max_emission_current_ma:g}mA"
        )
        self._initialize_main_control_beam_status_state()
        self.create_main_control_notebook(parent_frame)

    def _get_com_ports(self):
        if callable(getattr(self, "_get_com_ports_callback", None)):
            try:
                return self._get_com_ports_callback() or {}
            except Exception:
                return {}
        return getattr(self, "com_ports", {})

    def _get_subsystem(self, name):
        if callable(getattr(self, "_get_subsystem_callback", None)):
            try:
                return self._get_subsystem_callback(name)
            except Exception:
                return None
        return getattr(self, "subsystems", {}).get(name)

    def save_current_pane_state(self):
        if callable(self.save_layout_callback):
            self.save_layout_callback()

    def update_com_ports(self, new_com_ports):
        self.com_ports = new_com_ports
        if callable(self.update_com_ports_callback):
            self.update_com_ports_callback(new_com_ports)

    def get_channel_enable_states(self):
        return list(getattr(self, "_ch_enable_states", [True, True, True]))

    def wire_beam_energy(self, beam_energy):
        """Register the Beam Energy +20kV current E-stop callback."""
        if beam_energy is not None and hasattr(beam_energy, "set_beams_estop_callback"):
            beam_energy.set_beams_estop_callback(
                lambda: self.handle_beams_off(
                    "20kV E-Stop Current Limit exceeded: All Beams Disabled"
                )
            )

    def wire_beam_pulse(self, beam_pulse):
        """Wire Beam Pulse callbacks and Main Control-hosted manual actions."""
        self.beam_pulse = beam_pulse
        if beam_pulse is None:
            return

        if hasattr(beam_pulse, "set_dashboard_beam_callback"):
            beam_pulse.set_dashboard_beam_callback(self.handle_beam_pulse_callback)

        if hasattr(beam_pulse, "set_channel_status_callback"):
            beam_pulse.set_channel_status_callback(self._on_channel_status_update)
        if hasattr(beam_pulse, "set_action_feedback_callback"):
            beam_pulse.set_action_feedback_callback(self._handle_action_feedback)
        if hasattr(beam_pulse, "set_channel_enable_status_callback"):
            beam_pulse.set_channel_enable_status_callback(self._on_channel_enable_status_update)
        if hasattr(beam_pulse, "set_output_start_guard"):
            beam_pulse.set_output_start_guard(self.check_total_emission_current_limit)

    def create_main_control_notebook(self, frame):
        notebook = ttk.Notebook(frame)
        notebook.pack(expand=True, fill='both')

        main_tab = ttk.Frame(notebook)
        config_tab = ttk.Frame(notebook)

        notebook.add(main_tab, text='Main')
        notebook.add(config_tab, text='Config')

        # TODO: add main control buttons to main tab here
        main_frame = ttk.Frame(main_tab, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        # Save reference so beam_pulse subsystem can add its buttons here
        self.main_control_frame = main_frame

        # Add safety beams off button (bottom)
        beams_off_button = tk.Button(
            main_frame,
            text="BEAMS E-STOP",
            bg="red",
            fg="white",
            font=("Helvetica",14,"bold"),
            command=self.handle_beams_off
        )
        beams_off_button.pack(side="bottom", fill="x", padx=10, pady=(4, 8))

        # Script dropdown
        self.create_script_dropdown(main_frame)

        # --- Manual-tab panel: Beam ON/OFF + CH Enable/Disable buttons --
        self.bp_manual_panel = tk.Frame(main_frame)
        self.bp_manual_panel.pack(side="top", fill="x", padx=10, pady=(10, 0))

        # Beam ON/OFF row.
        self.beam_on_off_frame = tk.Frame(self.bp_manual_panel)
        self.beam_on_off_frame.pack(side="top", fill="x")
        buttons_frame = self.beam_on_off_frame
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
        enable_toggle_frame = tk.Frame(self.bp_manual_panel)
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

        sync_control_frame = tk.Frame(self.bp_manual_panel)
        sync_control_frame.pack(side="top", fill="x", pady=(4, 0))
        sync_control_frame.grid_columnconfigure(0, weight=1, uniform="sync")
        sync_control_frame.grid_columnconfigure(1, weight=1, uniform="sync")

        self.sync_start_button = tk.Button(
            sync_control_frame,
            text="Sync Start",
            bg="#1565C0",
            fg="white",
            font=("Helvetica", 9, "bold"),
            state="disabled",
            command=self.handle_sync_start,
        )
        self.sync_start_button.grid(row=0, column=0, sticky="ew", padx=(2, 1))

        self.sync_stop_button = tk.Button(
            sync_control_frame,
            text="Sync Stop",
            bg="#B71C1C",
            fg="white",
            font=("Helvetica", 9, "bold"),
            state="normal",
            command=self.handle_sync_stop,
        )
        self.sync_stop_button.grid(row=0, column=1, sticky="ew", padx=(1, 2))

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

        # 1. COM Port Configuration
        self.create_com_port_frame(config_frame)

        # 2. Save Layout button
        save_layout_frame = ttk.Frame(config_frame)
        save_layout_frame.pack(side=tk.TOP, anchor='nw', padx=5, pady=5)
        ttk.Button(
            save_layout_frame,
            text="Save Layout",
            command=self.save_current_pane_state
        ).pack(side=tk.LEFT, padx=5)

        # 3. Post Processor button
        self.create_post_processor_button(config_frame)

        # 4. Log Level dropdown
        self.create_log_level_dropdown(config_frame)
        self.file_create_log_level_dropdown(config_frame)

        # Expose the limit used by beam-output start paths.
        self.create_total_max_emission_current_controls(config_frame)

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

        self.beam_action_status_label = ttk.Label(
            status_frame,
            textvariable=self.beam_action_status_var,
            font=("Segoe UI", 8, "bold"),
            foreground=self._beam_action_status_color,
            anchor=tk.W,
        )
        self.beam_action_status_label.pack(anchor=tk.W, fill=tk.X, pady=(2, 0))

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
        if not hasattr(self, "_beam_action_status_color"):
            self._beam_action_status_color = BEAM_ACTION_NEUTRAL_COLOR

    def _coerce_beam_config(self, config):
        """Normalize a BCON channel config dict for display/state storage."""
        if not isinstance(config, dict):
            return {"mode": "OFF", "duration_ms": 0, "count": 1}

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

        return {"mode": mode, "duration_ms": duration, "count": count, "remaining": remaining}

    def _beam_on_description(self, config):
        """Return the mode-specific phrase used in ON status lines."""
        config = self._coerce_beam_config(config)
        mode = config["mode"]
        if mode == "DC":
            return "running DC"
        if mode == "PULSE":
            return f"running PULSE for {config['duration_ms']}ms"
        if mode == "PULSE_TRAIN":
            return (
                f"running PULSE_TRAIN: set to {config['count']} pulses"
                f", {config['duration_ms']}ms each. Remaining: {config['remaining']}"
            )
        return "OFF"

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
        return self._beam_output_status_colors[beam_index] == BEAM_OUTPUT_ON_COLOR

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
        color = BEAM_OUTPUT_ON_COLOR if is_output_on else BEAM_OUTPUT_OFF_COLOR

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
            try:
                labels[beam_index].config(foreground=color)
            except Exception:
                pass

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
        color = {
            "success": BEAM_ACTION_SUCCESS_COLOR,
            "failure": BEAM_ACTION_FAILURE_COLOR,
            "error": BEAM_ACTION_FAILURE_COLOR,
            "estop": BEAM_ACTION_FAILURE_COLOR,
            "neutral": BEAM_ACTION_NEUTRAL_COLOR,
        }.get(str(outcome).strip().lower(), BEAM_ACTION_NEUTRAL_COLOR)

        self._beam_action_status_text = str(message or "")
        self._beam_action_status_color = color

        action_var = getattr(self, "beam_action_status_var", None)
        if action_var is not None:
            try:
                action_var.set(self._beam_action_status_text)
            except Exception:
                pass

        action_label = getattr(self, "beam_action_status_label", None)
        if action_label is not None:
            try:
                action_label.config(foreground=color)
            except Exception:
                pass

    def _beam_success_message(self, beam_index, config):
        """Build line 4 success text for a beam ON command."""
        return (
            f"Beam {channel_label(beam_index)} successfully set to ON, "
            f"{self._beam_on_description(config)}"
        )

    def _format_sync_start_message(self, configs):
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
        return "Sync Start: " + ", ".join(parts) if parts else "Sync Start"

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
                message = self._format_sync_start_message(configs)
        elif event_type == "all_off":
            self._clear_all_beam_output_displays()

        if message:
            self._set_beam_action_status(message, outcome)

    def create_script_dropdown(self, parent_frame):
        SetupScripts(parent_frame)

    def create_total_max_emission_current_controls(self, parent_frame):
        """Create Main Control config UI for the total predicted emission limit."""
        section = ttk.Frame(parent_frame)
        section.pack(side=tk.TOP, anchor='nw', fill=tk.X, padx=5, pady=(5, 2))

        ttk.Label(
            section,
            text="Total Max Emission Current",
            font=("Segoe UI", 8, "bold"),
        ).pack(anchor=tk.W, pady=(0, 2))

        row = ttk.Frame(section)
        row.pack(fill=tk.X, pady=(2, 0))

        ttk.Label(row, text="Max I:", font=("Segoe UI", 8)).grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(
            row,
            textvariable=self.total_max_emission_current_entry_var,
            width=7,
        ).grid(row=0, column=1, sticky=tk.W, padx=(2, 2))
        ttk.Label(row, text="mA", font=("Segoe UI", 8)).grid(row=0, column=2, sticky=tk.W)
        ttk.Button(
            row,
            text="Set",
            width=4,
            command=self.set_total_max_emission_current_limit,
        ).grid(row=0, column=3, sticky=tk.W, padx=(4, 0))

        ttk.Label(
            section,
            textvariable=self.total_max_emission_current_value_var,
            font=("Segoe UI", 8),
            foreground="gray",
        ).pack(anchor=tk.W, padx=(2, 0), pady=(0, 4))

    def set_total_max_emission_current_limit(self):
        """UI callback for committing the Main Control total emission limit."""
        raw_text = str(self.total_max_emission_current_entry_var.get()).strip()
        context = "Total Max Emission Current"
        # Keep validation here so UI callbacks and tests use the same rules.
        if not raw_text:
            message = f"{context}: please enter a limit value in mA."
            self.logger.error(message)
            messagebox.showerror("Invalid Input", message)
            return

        try:
            new_value = float(raw_text)
        except ValueError:
            message = f"{context}: please enter a valid number in mA."
            self.logger.error(message)
            messagebox.showerror("Invalid Input", message)
            return

        # Reject values that would make the limit comparison ambiguous.
        if not math.isfinite(new_value) or new_value < 0:
            message = f"{context}: value must be a finite, non-negative number in mA."
            self.logger.error(message)
            messagebox.showerror("Invalid Input", message)
            return

        self.total_max_emission_current_ma = new_value
        self.total_max_emission_current_value_var.set(
            f"Limit set to: {self.total_max_emission_current_ma:g}mA"
        )
        self.total_max_emission_current_entry_var.set("")

        # Runtime updates still apply even if persisting to disk fails.
        if not save_total_max_emission_current(new_value, logger=self.logger):
            message = f"{context}: value was updated for this session but could not be saved."
            self.logger.warning(message)
            messagebox.showwarning("Save Failed", message)

    def create_post_processor_button(self, parent_frame):
        """Create a button to launch the standalone post-processor application"""
        post_processor_frame = ttk.Frame(parent_frame)
        post_processor_frame.pack(side=tk.TOP, anchor='nw', padx=5, pady=5)

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

            self.logger.info("Log post-processor launched successfully")
        except Exception as e:
            self.logger.error(f"Failed to launch log post-processor: {str(e)}")
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

    def _update_sync_control_states(self, armed=False):
        if hasattr(self, "sync_start_button"):
            self.sync_start_button.config(state="normal" if armed else "disabled")

    def handle_sync_start(self):
        beam_pulse = self.subsystems.get('Beam Pulse')
        if not beam_pulse or not hasattr(beam_pulse, "sync_start"):
            self._set_beam_action_status("Failed to sync start, Beam Pulse subsystem not available", "failure")
            return
        beam_pulse.sync_start()

    def handle_sync_stop(self):
        beam_pulse = self.subsystems.get('Beam Pulse')
        if not beam_pulse or not hasattr(beam_pulse, "sync_stop_all"):
            self._set_beam_action_status("Failed to sync stop, Beam Pulse subsystem not available", "failure")
            return
        beam_pulse.sync_stop_all()

    def handle_arm_beams(self):
        """Handle ARM BEAMS toggle press with state management."""
        try:
            # Check if Beam Pulse subsystem is available
            if 'Beam Pulse' not in self.subsystems or self.subsystems['Beam Pulse'] is None:
                self.logger.error("Beam Pulse subsystem not available")
                self._set_beam_action_status("Failed to arm beams, Beam Pulse subsystem not available", "failure")
                return

            beam_pulse = self.subsystems['Beam Pulse']

            # Check current armed state
            if hasattr(beam_pulse, 'get_beams_armed_status') and beam_pulse.get_beams_armed_status():
                # Beams are already armed, so disarm them
                if hasattr(beam_pulse, 'disarm_beams') and beam_pulse.disarm_beams():
                    # Successfully disarmed - update toggle to OFF
                    if self.toggle_on_image and self.toggle_off_image:
                        self.beams_ready_button.config(image=self.toggle_off_image)
                    else:
                        self.beams_ready_button.config(
                            text="ARM BEAMS",
                            bg="sky blue"
                        )
                    # Disable beam toggle buttons, enable toggle buttons and reset states
                    self.update_beam_toggle_states(enabled=False, reset=True)
                    self._update_enable_toggle_states(enabled=False)
                    self._update_sync_control_states(armed=False)
                    self._clear_all_beam_output_displays()
                    self._set_beam_action_status("Beams disarmed", "neutral")
                    self.logger.info("Beams disarmed via dashboard button")
                else:
                    self.logger.error("Failed to disarm beams")
                    self._set_beam_action_status("Failed to disarm beams", "failure")
            else:
                # Beams are not armed, so arm them
                if hasattr(beam_pulse, 'arm_beams') and beam_pulse.arm_beams():
                    # Successfully armed - update toggle to ON
                    if self.toggle_on_image and self.toggle_off_image:
                        self.beams_ready_button.config(image=self.toggle_on_image)
                    else:
                        self.beams_ready_button.config(
                            text="BEAMS ARMED",
                            bg="navy"  # Darker shade of blue
                        )
                    # Enable beam toggle buttons and enable toggle buttons
                    self.update_beam_toggle_states(enabled=True)
                    self._update_enable_toggle_states(enabled=True)
                    self._update_sync_control_states(armed=True)
                    self._set_beam_action_status("Beams armed", "success")
                    self.logger.info("Beams armed via dashboard button")
                else:
                    self.logger.error("Failed to arm beams")
                    self._set_beam_action_status("Failed to arm beams", "failure")

        except Exception as e:
            self.logger.error(f"Error in handle_arm_beams: {str(e)}")
            self._set_beam_action_status(f"Failed to arm beams: {str(e)}", "failure")

    def handle_beams_off(self, reason=None):
        """Handle Beams E-stop button press — force stop all BCON channels,
        turn off cathode heating, and disarm beams."""
        try:
            # Force stop all BCON channels immediately
            if 'Beam Pulse' in self.subsystems and self.subsystems['Beam Pulse'] is not None:
                beam_pulse = self.subsystems['Beam Pulse']
                if hasattr(beam_pulse, 'stop_all_channels'):
                    beam_pulse.stop_all_channels()
                    self.logger.info("All BCON channels force-stopped via E-STOP")

            # Turn off cathode heating power supplies
            if 'Cathode Heating' in self.subsystems and self.subsystems['Cathode Heating'] is not None:
                cathode = self.subsystems['Cathode Heating']
                if hasattr(cathode, 'turn_off_all_beams'):
                    cathode.turn_off_all_beams()
                    self.logger.info("Cathode heating turned off via Beams E-stop button")

            # Disarm beams
            if 'Beam Pulse' in self.subsystems and self.subsystems['Beam Pulse'] is not None:
                beam_pulse = self.subsystems['Beam Pulse']
                if hasattr(beam_pulse, 'get_beams_armed_status') and beam_pulse.get_beams_armed_status():
                    if hasattr(beam_pulse, 'disarm_beams') and beam_pulse.disarm_beams():
                        # Update the ARM BEAMS toggle state to OFF
                        if self.toggle_on_image and self.toggle_off_image:
                            self.beams_ready_button.config(image=self.toggle_off_image)
                        else:
                            self.beams_ready_button.config(
                                text="ARM BEAMS",
                                bg="sky blue"
                            )
                        self.logger.info("Beams disarmed via Beams E-stop button")
                    else:
                        self.logger.error("Failed to disarm beams via Beams E-stop")
                self.update_beam_toggle_states(enabled=False, reset=True)
                self._update_enable_toggle_states(enabled=False)
                self._update_sync_control_states(armed=False)
            self._clear_all_beam_output_displays()
            if reason:
                self._set_beam_action_status(str(reason), "estop")
            else:
                self._set_beam_action_status("Beams E-STOP pressed: All Beams Disabled", "estop")
        except Exception as e:
            self.logger.error(f"Error in handle_beams_off: {str(e)}")
            self._set_beam_action_status(f"Failed to stop beams: {str(e)}", "failure")

    def check_total_emission_current_limit(self, action, channel_indices, configs=None):
        """Return True when the projected emission total is below the configured limit."""
        # Only requested BCON channels A/B/C participate in this limit.
        unique_channels = sorted({
            int(index)
            for index in channel_indices
            if isinstance(index, int) and 0 <= index < 3
        })
        if not unique_channels:
            return True

        currents = [0.0, 0.0, 0.0]
        cathode = getattr(self, "subsystems", {}).get("Cathode Heating")
        getter = getattr(cathode, "get_predicted_emission_currents_ma", None)
        if callable(getter):
            try:
                for index, value in enumerate(list(getter())[:3]):
                    try:
                        numeric_value = float(value)
                    except (TypeError, ValueError):
                        continue
                    if math.isfinite(numeric_value) and numeric_value >= 0:
                        currents[index] = numeric_value
            except Exception as e:
                self.logger.error(f"Could not read Cathode Heating predicted emission currents: {e}")

        projected_total = sum(currents[index] for index in unique_channels)
        limit = self.total_max_emission_current_ma

        # The limit is exclusive: matching the configured cap blocks the action.
        if projected_total < limit:
            return True

        breakdown = ", ".join(
            f"{channel_label(index)}={currents[index]:.3f}mA"
            for index in unique_channels
        )
        self.logger.error(
            f"{action} blocked: predicted total emission current "
            f"{projected_total:.3f}mA is at or above limit {limit:g}mA "
            f"({breakdown})."
        )
        action_key = str(action).strip().lower()
        if action_key == "sync start":
            message = "Failed to sync start, total emission current limit exceeded"
        elif action_key.startswith("beam ") and action_key.endswith(" on"):
            message = f"Failed to set {action}, total emission current limit exceeded"
        else:
            message = f"Failed to {action}, total emission current limit exceeded"
        self._set_beam_action_status(message, "failure")
        return False

    def _toggle_channel_enable(self, ch_index: int):
        """Toggle the hardware enable for a BCON channel (0-based index).

        Only allowed when beams are armed.  When the channel is being
        disabled (enabled -> disabled), also send OFF to ensure the
        channel stops outputting.  Button reflects ON (green) / OFF (gray).
        """
        try:
            beam_pulse = self.subsystems.get('Beam Pulse')
            if not beam_pulse or not hasattr(beam_pulse, 'get_beams_armed_status'):
                self.logger.warning("Beam Pulse subsystem not available")
                self._set_beam_action_status("Failed to toggle channel enable, Beam Pulse subsystem not available", "failure",)
                return
            if not beam_pulse.get_beams_armed_status():
                self._set_beam_action_status("Failed to toggle channel enable, beams are not armed", "failure", )
                self.logger.warning("Cannot toggle enable - beams not armed")
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
                self.logger.warning(detail)
                self._set_beam_action_status(
                    f"Failed to toggle Channel {channel_label(ch_index)} enable: {detail}",
                    "failure",
                )
                return

            self._on_channel_enable_status_update(ch_index, enabled)
            self.logger.info(f"{channel_name(ch_index)} enable -> {'Enabled' if enabled else 'Disabled'}")
            self._set_beam_action_status(
                f"Channel {channel_label(ch_index)} successfully {'enabled' if enabled else 'disabled'}",
                "success",
            )
            if not enabled and ch_index < len(self.beam_toggle_buttons):
                self.beam_toggle_buttons[ch_index].config(
                    bg="gray", text=f"Beam {channel_label(ch_index)} OFF")
        except Exception as e:
            self.logger.error(f"Error toggling {channel_name(ch_index)} enable: {e}")
            self._set_beam_action_status(f"Failed to toggle Channel {channel_label(ch_index)} enable: {e}", "failure")

    def toggle_individual_beam_with_status(self, beam_index):
        """Toggle individual beam on/off.

        ON  = read channel config from Beam Pulse panel and send to BCON.
        OFF = send OFF command for the channel.
        """
        try:
            if 'Beam Pulse' not in self.subsystems or self.subsystems['Beam Pulse'] is None:
                self.logger.error("Beam Pulse subsystem not available")
                self._set_beam_action_status("Failed to toggle beam, Beam Pulse subsystem not available", "failure")
                return

            beam_pulse = self.subsystems['Beam Pulse']

            # Get current beam status
            current_status = beam_pulse.get_beam_status(beam_index)
            btn = self.beam_toggle_buttons[beam_index]

            if current_status:
                # Currently ON -> turn OFF
                if beam_pulse.send_channel_off(beam_index):
                    btn.config(bg="gray", text=f"Beam {channel_label(beam_index)} OFF")
                    self._clear_beam_output_display(beam_index)
                    self._set_beam_action_status(
                        f"Beam {channel_label(beam_index)} successfully set to OFF",
                        "success",
                    )
                    self.logger.info(f"Beam {channel_label(beam_index)} turned OFF")
                else:
                    self._set_beam_action_status(
                        f"Failed to set Beam {channel_label(beam_index)} OFF",
                        "failure",
                    )
                    self.logger.error(f"Failed to set Beam {channel_label(beam_index)} OFF")
            else:
                # Currently OFF -> send channel config to BCON
                config = (
                    beam_pulse.get_channel_config(beam_index)
                    if hasattr(beam_pulse, 'get_channel_config')
                    else {'mode': 'PULSE'}
                )
                mode_label = str(config.get('mode', 'PULSE')).strip().upper()
                # OFF-mode configs do not create beam output, so they skip the emission guard.
                if mode_label != 'OFF':
                    # Include beams that are already ON because the limit applies to total output.
                    projected_channels = [
                        idx for idx in range(3)
                        if hasattr(beam_pulse, 'get_beam_status') and beam_pulse.get_beam_status(idx)
                    ]
                    if beam_index not in projected_channels:
                        projected_channels.append(beam_index)
                    if not self.check_total_emission_current_limit(
                        f"Beam {channel_label(beam_index)} ON",
                        projected_channels,
                    ):
                        return

                ok = beam_pulse.send_channel_config(beam_index)
                if ok:
                    self._set_beam_output_display(beam_index, config, is_on=True)
                    self._set_beam_action_status(
                        self._beam_success_message(beam_index, config),
                        "success",
                    )
                    btn.config(bg="green", text=f"Beam {channel_label(beam_index)} ON")
                    self.logger.info(f"Beam {channel_label(beam_index)} config sent to BCON")
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
                        failure_message = (f"Failed to send Beam {channel_label(beam_index)} config: "f"{failure_message}")
                    else:
                        failure_message = f"Failed to send Beam {channel_label(beam_index)} config"
                    self._set_beam_action_status(failure_message,"failure",)
                    self.logger.error(failure_message)

        except Exception as e:
            self.logger.error(f"Error toggling beam {beam_index}: {str(e)}")
            self._set_beam_action_status(
                f"Failed to toggle Beam {channel_label(beam_index)}: {str(e)}",
                "failure",
            )

    def toggle_individual_beam(self, beam_index):
        """Legacy method - redirects to new method with status bar."""
        self.toggle_individual_beam_with_status(beam_index)

    def get_beam_pulse_duration(self, beam_index):
        """Get the pulse duration for a specific beam."""
        try:
            if 'Beam Pulse' not in self.subsystems or self.subsystems['Beam Pulse'] is None:
                return 0

            beam_pulse = self.subsystems['Beam Pulse']

            # Get duration from the beam pulse subsystem
            if beam_index == 0 and hasattr(beam_pulse, 'beam_a_duration'):
                return beam_pulse.beam_a_duration.get()
            elif beam_index == 1 and hasattr(beam_pulse, 'beam_b_duration'):
                return beam_pulse.beam_b_duration.get()
            elif beam_index == 2 and hasattr(beam_pulse, 'beam_c_duration'):
                return beam_pulse.beam_c_duration.get()

            return 100.0  # Default fallback
        except Exception as e:
            self.logger.error(f"Error getting beam {beam_index} duration: {str(e)}")
            return 100.0

    def auto_turn_off_beam(self, beam_index):
        """Automatically turn off a beam after pulse duration."""
        try:
            if 'Beam Pulse' not in self.subsystems or self.subsystems['Beam Pulse'] is None:
                return

            beam_pulse = self.subsystems['Beam Pulse']
            beam_names = ["A", "B", "C"]

            # Check if beam is still on before turning off
            if hasattr(beam_pulse, 'get_beam_status') and beam_pulse.get_beam_status(beam_index):
                # Turn off the beam
                if hasattr(beam_pulse, 'set_beam_status'):
                    beam_pulse.set_beam_status(beam_index, False)

                    # Update button appearance
                    btn = self.beam_toggle_buttons[beam_index]
                    btn.config(bg="gray", text=f"Beam {beam_names[beam_index]} OFF")
                    self._clear_beam_output_display(beam_index)

                    self.logger.info(f"Beam {beam_names[beam_index]} automatically turned OFF after pulse duration")

        except Exception as e:
            self.logger.error(f"Error auto-turning off beam {beam_index}: {str(e)}")

    def handle_beam_pulse_callback(self, beam_index, status, duration=0):
        """Handle beam pulse callback for button updates.

        This method is called by the beam pulse subsystem when beam status changes.
        """
        try:
            beam_names = ["A", "B", "C"]

            if status:
                # Beam turned ON - update button display
                if beam_index < len(self.beam_toggle_buttons):
                    self.beam_toggle_buttons[beam_index].config(bg="green", text=f"Beam {beam_names[beam_index]} ON")

                if duration > 0:
                    self.logger.info(f"Beam {beam_names[beam_index]} pulsed for {duration}ms")
                    # Schedule auto turn-off after pulse duration
                    self.root.after(int(duration), lambda: self.auto_turn_off_beam(beam_index))
                else:
                    self.logger.info(f"Beam {beam_names[beam_index]} turned ON, running DC")
            else:
                # Beam turned OFF - update button display
                if beam_index < len(self.beam_toggle_buttons):
                    self.beam_toggle_buttons[beam_index].config(bg="gray", text=f"Beam {beam_names[beam_index]} OFF")
                self._clear_beam_output_display(beam_index)

        except Exception as e:
            self.logger.error(f"Error in beam pulse callback for beam {beam_index}: {str(e)}")

    def _on_channel_status_update(self, ch: int, mode_code: int, remaining: int, status_config=None):
        """Mirror live BCON register state onto Main Control beam displays.

        Called on every register-poll cycle by BeamPulseSubsystem.
        mode_code=0 means OFF; remaining=0 means all pulses delivered.
        """
        if not hasattr(self, 'beam_toggle_buttons') or ch >= len(self.beam_toggle_buttons):
            return
        btn = self.beam_toggle_buttons[ch]
        # DC mode never counts down, so remaining is always 0 in hardware.
        # Treat DC as running whenever mode != OFF to prevent button glitching.
        MODE_DC = 1
        is_running = (mode_code != 0) and (remaining > 0 or mode_code == MODE_DC)
        try:
            if is_running:
                btn.config(bg="green", text=f"Beam {channel_label(ch)} ON")
                if status_config is not None:
                    self._set_beam_output_display(ch, status_config, is_on=True)
            else:
                if str(btn.cget('bg')) == 'green':
                    btn.config(bg="gray", text=f"Beam {channel_label(ch)} OFF")
                self._clear_beam_output_display(ch)
        except Exception:
            pass

    def _on_channel_enable_status_update(self, ch: int, enabled: bool):
        """Mirror firmware-backed channel enable state onto dashboard controls."""
        try:
            if hasattr(self, '_ch_enable_states') and ch < len(self._ch_enable_states):
                self._ch_enable_states[ch] = bool(enabled)

            if hasattr(self, 'enable_toggle_buttons') and ch < len(self.enable_toggle_buttons):
                self.enable_toggle_buttons[ch].config(
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
                self.enable_toggle_buttons[ch].config(state="normal" if armed else "disabled")

            self.update_beam_toggle_states(enabled=armed)
            self._update_sync_control_states(armed=armed)
        except Exception as e:
            self.logger.error(f"Error updating {channel_name(ch)} enable status: {str(e)}")

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
                    btn.config(state="normal" if ch_enabled else "disabled")
                    if reset:
                        btn.config(bg="gray", text=f"Beam {channel_label(i)} OFF")
                        self._clear_beam_output_display(i)
                        if 'Beam Pulse' in self.subsystems and self.subsystems['Beam Pulse'] is not None:
                            beam_pulse = self.subsystems['Beam Pulse']
                            if hasattr(beam_pulse, 'set_beam_status'):
                                beam_pulse.set_beam_status(i, False)
                else:
                    btn.config(state="disabled", bg="gray", text=f"Beam {channel_label(i)} OFF")
                    if reset:
                        self._clear_beam_output_display(i)
                        if 'Beam Pulse' in self.subsystems and self.subsystems['Beam Pulse'] is not None:
                            beam_pulse = self.subsystems['Beam Pulse']
                            if hasattr(beam_pulse, 'set_beam_status'):
                                beam_pulse.set_beam_status(i, False)

        except Exception as e:
            self.logger.error(f"Error updating beam toggle states: {str(e)}")

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
                    btn.config(state="normal")
                else:
                    # Disarmed — force all to Disabled appearance and reset tracking
                    if hasattr(self, '_ch_enable_states') and i < len(self._ch_enable_states):
                        self._ch_enable_states[i] = False
                    btn.config(
                        state="disabled",
                        bg="#888888",
                        text=f"CH {channel_label(i)}: Disabled",
                    )
        except Exception as e:
            self.logger.error(f"Error updating enable toggle states: {str(e)}")

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
            'TempControllers', 'Interlocks', 'ProcessMonitors', 'KnobBox']:
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
            port_var = tk.StringVar(value=get_beam_pulse_com_port(self.com_ports))
            self.port_selections['BeamPulse'] = port_var
            dropdown = ttk.Combobox(frame, textvariable=port_var)
            dropdown.pack(side=tk.RIGHT)
            self.port_dropdowns['BeamPulse'] = dropdown

        ttk.Button(self.com_port_menu, text="Apply", command=self.apply_com_port_changes).pack(pady=5)

    def toggle_com_port_menu(self):
        if self.com_port_menu.winfo_viewable():
            self.com_port_menu.pack_forget()
            self.com_port_button.config(text="Configure COM Ports")
        else:
            self.update_available_ports()
            self.com_port_menu.pack(after=self.com_port_button, fill=tk.X, expand=True)
            self.com_port_button.config(text="Hide COM Port Configuration")

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

