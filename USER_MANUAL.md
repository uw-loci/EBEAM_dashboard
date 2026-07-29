# EBEAM Dashboard User Manual

This manual describes the dashboard as implemented in the current codebase for the melt metal experiment.

## 1. Interaction labels used in this manual

Every interactive control falls into one of these categories:

| Label | Meaning |
|---|---|
| **Software only** | Changes dashboard state, display, logging, or a local file. It does not intentionally send an equipment command. |
| **Serial** | Attempts communication with equipment. The request can fail, time out, or be rejected by firmware. |
| **Mixed** | Changes software state and can also cause a serial command under the conditions described. |
| **File/process** | Reads or writes a local file or launches another local program; no equipment command is intended. |
| **Read-only** | The item is an indicator populated from polling or other dashboard state. |

For safety-critical operations, distinguish these stages:

1. **Requested** means the dashboard accepted the button press.
2. **Command acknowledged** means the firmware returned success.
3. **Status confirmed** means a later poll reported the expected live state.

## 2. Starting and closing the dashboard

### 2.1 COM-port startup dialog

At startup, the dashboard requests a port for:

- VTRX
- 902B vacuum gauge
- Cathode A, B, and C 9104 power supplies
- E5CN Temperature controllers
- Interlocks
- Process monitors
- Knob Box
- Beam Pulse/BCON
- Laser Monitor

Previously saved choices are preselected from **usr/usr_data/com_ports.json**. Choose a real port or **dummy** for every row, then select **Submit**. Submit saves the final choices for the next launch. If any row is blank, the dialog asks whether to fill all blank rows with dummy values; declining returns to the dialog. Closing the dialog without submitting cancels dashboard startup.

Selecting dummy permits the associated subsystem or panel to be created without the instrument. Its connection indicator, when one is provided, remains unavailable or disconnected, and hardware actions for that instrument will not succeed.

