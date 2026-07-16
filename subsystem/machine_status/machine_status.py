import math
import threading
import tkinter as tk
from collections import OrderedDict
from dataclasses import dataclass

from utils import LogLevel


STATUS_TEMPS = "STATUS_TEMPS"
STATUS_PRESSURE_1E_4 = "STATUS_PRESSURE_1E_4"
STATUS_INTERLOCKS = "STATUS_INTERLOCKS"
STATUS_HV_PANEL = "STATUS_HV_PANEL"
STATUS_PRESSURE_1E_6 = "STATUS_PRESSURE_1E_6"
STATUS_HVPS_NOMINAL = "STATUS_HVPS_NOMINAL"
STATUS_BCON = "STATUS_BCON"
STATUS_CATHODES = "STATUS_CATHODES"
STATUS_BEAMS_READY = "STATUS_BEAMS_READY"
STATUS_BEAMS_ON = "STATUS_BEAMS_ON"


@dataclass(frozen=True)
class StatusDefinition:
    key: str
    name: str


@dataclass(frozen=True)
class StatusConditions:
    force_red: bool = False
    ready: bool = False


STATUS_DEFINITIONS = (
    StatusDefinition(STATUS_TEMPS, "PMON Temperatures OK"),
    StatusDefinition(STATUS_PRESSURE_1E_4, "Pressure Below 1e-4 mbar"),
    StatusDefinition(STATUS_INTERLOCKS, "All Safety Interlocks Pass"),
    StatusDefinition(STATUS_HV_PANEL, "High Voltage Subpanel On"),
    StatusDefinition(STATUS_PRESSURE_1E_6, "Pressure Below 1e-6 mbar"),
    StatusDefinition(STATUS_HVPS_NOMINAL, "HV Power Supplies Nominal"),
    StatusDefinition(STATUS_BCON, "Beam Controller Nominal"),
    StatusDefinition(STATUS_CATHODES, "Cathode Heating"),
    StatusDefinition(STATUS_BEAMS_READY, "Beams Ready"),
    StatusDefinition(STATUS_BEAMS_ON, "Beams On"),
)
STATUS_KEYS = tuple(status.key for status in STATUS_DEFINITIONS)
STATUS_NAME_BY_KEY = {status.key: status.name for status in STATUS_DEFINITIONS}

STATE_GRAY = "gray"
STATE_GREEN = "green"
STATE_RED = "red"

STATE_COLORS = {
    STATE_GRAY: "#dbd9d9",
    STATE_GREEN: "green",
    STATE_RED: "red",
}
STATE_TEXT_COLORS = {
    STATE_GRAY: "gray",
    STATE_GREEN: "white",
    STATE_RED: "white",
}
STATE_LOG_TEXT = {
    STATE_GRAY: "In Progress",
    STATE_GREEN: "Ready",
    STATE_RED: "Warning",
}

POLL_INTERVAL_SECONDS = 0.2
PRESSURE_1E_4_MBAR = 1e-4
PRESSURE_1E_6_MBAR = 1e-6
BEAM_ENERGY_SUPPLIES = ("pos1kv", "neg1kv", "pos20kv", "pos3kv")
BCON_SUPPLIES = ("pos1kv", "neg1kv")
_AFTER_SCHEDULING = object()
STATUS_BAR_HEIGHT = 29
STATUS_BAR_SEPARATOR_WIDTH = 1


def calculate_display_states(status_conditions):
    display_states = {}
    higher_green = False

    for key in reversed(STATUS_KEYS):
        conditions = status_conditions.get(key, StatusConditions())
        if conditions.force_red:
            display_states[key] = STATE_RED
        elif conditions.ready:
            display_states[key] = STATE_GREEN
            higher_green = True
        elif higher_green:
            display_states[key] = STATE_RED
        else:
            display_states[key] = STATE_GRAY

    return OrderedDict((key, display_states[key]) for key in STATUS_KEYS)


def build_status_transition_logs(previous_states, current_states):
    if not previous_states:
        return []

    entries = []
    for key, current_state in current_states.items():
        previous_state = previous_states.get(key)
        if previous_state == current_state:
            continue
        level = LogLevel.WARNING if current_state == STATE_RED else LogLevel.INFO
        entries.append((STATUS_NAME_BY_KEY.get(key, key), previous_state, current_state, level))
    return entries


def _snapshot_subsystems(subsystems):
    if not subsystems:
        return {}
    try:
        return dict(subsystems)
    except Exception:
        return {}


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


