import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from subsystem.main_control.main_control import MainControlPanel


class FakeBeamPulse:
    def __init__(self, output_on=False, all_off_result=True):
        self.output_on = output_on
        self.all_off_result = all_off_result
        self.all_off_calls = 0

    def get_beam_status(self, _channel):
        return self.output_on

    def disable_all_beams(self):
        self.all_off_calls += 1
        return self.all_off_result


class MainControlSoftwareInterlockTest(unittest.TestCase):
    def make_panel(self, beam_pulse):
        panel = object.__new__(MainControlPanel)
        panel._beam_software_interlock_states = [True, False, False]
        panel.enable_toggle_buttons = []
        panel.update_calls = []
        panel.status_updates = []
        panel.errors = []
        panel._get_beam_pulse_or_fail = lambda _action: beam_pulse
        panel.update_beam_toggle_states = lambda **kwargs: panel.update_calls.append(kwargs)
        panel._set_beam_action_status = lambda *args: panel.status_updates.append(args)
        panel._log_error = panel.errors.append
        return panel

    def test_disabling_active_beam_waits_for_confirmed_all_off(self):
        beam_pulse = FakeBeamPulse(output_on=True, all_off_result=True)
        panel = self.make_panel(beam_pulse)

        panel._toggle_beam_software_interlock(0)

        self.assertEqual(beam_pulse.all_off_calls, 1)
        self.assertEqual(panel._beam_software_interlock_states, [False, False, False])

    def test_failed_all_off_keeps_active_beam_interlock_enabled(self):
        beam_pulse = FakeBeamPulse(output_on=True, all_off_result=False)
        panel = self.make_panel(beam_pulse)

        panel._toggle_beam_software_interlock(0)

        self.assertEqual(beam_pulse.all_off_calls, 1)
        self.assertEqual(panel._beam_software_interlock_states, [True, False, False])
        self.assertIn("Failed to stop output", panel.status_updates[-1][0])

    def test_disabling_inactive_beam_does_not_send_all_off(self):
        beam_pulse = FakeBeamPulse(output_on=False)
        panel = self.make_panel(beam_pulse)

        panel._toggle_beam_software_interlock(0)

        self.assertEqual(beam_pulse.all_off_calls, 0)
        self.assertEqual(panel._beam_software_interlock_states, [False, False, False])


if __name__ == "__main__":
    unittest.main()
