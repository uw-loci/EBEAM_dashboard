import os
import sys
import threading
import unittest
from collections import OrderedDict

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from subsystem.machine_status.machine_status import (
    STATE_GRAY,
    STATE_GREEN,
    STATE_RED,
    STATUS_NAMES,
    MachineStatus,
    build_status_transition_logs,
    calculate_display_states,
    evaluate_machine_statuses,
)
from utils import LogLevel


class FakeInterlocks:
    def __init__(self, states):
        self.states = dict(states)

    def get_interlock_status(self, name):
        return self.states.get(name, False)


class FakeProcessMonitor:
    def __init__(self, environment_pass):
        self.environment_pass = environment_pass

    def get_environment_pass(self):
        return self.environment_pass


class FakeBeamEnergy:
    def __init__(self, inputs):
        self.inputs = inputs

    def get_machine_status_inputs(self):
        return self.inputs


class FakeBeamPulse:
    def __init__(self, bcon_connected=True, any_beam_active=False, emission_allowed=True):
        self.inputs = {
            "bcon_connected": bcon_connected,
            "any_beam_active": any_beam_active,
            "channel_enable_status": [True, True, False],
        }
        self.emission_allowed = emission_allowed

    def get_machine_status_inputs(self):
        return self.inputs

    def _emission_limit_allows_output(self, _action, _configs, log_failure=True):
        return self.emission_allowed, None


class FakeCathodeHeating:
    def __init__(self):
        self.inputs = {
            "output_states": [True, False, False],
            "clamp_temperatures_c": [25.0, 26.0, 27.0],
            "overtemp_limits_c": [200.0, 200.0, 200.0],
            "predicted_emission_currents_ma": [1.0, 2.0, 1.5],
        }

    def get_machine_status_inputs(self):
        return self.inputs


class FakeMainControl:
    total_max_emission_current_ma = 6.0


class FakeParent:
    def __init__(self):
        self.callbacks = {}
        self.cancelled = []
        self._next_id = 1

    def after(self, _delay_ms, callback):
        after_id = f"after-{self._next_id}"
        self._next_id += 1
        self.callbacks[after_id] = callback
        return after_id

    def after_cancel(self, after_id):
        self.cancelled.append(after_id)
        self.callbacks.pop(after_id, None)


def beam_energy_inputs(pos1_current=5.0):
    limits = {
        "min_voltage_v": 0.0,
        "max_voltage_v": 1000.0,
        "max_current_ma": 30.0,
    }
    supplies = {
        "pos1kv": {
            "unit_id": 1,
            "actual_voltage_v": 500.0,
            "actual_current_ma": pos1_current,
            "warning_limits": dict(limits),
        },
        "neg1kv": {
            "unit_id": 2,
            "actual_voltage_v": -500.0,
            "actual_current_ma": 5.0,
            "warning_limits": dict(limits),
        },
        "pos20kv": {
            "unit_id": 3,
            "actual_voltage_v": 10000.0,
            "actual_current_ma": 0.2,
            "warning_limits": {
                "min_voltage_v": 0.0,
                "max_voltage_v": 20000.0,
                "max_current_ma": 1.0,
            },
        },
        "pos3kv": {
            "unit_id": 4,
            "actual_voltage_v": 1000.0,
            "actual_current_ma": 1.0,
            "warning_limits": {
                "min_voltage_v": 0.0,
                "max_voltage_v": 3000.0,
                "max_current_ma": 10.0,
            },
        },
    }
    return {
        "data": {
            4: {
                "nomop_flag": 1,
                "vcomp_1k_flag": 0,
                "icomp_1k_flag": 0,
                "neg_vcomp_1k_flag": 0,
                "neg_icomp_1k_flag": 0,
            },
        },
        "unit_connected": {1: True, 2: True, 3: True, 4: True},
        "supplies": supplies,
        "interlock_flags": {
            "pos1kv": ("vcomp_1k_flag", "icomp_1k_flag"),
            "neg1kv": ("neg_vcomp_1k_flag", "neg_icomp_1k_flag"),
            "pos20kv": ("vcomp_20k_flag", "icomp_20k_flag"),
            "pos3kv": ("vcomp_3k_flag", "icomp_3k_flag"),
        },
    }


