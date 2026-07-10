# SIC / Interlocks Subsystem Test Plan

## Purpose

Verify that the dashboard safely and accurately represents the Safety
Interlock Controller (SIC, OMRON G9SP) without presenting a lost,
incomplete, or contradictory status as healthy. This plan exercises every
operator-accessible SIC action: the display-only Interlocks strip, startup and
live COM-port configuration, logging/export, dashboard lifecycle controls,
and the specified physical safety, serial, and power manipulations.

The plan is deliberately fault-oriented. A fault passes only when it is
unambiguous in the Interlocks strip, Machine Status, and SIC-tagged log, and
when recovery cannot reuse stale healthy data.

## Safety Considerations

- Use a designated SIC test fixture. Keep beam, cathode, high-voltage, and
  stored-energy systems off, locked out, and independently verified safe.
  The dashboard is monitoring equipment; it is not the safety control.
- Do not use the acutal enclosure door for these tests, use the spare door lock key to simulate closing the door
- Do not use the actual High Voltage Subpanel for this test. The High Voltage Subpanel Monitor Arduino can be plugged into a regular outlet to simulate the HV subpanel turning on.
- **The HV Subpanel Enable Key should be set to `OFF`. DO NOT SET TO `REMOTE MODE` OR TO `ON` AT ANY POINT DURING THESE TESTS**
- Do not use VTRX at any point during thes tests, the VTRX override should be used to simulate VTRX interlocks.
- Before each case, record the current time, indicator colors, Machine Status,
  active COM number, and log position. One person changes hardware; another
  observes the dashboard and records transition times.
- Back up `usr/usr_data/com_ports.json` before file cases. Restore the
  approved file, all sensor connections, power, serial cables, E-stops, door
  hardware, and the HVolt monitor after every suite.
- Do not unplug/reconnect hardware under unsafe voltage, in a hazardous area,
  or contrary to safety procedures.

## Outline

1. Baseline display, mapping, and read-only UI behavior
2. Physical safety inputs, door protection, G9 output, and HVolt monitor
3. SIC power and serial transport failures
4. Startup, COM-port UI, and configuration-file resilience
5. Machine Status, logging, semantic consistency, and export
6. Shutdown, restart, and interaction stress

Unless a case states otherwise, begin with the safety conditions above; the
approved SIC test fixture powered; SIC serial and laptop adapter connected;
the known-good Interlocks COM port selected; both E-stops released; the door
closed and locked; all installed interlock inputs healthy; VTRX override installed; OTRX override installed; G9SP Output off;
and the high-voltage subpanel in its `OFF` state. Keep the Messages
pane visible and retain verbose SIC logs in the log export. Hold downstream
machine stages not-ready unless a case explicitly tests their interaction, so
their state cannot mask a SIC result.

For timing checks, the panel normally polls every 500 ms. A no-response
transaction can take longer; use a three-second observation window for an
initial display transition, then continue through at least 15 seconds for
backoff, rate-limit, and recovery checks.

## Suite 1 - Baseline display, mapping, and read-only UI behavior

**Description:** Establish a known-good reference, prove that the status strip
is display-only, and verify it remains intelligible during normal dashboard
interaction.

**Initial conditions:** Common initial conditions apply. The SIC test fixture
must provide a fresh normal response and all first 11 safety inputs must be
healthy. Keep G9SP Output and HVolt off initially.

### SIC-1.1 - Normal startup and indicator baseline

**Description:** Verify the intended normal input mapping, initial safe output
state, and Machine Status integration.

