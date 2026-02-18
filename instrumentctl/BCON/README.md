# BCON (Beam Controller) Driver

## Overview

The BCON driver provides programmatic control of the Beam Controller Arduino firmware over RS-485 serial communication. This driver handles command formatting, response parsing, telemetry monitoring, and status tracking for three independent pulser channels.

## Hardware

**Device:** Arduino Mega running BCON firmware  
**Interface:** RS-485 serial communication  
**Baud Rate:** 115200 (configurable)  
**Line Termination:** `\n` (newline)

## Features

- **Command Interface:** Full support for all BCON firmware commands (PING, STATUS, SET CH, etc.)
- **Telemetry Monitoring:** Automatic parsing of system and channel telemetry
- **State Tracking:** Real-time monitoring of system state (READY, SAFE_INTERLOCK, SAFE_WATCHDOG, FAULT_LATCHED)
- **Channel Control:** Independent control of 3 pulser channels (OFF, DC, PULSE modes)
- **Safety Features:** Watchdog configuration, fault management, interlock monitoring
- **Status Monitoring:** Per-channel status inputs (enable, power, overcurrent, gated)

## Supported Commands

| Command | Method | Description |
|---------|--------|-------------|
| `PING` | `ping()` | Check communication and refresh watchdog |
| `STATUS` | `get_status()` | Get full system and channel status |
| `STOP ALL` | `stop_all()` | Force all channels to OFF mode |
| `SET WATCHDOG` | `set_watchdog(ms)` | Configure watchdog timeout (50-60000 ms) |
| `SET TELEMETRY` | `set_telemetry(ms)` | Configure telemetry interval (0=disabled) |
| `SET CH OFF` | `set_channel_off(channel)` | Turn off specific channel |
| `SET CH DC` | `set_channel_dc(channel)` | Set channel to DC mode |
| `SET CH PULSE` | `set_channel_pulse(channel, duration_ms)` | Pulse channel for duration |
| `CLEAR FAULT` / `ARM` | `clear_fault()` or `arm()` | Clear latched faults |

## Usage Example

```python
from instrumentctl.BCON import BCONDriver

# Create driver instance
bcon = BCONDriver(port='COM3', baudrate=115200, timeout=1.0, debug=True)

# Connect to hardware
if bcon.connect():
    print("Connected to BCON")
    
    # Ping device
    if bcon.ping():
        print("BCON responding")
    
    # Get status
    status = bcon.get_status()
    print(f"System state: {status['system']['state']}")
    
    # Configure watchdog (1 second)
    bcon.set_watchdog(1000)
    
    # Enable telemetry (500ms interval)
    bcon.set_telemetry(500)
    
    # Set channel 1 to DC mode
    if bcon.set_channel_dc(1):
        print("Channel 1 in DC mode")
    
    # Pulse channel 2 for 250ms
    if bcon.set_channel_pulse(2, 250):
        print("Channel 2 pulsing")
    
    # Get real-time telemetry
    telemetry = bcon.get_latest_telemetry()
    print(f"Channel 1 mode: {telemetry['channels'][0]['mode']}")
    
    # Stop all channels
    bcon.stop_all()
    
    # Disconnect
    bcon.disconnect()
else:
    print("Failed to connect to BCON")
```

## Telemetry Format

### System Telemetry (`SYS` line)
```
SYS state=READY reason=NONE fault_latched=0 telemetry_ms=1000
```

Fields:
- `state`: READY, SAFE_INTERLOCK, SAFE_WATCHDOG, FAULT_LATCHED
- `reason`: NONE, INTERLOCK_LOW, WATCHDOG_EXPIRED, FAULT_LATCHED
- `fault_latched`: 0 or 1
- `telemetry_ms`: Configured interval (0 = disabled)

### Channel Telemetry (`CHn` line)
```
CH1 mode=DC pulse_ms=0 en_st=1 pwr_st=1 oc_st=0 gated_st=0
```

Fields:
- `mode`: OFF, DC, PULSE
- `pulse_ms`: Configured pulse duration (0 if not pulsing)
- `en_st`: Enable status input (0/1)
- `pwr_st`: Power status input (0/1)
- `oc_st`: Over-current status input (0/1)
- `gated_st`: Gated status input (0/1)

## API Reference

### Connection Management

#### `connect() -> bool`
Connect to BCON hardware over serial port. Returns `True` on success.

#### `disconnect() -> None`
Close serial connection and cleanup resources.

#### `is_connected() -> bool`
Check if currently connected to hardware.

### Basic Commands

#### `ping() -> bool`
Send PING command and wait for PONG response. Also refreshes communication watchdog.

#### `get_status() -> dict`
Request and parse full system status. Returns dictionary with `system` and `channels` keys.

#### `stop_all() -> bool`
Force all channels to OFF mode immediately.

### Configuration

#### `set_watchdog(timeout_ms: int) -> bool`
Configure communication watchdog timeout (50-60000 ms). If no command received within timeout, system enters SAFE_WATCHDOG state.

#### `set_telemetry(interval_ms: int) -> bool`
Configure periodic telemetry transmission interval. Set to 0 to disable automatic telemetry.

### Channel Control

#### `set_channel_off(channel: int) -> bool`
Turn off specified channel (1-3). Only works in READY state.

#### `set_channel_dc(channel: int) -> bool`
Set channel (1-3) to DC mode (continuous output). Only works in READY state.

#### `set_channel_pulse(channel: int, duration_ms: int) -> bool`
Pulse channel (1-3) for specified duration (1-60000 ms). Channel automatically returns to OFF after pulse completes. Only works in READY state.

### Safety & Fault Management

#### `clear_fault() -> bool`
Clear latched fault condition. Alias: `arm()`. Fails if overcurrent still active or interlock not satisfied.

#### `arm() -> bool`
Alias for `clear_fault()`.

### Status & Telemetry

#### `get_latest_telemetry() -> dict`
Return most recently received telemetry data without sending a command.

#### `get_system_state() -> str`
Return current system state: READY, SAFE_INTERLOCK, SAFE_WATCHDOG, or FAULT_LATCHED.

#### `get_channel_mode(channel: int) -> str`
Return current mode for channel (1-3): OFF, DC, or PULSE.

#### `get_channel_status(channel: int) -> dict`
Return status inputs for channel (1-3): en_st, pwr_st, oc_st, gated_st.

## Error Handling

All command methods return `bool` or parsed data structures. Check return values to detect command failures:

```python
if not bcon.set_channel_dc(1):
    print("Failed to set channel 1 to DC mode")
    # Check if system is in READY state
    if bcon.get_system_state() != "READY":
        print("System not in READY state")
```

Enable debug mode to see command/response traffic:
```python
bcon = BCONDriver(port='COM3', debug=True)
```

## Thread Safety

The driver uses a threading lock (`_serial_lock`) to ensure thread-safe access to the serial port. Multiple threads can safely call driver methods concurrently.

## Dependencies

- `pyserial` - Serial communication library

## Development

Run driver standalone for testing:

```bash
python -m instrumentctl.BCON.bcon_driver --port COM3 --test
```
