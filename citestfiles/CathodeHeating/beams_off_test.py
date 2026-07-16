import sys, os, unittest
from unittest.mock import MagicMock

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from subsystem.cathode_heating.cathode_heating import CathodeHeatingSubsystem
from utils import LogLevel

class TestBeamsOff(unittest.TestCase):
    def make_power_supply(self, disable_result=True, set_result=True, has_disable=True):
        methods = ['set_output', 'stop_ramp']
        if has_disable:
            methods.append('disable_output')
        ps = MagicMock(spec=methods)
        ps.set_output.return_value = set_result
        ps.stop_ramp.return_value = None
        if has_disable:
            ps.disable_output.return_value = disable_result
        return ps

    def make_warning_widgets(self):
        return [[MagicMock(), MagicMock()] for _ in range(3)]

    def install_measured_output_warning_state(self):
        self.subsys.measured_output_warning_since = {
            "voltage": [object(), object(), object()],
            "current": [object(), object(), object()],
        }
        self.subsys.measured_output_warning_active = {
            "voltage": [True, True, True],
            "current": [True, True, True],
        }
        self.subsys.measured_output_warning_logged = {
            "voltage": [True, True, True],
            "current": [True, True, True],
        }
        self.subsys.actual_heater_voltage_box_widgets = self.make_warning_widgets()
        self.subsys.actual_heater_current_box_widgets = self.make_warning_widgets()

    def assert_measured_output_warning_cleared(self, index):
        for measurement_type in ("voltage", "current"):
            self.assertIsNone(
                self.subsys.measured_output_warning_since[measurement_type][index]
            )
            self.assertFalse(
                self.subsys.measured_output_warning_active[measurement_type][index]
            )
            self.assertFalse(
                self.subsys.measured_output_warning_logged[measurement_type][index]
            )

    def setUp(self):
        # Bypass __init__ to avoid Tk and image loading
        self.subsys = object.__new__(CathodeHeatingSubsystem)
        # Inject only what turn_off_all_beams uses
        self.subsys.power_supplies_initialized = True
        self.subsys.power_supplies = [self.make_power_supply(), None, self.make_power_supply()]
        self.subsys.power_supply_status = [True, False, True]
        self.subsys.toggle_states = [True, False, True]
        self.subsys.toggle_off_image = object()
        self.subsys.toggle_buttons = [MagicMock(), MagicMock(), MagicMock()]
        # Simple logger hook
        self.subsys.logger = MagicMock()
        self.subsys.log = lambda msg, lvl=LogLevel.INFO: None
        self.install_measured_output_warning_state()

        # Alias method under test (name in your file)
        self.turn_off_all_beams = self.subsys.turn_off_all_beams

    def test_turns_off_available_ps_handles_and_updates_ui_on_success(self):
        self.assertTrue(self.turn_off_all_beams())

        self.subsys.power_supplies[0].disable_output.assert_called_once_with()
        self.subsys.power_supplies[2].disable_output.assert_called_once_with()
        self.subsys.power_supplies[0].set_output.assert_not_called()
        self.subsys.power_supplies[2].set_output.assert_not_called()
        self.assertFalse(self.subsys.toggle_states[0])
        self.assertFalse(self.subsys.toggle_states[2])
        self.subsys.toggle_buttons[0].config.assert_called_once()
        self.subsys.toggle_buttons[2].config.assert_called_once()
        self.assert_measured_output_warning_cleared(0)
        self.assert_measured_output_warning_cleared(2)
        # Uninitialized index 1 untouched
        self.subsys.toggle_buttons[1].config.assert_not_called()

    def test_does_not_update_ui_when_off_fails(self):
        # Simulate failure on index 0, success on index 2
        self.subsys.power_supplies[0].disable_output.return_value = False

        self.assertFalse(self.turn_off_all_beams())

        # UI should not change for failed OFF
        self.assertTrue(self.subsys.toggle_states[0])
        self.subsys.toggle_buttons[0].config.assert_not_called()

        # UI should change for successful OFF
        self.assertFalse(self.subsys.toggle_states[2])
        self.subsys.toggle_buttons[2].config.assert_called_once()

    def test_exceptions_are_caught_and_others_continue(self):
        self.subsys.power_supplies[0].disable_output.side_effect = RuntimeError("boom")

        # Should not raise
        self.assertFalse(self.turn_off_all_beams())

        self.subsys.power_supplies[2].disable_output.assert_called_once_with()
        self.assertFalse(self.subsys.toggle_states[2])

    def test_attempts_available_handles_even_when_not_marked_initialized(self):
        # Arrange: pretend readback/status tracking says nothing is initialized
        self.subsys.power_supplies_initialized = False
        self.subsys.power_supplies = [
            self.make_power_supply(),
            self.make_power_supply(),
            self.make_power_supply(),
        ]
        self.subsys.power_supply_status = [False, False, False]

        # Act
        self.assertTrue(self.turn_off_all_beams())

        # Assert: E-stop path still tries every existing handle
        for ps in self.subsys.power_supplies:
            ps.disable_output.assert_called_once_with()

    def test_returns_early_when_power_supply_list_empty(self):
        self.subsys.power_supplies = []
        self.subsys.power_supplies_initialized = False

        self.assertFalse(self.turn_off_all_beams())

        for btn in self.subsys.toggle_buttons:
            btn.config.assert_not_called()

    def test_does_not_skip_existing_handle_when_status_false(self):
        # Arrange: ps exists but status is False due to a readback failure
        self.subsys.power_supplies = [
            self.make_power_supply(),
            self.make_power_supply(),
            self.make_power_supply(),
        ]
        self.subsys.power_supply_status = [True, False, True]

        # Act
        self.assertTrue(self.turn_off_all_beams())

        # Assert
        self.subsys.power_supplies[1].disable_output.assert_called_once_with()
        self.assertFalse(self.subsys.toggle_states[1])

    def test_updates_button_with_correct_image_on_success(self):
        # Act
        self.assertTrue(self.turn_off_all_beams())

        # Assert exact image argument used
        self.subsys.toggle_buttons[0].config.assert_called_once_with(image=self.subsys.toggle_off_image)
        self.subsys.toggle_buttons[2].config.assert_called_once_with(image=self.subsys.toggle_off_image)

    def test_true_status_but_none_power_supply_is_safely_skipped(self):
        # Arrange: ps None but status True for index 1
        self.subsys.power_supplies = [self.make_power_supply(), None, self.make_power_supply()]
        self.subsys.power_supply_status = [True, True, True]

        # Act (should not raise)
        self.assertTrue(self.turn_off_all_beams())

        # Assert: others still called, middle skipped
        self.subsys.power_supplies[0].disable_output.assert_called_once_with()
        self.subsys.power_supplies[2].disable_output.assert_called_once_with()

        # Button 1 should not be touched since ps is None
        self.subsys.toggle_buttons[1].config.assert_not_called()

    def test_returns_false_when_active_cathode_has_no_power_supply_handle(self):
        self.subsys.toggle_states = [False, True, False]

        self.assertFalse(self.turn_off_all_beams())

    def test_second_call_is_idempotent_and_keeps_off_state(self):
        # Act: call twice
        self.assertTrue(self.turn_off_all_beams())
        self.assertTrue(self.turn_off_all_beams())

        # Assert: disable_output called twice for available handles
        self.assertEqual(self.subsys.power_supplies[0].disable_output.call_count, 2)
        self.assertEqual(self.subsys.power_supplies[2].disable_output.call_count, 2)
        # State remains off
        self.assertFalse(self.subsys.toggle_states[0])
        self.assertFalse(self.subsys.toggle_states[2])

    def test_falls_back_to_set_output_when_disable_output_is_unavailable(self):
        self.subsys.power_supplies = [
            self.make_power_supply(has_disable=False),
            None,
            self.make_power_supply(has_disable=False),
        ]

        self.assertTrue(self.turn_off_all_beams())

        self.subsys.power_supplies[0].set_output.assert_called_once_with("0")
        self.subsys.power_supplies[2].set_output.assert_called_once_with("0")

if __name__ == '__main__':
    unittest.main()
