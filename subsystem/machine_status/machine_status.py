import math
import threading
import tkinter as tk
from collections import OrderedDict

from utils import LogLevel


STATUS_NAMES = (
    "Chamber Pressure",
    "Environment Temperature Monitors",
    "Safety Interlocks",
    "HV Panel On",
    "High Voltage Power Supplies Nominal",
    "Beam Controller Nominal",
    "Cathode Heating",
    "Beams Ready",
    "Beams On",
)

STATE_GRAY = "gray"
STATE_GREEN = "green"
STATE_RED = "red"

STATE_COLORS = {
    STATE_GRAY: "#dbd9d9",
    STATE_GREEN: "green",
    STATE_RED: "red",
}
STATE_LOG_TEXT = {
    STATE_GRAY: "In Progress",
    STATE_GREEN: "Ready",
    STATE_RED: "Warning",
}

POLL_INTERVAL_SECONDS = 0.2
BEAM_ENERGY_SUPPLIES = ("pos1kv", "neg1kv", "pos20kv", "pos3kv")
BCON_SUPPLIES = ("pos1kv", "neg1kv")
_AFTER_SCHEDULING = object()


def calculate_display_states(raw_statuses):
    display_states = {}
    later_green = False

    for name in reversed(STATUS_NAMES):
        if raw_statuses.get(name, False):
            display_states[name] = STATE_GREEN
            later_green = True
        else:
            display_states[name] = STATE_RED if later_green else STATE_GRAY

    return OrderedDict((name, display_states[name]) for name in STATUS_NAMES)


def build_status_transition_logs(previous_states, current_states):
    if not previous_states:
        return []

    entries = []
    for name, current_state in current_states.items():
        previous_state = previous_states.get(name)
        if previous_state == current_state:
            continue
        level = LogLevel.WARNING if current_state == STATE_RED else LogLevel.INFO
        entries.append((name, previous_state, current_state, level))
    return entries


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _subsystem(subsystems, name_prefix):
    direct = subsystems.get(name_prefix)
    if direct is not None:
        return direct

    prefix = name_prefix.lower()
    for name, subsystem in subsystems.items():
        if str(name).lower().startswith(prefix):
            return subsystem
    return None


def _inputs(subsystem):
    getter = getattr(subsystem, "get_machine_status_inputs", None)
    if not callable(getter):
        return {}
    try:
        value = getter()
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _interlock_green(interlocks, name):
    getter = getattr(interlocks, "get_interlock_status", None)
    if not callable(getter):
        return False
    try:
        return bool(getter(name))
    except Exception:
        return False


def _environment_pass(process_monitor):
    getter = getattr(process_monitor, "get_environment_pass", None)
    if not callable(getter):
        return False
    try:
        return bool(getter())
    except Exception:
        return False


def _comparison_value(supply_key, value):
    value = _number(value)
    if value is None:
        return None
    return abs(value) if supply_key == "neg1kv" else value


def _beam_energy_limits_clear(beam_energy_inputs, supply_keys):
    supplies = beam_energy_inputs.get("supplies", {})
    for supply_key in supply_keys:
        supply = supplies.get(supply_key, {})
        limits = supply.get("warning_limits", {})
        voltage = _comparison_value(supply_key, supply.get("actual_voltage_v"))
        current = _comparison_value(supply_key, supply.get("actual_current_ma"))
        min_voltage = _number(limits.get("min_voltage_v"))
        max_voltage = _number(limits.get("max_voltage_v"))
        max_current = _number(limits.get("max_current_ma"))

        if None in (voltage, current, min_voltage, max_voltage, max_current):
            return False
        if voltage < min_voltage or voltage >= max_voltage:
            return False
        if current >= max_current:
            return False
    return True


def _beam_energy_nomop(beam_energy_inputs):
    data = beam_energy_inputs.get("data", {})
    connected = beam_energy_inputs.get("unit_connected", {})
    global_data = data.get(4) if connected.get(4) else None
    return bool(global_data and global_data.get("nomop_flag"))


def _beam_energy_interlocks_clear(beam_energy_inputs, supply_keys):
    data = beam_energy_inputs.get("data", {})
    connected = beam_energy_inputs.get("unit_connected", {})
    global_data = data.get(4) if connected.get(4) else None
    if not global_data:
        return False

    flags_by_supply = beam_energy_inputs.get("interlock_flags", {})
    supplies = beam_energy_inputs.get("supplies", {})
    for supply_key in supply_keys:
        unit_id = supplies.get(supply_key, {}).get("unit_id")
        if not connected.get(unit_id):
            return False

        voltage_flag, current_flag = flags_by_supply.get(supply_key, (None, None))
        if bool(global_data.get(voltage_flag)) or bool(global_data.get(current_flag)):
            return False
    return True


