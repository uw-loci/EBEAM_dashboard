# 9104 Power Supply Driver Documentation

### Hardware Specifications
- Manufacturer: BK Precision
- Model: 9104 Series 320W Multi Range DC Power Supply
- Firmware version: 1.30
- User manual: [(link)](https://bkpmedia.s3.us-west-1.amazonaws.com/downloads/manuals/en-us/9103_9104_manual.pdf)
- Datasheet [(link)](https://www.mouser.com/datasheet/2/43/9103_9104_series_datasheet-1131399.pdf)
- Communication interface: UART over RS485
- Programming manual: [(link)](https://bkpmedia.s3.us-west-1.amazonaws.com/downloads/programming_manuals/en-us/9103_9104_programming_manual.pdf)

### Serial Port Configuration Settings
| Setting | Value |
|---------|-------|
| Baud rate | 9600 |
| Data bits | 8 |
| Parity | None |
| Stop bits | 1 |
| Flow control | None |

### Basic Usage

```python
# Initialize the power supply
>>> ps = PowerSupply9104(port="COM3", baudrate=9600)

# Check connection
>>> ps.is_connected()
True

# Set to preset mode 3 (normal operation)
>>> ps.set_preset_selection(3)
True

# Configure protection limits
>>> ps.set_over_voltage_protection(2.0)  # 2V OVP limit
True
>>> ps.set_over_current_protection(8.5)   # 8.5A OCP limit
True

# Set voltage and current for preset 3
>>> ps.set_voltage(3, 1.0)  # Set to 1V
True
>>> ps.set_current(3, 1.0)  # Set to 1A
True

# Verify settings
>>> ps.get_settings(3)
(1.0, 1.0)  # Returns (voltage, current)

# Turn output on
>>> ps.set_output(1)
True

# Read current measurements
>>> ps.get_voltage_current_mode()
(1.02, 0.98, 'CV Mode')  # Returns (voltage, current, mode)

# Turn output off
>>> ps.set_output(0)
True

>>> ps.close()
```

# Backend Ramping Procedure for Current
```mermaid
flowchart TB
    Start["Ramp current requested (target, step, delay)"] --> ActiveRamp{"Active ramp process?"}

    ActiveRamp -->|Yes| RampWarn["Display/Log ramp in progress warning"]
    RampWarn --> End

    ActiveRamp -->|No| Prep["Clear stop event<br/>Record start time<br/>Read initial V/I/Mode"]
    Prep --> Plan["Compute ramp plan<br/>steps = ceil(|target - I0| / step)"]

    Plan --> Loop{"For each step until target reached"}

    Loop -->|Stop set| StopEarly["Stop event set — abort ramp"]
    StopEarly --> CallbackFail["Callback(False)"] --> End

    Loop -->|Continue| Conn{"Supply connected?"}
    Conn -->|No| ConnWarn["Connection lost — abort ramp"]
    ConnWarn --> CallbackFail2["Callback(False)"] --> End

    Conn -->|Yes| NextVal["Compute next current setpoint<br/>clamp to target"]

    NextVal --> TrySet{"Set current succeeded?"}
    TrySet -->|No| Retry{"Retry ≤ MAX_RETRIES ?"}
    Retry -->|Yes| NextVal
    Retry -->|No| GiveUp["Failed after retries — abort"] --> CallbackFail3["Callback(False)"] --> End

    TrySet -->|Yes| LimitChk{"Being limited?<br/>(Mode==CV AND |Imeas - Iset| > tol)?"}

    LimitChk -->|Yes| StoreGood{"Store last good value (first hit)"} --> HitCount{"Consecutive hits ≥ HIT_LIMIT?"}
    LimitChk -->|No| Progress["Update progress log"]

    HitCount -->|No| Delay["sleep(step_delay)"] --> Loop
    HitCount -->|Yes| Restore{"Restore last good if stored"} --> Abort["Abort ramp due to limit"] --> CallbackFail4["Callback(False)"] --> End

    Progress --> Delay2["sleep(step_delay)"] --> Loop

    Loop -->|Done| Settle["sleep(verify_delay)"] --> Verify{"Final reading OK?"}
    Verify -->|No| CallbackFail5["Callback(False)"] --> End
    Verify -->|Yes| CallbackOK["Callback(True)"] --> End
```

# Backend Ramping Procedure for Voltage
```mermaid
flowchart TB
    Start["Ramp voltage requested (target, step, delay)"] --> ActiveRamp{"Active ramp process?"}

    ActiveRamp -->|Yes| RampWarn["Display/Log ramp in progress warning"]
    RampWarn --> End

    ActiveRamp -->|No| Prep["Clear stop event<br/>Record start time<br/>Read initial V/I/Mode"]
    Prep --> Plan["Compute ramp plan<br/>steps = ceil(|target - V0| / step)"]

    Plan --> Loop{"For each step until target reached"}

    Loop -->|Stop set| StopEarly["Stop event set — abort ramp"]
    StopEarly --> CallbackFail["Callback(False)"] --> End

    Loop -->|Continue| Conn{"Supply connected?"}
    Conn -->|No| ConnWarn["Connection lost — abort ramp"]
    ConnWarn --> CallbackFail2["Callback(False)"] --> End

    Conn -->|Yes| NextVal["Compute next voltage setpoint<br/>clamp to target"]

    NextVal --> TrySet{"Set voltage succeeded?"}
    TrySet -->|No| Retry{"Retry ≤ MAX_RETRIES ?"}
    Retry -->|Yes| NextVal
    Retry -->|No| GiveUp["Failed after retries — abort"] --> CallbackFail3["Callback(False)"] --> End

    TrySet -->|Yes| LimitChk{"Being limited?<br/>(Mode==CC AND |Vmeas - Vset| > tol)?"}

    LimitChk -->|Yes| StoreGood{"Store last good value (first hit)"} --> HitCount{"Consecutive hits ≥ HIT_LIMIT?"}
    LimitChk -->|No| Progress["Update progress log"]

    HitCount -->|No| Delay["sleep(step_delay)"] --> Loop
    HitCount -->|Yes| Restore{"Restore last good if stored"} --> Abort["Abort ramp due to limit"] --> CallbackFail4["Callback(False)"] --> End

    Progress --> Delay2["sleep(step_delay)"] --> Loop

    Loop -->|Done| Settle["sleep(verify_delay)"] --> Verify{"Final reading OK?"}
    Verify -->|No| CallbackFail5["Callback(False)"] --> End
    Verify -->|Yes| CallbackOK["Callback(True)"] --> End

```