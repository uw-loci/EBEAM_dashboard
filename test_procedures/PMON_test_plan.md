# PMON Subsystem Test Plan

## Purpose

Verify that the dashboard's PMON subsystem safely and accurately presents six
Omega DP16 temperature channels, preserves operator configuration, handles
physical and serial failures, and reports coherent status and logs. This plan
is intentionally fault-oriented: a failure is useful only if the dashboard
makes the failure obvious, does not present stale data as healthy, and recovers
without a restart when recovery is supported.

PMON channel mapping: 1 = Solenoid 1, 2 = Solenoid 2, 3 = Chamber Top,
4 = Chamber Bot, 5 = Air temp, and 6 = Unassigned (disabled by default).

## Safety Considerations

- Perform physical fault injection only on a designated test setup. Keep beam,
  high-voltage, and cathode outputs off, disarmed, and independently verified
  safe before touching PMON power, RS-485, USB, or sensors.
- Do not remove or reconnect wiring under unsafe voltage, in a hazardous area,
  or contrary to the DP16 and facility procedures. Use ESD precautions and
  strain relief; do not short sensor leads.
- One person performs the physical change and one observes the dashboard and
  log. Record wall-clock times for removal, UI transition, and recovery.
- Back up `usr/usr_data/process_monitor_config.json` and
  `usr/usr_data/com_ports.json` before file-manipulation cases. Restore the
  approved production files and all cabling after each suite.
- Verify sensor and RS-485 connectors are fully connected after every
  case.
- Use an approved dummy thermocouple only on Solenoid 1, Solenoid 2, or
  Unassigned. A connected dummy should stabilize near 20 C; pinch its insulated
  sensing end only to raise it gradually to about 30 C. Chamber Top, Chamber
  Bot, and Air temp use RTDs: do not attach the dummy to them; test those
  channels only with their installed RTD or a controlled unplug/replug action.

## Outline

1. Baseline display, channel mapping, and Machine Status
2. PMON Config-tab controls and persistence
3. Disabled-channel behavior
4. Physical PMON and sensor fault injection
5. Startup and configuration-file resilience
6. COM-port selection, live changes, and hot-plug behavior
7. Logging, status semantics, and log export
8. Shutdown, restart, and interaction stress

Unless a case states otherwise, begin with the safety conditions above, all
six DP16 units powered and connected, the USB/RS-485 adapter connected to the
test laptop, a known-good PMON configuration, the configured ProcessMonitors
COM port selected at startup, and all enabled channels at stable in-range
temperatures. Keep the Messages pane visible or export its log after the case.
Use an approved dummy thermocouple only for Solenoid 1, Solenoid 2, or
Unassigned temperature-manipulation cases; allow it to stabilize near 20 C
before each measurement.

## Suite 1 — Baseline display, mapping, and Machine Status

**Description:** Establish the reference behavior before injecting faults and
prove that each dashboard row represents the intended DP16 address.

**Initial conditions:** Common initial conditions apply. Confirm that channel 6
is disabled in the loaded configuration unless the case changes it.

### PMON-1.1 — Normal startup and six-channel baseline

**Description:** Verify normal connection, values, visual state, and the
default disabled spare channel.

**Initial conditions:** Record each DP16 front-panel temperature and status;
all enabled values are strictly inside their configured warning ranges.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Start the dashboard and select the known PMON COM port. | The dashboard starts without a PMON initialization exception. | |
| 2. Open Process Monitor > Main and wait for two complete polling passes. | Rows 1–5 show a current numeric value to one decimal place and green bars. Unassigned shows `OFF`, not a value. | |
| 3. Compare every enabled row with its DP16 display. | Each dashboard value agrees with its DP16 display within normal display/measurement tolerance. | |
| 4. Inspect Machine Status and Messages. | Environment Pass is true, PMON Temperatures OK is green, and the log identifies connection and initial valid readings without errors. | |

### PMON-1.2 — Channel-to-row routing and supported sensor response

