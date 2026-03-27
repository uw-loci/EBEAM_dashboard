import csv
import os
import argparse
import matplotlib.pyplot as plt
from collections import defaultdict
from statistics import median

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

POWER_SUPPLY_INPUT_DIR = os.path.join(BASE_DIR, "power_supply")
POWER_SUPPLY_PLOT_DIR = os.path.join(BASE_DIR, "power_supply", "plots")
POWER_SUPPLY_OUTPUT_DIR = os.path.join(BASE_DIR, "power_supply")

BEAM_CONTROL_INPUT_DIR = os.path.join(BASE_DIR, "beam_control")
BEAM_CONTROL_PLOT_DIR = os.path.join(BASE_DIR, "beam_control", "plots")
BEAM_CONTROL_OUTPUT_DIR = os.path.join(BASE_DIR, "beam_control")

# Backward-compatible support for legacy raw_files folders.
POWER_SUPPLY_RAW_DIR = os.path.join(BASE_DIR, "power_supply", "raw_files")
BEAM_CONTROL_RAW_DIR = os.path.join(BASE_DIR, "beam_control", "raw_files")

POWER_SUPPLY_POLICIES = (
    "max_beam",
    "min_current_95pct_beam",
    "median_top_band",
)

POLICY_TO_METHOD_LABEL = {
    "max_beam": "Method 1 (max_beam)",
    "min_current_95pct_beam": "Method 2 (min_current_95pct_beam)",
    "median_top_band": "Method 3 (median_top_band)",
}

# Rows below these thresholds are treated as non-operational/off-state points.
MIN_OPERATIONAL_BEAM_CURRENT_MA = 0.001
MIN_OPERATIONAL_VOLTAGE_V = 0.001
MIN_OPERATIONAL_HEATER_CURRENT_A = 0.001

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

def _try_float(value):
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _to_numeric_power_rows(rows):
    """Parse power-supply rows and keep only complete operational numeric triples."""
    numeric = []
    for row in rows:
        beam = _try_float(row.get("beam_current"))
        voltage = _try_float(row.get("voltage"))
        heater = _try_float(row.get("heater_current"))
        if beam is None or voltage is None or heater is None:
            continue
        if beam < 0 or voltage < 0 or heater < 0:
            continue

        # Drop non-operational/off-state points that otherwise appear as LUT outliers.
        # Examples: (0, 0, 0), (0, 1.04, 0), and similar startup/transient records.
        if beam <= MIN_OPERATIONAL_BEAM_CURRENT_MA:
            continue
        if voltage <= MIN_OPERATIONAL_VOLTAGE_V:
            continue
        if heater <= MIN_OPERATIONAL_HEATER_CURRENT_A:
            continue

        numeric.append(
            {
                "beam_current": beam,
                "voltage": round(voltage, 2),
                "heater_current": round(heater, 2),
            }
        )
    return numeric


def _select_row_for_voltage_bin(group, policy):
    """Choose one representative row for a voltage bin according to policy."""
    if policy == "max_beam":
        # Practical default: best measured beam at this voltage.
        return max(group, key=lambda r: (r["beam_current"], r["heater_current"]))

    if policy == "min_current_95pct_beam":
        max_beam = max(r["beam_current"] for r in group)
        threshold = 0.95 * max_beam
        candidates = [r for r in group if r["beam_current"] >= threshold]
        return min(candidates, key=lambda r: (r["heater_current"], -r["beam_current"]))

    # median_top_band: robust against noisy clusters in a voltage bin.
    beams = [r["beam_current"] for r in group]
    beam_median = median(beams)
    top_band = [r for r in group if r["beam_current"] >= beam_median]
    hc_median = median(r["heater_current"] for r in top_band)
    return min(top_band, key=lambda r: (abs(r["heater_current"] - hc_median), -r["beam_current"]))