def _pressure_below(vtrx_inputs, threshold_mbar):
    pressure = _number(vtrx_inputs.get("last_valid_pressure_value"))
    if pressure is None or not vtrx_inputs.get("pressure_fresh"):
        return False
    return pressure < threshold_mbar


def _comparison_value(supply_key, value):
    value = _number(value)
    if value is None:
        return None
    return abs(value) if supply_key == "neg1kv" else value


def _supply_values_complete(supply_key, supply):
    limits = supply.get("warning_limits", {})
    values = (
        _comparison_value(supply_key, supply.get("actual_voltage_v")),
        _comparison_value(supply_key, supply.get("actual_current_ma")),
        _number(limits.get("min_voltage_v")),
        _number(limits.get("max_voltage_v")),
        _number(limits.get("max_current_ma")),
    )
    return None not in values


def _supply_warning_tripped(supply_key, supply):
    limits = supply.get("warning_limits", {})
    voltage = _comparison_value(supply_key, supply.get("actual_voltage_v"))
    current = _comparison_value(supply_key, supply.get("actual_current_ma"))
    min_voltage = _number(limits.get("min_voltage_v"))
    max_voltage = _number(limits.get("max_voltage_v"))
    max_current = _number(limits.get("max_current_ma"))

    if None in (voltage, current, min_voltage, max_voltage, max_current):
        return False
    return (
        voltage < min_voltage
        or voltage >= max_voltage
        or current >= max_current
    )


def _beam_energy_limits_tripped(beam_energy_inputs, supply_keys):
    supplies = beam_energy_inputs.get("supplies", {})
    return any(
        _supply_warning_tripped(supply_key, supplies.get(supply_key, {}))
        for supply_key in supply_keys
    )


def _beam_energy_limits_clear(beam_energy_inputs, supply_keys):
    supplies = beam_energy_inputs.get("supplies", {})
    for supply_key in supply_keys:
        supply = supplies.get(supply_key, {})
        if not _supply_values_complete(supply_key, supply):
            return False
        if _supply_warning_tripped(supply_key, supply):
            return False
    return True


def _beam_energy_supply_comms_good(beam_energy_inputs, supply_keys):
    connected = beam_energy_inputs.get("unit_connected", {})
    supplies = beam_energy_inputs.get("supplies", {})
    if not connected:
        return False

    for supply_key in supply_keys:
        unit_id = supplies.get(supply_key, {}).get("unit_id")
        if unit_id is None or not connected.get(unit_id):
            return False
    return True


def _beam_energy_global_data(beam_energy_inputs):
    data = beam_energy_inputs.get("data", {})
    connected = beam_energy_inputs.get("unit_connected", {})
    if connected and not connected.get(4):
        return None
    return data.get(4)


def _beam_energy_interlocks_clear(beam_energy_inputs, supply_keys):
    global_data = _beam_energy_global_data(beam_energy_inputs)
    if not global_data:
        return False

    flags_by_supply = beam_energy_inputs.get("interlock_flags", {})
    supplies = beam_energy_inputs.get("supplies", {})
    connected = beam_energy_inputs.get("unit_connected", {})
    for supply_key in supply_keys:
        unit_id = supplies.get(supply_key, {}).get("unit_id")
        if connected and not connected.get(unit_id):
            return False

        voltage_flag, current_flag = flags_by_supply.get(supply_key, (None, None))
        if voltage_flag is None or current_flag is None:
            return False
        if bool(global_data.get(voltage_flag)) or bool(global_data.get(current_flag)):
            return False
    return True


def _cathode_overtemp_tripped(cathode_inputs):
    temperatures = cathode_inputs.get("clamp_temperatures_c", [])[:3]
    limits = cathode_inputs.get("overtemp_limits_c", [])[:3]
    for temperature, limit in zip(temperatures, limits):
        temperature = _number(temperature)
        limit = _number(limit)
        if temperature is not None and limit is not None and temperature > limit:
            return True
    return False


def _cathode_single_emission_tripped(cathode_inputs, total_limit_ma):
    total_limit_ma = _number(total_limit_ma)
    if total_limit_ma is None:
        return False

    for current in cathode_inputs.get("predicted_emission_currents_ma", [])[:3]:
        current = _number(current)
        if current is not None and current >= total_limit_ma:
            return True
    return False


