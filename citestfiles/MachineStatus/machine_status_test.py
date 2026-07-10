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
    STATUS_BCON,
    STATUS_BEAMS_ON,
    STATUS_BEAMS_READY,
    STATUS_CATHODES,
    STATUS_DEFINITIONS,
    STATUS_HV_PANEL,
    STATUS_HVPS_NOMINAL,
    STATUS_INTERLOCKS,
    STATUS_KEYS,
    STATUS_PRESSURE_1E_4,
    STATUS_PRESSURE_1E_6,
    STATUS_TEMPS,
    MachineStatus,
    StatusConditions,
    _snapshot_subsystems,
    build_status_transition_logs,
    calculate_display_states,
    evaluate_machine_status_conditions,
)
from utils import LogLevel


class FakeInterlocks:
    def __init__(self, states):
        self.states = dict(states)

    def get_interlock_status(self, name):
        return self.states.get(name, False)


class FakeProcessMonitor:
    def __init__(self, environment_pass=True):
        self.environment_pass = environment_pass

    def get_machine_status_inputs(self):
        return {"environment_pass": self.environment_pass}


class FakeVTRX:
    def __init__(self, pressure=5e-7, communicating=True):
        self.pressure = pressure
        self.pressure_fresh = communicating

    def get_machine_status_inputs(self):
        return {
            "last_valid_pressure_value": self.pressure,
            "pressure_fresh": self.pressure_fresh,
        }


class FakeBeamEnergy:
    def __init__(self, inputs):
        self.inputs = inputs

    def get_machine_status_inputs(self):
        return self.inputs


class FakeBeamPulse:
    def __init__(
        self,
        bcon_connected=True,
        any_beam_active=False,
        beams_armed=True,
        enabled_channels=None,
        activate_enabled_beams_guard_clear=True,
    ):
        self.inputs = {
            "bcon_connected": bcon_connected,
            "any_beam_active": any_beam_active,
            "channel_enable_status": (
                [True, False, False]
                if enabled_channels is None
                else list(enabled_channels)
            ),
            "beams_armed_status": beams_armed,
            "activate_enabled_beams_guard_clear": activate_enabled_beams_guard_clear,
        }

    def get_machine_status_inputs(self):
        return self.inputs


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


def beam_energy_inputs(
    *,
    nomop=True,
    logic_comms=True,
    arm_beams_hardware=True,
    disconnected_units=None,
    pos1_current=5.0,
    pos1_voltage_flag=0,
):
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
                "nomop_flag": int(nomop),
                "arm_beams": int(arm_beams_hardware),
                "vcomp_1k_flag": int(pos1_voltage_flag),
                "icomp_1k_flag": 0,
                "neg_vcomp_1k_flag": 0,
                "neg_icomp_1k_flag": 0,
                "vcomp_20k_flag": 0,
                "icomp_20k_flag": 0,
                "vcomp_3k_flag": 0,
                "icomp_3k_flag": 0,
                "logic_alive": int(logic_comms),
            },
        },
        "unit_connected": {
            unit_id: unit_id not in set(disconnected_units or ())
            for unit_id in (1, 2, 3, 4)
        },
        "supplies": supplies,
        "interlock_flags": {
            "pos1kv": ("vcomp_1k_flag", "icomp_1k_flag"),
            "neg1kv": ("neg_vcomp_1k_flag", "neg_icomp_1k_flag"),
            "pos20kv": ("vcomp_20k_flag", "icomp_20k_flag"),
            "pos3kv": ("vcomp_3k_flag", "icomp_3k_flag"),
        },
        "nomop": bool(nomop),
        "logic_comms": bool(logic_comms),
        "arm_beams_hardware": bool(arm_beams_hardware),
    }


def base_subsystems(
    *,
    pressure=5e-7,
    environment_pass=True,
    hvolt_on=True,
    g9_output=True,
    beam_energy=None,
    beam_pulse=None,
    cathode=None,
):
    return {
        "Vacuum System": FakeVTRX(pressure=pressure),
        "Process Monitor [C]": FakeProcessMonitor(environment_pass),
        "Interlocks": FakeInterlocks(
            {
                "All Interlocks": True,
                "HVolt ON": hvolt_on,
                "G9SP Output": g9_output,
            }
        ),
        "Beam Energy": FakeBeamEnergy(beam_energy or beam_energy_inputs()),
        "Beam Pulse": beam_pulse or FakeBeamPulse(any_beam_active=True),
        "Cathode Heating": cathode or FakeCathodeHeating(),
    }