def _apply_power_supply_policy(rows, policy="max_beam"):
    """
    Clean raw power-supply rows into a single-valued LUT by voltage.

    Steps:
    1) Parse complete numeric rows only.
    2) Sort rows for deterministic grouping/selection.
    3) Deduplicate each voltage bin using selected policy.
    """
    numeric_rows = _to_numeric_power_rows(rows)
    if not numeric_rows:
        return []

    sorted_rows = sorted(
        numeric_rows,
        key=lambda r: (r["heater_current"], r["voltage"], r["beam_current"]),
    )

    by_voltage = defaultdict(list)
    for row in sorted_rows:
        by_voltage[row["voltage"]].append(row)

    cleaned_rows = []
    for voltage in sorted(by_voltage.keys()):
        selected = _select_row_for_voltage_bin(by_voltage[voltage], policy)
        cleaned_rows.append(selected)

    return sorted(cleaned_rows, key=lambda r: r["voltage"])


def _validate_power_supply_rows(rows, min_points=10):
    if len(rows) < min_points:
        raise ValueError(
            f"Power supply LUT contains only {len(rows)} usable points after cleaning; expected at least {min_points}."
        )

    voltages = [r["voltage"] for r in rows]
    if len(voltages) != len(set(voltages)):
        raise ValueError("Power supply LUT is not a function of voltage after cleaning (duplicate voltage bins remain).")

    by_heater = sorted(rows, key=lambda r: r["heater_current"])
    inversions = 0
    for prev, cur in zip(by_heater, by_heater[1:]):
        if cur["beam_current"] + 1e-9 < prev["beam_current"]:
            inversions += 1
    if inversions > 0:
        print(
            f"Warning: cleaned LUT has {inversions} beam-current inversions vs heater current; check data quality."
        )


def _format_power_supply_rows(rows):
    return [
        {
            "beam_current": f"{r['beam_current']:.3f}",
            "voltage": f"{r['voltage']:.2f}",
            "heater_current": f"{r['heater_current']:.2f}",
        }
        for r in rows
    ]

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

def clean_power_supply_file(raw_path, clean_path, policy="max_beam"):
    rows = read_csv(raw_path)
    cleaned_numeric = _apply_power_supply_policy(rows, policy=policy)
    _validate_power_supply_rows(cleaned_numeric)
    cleaned_rows = _format_power_supply_rows(cleaned_numeric)
    write_csv(clean_path, cleaned_rows)
    return rows, cleaned_rows


def discover_csv_file_pairs(input_dir):
    """Return (input_name, clean_name) for CSV files in input_dir."""
    if not os.path.isdir(input_dir):
        return []

    file_pairs = []
    for name in sorted(os.listdir(input_dir), key=str.lower):
        lower_name = name.lower()
        if not lower_name.endswith(".csv"):
            continue
        # Skip hidden/temp artifacts.
        if lower_name.startswith(".") or lower_name.startswith("~"):
            continue

        clean_name = name
        clean_stem, clean_ext = os.path.splitext(clean_name)
        if not clean_name or clean_ext.lower() != ".csv" or not clean_stem:
            continue
        file_pairs.append((name, clean_name))

    return file_pairs

