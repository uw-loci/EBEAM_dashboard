import serial
import threading
import time
from utils import LogLevel
import os
from subsystem import interlocks

# Ask electronics team if the G9 is storing the data that it is reading from sensors or if it is just checking 
# if it is just checking we will have to figure out how to read that data thur the G9, to display on GUI

# Ask if we need to communicate the status should be also end the the power supplies 

# Ask what the unwritten area of response data should be (0s or Fs, or random)

# Ask him what he says that we don't understand 

# What configuration data in the G9SP configuration data from the config program
# - system settings, saftey program I/O terminal settings

# what does the PLC mean in the manual refer to? Our program? or something else?
inStatus = {
    0: "No error",
    1: "Invalid configuration",
    2: 'External test signal failure',
    3: 'Internal circuit error',
    4: 'Discrepancy error',
    5: 'Failure of the associated dual-channel input'
}

outStatus = {
    0: 'No error',
    1: 'Invalid configuration',
    2: 'Overcurrent detection',
    3: 'Short circuit detection',
    4: 'Stuck-at-high detection',
    5: 'Failure of the associated dual-channel output',
    6: 'Internal circuit error',
    8: 'Dual channel violation'
}

usStatus = {
    32: "Output Power Supply Error Flag",
    64: "Safety I/O Terminal Error Flag",
    512: "Function Block Error Flag"
}

