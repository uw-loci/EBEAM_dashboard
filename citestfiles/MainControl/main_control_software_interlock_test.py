import os
import sys
import unittest
from unittest.mock import patch

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from subsystem.main_control.main_control import MainControlPanel


class FakeBeamPulse:
    def __init__(self, output_on=False, channel_off_result=True):
        self.output_on = output_on
        self.channel_off_result = channel_off_result
        self.channel_off_calls = []

    def get_beam_status(self, _channel):
        return self.output_on

    def send_channel_off(self, channel, operation_token=None):
        self.channel_off_calls.append(channel)
        return self.channel_off_result


class BeamPulseWithoutStatus:
    def __init__(self):
        self.channel_off_calls = []

    def send_channel_off(self, channel, operation_token=None):
        self.channel_off_calls.append(channel)
        return True


class FakeButton:
    def __init__(self, **values):
        self.values = values

    def config(self, **kwargs):
        self.values.update(kwargs)

    def cget(self, key):
        return self.values.get(key)


class FakeRoot:
    def __init__(self):
        self.calls = []

    def after(self, delay_ms, callback):
        self.calls.append((delay_ms, callback))
        return len(self.calls)

    def after_cancel(self, _after_id):
        pass


class MainControlSoftwareInterlockTest(unittest.TestCase):
    def make_panel(self, beam_pulse):
        panel = object.__new__(MainControlPanel)
        panel._beam_software_interlock_states = [True, False, False]
        panel.software_interlock_buttons = [
            FakeButton(state="normal", bg="#2e7d32", text="Beam A Enabled")
        ]
        panel.update_calls = []
        panel.status_updates = []
        panel.errors = []
        panel.infos = []
        panel.warnings = []
        panel._get_beam_pulse_or_fail = lambda _action: beam_pulse
        panel._update_beam_output_button_states = lambda **kwargs: panel.update_calls.append(kwargs)
        panel._set_beam_action_status = lambda *args: panel.status_updates.append(args)
        panel._log_error = panel.errors.append
        panel._log_info = panel.infos.append
        panel._log_warning = panel.warnings.append
        panel._log_critical = panel.errors.append
        return panel

    @staticmethod
    def confirm_operation(panel):
        token = panel._pending_bcon_operation["token"]
        panel._handle_bcon_operation_event("operation_sent", {"token": token})
        panel._handle_bcon_operation_event("operation_result", {
            "operation_token": token,
            "accepted": True,
            "last_command_result": "EXECUTED",
        })

    def test_disabling_active_beam_waits_for_polled_channel_off(self):
        beam_pulse = FakeBeamPulse(output_on=True, channel_off_result=True)
        panel = self.make_panel(beam_pulse)

        panel._toggle_beam_software_interlock(0)

        self.assertEqual(beam_pulse.channel_off_calls, [0])
        self.assertEqual(panel._beam_software_interlock_states, [True, False, False])
        self.assertEqual(panel.software_interlock_buttons[0].cget("state"), "normal")
        self.assertEqual(panel.software_interlock_buttons[0].cget("text"), "Beam A Enabled")

        self.confirm_operation(panel)
        panel._on_channel_status_update(0, 0, 0, {"output_level": 0})
        panel._handle_bcon_operation_event("operation_poll", {})

        self.assertEqual(panel._beam_software_interlock_states, [False, False, False])
        self.assertEqual(panel.software_interlock_buttons[0].cget("state"), "normal")
        self.assertEqual(panel.software_interlock_buttons[0].cget("text"), "Beam A Disabled")
        self.assertIn(
            "Beam A software interlock disabled after output confirmed OFF",
            panel.infos,
        )

    def test_failed_channel_off_keeps_active_beam_interlock_enabled(self):
        beam_pulse = FakeBeamPulse(output_on=True, channel_off_result=False)
        panel = self.make_panel(beam_pulse)

        panel._toggle_beam_software_interlock(0)

        self.assertEqual(beam_pulse.channel_off_calls, [0])
        self.assertEqual(panel._beam_software_interlock_states, [True, False, False])
        self.assertIn("Failed to request", panel.status_updates[-1][0])

    def test_missing_beam_status_fails_closed(self):
        beam_pulse = BeamPulseWithoutStatus()
        panel = self.make_panel(beam_pulse)

        panel._toggle_beam_software_interlock(0)

        self.assertEqual(panel._beam_software_interlock_states, [True, False, False])
        self.assertEqual(beam_pulse.channel_off_calls, [])
        self.assertIn("output status unavailable", panel.status_updates[-1][0])
        self.assertIn("Beam Pulse status API is unavailable", panel.errors[-1])

    def test_nonzero_output_does_not_complete_pending_stop(self):
        beam_pulse = FakeBeamPulse(output_on=True)
        panel = self.make_panel(beam_pulse)

        panel._toggle_beam_software_interlock(0)
        self.confirm_operation(panel)
        panel._on_channel_status_update(0, 0, 0, {"output_level": 1})
        panel._handle_bcon_operation_event("operation_poll", {})

        self.assertEqual(panel._beam_software_interlock_states, [True, False, False])
        self.assertEqual(panel.software_interlock_buttons[0].cget("state"), "normal")

    def test_ack_timeout_keeps_interlock_enabled(self):
        beam_pulse = FakeBeamPulse(output_on=True)
        panel = self.make_panel(beam_pulse)

        panel._toggle_beam_software_interlock(0)
        token = panel._pending_bcon_operation["token"]
        panel._handle_bcon_operation_event("operation_sent", {"token": token})
        panel._expire_bcon_operation(token, "ack")

        self.assertEqual(panel._beam_software_interlock_states, [True, False, False])
        self.assertIn("timed out", panel.status_updates[-1][0])
        self.assertIn("timed out", panel.errors[-1])

    def test_disabling_inactive_beam_does_not_send_all_off(self):
        beam_pulse = FakeBeamPulse(output_on=False)
        panel = self.make_panel(beam_pulse)

        panel._toggle_beam_software_interlock(0)

        self.assertEqual(beam_pulse.channel_off_calls, [])
        self.assertEqual(panel._beam_software_interlock_states, [False, False, False])
        self.assertIn("Beam A software interlock disabled", panel.infos)

    def test_enabling_beam_logs_software_interlock_transition(self):
        beam_pulse = FakeBeamPulse(output_on=False)
        panel = self.make_panel(beam_pulse)

        panel._toggle_beam_software_interlock(1)

        self.assertEqual(panel._beam_software_interlock_states, [True, True, False])
        self.assertIn("Beam B software interlock enabled", panel.infos)

    def test_ack_poll_deadline_starts_when_the_command_is_sent(self):
        panel = self.make_panel(FakeBeamPulse())
        panel.root = FakeRoot()

        with patch("subsystem.main_control.main_control.time.monotonic", return_value=100.25):
            token = panel._start_bcon_operation("Beam A ON", (0,))
            panel._handle_bcon_operation_event(
                "operation_sent", {"token": token, "sent_at": 100.0}
            )

        self.assertEqual(panel.root.calls[-1][0], 750)

    def test_disconnect_terminates_pending_operation_immediately(self):
        panel = self.make_panel(FakeBeamPulse())
        panel.disable_ccs_output_on_bcon_disconnect = False
        token = panel._start_bcon_operation("Beam A ON", (0,))

        panel._handle_bcon_disconnected()

        self.assertIsNone(panel._pending_bcon_operation)
        self.assertIn(token, panel.errors[-1])
        self.assertIn("terminated by BCON disconnect", panel.errors[-1])


if __name__ == "__main__":
    unittest.main()