def _cathode_temperature_ok(cathode_inputs):
    temperatures = cathode_inputs.get("clamp_temperatures_c", [])[:3]
    limits = cathode_inputs.get("overtemp_limits_c", [])[:3]
    if len(temperatures) < 3 or len(limits) < 3:
        return False

    for temperature, limit in zip(temperatures, limits):
        temperature = _number(temperature)
        limit = _number(limit)
        if temperature is None or limit is None or temperature > limit:
            return False
    return True


def _cathode_emission_ok(cathode_inputs, total_limit_ma):
    total_limit_ma = _number(total_limit_ma)
    currents = cathode_inputs.get("predicted_emission_currents_ma", [])[:3]
    if total_limit_ma is None or len(currents) < 3:
        return False

    for current in currents:
        current = _number(current)
        if current is None or current >= total_limit_ma:
            return False
    return True


def _activate_enabled_beams_limit_ok(beam_pulse, beam_pulse_inputs, cathode_inputs, total_limit_ma):
    enabled_channels = [
        index
        for index, enabled in enumerate(beam_pulse_inputs.get("channel_enable_status", [])[:3])
        if enabled
    ]
    if not enabled_channels:
        return True

    checker = getattr(beam_pulse, "_emission_limit_allows_output", None)
    if callable(checker):
        configs = [
            {"ch": index + 1, "mode": "DC", "duration_ms": 0, "count": 1}
            for index in enabled_channels
        ]
        try:
            allowed, _message = checker("Activate Enabled Beams", configs, log_failure=False)
            return bool(allowed)
        except Exception:
            return False

    total_limit_ma = _number(total_limit_ma)
    currents = cathode_inputs.get("predicted_emission_currents_ma", [])[:3]
    if total_limit_ma is None or len(currents) < 3:
        return False

    total = 0.0
    for index in enabled_channels:
        current = _number(currents[index])
        if current is None:
            return False
        total += current
    return total < total_limit_ma


def evaluate_machine_statuses(subsystems, main_control=None):
    subsystems = subsystems or {}
    interlocks = _subsystem(subsystems, "Interlocks")
    process_monitor = _subsystem(subsystems, "Process Monitor")
    beam_energy = _subsystem(subsystems, "Beam Energy")
    beam_pulse = _subsystem(subsystems, "Beam Pulse")
    cathode = _subsystem(subsystems, "Cathode Heating")

    beam_energy_inputs = _inputs(beam_energy)
    beam_pulse_inputs = _inputs(beam_pulse)
    cathode_inputs = _inputs(cathode)
    total_limit_ma = _number(getattr(main_control, "total_max_emission_current_ma", None))

    raw = OrderedDict((name, False) for name in STATUS_NAMES)
    raw["Chamber Pressure"] = _interlock_green(interlocks, "Vacuum Pressure")
    raw["Environment Temperature Monitors"] = _environment_pass(process_monitor)
    raw["Safety Interlocks"] = _interlock_green(interlocks, "All Interlocks")
    raw["HV Panel On"] = _interlock_green(interlocks, "HVolt ON")
    raw["High Voltage Power Supplies Nominal"] = (
        _beam_energy_nomop(beam_energy_inputs)
        and _beam_energy_limits_clear(beam_energy_inputs, BEAM_ENERGY_SUPPLIES)
    )
    raw["Beam Controller Nominal"] = (
        bool(beam_pulse_inputs.get("bcon_connected"))
        and _beam_energy_limits_clear(beam_energy_inputs, BCON_SUPPLIES)
        and _beam_energy_interlocks_clear(beam_energy_inputs, BCON_SUPPLIES)
    )
    raw["Cathode Heating"] = (
        any(cathode_inputs.get("output_states", [])[:3])
        and _cathode_temperature_ok(cathode_inputs)
        and _cathode_emission_ok(cathode_inputs, total_limit_ma)
    )
    raw["Beams Ready"] = (
        all(raw[name] for name in STATUS_NAMES[:7])
        and _activate_enabled_beams_limit_ok(
            beam_pulse,
            beam_pulse_inputs,
            cathode_inputs,
            total_limit_ma,
        )
    )
    raw["Beams On"] = bool(beam_pulse_inputs.get("any_beam_active"))
    return raw