**Initial conditions:** Confirm the Interlocks COM port is available and
selected in the startup COM-port dialog. Record the test fixture's physical
input/output state before launch.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Start the dashboard, submit the known SIC COM port, and wait for two complete polls. | Dashboard remains responsive; the log records SIC driver initialization and receives a current SIC snapshot. | |
| 2. Inspect the Interlocks strip. | `E-STOP Int`, `E-STOP Ext`, `Door`, `Vacuum Power`, `Vacuum Pressure`, `High Oil`, `Low Oil`, `Water`, and `All Interlocks` are green. `G9SP Output` and `HVolt ON` are red while their controlled states are off. | |
| 3. Compare the strip with the SIC fixture input LEDs/status display. | Every named dashboard indicator agrees with the physical/controller state; no label is swapped or duplicated visually. | |
| 4. Inspect Machine Status with its preceding PMON and vacuum prerequisites healthy. | `All Safety Interlocks Pass` is green. `High Voltage Subpanel On` is not green while HVolt is off; it is gray unless another later-ready stage makes it behind-red. | |
| 5. Inspect Messages and the logger value fields. | SIC entries carry the `SIC` tag. Current safety input/output status fields agree with the same snapshot; no communication, unit-status, or terminal-error message is present. | |

### SIC-1.2 - Display-only controls, navigation, and layout under live polling

**Description:** Confirm there is no hidden software command path in the SIC
strip and normal dashboard actions cannot freeze, duplicate, or obscure it.

**Initial conditions:** SIC-1.1 is passing and polling.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Repeatedly resize the dashboard and adjust adjacent panes while polling continues. | All eleven labels and circles remain visible, paired correctly, and readable; no duplicate strip, Tk exception, or stalled updates. | |
| 2. Use F1, F11, Escape, and Ctrl+M, then return to the normal window state. | Shortcut help and window-state changes work without changing SIC status, serial ownership, or polling. | |
| 3. Switch focus among Main Control, Messages, and the SIC strip while a fixture input changes healthy-to-fault-to-healthy. | The affected SIC indicator updates once per actual transition and remains visible; no view change hides a fault or creates duplicate polling/log streams. | |
| 4. Use Ctrl+S to export the current log. | Export completes without interrupting SIC polling; the file contains chronological SIC events and current test evidence. | |

## Suite 2 - Physical safety inputs, door protection, G9 output, and HVolt monitor

**Description:** Exercise the physical actions that can change SIC data or
terminal status. Test each action separately first, then verify that combined
faults and recovery order cannot create a false pass.

**Initial conditions:** Common initial conditions apply. Use only the approved
test fixture connections. Before every case, restore a fresh normal SIC
snapshot and clear/mark the log.

### SIC-2.1 - Remove and restore sensor connections

**Description:** Verify interlock functionality for normally non-triggerable interlocks

**Initial conditions:** G9SP Output is off. The fixture exposes the individual
SIC input connections. For each row, remove only the named connection, wait
for a fresh fault snapshot, then reconnect it and wait for recovery before the
next row.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Remove and restore the VTRX Override connector from SIC. | Only `Vacuum Power`, `Vacuum Pressure`, and `All Interlocks` change to red for the fault; they recover only after a fresh healthy input. | |
| 2. Remove and restore the OTRX Override connector from SIC. | Only `High Oil`, `Low Oil`, and `All Interlocks` change to red for the fault; they recover only after a fresh healthy input. | |
| 3. Remove and restore the Water sensor connection. | Only `Water` and `All Interlocks` change to red for the fault; they recover only after a fresh healthy input. | |

### SIC-2.2 - Internal and external E-stop operation and reset

**Description:** Verify both physical E-stops are fail-safe, correctly named,
and do not automatically re-energize the safety output after release.

**Initial conditions:** All input indicators are green, G9SP Output is off

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Press the internal/chassis E-stop. | `E-STOP Int` and `All Interlocks` become red within the observation window. Machine Status `All Safety Interlocks Pass` is not green, and no stale all-safe indication remains. | |
| 2. Observe the controller output and SIC logs while the internal E-stop remains pressed. | Any previously asserted G9SP safety output de-energizes on the fixture. Logs identify the internal E-stop fault/transition and do not claim the system is ready. | |
| 3. Release the internal E-stop and perform only the approved physical reset; do not press the G9 Output button. | Input and `All Interlocks` may return green only after a fresh healthy snapshot. `G9SP Output` remains red until separately enabled; there is no unexpected restart. | |
| 4. Repeat steps 1-3 with the external/peripheral E-stop in the enclosure. | The same fail-safe and non-auto-restart behavior occurs, but the fault is named `E-STOP Ext`. | |