class MachineStatusTest(unittest.TestCase):
    def test_display_rule_marks_lower_incomplete_statuses_red(self):
        raw = OrderedDict((name, False) for name in STATUS_NAMES)
        raw["Environment Temperature Monitors"] = True
        raw["HV Panel On"] = True

        display = calculate_display_states(raw)

        self.assertEqual(display["Chamber Pressure"], STATE_RED)
        self.assertEqual(display["Environment Temperature Monitors"], STATE_GREEN)
        self.assertEqual(display["Safety Interlocks"], STATE_RED)
        self.assertEqual(display["HV Panel On"], STATE_GREEN)
        self.assertEqual(display["High Voltage Power Supplies Nominal"], STATE_GRAY)

    def test_transition_logs_use_warning_only_for_red(self):
        previous = OrderedDict(
            [
                ("Chamber Pressure", STATE_GRAY),
                ("Environment Temperature Monitors", STATE_GREEN),
                ("Safety Interlocks", STATE_RED),
            ]
        )
        current = OrderedDict(
            [
                ("Chamber Pressure", STATE_RED),
                ("Environment Temperature Monitors", STATE_GRAY),
                ("Safety Interlocks", STATE_GREEN),
            ]
        )

        entries = build_status_transition_logs(previous, current)

        self.assertEqual(entries[0], ("Chamber Pressure", STATE_GRAY, STATE_RED, LogLevel.WARNING))
        self.assertEqual(entries[1], ("Environment Temperature Monitors", STATE_GREEN, STATE_GRAY, LogLevel.INFO))
        self.assertEqual(entries[2], ("Safety Interlocks", STATE_RED, STATE_GREEN, LogLevel.INFO))

    def test_evaluator_maps_all_green_sources(self):
        subsystems = {
            "Interlocks": FakeInterlocks(
                {
                    "Vacuum Pressure": True,
                    "All Interlocks": True,
                    "HVolt ON": True,
                }
            ),
            "Process Monitor [C]": FakeProcessMonitor(True),
            "Beam Energy": FakeBeamEnergy(beam_energy_inputs()),
            "Beam Pulse": FakeBeamPulse(any_beam_active=True),
            "Cathode Heating": FakeCathodeHeating(),
        }

        raw = evaluate_machine_statuses(subsystems, FakeMainControl())

        for name in STATUS_NAMES:
            self.assertTrue(raw[name], name)

    def test_bcon_current_must_be_below_max_i(self):
        subsystems = {
            "Interlocks": FakeInterlocks(
                {
                    "Vacuum Pressure": True,
                    "All Interlocks": True,
                    "HVolt ON": True,
                }
            ),
            "Process Monitor [C]": FakeProcessMonitor(True),
            "Beam Energy": FakeBeamEnergy(beam_energy_inputs(pos1_current=30.0)),
            "Beam Pulse": FakeBeamPulse(),
            "Cathode Heating": FakeCathodeHeating(),
        }

        raw = evaluate_machine_statuses(subsystems, FakeMainControl())

        self.assertFalse(raw["Beam Controller Nominal"])

    def test_beams_ready_uses_beam_pulse_emission_limit_result(self):
        subsystems = {
            "Interlocks": FakeInterlocks(
                {
                    "Vacuum Pressure": True,
                    "All Interlocks": True,
                    "HVolt ON": True,
                }
            ),
            "Process Monitor [C]": FakeProcessMonitor(True),
            "Beam Energy": FakeBeamEnergy(beam_energy_inputs()),
            "Beam Pulse": FakeBeamPulse(emission_allowed=False),
            "Cathode Heating": FakeCathodeHeating(),
        }

        raw = evaluate_machine_statuses(subsystems, FakeMainControl())

        self.assertFalse(raw["Beams Ready"])

    def test_cancel_updates_cancels_all_pending_after_callbacks(self):
        parent = FakeParent()
        status = MachineStatus.__new__(MachineStatus)
        status.parent = parent
        status.logger = None
        status._latest_update_lock = threading.Lock()
        status._pending_after_ids = set()
        status._ui_after_id = None
        status._stop_event = threading.Event()
        status._latest_raw_statuses = None

        status._queue_log("queued log", LogLevel.INFO)
        status._queue_status_update(OrderedDict((name, False) for name in STATUS_NAMES))

        pending_ids = set(parent.callbacks)
        status.cancel_updates()

        self.assertEqual(set(parent.cancelled), pending_ids)
        self.assertFalse(status._pending_after_ids)
        self.assertIsNone(status._ui_after_id)


if __name__ == "__main__":
    unittest.main()
