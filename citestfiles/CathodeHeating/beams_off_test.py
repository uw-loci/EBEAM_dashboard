import sys, os, unittest
from unittest.mock import MagicMock

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from subsystem.cathode_heating.cathode_heating import CathodeHeatingSubsystem
from utils import LogLevel

class TestBeamsOff(unittest.TestCase):
    def setUp(self):
        # Bypass __init__ to avoid Tk and image loading
        self.subsys = object.__new__(CathodeHeatingSubsystem)
        # Inject only what turn_off_all_beams uses
        self.subsys.power_supplies_initialized = True
        self.subsys.power_supplies = [MagicMock(), None, MagicMock()]
        self.subsys.power_supply_status = [True, False, True]
        self.subsys.toggle_states = [True, True, True]
        self.subsys.toggle_off_image = object()
        self.subsys.toggle_buttons = [MagicMock(), MagicMock(), MagicMock()]
        # Simple logger hook
        self.subsys.logger = MagicMock()
        self.subsys.log = lambda msg, lvl=LogLevel.INFO: None

        # Alias method under test (name in your file)
        self.turn_off_all_beams = self.subsys.turn_off_all_beams

    def test_turns_off_only_initialized_ps_and_updates_ui_on_success(self):
        # First and third supply return True; middle is uninitialized
        self.subsys.power_supplies[0].set_output.return_value = True
        self.subsys.power_supplies[2].set_output.return_value = True

        self.turn_off_all_beams()

        self.subsys.power_supplies[0].set_output.assert_called_once_with("0")
        self.subsys.power_supplies[2].set_output.assert_called_once_with("0")
        self.assertFalse(self.subsys.toggle_states[0])
        self.assertFalse(self.subsys.toggle_states[2])
        self.subsys.toggle_buttons[0].config.assert_called_once()
        self.subsys.toggle_buttons[2].config.assert_called_once()
        # Uninitialized index 1 untouched
        self.subsys.toggle_buttons[1].config.assert_not_called()

    def test_does_not_update_ui_when_off_fails(self):
        # Simulate failure on index 0, success on index 2
        self.subsys.power_supplies[0].set_output.return_value = False
        self.subsys.power_supplies[2].set_output.return_value = True

        self.turn_off_all_beams()

        # UI should not change for failed OFF
        self.assertTrue(self.subsys.toggle_states[0])
        self.subsys.toggle_buttons[0].config.assert_not_called()

        # UI should change for successful OFF
        self.assertFalse(self.subsys.toggle_states[2])
        self.subsys.toggle_buttons[2].config.assert_called_once()

    def test_exceptions_are_caught_and_others_continue(self):
        self.subsys.power_supplies[0].set_output.side_effect = RuntimeError("boom")
        self.subsys.power_supplies[2].set_output.return_value = True

        # Should not raise
        self.turn_off_all_beams()

        self.subsys.power_supplies[2].set_output.assert_called_once_with("0")
        self.assertFalse(self.subsys.toggle_states[2])

if __name__ == '__main__':
    unittest.main()