### SIC-2.3 - Door-open, dummy-key, and door-unlock protection

**Description:** Prove that the two Door channels require both a true closed
door and a locked condition, and that the dummy key cannot defeat an open-door
fault.

**Initial conditions:** Door circuit and lock circuit are healthy; G9SP Output is off. Enclosure door is open. SIC door unlock switch is set to unlock.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. With the door open, use the approved dummy door-lock key to simulate the closed condition. | `Door` remains red because the independent open-door channel is still unsafe. The key must not create `All Interlocks` green. | |
| 2. Flip the door-unlock switch to locked while the dummy door key is in the door-lock sensor | `Door` and `All Interlocks` turn green. | |
| 3. Return the unlock switch to unlocked and complete the approved reset. | The Door indication is only green only when both Door channels are healthy; the Door indication turns red once the door is unlocked. | |

### SIC-2.4 - G9SP Output button and HVolt-monitor state transitions

**Description:** Verify output-demand, HVolt feedback, and the special Machine
Status forced-red condition. This is a fixture-only test because it can change
a real safety output.

**Initial conditions:** All first 11 inputs are green. The HVolt subpanel monitor Arduino is initially disconnected/off and
the G9SP Output button is not latched.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Confirm the initial off state. | `All Interlocks` is green, while `HVolt ON` and `G9SP Output` are red. | |
| 2. Press the G9 Output button for at least 0.5s while the HVolt monitor still reports off. | `G9SP Output` turns green only if the SIC output and associated status are both on. `HVolt ON` remains red, `All Interlocks` stays green, and Machine Status `High Voltage Subpanel On` is forced red. | |
| 3. Plug in the High Voltage Subpanel Monitor Arduino to produce its known ON feedback state. | `HVolt ON` turns green only after the SIC reports its implemented ON pattern (normal status with data bit low). Machine Status HVolt becomes green when its other display rules allow it. | |
| 4. Unplug the monitor Arduino. | `HVolt ON` turns red on the next current SIC snapshot. The Machine Status HVolt stage is forced red; `All Interlocks` remains green. | |
| 5. Restore the HV monitor, then reset the G9 Output button by cycling an E-Stop. | The monitor and output indicators follow their actual feedback independently. With output no longer asserted, `G9SP Output` is red and no residual output-demand/ready message remains. | |
| 6. Compare the physical SIC output and HVolt monitor state with the dashboard after each transition. | The dashboard never shows `G9SP Output` or `HVolt ON` green before the corresponding physical/controller feedback is present. | |

### SIC-2.5 - Multiple faults and out-of-order recovery

**Description:** Detect aggregation errors, stale green state, and accidental
output re-enable when two safety conditions change near the same poll.

**Initial conditions:** Restore the baseline. G9SP Output is off.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Create a Door fault and press the external E-stop before the next dashboard poll. | Both named detail indicators are red, `All Interlocks` is red, and no intermediate all-green state is displayed after the first fault is observed. | |
| 2. Restore only the Door condition while the external E-stop remains active. | `Door` may recover, but `E-STOP Ext` and `All Interlocks` remain red. | |
| 3. Release/reset only the external E-stop. | `All Interlocks` returns green only after both physical conditions are healthy and a fresh valid snapshot is received. | |
| 4. With G9SP Output asserted on the isolated fixture, trigger either E-stop and then restore it. | The output is de-energized by the safety action and remains non-green until the separate, approved output-enable action is performed. | |

## Suite 3 - SIC power and serial transport failures

