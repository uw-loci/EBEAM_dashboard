## Overview

`process_monitor.py` aims to visualize real-time temperature data of different sensors (**Solenoid 1**, **Solenoid 2**, **Chamber Bot**, 

**Chamber Top**, **Air temp**) using the GUI. It communicates with the DP16_process_monitor.py in order to retrieve information from the 

`temperature` dictionary retuned by the read_temperatures method in the driver file (DP16_process_monitor.py). 


&nbsp;



## Dependencies Utilized:

- **Tkinter** : For the GUI development

- **matplotlib** : For plotting graphs

    - **FigureCanvasTkAgg** : To embed Matplotlib figures in Tkinter.

    - **Normalize**: To normalize the data for color mapping. 

- **instrumentctl.DP16_process_monitor.DP16_process_monitor**: For interfacing with the DP16 process monitor. 




&nbsp;



## Key Components - Main Code Structure

This application mainly consists of the following key components -

- **TemperatureBar Class**: The `TemperatureBar Class` is responsible for creating and updating the visual representation of temperature data for each sensor. It instantiates a constructor that inherits from tk.canvas and sets the attributes - name, height, width, bar_width, and value. The update_value method within this class is called with the updated temperatures of all the units. It is mainly called on the bar corresponding to the sensor whose temperature is to be updated. Upon being called, the bar for that particular sensor is deleted and a new bar is recreated which is scaled and colored based on the updated temperatures returned by the temp_bars disctionary. 



- **ProcessMonitorSusbsystem Class**: The `ProcessMonitorSubsystem Class` is responsible for calling the parent tkinter frame. It instantiates a DP16ProcessMonitor object. If the DP16Monitor object fails to connect via the RS-485 port, i.e., if the connect method in the `DP16_process_monitor` class fails to execute, the logger throws a warning message mentioning the same. 

    The `setup_gui` method within this class is responsible for the initial setup of the GUI. It instantiates and places the TemperatureBar objects          within the parent frame for readily displaying the real-time temperature status of the monitored units, when the class is instantiated. 

    The `update_temperatures` method within this class communicates with the driver file to retrieve the updated temperatures of all the units. The retireved temperatures are stored in the form of a dictionary with the key corresponding to the unit numbers of the sensors and the value correcponding to their respective temperatures. The `thermometer_maps` dictionary, initialized within the constructor, is utilized to retrieve the name of the sensor corresponding to the particular unit numbers. The bar graph for that particular sensor is then updated to the new temperature value retrieved from the driver file. 



- **DP16_process_monitor.py**:




&nbsp;



## Flow Chart for process_monitor.py
