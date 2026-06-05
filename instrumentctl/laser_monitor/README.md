# Laser Monitor Driver

Dashboard-side USB serial driver for the EBEAM Laser Monitor indicator.

This module complements the `ebeam-laser-monitor` Arduino firmware. The
firmware drives the physical radiation and beams-on indicator outputs; this
dashboard driver owns the host-side serial connection, periodically verifies
that the Arduino is alive, and sends state changes from the dashboard
subsystems.

## System Overview

The Laser Monitor system has two parts:

- `ebeam-laser-monitor` firmware runs on an Arduino Uno and drives two digital
  outputs:
  - radiation indicator
  - beams-on indicator
- `instrumentctl.laser_monitor` runs in the dashboard process and communicates
  with the Arduino over USB serial.

The dashboard creates `LaserMonitorDriver(port)` using the configured `Laser
Monitor` COM port. Once started, the driver runs a background worker thread that
owns all serial I/O. Dashboard callbacks only update desired state; they do not
write directly to the serial port.

Current dashboard wiring:

- `Beam Energy` calls `set_radiation_indicator(active)` when the +20 kV readback
  crosses the radiation indicator threshold.
- `Beam Pulse` calls `set_beams_on(active)` when any live beam pulse channel is
  active.

## Runtime Dependency

The driver requires `pyserial`:

```powershell
python -m pip install pyserial
```

If `pyserial` is not installed, constructing `LaserMonitorDriver` raises a
runtime error with the same install command.

## Serial Settings

The driver opens the Arduino USB serial port with the settings expected by the
firmware:

| Setting | Value |
| --- | --- |
| Baud rate | `9600` |
| Data bits | `8` |
| Parity | `None` |
| Stop bits | `1` |
| Read timeout | `0.25 s` |
| Write timeout | `0.5 s` |
| Line ending | `\n` |
| Encoding | ASCII |

Opening an Arduino Uno serial port resets the board, so the driver waits `2.0 s`
after connecting before flushing serial buffers and starting normal polling.

## Communication Protocol

All messages are ASCII and newline-delimited. The driver uses a strict
request/response exchange: every command must receive the expected response, or
the connection is treated as unhealthy and the worker reconnects.

### Poll

Sent every `0.5 s`:

```text
PING
```

Expected response:

```text
PONG
```

Successful polls set `is_connected()` to `True`.

### State Update

Sent after reconnect and whenever either desired indicator value changes:

```text
STATE beams=<0|1> radiation=<0|1>
```

Expected response:

```text
OK
```

Examples:

```text
STATE beams=0 radiation=0
STATE beams=1 radiation=0
STATE beams=0 radiation=1
STATE beams=1 radiation=1
```

## Driver Lifecycle

`LaserMonitorDriver(port)` starts its worker thread immediately.

Public API:

- `set_beams_on(active)` updates the desired beams-on indicator state.
- `set_radiation_indicator(active)` updates the desired radiation indicator
  state.
- `is_connected()` reports whether the most recent poll exchange succeeded.
- `last_error` returns the most recent connection or protocol error text.
- `disconnect()`, `close()`, and `close_com_ports()` stop the worker and close
  the serial port.

On disconnect, the driver first attempts to send `beams=0` while preserving the
last desired radiation indicator state. This leaves the physical beams-on
indicator off during dashboard shutdown when the Arduino is still reachable.

## Reconnect and Failure Behavior

The worker handles serial failures without blocking dashboard callbacks:

1. If the port is closed or a transaction fails, mark the driver disconnected.
2. Close the serial object.
3. Reconnect with exponential backoff from `0.5 s` up to `5.0 s`.
4. After a successful reconnect, send the latest desired state again.

Unexpected responses, missing responses, write failures, and decode issues are
recorded in `last_error`.

The firmware also has its own dashboard communication watchdog. If it receives
no valid dashboard message for 4 seconds, it forces only the beams-on output LOW
and leaves the radiation indicator unchanged. The driver therefore polls every
500 ms to keep the firmware watchdog satisfied during normal operation.