**Description:** Distinguish a genuine interlock fault from an unavailable SIC
or transport. Communication failure must fail safe, clear diagnostic fields,
avoid log floods, and recover only from fresh controller data.

**Initial conditions:** SIC-1.1 is passing. Mark the log, record the Windows
COM number and adapter serial identity, and leave G9SP Output off.

### SIC-3.1 - Remove and restore SIC power

**Description:** Test total controller power loss while the serial path remains
connected.

**Initial conditions:** Confirm the laptop serial adapter remains physically
connected when SIC power is removed.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Remove power from the SIC while the dashboard is polling. | Within the observation window, every SIC indicator becomes red and `hvolt_on`/Machine Status cannot remain green from the previous snapshot. The dashboard remains responsive. | |
| 2. Observe for at least 15 seconds. | Logs identify no-response/communication loss rather than asserting that every physical sensor independently failed. SIC diagnostic status fields are cleared, retry/error messages are bounded, and the UI does not become sluggish. | |
| 3. Restore SIC power without restarting the dashboard. | With the original serial session still valid, a fresh normal response restores the baseline indicators; recovery is logged once per state transition. | |
| 4. Compare timestamps of repeated retry/error messages. | If no usable data is available, the effective UI retry interval backs off toward its documented maximum rather than continuously reporting a healthy 500-ms poll; a sustained failure must not overflow/drop logger events. | |

### SIC-3.2 - Remove and restore the SIC-side serial cable

**Description:** Test loss of SIC responses while the laptop COM port may stay
open.

**Initial conditions:** SIC and adapter remain powered; only the serial cable
at the SIC is accessible.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Remove the serial cable from the SIC during healthy polling. | No indicator remains green solely from cached data. The strip fails red and Machine Status interlocks is not green without crashing the dashboard. | |
| 2. Inspect messages and status fields through the sustained outage. | The log describes a G9 response/transport failure, not a known Door, E-stop, or fluid-sensor activation. Safety input/output flag fields are cleared rather than retained as current. | |
| 3. Reconnect the same SIC serial cable without changing the COM selection. | The existing serial session accepts fresh valid frames and the prior healthy indicators recover without a dashboard restart. | |

### SIC-3.3 - Remove the laptop serial adapter and test COM reassignment

**Description:** Test actual Windows-port disappearance, the required I/O
expander restart procedure, and the invalid-COM failure path.

**Initial conditions:** Record the adapter's current COM number and serial
number. Confirm the approved adapter is identified by the dashboard's SIC
port-monitoring configuration.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Remove the serial adapter cable from the testing laptop. | The dashboard does not freeze. All SIC indicators become red, SIC flag fields clear, and logs identify serial-port/device loss; no old safe snapshot remains visible. | |
| 2. Wait through the disconnected observation window. | The Interlocks panel and Machine Status remain fail-safe. Retry/error events are bounded; no false "driver initialized" or healthy-SIC message appears without a valid response. | |
| 3. Reinsert the approved adapter, then restart the testing computer before reopening the dashboard. | The I/O expander restart requirement is met. No fresh SIC polling is expected before the computer restart; after restart, Windows exposes the adapter for a new dashboard session. | |
| 4. Relaunch the dashboard and record whether Windows assigns the original COM number. | Fresh normal SIC data restores the baseline only after the computer restart and dashboard relaunch. No pre-restart snapshot is treated as current. | |
| 5. If the adapter receives a different COM number, relaunch using the previously saved port. | Startup with the unavailable saved port fails safe: all SIC indicators are red and the log names the attempted port/open failure. It must not silently use another device. | |
| 6. Select the newly assigned correct COM port through the startup selector and launch again. | A fresh valid SIC response restores the baseline and the selected port is saved for the next startup. | |

### SIC-3.4 - Wrong, busy, and non-SIC serial endpoint

**Description:** Ensure an open serial handle is not confused with a healthy
SIC connection.