def _enabled_emission_total_tripped(
    beam_pulse_inputs,
    cathode_inputs,
    total_limit_ma,
):
    """Return whether enabled beam channels meet or exceed the emission limit.

    This is a dashboard-status check and deliberately does not consult the
    emission-limit enable setting.  Disabling that setting permits Beam Pulse
    output commands, but does not disable the Beams Ready status check.
    """
    total_limit_ma = _number(total_limit_ma)
    if total_limit_ma is None:
        return False

    enabled_channels = list(
        beam_pulse_inputs.get("activation_interlock_states", [])
    )[:3]
    currents = list(cathode_inputs.get("predicted_emission_currents_ma", []))[:3]
    enabled_indices = [
        index for index, enabled in enumerate(enabled_channels) if bool(enabled)
    ]
    if not enabled_indices:
        return False

    total_current_ma = 0.0
    for index in enabled_indices:
        if index >= len(currents):
            return False
        current = _number(currents[index])
        if current is None:
            return False
        total_current_ma += current
    return total_current_ma >= total_limit_ma


def _lower_statuses_green_candidate(conditions):
    for key in STATUS_KEYS[:STATUS_KEYS.index(STATUS_BEAMS_READY)]:
        status = conditions.get(key, StatusConditions())
        if status.force_red or not status.ready:
            return False
    return True


def evaluate_machine_status_conditions(subsystems, main_control=None):
    subsystems = subsystems or {}
    interlocks = _subsystem(subsystems, "Interlocks")
    process_monitor = _subsystem(subsystems, "Process Monitor")
    vtrx = _subsystem(subsystems, "Vacuum System") or _subsystem(subsystems, "VTRX")
    beam_energy = _subsystem(subsystems, "Beam Energy")
    beam_pulse = _subsystem(subsystems, "Beam Pulse")
    cathode = _subsystem(subsystems, "Cathode Heating")

    process_monitor_inputs = _inputs(process_monitor)
    vtrx_inputs = _inputs(vtrx)
    beam_energy_inputs = _inputs(beam_energy)
    beam_pulse_inputs = _inputs(beam_pulse)
    cathode_inputs = _inputs(cathode)
    total_limit_ma = _number(getattr(main_control, "total_max_emission_current_ma", None))

    hvolt_on = _interlock_green(interlocks, "HVolt ON")
    g9_output = _interlock_green(interlocks, "G9SP Output")

    conditions = OrderedDict((key, StatusConditions()) for key in STATUS_KEYS)
    conditions[STATUS_TEMPS] = StatusConditions(
        ready=bool(process_monitor_inputs.get("environment_pass")),
    )
    conditions[STATUS_PRESSURE_1E_4] = StatusConditions(
        ready=_pressure_below(vtrx_inputs, PRESSURE_1E_4_MBAR),
    )
    conditions[STATUS_INTERLOCKS] = StatusConditions(
        ready=_interlock_green(interlocks, "All Interlocks"),
    )
    conditions[STATUS_HV_PANEL] = StatusConditions(
        force_red=g9_output and not hvolt_on,
        ready=hvolt_on,
    )
    conditions[STATUS_PRESSURE_1E_6] = StatusConditions(
        ready=_pressure_below(vtrx_inputs, PRESSURE_1E_6_MBAR),
    )
    conditions[STATUS_HVPS_NOMINAL] = StatusConditions(
        force_red=_beam_energy_limits_tripped(beam_energy_inputs, BEAM_ENERGY_SUPPLIES),
        ready=(
            bool(beam_energy_inputs.get("nomop"))
            and _beam_energy_supply_comms_good(beam_energy_inputs, BEAM_ENERGY_SUPPLIES)
            and bool(beam_energy_inputs.get("logic_comms"))
        ),
    )
    conditions[STATUS_BCON] = StatusConditions(
        ready=(
            bool(beam_pulse_inputs.get("bcon_connected"))
            and _beam_energy_limits_clear(beam_energy_inputs, BCON_SUPPLIES)
            and _beam_energy_interlocks_clear(beam_energy_inputs, BCON_SUPPLIES)
        ),
    )
    conditions[STATUS_CATHODES] = StatusConditions(
        force_red=(
            _cathode_overtemp_tripped(cathode_inputs)
            or _cathode_single_emission_tripped(cathode_inputs, total_limit_ma)
        ),
        ready=any(cathode_inputs.get("output_states", [])[:3]),
    )
    conditions[STATUS_BEAMS_READY] = StatusConditions(
        force_red=(
            not bool(beam_pulse_inputs.get("activate_enabled_beams_guard_clear", True))
            or _enabled_emission_total_tripped(
                beam_pulse_inputs,
                cathode_inputs,
                total_limit_ma,
            )
        ),
        ready=(
            _lower_statuses_green_candidate(conditions)
            and bool(beam_pulse_inputs.get("beams_armed_status"))
            and bool(beam_energy_inputs.get("arm_beams_hardware"))
        ),
    )
    conditions[STATUS_BEAMS_ON] = StatusConditions(
        ready=bool(beam_pulse_inputs.get("any_beam_active")),
    )
    return conditions


