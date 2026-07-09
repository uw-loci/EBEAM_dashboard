# usr/panel_config.py
import json
import os

CONFIG_FILE = 'usr/usr_data/pane_state.json'

# saves all the data related to the frames/widgets and panes to a file
def save_pane_states(config, frames, pane, filepath=CONFIG_FILE, logger=None):
    try:
        data = {}
        _ = len(pane.panes())
        for i in range(_ - 1):
            data[f'paned_{i}'] = pane.sash_coord(i)

        for item in config:
            data[item[0]] = (frames[item[0]].winfo_width(), frames[item[0]].winfo_height())

        directory = os.path.dirname(filepath)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(filepath, 'w') as file:
            json.dump(data, file)
    except Exception as e:
        if logger is not None:
            logger.error(f"Failed to save pane states: {e}", tag="Config")
        raise

    if logger is not None:
        logger.info(f"Pane state saved to {filepath}.", tag="Config")

# reads in file and passes the config file back as a dict
def load_pane_states(filepath=CONFIG_FILE, logger=None):
    try:
        with open(filepath, 'r') as file:
            data = json.load(file)
        if logger is not None:
            logger.debug(f"Pane state loaded from {filepath}.", tag="Config")
        return dict(data)
    except FileNotFoundError:
        if logger is not None:
            logger.info("No previous pane state saved.", tag="Config")
    except Exception as e:
        if logger is not None:
            logger.error(f"Failed to load pane states: {e}", tag="Config")

# checks to see if that config file exists
def saveFileExists(filepath=CONFIG_FILE, logger=None):
    try:
        with open(filepath, 'r') as file:
            json.load(file)
        return True
    except FileNotFoundError:
        return False
    except Exception as e:
        if logger is not None:
            logger.error(f"Failed to validate pane state file: {e}", tag="Config")
        return False
