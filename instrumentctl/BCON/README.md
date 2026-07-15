# BCON (Beam Controller) Driver

## Overview

The BCON driver provides programmatic control of the Beam Controller Arduino
firmware over Modbus RTU / RS-485. It handles binary Modbus framing, register
polling, queued writes, firmware command confirmation, and status tracking for
three independent pulser channels.

## Hardware

**Device:** Arduino Mega running BCON firmware
**Interface:** Modbus RTU over RS-485 serial communication
**Baud Rate:** 115200 (configurable)
**Data Format:** 8 data bits, no parity, 1 stop bit

## Features

- **Command Interface:** FC03 holding-register reads and FC06 single-register writes
- **Telemetry Monitoring:** Background polling of system and channel status registers
- **State Tracking:** Real-time monitoring of system state (READY, SAFE_INTERLOCK, SAFE_WATCHDOG)
- **Channel Control:** Independent control of 3 pulser channels (OFF, DC, PULSE, PULSE_TRAIN modes)
- **Safety Features:** Watchdog configuration, external interlock monitoring, confirmed `ALL_OFF`, and stale-write invalidation
- **Status Monitoring:** Per-channel status inputs (toggle busy, power, overcurrent, gated)

## Supported Operations

| Operation | Method | Description |
|---------|--------|-------------|
| Communication check | `ping()` | Read the system-state register; BCON has no literal PING command |
| Cached status | `get_status()` | Get the latest polled system and channel status |
| `ALL_OFF` | `stop_all()` | Force all channels to OFF mode and confirm firmware execution |
| Set watchdog | `set_watchdog(ms)` | Configure watchdog timeout (50-60000 ms) |
| Set telemetry | `set_telemetry(ms)` | Configure telemetry interval (0=disabled) |
| Set channel OFF | `set_channel_off(channel)` | Stage OFF and queue the apply command |
| Set channel DC | `set_channel_dc(channel)` | Stage DC and queue the apply command |
| Set channel pulse | `set_channel_pulse(channel, duration_ms)` | Stage a pulse and queue the apply command |
| PVX enable toggle | `trigger_channel_enable_toggle(channel)` | Write one toggle request to R13/R23/R33 |

## Usage Example

```python
from instrumentctl.BCON import BCONDriver

# Create driver instance
bcon = BCONDriver(port='COM3', baudrate=115200, timeout=1.0)

# Connect to hardware
if bcon.connect():
    print("Connected to BCON")

    # Check communication with a Modbus register read
    if bcon.ping():
        print("BCON responding")

    # Get the latest cached status
    status = bcon.get_status()
    print(f"System state: {status['system']['state']}")

    # Configure watchdog (1 second)
    bcon.set_watchdog(1000)

    # Configure firmware telemetry (500ms interval)
    bcon.set_telemetry(500)

    # Queue channel 1 DC mode
    if bcon.set_channel_dc(1):
        print("Channel 1 DC request queued")

    # Queue a channel 2 pulse
    if bcon.set_channel_pulse(2, 250):
        print("Channel 2 pulse request queued")

    # Get the latest cached telemetry
    telemetry = bcon.get_latest_telemetry()
    print(f"Channel 1 mode: {telemetry['channels'][0]['mode']}")

    # Stop all channels and verify firmware confirmation
    if not bcon.stop_all():
        print("STOP ALL was not confirmed")
    
    # Disconnect
    bcon.disconnect()
else:
    print("Failed to connect to BCON")
```

## Cached Status Format

`get_status()` and `get_latest_telemetry()` return the latest complete register
poll as a dictionary. They do not initiate a new serial read.

### System Status

Important fields include:

- `state`: READY, SAFE_INTERLOCK, SAFE_WATCHDOG, or UNKNOWN
- `interlock_ok`: Hardware-interlock status
- `watchdog_ok`: Communication-watchdog status
- `fault_latched`: Reserved compatibility field; current firmware always reports 0
- `telemetry_ms`: Configured telemetry interval
- `supervisor_state`: Current firmware supervisor state
- `last_command_result`: NONE, QUEUED, EXECUTED, or REJECTED
- `last_reject_reason` and `last_cmd_seq`: Command-confirmation diagnostics

### Channel Status

Important fields include:

- `mode`: OFF, DC, PULSE, or PULSE_TRAIN
- `pulse_ms`, `count`, and `remaining`: Actual pulse configuration/status
- `toggle_busy`: `1` only while firmware is emitting the approximately 100 ms
  PVX enable-toggle pulse; otherwise `0`
- `pwr_st`, `oc_st`, and `gated_st`: Hardware status inputs
- `output_level`: Current channel output level
- `run_state`, `stop_reason`, `complete`, and `aborted`: Supervisor status

## API Reference

### Connection Management

#### `connect() -> bool`
Connect to BCON hardware over serial port. Returns `True` on success.

#### `disconnect() -> None`
Attempt `ALL_OFF`, close the serial connection, and clean up resources.

#### `is_connected() -> bool`
Check if currently connected to hardware.

### Basic Commands

#### `ping() -> bool`
Check communication by reading the system-state register over Modbus.

#### `get_status() -> dict`
Return the latest cached system and channel status.

#### `stop_all() -> bool`
Force all channels to OFF mode immediately. Returns `True` only when firmware
diagnostics confirm the `ALL_OFF` command executed; a closed serial port,
rejection, or inconclusive diagnostics return `False`.

