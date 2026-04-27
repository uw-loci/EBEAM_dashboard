# Cathode Heating Subsystem

## Purpose

`cathode_heating.py` implements the dashboard subsystem used to operate three cathode heater channels, labeled A, B, and C.

The subsystem sits between the Tkinter GUI and the hardware drivers. It is responsible for:

- Building the cathode-heating UI.
- Managing one `PowerSupply9104` per cathode.
- Managing the temperature-controller connection.
- Validating operator-entered voltage and current requests.
- Coordinating immediate sets vs. ramped sets.
- Polling live voltage, current, mode, and temperature data for display.

## Hardware Relationships

Each cathode channel is backed by:

- One BK Precision 9104 power supply, used for heater voltage/current control.
- One temperature-controller input, used for clamp-temperature monitoring.

The subsystem creates and stores three power-supply driver instances in `self.power_supplies`, one for each cathode.

## High-Level Behavior

At runtime the subsystem has three main jobs:

1. Build and maintain the GUI state for each cathode.
2. Send validated setpoint changes to the power supply drivers.
3. Refresh measured values and plots on a 500 ms loop.

## UI Structure Per Cathode

Each cathode frame contains:

- A `Main` tab for operator control and live readback.
- A `Config` tab for protection limits, slew rates, and status queries.

The `Main` tab includes:

- Heater current control:
  - Sent current display.
  - Goal current display.
  - Entry box and `Set` button.
  - `+0.01` and `-0.01` nudge buttons.
- Heater voltage control:
  - Sent voltage display.
  - Goal voltage display.
  - Entry box and `Set` button.
  - `+0.02` and `-0.02` nudge buttons.
- Output controls:
  - Output toggle button.
  - Output mode dropdown.
  - `STOP RAMP` button.
- Read-only displays:
  - Predicted output values.
  - Measured heater current and voltage.
  - Clamp temperature.
  - CV/CC mode indicator.
  - Temperature plot.

The `Config` tab includes:

- Overtemperature limit.
- Overvoltage protection (OVP).
- Overcurrent protection (OCP).
- Current slew rate.
- Voltage slew rate.
- Query-settings button and status readback.

## Output Modes

Each cathode has an output mode selector with three choices:

- `Immediate Set`
- `Ramp Current`
- `Ramp Voltage`

These map to the subsystem state:

- `self.ramp_status[index]`
- `self.ramp_control_mode[index]`

### Immediate Set

When output is already on:

- Current changes call `set_current(...)` directly.
- Voltage changes call `set_voltage(...)` directly.

When output is turned on:

- The subsystem requires both a stored target current and target voltage.
- It enables the output and then sends both setpoints immediately.

### Ramp Current

When output is turned on:

- The subsystem immediately sets the target voltage.
- It then ramps current from the present measured current to the stored target current.

When the operator changes current while output is already on:

- The subsystem ramps current to the new target.

When the operator changes voltage while output is already on:

- The subsystem immediately updates voltage, then ramps current back toward the stored current target.

### Ramp Voltage

When output is turned on:

- The subsystem immediately sets the target current.
- It then ramps voltage from the present measured voltage to the stored target voltage.

When the operator changes voltage while output is already on:

- The subsystem ramps voltage to the new target.

When the operator changes current while output is already on:

- The subsystem immediately updates current, then ramps voltage back toward the stored voltage target.

## Validation Rules

Before sending a new setpoint, the subsystem validates it against current driver and hardware assumptions.

### Voltage Validation

`validate_voltage()` checks that:

- The requested voltage is not negative.
- The requested voltage does not exceed the current OVP setting.
- The requested voltage is a multiple of 0.02 V.

### Current Validation

`validate_current()` checks that:

- The requested current is not negative.
- The requested current does not exceed the current OCP setting.

### Output Enable Validation

When the output toggle is switched on, `toggle_output()` also verifies:

- A stored target voltage exists.
- A stored target current exists.
- The stored target voltage is within OVP.
- The stored target current is within OCP.

If any of those checks fail, output is not enabled.

## Ramping Behavior

The subsystem delegates actual ramp execution to `PowerSupply9104.ramp_current()` and `PowerSupply9104.ramp_voltage()`.

The subsystem also manages GUI state during ramps:

- Disables adjustment buttons and text-entry set buttons.
- Disables the output-mode dropdown.
- Enables the `STOP RAMP` button.
- Re-enables controls when the ramp completes or is stopped.

Important helpers:

- `is_ramping()`
- `on_ramp_start()`
- `on_ramp_complete()`
- `stop_ramp()`

`STOP RAMP` signals the driver to stop the active ramp thread through `PowerSupply9104.stop_ramp()`.

## Sent vs Goal vs Measured Values

The UI tracks three different kinds of values:

- Sent values:
  - Last values sent to the power supply during direct sets or ramp steps.
  - Updated through callbacks from the power-supply driver.
- Goal values:
  - Operator-requested targets stored in the subsystem.
  - Shown as the intended current and voltage for the channel.
- Measured values:
  - Live readback from `get_voltage_current_mode()`.
  - Updated every poll cycle.

This separation is useful during ramps because the sent value can change step-by-step before the measured value settles.

## Data Refresh Loop

`update_data()` is the main polling loop. It runs every 500 ms and, for each cathode:

- Verifies or retries the power-supply connection.
- Reads heater voltage, current, and CV/CC mode from the supply.
- Updates live GUI displays.
- Reads clamp temperature from the temperature-controller interface.
- Updates overtemperature state and plot color.
- Appends plot data on the plot interval.
- Schedules the next update with `self.parent.after(500, self.update_data)`.

## Protection and Configuration Handling

Key configuration methods include:

- `set_overvoltage_limit()`
- `set_overcurrent_limit()`
- `set_overtemp_limit()`
- `set_slew_rate()`
- `query_and_check_settings()`

These methods are responsible for writing protection settings to the supply, reading them back, and logging mismatches or failures.

## Modeling and Predicted Output

The subsystem still initializes cathode models in `init_cathode_model()` for:

- Heater current to heater voltage.
- Heater current to emission current.
- Heater current to true temperature.

However, the current manual setpoint handlers do not actively update predictions when the operator changes current or voltage:

- `on_current_label_click()`
- `on_voltage_label_click()`
- `adjust_current()`
- `adjust_voltage()`

Those handlers currently skip prediction updates and focus on validation plus direct output control.

That means the "Predicted Output" panel should be treated as partial/incomplete documentation of future behavior, not as a fully active feature path for the current manual-control flow.

## Main Methods To Read First

If you are trying to understand the file quickly, start with these methods:

- `__init__()`
- `initialize_power_supplies()`
- `update_data()`
- `toggle_output()`
- `on_current_label_click()`
- `on_voltage_label_click()`
- `update_output_from_current()`
- `update_output_from_voltage()`
- `validate_current()`
- `validate_voltage()`
- `set_ramp_mode()`
- `stop_ramp()`

## Relationship To `power_supply_9104.py`

`cathode_heating.py` is the subsystem/orchestration layer.

It decides:

- What the operator is asking for.
- Whether the request is valid.
- Which control mode is active.
- Which driver call to issue next.

`power_supply_9104.py` is the instrument-driver layer.

It handles:

- Serial communication.
- Command formatting.
- Protection-setting commands.
- Direct set commands.
- Background ramp threads.
- Ramp stop signaling.

In short:

- `cathode_heating.py` decides what should happen.
- `power_supply_9104.py` performs the hardware I/O.


