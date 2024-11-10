import re
import argparse
import matplotlib.pyplot as plt
import pandas as pd
import os

def parse_arguments():
    parser = argparse.ArgumentParser(description='Post-process experimental log files.')
    parser.add_argument('-f', '--files', nargs='+', required=True, help='Path(s) to the log file(s).')
    parser.add_argument('-d', '--data', nargs='+', choices=['voltage', 'current', 'temperature', 'pressure'],
                        default=['voltage', 'current', 'temperature'],
                        help='Data types to extract.')
    parser.add_argument('-o', '--output', choices=['csv', 'xlsx', 'plot'], nargs='+',
                        default=['csv', 'plot'],
                        help='Output formats.')
    parser.add_argument('--outdir', default='output', help='Output directory path')
    return parser.parse_args()

def get_patterns(data_types):
    """
    Regex patterns for different equipment types and their measurements.
    Structure:
    {
        'equipment_type': {
            'pattern': regex_pattern,
            'display_name': 'Equipment Display Name',
            'measurements': ['measurement1', 'measurement2']
        }
    }
    """
    patterns = {}
    
    if 'voltage' in data_types or 'current' in data_types:
        patterns['power_supply'] = {
            'pattern': r'\[(\d{2}:\d{2}:\d{2})\] - DEBUG: Power supply (\d) readings - Voltage: ([\d.]+)V, Current: ([\d.]+)A, Mode: (.+)',
            'display_name': 'Power Supply',
            'measurements': ['voltage', 'current']
        }
    
    if 'temperature' in data_types:
        patterns['cathode_temp'] = {
            'pattern': r'\[(\d{2}:\d{2}:\d{2})\] - INFO: Unit (\d) Temperature: ([\d.]+) °C',
            'display_name': 'Cathode',
            'measurements': ['temperature']
        }

    if 'pressure' in data_types:
        patterns['vacuum_pressure'] = {
            'pattern': r'\[(\d{2}:\d{2}:\d{2})\] - INFO: Chamber pressure: ([\d.]+(?:E[+-]\d+)?)\s*mbar\s*\(([\d.]+(?:E[+-]\d+)?)\)',
            'display_name': 'Vacuum Chamber',
            'measurements': ['pressure']
        }
    
    return patterns

def parse_log_file(filename, patterns):
    data = {key: [] for key in patterns.keys()}
    try:
        with open(filename, 'r') as file:
            for line in file:
                for equip_type, equip_info in patterns.items():
                    match = re.search(equip_info['pattern'], line)
                    if match:
                        time_str = match.group(1)
                        
                        if equip_type == 'power_supply':
                            ps_number = int(match.group(2))
                            voltage = float(match.group(3))
                            current = float(match.group(4))
                            mode = match.group(5)
                            data[equip_type].append({
                                'timestamp': time_str,
                                'ps_number': ps_number,
                                'voltage': voltage,
                                'current': current,
                                'mode': mode
                            })
                        elif equip_type == 'cathode_temp':
                            sensor = int(match.group(2))
                            temperature = float(match.group(3))
                            data[equip_type].append({
                                'timestamp': time_str,
                                'sensor': sensor,
                                'temperature': temperature,
                                'equipment': 'cathode'  # Tag the equipment type
                            })
                        elif equip_type == 'vacuum_pressure':
                            pressure = float(match.group(2))
                            raw_pressure = float(match.group(3))
                            data[equip_type].append({
                                'timestamp': time_str,
                                'pressure': pressure,
                                'raw_pressure': raw_pressure
                            })

            for equip_type, readings in data.items():
                print(f"Found {len(readings)} {patterns[equip_type]['display_name']} readings")
        return data
    except FileNotFoundError:
        print(f"Error: File {filename} not found.")
        return None
    except Exception as e:
        print(f"An error occurred while parsing {filename}: {e}")
        return None

def get_output_dir(filename):
    """Create output directory name based on log file date prefix."""
    base_name = os.path.basename(filename)
    # Look for date pattern in filename (assuming format: log_YYYY-MM-DD_*)
    match = re.search(r'log_(\d{4}-\d{2}-\d{2})', base_name)
    if match:
        date_str = match.group(1)
        return f"log_{date_str}_output"
    return "output"  # Default if no date found

def ensure_output_dir(base_dir, subdir):
    """Create output directory structure if it doesn't exist."""
    output_path = os.path.join(base_dir, subdir)
    os.makedirs(output_path, exist_ok=True)
    return output_path

def save_to_csv(df, output_path):
    df.to_csv(output_path, index=False)
    print(f"CSV saved to {output_path}")

def save_to_excel(df, output_path):
    df.to_excel(output_path, index=False)
    print(f"Excel file saved to {output_path}")

