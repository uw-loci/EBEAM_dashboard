import csv
import json
import math
import os
import sys
import threading
import time
import queue
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from typing import Optional, Dict
from pathlib import Path
from collections import deque

from instrumentctl.BCON import (
    BCONDriver,
    BCONMode,
    MODE_LABEL_TO_CODE,
    MODE_CODE_TO_LABEL,
    CH_BASE,
    CH_MODE_OFF,
    CH_PULSE_MS_OFF,
    CH_COUNT_OFF,
    CH_ENABLE_SET_OFF,
    REG_WATCHDOG_MS,
    REG_TELEMETRY_MS,
    REG_COMMAND,
    REG_SYS_STATE,
    REG_INTERLOCK_OK,
    REG_WATCHDOG_OK,
    REG_CH_STATUS_BASE,
    REG_CH_STATUS_STRIDE,
)
from utils import LogLevel


def resource_path(relative_path):
    """Get absolute path to resource for PyInstaller."""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


CHANNEL_LABELS = ("A", "B", "C")


class BeamPulseSubsystem:
    """Beam Pulse subsystem (BCON) with tabbed GUI interface for pulser controls.

    Provides three control tabs aligned with pulser_test_gui functionality:
      1. Manual Separate Control  — per-channel parameters, mode buttons, enable toggle
      2. Manual All Beams Control — activate enabled beams / disable all beams
      3. Auto CSV Sequence        — load/run/stop CSV pulse sequences

    Hardware communication uses the BCONDriver (Modbus RTU).
    """

    # Mode constants matching the firmware register values
    MODE_OFF         = int(BCONMode.OFF)
    MODE_DC          = int(BCONMode.DC)
    MODE_PULSE       = int(BCONMode.PULSE)
    MODE_PULSE_TRAIN = int(BCONMode.PULSE_TRAIN)
    DEFAULT_WATCHDOG_MS = BCONDriver.DEFAULT_WATCHDOG_MS
    DEFAULT_TELEMETRY_MS = BCONDriver.DEFAULT_TELEMETRY_MS
    # Mirror BCON's pulse limits so UI-triggered commands fail before sending.
    PULSE_DURATION_MIN_MS = BCONDriver.PULSE_DURATION_MIN_MS
    PULSE_DURATION_MAX_MS = BCONDriver.PULSE_DURATION_MAX_MS
    PULSE_COUNT_MAX = BCONDriver.PULSE_COUNT_MAX

    def __init__(self, parent_frame=None, port=None, unit=1, baudrate=115200,
                 logger=None, debug: bool = False):
        """Create the BeamPulseSubsystem.

        Parameters:
            parent_frame: tkinter frame for GUI components (if None, no GUI created)
            port: Serial port for BCON hardware (e.g., 'COM3')
            unit: Modbus unit/slave address (default: 1)
            baudrate: Serial baudrate for Modbus RTU communication (default: 115200)
            logger: optional logger object compatible with utils.LogLevel
            debug: enable debug logs
        """
        self.parent_frame = parent_frame
        self.logger = logger
        self.debug = debug
        self.disable_logging_when_hvolt_off = False
        self.hvolt_on_provider = None

        # Instantiate BCONDriver if port is provided
        if port:
            self.bcon_driver = BCONDriver(
                port=port,
                baudrate=baudrate,
                unit=unit,
                timeout=BCONDriver.DEFAULT_TIMEOUT,
            )
            self._apply_bcon_driver_logging_suppression()
        else:
            self.bcon_driver = None

        # UI-facing queue for driver events (regs, connected, error, …)
        self._ui_queue: queue.Queue = queue.Queue()
        if self.bcon_driver:
            self.bcon_driver.set_ui_queue(self._ui_queue)

        # Status indicators
        self.bcon_connection_status = False
        self._bcon_disconnect_callback_armed = False
        self.beams_armed_status = False
        self.beam_on_status = [False, False, False]
        self.channel_enable_status = [False, False, False]
        self._active_channels: set = set()  # channels currently executing (from registers)

        # Dashboard integration callbacks
        self._action_feedback_callback = None
        self._armed_status_callback = None
        self._beam_activity_callback = None
        self._manual_disconnect_callback = None
        self._disconnect_callback = None
        self._last_beam_activity_sent = None
        self._pending_firmware_acks = deque()
        self._last_send_failure_message = ""
        self._host_toplevel = None
        self._shutdown_in_progress = False
        self._last_interlock_ok = None
        self._last_watchdog_ok = None
        self._logged_callback_errors = set()

        # CSV sequence player state
        self._seq_steps: list = []
        self._seq_thread: Optional[threading.Thread] = None
        self._seq_stop = threading.Event()

        # Channel status callback — set_channel_status_callback(cb) registers
        # cb(ch, mode_code, remaining, config) called from register polling.
        # config includes mode, duration_ms, count, remaining, and output_level.
        self._channel_status_callback = None

        # Channel enable status callback — set_channel_enable_status_callback(cb)
        # registers a function cb(ch, enabled) called from register polling.
        self._channel_enable_status_callback = None

        # Dashboard-provided raw data sources for Beam Pulse-owned emission checks.
        self._emission_limit_provider = None
        self._predicted_currents_provider = None
        self._emission_limit_enabled_provider = None
        self._vtrx_pressure_guard_enabled_provider = None
        self._vtrx_pressure_provider = None
        self._vtrx_pressure_limit_provider = None
        self._vtrx_pressure_fresh_provider = None

        # Ensure directories exist for presets, logs, sequences
        for d in ("presets", "sequences"):
            Path(d).mkdir(exist_ok=True)

        # GUI variables (populated if parent_frame provided)
        self.channel_vars: list = []      # per-channel widget references

        # Tk after() ids for scheduled callbacks (used to cancel on shutdown)
        self._ui_after_id = None
        self._bcon_mon_after_id = None
        self._pulser_mon_after_id = None
        # Create GUI if parent frame is provided
        if parent_frame:
            self.setup_ui()
            self._register_host_close_hook()

        # Auto-connect in background if a port was supplied
        if self.bcon_driver:
            threading.Thread(target=self._auto_connect, daemon=True).start()

    def _channel_label(self, ch: int) -> str:
        """Return the UI-facing channel label for a 0-based channel index."""
        if 0 <= ch < len(CHANNEL_LABELS):
            return CHANNEL_LABELS[ch]
        return str(ch + 1)

    def _channel_name(self, ch: int) -> str:
        """Return a verbose UI-facing channel name for a 0-based channel index."""
        return f"Channel {self._channel_label(ch)}"

    # ================================================================== #
    #                          GUI Setup                                 #
    # ================================================================== #

    def setup_ui(self):
        """Create the user interface with tabbed layout."""
        scroll_outer = ttk.Frame(self.parent_frame)
        scroll_outer.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(scroll_outer, highlightthickness=0)
        vsb = ttk.Scrollbar(scroll_outer, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)

        ui_root = ttk.Frame(canvas)
        win_id = canvas.create_window((0, 0), window=ui_root, anchor="nw")

        def _on_inner_configure(_event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas_configure(event):
            try:
                canvas.itemconfig(win_id, width=event.width)
            except tk.TclError:
                pass

        ui_root.bind("<Configure>", _on_inner_configure)
        canvas.bind("<Configure>", _on_canvas_configure)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        def _on_mousewheel(event):
            if event.delta:
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            elif getattr(event, "num", None) == 4:
                canvas.yview_scroll(-1, "units")
            elif getattr(event, "num", None) == 5:
                canvas.yview_scroll(1, "units")

        canvas.bind("<Enter>", lambda _e: canvas.focus_set())
        canvas.bind("<MouseWheel>", _on_mousewheel)
        canvas.bind("<Button-4>", _on_mousewheel)
        canvas.bind("<Button-5>", _on_mousewheel)

        self._bp_ui_root = ui_root

        # Top status bar (BCON connection + safety)
        self._build_status_bar()

        # Notebook with three tabs
        self.notebook = ttk.Notebook(ui_root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Tab 1: Manual Separate Control
        self.manual_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.manual_tab, text="Manual Control")
        self._build_manual_tab()

        # Tab 2: Auto CSV Sequence
        self.sequence_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.sequence_tab, text="CSV Sequence")
        self._build_csv_sequence_tab()

        # Start periodic UI update from driver queue
        self._start_periodic_ui_update()

        # Start connection & pulser status monitoring
        self.start_bcon_connection_monitoring()
        self.start_pulser_status_monitoring()

    def _register_host_close_hook(self) -> None:
        """Disconnect BCON when the owning Tk toplevel is destroyed."""
        if not self.parent_frame:
            return
        try:
            toplevel = self.parent_frame.winfo_toplevel()
        except Exception:
            return
        if toplevel is self._host_toplevel:
            return
        self._host_toplevel = toplevel
        try:
            toplevel.bind("<Destroy>", self._on_host_destroy, add="+")
        except Exception:
            self._host_toplevel = None

    def _shutdown_for_host_close(self) -> None:
        """One-shot shutdown path used when the dashboard window is closing."""
        if self._shutdown_in_progress:
            return
        self._shutdown_in_progress = True
        try:
            self.disconnect()
        except Exception:
            pass

    def _on_host_destroy(self, event) -> None:
        """Tear down BCON when the dashboard toplevel is being destroyed."""
        if self._host_toplevel is None or event.widget is not self._host_toplevel:
            return
        self._shutdown_for_host_close()

    # ----------------------------- Status bar ----------------------------- #

    def _build_status_bar(self):
        """Build the top status bar with connection, interlock, arm info."""
        bar = ttk.Frame(self._bp_ui_root)
        bar.pack(fill=tk.X, padx=5, pady=(5, 0))

        # BCON connection indicator
        conn_frame = ttk.Frame(bar)
        conn_frame.pack(side=tk.LEFT, padx=(0, 10))
        ttk.Label(conn_frame, text="BCON", font=("Arial", 9, "bold")).pack(side=tk.LEFT)
        self.bcon_connection_canvas = tk.Canvas(conn_frame, width=15, height=15, highlightthickness=0)
        self.bcon_connection_canvas.pack(side=tk.LEFT, padx=(4, 0))
        self.bcon_connection_canvas.create_oval(2, 2, 13, 13, fill="red", outline="black", tags="indicator")

        # Safety / interlock label
        self.safety_label = ttk.Label(bar, text="Interlock: --  Watchdog: --", font=("Arial", 8))
        self.safety_label.pack(side=tk.LEFT, padx=10)

        self.connect_btn = ttk.Button(bar, text="Connect", command=self._manual_connect)
        self.connect_btn.pack(side=tk.RIGHT, padx=4)

        # System settings row (watchdog / telemetry)
        sys_frame = ttk.Frame(self._bp_ui_root)
        sys_frame.pack(fill=tk.X, padx=5, pady=(2, 0))
        ttk.Label(sys_frame, text="Watchdog (ms):", font=("Arial", 8)).pack(side=tk.LEFT)
        self.watchdog_entry = ttk.Entry(sys_frame, width=7)
        self.watchdog_entry.insert(0, str(self.DEFAULT_WATCHDOG_MS))
        self.watchdog_entry.pack(side=tk.LEFT, padx=2)
        ttk.Button(sys_frame, text="Set", width=4, command=self._set_watchdog).pack(side=tk.LEFT, padx=(0, 8))

        # Log line
        self.log_label = ttk.Label(sys_frame, text="Log: ready", font=("Arial", 8), foreground="gray")
        self.log_label.pack(side=tk.RIGHT, padx=4)

    # ----------------------------- Tab 1: Manual Separate Control ----------------------------- #

    def _build_manual_tab(self):
        """Build per-channel control cards (like pulser_test_gui channel cards)."""
        container = ttk.Frame(self.manual_tab, padding="5")
        container.pack(fill=tk.BOTH, expand=True)

        self.pulser_status_canvases = []
        self.pulser_enabled_canvases = []

        # Validation command: allow only whole numbers (digits only, may be empty)
        _int_vcmd = (container.register(lambda s: s.isdigit() or s == ""), "%P")

        # --- Per-channel control cards (horizontal layout) ---
        cards_frame = ttk.Frame(container)
        cards_frame.pack(fill=tk.BOTH, expand=True)
        cards_frame.columnconfigure(0, weight=1)
        cards_frame.columnconfigure(1, weight=1)
        cards_frame.columnconfigure(2, weight=1)

        self.channel_vars = []
        for ch in range(3):
            frame = ttk.LabelFrame(cards_frame, text=self._channel_name(ch), padding="5")
            frame.grid(row=0, column=ch, sticky="nsew", pady=4, padx=4)

            # Row 1: Mode selector
            r1 = ttk.Frame(frame)
            r1.pack(fill=tk.X, pady=2)
            ttk.Label(r1, text="Mode:").pack(side=tk.LEFT)
            mode_cb = ttk.Combobox(r1, values=["OFF", "DC", "PULSE", "PULSE_TRAIN"],
                                   state="readonly", width=12)
            mode_cb.set("PULSE")
            mode_cb.pack(side=tk.LEFT, padx=4)

            # Row 2: Duration + Count (digits-only input)
            r2 = ttk.Frame(frame)
            r2.pack(fill=tk.X, pady=2)
            ttk.Label(r2, text="Duration (ms):").pack(side=tk.LEFT)
            dur_entry = ttk.Entry(r2, width=8, validate="key", validatecommand=_int_vcmd)
            dur_entry.insert(0, "100")
            dur_entry.pack(side=tk.LEFT, padx=(2, 10))
            ttk.Label(r2, text="Count:").pack(side=tk.LEFT)
            cnt_entry = ttk.Entry(r2, width=6, validate="key", validatecommand=_int_vcmd)
            cnt_entry.insert(0, "1")
            cnt_entry.pack(side=tk.LEFT, padx=2)

            def _on_mode_change(event, d=dur_entry, c=cnt_entry, m=mode_cb):
                mode = m.get()
                if mode in ("OFF", "DC"):
                    d.config(state="normal")
                    c.config(state="normal")
                    self._safe_fill(d, "100")
                    self._safe_fill(c, "1")
                    d.config(state="disabled")
                    c.config(state="disabled")
                elif mode == "PULSE":
                    d.config(state="normal")
                    self._safe_fill(d, "100")
                    c.config(state="normal")
                    c.delete(0, "end")
                    c.insert(0, "1")
                    c.config(state="disabled")
                else:  # PULSE_TRAIN
                    d.config(state="normal")
                    c.config(state="normal")
                    self._safe_fill(d, "100")
                    self._safe_fill(c, "1")

            mode_cb.bind("<<ComboboxSelected>>", _on_mode_change)
            # Apply initial state (PULSE: count grayed out)
            cnt_entry.config(state="disabled")

            # Row 3: Status / pulses remaining
            r3 = ttk.Frame(frame)
            r3.pack(fill=tk.X, pady=2)
            status_lbl = ttk.Label(r3, text="Status: idle", font=("Arial", 8))
            status_lbl.pack(side=tk.LEFT, padx=(0, 15))
            pulses_lbl = ttk.Label(r3, text="Remaining: 0", font=("Arial", 8))
            pulses_lbl.pack(side=tk.LEFT)

            self.channel_vars.append({
                'duration': dur_entry,
                'count': cnt_entry,
                'mode': mode_cb,
                'status': status_lbl,
                'pulses': pulses_lbl,
            })

    # ----------------------------- Tab 2: CSV Sequence ----------------------------- #

    def _build_csv_sequence_tab(self):
        """Build CSV pulse sequence player interface."""
        container = ttk.Frame(self.sequence_tab, padding="5")
        container.pack(fill=tk.BOTH, expand=True)

        self.seq_file_lbl = ttk.Label(container, text="No sequence loaded", foreground="gray")
        self.seq_file_lbl.pack(anchor="w", padx=4)

        self.seq_progress_lbl = ttk.Label(container, text="")
        self.seq_progress_lbl.pack(anchor="w", padx=4, pady=(2, 4))

        button_container = ttk.Frame(container, padding="0")
        button_container.pack(fill=tk.X, padx=6, pady=(4, 2))

        row1 = ttk.Frame(button_container)
        row1.pack(fill=tk.X, pady=1)
        ttk.Button(row1, text="Load CSV",
                   command=self._load_sequence).pack(
                   side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 2))
        ttk.Button(row1, text="Save Template",
                   command=self._save_sequence_template).pack(
                   side=tk.LEFT, fill=tk.X, expand=True)

        row2 = ttk.Frame(button_container)
        row2.pack(fill=tk.X, pady=1)
        self.seq_run_btn = ttk.Button(row2, text="Run Sequence",
                                      state="disabled", command=self._run_sequence)
        self.seq_run_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 2))
        self.seq_stop_btn = ttk.Button(row2, text="Stop Sequence",
                                       state="disabled", command=self._stop_sequence)
        self.seq_stop_btn.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Sequence preview (simple text view)
        ttk.Label(container, text="Loaded Steps:", font=("Arial", 9, "bold")).pack(anchor="w", padx=4, pady=(4, 0))
        self.seq_preview_text = tk.Text(container, height=10, width=60, state="disabled", font=("Courier", 9))
        self.seq_preview_text.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

    # ================================================================== #
    #                         Manual Tab Actions                         #
    # ================================================================== #

    def _require_armed(self) -> bool:
        """Return True if beams are armed; log a warning and return False otherwise.

        Call this at the top of every action that sends commands to BCON.
        Stop / disarm / off actions should NOT call this — they must always work.
        """
        if not self.beams_armed_status:
            self._log_event("Action blocked: beams are not armed", LogLevel.WARNING)
            return False
        return True

    def _set_last_send_failure(self, message: str) -> None:
        self._last_send_failure_message = str(message or "")

    def _clear_last_send_failure(self) -> None:
        self._last_send_failure_message = ""

    def get_last_send_failure_message(self) -> str:
        return getattr(self, "_last_send_failure_message", "")

    def _bcon_is_connected(self) -> bool:
        """Return whether BCON can receive commands.

        Real BCON drivers expose is_connected(); test doubles or older driver
        shims without that method are treated as connected once present.
        """
        if not getattr(self, "bcon_driver", None):
            return False
        checker = getattr(self.bcon_driver, "is_connected", None)
        if not callable(checker):
            return True
        try:
            return bool(checker())
        except Exception:
            return False

    # Shared validation for every Beam Pulse path that can start output.
    # It also records a short failure message for action status displays.
    def _invalid_config(self, context: str, detail: str, show_error: bool = True):
        message = f"{context}: {detail}"
        self._set_last_send_failure(message)
        if show_error:
            self._log_event(message, LogLevel.ERROR)
            messagebox.showerror("Invalid Configuration", message)
        return None

    def _validate_config_values(
        self,
        context: str,
        mode_label,
        duration_value,
        count_value,
        show_error: bool = True,
    ) -> 'Dict | None':
        mode_label = str(mode_label).strip().upper()
        if mode_label not in MODE_LABEL_TO_CODE:
            return self._invalid_config(context, f"unknown mode '{mode_label}'", show_error)

        if mode_label in ('OFF', 'DC'):
            return {'mode': mode_label, 'duration_ms': 0, 'count': 1}

        try:
            duration = int(str(duration_value).strip())
        except (ValueError, TypeError):
            return self._invalid_config(
                context,
                "duration must be a whole number of ms",
                show_error,
            )
        if not (self.PULSE_DURATION_MIN_MS <= duration <= self.PULSE_DURATION_MAX_MS):
            return self._invalid_config(
                context,
                f"duration must be {self.PULSE_DURATION_MIN_MS}-{self.PULSE_DURATION_MAX_MS} ms",
                show_error,
            )

        if mode_label == 'PULSE':
            return {'mode': mode_label, 'duration_ms': duration, 'count': 1}

        try:
            count = int(str(count_value).strip())
        except (ValueError, TypeError):
            return self._invalid_config(context, "count must be a whole number", show_error)
        if not (2 <= count <= self.PULSE_COUNT_MAX):
            return self._invalid_config(
                context,
                f"PULSE_TRAIN count must be 2-{self.PULSE_COUNT_MAX}",
                show_error,
            )

        return {'mode': mode_label, 'duration_ms': duration, 'count': count}

    def _update_armed_button_states(self, armed: bool) -> None:
        """Enable or disable all BCON-action buttons to match the armed state.

        seq_run_btn is only re-enabled when armed AND a sequence is loaded.
        Stop buttons are never touched here (they must always be accessible).
        """
        new_state = "normal" if armed else "disabled"
        for btn in getattr(self, '_armed_gated_buttons', []):
            try:
                btn.configure(state=new_state)
            except Exception:
                pass
        # seq_run_btn: enable only when armed AND sequence already loaded
        if hasattr(self, 'seq_run_btn'):
            try:
                if armed and self._seq_steps:
                    self.seq_run_btn.configure(state="normal")
                else:
                    self.seq_run_btn.configure(state="disabled")
            except Exception:
                pass

    @staticmethod
    def _safe_emission_current_ma(value):
        """Return a valid predicted current in mA, or None when unknown/invalid."""
        if value is None:
            return None
        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(numeric_value) or numeric_value < 0:
            return None
        return numeric_value

    def _read_emission_limit_ma(self):
        provider = getattr(self, "_emission_limit_provider", None)
        if not callable(provider):
            return None, "emission limit provider unavailable"
        try:
            limit = float(provider())
        except Exception as e:
            return None, f"emission limit provider failed ({e})"
        if not math.isfinite(limit) or limit < 0:
            return None, "emission limit is invalid"
        return limit, None

    def _read_predicted_emission_currents_ma(self):
        provider = getattr(self, "_predicted_currents_provider", None)
        if not callable(provider):
            return None, "predicted emission current provider unavailable"
        try:
            raw_values = list(provider() or [])
        except Exception as e:
            return None, f"predicted emission current provider failed ({e})"
        currents = [None, None, None]
        for index, value in enumerate(raw_values[:3]):
            currents[index] = self._safe_emission_current_ma(value)
        return currents, None

    def _prediction_unavailable_detail(self, currents, projected_channels):
        unknown_channels = [
            index
            for index in sorted(projected_channels)
            if index >= len(currents) or currents[index] is None
        ]
        if not unknown_channels:
            return None
        labels = ", ".join(self._channel_label(index) for index in unknown_channels)
        return f"predicted emission current unavailable for {labels}"

    def _emission_block_message(self, action: str, detail: str = "total emission current limit exceeded") -> str:
        action_text = str(action or "output start").strip()
        action_key = action_text.lower()
        if action_key == "activate enabled beams":
            return f"Failed to activate enabled beams, {detail}"
        if action_key.startswith("beam ") and action_key.endswith(" on"):
            return f"Failed to set {action_text}, {detail}"
        return f"Failed to {action_text}, {detail}"

    def _vtrx_pressure_allows_output(self, action, log_failure: bool = True):
        enabled_provider = getattr(self, "_vtrx_pressure_guard_enabled_provider", None)
        pressure_provider = getattr(self, "_vtrx_pressure_provider", None)
        limit_provider = getattr(self, "_vtrx_pressure_limit_provider", None)
        fresh_provider = getattr(self, "_vtrx_pressure_fresh_provider", None)
        if not all(callable(provider) for provider in (enabled_provider, pressure_provider, limit_provider)):
            return True, None

        try:
            if not bool(enabled_provider()):
                return True, None
            pressure = pressure_provider()
            limit = limit_provider()
            pressure_is_fresh = bool(fresh_provider()) if callable(fresh_provider) else True
        except Exception as e:
            message = self._emission_block_message(
                action,
                f"VTRX pressure check failed ({e})",
            )
            if log_failure:
                self._log_event(message, LogLevel.WARNING)
            return False, message

        if not pressure_is_fresh:
            detail = "VTRX pressure reading is stale"
            if log_failure:
                self._log_event(f"{action} blocked: {detail}.", LogLevel.WARNING)
            return False, self._emission_block_message(action, detail)

        try:
            pressure = float(pressure)
        except (TypeError, ValueError):
            detail = "VTRX pressure unavailable"
            if log_failure:
                self._log_event(f"{action} blocked: {detail}.", LogLevel.WARNING)
            return False, self._emission_block_message(action, detail)

        try:
            limit = float(limit)
        except (TypeError, ValueError):
            limit = None

        if not math.isfinite(pressure):
            detail = "VTRX pressure unavailable"
            if log_failure:
                self._log_event(f"{action} blocked: {detail}.", LogLevel.WARNING)
            return False, self._emission_block_message(action, detail)

        if limit is None or not math.isfinite(limit):
            message = self._emission_block_message(action, "VTRX pressure limit unavailable")
            if log_failure:
                self._log_event(message, LogLevel.WARNING)
            return False, message

        if pressure <= limit:
            return True, None

        detail = f"VTRX pressure {pressure:g} mbar is above limit {limit:g} mbar"
        if log_failure:
            self._log_event(f"{action} blocked: {detail}.", LogLevel.WARNING)
        return False, self._emission_block_message(action, detail)

    def _beam_checks_allow_output(
        self,
        action,
        configs,
        log_failure: bool = True,
        check_vtrx_pressure: bool = True,
    ):
        """Return (allowed, error_message) before any non-OFF output command."""
        active_channels = {
            index
            for index, is_on in enumerate(getattr(self, "beam_on_status", []))
            if is_on and 0 <= index < 3
        }
        active_channels.update(
            index
            for index in getattr(self, "_active_channels", set())
            if isinstance(index, int) and 0 <= index < 3
        )

        requested_output = set()
        requested_off = set()
        for cfg in configs or []:
            try:
                channel_index = int(cfg.get("ch")) - 1
            except (TypeError, ValueError, AttributeError):
                continue
            if not 0 <= channel_index < 3:
                continue
            mode = str(cfg.get("mode", "")).strip().upper()
            if mode == "OFF":
                requested_off.add(channel_index)
            else:
                requested_output.add(channel_index)

        if not requested_output:
            return True, None

        projected_channels = (active_channels - requested_off) | requested_output
        if not projected_channels:
            return True, None

        if check_vtrx_pressure:
            allowed, error_message = self._vtrx_pressure_allows_output(action, log_failure)
            if not allowed:
                return False, error_message

        enabled_provider = getattr(self, "_emission_limit_enabled_provider", None)
        if callable(enabled_provider):
            try:
                if not bool(enabled_provider()):
                    return True, None
            except Exception as e:
                if log_failure:
                    self._log_event(
                        f"Emission limit enable provider failed ({e}); keeping emission limit active.",
                        LogLevel.WARNING,
                    )

        currents, error_message = self._read_predicted_emission_currents_ma()
        if error_message:
            message = self._emission_block_message(action, error_message)
            if log_failure:
                self._log_event(message, LogLevel.WARNING)
            return False, message

        unavailable_detail = self._prediction_unavailable_detail(currents, projected_channels)
        if unavailable_detail:
            message = self._emission_block_message(action, unavailable_detail)
            if log_failure:
                self._log_event(f"{action} blocked: {unavailable_detail}.", LogLevel.WARNING)
            return False, message

        limit, error_message = self._read_emission_limit_ma()
        if error_message:
            message = self._emission_block_message(action, error_message)
            if log_failure:
                self._log_event(message, LogLevel.WARNING)
            return False, message

        projected_total = sum(currents[index] for index in sorted(projected_channels))
        if projected_total < limit:
            return True, None

        breakdown = ", ".join(
            f"{self._channel_label(index)}={currents[index]:.3f}mA"
            for index in sorted(projected_channels)
        )
        if log_failure:
            self._log_event(
                f"{action} blocked: predicted total emission current "
                f"{projected_total:.3f}mA is at or above limit {limit:g}mA "
                f"({breakdown}).",
                LogLevel.WARNING,
            )
        return False, self._emission_block_message(action)

    def activate_enabled_beams(self):
        """Synchronous start of enabled channels using Manual Control tab configuration.

        Only channels that are currently hardware-enabled are included.
        """
        if not self._require_armed():
            self._notify_action_feedback(
                "status",
                "Failed to activate enabled beams, beams are not armed",
                "failure",
            )
            return
        if not self.bcon_driver:
            self._log_event("Failed to activate enabled beams, BCON driver not available", LogLevel.ERROR)
            self._notify_action_feedback(
                "status",
                "Failed to activate enabled beams, BCON driver not available",
                "failure",
            )
            return
        if not self._bcon_is_connected():
            self._log_event("Failed to activate enabled beams, BCON device not connected", LogLevel.ERROR)
            self._notify_action_feedback(
                "status",
                "Failed to activate enabled beams, BCON device not connected",
                "failure",
            )
            return

        enable_states = list(getattr(self, "channel_enable_status", [True, True, True]))

        configs = []
        for ch in range(3):
            if ch >= len(self.channel_vars):
                continue
            if not enable_states[ch] if ch < len(enable_states) else False:
                self._log_event(f"Activate Enabled Beams: {self._channel_name(ch)} skipped (not enabled)", LogLevel.DEBUG)
                continue
            config = self._validate_and_get_config(ch)
            if config is None:
                message = self.get_last_send_failure_message() or "invalid configuration"
                self._notify_action_feedback(
                    "status",
                    f"Failed to activate enabled beams: {message}",
                    "failure",
                )
                return
            configs.append({
                'ch': ch + 1,
                'mode': config['mode'],
                'duration_ms': config['duration_ms'],
                'count': config['count'],
            })

        if configs:
            allowed, error_message = self._beam_checks_allow_output("Activate Enabled Beams", configs)
            if not allowed:
                # Surface guard-rail failures without writing to BCON.
                if error_message:
                    message = error_message
                else:
                    message = "Failed to activate enabled beams, total emission current limit exceeded"
                self._notify_action_feedback("status", message, "failure")
                return

            ack = self._queue_firmware_ack("Activate Enabled Beams")
            if not self.bcon_driver.sync_start(configs):
                self._cancel_firmware_ack(ack)
                self._notify_action_feedback(
                    "status",
                    "Failed to activate enabled beams, BCON did not queue command",
                    "failure",
                )
                self._log_event("Activate Enabled Beams failed: BCON did not queue command", LogLevel.ERROR)
                return
            self._notify_action_feedback("beams_sent", "", "success", configs)
            self._log_event("Activate Enabled Beams sent to BCON")
        else:
            # No channels were eligible, so line 4 gets status but lines 1-3 stay unchanged.
            self._notify_action_feedback(
                "status",
                "Activate Enabled Beams skipped: no enabled channels",
                "neutral",
            )
            self._log_event("Activate Enabled Beams skipped: no enabled channels", LogLevel.WARNING)

    def disable_all_beams(self):
        """Stop all channels immediately."""
        if not self.bcon_driver:
            message = "Disable All Beams failed: BCON driver not available"
            self._notify_action_feedback("status", message, "failure")
            self._log_event(message, LogLevel.ERROR)
            return
        ack = self._queue_firmware_ack("Disable All Beams")
        if not self.bcon_driver.stop_all():
            self._cancel_firmware_ack(ack)
            message = "Disable All Beams failed: BCON did not queue command"
            self._notify_action_feedback("status", message, "failure")
            self._log_event(message, LogLevel.ERROR)
            return
        self._clear_output_state()
        self._notify_action_feedback(
            "all_off",
            "Disable All Beams: all channels -> OFF",
            "neutral",
        )
        self._log_event("Disable All Beams: all channels -> OFF")

    # ================================================================== #
    #                      CSV Sequence Tab Actions                      #
    # ================================================================== #

    def _load_sequence(self):
        """Load a CSV pulse sequence file."""
        fname = filedialog.askopenfilename(
            initialdir="sequences",
            filetypes=[("CSV Sequence", "*.csv"), ("All files", "*.*")],
            title="Load Pulse Sequence CSV",
        )
        if not fname:
            return
        try:
            steps_raw: dict = {}
            with open(fname, newline="") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or line.lower().startswith("step"):
                        continue
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) < 3:
                        self._log_event(f"Sequence row skipped: malformed row '{line}'", LogLevel.WARNING)
                        continue
                    step_num = int(parts[0])
                    ch_str   = parts[1].upper()
                    mode     = parts[2].upper()
                    dur_ms   = int(parts[3]) if len(parts) > 3 and parts[3] else 100
                    count    = int(parts[4]) if len(parts) > 4 and parts[4] else 1
                    dwell_ms = int(parts[5]) if len(parts) > 5 and parts[5] else 0

                    if mode not in MODE_LABEL_TO_CODE:
                        raise ValueError(f"Unknown mode '{mode}' at step {step_num}")
                    config = self._validate_config_values(f"Step {step_num}",mode,dur_ms,count,show_error=False,)
                    if config is None:
                        raise ValueError(self.get_last_send_failure_message())

                    if ch_str == "ALL":
                        ch_list = list(range(3))
                    else:
                        ch_idx = int(ch_str) - 1
                        if not 0 <= ch_idx < 3:
                            raise ValueError(f"Step {step_num}: channel must be 1, 2, 3, or ALL")
                        ch_list = [ch_idx]
                    if step_num not in steps_raw:
                        steps_raw[step_num] = {"rows": [], "dwell_ms": 0}
                    for ch_idx in ch_list:
                        steps_raw[step_num]["rows"].append(
                            {
                                "ch": ch_idx,
                                "mode": config["mode"],
                                "duration_ms": config["duration_ms"],
                                "count": config["count"],
                            }
                        )
                    steps_raw[step_num]["dwell_ms"] = dwell_ms

            self._seq_steps = [
                (sn, steps_raw[sn]["rows"], steps_raw[sn]["dwell_ms"])
                for sn in sorted(steps_raw.keys())
            ]
            n = len(self._seq_steps)
            self.seq_file_lbl.configure(
                text=f"{os.path.basename(fname)}  ({n} step{'s' if n != 1 else ''})")
            self.seq_progress_lbl.configure(text="Ready")
            # Only enable Run Sequence if beams are currently armed
            if hasattr(self, 'seq_run_btn'):
                self.seq_run_btn.configure(
                    state="normal" if self.beams_armed_status else "disabled")

            # Update preview
            self.seq_preview_text.configure(state="normal")
            self.seq_preview_text.delete("1.0", tk.END)
            for sn, rows, dwell in self._seq_steps:
                for row in rows:
                    self.seq_preview_text.insert(tk.END,
                        f"Step {sn}: {self._channel_name(row['ch'])} {row['mode']} "
                        f"dur={row['duration_ms']}ms cnt={row['count']}  dwell={dwell}ms\n")
            self.seq_preview_text.configure(state="disabled")

            self._log_event(f"Sequence loaded: {os.path.basename(fname)} ({n} steps)")
        except Exception as e:
            messagebox.showerror("Sequence Load Error", str(e))
            self._log_event(f"Sequence load failed: {e}", LogLevel.ERROR)

    def _save_sequence_template(self):
        """Save a CSV template file for reference."""
        fname = filedialog.asksaveasfilename(
            defaultextension=".csv",
            initialdir="sequences",
            filetypes=[("CSV Sequence", "*.csv")],
            title="Save Sequence Template",
        )
        if not fname:
            return
        template = (
            "# BCON Pulse Sequence\n"
            "# ============================================================\n"
            "# Columns:\n"
            "#   step        - integer; rows sharing a step number launch together\n"
            "#   ch          - channel number (1, 2, 3) or ALL\n"
            "#   mode        - OFF | DC | PULSE | PULSE_TRAIN\n"
            "#   duration_ms - pulse width in ms  (PULSE / PULSE_TRAIN only)\n"
            "#   count       - pulse count        (PULSE_TRAIN must be >= 2)\n"
            "#   dwell_ms    - wait AFTER this step before the next one\n"
            "#                 (only the last row per step number is used)\n"
            "# ============================================================\n"
            "step,ch,mode,duration_ms,count,dwell_ms\n"
            "1,1,PULSE,100,5,0\n"
            "1,2,PULSE,200,1,0\n"
            "1,3,DC,,,500\n"
            "2,1,PULSE_TRAIN,50,10,0\n"
            "2,2,OFF,,,0\n"
            "2,3,OFF,,,1000\n"
            "3,ALL,OFF,,,500\n"
        )
        with open(fname, "w") as f:
            f.write(template)
        self._log_event(f"Sequence template saved: {os.path.basename(fname)}")

    def _run_sequence(self):
        """Start running the loaded CSV sequence."""
        if not self._require_armed():
            self._notify_action_feedback(
                "status",
                "Failed to run sequence, beams are not armed",
                "failure",
            )
            return
        if not self._seq_steps:
            self._log_event("Failed to run sequence, no sequence loaded", LogLevel.WARNING)
            messagebox.showinfo("Sequence", "No sequence loaded.")
            self._notify_action_feedback(
                "status",
                "Failed to run sequence, no sequence loaded",
                "failure",
            )
            return
        if not self._bcon_is_connected():
            self._log_event("Failed to run sequence, BCON device not connected", LogLevel.ERROR)
            messagebox.showwarning("Sequence", "Not connected to BCON device.")
            self._notify_action_feedback(
                "status",
                "Failed to run sequence, BCON device not connected",
                "failure",
            )
            return
        if self._seq_thread and self._seq_thread.is_alive():
            self._log_event("Failed to run sequence, sequence already running", LogLevel.WARNING)
            return
        self._seq_stop.clear()
        if hasattr(self, 'seq_run_btn'):
            self.seq_run_btn.configure(state="disabled")
        if hasattr(self, 'seq_stop_btn'):
            self.seq_stop_btn.configure(state="normal")
        self._seq_thread = threading.Thread(target=self._sequence_worker, daemon=True)
        self._seq_thread.start()
        self._notify_action_feedback("status", "Sequence started", "success")
        self._log_event("Sequence started")

    def _stop_sequence(self):
        """Request sequence stop."""
        self._seq_stop.set()
        self._ui_queue.put((
            "action_feedback",
            "status",
            "Sequence stop requested",
            "neutral",
            None,
        ))
        self._log_event("Sequence stop requested")

    def _queue_seq_status(self, text: str, level=LogLevel.INFO) -> None:
        """Queue a sequence status update with an explicit dashboard log level."""
        self._ui_queue.put(("seq_status", text, self._coerce_log_level(level).name))

    def _sequence_worker(self):
        """Background thread that plays the CSV sequence."""
        total = len(self._seq_steps)
        failed = False
        stopped_for_disarm = False
        for idx, (step_num, rows, dwell_ms) in enumerate(self._seq_steps):
            if self._seq_stop.is_set():
                break
            if not self.beams_armed_status:
                stopped_for_disarm = True
                break
            # Update progress via queue
            self._queue_seq_status(f"Step {idx+1}/{total} (#{step_num})", LogLevel.VERBOSE)

            configs = []
            for row in rows:
                config = self._validate_config_values(
                    f"CSV Sequence step {step_num} {self._channel_name(row['ch'])}",
                    row["mode"],
                    row["duration_ms"],
                    row["count"],
                    show_error=False,
                )
                if config is None:
                    message = (
                        f"Failed to CSV Sequence step {step_num}: "
                        f"{self.get_last_send_failure_message()}"
                    )
                    self._queue_seq_status(message, LogLevel.ERROR)
                    self._ui_queue.put(("action_feedback", "status", message, "failure", None))
                    self._seq_stop.set()
                    failed = True
                    break
                configs.append({
                    "ch": row["ch"] + 1,
                    "mode": config["mode"],
                    "duration_ms": config["duration_ms"],
                    "count": config["count"],
                })
            if failed:
                break
            if self._seq_stop.is_set():
                break
            if not self.beams_armed_status:
                stopped_for_disarm = True
                break

            allowed, error_message = self._beam_checks_allow_output(
                f"CSV Sequence step {step_num}",
                configs,
                log_failure=False,
            )
            if not allowed:
                if error_message:
                    self._queue_seq_status(error_message, LogLevel.ERROR)
                    message = error_message
                else:
                    message = (
                        f"Failed to CSV Sequence step {step_num}, "
                        "total emission current limit exceeded"
                    )
                    self._queue_seq_status(message, LogLevel.ERROR)
                self._ui_queue.put(("action_feedback", "status", message, "failure", None))
                self._seq_stop.set()
                failed = True
                break
            if not self.bcon_driver.sync_start(configs):
                message = f"Failed to CSV Sequence step {step_num}, BCON did not queue command"
                self._queue_seq_status(message, LogLevel.ERROR)
                self._ui_queue.put(("action_feedback", "status", message, "failure", None))
                self._seq_stop.set()
                failed = True
                break
            self._ui_queue.put((
                "action_feedback",
                "beams_sent",
                f"CSV Sequence step {step_num} sent to BCON",
                "success",
                configs,
            ))

            # Dwell
            deadline = time.time() + dwell_ms / 1000.0
            while time.time() < deadline and not self._seq_stop.is_set():
                time.sleep(0.05)

        if stopped_for_disarm:
            final = "Sequence stopped: beams disarmed"
            final_level = LogLevel.WARNING
        else:
            final = "Sequence complete" if not self._seq_stop.is_set() else "Sequence stopped"
            final_level = LogLevel.INFO
        if not failed:
            outcome = "failure" if stopped_for_disarm else "neutral"
            self._ui_queue.put(("action_feedback", "status", final, outcome, None))
        self._queue_seq_status(final, final_level)
        self._ui_queue.put(("seq_done", None))

    # ================================================================== #
    #                   Periodic UI Update                                 #
    # ================================================================== #

    def _start_periodic_ui_update(self):
        """Poll the driver's UI queue and update widgets."""
        def _tick():
            try:
                while not self._ui_queue.empty():
                    msg = self._ui_queue.get_nowait()
                    self._handle_driver_msg(msg)
            except queue.Empty:
                pass
            if self.parent_frame:
                try:
                    self._ui_after_id = self.parent_frame.after(200, _tick)
                except Exception:
                    self._ui_after_id = None
        if self.parent_frame:
            try:
                self._ui_after_id = self.parent_frame.after(200, _tick)
            except Exception:
                self._ui_after_id = None

    def _handle_driver_msg(self, msg):
        """Process a single message from the driver/UI queue."""
        typ = msg[0]
        if typ == "connected":
            ok = msg[1]
            callback_armed = getattr(self, "_bcon_disconnect_callback_armed", False)
            self.bcon_connection_status = ok
            if ok:
                self._bcon_disconnect_callback_armed = True
            else:
                self._clear_firmware_acks()
                self.beams_armed_status = False
                self._notify_armed_status(False)
                self._clear_output_state()
                self.channel_enable_status = [False, False, False]
                self._update_armed_button_states(False)
                self._notify_all_channel_enables(False)
                callback = getattr(self, "_disconnect_callback", None)
                if callback_armed and callable(callback):
                    try:
                        callback()
                    except Exception as e:
                        self._log_once(f"BCON disconnect callback failed: {e}", LogLevel.ERROR)
                self._bcon_disconnect_callback_armed = False
            self.update_bcon_connection_status()
        elif typ == "regs":
            regs = msg[1]
            self._update_ui_from_registers(regs)
        elif typ == "log":
            # BCON driver queued this from a worker thread; _log handles main-thread UI logging.
            text = str(msg[1])
            level_name = str(msg[2]).upper() if len(msg) > 2 else "INFO"
            level = getattr(LogLevel, level_name, LogLevel.INFO)
            self._log(text, level)
        elif typ == "wrote":
            reg, val = msg[1], msg[2]
            if reg == REG_COMMAND and val != 0:
                return
            self._log_event(f"Wrote R{reg}={val}", LogLevel.DEBUG)
        elif typ == "command_result":
            info = msg[1]
            requested = info.get("requested_label", f"CMD_{info.get('requested_code', '?')}")
            actual = info.get("last_command_label", requested)
            cmd_text = requested if actual == requested else f"{requested}->{actual}"
            seq = info.get("last_cmd_seq", 0)
            ack_context = self._pop_firmware_ack()
            if info.get("rejected"):
                reason = info.get("last_reject_reason", "UNKNOWN")
                message = f"BCON command {cmd_text} rejected: {reason}"
                self._notify_action_feedback("status", message, "failure")
                context_suffix = f" [{ack_context}]" if ack_context else ""
                self._log_event(f"{message} (seq={seq}){context_suffix}", LogLevel.ERROR)
            else:
                result = str(info.get("last_command_result", "UNKNOWN")).lower()
                context_suffix = f" [{ack_context}]" if ack_context else ""
                self._log_event(f"BCON command {cmd_text} {result} (seq={seq}){context_suffix}")
                accepted = bool(info.get("accepted")) or result == "executed"
                if ack_context and accepted:
                    ack_message = f"FW OK: {ack_context}"
                    if seq:
                        ack_message = f"{ack_message} seq={seq}"
                    self._notify_action_feedback("firmware_ack", ack_message, "success")
        elif typ == "error":
            text = str(msg[1])
            level = LogLevel.ERROR if text.startswith((
                "Write reg",
                "Command ",
                "Poll error",
                "Connect failed",
                "Auto-disconnected",
            )) else LogLevel.WARNING
            self._log_event(f"Error: {text}", level)
            if text.startswith("Write reg") or text.startswith("Command "):
                self._clear_firmware_acks()
                self._notify_action_feedback("status", f"BCON send failed: {text}", "failure")
        elif typ == "seq_status":
            text = msg[1]
            level = self._coerce_log_level(msg[2]) if len(msg) > 2 else LogLevel.INFO
            if hasattr(self, 'seq_progress_lbl'):
                self.seq_progress_lbl.configure(text=text)
            self._log_event(text, level)
        elif typ == "action_feedback":
            self._notify_action_feedback(*msg[1:])
        elif typ == "seq_done":
            self._update_armed_button_states(self.beams_armed_status)
            if hasattr(self, 'seq_stop_btn'):
                self.seq_stop_btn.configure(state="disabled")

    def _update_ui_from_registers(self, regs):
        """Mirror register data into GUI widgets (like pulser_test_gui._handle_msg 'regs')."""
        # Update channel state first; manual-tab widgets are optional for headless use.
        channel_vars = getattr(self, "channel_vars", [])
        had_active_output = bool(getattr(self, "_active_channels", set()))
        for ch in range(3):
            has_channel_widgets = ch < len(channel_vars)
            status_base = REG_CH_STATUS_BASE + ch * REG_CH_STATUS_STRIDE

            mode_code = regs[status_base + 0]
            remaining = regs[status_base + 3]
            enabled_state = bool(regs[status_base + 4])
            output_level = regs[status_base + 8]
            # Duration/count feed Dashboard status text.
            base = CH_BASE[ch]
            pulse_ms = regs[base + CH_PULSE_MS_OFF]
            count_val = regs[base + CH_COUNT_OFF]

            if has_channel_widgets:
                st_text = MODE_CODE_TO_LABEL.get(mode_code, "unknown")
                channel_vars[ch]['status'].configure(text=f"Status: {st_text} | O:{output_level}")
                channel_vars[ch]['pulses'].configure(text=f"Remaining: {remaining}")

            # DC mode never counts down (remaining stays 0) — treat it as
            # running whenever mode != OFF so the manual controls stay locked
            # and the dashboard Beam button stays green.
            is_running = (mode_code != self.MODE_OFF) and (
                remaining > 0 or mode_code == self.MODE_DC
            )
            self.beam_on_status[ch] = is_running
            self.channel_enable_status[ch] = enabled_state
            if is_running:
                self._active_channels.add(ch)
            else:
                self._active_channels.discard(ch)
            if has_channel_widgets:
                self._set_manual_channel_lock(ch, is_running)

            # Notify dashboard so beam toggle button colour tracks hardware state
            if callable(getattr(self, '_channel_status_callback', None)):
                try:
                    # The fourth argument lets callers describe the live output mode.
                    self._channel_status_callback(ch, mode_code, remaining,
                        {
                            "mode": MODE_CODE_TO_LABEL.get(mode_code, "OFF"),
                            "duration_ms": pulse_ms,
                            "count": count_val,
                            "remaining": remaining,
                            "output_level": output_level,
                        },
                    )
                except Exception as e:
                    self._log_once(f"Channel status callback failed for {self._channel_name(ch)}: {e}", LogLevel.ERROR)

            if callable(getattr(self, '_channel_enable_status_callback', None)):
                try:
                    self._channel_enable_status_callback(ch, enabled_state)
                except Exception as e:
                    self._log_once(f"Channel enable status callback failed for {self._channel_name(ch)}: {e}", LogLevel.ERROR)

            # NOTE: do NOT push hardware mode back into the mode combobox — that
            # would overwrite the user's intended configuration.  The status label
            # above already shows the live running mode.

        self._notify_beam_activity(bool(self._active_channels))

        # Interlock / watchdog / state
        interlock_ok = regs[REG_INTERLOCK_OK]
        watchdog_ok = regs[REG_WATCHDOG_OK]
        if hasattr(self, 'safety_label'):
            self.safety_label.configure(
                text=f"Interlock: {'ok' if interlock_ok else 'locked'} | "
                     f"Watchdog: {'ok' if watchdog_ok else 'expired'}")
        self._log_safety_transition(bool(interlock_ok), bool(watchdog_ok), had_active_output)

        # Update pulser enabled/overcurrent canvases
        for i in range(3):
            self.update_pulser_status_display(i)

    @staticmethod
    def _safe_fill(entry_widget, value):
        """Overwrite entry only if empty or '0'."""
        try:
            cur = entry_widget.get().strip()
        except Exception:
            return
        if cur == '' or cur == '0':
            entry_widget.delete(0, 'end')
            entry_widget.insert(0, str(value))

    def _set_manual_channel_lock(self, ch: int, locked: bool):
        """Gray out (lock=True) or restore (lock=False) editable widgets for a manual-tab channel."""
        if ch >= len(self.channel_vars):
            return
        cv = self.channel_vars[ch]
        try:
            if locked:
                cv['mode'].configure(state='disabled')
                cv['duration'].configure(state='disabled')
                cv['count'].configure(state='disabled')
            else:
                cv['mode'].configure(state='readonly')
                mode = cv['mode'].get()
                if mode in ('OFF', 'DC'):
                    cv['duration'].configure(state='disabled')
                    cv['count'].configure(state='disabled')
                elif mode == 'PULSE':
                    cv['duration'].configure(state='normal')
                    cv['count'].configure(state='disabled')
                else:  # PULSE_TRAIN
                    cv['duration'].configure(state='normal')
                    cv['count'].configure(state='normal')
        except Exception:
            pass

    def _log_once(self, message: str, level=LogLevel.ERROR) -> None:
        """Log repeated background/callback failures once per unique message."""
        message = str(message)
        if message in self._logged_callback_errors:
            return
        self._logged_callback_errors.add(message)
        self._log_event(message, level)

    def _log_safety_transition(self, interlock_ok: bool, watchdog_ok: bool, had_active_output: bool) -> None:
        """Log BCON interlock/watchdog transitions without spamming every poll."""
        interlock_ok = bool(interlock_ok)
        watchdog_ok = bool(watchdog_ok)

        interlock_became_locked = not interlock_ok and (self._last_interlock_ok is None or self._last_interlock_ok)
        watchdog_became_expired = not watchdog_ok and (self._last_watchdog_ok is None or self._last_watchdog_ok)

        if interlock_became_locked or watchdog_became_expired:
            details = []
            if interlock_became_locked:
                details.append("interlock locked")
            if watchdog_became_expired:
                details.append("watchdog expired")
            level = LogLevel.CRITICAL if had_active_output else LogLevel.WARNING
            self._log_event(f"BCON safety state: {', '.join(details)}", level)

        self._last_interlock_ok = interlock_ok
        self._last_watchdog_ok = watchdog_ok

    # ================================================================== #
    #                         Status Monitoring                          #
    # ================================================================== #

    def start_bcon_connection_monitoring(self):
        """Periodically check BCON driver connection status."""
        def check():
            if self.bcon_driver:
                connected = self.bcon_driver.is_connected()
                if connected != self.bcon_connection_status:
                    self.bcon_connection_status = connected
                    self.update_bcon_connection_status()
            else:
                if self.bcon_connection_status:
                    self.bcon_connection_status = False
                    self.update_bcon_connection_status()
            if self.parent_frame:
                try:
                    self._bcon_mon_after_id = self.parent_frame.after(2000, check)
                except Exception:
                    self._bcon_mon_after_id = None
        if self.parent_frame:
            try:
                self._bcon_mon_after_id = self.parent_frame.after(1000, check)
            except Exception:
                self._bcon_mon_after_id = None

    def start_pulser_status_monitoring(self):
        """Periodically refresh pulser status indicators."""
        def check():
            for i in range(3):
                self.update_pulser_status_display(i)
            if self.parent_frame:
                try:
                    self._pulser_mon_after_id = self.parent_frame.after(500, check)
                except Exception:
                    self._pulser_mon_after_id = None
        if self.parent_frame:
            try:
                self._pulser_mon_after_id = self.parent_frame.after(1000, check)
            except Exception:
                self._pulser_mon_after_id = None

    def update_bcon_connection_status(self):
        """Repaint the BCON connection indicator and connect button label."""
        if hasattr(self, 'bcon_connection_canvas'):
            self.bcon_connection_canvas.delete("indicator")
            color = "green" if self.bcon_connection_status else "red"
            self.bcon_connection_canvas.create_oval(2, 2, 13, 13, fill=color, outline="black", tags="indicator")
        if hasattr(self, 'connect_btn'):
            self.connect_btn.configure(
                text="Disconnect" if self.bcon_connection_status else "Reconnect",
                state="normal"
            )

    def update_pulser_status_display(self, pulser_index: int):
        """Update enabled + overcurrent indicators for a pulser."""
        if not (0 <= pulser_index < 3):
            return
        try:
            # Enabled
            is_enabled = False
            if self.bcon_driver and self.bcon_connection_status:
                is_enabled = self.bcon_driver.is_channel_enabled(pulser_index + 1)
            if pulser_index < len(self.pulser_enabled_canvases):
                ec = self.pulser_enabled_canvases[pulser_index]
                ec.delete("indicator")
                ec.create_oval(2, 2, 13, 13,
                               fill="green" if is_enabled else "gray",
                               outline="black", tags="indicator")
            # Overcurrent
            has_oc = self.get_pulser_overcurrent_status(pulser_index)
            if pulser_index < len(self.pulser_status_canvases):
                sc = self.pulser_status_canvases[pulser_index]
                sc.delete("indicator")
                sc.create_oval(2, 2, 13, 13,
                               fill="red" if has_oc else "green",
                               outline="black", tags="indicator")
        except Exception as e:
            self._log(f"Error updating pulser {pulser_index} status: {e}", LogLevel.ERROR)

    def get_pulser_overcurrent_status(self, pulser_index: int) -> bool:
        """Check overcurrent from BCON driver."""
        if self.bcon_driver and self.bcon_connection_status:
            try:
                return self.bcon_driver.is_channel_overcurrent(pulser_index + 1)
            except Exception as e:
                self._log_once(f"Pulser {pulser_index + 1} overcurrent read failed: {e}", LogLevel.WARNING)
        return False

    # ================================================================== #
    #                  Safety / System Settings Actions                  #
    # ================================================================== #

    def _apply_default_bcon_settings(self) -> None:
        """Apply the dashboard's preferred runtime settings after connect."""
        if not self.bcon_driver or not self.bcon_driver.is_connected():
            return
        self.bcon_driver.set_watchdog(self.DEFAULT_WATCHDOG_MS)
        self.bcon_driver.set_telemetry(self.DEFAULT_TELEMETRY_MS)

    def _stop_sequence_worker(self) -> None:
        """Stop any active CSV sequence worker before disconnecting hardware."""
        self._seq_stop.set()
        if (
            self._seq_thread
            and self._seq_thread.is_alive()
            and threading.current_thread() is not self._seq_thread
        ):
            self._seq_thread.join(timeout=1.0)
            if self._seq_thread.is_alive():
                self._log_event("CSV sequence worker did not stop before timeout", LogLevel.WARNING)
        self._seq_thread = None

    def _auto_connect(self):
        """Background thread: open the serial port and connect to BCON."""
        port = self.bcon_driver.port
        self._queue_seq_status(f"Connecting to BCON on {port}…", LogLevel.DEBUG)
        ok = self.bcon_driver.connect()
        if self._shutdown_in_progress:
            self.bcon_driver.disconnect()
            return
        if ok:
            self._apply_default_bcon_settings()
        msg = f"BCON connected on {port}" if ok else f"BCON connect failed on {port} — check port & firmware"
        # Route via the UI queue so Messages & Errors is updated on the main
        # thread (direct self._log() from a background thread is not safe).
        self._queue_seq_status(msg, LogLevel.INFO if ok else LogLevel.ERROR)

    def _manual_connect(self):
        """Button handler: disconnect when connected, reconnect when disconnected."""
        if self._shutdown_in_progress:
            return
        if not self.bcon_driver:
            self._log_event("BCON connect failed: no port configured", LogLevel.WARNING)
            messagebox.showwarning("Connect", "No port configured for BCON.")
            return
        if self.bcon_driver.is_connected():
            # User clicked "Disconnect" — only tear down, do NOT reconnect.
            callback = getattr(self, "_manual_disconnect_callback", None)
            if callable(callback):
                try:
                    if not callback():
                        return
                except Exception as e:
                    self._log_event(f"BCON manual disconnect callback failed: {e}", LogLevel.ERROR)
                    return
            self.disconnect()
            if hasattr(self, 'connect_btn'):
                self.connect_btn.configure(text="Reconnect", state="normal")
            self._log_event("BCON disconnected by user")
            return
        # User clicked "Reconnect" / "Connect" — open the port.
        if hasattr(self, 'connect_btn'):
            self.connect_btn.configure(state="disabled", text="Connecting…")
            self.parent_frame.after(100, lambda: None)  # force redraw
        def _do():
            ok = self.bcon_driver.connect()
            if self._shutdown_in_progress:
                self.bcon_driver.disconnect()
                return
            if ok:
                self._apply_default_bcon_settings()
            if self.parent_frame:
                try:
                    self.parent_frame.after(0, lambda: self._on_connect_done(ok))
                except Exception:
                    pass
        threading.Thread(target=_do, daemon=True).start()

    def _on_connect_done(self, ok: bool):
        """Called on the main thread after a manual connect attempt."""
        if hasattr(self, 'connect_btn'):
            self.connect_btn.configure(state="normal", text="Disconnect" if ok else "Reconnect")
        if ok:
            self._log_event("BCON connected", LogLevel.INFO)
        else:
            self._log_event("BCON connect failed - check port & firmware", LogLevel.ERROR)

    def _set_watchdog(self):
        """Write the watchdog timeout register."""
        val = self.watchdog_entry.get().strip()
        if not val:
            return
        try:
            ms = int(val)
        except ValueError:
            self._log_event("Invalid watchdog value: must be integer", LogLevel.WARNING)
            messagebox.showerror("Invalid", "Watchdog value must be integer")
            return
        if self.bcon_driver:
            self.bcon_driver.set_watchdog(ms)
            self._log_event(f"Set watchdog = {ms} ms")
        else:
            self._log_event("Failed to set watchdog: BCON driver not available", LogLevel.ERROR)

    # ================================================================== #
    #                          Event Log Helper                          #
    # ================================================================== #

    @staticmethod
    def _coerce_log_level(level) -> LogLevel:
        if isinstance(level, LogLevel):
            return level
        if isinstance(level, str):
            return getattr(LogLevel, level.upper(), LogLevel.INFO)
        try:
            return LogLevel(level)
        except (TypeError, ValueError):
            return LogLevel.INFO

    def _log_event(self, text: str, level=LogLevel.INFO):
        """Log an event to console, label, and CSV session log."""
        level = self._coerce_log_level(level)
        if hasattr(self, 'log_label'):
            try:
                self.log_label.configure(text=text)
            except Exception:
                pass
        self._log(text, level)

    # ================================================================== #
    #           Public API (backward-compatible with dashboard)          #
    # ================================================================== #

    # --- Status access ---

    def set_bcon_connection_status(self, status: bool):
        self.bcon_connection_status = status
        self.update_bcon_connection_status()

    def get_beam_status(self, beam_index: int) -> bool:
        if 0 <= beam_index < 3:
            return self.beam_on_status[beam_index]
        return False

    def set_channel_status_callback(self, callback):
        """Register callback(ch, mode_code, remaining, config) for every register poll.

        The dashboard uses this to keep the Beam A/B/C toggle buttons in sync
        with live hardware state without polling from the dashboard side.
        config includes mode, duration_ms, count, remaining, and output_level.
        """
        self._channel_status_callback = callback

    def set_emission_limit_providers(
        self,
        limit_provider,
        predicted_currents_provider,
        enabled_provider=None,
    ):
        """Register raw data providers used for Beam Pulse-owned emission checks."""
        self._emission_limit_provider = limit_provider
        self._predicted_currents_provider = predicted_currents_provider
        self._emission_limit_enabled_provider = (
            enabled_provider if callable(enabled_provider) else None
        )

    def set_vtrx_pressure_guard_providers(
        self,
        enabled_provider,
        pressure_provider,
        limit_provider=None,
        fresh_provider=None,
    ):
        """Register providers used to block new output starts during high pressure."""
        self._vtrx_pressure_guard_enabled_provider = (
            enabled_provider if callable(enabled_provider) else None
        )
        self._vtrx_pressure_provider = pressure_provider if callable(pressure_provider) else None
        self._vtrx_pressure_limit_provider = limit_provider if callable(limit_provider) else None
        self._vtrx_pressure_fresh_provider = fresh_provider if callable(fresh_provider) else None

    def set_channel_enable_status_callback(self, callback):
        """Register callback(ch, enabled) invoked on every register poll."""
        self._channel_enable_status_callback = callback

    def set_action_feedback_callback(self, callback):
        """Register optional callback for action status events."""
        self._action_feedback_callback = callback

    def set_armed_status_callback(self, callback):
        """Register callback(armed) for software armed-state changes."""
        self._armed_status_callback = callback

    def set_beam_activity_callback(self, callback):
        """Register callback(active) for live any-channel output state."""
        self._beam_activity_callback = callback
        self._last_beam_activity_sent = None
        self._notify_beam_activity(bool(getattr(self, "_active_channels", set())))

    def set_logging_suppression(self, disable_when_hvolt_off, hvolt_on_provider=None):
        self.disable_logging_when_hvolt_off = bool(disable_when_hvolt_off)
        self.hvolt_on_provider = hvolt_on_provider if callable(hvolt_on_provider) else None
        self._apply_bcon_driver_logging_suppression()

    def _apply_bcon_driver_logging_suppression(self):
        if not getattr(self, "bcon_driver", None):
            return
        self.bcon_driver.disable_logging_when_hvolt_off = self.disable_logging_when_hvolt_off
        self.bcon_driver.hvolt_on_provider = self.hvolt_on_provider

    def _logging_suppressed(self):
        if not self.disable_logging_when_hvolt_off or self.hvolt_on_provider is None:
            return False
        try:
            return not bool(self.hvolt_on_provider())
        except Exception:
            return False

    def set_manual_disconnect_callback(self, callback):
        self._manual_disconnect_callback = callback if callable(callback) else None

    def set_disconnect_callback(self, callback):
        self._disconnect_callback = callback if callable(callback) else None

    def _notify_beam_activity(self, active: bool) -> None:
        """Notify when any Beam Pulse channel transitions between active/off."""
        active = bool(active)
        if active == getattr(self, "_last_beam_activity_sent", None):
            return
        callback = getattr(self, "_beam_activity_callback", None)
        if not callable(callback):
            return
        self._last_beam_activity_sent = active
        try:
            callback(active)
        except Exception as e:
            self._log_once(f"Beam activity callback failed: {e}", LogLevel.ERROR)

    def _notify_armed_status(self, armed):
        """Tell the host dashboard when Beam Pulse changes armed state."""
        callback = getattr(self, "_armed_status_callback", None)
        if not callable(callback):
            return
        try:
            callback(bool(armed))
        except Exception as e:
            self._log_once(f"Armed status callback failed: {e}", LogLevel.ERROR)

    def _notify_action_feedback(self, event_type, message="", outcome="neutral", configs=None):
        """Send one action status update when Dashboard is present."""
        callback = getattr(self, "_action_feedback_callback", None)
        if not callable(callback):
            return
        try:
            callback(event_type, message, outcome, configs)
        except Exception as e:
            self._log_once(f"Action feedback callback failed: {e}", LogLevel.ERROR)

    def _firmware_ack_queue(self):
        queue_obj = getattr(self, "_pending_firmware_acks", None)
        if queue_obj is None:
            queue_obj = deque()
            self._pending_firmware_acks = queue_obj
        return queue_obj

    def _queue_firmware_ack(self, message: str) -> str:
        """Remember one user-facing context for the next firmware command result."""
        message = str(message or "").strip()
        if message:
            self._firmware_ack_queue().append(message)
        return message

    def _cancel_firmware_ack(self, message: str) -> None:
        if not message:
            return
        queue_obj = self._firmware_ack_queue()
        try:
            queue_obj.remove(message)
        except ValueError:
            pass

    def _pop_firmware_ack(self) -> str:
        queue_obj = self._firmware_ack_queue()
        if queue_obj:
            return queue_obj.popleft()
        return ""

    def _clear_firmware_acks(self) -> None:
        self._firmware_ack_queue().clear()

    def _clear_output_state(self) -> None:
        self.beam_on_status = [False, False, False]
        active_channels = getattr(self, "_active_channels", None)
        if hasattr(active_channels, "clear"):
            active_channels.clear()
        else:
            self._active_channels = set()
        self._notify_beam_activity(False)

    def _notify_all_channel_enables(self, enabled: bool) -> None:
        """Mirror a known all-channel enable state to dashboard controls."""
        self.channel_enable_status = [bool(enabled), bool(enabled), bool(enabled)]
        if self.bcon_driver:
            self.bcon_driver.reset_channel_enable_cache(enabled)
        if not callable(getattr(self, '_channel_enable_status_callback', None)):
            return
        for ch in range(3):
            try:
                self._channel_enable_status_callback(ch, enabled)
            except Exception as e:
                self._log_once(f"Channel enable status callback failed for {self._channel_name(ch)}: {e}",LogLevel.ERROR)

    def get_integration_status(self) -> dict:
        return {
            'has_channel_status_callback': self._channel_status_callback is not None,
            'bcon_connected': self.bcon_connection_status,
        }

    def get_machine_status_inputs(self) -> dict:
        """Return existing Beam Pulse variables needed by MachineStatus."""
        connected = bool(self.bcon_connection_status and self.is_connected())
        active_channels = {
            int(channel)
            for channel in getattr(self, "_active_channels", set())
            if isinstance(channel, int)
        }
        return {
            "bcon_connected": connected,
            "any_beam_active": bool(active_channels),
            "active_channels": active_channels,
            "channel_enable_status": list(getattr(self, "channel_enable_status", [])),
            "beams_armed_status": bool(getattr(self, "beams_armed_status", False)),
            "activate_enabled_beams_guard_clear": (
                self._activate_enabled_beams_guard_clear()
            ),
        }

    def _activate_enabled_beams_guard_clear(self) -> bool:
        enabled_configs = [
            {"ch": index + 1, "mode": "DC", "duration_ms": 0, "count": 1}
            for index, enabled in enumerate(
                list(getattr(self, "channel_enable_status", []))[:3]
            )
            if enabled
        ]
        try:
            allowed, _message = self._beam_checks_allow_output(
                "Activate Enabled Beams",
                enabled_configs,
                log_failure=False,
                check_vtrx_pressure=False,
            )
            return bool(allowed)
        except Exception:
            return False

    # --- Hardware driver interface ---

    def connect(self) -> bool:
        if self._shutdown_in_progress:
            return False
        if self.bcon_driver:
            success = self.bcon_driver.connect()
            if self._shutdown_in_progress:
                self.bcon_driver.disconnect()
                return False
            if success:
                self._apply_default_bcon_settings()
            return success
        self._log_event("BCON connect failed: driver not available", LogLevel.ERROR)
        return False

    def disconnect(self) -> None:
        self._stop_sequence_worker()
        self._clear_firmware_acks()
        self.bcon_connection_status = False
        self._bcon_disconnect_callback_armed = False
        self.beams_armed_status = False
        self._notify_armed_status(False)
        self._clear_output_state()
        self.channel_enable_status = [False, False, False]
        self._update_armed_button_states(False)
        self._notify_all_channel_enables(False)
        if self.bcon_driver:
            self.bcon_driver.disconnect()

    def close_com_ports(self) -> None:
        """Dashboard cleanup hook."""
        self._shutdown_for_host_close()

    def is_connected(self) -> bool:
        if self.bcon_driver:
            return self.bcon_driver.is_connected()
        return False

    def ping(self) -> bool:
        if self.bcon_driver:
            return self.bcon_driver.ping()
        return False

    def get_system_status(self) -> Dict:
        if self.bcon_driver:
            return self.bcon_driver.get_status()
        return {'system': {'state': 'UNKNOWN'}, 'channels': []}

    def toggle_channel_enable(self, ch_index: int):
        """Toggle one channel enable latch. Returns (ok, enabled, message)."""
        if not 0 <= ch_index < len(CHANNEL_LABELS):
            self._log_event(f"Failed to toggle channel enable: invalid channel {ch_index}", LogLevel.ERROR)
            return False, False, "invalid channel"
        if not self._require_armed():
            return False, self.channel_enable_status[ch_index], "beams are not armed"
        if not self.bcon_driver:
            self._log_event("Failed to toggle channel enable: BCON driver not available", LogLevel.ERROR)
            return False, self.channel_enable_status[ch_index], "BCON driver not available"
        if not self._bcon_is_connected():
            self._log_event("Failed to toggle channel enable: BCON device not connected", LogLevel.ERROR)
            return False, self.channel_enable_status[ch_index], "BCON device not connected"

        current = bool(self.bcon_driver.is_channel_enabled(ch_index + 1))
        new_enabled = not current
        if new_enabled:
            allowed, error_message = self._vtrx_pressure_allows_output(
                f"enable {self._channel_name(ch_index)}"
            )
            if not allowed:
                return False, current, error_message

        if not self.bcon_driver.set_channel_enable(ch_index + 1, new_enabled):
            self._log_event(f"Failed to set {self._channel_name(ch_index)} enable", LogLevel.ERROR)
            return (
                False,
                current,
                f"Failed to set {self._channel_name(ch_index)} enable",
            )

        self.channel_enable_status[ch_index] = new_enabled
        if callable(getattr(self, "_channel_enable_status_callback", None)):
            try:
                self._channel_enable_status_callback(ch_index, new_enabled)
            except Exception as e:
                self._log_once(f"Channel enable status callback failed for {self._channel_name(ch_index)}: {e}", LogLevel.ERROR)

        if current:
            self.send_channel_off(ch_index, firmware_ack=False)

        state = "enabled" if new_enabled else "disabled"
        self._log_event(f"{self._channel_name(ch_index)} successfully {state}")
        return True, new_enabled, f"{self._channel_name(ch_index)} successfully {state}"

    def stop_all_channels(self, firmware_ack: str = "All OFF") -> bool:
        if self.bcon_driver:
            ack = self._queue_firmware_ack(firmware_ack)
            ok = self.bcon_driver.stop_all()
            if not ok:
                self._cancel_firmware_ack(ack)
                self._log_event("BCON Driver failed to stop all BCON channels", LogLevel.CRITICAL)
            self._clear_output_state()
            self._notify_all_channel_enables(False)
            return bool(ok)
        self._log_event("Failed to stop all BCON channels: driver not available", LogLevel.ERROR)
        return False

    # --- Safety ---

    def arm_beams(self) -> bool:
        self.beams_armed_status = True
        self._notify_armed_status(True)
        self._log("Beams ARMED (software-only)", LogLevel.INFO)
        self._update_armed_button_states(True)
        return True

    def disarm_beams(self) -> bool:
        self.beams_armed_status = False
        self._notify_armed_status(False)
        self._stop_sequence_worker()
        self._clear_output_state()
        if self.bcon_driver:
            ack = self._queue_firmware_ack("Disarm all OFF")
            if not self.bcon_driver.stop_all():
                self._cancel_firmware_ack(ack)
                self._log_event("Failed to stop all BCON channels during disarm", LogLevel.ERROR)
        self._notify_all_channel_enables(False)
        self._log("Beams DISARMED", LogLevel.INFO)
        self._update_armed_button_states(False)
        return True

    def get_beams_armed_status(self) -> bool:
        return self.beams_armed_status

    # --- Channel config access for dashboard integration ---

    def get_channel_config(self, ch: int) -> Dict:
        """Return the GUI-configured params for a channel (0-based index).

        Returns dict with keys: mode (str), duration_ms (int), count (int).
        Falls back to defaults if GUI widgets are not available.
        """
        config = {'mode': 'PULSE', 'duration_ms': 100, 'count': 1}
        if ch < len(self.channel_vars):
            cv = self.channel_vars[ch]
            try:
                config['mode'] = cv['mode'].get().strip().upper()
            except Exception:
                pass
            try:
                config['duration_ms'] = int(cv['duration'].get())
            except (ValueError, Exception):
                pass
            try:
                config['count'] = int(cv['count'].get())
            except (ValueError, Exception):
                pass
        return config

    def _validate_and_get_config(self, ch: int) -> 'Dict | None':
        """Read, validate, and return the configuration for channel *ch* (0-based).

        Shows an "Invalid Configuration" messagebox and returns None on any
        input error. Manual channel output and Activate Enabled Beams delegate
        here so validation is in one place.

        Validation rules:
          OFF / DC      — always valid; duration and count are not used.
          PULSE         — duration > 0 ms required; count is always forced to 1.
          PULSE_TRAIN   — duration > 0 ms and count ≥ 2 required.
        """
        channel_name = self._channel_name(ch)
        if ch >= len(self.channel_vars):
            config = self.get_channel_config(ch)  # fallback to defaults
            return self._validate_config_values(
                channel_name,
                config.get('mode', 'PULSE'),
                config.get('duration_ms', 100),
                config.get('count', 1),
            )

        cv = self.channel_vars[ch]
        return self._validate_config_values(
            channel_name,
            cv['mode'].get(),
            cv['duration'].get(),
            cv['count'].get(),
        )

    def send_channel_config(self, ch: int) -> bool:
        """Validate GUI params for channel *ch* (0-based) and write them to BCON.

        Shows an 'Invalid Configuration' popup and returns False on bad input.
        Returns True on success.
        """
        # Callers read this if the send fails, so reset it for each attempt.
        self._clear_last_send_failure()
        if not self._require_armed():
            self._set_last_send_failure("beams are not armed")
            return False
        if not self.bcon_driver:
            self._log("No BCON driver", LogLevel.ERROR)
            self._set_last_send_failure("BCON driver not available")
            return False
        if not self._bcon_is_connected():
            self._log_event("Failed to send channel config: BCON device not connected", LogLevel.ERROR)
            self._set_last_send_failure("BCON device not connected")
            return False

        config = self._validate_and_get_config(ch)
        if config is None:
            return False  # messagebox already shown by helper

        mode_label = config['mode']
        duration   = config['duration_ms']
        count      = config['count']

        if mode_label != 'OFF':
            allowed, error_message = self._beam_checks_allow_output(
                f"Beam {self._channel_label(ch)} ON",
                [{
                    'ch': ch + 1,
                    'mode': mode_label,
                    'duration_ms': duration,
                    'count': count,
                }],
            )
            if not allowed:
                self._set_last_send_failure(
                    error_message or "total emission current limit exceeded"
                )
                return False

        ack = self._queue_firmware_ack(
            f"Beam {self._channel_label(ch)} {'ON' if mode_label != 'OFF' else 'OFF'}"
        )
        if not self.bcon_driver.set_channel_mode(ch + 1, mode_label, duration_ms=duration, count=count):
            self._cancel_firmware_ack(ack)
            self._set_last_send_failure(
                f"BCON did not queue {self._channel_name(ch)} {mode_label} command"
            )
            self._log_event(f"Failed to send {self._channel_name(ch)} {mode_label}: BCON did not queue command", LogLevel.ERROR)
            return False

        is_on = mode_label != 'OFF'
        self.beam_on_status[ch] = is_on
        self._log_event(f"Sent {self._channel_name(ch)}: mode={mode_label} dur={duration}ms count={count}")
        return True

    def send_channel_off(self, ch: int, firmware_ack: bool = True) -> bool:
        """Send OFF mode to a single channel (0-based index)."""
        if not self.bcon_driver:
            self._log("No BCON driver", LogLevel.ERROR)
            return False
        ack = (
            self._queue_firmware_ack(f"Beam {self._channel_label(ch)} OFF")
            if firmware_ack else ""
        )
        if not self.bcon_driver.set_channel_off(ch + 1):
            self._cancel_firmware_ack(ack)
            self._log_event(f"{self._channel_name(ch)} OFF failed", LogLevel.ERROR)
            return False
        self.beam_on_status[ch] = False
        self._log_event(f"{self._channel_name(ch)} -> OFF")
        return True

    def safe_shutdown(self, reason: Optional[str] = None) -> bool:
        self._log(f"Safe shutdown: {reason or 'No reason'}", LogLevel.WARNING)
        self.disarm_beams()
        self._log("Safe shutdown complete", LogLevel.INFO)
        return True

    def cancel_updates(self) -> None:
        """Cancel any scheduled Tk `after` callbacks created by this subsystem."""
        if not self.parent_frame:
            return
        for name in ("_ui_after_id", "_bcon_mon_after_id", "_pulser_mon_after_id"):
            aid = getattr(self, name, None)
            if aid:
                try:
                    self.parent_frame.after_cancel(aid)
                    self._log("Cancelled one BCON scheduled update (3 total).", LogLevel.DEBUG)
                except Exception:
                    pass
                try:
                    setattr(self, name, None)
                except Exception:
                    pass

    # --- internal ---

    def _log(self, msg: str, level=LogLevel.INFO) -> None:
        """Route a message to the dashboard Messages & Errors logger.

        Always thread-safe: when called from a background thread the write is
        scheduled on the main thread via parent_frame.after(0, ...).
        """
        if self._logging_suppressed():
            return
        if self.logger:
            if self.parent_frame:
                try:
                    self.parent_frame.after(
                        0, lambda m=msg, l=level: self.logger.log(m, l, tag="BCON"))
                    return
                except Exception:
                    pass
            self.logger.log(msg, level, tag="BCON")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="BeamPulseSubsystem quick test")
    parser.add_argument("--port", default="COM1", help="Serial port for Modbus RTU")
    parser.add_argument("--unit", type=int, default=1, help="Modbus unit ID")
    parser.add_argument("--test-status", action="store_true", help="Test status reading")
    args = parser.parse_args()

    b = BeamPulseSubsystem(port=args.port, unit=args.unit, baudrate=115200, debug=True)

    if not b.connect():
        print("Could not connect to BCON device")
    else:
        print(f"Connected to BCON on {args.port}")

        if args.test_status:
            if b.ping():
                print("Ping successful")

            status = b.get_system_status()
            print(f"\nSystem: {status['system']}")
            for i, ch in enumerate(status['channels'], 1):
                print(f"Channel {CHANNEL_LABELS[i - 1]}: {ch}")

        b.disconnect()
