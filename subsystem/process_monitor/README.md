# Process Monitor Subsystem

## Overview

The Process Monitor Subsystem is a real-time temperature monitoring system that interfaces with Omega iSeries DP16PT Process Monitors via Modbus RTU. It provides visual representation of temperature data captured from multiple experimental locations including:
- **Solenoid 1**
- **Solenoid 2**
- **Chamber Bottom**
- **Chamber Top**
- **Air temp** 

## Process Monitor Subsystem Class
### Overview:
Mainly used to inatlized and start Temperatrue Bar objects and to establish communictions via the DP16 driver.
### Important Method(s)
#### update_temperatures():
This method communicates directly to the driver to collect the data needed to update the visual representation of the themature data.
The expected return value is a dictionary, with the unit number being the key (1-6) and the tempature values being the value. Whatever is retuned from the driver(expected or unexpected), this method iteratviely udpates each of the corresponding thermonitors.

## Temperature Bar Class
### Overview
When called created a thermointor with the given specs. This method was created due to the fact that our different locations are expected to have different ranges of expected temperatures. This class does not handle any of the data parsing, it only displays/updates, in numeric, color, and bar data.

### Solenoid Temperature Ranges (0-120°C)
- Normal: < 70°C (Green)
- Warning: 70-100°C (Yellow)
- Critical: > 100°C (Red)

### Chamber Temperature Ranges (0-100°C)
- Normal: < 50°C (Green)
- Warning: 50-70°C (Yellow)
- Critical: > 70°C (Red)

### Air Temperature Ranges (0-50°C)
- Normal: < 30°C (Green)
- Warning: 30-40°C (Yellow)
- Critical: > 40°C (Red)


&nbsp;



## Flow Charts for process_monitor.py

### Subsystem Initialization
```mermaid
flowchart TD
    Start([Initialize ProcessMonitorSubsystem]) --> InitVars[Initialize variables:<br/>- error tracking<br/>- update interval<br/>- error counts<br/>- last good readings]
    InitVars --> SetThermo[Setup thermometer arrays:<br/>- thermometers list<br/>- thermometer_map dictionary]
    
    SetThermo --> ComCheck{COM Port<br/>Provided?}
    ComCheck -->|No| NoComPort[Set monitor = None<br/>Log warning]
    ComCheck -->|Yes| TryInit[Try DP16ProcessMonitor initialization]
    
    TryInit --> ConnectAttempt{Try up to 3<br/>connection attempts}
    ConnectAttempt -->|Success| ConfigureUnits[Configure each unit]
    ConnectAttempt -->|All Failed| InitFailed[Log error<br/>Set monitor = None]
    
    ConfigureUnits --> UnitLoop[For each unit]
    UnitLoop --> ConfigCheck{Configuration<br/>successful?}
    ConfigCheck -->|Yes| AddUnit[Add to configured units]
    ConfigCheck -->|No| LogUnitFail[Log unit failure]
    
    AddUnit --> MoreUnits{More units?}
    LogUnitFail --> MoreUnits
    MoreUnits -->|Yes| UnitLoop
    MoreUnits -->|No| UnitsCheck{Any units<br/>configured?}
    
    UnitsCheck -->|Yes| StartThread[Start polling thread]
    UnitsCheck -->|No| RaiseError[Raise RuntimeError]
    
    NoComPort --> SetupGUI[Setup GUI]
    InitFailed --> SetupGUI
    StartThread --> SetupGUI
    RaiseError --> SetupGUI
    
    SetupGUI --> CreateFrame[Create and configure frame]
    CreateFrame --> CreateBars[Create temperature bars]
    CreateBars --> StartUpdate[Start update_temperatures loop]
```

