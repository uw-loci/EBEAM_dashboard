# g9_driver.py
import serial
import threading
import queue
import time

class G9Driver:
    NUMIN = 13

    # Constants for protocol
    SNDHEADER = b'\x40\x00\x00\x0F\x4B\x03\x4D\x00\x01' 
    SNDDATA = b'\x00\x00\x00\x00'
    SNDRES = b'\x00\x00'
    RECHEADER = b'\x40\x00\x00'
    FOOTER = b'\x2A\x0D'
    ALWAYS_START_BYTE = b'\x40'
    EXPECTED_RESPONSE_LENGTH = b'\xC3'
    EXPECTED_DATA_LENGTH = 199 # bytes

    # Offsets for data extraction
    OCTD_OFFSET = 7     # Optional Communications Transmission Data
    US_OFFSET = 73      # Unit Status 
    SITDF_OFFSET = 11   # Safety Input Terminal Data Flags
    SOTDF_OFFSET = 17   # Safety Output Terminal Data Flags
    SITSF_OFFSET = 21   # Safety Input Terminal Status Flags
    SOTSF_OFFSET = 27   # Safety Output Terminal Status Flags
    SOTEC_OFFSET = 55   # Safety Output Terminal Error Causes
    SITEC_OFFSET = 31   # Safety Input Terminal Error Causes
    CHECKSUM_HIGH = 195 # G9 Response Checksum 
    CHECKSUM_LOW = 196  # G9 Response Checksum

    # Status dictionaries
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
        self.logger = logger
        self.debug_mode = debug_mode
        self.ser = None
        self.setup_serial(port, baudrate, timeout)
        self.last_data = None
        self.input_flags = []
        self._lock = threading.Lock()
        self._response_queue = queue.Queue(maxsize=1)
        self._running = True
        self._thread = threading.Thread(target=self._communication_thread, daemon=True)
        self._thread.start()

    def setup_serial(self, port, baudrate=9600, timeout=0.5):
        """
        Attempts to make a serial connection

        Catch:
            SerialException: If initizlization of serial port fails
        """
        if port:
            try:
                self.ser = serial.Serial(
                    port=port,
                    baudrate=baudrate,
                    parity=serial.PARITY_EVEN,
                    stopbits=serial.STOPBITS_ONE,
                    bytesize=serial.EIGHTBITS,
                    timeout=timeout
                    )   
            except serial.SerialException:
                self._close_serial()
        else:
            self._close_serial()
            raise ConnectionError

    def _close_serial(self):
        """ Attempt to close serial port """
        if self.ser and self.ser.is_open:
            self.ser.close()
        self.ser = None

    def _update_queue(self, response=None):
        data = response if response else ([0] * 13, [0] * 13, 0)
        if self._response_queue.full():
            self._response_queue.get_nowait()
        self._response_queue.put(data)

    def _communication_thread(self):
        """Background thread for handling serial communication"""
        while self._running:
            try:
                with self._lock:
                    if not self.is_connected():
                        time.sleep(0.1)
                        continue

                    self._send_command()
                    response_data = self._read_response() # blocking until complete or timeout
                    if response_data:
                        result = self._process_response(response_data)
                        self._update_queue(result)
           
            except PermissionError:
                self._update_queue()
                self._running = False
                self._close_serial()

            except serial.SerialException:
                self._update_queue()

            time.sleep(0.1)  # minimum sleep between successful reads


    def get_interlock_status(self):
        """
        Non-blocking method to get the latest interlock status
        Returns None if no data is available or on error
        """
        try:
            # Try to get an item from the queue without removing it
            item = self._response_queue.get_nowait()
            # Put it back since we just wanted to peek
            self._response_queue.put(item)
            return item
        except queue.Empty:
            # Queue is empty, return None
            return None

    def _send_command(self):
        """
        Creates message for G9, sends it through serial connection

        Catch:
            SerialException: If sending messages throws an error

        Raise:
            ConnectionError: Throws when sending message throws error
        """
        message = self.SNDHEADER + self.SNDDATA + self.SNDRES
        checksum = self._calculate_checksum(message, 14)
        full_message = message + checksum + self.FOOTER

        self.ser.write(full_message)


    def _read_response(self):
        """
        Read and validate response from G9SP device.

        Catch:
            SerialException: If reading messages throws an error
        
        Raise:
            ConnectionError: If serial port is not open
            ValueError: For various validation failures
        """
        data = bytearray()
        for _ in range(10):
            chunk = self.ser.read(50)
            if chunk is not None:
                data.extend(chunk)

                if data[-len(self.FOOTER):] == self.FOOTER:
                    break
            else:
                time.sleep(0.05)

        if data == bytearray(b''):
            raise TimeoutError("No response received within timeout")

        if len(data) < self.EXPECTED_DATA_LENGTH:
            raise ValueError(f"Incomplete response received: {len(data)} bytes")

        if len(data) > self.EXPECTED_DATA_LENGTH:
            raise ValueError(f"Invalid response received: {len(data)} bytes")

        self._validate_response_format(data)
        self._validate_checksum(data)

        return data

    def _process_response(self, data):
        """
        Process validated response and extract interlock data

        Return:
            Bit representation of the I/O Data flags
        """
        if data is None:
            raise ValueError("Invalid inputs to _process_response: Data is None")
        # Extract status data
        status_data = {
            'unit_status': data[self.US_OFFSET:self.US_OFFSET + 2],
            'sitdf': data[self.SITDF_OFFSET:self.SITDF_OFFSET + 6],
            'sitsf': data[self.SITSF_OFFSET:self.SITSF_OFFSET + 6],
            'sotdf': data[self.SOTDF_OFFSET:self.SOTDF_OFFSET + 4],
            'sotsf': data[self.SOTSF_OFFSET:self.SOTSF_OFFSET + 4]
        }

        # Convert to binary strings
        binary_data = {
            'sitdf': self._extract_flags(status_data['sitdf'], self.NUMIN),
            'sitsf': self._extract_flags(status_data['sitsf'], self.NUMIN),
            'sotdf': self._extract_flags(status_data['sotdf'], 7),
            'sotsf': self._extract_flags(status_data['sotsf'], 7)
        }

        return (binary_data['sitsf'], binary_data['sitdf'],                 # sitsf_bits , sitdf_bits
                    binary_data['sotsf'][4] & binary_data['sotdf'][4],      # g9_active
                    data[self.US_OFFSET:self.US_OFFSET + 2],                # unit_status
                    data[self.SITEC_OFFSET:self.SITEC_OFFSET + 24][-10:],   # input 
                    data[self.SOTEC_OFFSET:self.SOTEC_OFFSET + 16][-10:])   # output 

    def _validate_response_format(self, data):
        """
        Validate basic response format

        Raise:
            ValueError: if formate is not as expected
        """
        if data == None:
            raise ValueError("Invalid inputs to _validate_response_format: Data is None")
        if data[0:1] != self.ALWAYS_START_BYTE:
            raise ValueError(f"Invalid start byte: {data[0:1].hex()}")
        if data[1:3] != b'\x00\x00':
            raise ValueError(f"Invalid response length bytes: {data[1:3].hex()}")
        if data[3:4] != self.EXPECTED_RESPONSE_LENGTH:
            raise ValueError(f"Incorrect response length indicator: {data[3:4].hex()}")
        if data[-2:] != self.FOOTER:
            raise ValueError(f"Invalid footer: {data[-2:].hex()}")

    def _calculate_checksum(self, data, bytes):
        """
        Args:
            data (bytes): The complete message bytes
            start (int): Starting index for checksum calculation (default 0)
            end (int): Ending index for checksum calculation (default 194) pg. 115
            
        Return:
            bytes: Two-byte checksum value
        """
        if data is None:
            raise ValueError("Invalid inputs to _calculate_checksum: Data is None")
        checksum = sum(data[0:bytes + 1]) & 0xFFFF
        return checksum.to_bytes(2, 'big')

    def _validate_checksum(self, data):
        """
        Validate checksum of received data
        
        Raise:
            ValueError: Calculated check sum does not match
        """
        if data is None:
            raise ValueError("Invalid inputs to _validate_checksum: Data is None")

        # Extract the received checksum (bytes 195-196)
        received = data[self.CHECKSUM_HIGH:self.CHECKSUM_LOW + 1] # 1349

        # Calculate expected checksum (bytes 0-194)
        expected = self._calculate_checksum(data, 194) #1255
        if received != expected:
            raise ValueError(
                f"G9 Checksum failed. "
                f"Expectation: expected {expected.hex()}, "
                f" Received: {received.hex()}"
            )

    # helper function to convert bytes to bits for checking flags
    # not currently being used but many be helpful in the future for getting errors
    def _bytes_to_binary(self, byte_string):
        return ''.join(format(byte, '08b') for byte in byte_string)

    # this just makes sure that the ser object is considered to be valid
    def is_connected(self):
        """returns if serial connection is set up"""
        return self.ser is not None and self.ser.is_open

    def _extract_flags(self, byte_string, num_bits):
        """Extracts num_bits from the data
        the bytes are order in big-endian meaning the first 8 are on top 
        but the bits in the bye are ordered in little-endian 7 MSB and 0 LSB
        
        Raise:
            ValueError: When called requesting more bits than in the bytes
        Return:
            num_bits array - MSB is 0 signal LSB if (num_bits - 1)th bit (aka little endian)
        """
        num_bytes = (num_bits + 7) // 8

        if len(byte_string) < num_bytes:
            raise ValueError(f"Input must contain at least {num_bytes} bytes; received {len(byte_string)}")

        extracted_bits = []
        for byte_index in range(num_bytes):
            byte = byte_string[byte_index]
            bits_to_extract = min(8, num_bits - (byte_index * 8))
            extracted_bits.extend(((byte >> i) & 1) for i in range(bits_to_extract - 1, -1, -1)[::-1])

        return extracted_bits[:num_bits]


    #TODO: Figure out how to handle all the errors (end task)
    #TODO: add a function to keep track of the driver uptime\