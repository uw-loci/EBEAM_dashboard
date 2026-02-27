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
    'ProcessMonitors',
    'BeamPulse',
]

# Material Design Dark Theme Palette
MD_BG = "#1E1E2E"
MD_CARD = "#2A2A3C"
MD_CARD_BORDER = "#3A3A4C"
MD_PRIMARY = "#7C4DFF"
MD_PRIMARY_HOVER = "#6A3FE0"
MD_TEXT = "#E0E0E0"
MD_TEXT_DIM = "#9E9E9E"
MIN_DASHBOARD_WIDTH = 1200
MIN_DASHBOARD_HEIGHT = 675

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
    root.configure(bg=MD_BG)
    root.minsize(MIN_DASHBOARD_WIDTH, MIN_DASHBOARD_HEIGHT)
    root.attributes('-zoomed', True)
    restore_geometry = "1920x1080"

    # Track fullscreen state
    fullscreen = False
    was_zoomed = True
    was_fullscreen = False

    def restore_window_size_1080p():
        root.attributes('-fullscreen', False)
        root.attributes('-zoomed', False)
        root.geometry(restore_geometry)
  
    def quit_app(event=None):
        if messagebox.askokcancel("Quit", "Do you want to quit?"):
            app.cleanup()
            root.destroy()
        return "break"
    
    def toggle_fullscreen(event=None):
        nonlocal fullscreen
        is_fullscreen = bool(root.attributes('-fullscreen'))
        if is_fullscreen:
            fullscreen = False
            restore_window_size_1080p()
        else:
            fullscreen = True
            root.attributes('-fullscreen', True)
        return "break"
    
    def escape_handler(event=None):
        nonlocal fullscreen
        if fullscreen:
            fullscreen = False
            restore_window_size_1080p()
        return "break"
    
    def toggle_maximize(event=None):
        current = bool(root.attributes('-zoomed'))
        if current:
            restore_window_size_1080p()
        else:
            root.attributes('-zoomed', True)
        return "break"

    def enforce_restore_geometry(event=None):
        nonlocal was_zoomed, was_fullscreen, fullscreen
        if event is not None and event.widget is not root:
            return
        is_zoomed = bool(root.attributes('-zoomed'))
        is_fullscreen = bool(root.attributes('-fullscreen'))
        fullscreen = is_fullscreen
        if was_zoomed and (not is_zoomed) and (not is_fullscreen):
            root.geometry(restore_geometry)
        if was_fullscreen and (not is_fullscreen) and (not is_zoomed):
            root.geometry(restore_geometry)
        was_zoomed = is_zoomed
        was_fullscreen = is_fullscreen

    def save_logs(event=None):
        if hasattr(app, 'messages_frame'):
            app.messages_frame.export_log()
        else:
            messagebox.showwarning(
                "Warning", 
                "Message frame not initialized. Cannot save logs"
            )
        return "break"

    def show_shortcuts(event=None):
        """Display a window showing all keyboard shortcuts."""
        shortcuts_window = tk.Toplevel(root)
        shortcuts_window.title("Keyboard Shortcuts")
        shortcuts_window.geometry("280x300")
        
        # Make the window modal (user must close it to continue)
        shortcuts_window.transient(root)
        shortcuts_window.grab_set()
        
        # Create a frame with padding
        frame = ttk.Frame(shortcuts_window, padding="20 20 20 20")
        frame.pack(fill=tk.BOTH, expand=True)
        
        # Title
        title_label = ttk.Label(
            frame, 
            text="Available Keyboard Shortcuts",
            font=("Helvetica", 12, "bold")
        )
        title_label.pack(pady=(0, 20))
        
        # Shortcuts list
        shortcuts = [
            ("F1", "Show this help window"),
            ("Ctrl + Q", "Quit application"),
            ("Ctrl + W", "Quit application (alt.)"),
            ("F11", "Toggle fullscreen"),
            ("Escape", "Exit fullscreen"),
            ("Ctrl + M", "Toggle maximize/restore"),
            ("Ctrl + S", "Save logs"),
        ]
        
        # Create a frame for the shortcuts
        shortcuts_frame = ttk.Frame(frame)
        shortcuts_frame.pack(fill=tk.BOTH, expand=True)
        
        # Add shortcuts to the frame in a grid
        for i, (key, description) in enumerate(shortcuts):
            key_label = ttk.Label(
                shortcuts_frame,
                text=key,
                font=("Courier", 10),
                padding=(5, 2)
            )
            key_label.grid(row=i, column=0, sticky="e", padx=(0, 10))
            
            desc_label = ttk.Label(
                shortcuts_frame,
                text=description,
                padding=(5, 2)
            )
            desc_label.grid(row=i, column=1, sticky="w")
        
        # Close button
        close_button = ttk.Button(
            frame,
            text="Close",
            command=shortcuts_window.destroy
        )
        close_button.pack(pady=(20, 0))
        
        # Bind Escape key to close the window
        shortcuts_window.bind('<Escape>', lambda e: shortcuts_window.destroy())
        
        # Center the window on the screen
        shortcuts_window.update_idletasks()
        width = shortcuts_window.winfo_width()
        height = shortcuts_window.winfo_height()
        x = (root.winfo_screenwidth() // 2) - (width // 2)
        y = (root.winfo_screenheight() // 2) - (height // 2)
        shortcuts_window.geometry(f'{width}x{height}+{x}+{y}')

        return "break"

    # Bind keyboard shortcuts
    root.bind('<Control-q>', quit_app)          # Quit application
    root.bind('<Control-w>', quit_app)          # Alternative quit
    root.bind('<F11>', toggle_fullscreen)       # Toggle fullscreen
    root.bind('<F1>', show_shortcuts)            # Show keyboard shortcuts
    root.bind('<Escape>', escape_handler)       # Exit fullscreen
    root.bind('<Control-m>', toggle_maximize)   # Toggle maximize  
    root.bind('<Control-s>', save_logs)         # Save log file
  

    app = EBEAMSystemDashboard(root, com_ports)
    root.bind('<Configure>', enforce_restore_geometry, add='+')
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
    config_root.configure(bg=MD_BG)

    style = ttk.Style(config_root)
    if "clam" in style.theme_names():
        style.theme_use("clam")
    style.configure(".", background=MD_BG, foreground=MD_TEXT)
    style.configure("TFrame", background=MD_BG)
    style.configure("TLabel", background=MD_BG, foreground=MD_TEXT)
    style.configure("TButton", background=MD_PRIMARY, foreground="#FFFFFF", borderwidth=0, focusthickness=0, padding=(10, 6))
    style.map("TButton", background=[("active", MD_PRIMARY_HOVER), ("pressed", MD_PRIMARY)], foreground=[("disabled", MD_TEXT_DIM)])
    style.configure(
        "MD.TCombobox",
        fieldbackground=MD_CARD,
        background=MD_CARD_BORDER,
        foreground=MD_TEXT,
        arrowcolor=MD_TEXT,
        bordercolor=MD_CARD_BORDER,
        lightcolor=MD_CARD_BORDER,
        darkcolor=MD_CARD_BORDER,
        insertcolor=MD_TEXT,
        padding=(6, 4),
    )
    style.map(
        "MD.TCombobox",
        fieldbackground=[("readonly", MD_CARD), ("focus", MD_CARD)],
        background=[("readonly", MD_CARD_BORDER), ("active", MD_PRIMARY_HOVER)],
        foreground=[("readonly", MD_TEXT), ("disabled", MD_TEXT_DIM)],
        arrowcolor=[("active", "#FFFFFF"), ("readonly", MD_TEXT)],
    )
    config_root.option_add('*TCombobox*Listbox*Background', MD_CARD)
    config_root.option_add('*TCombobox*Listbox*Foreground', MD_TEXT)
    config_root.option_add('*TCombobox*Listbox*selectBackground', MD_PRIMARY)
    config_root.option_add('*TCombobox*Listbox*selectForeground', '#FFFFFF')

    selections = {}

    main_frame = ttk.Frame(config_root, padding="20 20 20 20")
    main_frame.pack(side=tk.TOP, fill=tk.X)

    # Create a dropdown for each subsystem
    for subsystem in SUBSYSTEMS:
        frame = ttk.Frame(main_frame)
        frame.pack(pady=5, anchor='center')

        label = ttk.Label(
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
            width=15,
            style='MD.TCombobox'
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

    submit_button = ttk.Button(config_root, text="Submit", command=on_submit)
    submit_button.pack(pady=20)
    
    config_root.bind('<Return>', lambda event: on_submit())
    config_root.mainloop()


if __name__ == "__main__":
    # Load previously saved COM ports, if any
    saved_com_ports = load_com_ports()

    # Prompt the user to confirm or change COM ports
    config_com_ports(saved_com_ports)
