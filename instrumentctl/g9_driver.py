import serial
import threading
import time
from utils import LogLevel
import os
from subsystem import interlocks

# Ask nerd team if the G9 is storing the data that it is reading from sensors or if it is just checking 
# if it is just checking we will have to figure out how to read that data thur the G9, to display on GUI

# Ask if we need to communicate the status should be also end the the power supplies 

# Ask what the unwritten area of response data should be (0s or Fs, or random)

# Ask him what he says that we don't understand 

# What configuration data in the G9SP configuration data from the config program
# - system settings, saftey program I/O terminal settings

# what does the PLC mean in the manual refer to? Our program? or something else?

class G9Driver:
    #TODO: Return to this and check if these parms are good by default
    def __init__(self, port, baudrate=9600, timeout=0.5, logger=None, debug_mode=False):
        self.ser = serial.Serial(port, baudrate, timeout=timeout)
        self.debug_mode = debug_mode
        self.logger = logger

    #TODO: send query for data
    #TODO: decided if we want to store command args in here (like with a dict) or if we should do it in the callee file
    def sendCommand(self):
        # TODO: frontend topic : decided how we want to display the exception
        if not self.is_connected():
            raise ConnectionError("Seiral Port is Not Open.")
        query = b'\x40\x00\x00\x0F\x4B\x03\x4D\x00\x01' # could also use bytes.fromhex() method in future for simplicity
        footer = b'\x2A\x0D' # marks the end of the command 
        data = data.ljust(6, b'\x00')[:6]
        checksum_data = query + data
        checksum = self.calculate_checksum(checksum_data)
        

        self.response()

    def calculate_checksum(data):




    #TODO: async function, waiting for responce from query
    #TODO: how do we want to handle the data 
    def response(self):
        pass



    #TODO: make a method that is constantly running to be pulling data all the time. 
    def run(self):
        if self.is_connected():
            # call sendCommand to get G9 to send new data
            self.sendCommand()

            time.sleep(0.)
    #TODO: Check to see if the G9 switch is allowing high Voltage or not
    # this function will need to be constantly sending requests/receiving to check when the high voltage is off/on
    def checkStatus():
        pass

    def flush_serial(self):
        self.ser.reset_input_buffer()    # flushes the input buffer to rid of unwanted bits


    #TODO: make funtion to turn all interlocks to red
    def is_connected(self):
        try:
            #TODO: check if this works with G9 copied from Power Supply Driver
            # Attempt to write a simple command to the device
            self.ser.write(b'\r')  # Send a carriage return
            # Try to read a response (there might not be one)
            self.ser.read(1)

            self.isConnected = True
            return True
        except serial.SerialException:
            return False
        

    #TODO: Figure out how to handle all the errors (end task)