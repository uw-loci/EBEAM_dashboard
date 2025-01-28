import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


import unittest
from unittest.mock import MagicMock, patch
from instrumentctl.E5CN_modbus.E5CN_modbus import E5CNModbus

from utils import LogLevel
import threading
import time

class TestE5CNModbus(unittest.TestCase):
    def setUp(self):
        """Setup test environment before each test"""
        self.mock_logger = MagicMock()
        self.device = E5CNModbus(
            port='COM1',  # Dummy port for testing
            logger=self.mock_logger,
            debug_mode=True
        )
        # Mock the Modbus client to prevent actual hardware communication
        self.device.client = MagicMock()

    def test_initialization(self):
        """Test proper initialization of E5CNModbus"""
        self.assertEqual(self.device.port, 'COM1')
        self.assertTrue(self.device.debug_mode)
        self.assertIsInstance(self.device.stop_event, threading.Event)
        self.assertEqual(len(self.device.temperatures), 3)
        self.assertIsInstance(self.device.temperatures_lock, threading.Lock().__class__)
        self.assertIsInstance(self.device.modbus_lock, threading.Lock().__class__)

    def test_connect_success(self):
        """Test successful connection"""
        self.device.client.is_socket_open.return_value = False
        self.device.client.connect.return_value = True
        
        result = self.device.connect()
        
        self.assertTrue(result)
        self.device.client.connect.assert_called_once()

    def test_connect_already_connected(self):
        """Test connection when already connected"""
        self.device.client.is_socket_open.return_value = True
        
        result = self.device.connect()
        
        self.assertTrue(result)
        self.device.client.connect.assert_not_called()

    def test_read_temperature_success(self):
        """Test successful temperature reading"""
        # Mock response object
        mock_response = MagicMock()
        mock_response.isError.return_value = False
        mock_response.registers = [0, 250]  # Represents 25.0°C
        
        self.device.client.is_socket_open.return_value = True
        self.device.client.read_holding_registers.return_value = mock_response
        
        temperature = self.device.read_temperature(1)
        
        self.assertEqual(temperature, 25.0)
        self.device.client.read_holding_registers.assert_called_with(
            address=self.device.TEMPERATURE_ADDRESS,
            count=2,
            slave=1
        )

    def test_read_temperature_connection_retry(self):
        """Test temperature reading with connection retry"""

        # set up the socket check to fail first, then succeed
        self.device.client.is_socket_open.side_effect = [False, True]
        self.device.client.connect.return_value = True
        
        mock_response = MagicMock()
        mock_response.isError.return_value = False
        mock_response.registers = [0, 250]
        self.device.client.read_holding_registers.return_value = mock_response

        # mock sleep
        with patch('time.sleep'):
            temperature = self.device.read_temperature(1)
        
        self.assertEqual(temperature, 25.0)
        self.device.client.connect.assert_called_once()

    def test_start_stop_reading(self):
        """Test starting and stopping continuous reading"""
        self.device.client.is_socket_open.return_value = True
        self.device.client.connect.return_value = True
        
        with patch('threading.Thread') as mock_thread:
            mock_thread_instance = MagicMock()
            mock_thread.return_value = mock_thread_instance

            # start reading
            success = self.device.start_reading_temperatures()

            # verify success
            self.assertTrue(success)
            mock_thread.assert_called()
            mock_thread_instance.start.assert_called()

            # stop reading
            self.device.stop_reading()

    def test_error_handling(self):
        """Test error handling during temperature reading"""
        self.device.client.is_socket_open.return_value = True
        self.device.client.read_holding_registers.side_effect = Exception("Simulated error")
        
        temperature = self.device.read_temperature(1)
        
        self.assertIsNone(temperature)
        self.assertTrue(any(
            "Unexpected error for unit 1" in str(call) 
            for call in self.mock_logger.log.call_args_list
        ))

if __name__ == '__main__':
    unittest.main()