The in-dashboard **Configure COM Ports** command is not fully functioning; see [Section 11.1](#111-general-menu).

> After a USB device is unplugged unexpectedly, some devices may not recover cleanly from within the running dashboard due to an I/O expander driver issue. To re-establish communication, make sure each device is plugged in, restart the experiment computer, and reopen the dashboard.

### 2.2 Dashboard layout

The visible dashboard contains:

- Interlocks
- Vacuum System
- Process Monitor
- Messages
- Beam Energy
- Cathode Heating
- Beam Pulse
- Main Control
- Machine Status

Drag the panel dividers to resize these areas. **General → Save Layout** stores divider positions in **usr/usr_data/pane_state.json**.

### 2.3 Keyboard shortcuts

| Shortcut | Action | Interaction |
|---|---|---|
| **F1** | Open the Keyboard Shortcuts window | Software only |
| **F11** | Enter or leave full screen | Software only |
| **Escape** | Leave full screen | Software only |
| **Ctrl+M** | Maximize the window | Software only |
| **Ctrl+S** | Export the currently visible Messages text | File only |
| **Ctrl+Q** or **Ctrl+W** | Request dashboard shutdown; confirmation is required | Mixed shutdown workflow |

The Keyboard Shortcuts window’s **Close** button, or Escape while that window has focus, closes only that window and is **Software only**.

After confirmation, normal shutdown stops background workers and closes available serial connections. During cleanup, the dashboard attempts BCON ALL_OFF and attempts to disable available cathode-heater outputs before closing their ports. These are best-effort cleanup commands, not status-confirmed safety workflows. Use the applicable OFF, **Disable All Beams**, disarm, or **E-STOP: BEAMS & CCS** action and verify the result before closing when outputs may be active.

## 3. Interlocks

The Interlocks panel is read-only. It polls the G9 controller about every 500 ms during normal communication. Communication errors cause slower retries, up to about 5 seconds, until communication recovers.

Indicators:

- Door
- Water
- Vacuum Power
- Vacuum Pressure
- Low Oil
- High Oil
- E-STOP Internal (SIC Chassis E-Stop)
- E-STOP External (Enclosure E-Stop)
- All Interlocks
- G9SP Output
- HVolt ON

Green means pass/on and red means fail/off/unavailable as appropriate. **All Interlocks** combines the safety-input group; it does not include HVolt ON or the G9SP output state. HVolt ON is derived from the G9SP firmware fields associated with the HVolt Subpanel Arduino Monitor, while G9SP Output reports the controller output bit connected to SIC's 24 V signal to turn on the HVolt Subpanel.

## 4. Vacuum System / VTRX and 902B

The Vacuum System panel is a read-only subpanel with software-only plot controls. It can display two independent pressure sources:

- **972B/VTRX** is the authoritative pressure source for Main Control pressure guards and Machine Status.
- **902B** is a secondary display, graph, and Data Log source. It is not used to permit or stop beams or CCS, and it does not drive Machine Status.

### 4.1 VTRX status indicators

The eight switch indicators are:

1. Pumps Power ON
2. Turbo Rotor ON
3. Turbo Vent OPEN
4. 972B Relay 1 ON
5. Turbo Gate CLOSED
6. Turbo Gate OPEN
7. Argon Gate OPEN
8. Argon Gate CLOSED

Green means the corresponding firmware bit is 1; gray means 0. A communication, parsing, or firmware-error condition makes all indicators red rather than inferring a safe state.

The two pressure values are displayed in mbar, and the logarithmic plot uses a green line for 972B and an indigo line for 902B. VTRX serial/UI processing is about every 500 ms, while the 902B is normally polled about once per second. A valid 972B packet remains “fresh” for approximately 3 seconds; a valid 902B value remains fresh for approximately 6 seconds. Stale values display as unavailable. Main Control treats stale, unavailable, or firmware-error 972B pressure as unsafe when the corresponding guards are enabled.

### 4.2 Pressure display, suppression, and guards

- The Main Control beam and CCS pressure guards consider 972B/VTRX pressure above 1e-5 mbar unsafe.
- Pressure at exactly 1e-5 mbar is safe for those guards.
- Machine Status separately requires fresh 972B pressure strictly below 1e-4 and 1e-6 mbar for its two vacuum milestones.
- The 902B reading never substitutes for a missing or faulty 972B reading in a guard or Machine Status calculation.

When a fresh, valid 972B reading is strictly below 1.0 mbar, the secondary 902B display is intentionally suppressed: its value box is hidden, new 902B plot samples are discarded, its Data Log/Supabase field is cleared, and routine 902B operational log messages are suppressed. Existing 902B plot history remains until it ages out of the selected time window. When 902B display resumes, a gap separates the new line from the older samples. A 972B value exactly equal to 1.0 mbar does not suppress 902B. A stale, disconnected, or erroneous 972B also does not hide an independently fresh 902B reading.

### 4.3 Plot controls

The plot keeps a rolling history of up to seven days. The time-window selector provides 5, 15, or 30 minutes; 1, 5, or 10 hours; 1 through 6 days; and Max. Changing the window is **Software only** and is not persisted during dashboard restart.

**Save Plot** is **File only**. It writes a timestamped PNG under **EBEAM-Dashboard-Logs** relative to the dashboard’s current working directory. This may be a different directory from the user-profile log location used by the Messages logger if the repo is not located in the user's root directory.

## 5. Process Monitor

The six displayed channels are:

- Solenoid 1
- Solenoid 2
- Chamber Top
- Chamber Bot
- Air temp
- Unassigned

The driver reads channels sequentially in the background and the GUI refreshes about every 500 ms.

### 5.1 Indicator meaning

| Appearance | Meaning |
|---|---|
| Green bar/value | Numeric value is within the configured warning minimum and maximum, inclusive |
| Orange bar/value | Numeric value is below the warning minimum or above the warning maximum |
| Gray hatched and **---** | Disconnected/unavailable |
| Orange **ERR** | Sensor/driver error |
| Gray hatched **OFF** | Channel is disabled |

The colored bar is clipped to its configured display range, while the text shows the numeric reading, or **OFF** state.

The hidden **Environment Pass** result is true only when every enabled sensor has a numeric value within its warning range, including equality. Disabled sensors are ignored for this aggregate. Machine Status reports this result as the **PMON Temperatures OK** status milestone.

Disabling a channel suppresses its normal display, Environment Pass participation, and per-channel error/range log messages, but the underlying driver still polls the device. Its latest reading may therefore still appear in the aggregate Data Log temperature payload.

### 5.2 Process Monitor Config

| Setting | Effect | Interaction/persistence |
|---|---|---|
| **Enabled** | Includes/excludes the channel from display warning and Environment Pass; suppresses its normal error/range logging when disabled | Software/driver filtering; persisted in **usr/usr_data/process_monitor_config.json** |
| **Warn min °C / Warn max °C + Set** | Defines green inclusive bounds and Environment Pass | Software/file only; persisted in the Process Monitor config file |
| **Bar min °C / Bar max °C + Set** | Defines the graphical bar scale only | Software/file only; persisted in the Process Monitor config file |

All four limits must be finite and Display Min must be less than Display Max; Warning Min must be less than Warning Max.

An out-of-range value logs on entry into the condition and then no more than about once per 60 seconds while it persists.

There is no supported live PMON COM-port reassignment/recovery path. If the monitor was not created at startup, assigning a value in the in-dashboard COM dialog does not create its polling schedule; restart the dashboard, and computer workstation if necessary, with the correct startup assignment.

## 6. Beam Energy

Beam Energy is a monitoring panel for the Knob Box remote interfacing with the High Voltage Power Supplies in the Enclosure.

### 6.1 Per-supply indicators

| Indicator | Meaning |
|---|---|
| **Comms** | Green for current valid communication; red/unavailable otherwise |
| **Output ENABLED/DISABLED** | Knob Box-reported supply enable state |
| **Set Voltage** | Knob Box-reported HVPS requested voltage |
| **Actual Voltage/Current** | Knob Box ADC sampled HVPS readback values |
| **Overcurrent** on ±1 kV | White normal; yellow when the reset/overcurrent flag is set |
| **Forced Off** on +3 kV | White normal; red when a forced-off reset count is present |
| **Voltage/Current Interlock** | Green clear, red asserted, white unavailable |

Normal measured text is black. A configured warning changes the affected value to orange. The separate +20 kV automatic beam-disarm threshold configured in the Main Control config menu changes the measured current to red and takes priority over the orange warning.

### 6.2 System indicators and interlock log

- **Arm Beams**, **CCS Power**, and **Arm 80kV** are Knob Box-reported text indicators. These report Knob Box output states, which may differ from physical Knob Box switch states if an interlock has been tripped.
- **Logic Comms** is green when Knob Box logic communication is valid.
- **Interlocks** is green for nominal Knob Box interlock status and red for a reported fault.
- **Interlock Log** latches comparator trip messages. It clears when the firmware reports that the Knob Box is in nominal-operation mode.

Knob Box data is polled about every 200 ms; the visible panel normally refreshes about every 500 ms.

### 6.3 Beam Energy Config

Each supply has **Max Voltage**, **Min Voltage**, and **Max Current** warning limits with a **Set** action.

These are **Software/file only**. They recolor dashboard values, affect Machine Status, and are saved to **usr/usr_data/beam_energy_warning_limits.json**. They do not program or limit the high-voltage supplies in any way.

| Supply | Allowed abs maximum for Max Voltage warning | Allowed maximum for Max Current warning | Default Min Voltage warning |
|---|---:|---:|---:|
| +1 kV | 1000 V | 30 mA | 0 V |
| -1 kV | -1000 V | 30 mA | 0 V |
| +20 kV | 20000 V | 1 mA | 0 V |
| +3 kV | 3000 V | 10 mA | 0 V |

Inputs must be finite and nonnegative, may not exceed the listed rating/default maximum, and Min Voltage may not exceed Max Voltage. Voltage warns when it is below Min Voltage or greater than or equal to Max Voltage. Current warns when it is greater than or equal to Max Current.

Negative 1 kV Matsusada voltage and current warning comparisons use magnitude. Enter positive magnitudes in Config; for example, enter `900` for a -900 V Max Voltage warning limit.

The +20 kV **Max Current** warning limit is separate from Main Control’s [**Disable Beams if 20kV Bertan reaches or exceeds** setting](#113-beamcathode-settings). The latter uses its own threshold and requests a dashboard beam disarm: BCON ALL_OFF is requested and software arm/interlocks are cleared only after an all-off status poll confirms the result. It does not turn CCS off and does not trigger the full dashboard E-stop.

Warnings are evaluated on each update and are not edge-latched. A persistent warning can produce repeated log messages, and a persistent +20 kV automatic-disarm reading can request disarm again after the prior operation finishes. Enabling that guard or editing its threshold can act immediately on an already-held valid reading.

## 7. Cathode Heating / CCS

Cathode A, B, and C each have a Main tab and a Config tab. Each cathode subsection combines the corresponding 9104 heater supply and E5CN temperature controller.

### 7.1 Connection and update indicators

| Indicator | Meaning | Typical update |
|---|---|---|
| **9104 Cathode Heater** dot | Green only after valid supply readback and confirmation of preset 3, OVP, and OCP; red otherwise | Supply polling and UI refresh about every 500 ms |
| **E5CN Temp Sensor** dot/temperature | Green after a valid numeric temperature; unavailable/error otherwise | Each controller polls about every 500 ms |

Hardware controls remain disabled until the supply is command-ready. Temperature plots are disabled in this release; only the numeric temperature and status are active.

### 7.2 Setpoints, goals, and nudges

The three displayed value types are different:

| Indicator | Exact meaning |
|---|---|
| **Sent** | Last current or voltage setpoint whose serial command returned OK. During a ramp, this changes after each acknowledged step. It is a command record, not measured output. |
| **Goal** | Final target stored in dashboard software and used for prediction, later output activation, and ramp completion. |
| **Measured Output** | Independent live voltage/current readback from the 9104; see Section 7.5. |

The following behavior applies when a nonblank value is entered and its **Set** button is pressed:

| Dashboard output state and selected mode | Current **Set** | Voltage **Set** |
|---|---|---|
| **OFF**, any mode | Validates current, stores the current Goal, and updates predictions. It may serially read OCP for validation, but does not send a `CURR` setpoint. | Validates voltage, stores the voltage Goal, and updates predictions. It may serially read OVP for validation, but does not send a `VOLT` setpoint. |
| **ON — Immediate Set** | Stores the Goal and immediately sends that current setpoint to preset 3. Output remains ON. | Stores the Goal and immediately sends that voltage setpoint to preset 3. Output remains ON. |
| **ON — Ramp Current** | Stores the new current Goal and starts a current ramp from the live current readback toward it. It does not reset current to zero. | Immediately sends the new fixed voltage, then starts a current ramp from the live current readback toward the already-stored current Goal. |
| **ON — Ramp Voltage** | Immediately sends the new fixed current, then starts a voltage ramp from the live voltage readback toward the already-stored voltage Goal. | Stores the new voltage Goal and starts a voltage ramp from the live voltage readback toward it. It does not reset voltage to zero. |
| **An active ramp worker is running** | The Set controls are disabled; a handler invocation is rejected. | The Set controls are disabled; a handler invocation is rejected. |

In the two cross-mode cases—Voltage **Set** during Ramp Current or Current **Set** during Ramp Voltage—the fixed value is sent immediately and the selected ramp variable is then driven toward its existing Goal. The zero-start sequence described in Section 7.3 is not repeated while output is already ON.

If the immediate fixed-value command in a cross-mode Set or nudge fails, the dashboard attempts `SOUT0`; the output is shown OFF only if that shutdown is acknowledged. If the fixed write succeeds but the new ramp cannot be started, the output can remain ON at the newly sent fixed value and the prior ramp-variable setpoint.

Submitting a blank entry is different from setting zero. When no ramp worker is active, Blank + **Set** clears that Goal and clears its Sent display without sending a setpoint command. This is allowed even while output is ON; it does not turn output off, change a fixed hardware setpoint already in effect, or prove the measured value is zero. After a Goal is cleared, a later OFF-to-ON request is blocked until both Goals have been set again. A cross-mode operation while output remains ON also cannot successfully ramp a variable whose Goal has been cleared.

#### Nudge buttons

The nudge buttons use the same goal-setting path as the text **Set** buttons:

| Selected mode while no ramp worker is active | Available nudge buttons | Effect while output is OFF | Effect while output is ON |
|---|---|---|---|
| **Immediate Set** | Current **+0.01/-0.01 A** and voltage **+0.02/-0.02 V** | Changes the corresponding Goal only; no setpoint is sent. | Immediately sends the changed current or voltage setpoint. |
| **Ramp Current** | Voltage nudges only; current nudges are disabled | Changes the voltage Goal only. | Sends the changed fixed voltage immediately, then starts a current ramp toward the stored current Goal. |
| **Ramp Voltage** | Current nudges only; voltage nudges are disabled | Changes the current Goal only. | Sends the changed fixed current immediately, then starts a voltage ramp toward the stored voltage Goal. |

All nudge buttons are disabled while a ramp worker is active. If the value used by a nudge is unavailable or **--**, its calculation starts from zero. A nudge still undergoes the normal OCP/OVP and voltage-step validation.

Current must be nonnegative and no greater than the confirmed OCP. Voltage must be nonnegative, no greater than the confirmed OVP, and a multiple of 0.02 V. Zero is a valid numeric Goal and is not the same as a blank Goal.

### 7.3 Output mode and output toggle

Selecting **Immediate Set**, **Ramp Current**, or **Ramp Voltage** is always **Software only**. Selection does not change either Goal, send zero, start a ramp, or change output state. The selector is disabled only while a ramp worker is active, so changing modes while output is already ON also sends nothing by itself.

The **Output OFF/ON** image button operates from the dashboard's commanded output belief. Its OFF-to-ON sequence depends on the selected mode:

| Selected mode when dashboard output is OFF | Exact OFF-to-ON serial sequence |
|---|---|
| **Immediate Set** | Send the current Goal to preset 3 → send the voltage Goal to preset 3 → send `SOUT1`. |
| **Ramp Current** | Send the fixed voltage Goal to preset 3 → explicitly send `0.00 A` to preset 3 → send `SOUT1` → read live current → send current steps toward the current Goal. |
| **Ramp Voltage** | Send the fixed current Goal to preset 3 → explicitly send `0.00 V` to preset 3 → send `SOUT1` → read live voltage → send voltage steps toward the voltage Goal. |

The Ramp Current zero is an actual `CURR 30000` serial setpoint and the Ramp Voltage zero is an actual `VOLT 30000` serial setpoint; each encodes zero for preset 3. It is not a temporary Goal: the Goal remains the final requested target, while Sent changes to `0.00` after the zero command is acknowledged. The dashboard does not wait for a measured-zero readback before sending `SOUT1`. After output is enabled, the ramp worker reads the live value and calculates its steps from that reading rather than assuming the physical output is exactly zero.

The zero-start sequence occurs only on a dashboard-believed OFF-to-ON transition. It does not occur merely because a ramp mode is selected, nor because a Goal is entered while output is OFF, nor because modes are changed while output is ON, nor because a new Goal is submitted while output is already ON.

Enable is allowed only when:

- The supply is command-ready.
- Both current and voltage goals exist.
- Goals are within confirmed OCP/OVP.
- BCON is connected when **Disable CCS Output on BCON Disconnect** is enabled.
- VTRX state permits enable when the **VTRX CCS pressure guard** is enabled.

If a required fixed setpoint or explicit zero command fails, enable is cancelled and the dashboard attempts output OFF. If `SOUT1` is not acknowledged, the ramp does not start and the UI remains OFF, but the physical output state must be treated as uncertain.

When the dashboard believes output is ON, pressing the same Output button stops any active ramp and sends unconditional `SOUT0`, regardless of selected mode, Goals, BCON state, or pressure guard. The UI changes to OFF only after `SOUT0` returns OK. If it fails or is uncertain, the dashboard intentionally retains ON/uncertain rather than claiming a safe state.

#### Active ramp controls and completion

Current and voltage ramp steps are normally separated by about 1 second and use the configured slew rate to determine step size. The worker verifies the final live readback after settling. Starting or completing a ramp does not turn the 9104 output off.

- Current/Voltage **Set**, all nudge buttons, and the Output Mode selector are disabled while the ramp worker is active.
- **STOP RAMP** remains available. It sets a software stop request; it sends neither a zero setpoint nor `SOUT0`. A serial step already in progress may finish before the worker observes the request. Output remains ON at the last successfully sent value.
- The Output OFF/ON button also remains available. Pressing it during a ramp stops the worker and sends `SOUT0`.
- If a ramp worker aborts because live readback is unavailable, communication is lost, a step repeatedly fails, or final verification fails, the dashboard warns and restores the controls but does not automatically send `SOUT0`. Treat the output as still enabled at zero, a partial step, the last sent value, or an otherwise uncertain value until OFF is confirmed.

Use **STOP RAMP** only to stop future ramp steps while retaining output. Use the separate Output button when the intended result is output OFF.

### 7.4 LUT and predicted values

The LUT selector is **File/software only**. It lists valid CSV files in **data/lut/power_supply** whose header consists of the three columns **beam_current, voltage, heater_current** and whose data is numeric and nonempty. Each cathode has its own selector; the first valid filename alphabetically is selected at startup, and selections are not persisted through dashboard restart. An invalid selection is rejected and the prior valid selection is restored.

The selected LUT/model recalculates:

- Predicted beam current (used internally)
- Predicted emission current
- Predicted grid current
- Predicted heater current and voltage

Within the LUT data range, predictions use linear interpolation and duplicate input points are collapsed to their median. The binding heater-current or heater-voltage goal determines the operating point. Inputs below the LUT range or otherwise without a solution show **--** rather than being extrapolated.

Above the LUT range, the dashboard can provide a Richardson-Dushman model estimate rather than a measured or interpolated LUT value; the Messages log identifies this as model-derived. The dashboard calculates emission current as beam current divided by 0.72 and grid current as 28% of emission. Main Control’s emission guard uses these predictions when enabled.

### 7.5 Measured values and warnings

| Indicator | Meaning |
|---|---|
| **Measured Output** voltage/current | Live 9104 measurements; **--** or error text means a valid reading is unavailable |
| **Temp** | Live E5CN clamp temperature |
| **CV / CC** | The active 9104 regulation mode is highlighted; gray means that mode is not reported active |
| **Predicted Output: Emission / Grid** | Calculated currents derived from the selected LUT/model and accepted heater goals |
| **Predicted Output: Heater Voltage / Heater Current** | Expected binding heater operating point after considering both goals |

Measured voltage, current, temperature, and CV/CC mode come from polling.

- Voltage-difference warning is evaluated only while output is ON and the supply reports CV Mode.
- Current-difference warning is evaluated only while output is ON and the supply reports CC Mode.
- A difference must be strictly greater than the configured percentage of the sent value for more than about 1.5 seconds to warn. Equality does not warn. A sent value of zero disables that comparison.
- Measured temperature strictly above the Overtemp Limit warns. This is display/logging only and does not automatically turn CCS off. A critical message is logged immediately, then no more than about once every 10 seconds while the overtemperature persists; the interval resets after a normal or unavailable reading.
- Missing readback shows unavailable/error status rather than a safe value.

### 7.6 Cathode Config tab

| Setting/control | Exact current behavior | Interaction and persistence |
|---|---|---|
| **Log Power Settings** | Reads preset 3 from the supply, compares returned voltage with the goal, and logs the result | Serial; not a setting change |
| **Overvoltage Limit (V)** (OVP) | Accepts 0.02 through 84 V, inclusive, sends the limit, reads it back, and requires confirmation; the live box shows confirmed readback or **N/A** | Serial; not saved by the dashboard |
| **Overcurrent Limit (A)** (OCP) | Accepts 0.10 through 10 A, inclusive, sends the limit, reads it back, and requires confirmation; the live box shows confirmed readback or **N/A** | Serial; not saved by the dashboard |
| **Current Slew Rate** | Ramp-current step rate; default 0.01 A/s | Software only; session only |
| **Voltage Slew Rate** | Ramp-voltage step rate; default 0.02 V/s | Software only; session only |
| **Voltage Diff Warning** | Allowed percent deviation before the timed voltage warning | Software only; default 10%; session only |
| **Current Diff Warning** | Allowed percent deviation before the timed current warning | Software only; default 10%; session only |
| **Overtemp Limit** | Temperature threshold for display/log warning | Software only; default 150 °C; session only; no automatic shutdown |

Session only means the setting does not persist between dashboard restarts

#### Current validation caveats

- For finite numeric inputs, the OVP tooltip says the value must be **greater than** 0.02 V, but the implemented check accepts exactly 0.02 V and rejects values below it.
- For finite numeric inputs, the OCP tooltip says the value must be **greater than** 0.10 A, but the implemented check accepts exactly 0.10 A and rejects values below it.
- Therefore the tooltip does not accurately describe the inclusive minimum boundary. Current code applies the finite numeric lower and upper OVP/OCP comparisons stated in the table.
- The OVP/OCP handlers do not explicitly reject NaN before attempting the serial operation. This is a validation gap, although hardware readback confirmation can still fail. Use only finite values within the stated ranges.
- The Current Slew Rate spinbox advertises 0.01–10 A/s and the Voltage Slew Rate spinbox advertises 0.02–0.06 V/s. A typed value submitted with **Set** is only checked as parseable and greater than zero, then rounded to two decimals. The handler does not enforce either displayed upper limit.
- Non-finite typed values such as NaN or positive infinity are not explicitly rejected by the slew-rate handler. Treat this as a validation gap; use finite values within the displayed ranges for normal operation.
- The Overtemp Limit handler parses a number but does not enforce a range or explicitly reject non-finite values. Use a finite, physically meaningful threshold.

The dashboard’s desired startup OVP/OCP defaults are reapplied as part of connection readiness (1.1 V OVP and 7.0 A OCP in the current implementation). Config-tab values are not written to a dashboard persistence file, even if the instrument itself retains a value temporarily.

## 8. Beam Pulse / BCON

### 8.1 Connection and controller status

The connection dot is green while the BCON serial link is active and red while disconnected. The dashboard attempts to connect automatically.

| Control/indicator | Behavior | Interaction |
|---|---|---|
| **Connect/Reconnect** | Opens or reopens the configured BCON serial port | Serial |
| **Disconnect** | Requests ALL_OFF before closing the port. Main Control may block the disconnect when CCS shutdown is required but cannot be confirmed. | Serial |
| **Interlock OK/LOCKED** | BCON firmware interlock state from register polling | Read-only |
| **Watchdog OK/EXPIRED** | BCON watchdog state from register polling | Read-only |
| **Watchdog entry + Set** | Applies the watchdog timeout; the value is reapplied on connection | Serial |
| **Log:** line | Most recent Beam Pulse/BCON action, status, or error summarized in the panel | Read-only |

The watchdog defaults to 1500 ms and is reapplied on every connection. The driver-supported range is 50–60000 ms. The UI checks that the entry is an integer but does not pre-check this full range; the driver/firmware error is therefore the final rejection for an out-of-range integer. The value is not saved between dashboard sessions. BCON telemetry is configured around 500 ms, the full status is polled about every 500 ms, and queued UI updates are processed about every 200 ms.

### 8.2 Manual channel settings

Each channel has:

- **Mode:** OFF, DC, PULSE, or PULSE_TRAIN.
- **Duration:** whole milliseconds from 1 through 60000 for Pulse and Pulse Train.
- **Count:** forced to 1 for a single Pulse; 2 through 10000 for Pulse Train.
- **O:** live polled output state, 0 or 1.
- **Remaining:** live remaining pulse count when firmware provides it.

Changing Mode, Duration, or Count is **Software only** until a Main Control activation or CSV step applies it. These fields describe the next intended manual configuration, not necessarily the live firmware state. Controls are locked while the channel is reported active; DC is treated as running.

Each channel starts in OFF with a 100 ms duration and count 1. OFF and DC disable the Duration and Count entries. PULSE forces Count to 1. After selecting PULSE_TRAIN, enter a count of at least 2 before activation.

### 8.3 Toggle PVX Enable

**Toggle PVX A/B/C Enable** sends an immediate single-register serial toggle to the respective physical PVX enable latch. Each channel has an approximately 150 ms cooldown.

- It does not require dashboard beam arming.
- It does not check the Main Control Enabled/Disabled software interlock.
- It does not check VTRX pressure or predicted emission.
- A transport success does not prove the physical latch changed.
- The dashboard does not display the latched PVX enable state.
- BCON ALL_OFF, dashboard disarm, watchdog expiration, and the dashboard E-stop do not change this latch.

Use the physical PVX LED as the authoritative enable indication.

### 8.4 Experimental CSV sequence

> **Experimental—usable with documented limitations.**

The CSV controls support local load/save/template operations and a running sequence:

| Control | Behavior | Interaction |
|---|---|---|
| **Load CSV** | Reads sequence rows from a local CSV file | File only |
| **Save Template** | Writes a sequence-template CSV to a selected local file | File only |
| **Run Sequence** | Starts the worker that sends BCON settings and synchronized start commands step by step | Serial |
| **Stop Sequence** | Prevents future sequence steps from being submitted | Software only |

Supported row form:

**step, ch, mode, duration_ms, count, dwell_ms**

Blank lines, comments, and a header are accepted. Channel can be 1, 2, 3, or ALL. Rows with the same step number are applied together. Where permitted by parsing, duration defaults to 100 ms and count defaults to 1; the final dwell value for the step controls its fixed wait.

The sequence requires a loaded file, an idle sequence worker, dashboard beam arm, BCON connection, and passing configured pressure/emission guards.

The file label shows the loaded filename and parsed step count. The progress line reports states such as Ready, the current step, stopped, complete, or an error. **Loaded Steps** is a read-only preview of the parsed operations; it is not an editor.

Critical limitations:

- CSV channels bypass the Main Control per-beam Enabled/Disabled software interlocks.
- The worker submits a synchronized start, waits the configured fixed dwell, and moves on. It does not wait for firmware acknowledgement, a confirming status poll, or pulse completion.
- **Stop Sequence does not send OFF and does not stop a DC, Pulse, or Pulse Train already started.**
- Normal sequence completion also does not send ALL_OFF.
- Command feedback is not coordinated through the same transaction/token handling used by Main Control.

To shut down active outputs, use the individual Main Control OFF controls, **Disable All Beams**, disarm, or **E-STOP: BEAMS & CCS** as appropriate. Do not treat **Stop Sequence** as an output-off control.

## 9. Main Control

Main Control coordinates BCON beam actions, dashboard-only per-beam interlocks, software arming, and the combined beam/CCS E-stop.

### 9.1 Beam controls

| Control | What it does | Restrictions and confirmation | Interaction |
|---|---|---|---|
| **Beam A/B/C OFF/ON** | Each Beam A, B, or C button is a state-dependent toggle. When its cached polled state is ON, it queues single-channel OFF. When its cached polled state is OFF, it queues that channel's Beam Pulse Manual mode, duration, and count. | The button is normally available only while armed and that channel is Enabled. Starting output requires valid settings, BCON connection, and enabled pressure/emission guards. The OFF path does not re-run activation guards and requires a confirming mode-OFF/output-low poll. | Serial |
| **Beam A/B/C Disabled/Enabled** | Toggles a dashboard software interlock used by Main Control activation | Only operable while armed. It does not read or write a BCON interlock register. Disabling a live beam first sends OFF and waits for confirmation. | Software only when inactive; mixed when disabling an active beam |
| **Activate Enabled Beams** | Applies the selected settings to all channels whose Main Control interlock is Enabled and starts them together | Requires arm, connection, valid settings, and all enabled guards. | Serial |
| **Disable All Beams** | Sends BCON ALL_OFF and, after a confirming poll, clears all three dashboard software interlocks | No arm requirement. Does not disarm or toggle PVX enable. | Mixed |
| **ARM BEAMS / BEAMS ARMED** | Arms or disarms the dashboard’s Main Control workflow | Arming requires BCON connection but sends no firmware arm command. Disarming requests serial output shutdown; it remains armed if shutdown is not confirmed. | Software only to arm; mixed to disarm |
| **E-STOP: BEAMS & CCS** | Requests BCON ALL_OFF and turns off active or uncertain cathode outputs | Available regardless of normal start guards. Any individual failed attempt is logged as critical even if another attempt succeeds. Unconfirmed cathode state remains shown as ON/uncertain. | Serial |

Main Control allows one normal BCON operation at a time. A second normal action is rejected while one is pending. Safety operations have the priority **E-stop > Disarm > Disable All > normal operation**. A higher-priority request can preempt lower-priority work. The normal send timeout is approximately 1.5 seconds. After a command is sent, acknowledgement and a confirming post-command poll share an additional timeout window of approximately 1 second. A disconnect during an operation makes the result indeterminate unless a later status poll proves the state.

### 9.2 Software interlocks, beam state, and button behavior

#### Relationship between software interlock and beam output

Dashboard arm, the per-beam software interlock, and live BCON output are separate states:

| State | Meaning and effect |
|---|---|
| Dashboard **disarmed** | All three software interlocks are reset to Disabled. Their buttons, the three beam output buttons, and **Activate Enabled Beams** are disabled. |
| Dashboard **armed**, Beam X **Disabled** | The software interlock is closed in dashboard software. Beam X's output button is disabled and Activate Enabled Beams skips it. This state is not a BCON register and does not itself send OFF. |
| Dashboard **armed**, Beam X **Enabled** | The software interlock grants Main Control permission to operate Beam X. Its output button is enabled. This does not turn the beam on or prove that it is on. |
| Live BCON output state | Comes from BCON register polling and determines whether the beam output button's next action is ON/configure or OFF. A finite pulse can end while its software interlock remains Enabled. |

The software interlock is therefore a permission gate, not a live-output indicator or hardware safety interlock. Enabled does not mean ON; Disabled does not by itself prove OFF. Main Control delays changing Enabled to Disabled when it believes a beam is active so that it can request that channel OFF and confirm the polled OFF state first.

#### Queued operations versus immediate ALL_OFF

Normal per-channel and multi-channel start/stop operations use two layers:

1. Main Control creates one pending operation token. This is a confirmation slot, not a backlog of button presses.
2. The BCON driver queues the channel parameter/mode register writes and a firmware **APPLY_STAGED_MODES** command for its background serial worker.
3. Main Control follows command transmission, firmware EXECUTED/rejected diagnostics, and a later full status poll.

Only one Main Control operation may be pending. Another normal button press while any operation is pending is rejected with a status warning; it is not saved to run later. If a tokenized staged batch is partially written, rejected after staging, or becomes inconclusive, the BCON driver fails closed by attempting an immediate ALL_OFF.

**Disable All Beams**, disarm, and E-stop do not wait behind the normal write queue. They use the driver's immediate ALL_OFF path, which invalidates and clears queued BCON writes, attempts the ALL_OFF command even when the cached connection flag is stale but the serial handle remains open, and checks firmware command diagnostics. Main Control then still requires a later poll showing the affected channels in mode OFF with output level 0 before committing the corresponding software-state change.

Safety-operation priority is **E-stop > Disarm > Disable All > normal**. A higher-priority request preempts a lower-priority pending operation. An equal- or higher-priority pending operation normally blocks the new request; a failed E-stop confirmation can be released to permit an operator recovery request. Repeated disarm requests are coalesced; a repeated E-stop reuses the active E-stop transaction and performs its redundant shutdown attempts again.

#### Beam A/B/C output button

The text and color are driven by cached BCON polling. Pressing the button does not immediately change its displayed live state.

- **When the cached beam state is OFF:** Main Control reads that channel's Mode, Duration, and Count from Beam Pulse Manual Control. With an ON-producing mode, it rechecks arm, connection, settings, pressure, and predicted-emission guards, then queues the staged channel configuration and APPLY command. If Manual Mode is OFF, it queues an OFF configuration instead of starting output.
- **When the cached beam state is ON:** Main Control queues OFF for that channel only. Pressure and emission activation guards are not applied to this shutdown path. The operation completes only after firmware acceptance and a later poll reports both mode OFF and output level 0 for that channel.
- A normal press never intentionally sends global ALL_OFF. However, an uncertain or partially failed tokenized staged-write batch invokes the driver's fail-closed ALL_OFF recovery.
- The UI output button is available only while the dashboard is armed and that channel's software interlock is Enabled. If those permissions are unavailable, use an applicable global shutdown control rather than relying on the disabled per-channel button.

For an ON/configure operation, firmware EXECUTED followed by a later full poll completes the transaction status; the operation tracker does not require that poll to match the requested ON mode. Treat the first three live beam-status lines and physical equipment as the authoritative evidence that output actually started.

#### Beam A/B/C Disabled/Enabled software-interlock button

This button is operable only while the dashboard is armed.

- **Disabled → Enabled:** Changes the dashboard boolean and enables that beam's output button. It sends no BCON command and does not start output.
- **Enabled → Disabled while the cached beam state is inactive:** Changes to Disabled immediately. It sends no channel OFF and no ALL_OFF because the cached state is already inactive.
- **Enabled → Disabled while the cached beam state is active:** Creates a normal pending operation and queues single-channel OFF. The button remains Enabled until firmware accepts the command and a later poll reports mode OFF and output level 0. Only then does it change to Disabled. A rejection, timeout, disconnect, unavailable status API, or nonzero output-level poll leaves the interlock Enabled.
- Pressing an interlock button while another operation is pending is rejected rather than queued for later.

#### Activate Enabled Beams

- The button is available only while armed.
- It gathers the Manual Control configuration for every software-Enabled channel; Disabled channels are skipped and are not sent OFF.
- If no channel is Enabled, it reports that nothing was eligible and queues no serial command.
- Every included configuration and the enabled pressure/emission guards must pass before the synchronized staged batch is queued. One invalid included channel rejects the whole activation request.
- The BCON driver queues the included settings and modes, then one APPLY command so the selected channels start together.
- This is a normal queued operation, not global ALL_OFF. The driver's fail-closed ALL_OFF recovery still applies if the staged batch becomes partial or uncertain.
- As with an individual ON operation, completion means firmware EXECUTED plus a later full poll; inspect the live beam lines to verify which outputs actually became active.

#### Disable All Beams

- Requires no dashboard arm and bypasses normal activation guards.
- Preempts a pending normal operation, invalidates and clears queued BCON writes, and attempts one immediate, firmware-confirmed ALL_OFF.
- Main Control waits for a later full poll showing all three channels mode OFF and output level 0.
- Only after that poll does it reset all three software interlocks to Disabled.
- It leaves the dashboard armed and does not change PVX enable latches, CCS output, or Beam Energy high-voltage supplies.
- If Disarm, E-stop, or another Disable All of equal/higher priority is already pending, the new Disable All request is normally rejected rather than queued. A failed E-stop confirmation may be released so that an operator recovery request can proceed.

#### ARM BEAMS / BEAMS ARMED

- **When disarmed:** Pressing **ARM BEAMS** requires a connected BCON but changes dashboard software state only. It sends no firmware arm command, does not enable any per-beam software interlock, and does not start output.
- **When armed:** Pressing **BEAMS ARMED** requests disarm. It stops CSV sequence steps, preempts lower-priority work, clears the BCON write queue, and attempts immediate ALL_OFF even when cached beam states are already OFF.
- The dashboard remains armed and the software interlocks retain their current state until a later full poll confirms all three channels OFF/output-low. Only then does disarm complete and reset the interlocks. A failed or unconfirmed ALL_OFF leaves the dashboard armed.

#### E-STOP: BEAMS & CCS

- Available regardless of dashboard arm, software interlocks, pressure, emission, or normal command state.
- Preempts every lower-priority BCON operation and makes two redundant immediate ALL_OFF attempts. Each attempt clears queued BCON writes rather than joining the normal queue.
- Independently requests OFF for all available cathode-heater supplies.
- A later all-channels-OFF/output-low poll completes the BCON disarm state. Individual failures remain critical even if another redundant attempt succeeds.
- It does not turn off Beam Energy high-voltage supplies or change PVX enable latches.

#### Status lines and confirmation

The first three lines show the latest polled BCON state for Beam A, B, and C:

- **OFF** when the polled channel is not considered running.
- The active mode and configuration for DC, Pulse, or Pulse Train.
- Pulse Train remaining count when available.
- For long pulse timing, the current waveform high/low phase can be shown.

The fourth line shows the current or most recent Main Control transaction progressing through request accepted, command sent, firmware OK/rejected, post-command poll, timeout, or failure. These lines are driven by BCON events and full polls; they do not change merely because a button was clicked.

### 9.3 Experimental Main Control Script bar

> **Experimental—usable with documented limitations.**

The **Script** selector is **Software only**. When its launch-path check succeeds, it discovers Python files directly inside the top-level **scripts** directory; it does not recursively discover utility scripts in nested folders. The launch-path check looks for a scripts directory beside the running Python executable before populating the selector, so the selector can be empty in launch modes where that directory does not exist even though the repository has a top-level scripts directory. **Execute** is **File/process** and launches the selected file using a blocking Python subprocess on the dashboard’s GUI thread.

Consequences:

- The dashboard can appear frozen until the script exits.
- There is no shared Main Control safety transaction, status confirmation, or automatic output shutdown.
- A script defines its own device access and safety behavior.
- The control is **File/process**, but the launched script may communicate with hardware according to that script’s code.

Do not assume Main Control arming, pressure, emission, or software-interlock rules apply to a launched script.

## 10. Machine Status

Machine Status is a read-only advisory chain refreshed by a worker approximately every 200 ms. It does not issue serial commands.

| Segment | Green condition | Forced red or notable caveat |
|---|---|---|
| **PMON Temperatures OK** | Process Monitor Environment Pass | Missing data remains unmet |
| **Pressure Below 1e-4 mbar** | Fresh valid pressure strictly below 1e-4 mbar | Equality is not green |
| **All Safety Interlocks Pass** | G9 aggregate interlock pass | Missing/fault is unmet |
| **High Voltage Subpanel On** | HVolt ON | G9 output on while HVolt is not on forces warning |
| **Pressure Below 1e-6 mbar** | Fresh valid pressure strictly below 1e-6 mbar | Equality is not green |
| **HV Power Supplies Nominal** | Supply communications, logic, values, and flags nominal | Any Beam Energy configured warning forces red |
| **Beam Controller Nominal** | BCON connected, ±1 kV criteria satisfied, flags clear, controller communication valid | This status is not the same as software arming |
| **Cathode Heating** | At least one cathode output is believed ON | Any overtemperature or an individual prediction at/above the total configured emission maximum forces red |
| **Beams Ready** | All preceding readiness conditions, dashboard software arm, and reported hardware arm are present | Enabled-channel predicted sum at/above emission maximum forces red even if the activation guard checkbox is disabled |
| **Beams On** | Any live BCON output is active | Uses BCON live state, not merely a button request |

Color priority is: forced warning red, ready green, an earlier unmet prerequisite red when a later stage is already green, otherwise gray.

The two pressure milestones use only fresh, valid 972B/VTRX pressure; the secondary 902B is not a fallback.

The complete displayed Machine Status state is included in the Data Log and Supabase snapshot.

## 11. Configuration menus

### 11.1 General menu

| Control | Exact effect | Interaction |
|---|---|---|
| **Configure COM Ports / Hide COM Port Configuration** | Shows or hides the assignment rows. Opening the rows scans currently enumerated real ports. | Software only |
| **Apply** under COM assignments | Builds a new in-memory port map, forwards it to the dashboard’s partial live-update path, then hides the rows | Mixed: can disconnect/reconnect supported serial subsystems; not persistent |
| **Save Layout** | Persists current resizable-pane positions to **usr/usr_data/pane_state.json** | File only |
| **Launch Log Post-processor** | Starts **scripts/post-process/post_process_gui.py** in a separate process | File/process |

#### Configure COM Ports limitation

This control is **not fully supported** as an operating port-reassignment tool:

- When a previously saved selection is absent, the dialog can automatically choose the first enumerated real port. Verify every row before applying.
- Apply changes the in-memory dictionary but does not save it as the startup COM configuration.
- The update path attempts live changes for VTRX, Cathode Heating, and Beam Energy/Knob Box. These reconnect operations can still fail or leave a partially reconfigured subsystem.
- The rows do not include the 902B. Applying the displayed rows replaces the in-memory port map without a 902B entry but does not reconstruct or intentionally reconnect the already-running 902B driver.
- Interlocks has a separate update method, but this Apply path does not invoke it. Process Monitor, Beam Pulse/BCON, and Laser Monitor are also not reconstructed or reconnected by this path.

Use the startup port dialog and restart the dashboard for reliable reassignment.

### 11.2 Log Settings

| Setting | Options/default | Exact effect | Persistence |
|---|---|---|---|
| **Log Level** | VERBOSE, DEBUG, INFO, WARNING, ERROR, CRITICAL; normally INFO at startup | Sets the minimum severity shown in Messages; the selected level and more severe messages are displayed | Runtime only |
| **File Log Level** | DEBUG or VERBOSE; VERBOSE at startup | DEBUG omits VERBOSE messages; VERBOSE records all dashboard levels | Runtime only |
| **Disable Knob Box logging when HV subpanel is off** | Checked by default | Suppresses Knob Box log records while the subpanel is off; does not stop polling, display, or serial traffic | Runtime only |
| **Disable BCON logging when HV subpanel is off** | Checked by default | Suppresses BCON log records while the subpanel is off; does not disconnect or stop BCON | Runtime only |
| **Disable CCS logging when CCS power is off** | Checked by default | Suppresses CCS log records while CCS power is off; does not turn outputs off or stop polling | Runtime only |

### 11.3 Beam/Cathode Settings

The checkbox guards default enabled at each launch. The numeric settings described below are persisted in **usr/usr_data/main_control_config.json**.

| Setting | Default value | Exact effect | Interaction |
|---|---|---|---|
| **Disable CCS Output on BCON Disconnect** | Checked | An unexpected BCON disconnect requests all cathode outputs OFF and blocks new CCS enables. A manual disconnect with active CCS first requires a shutdown attempt and is blocked when OFF cannot be confirmed. Enabling this setting while already disconnected immediately invokes CCS shutdown. | Mixed: software guard; can immediately attempt serial CCS OFF |
| **Disable CCS Output if pressure exceeds 1e-5 mbar for N s** | Checked; grace default 30 s | Unsafe/stale/error 972B pressure starts a grace timer while CCS is active and blocks new CCS enables. Active cathodes are shut down after the grace expires. Valid pressure at or below 1e-5, or no active CCS, clears the timer. Warnings are emitted about every 10 seconds during the condition. | Mixed: software guard/timer; expiry causes serial CCS OFF |
| **Grace Period** | Default 30 s; finite, nonnegative | Sets the CCS pressure-shutdown delay in seconds | Software/file only |
| **Disable Beams if pressure exceeds 1e-5 mbar** | Checked | 972B pressure above 1e-5, stale/unavailable pressure, or firmware error invalidates a pending operation and requests BCON ALL_OFF. The software interlocks clear only after confirmed all-off; the dashboard remains armed. The one-shot condition resets after valid pressure at or below 1e-5. | Mixed: software guard; later unsafe updates cause serial ALL_OFF |
| **Disable Beams if 20kV Bertan reaches or exceeds N mA** | Checked; default 0.7 mA; accepted 0 through 1 mA inclusive | Each Beam Energy update requests beam disarm when measured +20 kV current is **greater than or equal to** the threshold. BCON ALL_OFF is requested; after confirmed all-off, dashboard arm and all three software interlocks clear. CCS is not turned off. A persistent high reading can request disarm again after the previous operation ends. | Mixed: software guard; qualifying readback causes serial beam disarm |
| **Max 20kV I** | Default 0.7 mA; 0–1 mA inclusive | Threshold used by the automatic beam-disarm guard | Software/file only |
| **Do not activate Beams if Predicted Emission Current exceeds N mA** | Checked; maximum default 6 mA; finite, nonnegative | Requires predictions for all projected active/new channels and blocks at **greater than or equal to** the maximum. Applies to Main Control ON, Activate Enabled Beams, and experimental CSV starts. When unchecked, this activation check is skipped, but Machine Status still warns. | Software guard |
| **Max Emission I** | Default 6 mA; finite, nonnegative | Threshold used by emission checks; activation requires predicted total strictly below it | Software/file only |

These are dashboard software protections layered on top of hardware protections. Disabling a checkbox does not alter any hardware interlock or equipment limit.

## 12. Messages and logging

The Messages pane shows the newest approximately 100 visible lines at or above the configured display level.

| Control | Effect | Interaction |
|---|---|---|
| **Clear** | After confirmation, clears the visible Messages pane only; existing log files remain | Software only |
| **Export** | Writes the currently visible text, up to the pane’s retained lines, to a selected file | File only |
| **Log/Record toggle** | Starts or stops both event-log and Data Log recording; green circle means recording, gray means stopped | File only |

Recording starts enabled during normal startup. It produces two types of local file:

- Event logs under **%USERPROFILE%/EBEAM_dashboard/EBEAM-Dashboard-Logs** contain timestamped dashboard messages and rotate approximately every 8 hours.
- Data Logs under **%USERPROFILE%/EBEAM_dashboard/EBEAM-Dashboard-Datalogs** contain one timestamped JSON status snapshot per line and rotate approximately every hour.

The Data Log snapshot includes 972B and unsuppressed 902B pressure, G9 safety fields, Process Monitor temperatures, VTRX switch bits, cathode heater current/voltage/clamp temperature, Beam Energy state, and the complete displayed Machine Status state. It is change-driven with a minimum interval of about 100 ms between ordinary snapshots; after about one second without a write, a heartbeat records the current full state. Turning recording back on creates new files and writes a Data Log baseline.

If Supabase logging is configured, the same recording state gates those submissions. Supabase updates are limited to no more than approximately one every 3 seconds. The secondary 902B value is deliberately cleared from both destinations while the low-972B suppression described in [Section 4.2](#42-pressure-display-suppression-and-guards) is active.

Clearing or filtering the visible pane does not erase records already written to disk. **Ctrl+S** performs the same visible-text export workflow.

## 13. Laser Monitor

The Laser Monitor has no visible dashboard panel in this release. With a real startup COM port, a background worker sends state about every 500 ms:

- **beams** is based on live BCON beam activity, not dashboard arm or PVX enable.
- **radiation** is based on valid +20 kV actual voltage at or above 10 kV.

If +20 kV readback becomes unavailable, the dashboard retains the last valid radiation state rather than assuming radiation off. The driver expects an OK response, waits for the controller’s initial boot interval, and retries a lost link with increasing delays. The firmware watchdog forces the beams indication low after approximately 4 seconds without updates; it does not similarly clear the last radiation state. On normal dashboard shutdown, the worker sends beams off while preserving the current radiation state if possible.

There is no dashboard connection indicator or live COM reassignment for this feature; use logs and the external indicator hardware for status.

## 14. Features not fully supported in this release

| Feature | Current status and operator guidance |
|---|---|
| BCON CSV sequence | **Experimental—usable with documented limitations.** It bypasses Main Control software interlocks, advances without command/status or pulse-completion confirmation, and Stop Sequence does not turn active outputs off. |
| Main Control Script bar | **Experimental—usable with documented limitations.** It runs a selected top-level Python script on the GUI thread without Main Control safety coordination. The selector can be empty when the running executable does not have the launch-path directory the implementation checks. |
| Main Control **Configure COM Ports** | Not a reliable live-reassignment or persistent configuration tool. Use the startup dialog and restart. |
| Cathode temperature graphs | Disabled in this release; numeric temperature and warning status remain available. |
| Oil System panel | Present in the source tree but not instantiated in the active dashboard layout. |
| Visualization Gas Control | Scaffold only and not instantiated in the active dashboard. |
| Beam Extraction | Placeholder/TODO subsystem and not instantiated. |
| Deflection Monitor | Placeholder/TODO subsystem and not instantiated. |
| PVX latch/readback display | The dashboard can send a PVX enable toggle but does not show the resulting latched enable state; use the physical indicator. |
| Laser Monitor UI | Background integration only; no visible connection/status panel or in-app reassignment. |
| Process Monitor live port recovery | No supported creation/reassignment path after startup; restart with the correct port. |

## 15. Recommended output-off and recovery choices

Use the control whose scope matches the condition:

| Need | Use | Notes |
|---|---|---|
| Stop future CSV rows | **Stop Sequence** Button in CSV tab of Beam Pulse | **Stop Sequence** will not stop an already active output |
| Turn one beam channel off | That channel’s **OFF** button in Main Control | Solely changing its next Mode to OFF in Beam Pulse does not send an OFF command |
| Turn all BCON outputs off and clear Main software enables | **Disable All Beams** | |
| Turn all beams off and leave the dashboard disarmed | Click **BEAMS ARMED** to disarm and wait for confirmed shutdown | |
| Respond to automatic +20 kV current beam disarm | Verify BCON outputs are off and the dashboard is disarmed; investigate the +20 kV condition under the approved procedure | |
| Stop an active cathode ramp but retain output | **STOP RAMP** | This is not an output-off action |
| Turn one cathode output off | Its **Output ON/OFF** toggle and verify success | |
| Emergency dashboard request for all beams and CCS off | **E-STOP: BEAMS & CCS** and verify equipment state | It does not turn off HVolt supplies or PVX channel enable latches |
| Recover a port assignment | Restart experiment computer and dashboard, then use the startup COM dialog | The Main Control Configure COM Ports button is not fully supported |

When a safety-critical OFF remains unconfirmed, treat the output as potentially active. Check the physical equipment, local indicators, hardware interlocks, and approved shutdown procedure.
