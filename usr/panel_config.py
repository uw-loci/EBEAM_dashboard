# usr/panel_config.py
import json

def save_pane_state(main_pane, num_sashes, filepath='usr/pane_state.json'):
    sash_positions = [main_pane.sash_coord(i) for i in range(num_sashes)]
    window_size = (main_pane.winfo_width(), main_pane.winfo_height())
    with open(filepath, 'w') as file:
        json.dump({'sash_positions': sash_positions, 'window_size': window_size}, file)

def load_pane_state(main_pane, num_sashes, filepath='usr/pane_state.json'):
    try:
        with open(filepath, 'r') as file:
            data = json.load(file)
        print("Loaded data:", data)  # Confirm the structure of loaded data

        # Explicit check for expected keys
        if 'sash_positions' in data:
            sash_positions = data['sash_positions']
            print("Sash positions:", sash_positions)
        else:
            print("Error: 'sash_positions' key not found in the loaded data")

        if 'window_size' in data:
            window_size = data['window_size']
            print("Window size:", window_size)
        else:
            print("Error: 'window_size' key not found in the loaded data")

        main_pane.after(500, lambda: restore_sashes(main_pane, sash_positions))

    except FileNotFoundError:
        print("No previous pane state saved.")
    except Exception as e:
        print(f"Failed to load pane state: {e}")

def restore_sashes(main_pane, sash_positions):
    for i, pos in enumerate(sash_positions):
        print(f"Attempting to restore sash {i} with position {pos}")  # Detailed debug statement
        try:
            main_pane.sash_place(i, *pos)
        except Exception as e:
            print(f"Failed to place sash {i}: {e}")