**Description:** Detect swapped addresses, stale row updates, and a row that does not follow its supported physical input.

**Initial conditions:** Use an approved dummy thermocouple only for Solenoid 1, Solenoid 2, and, if safe, Unassigned. Chamber Top, Chamber Bot, and Air temp have their installed RTDs connected and stable.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Connect the dummy sensor to unit 1; allow it to settle near 20 C and identify its Main-tab row. | Solenoid 1 alone shows the dummy sensor's current value. | |
| 2. Pinch the dummy sensor's insulated sensing end until it rises toward 30 C, then release it. | Solenoid 1 follows the rise and subsequent cooling; no other row follows it. | |
| 3. Move the dummy sensor to unit 2; allow it to settle near 20 C and identify its Main-tab row. | Solenoid 2 alone shows the dummy sensor's current value. | |
| 4. Pinch and release the dummy sensor on unit 2. | Solenoid 2 follows the rise and subsequent cooling; no other row follows it. | |
| 5. Compare Chamber Top, Chamber Bot, and Air temp rows with their corresponding powered DP16 front-panel RTD readings. | Each RTD channel maps only to its documented row; the dashboard value agrees with the corresponding DP16 display within normal display/measurement tolerance. | |
| 6. Enable Unassigned, connect and pinch the dummy sensor on unit 6, then disable Unassigned again. | Unassigned alone follows unit 6 while enabled and returns to `OFF` when disabled. | |
| 7. In Config, change only the tested Solenoid 1 or Solenoid 2 row's bar range to bracket its current value; select Set, confirm the scale, then restore it. | Only the selected row's scale changes; another row's limits, value, enable state, and warning state do not change. | |

### PMON-1.3 — Warning-range boundaries and Machine Status propagation

**Description:** Verify the inclusive range boundary and the PMON-to-Machine-Status safety signal.

**Initial conditions:** Connect the dummy sensor to enabled Solenoid 1 or Solenoid 2. Let it stabilize near 20 C and record the current value `T`.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Set warning min and max so `T` is strictly inside; select Set and wait for an update. | The bar is green and Environment Pass remains true. | |
| 2. Set either warning bound exactly to `T`; select Set and wait for an update. | The bar remains green and Environment Pass remains true. | |
| 3. Move that bound past `T` so `T` is strictly outside; select Set and wait for an update. | The bar turns orange, Environment Pass is false, and PMON Temperatures OK is not green (gray or behind-red according to status progression). | |
| 4. Pinch the dummy sensor to about 30 C while its warning max remains below the new value. | The row remains orange and its displayed value follows the temperature rise; the warning log names the sensor, reading, and configured bounds. | |
| 5. Restore the approved limits and let the dummy sensor settle. | The bar and PMON status return to healthy on the next valid snapshot. | |

## Suite 2 — PMON Config-tab controls and persistence

**Description:** Exercise every Config-tab control and validate that invalid
operator input cannot create an unsafe or misleading configuration.

**Initial conditions:** Common initial conditions apply. Back up the PMON
configuration file and record the displayed settings for all rows.

### PMON-2.1 — Enable and disable every sensor

**Description:** Verify each checkbox applies immediately, persists, and changes only its own channel.

**Initial conditions:** Begin with enabled channels healthy; retain the default disabled state of Unassigned until its turn.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. For each row, toggle Enabled off and observe Main, Machine Status, and Messages. | The selected row immediately shows `OFF`, is removed from Environment Pass, clears its active warning rate-limit state, and logs `<PMON> <sensor> sensor disabled.` No other row changes. | |
| 2. Toggle the same row on and wait for a fresh poll. | The row shows `---` until fresh data arrives, then its current reading; it again affects Environment Pass and logs an enabled event. | |
| 3. Repeat steps 1–2 for all six rows, restoring the approved final enable states. | Every row independently exhibits the specified behavior and the final persisted state matches the approved configuration. | |