# 9104 Power Supply Initialization
```mermaid
flowchart TB
    Start([Start]) --> InitArrays[Initialize power_supplies and status arrays]
    InitArrays --> LoopStart{For each cathode PS}

    LoopStart --> HasPort{Port exists?}
    HasPort -- No --> SetNull[Set PS to null & status false]
    HasPort -- Yes --> TryInit[Try initialization]

    TryInit --> PSExists{PS exists?}
    PSExists -- No --> CreatePS[Create new PowerSupply9104]
    PSExists -- Yes --> CheckConnection{Is connected?}

    CheckConnection -- No --> UpdatePort[Update COM port]
    CheckConnection -- Yes --> SetPreset[Normal mode]
    CreatePS --> SetPreset
    UpdatePort --> SetPreset

    SetPreset --> ConfirmPreset{Preset == 3?}
    ConfirmPreset -- No --> LogPresetWarning[Log preset warning]
    ConfirmPreset -- Yes --> SetOVP[Set overvoltage protection]
    LogPresetWarning --> SetOVP

    SetOVP --> OVPSuccess{OVP set?}
    OVPSuccess -- No --> LogOVPFail[Log OVP failure]
    OVPSuccess -- Yes --> ConfirmOVP{OVP matches?}

    ConfirmOVP -- No --> LogOVPMismatch[Log OVP mismatch]
    ConfirmOVP -- Yes --> SetOCP[Set overcurrent protection]
    LogOVPMismatch --> SetOCP
    LogOVPFail --> SetOCP

    SetOCP --> OCPSuccess{OCP set?}
    OCPSuccess -- No --> LogOCPFail[Log OCP failure]
    OCPSuccess -- Yes --> ConfirmOCP{OCP matches?}

    ConfirmOCP -- No --> LogOCPMismatch[Log OCP mismatch]
    ConfirmOCP -- Yes --> SetSuccess[Set PS status true]
    LogOCPMismatch --> SetSuccess
    LogOCPFail --> SetSuccess

    SetSuccess --> NextPS{More PS?}
    SetNull --> NextPS

    NextPS -- Yes --> LoopStart
    NextPS -- No --> UpdateButtons[Update button states
    enabled/disabled]

    UpdateButtons --> CheckAnyInit{Any PS initialized?}
    CheckAnyInit -- Yes --> SetInitTrue[Set initialized flag true]
    CheckAnyInit -- No --> LogNoInit[Log no PS initialized]

    SetInitTrue --> UpdateSettings[Update query settings]
    LogNoInit --> UpdateSettings

    UpdateSettings --> End([to idle state])

    Error[Handle Exception] --> SetErrorState[Set PS null & status false]
    SetErrorState --> NextPS

    TryInit -- Exception --> Error
```

# Idle State Monitoring
Parallel operations for each Cathode (A, B, C)
```mermaid
flowchart TB
    Start["Start Update Cycle
    (500ms)"] --> ParallelCheck["Check Each Cathode
    (A, B, C)"]

    ParallelCheck --> PSCheck{"Power Supply
    Connected?"}
    ParallelCheck --> TempCheck{"Temperature
    Controller Connected?"}

    PSCheck -->|Yes| PSResume
    PSCheck -->|No| PSRetry["Retry Connection
    1. Log Warning
    2. Max 3 Attempts
    3. 500ms Delay"]
    PSRetry --> PSSuccess{"Reconnection
    Successful?"}

    PSSuccess -->|Yes| PSResume["Continue
    1. Update Status
    2. Enable Controls
    3. Log Success"]

    PSSuccess -->|No| PSFail["Set Disabled
    1. Disable Controls
    2. Clear Readings
    3. Log Error"]

    TempCheck -->|No| TempFail["Temp Read Failure
    1. Set Plot Alert (Red)
    2. Display '--' °C
    3. Log Error"]
    TempCheck -->|Yes| ReadTemp["Read Temperature"]

    ReadTemp --> ValidateTemp{"Temperature
    Valid?"}
    ValidateTemp -->|No| TempFail
    ValidateTemp -->|Yes| CheckOT{"Temperature >
    Overtemp Limit?"}

    CheckOT -->|Yes| OTActions[" Set Status 'OVERTEMP!'
    1. Update Plot (Red)
    2. Log Critical Error
    3. Update Label Style"]
    CheckOT -->|No| NormalTemp["Set Status 'Normal'
    1. Update Plot (Blue)
    2. Update Display"]

    PSResume --> UpdateDisplay["Update GUI Display
    1. Voltage & Current
    2. Operation Mode
    3. Temperature Plot"]
    PSFail --> UpdateDisplay
    OTActions --> UpdateDisplay
    NormalTemp --> UpdateDisplay
    TempFail --> UpdateDisplay

    UpdateDisplay --> NextCycle["Schedule Next
    Update (500ms)"]

    NextCycle --> Start

    subgraph GUI_Updates["GUI Status Updates"]
        direction TB
        UpdateLabels["Update Display Labels:
        - Heater Current & Voltage
        - Target Current
        - Temperature
        - Operation Mode"]

        UpdatePlot["Update Temperature Plot:
        - Add New Data Point
        - Adjust Color (Red/Blue)
        - Update Axes
        - Redraw"]

        UpdateControls["Update Control States:
        - Toggle Buttons
        - Query Settings
        - Configuration Options"]
    end
```

