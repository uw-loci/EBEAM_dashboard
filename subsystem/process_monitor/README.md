## Overview

`process_monitor.py` aims to visualize real-time temperature data of different sensors (

**Solenoid 1**, **Solenoid 2**, **Chamber Bot**, **Chamber Top**, **Air temp**) using the GUI. It

communicates with the DP16_process_monitor.py in order to retrieve information from the 

`temperature` dictionary retuned by the read_temperatures method in the driver file 

(DP16_process_monitor.py). 




## Key Components

This application mainly consists of the following key components -

- **TemperatureBar Class**: The `TemperatureBar Class` is responsible for creating and updating the 

visual representation of temperature data for each sensor. It instantiates a constructor that 

inherits from tk.canvas and sets the attributes - name, height, width, bar_width, and value. The 

update_value method within this class is called with the updated temperatures of all the units. It 

is mainly called on the bar corresponding to the sensor whose temperature is to be updated. Upon 

being called, the bar for that particular sensor is deleted and a new bar is recreated which is 

scaled and colored based on the updated temperatures returned by the temp_bars disctionary. 



- **ProcessMonitorSusbsystem Class**: 



- **DP16_process_monitor.py**:




## Flow Chart for process_monitor.py