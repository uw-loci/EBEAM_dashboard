import tkinter as tk
from tkinter import ttk
import serial.tools.list_ports
from dashboard import EBEAMSystemDashboard
from utils import LogLevel
import sys

def start_main_app(root, com_ports):
    app = EBEAMSystemDashboard(root, com_ports)
    root.mainloop()

def config_com_ports(root):
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        try:
            import pyi_splash
            pyi_splash.close()
        except ImportError:
            pass

    config_root = tk.Toplevel(root)
    config_root.title("Configure COM Ports")
    config_root.geometry('600x400')
    
    com_ports = serial.tools.list_ports.comports()
    available_ports = [port.device for port in com_ports]
    
    # Store COM port selections
    selections = {}

    # Create a dropdown for each subsystem
    subsystems = ['VTRXSubsystem', 'CathodeA PS', 'CathodeB PS', 'CathodeC PS', 'TempControllers']
    for subsystem in subsystems:
        tk.Label(config_root, text=f"{subsystem} COM Port:").pack()
        selected_port = tk.StringVar()
        ttk.Combobox(config_root, values=available_ports, textvariable=selected_port).pack()
        selections[subsystem] = selected_port

    def on_submit():
        selected_ports = {key: value.get() for key, value in selections.items()}
        config_root.destroy()
        start_main_app(root, selected_ports)

    submit_button = tk.Button(config_root, text="Submit", command=on_submit)
    submit_button.pack()
    
    config_root.mainloop()

if __name__ == "__main__":
    root = tk.Tk()
    config_com_ports(root)