class MachineStatus:
    def __init__(self, parent, logger=None, subsystem_provider=None, main_control_provider=None):
        self.parent = parent
        self.logger = logger
        self.subsystem_provider = subsystem_provider or (lambda: {})
        self.main_control_provider = main_control_provider or (lambda: None)
        self.status_labels = {}
        self._display_states = OrderedDict((key, STATE_GRAY) for key in STATUS_KEYS)
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
        self.machine_status_frame = tk.Frame(self.parent, bg="white", height=STATUS_BAR_HEIGHT)
        self.machine_status_frame.pack_propagate(False)
        self.machine_status_frame.pack(fill=tk.BOTH, expand=True)

        self.status_canvas = tk.Canvas(
            self.machine_status_frame,
            height=STATUS_BAR_HEIGHT,
            bg="white",
            highlightthickness=0,
            bd=0,
        )
        self.status_canvas.pack(fill=tk.BOTH, expand=True)
        self.status_canvas.bind("<Configure>", lambda _event: self._draw_status_bar())
        self._draw_status_bar()

    def _draw_status_bar(self):
        canvas = getattr(self, "status_canvas", None)
        if canvas is None:
            return

        width = canvas.winfo_width()
        height = canvas.winfo_height()
        if width <= 1 or height <= 1:
            width = max(width, self.machine_status_frame.winfo_reqwidth())
            height = max(height, STATUS_BAR_HEIGHT)

        canvas.delete("all")
        self.status_labels.clear()

        segment_count = len(STATUS_DEFINITIONS)
        segment_width = width / segment_count
        tip_width = min(40, (height - STATUS_BAR_SEPARATOR_WIDTH) / 2)
        mid_y = height / 2

        for index, status in enumerate(STATUS_DEFINITIONS):
            x0 = index * segment_width
            x1 = (index + 1) * segment_width
            state = self._display_states.get(status.key, STATE_GRAY)
            fill_color = STATE_COLORS[state]
            text_color = STATE_TEXT_COLORS[state]

            if index == 0:
                points = (x0, 0, x1 - tip_width, 0, x1, mid_y, x1 - tip_width, height, x0, height)
            else:
                points = (
                    x0,
                    0,
                    x1 - tip_width,
                    0,
                    x1,
                    mid_y,
                    x1 - tip_width,
                    height,
                    x0,
                    height,
                    x0 + tip_width,
                    mid_y,
                )

            segment_id = canvas.create_polygon(
                points,
                fill=fill_color,
                outline="white",
                width=STATUS_BAR_SEPARATOR_WIDTH,
            )
            text_id = canvas.create_text(
                x0 + segment_width / 2 + (tip_width / 5 if index == 0 else tip_width / 3),
                mid_y,
                text=status.name,
                fill=text_color,
                font=("Segoe UI", 8, "bold"),
                width=max(24, int(segment_width - tip_width - 10)),
                justify="center",
            )
            self.status_labels[status.key] = {"segment": segment_id, "text": text_id}

    def _log(self, message, level):
        if self.logger and hasattr(self.logger, "log"):
            self.logger.log(message, level, tag="Machine Status")

    def _worker_loop(self):
        while not self._stop_event.is_set():
            try:
                subsystems = _snapshot_subsystems(self.subsystem_provider() or {})
                status_conditions = evaluate_machine_status_conditions(
                    subsystems,
                    self.main_control_provider(),
                )
                if self._last_error:
                    self._queue_log("Machine status evaluation recovered.", LogLevel.INFO)
                    self._last_error = None
            except Exception as exc:
                status_conditions = OrderedDict((key, StatusConditions()) for key in STATUS_KEYS)
                error_text = f"{type(exc).__name__}: {exc}"
                if error_text != self._last_error:
                    self._queue_log(f"Machine status evaluation failed: {error_text}", LogLevel.ERROR)
                    self._last_error = error_text

            if self._stop_event.is_set():
                break
            self._queue_status_update(status_conditions)
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

    def _queue_status_update(self, status_conditions):
        should_schedule = False
        with self._latest_update_lock:
            self._latest_raw_statuses = status_conditions
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
            status_conditions = self._latest_raw_statuses
            self._ui_after_id = None

        if status_conditions is None:
            return

        display_states = calculate_display_states(status_conditions)
        self._display_states = display_states
        self._draw_status_bar()

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
