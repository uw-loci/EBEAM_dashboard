# main.py
import tkinter as tk
from dashboard import EBEAMSystemDashboard
import subprocess
import os

def start_main_app():
    root = tk.Tk()
    app = EBEAMSystemDashboard(root)
    root.mainloop()

if __name__ == "__main__":
    #splash = os.path.join(os.path.dirname(__file__), 'splash_screen.py')
    #subprocess.Popen(['python', splash])

    start_main_app()