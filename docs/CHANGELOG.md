# Changelog

All notable changes to the EBEAM Dashboard project are documented here.

---

## [Unreleased] - 2026-02-26

### Fixed

- **Linux compatibility — window maximize** (`main.py`)  
  Replaced `root.state('zoomed')` (Windows-only) with `root.attributes('-zoomed', True)` in `start_main_app()` and `toggle_maximize()`. The previous call raised `_tkinter.TclError: bad argument "zoomed"` on Linux/X11.

- **Dependencies — pandas Python 3.13 compatibility** (`requirements.txt`)  
  Changed `pandas==2.1.3` to `pandas>=2.2.0`. Version 2.1.3 fails to build from source on Python 3.13 due to a Cython/`_PyLong_AsByteArray` API incompatibility introduced in CPython 3.13.

- **Adaptive UI crash — X11 `BadValue (0x0)` on startup** (`dashboard.py`)  
  Before the root window was fully rendered, `winfo_width()` returned `1`. The resize handler used this as the scaling baseline, producing explosive scale factors (e.g. `1920 / 1 = 1920×`) that corrupted all frame dimensions to values that caused X11 `X_CreatePixmap` to fail with `BadValue`. Fixed by:
  - Storing the design reference dimensions (`_design_w`, `_design_h`) from `frames_config` separately in `setup_main_pane()`.
  - Using `_last_w = 0` / `_last_h = 0` as a "not yet initialised" sentinel; the first real resize event now scales from the design reference rather than a garbage value.
  - Skipping `<Configure>` events where `winfo_width() < 50` (pre-render noise from Tk).
  - Adding `width > 0 and height > 0` guards before every `place()` call (frames, sashes, grips) so zero-dimension pixmaps are never passed to X11.

- **Thread teardown error — log widget destroyed** (`utils.py`)  
  Background polling threads (e.g. `poll_all_units` in `DP16_process_monitor`) continued to call `MessagesFrame.log()` after the Tk window was destroyed on quit, raising `TclError: invalid command name`. Wrapped the `text_widget.insert()` / `see()` calls in `try/except tk.TclError`; messages that arrive after window destruction fall back to `print()`.

### Added

- **Adaptive / responsive UI** (`dashboard.py`)  
  The dashboard layout now scales proportionally whenever the window is resized or un-maximised:
  - `_on_window_resize(event)` — bound to `root <Configure>` after all frames are created (avoids spurious construction events). Computes `scale_x` / `scale_y` from the previous window size, updates every entry in `frames_config`, and schedules a debounced reflow.
  - `_do_resize_reflow()` — fires 50 ms after the last resize event to avoid reflowing on every pixel of a drag operation.
  - Existing manual sash (horizontal) and grip (vertical) drag-resize continue to work; the resize handler scales from whatever dimensions the user last set.
  - The `<Configure>` binding is registered at the end of `__init__()`, after `create_frames()` and `create_subsystems()`, so construction-time Configure events do not trigger premature scaling.

- **Hardware simulator** (`simulator/`)  
  A full virtual-hardware simulator that lets the dashboard run without any physical equipment. Located in the `simulator/` folder:

  - **`virtual_serial.py`** — `PortManager` creates Linux PTY pairs (`/dev/pts/XX`) for each subsystem. The slave path is given to the dashboard as a real serial port; the master fd is used by instrument threads.
  - **`instruments.py`** — One simulator class per instrument protocol:
    | Simulator | Protocol | What it emulates |
    |-----------|----------|------------------|
    | `VTRXSimulator` | Read-only ASCII stream, 1 Hz | Vacuum pressure + 8 switch bits |
    | `PowerSupply9104Sim` | ASCII cmd/response (×3 instances) | Cathode heater PSU (GETD, VOLT, CURR, SOUT, …) |
    | `E5CNModbusSim` | Modbus RTU 8E2, slaves 1–3 | Omron E5CN temperature controllers |
    | `G9DriverSim` | Raw binary 199-byte packets | G9SP safety interlocks (13 inputs) |
    | `DP16ProcessMonitorSim` | Modbus RTU 8N1, slaves 1–5 | DP16PT RTD process monitors (IEEE 754 float) |
    | `BCONDriverSim` | Modbus RTU, 160 registers | BCON beam pulse controller (arm, mode, enable, etc.) |
  - **`sim_gui.py`** — Material Design dark-themed Tkinter GUI with card-based layout. Each instrument gets a live-updating card showing its current state. Operator controls include interlock toggles, pressure slider, temperature sliders, and channel inspection.
  - **`run_simulator.py`** — Entry point / launcher:
    - `python -m simulator.run_simulator` — opens the simulator GUI only  
    - `python -m simulator.run_simulator --dashboard` — writes virtual port mapping to `usr/usr_data/com_ports.json` and auto-launches the dashboard as a child process  
    - `--print-ports` — prints the JSON port map and exits  
    - On exit: stops all simulator threads, closes PTY pairs, terminates the dashboard child.
