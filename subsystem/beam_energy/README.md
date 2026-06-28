# Beam Energy Subsystem

## Purpose

`beam_energy.py` implements the dashboard subsystem used to monitor and supervise the beam energy power supplies.

The subsystem sits between the Tkinter GUI and the Knob Box hardware controller. It is responsible for:

- Building the beam-energy UI.
- Managing communication with the Knob Box via Modbus (RS-485).
- Displaying live voltage, current, and output states for each supply.
- Reflecting interlock, arming, and system status conditions.
- Handling connection monitoring and automatic reconnection.

## Hardware Relationships

The subsystem interfaces with the **Knob Box**, which acts as the hardware control and monitoring layer for multiple high-voltage supplies.

### Power Supplies Monitored

- +1 kV Matsusada
- –1 kV Matsusada
- +3 kV Bertan
- +20 kV Bertan
- +80 kV Glassman (interlock only, not directly controlled)

The Knob Box:

- Provides **voltage/current telemetry** for each supply.
- Handles **fast interlocks and protection logic** (e.g., overcurrent shutdowns).
- Exposes status via **Modbus registers** to the dashboard.
- Can **force shutdowns** (e.g., 3 kV forced-off condition).
- Monitors system-level faults and can trigger beam shutdown within ~1 ms per spec.

## High-Level Behavior

At runtime the subsystem has three main jobs:

1. Build and maintain the GUI for all beam energy supplies.
2. Maintain a live connection to the Knob Box controller.
3. Continuously poll and update system state for display.

## UI Structure

The UI consists of:

### Power Supply Panels (4 total)

Each supply has a vertical panel showing:

- Communication status indicator.
- Output status (ENABLED / DISABLED).
- Set voltage (from Knob Box).
- Measured voltage.
- Measured current.

Additional indicators:

- Matsusada supplies:
  - Overcurrent/reset indicator.
- 3 kV Bertan:
  - Forced-off indicator.

### System Status Panel

Displays global system state:

- Arm Beams (Armed / Unarmed)
- CCS Power (On / Off)
- 80 kV Interlock (Armed / Unarmed)
- Logic Communications (Connected / Disconnected)
- Interlocks (Fault / OK)

## Knob Box Communication

### Initialization

`initialize_knob_box_modbus()`:

- Creates a `KnobBoxModbus` instance using the configured COM port.
- Establishes RS-485 communication.
- Starts a background polling thread on success.

### Polling

A background thread (`polling_loop`) runs every ~200 ms:

- Calls `poll_all()` on the Knob Box controller.
- Updates internal data buffers.
- Detects communication failures.

### Reconnection Strategy

- Automatic reconnect attempts are scheduled on failure.
- Backoff timing is respected via controller state.
- Reconnect runs in a background thread to avoid UI blocking.

## Data Flow

### Source of Truth

All live data comes from the Knob Box:

- Voltages
- Currents
- Output states
- Interlock and system flags

### Update Cycle

`update_readings()` runs every 500 ms:

- Processes reconnect requests.
- Checks controller health.
- Updates all GUI elements:
  - Voltage/current displays
  - Output states
  - Indicator colors
- Falls back to default (“--”) values if disconnected.

## Status Indicators

Color conventions:

- **Blue** → Communication active  
- **Red** → Fault / disconnected / disabled  
- **Green** → Enabled / healthy state  
- **Yellow** → Warning (e.g., overcurrent reset)  
- **White** → Neutral / inactive  

## Protection & Interlocks

Protection logic is primarily enforced in hardware (Knob Box), not in this subsystem.

The subsystem reflects:

- Overcurrent conditions (Matsusada reset flags)
- Forced shutdowns (3 kV supply)
- Global interlock status
- Beam arm state

Per system design:

- The Knob Box can shut down beam-related supplies within ~1 ms on fault.
- The dashboard is responsible for **visibility**, not first-line protection.

## Key Methods To Read First

- `__init__()`
- `setup_ui()`
- `initialize_knob_box_modbus()`
- `polling_loop()`
- `update_readings()`
- `update_output_status()`
- `update_connection_status()`
- `update_indicators_panel()`

## Relationship To Knob Box

`beam_energy.py` is the **monitoring and visualization layer**.

It decides:

- How system state is displayed.
- How connection health is handled.
- When to attempt reconnection.

The Knob Box:

- Performs **real-time control and protection**.
- Interfaces directly with high-voltage supplies.
- Enforces interlocks and safety-critical behavior.

In short:

- `beam_energy.py` shows what is happening.
- The Knob Box decides what is allowed to happen.