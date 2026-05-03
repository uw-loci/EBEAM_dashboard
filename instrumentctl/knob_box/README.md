# Knob Box Driver Documentation

This README documents the dashboard-side Knob Box integration in `instrumentctl/knob_box/`.

### System Overview

The Knob Box is the operator panel and local monitoring/interlock interface for four high-voltage supplies:

- `+1 kV` Matsusada
- `-1 kV` Matsusada
- `+20 kV` Bertan
- `+3 kV` Bertan

On the hardware side, the system is split into:

- Four monitoring Arduinos that read supply telemetry and expose it on RS-485 / Modbus RTU
- One Logic Arduino that enforces beam/interlock behavior

Only the monitoring Arduinos speak Modbus. The Logic Arduino is visible to the dashboard only through the `+3 kV` monitoring Arduino, which republishes live logic state and latched fault history in its Modbus register map.

Inside this dashboard repo:

- `knob_box_modbus.py` polls all four monitor Arduinos over one RS-485 serial port
- `subsystem/beam_energy/beam_energy.py` consumes that data and updates the GUI

### Hardware / Serial Summary

| Item | Value |
|------|-------|
| Physical transport | RS-485 |
| Protocol | Modbus RTU |
| Active dashboard driver | `KnobBoxModbus` |
| Dashboard COM-port key | `KnobBox` |
| Baud rate | `9600` |
| Data bits | `8` |
| Parity | `N` |
| Stop bits | `1` |
| Default timeout | `0.5 s` |
| Modbus unit IDs | `1-4` |

### Power Supply / Unit Mapping

| Unit ID | Supply | Role in dashboard |
|---------|--------|-------------------|
| `1` | `+1 kV` Matsusada | Local telemetry plus Matsusada reset-state indication |
| `2` | `-1 kV` Matsusada | Local telemetry plus Matsusada reset-state indication |
| `3` | `+20 kV` Bertan | Local telemetry |
| `4` | `+3 kV` Bertan | Local telemetry plus Logic Arduino state, flags, and handshake status |

### Current Dashboard Integration

The current dashboard path is:

```python
from instrumentctl.knob_box.knob_box_modbus import KnobBoxModbus
```

`KnobBoxModbus` is not exported from `instrumentctl/__init__.py`, so callers must import it from the full module path.

#### Constructor Parameters

| Parameter | Default | Meaning |
|-----------|---------|---------|
| `port` | required | Serial COM port for the RS-485 adapter |
| `baudrate` | `9600` | Modbus baud rate |
| `timeout` | `0.5` | Read timeout in seconds |
| `parity` | `"N"` | Serial parity |
| `stopbits` | `1` | Serial stop bits |
| `bytesize` | `8` | Serial data bits |
| `logger` | `None` | Optional dashboard logger |
| `debug_mode` | `True` | Stored flag for debug-oriented behavior/logging |

#### Core Methods Used by the Dashboard

| Method | Purpose |
|--------|---------|
| `connect()` | Open the Modbus serial client with exponential reconnect backoff |
| `disconnect()` | Close the Modbus serial client |
| `poll_all()` | Poll all four unit IDs, rotating start order each pass |
| `get_data_snapshot()` | Return a copy of the latest per-unit data |
| `get_unit_connection_status(uid)` | Report whether a unit has polled successfully within `CONNECTION_TIMEOUT` |
| `any_unit_connected()` | Report whether any unit has polled successfully within `CONNECTION_TIMEOUT` |
| `close()` | Compatibility alias that calls `disconnect()` |

#### Basic Usage

```python
from instrumentctl.knob_box.knob_box_modbus import KnobBoxModbus

knob_box = KnobBoxModbus(port="COM13")

if knob_box.connect():
    snapshot = knob_box.poll_all()
    unit_4 = snapshot[4]
    print(unit_4["actual_voltage_V"])
    print(unit_4["logic_alive"])

knob_box.close()
```

#### Polling and Reconnect Behavior

- `UNIT_IDS` is fixed to `[1, 2, 3, 4]`
- `poll_all()` rotates the unit polling order so the same device is not always last
- Each unit read is attempted up to `3` times before that unit is marked failed for the current pass
- Failed unit polls back off exponentially from `0.5 s` up to `5.0 s`
- Failed connection attempts also back off exponentially from `0.5 s` up to `5.0 s`
- Connection freshness is based on `last_success` timestamps, not just whether the serial port is open
- `CONNECTION_TIMEOUT` is `10.0 s`; if a unit has not answered within that window, the dashboard treats that unit as disconnected

#### How `BeamEnergySubsystem` Uses It

`subsystem/beam_energy/beam_energy.py` instantiates `KnobBoxModbus` using the COM port stored under the `KnobBox` key in the dashboard COM-port configuration.

The subsystem then:

- Starts a polling thread that calls `poll_all()` every `0.2 s`
- Calls `get_data_snapshot()` during UI refresh
- Calls `get_unit_connection_status(uid)` to decide whether to show live data or placeholder values
- Calls `any_unit_connected()` to decide when to trigger reconnect behavior
- Refreshes the UI every `500 ms`

If no unit has reported successfully within `CONNECTION_TIMEOUT`, the subsystem falls back to placeholder values and starts reconnect logic.

### Modbus Register Contract

The current driver expects one contiguous block of six input registers from each unit:

