import subsystem
import tkinter as tk
from tkinter import ttk
from utils import MessagesFrame, SetupScripts, LogLevel
from usr.panel_config import save_pane_states, load_pane_states, saveFileExists
import serial.tools.list_ports

# Only have the interlocks at the top of the display
# title, row, width, height
frames_config = [
    ("Interlocks", 0, None, 2),  # Moved to the top row
    ("Oil System", 1, 50, 150),
    ("Visualization Gas Control", 2, 50, 150),
    ("System Checks", 1, None, None),
    ("Beam Extraction", 1, None, None),
    ("Vacuum System", 2, 150, 300),
    ("Deflection Monitor", 2, None, None),
    ("Beam Pulse", 2, None, None),
    ("Main Control", 2, 50, 300),
    ("Setup Script", 3, None, 25),
    ("High Voltage Warning", 3, None, 25),
    ("Environmental", 4, 150, 450),
    ("Cathode Heating", 4, 960, 450),
]

class EBEAMSystemDashboard:
    PORT_INFO = {
        "AD0K0ZIEA" : "Interlocks"
    }
    def __init__(self, root, com_ports):
        self.root = root
        self.com_ports = com_ports
        self.num_ports = len(serial.tools.list_ports.comports())
        self.set_com_ports = set(serial.tools.list_ports.comports())

        self.root.title("EBEAM Control System Dashboard")


        # if save file exists call it and open it
        if saveFileExists():
             self.load_saved_pane_state()

        # if save file exists call it and open it
        if saveFileExists():
             self.load_saved_pane_state()

        # Initialize the frames dictionary to store various GUI components
        self.frames = {}
        
        # Set up the main pane using PanedWindow for flexible layout
        self.setup_main_pane()

        # Initialize all the frames within the main pane
        self.create_frames()

        # Set up a frame for displaying messages and errors
        self.create_messages_frame()

        # Set up different subsystems within their respective frames
        self.create_subsystems()

        # starts the constant check for the avavilbe com ports
        self._check_for_port_changes()

    def setup_main_pane(self):
        """Initialize the main layout pane and its rows."""
        self.main_pane = tk.PanedWindow(self.root, orient='vertical', sashrelief=tk.RAISED)
        self.main_pane.grid(row=0, column=0, sticky='nsew')
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(0, weight=1)
        self.rows = [tk.PanedWindow(self.main_pane, orient='horizontal', sashrelief=tk.RAISED) for _ in range(5)]
        for row_pane in self.rows:
            self.main_pane.add(row_pane, stretch='always')

    def create_frames(self):
        """Create frames for different systems and controls within the dashboard."""
        global frames_config
        global frames_config

        for title, row, width, height in frames_config:
            if width and height and title:
                frame = tk.Frame( borderwidth=1, relief="solid", width=width, height=height)
                frame.pack_propagate(False)
            else:
                frame = tk.Frame(borderwidth=1, relief="solid")
            self.rows[row].add(frame, stretch='always')
            if title != "Interlocks":
                self.add_title(frame, title)
            self.frames[title] = frame
            if title == "Setup Script":
                SetupScripts(frame)
            if title == "Main Control":
                self.create_main_control_notebook(frame)

    def create_main_control_notebook(self, frame):
        notebook = ttk.Notebook(frame)
        notebook.pack(expand=True, fill='both')

        main_tab = ttk.Frame(notebook)
        config_tab = ttk.Frame(notebook)

        notebook.add(main_tab, text='Main')
        notebook.add(config_tab, text='Config')

        # TODO: add main control buttons to main tab here

        # Add stuff to Config tab
        self.create_com_port_frame(config_tab)
        self.create_log_level_dropdown(config_tab)
        save_layout_button = tk.Button(config_tab, text="Save Layout", command=self.save_current_pane_state)
        save_layout_button.pack(side=tk.BOTTOM, anchor='se', padx=5, pady=5)

    def add_title(self, frame, title):
        """Add a title label to a frame."""
        label = tk.Label(frame, text=title, font=("Helvetica", 10, "bold"))
        label.pack(pady=0, fill=tk.X)

    # saves data to file when button is pressed
    def save_current_pane_state(self):
        save_pane_states(frames_config, self.frames, self.main_pane)

    # gets data in save config file (as dict) and updates the global var of frames_config
    def load_saved_pane_state(self):
        savedData = load_pane_states()

        for i in range(len(frames_config)):
            if frames_config[i][0] in savedData:
                frames_config[i] = (frames_config[i][0], frames_config[i][1], savedData[frames_config[i][0]][0],savedData[frames_config[i][0]][1])
        savedData = load_pane_states()

        for i in range(len(frames_config)):
            if frames_config[i][0] in savedData:
                frames_config[i] = (frames_config[i][0], frames_config[i][1], savedData[frames_config[i][0]][0],savedData[frames_config[i][0]][1])

    def create_log_level_dropdown(self, parent_frame):
        log_level_frame = ttk.Frame(parent_frame)
        log_level_frame.pack(side=tk.TOP, anchor='nw', padx=5, pady=5)
        ttk.Label(log_level_frame, text="Log Level:").pack(side=tk.LEFT)

        self.log_level_var = tk.StringVar()
        log_levels = [level.name for level in LogLevel]
        log_level_dropdown = ttk.Combobox(log_level_frame, textvariable=self.log_level_var, values=log_levels, state="readonly")
        log_level_dropdown.pack(side=tk.LEFT, padx=(5, 0))
        log_level_dropdown.set(LogLevel.INFO.name) 
        log_level_dropdown.bind("<<ComboboxSelected>>", self.on_log_level_change)

    def on_log_level_change(self, event):
        selected_level = LogLevel[self.log_level_var.get()]
        self.messages_frame.set_log_level(selected_level)
        print(f"Log level changed to: {selected_level.name}")

    def create_subsystems(self):
        """Initialize subsystems in their designated frames using component settings."""
        self.subsystems = {
            'Vacuum System': subsystem.VTRXSubsystem(
                self.frames['Vacuum System'],
                serial_port=self.com_ports['VTRXSubsystem'], 
                logger=self.logger
            ),
            'Environmental [°C]': subsystem.EnvironmentalSubsystem(
                self.frames['Environmental'], 
                logger=self.logger
            ),
            'Visualization Gas Control': subsystem.VisualizationGasControlSubsystem(
                self.frames['Visualization Gas Control'], 
                logger=self.logger
            ),
            'Interlocks': subsystem.InterlocksSubsystem(
                self.frames['Interlocks'],
                com_ports = self.com_ports['Interlocks'],
                logger=self.logger,
                frames = self.frames
            ),
            'Oil System': subsystem.OilSubsystem(
                self.frames['Oil System'],
                logger=self.logger
            ), 
            'Cathode Heating': subsystem.CathodeHeatingSubsystem(
                self.frames['Cathode Heating'],
                com_ports=self.com_ports,
                logger=self.logger
            )
        }

    def create_messages_frame(self):
        """Create a frame for displaying messages and errors."""
        self.messages_frame = MessagesFrame(self.rows[4])
        self.rows[4].add(self.messages_frame.frame, stretch='always')
        self.logger = self.messages_frame.logger

    def create_com_port_frame(self, parent_frame):
        self.com_port_frame = ttk.Frame(parent_frame)
        self.com_port_frame.pack(side=tk.TOP, fill=tk.X, padx=5, pady=5)

        self.com_port_button = ttk.Button(self.com_port_frame, text="Configure COM Ports", command=self.toggle_com_port_menu)
        self.com_port_button.pack(side=tk.TOP, anchor='w')

        self.com_port_menu = ttk.Frame(self.com_port_frame)
        self.com_port_menu.pack(side=tk.TOP, fill=tk.X, expand=True)
        self.com_port_menu.pack_forget()  # Initially hidden

        self.port_selections = {}
        self.port_dropdowns = {}

        for subsystem in ['VTRXSubsystem', 'CathodeA PS', 'CathodeB PS', 'CathodeC PS', 'TempControllers', 'Interlocks']:
            frame = ttk.Frame(self.com_port_menu)
            frame.pack(fill=tk.X, padx=5, pady=2)
            ttk.Label(frame, text=f"{subsystem}:").pack(side=tk.LEFT)
            port_var = tk.StringVar(value=self.com_ports.get(subsystem, ''))
            self.port_selections[subsystem] = port_var
            dropdown = ttk.Combobox(frame, textvariable=port_var)
            dropdown.pack(side=tk.RIGHT)
            self.port_dropdowns[subsystem] = dropdown

        ttk.Button(self.com_port_menu, text="Apply", command=self.apply_com_port_changes).pack(pady=5)

    def toggle_com_port_menu(self):
        if self.com_port_menu.winfo_viewable():
            self.com_port_menu.pack_forget()
            self.com_port_button.config(text="Configure COM Ports")
        else:
            self.update_available_ports() 
            self.com_port_menu.pack(after=self.com_port_button, fill=tk.X, expand=True)
            self.com_port_button.config(text="Hide COM Port Configuration")

    def update_available_ports(self):
        available_ports = [port.device for port in serial.tools.list_ports.comports()]
        for dropdown in self.port_dropdowns.values():
            current_value = dropdown.get()
            dropdown['values'] = available_ports
            if current_value in available_ports:
                dropdown.set(current_value)
            elif available_ports:
                dropdown.set(available_ports[0])
            else:
                dropdown.set('')

    def apply_com_port_changes(self):
        new_com_ports = {subsystem: var.get() for subsystem, var in self.port_selections.items()}
        self.update_com_ports(new_com_ports)
        self.toggle_com_port_menu()

    def update_com_ports(self, new_com_ports):
        self.com_ports = new_com_ports
        # TODO: update the COM ports for each subsystem

        for subsystem_name, subsystem in self.subsystems.items():
            if hasattr(subsystem, 'update_com_port'):
                if subsystem_name == 'Vacuum System':
                    subsystem.update_com_port(new_com_ports.get('VTRXSubsystem'))
                elif subsystem_name == 'Cathode Heating':
                    subsystem.update_com_ports(new_com_ports)
            else:
                self.logger.warning(f"Subsystem {subsystem_name} does not have an update_com_port method")
        self.logger.info(f"COM ports updated: {self.com_ports}")

    def _check_for_port_changes(self):
        nowPorts = set(serial.tools.list_ports.comports())

        if self.num_ports != len(nowPorts):

            self.num_ports = len(nowPorts)
            # should be a list of ListPortIO objects
            dif = self.set_com_ports - nowPorts
            print(self.set_com_ports, nowPorts)

            for port in dif:
                print("HERER")
                if port.serial_number in self.PORT_INFO:
                    if port in nowPorts:
                        self._check_for_port_changes(self.PORT_INFO[port.serial_number], port)
                    else:
                        self._check_for_port_changes(self.PORT_INFO[port.serial_number])
                        
        self.root.after(500, self._check_for_port_changes)

    def _update_com_ports(self, subsystem, port=None):
        print(subsystem)

        if subsystem in self.subsystems.keys():
            if hasattr(subsystem, 'update_com_port'):
                if subsystem == 'Vacuum System':
                    self.subsystems[subsystem].update_com_port(subsystem.get('VTRXSubsystem'))
                elif subsystem == 'Cathode Heating':
                    self.subsystems[subsystem].update_com_ports(subsystem)
                elif subsystem == "Interlocks":
                    print("123")
                    self.subsystems["Interlocks"].update_com_port(subsystem, port)
            
            else:
                self.logger.warning(f"Subsystem {subsystem} does not have an update_com_port method")
        self.logger.info(f"COM ports updated: {self.com_ports}")

