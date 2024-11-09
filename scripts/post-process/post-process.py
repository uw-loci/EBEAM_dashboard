import re
import argparse
from datetime import datetime
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
    return parser.parse_args()

def get_patterns(data_types):
    patterns = {}
    if 'voltage' in data_types or 'current' in data_types:
        patterns['power_supply'] = r'\[(\d{2}:\d{2}:\d{2})\] - DEBUG: Power supply (\d) readings - Voltage: ([\d.]+)V, Current: ([\d.]+)A, Mode: (.+)'
    if 'temperature' in data_types:
        patterns['temp'] = r'\[(\d{2}:\d{2}:\d{2})\] - INFO: Unit (\d) Temperature: ([\d.]+) °C'
    return patterns

def parse_log_file(filename, patterns):
    data = { 'power_supply': [], 'temp': [] }
    try:
        with open(filename, 'r') as file:
            for line in file:
                for key, pattern in patterns.items():
                    match = re.search(pattern, line)
                    if match:
                        if key == 'power_supply':
                            time_str = match.group(1)
                            timestamp = datetime.strptime(time_str, '%H:%M:%S')
                            ps_number = int(match.group(2))
                            voltage = float(match.group(3))
                            current = float(match.group(4))
                            mode = match.group(5)
                            data['power_supply'].append({
                                'timestamp': timestamp,
                                'ps_number': ps_number,
                                'voltage': voltage,
                                'current': current,
                                'mode': mode
                            })
                        elif key == 'temp':
                            time_str = match.group(1)
                            timestamp = datetime.strptime(time_str, '%H:%M:%S')
                            sensor = int(match.group(2))
                            temperature = float(match.group(3))
                            data['temp'].append({
                                'timestamp': timestamp,
                                'sensor': sensor,
                                'temperature': temperature
                            })
            print(f"Found {len(data['power_supply'])} power supply readings")
            print(f"Found {len(data['temp'])} temperature readings")
        return data
    except FileNotFoundError:
        print(f"Error: File {filename} not found.")
        return None
    except Exception as e:
        print(f"An error occurred while parsing {filename}: {e}")
        return None

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
    
    plt.title(f'{data_type.capitalize()} Over Time')
    plt.xlabel('Time')
    plt.legend()
    plt.grid(True)
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()
    print(f"Plot saved to {output_path}")

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

def process_files(file_list, data_types, output_formats):
    for file in file_list:
        print(f"\nProcessing file: {file}")
        patterns = get_patterns(data_types)
        parsed_data = parse_log_file(file, patterns)
        
        if not parsed_data:
            continue
            
        for data_type in data_types:
            if data_type in ['voltage', 'current']:
                if parsed_data['power_supply']:
                    df = pd.DataFrame(parsed_data['power_supply'])
                    df_sorted = df.sort_values('timestamp')
                    base_filename = os.path.splitext(os.path.basename(file))[0]
                    
                    if 'csv' in output_formats:
                        save_to_csv(df_sorted, f"{base_filename}_{data_type}.csv")
                    if 'xlsx' in output_formats:
                        save_to_excel(df_sorted, f"{base_filename}_{data_type}.xlsx")
                    if 'plot' in output_formats:
                        plot_data(df_sorted, data_type, f"{base_filename}_{data_type}.png")
                    if 'csv' in output_formats or 'xlsx' in output_formats:
                        save_statistics(df_sorted, data_type, f"{base_filename}_{data_type}_stats.txt")
                        
            elif data_type == 'temperature' and parsed_data['temp']:
                df = pd.DataFrame(parsed_data['temp'])
                df_sorted = df.sort_values('timestamp')
                base_filename = os.path.splitext(os.path.basename(file))[0]
                
                if 'csv' in output_formats:
                    save_to_csv(df_sorted, f"{base_filename}_temperature.csv")
                if 'xlsx' in output_formats:
                    save_to_excel(df_sorted, f"{base_filename}_temperature.xlsx")
                if 'plot' in output_formats:
                    plot_data(df_sorted, 'temperature', f"{base_filename}_temperature.png")
                if 'csv' in output_formats or 'xlsx' in output_formats:
                    save_statistics(df_sorted, 'temperature', f"{base_filename}_temperature_stats.txt")

def main():
    args = parse_arguments()
    process_files(args.files, args.data, args.output)

if __name__ == "__main__":
    main()