Before sending `ALL_OFF`, the driver advances an internal write epoch while
holding the serial lock and clears the pending write queue. Queued writes carry
the epoch captured when they were enqueued, so any poll-thread write that was
already dequeued before `ALL_OFF` but reaches the serial port afterward is
dropped as stale. This prevents earlier output-producing writes from running
after a confirmed all-off shutdown.

### Dashboard operation tokens

An `operation_token` is an opaque host-side correlation ID, such as `bcon-7`,
created by Main Control and passed through Beam Pulse into the driver. It is not
sent to BCON firmware, is not an arming credential, and does not replace the
driver's write epoch.

For a tokenized queued write, the internal metadata contains the token, a batch
ID (normally the same token), a `stage` flag for parameter/mode writes, and a
`terminal` flag for the final nonzero `COMMAND` write. The driver reports:

- `command_sent` with `token`, command code, and monotonic `sent_at` time after
  the terminal FC06 write completes.
- `command_result` with `operation_token`, accepted/rejected status, reject
  reason, and firmware command sequence.
- `operation_failed` or `operation_cancelled` with `token` and a reason.

Beam Pulse forwards those as `operation_sent`, `operation_result`,
`operation_failed`, and `operation_cancelled`. Main Control accepts an event
only when its token matches the currently pending operation, so late results
from an older request are ignored.

Full register-poll messages are intentionally not tokenized. After firmware
reports a command executed, Main Control waits for a complete poll whose
`completed_at` timestamp is later than `command_sent.sent_at`; OFF-related
operations also require the relevant channels to report mode OFF and output
low. This keeps command execution confirmation separate from poll-derived
hardware state.

If any tokenized staged write fails or is unconfirmed, the batch's remaining
writes are suppressed, the failure is logged as CRITICAL, and the driver forces
`ALL_OFF`. A rejected or inconclusive terminal apply command after staging also
forces `ALL_OFF`.

### Configuration

#### `set_watchdog(timeout_ms: int) -> None`
Validate and queue a watchdog timeout from 50-60000 ms. If no command is
received within the timeout, the system enters SAFE_WATCHDOG state.

#### `set_telemetry(interval_ms: int) -> None`
Queue the firmware telemetry interval. Set to 0 to disable firmware telemetry;
dashboard status remains register-poll driven.

### Channel Control

#### `trigger_channel_enable_toggle(channel: int) -> bool`

Request one 100 ms PVX enable-toggle pulse for channel 1-3 by writing `1` to
R13, R23, or R33. The firmware immediately self-clears the holding register;
writing `0` is a no-op and values greater than `1` are rejected with
`LAST_ERROR=3`. The FC06 response acknowledges the write but does not prove the
firmware accepted the toggle. A request during that channel's active pulse is
rejected locally when another toggle request for that channel was sent within
the prior 150 ms. Firmware still rejects a request during an active pulse
through `LAST_ERROR=11`.

R114/R124/R134 are `ENABLE_TOGGLE_BUSY` flags: `1` only during the associated 100 ms pulse.

#### `set_channel_off(channel: int) -> bool`
Validate and queue an OFF stage/apply request. `True` means the request was
queued, not that firmware execution has been confirmed.

#### `set_channel_dc(channel: int) -> bool`
Validate and queue a DC stage/apply request. Firmware remains authoritative for
rejecting the command while a safety condition is active.

#### `set_channel_pulse(channel: int, duration_ms: int) -> bool`
Validate and queue a pulse request for 1-60000 ms. The channel automatically
returns to OFF after the pulse completes.

### Safety Behavior

Current firmware does not expose a clear-fault / arm command. The dashboard's
BEAMS ARMED control is a frontend software interlock, while the external
hardware interlock and communication watchdog remain the firmware-level safety
mechanisms that can force outputs off.

### Status & Telemetry

#### `get_latest_telemetry() -> dict`
Return the latest cached structured status without sending a command.

#### `get_system_state() -> str`
Return current system state: READY, SAFE_INTERLOCK, or SAFE_WATCHDOG.

#### `get_channel_mode(channel: int) -> str`
Return current mode for channel (1-3): OFF, DC, PULSE, or PULSE_TRAIN.

#### `get_channel_status(channel: int) -> dict`
Return live and supervisor status for channel 1-3, including mode,
`toggle_busy`, `pwr_st`, `oc_st`, `gated_st`, and `output_level`.

## Error Handling

Queued channel methods return `bool` for validation/queueing. A `True` result
does not confirm firmware execution; use tokenized results and a later poll for
coordinated dashboard operations. `stop_all()` is different because it returns
`True` only after firmware diagnostics report `EXECUTED`.

```python
if not bcon.set_channel_dc(1):
    print("Failed to queue channel 1 DC mode")
```

## Thread Safety

The driver uses a threading lock (`_serial_lock`) to ensure thread-safe access
to the serial port. Multiple threads can safely call driver methods
concurrently. Queued writes are also tagged with an internal write epoch;
`stop_all()` advances that epoch to invalidate queued or already-dequeued writes
from before the all-off request.

## Dependencies

- `pyserial` - Serial communication library

## Development

Run driver standalone for testing:

```bash
python -m instrumentctl.BCON.bcon_driver --port COM3 --test
```
