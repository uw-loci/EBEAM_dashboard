# usr/panel_config.py
import json
import tkinter as tk
from tkinter import PanedWindow

# Assuming you have a list of all PanedWindows you want to manage
def save_pane_states(paned_windows, filepath='usr/pane_state.json'):
    data = {}
    for index, pw in enumerate(paned_windows.panes()):
        num_sashes = len(pw.panes()) - 1
        sash_positions = [pw.sash_coord(i) for i in range(num_sashes)]
        data[f'paned_window_{index}'] = sash_positions
    with open(filepath, 'w') as file:
        json.dump(data, file)

def save_pane_states2(config, frames, pane, filepath='usr/pane_state.json'):
    data = {}
    _ = len(pane.panes())
    for i in range(_ - 1):
        data[f'paned_{i}'] = pane.sash_coord(i)

    for item in config:
        data[item[0]] = (frames[item[0]].winfo_width(), frames[item[0]].winfo_height())

    with open(filepath, 'w') as file:
        json.dump(data, file)

def load_pane_states(filepath='usr/pane_state.json'):
    try:
        with open(filepath, 'r') as file:
            data = json.load(file)
        return dict(data)
        # Delay the restoration to ensure the GUI is fully up and running
        # paned_windows[0].after(500, lambda: apply_sash_positions(paned_windows, all_sash_positions))
    except FileNotFoundError:
        print("No previous pane state saved.")
    except Exception as e:
        print(f"Failed to load pane states: {e}")

def saveFileExists(filepath='usr/pane_state.json'):
    try:
        with open(filepath, 'r') as file:
            json.load(file)
        return True
    except FileNotFoundError:
        return False
    except Exception as e:
        return False



# def apply_sash_positions(paned_windows, all_sash_positions):
#     for index, pw in enumerate(paned_windows):
#         sash_positions = all_sash_positions.get(f'paned_window_{index}', [])
#         for i, (x, y) in enumerate(sash_positions):
#             try:
#                 pw.sash_place(i, x, y)
#             except Exception as e:
#                 print(f"Error placing sash {i} at {x}, {y}: {e}")