| Address | Constant | Meaning |
|---------|----------|---------|
| `0` | `IREG_V_SET_ADDR` | Set voltage in integer volts |
| `1` | `IREG_V_READ_ADDR` | Measured voltage in integer volts |
| `2` | `IREG_I_READ_ADDR` | Measured current in integer microamps |
| `3` | `IREG_3KV_RESET_COUNT_ADDR` | `+3 kV` timer/reset-event counter |
| `4` | `DINPUT_UNLATCHED_SIGNALS_ADDR` | Packed unlatched signals word |
| `5` | `DINPUT_LATCHED_FLAGS_ADDR` | Packed latched flags word |

Registers `0-5` are all read through Modbus function code `04` in one request per unit.

#### Unlatched Signals Word (`register 4`)

| Bit | Mask | Driver field | Meaning |
|-----|------|--------------|---------|
| `0` | `UNLATCHED_SIGNAL_MASK_HVENABLE` | raw `hv_enable` source for units `1-3` | Local HV enable switch telemetry |
| `1` | `UNLATCHED_SIGNAL_MASK_RESET_STATE_1KV` | `reset_state_1kV` | Matsusada inferred reset/overcurrent state |
| `2` | `UNLATCHED_SIGNAL_MASK_ARM80KV_ENABLE` | `arm_80kV` | Raw `Arm 80kV` switch state from the `+3 kV` monitor path |
| `3` | `UNLATCHED_SIGNAL_MASK_CCSPOWER_ENABLE` | `ccs_power` | Logic Arduino CCS enable output mirror on unit `4` |
| `4` | `UNLATCHED_SIGNAL_MASK_ARMBEAMS_ENABLE` | `arm_beams` | Logic Arduino Arm Beams output mirror on unit `4` |
| `5` | `UNLATCHED_SIGNAL_MASK_3KV_ENABLE` | `3kV_enable` | Logic Arduino `3 kV` enable output mirror on unit `4` |
| `6` | `UNLATCHED_SIGNAL_MASK_NOMOP` | `nomop_flag` | Logic Arduino Nominal Operation flag on unit `4` |
| `7` | `UNLATCHED_SIGNAL_MASK_LOGIC_ALIVE` | `logic_alive` | Logic alive heartbeat derived from D9 ack-back edge detection |

#### Latched Flags Word (`register 5`)

| Bit | Mask | Driver field | Meaning |
|-----|------|--------------|---------|
| `4` | `LATCHED_FLAG_MASK_3KV_TIMER` | `timer_state_3kV` | `3 kV` timer event occurred since the last ACK cycle |
| `5` | `LATCHED_FLAG_MASK_ARMBEAMS_SWITCH` | `armbeams_flag` | Arm Beams switch asserted since the last ACK cycle |
| `6` | `LATCHED_FLAG_MASK_CCSPOWER_ALLOW` | `ccspower_flag` | CCS Power Allow switch asserted since the last ACK cycle |
| `7` | `LATCHED_FLAG_MASK_ARM80KV_SWITCH` | `arm80kv_flag` | Arm 80 kV switch asserted since the last ACK cycle |
| `8` | `LATCHED_FLAG_MASK_1K_VCOMP` | `vcomp_1k_flag` | `+1 kV` voltage comparator fault since the last ACK cycle |
| `9` | `LATCHED_FLAG_MASK_1K_ICOMP` | `icomp_1k_flag` | `+1 kV` current comparator fault since the last ACK cycle |
| `10` | `LATCHED_FLAG_MASK_NEG_1K_VCOMP` | `neg_vcomp_1k_flag` | `-1 kV` voltage comparator fault since the last ACK cycle |
| `11` | `LATCHED_FLAG_MASK_NEG_1K_ICOMP` | `neg_icomp_1k_flag` | `-1 kV` current comparator fault since the last ACK cycle |
| `12` | `LATCHED_FLAG_MASK_20K_VCOMP` | `vcomp_20k_flag` | `+20 kV` voltage comparator fault since the last ACK cycle |
| `13` | `LATCHED_FLAG_MASK_20K_ICOMP` | `icomp_20k_flag` | `+20 kV` current comparator fault since the last ACK cycle |
| `14` | `LATCHED_FLAG_MASK_3K_VCOMP` | `vcomp_3k_flag` | `+3 kV` voltage comparator fault since the last ACK cycle |
| `15` | `LATCHED_FLAG_MASK_3K_ICOMP` | `icomp_3k_flag` | `+3 kV` current comparator fault since the last ACK cycle |

Bits `0-3` are currently unused.

#### Important Decoding Rules

- `actual_current_mA` is derived from register `2` by dividing the integer microamp value by `1000.0`
- `3kv_reset_count` is only meaningful for unit `4`; other units should normally report `0`
- `arm_beams` and `ccs_power` are live Logic Arduino output mirrors on the `+3 kV` path, not raw switch inputs
- For unit `4`, `hv_enable` is intentionally overridden to use `3kV_enable` instead of the raw HV-enable switch bit

That unit-`4` special case matters because the Beam Energy panel uses `hv_enable` for the `Output` indicator. For the `+3 kV` supply, that indicator therefore reflects the logic-authorized enable output, not just the front-panel request switch.


#### Exposed Data Shape

`get_power_supply_data()` returns a copy of:

| Key | Meaning |
|-----|---------|
| `set_voltage` | Parsed set voltage as `float` or `None` |
| `meas_voltage` | Parsed measured voltage as `float` or `None` |
| `meas_current` | Parsed measured current as `float` or `None` |
| `connected` | Serial connection state |