**Initial conditions:** Make a safe wrong real COM endpoint available, and if
possible an endpoint already held by another test application. Keep the real
SIC disconnected from those endpoints.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Start the dashboard with a wrong but open COM port assigned to Interlocks. | The strip stays red until a valid, checksum-correct SIC response arrives. A successful serial open alone is not displayed or logged as a healthy interlock state. | |
| 2. Repeat with a busy/permission-denied port. | Startup remains responsive and fail-safe; the log identifies port/permission failure without stale values. | |
| 3. Return to the real SIC COM port while the dashboard is open using an approved reconfiguration path. | The panel obtains a fresh SIC snapshot before any indicator turns green. If live reconfiguration is unsupported, the UI must say so clearly and require restart rather than reporting an unapplied success. | |

## Suite 4 - Startup, COM-port UI, and configuration-file resilience

**Description:** Exercise every SIC-relevant configuration action available to
the operator and deliberate startup-file manipulation. A bad configuration
must lead to an editable startup choice or a clear failure, never a partially
healthy SIC display.

**Initial conditions:** Dashboard is closed. Back up
`usr/usr_data/com_ports.json` outside the workspace configuration path and
record the known-good Interlocks COM port.

### SIC-4.1 - Startup COM-port selector actions

**Description:** Verify valid selection, blank selection, dummy selection,
decline/cancel paths, and persistence for the Interlocks entry.

**Initial conditions:** The real SIC adapter is connected and appears in the
startup selector's port list.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Select the known real Interlocks COM port and submit the startup dialog. | The selection is written to `com_ports.json`; dashboard startup uses that port and obtains a valid SIC snapshot. | |
| 2. On a fresh launch, leave Interlocks blank and decline the dummy-port prompt. | The selector remains open, the dashboard does not start, and the previously saved selection is not overwritten. | |
| 3. Leave Interlocks blank again and accept the dummy-port prompt. | The selected dummy value is saved and startup completes fail-safe: SIC indicators remain red and the log records an open/connection failure rather than healthy data. | |
| 4. Reopen startup configuration, select the real SIC port, and close the dialog with its window close control without submitting. | No dashboard session starts and the last submitted configuration remains on disk. | |
| 5. Start once more with the real SIC port submitted. | The saved real selection is offered on the next launch and normal SIC operation returns. | |

### SIC-4.2 - Missing, corrupt, incomplete, and unwritable COM configuration

**Description:** Verify the configuration loader and selector cope with file
loss and hostile-but-attainable user edits.

**Initial conditions:** Dashboard is closed. Use a separate backup for each
variant: missing file; malformed JSON; valid JSON with a non-object root;
object with no `Interlocks` key; `Interlocks` blank/null/non-string; unknown
COM value; and an unwritable `usr/usr_data` target directory.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Install one variant as `usr/usr_data/com_ports.json`. | N/A. | |
| 2. Launch the application and inspect the startup selector and bootstrap log. | Missing, malformed, incomplete, and semantically invalid configuration is reported clearly and falls back to an editable selector. The application must not crash because the JSON root lacks dictionary behavior or a key is missing. | |
| 3. Submit the known real Interlocks port after each recoverable variant. | The dashboard starts with current SIC data; it does not retain a stale/dummy/intermediate value from the bad file. | |
| 4. For the unwritable variant, submit a changed port selection and inspect the log and disk. | A save failure is reported; the dashboard may use the submitted in-memory choice for that session, but it must not claim persistence or overwrite the last good file. | |
| 5. Close the dashboard and repeat for every listed variant. | Each variant is isolated; no malformed value leaks into a later case. | |
| 6. Restore the approved backed-up file and permissions. | The approved configuration and normal startup behavior are restored. | |

### SIC-4.3 - SIC unavailable during startup

**Description:** Distinguish no hardware, no SIC response, and wrong configured
port at first launch.

