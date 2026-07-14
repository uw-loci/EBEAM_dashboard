import pandas as pd
import pytest
import shutil

from subsystem.cathode_heating.cathode_heating import CathodeHeatingSubsystem


RAW_LUT_PATH = "data/lut/power_supply/Cbmark_Beam_A_07_2025.csv"
GENERATED_ROOT = "data/lut/power_supply/generated"
LUT_FILENAME = "Cbmark_Beam_A_07_2025.csv"


class DummyVar:
    def __init__(self):
        self.value = None

    def set(self, value):
        self.value = value


@pytest.fixture
def prediction_model():
    model = CathodeHeatingSubsystem.__new__(CathodeHeatingSubsystem)
    model.lookup_table_setting = [
        {
            "current_lut": pd.read_csv(f"{GENERATED_ROOT}/current/{LUT_FILENAME}"),
            "voltage_lut": pd.read_csv(f"{GENERATED_ROOT}/voltage/{LUT_FILENAME}"),
            "iv_curve": pd.read_csv(f"{GENERATED_ROOT}/iv/{LUT_FILENAME}"),
        }
    ]
    model.selected_lut_files = [LUT_FILENAME]
    model.log = lambda *args, **kwargs: None
    model.voltage_set = [False]
    model.current_set = [False]
    model.user_set_voltages = [None]
    model.user_set_currents = [None]
    model.ideal_cathode_emission_currents = [None]
    model.predicted_emission_current_vars = [DummyVar()]
    model.predicted_grid_current_vars = [DummyVar()]
    model.predicted_heater_current_vars = [DummyVar()]
    model.predicted_heater_voltage_vars = [DummyVar()]
    model.predicted_temperature_vars = [DummyVar()]
    return model


def test_lut_remains_authoritative_at_boundary(prediction_model):
    voltage, heater_current, beam_current = prediction_model.emission_cur_vlt_converter(
        0,
        0.81,
        target_heater_current=6.03,
        controlling_mode="current",
    )

    assert voltage == pytest.approx(0.81)
    assert heater_current == pytest.approx(6.03)
    assert beam_current == pytest.approx(5.111)


def test_current_control_maps_heater_current_directly_to_beam_current(
    prediction_model,
):
    heater_current = 5.8734
    heater_voltage = prediction_model._voltage_for_current(0, heater_current)

    _, resolved_current, beam_current = prediction_model.emission_cur_vlt_converter(
        0,
        heater_voltage,
        target_heater_current=heater_current,
        controlling_mode="current",
    )

    assert resolved_current == pytest.approx(heater_current)
    assert beam_current == pytest.approx(4.118680)


def test_voltage_control_retains_voltage_to_beam_current_mapping(prediction_model):
    heater_voltage = 0.80
    heater_current = prediction_model._current_for_voltage(0, heater_voltage)

    _, resolved_current, beam_current = prediction_model.emission_cur_vlt_converter(
        0,
        heater_voltage,
        target_heater_current=heater_current,
        controlling_mode="voltage",
    )

    assert resolved_current == pytest.approx(heater_current)
    assert resolved_current == pytest.approx(5.8454651)
    assert beam_current == pytest.approx(5.109)


def test_canonical_inverse_uses_highest_current_on_exact_voltage_plateau(
    prediction_model,
):
    assert prediction_model._current_for_voltage(0, 0.808298) == pytest.approx(6.10)


def test_direct_current_lookup_uses_current_keyed_max_beam_row(
    prediction_model,
):
    heater_current = 4.88
    heater_voltage = prediction_model._voltage_for_current(0, heater_current)

    _, _, beam_current = prediction_model.emission_cur_vlt_converter(
        0,
        heater_voltage,
        target_heater_current=heater_current,
        controlling_mode="current",
    )

    assert beam_current == pytest.approx(0.05)


def test_current_update_publishes_direct_current_lookup_prediction(
    prediction_model,
):
    assert prediction_model.update_predictions_from_current(0, 5.8734)

    assert prediction_model.ideal_cathode_emission_currents[0] == pytest.approx(
        4.118680 / prediction_model.BEAM_CURRENT_FRACTION_OF_EMISSION
    )


def test_corrected_physical_iv_model_is_continuous_above_current_boundary(
    prediction_model,
):
    assert prediction_model._voltage_for_current(0, 6.10) == pytest.approx(0.808298)
    assert prediction_model._voltage_for_current(0, 6.11) == pytest.approx(
        0.8096969772
    )


