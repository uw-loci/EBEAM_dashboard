import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import unittest
from unittest.mock import MagicMock, patch
from instrumentctl.g9_driver import G9Driver

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
        self.driver = G9Driver()
        self.driver.ser = MagicMock()
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
        msg[self.driver.US_OFFSET:self.driver.US_OFFSET + 2] = b'\x00\x01'  # Normal unit status
        msg_with_checksum = self.create_response_with_checksum(bytes(msg))
        
        self.driver.ser.read_until.return_value = msg_with_checksum
        
        try:
            sitsf, sitdf = self.driver._process_response(msg_with_checksum)
            self.assertEqual(len(sitsf), self.driver.NUMIN)
            self.assertEqual(len(sitdf), self.driver.NUMIN)
            self.assertTrue(all(bit == 1 for bit in sitsf))
            self.assertTrue(all(bit == 1 for bit in sitdf))
        except ValueError as e:
            self.fail(f"process_response() raised ValueError unexpectedly: {str(e)}")

    def test_unit_status_error(self):
        """Test detection of unit status errors"""
        pass
        # # Ensure msg is a bytearray to allow modification
        # msg = bytearray(self.BASE_RESPONSE)
        # # Set Output Power Supply Error Flag (bit 9)
        # msg[self.driver.US_OFFSET:self.driver.US_OFFSET + 2] = b'\xFF\xFF'
        
        # # Convert to bytes only when needed for checksum creation
        # msg_with_checksum = self.create_response_with_checksum(bytes(msg))
        
        # with self.assertRaises(ValueError) as context:
        #     self.driver._process_response(msg_with_checksum)
        # self.assertIn("Output Power Supply Error Flag", str(context.exception))



    def test_safety_input_error(self):
        """Test detection of safety input terminal errors"""
        msg = bytearray(self.BASE_RESPONSE)
        # Fill input error section with zeros first
        msg[self.driver.SITEC_OFFSET:self.driver.SITEC_OFFSET + 24] = bytes([0] * 24)
        # Set error in the last 10 bytes of the input section
        error_section = msg[self.driver.SITEC_OFFSET:self.driver.SITEC_OFFSET + 24]
        # Put error code 3 (Internal circuit error) at start of last 10 bytes
        msg[self.driver.SITEC_OFFSET + 14] = 0x30  # Position error at start of last 10 bytes
        msg_with_checksum = self.create_response_with_checksum(bytes(msg))
        
        with self.assertRaises(ValueError) as context:
            self.driver._process_response(msg_with_checksum)
        self.assertIn("Internal circuit error", str(context.exception))

    def test_safety_output_error(self):
        """Test detection of safety output terminal errors"""
        msg = bytearray(self.BASE_RESPONSE)
        # Fill output error section with zeros first
        msg[self.driver.SOTEC_OFFSET:self.driver.SOTEC_OFFSET + 16] = bytes([0] * 16)
        # Set error code 2 (Overcurrent detection) at start of last 10 bytes
        msg[self.driver.SOTEC_OFFSET + 6] = 0x20
        msg_with_checksum = self.create_response_with_checksum(bytes(msg))
        
        with self.assertRaises(ValueError) as context:
            self.driver._process_response(msg_with_checksum)
        self.assertIn("Overcurrent detection", str(context.exception))

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

    #TODO: change this test since the unit status now does not raise an error
    # def test_complex_error_combinations(self):
    #     """Test multiple simultaneous error conditions"""
    #     msg = bytearray(self.BASE_RESPONSE)
    #     # Set multiple errors
    #     # msg[self.driver.US_OFFSET:self.driver.US_OFFSET + 2] = b'\x02\x00'  # Unit status error
    #     msg[self.driver.SITEC_OFFSET] = 0x30  # Input error
    #     msg[self.driver.SOTEC_OFFSET] = 0x20  # Output error
    #     msg_with_checksum = self.create_response_with_checksum(bytes(msg))
        
    #     with self.assertRaises(ValueError) as context:
    #         self.driver._process_response(msg_with_checksum)
    #     # Should raise the first error it encounters
    #     self.assertIn("Output Power Supply Error Flag", str(context.exception))

    def test_input_terminal_status_checker(self):
        """Test the input terminal status checker with various error codes"""
        test_cases = [
            (0x10, "Invalid configuration"),
            (0x20, "External test signal failure"),
            (0x30, "Internal circuit error"),
            (0x40, "Discrepancy error"),
            (0x50, "Failure of the associated dual-channel input")
        ]
        
        for error_code, expected_message in test_cases:
            msg = bytearray(self.BASE_RESPONSE)
            # Fill with zeros first
            msg[self.driver.SITEC_OFFSET:self.driver.SITEC_OFFSET + 24] = bytes([0] * 24)
            # Place error code in last byte
            msg[self.driver.SITEC_OFFSET + 23] = error_code
            msg_with_checksum = self.create_response_with_checksum(bytes(msg))

            with self.assertRaises(ValueError) as context:
                self.driver._process_response(msg_with_checksum)
            self.assertIn(expected_message, str(context.exception))

    def test_output_terminal_status_checker(self):
        """Test the output terminal status checker with various error codes"""
        test_cases = [
            (0x10, "Invalid configuration"),
            (0x20, "Overcurrent detection"),
            (0x30, "Short circuit detection"),
            (0x40, "Stuck-at-high detection"),
            (0x50, "Failure of the associated dual-channel output"),
            (0x60, "Internal circuit error"),
            (0x80, "Dual channel violation")
        ]
        
        for error_code, expected_message in test_cases:
            msg = bytearray(self.BASE_RESPONSE)
            # Fill with zeros first
            msg[self.driver.SOTEC_OFFSET:self.driver.SOTEC_OFFSET + 16] = bytes([0] * 16)
            # Place error code in last byte
            msg[self.driver.SOTEC_OFFSET + 15] = error_code
            msg_with_checksum = self.create_response_with_checksum(bytes(msg))
            msg_with_checksum = self.create_response_with_checksum(bytes(msg))
            
            with self.assertRaises(ValueError) as context:
                self.driver._process_response(msg_with_checksum)
            self.assertIn(expected_message, str(context.exception))

    def test_calculate_checksum(self):
        """Test the checksum calculation for a known data message."""
        # Create a sample message with known bytes
        test_data = b'@\x00\x00\xc3\x00\x00\xcb\x00\x00\x00\x00\xfc\x0f\x00\x00\x00\x00E\x00\x00\x00\xff\xff\x0f\x00\x00\x00\xff\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x08\x00\x12\x00\x9a\x08~\x15\x00\x0020000012X17M\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00@\x00\x00\x00\x00\n\n?\x00\x15~?\x00\x15l?\x00\x15f?\x00\x15`?\x00\x15`?\x00\x15`?\x00\x15H?\x00\x15H?\x00\x15H?\x00\x15B\x06\x00\x15f\x01\x00\x15f\x06\x00\x15`\x01\x00\x15`\x06\x00\x15B\x01\x00\x15B\x06\x00\x15B\x01\x00\x15B\x06\x00\x15\x1e\x01\x00\x15\x1e\x14\xf6*\r'
        
        # Verify that the calculated checksum is correct
        cal = self.driver._calculate_checksum(test_data, 194)
        self.assertEqual(test_data[-4:-2], cal,
                         f"""
                         Checksum calculation did not match expected value: calculated {self.driver._calculate_checksum(test_data, 194)};
                           expected {test_data[-4:-2]}
                            """)



if __name__ == '__main__':
    unittest.main()
