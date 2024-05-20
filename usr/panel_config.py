# usr/panel_config.py
import json

def save_pane_state(main_pane, num_sashes, filepath='usr/pane_state.json'):
    sash_positions = []
    for i in range(num_sashes):
        try:
            pos = main_pane.sash_coord(i)
            sash_positions.append(pos)
        except Exception as e:
            print(f"Error reading sash position {i}: {e}")
    with open(filepath, 'w') as file:
        json.dump(sash_positions, file)

def load_pane_state(main_pane, num_sashes, filepath='usr/pane_state.json'):
    try:
        with open(filepath, 'r') as file:
            sash_positions = json.load(file)
        # Delay the restoration of sash positions
        main_pane.after(100, lambda: restore_sashes(main_pane, sash_positions))
    except FileNotFoundError:
        print("No previous pane state saved.")
    except Exception as e:
        print(f"Failed to load pane state: {e}")

def restore_sashes(main_pane, sash_positions):
    for i, (x, y) in enumerate(sash_positions):
        try:
            main_pane.sash_place(i, x, y)
        except Exception as e:
            print(f"Error placing sash {i} at {x}, {y}: {e}")