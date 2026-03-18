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

POWER_SUPPLY_FILES = [
    ("raw_default.csv", "default.csv"),
    ("raw_A.csv", "powersupply_A.csv"),
    ("raw_B.csv", "powersupply_B.csv"),
    ("raw_C.csv", "powersupply_C.csv"),
]

BEAM_CONTROL_FILES = [
    ("raw_bd_20keV.csv", "beam_deflection_20keV.csv"),
    ("raw_bd_50keV.csv", "beam_deflection_50keV.csv"),
    ("raw_ss_20keV.csv", "scan_speed_20keV.csv"),
    ("raw_ss_50keV.csv", "scan_speed_50keV.csv"),
]

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
    missing = []
    for raw_name, clean_name in POWER_SUPPLY_FILES:
        raw_path = os.path.join(POWER_SUPPLY_RAW_DIR, raw_name)
        clean_path = os.path.join(POWER_SUPPLY_OUTPUT_DIR, clean_name)
        if not os.path.exists(raw_path):
            missing.append(raw_name)
            continue
        rows = clean_power_supply_file(raw_path, clean_path)
        plot_power_supply_graphs(rows, clean_name.replace('.csv',''), POWER_SUPPLY_PLOT_DIR)
    
    if missing:
        print(f"Power Supply: The following files are missing: {', '.join(missing)}")
    else:
        print("Power Supply: All files processed and plots generated.")

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

def clean_beam_control_file(raw_path, clean_path):
    """Clean beam control files (pass-through with validation)."""
    rows = read_beam_control_csv(raw_path)
    # Determine columns from the first row keys
    if rows:
        columns = list(rows[0].keys())
        write_beam_control_csv(clean_path, rows, columns)
    return rows

def plot_beam_control_graphs(rows, name, plot_dir, file_type):
    """Generate plots for beam control data."""
    if not rows:
        return
    
    if not os.path.exists(plot_dir):
        os.makedirs(plot_dir)
    
    # Determine plot type based on file type
    if 'beam_deflection' in name:
        # Beam deflection plot: current_amplitude_A vs deflection_cm
        x_data = [float(r['current_amplitude_A']) for r in rows]
        y_data = [float(r['deflection_cm']) for r in rows]
        x_label = 'Current Amplitude (A)'
        y_label = 'Deflection (cm)'
        title = f'{name.replace("_", " ").title()}'
    elif 'scan_speed' in name:
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
    missing = []
    for raw_name, clean_name in BEAM_CONTROL_FILES:
        raw_path = os.path.join(BEAM_CONTROL_RAW_DIR, raw_name)
        clean_path = os.path.join(BEAM_CONTROL_OUTPUT_DIR, clean_name)
        if not os.path.exists(raw_path):
            missing.append(raw_name)
            continue
        rows = clean_beam_control_file(raw_path, clean_path)
        # Determine file type for plotting
        file_type = 'deflection' if 'bd' in raw_name else 'scan_speed'
        plot_beam_control_graphs(rows, clean_name.replace('.csv',''), BEAM_CONTROL_PLOT_DIR, file_type)
    
    if missing:
        print(f"Beam Control: The following files are missing: {', '.join(missing)}")
    else:
        print("Beam Control: All files processed and plots generated.")

def main():
    parser = argparse.ArgumentParser(description='Clean and process EBEAM lookup table data')
    parser.add_argument('--subsystem', choices=['power_supply', 'beam_control', 'all'], 
                       default='all', help='Which subsystem data to process')
    args = parser.parse_args()
    
    if args.subsystem in ['power_supply', 'all']:
        process_power_supply_data()
    
    if args.subsystem in ['beam_control', 'all']:
        process_beam_control_data()

if __name__ == "__main__":
    main()
