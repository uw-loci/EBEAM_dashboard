import csv
import json
import os
import sys
import threading
import time
import queue
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from typing import Optional, Dict
from pathlib import Path
from datetime import datetime

from instrumentctl.BCON import (
    BCONDriver,
    BCONMode,
    MODE_LABEL_TO_CODE,
    MODE_CODE_TO_LABEL,
    CH_BASE,
    CH_MODE_OFF,
    CH_PULSE_MS_OFF,
    CH_COUNT_OFF,
    CH_ENABLE_TOGGLE_OFF,
    REG_WATCHDOG_MS,
    REG_TELEMETRY_MS,
    REG_COMMAND,
    REG_SYS_STATE,
    REG_FAULT_LATCHED,
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


class BeamPulseSubsystem:
    """Beam Pulse subsystem (BCON) with tabbed GUI interface for pulser controls.

    Provides three control tabs aligned with pulser_test_gui functionality:
      1. Manual Separate Control  — per-channel parameters, mode buttons, enable toggle
      2. Sync Manual Control      — write params + synchronous start/stop across channels
      3. Auto CSV Sequence        — load/run/stop CSV pulse sequences

    Hardware communication uses the BCONDriver (Modbus RTU).
    """

    # Mode constants matching the firmware register values
    MODE_OFF         = int(BCONMode.OFF)
    MODE_DC          = int(BCONMode.DC)
    MODE_PULSE       = int(BCONMode.PULSE)
    MODE_PULSE_TRAIN = int(BCONMode.PULSE_TRAIN)

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

        # Instantiate BCONDriver if port is provided
        if port:
            self.bcon_driver = BCONDriver(
                port=port,
                baudrate=baudrate,
                unit=unit,
                timeout=1.0,
                debug=debug,
            )
        else:
            self.bcon_driver = None

        # UI-facing queue for driver events (regs, connected, error, …)
        self._ui_queue: queue.Queue = queue.Queue()
        if self.bcon_driver:
            self.bcon_driver.set_ui_queue(self._ui_queue)

        # Status indicators
        self.bcon_connection_status = False
        self.beams_armed_status = False
        self.beam_on_status = [False, False, False]
        self._active_channels: set = set()  # channels currently executing (from registers)

        # Dashboard integration callback
        self._dashboard_beam_callback = None

        # CSV sequence player state
        self._seq_steps: list = []
        self._seq_thread: Optional[threading.Thread] = None
        self._seq_stop = threading.Event()

        # Channel status callback — set_channel_status_callback(cb) registers
        # a function cb(ch, mode_code, remaining) called from register polling.
        self._channel_status_callback = None

        # Ensure directories exist for presets, logs, sequences
        for d in ("presets", "sequences"):
            Path(d).mkdir(exist_ok=True)

        # GUI variables (populated if parent_frame provided)
        self.channel_vars: list = []      # per-channel widget references
        self.sync_configs: list = []      # sync-tab per-channel entries
        self.sync_ch_vars: list = []      # sync-tab include checkboxes

        # Pulse duration variables for external / non-GUI access
        if parent_frame:
            self.pulsing_behavior = tk.StringVar(value="DC")
            self.beam_a_duration = tk.DoubleVar(value=50.0)
            self.beam_b_duration = tk.DoubleVar(value=50.0)
            self.beam_c_duration = tk.DoubleVar(value=50.0)
        else:
            self.pulsing_behavior = "DC"
            self.beam_a_duration = 50.0
            self.beam_b_duration = 50.0
            self.beam_c_duration = 50.0

        # Duration spinbox references (for enable/disable in pulsing behaviour)
        self.duration_spinboxes: list = []

        # Create GUI if parent frame is provided
        if parent_frame:
            self.setup_ui()

        # Auto-connect in background if a port was supplied
        if self.bcon_driver:
            threading.Thread(target=self._auto_connect, daemon=True).start()

    # ================================================================== #
    #                          GUI Setup                                   #
    # ================================================================== #

    def setup_ui(self):
        """Create the user interface with tabbed layout."""
        # Top status bar (BCON connection + safety)
        self._build_status_bar()

        # Notebook with three tabs
        self.notebook = ttk.Notebook(self.parent_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Tab 1: Manual Separate Control
        self.manual_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.manual_tab, text="Manual Control")
        self._build_manual_tab()

        # Tab 2: Auto CSV Sequence
        self.sequence_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.sequence_tab, text="CSV Sequence")
        self._build_sequence_tab()

        # Start periodic UI update from driver queue
        self._start_periodic_ui_update()

        # Start connection & pulser status monitoring
        self.start_bcon_connection_monitoring()
        self.start_pulser_status_monitoring()

    # ----------------------------- Status bar ----------------------------- #

    def _build_status_bar(self):
        """Build the top status bar with connection, interlock, arm info."""
        bar = ttk.Frame(self.parent_frame)
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
        sys_frame = ttk.Frame(self.parent_frame)
        sys_frame.pack(fill=tk.X, padx=5, pady=(2, 0))
        ttk.Label(sys_frame, text="Watchdog (ms):", font=("Arial", 8)).pack(side=tk.LEFT)
        self.watchdog_entry = ttk.Entry(sys_frame, width=7)
        self.watchdog_entry.pack(side=tk.LEFT, padx=2)
        ttk.Button(sys_frame, text="Set", width=4, command=self._set_watchdog).pack(side=tk.LEFT, padx=(0, 8))

        # Log line
        self.log_label = ttk.Label(sys_frame, text="Log: ready", font=("Arial", 8), foreground="gray")
        self.log_label.pack(side=tk.RIGHT, padx=4)

    # ----------------------------- Tab 1: Manual Separate Control --------- #

    def _build_manual_tab(self):
        """Build per-channel control cards (like pulser_test_gui channel cards)."""
        container = ttk.Frame(self.manual_tab, padding="5")
        container.pack(fill=tk.BOTH, expand=True)

        self.pulser_status_canvases = []
        self.pulser_enabled_canvases = []

        # --- Per-channel control cards (horizontal layout) ---
        cards_frame = ttk.Frame(container)
        cards_frame.pack(fill=tk.BOTH, expand=True)
        cards_frame.columnconfigure(0, weight=1)
        cards_frame.columnconfigure(1, weight=1)
        cards_frame.columnconfigure(2, weight=1)

        self.channel_vars = []
        for ch in range(3):
            frame = ttk.LabelFrame(cards_frame, text=f"Channel {ch+1}", padding="5")
            frame.grid(row=0, column=ch, sticky="nsew", pady=4, padx=4)

            # Row 1: Mode selector
            r1 = ttk.Frame(frame)
            r1.pack(fill=tk.X, pady=2)
            ttk.Label(r1, text="Mode:").pack(side=tk.LEFT)
            mode_cb = ttk.Combobox(r1, values=["OFF", "DC", "PULSE", "PULSE_TRAIN"],
                                   state="readonly", width=12)
            mode_cb.set("PULSE")
            mode_cb.pack(side=tk.LEFT, padx=4)

            # Row 2: Duration + Count
            r2 = ttk.Frame(frame)
            r2.pack(fill=tk.X, pady=2)
            ttk.Label(r2, text="Duration (ms):").pack(side=tk.LEFT)
            dur_entry = ttk.Entry(r2, width=8)
            dur_entry.insert(0, "100")
            dur_entry.pack(side=tk.LEFT, padx=(2, 10))
            ttk.Label(r2, text="Count:").pack(side=tk.LEFT)
            cnt_entry = ttk.Entry(r2, width=6)
            cnt_entry.insert(0, "1")
            cnt_entry.pack(side=tk.LEFT, padx=2)

            def _on_mode_change(event, d=dur_entry, c=cnt_entry, m=mode_cb):
                mode = m.get()
                if mode in ("OFF", "DC"):
                    d.config(state="disabled")
                    c.config(state="disabled")
                elif mode == "PULSE":
                    d.config(state="normal")
                    c.config(state="disabled")
                    c.delete(0, "end")
                    c.insert(0, "1")
                else:  # PULSE_TRAIN
                    d.config(state="normal")
                    c.config(state="normal")

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

    # ----------------------------- Tab 2: Sync Manual Control ------------- #

    def _build_sync_tab(self):
        """Build synchronous multi-channel control table."""
        container = ttk.Frame(self.sync_tab, padding="5")
        container.pack(fill=tk.BOTH, expand=True)

        ttk.Label(container, text="Synchronous Control",
                  font=("Arial", 10, "bold")).pack(anchor="w", pady=(0, 5))

        table = ttk.Frame(container)
        table.pack(fill=tk.X)

        # Header
        for col, hdr in enumerate(("CH", "Duration (ms)", "Count", "Mode", "Include")):
            ttk.Label(table, text=hdr, font=("Arial", 9, "bold")).grid(row=0, column=col, padx=6, pady=(0, 4))

        self.sync_ch_vars = [tk.BooleanVar(value=True) for _ in range(3)]
        self.sync_configs = []

        for ch in range(3):
            r = ch + 1
            ttk.Label(table, text=f"CH{ch+1}", font=("Arial", 9, "bold")).grid(row=r, column=0, padx=6, pady=3, sticky="w")

            dur_e = ttk.Entry(table, width=10)
            dur_e.insert(0, "100")
            dur_e.grid(row=r, column=1, padx=4, pady=3)

            cnt_e = ttk.Entry(table, width=8)
            cnt_e.insert(0, "1")
            cnt_e.grid(row=r, column=2, padx=4, pady=3)

            mode_cb = ttk.Combobox(table, values=["OFF", "DC", "PULSE", "PULSE_TRAIN"],
                                   state="readonly", width=12)
            mode_cb.set("PULSE")
            mode_cb.grid(row=r, column=3, padx=4, pady=3)

            def _on_sync_mode_change(event, d=dur_e, c=cnt_e, m=mode_cb):
                mode = m.get()
                if mode in ("OFF", "DC"):
                    d.config(state="disabled")
                    c.config(state="disabled")
                elif mode == "PULSE":
                    d.config(state="normal")
                    c.config(state="disabled")
                    c.delete(0, "end")
                    c.insert(0, "1")
                else:  # PULSE_TRAIN
                    d.config(state="normal")
                    c.config(state="normal")

            mode_cb.bind("<<ComboboxSelected>>", _on_sync_mode_change)
            # Apply initial state (default PULSE: count grayed out)
            cnt_e.config(state="disabled")

            ttk.Checkbutton(table, variable=self.sync_ch_vars[ch]).grid(row=r, column=4, padx=8, pady=3)

            self.sync_configs.append({'duration': dur_e, 'count': cnt_e, 'mode': mode_cb})

        # (Action buttons for Sync Control are hosted in the Main Control panel)

    # ----------------------------- Tab 3: Auto CSV Sequence --------------- #

    def _build_sequence_tab(self):
        """Build CSV pulse sequence player interface."""
        container = ttk.Frame(self.sequence_tab, padding="5")
        container.pack(fill=tk.BOTH, expand=True)

        ttk.Label(container, text="CSV Pulse Sequence",
                  font=("Arial", 10, "bold")).pack(anchor="w", pady=(0, 5))

        self.seq_file_lbl = ttk.Label(container, text="No sequence loaded", foreground="gray")
        self.seq_file_lbl.pack(anchor="w", padx=4)

        self.seq_progress_lbl = ttk.Label(container, text="")
        self.seq_progress_lbl.pack(anchor="w", padx=4, pady=(2, 4))

        # (Action buttons for CSV Sequence are hosted in the Main Control panel)

        # Sequence preview (simple text view)
        ttk.Label(container, text="Loaded Steps:", font=("Arial", 9, "bold")).pack(anchor="w", padx=4, pady=(4, 0))
        self.seq_preview_text = tk.Text(container, height=10, width=60, state="disabled", font=("Courier", 9))
        self.seq_preview_text.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

    # ------------------------------------------------------------------ #
    #  External control buttons (hosted in the Main Control panel)        #
    # ------------------------------------------------------------------ #

    def create_external_control_buttons(self, parent_frame, manual_panel_override=None,
                                         beam_on_off_frame=None, csv_frame=None):
        """Append Sync Start / Sync Stop buttons and wire tab-aware panel visibility.

        Tabs in the Beam Pulse notebook:
          Tab 0 – Manual Control  → show beam_on_off_frame + Sync row;  hide csv_frame
          Tab 1 – CSV Sequence    → hide beam_on_off_frame + Sync row;  show csv_frame
          CH Enable/Disable row is always visible.

        Parameters:
            parent_frame:          Tkinter frame used when no manual_panel_override.
            manual_panel_override: Dashboard's bp_manual_panel — Sync row is appended here.
            beam_on_off_frame:     Dashboard's Beam A/B/C ON/OFF row frame to show/hide.
            csv_frame:             Dashboard's csv_buttons_frame to show/hide.
        """
        self._armed_gated_buttons: list = []
        # References used by the tab-change handler
        self._beam_on_off_frame = beam_on_off_frame
        self._csv_frame = csv_frame
        self._sync_row = None

        if manual_panel_override is not None:
            self._ext_manual_frame = manual_panel_override

            # --- Sync action row (appended below the CH Enable/Disable row) ---
            self._sync_row = tk.Frame(manual_panel_override)
            self._sync_row.pack(side="top", fill="x", pady=(4, 0))
            self._sync_row.grid_columnconfigure(0, weight=1, uniform="sbtn")
            self._sync_row.grid_columnconfigure(1, weight=1, uniform="sbtn")

            self.sync_start_btn = tk.Button(
                self._sync_row, text="Sync Start",
                bg="#1565C0", fg="white", font=("Helvetica", 9, "bold"),
                state="disabled", command=self._sync_start,
            )
            self.sync_start_btn.grid(row=0, column=0, sticky="ew", padx=(2, 1))
            self._armed_gated_buttons.append(self.sync_start_btn)

            self.sync_stop_btn = tk.Button(
                self._sync_row, text="Sync Stop",
                bg="#B71C1C", fg="white", font=("Helvetica", 9, "bold"),
                state="normal", command=self._sync_stop_all,
            )
            self.sync_stop_btn.grid(row=0, column=1, sticky="ew", padx=(1, 2))

        else:
            # Standalone fallback: per-channel Apply buttons + Sync row
            outer = ttk.Frame(parent_frame)
            outer.pack(fill=tk.X, padx=6, pady=(6, 2))
            self._ext_manual_frame = outer
            ttk.Label(outer, text="Manual + Sync Control",
                      font=("Arial", 9, "bold")).pack(fill=tk.X, pady=(0, 2))
            for ch in range(3):
                btn = ttk.Button(
                    outer, text=f"Apply CH{ch + 1}", state="disabled",
                    command=lambda c=ch: self._manual_apply(
                        c,
                        self.channel_vars[c]['duration'],
                        self.channel_vars[c]['count'],
                        self.channel_vars[c]['mode'],
                    ),
                )
                btn.pack(fill=tk.X, pady=1)
                self._armed_gated_buttons.append(btn)
            self._sync_row = ttk.Frame(outer)
            self._sync_row.pack(fill=tk.X)
            sync_start = ttk.Button(self._sync_row, text="Sync Start", state="disabled",
                                    command=self._sync_start)
            sync_start.pack(fill=tk.X, pady=1)
            self._armed_gated_buttons.append(sync_start)
            ttk.Button(self._sync_row, text="Sync Stop",
                       command=self._sync_stop_all).pack(fill=tk.X, pady=1)

        # ---- Tab-switching logic -----------------------------------------
        def _apply_tab(idx: int):
            """Show/hide frames to match the selected Beam Pulse notebook tab."""
            is_manual = (idx == 0)
            # Beam ON/OFF row
            if self._beam_on_off_frame is not None:
                try:
                    if is_manual:
                        self._beam_on_off_frame.pack(side="top", fill="x")
                    else:
                        self._beam_on_off_frame.pack_forget()
                except Exception:
                    pass
            # Sync Start/Stop row
            if self._sync_row is not None:
                try:
                    if is_manual:
                        self._sync_row.pack(side="top", fill="x", pady=(4, 0))
                    else:
                        self._sync_row.pack_forget()
                except Exception:
                    pass
            # CSV buttons frame
            if self._csv_frame is not None:
                try:
                    if is_manual:
                        self._csv_frame.pack_forget()
                    else:
                        self._csv_frame.pack(side="top", fill="x")
                except Exception:
                    pass

        def _on_tab_changed(event=None):
            try:
                idx = self.notebook.index(self.notebook.select())
            except Exception:
                idx = 0
            _apply_tab(idx)

        self.notebook.bind("<<NotebookTabChanged>>", _on_tab_changed)
        # Apply initial state (Tab 0 = Manual is selected at startup)
        _apply_tab(0)

    def create_csv_buttons(self, parent_frame):
        """Build CSV sequence control buttons in *parent_frame* (always visible).

        Designed to be called by the dashboard immediately after the script-
        selection dropdown, so the buttons appear below it regardless of which
        Beam Pulse notebook tab is active.

        Parameters:
            parent_frame: Tkinter frame that will host the CSV controls.
        """
        container = ttk.LabelFrame(parent_frame, text="CSV Sequence", padding="4")
        container.pack(fill=tk.X, padx=6, pady=(4, 2))

        # Load CSV / Save Template — file operations; always enabled
        row1 = ttk.Frame(container)
        row1.pack(fill=tk.X, pady=1)
        ttk.Button(row1, text="Load CSV",
                   command=self._load_sequence).pack(
                   side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 2))
        ttk.Button(row1, text="Save Template",
                   command=self._save_sequence_template).pack(
                   side=tk.LEFT, fill=tk.X, expand=True)

        # Run / Stop — Run is gated by armed state AND sequence loaded
        row2 = ttk.Frame(container)
        row2.pack(fill=tk.X, pady=1)
        self.seq_run_btn = ttk.Button(row2, text="Run Sequence",
                                      state="disabled", command=self._run_sequence)
        self.seq_run_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 2))
        # Stop Sequence always enabled (safety action)
        self.seq_stop_btn = ttk.Button(row2, text="Stop Sequence",
                                       state="disabled", command=self._stop_sequence)
        self.seq_stop_btn.pack(side=tk.LEFT, fill=tk.X, expand=True)

    # ================================================================== #
    #                    Manual Tab Actions                                #
    # ================================================================== #

    def _require_armed(self) -> bool:
        """Return True if beams are armed; log a warning and return False otherwise.

        Call this at the top of every action that sends commands to BCON.
        Stop / disarm / off actions should NOT call this — they must always work.
        """
        if not self.beams_armed_status:
            self._log_event("Action blocked: beams are not armed")
            return False
        return True

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

    def _manual_apply(self, ch, dur_entry, cnt_entry, mode_cb):
        """Apply parameters + mode for a single channel."""
        if not self._require_armed():
            return
        if not self.bcon_driver:
            self._log("No BCON driver", LogLevel.WARNING)
            return
        try:
            duration = int(dur_entry.get())
            count = int(cnt_entry.get())
        except (ValueError, tk.TclError):
            messagebox.showerror("Invalid", "Enter numeric values for duration and count")
            return
        if duration <= 0:
            messagebox.showerror("Invalid", "Duration must be > 0")
            return
        if count <= 0:
            messagebox.showerror("Invalid", "Count must be > 0")
            return

        mode_label = mode_cb.get().strip().upper()
        if mode_label not in MODE_LABEL_TO_CODE:
            messagebox.showerror("Invalid", f"Unsupported mode: {mode_label}")
            return

        channel = ch + 1  # 1-based
        base = CH_BASE[ch]
        self.bcon_driver.enqueue_write(base + CH_PULSE_MS_OFF, duration)
        self.bcon_driver.enqueue_write(base + CH_COUNT_OFF, count)
        self.bcon_driver.enqueue_write(base + CH_MODE_OFF, MODE_LABEL_TO_CODE[mode_label])
        self._log_event(f"Applied CH{channel}: mode={mode_label} dur={duration}ms count={count}")

    def _manual_set_mode(self, ch, mode_code):
        """Quick mode button for a single channel."""
        if not self._require_armed():
            return
        if not self.bcon_driver:
            return
        base = CH_BASE[ch]
        if mode_code == self.MODE_PULSE:
            self.bcon_driver.enqueue_write(base + CH_COUNT_OFF, 1)
        self.bcon_driver.enqueue_write(base + CH_MODE_OFF, mode_code)
        label = MODE_CODE_TO_LABEL.get(mode_code, str(mode_code))
        self._log_event(f"CH{ch+1} -> {label}")

    def _manual_toggle_enable(self, ch):
        """Toggle enable for a single channel."""
        if not self._require_armed():
            return
        if not self.bcon_driver:
            return
        self.bcon_driver.toggle_channel_enable(ch + 1)
        self._log_event(f"CH{ch+1} ENABLE_TOGGLE")

    # ================================================================== #
    #                    Sync Tab Actions                                   #
    # ================================================================== #

    def _sync_write_params(self):
        """Write duration + count for all channels from Manual tab configuration."""
        if not self._require_armed():
            return
        if not self.bcon_driver:
            return
        for ch in range(3):
            if ch >= len(self.channel_vars):
                continue
            cv = self.channel_vars[ch]
            dur_str = cv['duration'].get().strip()
            cnt_str = cv['count'].get().strip()
            try:
                dur = int(dur_str) if dur_str else 100
                cnt = int(cnt_str) if cnt_str else 1
            except ValueError:
                messagebox.showerror("Invalid", f"CH{ch+1}: duration and count must be integers")
                return
            if dur > 0:
                self.bcon_driver.set_channel_params(ch + 1, dur, cnt if cnt > 0 else 1)
        self._log_event("Sync wrote params for all channels")

    def _sync_start(self):
        """Synchronous start of all channels using Manual Control tab configuration."""
        if not self._require_armed():
            return
        if not self.bcon_driver:
            return

        configs = []
        for ch in range(3):
            if ch >= len(self.channel_vars):
                continue
            cv = self.channel_vars[ch]
            dur_str = cv['duration'].get().strip()
            cnt_str = cv['count'].get().strip()
            mode_label = cv['mode'].get().strip().upper()
            try:
                dur = int(dur_str) if dur_str else 100
                cnt = int(cnt_str) if cnt_str else 1
            except ValueError:
                messagebox.showerror("Invalid", f"CH{ch+1}: duration and count must be integers")
                return
            if mode_label not in MODE_LABEL_TO_CODE:
                messagebox.showerror("Invalid", f"CH{ch+1}: unknown mode '{mode_label}'")
                return
            mode_code = MODE_LABEL_TO_CODE[mode_label]
            if mode_code == self.MODE_PULSE_TRAIN and cnt < 2:
                messagebox.showerror("Invalid", f"CH{ch+1}: PULSE_TRAIN requires count >= 2")
                return
            configs.append({
                'ch': ch + 1, 'mode': mode_label,
                'duration_ms': dur, 'count': cnt,
            })

        if configs:
            self.bcon_driver.sync_start(configs)
            self._log_event(
                "Sync Start: " +
                ", ".join(f"CH{c['ch']}={c['mode']}({c['duration_ms']}ms x{c['count']})" for c in configs)
            )

    def _sync_stop_all(self):
        """Stop all channels immediately."""
        if self.bcon_driver:
            self.bcon_driver.stop_all()
        self._log_event("Sync Stop: all channels -> OFF")

    # ================================================================== #
    #                  CSV Sequence Tab Actions                             #
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
                        continue
                    step_num = int(parts[0])
                    ch_str   = parts[1].upper()
                    mode     = parts[2].upper()
                    dur_ms   = int(parts[3]) if len(parts) > 3 and parts[3] else 100
                    count    = int(parts[4]) if len(parts) > 4 and parts[4] else 1
                    dwell_ms = int(parts[5]) if len(parts) > 5 and parts[5] else 0

                    if mode not in MODE_LABEL_TO_CODE:
                        raise ValueError(f"Unknown mode '{mode}' at step {step_num}")
                    if mode == "PULSE_TRAIN" and count < 2:
                        raise ValueError(f"Step {step_num}: PULSE_TRAIN requires count >= 2")

                    ch_list = list(range(3)) if ch_str == "ALL" else [int(ch_str) - 1]
                    if step_num not in steps_raw:
                        steps_raw[step_num] = {"rows": [], "dwell_ms": 0}
                    for ch_idx in ch_list:
                        steps_raw[step_num]["rows"].append(
                            {"ch": ch_idx, "mode": mode, "duration_ms": dur_ms, "count": count}
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
                        f"Step {sn}: CH{row['ch']+1} {row['mode']} "
                        f"dur={row['duration_ms']}ms cnt={row['count']}  dwell={dwell}ms\n")
            self.seq_preview_text.configure(state="disabled")

            self._log_event(f"Sequence loaded: {os.path.basename(fname)} ({n} steps)")
        except Exception as e:
            messagebox.showerror("Sequence Load Error", str(e))
            self._log_event(f"Sequence load failed: {e}")

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
            return
        if not self._seq_steps:
            messagebox.showinfo("Sequence", "No sequence loaded.")
            return
        if not self.bcon_driver or not self.bcon_driver.is_connected():
            messagebox.showwarning("Sequence", "Not connected to BCON device.")
            return
        if self._seq_thread and self._seq_thread.is_alive():
            return
        self._seq_stop.clear()
        if hasattr(self, 'seq_run_btn'):
            self.seq_run_btn.configure(state="disabled")
        if hasattr(self, 'seq_stop_btn'):
            self.seq_stop_btn.configure(state="normal")
        self._seq_thread = threading.Thread(target=self._sequence_worker, daemon=True)
        self._seq_thread.start()
        self._log_event("Sequence started")

    def _stop_sequence(self):
        """Request sequence stop."""
        self._seq_stop.set()
        self._log_event("Sequence stop requested")

    def _sequence_worker(self):
        """Background thread that plays the CSV sequence."""
        total = len(self._seq_steps)
        for idx, (step_num, rows, dwell_ms) in enumerate(self._seq_steps):
            if self._seq_stop.is_set():
                break
            # Update progress via queue
            self._ui_queue.put(("seq_status", f"Step {idx+1}/{total} (#{step_num})"))

            # Phase 1: write parameters
            for row in rows:
                if row["mode"] in ("OFF", "DC"):
                    continue
                ch = row["ch"]  # 0-based
                base = CH_BASE[ch]
                self.bcon_driver.enqueue_write(base + CH_PULSE_MS_OFF, row["duration_ms"])
                self.bcon_driver.enqueue_write(base + CH_COUNT_OFF, row["count"])

            # Phase 2: write modes
            for row in rows:
                ch = row["ch"]
                self.bcon_driver.enqueue_write(
                    CH_BASE[ch] + CH_MODE_OFF, MODE_LABEL_TO_CODE[row["mode"]]
                )

            # Dwell
            deadline = time.time() + dwell_ms / 1000.0
            while time.time() < deadline and not self._seq_stop.is_set():
                time.sleep(0.05)

        final = "Sequence complete" if not self._seq_stop.is_set() else "Sequence stopped"
        self._ui_queue.put(("seq_status", final))
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
                self.parent_frame.after(200, _tick)
        if self.parent_frame:
            self.parent_frame.after(200, _tick)

    def _handle_driver_msg(self, msg):
        """Process a single message from the driver/UI queue."""
        typ = msg[0]
        if typ == "connected":
            ok = msg[1]
            self.bcon_connection_status = ok
            self.update_bcon_connection_status()
        elif typ == "regs":
            regs = msg[1]
            self._update_ui_from_registers(regs)
        elif typ == "wrote":
            reg, val = msg[1], msg[2]
            self._log_event(f"Wrote R{reg}={val}")
        elif typ == "error":
            self._log_event(f"Error: {msg[1]}")
        elif typ == "seq_status":
            text = msg[1]
            if hasattr(self, 'seq_progress_lbl'):
                self.seq_progress_lbl.configure(text=text)
            self._log_event(text)
        elif typ == "seq_done":
            if hasattr(self, 'seq_run_btn'):
                self.seq_run_btn.configure(state="normal")
            if hasattr(self, 'seq_stop_btn'):
                self.seq_stop_btn.configure(state="disabled")

    def _update_ui_from_registers(self, regs):
        """Mirror register data into GUI widgets (like pulser_test_gui._handle_msg 'regs')."""
        # Update manual-tab channel cards
        for ch in range(3):
            if ch >= len(self.channel_vars):
                continue
            status_base = REG_CH_STATUS_BASE + ch * REG_CH_STATUS_STRIDE

            mode_code = regs[status_base + 0]
            remaining = regs[status_base + 3]
            output_level = regs[status_base + 8]

            st_text = MODE_CODE_TO_LABEL.get(mode_code, "unknown")
            self.channel_vars[ch]['status'].configure(text=f"Status: {st_text} | O:{output_level}")
            self.channel_vars[ch]['pulses'].configure(text=f"Remaining: {remaining}")

            # DC mode never counts down (remaining stays 0) — treat it as
            # running whenever mode != OFF so the manual controls stay locked
            # and the dashboard Beam button stays green.
            is_running = (mode_code != self.MODE_OFF) and (
                remaining > 0 or mode_code == self.MODE_DC
            )
            if is_running:
                self._active_channels.add(ch)
                self._set_manual_channel_lock(ch, True)
            else:
                self._active_channels.discard(ch)
                self._set_manual_channel_lock(ch, False)

            # Notify dashboard so beam toggle button colour tracks hardware state
            if callable(getattr(self, '_channel_status_callback', None)):
                try:
                    self._channel_status_callback(ch, mode_code, remaining)
                except Exception:
                    pass

            # NOTE: do NOT push hardware mode back into the mode combobox — that
            # would overwrite the user's intended configuration.  The status label
            # above already shows the live running mode.

            # Auto-fill duration/count from param registers if widget is empty or '0'
            base = CH_BASE[ch]
            pulse_ms = regs[base + CH_PULSE_MS_OFF]
            count_val = regs[base + CH_COUNT_OFF]
            self._safe_fill(self.channel_vars[ch]['duration'], pulse_ms)
            self._safe_fill(self.channel_vars[ch]['count'], count_val)

        # Interlock / watchdog / state
        interlock_ok = regs[REG_INTERLOCK_OK]
        watchdog_ok = regs[REG_WATCHDOG_OK]
        fault = regs[REG_FAULT_LATCHED]
        if hasattr(self, 'safety_label'):
            fault_txt = "  FAULT" if fault else ""
            self.safety_label.configure(
                text=f"Interlock: {'ok' if interlock_ok else 'locked'} | "
                     f"Watchdog: {'ok' if watchdog_ok else 'expired'}{fault_txt}")

        # Watchdog entry
        if hasattr(self, 'watchdog_entry'):
            self._safe_fill(self.watchdog_entry, regs[REG_WATCHDOG_MS])

        # Update pulser enabled/overcurrent canvases
        for i in range(3):
            self.update_pulser_status_display(i)

    @staticmethod
    def _safe_fill(entry_widget, value):
        """Overwrite entry only if empty or '0', and only when the widget is not disabled."""
        try:
            if str(entry_widget.cget("state")) == "disabled":
                return
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

    # ================================================================== #
    #                  Status Monitoring                                    #
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
                self.parent_frame.after(2000, check)
        if self.parent_frame:
            self.parent_frame.after(1000, check)

    def start_pulser_status_monitoring(self):
        """Periodically refresh pulser status indicators."""
        def check():
            for i in range(3):
                self.update_pulser_status_display(i)
            if self.parent_frame:
                self.parent_frame.after(500, check)
        if self.parent_frame:
            self.parent_frame.after(1000, check)

    def update_bcon_connection_status(self):
        """Repaint the BCON connection indicator and sync button label."""
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
            except Exception:
                pass
        return False

    # ================================================================== #
    #               Safety / System Settings Actions                       #
    # ================================================================== #

    def _auto_connect(self):
        """Background thread: open the serial port and connect to BCON."""
        port = self.bcon_driver.port
        self._ui_queue.put(("seq_status", f"Connecting to BCON on {port}…"))
        ok = self.bcon_driver.connect()
        msg = f"BCON connected on {port}" if ok else f"BCON connect failed on {port} — check port & firmware"
        self._ui_queue.put(("seq_status", msg))
        self._log(msg, LogLevel.INFO)

    def _manual_connect(self):
        """Button handler: (re)connect to BCON in a background thread."""
        if not self.bcon_driver:
            messagebox.showwarning("Connect", "No port configured for BCON.")
            return
        if self.bcon_driver.is_connected():
            self.bcon_driver.disconnect()
        if hasattr(self, 'connect_btn'):
            self.connect_btn.configure(state="disabled", text="Connecting…")
            self.parent_frame.after(100, lambda: None)  # force redraw
        def _do():
            ok = self.bcon_driver.connect()
            if self.parent_frame:
                self.parent_frame.after(0, lambda: self._on_connect_done(ok))
        threading.Thread(target=_do, daemon=True).start()

    def _on_connect_done(self, ok: bool):
        """Called on the main thread after a manual connect attempt."""
        if hasattr(self, 'connect_btn'):
            self.connect_btn.configure(state="normal",
                                       text="Disconnect" if ok else "Reconnect")
        self._log_event("BCON connected" if ok else "BCON connect failed — check port & firmware")

    def _arm_beam(self):
        """Send ARM / CLEAR_FAULT command."""
        if not self.bcon_driver:
            messagebox.showwarning("Arm", "No BCON driver available")
            return
        self.bcon_driver.arm()
        self.beams_armed_status = True
        self._log_event("ARM command sent")

    def _set_watchdog(self):
        """Write the watchdog timeout register."""
        val = self.watchdog_entry.get().strip()
        if not val:
            return
        try:
            ms = int(val)
        except ValueError:
            messagebox.showerror("Invalid", "Watchdog value must be integer")
            return
        if self.bcon_driver:
            self.bcon_driver.set_watchdog(ms)
            self._log_event(f"Set watchdog = {ms} ms")

    def _set_telemetry(self):
        """Write the telemetry interval register."""
        val = self.telemetry_entry.get().strip()
        if not val:
            return
        try:
            ms = int(val)
        except ValueError:
            messagebox.showerror("Invalid", "Telemetry value must be integer")
            return
        if self.bcon_driver:
            self.bcon_driver.set_telemetry(ms)
            self._log_event(f"Set telemetry = {ms} ms")

    # ================================================================== #
    #           Event Log Helper                                           #
    # ================================================================== #

    def _log_event(self, text: str):
        """Log an event to console, label, and CSV session log."""
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        line = f"[{ts}] {text}"
        if self.debug:
            print(line)
        if hasattr(self, 'log_label'):
            try:
                self.log_label.configure(text=text)
            except Exception:
                pass
        self._log(text, LogLevel.INFO)

    # ================================================================== #
    #          Public API (backward-compatible with dashboard)             #
    # ================================================================== #

    # --- Status access ---

    def set_bcon_connection_status(self, status: bool):
        self.bcon_connection_status = status
        self.update_bcon_connection_status()

    def set_beam_status(self, beam_index: int, status: bool):
        if 0 <= beam_index < 3:
            self.beam_on_status[beam_index] = status
            if self.bcon_driver:
                ch = beam_index + 1
                if status:
                    pulsing = self.get_pulsing_behavior()
                    if pulsing == "Pulsed":
                        dur = int(self.get_beam_duration(beam_index))
                        self.bcon_driver.set_channel_pulse(ch, dur)
                    else:
                        self.bcon_driver.set_channel_dc(ch)
                else:
                    self.bcon_driver.set_channel_off(ch)
            if self._dashboard_beam_callback:
                try:
                    self._dashboard_beam_callback(beam_index, status)
                except Exception:
                    pass

    def get_beam_status(self, beam_index: int) -> bool:
        if 0 <= beam_index < 3:
            return self.beam_on_status[beam_index]
        return False

    def set_all_beams_status(self, status: bool):
        for i in range(3):
            self.set_beam_status(i, status)

    def get_pulsing_behavior(self) -> str:
        if hasattr(self.pulsing_behavior, 'get'):
            return self.pulsing_behavior.get()
        return self.pulsing_behavior

    def get_beam_duration(self, beam_index: int) -> float:
        vars_list = [self.beam_a_duration, self.beam_b_duration, self.beam_c_duration]
        if 0 <= beam_index < 3:
            v = vars_list[beam_index]
            return v.get() if hasattr(v, 'get') else float(v)
        return 50.0

    def set_channel_status_callback(self, callback):
        """Register callback(ch, mode_code, remaining) invoked on every register poll.

        The dashboard uses this to keep the Beam A/B/C toggle buttons in sync
        with live hardware state without polling from the dashboard side.
        """
        self._channel_status_callback = callback

    def set_dashboard_beam_callback(self, callback):
        self._dashboard_beam_callback = callback
        self._log("Dashboard beam callback registered", LogLevel.DEBUG)

    def get_integration_status(self) -> dict:
        return {
            'has_dashboard_callback': self._dashboard_beam_callback is not None,
            'bcon_connected': self.bcon_connection_status,
        }

    # --- Hardware driver interface ---

    def connect(self) -> bool:
        if self.bcon_driver:
            success = self.bcon_driver.connect()
            if success:
                self.bcon_driver.set_watchdog(1000)
                self.bcon_driver.set_telemetry(500)
            return success
        return False

    def disconnect(self) -> None:
        if self.bcon_driver:
            try:
                self.bcon_driver.stop_all()
                time.sleep(0.3)  # let the write drain
            except Exception:
                pass
            self.bcon_driver.disconnect()

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

    def set_channel_mode(self, channel_index: int, mode: str, duration_ms: int = 0) -> bool:
        if not self._require_armed():
            return False
        if not self.bcon_driver:
            return False
        channel = channel_index + 1
        if mode == 'OFF':
            self.bcon_driver.set_channel_off(channel)
        elif mode == 'DC':
            self.bcon_driver.set_channel_dc(channel)
        elif mode == 'PULSE':
            self.bcon_driver.set_channel_pulse(channel, duration_ms)
        elif mode == 'PULSE_TRAIN':
            self.bcon_driver.set_channel_pulse_train(channel, duration_ms, 2)
        else:
            self._log(f"Invalid mode: {mode}", LogLevel.ERROR)
            return False
        return True

    def stop_all_channels(self) -> bool:
        if self.bcon_driver:
            self.bcon_driver.stop_all()
            return True
        return False

    # --- Safety ---

    def arm_beams(self) -> bool:
        if self.bcon_driver:
            self.bcon_driver.arm()
            self.beams_armed_status = True
            self._log("Beams ARMED", LogLevel.INFO)
            self._update_armed_button_states(True)
            return True
        self.beams_armed_status = True
        self._update_armed_button_states(True)
        return True

    def disarm_beams(self) -> bool:
        self.beams_armed_status = False
        self.set_all_beams_status(False)
        if self.bcon_driver:
            self.bcon_driver.stop_all()
        self._log("Beams DISARMED", LogLevel.INFO)
        self._update_armed_button_states(False)
        return True

    def get_beams_armed_status(self) -> bool:
        return self.beams_armed_status

    def get_deflect_beam_status(self) -> bool:
        return any(self.beam_on_status)

    def set_deflect_beam_status(self, enable: bool) -> bool:
        if enable:
            if not self.beams_armed_status:
                self._log("Cannot enable deflect beam - beams not armed", LogLevel.WARNING)
                return False
            self._apply_pulsing_behavior()
        else:
            self.set_all_beams_status(False)
            if self.bcon_driver:
                self.bcon_driver.stop_all()
        return True

    def _apply_pulsing_behavior(self):
        if not self.bcon_driver:
            return
        pulsing_mode = self.get_pulsing_behavior()
        for idx in range(3):
            ch = idx + 1
            if self.beam_on_status[idx]:
                if pulsing_mode == "Pulsed":
                    dur = int(self.get_beam_duration(idx))
                    self.bcon_driver.set_channel_pulse(ch, dur)
                else:
                    self.bcon_driver.set_channel_dc(ch)
            else:
                self.bcon_driver.set_channel_off(ch)

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

    def send_channel_config(self, ch: int) -> bool:
        """Read GUI params for channel *ch* (0-based) and write them to BCON.

        Returns True on success.
        """
        if not self._require_armed():
            return False
        if not self.bcon_driver:
            self._log("No BCON driver", LogLevel.WARNING)
            return False
        config = self.get_channel_config(ch)
        mode_label = config['mode']
        duration = config['duration_ms']
        count = config['count']
        if mode_label not in MODE_LABEL_TO_CODE:
            self._log(f"Invalid mode: {mode_label}", LogLevel.ERROR)
            return False
        base = CH_BASE[ch]
        self.bcon_driver.enqueue_write(base + CH_PULSE_MS_OFF, duration)
        self.bcon_driver.enqueue_write(base + CH_COUNT_OFF, count)
        self.bcon_driver.enqueue_write(base + CH_MODE_OFF, MODE_LABEL_TO_CODE[mode_label])
        self.beam_on_status[ch] = True
        self._log_event(f"Sent CH{ch+1}: mode={mode_label} dur={duration}ms count={count}")
        if self._dashboard_beam_callback:
            try:
                self._dashboard_beam_callback(ch, True)
            except Exception:
                pass
        return True

    def send_channel_off(self, ch: int) -> bool:
        """Send OFF mode to a single channel (0-based index)."""
        if not self.bcon_driver:
            self._log("No BCON driver", LogLevel.WARNING)
            return False
        base = CH_BASE[ch]
        self.bcon_driver.enqueue_write(base + CH_MODE_OFF, int(BCONMode.OFF))
        self.beam_on_status[ch] = False
        self._log_event(f"CH{ch+1} -> OFF")
        if self._dashboard_beam_callback:
            try:
                self._dashboard_beam_callback(ch, False)
            except Exception:
                pass
        return True

    def safe_shutdown(self, reason: Optional[str] = None) -> bool:
        self._log(f"Safe shutdown: {reason or 'No reason'}", LogLevel.WARNING)
        self.disarm_beams()
        self.set_all_beams_status(False)
        self._log("Safe shutdown complete", LogLevel.INFO)
        return True

    # --- internal ---

    def _log(self, msg: str, level=LogLevel.INFO) -> None:
        if self.logger:
            self.logger.log(msg, level)
        elif self.debug:
            print(f"[{level.name}] {msg}")


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
                print(f"Channel {i}: {ch}")

        b.disconnect()