### PMON-2.2 — Valid limits, bar scaling, and restart persistence

**Description:** Verify a successful Set action changes the intended behavior and survives restart.

**Initial conditions:** Choose one enabled sensor and a finite set of valid limits with warning min < warning max and bar min < bar max.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Enter valid warning and bar limits for the selected row; select Set. | The row immediately uses the entered limits, logs an updated-configuration event, and saves one well-formed configuration record. | |
| 2. Confirm the scale endpoints, bar color, and warning behavior against the new limits. | The displayed scale and color match the new limits. | |
| 3. Quit normally, relaunch, and open Config and Main. | The four values, bar scale, enable state, and warning behavior match the saved settings. | |
| 4. Restore the approved limits using Set. | The approved limits are active and persisted. | |

### PMON-2.3 — Invalid numeric input rejection

**Description:** Ensure malformed values cannot partially update a sensor or be persisted.

**Initial conditions:** Choose one row and record its four current values and Main-tab rendering.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Enter one invalid value: blank, text, whitespace-only text, `NaN`, `Infinity`, `-Infinity`, or a boolean-like string; select Set. | An Invalid PMON Configuration dialog and a row-specific warning identify that all limits must be valid finite numbers. | |
| 2. Dismiss the dialog and inspect the row and saved JSON. | All four active limits, bar rendering, Environment Pass, and saved configuration remain unchanged; no partial update occurs. | |
| 3. Repeat steps 1–2 for every listed invalid value. | Each invalid value is rejected identically; no visual change occurs beyond the error dialog. | |
| 4. Restore the original entry text if necessary. | N/A. | |

### PMON-2.4 — Invalid range relationships

**Description:** Verify equal or reversed endpoints are rejected independently for warning and bar ranges.

**Initial conditions:** Choose one row and retain a copy of its valid configuration.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Set warning min equal to warning max; select Set. | The warning-range validation error is shown; active configuration and JSON remain intact. | |
| 2. Set warning min greater than warning max; select Set. | The warning-range validation error is shown; active configuration and JSON remain intact. | |
| 3. Restore warning limits, then repeat steps 1–2 for bar min and bar max. | The bar-range validation error is shown for both attempts; active configuration and JSON remain intact. | |
| 4. Restore the saved valid configuration. | The approved configuration is active and persisted. | |

### PMON-2.5 — Display range distinct from warning range

**Description:** Verify clipping does not hide an in-range/out-of-range safety condition.

**Initial conditions:** Select an enabled sensor with a stable reading `T`.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Set a valid bar range entirely below `T` while retaining warning bounds that contain `T`; select Set. | The value remains numerically visible, clips at the upper bar end, and remains green. | |
| 2. Set a valid bar range entirely above `T`; select Set. | The value remains numerically visible, clips at the lower bar end, and remains green. | |
| 3. Set warning bounds to exclude `T` while retaining a bar range containing `T`. | The bar is orange and Environment Pass is false even though the bar scale contains the value. | |
| 4. Restore approved settings. | The approved scale and warning behavior return. | |

### PMON-2.6 — Rapid and conflicting Config-tab actions

**Description:** Find stale-entry, race, and misleading success-message failures during normal operator use.

**Initial conditions:** One chosen enabled sensor is stable; record its original state.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Rapidly alternate its checkbox off/on several times, allowing UI events to complete. | The final checkbox state is the only persisted state; the UI remains responsive. | |
| 2. Edit limits, switch to Main without selecting Set, then return to Config. | Unsaved edits do not affect Main or JSON. | |
| 3. Select Set repeatedly with the same valid values while polling continues. | The last successful Set state persists; no duplicate polling loops, bars, or contradictory logs are created. | |
| 4. Restore the original state and limits. | The approved configuration is active and persisted. | |

## Suite 3 — Disabled-channel behavior

**Description:** Confirm that disabling a channel is explicit and scoped; it
must not conceal failures from an enabled channel or misrepresent the physical
state as a valid temperature.