def test_current_control_uses_temperature_corrected_fallback(prediction_model):
    heater_current = 6.11
    heater_voltage = prediction_model._voltage_for_current(0, heater_current)

    fallback = prediction_model._richardson_fallback_beam_current_ma(
        0,
        heater_voltage,
        target_heater_current=heater_current,
        controlling_mode="current",
    )

    assert fallback["control_mode"] == "current"
    assert fallback["model_heater_current"] == pytest.approx(heater_current)
    assert fallback["temperature_k"] == pytest.approx(1560.7128403)
    assert fallback["beam_current_ma"] == pytest.approx(7.1875501)


def test_voltage_control_uses_internal_voltage_corrected_fallback(prediction_model):
    heater_voltage = 0.83
    physical_current = prediction_model._current_for_voltage(0, heater_voltage)

    fallback = prediction_model._richardson_fallback_beam_current_ma(
        0,
        heater_voltage,
        target_heater_current=physical_current,
        controlling_mode="voltage",
    )

    assert fallback["control_mode"] == "voltage"
    assert fallback["heater_current"] == pytest.approx(6.2597896)
    assert fallback["model_heater_current"] == pytest.approx(8.6015279)
    assert fallback["beam_current_ma"] == pytest.approx(5.8757980)


def test_unconfigured_dataset_uses_zero_offsets(prediction_model):
    prediction_model.selected_lut_files[0] = "Future_Uncalibrated_LUT.csv"

    calibration = prediction_model._prediction_model_calibration(0)

    assert calibration == prediction_model.PREDICTION_MODEL_DEFAULT_CALIBRATION


def test_voltage_limit_selects_voltage_correction_during_current_update(
    prediction_model,
):
    prediction_model.voltage_set[0] = True
    prediction_model.user_set_voltages[0] = 0.83

    assert prediction_model.update_predictions_from_current(0, 6.50)

    assert prediction_model.predicted_heater_voltage_vars[0].value == "0.83 V"
    assert prediction_model.predicted_heater_current_vars[0].value == "6.26 A"
    assert prediction_model.ideal_cathode_emission_currents[0] == pytest.approx(
        5.8757980 / prediction_model.BEAM_CURRENT_FRACTION_OF_EMISSION
    )


def test_current_limit_selects_current_correction_during_voltage_update(
    prediction_model,
):
    prediction_model.current_set[0] = True
    prediction_model.user_set_currents[0] = 6.11

    assert prediction_model.update_predictions_from_voltage(0, 0.90)

    assert prediction_model.predicted_heater_voltage_vars[0].value == "0.81 V"
    assert prediction_model.predicted_heater_current_vars[0].value == "6.11 A"
    assert prediction_model.ideal_cathode_emission_currents[0] == pytest.approx(
        7.1875501 / prediction_model.BEAM_CURRENT_FRACTION_OF_EMISSION
    )


def test_both_entry_paths_resolve_the_same_binding_mode(prediction_model):
    prediction_model.voltage_set[0] = True
    prediction_model.user_set_voltages[0] = 0.80
    assert prediction_model.update_predictions_from_current(0, 5.90)
    current_entry_prediction = prediction_model.ideal_cathode_emission_currents[0]

    prediction_model.current_set[0] = True
    prediction_model.user_set_currents[0] = 5.90
    assert prediction_model.update_predictions_from_voltage(0, 0.80)
    voltage_entry_prediction = prediction_model.ideal_cathode_emission_currents[0]

    assert current_entry_prediction == pytest.approx(voltage_entry_prediction)
    assert prediction_model.predicted_heater_voltage_vars[0].value == "0.80 V"
    assert prediction_model.predicted_heater_current_vars[0].value == "5.85 A"


def test_loader_validates_generated_bundle(prediction_model):
    bundle = prediction_model._load_lut_bundle(RAW_LUT_PATH, GENERATED_ROOT)

    assert prediction_model._is_valid_lut_bundle(bundle)
    assert len(bundle["current_lut"]) == 100
    assert len(bundle["voltage_lut"]) == 20
    assert len(bundle["iv_curve"]) == 100


def test_loader_rejects_bundle_after_raw_data_changes(prediction_model, tmp_path):
    raw_copy = tmp_path / LUT_FILENAME
    generated_copy = tmp_path / "generated"
    shutil.copy2(RAW_LUT_PATH, raw_copy)
    shutil.copytree(GENERATED_ROOT, generated_copy)
    raw_copy.write_text(raw_copy.read_text() + "\n")

    with pytest.raises(ValueError, match="stale"):
        prediction_model._load_lut_bundle(raw_copy, generated_copy)
