import csv
import os
import argparse
import matplotlib.pyplot as plt
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

POWER_SUPPLY_INPUT_DIR = os.path.join(BASE_DIR, "power_supply")
POWER_SUPPLY_PLOT_DIR = os.path.join(BASE_DIR, "power_supply", "plots")

# Backward-compatible support for legacy raw_files folders.
POWER_SUPPLY_RAW_DIR = os.path.join(BASE_DIR, "power_supply", "raw_files")

POWER_SUPPLY_METHOD_LABEL = "Method 1 (max beam; lower heater current on ties)"

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

        numeric.append(
            {
                "beam_current": beam,
                "voltage": round(voltage, 2),
                "heater_current": round(heater, 2),
            }
        )
    return numeric


def _select_row_for_voltage_bin(group):
    """Choose one representative row for a voltage bin.

    Method 1:
    1) Select rows with the maximum beam current in the bin.
    2) If tied, choose the row with the lower heater current.
    """
    max_beam = max(r["beam_current"] for r in group)
    tied = [r for r in group if r["beam_current"] == max_beam]
    return min(tied, key=lambda r: r["heater_current"])


def _clean_power_supply_rows(rows):
    """
    Clean raw power-supply rows into a single-valued LUT by voltage.

    Steps:
    1) Parse complete numeric rows only.
    2) Sort rows for deterministic grouping/selection.
    3) Deduplicate each voltage bin using Method 1.
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
        selected = _select_row_for_voltage_bin(by_voltage[voltage])
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

def clean_power_supply_file(raw_path, clean_path):
    rows = read_csv(raw_path)
    cleaned_numeric = _clean_power_supply_rows(rows)
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

def plot_power_supply_graphs(rows, name, plot_dir):
    numeric_rows = _to_numeric_power_rows(rows)
    beam = [r["beam_current"] for r in numeric_rows]
    volt = [r["voltage"] for r in numeric_rows]
    heater = [r["heater_current"] for r in numeric_rows]
    if not numeric_rows:
        return
    if not os.path.exists(plot_dir):
        os.makedirs(plot_dir)
    title_prefix = f"{name}: {POWER_SUPPLY_METHOD_LABEL} - "

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


def plot_power_supply_comparison(raw_rows, cleaned_rows, name, plot_dir):
    """Create raw vs cleaned comparison plots for documentation and review."""
    raw_numeric = _to_numeric_power_rows(raw_rows)
    clean_numeric = _to_numeric_power_rows(cleaned_rows)
    if not raw_numeric or not clean_numeric:
        return

    if not os.path.exists(plot_dir):
        os.makedirs(plot_dir)

    method_label = POWER_SUPPLY_METHOD_LABEL

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
    plt.savefig(os.path.join(plot_dir, f"{name}_raw_vs_clean_beam_vs_voltage.png"), dpi=150)
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
    plt.savefig(os.path.join(plot_dir, f"{name}_raw_vs_clean_heater_vs_voltage.png"), dpi=150)
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
    plt.savefig(os.path.join(plot_dir, f"{name}_clean_beam_vs_heater.png"), dpi=150)
    plt.close()

def process_power_supply_data():
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
        raw_rows, cleaned_rows = clean_power_supply_file(raw_path, raw_path)
        plot_name = clean_name.replace('.csv', '')
        plot_power_supply_graphs(cleaned_rows, plot_name, POWER_SUPPLY_PLOT_DIR)
        plot_power_supply_comparison(raw_rows, cleaned_rows, plot_name, POWER_SUPPLY_PLOT_DIR)

    print(f"Power Supply: Processed {len(file_pairs)} files and generated plots.")


def _validate_power_supply_input_rows(rows, filename):
    """Validate that single-file input is a power-supply CSV."""
    if not rows:
        raise ValueError(f"CSV file '{filename}' is empty.")

    headers = set(rows[0].keys())
    required = {"beam_current", "voltage", "heater_current"}
    if not required.issubset(headers):
        found = ", ".join(list(rows[0].keys()))
        raise ValueError(
            f"File '{filename}' is not a power-supply LUT CSV. "
            f"Expected headers: beam_current, voltage, heater_current. Found: {found}."
        )


def _resolve_input_path(filename):
    """Resolve filename/path to an existing CSV path."""
    if not filename:
        raise ValueError("Filename is required.")

    candidate_paths = []
    # Direct path support (absolute or relative)
    candidate_paths.append(filename)
    candidate_paths.append(os.path.join(BASE_DIR, filename))

    # Bare filename support against power-supply data directories.
    basename = os.path.basename(filename)
    candidate_paths.append(os.path.join(POWER_SUPPLY_INPUT_DIR, basename))
    # Legacy support.
    candidate_paths.append(os.path.join(POWER_SUPPLY_RAW_DIR, basename))

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


def process_single_file(filename):
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

    rows_for_validation = read_csv(raw_path)
    _validate_power_supply_input_rows(rows_for_validation, raw_name)

    raw_rows, cleaned_rows = clean_power_supply_file(raw_path, raw_path)
    plot_power_supply_graphs(cleaned_rows, clean_stem, POWER_SUPPLY_PLOT_DIR)
    plot_power_supply_comparison(raw_rows, cleaned_rows, clean_stem, POWER_SUPPLY_PLOT_DIR)
    print(f"Power Supply: Processed in place {raw_name} using Method 1")

def main():
    parser = argparse.ArgumentParser(description='Clean and process power-supply EBEAM lookup table data')
    parser.add_argument(
        'filename',
        nargs='?',
        help='CSV filename (or path). Example: Cbmark_Beam_A_07_2025.csv'
    )
    args = parser.parse_args()

    if args.filename:
        process_single_file(args.filename)
        return

    process_power_supply_data()

if __name__ == "__main__":
    main()