def plot_power_supply_graphs(rows, name, plot_dir, policy=None):
    numeric_rows = _to_numeric_power_rows(rows)
    beam = [r["beam_current"] for r in numeric_rows]
    volt = [r["voltage"] for r in numeric_rows]
    heater = [r["heater_current"] for r in numeric_rows]
    if not numeric_rows:
        return
    if not os.path.exists(plot_dir):
        os.makedirs(plot_dir)
    method_label = POLICY_TO_METHOD_LABEL.get(policy)
    title_prefix = f"{name}: {method_label} - " if method_label else f"{name}: "

    # Plot voltage vs heater current (X: voltage, Y: heater current)
    plt.figure()
    plt.plot(volt, heater, marker='o')
    plt.xlabel('Voltage (V)')
    plt.ylabel('Heater Current (A)')
    plt.title(f'{title_prefix}\nHeater Current (A) vs Voltage (V)')
    plt.grid(True)
    plt.savefig(os.path.join(plot_dir, f'{name}_heater_vs_voltage.png'))
    plt.close()
    # Plot heater current vs beam current (X: heater current, Y: beam current)
    plt.figure()
    plt.plot(heater, beam, marker='o')
    plt.xlabel('Heater Current (A)')
    plt.ylabel('Beam Current (mA)')
    plt.title(f'{title_prefix}\nBeam Current (mA) vs Heater Current (A)')
    plt.grid(True)
    plt.savefig(os.path.join(plot_dir, f'{name}_beam_vs_heater.png'))
    plt.close()

    # Plot voltage vs beam current with heater current encoded as color.
    plt.figure(figsize=(8, 6.5))
    scatter = plt.scatter(volt, beam, c=heater, cmap='viridis', edgecolors='k', linewidths=0.3)
    cbar = plt.colorbar(scatter)
    cbar.set_label('Heater Current (A)')
    plt.xlabel('Voltage (V)')
    plt.ylabel('Beam Current (mA)')
    plt.title(
        f'{title_prefix}\n'
        'Beam Current (mA) vs Voltage (V)\n'
        '(colored by Heater Current (A))',
        pad=14,
    )
    plt.grid(True)
    plt.tight_layout(rect=(0.0, 0.0, 1.0, 0.90))
    plt.savefig(os.path.join(plot_dir, f'{name}_beam_vs_voltage_colored_by_heater.png'))
    plt.close()


def plot_power_supply_comparison(raw_rows, cleaned_rows, name, plot_dir, policy):
    """Create raw vs cleaned comparison plots for documentation and review."""
    raw_numeric = _to_numeric_power_rows(raw_rows)
    clean_numeric = _to_numeric_power_rows(cleaned_rows)
    if not raw_numeric or not clean_numeric:
        return

    if not os.path.exists(plot_dir):
        os.makedirs(plot_dir)

    method_label = POLICY_TO_METHOD_LABEL.get(policy, policy)

    raw_v = [r["voltage"] for r in raw_numeric]
    raw_b = [r["beam_current"] for r in raw_numeric]
    clean_sorted_v = sorted(clean_numeric, key=lambda r: r["voltage"])
    clean_sorted_h = sorted(clean_numeric, key=lambda r: r["heater_current"])

    # Beam current vs heater voltage: raw cloud + cleaned functional approximation.
    plt.figure(figsize=(8, 6))
    plt.scatter(raw_v, raw_b, s=18, alpha=0.35, color="gray", label="Raw")
    plt.plot(
        [r["voltage"] for r in clean_sorted_v],
        [r["beam_current"] for r in clean_sorted_v],
        marker="o",
        linewidth=2.0,
        label=f"Cleaned ({method_label})",
    )
    plt.xlabel("Voltage (V)")
    plt.ylabel("Beam Current (mA)")
    plt.title(
        f"{name}: {method_label}\n"
        "Raw vs Cleaned Beam Current (mA) vs Heater Voltage (V)",
        pad=14,
    )
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout(rect=(0.0, 0.0, 1.0, 0.92))
    plt.savefig(os.path.join(plot_dir, f"{name}_{policy}_raw_vs_clean_beam_vs_voltage.png"), dpi=150)
    plt.close()

    # Heater current vs heater voltage: raw cloud + cleaned representative curve.
    plt.figure(figsize=(8, 6))
    plt.scatter(
        [r["voltage"] for r in raw_numeric],
        [r["heater_current"] for r in raw_numeric],
        s=18,
        alpha=0.35,
        color="gray",
        label="Raw",
    )
    plt.plot(
        [r["voltage"] for r in clean_sorted_v],
        [r["heater_current"] for r in clean_sorted_v],
        marker="o",
        linewidth=2.0,
        label=f"Cleaned ({method_label})",
    )
    plt.xlabel("Voltage (V)")
    plt.ylabel("Heater Current (A)")
    plt.title(
        f"{name}: {method_label}\n"
        "Raw vs Cleaned Heater Current (A) vs Heater Voltage (V)"
    )
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.savefig(os.path.join(plot_dir, f"{name}_{policy}_raw_vs_clean_heater_vs_voltage.png"), dpi=150)
    plt.close()

    # Beam current vs heater current for cleaned result only.
    plt.figure(figsize=(8, 6))
    plt.plot(
        [r["heater_current"] for r in clean_sorted_h],
        [r["beam_current"] for r in clean_sorted_h],
        marker="o",
        linewidth=2.0,
        label=f"Cleaned ({method_label})",
    )
    plt.xlabel("Heater Current (A)")
    plt.ylabel("Beam Current (mA)")
    plt.title(
        f"{name}: {method_label}\n"
        "Cleaned Beam Current (mA) vs Heater Current (A)"
    )
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.savefig(os.path.join(plot_dir, f"{name}_{policy}_clean_beam_vs_heater.png"), dpi=150)
    plt.close()

