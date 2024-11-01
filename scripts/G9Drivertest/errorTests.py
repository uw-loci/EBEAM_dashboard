import unittest
from unittest.mock import MagicMock, patch
from instrumentctl.g9_driver import G9Driver

# Optional Data modified to throw no errors
msg = b'@\x00\x00\xc3\x00\x00\xcb\x00\x00\x00\x00\x00\x08\x00\x00\x1f\xffC\x00\x1f\xff\xff\xff\x0f\x00\x1f\xff\xff\x00\x1f\xff\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x08\x00\x00\x01\x9a\x08\xbe\x14\x00\x0020000012X17M\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\n\n?\x00\x14\xb8?\x00\x14\xb8?\x00\x14\xb8?\x00\x14\xb8?\x00\x14\xb2?\x00\x14\xac?\x00\x14\xac?\x00\x14\xac?\x00\x14\xa0?\x00\x14\xa0\x06\x00\x14\xb2\x01\x00\x14\xb2\x01\x00\x14\xb2\x01\x00\x14\xb2\x06\x00\x14\xb2\x01\x00\x14\xb2\x06\x00\x14\x9a\x01\x00\x14\x9a\x01\x00\x14\x9a\x06\x00\x14\x9a\x1a\xe8*\r'

class TestG9Driver(unittest.TestCase):
    UNIT_ERROR_MSG = b'@\x00\x00\xc3\x00\x00\xcb\x00\x00\x00\x00\x00\x08\x00\x00\x1f\xffC\x00\x1f\xff\xff\xff\x0f\x00\x1f\xff\xff\x00\x1f\xff\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x08\x00\x02\x00\x9a\x08\xbe\x14\x00\x0020000012X17M\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\n\n?\x00\x14\xb8?\x00\x14\xb8?\x00\x14\xb8?\x00\x14\xb8?\x00\x14\xb2?\x00\x14\xac?\x00\x14\xac?\x00\x14\xac?\x00\x14\xa0?\x00\x14\xa0\x06\x00\x14\xb2\x01\x00\x14\xb2\x01\x00\x14\xb2\x01\x00\x14\xb2\x06\x00\x14\xb2\x01\x00\x14\xb2\x06\x00\x14\x9a\x01\x00\x14\x9a\x01\x00\x14\x9a\x06\x00\x14\x9a\x1a\xe8*\r'
    INPUT_ERROR_MSG = b'@\x00\x00\xc3\x00\x00\xcb\x00\x00\x00\x00\x00\x08\x00\x00\x1f\x00C\x00\x1f\xff\xff\xff\x0f\x00\x1f\xff\xff\x00\x1f\xff\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x08\x00\x00\x01\x9a\x08\xbe\x14\x00\x0020000012X17M\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\n\n?\x00\x14\xb8?\x00\x14\xb8?\x00\x14\xb8?\x00\x14\xb8?\x00\x14\xb2?\x00\x14\xac?\x00\x14\xac?\x00\x14\xac?\x00\x14\xa0?\x00\x14\xa0\x06\x00\x14\xb2\x01\x00\x14\xb2\x01\x00\x14\xb2\x01\x00\x14\xb2\x06\x00\x14\xb2\x01\x00\x14\xb2\x06\x00\x14\x9a\x01\x00\x14\x9a\x01\x00\x14\x9a\x06\x00\x14\x9a\x1a\xe8*\r'
    OUTPUT_ERROR_MSG = b'@\x00\x00\xc3\x00\x00\xcb\x00\x00\x00\x00\x00\x08\x00\x00\x1f\xffC\x00\x1f\x00\x00\xff\x0f\x00\x1f\xff\xff\x00\x1f\xff\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x08\x00\x00\x01\x9a\x08\xbe\x14\x00\x0020000012X17M\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\n\n?\x00\x14\xb8?\x00\x14\xb8?\x00\x14\xb8?\x00\x14\xb8?\x00\x14\xb2?\x00\x14\xac?\x00\x14\xac?\x00\x14\xac?\x00\x14\xa0?\x00\x14\xa0\x06\x00\x14\xb2\x01\x00\x14\xb2\x01\x00\x14\xb2\x01\x00\x14\xb2\x06\x00\x14\xb2\x01\x00\x14\xb2\x06\x00\x14\x9a\x01\x00\x14\x9a\x01\x00\x14\x9a\x06\x00\x14\x9a\x1a\xe8*\r'
    
    def create_message_with_checksum(self, base_message):
        """Helper to create a message with valid checksum"""
        message_without_checksum = base_message[:-4]  # Remove existing checksum and footer (these are probably incorrect in this older msg data)
        checksum = self.driver.calculate_checksum(message_without_checksum)
        return message_without_checksum + checksum + self.driver.FOOTER
    
    def setUp(self):
        self.driver = G9Driver()
        self.driver.msgOptData = b'\x00\x00\x00\x00'
        self.driver.ser = MagicMock()
        self.driver.logger = MagicMock()

    # Modified bytes msg[73:75] to ['02', '00'] to trigger a power supply error within unit status bytes
    def test_unit_state_error(self):
        msg_base = bytearray(self.UNIT_ERROR_MSG)
        msg_base[73:75] = b'\x02\x00'  # Set US bytes to trigger power supply error
        msg_with_checksum = self.create_message_with_checksum(bytes(msg_base))
        
        self.driver.ser.read_until.return_value = msg_with_checksum
        
        with self.assertRaises(ValueError) as context:
            self.driver.read_response()
        self.assertIn("Output Power Supply Error Flag (bit 9)", str(context.exception))

    # changed 10 to \x00 instead of expected \xff
    def test_input_error(self):
        # Create base message with input error
        msg_base = bytearray(self.INPUT_ERROR_MSG)
        msg_base[self.driver.SITDF_OFFSET:self.driver.SITDF_OFFSET + 6] = b'\x00' * 6  # Set SITDF to all zeros
        msg_with_checksum = self.create_message_with_checksum(bytes(msg_base))
        
        self.driver.ser.read_until.return_value = msg_with_checksum
        
        with self.assertRaises(ValueError) as context:
            self.driver.read_response()
        self.assertIn("Inputs off or in error state", str(context.exception))

    # changed byte 20 to be \x00 instead of expected \xff
    def test_output_error(self):
        # Create base message with output error
        msg_base = bytearray(self.OUTPUT_ERROR_MSG)
        msg_base[self.driver.SOTDF_OFFSET:self.driver.SOTDF_OFFSET + 4] = b'\x00' * 4  # Set SOTDF to all zeros
        msg_with_checksum = self.create_message_with_checksum(bytes(msg_base))
        
        self.driver.ser.read_until.return_value = msg_with_checksum
        
        with self.assertRaises(ValueError) as context:
            self.driver.read_response()
        self.assertIn("Outputs in off state", str(context.exception))


    # test of normal excepted values
    def test_no_error(self):
        # Create message with valid checksum
        msg_with_checksum = self.create_message_with_checksum(msg)
        self.driver.ser.read_until.return_value = msg_with_checksum
        
        try:
            self.driver.read_response()
        except ValueError as e:
            self.fail(f"read_response() raised ValueError unexpectedly: {str(e)}")

    def test_invalid_start_byte(self):
        invalid_msg = b'\x41' + msg[1:]  # Replace start byte
        msg_with_checksum = self.create_message_with_checksum(invalid_msg)
        self.driver.ser.read_until.return_value = msg_with_checksum
        
        with self.assertRaises(ValueError) as context:
            self.driver.read_response()
        self.assertIn("Invalid start byte", str(context.exception))

    def test_invalid_length(self):
        short_msg = msg[:-10]  # Remove last 10 bytes
        self.driver.ser.read_until.return_value = short_msg
        
        with self.assertRaises(ValueError) as context:
            self.driver.read_response()
        self.assertIn("Invalid response length", str(context.exception))

    def test_checksum_validation(self):
        bad_checksum_msg = msg[:-4] + b'\x00\x00' + msg[-2:]  # Replace checksum bytes
        self.driver.ser.read_until.return_value = bad_checksum_msg
        
        with self.assertRaises(ValueError) as context:
            self.driver.read_response()
        self.assertIn("Checksum validation failed", str(context.exception))

if __name__ == '__main__':
    unittest.main()
