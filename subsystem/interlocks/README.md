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
### Description
__init__() - constructor 
The constructor method of the InterlocksSubsystem Class initializes the key components of the interlocks subsystem, including establishing a communication with the G9 driver, as well as setting up error handling, error counts, polling intervals, GUI elements, and indicator controllers. 

#### Parameters:

1) parent: The parent container refers to the main window that houses all the subsystem components including the interlocks GUI. This attribute structures all the GUI components (subsystems) and places them correctly on the application window. 

2) com_ports: The COM ports are used to connect with the G9 driver. Enables serial port communications to monitor the status of the interlocks. 

3) logger: for handling messages and reporting errors throughout the subsystem. Utilized for structured logging purposes to constantly monitor all the 

4) frames: GUI element that enables us to integrate the interlocks subsystem into a larger GUI application. 


#### Constructor Attributes and Initialization:

self.parent: stores reference to the parent component of the entire dashboard that contains all the subsystems as individual GUI components. 
self.logger: stores reference to the logger object that logs all the messages at different levels (INFO, ERROR, and WARNING), defaults to “None” if not provided.
self.last_error_time: Tracks the timestamps of the last error that occurred which occurred while establishing communication with the G9 Driver. 
self.error_count: Counts the consecutive number of errors.
self.update_interval: Sets the initial interval (in milliseconds) between each data update or polling cycle. The default interval is 500 ms, allowing for frequent status checks while avoiding overloading the system.
self.max_interval: Sets the maximum allowable interval for data updates to be 5000. Acts as a ceiling value for the polling interval, prevents it from crossing this value even if consecutive errors are thrown. Maintains responsiveness and prevents data overload.  
self.driver:  this attribute is set to an instance of the G9Driver class in the g9_driver module, if the comPorts are valid. Set to none if instantiation of the driver object fails.

self.parent.after: the constructor schedules the data polling cycle, which primarily calls the update_data() method to fetch and display all the interlock statuses. 
update_data()
Regularly fetches the current interlock statuses using the G9 driver and updates the GUI indicators to reflect real-time conditions. Handles communication errors, adjusts polling intervals dynamically, and ensures safe operations through error management and logging.

The data for the interlocks is updated separately based on whether the interlocks have a single-input or a dual-input. 

For the interlocks having dual-inputs, we iterate through the first three pairs. We first evaluate the (safety) sitsf bits and the data (status input terminal data flags) bits by combining the two inputs per each interlock and using the bitwise pair AND. We further update the GUI indicators for each of these interlock pairs. 

For the interlocks having single-inputs, we iterate through the remaining interlocks ranging from 6 to 12. We directly evaluate the safety and the data associate with their respective single inputs. We further update the GUI for these interlocks as well.



setup_gui()
This method sets up the graphical user interface for the interlock subsystems, creating individual light indicators for each of the interlocks. This helps us ensure better readability and usability of all the light indicators. 
_adjust_update_interval()
Dynamically adjusts the interval between data updates based on communication success or failure. Uses exponential backoff for consecutive errors to prevent overloading the system and restores the default interval after successful communication. Ensures responsiveness while avoiding performance degradation during failures.
update_com_port()
Updates the communication port for the G9 driver. Tests the connection to ensure the new port is functional and updates the driver object. Logs any issues encountered during the update process and sets all indicators to red if the update fails.
update_interlock()
Updates the color of a specific interlock indicator based on its safety and data status. Logs any changes to the indicator's state and ensures accurate visualization of the interlock's condition in the GUI.

** We make dynamic updates to the color of the indicators for better optimization. 
log()







