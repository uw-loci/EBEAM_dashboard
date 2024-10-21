import serial
import threading
import time
# from utils import LogLevel
import os
# from subsystem import interlocks

class G9Driver:
    NUMIN = 13

    SNDHEADER = b'\x40\x00\x00\x0F\x4B\x03\x4D\x00\x01' 
    SNDDATA = b'\x00\x00\x00\x00'
    SNDRES = b'\x00\x00'

    RECHEADER = b'\x40\x00\x00'

    FOOTER = b'\x2A\x0D'

    US_OFFSET = 73  
    SITDF_OFFSET = 11  
    SOTDF_OFFSET = 17  
    SITSF_OFFSET = 21  
    SOTSF_OFFSET = 27 

    IN_STATUS = {  
        0: "No error",  
        1: "Invalid configuration",  
        2: 'External test signal failure',  
        3: 'Internal circuit error',  
        4: 'Discrepancy error',  
        5: 'Failure of the associated dual-channel input'  
    }  

    OUT_STATUS = {
    0: 'No error',
    1: 'Invalid configuration',
    2: 'Overcurrent detection',
    3: 'Short circuit detection',
    4: 'Stuck-at-high detection',
    5: 'Failure of the associated dual-channel output',
    6: 'Internal circuit error',
    8: 'Dual channel violation'
}

    US_STATUS = {
    9: "Output Power Supply Error Flag",
    10: "Safety I/O Terminal Error Flag",
    13: "Function Block Error Flag"
    }  

    def __init__(self, port=None, baudrate=9600, timeout=0.5, logger=None, debug_mode=False):
        # not sure if we will need all of these but just adding them now in case
        self.US, self.SITDF, self.SITSF, self.SOTDF, self.SOTSF, self.lastResponse = None, None, None, None, None, None

        if port:  
            self.ser = serial.Serial(  
            port=port,  
            baudrate=baudrate,  
            parity=serial.PARITY_EVEN,  
            stopbits=serial.STOPBITS_ONE,  
            bytesize=serial.EIGHTBITS,  
            timeout=timeout  
            )  
        else:  
            self.ser = None

        self.debug_mode = debug_mode
        self.logger = logger
        self.input_flags = []

    def send_command(self):
        if not self.is_connected():
            raise ConnectionError("Seiral Port is Not Open.")

        checksum = self.calculate_checksum(self.SNDHEADER + self.SNDDATA + self.SNDRES, 0 , len(self.SNDHEADER + self.SNDDATA))

        self.ser.write(self.SNDHEADER + self.SNDDATA + self.SNDRES + checksum + self.FOOTER)

        self.response()

    # used mainly for the check sum but can also be used to check for error flags
    # needs an input of a byte string and the range of bytes that need to be sum
    # will return the sum of the bytes in the a byte string in the form of b'\x12'
    def calculate_checksum(self, byteString, startByte, endByte):
        assert isinstance(byteString, bytes)
        return sum(byteString[startByte:endByte + 1]).to_bytes(2, "big") 

    # helper function to convert bytes to bits for checking flags
    # not currently being used but many be helpful in the future for getting errors
    def bytes_to_binary(self, byte_string):
        return ''.join(format(byte, '08b') for byte in byte_string)
    
    # this method is made to check the error flags, right not only checks the last 13 bits
    # of a byte string
    def check_flags13(self, byteString, norm = '1'):
        assert isinstance(byteString, bytes)
        binary_string = self.bytes_to_binary(byteString)[-self.NUMIN:]
        string_of_ones = norm * self.NUMIN
        return binary_string == string_of_ones
    
    def response(self):
        if not self.is_connected():
            raise ConnectionError("Serial Port is Not Open.")
        
        data = self.ser.read_until(self.FOOTER)
        self.lastResponse = data

        # Indexing such that we don't return an integer
        if data[0] == b'\x40':
            if data[3] == b'\xc3':
                alwaysHeader = data[0:3]
                alwaysFooter = data[-2:]
                if alwaysHeader != self.RECHEADER or alwaysFooter != self.FOOTER:
                    raise ValueError("Always bits are incorrect")
                
                # Save all the msg data so backend can access before checking for errors
                self.US = data[self.US_OFFSET:self.US_OFFSET + 2]          # Unit Status
                self.SITDF = data[self.SITDF_OFFSET:self.SITDF_OFFSET + 6] # Input Terminal Data Flags
                self.SITSF = data[self.SITSF_OFFSET:self.SITSF_OFFSET + 6] # Input Terminal Status Flags
                self.SOTDF = data[self.SOTDF_OFFSET:self.SOTDF_OFFSET + 4] # Output Terminal Data Flags
                self.SOTSF = data[self.SOTSF_OFFSET:self.SOTSF_OFFSET + 4] # Output Terminal Status Flags

                # Unit status
                if self.US != b'\x00\x01':
                    if self.unit_state_error(self.US):
                        raise ValueError("Error was detected in Unit State but was not identified. Could be more than one")

                # Input Terminal Data Flags (1 - ON 0 - OFF)
                if not self.check_flags13(self.SITDF):
                    err = []
                    gates = self.bytes_to_binary(self.SITDF[-3:])
                    for i in range(20):
                        if gates[-i + 1] == "0":
                            err.append(i)
                    self.input_flags = gates
                    raise ValueError(f"An input is either off or throwing an error: {err}")

                # Input Terminal Status Flags (1 - OK 0 - OFF/ERR)
                if not self.check_flags13(self.SITSF):
                    # if error dected checkout terminal error cause
                    if self.safety_in_terminal_error(data[31:55][-10:]):
                        raise ValueError("Error was detected in inputs but was not found")
                       
                # Output Terminal Data Flags (1 - ON 0 - OFF)
                if not self.check_flags13(self.SOTDF):
                    err = []
                    gates = self.bytes_to_binary(self.SOTDF[-3:])
                    for i in range(self.NUMIN):
                        if gates[-i + 1] == "0":
                            err.append(i)
                    raise ValueError(f"There is output(s) off: {err}")
                
                # Output Terminal Status Flags (1 - OK 0 - OFF/ERR)
                if not self.check_flags13(self.SOTSF):
                    if self.safety_out_terminal_error(data[55:71][-10:]):
                        raise ValueError("Error was detected in outputs but was not found")
                    
                # Optional Communication data 
                OCTD = data[7:11]
                if OCTD != self.SNDDATA:
                    raise ValueError("Optional Transmission data doesn't match data sent to the G9SP")
                
                # # TODO: Need to add error log
                # errorLog = data[108:149]

                # # TODO: Need to add operation log
                # operationLog = data[148:199]
                    
            else:
                raise ValueError("Response length was not OxC3, either an error or command formate invalid.")

    """
    0: No error
    1: Invalid configuration
    2: External test signal failure
    3: Internal circuit error
    4: Discrepancy error
    5: Failure of the associated dual-channel input
    """
    # checks all the SITSFs, throws error is one is found
    def safety_in_terminal_error(self, data):
        if len(data) != 10:
            raise ValueError(f"Expected 24 bytes, but received {len(data)}.")

        last_bytes = data[-self.NUMIN:]
        last_bytes = last_bytes[::-1]

        for i, byte in enumerate(last_bytes):
            msb = byte >> 4  # most sig bits
            lsb = byte & 0x0F  # least sig bits

            # check high bits for errors
            if msb in self.IN_STATUS and msb != 0:
                raise ValueError(f"Error at byte {i}H, MSB: {self.IN_STATUS[msb]} (code {msb})")
            # check low bits for errors
            if lsb in self.IN_STATUS and lsb != 0:
                raise ValueError(f"Error at byte {i}L, LSB: {self.IN_STATUS[lsb]} (code {lsb})")
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
    def safety_out_terminal_error(self, data):
        if len(data) != 10:
            raise ValueError(f"Expected 16 bytes, but received {len(data)}.")

        # only keep needs bytes
        last_bytes = data[-self.NUMIN:]
        # flip direction so enumerate can if us the byte number in the error
        last_bytes = last_bytes[::-1]

        for i, byte in enumerate(last_bytes):
            msb = byte >> 4  # most sig bits
            lsb = byte & 0x0F  # least sig bits

            # check high bits for errors
            if msb in self.OUT_STATUS and msb != 0:
                raise ValueError(f"Error at byte {i}H, MSB: {self.OUT_STATUS[msb]} (code {msb})")
            # check low bits for errors
            if lsb in self.OUT_STATUS and lsb != 0:
                raise ValueError(f"Error at byte {i}L, LSB: {self.OUT_STATUS[lsb]} (code {lsb})")
        return True
    
    """
    bit position: error
    0: Normal Operation Error Flag
    9: Output Power Supply Error Flag
    10: Safety I/O Terminal Error Flag
    13: Function Block Error Flag
    """
    
    # rn am hoping that only one of the error flags can be set at a time
    def unit_state_error(self, data):
        if len(data) != 2:
            raise ValueError(f"Expected 2 bytes, but received {len(data)}.")
        
        bits = self.bytes_to_binary(data)

        for k in self.US_STATUS.keys():
            if bits[-(k + 1)] == "1":
                raise ValueError(f"Unit State Error: {self.US_STATUS[k]} (bit {k})")
            
        if bits[-1] == "0":
            raise ValueError(f"Unit State Error: Normal Operation Error Flag (bit 0)")

    #TODO: Check to see if the G9 switch is allowing high Voltage or not
    # this function will need to be constantly sending requests/receiving to check when the high voltage is off/on
    def checkStatus():
        pass

    def flush_serial(self):
        self.ser.reset_input_buffer()

    # this just makes sure that the ser object is considered to be valid
    def is_connected(self):
        return self.ser is not None and self.ser.is_open
        

    #TODO: Figure out how to handle all the errors (end task)
    #TODO: add a function to keep track of the driver uptime\