**Initial conditions:** Use the known real Interlocks port in the saved/startup
configuration. Run each listed physical state from a clean dashboard launch.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Launch with SIC power removed. | Startup completes and remains responsive; all SIC indicators are red, Machine Status is not interlock-ready, and the log identifies unavailable/no-response SIC data. | |
| 2. Launch with the SIC serial cable removed but the adapter present. | The same fail-safe display occurs, with response/transport failure distinguished from an asserted physical input where observable. | |
| 3. Launch with the laptop serial adapter absent. | The log identifies the configured port open failure and all SIC indicators are red; no stale status fields remain. | |
| 4. Restore the missing hardware while the dashboard stays open. | Recognized adapter hot-plug or a supported explicit COM update yields a fresh snapshot and recovery. If neither can reconnect, the UI/log gives a clear reconfigure/restart requirement rather than implying automatic recovery. | |
| 5. Relaunch after hardware is fully restored. | The known real port starts normally with no lingering red latch, locked port, old worker, or queued pre-fault status. | |

## Suite 5 - Machine Status, logging, semantic consistency, and export

**Description:** Verify that the three operator-facing sources of truth - SIC
strip, Machine Status, and logs/value fields - tell the same story and retain
enough evidence to diagnose an unsafe condition.

**Initial conditions:** Common initial conditions apply. Enable/retain verbose
file logging, mark the log start, and make PMON/vacuum prerequisites healthy
when observing Machine Status colors.

### SIC-5.1 - Indicator, Machine Status, and output-state semantics

**Description:** Check nuanced conditions that are easy to misrepresent: an
input failure, HVolt feedback alone, and G9 output without HVolt feedback.

**Initial conditions:** Begin from SIC-1.1 baseline with G9SP Output and HVolt
off.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Create one ordinary first-11 input fault, such as E-Stop or Door. | Its named detail indicator and `All Interlocks` are red; `All Safety Interlocks Pass` is not green. HVolt/G9 output colors do not change unless their physical states changed. | |
| 2. Restore that input and verify a fresh healthy snapshot. | The named input and `All Interlocks` recover green; the log records one coherent recovery rather than retaining the old fault as current. | |
| 3. With all first 11 inputs healthy, leave HVolt feedback off and G9SP Output off. | `All Interlocks` remains green, `HVolt ON` remains red, and the Machine Status HVolt stage is not green but is not forced-red by an output demand. | |
| 4. Assert G9SP Output while HVolt feedback remains off. | `G9SP Output` green plus `HVolt ON` red forces the Machine Status HVolt stage red. `All Interlocks` remains green because output/HVolt are outside its first-11 aggregate. | |
| 5. Restore the approved off state. | The strip, Machine Status, and logs return to the same semantic baseline with no residual ready/output indication. | |

### SIC-5.2 - Failure classification, rate limiting, and logger-field hygiene

**Description:** Detect log floods and incorrect attribution of transport loss
as physical sensor activation.

**Initial conditions:** Establish one normal snapshot, then prepare one Door or
Water input fault and one SIC serial-cable no-response fault.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Trigger the ordinary input fault and inspect all SIC messages. | Transition log identifies the named interlock; any terminal error includes the controller-reported cause. It is not reported as a serial failure. | |
| 2. Restore the input and confirm recovery, then remove the SIC serial cable. | Transport loss is logged as response/serial communication failure. The panel fails red, but logs do not falsely claim that all individual physical sensors were independently actuated. | |
| 3. Keep the transport fault active for at least 15 seconds. | Repeated errors are rate-limited/backed off, the UI remains responsive, and no `Dropped ... queued G9 logger event(s)` warning occurs. Diagnostic input/output fields remain cleared rather than stale. | |
| 4. Reconnect the cable and wait for one complete healthy snapshot. | Recovery is logged after valid data returns; fields repopulate from that fresh frame and do not show a mixture of old/new snapshots. | |
| 5. Compare timestamps, colors, and text across every transition. | No log says connected, initialized-as-healthy, all-safe, or output-on at a time inconsistent with the displayed current SIC data. | |

