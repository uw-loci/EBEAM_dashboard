import serial
# import threading
# import time
# from utils import LogLevel
# import os
# from subsystem import interlocks

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
    9: "Output Power Supply Error Flag",
    10: "Safety I/O Terminal Error Flag",
    13: "Function Block Error Flag"
}

class G9Driver:
    def __init__(self, port=None, baudrate=9600, timeout=0.5, logger=None, debug_mode=False):
        if port:
            self.ser = serial.Serial(port, baudrate, parity=serial.PARITY_EVEN, stopbits=serial.STOPBITS_ONE, bytesize=serial.EIGHTBITS, timeout=timeout)
        self.debug_mode = debug_mode
        self.logger = logger
        self.lastResponse = None
        self.msgOptData = None
        self.input_flags = None

    def send_command(self):
        if not self.is_connected():
            raise ConnectionError("Seiral Port is Not Open.")
        header = b'\x40\x00\x00\x0F\x4B\x03\x4D\x00\x01' 
        data = b'\x00\x00\x00\x00'
        reserve = b'\x00\x00'
        self.msgOptData = data
        checksum = self.calculate_checksum(header + data + reserve, 0 , len(header + data))
        cs = b'\x00' + checksum if len(checksum) == 1 else checksum
        footer = b'\x2A\x0D' 
        self.ser.write(header + data + reserve+ cs + footer)

        self.response()

    # used mainly for the check sum but can also be used to check for error flags
    # needs an input of a byte string and the range of bytes that need to be sum
    # will return the sum of the bytes in the a byte string in the form of b'\x12'
    def calculate_checksum(self, byteString, startByte, endByte):
        assert isinstance(byteString, bytes)
        return sum(byteString[startByte:endByte + 1]).to_bytes(1, "big") 

    # helper function to convert bytes to bits for checking flags
    # not currently being used but many be helpful in the future for getting errors
    def bytes_to_binary(self, byte_string):
        return ''.join(format(byte, '08b') for byte in byte_string)
    
    # this method is made to check the error flags, right not only checks the last 13 bits
    # of a byte string
    def check_flags13(self, byteString, norm = 1):
        assert isinstance(byteString, bytes)
        # this is for if we only need the last 13 bits (more or less hardcoding this 
        # just including the rest if it might be helpful in the future
        if int(self.bytes_to_binary(byteString)[-13:], 2) >= (13 * norm):
            # all flags we care about are 1
            return True
        else:
            return False

    def response(self):
        if not self.is_connected():
            raise ConnectionError("Seiral Port is Not Open.")
        
        data = self.ser.read_until('b\r')
        self.lastResponse = data
        if data[1] == b'@':
            if data[3] == 195:
                alwaysHeader = data[0:3]
                alwaysFooter = data[-2:]
                if alwaysHeader != b'\x40\x00\x00' or alwaysFooter != b'\x2A\x0D':
                    raise ValueError("Always bits are incorrect")
                OCTD = data[7:11]
                if OCTD != self.msgOptData:
                    raise ValueError("Optional Transmission data doesn't match data sent to the G9SP")

                # Terminal Data Flags
                SITDF = data[11:17]
                if not self.check_flags13(SITDF):
                    err = []
                    print(SITDF)
                    gates = self.bytes_to_binary(SITDF[-3:])
                    for i in range(20):
                        if gates[-i + 1] == "0":
                            err.append(i)
                    self.input_flags = gates
                    raise ValueError(f"An input is either off or throwing an error: {err}")
                
                SOTDF = data[17:21]
                if not self.check_flags13(SOTDF):
                    err = []
                    gates = self.bytes_to_binary(SOTDF[-2:])
                    for i in range(14):
                        if gates[-i + 1] == "0":
                            err.append(i)
                    raise ValueError(f"There is output(s) off: {err}")

                # Terminal Status Flags
                SITSF = data[21:27]
                if not self.check_flags13(SITSF):
                    if self.safety_in_terminal_error(data[31:55][-10:]):
                        raise ValueError("Error was detected in inputs but was not found")
                    
                SOTSF = data[27:31]
                if not self.check_flags13(SOTSF):
                    if self.safety_out_terminal_error(data[55:71][-10:]):
                        raise ValueError("Error was detected in outputs but was not found")
                    
                # Unit status
                US = data[73:75]
                if US != b'\x00\x01':
                    if self.unit_state_error(US):
                        raise ValueError("Error was detected in Unit State but was not identified. Could be more than one")
                    
                
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
        if len(data) != 24:
            raise ValueError(f"Expected 24 bytes, but received {len(data)}.")

        last_bytes = data[-13:]
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
    def safety_out_terminal_error(self, data, inputs = 13):
        if len(data) != 16:
            raise ValueError(f"Expected 16 bytes, but received {len(data)}.")

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

        if bits[-1] == "0":
            raise ValueError(f"Unit State Error: Normal Operation Error Flag (bit 0)")
        
        for k in usStatus.keys():
            if bits[-(k + 1)] == "1":
                raise ValueError(f"Unit State Error: {usStatus[k]} (bit {k})")


    #TODO: Check to see if the G9 switch is allowing high Voltage or not
    # this function will need to be constantly sending requests/receiving to check when the high voltage is off/on
    def checkStatus():
        pass

    def flush_serial(self):
        self.ser.reset_input_buffer()


    #TODO: make funtion to turn all interlocks to red
    def is_connected(self):
        # i do not think this will work right now
        # try:
        #     #TODO: check if this works with G9 copied from Power Supply Driver
        #     # Attempt to write a simple command to the device
        #     self.ser.write(b'\r')  # Send a carriage return
        #     # Try to read a response (there might not be one)
        #     self.ser.read(1)

        #     self.isConnected = True
        #     return True
        # except serial.SerialException:
        #     return False
        return True
        

    #TODO: Figure out how to handle all the errors (end task)
    #TODO: add a function to keep track of the driver uptime\