import sys
import tkinter as tk
from tkinter import ttk, messagebox
import serial.tools.list_ports

from dashboard import EBEAMSystemDashboard
from usr.com_port_config import save_com_ports, load_com_ports


SUBSYSTEMS = [
    'VTRXSubsystem', 
    'CathodeA PS', 
    'CathodeB PS', 
    'CathodeC PS', 
    'TempControllers', 
    'Interlocks', 
    'ProcessMonitors'
]

def create_dummy_port_labels(subsystems):
    """
    Create a list of dummy port labels that the user can select
    for each subsystem. Example: ['DUMMY_COM1', 'DUMMY_COM2', ...]
    """
    return [f"DUMMY_COM{i+1}" for i, _ in enumerate(subsystems)]

def create_dummy_ports(subsystems):
    """
    Return a dict mapping each subsystem to a unique dummy port name.
    Example:
    {
        'VTRXSubsystem': 'DUMMY_COM1',
        'CathodeA PS': 'DUMMY_COM2',
        ...
    }
    """
    return {subsystem: f"DUMMY_COM{i+1}" for i, subsystem in enumerate(subsystems)}

def start_main_app(com_ports):
    """
    Create and start the main EBEAM System Dashboard application.

    :param com_ports: Dict mapping subsystems to their selected COM ports.
    """
    root = tk.Tk()
    root.title("EBEAM System Dashboard")
    root.state('zoomed')

    app = EBEAMSystemDashboard(root, com_ports)
    root.mainloop()

def config_com_ports(saved_com_ports):
    """
    Display a configuration GUI for selecting COM ports for each subsystem.
    Users can choose from available real COM ports or dummy ports.
    If any subsystem is left blank, the user will be prompted to fill
    in dummy ports or return to the config window.
    
    :param saved_com_ports: Dict of previously saved COM port settings.
    """
    # Close the PyInstaller splash if running as bundled executable
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        try:
            import pyi_splash
            pyi_splash.close()
        except ImportError:
            pass
    
    # Get real COM ports on the system
    real_ports = [port.device for port in serial.tools.list_ports.comports()]
    # Create a combined list of real + dummy port labels for user to pick
    dummy_port_labels = create_dummy_port_labels(SUBSYSTEMS)
    # Combine real + dummy port labels
    combined_port_options = real_ports + dummy_port_labels

    config_root = tk.Tk()
    config_root.title("Configure COM Ports")

    selections = {}

    main_frame = ttk.Frame(config_root, padding="20 20 20 20")
    main_frame.pack(side=tk.TOP, fill=tk.X)

    # Create a dropdown for each subsystem
    for subsystem in SUBSYSTEMS:
        frame = ttk.Frame(main_frame)
        frame.pack(pady=5, anchor='center')

        label = tk.Label(
            frame, 
            text=f"{subsystem} COM Port:", 
            width=25, 
            anchor='e'
        )
        label.pack(side=tk.LEFT, padx=(0, 10))

        # Default to a previously saved port if available, otherwise blank
        selected_port = tk.StringVar(value=saved_com_ports.get(subsystem, ''))

        combobox = ttk.Combobox(
            frame, 
            values=combined_port_options, 
            textvariable=selected_port, 
            state='readonly', 
            width=15
        )
        combobox.pack(side=tk.LEFT)
        selections[subsystem] = selected_port

    def on_submit():
        """
        Handler for the 'Submit' button. Checks if all subsystems have a port
        selected. If not, offers to fill those with dummy ports. If the user
        refuses, they remain in the config window.
        """
        selected_ports = {key: value.get() for key, value in selections.items()}
        
        # check that all COM ports are selected
        if not all(selected_ports.values()):
            response = messagebox.askquestion(
                "No Ports Selected",
                "One or more subsystems has no COM port selected.\n"
                "Would you like to use dummy ports for those?",
                icon='warning'
            )
            if response == 'yes':
                # Fill in dummy ports for any subsystem left blank
                for subsystem, port_choice in selected_ports.items():
                    if not port_choice:
                        selected_ports[subsystem] = f"DUMMY_COM_{subsystem}"
            else:
                # if the user doesn't want to use dummy ports, they must pick real ones
                return  # Stay on the configuration window
        
        # save final selections
        save_com_ports(selected_ports)
        config_root.destroy()
        
        # Launch the main application
        start_main_app(selected_ports)

    submit_button = tk.Button(config_root, text="Submit", command=on_submit)
    submit_button.pack(pady=20)
    
    config_root.bind('<Return>', lambda event: on_submit())
    config_root.mainloop()


if __name__ == "__main__":
    # Load previously saved COM ports, if any
    saved_com_ports = load_com_ports()

    # Prompt the user to confirm or change COM ports
    config_com_ports(saved_com_ports)