**Initial conditions:** Common initial conditions apply. Keep a backup of the
PMON configuration and note current Machine Status.

### PMON-3.1 — Disabled channel with a physical sensor fault

**Description:** Verify that a deliberately disabled channel is excluded from the Environment Pass decision and error-noise policy.

**Initial conditions:** Select one non-spare channel, disable it in Config, and confirm `OFF` before manipulating its sensor.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Remove the selected sensor from its DP16. | The disabled row remains `OFF`; no visual changes occur in healthy enabled rows. | |
| 2. Wait longer than five failed poll cycles and the normal PMON disconnected-log interval. | The disabled unit produces no repeated per-unit poll, status, first-valid, or recovery noise. | |
| 3. Inspect healthy enabled rows, Environment Pass, Machine Status, and logs. | Healthy enabled rows and Environment Pass remain healthy. | |
| 4. Reconnect the sensor, allow it to stabilize, and re-enable the row. | The row must obtain a fresh valid reading before it contributes to Environment Pass. | |

### PMON-3.2 — All channels disabled while PMON is unavailable

**Description:** Test the edge case where configuration deliberately excludes every physical channel.

**Initial conditions:** With hardware healthy, disable all six rows and confirm all show `OFF`.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Remove PMON power or its RS-485 cable. | Every row remains explicitly `OFF`; no stale numeric values appear. | |
| 2. Wait through reconnect attempts. | No visual changes occur; no enabled channel exists to present a connection state. | |
| 3. Verify Environment Pass, Machine Status, and logs. | Environment Pass is treated as `True` | |
| 4. Restore hardware, then restore the approved enable configuration. | The approved enable states and healthy readings return. | |

### PMON-3.3 — Re-enable a channel during an outage

**Description:** Verify an enabled channel cannot inherit an old healthy state during a PMON outage.

**Initial conditions:** One channel is disabled, PMON communication is deliberately unavailable, and all other test setup conditions are safe.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Enable the disabled row while communication remains unavailable. | The row changes from `OFF` to `---`, not to a stale number or `ERR` without a corresponding device fault. | |
| 2. Observe the row and Machine Status through the failure threshold. | Environment Pass is false and PMON Temperatures OK is not green. | |
| 3. Restore communication and wait for a valid reading. | Recovery updates the row and status exactly once per state transition. | |
| 4. Restore the original enable state. | The approved enable state is active and persisted. | |

## Suite 4 — Physical PMON and sensor fault injection

**Description:** Exercise each attainable physical user action and prove that
loss, degradation, reconnect, and value trustworthiness are visible.

**Initial conditions:** Common initial conditions apply. Record baseline values,
time, and the current log position before each fault. Restore the setup fully
between cases.

### PMON-4.1 — Remove and restore PMON power

**Description:** Test total controller power loss after healthy operation.

**Initial conditions:** At least one enabled channel has a recent valid reading; all sensor connectors remain connected.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Remove PMON power while the dashboard is polling. | Existing values may be held only during retry; no row is newly shown as healthy. | |
| 2. Observe values and logs through five failed poll cycles and at least one reconnect interval. | Enabled rows become `---`, Environment Pass is false, PMON Temperatures OK is not green, and logs show degraded/disconnected progression plus a rate-limited PMON device-disconnected error without per-poll flooding. | |
| 3. Restore power without restarting the dashboard. | The driver begins automatic reconnect attempts. | |
| 4. Wait for all enabled units to report valid readings. | Readings become current and a reconnect/recovery log is emitted. | |

### PMON-4.2 — Remove and restore the PMON RS-485 cable

**Description:** Distinguish loss of the RS-485 path from a UI failure while the DP16 units remain powered.