### SIC-5.3 - Log export evidence and no-data recovery

**Description:** Verify saved logs preserve enough information to reconstruct a
physical test and that stale values are not exported as current after loss.

**Initial conditions:** Generate one normal baseline, one terminal/input fault,
one serial/power loss, and one recovery in the current session.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Export the log with Ctrl+S while polling is active. | Export completes without stopping the UI or SIC worker. | |
| 2. Inspect the exported log chronologically. | Entries include timestamps, levels, `SIC` tag, port/response failure context, named interlock transitions, and recovery evidence sufficient to correlate with the physical action record. | |
| 3. Inspect exported/current safety flag values after the communication-loss portion. | Cleared/unavailable status is not represented as current healthy input/output flags or as a fresh safe SIC frame. | |
| 4. Export again after recovery and compare with the first export. | The later export contains the subsequent fresh recovery and does not erase or rewrite the preceding fault evidence. | |

## Suite 6 - Shutdown, restart, and interaction stress

**Description:** Verify scheduled SIC updates, the background communication
thread, and the serial handle are released safely in normal and adverse timing.

**Initial conditions:** Record the active Interlocks COM port. Confirm the
operator can observe Windows serial ownership or immediately relaunch the
dashboard to test it.

### SIC-6.1 - Normal quit, cancellation, and relaunch

**Description:** Test all SIC-relevant dashboard quit controls and clean serial
release.

**Initial conditions:** SIC is healthy and polling.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Invoke Ctrl+Q and choose Cancel in the Quit dialog. | The dashboard stays open and SIC polling continues normally. | |
| 2. Invoke Ctrl+W and choose OK in the Quit dialog. | The dashboard closes in bounded time; scheduled SIC updates are cancelled, the SIC worker is stopped, and the serial port is released. | |
| 3. Immediately relaunch using the same known SIC COM port. | The port opens normally, one SIC worker/polling stream starts, and the strip obtains a fresh normal snapshot. | |
| 4. Repeat the quit confirmation using the window close control. | The same cleanup path is used; no leaked port, stale callback, or duplicate SIC logs occur on the next launch. | |

### SIC-6.2 - Quit during a fault, reconfiguration, and rapid physical changes

**Description:** Find deadlocks, thread races, and serial-handle leaks that
only occur when the operator exits during an active failure.

**Initial conditions:** SIC is healthy and polling. Keep all energy systems
isolated.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Remove SIC power, wait until failure logging begins. | The expected fail-safe state appears and the dashboard remains interactive. | |
| 2. Confirm quit while the poll  worker is timing out/retrying and measure shutdown time. | Shutdown is bounded and does not deadlock. If the worker cannot stop within its timeout, a clear warning is logged rather than a silent hang. | |
| 3. Restore hardware and immediately relaunch. | The restored SIC can be opened; no old queued error/healthy event changes the new session's strip, and exactly one fresh recovery/baseline sequence appears. | |
| 4. During a final healthy session, rapidly perform two safe serial disconnect/reconnects while resizing/navigating the dashboard. | The final displayed state matches the final physical connection; no Tk error, duplicate update callback, event-queue drop, or false green state occurs. | |

## Completion Criteria

The SIC subsystem passes when every testable physical input is correctly
routed; an open, E-stop, door, output, HVolt, power, serial, wrong-port, and
startup/configuration fault is visibly fail-safe; and only a fresh valid SIC
frame restores green. The dashboard must preserve the distinction between a
physical interlock action and unavailable/corrupt communication. Machine
Status, SIC indicators, logger fields, and exported logs must agree.

Record a defect for any stale green indicator, unexpected output re-enable,
unlabeled/incorrectly labeled fault, transport outage reported as a physical
sensor action, log flood/dropped event, incomplete config crash, undisclosed
live-COM limitation, serial-handle leak, or disagreement among the three
operator-facing status surfaces.
