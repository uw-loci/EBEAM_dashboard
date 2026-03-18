import csv
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data.lut.clean import (
    clean_beam_control_file,
    clean_power_supply_file,
    discover_raw_file_pairs,
    fill_missing_voltages,
)


def test_discover_raw_file_pairs_filters_and_strips_prefix(tmp_path):
    raw_dir = tmp_path / "raw_files"
    raw_dir.mkdir()

    (raw_dir / "raw_cathodeA.csv").write_text("", encoding="utf-8")
    (raw_dir / "raw_default.csv").write_text("", encoding="utf-8")
    (raw_dir / "cathodeB.csv").write_text("", encoding="utf-8")
    (raw_dir / "raw_notes.txt").write_text("", encoding="utf-8")
    (raw_dir / "raw_.csv").write_text("", encoding="utf-8")

    pairs = discover_raw_file_pairs(str(raw_dir))

    assert pairs == [
        ("raw_cathodeA.csv", "cathodeA.csv"),
        ("raw_default.csv", "default.csv"),
    ]


def test_fill_missing_voltages_all_missing_leaves_rows_unchanged():
    rows = [
        {"beam_current": "1.000", "voltage": "", "heater_current": "6.00"},
        {"beam_current": "1.250", "voltage": "", "heater_current": "6.10"},
    ]

    result = fill_missing_voltages(rows)

    assert result == rows
    assert all(row["voltage"] == "" for row in result)


def test_fill_missing_voltages_skips_non_numeric_heater_current():
    rows = [
        {"beam_current": "2.000", "voltage": "0.80", "heater_current": "6.00"},
        {"beam_current": "2.100", "voltage": "", "heater_current": "not-a-number"},
        {"beam_current": "2.200", "voltage": "", "heater_current": "6.08"},
    ]

    result = fill_missing_voltages(rows)

    assert result[1]["voltage"] == ""
    assert result[2]["voltage"] == "0.80"


def test_fill_missing_voltages_uses_nearest_known_heater_current():
    rows = [
        {"beam_current": "3.000", "voltage": "0.70", "heater_current": "5.00"},
        {"beam_current": "3.200", "voltage": "0.90", "heater_current": "6.00"},
        {"beam_current": "3.100", "voltage": "", "heater_current": "5.80"},
    ]

    result = fill_missing_voltages(rows)

    assert result[2]["voltage"] == "0.90"


def test_clean_power_supply_file_with_all_missing_voltage_does_not_crash(tmp_path):
    raw_path = tmp_path / "raw_missing_voltage.csv"
    clean_path = tmp_path / "clean_missing_voltage.csv"

    with raw_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["beam_current", "voltage", "heater_current"])
        writer.writeheader()
        writer.writerow({"beam_current": "1.0", "voltage": "", "heater_current": "6.00"})
        writer.writerow({"beam_current": "1.2", "voltage": "", "heater_current": "6.00"})

    rows = clean_power_supply_file(str(raw_path), str(clean_path))

    assert clean_path.exists()
    assert len(rows) == 1
    assert rows[0]["heater_current"] == "6.00"
    assert rows[0]["voltage"] == ""


def test_clean_beam_control_file_raises_on_missing_required_columns(tmp_path):
    raw_path = tmp_path / "raw_bd_bad.csv"
    clean_path = tmp_path / "bd_bad.csv"

    with raw_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["current_amplitude_A", "wrong_col"])
        writer.writeheader()
        writer.writerow({"current_amplitude_A": "0.5", "wrong_col": "1.2"})

    with pytest.raises(ValueError, match="missing required columns"):
        clean_beam_control_file(str(raw_path), str(clean_path), file_type="deflection")


def test_clean_beam_control_file_raises_on_non_numeric_values(tmp_path):
    raw_path = tmp_path / "raw_ss_bad.csv"
    clean_path = tmp_path / "ss_bad.csv"

    with raw_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["frequency_hz", "scan_speed_mps"])
        writer.writeheader()
        writer.writerow({"frequency_hz": "abc", "scan_speed_mps": "2.3"})

    with pytest.raises(ValueError, match="non-numeric value"):
        clean_beam_control_file(str(raw_path), str(clean_path), file_type="scan_speed")


def test_clean_beam_control_file_infers_type_from_headers_when_not_provided(tmp_path):
    raw_path = tmp_path / "raw_custom.csv"
    clean_path = tmp_path / "custom.csv"

    with raw_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["current_amplitude_A", "deflection_cm"])
        writer.writeheader()
        writer.writerow({"current_amplitude_A": "0.5", "deflection_cm": "1.2"})

    rows = clean_beam_control_file(str(raw_path), str(clean_path), file_type=None)

    assert len(rows) == 1
    assert clean_path.exists()
