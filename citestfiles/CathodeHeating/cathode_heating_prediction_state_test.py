import math
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from subsystem.cathode_heating.cathode_heating import CathodeHeatingSubsystem


class FakeVar:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class CathodeHeatingPredictionStateTest(unittest.TestCase):
    def make_subsystem(self):
        subsystem = object.__new__(CathodeHeatingSubsystem)
        subsystem.ideal_cathode_emission_currents = [None, None, None]
        subsystem.predicted_emission_current_vars = [FakeVar("--") for _ in range(3)]
        return subsystem

    def test_cleared_prediction_returns_none_and_displays_unknown(self):
        subsystem = self.make_subsystem()
        subsystem._set_predicted_emission_current_ma(0, 1.25)

        subsystem._set_predicted_emission_current_ma(0)

        self.assertEqual(subsystem.predicted_emission_current_vars[0].get(), "--")
        self.assertEqual(subsystem.get_predicted_emission_currents_ma(), [None, None, None])

    def test_real_zero_prediction_is_preserved(self):
        subsystem = self.make_subsystem()

        subsystem._set_predicted_emission_current_ma(0, 0.0)

        self.assertEqual(subsystem.predicted_emission_current_vars[0].get(), "0.00 mA")
        self.assertEqual(subsystem.get_predicted_emission_currents_ma(), [0.0, None, None])

    def test_invalid_predictions_return_none(self):
        invalid_values = ["bad", math.nan, math.inf, -0.1]
        for value in invalid_values:
            with self.subTest(value=value):
                subsystem = self.make_subsystem()

                subsystem._set_predicted_emission_current_ma(0, value)

                self.assertEqual(subsystem.predicted_emission_current_vars[0].get(), "--")
                self.assertEqual(subsystem.get_predicted_emission_currents_ma()[0], None)


if __name__ == "__main__":
    unittest.main()
