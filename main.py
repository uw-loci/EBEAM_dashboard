import tkinter as tk
from tkinter import ttk, messagebox
import serial.tools.list_ports
from dashboard import EBEAMSystemDashboard
import sys
from usr.com_port_config import save_com_ports, load_com_ports

def start_main_app(com_ports):
    root = tk.Tk()
    root.title("EBEAM System Dashboard")
    app = EBEAMSystemDashboard(root, com_ports)
    root.mainloop()

def config_com_ports(saved_com_ports):
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        try:
            import pyi_splash
            pyi_splash.close()
        except ImportError:
            pass

    config_root = tk.Tk()
    config_root.title("Configure COM Ports")
    # config_root.geometry('600x400')
    
    com_ports = serial.tools.list_ports.comports()
    available_ports = [port.device for port in com_ports]

    selections = {}

    main_frame = ttk.Frame(config_root, padding="20 20 20 20")
    main_frame.pack(side=tk.TOP, fill=tk.X)

    # Create a dropdown for each subsystem
    subsystems = ['VTRXSubsystem', 'CathodeA PS', 'CathodeB PS', 'CathodeC PS', 'TempControllers']
    for subsystem in subsystems:
        frame = ttk.Frame(main_frame)
        frame.pack(pady=5, anchor='center')
        label = tk.Label(frame, text=f"{subsystem} COM Port:", width=25, anchor='e')
        label.pack(side=tk.LEFT, padx=(0, 10))

        selected_port = tk.StringVar(value=saved_com_ports.get(subsystem, ''))
        combobox = ttk.Combobox(frame, values=available_ports, textvariable=selected_port, state='readonly', width=15)
        combobox.pack(side=tk.LEFT)
        selections[subsystem] = selected_port

    def on_submit():
        selected_ports = {key: value.get() for key, value in selections.items()}
        
        # check that all COM ports are selected
        if not all(selected_ports.values()):
            messagebox.showerror("Error", "Please select all COM ports.")
            return
        
        save_com_ports(selected_ports)
        config_root.destroy()
        
        # Start the main application
        start_main_app(selected_ports)

    submit_button = tk.Button(config_root, text="Submit", command=on_submit)
    submit_button.pack(pady=20)
    
    config_root.mainloop()

if __name__ == "__main__":
    
    saved_com_ports = load_com_ports()

    # Prompt the user to confirm or change COM ports
    config_com_ports(saved_com_ports)