def process_power_supply_data(policy="max_beam"):
    print("Processing power supply data...")
    file_pairs = discover_csv_file_pairs(POWER_SUPPLY_INPUT_DIR)
    if not file_pairs:
        # Fallback for older layout.
        file_pairs = discover_csv_file_pairs(POWER_SUPPLY_RAW_DIR)
    if not file_pairs:
        print("Power Supply: No CSV files found.")
        return

    for raw_name, clean_name in file_pairs:
        raw_path = os.path.join(
            POWER_SUPPLY_INPUT_DIR if os.path.isfile(os.path.join(POWER_SUPPLY_INPUT_DIR, raw_name)) else POWER_SUPPLY_RAW_DIR,
            raw_name,
        )
        raw_rows, cleaned_rows = clean_power_supply_file(raw_path, raw_path, policy=policy)
        plot_name = clean_name.replace('.csv', '')
        plot_power_supply_graphs(cleaned_rows, plot_name, POWER_SUPPLY_PLOT_DIR)
        plot_power_supply_comparison(raw_rows, cleaned_rows, plot_name, POWER_SUPPLY_PLOT_DIR, policy)

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
    file_pairs = discover_csv_file_pairs(BEAM_CONTROL_INPUT_DIR)
    if not file_pairs:
        # Fallback for older layout.
        file_pairs = discover_csv_file_pairs(BEAM_CONTROL_RAW_DIR)
    if not file_pairs:
        print("Beam Control: No CSV files found.")
        return

    for raw_name, clean_name in file_pairs:
        raw_path = os.path.join(
            BEAM_CONTROL_INPUT_DIR if os.path.isfile(os.path.join(BEAM_CONTROL_INPUT_DIR, raw_name)) else BEAM_CONTROL_RAW_DIR,
            raw_name,
        )
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


def _resolve_input_path(filename):
    """Resolve filename/path to an existing CSV path."""
    if not filename:
        raise ValueError("Filename is required.")

    candidate_paths = []
    # Direct path support (absolute or relative)
    candidate_paths.append(filename)
    candidate_paths.append(os.path.join(BASE_DIR, filename))

    # Bare filename support against known data directories.
    basename = os.path.basename(filename)
    candidate_paths.append(os.path.join(POWER_SUPPLY_INPUT_DIR, basename))
    candidate_paths.append(os.path.join(BEAM_CONTROL_INPUT_DIR, basename))
    # Legacy support.
    candidate_paths.append(os.path.join(POWER_SUPPLY_RAW_DIR, basename))
    candidate_paths.append(os.path.join(BEAM_CONTROL_RAW_DIR, basename))

    existing = []
    for path in candidate_paths:
        if os.path.isfile(path):
            abs_path = os.path.abspath(path)
            if abs_path not in existing:
                existing.append(abs_path)

    if not existing:
        raise FileNotFoundError(
            f"Could not find CSV file '{filename}'. "
            f"Checked direct path and data folders under {BASE_DIR}."
        )
    if len(existing) > 1:
        raise ValueError(
            "Filename is ambiguous across directories. "
            f"Please pass an explicit path. Matches: {existing}"
        )

    return existing[0]


