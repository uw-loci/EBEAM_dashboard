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
            #TODO: throw an exception so the program does has to handle the serial connection
            raise 
        
        query = f'{b'400000F4B034D0001'}'


    #TODO: async function, waiting for responce from query
    #TODO: how do we want to handle the data 
    def response():
        pass


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