**Initial conditions:** Confirm DP16 front panels stay powered after the cable is removed.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Remove the PMON-side RS-485 cable during healthy polling. | Existing values may be held only during retry; no row is newly shown as healthy. | |
| 2. Observe the dashboard through the disconnect threshold. | Enabled rows become `---`, Environment Pass is false, and logs identify no response/PMON disconnection rather than sensor overtemperature. | |
| 3. Confirm DP16 local displays remain powered if applicable. | Local displays may remain valid; this does not change the dashboard's disconnected state. | |
| 4. Reconnect the cable and observe automatic recovery. | Live readings return without a dashboard restart. | |

### PMON-4.3 — Remove and restore the laptop USB/RS-485 adapter

**Description:** Test serial-port disappearance, not merely loss of Modbus replies.

**Initial conditions:** Record the adapter's Windows COM number and confirm the DP16 chain remains powered.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Unplug the USB/RS-485 adapter from the testing laptop while polling. | Serial loss does not freeze or crash the dashboard. | |
| 2. Observe UI, Machine Status, and logs until disconnected. | Enabled rows become `---`, Environment Pass is false, and logs describe a serial/port or PMON-disconnected failure at a rate-limited cadence. | |
| 3. Reinsert the adapter; note whether Windows assigns the same COM number. | The assigned COM number is recorded. | |
| 4. Restart the computer, launch the dashboard. | Dashboard can read from PMON after restart. | |

### PMON-4.4 — Remove and restore one DP16 sensor

**Description:** Verify the specified sensor-fault sequence for one channel while the remaining units remain healthy.

**Initial conditions:** For Solenoid 1, Solenoid 2, or enabled Unassigned, connect an approved dummy sensor and establish a valid reading near 20 C. For Chamber Top, Chamber Bot, and Air temp, retain their installed RTDs and verify each has a valid baseline reading. Do not disturb DP16 power or the RS-485 chain.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. On Solenoid 1, Solenoid 2, or enabled Unassigned, confirm that the connected dummy sensor shows a stable value near 20 C. | The selected row has a current numeric value. | |
| 2. Remove the dummy sensor from its DP16 input. | The selected row changes to `ERR` while the DP16 reports the sensor fault. | |
| 3. Observe the selected row, DP16 front-panel indication/status, Machine Status, and logs through the disconnect threshold. | The selected row changes from `ERR` to `---` when the driver marks the channel disconnected. Other rows remain current and healthy; Environment Pass is false. Logs identify the unit and transition without calling the fault a healthy temperature. | |
| 4. Reconnect the dummy sensor, allow it to stabilize near 20 C, then pinch it toward 30 C. | The row returns to a current value, follows the dummy-sensor temperature change, and emits one recovery event. | |
| 5. Repeat steps 1–4 for the remaining Solenoid and enabled Unassigned channel. | Every tested dummy-capable channel follows the specified `ERR`, `---`, and recovery behavior. | |
| 6. For each RTD channel—Chamber Top, Chamber Bot, and Air temp—verify the installed RTD has a valid baseline reading, then unplug that RTD. | The corresponding RTD row changes to `ERR` while its DP16 reports the sensor fault. | |
| 7. Observe the unplugged RTD row through the disconnect threshold. | The RTD row changes from `ERR` to `---`; other rows remain current and healthy, Environment Pass is false, and logs identify the correct unit. | |
| 8. Reconnect the RTD and wait for its stable reading. | The correct RTD row returns to a current value and emits one recovery event. | |
| 9. Repeat steps 6–8 for the other two RTD channels. | Chamber Top, Chamber Bot, and Air temp each exhibit the specified fault and recovery sequence. | |

## Suite 5 — Startup and configuration-file resilience

**Description:** Test startup states and deliberate configuration loss or
corruption. These cases must be run on copies or after making verified backups.

**Initial conditions:** Dashboard is closed. Back up both PMON and COM-port
configuration files outside `usr/usr_data`.

### PMON-5.1 — Missing PMON configuration file

**Description:** Verify default creation and a safe first-run state.

