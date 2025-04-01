# usr/panel_config.py
import json


CONFIG_FILE = 'usr/usr_data/pane_state.json'


# saves all the data related to the frames/widgets and panes to a file
def save_pane_states(config, frames, pane, filepath=CONFIG_FILE):
   data = {}
   _ = len(pane.panes())
   for i in range(_ - 1):
       data[f'paned_{i}'] = pane.sash_coord(i)


   for item in config:
       data[item[0]] = (frames[item[0]].winfo_width(), frames[item[0]].winfo_height())


   with open(filepath, 'w') as file:
       json.dump(data, file)


# reads in file and passes the config file back as a dict
def load_pane_states(filepath=CONFIG_FILE):
   try:
       with open(filepath, 'r') as file:
           data = json.load(file)
       return dict(data)
   except FileNotFoundError:
       print("No previous pane state saved.")
   except Exception as e:
       print(f"Failed to load pane states: {e}")


# checks to see if that config file exists
def saveFileExists(filepath=CONFIG_FILE):
   try:
       with open(filepath, 'r') as file:
           json.load(file)
       return True
   except FileNotFoundError:
       return False
   except Exception as e:
       return False