def plot_data(df, data_type, output_path):
    plt.figure(figsize=(12, 6))
    if data_type in ['voltage', 'current']:
        for ps_number, group in df.groupby('ps_number'):
            plt.plot(group['timestamp'], group[data_type], label=f'Power Supply {ps_number}', marker='o')
        ylabel = 'Voltage (V)' if data_type == 'voltage' else 'Current (A)'
        plt.ylabel(ylabel)
    elif data_type == 'temperature':
        for sensor, group in df.groupby('sensor'):
            plt.plot(group['timestamp'], group['temperature'], label=f'Sensor {sensor}', marker='x')
        plt.ylabel('Temperature (°C)')
    elif data_type == 'pressure':
        plt.plot(df['timestamp'], df['pressure'], label='Chamber Pressure', marker='.')
        plt.yscale('log')
        plt.ylabel('Pressure (mbar)') 
    
    plt.title(f'{data_type.capitalize()} Over Time')
    plt.xlabel('Time')
    plt.legend()
    plt.grid(True)
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()
    print(f"Plot saved to {output_path}")

def process_files(file_list, data_types, output_formats, output_dir):
    for file in file_list:
        print(f"\nProcessing file: {file}")
        patterns = get_patterns(data_types)
        parsed_data = parse_log_file(file, patterns)
        
        if not parsed_data:
            continue

        output_dir = get_output_dir(file)
        base_filename = os.path.splitext(os.path.basename(file))[0]
        
        # Create subdirectories for each type of output
        csv_dir = ensure_output_dir(output_dir, 'csv') if 'csv' in output_formats else None
        excel_dir = ensure_output_dir(output_dir, 'excel') if 'xlsx' in output_formats else None
        plot_dir = ensure_output_dir(output_dir, 'plots') if 'plot' in output_formats else None
        stats_dir = ensure_output_dir(output_dir, 'statistics')
            
        for data_type in data_types:
            if data_type in ['voltage', 'current'] and parsed_data['power_supply']:
                df = pd.DataFrame(parsed_data['power_supply'])
                df_sorted = df.sort_values('timestamp')
                
                if csv_dir:
                    save_to_csv(df_sorted, os.path.join(csv_dir, f"{base_filename}_{data_type}.csv"))
                if excel_dir:
                    save_to_excel(df_sorted, os.path.join(excel_dir, f"{base_filename}_{data_type}.xlsx"))
                if plot_dir:
                    plot_data(df_sorted, data_type, os.path.join(plot_dir, f"{base_filename}_{data_type}.png"))
                save_statistics(df_sorted, data_type, os.path.join(stats_dir, f"{base_filename}_{data_type}_stats.txt"))
                    
            elif data_type == 'temperature' and parsed_data['cathode_temp']:
                df = pd.DataFrame(parsed_data['cathode_temp'])
                df_sorted = df.sort_values('timestamp')
                
                if csv_dir:
                    save_to_csv(df_sorted, os.path.join(csv_dir, f"{base_filename}_temperature.csv"))
                if excel_dir:
                    save_to_excel(df_sorted, os.path.join(excel_dir, f"{base_filename}_temperature.xlsx"))
                if plot_dir:
                    plot_data(df_sorted, 'temperature', os.path.join(plot_dir, f"{base_filename}_temperature.png"))
                save_statistics(df_sorted, 'temperature', os.path.join(stats_dir, f"{base_filename}_temperature_stats.txt"))

            elif data_type == 'pressure' and parsed_data['vacuum_pressure']:
                df = pd.DataFrame(parsed_data['vacuum_pressure'])
                df_sorted = df.sort_values('timestamp')
                
                if csv_dir:
                    save_to_csv(df_sorted, os.path.join(csv_dir, f"{base_filename}_pressure.csv"))
                if excel_dir:
                    save_to_excel(df_sorted, os.path.join(excel_dir, f"{base_filename}_pressure.xlsx"))
                if plot_dir:
                    plot_data(df_sorted, 'pressure', os.path.join(plot_dir, f"{base_filename}_pressure.png"))
                save_statistics(df_sorted, 'pressure', os.path.join(stats_dir, f"{base_filename}_pressure_stats.txt"))

def save_statistics(df, data_type, output_path):
    with open(output_path, 'w') as f:
        f.write(f"{data_type.capitalize()} Summary Statistics\n")
        group_by = 'ps_number' if data_type in ['voltage', 'current'] else 'sensor'
        value_col = data_type if data_type in ['voltage', 'current'] else 'temperature'
        
        for group, group_df in df.groupby(group_by):
            f.write(f"\n{data_type.capitalize()} {group_by.replace('_', ' ').title()} {group}:\n")
            stats = group_df[value_col].describe()
            f.write(str(stats))
            f.write('\n')
    print(f"Statistics saved to {output_path}")


def main():
    args = parse_arguments()
    process_files(args.files, args.data, args.output, args.outdir)

if __name__ == "__main__":
    main()