class MachineStatus:
    def __init__(self, parent, logger=None, subsystem_provider=None, main_control_provider=None):
        self.parent = parent
        self.logger = logger
        self.subsystem_provider = subsystem_provider or (lambda: {})
        self.main_control_provider = main_control_provider or (lambda: None)
        self.status_labels = {}
        self._previous_display_states = None
        self._latest_raw_statuses = None
        self._latest_update_lock = threading.Lock()
        self._pending_after_ids = set()
        self._ui_after_id = None
        self._stop_event = threading.Event()
        self._last_error = None

        self.setup_gui()
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            name="MachineStatusWorker",
            daemon=True,
        )
        self._worker_thread.start()

    def setup_gui(self):
        self.machine_status_frame = tk.Frame(self.parent, bg=STATE_COLORS[STATE_GRAY])
        self.machine_status_frame.pack(fill=tk.BOTH, expand=True)

        for index in range(len(STATUS_NAMES)):
            self.machine_status_frame.grid_columnconfigure(index * 2, weight=1)
            self.machine_status_frame.grid_columnconfigure(index * 2 + 1, weight=0)

        for index, name in enumerate(STATUS_NAMES):
            label = tk.Label(
                self.machine_status_frame,
                text=name,
                anchor="w",
                padx=5,
                bg=STATE_COLORS[STATE_GRAY],
                fg="black",
                width=12,
                height=2,
                wraplength=95,
                justify="left",
            )
            label.grid(row=0, column=index * 2, sticky="ew")
            self.status_labels[name] = label

            if index < len(STATUS_NAMES) - 1:
                separator = tk.Frame(self.machine_status_frame, bg="black", width=1)
                separator.grid(row=0, column=index * 2 + 1, sticky="ns")

    def _log(self, message, level):
        if self.logger and hasattr(self.logger, "log"):
            self.logger.log(message, level, tag="Machine Status")

    def _worker_loop(self):
        while not self._stop_event.is_set():
            try:
                raw_statuses = evaluate_machine_statuses(
                    self.subsystem_provider() or {},
                    self.main_control_provider(),
                )
                if self._last_error:
                    self._queue_log("Machine status evaluation recovered.", LogLevel.INFO)
                    self._last_error = None
            except Exception as exc:
                raw_statuses = OrderedDict((name, False) for name in STATUS_NAMES)
                error_text = f"{type(exc).__name__}: {exc}"
                if error_text != self._last_error:
                    self._queue_log(f"Machine status evaluation failed: {error_text}", LogLevel.ERROR)
                    self._last_error = error_text

            if self._stop_event.is_set():
                break
            self._queue_status_update(raw_statuses)
            self._stop_event.wait(POLL_INTERVAL_SECONDS)

    def _queue_log(self, message, level):
        self._queue_after(lambda: self._log(message, level))

    def _queue_after(self, callback):
        if self._stop_event.is_set():
            return None

        after_id_ref = {"id": None}

        def _run():
            after_id = after_id_ref["id"]
            with self._latest_update_lock:
                self._pending_after_ids.discard(after_id)
            if not self._stop_event.is_set():
                callback()

        try:
            after_id = self.parent.after(0, _run)
        except Exception:
            return None
        after_id_ref["id"] = after_id

        with self._latest_update_lock:
            if not self._stop_event.is_set():
                self._pending_after_ids.add(after_id)
                return after_id

        try:
            self.parent.after_cancel(after_id)
        except Exception:
            pass
        return None

    def _queue_status_update(self, raw_statuses):
        should_schedule = False
        with self._latest_update_lock:
            self._latest_raw_statuses = raw_statuses
            if self._ui_after_id is None and not self._stop_event.is_set():
                self._ui_after_id = _AFTER_SCHEDULING
                should_schedule = True

        if not should_schedule:
            return

        after_id = self._queue_after(self._apply_latest_statuses)
        with self._latest_update_lock:
            if self._ui_after_id is _AFTER_SCHEDULING:
                self._ui_after_id = after_id

    def _apply_latest_statuses(self):
        with self._latest_update_lock:
            raw_statuses = self._latest_raw_statuses
            self._ui_after_id = None

        if raw_statuses is None:
            return

        display_states = calculate_display_states(raw_statuses)
        for name, state in display_states.items():
            label = self.status_labels.get(name)
            if label is not None:
                label.config(bg=STATE_COLORS[state])

        for name, _previous, current, level in build_status_transition_logs(
            self._previous_display_states,
            display_states,
        ):
            status_text = STATE_LOG_TEXT.get(current, current)
            self._log(f"{name} Status Indicator set to: {status_text}", level)

        self._previous_display_states = display_states

    def cancel_updates(self):
        self._stop_event.set()
        with self._latest_update_lock:
            after_ids = list(self._pending_after_ids)
            self._pending_after_ids.clear()
            self._ui_after_id = None

        for after_id in after_ids:
            try:
                self.parent.after_cancel(after_id)
            except Exception:
                pass

        worker = getattr(self, "_worker_thread", None)
        if (
            worker is not None
            and worker.is_alive()
            and threading.current_thread() is not worker
        ):
            self._worker_thread.join(timeout=0.25)
            if self._worker_thread.is_alive():
                self._log("Machine Status worker did not stop before timeout.", LogLevel.WARNING)
        self._log("Cancelled Machine Status worker.", LogLevel.DEBUG)
