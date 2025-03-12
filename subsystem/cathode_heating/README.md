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

# Defining a target electron beam emission current
 
```mermaid
flowchart TB
    Input["User Enters<b> Target Current"] --> Calculate["Calculate Settings
                                                        - Emission Current 
                                                        - Heater Current
                                                        - Heater Voltage"]
    
    Calculate --> ValidateRange{"Within Model<b> Ranges?"}
    
    ValidateRange -->|No| ResetVars["Reset Variables <b>Show Error"]
    ValidateRange -->|Yes| CheckOVP{"Voltage < OVP<b> Limit?"}
    
    CheckOVP -->|No| OVPWarn["Show OVP Warning"]
    CheckOVP -->|Yes| CheckOCP{"Current < OCP Limit?"}

    CheckOCP -->|No| OCPWarn["Show OCP Warning"]
    CheckOCP -->|Yes| SetPS["Set Power Supply Voltage"]
    
    SetPS --> Confirm{"Confirm Settings"}
    
    Confirm -->|Mismatch| LogError["Log Mismatch<b> Show Warning"]
    Confirm -->|Match| UpdateDisplay["Update Display<b> - Predictions<b> - Status"]
    

    UpdateDisplay --> OutputToggled{"Did user toggle output?"}

    OutputToggled --> |No| End
    OutputToggled --> |Yes| OutputOn["Output Switched On"]
    
    
    ResetVars --> End
    OVPWarn --> End
    OCPWarn --> End
    LogError --> End
```

# Setting output via Dashboard for Benchmarking
 
```mermaid
flowchart TB
    Input["User Enters<b> Voltage"] --> LUT["Use Voltage LUT to set Heater Voltage"]
    

    LUT --> CheckOVP{"Voltage < OVP<b> Limit?"}
    
    CheckOVP -->|No| OVPWarn["Show OVP Warning"]
    CheckOVP -->|Yes| CheckOCP{"Current < OCP Limit?"}

    CheckOCP -->|No| OCPWarn["Show OCP Warning"]
    CheckOCP -->|Yes| SetPS["Set Power Supply Voltage"]
    
    SetPS --> Confirm{"Confirm<b> Settings"}
    
    Confirm -->|Match| UpdateDisplay["Update Display 
                                     - Predictions 
                                     - Status"]
    Confirm -->|Mismatch| LogError["Log Mismatch<b> Show Warning"]

    UpdateDisplay --> OutputToggle{"Did user toggle output?"}

    OutputToggle --> |Yes| RampToggle{"Did user toggle a ramp?"}

    RampToggle --> |Yes| Ramp --> OutputOn["Output turned on"]
    RampToggle --> |No| OutputOn
    OutputToggle --> |No| End

    OVPWarn --> End
    OCPWarn --> End
    LogError --> End
```