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
    NORMAL_RESPONSE_LENGTH = 0xC3
    ERROR_RESPONSE_LENGTH = 0x09
    INCORRECT_COMMAND_RESPONSE_LENGTH = 0x06
    EXPECTED_RESPONSE_LENGTH = b'\xC3'
    EXPECTED_DATA_LENGTH = 199 # bytes
    EXPECTED_END_CODE = b'\x00\x00'
    EXPECTED_SERVICE_CODE = b'\xCB'
    ERROR_SERVICE_CODE = b'\x94'

    # Offsets for data extraction
    END_CODE_OFFSET = 4
    SERVICE_CODE_OFFSET = 6
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
        0: "Normal",
        9: "Output Power Supply Error Flag",
        10: "Safety I/O Terminal Error Flag",
        13: "Function Block Error Flag"
    }

    def __init__(self, port=None, baudrate=9600, timeout=0.5, write_timeout=None, logger=None, debug_mode=False):
        self.logger = logger
        self.debug_mode = debug_mode
        self.ser = None
        self._lock = threading.RLock()
        self._serial_timeout = timeout
        self._serial_write_timeout = timeout if write_timeout is None else write_timeout
        self.last_data = None
        self.input_flags = []
        self._response_queue = queue.Queue(maxsize=1)
        self._status_lock = threading.Lock()
        self._last_status = None
        self._logger_event_queue = queue.Queue(maxsize=100)
        self._running = True
        self._thread = None
        self.setup_serial(port, baudrate, timeout, write_timeout)
        self._start_communication_thread()

    def _start_communication_thread(self):
        """Start or restart the background communication worker if needed."""
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._running = True
            self._thread = threading.Thread(target=self._communication_thread, daemon=True)
            self._thread.start()

    def _clear_cached_status(self):
        """Clear status from a previous connection so consumers wait for fresh data."""
        with self._status_lock:
            self._last_status = None

        try:
            while True:
                self._response_queue.get_nowait()
        except queue.Empty:
            pass

        try:
            while True:
                self._logger_event_queue.get_nowait()
        except queue.Empty:
            pass
        self._queue_status_field_clears()

    def setup_serial(self, port, baudrate=9600, timeout=0.5, write_timeout=None):
        """
        Attempts to make a serial connection

        Catch:
            SerialException: If initialization of serial port fails
        """
        if not port:
            self._close_serial()
            raise ConnectionError("No port specified for G9SP connection")

        with self._lock:
            old_ser = self.ser
            self.ser = None
            if old_ser and old_ser.is_open:
                try:
                    old_ser.close()
                except Exception:
                    pass
            self._clear_cached_status()

            try:
                self.ser = serial.Serial(
                    port=port,
                    baudrate=baudrate,
                    parity=serial.PARITY_EVEN,
                    stopbits=serial.STOPBITS_ONE,
                    bytesize=serial.EIGHTBITS,
                    timeout=timeout,
                    write_timeout=timeout if write_timeout is None else write_timeout
                    )
                self._serial_timeout = timeout
                self._serial_write_timeout = timeout if write_timeout is None else write_timeout
                self._start_communication_thread()
            except serial.SerialException as e:
                raise ConnectionError(f"Failed to open G9SP serial port {port}: {e}") from e

    def _close_serial(self):
        """ Attempt to close serial port """
        with self._lock:
            ser = self.ser
            self.ser = None
            self._clear_cached_status()

            if ser and ser.is_open:
                try:
                    ser.close()
                except Exception:
                    pass

    def _update_queue(self, response=None):
        data = response if response else (
            [0] * self.NUMIN,                    # sitsf_bits
            [0] * self.NUMIN,                    # sitdf_bits
            0,                                   # g9_output
            {},                                  # unit_status
            bytearray(10),                       # input_terms
            bytearray(10),                       # output_terms
            {'sotdf': [0] * 7, 'sitdf': [0] * self.NUMIN}  # debug_data
        )
        with self._status_lock:
            self._last_status = data

        try:
            if self._response_queue.full():
                self._response_queue.get_nowait()
            self._response_queue.put_nowait(data)
        except (queue.Empty, queue.Full):
            pass

    def _queue_logger_event(self, event):
        try:
            self._logger_event_queue.put_nowait(event)
        except queue.Full:
            try:
                self._logger_event_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._logger_event_queue.put_nowait(event)
            except queue.Full:
                pass

    def _queue_log(self, message, level="ERROR"):
        self._queue_logger_event(("log", level, message))

    def _queue_field_update(self, field, value):
        self._queue_logger_event(("update_field", field, value))

    def _queue_field_clear(self, field):
        self._queue_logger_event(("clear_value", field, None))

    def _queue_status_field_clears(self):
        for field in [
            "safetyOutputDataFlags",
            "safetyInputDataFlags",
            "safetyOutputStatusFlags",
            "safetyInputStatusFlags",
        ]:
            self._queue_field_clear(field)

    def drain_logger_events(self):
        events = []
        while True:
            try:
                events.append(self._logger_event_queue.get_nowait())
            except queue.Empty:
                return events

    def _communication_thread(self):
        """Background thread for handling serial communication"""
        while self._running:
            try:
                with self._lock:
                    if self.is_connected():
                        self._send_command()
                        response_data = self._read_response() # blocking until complete or timeout
                        if response_data:
                            result = self._process_response(response_data)
                            self._update_queue(result)

            except (ValueError, TimeoutError) as e:
                self._update_queue()
                self._queue_status_field_clears()
                self._queue_log(f"G9 response error: {e}", "ERROR")
            except PermissionError as e:
                self._update_queue()
                self._queue_status_field_clears()
                self._queue_log(f"G9 serial permission error: {e}", "ERROR")
                self._close_serial()

            except (serial.SerialException, OSError, TypeError) as e:
                self._update_queue()
                self._queue_status_field_clears()
                self._queue_log(f"G9 serial communication error: {e}", "ERROR")
                self._close_serial()
            except Exception as e:
                self._update_queue()
                self._queue_status_field_clears()
                self._queue_log(f"Unexpected G9 worker error: {e}", "ERROR")

            time.sleep(0.1)  # minimum sleep between successful reads

    def stop_thread(self):
        """Stops the communication thread"""
        self._running = False
        if self._thread and self._thread.is_alive():
            join_timeout = max(1.0, (10 * self._serial_timeout) + 1.0)
            self._thread.join(timeout=join_timeout)
        self._close_serial()

    def disconnect(self):
        """Close the serial port without stopping the communication thread."""
        self._close_serial()

    def get_interlock_status(self):
        """
        Non-blocking method to get the latest interlock status
        Returns None if no data is available or on error
        """
        with self._status_lock:
            return self._last_status

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

        bytes_written = self.ser.write(full_message)
        if bytes_written != len(full_message):
            raise TimeoutError(
                f"Incomplete G9 command write: wrote {bytes_written} of {len(full_message)} bytes"
            )


    def _read_response(self):
        """
        Read and validate response from G9SP device.

        Catch:
            SerialException: If reading messages throws an error
        
        Raise:
            ConnectionError: If serial port is not open
            ValueError: For various validation failures
        """
        header_length = len(self.RECHEADER) + 1
        data = self._read_exact(header_length)

        if data == bytearray(b''):
            raise TimeoutError("No response received within timeout")

        if len(data) < header_length:
            raise ValueError(f"Incomplete response received: {len(data)} bytes")

        if data[0:len(self.RECHEADER)] != self.RECHEADER:
            raise ValueError(f"Invalid response header: {data[0:len(self.RECHEADER)].hex()}")

        data.extend(self._read_exact(data[3]))

        self._validate_response_format(data)
        self._validate_checksum(data)
        self._raise_protocol_error_response(data)

        if len(data) < self.EXPECTED_DATA_LENGTH:
            raise ValueError(f"Incomplete response received: {len(data)} bytes")

        if len(data) > self.EXPECTED_DATA_LENGTH:
            raise ValueError(f"Invalid response received: {len(data)} bytes")

        return data

    def _read_exact(self, byte_count):
        """Read up to byte_count bytes, allowing pyserial to return partial chunks."""
        data = bytearray()
        while len(data) < byte_count:
            chunk = self.ser.read(byte_count - len(data))
            if chunk is None:
                break
            if not chunk:
                break
            data.extend(chunk)

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

        self._queue_field_update("safetyOutputDataFlags", binary_data["sotdf"])
        self._queue_field_update("safetyInputDataFlags", binary_data["sitdf"])
        self._queue_field_update("safetyOutputStatusFlags", binary_data["sotsf"])
        self._queue_field_update("safetyInputStatusFlags", binary_data["sitsf"])

        # Store data flags to be logged in interlock.py for web monitor
        debug_data = {
            'sotdf': binary_data['sotdf'],
            'sitdf': binary_data['sitdf']
        }

        unit_status_flags = self._extract_flags(status_data['unit_status'], 16)

        unit_flags = {self.US_STATUS[k] : unit_status_flags[k] for k in self.US_STATUS.keys()}

        return (binary_data['sitsf'], binary_data['sitdf'],                 # sitsf_bits , sitdf_bits
                    binary_data['sotsf'][4] & binary_data['sotdf'][4],      # g9_output
                    unit_flags,                                             # unit_status
                    data[self.SITEC_OFFSET:self.SITEC_OFFSET + 24][-10:],   # input 
                    data[self.SOTEC_OFFSET:self.SOTEC_OFFSET + 16][-10:],   # output
                    debug_data)                                             # debug data for terminal flags

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
        if len(data) != data[3] + 4:
            raise ValueError(
                f"Response length mismatch: indicator {data[3]}, received {len(data)} bytes"
            )
        if data[-2:] != self.FOOTER:
            raise ValueError(f"Invalid footer: {data[-2:].hex()}")

        if data[3] in (self.ERROR_RESPONSE_LENGTH, self.INCORRECT_COMMAND_RESPONSE_LENGTH):
            return

        if data[3:4] != self.EXPECTED_RESPONSE_LENGTH:
            raise ValueError(f"Incorrect response length indicator: {data[3:4].hex()}")
        if data[self.END_CODE_OFFSET:self.END_CODE_OFFSET + 2] != self.EXPECTED_END_CODE:
            raise ValueError(
                "Invalid normal response end code: "
                f"{data[self.END_CODE_OFFSET:self.END_CODE_OFFSET + 2].hex()}"
            )
        if data[self.SERVICE_CODE_OFFSET:self.SERVICE_CODE_OFFSET + 1] != self.EXPECTED_SERVICE_CODE:
            raise ValueError(
                "Invalid normal response service code: "
                f"{data[self.SERVICE_CODE_OFFSET:self.SERVICE_CODE_OFFSET + 1].hex()}"
            )

    def _raise_protocol_error_response(self, data):
        """Raise explicit errors for valid non-normal G9 protocol response frames."""
        response_length = data[3]
        end_code = data[self.END_CODE_OFFSET:self.END_CODE_OFFSET + 2]

        if response_length == self.ERROR_RESPONSE_LENGTH:
            service_code = data[self.SERVICE_CODE_OFFSET:self.SERVICE_CODE_OFFSET + 1]
            if end_code != self.EXPECTED_END_CODE:
                raise ValueError(f"G9 protocol error response end code: {end_code.hex()}")
            if service_code != self.ERROR_SERVICE_CODE:
                raise ValueError(f"G9 protocol error response service code: {service_code.hex()}")
            raise ValueError("G9 protocol error response received")

        if response_length == self.INCORRECT_COMMAND_RESPONSE_LENGTH:
            if end_code != self.EXPECTED_END_CODE:
                raise ValueError(f"G9 incorrect-command response end code: {end_code.hex()}")
            raise ValueError("G9 incorrect command format response received")

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

        checksum_offset = len(data) - len(self.FOOTER) - 2
        if checksum_offset < 0:
            raise ValueError(f"Response too short for checksum: {len(data)} bytes")

        received = data[checksum_offset:checksum_offset + 2]
        expected = self._calculate_checksum(data, checksum_offset - 1)
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
        with self._lock:
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
