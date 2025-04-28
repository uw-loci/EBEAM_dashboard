"""Test file for G9 driver"""
import sys
import os
import unittest
import json
import base64
import serial
from unittest.mock import MagicMock
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from instrumentctl.G9SP_interlock.g9_driver import G9Driver

with open('citestfiles/G9Driver/g9_test_cases.json', 'r') as json_file:
    json_data = json.load(json_file)

for k,v in json_data.items():
    json_data[k] = base64.b64decode(v)


class TestG9Driver(unittest.TestCase):
        # Sample response data - modified versions for different test cases
    BASE_RESPONSE = bytearray([
        0x40, 0x00, 0x00, 0xC3,  # Header
        # Bytes 4-10: Initial padding
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        # SITDF (Safety Input Terminal Data Flags) - 6 bytes
        0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF,
        # SOTDF (Safety Output Terminal Data Flags) - 4 bytes
        0xFF, 0xFF, 0xFF, 0xFF,
        # SITSF (Safety Input Terminal Status Flags) - 6 bytes
        0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF,
        # SOTSF (Safety Output Terminal Status Flags) - 4 bytes
        0xFF, 0xFF, 0xFF, 0xFF
    ] + [0x00] * 145 + [0x2A, 0x0D])  # Padding + Footer

    def setUp(self):
        self.mock_serial = MagicMock()
        self.mock_serial.port = "COM1"  # Add port name to mock_serial
        self.driver = G9Driver(port="COM1")  # Pass port to G9Driver
        self.driver.ser = self.mock_serial
        # Set normal operation status in BASE_RESPONSE
        self.BASE_RESPONSE[self.driver.US_OFFSET:self.driver.US_OFFSET + 2] = b'\x00\x01'
        
    def create_response_with_checksum(self, base_message):
        """Helper to create a response with valid checksum"""
        message_without_checksum = base_message[:-4]
        checksum = self.driver._calculate_checksum(message_without_checksum, 194)
        return message_without_checksum + checksum + self.driver.FOOTER

    def test_normal_response_processing(self):
        """Test processing of a normal response with all systems operational"""
        msg = bytearray(self.BASE_RESPONSE)
        msg[self.driver.US_OFFSET:self.driver.US_OFFSET + 2] = b'\x01\x00'  # Normal unit status
        msg_with_checksum = self.create_response_with_checksum(bytes(msg))
        
        self.driver.ser.read_until.return_value = msg_with_checksum
        
        try:
            sitsf, sitdf, g9Active, _ , _, _ = self.driver._process_response(msg_with_checksum)
            self.assertEqual(len(sitsf), self.driver.NUMIN)
            self.assertEqual(len(sitdf), self.driver.NUMIN)
            self.assertTrue(all(bit == 1 for bit in sitsf))
            self.assertTrue(all(bit == 1 for bit in sitdf))
        except ValueError as e:
            self.fail(f"process_response() raised ValueError unexpectedly: {str(e)}")


    def test_response_format_validation(self):
        """Test validation of response format"""
        # Test invalid start byte
        msg = bytearray(self.BASE_RESPONSE)
        msg[0] = 0x41  # Wrong start byte
        msg_with_checksum = self.create_response_with_checksum(bytes(msg))
        with self.assertRaises(ValueError) as context:
            self.driver._validate_response_format(msg_with_checksum)
        self.assertIn("Invalid start byte", str(context.exception))

    def test_checksum_validation(self):
        """Test checksum validation"""
        msg = bytes(self.BASE_RESPONSE)
        # Corrupt the message after calculating valid checksum
        msg_with_checksum = self.create_response_with_checksum(msg)
        corrupted_msg = bytearray(msg_with_checksum)
        corrupted_msg[10] = 0xFF  # Change a byte in the message
        with self.assertRaises(ValueError) as context:
            self.driver._validate_checksum(corrupted_msg)
        self.assertIn("Checksum failed", str(context.exception))

    def test_calculate_checksum(self):
        """Test the checksum calculation for a known data message."""
        # Create a sample message with known bytes
        # Verify that the calculated checksum is correct
        test_data = json_data["expected"]
        cal = self.driver._calculate_checksum(test_data, 194)
        self.assertEqual(test_data[-4:-2], cal,
                         f"""
                         Checksum calculation did not match expected value: calculated 
                         {self.driver._calculate_checksum(test_data, 194)};
                           expected {test_data[-4:-2]}
                            """)
                  
    def test_read_response_success(self):
        """Test _read_response reads complete and valid response in chunks."""
        mock_response = json_data["expected"]
        self.mock_serial.read.side_effect = [mock_response[x:x+50] for x in range(0, 500, 50)]
        self.assertEqual(self.driver._read_response(), mock_response)

    def test_read_response_without_footer(self):
        """Test _read_response detects when no footer is available"""
        mock_response = json_data["noend"]
        self.mock_serial.read.side_effect = [mock_response[x:x+50] for x in range(0, 500, 50)]
        with self.assertRaises(ValueError):
            self.driver._read_response()

    def test_read_response_timeout(self):
        """Test _read_response handles timeout correctly."""
        self.mock_serial.return_value = []
        with self.assertRaises(TimeoutError):
            self.driver._read_response()

    def test_read_response_too_long(self):
        """Test _read_response detects when no footer is available"""
        mock_response = json_data["long"]
        self.mock_serial.read.side_effect = [mock_response[x:x+50] for x in range(0, 500, 50)]
        with self.assertRaises(ValueError):
            self.driver._read_response()
            
    def test_read_response_too_short(self):
        """Test _read_response detects when no footer is available"""
        mock_response = json_data["short"]
        self.mock_serial.read.side_effect = [mock_response[x:x+50] for x in range(0, 500, 50)]
        with self.assertRaises(ValueError):
            self.driver._read_response()

    def test_comport_connection_none(self):
        """Testing with passing none to the method"""
        self.driver.ser = serial.Serial(port=None)
        self.assertIsNotNone(self.driver.ser)
        try:
            self.driver.setup_serial(None)
        except ConnectionError:
            self.assertIsNone(self.driver.ser)

    def test_comport_connection_not_real(self):
        """Testing with not real port"""
        self.driver.ser = serial.Serial(port=None)
        self.assertIsNotNone(self.driver.ser)
        self.driver.setup_serial("NOT A REAL PORT")
        self.assertIsNone(self.driver.ser)


if __name__ == '__main__':
    unittest.main()