def process_single_file(filename, ps_policy="max_beam", all_ps_policies=False):
    """Process one CSV file identified by filename/path."""
    raw_path = _resolve_input_path(filename)
    raw_name = os.path.basename(raw_path)

    clean_name = raw_name
    clean_stem, clean_ext = os.path.splitext(clean_name)
    if clean_ext.lower() != ".csv" or not clean_stem:
        raise ValueError(
            f"Invalid input filename '{raw_name}'. "
            "Expected a CSV with a non-empty name."
        )

    normalized_raw_path = os.path.normcase(os.path.abspath(raw_path))
    if normalized_raw_path.startswith(os.path.normcase(os.path.abspath(POWER_SUPPLY_INPUT_DIR))) or normalized_raw_path.startswith(os.path.normcase(os.path.abspath(POWER_SUPPLY_RAW_DIR))):
        subsystem = "power_supply"
    elif normalized_raw_path.startswith(os.path.normcase(os.path.abspath(BEAM_CONTROL_INPUT_DIR))) or normalized_raw_path.startswith(os.path.normcase(os.path.abspath(BEAM_CONTROL_RAW_DIR))):
        subsystem = "beam_control"
    else:
        rows_for_inference = read_csv(raw_path)
        subsystem = _infer_subsystem_from_rows(rows_for_inference)

    if subsystem == "power_supply":
        policies = POWER_SUPPLY_POLICIES if all_ps_policies else (ps_policy,)

        # If using one explicit policy, preserve backward-compatible in-place behavior.
        if len(policies) == 1:
            raw_rows, cleaned_rows = clean_power_supply_file(raw_path, raw_path, policy=policies[0])
            plot_power_supply_graphs(cleaned_rows, clean_stem, POWER_SUPPLY_PLOT_DIR, policy=policies[0])
            plot_power_supply_comparison(raw_rows, cleaned_rows, clean_stem, POWER_SUPPLY_PLOT_DIR, policies[0])
            print(f"Power Supply: Processed in place {raw_name} with policy '{policies[0]}'")
            return

        # If comparing policies, keep raw untouched and write one output per policy.
        raw_rows = read_csv(raw_path)
        for policy in policies:
            output_name = f"{clean_stem}__{policy}.csv"
            output_path = os.path.join(os.path.dirname(raw_path), output_name)
            cleaned_numeric = _apply_power_supply_policy(raw_rows, policy=policy)
            _validate_power_supply_rows(cleaned_numeric)
            cleaned_rows = _format_power_supply_rows(cleaned_numeric)
            write_csv(output_path, cleaned_rows)
            plot_power_supply_graphs(cleaned_rows, f"{clean_stem}__{policy}", POWER_SUPPLY_PLOT_DIR, policy=policy)
            plot_power_supply_comparison(raw_rows, cleaned_rows, clean_stem, POWER_SUPPLY_PLOT_DIR, policy)
            print(f"Power Supply: Wrote {output_name} using policy '{policy}'")
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
        help='CSV filename (or path). Example: Cbmark_Beam_A_07_2025.csv'
    )
    parser.add_argument(
        '--ps-policy',
        choices=POWER_SUPPLY_POLICIES,
        default='max_beam',
        help='Power-supply LUT approximation policy (default: max_beam).'
    )
    parser.add_argument(
        '--all-ps-policies',
        action='store_true',
        help='For a single power-supply file, generate one cleaned CSV per policy instead of in-place overwrite.'
    )
    args = parser.parse_args()

    if args.filename:
        process_single_file(args.filename, ps_policy=args.ps_policy, all_ps_policies=args.all_ps_policies)
        return

    process_power_supply_data(policy=args.ps_policy)
    process_beam_control_data()

if __name__ == "__main__":
    main()
