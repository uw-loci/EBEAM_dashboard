import csv
import hashlib
import json
from pathlib import Path

import pytest

from data.lut import clean


RAW_LUT = Path("data/lut/power_supply/Cbmark_Beam_A_07_2025.csv")


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def test_generation_preserves_raw_and_writes_complete_bundle(tmp_path):
    before = _sha256(RAW_LUT)

    result = clean.generate_power_supply_artifacts(RAW_LUT, tmp_path)

    assert _sha256(RAW_LUT) == before
    assert len(result["current_rows"]) == 100
    assert len(result["voltage_rows"]) == 20
    assert len(result["iv_rows"]) == 100
    assert all(Path(path).is_file() for path in result["paths"].values())

    manifest = json.loads(Path(result["paths"]["manifest"]).read_text())
    assert manifest["source"]["sha256"] == before
    for name in ("current_lut", "voltage_lut", "iv_curve"):
        assert manifest["artifacts"][name]["sha256"] == _sha256(
            result["paths"][name]
        )

    first_bundle_hashes = {
        name: _sha256(path) for name, path in result["paths"].items()
    }
    second_result = clean.generate_power_supply_artifacts(RAW_LUT, tmp_path)
    assert {
        name: _sha256(path) for name, path in second_result["paths"].items()
    } == first_bundle_hashes


def test_current_and_voltage_luts_use_their_own_max_beam_bins(tmp_path):
    result = clean.generate_power_supply_artifacts(RAW_LUT, tmp_path)

    current_rows = {
        float(row["heater_current"]): row for row in result["current_rows"]
    }
    voltage_rows = {float(row["voltage"]): row for row in result["voltage_rows"]}

    assert float(current_rows[5.94]["beam_current"]) == pytest.approx(5.106)
    assert float(current_rows[5.94]["voltage"]) == pytest.approx(0.80)
    assert float(voltage_rows[0.81]["beam_current"]) == pytest.approx(5.111)
    assert float(voltage_rows[0.81]["heater_current"]) == pytest.approx(6.03)


def test_canonical_iv_curve_is_beam_independent_and_monotonic(tmp_path):
    result = clean.generate_power_supply_artifacts(RAW_LUT, tmp_path)
    with open(result["paths"]["iv_curve"], newline="") as stream:
        rows = list(csv.DictReader(stream))

    currents = [float(row["heater_current"]) for row in rows]
    voltages = [float(row["voltage"]) for row in rows]
    assert currents == sorted(set(currents))
    assert all(current >= previous for previous, current in zip(voltages, voltages[1:]))
    assert set(rows[0]) == {
        "heater_current",
        "voltage",
        "raw_median_voltage",
        "sample_count",
    }


def test_weighted_isotonic_fit_pools_adjacent_reversals():
    fitted = clean._weighted_isotonic_non_decreasing(
        [0.60, 0.62, 0.61, 0.64],
        [1, 1, 1, 1],
    )

    assert fitted == pytest.approx([0.60, 0.615, 0.615, 0.64])
