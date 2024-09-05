# EBEAM System Dashboard Software

### 1. Development Workflow
![branching](https://github.com/mslaffin/EBEAM_dashboard/blob/main/media/branching_diagram.png)
#### Branching strategy
All code development intended to impact a future release is done on the latest `develop` branch. This applies to new instrument features, bug fixes, etc. The `develop` branch is **not stable**.
The `main` branch contains the latest production code.

#### Development Process 
Install requirements.
Navigate to your project directory:
```
cd project_directory_location
```
Create a virtual environment:
```
python -m venv venv
```
Activate the virtual environment (assuming on Windows):
```
venv\Scripts\activate
```
Install the requirements:
```
pip install -r requirements.txt
```
Run the main application:
```
python main.py
```

Create a new branch from develop for your feature or bug fix:

```
git checkout develop
git pull origin develop
git checkout -b feature/your-feature-name
```
Make your changes and commit:
```
git add changedfile.py
git commit -m "Descriptive commit message"
```

Push your branch to GitHub:
```
git push origin feature/your-feature-name
```

Create a "New pull request".
Set the base branch to develop and compare branch to your feature branch.
Fill in the PR template with a description of your changes, any related issues, and testing performed.

Assign reviewers to your PR. Merge.

### 2. Executable Build Instructions
```
git clone https://github.com/mslaffin/EBEAM_dashboard.git
```
```
cd EBEAM_dashboard
```
```
python -m PyInstaller EBEAM_DASHBOARD.spec
```


### 3. Architecture

- **Language & Libraries**: Python, using the [Tkinter](https://docs.python.org/3/library/tkinter.html) interface for the GUI, [matplotlib](https://matplotlib.org/) for plotting, and [Pyserial](https://pythonhosted.org/pyserial/) for communication with external systems through virtual COM ports.
- **High-level Design**: The application is divided into several modules:
  - **main.py**: Manages the main application startup and configuration.
  - **dashboard.py**: Handles the main user interface and dashboard setup.
  - **instrumentctl/**: Instrument specific command libraries.
  - **subsystem/**: Contains classes and methods to manage individual subsystems (e.g., VTRXSubsystem, EnvironmentalSubsystem).
  - **utils.py**: Utility functions and classes that support the main application (Logging, setup scripts, etc.).
  - Core Structure:
```
EBEAM_DASHBOARD/
├── __init__.py 
├── dashboard.py
├── instrumentctl/
│   ├── __init__.py
│   ├── apex_mass_flow_controller.py
│   └── power_supply_9014.py
├── main.py
├── subsystem/
│   ├── __init__.py
│   ├── cathode_heating.py
│   ├── environmental.py
│   ├── interlocks.py
│   ├── oil_system.py
│   ├── visualization_gas_control.py
│   └── vtrx.py
└── utils.py
```

### 4. Components

- **Main Application (main.py)**:
  - **Configuration Loader**: Responsible for initial configurations, setting up COM ports, and starting the main dashboard.
  - **COM Port Configuration**: Dynamically detects and assigns COM ports for various hardware interfaces. TODO: Write dropdowns for additional subsystems.

- **Instrument Control (instrumentctl.py)**:
  - **Equipment specific driver libraries**:
    - 9104 Cathode Heating Power Supplies [(datasheet)](https://bkpmedia.s3.us-west-1.amazonaws.com/downloads/programming_manuals/en-us/9103_9104_programming_manual.pdf) IN PROGRESS
    - E5CN Cathode Temperature Controller [(datasheet)]() IN PROGRESS
    - Apex Mass Flow Controller [(datasheet)]() IN PROGRESS
    - TODO: Agilent 33120A [(datasheet)]()
    - TODO: Quantum 9530
    - TODO: G9SP serial option (status door, e-stops, vac, levels, timer)
    - VTRX system
    - TODO: Temp monitor
    - TODO: A655sc
    - TODO: BOP-100-2ML

### 5. Dashboard (dashboard.py)

- **EBEAMSystemDashboard Class**: The main class that sets up the dashboard interface.
  - **`setup_main_pane`**: Initializes the main layout pane and its rows.
  - **`create_frames`**: Creates frames for different systems and controls within the dashboard.
  - **`create_messages_frame`**: Creates a frame for displaying messages and errors.
  - **`create_subsystems`**: Initializes subsystems in their designated frames using component settings.

### 5. Subsystems

- **`vtrx.py`**:
  - Manages the VTRX system, including serial communication and GUI updates.
  - Handles pressure data and switch states, updating the GUI in real-time.
  - Logs messages and errors to the messages frame.

- **`environmental.py`**:
  - Monitors and displays temperature data from various thermometers.
  - Uses Matplotlib to create bar charts for temperature visualization.

- **`visualization_gas_control.py`**:
  - Controls the Argon bleed system via serial communication.
  - Provides GUI buttons for taring flow and absolute pressure.

- **`interlocks.py`**:
  - Manages the status of various interlocks (e.g., Vacuum, Water, Door).
  - Updates GUI indicators based on interlock status.

- **`oil_system.py`**:
  - Monitors and displays oil temperature and pressure.
  - Uses a vertical temperature gauge and a dial meter for pressure visualization.

### 6. Utilities (`utils.py`)

- **MessagesFrame Class**:
  - A custom Tkinter frame for displaying messages and errors.
  - Supports logging messages with timestamps and trimming old messages to maintain a maximum number of lines.

- **TextRedirector Class**:
  - Redirects stdout to a Tkinter Text widget.
  - Ensures that all print statements in the application are displayed in the messages frame.

- **SetupScripts Class**:
  - Manages the selection and execution of configuration scripts.
  - Provides a GUI for selecting scripts from a dropdown menu and executing them.

### 7. Flowchart
![Application architecture](https://github.com/mslaffin/EBEAM_dashboard/blob/main/media/CCS_GUI_flowchart.png)
