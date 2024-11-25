# E5CN Temperature Controller Driver Documentation

### Hardware Specifications
- Manufacturer: Omron
- Model: E5CN-HV2M-500
- Datasheet [(link)](https://mm.digikey.com/Volume0/opasdata/d220001/medias/docus/518/E5CN-H.pdf)
- Communication interface: Modbus RTU over RS485
- Resolution: 0.01 °C
- Sampling cycle: 60 ms

### Serial Port Configuration Settings
| Setting | Value |
|---------|-------|
| Baud rate | 9600 |
| Data bits | 8 |
| Parity | Even |
| Stop bits | 2 |
| Slave Address | 1-3 (supports multiple units) |

### Basic Usage

```python
>>> from instrumentctl import E5CNModbus

# Initialize controller with default settings
>>> controller = E5CNModbus(port="COM4")

# Connect to the device
>>> controller.connect()
True

# Read temperature from a single unit
>>> temp = controller.read_temperature(unit=1)
>>> print(f"Temperature: {temp}°C")
Temperature: 23.5°C

# Clean up
>>> controller.disconnect()
```

### Flowcharts
```mermaid
flowchart TD
    %% Connection Management
    subgraph Connection_Management[E5CN Modbus Management]
        Connect[Connect] --> CheckConnection{Is Socket Open?}
        CheckConnection -- Yes --> AlreadyConnected[Return True]
        CheckConnection -- No --> AttemptConnect{Attempt Connection}
        AttemptConnect -- Success --> UpdateConnected[Set Connected State]
        AttemptConnect -- Failure --> HandleError[Log Error]
        HandleError --> ReturnFalse[Return False]
    end
```

```mermaid
flowchart TD
    %% Single Temperature Read
    subgraph Single_Read[Single Temperature Read]
        ReadTemperature[read_temperature] --> CheckUnit{Valid Unit?}
        CheckUnit -- No --> ReturnNone1[Return None]
        CheckUnit -- Yes --> InitAttempts[Initialize Attempts]
        InitAttempts --> CheckSocket{Socket Open?}
        CheckSocket -- No --> ReconnectAttempt[Attempt Reconnect]
        CheckSocket -- Yes --> ReadRegisters[Read Registers]
        
        ReconnectAttempt -- Success --> ReadRegisters
        ReconnectAttempt -- Failure --> DecrementAttempts1[Decrement Attempts]
        
        ReadRegisters -- Success --> ProcessTemp[Process Temperature]
        ReadRegisters -- Error --> DecrementAttempts2[Decrement Attempts]
        
        DecrementAttempts1 --> CheckAttempts1{Attempts<br>left > 0?}
        DecrementAttempts2 --> CheckAttempts2{Attempts<br>left > 0?}
        
        CheckAttempts1 -- Yes --> CheckSocket
        CheckAttempts1 -- No --> ReturnNone2[Return None]
        
        CheckAttempts2 -- Yes --> CheckSocket
        CheckAttempts2 -- No --> ReturnNone3[Return None]
        
        ProcessTemp --> ValidateRange{Temperature in Range?}
        ValidateRange -- Yes --> ReturnTemp[Return Temperature]
        ValidateRange -- No --> LogWarning[Log Warning]
        LogWarning --> ReturnTemp
    end
```

```mermaid
flowchart TD
    %% Temperature Reading Process
    subgraph Temperature_Reading[Temperature Reading Process]
        StartReading[start_reading_temperatures] --> ForEachUnit[For Each Unit in UNIT_NUMBERS]
        ForEachUnit --> CreateThread[Create Reading Thread]
        CreateThread --> StartThread[Start Thread]
        StartThread --> AddToThreadList[Add to Thread List]
        
        %% Continuous Reading Loop
        ReadContinuously[_read_temperature_continuously] --> CheckStop{Check stop_event}
        CheckStop -- Not Set --> ReadTemp[Read Temperature]
        CheckStop -- Set --> ExitThread[Exit Thread]
        
        ReadTemp --> ValidateReading{Valid Reading?}
        ValidateReading -- Yes --> AcquireLock[Acquire Lock]
        AcquireLock --> UpdateTemp[Update Temperature]
        UpdateTemp --> ReleaseLock[Release Lock]
        ValidateReading -- No --> LogError[Log Error]
        
        ReleaseLock --> Sleep[Sleep 500ms]
        LogError --> Sleep
        Sleep --> CheckStop
    end
```