**Initial conditions:** `process_monitor_config.json` has been backed up and removed; hardware is healthy.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Start the dashboard using the known PMON COM port. | The dashboard starts without an exception and logs that no PMON configuration was found. | |
| 2. Open Config and inspect all rows. | All named sensors have finite valid limits, and Unassigned alone is disabled by default. | |
| 3. Inspect the recreated JSON and Messages. | A valid default PMON configuration file was created. | |
| 4. Quit and restart once. | The created file loads without another creation message. | |
| 5. Restore the backed-up file. | The approved configuration is restored. | |

### PMON-5.2 — Corrupt, incomplete, and semantically invalid PMON configuration

**Description:** Verify normalization does not accept unsafe or nonsensical JSON.

**Initial conditions:** Prepare separate test copies containing: malformed JSON; a non-object root; missing sensors; unknown disabled sensor names; non-list disabled sensors; non-numeric/boolean/NaN/infinite values; and equal/reversed warning or display bounds.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Install one test file at a time as `process_monitor_config.json` while the dashboard is closed. | N/A. | |
| 2. Start the dashboard and inspect Config, Main, Machine Status, and Messages. | Startup remains operational; logs identify loading/validation errors. Invalid or absent data falls back only to documented defaults, while known valid fields are retained where applicable. | |
| 3. Verify the on-disk normalized result where loading succeeds. | Unknown disabled names are ignored, ranges are finite and correctly ordered, and no invalid values reach a bar calculation or Environment Pass. Normalized files are rewritten only when the load path supports saving. | |
| 4. Close the dashboard and proceed to the next test file. | N/A. | |
| 5. Restore the approved file at the end. | The approved configuration is restored. | |

### PMON-5.3 — PMON config removed or made unwritable during use

**Description:** Verify a runtime file problem cannot silently misrepresent a saved setting.

**Initial conditions:** Start with a valid loaded PMON configuration. Use a controlled test copy/location or file permissions that can be restored.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. While the dashboard is open, remove the PMON config file. | Active settings do not change. | |
| 2. Change one valid row setting with Set. | The save recreates a valid PMON configuration file. | |
| 3. Make the target config location unwritable, change a second valid setting or checkbox, and attempt to save. | The session change remains visible only for that session, a save-failed dialog/warning is shown, and no success log claims persistence. | |
| 4. Inspect Main, dialog, logs, and disk contents. | The dashboard continues polling safely; disk contents retain the last successful saved configuration. | |
| 5. Restore permissions and configuration. | The approved configuration is restored. | |

### PMON-5.4 — Missing, corrupt, blank, dummy, and wrong PMON COM selection at startup

**Description:** Verify startup cannot confuse a configured-but-unusable port with a healthy PMON.

**Initial conditions:** Dashboard is closed. Prepare COM-port file variants or use the startup selector to choose each state.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Test a missing and malformed `com_ports.json`; use the startup dialog to select a valid PMON port. | Missing/corrupt COM configuration is logged and the startup dialog remains usable. | |
| 2. Test ProcessMonitors left blank and choose the offered dummy assignment. | The dashboard does not crash or create apparently healthy readings; enabled rows show fault/disconnected presentation and Environment Pass is false. | |
| 3. Test a dummy port and an available but wrong real COM port. | The log names the initialization/serial connection failure and selected-port context; no healthy reading is shown. | |
| 4. Return to the known valid port and start normally. | A valid selection restores normal startup. | |

### PMON-5.5 — Hardware unavailable during startup

**Description:** Verify startup behavior differs cleanly from a later outage but remains fail-safe.

**Initial conditions:** Use the known real PMON COM assignment. Run one launch with PMON power removed, one with PMON RS-485 removed, and one with the USB adapter absent.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. For one unavailable state, launch the dashboard and wait beyond the connection failure threshold. | Startup completes and remains responsive. | |
| 2. Inspect enabled rows, Environment Pass, Machine Status, and logs. | Enabled rows do not show a valid or stale temperature, Environment Pass is false, PMON Temperatures OK is not green, and logs distinguish no COM port/serial-open failure from no responding DP16 units where observable. | |
| 3. Restore the physical connection while the dashboard remains open and wait for recovery. | Recovery is automatic whenever the same configured port returns. | |
| 4. Repeat steps 1–3 from a clean restart for each remaining unavailable state. | Each unavailable state has the specified fail-safe startup behavior. | |