class MachineStatusTest(unittest.TestCase):
    def test_status_definitions_use_requested_keys_and_names(self):
        self.assertEqual(
            [status.key for status in STATUS_DEFINITIONS],
            list(STATUS_KEYS),
        )
        self.assertIn(STATUS_PRESSURE_1E_4, STATUS_KEYS)
        self.assertIn(STATUS_PRESSURE_1E_6, STATUS_KEYS)
        names = [status.name for status in STATUS_DEFINITIONS]
        self.assertIn("Pressure Below 1e-4 mbar", names)
        self.assertIn("Pressure Below 1e-6 mbar", names)

    def test_display_rule_marks_lower_incomplete_statuses_red(self):
        conditions = OrderedDict((key, StatusConditions()) for key in STATUS_KEYS)
        conditions[STATUS_TEMPS] = StatusConditions(ready=True)
        conditions[STATUS_HV_PANEL] = StatusConditions(ready=True)

        display = calculate_display_states(conditions)

        self.assertEqual(display[STATUS_TEMPS], STATE_GREEN)
        self.assertEqual(display[STATUS_PRESSURE_1E_4], STATE_RED)
        self.assertEqual(display[STATUS_INTERLOCKS], STATE_RED)
        self.assertEqual(display[STATUS_HV_PANEL], STATE_GREEN)
        self.assertEqual(display[STATUS_PRESSURE_1E_6], STATE_GRAY)

    def test_force_red_takes_precedence_over_ready(self):
        conditions = OrderedDict((key, StatusConditions()) for key in STATUS_KEYS)
        conditions[STATUS_CATHODES] = StatusConditions(force_red=True, ready=True)

        display = calculate_display_states(conditions)

        self.assertEqual(display[STATUS_CATHODES], STATE_RED)

    def test_transition_logs_use_warning_only_for_red(self):
        previous = OrderedDict(
            [
                (STATUS_TEMPS, STATE_GRAY),
                (STATUS_PRESSURE_1E_4, STATE_GREEN),
                (STATUS_INTERLOCKS, STATE_RED),
            ]
        )
        current = OrderedDict(
            [
                (STATUS_TEMPS, STATE_RED),
                (STATUS_PRESSURE_1E_4, STATE_GRAY),
                (STATUS_INTERLOCKS, STATE_GREEN),
            ]
        )

        entries = build_status_transition_logs(previous, current)

        self.assertEqual(entries[0], ("PMON Temperatures OK", STATE_GRAY, STATE_RED, LogLevel.WARNING))
        self.assertEqual(entries[1], ("Pressure Below 1e-4 mbar", STATE_GREEN, STATE_GRAY, LogLevel.INFO))
        self.assertEqual(entries[2], ("All Safety Interlocks Pass", STATE_RED, STATE_GREEN, LogLevel.INFO))

    def test_evaluator_maps_all_green_sources(self):
        conditions = evaluate_machine_status_conditions(
            base_subsystems(),
            FakeMainControl(),
        )

        for key in STATUS_KEYS:
            self.assertTrue(conditions[key].ready, key)
            self.assertFalse(conditions[key].force_red, key)

        display = calculate_display_states(conditions)
        for key in STATUS_KEYS:
            self.assertEqual(display[key], STATE_GREEN, key)

    def test_pmon_status_uses_environment_pass_only(self):
        conditions = evaluate_machine_status_conditions(
            base_subsystems(environment_pass=False),
            FakeMainControl(),
        )
        self.assertFalse(conditions[STATUS_TEMPS].ready)

        class LegacyProcessMonitor:
            def get_machine_status_inputs(self):
                return {"pmon_communicating": True}

        subsystems = base_subsystems()
        subsystems["Process Monitor [C]"] = LegacyProcessMonitor()
        conditions = evaluate_machine_status_conditions(subsystems, FakeMainControl())
        self.assertFalse(conditions[STATUS_TEMPS].ready)

    def test_pressure_thresholds_use_1e_keys_and_strict_below(self):
        conditions = evaluate_machine_status_conditions(
            base_subsystems(pressure=5e-5),
            FakeMainControl(),
        )
        self.assertTrue(conditions[STATUS_PRESSURE_1E_4].ready)
        self.assertFalse(conditions[STATUS_PRESSURE_1E_6].ready)

        conditions = evaluate_machine_status_conditions(
            base_subsystems(pressure=1e-6),
            FakeMainControl(),
        )
        self.assertFalse(conditions[STATUS_PRESSURE_1E_6].ready)

        conditions = evaluate_machine_status_conditions(
            base_subsystems(pressure=9e-7),
            FakeMainControl(),
        )
        self.assertTrue(conditions[STATUS_PRESSURE_1E_6].ready)

    def test_hv_panel_forces_red_when_g9_output_on_without_hvolt(self):
        conditions = evaluate_machine_status_conditions(
            base_subsystems(hvolt_on=False, g9_output=True),
            FakeMainControl(),
        )

        self.assertTrue(conditions[STATUS_HV_PANEL].force_red)
        self.assertFalse(conditions[STATUS_HV_PANEL].ready)

    def test_hvps_nominal_force_red_uses_all_beam_energy_warning_limits(self):
        beam_energy = beam_energy_inputs(pos1_current=30.0)

        conditions = evaluate_machine_status_conditions(
            base_subsystems(beam_energy=beam_energy),
            FakeMainControl(),
        )

        self.assertTrue(conditions[STATUS_HVPS_NOMINAL].force_red)
        self.assertTrue(conditions[STATUS_HVPS_NOMINAL].ready)
        self.assertEqual(
            calculate_display_states(conditions)[STATUS_HVPS_NOMINAL],
            STATE_RED,
        )

    def test_hvps_nominal_requires_nomop_all_supply_comms_and_logic_comms(self):
        conditions = evaluate_machine_status_conditions(
            base_subsystems(beam_energy=beam_energy_inputs()),
            FakeMainControl(),
        )
        self.assertTrue(conditions[STATUS_HVPS_NOMINAL].ready)

        conditions = evaluate_machine_status_conditions(
            base_subsystems(beam_energy=beam_energy_inputs(nomop=False)),
            FakeMainControl(),
        )
        self.assertFalse(conditions[STATUS_HVPS_NOMINAL].ready)

        conditions = evaluate_machine_status_conditions(
            base_subsystems(beam_energy=beam_energy_inputs(disconnected_units={2})),
            FakeMainControl(),
        )
        self.assertFalse(conditions[STATUS_HVPS_NOMINAL].ready)

        conditions = evaluate_machine_status_conditions(
            base_subsystems(beam_energy=beam_energy_inputs(logic_comms=False)),
            FakeMainControl(),
        )
        self.assertFalse(conditions[STATUS_HVPS_NOMINAL].ready)

    def test_bcon_requires_connection_limits_and_interlocks(self):
        conditions = evaluate_machine_status_conditions(
            base_subsystems(beam_pulse=FakeBeamPulse(bcon_connected=False)),
            FakeMainControl(),
        )
        self.assertFalse(conditions[STATUS_BCON].ready)

        conditions = evaluate_machine_status_conditions(
            base_subsystems(beam_energy=beam_energy_inputs(pos1_current=30.0)),
            FakeMainControl(),
        )
        self.assertFalse(conditions[STATUS_BCON].ready)

        conditions = evaluate_machine_status_conditions(
            base_subsystems(beam_energy=beam_energy_inputs(pos1_voltage_flag=1)),
            FakeMainControl(),
        )
        self.assertFalse(conditions[STATUS_BCON].ready)

    def test_cathode_force_red_uses_overtemp_and_single_current_limit(self):
        cathode = FakeCathodeHeating()
        cathode.inputs["clamp_temperatures_c"] = [25.0, 250.0, 27.0]

        conditions = evaluate_machine_status_conditions(
            base_subsystems(cathode=cathode),
            FakeMainControl(),
        )
        self.assertTrue(conditions[STATUS_CATHODES].force_red)
        self.assertTrue(conditions[STATUS_CATHODES].ready)

        cathode = FakeCathodeHeating()
        cathode.inputs["predicted_emission_currents_ma"] = [1.0, 6.0, 1.5]

        conditions = evaluate_machine_status_conditions(
            base_subsystems(cathode=cathode),
            FakeMainControl(),
        )
        self.assertTrue(conditions[STATUS_CATHODES].force_red)

    def test_beams_ready_requires_lower_statuses_and_software_and_hardware_arm(self):
        conditions = evaluate_machine_status_conditions(
            base_subsystems(),
            FakeMainControl(),
        )
        self.assertTrue(conditions[STATUS_BEAMS_READY].ready)

        conditions = evaluate_machine_status_conditions(
            base_subsystems(beam_pulse=FakeBeamPulse(beams_armed=False)),
            FakeMainControl(),
        )
        self.assertFalse(conditions[STATUS_BEAMS_READY].ready)

        conditions = evaluate_machine_status_conditions(
            base_subsystems(beam_energy=beam_energy_inputs(arm_beams_hardware=False)),
            FakeMainControl(),
        )
        self.assertFalse(conditions[STATUS_BEAMS_READY].ready)

        conditions = evaluate_machine_status_conditions(
            base_subsystems(pressure=5e-5),
            FakeMainControl(),
        )
        self.assertFalse(conditions[STATUS_BEAMS_READY].ready)

    def test_beams_ready_force_red_uses_beam_pulse_guard_result(self):
        cathode = FakeCathodeHeating()
        cathode.inputs["predicted_emission_currents_ma"] = [3.0, 3.0, 1.0]
        beam_pulse = FakeBeamPulse(activate_enabled_beams_guard_clear=False)

        conditions = evaluate_machine_status_conditions(
            base_subsystems(beam_pulse=beam_pulse, cathode=cathode),
            FakeMainControl(),
        )

        self.assertTrue(conditions[STATUS_BEAMS_READY].force_red)
        self.assertEqual(
            calculate_display_states(conditions)[STATUS_BEAMS_READY],
            STATE_RED,
        )

    def test_beams_ready_force_red_when_enabled_current_sum_meets_limit_disabled(self):
        cathode = FakeCathodeHeating()
        cathode.inputs["predicted_emission_currents_ma"] = [3.0, 3.0, 1.0]
        beam_pulse = FakeBeamPulse(
            enabled_channels=[True, True, False],
            activate_enabled_beams_guard_clear=True,
        )
        main_control = FakeMainControl()
        main_control.total_max_emission_current_limit_enabled = False

        conditions = evaluate_machine_status_conditions(
            base_subsystems(beam_pulse=beam_pulse, cathode=cathode),
            main_control,
        )

        self.assertTrue(conditions[STATUS_BEAMS_READY].force_red)
        self.assertEqual(
            calculate_display_states(conditions)[STATUS_BEAMS_READY],
            STATE_RED,
        )

    def test_beams_on_uses_any_beam_active(self):
        conditions = evaluate_machine_status_conditions(
            base_subsystems(beam_pulse=FakeBeamPulse(any_beam_active=False)),
            FakeMainControl(),
        )
        self.assertFalse(conditions[STATUS_BEAMS_ON].ready)

        conditions = evaluate_machine_status_conditions(
            base_subsystems(beam_pulse=FakeBeamPulse(any_beam_active=True)),
            FakeMainControl(),
        )
        self.assertTrue(conditions[STATUS_BEAMS_ON].ready)

    def test_evaluator_returns_conditions_by_key(self):
        conditions = evaluate_machine_status_conditions(base_subsystems(), FakeMainControl())

        self.assertEqual(list(conditions.keys()), list(STATUS_KEYS))
        self.assertTrue(conditions[STATUS_TEMPS].ready)

    def test_snapshot_subsystems_returns_independent_copy(self):
        source = {"Interlocks": FakeInterlocks({})}

        snapshot = _snapshot_subsystems(source)
        source["Beam Energy"] = FakeBeamEnergy(beam_energy_inputs())

        self.assertIsNot(snapshot, source)
        self.assertIn("Interlocks", snapshot)
        self.assertNotIn("Beam Energy", snapshot)

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
        status._queue_status_update(OrderedDict((key, StatusConditions()) for key in STATUS_KEYS))

        pending_ids = set(parent.callbacks)
        status.cancel_updates()

        self.assertEqual(set(parent.cancelled), pending_ids)
        self.assertFalse(status._pending_after_ids)
        self.assertIsNone(status._ui_after_id)


if __name__ == "__main__":
    unittest.main()
