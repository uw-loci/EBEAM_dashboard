## Experimental Log Post-Processor

A script for analyzing EBEAM Dashboard log files.

### Features
- Extracts measurement values from log files
- Generates various output formats (csv, txt, graphical plots)
- Provides statistical analysis of extracted data

### Requirements 
- python 3.6+
- required packages: 
```
pip install pandas matplotlib
```

### Usage
```
python post-process.py -f <log_files> [-d <data_types>] [-o <output_formats>] [--outdir <output_directory>]
```

Arguments
- `-f, --files`: Path(s) to the log file(s) (required)
- `-d, --data`: Data types to extract (default: voltage, current, temperature)
    - Choices: voltage, current, temperature, pressure
- `-o, --output`: Output formats (default: csv, plot)
    - Choices: csv, xlsx, plot
- `--outdir`: Output directory path (default: 'output')


# Output Directory Structure
For a log file named log_2024-11-04_experiment.log, the following directory structure is created:

```
log_2024-11-04_output/
├── csv/
│   ├── log_2024-11-04_voltage.csv
│   ├── log_2024-11-04_current.csv
│   └── log_2024-11-04_temperature.csv
├── plots/
│   ├── log_2024-11-04_voltage.png       # "Voltage Over Time"
│   ├── log_2024-11-04_current.png       # "Current Over Time"
│   └── log_2024-11-04_temperature.png   # "Cathode Temperatures Over Time"
└── statistics/
    ├── log_2024-11-04_voltage_stats.txt
    ├── log_2024-11-04_current_stats.txt
    └── log_2024-11-04_temperature_stats.txt
```
