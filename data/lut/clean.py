import csv
import os
import argparse
import matplotlib.pyplot as plt
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

POWER_SUPPLY_RAW_DIR = os.path.join(BASE_DIR, "power_supply", "raw_files")
POWER_SUPPLY_PLOT_DIR = os.path.join(BASE_DIR, "power_supply", "plots")
POWER_SUPPLY_OUTPUT_DIR = os.path.join(BASE_DIR, "power_supply")

BEAM_CONTROL_RAW_DIR = os.path.join(BASE_DIR, "beam_control", "raw_files")
BEAM_CONTROL_PLOT_DIR = os.path.join(BASE_DIR, "beam_control", "plots")
BEAM_CONTROL_OUTPUT_DIR = os.path.join(BASE_DIR, "beam_control")

RAW_PREFIX = "raw_"

def read_csv(filename):
    with open(filename, newline="") as f:
        reader = csv.DictReader(f)
        rows = [row for row in reader]
    return rows

def write_csv(filename, rows):
    with open(filename, "w", newline="") as f:
        fieldnames = ["beam_current", "voltage", "heater_current"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

def average_duplicates(rows):
    grouped = defaultdict(list)
    for row in rows:
        hc = row["heater_current"]
        if hc:
            grouped[hc].append(row)
    result = []
    for hc, group in grouped.items():
        beam_vals = [float(r["beam_current"]) for r in group if r["beam_current"]]
        volt_vals = [float(r["voltage"]) for r in group if r["voltage"]]
        avg_beam = sum(beam_vals)/len(beam_vals) if beam_vals else ""
        avg_volt = sum(volt_vals)/len(volt_vals) if volt_vals else ""
        result.append({
            "beam_current": f"{avg_beam:.3f}" if avg_beam != "" else "",
            "voltage": f"{avg_volt:.2f}" if avg_volt != "" else "",
            "heater_current": hc
        })
    return result

def fill_missing_voltages(rows):
    hc_to_volt = {float(r["heater_current"]): float(r["voltage"]) for r in rows if r["voltage"]}
    # If there are no known voltages to infer from, leave rows unchanged.
    if not hc_to_volt:
        return rows
    for row in rows:
        if not row["voltage"]:
            try:
                hc = float(row["heater_current"])
            except (ValueError, TypeError):
                # Skip rows with non-numeric or missing heater_current values.
                continue
            nearest = min(hc_to_volt.keys(), key=lambda x: abs(x-hc))
            row["voltage"] = f"{hc_to_volt[nearest]:.2f}"
    return rows

def clean_power_supply_file(raw_path, clean_path):
    rows = read_csv(raw_path)
    rows = average_duplicates(rows)
    rows = fill_missing_voltages(rows)
    write_csv(clean_path, rows)
    return rows


def discover_raw_file_pairs(raw_dir):
    """Return (raw_name, clean_name) for files named raw_*.csv in raw_dir."""
    if not os.path.isdir(raw_dir):
        return []

    file_pairs = []
    for name in sorted(os.listdir(raw_dir), key=str.lower):
        lower_name = name.lower()
        if not lower_name.endswith(".csv"):
            continue
        if not lower_name.startswith(RAW_PREFIX):
            continue

        clean_name = name[len(RAW_PREFIX):]
        clean_stem, clean_ext = os.path.splitext(clean_name)
        if not clean_name or clean_ext.lower() != ".csv" or not clean_stem:
            continue
        file_pairs.append((name, clean_name))

    return file_pairs

def plot_power_supply_graphs(rows, name, plot_dir):
    beam = [float(r["beam_current"]) for r in rows if r["beam_current"] and r["voltage"] and r["heater_current"]]
    volt = [float(r["voltage"]) for r in rows if r["beam_current"] and r["voltage"] and r["heater_current"]]
    heater = [float(r["heater_current"]) for r in rows if r["beam_current"] and r["voltage"] and r["heater_current"]]
    if not os.path.exists(plot_dir):
        os.makedirs(plot_dir)
    # Plot voltage vs beam current (X: voltage, Y: beam current)
    plt.figure()
    plt.plot(volt, beam, marker='o')
    plt.xlabel('Voltage')
    plt.ylabel('Beam Current')
    plt.title(f'{name}: Beam Current vs Voltage')
    plt.grid(True)
    plt.savefig(os.path.join(plot_dir, f'{name}_beam_vs_voltage.png'))
    plt.close()
    # Plot heater current vs beam current (X: heater current, Y: beam current)
    plt.figure()
    plt.plot(heater, beam, marker='o')
    plt.xlabel('Heater Current')
    plt.ylabel('Beam Current')
    plt.title(f'{name}: Beam Current vs Heater Current')
    plt.grid(True)
    plt.savefig(os.path.join(plot_dir, f'{name}_beam_vs_heater.png'))
    plt.close()

def process_power_supply_data():
    print("Processing power supply data...")
    file_pairs = discover_raw_file_pairs(POWER_SUPPLY_RAW_DIR)
    if not file_pairs:
        print("Power Supply: No raw CSV files found matching raw_*.csv")
        return

    for raw_name, clean_name in file_pairs:
        raw_path = os.path.join(POWER_SUPPLY_RAW_DIR, raw_name)
        rows = clean_power_supply_file(raw_path, raw_path)
        plot_name = clean_name.replace('.csv', '')
        plot_power_supply_graphs(rows, plot_name, POWER_SUPPLY_PLOT_DIR)

    print(f"Power Supply: Processed {len(file_pairs)} files and generated plots.")

def read_beam_control_csv(filename):
    """Read beam control CSV files (already in final format)."""
    with open(filename, newline="") as f:
        reader = csv.DictReader(f)
        rows = [row for row in reader]
    return rows

def write_beam_control_csv(filename, rows, columns):
    """Write beam control CSV files."""
    with open(filename, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _normalize_beam_control_type(file_type):
    """Normalize beam-control type aliases to canonical values."""
    if not file_type:
        return None
    ft = str(file_type).strip().lower()
    if ft in ("deflection", "beam_deflection", "bd"):
        return "deflection"
    if ft in ("scan_speed", "scan", "ss"):
        return "scan_speed"
    return None


def _infer_beam_control_type(rows):
    """Infer beam-control data type from row headers when filename hints are absent."""
    if not rows:
        return None
    headers = set(rows[0].keys())
    if {"current_amplitude_A", "deflection_cm"}.issubset(headers):
        return "deflection"
    if {"frequency_hz", "scan_speed_mps"}.issubset(headers):
        return "scan_speed"
    return None


def _validate_beam_control_rows(rows, filename, file_type=None):
    """Validate beam-control rows against expected schema before write/plot."""
    if not rows:
        return

    normalized_type = _normalize_beam_control_type(file_type) or _infer_beam_control_type(rows)
    if normalized_type == "deflection":
        required_columns = ["current_amplitude_A", "deflection_cm"]
    elif normalized_type == "scan_speed":
        required_columns = ["frequency_hz", "scan_speed_mps"]
    else:
        found = ", ".join(list(rows[0].keys()))
        raise ValueError(
            f"Beam control file '{filename}' type could not be inferred. "
            f"Expected headers for deflection ({'current_amplitude_A, deflection_cm'}) "
            f"or scan speed ({'frequency_hz, scan_speed_mps'}). Found: {found}."
        )

    header_keys = list(rows[0].keys())
    missing = [col for col in required_columns if col not in header_keys]
    if missing:
        raise ValueError(
            f"Beam control file '{filename}' is missing required columns: "
            f"{', '.join(missing)}. Expected at least: {', '.join(required_columns)}."
        )

    for idx, row in enumerate(rows, start=2):
        # Skip entirely empty lines.
        if all((val is None or str(val).strip() == "") for val in row.values()):
            continue
        for col in required_columns:
            value = row.get(col)
            if value is None or str(value).strip() == "":
                raise ValueError(
                    f"Beam control file '{filename}' has empty value for required column "
                    f"'{col}' at CSV row {idx}."
                )
            try:
                float(value)
            except (TypeError, ValueError):
                raise ValueError(
                    f"Beam control file '{filename}' has non-numeric value for column "
                    f"'{col}' at CSV row {idx}: {value!r}."
                )


def clean_beam_control_file(raw_path, clean_path, file_type=None):
    """Clean beam control files (pass-through with validation)."""
    rows = read_beam_control_csv(raw_path)
    if not rows:
        return rows

    _validate_beam_control_rows(rows, os.path.basename(raw_path), file_type=file_type)

    # Determine columns from the first row keys
    columns = list(rows[0].keys())
    write_beam_control_csv(clean_path, rows, columns)
    return rows

def plot_beam_control_graphs(rows, name, plot_dir, file_type):
    """Generate plots for beam control data."""
    if not rows:
        return
    
    if not os.path.exists(plot_dir):
        os.makedirs(plot_dir)
    
    normalized_type = _normalize_beam_control_type(file_type) or _infer_beam_control_type(rows)

    # Determine plot type based on file type (with header-based fallback)
    if normalized_type == "deflection":
        # Beam deflection plot: current_amplitude_A vs deflection_cm
        x_data = [float(r['current_amplitude_A']) for r in rows]
        y_data = [float(r['deflection_cm']) for r in rows]
        x_label = 'Current Amplitude (A)'
        y_label = 'Deflection (cm)'
        title = f'{name.replace("_", " ").title()}'
    elif normalized_type == "scan_speed":
        # Scan speed plot: frequency_hz vs scan_speed_mps
        x_data = [float(r['frequency_hz']) for r in rows]
        y_data = [float(r['scan_speed_mps']) for r in rows]
        x_label = 'Frequency (Hz)'
        y_label = 'Scan Speed (m/s)'
        title = f'{name.replace("_", " ").title()}'
    else:
        return
    
    plt.figure(figsize=(8, 6))
    plt.plot(x_data, y_data, marker='o', linestyle='-', linewidth=2, markersize=6)
    plt.xlabel(x_label, fontsize=12)
    plt.ylabel(y_label, fontsize=12)
    plt.title(title, fontsize=14, fontweight='bold')
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(plot_dir, f'{name}.png'), dpi=150)
    plt.close()

def process_beam_control_data():
    print("Processing beam control data...")
    file_pairs = discover_raw_file_pairs(BEAM_CONTROL_RAW_DIR)
    if not file_pairs:
        print("Beam Control: No raw CSV files found matching raw_*.csv")
        return

    for raw_name, clean_name in file_pairs:
        raw_path = os.path.join(BEAM_CONTROL_RAW_DIR, raw_name)
        raw_lower = raw_name.lower()
        if "bd" in raw_lower:
            file_type = "deflection"
        elif "ss" in raw_lower:
            file_type = "scan_speed"
        else:
            file_type = None
        rows = clean_beam_control_file(raw_path, raw_path, file_type=file_type)
        plot_name = clean_name.replace('.csv', '')
        plot_beam_control_graphs(rows, plot_name, BEAM_CONTROL_PLOT_DIR, file_type)

    print(f"Beam Control: Processed {len(file_pairs)} files and generated plots.")


def _infer_subsystem_from_rows(rows):
    """Infer subsystem from CSV headers when path does not identify it."""
    if not rows:
        raise ValueError("CSV file is empty; cannot infer subsystem.")
    headers = set(rows[0].keys())
    if {"beam_current", "voltage", "heater_current"}.issubset(headers):
        return "power_supply"
    if (
        {"current_amplitude_A", "deflection_cm"}.issubset(headers)
        or {"frequency_hz", "scan_speed_mps"}.issubset(headers)
    ):
        return "beam_control"
    raise ValueError(
        "Could not infer subsystem from CSV headers. "
        "Expected power supply columns (beam_current, voltage, heater_current) "
        "or beam control columns (current_amplitude_A/deflection_cm or frequency_hz/scan_speed_mps)."
    )


def _resolve_raw_input_path(filename):
    """Resolve filename/path to an existing raw CSV path."""
    if not filename:
        raise ValueError("Filename is required.")

    candidate_paths = []
    # Direct path support (absolute or relative)
    candidate_paths.append(filename)

    # Bare filename support against known raw directories.
    basename = os.path.basename(filename)
    candidate_paths.append(os.path.join(POWER_SUPPLY_RAW_DIR, basename))
    candidate_paths.append(os.path.join(BEAM_CONTROL_RAW_DIR, basename))

    # Convenience: allow omission of raw_ prefix.
    if not basename.lower().startswith(RAW_PREFIX):
        prefixed = f"{RAW_PREFIX}{basename}"
        candidate_paths.append(os.path.join(POWER_SUPPLY_RAW_DIR, prefixed))
        candidate_paths.append(os.path.join(BEAM_CONTROL_RAW_DIR, prefixed))

    existing = []
    for path in candidate_paths:
        if os.path.isfile(path):
            abs_path = os.path.abspath(path)
            if abs_path not in existing:
                existing.append(abs_path)

    if not existing:
        raise FileNotFoundError(
            f"Could not find CSV file '{filename}'. "
            f"Checked direct path and raw folders under {BASE_DIR}."
        )
    if len(existing) > 1:
        raise ValueError(
            "Filename is ambiguous across directories. "
            f"Please pass an explicit path. Matches: {existing}"
        )

    return existing[0]


def process_single_file(filename):
    """Process one CSV file identified by filename/path."""
    raw_path = _resolve_raw_input_path(filename)
    raw_name = os.path.basename(raw_path)

    clean_name = raw_name[len(RAW_PREFIX):] if raw_name.lower().startswith(RAW_PREFIX) else raw_name
    clean_stem, clean_ext = os.path.splitext(clean_name)
    if clean_ext.lower() != ".csv" or not clean_stem:
        raise ValueError(
            f"Invalid input filename '{raw_name}'. "
            "Expected a CSV with a non-empty name, typically starting with raw_."
        )

    normalized_raw_path = os.path.normcase(os.path.abspath(raw_path))
    if normalized_raw_path.startswith(os.path.normcase(os.path.abspath(POWER_SUPPLY_RAW_DIR))):
        subsystem = "power_supply"
    elif normalized_raw_path.startswith(os.path.normcase(os.path.abspath(BEAM_CONTROL_RAW_DIR))):
        subsystem = "beam_control"
    else:
        rows_for_inference = read_csv(raw_path)
        subsystem = _infer_subsystem_from_rows(rows_for_inference)

    if subsystem == "power_supply":
        rows = clean_power_supply_file(raw_path, raw_path)
        plot_power_supply_graphs(rows, clean_stem, POWER_SUPPLY_PLOT_DIR)
        print(f"Power Supply: Processed in place {raw_name}")
        return

    raw_lower = raw_name.lower()
    if "bd" in raw_lower:
        file_type = "deflection"
    elif "ss" in raw_lower:
        file_type = "scan_speed"
    else:
        file_type = None

    rows = clean_beam_control_file(raw_path, raw_path, file_type=file_type)
    plot_beam_control_graphs(rows, clean_stem, BEAM_CONTROL_PLOT_DIR, file_type)
    print(f"Beam Control: Processed in place {raw_name}")

def main():
    parser = argparse.ArgumentParser(description='Clean and process EBEAM lookup table data')
    parser.add_argument(
        'filename',
        nargs='?',
        help='Raw CSV filename (or path). Example: raw_powersupply_A.csv'
    )
    args = parser.parse_args()

    if args.filename:
        process_single_file(args.filename)
        return

    process_power_supply_data()
    process_beam_control_data()

if __name__ == "__main__":
    main()
