import unittest
from unittest.mock import MagicMock, patch
from g9_driver import G9Driver

msg = b'@\x00\x00\xc3\x00\x00\xcb\x00\x00\x00\x00\x00\x08\x00\x00\x1f\xffC\x00\x1f\xff\xff\xff\x0f\x00\x1f\xff\xff\x00\x1f\xff\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x08\x00\x00\x01\x9a\x08\xbe\x14\x00\x0020000012X17M\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\n\n?\x00\x14\xb8?\x00\x14\xb8?\x00\x14\xb8?\x00\x14\xb8?\x00\x14\xb2?\x00\x14\xac?\x00\x14\xac?\x00\x14\xac?\x00\x14\xa0?\x00\x14\xa0\x06\x00\x14\xb2\x01\x00\x14\xb2\x01\x00\x14\xb2\x01\x00\x14\xb2\x06\x00\x14\xb2\x01\x00\x14\xb2\x06\x00\x14\x9a\x01\x00\x14\x9a\x01\x00\x14\x9a\x06\x00\x14\x9a\x1a\xe8*\r'

class TestG9Driver(unittest.TestCase):
    
    def setUp(self):
        self.driver = G9Driver()
        self.driver.msgOptData = b'\x00\x00\x00\x00'
        self.driver.ser = MagicMock()

    # def test_unit_state_error(self):
    #     self.driver.ser.read_until.return_value = msg
        
    #     with self.assertRaises(ValueError) as context:
    #         self.driver.response()

    #     self.assertIn("Output Power Supply Error Flag (bit 9)", str(context.exception))

    # def test_input_error(self):
    #     self.driver.ser.read_until.return_value = msg

    #     with self.assertRaises(ValueError) as context:
    #         self.driver.response()

    #     self.assertIn("An input is either off or throwing an error", str(context.exception))

    def test_output_error(self):
        msg[21:22] = '00'
        print(msg[21:22])
        self.driver.ser.read_until.return_value = msg

        with self.assertRaises(ValueError) as context:
            self.driver.response()

        self.assertIn("There is output(s) off", str(context.exception))

    def test_mismatched_optional_data(self):
        self.driver.msgOptData = b'\x00\x01\x00\x00'
        self.driver.ser.read_until.return_value = msg
        
        with self.assertRaises(ValueError) as context:
            self.driver.response()

        self.assertIn("Optional Transmission data doesn't match", str(context.exception))

    def test_no_error(self):
        self.driver.ser.read_until.return_value = msg

        try:
            self.driver.response()
        except ValueError:
            self.fail("response() raised ValueError unexpectedly")

if __name__ == '__main__':
    unittest.main()