class G9Driver:


    #TODO: Return to this and check if these parms are good by default
    def __init__(self, port, baudrate=9600, timeout=0.5, logger=None, debug_mode=False):
        self.ser = serial.Serial(port, baudrate, timeout=timeout)
        self.debug_mode = debug_mode
        self.logger = logger
        self.lastResponse = None
        self.msgOptData = None


    #TODO: send query for data
    #TODO: decided if we want to store command args in here (like with a dict) or if we should do it in the callee file
    def sendCommand(self):
        # TODO: frontend topic : decided how we want to display the exception
        if not self.is_connected():
            raise ConnectionError("Seiral Port is Not Open.")
        query = b'\x40\x00\x00\x0F\x4B\x03\x4D\x00\x01' # could also use bytes.fromhex() method in future for simplicity
        data = data.ljust(6, b'\x00')[:6]
        self.msgOptData = data
        checksum_data = query + data
        checksum = self.calculate_checksum(checksum_data)
        footer = b'\x2A\x0D' # marks the end of the command 
        self.ser(query + data + checksum + footer)

        self.response()

    # used mainly for the check sum but can also be used to check for error flags
    # needs an input of a byte string and the range of bytes that need to be sum
    # will return the sum of the bytes in the a byte string in the form of b'\x12'
    def calculate_checksum(byteString, startByte, endByte):
        assert isinstance(byteString, bytes)
        return sum(byteString[startByte:endByte + 1]).to_bytes(1, "big") 

    # helper function to convert bytes to bits for checking flags
    # not currently being used but many be helpful in the future for getting errors
    def bytesToBinary(byte_string):
        return ''.join(format(byte, '08b') for byte in byte_string)
    
    # this method is made to check the error flags, right not only checks the last 13 bits
    # of a byte string
    def checkFlags13(self, byteString, startByte, endByte, inputs, norm = 1):
        assert isinstance(byteString, bytes)
        # this is for if we only need the last 13 bits (more or less hardcoding this 
        # just including the rest if it might be helpful in the future
        if inputs == -1:
            if sum(byteString[-1] >= 13):
                # all flags we care about are 1
                return True
            else:
                # there is an error
                return False


    #TODO: async function, waiting for responce from query
    #TODO: how do we want to handle the data 
    def response(self):
        if not self.is_connected():
            raise ConnectionError("Seiral Port is Not Open.")
        
        data = self.ser.read(size=198)
        self.lastResponse = data
        if len(data) == 198:
            OCTD = data[0:4]
            if OCTD != self.msgOptData:
                raise ValueError("Optional Transmission data doesn't match data sent to the G9SP")

            # TODO: Need to add SITDF functionality
            SITDF = data[4:10]           


            SOTDF = data[10:14]
            SOTDFBits = self.bytesToBinary(SOTDF)

            # Dictionary with status
            interlocks_status = self.SOTDF_Reading(SOTDFBits) 

            SITSF = data[14:20]
            SOTSF = data[20:24]
            if not self.checkFlags13(SITSF):
                if self.safetyInTerminalError(SITSF):
                    raise ValueError("Error was detected but was not found")
            if not self.checkFlags13(SOTSF):
                if self.safetyOutTerminalError(SOTSF):
                    raise ValueError("Error was detected but was not found")
                
            # TODO: Need to add error cause

            # US - Unit Status
            US = data[66:68]
            if US != 0:
                if self.unitStateError(US):
                    raise ValueError("Error was detected in Unit State. Could be more than one")
                
            
            # TODO: Need to add error log
            errorLog = data[108:148]

            # TODO: Need to add operation log
            operationLog = data[148:198]
                


        else:
            self.sendCommand()

        pass


    """
    0: No error
    1: Invalid configuration
    2: External test signal failure
    3: Internal circuit error
    4: Discrepancy error
    5: Failure of the associated dual-channel input
    """

    # Retrieves status from S01-S12 and returns sensor status
    def SOTDF_Readings(SOTDFBits):

        #Reversing bits 
        data = SOTDFBits[::-1]

        interlocks_status = { 
        
        "E-Stop Int" : bool(int(data[0])) and bool(int(data[1])), #checking if both 2B and 2A return 1
        "E-Stop Ext" :  bool(int(data[2])) and bool(int(data[3])), #checking if both 2B and 2A return 1

        "Door Status" : bool(int(data[4])),
        "Door Lock" : bool(int(data[5])),

        "Vacuum Power" : bool(int(data[6])),
        "Vacuum Pressue" : bool(int(data[7])),

        "Oil High" : bool(int(data[8])),
        "Oil Low" : bool(int(data[9])),

        "Water" : bool(int(data[10])),

        # HV status relay
        "G9SP_Active" : bool(int(data[11])), 

        # Reset\Enable has an output sensor but should only be active if ALL other incoming states are true
        "Reset\Enable Button" : bool((data[12]))
        }


        return interlocks_status

    # checks all the SITSFs, throws error is one is found
    def safetyInTerminalError(self, data, inputs=13):
        if len(data) < inputs:
            raise ValueError(f"Expected at least {inputs} bytes, but received {len(data)}.")

        last_bytes = data[-inputs:]
        last_bytes = last_bytes[::-1]

        for i, byte in enumerate(last_bytes):
            msb = byte >> 4  # most sig bits
            lsb = byte & 0x0F  # least sig bits

            # check high bits for errors
            if msb in inStatus and msb != 0:
                raise ValueError(f"Error at byte {i}H, MSB: {inStatus[msb]} (code {msb})")
            # check low bits for errors
            if lsb in inStatus and lsb != 0:
                raise ValueError(f"Error at byte {i}L, LSB: {inStatus[lsb]} (code {lsb})")
        return True
        


    """
    0: No error
    1: Invalid configuration
    2: Overcurrent detection
    3: Short circuit detection
    4: Stuck-at-high detection
    5: Failure of the associated dual-channel output
    6: Internal circuit error
    8: Dual channel violation
    """

    # checks all the SOTSFs, throws error is one is found 
    def safetyOutTerminalError(self, data, inputs = 13):
        if len(data) < inputs:
            raise ValueError(f"Expected at least {inputs} bytes, but received {len(data)}.")

        # only keep needs bytes
        last_bytes = data[-inputs:]
        # flip direction so enumerate can if us the byte number in the error
        last_bytes = last_bytes[::-1]

        for i, byte in enumerate(last_bytes):
            msb = byte >> 4  # most sig bits
            lsb = byte & 0x0F  # least sig bits

            # check high bits for errors
            if msb in outStatus and msb != 0:
                raise ValueError(f"Error at byte {i}H, MSB: {outStatus[msb]} (code {msb})")
            # check low bits for errors
            if lsb in outStatus and lsb != 0:
                raise ValueError(f"Error at byte {i}L, LSB: {outStatus[lsb]} (code {lsb})")
        return True
    
    """
    32: Output Power Supply Error Flag
    64: Safety I/O Terminal Error Flag
    512: Function Block Error Flag
    """
    
    # rn am hoping that only one of the error flags can be set at a time
    def unitStateError(self, data):
        if len(data) != 2:
            raise ValueError(f"Expected at least 2 bytes, but received {len(data)}.")
        
        er = sum(data)
        
        if er in usStatus:
            raise ValueError(f"Unit State Error: {usStatus[er]} (code {er})")
        return True

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
