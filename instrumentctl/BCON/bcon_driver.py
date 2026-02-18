"""
BCON (Beam Controller) Driver

RS-485 serial driver for Arduino Mega running BCON firmware.
Provides command interface, status monitoring, and telemetry parsing.
"""

import serial
import threading
import time
import re
from typing import Optional, Dict, List, Tuple
from enum import Enum


class BCONState(Enum):
    """BCON system states."""
    READY = "READY"
    SAFE_INTERLOCK = "SAFE_INTERLOCK"
    SAFE_WATCHDOG = "SAFE_WATCHDOG"
    FAULT_LATCHED = "FAULT_LATCHED"
    UNKNOWN = "UNKNOWN"


class BCONChannelMode(Enum):
    """BCON channel output modes."""
    OFF = "OFF"
    DC = "DC"
    PULSE = "PULSE"
    UNKNOWN = "UNKNOWN"


class BCONDriver:
    """
    BCON (Beam Controller) RS-485 driver.
    
    Communicates with Arduino Mega running BCON firmware to control
    three independent pulser channels with safety interlocks.
    
    Features:
        - RS-485 serial communication
        - Command/response interface
        - Telemetry parsing and monitoring
        - Thread-safe operation
        - Watchdog and fault management
    """
    
    # Command constants
    CMD_PING = "PING"
    CMD_HELP = "HELP"
    CMD_STATUS = "STATUS"
    CMD_GET_STATUS = "GET STATUS"
    CMD_STOP_ALL = "STOP ALL"
    CMD_SET_WATCHDOG = "SET WATCHDOG"
    CMD_SET_TELEMETRY = "SET TELEMETRY"
    CMD_SET_CH = "SET CH"
    CMD_CLEAR_FAULT = "CLEAR FAULT"
    CMD_ARM = "ARM"
    
    # Response constants
    RESP_PONG = "PONG"
    RESP_OK = "OK"
    RESP_ERR = "ERR"
    
    # Telemetry prefixes
    TELEM_SYS = "SYS"
    TELEM_CH = "CH"
    
    def __init__(self, port: str, baudrate: int = 115200, 
                 timeout: float = 1.0, debug: bool = False):
        """
        Initialize BCON driver.
        
        Args:
            port: Serial port name (e.g., 'COM3' on Windows, '/dev/ttyUSB0' on Linux)
            baudrate: Serial baudrate (default: 115200)
            timeout: Serial read timeout in seconds (default: 1.0)
            debug: Enable debug logging (default: False)
        """
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.debug = debug
        
        # Serial connection
        self._serial: Optional[serial.Serial] = None
        self._serial_lock = threading.Lock()
        
        # Latest telemetry data
        self._latest_telemetry = {
            'system': {
                'state': 'UNKNOWN',
                'reason': 'NONE',
                'fault_latched': 0,
                'telemetry_ms': 0
            },
            'channels': [
                {'mode': 'UNKNOWN', 'pulse_ms': 0, 'en_st': 0, 'pwr_st': 0, 'oc_st': 0, 'gated_st': 0},
                {'mode': 'UNKNOWN', 'pulse_ms': 0, 'en_st': 0, 'pwr_st': 0, 'oc_st': 0, 'gated_st': 0},
                {'mode': 'UNKNOWN', 'pulse_ms': 0, 'en_st': 0, 'pwr_st': 0, 'oc_st': 0, 'gated_st': 0}
            ]
        }
        self._telemetry_lock = threading.Lock()
        
        # Background telemetry parser thread
        self._telemetry_thread: Optional[threading.Thread] = None
        self._telemetry_running = False
        
    def _log(self, message: str, level: str = "INFO"):
        """Internal logging helper."""
        if self.debug or level in ["ERROR", "WARNING"]:
            print(f"[BCON {level}] {message}")
    
    # ==================== Connection Management ====================
    
    def connect(self) -> bool:
        """
        Connect to BCON hardware.
        
        Returns:
            True if connection successful, False otherwise
        """
        try:
            with self._serial_lock:
                if self._serial and self._serial.is_open:
                    self._log("Already connected", "WARNING")
                    return True
                
                self._serial = serial.Serial(
                    port=self.port,
                    baudrate=self.baudrate,
                    timeout=self.timeout,
                    bytesize=serial.EIGHTBITS,
                    parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE
                )
                
                # Clear any stale data
                self._serial.reset_input_buffer()
                self._serial.reset_output_buffer()
                
                self._log(f"Connected to {self.port} at {self.baudrate} baud", "INFO")
                
            # Start telemetry monitoring thread
            self._start_telemetry_thread()
            
            # Verify communication with PING
            time.sleep(0.1)  # Allow device to stabilize
            if self.ping():
                self._log("BCON communication verified", "INFO")
                return True
            else:
                self._log("BCON not responding to PING", "WARNING")
                return False
                
        except serial.SerialException as e:
            self._log(f"Failed to connect: {e}", "ERROR")
            return False
        except Exception as e:
            self._log(f"Unexpected error during connect: {e}", "ERROR")
            return False
    
    def disconnect(self):
        """Disconnect from BCON hardware."""
        # Stop telemetry thread
        self._stop_telemetry_thread()
        
        with self._serial_lock:
            if self._serial and self._serial.is_open:
                try:
                    self._serial.close()
                    self._log("Disconnected from BCON", "INFO")
                except Exception as e:
                    self._log(f"Error during disconnect: {e}", "ERROR")
            self._serial = None
    
    def is_connected(self) -> bool:
        """
        Check if connected to BCON hardware.
        
        Returns:
            True if connected and serial port is open
        """
        with self._serial_lock:
            return self._serial is not None and self._serial.is_open
    
    # ==================== Low-Level Communication ====================
    
    def _send_command(self, command: str) -> bool:
        """
        Send command to BCON (low-level).
        
        Args:
            command: Command string (without newline)
            
        Returns:
            True if sent successfully, False otherwise
        """
        if not self.is_connected():
            self._log("Cannot send command: not connected", "ERROR")
            return False
        
        try:
            with self._serial_lock:
                command_bytes = (command + "\n").encode('ascii')
                self._serial.write(command_bytes)
                self._serial.flush()
                self._log(f"TX: {command}", "DEBUG")
                return True
        except Exception as e:
            self._log(f"Error sending command '{command}': {e}", "ERROR")
            return False
    
    def _read_line(self, timeout: Optional[float] = None) -> Optional[str]:
        """
        Read a single line from BCON (low-level).
        
        Args:
            timeout: Optional timeout override (seconds)
            
        Returns:
            Line string without newline, or None on timeout/error
        """
        if not self.is_connected():
            return None
        
        try:
            with self._serial_lock:
                if timeout is not None:
                    old_timeout = self._serial.timeout
                    self._serial.timeout = timeout
                
                line_bytes = self._serial.readline()
                
                if timeout is not None:
                    self._serial.timeout = old_timeout
                
                if not line_bytes:
                    return None
                
                line = line_bytes.decode('ascii', errors='ignore').strip()
                if line:
                    self._log(f"RX: {line}", "DEBUG")
                return line if line else None
                
        except Exception as e:
            self._log(f"Error reading line: {e}", "ERROR")
            return None
    
    def _send_and_wait_response(self, command: str, expected_prefix: Optional[str] = None,
                                 timeout: float = 2.0) -> Optional[str]:
        """
        Send command and wait for response line.
        
        Args:
            command: Command string
            expected_prefix: Optional expected response prefix (e.g., "OK", "ERR", "PONG")
            timeout: Total timeout for response (seconds)
            
        Returns:
            Response line or None on timeout/error
        """
        if not self._send_command(command):
            return None
        
        start_time = time.time()
        while (time.time() - start_time) < timeout:
            line = self._read_line(timeout=0.1)
            if line:
                # Check if this is telemetry (parse in background)
                if line.startswith(self.TELEM_SYS) or line.startswith(self.TELEM_CH):
                    self._parse_telemetry_line(line)
                    continue  # Keep waiting for command response
                
                # Check if response matches expected prefix
                if expected_prefix is None or line.startswith(expected_prefix):
                    return line
                
                # Got a response but not expected prefix
                return line
        
        self._log(f"Timeout waiting for response to '{command}'", "WARNING")
        return None
    
    # ==================== Telemetry Parsing ====================
    
    def _parse_telemetry_line(self, line: str):
        """
        Parse a telemetry line and update internal state.
        
        Telemetry formats:
            SYS state=READY reason=NONE fault_latched=0 telemetry_ms=1000
            CH1 mode=DC pulse_ms=0 en_st=1 pwr_st=1 oc_st=0 gated_st=0
        """
        try:
            parts = line.split()
            if not parts:
                return
            
            prefix = parts[0]
            
            # Parse key=value pairs
            data = {}
            for part in parts[1:]:
                if '=' in part:
                    key, value = part.split('=', 1)
                    data[key] = value
            
            with self._telemetry_lock:
                if prefix == self.TELEM_SYS:
                    # System telemetry
                    self._latest_telemetry['system']['state'] = data.get('state', 'UNKNOWN')
                    self._latest_telemetry['system']['reason'] = data.get('reason', 'NONE')
                    self._latest_telemetry['system']['fault_latched'] = int(data.get('fault_latched', '0'))
                    self._latest_telemetry['system']['telemetry_ms'] = int(data.get('telemetry_ms', '0'))
                    self._log(f"System state: {data.get('state')}", "DEBUG")
                    
                elif prefix.startswith(self.TELEM_CH):
                    # Channel telemetry (CH1, CH2, CH3)
                    channel_num = int(prefix[2:])  # Extract number from "CH1", "CH2", "CH3"
                    channel_idx = channel_num - 1
                    
                    if 0 <= channel_idx < 3:
                        self._latest_telemetry['channels'][channel_idx]['mode'] = data.get('mode', 'UNKNOWN')
                        self._latest_telemetry['channels'][channel_idx]['pulse_ms'] = int(data.get('pulse_ms', '0'))
                        self._latest_telemetry['channels'][channel_idx]['en_st'] = int(data.get('en_st', '0'))
                        self._latest_telemetry['channels'][channel_idx]['pwr_st'] = int(data.get('pwr_st', '0'))
                        self._latest_telemetry['channels'][channel_idx]['oc_st'] = int(data.get('oc_st', '0'))
                        self._latest_telemetry['channels'][channel_idx]['gated_st'] = int(data.get('gated_st', '0'))
                        self._log(f"Channel {channel_num} mode: {data.get('mode')}", "DEBUG")
                        
        except Exception as e:
            self._log(f"Error parsing telemetry line '{line}': {e}", "WARNING")
    
    def _telemetry_thread_func(self):
        """Background thread function to continuously parse telemetry."""
        self._log("Telemetry thread started", "DEBUG")
        
        while self._telemetry_running:
            try:
                line = self._read_line(timeout=0.1)
                if line and (line.startswith(self.TELEM_SYS) or line.startswith(self.TELEM_CH)):
                    self._parse_telemetry_line(line)
            except Exception as e:
                self._log(f"Telemetry thread error: {e}", "WARNING")
                time.sleep(0.1)
    
    def _start_telemetry_thread(self):
        """Start background telemetry parsing thread."""
        if self._telemetry_thread and self._telemetry_thread.is_alive():
            return
        
        self._telemetry_running = True
        self._telemetry_thread = threading.Thread(target=self._telemetry_thread_func, daemon=True)
        self._telemetry_thread.start()
    
    def _stop_telemetry_thread(self):
        """Stop background telemetry parsing thread."""
        self._telemetry_running = False
        if self._telemetry_thread:
            self._telemetry_thread.join(timeout=2.0)
            self._telemetry_thread = None
    
    # ==================== Basic Commands ====================
    
    def ping(self) -> bool:
        """
        Send PING command and wait for PONG response.
        Also refreshes communication watchdog.
        
        Returns:
            True if PONG received, False otherwise
        """
        response = self._send_and_wait_response(self.CMD_PING, self.RESP_PONG, timeout=1.0)
        return response == self.RESP_PONG
    
    def get_status(self) -> Dict:
        """
        Request full system status.
        
        Returns status as multi-line report, parsing into telemetry structure.
        
        Returns:
            Dictionary with 'system' and 'channels' keys containing status data
        """
        if not self._send_command(self.CMD_STATUS):
            return self._get_latest_telemetry_copy()
        
        # Read multiple lines of status report
        # Status format:
        #   SYS ...
        #   CH1 ...
        #   CH2 ...
        #   CH3 ...
        
        timeout_end = time.time() + 2.0
        while time.time() < timeout_end:
            line = self._read_line(timeout=0.1)
            if line:
                if line.startswith(self.TELEM_SYS) or line.startswith(self.TELEM_CH):
                    self._parse_telemetry_line(line)
        
        return self._get_latest_telemetry_copy()
    
    def stop_all(self) -> bool:
        """
        Force all channels to OFF mode immediately.
        
        Returns:
            True if command acknowledged, False otherwise
        """
        response = self._send_and_wait_response(self.CMD_STOP_ALL, self.RESP_OK, timeout=1.0)
        return response is not None and response.startswith(self.RESP_OK)
    
    # ==================== Configuration Commands ====================
    
    def set_watchdog(self, timeout_ms: int) -> bool:
        """
        Configure communication watchdog timeout.
        
        Args:
            timeout_ms: Watchdog timeout in milliseconds (50-60000)
            
        Returns:
            True if command acknowledged, False otherwise
        """
        if not (50 <= timeout_ms <= 60000):
            self._log(f"Invalid watchdog timeout: {timeout_ms} (must be 50-60000)", "ERROR")
            return False
        
        command = f"{self.CMD_SET_WATCHDOG} {timeout_ms}"
        response = self._send_and_wait_response(command, self.RESP_OK, timeout=1.0)
        return response is not None and response.startswith(self.RESP_OK)
    
    def set_telemetry(self, interval_ms: int) -> bool:
        """
        Configure periodic telemetry transmission interval.
        
        Args:
            interval_ms: Telemetry interval in milliseconds (0 to disable)
            
        Returns:
            True if command acknowledged, False otherwise
        """
        command = f"{self.CMD_SET_TELEMETRY} {interval_ms}"
        response = self._send_and_wait_response(command, self.RESP_OK, timeout=1.0)
        return response is not None and response.startswith(self.RESP_OK)
    
    # ==================== Channel Control Commands ====================
    
    def set_channel_off(self, channel: int) -> bool:
        """
        Turn off specified channel.
        
        Args:
            channel: Channel number (1-3)
            
        Returns:
            True if command acknowledged, False otherwise
        """
        if not (1 <= channel <= 3):
            self._log(f"Invalid channel: {channel} (must be 1-3)", "ERROR")
            return False
        
        command = f"{self.CMD_SET_CH} {channel} OFF"
        response = self._send_and_wait_response(command, self.RESP_OK, timeout=1.0)
        return response is not None and response.startswith(self.RESP_OK)
    
    def set_channel_dc(self, channel: int) -> bool:
        """
        Set channel to DC mode (continuous output).
        
        Args:
            channel: Channel number (1-3)
            
        Returns:
            True if command acknowledged, False otherwise
        """
        if not (1 <= channel <= 3):
            self._log(f"Invalid channel: {channel} (must be 1-3)", "ERROR")
            return False
        
        command = f"{self.CMD_SET_CH} {channel} DC"
        response = self._send_and_wait_response(command, self.RESP_OK, timeout=1.0)
        success = response is not None and response.startswith(self.RESP_OK)
        
        if not success and response and "NOT_READY" in response:
            self._log(f"Channel {channel} DC rejected: system not in READY state", "WARNING")
        
        return success
    
    def set_channel_pulse(self, channel: int, duration_ms: int) -> bool:
        """
        Pulse channel for specified duration.
        Channel automatically returns to OFF after pulse completes.
        
        Args:
            channel: Channel number (1-3)
            duration_ms: Pulse duration in milliseconds (1-60000)
            
        Returns:
            True if command acknowledged, False otherwise
        """
        if not (1 <= channel <= 3):
            self._log(f"Invalid channel: {channel} (must be 1-3)", "ERROR")
            return False
        
        if not (1 <= duration_ms <= 60000):
            self._log(f"Invalid pulse duration: {duration_ms} (must be 1-60000)", "ERROR")
            return False
        
        command = f"{self.CMD_SET_CH} {channel} PULSE {duration_ms}"
        response = self._send_and_wait_response(command, self.RESP_OK, timeout=1.0)
        success = response is not None and response.startswith(self.RESP_OK)
        
        if not success and response and "NOT_READY" in response:
            self._log(f"Channel {channel} PULSE rejected: system not in READY state", "WARNING")
        
        return success
    
    # ==================== Safety & Fault Management ====================
    
    def clear_fault(self) -> bool:
        """
        Clear latched fault condition.
        
        Fails if:
        - Any overcurrent status still asserted
        - Interlock not satisfied
        
        Returns:
            True if fault cleared, False otherwise
        """
        response = self._send_and_wait_response(self.CMD_CLEAR_FAULT, self.RESP_OK, timeout=1.0)
        success = response is not None and response.startswith(self.RESP_OK)
        
        if not success and response:
            if "FAULT_STILL_ACTIVE" in response:
                self._log("Clear fault rejected: overcurrent still active", "WARNING")
            elif "INTERLOCK_NOT_READY" in response:
                self._log("Clear fault rejected: interlock not satisfied", "WARNING")
        
        return success
    
    def arm(self) -> bool:
        """
        Arm system (alias for clear_fault).
        
        Returns:
            True if armed successfully, False otherwise
        """
        response = self._send_and_wait_response(self.CMD_ARM, self.RESP_OK, timeout=1.0)
        return response is not None and response.startswith(self.RESP_OK)
    
    # ==================== Status & Telemetry Access ====================
    
    def _get_latest_telemetry_copy(self) -> Dict:
        """Get thread-safe copy of latest telemetry."""
        with self._telemetry_lock:
            import copy
            return copy.deepcopy(self._latest_telemetry)
    
    def get_latest_telemetry(self) -> Dict:
        """
        Get most recently received telemetry data.
        
        Returns:
            Dictionary with 'system' and 'channels' keys
        """
        return self._get_latest_telemetry_copy()
    
    def get_system_state(self) -> str:
        """
        Get current system state.
        
        Returns:
            State string: READY, SAFE_INTERLOCK, SAFE_WATCHDOG, FAULT_LATCHED, or UNKNOWN
        """
        with self._telemetry_lock:
            return self._latest_telemetry['system']['state']
    
    def get_channel_mode(self, channel: int) -> str:
        """
        Get current mode for specified channel.
        
        Args:
            channel: Channel number (1-3)
            
        Returns:
            Mode string: OFF, DC, PULSE, or UNKNOWN
        """
        if not (1 <= channel <= 3):
            return "UNKNOWN"
        
        with self._telemetry_lock:
            return self._latest_telemetry['channels'][channel - 1]['mode']
    
    def get_channel_status(self, channel: int) -> Dict:
        """
        Get status inputs for specified channel.
        
        Args:
            channel: Channel number (1-3)
            
        Returns:
            Dictionary with keys: en_st, pwr_st, oc_st, gated_st
        """
        if not (1 <= channel <= 3):
            return {'en_st': 0, 'pwr_st': 0, 'oc_st': 0, 'gated_st': 0}
        
        with self._telemetry_lock:
            ch_data = self._latest_telemetry['channels'][channel - 1]
            return {
                'en_st': ch_data['en_st'],
                'pwr_st': ch_data['pwr_st'],
                'oc_st': ch_data['oc_st'],
                'gated_st': ch_data['gated_st']
            }
    
    def is_channel_overcurrent(self, channel: int) -> bool:
        """
        Check if channel has overcurrent condition.
        
        Args:
            channel: Channel number (1-3)
            
        Returns:
            True if overcurrent detected, False otherwise
        """
        status = self.get_channel_status(channel)
        return bool(status['oc_st'])


