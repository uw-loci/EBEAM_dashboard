# usr/com_port_config.py
import json
import os

from utils import tag_log_message

CONFIG_FILE = 'usr/usr_data/com_ports.json'

def save_com_ports(com_ports, filepath=CONFIG_FILE, logger=None):
    """Save COM port selections to a JSON file."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)

    try:
        with open(filepath, 'w') as file:
            json.dump(com_ports, file, indent=4)
        if logger is not None:
            logger.info(tag_log_message(f"COM ports saved to {filepath}.", "Config"))
        else:
            print(tag_log_message(f"COM ports saved to {filepath}.", "Config"))
    except Exception as e:
        if logger is not None:
            logger.error(tag_log_message(f"Error saving COM ports: {e}", "Config"))
        else:
            print(tag_log_message(f"Error saving COM ports: {e}", "Config"))

def load_com_ports(filepath=CONFIG_FILE, logger=None):
    """Load COM port selections from a JSON file."""
    if not os.path.exists(filepath):
        if logger is not None:
            logger.info(tag_log_message("No COM port configuration file found.", "Config"))
        else:
            print(tag_log_message("No COM port configuration file found.", "Config"))
        return {}
    try:
        with open(filepath, 'r') as file:
            com_ports = json.load(file)
        if logger is not None:
            logger.info(tag_log_message(f"COM ports loaded from {filepath}.", "Config"))
        else:
            print(tag_log_message(f"COM ports loaded from {filepath}.", "Config"))
        return com_ports
    except Exception as e:
        if logger is not None:
            logger.error(tag_log_message(f"Error loading COM ports: {e}", "Config"))
        else:
            print(tag_log_message(f"Error loading COM ports: {e}", "Config"))
        return {}