### `update_temperatures` Loop
```mermaid
flowchart TD
    Start([Update Temperatures]) --> GetTime[Get current time]
    GetTime --> MonitorCheck{Monitor exists?}
    
    MonitorCheck -->|No| DebugLog[Log debug message]
    DebugLog --> TimeCheck1{Time since last<br/>error > interval?}
    TimeCheck1 -->|Yes| DisconnectAll[Set all temps to DISCONNECTED<br/>Log warning<br/>Update last_error_time]
    DisconnectAll --> AdjustInterval1[Increase error count<br/>Adjust interval exponentially]
    
    MonitorCheck -->|Yes| TryGetTemps[Try get_all_temperatures]
    TryGetTemps --> ValidCheck{Temperatures<br/>received?}
    
    ValidCheck -->|No| TimeCheck2{Time since last<br/>error > interval?}
    TimeCheck2 -->|Yes| LogError[Log error<br/>Set all temps to DISCONNECTED<br/>Update last_error_time]
    LogError --> AdjustInterval2[Increase error count<br/>Adjust interval exponentially]
    
    ValidCheck -->|Yes| ProcessTemps[Process each temperature]
    ProcessTemps --> TempLoop[For each thermometer]
    
    TempLoop --> ValueCheck{Check temp<br/>value type}
    ValueCheck -->|None| SetDisconnected[Update bar with DISCONNECTED]
    ValueCheck -->|SENSOR_ERROR| SetError[Update bar with SENSOR_ERROR]
    ValueCheck -->|DISCONNECTED| SetDisconnected
    ValueCheck -->|Valid Number| RangeCheck{-90°C ≤ temp ≤ 500°C?}
    
    RangeCheck -->|Yes| UpdateValue[Update bar with temperature<br/>Store as last good reading<br/>Reset error count]
    RangeCheck -->|No| ErrorCount{Error count ≥<br/>threshold?}
    
    ErrorCount -->|Yes| SetError
    ErrorCount -->|No| UseLastGood[Use last good reading<br/>Increment error count]
    
    SetDisconnected --> NextThermo{More<br/>thermometers?}
    SetError --> NextThermo
    UpdateValue --> NextThermo
    UseLastGood --> NextThermo
    
    NextThermo -->|Yes| TempLoop
    NextThermo -->|No| ResetInterval[Reset interval<br/>Reset error count]
    
    TimeCheck1 -->|No| Schedule[Schedule next update]
    TimeCheck2 -->|No| Schedule
    AdjustInterval1 --> Schedule
    AdjustInterval2 --> Schedule
    ResetInterval --> Schedule
```

Temperature Color Logic
```mermaid
flowchart TD
    Start([Get Temperature Color]) --> ErrorCheck{Temperature = -1?}
    ErrorCheck -->|Yes| ReturnOrange[Return Orange]
    ErrorCheck -->|No| ColdCheck{Temp < 15°C?}
    
    ColdCheck -->|Yes| ReturnBlue[Return Blue]
    ColdCheck -->|No| SensorCheck{Check sensor type}
    
    SensorCheck --> Solenoid{Starts with<br/>'Solenoid'?}
    SensorCheck --> Chamber{Starts with<br/>'Chamber'?}
    SensorCheck --> Air{Starts with<br/>'Air'?}
    SensorCheck --> Default{Default case}
    
    Solenoid --> SolCheck1{Temp < 70°C?}
    SolCheck1 -->|Yes| SolGreen[Return Green]
    SolCheck1 -->|No| SolCheck2{Temp < 100°C?}
    SolCheck2 -->|Yes| SolYellow[Return Yellow]
    SolCheck2 -->|No| SolRed[Return Red]
    
    Chamber --> ChamCheck1{Temp < 50°C?}
    ChamCheck1 -->|Yes| ChamGreen[Return Green]
    ChamCheck1 -->|No| ChamCheck2{Temp < 70°C?}
    ChamCheck2 -->|Yes| ChamYellow[Return Yellow]
    ChamCheck2 -->|No| ChamRed[Return Red]
    
    Air --> AirCheck1{Temp < 30°C?}
    AirCheck1 -->|Yes| AirGreen[Return Green]
    AirCheck1 -->|No| AirCheck2{Temp < 40°C?}
    AirCheck2 -->|Yes| AirYellow[Return Yellow]
    AirCheck2 -->|No| AirRed[Return Red]
    
    Default --> DefCheck1{Temp < 70°C?}
    DefCheck1 -->|Yes| DefGreen[Return Green]
    DefCheck1 -->|No| DefCheck2{Temp < 100°C?}
    DefCheck2 -->|Yes| DefYellow[Return Yellow]
    DefCheck2 -->|No| DefRed[Return Red]
```