# ==================== Standalone Test ====================

def main():
    """Standalone test function."""
    import argparse
    
    parser = argparse.ArgumentParser(description="BCON Driver Test")
    parser.add_argument("--port", required=True, help="Serial port (e.g., COM3)")
    parser.add_argument("--baudrate", type=int, default=115200, help="Baud rate")
    parser.add_argument("--test", action="store_true", help="Run interactive test")
    args = parser.parse_args()
    
    # Create driver
    bcon = BCONDriver(port=args.port, baudrate=args.baudrate, debug=True)
    
    # Connect
    if not bcon.connect():
        print("Failed to connect to BCON")
        return
    
    print("\n=== BCON Connected ===\n")
    
    try:
        if args.test:
            # Interactive test
            while True:
                print("\nBCON Test Menu:")
                print("1. Ping")
                print("2. Get Status")
                print("3. Set Channel 1 DC")
                print("4. Set Channel 2 PULSE (250ms)")
                print("5. Stop All")
                print("6. Set Watchdog (1000ms)")
                print("7. Set Telemetry (500ms)")
                print("8. Clear Fault / ARM")
                print("9. Show Latest Telemetry")
                print("0. Exit")
                
                choice = input("\nSelect option: ").strip()
                
                if choice == "1":
                    result = bcon.ping()
                    print(f"Ping: {'SUCCESS' if result else 'FAILED'}")
                
                elif choice == "2":
                    status = bcon.get_status()
                    print(f"\nSystem State: {status['system']['state']}")
                    print(f"Fault Latched: {status['system']['fault_latched']}")
                    for i, ch in enumerate(status['channels'], 1):
                        print(f"\nChannel {i}:")
                        print(f"  Mode: {ch['mode']}")
                        print(f"  Enable: {ch['en_st']}, Power: {ch['pwr_st']}, Overcurrent: {ch['oc_st']}")
                
                elif choice == "3":
                    result = bcon.set_channel_dc(1)
                    print(f"Set Channel 1 DC: {'SUCCESS' if result else 'FAILED'}")
                
                elif choice == "4":
                    result = bcon.set_channel_pulse(2, 250)
                    print(f"Set Channel 2 PULSE: {'SUCCESS' if result else 'FAILED'}")
                
                elif choice == "5":
                    result = bcon.stop_all()
                    print(f"Stop All: {'SUCCESS' if result else 'FAILED'}")
                
                elif choice == "6":
                    result = bcon.set_watchdog(1000)
                    print(f"Set Watchdog: {'SUCCESS' if result else 'FAILED'}")
                
                elif choice == "7":
                    result = bcon.set_telemetry(500)
                    print(f"Set Telemetry: {'SUCCESS' if result else 'FAILED'}")
                
                elif choice == "8":
                    result = bcon.clear_fault()
                    print(f"Clear Fault: {'SUCCESS' if result else 'FAILED'}")
                
                elif choice == "9":
                    telemetry = bcon.get_latest_telemetry()
                    print(f"\nSystem: {telemetry['system']}")
                    for i, ch in enumerate(telemetry['channels'], 1):
                        print(f"Channel {i}: {ch}")
                
                elif choice == "0":
                    break
                
                else:
                    print("Invalid option")
        
        else:
            # Quick non-interactive test
            print("Running quick test...")
            
            # Ping
            if bcon.ping():
                print("✓ Ping successful")
            
            # Get status
            status = bcon.get_status()
            print(f"✓ System state: {status['system']['state']}")
            
            # Show telemetry
            time.sleep(1)
            telemetry = bcon.get_latest_telemetry()
            print(f"✓ Latest telemetry: {telemetry}")
    
    finally:
        print("\nDisconnecting...")
        bcon.disconnect()
        print("Done")


if __name__ == "__main__":
    main()
