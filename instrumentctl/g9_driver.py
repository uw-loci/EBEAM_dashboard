import serial
from utils import LogLevel

class G9Driver:
    NUMIN = 13

    SNDHEADER = b'\x40\x00\x00\x0F\x4B\x03\x4D\x00\x01' 
    SNDDATA = b'\x00\x00\x00\x00'
    SNDRES = b'\x00\x00'
    RECHEADER = b'\x40\x00\x00'
    FOOTER = b'\x2A\x0D'
    ALWAYS_START_BYTE = b'\x40'
    EXPECTED_RESPONSE_LENGTH = b'\xC3'
    EXPECTED_DATA_LENGTH = 199 # bytes

    # Optional Communications Transmission Data
    OCTD_OFFSET = 7

    # Unit Status
    US_OFFSET = 73  

    # Safety Input/Output Terminal Data Flags
    SITDF_OFFSET = 11  
    SOTDF_OFFSET = 17  

    # Safety Input/Output Terminal Status Flags
    SITSF_OFFSET = 21  
    SOTSF_OFFSET = 27 

    # Safety Input/Output Terminal Error Causes
    SOTEC_OFFSET = 55
    SITEC_OFFSET = 31

    # G9 Response Checksum 
    CHECKSUM_HIGH = 195
    CHECKSUM_LOW = 196

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
        self.US, self.SITDF, self.SITSF, self.SOTDF, self.SOTSF, self.lastResponse, self.binSITDF, self.binSITSF = None, None, None, None, None, None, None, None

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

        message = self.SNDHEADER + self.SNDDATA + self.SNDRES
        checksum = self.calculate_checksum(message)
        full_message = message + checksum + self.FOOTER

        try:
            self.ser.write(full_message)
            self.read_response()
        except serial.SerialException as e:
            if self.logger:
                self.logger.error(f"Serial communication error ")


    def calculate_checksum(self, data, start=0, end=194):
        """
        Args:
            data (bytes): The complete message bytes
            start (int): Starting index for checksum calculation (default 0)
            end (int): Ending index for checksum calculation (default 194) pg. 115
            
        Returns:
            bytes: Two-byte checksum value
        """
        checksum = sum(data[start:end]) & 0xFFFF  # Mask to 16 bits
        return checksum.to_bytes(2, 'big')
    
    def validate_checksum(self, data):
        """
        Args:
            data (bytes): Complete response including checksum and footer
            
        Returns:
            bool: True if checksum is valid
        """
        if len(data) < 198:  # Minimum length needed for checksum validation
            raise ValueError("Response too short for checksum validation")
            
        # Extract the received checksum (bytes 195-196)
        received_checksum = data[self.CHECKSUM_HIGH:self.CHECKSUM_LOW + 1]
        
        # Calculate expected checksum (sum of bytes 0-194)
        expected_checksum = self.calculate_checksum(data)
        
        if received_checksum != expected_checksum:
            raise ValueError(
                f"Checksum validation failed. "
                f"Expected: {expected_checksum.hex()}, "
                f"Received: {received_checksum.hex()}"
            )
        
        return True

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
    
    def read_response(self):
        """
        Read and validate response from G9SP device.
        Raises:
            ConnectionError: If serial port is not open
            ValueError: For various validation failures
        """
        if not self.is_connected():
            self.log("G9SP Serial port is not open", LogLevel.ERROR)
            raise ConnectionError("Serial Port is Not Open.")
        
        data = self.ser.read_until(self.FOOTER)
        self.lastResponse = data
        self.log(f"Raw response received: {data.hex()}", LogLevel.DEBUG)

        if len(data) != self.EXPECTED_DATA_LENGTH:
            length_error_msg = f"Invalid response length: got: {len(data)}, expected 199 bytes"
            self.log(length_error_msg, LogLevel.ERROR)
            raise ValueError(length_error_msg)
        
        if data[0:1] != self.ALWAYS_START_BYTE:
            self.log(f"Invalid start byte: got {data[0:1].hex()}", LogLevel.ERROR)
            raise ValueError("Invalid start byte")
        
        if data[1:3] != b'\x00\x00':
            self.log(f"Invalid response length bytes 1-2: got {data[1:3].hex()}", LogLevel.ERROR)
            raise ValueError("Invalid response length bytes 1-2")
        
        if data[3:4] != self.EXPECTED_RESPONSE_LENGTH:
            self.log(f"Response length mismatch: got {data[3:4].hex()}, expected {self.EXPECTED_RESPONSE_LENGTH.hex()}", LogLevel.ERROR)
            raise ValueError(f"Response length was not 0xC3, got {data[3:4].hex()}")
        
        if data[-2:] != self.FOOTER:
            self.log(f"Invalid footer: got {data[-2:].hex()}", LogLevel.ERROR)
            raise ValueError(f"Invalid footer, got {data[-2:].hex()}")
        
        try:
            self.validate_checksum(data)
            self.log("Checksum validation passed", LogLevel.DEBUG)
        except ValueError as e:
            self.log(f"Checksum validation failed: {str(e)}", LogLevel.ERROR)
            raise

        # 3. Extract and save message components
        try:
            self.US = data[self.US_OFFSET:self.US_OFFSET + 2]
            self.SITDF = data[self.SITDF_OFFSET:self.SITDF_OFFSET + 6]
            self.SITSF = data[self.SITSF_OFFSET:self.SITSF_OFFSET + 6]
            self.SOTDF = data[self.SOTDF_OFFSET:self.SOTDF_OFFSET + 4]
            self.SOTSF = data[self.SOTSF_OFFSET:self.SOTSF_OFFSET + 4]
            
            self.binSITDF = self.bytes_to_binary(self.SITDF)
            self.binSITSF = self.bytes_to_binary(self.SITSF)
            
            self.log(f"Extracted US: {self.US.hex()}", LogLevel.DEBUG)
            self.log(f"Extracted SITDF: {self.SITDF.hex()}", LogLevel.DEBUG)
            self.log(f"Extracted SITSF: {self.SITSF.hex()}", LogLevel.DEBUG)
            self.log(f"Extracted SOTDF: {self.SOTDF.hex()}", LogLevel.DEBUG)
            self.log(f"Extracted SOTSF: {self.SOTSF.hex()}", LogLevel.DEBUG)

        except IndexError as e:
            self.log(f"Failed to extract message components: {str(e)}", LogLevel.ERROR)
            raise ValueError(f"Failed to extract message components: {str(e)}")

        # 4. Check Unit Status
        if self.US != b'\x00\x01':
            try:
                self.unit_state_error(self.US)
            except ValueError as e:
                self.log(f"Unit state error: {str(e)}", LogLevel.ERROR)
                raise

        # 5. Check Input Terminal Status
        if not self.check_flags13(self.SITDF):
            err = []
            gates = self.bytes_to_binary(self.SITDF[-3:])
            for i in range(self.NUMIN):
                if gates[-i - 1] == "0":
                    err.append(i)
            self.input_flags = gates
            self.log(f"Input terminal flags error - Inputs off or in error state: {err}", LogLevel.ERROR)
            raise ValueError(f"Inputs off or in error state: {err}")

        if not self.check_flags13(self.SITSF):
            try:
                self.safety_in_terminal_error(data[self.SITEC_OFFSET:self.SITEC_OFFSET + 24][-10:])
            except ValueError as e:
                self.log(f"Input terminal safety error: {str(e)}", LogLevel.ERROR)
                raise

        # 6. Check Output Terminal Status
        if not self.check_flags13(self.SOTDF):
            err = []
            gates = self.bytes_to_binary(self.SOTDF[-3:])
            for i in range(self.NUMIN):
                if gates[-i - 1] == "0":
                    err.append(i)
            self.log(f"Output terminal flags error - Outputs in off state: {err}", LogLevel.ERROR)
            raise ValueError(f"Outputs in off state: {err}")

        if not self.check_flags13(self.SOTSF):
            try:
                self.safety_out_terminal_error(data[self.SOTEC_OFFSET:self.SOTEC_OFFSET + 16][-10:])
            except ValueError as e:
                self.log(f"Output terminal safety error: {str(e)}", LogLevel.ERROR)
                raise

        # 7. Validate Optional Communication Data
        OCTD = data[self.OCTD_OFFSET:self.OCTD_OFFSET + 4]
        if OCTD != self.SNDDATA:
            self.log(f"Optional transmission data mismatch - Expected: {self.SNDDATA.hex()}, Got: {OCTD.hex()}", LogLevel.ERROR)
            raise ValueError(f"Optional transmission data mismatch. Expected: {self.SNDDATA.hex()}, Got: {OCTD.hex()}")

        self.log("Response validation completed successfully", LogLevel.DEBUG)
        return True

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
            raise ValueError(f"Expected 10 bytes, but received {len(data)}.")

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
            raise ValueError(f"Expected 10 bytes, but received {len(data)}.")

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
        
    def log(self, message, level=LogLevel.INFO):
        """Log a message with the specified level if a logger is configured."""
        if self.logger:
            self.logger.log(message, level)
        elif self.debug_mode:
            print(f"{level.name}: {message}")

    #TODO: Figure out how to handle all the errors (end task)
    #TODO: add a function to keep track of the driver uptime\