## Suite 6 — COM-port selection, live changes, and hot-plug behavior

**Description:** Verify that exposed COM-port UI actions either reconfigure
PMON safely or state clearly that a restart is required. A generic success log
must never mask an unchanged PMON connection.

**Initial conditions:** Common initial conditions apply. Record the active PMON
COM port, then make a second available test port or a safe wrong-port selection available.

### PMON-6.1 — Startup COM-port selector actions

**Description:** Test selection, validation prompt, cancellation, and persistence at the startup selector.

**Initial conditions:** Dashboard is closed; the PMON adapter is connected and visible to Windows.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Open the startup COM-port selector, select the real PMON port, and submit. | The ProcessMonitors selection is saved and the dashboard starts with that port. | |
| 2. On a new launch, leave ProcessMonitors blank and decline the dummy-port prompt. | The selector remains open. | |
| 3. Choose a port and submit. | The dashboard starts using the selected port. | |
| 4. Open the selector again and close/cancel without submitting. | A partially configured dashboard does not start and the last saved configuration is not overwritten. | |
| 5. Reopen the selector. | The last submitted selection is offered. | |

## Suite 7 — Logging, status semantics, and log export

**Description:** Verify that the operator-visible log is actionable, bounded,
and consistent with Main, Config, and Machine Status.

**Initial conditions:** Common initial conditions apply. Clear or mark the log
start and use a log level that records PMON verbose messages when needed.

### PMON-7.1 — State-transition logs and rate limiting

**Description:** Validate the log sequence for normal, degraded, disconnected, and recovered states.

**Initial conditions:** One enabled sensor is healthy and a controlled sustained communication fault can be induced.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Record a normal connection/first-valid-reading baseline. | PMON messages carry the PMON tag and show a connection summary and valid-reading state. | |
| 2. Create a sustained PMON RS-485 interruption and observe beyond the rate-limit interval. | Logs reflect degradation, threshold disconnection, and periodic device-disconnected state; there is no contradictory "connected" or "healthy" message while enabled rows are `---`. | |
| 3. Restore the cable and observe complete recovery. | Logs show recovery/reconnect consistent with current live values. | |
| 4. Count repeated identical events and compare event times with the configured intervals. | Repeated identical errors are rate-limited; different units/error families are not incorrectly suppressed. | |

### PMON-7.2 — Semantic consistency across sensor, communication, and configuration failures

**Description:** Ensure logs identify the failure class and do not mislead an operator about data validity.

**Initial conditions:** Prepare one example each of sensor removal, RS-485 removal, USB adapter removal, invalid Config entry, and an out-of-warning-range reading.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Remove a dummy sensor from Solenoid 1, Solenoid 2, or enabled Unassigned and observe its fault sequence. | The row is `ERR` then `---`; the log identifies a sensor/unit fault rather than a healthy temperature. | |
| 2. Unplug one RTD from Chamber Top, Chamber Bot, or Air temp and observe its fault sequence. | The corresponding RTD row is `ERR` then `---`; the log identifies the correct sensor/unit fault. | |
| 3. Remove the PMON RS-485 cable or USB adapter and observe the fault sequence. | Transport/port loss is logged as loss of communication, not as an overtemperature. | |
| 4. Enter an invalid Config value and select Set. | The log names the configuration defect and does not claim an update. | |
| 5. Use a dummy sensor on Solenoid 1 or Solenoid 2 and limits to create an out-of-warning-range but valid reading. | The log names its sensor, value, and bounds. | |
| 6. Compare Main row text/color, Environment Pass, Machine Status, and log entries for every fault. | In every enabled invalid/faulted state, Environment Pass is false and the three surfaces tell the same story. | |
| 7. Restore the baseline after each fault. | The approved configuration and healthy readings return. | |