# Setting current output via dashboard

```mermaid
flowchart TB
    Input["User enters new current using textbox or nudge buttons"] --> ActiveRamp{"Active ramp process?"}

    ActiveRamp -->|No| ValidateCurrent{"Validate Input Current
                                        Current < OCP
                                        Current > 0"}
    ActiveRamp -->|Yes| RampWarn["Display ramp warning"]

    RampWarn --> End

    ValidateCurrent -->|Fail| DispWarn["Display invalid input warning"]
    ValidateCurrent -->|Pass| UpdatePredictions["Update predictions from new current"]

    DispWarn --> End

    UpdatePredictions --> StoreCurrent["Store new set current value"]

    StoreCurrent --> UpdateOutput{"Is output enabled?"}

    UpdateOutput -->|No| End
    UpdateOutput -->|Yes| OutputMode{"Immediate Set or Ramp?"}

    OutputMode -->|Immediate| SetOutput["Immediate set new current"]
    OutputMode -->|Ramp| RampMode{"Ramp current or voltage?"}

    SetOutput --> End

    RampMode -->|Current| RampCurrent["Ramp current to new value"]
    RampMode -->|Voltage| RampVoltage["Ramp voltage given new current restraint"]

    RampCurrent --> End
    RampVoltage --> End
```

# Setting voltage output via dashboard

```mermaid
flowchart TB
    Input["User enters new voltage using textbox or nudge buttons"] --> ActiveRamp{"Active ramp process?"}

    ActiveRamp -->|No| ValidateVoltage{"Validate Input Voltage
                                        Voltage < OVP
                                        Voltage > 0
                                        Voltage is a multiple of .02"}
    ActiveRamp -->|Yes| RampWarn["Display ramp warning"]

    RampWarn --> End

    ValidateVoltage -->|Fail| DispWarn["Display invalid input warning"]
    ValidateVoltage -->|Pass| UpdatePredictions["Update predictions from new voltage"]

    DispWarn --> End

    UpdatePredictions --> StoreVoltage["Store new set voltage value"]

    StoreVoltage --> UpdateOutput{"Is output enabled?"}

    UpdateOutput -->|No| End
    UpdateOutput -->|Yes| OutputMode{"Immediate Set or Ramp?"}

    OutputMode -->|Immediate| SetOutput["Immediate set new voltage"]
    OutputMode -->|Ramp| RampMode{"Ramp current or voltage?"}

    SetOutput --> End

    RampMode -->|Current| RampCurrent["Ramp current given new voltage constraint"]
    RampMode -->|Voltage| RampVoltage["Ramp voltage to new value"]

    RampCurrent --> End
    RampVoltage --> End
```