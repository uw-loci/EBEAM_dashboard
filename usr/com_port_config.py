# usr/com_port_config.py
import json
import os

CONFIG_FILE = 'usr/usr_data/com_ports.json'

def save_com_ports(com_ports, filepath=CONFIG_FILE):
   """Save COM port selections to a JSON file."""
   os.makedirs(os.path.dirname(filepath), exist_ok=True)
   try:
       with open(filepath, 'w') as file:
           json.dump(com_ports, file, indent=4)
       print(f"COM ports saved to {filepath}.")
   except Exception as e:
       print(f"Error saving COM ports: {e}")


def load_com_ports(filepath=CONFIG_FILE):
    """Load COM port selections from a JSON file."""
    if not os.path.exists(filepath):
        print("No COM port configuration file found.")
        return {}
    try:
        with open(filepath, 'r') as file:
            com_ports = json.load(file)
        print(f"COM ports loaded from {filepath}.")
        return com_ports
    except Exception as e:
        print(f"Error loading COM ports: {e}")
        return {}
