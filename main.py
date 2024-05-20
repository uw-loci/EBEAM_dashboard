# main.py
import tkinter as tk
from dashboard import EBEAMSystemDashboard

if __name__ == "__main__":
    root = tk.Tk()
    app = EBEAMSystemDashboard(root)
    root.mainloop()