## Overview:
The interlocks.py script primarily focuses on implementing the GUI for the Safety Interlock Controller to monitor all the interlock statuses which are safety checks to encourage safe use of the 3-D metal printer. This script utilizes the g9 driver to communicate with the G9SP Safety Interlock Controller, retrieving all the interlock statuses, and displaying them in real-time on the GUI.


## Requirements:
### Dependencies: 

Tkinter: For the GUI development

instrumentctl.g9_driver: Driver file for establishing communication with the Safety Interlock Controller.

utils.LogLevel: For logging all the error responses.

### Code Structure:

The interlocks file consists of the InterlocksSubsystem class. It utilizes:

A dictionary called “INPUTS” that maps all the bit positions to specific interlocks. Each of the keys in the dictionary represents the interlock bit positions, while the values of the keys describe their respective functions. 

The “INDICATORS” dictionary contains the Tkinter indicator components for each of the interlocks. 

## Methods
### __init__():
    Initializes needed components for the interlocks subsystem to run:
    Sub Panel:
        - Creates a frame with a grid of all interlocks and labels (calls setup_gui())

    G9Driver:
        - When called with a COM port creates a G9 Driver Object.

### update_com_port(com_port):
    Called from dashboard if the COM port for the G9 needs to be changed. When called will either define a new G9Driver object (if COM port arg is not None), or will set all indicators to red, meaning COM port arg is None

### _adjust_update_interval(sucess):
    Will change the interval scheudling to allow more time if the G9 slow to respond.

    Sucess is True - shortern interval if possible (min 500 ms)

    Sucess if False - Lengthen interval if possible (max 5000 ms)

### setup_gui(), _create_main_frame(), _create_interlocks_frame(), _create_indicator_circle, _create_indicators():
    All of these are used to define the objects in the Tkinter frame

### update_interlock(color)
    Changes a interlock to the given color in the color arg
    

### update_data()
    Main method that interacts with the G9Driver. Calls the driver to pull data from G9, then parses the data and updates the interlocks to reflect the current status. Calls update_interlock(), with any changes that need to be made.

### Expected Data

sitsf_bits - These should always be 1s, if they are not their should be an error being raised, or an input is off
sitdf_bits - First 11 bits repersent the interlocks, where 1 means good and 0 indicates an off/error, bit 12 repersents the HVOLT which 0 indicates good/error and 1 indicates off, bit 13 represents the enable button's state(thus need to look at the output data so see if that buttom was pressed)
g9_active - bit 4 of the output data that indicates weather the g9 enable buttom had been pressed previously