### PMON-7.3 — Log export and value-field hygiene

**Description:** Verify that an operator can preserve evidence and that removed data is not retained as a current temperature.

**Initial conditions:** Generate one normal reading and one disconnected state; ensure the Messages pane is visible.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Use Ctrl+S or the log-export UI to export the current log. | Export completes without interrupting polling. | |
| 2. Open the export and check PMON entries, timestamps, levels, and tag. | The file preserves PMON events in chronological order with enough context to diagnose unit, port, and configuration state. | |
| 3. Trigger a PMON loss, wait for cleared/disconnected values, export again, and compare. | No stale temperature is represented as a current logger value; the exported record reflects the disconnected state. | |
| 4. Restore communication and export if recovery evidence is needed. | The exported record shows the subsequent recovery. | |

## Suite 8 — Shutdown, restart, and interaction stress

**Description:** Test cancellation of PMON updates and serial shutdown under
normal and adverse timing, then verify that the next session starts cleanly.

**Initial conditions:** Common initial conditions apply. Record the active COM
port and ensure the test operator can observe whether it is released on exit.

### PMON-8.1 — Normal quit and clean relaunch

**Description:** Verify a normal dashboard exit stops PMON cleanly.

**Initial conditions:** PMON is healthy and polling.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Quit using the window close control and confirm the Quit dialog. | The Quit dialog is displayed. | |
| 2. Choose Cancel and confirm polling continues. | The dashboard and PMON polling remain intact. | |
| 3. Quit again and choose OK. | Scheduled updates are cancelled, PMON is disconnected, and the dashboard does not hang. | |
| 4. Immediately relaunch the dashboard with the same PMON COM port. | The port opens normally, one polling thread starts, and one normal connection sequence is logged. | |

### PMON-8.2 — Quit during a blocked/reconnecting PMON transaction

**Description:** Detect shutdown deadlocks and leaked serial handles during a fault.

**Initial conditions:** PMON is healthy and polling

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Trigger a physical fault by turning off PMON power. | The PMON fault/reconnect sequence begins. | |
| 2. While reconnect attempts or a poll are active, confirm quit and time the shutdown. | The dashboard closes in bounded time without a UI deadlock. | |
| 3. Inspect final logs. | If the worker cannot stop within its timeout, a clear warning identifies that condition; it does not silently hang. | |
| 4. Restore hardware and relaunch. | The next launch polls the restored device normally, without duplicate workers or old queued logs. | |

### PMON-8.3 — UI navigation and resize while PMON state changes

**Description:** Find redraw and scheduling errors that occur when an operator changes view during live updates and faults.

**Initial conditions:** PMON is polling and healthy.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Repeatedly switch between Main and Config while temperature values update. | Tabs remain usable; no visual changes occur other than normal value updates. | |
| 2. Resize, maximize/restore, and enter/exit fullscreen while a bar is updating. | Each row retains its title, scale labels, current text, and correct fault/color state after redraw. | |
| 3. Change a valid range, then induce and recover a brief PMON interruption. | No Tk exceptions, duplicate canvases, duplicated scheduled updates, or frozen log/UI behavior occurs. | |
| 4. Check all rows, tabs, logs, and Machine Status after stabilization. | The stable display and Environment Pass agree with the latest valid data. | |

## Completion Criteria

The PMON subsystem passes when every enabled channel is correctly mapped; all
operator actions are validated and persistent; all specified physical faults
become visibly unsafe without stale healthy data; recovery and shutdown are
bounded; and Main, Machine Status, and logs tell the same story. Any divergence
between those three surfaces, any unannounced live-COM limitation, or any fault
that remains healthy/ambiguous is a defect to record with the exported log,
configuration files, physical action time, and observed UI transition time.
