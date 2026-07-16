# Beam Pulse (BCON) Subsystem Test Plan

## Test Plan Information

| Field | Value |
| --- | --- |
| Name of tester(s): | |
| Date/Time of Test Plan Start: | |
| Dashboard Version/Branch: | |
| Dashboard Commit Hash: | |
| Notes: | |

## Test Results

| Field | Value |
| --- | --- |
| Date/Time of Test Plan End: | |
| Summary of Results: | |
| Test Plan Edits or Comments: | |

## Purpose

Verify the dashboard's Beam Pulse subsystem and its three-channel BCON device
through operator-visible behavior, physical fault injection, startup
manipulation, and log review. The plan covers the Beam Pulse panel and the Beam
Pulse controls hosted in Main Control: `ARM BEAMS`, `E-STOP: BEAMS & CCS`,
Beam A/B/C software interlocks, Beam A/B/C output buttons,
`Activate Enabled Beams`, and `Disable All Beams`. It also covers the Beam
Pulse panel's `Toggle PVX A/B/C Enable` one-shot controls and the physical
enable LED on each independently powered PVX pulser. Those three LEDs are the
only source of truth for the PVX latched enable states.
For the mixed-purpose E-stop, assess only confirmed BCON all-off and Beam Pulse
disarm behavior.

This is a solo Beam Pulse plan. It does not test Main Control coordination with
Cathode Heating, Vacuum, Beam Energy, Machine Status, or any other subsystem.
The physical Arm Beams signal from the Knob Box is in scope because it is
BCON's hardware interlock.

The plan is deliberately fault-oriented. A passing system makes command
acceptance, rejection, communication loss, and physical safety state obvious;
never presents stale or merely queued state as confirmed hardware state; never
replays a stale output command after a confirmed shutoff; and never restores
output after an interlock or watchdog trip without a fresh operator command.

The following behaviors are excluded. Keep all three settings disabled in Main Control Config for the
entire plan:

- `Disable CCS Output on BCON Disconnect`
- `Disable Beams if pressure exceeds 1e-05 mbar`
- `Do not activate Beams if Predicted Emission Current exceeds 6mA`

PVX independence from the VTRX/emission/CCS states above is exercised in
INTER-5.6 of `Inter_subsystem_test_plan.md`; those cross-subsystem settings stay
disabled everywhere else in this solo plan.

## Safety Considerations

- **Disconnect every BCON Output cable from every PVX pulser before testing.
  No BCON Output cable may be connected to a PVX pulser during any case.** The
  DB15 cables that carry PVX enable-toggle commands remain connected. Keep the
  PVX boxes independently powered only as required by the approved fixture and
  to observe their enable LEDs.
- **CCS must remain OFF at all times.**
- **No high-voltage supply may ever be set to
  Enable from the Knob Box.** 
- Install the Knob Box Logic Arduino Override from
  <https://github.com/uw-loci/knob-box/tree/test/logic-arduino-OVERRIDE> before
  testing. This override is required to produce the Arm Beams signal used by
  the BCON hardware interlock.
- The three excluded Main Control config settings default to enabled and cannot be persisted as
  disabled. After every launch, open Main Control > Config immediately and
  uncheck them.
- The HV subpanel should remain off at all times. During pre-connection setup, uncheck `Disable BCON logging when HV subpanel is off` after every launch.
- Record the physical PVX A/B/C enable LEDs independently before each case.
  Each successful PVX toggle must change only its matching physical LED. Each
  failed toggle must leave all three LEDs unchanged. The blue BCON A/B/C gate LEDs
  indicate gate-output level, and the LCD/registers report at most the brief
  PVX toggle-busy pulse; none is a substitute for the physical PVX enable LED.
- PVX toggles are completely independent of software arm, Main Control software
  interlocks, emission and VTRX guards, the physical Arm Beams interlock,
  output mode, Disable All, disarm, E-stop, watchdog state, and every other
  BCON function. The only unrelated prerequisites are a connected BCON and a
  valid channel A/B/C; the intentional per-channel 150 ms cooldown still
  applies. Actions other than an accepted PVX toggle must not change a PVX
  enable LED.
- Use pulse widths of at least 1000 ms when a person must verify an LED or LCD
  transition.
- Back up `usr/usr_data/com_ports.json`,
  `usr/usr_data/main_control_config.json`, pane-state data, and test configuration
  files before manipulating them. Restore approved files after each suite.
- After any rejected, interrupted, or race-condition command, issue a confirmed
  `Disable All Beams` while communication is healthy or power-cycle BCON. Do
  not continue until all blue output LEDs are off and the LCD shows every
  channel `OFF` with `O:0`.
- Before completing the plan, use the physical PVX LEDs and deliberate,
  connection-confirmed toggles to leave PVX A/B/C Disabled. BCON all-off,
  disarm, E-stop, disconnect, or power removal cannot establish that state.

## Outline

1. Safety baseline, normal startup, and UI inventory
2. Connection lifecycle and watchdog controls
3. Software arming, software interlocks, and PVX enable-toggle controls
4. Manual channel configuration, modes, and validation
5. Multi-channel activation, all-off, E-stop, and command races
6. Physical Arm Beams interlock and firmware safety recovery
7. BCON power, serial, adapter, and stale-connection failures
8. Startup, configuration-file, and COM-port resilience
9. Logging, acknowledgements, and semantic consistency
10. Shutdown, restart, and interaction stress
11. Complete operator flow with injected failure checkpoints

Unless a case states otherwise, begin with all Safety Considerations satisfied;
BCON production firmware installed; BCON powered; the BCON-side RS-485 cable
and laptop USB adapter connected; the correct `BeamPulse` COM port selected;
the physical Arm Beams switch ON; and BCON connected with its 1500 ms default
watchdog. Begin disarmed, with all three Main Control software interlocks
Disabled, all requested and active modes OFF, and all blue output LEDs dark.
Keep the three PVX DB15 toggle cables connected, every BCON Output cable
disconnected from every PVX pulser, the independently powered PVX enable LEDs visible, and record
their starting Enabled/Disabled states. Unless a case deliberately begins in a
different PVX state, establish all three as Disabled using their physical LEDs.
Confirm LCD row 0 reads `WDG:OK INT:OK`; rows 1-3 identify `CH A`, `CH B`, and
`CH C` and show `OFF`, `O:0`, and zero remaining pulses.

After every dashboard restart, complete the mandatory setting/log changes before
the BCON settle interval finishes and before any Beam Pulse action or fault
injection. Confirm file logging remains ON and CCS and every high-voltage supply
remain OFF. Record the dashboard and firmware revisions, original COM number,
action times, and session-log path.
Assertions involving Main Control are limited to its Beam Pulse buttons and
four Beam Pulse status/action lines; do not assess another subsystem's reaction.

## Suite 1 - Safety baseline, normal startup, and UI inventory

**Description:** Establish the isolated, logged, physically safe reference state
and identify every operator surface used in later cases.

**Initial conditions:** Common initial conditions apply. The dashboard is not
running at the start of BCON-1.1.

### BCON-1.1 - Mandatory isolation, logging, and normal auto-connect

**Description:** Prove that the test fixture is isolated and that startup yields
one coherent BCON connection and safety snapshot.

**Initial conditions:** BCON is powered with the physical Arm Beams switch ON.
The correct COM port is saved or available in the startup selector.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Physically trace A/B/C. Verify every BCON Output cable is disconnected from the PVX pulsers and each matching DB15 enable-toggle cable is connected. | All three BCON gate outputs are visibly isolated, while the three low-voltage toggle paths map A/B/C one-to-one. | |
| 2. With BCON power OFF, power the three PVX boxes, record each physical enable LED, and observe them for at least 5 s. Then power BCON. | Every PVX LED is visible and stable without BCON power, proving that PVX state/power is independent. Powering BCON does not itself change any PVX LED. | |
| 3. Verify CCS is OFF, every high-voltage supply is disabled, and no high-voltage supply can be enabled by the Knob Box during this plan. | CCS and all high-voltage supplies remain OFF; the test can proceed without energized beam hardware. | |
| 4. Verify the Knob Box Logic Arduino Override from the URL in Safety Considerations is installed, then place the physical Arm Beams switch ON. | The override supplies the active-high Arm Beams interlock signal; no high-voltage enable signal is asserted. | |
| 5. Start the dashboard, select the correct `BeamPulse` COM port, and submit the startup dialog. | The dashboard opens and starts one BCON auto-connect attempt. No Beam Pulse initialization exception occurs. | |
| 6. Before the 4.5 s settle interval ends, open Main Control > Config and uncheck the three excluded settings and both BCON/Knob Box HV-off log-suppression settings. | All five check controls are unchecked before BCON is declared connected. The excluded guards remain inactive, and BCON/Knob Box messages are not suppressed while the HV subpanel is off. | |
| 7. Set the file-log level to `VERBOSE` and verify the Messages recording control indicates ON with a green indicator. | File logging is active and can capture all BCON and Knob Box levels for the rest of the case. | |
| 8. Wait for the 4.5 s firmware settle interval and the first complete register poll. | The BCON indicator becomes green, the button reads `Disconnect`, and the safety label reads `Interlock: ok \| Watchdog: ok`. | |
| 9. Compare the Beam Pulse cards with the BCON LCD, blue gate LEDs, and recorded PVX LEDs. | A/B/C map one-to-one; each card shows `Status: OFF \| O:0` and `Remaining: 0`; the LCD shows all channels OFF; all blue LEDs are dark; startup has not changed any PVX LED. | |
| 10. Inspect Main Control and the session log. | Beam Pulse is disarmed; all Beam A/B/C software-interlock buttons say Disabled; Beam A/B/C output buttons are disabled and OFF; the log identifies the selected port and one successful connection cycle without a Beam Pulse/BCON-tagged error or duplicate poll worker. | |

### BCON-1.2 - Beam Pulse and Main Control operator-surface inventory

**Description:** Verify that all in-scope controls are present, correctly gated,
and usable without layout corruption.

**Initial conditions:** BCON-1.1 passed and the system remains connected,
disarmed, and idle.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Scroll through Beam Pulse and open `Manual Control`. | The connection indicator, interlock/watchdog label, watchdog entry and Set button, and three complete channel cards remain visible and aligned. | |
| 2. Inspect the default A/B/C manual values. | Each mode is `PULSE`, duration is `100`, count is `1`, and count is disabled for single-pulse mode. | |
| 3. Inspect Main Control > Main and Beam Pulse > Manual Control. | `ARM BEAMS`, `E-STOP: BEAMS & CCS`, Beam A/B/C software interlocks and output buttons, `Activate Enabled Beams`, `Disable All Beams`, four Beam Pulse status/action lines, and `Toggle PVX A/B/C Enable` are present. | |
| 4. Verify the initial button gating.  | `Disable All Beams`, E-stop, `ARM BEAMS`, and PVX toggle controls are usable; Main Control software interlocks, Beam A/B/C output buttons, and Activate are disabled as designed. | |
| 5. Switch tabs, scroll, resize, maximize/restore, and return to the baseline view. | Controls remain associated with the correct channel; no duplicate widgets, clipped safety state, Tk exception, or state change occurs. | |

## Suite 2 - Connection lifecycle and watchdog controls

**Description:** Exercise every Beam Pulse connection/watchdog action and prove
that requested, applied, rejected, and disconnected states are distinguishable.

**Initial conditions:** Common initial conditions apply. Preserve the log from
each case and restore the watchdog to 1500 ms before leaving the suite. Record
the physical PVX LED vector before and after every connect, disconnect,
watchdog, and power action; it must remain unchanged because none is a PVX
toggle request.

### BCON-2.1 - Intentional disconnect and reconnect while idle

**Description:** Verify confirmed all-off, local-state clearing, watchdog expiry,
and clean reconnection for an operator-requested disconnect.

**Initial conditions:** BCON is connected, disarmed, and idle.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Record the physical PVX LED vector, then select `Disconnect` in Beam Pulse. | Pending writes are cleared, firmware confirms `ALL_OFF`, the serial port closes, the indicator turns red, and the button reads `Reconnect`. All three PVX LEDs retain their recorded states. | |
| 2. Inspect Beam Pulse and Main Control immediately. | Software arm and local output state are false; all Main Control software interlocks are Disabled. | |
| 3. Observe BCON without reconnecting for longer than 1500 ms. | BCON remains powered; all blue gate LEDs stay dark; LCD changes to `WDG:NO` while `INT:OK` remains. | |
| 4. Inspect the log. | The log distinguishes firmware `ALL_OFF` confirmation, intentional user disconnect, and driver disconnect. | |
| 5. Select `Reconnect` once. | The button is disabled and shows `Connecting...` during the attempt; one connection worker opens the configured port. | |
| 6. Wait through settle and one complete poll. | The indicator returns green, LCD returns to `WDG:OK INT:OK`, all channels remain OFF, no prior mode or queued command replays, and reconnect has not changed a PVX LED. | |

### BCON-2.2 - Reconnect with a valid COM port but no responding BCON

**Description:** Distinguish a present serial adapter from a responding BCON
firmware endpoint.

**Initial conditions:** Intentionally disconnect through the UI. Leave the
laptop USB adapter connected so its COM port still exists.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Remove the BCON-side RJ45 serial cable and select `Reconnect`. | The COM port opens, the button shows the connecting state, and the driver waits through its firmware settle interval. | |
| 2. Wait for the connection attempt to finish. | The register validation read fails, the indicator remains red, the button returns to `Reconnect`, and the dashboard remains responsive. | |
| 3. Inspect the log and BCON. | The log reports a connection/test-read failure rather than `BCON connected`; BCON remains powered, its blue gate LEDs remain off, and the LCD eventually shows `WDG:NO`. | |
| 4. Restore the BCON-side serial cable and select `Reconnect`. | One clean connection succeeds. | |
| 5. Repeat steps 1-4 with BCON power removed instead of the BCON-side serial cable while the independently powered PVX LEDs remain visible. | The dashboard again reports no responding firmware, does not hang, and reconnects cleanly only after power is restored. The physical PVX LED vector is unchanged through BCON power loss and recovery. | |

### BCON-2.3 - Watchdog entry syntax and firmware limits

**Description:** Partition the watchdog entry and detect false success messages
or an out-of-range value reaching firmware.

**Initial conditions:** BCON is connected and idle with watchdog 1500 ms.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Clear the watchdog entry and select `Set`. | No write occurs and no visual state changes. The applied watchdog remains 1500 ms. | |
| 2. Enter `abc` and select `Set`. | An `Invalid` dialog says the value must be an integer; a warning is logged; no register write occurs. | |
| 3. Enter `-1`, `0`, and `49` one at a time and select `Set` after each. | Each value is rejected as outside 50-60000 ms; no `Wrote R0=<value>` follows, the applied value remains unchanged, and no message falsely claims it was applied. | |
| 4. Enter `60001` and a much larger integer, selecting `Set` after each. | Each is rejected with the same clear range semantics; BCON remains connected with its prior watchdog. | |
| 5. Enter `50` and select `Set`; wait for the queued write result without starting output. | `R0=50` is written. Any resulting watchdog-safe transitions are reported as hardware state, not hidden by a generic Set success. | |
| 6. Enter `60000` and select `Set`; wait for the write result. | `R0=60000` is written and the log distinguishes request/queue/write from a firmware-confirmed command. | |
| 7. Enter `1500`, select `Set`, and wait for the write. | `R0=1500` is written and the normal heartbeat/poll state stabilizes at `WDG:OK`. | |

### BCON-2.4 - Watchdog Set while disconnected and reconnect readback

**Description:** Detect a stale entry, a queued-but-never-applied setting, and a
misleading success message across disconnect/reconnect.

**Initial conditions:** BCON is connected and idle at 1500 ms.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Enter `5000`, select `Set`, and wait for `Wrote R0=5000`. | The requested value reaches firmware; the entry and applied value agree. | |
| 2. Intentionally disconnect, enter `7000`, and select `Set`. | No hardware write can occur. The dashboard reports that the value was not applied while disconnected and does not claim success. | |
| 3. Reconnect and wait for defaults plus a full poll. | Reconnect clears the disconnected write queue and reapplies the dashboard default 1500 ms; `7000` is never replayed. | |
| 4. Compare the watchdog entry with the effective reconnect value and logs. | The UI either updates to 1500 or clearly identifies the entry as an unapplied request. A stale value must not be presented as the active firmware watchdog. | |
| 5. Enter `4000`, select Set, and immediately turn off BCON power before the queued result is known. | The log says either `R0=4000` was written before loss or the write failed; it never reports the value applied without evidence. | |
| 6. Restore power and reconnect. | Reconnect clears any unresolved Set request and reapplies 1500 ms; `4000` is not replayed. | |
| 7. Enter `1500`, select Set, and confirm the normal LCD state. | The final state is `WDG:OK`, all channels OFF, and no stale watchdog request remains queued. | |

### BCON-2.5 - Sub-cadence watchdog while an output is active

**Description:** Verify the physical safety response when a valid watchdog is
shorter than the heartbeat cadence.

**Initial conditions:** Every BCON Output cable is disconnected from every PVX pulser. BCON is connected at the
1500 ms watchdog, software armed, Beam A's software interlock enabled, and
Channel A visibly running DC.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Confirm blue A LED is solid ON and LCD/UI report A DC before changing the watchdog. | The active-output baseline is fresh and unambiguous. | |
| 2. Set watchdog to `50` ms and watch the blue A LED and LCD continuously. | Firmware accepts `R0=50`, then the sub-cadence watchdog forces active A low, clears its active mode, and prevents automatic reassertion. | |
| 3. Compare the LCD, Beam Pulse safety label/card, Main Control lines, and logs for several host cycles. | Every surface eventually reflects OFF. Any watchdog expiry missed because polling itself feeds the watchdog, oscillating safety label, stale green output, or missing shutoff record is captured as a defect. | |
| 4. Select `Disable All Beams`, set watchdog to `1500`, and wait for confirmation. | A confirmed all-off clears any latent gate request; normal `WDG:OK` operation returns and all blue gate LEDs remain dark. The physical PVX LEDs are unchanged by watchdog expiry and Disable All. | |

### BCON-2.6 - Intentional disconnect while outputs are active

**Description:** Verify that the healthy-link Disconnect action obtains confirmed
all-off before closing the serial port.

**Initial conditions:** Every BCON Output cable is disconnected from every PVX pulser. BCON is connected and
armed at the 1500 ms watchdog; A DC and B long PULSE_TRAIN are active.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Select `Disconnect` while A/B are active. | The driver confirms `ALL_OFF` before closing; blue A/B LEDs go dark, local output state clears, software arm resets, and the indicator turns red. | |
| 2. Inspect the action/event lines in Main Control and the log. | They distinguish confirmed all-off from serial close and intentional disconnect; no stale ON or unconfirmed shutdown wording remains. | |
| 3. Reconnect and wait for fresh registers. | A/B/C gate outputs remain OFF, no pre-disconnect command replays, and the physical PVX LED vector remains unchanged throughout disconnect/reconnect. | |

## Suite 3 - Software arming, software interlocks, and PVX enable-toggle controls

**Description:** Verify the software permission gate, Main Control's local
activation interlocks, and Beam Pulse's separate PVX one-shot controls without
confusing any of them with the physical interlock or gate-output LEDs.

**Initial conditions:** Common initial conditions apply.

### BCON-3.1 - Software arm and confirmed disarm semantics

**Description:** Show that arming changes permission only and that disarming is
gated on confirmed BCON all-off.

**Initial conditions:** BCON is connected, physical Arm Beams is ON, and the
system is disarmed and idle.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Select the Arm Beams toggle. | The toggle changes to its armed/ON image or `BEAMS ARMED` text; Beam A/B/C software interlocks and Activate become usable; Beam A/B/C output buttons remain disabled until their matching software interlock is enabled. | |
| 2. Inspect BCON blue gate LEDs/LCD and the Beam Pulse cards. | Arming alone sends no hardware arm, mode, PVX toggle, or output command. All channels remain OFF and all blue gate LEDs remain dark. | |
| 3. Inspect the action line and log. | They identify software-only arming and do not claim that a channel, pulser, CCS, or high-voltage supply was enabled. | |
| 4. Record the physical PVX LEDs, then select the armed/ON toggle again. | Disarm obtains a confirmed `ALL_OFF`, clears output and Main Control software-interlock state, then changes the toggle to its unarmed/OFF image or text. No physical PVX LED changes. | |
| 5. Repeat arm/disarm while already idle. | The operation is idempotent, produces coherent acknowledgements, and leaves no blue gate LED, mode, software interlock, or queued write active. PVX LEDs remain at their recorded states. | |
| 6. Arm, enable Beam A's software interlock without starting output, remove the BCON-side serial cable, and request disarm before auto-disconnect. | The unconfirmed `ALL_OFF` makes disarm fail. Before auto-disconnect, software arm and the deferred software-interlock state are not falsely cleared as if shutdown were confirmed; the action reports failure/uncertainty. | |
| 7. Restore the serial cable, reconnect if necessary, wait for a fresh all-off snapshot, and request disarm again. | Fresh polling reconciles hardware but does not retroactively mark the failed disarm successful. The new confirmed disarm clears software arm/interlocks. No failed request replays and no PVX LED changes. | |

### BCON-3.2 - Arm request while BCON is disconnected

**Description:** Verify that an open, responding BCON connection is required for
software arming.

**Initial conditions:** Intentionally disconnect BCON through Beam Pulse.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Select the Arm Beams toggle. | Arming fails; the toggle remains visually unarmed/OFF (or reads `ARM BEAMS`); Main Control software interlocks, Beam output buttons, and Activate remain disabled. | |
| 2. Inspect the action line and log. | Both state `Failed to arm beams` and identify the serial port/device connection reason; no success follows. | |
| 3. Reconnect BCON and wait for a fresh healthy snapshot. | Reconnection alone does not arm, select, or activate any channel. | |
| 4. Select the Arm Beams toggle. | Software arming now succeeds exactly once and the control becomes visually armed/ON. | |
| 5. Disarm and confirm all-off before ending the case. | The system returns to the common idle state. | |

### BCON-3.3 - Independent Beam A/B/C software-interlock mapping

**Description:** Verify each dashboard-only software interlock, Beam-button
gating, and the absence of a false gate-output indication.

**Initial conditions:** BCON is connected, armed, idle, and all Main Control
software interlocks are Disabled.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Select `Beam A Disabled`. | Only Beam A's software interlock becomes Enabled and only its output button becomes usable; B and C remain disabled. No BCON write occurs, no blue gate LED turns on, and LCD modes remain OFF. | |
| 2. Select `Beam B Disabled`. | Only Beam B additionally becomes Enabled and usable; A is unchanged and C remains disabled. | |
| 3. Select `Beam C Disabled`. | Beam C additionally becomes Enabled and all three output buttons are usable; no output mode starts. | |
| 4. Select `Beam B Enabled`. | Only Beam B's software interlock and output button return to Disabled; A and C remain enabled. | |
| 5. Disarm. | Confirmed all-off clears all three software interlocks, disables all Beam output buttons, and leaves all blue gate LEDs/LCD rows OFF. | |

### BCON-3.4 - Disabling a channel while it is active

**Description:** Verify that disabling an active channel also commands its gate
mode OFF and cannot affect another channel.

**Initial conditions:** BCON is connected and armed. Beam A and Beam B software
interlocks are enabled; A is configured DC, B is configured for a long pulse,
and C's software interlock is disabled.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Turn Beam A ON in DC and wait through its firmware result and eligible confirming poll. Then turn Beam B ON with a pulse of at least 5000 ms and wait for its confirmation. | The one-pending-operation rule admits the actions sequentially. Blue gate LEDs A and B turn on; the corresponding LCD/UI rows report the correct independent modes. | |
| 2. Select `Beam A Enabled` to disable its software interlock. | Main Control queues A OFF and leaves the interlock visibly Enabled until firmware acknowledgement and a later poll confirm mode OFF/output low. A's blue LED then goes dark while B continues without restart or interruption. | |
| 3. Inspect Main Control and Beam Pulse after the confirming poll. | Beam A's software interlock and output button are Disabled/OFF, Beam B remains Enabled, and B's remaining/output state agrees with hardware. | |
| 4. Disable Beam B's software interlock while its pulse is still active. | B transitions OFF before its interlock changes to Disabled; no later queued apply reactivates A or B. | |
| 5. Select `Disable All Beams` and disarm. | Confirmed all-off restores the common idle state. | |

### BCON-3.5 - Active software-interlock disable failure and recovery

**Description:** Prove that the local interlock is not cleared when its required
channel-OFF command cannot be confirmed.

**Initial conditions:** BCON is connected and armed. Beam A's software
interlock is Enabled and A is visibly running DC; B/C are OFF.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Record all three physical PVX LEDs, remove the BCON-side serial cable, and immediately select `Beam A Enabled` before auto-disconnect. | The A OFF request fails or times out. The software interlock remains visibly Enabled and the action is not described as confirmed OFF/Disabled. No PVX LED changes. | |
| 2. Observe the blue A gate LED through watchdog expiry. | A turns physically OFF from the firmware watchdog, not from the failed interlock-disable command. That physical transition does not retroactively complete the failed action. | |
| 3. Restore communication and obtain a fresh complete poll. | Hardware-derived A mode/output reconciles to OFF, but the old failure is not relabeled success and no stale command replays. | |
| 4. Select `Disable All Beams` on the healthy link and wait for the post-command all-off poll. | The new command reaches `Command Success` only after firmware execution and the later poll. Its confirmed completion clears all Main Control software interlocks. | |
| 5. Disarm and compare the PVX LED vector with step 1. | The common idle gate state returns and every physical PVX LED remains unchanged. | |

### BCON-3.6 - PVX physical enable-LED mapping and cooldown

**Description:** Verify that each accepted one-shot request changes exactly one
external PVX latch and that the physical LED, not BCON diagnostics, establishes
the resulting enable state.

**Initial conditions:** BCON is connected and idle. Software arming may remain
OFF because PVX toggle requests are not armed-gated. Use confirmed toggles to
establish physical PVX A/B/C LEDs as `[Disabled, Disabled, Disabled]`.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Record `[A, B, C]`, select `Toggle PVX A Enable` once, and observe all three physical PVX LEDs. | Exactly A changes Disabled -> Enabled; B/C remain Disabled. One immediate FC06 requests R13=1; R13 self-clears and R114 may show only the approximately 100 ms busy pulse. | |
| 2. Wait more than 150 ms and select A again. | Exactly A changes Enabled -> Disabled. The two physical observations, rather than request text, R13, R114, the LCD, or a blue BCON gate LED, prove the two successful latch transitions. | |
| 3. Repeat steps 1-2 for B and then C. | B maps only to R23/R124 and its physical LED; C maps only to R33/R134 and its physical LED. Each accepted click inverts exactly its matching LED, with no gate mode, software-interlock, or other PVX change. | |
| 4. From A Disabled, double-select A within 150 ms while watching its LED. | The first accepted click causes exactly one Disabled -> Enabled transition. The second local request is rejected by the per-channel cooldown with one ERROR log and causes no second LED transition or duplicate FC06. | |
| 5. Wait more than 150 ms and select A once. | A accepts a new request and changes Enabled -> Disabled exactly once, proving recovery after cooldown. | |
| 6. Confirm all three physical PVX LEDs are Disabled. | The case ends from LED-observed `[Disabled, Disabled, Disabled]`; BCON all-off is not used as evidence for this state. | |

### BCON-3.7 - PVX independence, failed attempts, and no replay

**Description:** Exercise accepted toggles across unrelated permission/safety
states, then inject definite transport failures and prove no latch change or
deferred replay occurs.

**Initial conditions:** Every BCON Output cable is disconnected from every PVX pulser and the three
DB15 toggle cables remain connected. BCON is serial-connected; the PVX boxes
are independently powered; all physical PVX LEDs are Disabled.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. While software disarmed, all Main Control software interlocks Disabled, and all gate modes OFF, toggle A; then wait more than 150 ms and toggle A back. | Both requests succeed and only the physical A LED inverts each time. Software arm/interlocks and gate modes remain unchanged. | |
| 2. Turn physical Arm Beams OFF, wait for `INT:NO`, and toggle B twice with more than 150 ms between clicks. | Both B requests still succeed and only B's physical LED changes each time. Firmware gate safety does not gate the PVX toggle path. | |
| 3. Restore Arm ON and all PVX LEDs Disabled. Select A, B, and C once each in rapid succession so the total A-to-C interval is under 150 ms. | All three requests are accepted because cooldown is per channel, not global; each matching physical LED changes exactly once. After more than 150 ms, three spaced requests restore all Disabled. | |
| 4. Arm and run A DC plus a long B PULSE_TRAIN. During active gate output, toggle PVX C Enabled then Disabled with more than 150 ms between clicks. Next, create a pending Main Control Beam action and quickly toggle PVX A before its post-command poll. | Accepted PVX toggles still change only their physical LEDs; active gate modes continue independently and the pending Main Control token/result is neither blocked, completed, nor replaced by the PVX action. | |
| 5. Confirm all gates OFF, set the watchdog to 50 ms, and where `WDG:NO` can be observed while transport remains connected, toggle PVX B twice with the required spacing; then restore 1500 ms. | Watchdog-safe gate state does not gate PVX. Each accepted immediate request changes only B's physical LED; any watchdog recovery caused by communication remains separate. If connected `WDG:NO` cannot be sustained because polling feeds it, record the fixture limitation and rely on BCON-2.5 for the measured transition. | |
| 6. Establish PVX vector `[Enabled, Disabled, Enabled]`, then run arm, software-interlock select/clear, `Disable All Beams`, confirmed disarm, E-stop, and a watchdog expiry in separate recorded iterations without pressing a PVX button. | None of those non-toggle actions changes any physical PVX LED; the vector remains `[Enabled, Disabled, Enabled]` throughout. Blue gate outputs may shut off independently. | |
| 7. Intentionally disconnect BCON in the UI and attempt A/B/C toggles separately. | Each attempt is rejected because no connected BCON exists. No FC06 is queued for later, all physical PVX LEDs remain `[Enabled, Disabled, Enabled]`, and failures name the connection condition. | |
| 8. Reconnect, remove the BCON-side serial cable during the stale-green window, and attempt one C toggle. | The immediate write fails or is explicitly uncertain; the physical LEDs determine what actually happened. A definite failed request changes no LED. If C changed despite a missing reply, record an indeterminate transport result and do not retry until its physical LED is observed. | |
| 9. Restore communication, record the LEDs, power BCON OFF, and attempt no dashboard action while observing the independently powered PVX boxes. Then power BCON and reconnect. | All three PVX LEDs remain visible and unchanged across BCON power loss/boot/reconnect. No prior failed toggle is replayed. | |
| 10. Use healthy, spaced, channel-specific toggles as needed to leave A/B/C physically Disabled. | Exactly the selected LEDs change and final state is `[Disabled, Disabled, Disabled]`. Neither `ALL_OFF` nor BCON power cycling is accepted as restoration evidence. | |

## Suite 4 - Manual channel configuration, modes, and validation

**Description:** Exercise every channel-card control, all supported modes, limit
boundaries, live locks, and one-to-one physical/UI mapping.

**Initial conditions:** Common initial conditions apply. Arm and enable only the
required Main Control software interlock for each case. Use `Disable All Beams`
between accepted boundary commands so a long valid pulse cannot carry into the
next step.

### BCON-4.1 - Mode-dependent widget state and input filtering

**Description:** Verify mode selection, editable fields, digit-only entry, and
preservation of the operator's next intended configuration.

**Initial conditions:** BCON is connected, disarmed, and idle.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. On Channel A select `OFF`, `DC`, `PULSE`, and `PULSE_TRAIN` in turn. | OFF/DC disable duration and count because they are ignored; PULSE enables duration, forces count to 1 and disables count; PULSE_TRAIN enables both fields. | |
| 2. Repeat the mode selections on Channels B and C. | B and C behave identically without changing A or each other. | |
| 3. In an enabled duration or count field, try typing and pasting letters, a minus sign, a plus sign, a decimal point, and whitespace. | Non-digit characters are rejected at entry; the prior valid digits remain unchanged. Empty text is allowed for later validation. | |
| 4. Enter a nondefault valid configuration, change to OFF, then return to its prior pulse mode. | The widgets remain coherent. No mode change sends a BCON command, and a retained value is not misrepresented as an active hardware setting. | |
| 5. Arm, enable Beam A's software interlock, configure A for a long DC or pulse, and select Beam A. | Live hardware status appears in `Status`/`Remaining` but does not overwrite the selected next-command mode or values. | |
| 6. Stop A, disable all, and disarm. | The intended configuration remains available after controls unlock; hardware status returns OFF and the common idle state is restored. | |

### BCON-4.2 - Pulse-duration validation boundaries

**Description:** Verify whole-millisecond limits before any partial command is
queued.

**Initial conditions:** BCON is connected and armed; Beam A's software
interlock is enabled; Channel A is in `PULSE` but not currently outputting; B
and C software interlocks are disabled and all outputs are OFF.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Clear A duration and select `Beam A OFF`. | An `Invalid Configuration` dialog says duration must be a whole number of ms; no blue BCON A gate LED, mode change, or write starts. | |
| 2. Enter `0` in duration and select Beam A. | The dialog says duration must be 1-60000 ms; no output command is queued. | |
| 3. Enter `1` in duration and select Beam A. | The command is accepted as one 1 ms pulse and completes safely; it may be too short to see, but register/log state returns OFF without an error. | |
| 4. Enter `60000` in duration, select Beam A, wait for firmware acceptance, then immediately select `Disable All Beams`. | The upper boundary is accepted; confirmed all-off terminates it and no stale 60 s pulse reappears. | |
| 5. Enter `60001` in duration and select Beam A. | The value is rejected before a BCON write; A remains OFF. | |
| 6. Enter a very large digit string and select Beam A. | The value is rejected without overflow, UI freeze, truncated hardware value, or partial write. | |
| 7. Restore duration `1000`, disable all, and disarm. | The system returns to a valid idle configuration. | |

### BCON-4.3 - Pulse-train count validation boundaries

**Description:** Verify the train-only lower bound, firmware upper bound, and
single-pulse count normalization.

**Initial conditions:** BCON is connected and armed; Beam A's software
interlock is enabled; A is set to `PULSE_TRAIN` mode with duration 100 ms, but
not actively outputting.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Clear count and select Beam A. | An invalid-configuration dialog requires a whole-number count; no output starts. | |
| 2. In Count, enter `0`, then `1`, selecting Beam A after each. | Each is rejected with `PULSE_TRAIN count must be 2-10000`; no partial parameter or mode write reaches BCON. | |
| 3. In Count, enter `2` and select Beam A. | A valid two-pulse train runs and returns OFF; remaining count does not increase. | |
| 4. Set duration `1`, count `10000`, select Beam A, wait for acceptance, then select `Disable All Beams`. | The upper count boundary is accepted; all-off stops it and prevents later reactivation. | |
| 5. Enter count `10001` and select Beam A. | The value is rejected before any BCON write. | |
| 6. Select `PULSE` mode after entering a different train count. | Count becomes 1 and is disabled; the next PULSE command uses exactly one pulse. | |
| 7. Select `OFF` and `DC` in turn. | Duration/count are ignored and normalized for the command; stale invalid train values cannot block an OFF or DC action. | |
| 8. Disable all and disarm. | The common idle state is restored. | |

### BCON-4.4 - OFF, DC, PULSE, and PULSE_TRAIN on A/B/C

**Description:** Prove mode timing and physical mapping on every channel using
visible pulse durations.

**Initial conditions:** BCON is connected and armed. Begin with all Main
Control software interlocks disabled and all modes OFF.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Enable only Beam A's software interlock, configure A as DC, and select Beam A. | Only blue A is solid on; LCD A reads `DC`, `O:1`, `R:0`; Beam Pulse A reads DC/O:1; Main Control A shows ON. B/C remain OFF. | |
| 2. Select Beam A again to turn it OFF. | Only A goes OFF; the blue A LED darkens and all A displays reconcile to OFF. | |
| 3. Configure A as PULSE, duration 1500 ms, and select Beam A. | Only A starts high, reports PULSE with remaining 1 when sampled, then automatically returns OFF after its high interval. | |
| 4. Configure A as PULSE_TRAIN, duration 1000 ms, count 3, and select Beam A. | Only A alternates 1 s high/1 s low; remaining falls 3 to 0 at falling edges; it finishes OFF and unlocks its card. | |
| 5. Disable Beam A's software interlock, enable Beam B's, configure B as DC, and select Beam B. | Only blue B is solid on and every B display reports DC; A/C remain OFF. | |
| 6. Select Beam B OFF, then run B as PULSE at 1500 ms. | Only B pulses once and automatically returns OFF. | |
| 7. Run B as PULSE_TRAIN at 1000 ms x 3. | Only B alternates, remaining falls to zero, and B finishes OFF. | |
| 8. Disable Beam B's software interlock, enable Beam C's, configure C as DC, and select Beam C. | Only blue C is solid on and every C display reports DC; A/B remain OFF. | |
| 9. Select Beam C OFF, then run C as PULSE at 1500 ms. | Only C pulses once and automatically returns OFF. | |
| 10. Run C as PULSE_TRAIN at 1000 ms x 3. | Only C alternates, remaining falls to zero, and C finishes OFF. | |
| 11. Compare status while a channel is DC or in a long train. | Its mode/duration/count widgets are locked while running; DC is treated as active even with remaining 0. | |
| 12. Wait for automatic completion or select the Beam button OFF. | The channel unlocks only after a fresh OFF status; no stale ON color or remaining count survives. | |
| 13. Disable all and disarm. | All channel outputs and software interlocks return to the common idle state. | |

### BCON-4.5 - Manual mode OFF selected from a Beam A/B/C button

**Description:** Detect contradictory `ON` wording or color when the selected
manual command is actually OFF.

**Initial conditions:** BCON is connected and armed; Beam A's software
interlock is enabled; A is physically OFF.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. In the Beam Pulse Manual Control Tab, select Mode `OFF` from the Channel A dropdown. Select `Beam A OFF` to turn Beam A ON | Firmware receives an OFF/apply request; blue A remains dark and A never represents active output. | |
| 2. Observe the Beam A button and status/action lines before and after the next poll. | They consistently say OFF. They do not turn green or say `successfully set to ON, OFF`, even temporarily. | |
| 3. Inspect the firmware acknowledgement and log. | The acknowledgement context identifies `Beam A OFF`; queued, executed, and live OFF state are not mislabeled as Beam ON. | |
| 4. Repeat with B and C. | Each channel has the same coherent OFF semantics and no cross-channel change. | |
| 5. Disable all and disarm. | The common idle state is restored. | |

## Suite 5 - Multi-channel activation, all-off, E-stop, and command races

**Description:** Verify filtering, synchronized starts, confirmation-gated
shutoff, and protection against stale queued writes.

**Initial conditions:** Common initial conditions apply. Every BCON Output cable is
disconnected from every PVX pulser; use 1000 ms or longer pulses for visual synchronization checks.

### BCON-5.1 - Activate Enabled Beams filtering and synchronized start

**Description:** Start a mixed configuration, prove disabled channels are
skipped, and compare simultaneous gate edges.

**Initial conditions:** BCON is armed and idle. Beam A and B software interlocks
are enabled and C is disabled. Configure A DC, B PULSE_TRAIN at 1000 ms x 2,
and leave C with an intentionally invalid train count of 1.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Select `Activate Enabled Beams`. | A and B are validated and staged; disabled C is skipped without its invalid config blocking the action. | |
| 2. Observe the first A/B gate edge. | Blue A and B rise together from the single apply; C remains dark. | |
| 3. Observe B through completion while A remains DC. | B alternates and finishes OFF; A stays solid ON; C remains OFF. LCD, cards, and Main Control lines agree. | |
| 4. Inspect action text and logs. | The sent configuration names only A and B, records firmware apply execution order, and does not claim C ran. | |
| 5. Select `Disable All Beams`. | A immediately goes OFF after confirmed all-off; no channel reactivates. | |
| 6. Enable only Beam C's software interlock, configure C DC, and select `Activate Enabled Beams`. | Only C starts; A/B remain OFF, proving the one-selected-channel path. | |
| 7. Disable all, enable all three software interlocks, give all three valid visible modes, and select `Activate Enabled Beams`. | All three selected channels start from one synchronized apply and map to their own blue LEDs/status rows. | |
| 8. Select Disable All and disarm. | Confirmed all-off restores the common idle state. | |

### BCON-5.2 - Invalid enabled config aborts the whole activation

**Description:** Ensure validation is atomic from the operator's perspective.

**Initial conditions:** BCON is armed and all outputs OFF. Enable the A, B, and
C software interlocks. Configure A DC, B PULSE 1000 ms, and C PULSE_TRAIN count
1.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Select `Activate Enabled Beams`. | C validation fails with a clear dialog/action message; no A/B/C parameter, mode, or apply command is sent for this activation. | |
| 2. Watch all blue LEDs and LCD rows through two polls. | All three remain OFF; no partial A or B start occurs. | |
| 3. Disable Beam C's software interlock without fixing its invalid config and select Activate again. | C is skipped; valid A and B start as configured. | |
| 4. Select `Disable All Beams`, then confirm all three software interlocks are Disabled. | Firmware confirms all-off before Main Control clears the software interlocks. | |
| 5. While still armed, select Activate. | The action is skipped with `no enabled channels`; no write or blue BCON gate-LED transition occurs and channel status lines are not falsely changed. | |
| 6. Disarm. | The common idle state is restored. | |

### BCON-5.3 - Disable All Beams active, idle, armed, and unsafe

**Description:** Verify immediate confirmed all-off independently of software
arm and firmware safety state.

**Initial conditions:** BCON is connected and armed. Enable all three software
interlocks and start A DC, B long PULSE, and C long PULSE_TRAIN.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Record the physical PVX LED vector, then select `Disable All Beams` while all three are active. | The driver invalidates older queued writes and firmware executes `ALL_OFF`; all blue gate LEDs go dark. Main Control clears active/deferred state and software interlocks only after a complete post-command all-off poll. The PVX LED vector is unchanged. | |
| 2. Inspect software arm state. | Beam Pulse remains software armed; Main Control software interlocks are Disabled after the confirming poll, and Beam A/B/C cannot start until re-enabled. | |
| 3. Select `Disable All Beams` again while idle. | A second confirmed all-off is safe and idempotent; no false error or output transition occurs. | |
| 4. Turn physical Arm Beams OFF and select `Disable All Beams`. | `ALL_OFF` executes even in SAFE_INTERLOCK, clears any latent gate modes, and leaves every blue gate LED off. | |
| 5. Turn physical Arm Beams ON and disarm. | Safety returns healthy without output; the common idle state is restored and the physical PVX LED vector still matches step 1. | |
| 6. While still disarmed, select `Disable All Beams` once more. | All-off remains admission-independent and idempotent while disarmed; it does not re-arm, alter PVX LEDs, or report a false error. | |

### BCON-5.4 - Output command followed immediately by all-off

**Description:** Stress the driver's write epoch so a queued or dequeued ON
cannot execute after confirmed all-off.

**Initial conditions:** BCON is connected and armed; all three software
interlocks are enabled and configured DC; all outputs are initially OFF.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Select `Activate Enabled Beams` and immediately select `Disable All Beams` before the next poll cycle if possible. | All-off invalidates/clears pre-stop queued writes and is synchronously confirmed. | |
| 2. Observe all blue gate LEDs/LCD rows for at least 5 seconds. | No channel turns on after the all-off confirmation; final modes and outputs are all OFF. A brief pre-confirmation edge, if any, is timestamped. | |
| 3. Repeat with a single `Beam A` ON click immediately followed by Disable All. | A cannot reassert after confirmation; B/C remain unaffected. | |
| 4. Repeat with rapid A, B, and C ON clicks followed by Disable All. | Only the first normal action is admitted while its Main Control token is pending; later normal clicks are explicitly busy/rejected rather than queued as hidden writes. Disable All preempts the admitted action, and no channel asserts after its confirmation. | |
| 5. Disarm. | The common idle state is restored. | |

### BCON-5.5 - E-stop BCON portion

**Description:** Verify only the in-scope confirmed BCON all-off and Beam Pulse
disarm portion of the mixed-system E-stop.

**Initial conditions:** CCS and every high-voltage supply are verified OFF. BCON
is armed with A DC, B long PULSE, and C long PULSE_TRAIN active.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Record the physical PVX LED vector, then select `E-STOP: BEAMS & CCS`. | Under one safety-operation token, the handler makes two sequential, redundant immediate BCON `ALL_OFF` attempts and requests CCS shutdown. All blue gate LEDs go dark and all active/staged modes clear. No PVX LED changes. | |
| 2. Observe Beam Pulse/Main Control state after the later eligible all-off poll. | Beam Pulse is disarmed; Beam output buttons and software interlocks reset to OFF/Disabled. The action line retains the E-stop command, firmware result, and status-poll result; it does not finalize on transport acknowledgement alone. | |
| 3. Inspect BCON acknowledgements and log. | The chronology proves both redundant BCON attempt paths ran and no earlier queued ON executes later. Any observed failure is preserved; two attempts are expected behavior and are not collapsed into a claim that an unobserved attempt succeeded. | |
| 4. Verify scope boundaries. | CCS and all high-voltage supplies are still OFF. Their internal integration behavior is not evaluated or changed for this case. | |
| 5. After the first E-stop has completed, press E-stop again while BCON is idle/disarmed. | A new safety operation again makes two bounded BCON all-off attempts. It remains safely idempotent, changes no PVX LED, and the dashboard stays responsive. Pending-token reuse is tested separately in BCON-5.6 and BCON-9.5. | |

### BCON-5.6 - E-stop redundant-attempt failures and recovery

**Description:** Verify that redundancy never erases an attributable failed
shutdown attempt or creates false confirmed safety.

**Initial conditions:** CCS and high voltage are OFF. BCON is connected and
armed with A DC active; record the physical PVX LED vector.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Remove the BCON-side serial cable and press E-stop during the stale-green window. | Both immediate BCON `ALL_OFF` attempts are made and fail/are unconfirmed independently. The action remains CRITICAL/failed or uncertain; it does not claim confirmed gate shutdown or clear software arm/interlocks as a successful disarm. PVX LEDs do not change. | |
| 2. Observe BCON through watchdog expiry. | The blue A gate LED eventually goes dark from firmware watchdog safety. That physical fallback is not attributed to either failed E-stop write. | |
| 3. Where timing can be controlled safely with the approved serial fault fixture, fail only one of the two attempts and allow the other plus a later all-off poll to succeed. | The later poll may reconcile/disarm the gate state, but the failed redundant attempt remains visible and the overall E-stop result retains failure wording; one success never overwrites one failure. | |
| 4. Repeat E-stop while the first safety operation is still pending. | The safety action is serialized/reuses its operation context without admitting a normal ON command; each press still executes its two physical BCON attempts and no stale result attaches to a newer action. | |
| 5. Restore communication, reconnect if needed, select `Disable All Beams`, and wait for firmware plus a strictly later all-off poll. | A new explicit recovery action confirms all gate outputs OFF and clears deferred state. The earlier failed E-stop remains failed in evidence and no request replays. | |
| 6. Disarm and compare physical PVX LEDs with the initial vector. | Gate state returns to common idle; all PVX LEDs remain exactly unchanged. | |

## Suite 6 - Physical Arm Beams interlock and firmware safety recovery

**Description:** Exercise the active-high Knob Box interlock before, during, and
after commands, including latent staged-mode hazards.

**Initial conditions:** Common initial conditions apply. The required Logic
Arduino Override is installed. Keep BCON serial communication connected unless
a step says otherwise. Record the physical PVX LED vector before each case;
physical Arm changes, firmware gate-safety actions, and recovery must not alter
it.

### BCON-6.1 - Interlock OFF at connection and output rejection

**Description:** Distinguish a healthy transport connection from firmware
permission to drive a gate.

**Initial conditions:** Turn physical Arm Beams OFF before starting or
reconnecting the dashboard. All channels are OFF.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Connect BCON and wait for a complete poll. | The connection indicator is green, while the safety label reads `Interlock: locked`; LCD reads `INT:NO`; every blue gate LED remains off. | |
| 2. Select the Arm Beams toggle. | Software arming succeeds; it does not change LCD, interlock, or output. | |
| 3. Configure A for DC, enable Beam A's Main Control software interlock, then select `Activate Enabled Beams`. | The local software interlock may remain Enabled, but BCON rejects the output command as `UNSAFE_INTERLOCK`; no blue A output is allowed. | |
| 4. Compare the log, action line, Beam Pulse card, and LCD after two polls. | The attempted A command remains in line 4 with the rejected result; A is OFF/O:0 everywhere. The known hardware-interlock rejection is logged as ERROR, not CRITICAL. | |
| 5. Select `Disable All Beams` before turning the switch ON. | Confirmed all-off clears the rejected staged request and Main Control clears its software interlocks after the confirming poll. | |
| 6. Turn Arm Beams ON. | LCD/dashboard return to interlock OK without automatically selecting or starting A. | |
| 7. Disarm. | The common idle state is restored. | |

### BCON-6.2 - Interlock trip during active DC and pulse train

**Description:** Verify immediate physical shutoff, register reconciliation,
abort semantics, and no automatic restart.

**Initial conditions:** BCON is connected and armed. Enable the A and B software
interlocks; run A DC and B PULSE_TRAIN with 2000 ms duration and at least 5
pulses.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Confirm A and B are in a high phase, then turn physical Arm Beams OFF. | Firmware immediately stops timers and forces blue A/B low; C stays low. LCD updates to `INT:NO` and all channel modes OFF within its refresh behavior. | |
| 2. Wait for one complete dashboard snapshot. | Beam Pulse cards and Main Control output lines show A/B OFF and remaining cleared. The connection remains green because serial communication is healthy; the local software interlocks remain selected until an operator or confirmed all-off resets them. | |
| 3. Inspect software arm and controls. | Software arm and local software-interlock selections remain independent permission state; no physical output silently returns. | |
| 4. Inspect the log. | One CRITICAL safety-transition entry identifies `interlock locked` because output was active; repeated polls do not flood identical entries. | |
| 5. Turn physical Arm Beams ON and observe for two polls without another command. | Interlock returns OK, but A/B do not reassert and all blue gate LEDs stay dark. Recovery is visible and traceable; absence of a recovery log is recorded as a semantic gap. | |
| 6. Issue a fresh output command to A. | Only the freshly commanded A may start; B remains OFF. | |
| 7. Disable all and disarm. | The common idle state is restored. | |

### BCON-6.3 - Interlock trip while idle and switch bounce

**Description:** Verify warning severity, bounded logs, and immunity to repeated
hardware edges.

**Initial conditions:** BCON is connected, armed, and idle with all Main
Control software interlocks disabled.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Turn physical Arm Beams OFF while idle. | LCD shows `INT:NO`, the dashboard shows locked, all blue gate LEDs remain off, and the safety transition is WARNING rather than CRITICAL. | |
| 2. Turn it ON, then cycle OFF/ON five times at a deliberate observable rate. | Each sampled state is physically safe; no mode or output appears; the UI remains responsive. | |
| 3. Inspect Knob Box and BCON logs. | Arm signal transitions use consistent ON/OFF semantics; safety entries correspond to observed unsafe edges without per-poll flooding or reversed wording. | |
| 4. End with the switch ON and wait for two polls. | LCD and dashboard stabilize at `INT:OK`; every channel remains OFF. | |
| 5. Disarm. | Confirmed all-off returns the common idle state. | |

### BCON-6.4 - Software-interlock selection while hardware is unsafe

**Description:** Keep the dashboard-only selector distinct from firmware safety
and confirmed output state.

**Initial conditions:** BCON is connected and software armed; all outputs and
software interlocks are OFF. Turn physical Arm Beams OFF and wait until locked
is displayed.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Select `Beam A Disabled` while the hardware interlock remains OFF. | The local software interlock changes to Enabled and its Beam output button becomes usable, but no BCON write, mode, or blue gate output occurs. | |
| 2. Wait for two polls and compare Main Control with firmware status. | Main Control still identifies the local software interlock as Enabled while BCON remains `INT:NO` and A output remains OFF/O:0; neither state is presented as the other. | |
| 3. Turn physical Arm Beams ON without sending an output command. | No gate output starts. Restoring the hardware interlock does not convert the local selector into an output command. | |
| 4. Select `Disable All Beams` and disarm. | Confirmed all-off resets Main Control's software interlocks and restores the common idle state. | |

### BCON-6.5 - Unsafe manual request must not activate on a later APPLY

**Description:** Verify that a manual output request blocked by an unsafe
interlock cannot be applied by a later, unrelated manual action.

**Initial conditions:** Every BCON Output cable is disconnected from every PVX pulser. BCON is connected and
software armed with all channels OFF. Configure A and B for DC in Manual
Control.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Turn physical Arm Beams OFF and wait for `INT:NO`. | Firmware is stably SAFE_INTERLOCK; all blue gate LEDs are off. | |
| 2. Enable Beam A's software interlock and select `Activate Enabled Beams`. | A remains physically OFF and the unsafe apply is explicitly rejected; fail-closed recovery forces all-off so its staged A mode cannot survive for a later apply. | |
| 3. Turn physical Arm Beams ON and wait for `INT:OK` without issuing all-off. | A remains OFF; recovery alone does not apply the blocked request. | |
| 4. Disable Beam A's software interlock, enable Beam B's, and select `Activate Enabled Beams` to issue a fresh, unrelated apply. | Only B may turn on. Blue A must remain dark and A must remain OFF in LCD/UI. If A also starts, record a critical latent-stage defect. | |
| 5. Select `Disable All Beams` immediately. | Confirmed all-off turns every blue gate LED off and clears all staged/active modes without changing PVX LEDs. | |
| 6. Repeat the unsafe A attempt, restore Arm, disable A's software interlock, enable only B's, and select Activate. | The fresh Main Control apply starts only B; the earlier rejected A staging remains incapable of activation. | |
| 7. Select Disable All and disarm. | Confirmed all-off clears every mode and software interlock and restores the common idle state. | |

## Suite 7 - BCON power, serial, adapter, and stale-connection failures

**Description:** Compare physical truth with dashboard state across short and
sustained transport loss, power loss, invalid handles, and actions attempted
during the driver's ten-failure detection window.

**Initial conditions:** Common initial conditions apply. Record the configured
watchdog and original Windows COM number. Unless stated otherwise, use the
default 1500 ms watchdog and a DC output so physical gate state is unambiguous.
Keep the independently powered PVX LEDs visible and record their vector; serial
loss, watchdog action, BCON power loss, reconnect, and non-PVX commands must
leave it unchanged.

### BCON-7.1 - BCON-side two-second serial interruption

**Description:** Verify recovery from a deliberate two-second link interruption
that remains below the configured watchdog interval.

**Initial conditions:** BCON is connected and armed; set and confirm the
watchdog at `5000 ms`; Beam A's software interlock is enabled and A is running DC. The USB adapter
remains connected to the laptop.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Remove the BCON-side serial cable for 2 seconds, then restore it. | Because the interruption is below the 5000 ms watchdog, blue A remains solid ON. At most a bounded communication error appears, and a later complete poll recovers without a false disconnect. | |
| 2. Verify the live state after two successful polls. | Connection remains green; A remains DC only if the firmware watchdog never expired; LCD, card, status line, and blue A gate LED agree. | |
| 3. Inspect the log around the interruption. | The link loss and recovery are distinguishable. A missing recovery record, caused by polling feeding the watchdog, is recorded as a semantic-observability defect. | |
| 4. Select `Disable All Beams`, restore the watchdog to `1500 ms`, and disarm. | Confirmed all-off clears any residual staged state, the default watchdog is restored, and the common idle state returns. | |

### BCON-7.2 - Sustained BCON-side serial loss and auto-disconnect

**Description:** Verify the complete default-watchdog-to-driver-disconnect
progression and explicit recovery.

**Initial conditions:** BCON is connected and armed; A DC and B long
PULSE_TRAIN are active. Leave the laptop adapter connected.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Remove the BCON-side serial cable and keep it removed. | Host heartbeat and polls fail. The dashboard logs bounded failures numbered toward 10 while retaining only the last known snapshot. | |
| 2. Observe BCON after approximately 1500 ms. | LCD shows `WDG:NO`; blue A/B go dark; timers and active/staged modes clear. | |
| 3. Observe the dashboard before its tenth failed poll. | It must indicate degraded/stale communication rather than silently presenting the last green/ON state as current. Any green healthy indication with no stale warning is a defect. | |
| 4. Wait for ten consecutive failed polls. | The driver auto-disconnects, the indicator turns red, software arm/local output state clears, and the button reads `Reconnect`. | |
| 5. Inspect Beam Pulse card/safety text after red disconnect. | No stale mode, remaining count, or `Interlock/Watchdog: ok` text is presented as live. Stale card/safety text is recorded as a defect. | |
| 6. Restore the cable without selecting Reconnect. | BCON remains watchdog-safe and the stopped driver does not falsely turn green or replay writes automatically. | |
| 7. Select `Reconnect` and wait for fresh registers. | Connection and watchdog recover; all channel outputs remain OFF and Main Control software interlocks remain Disabled; no prior DC/train request replays. | |

### BCON-7.3 - Operator commands during the stale-green failure window

**Description:** Detect optimistic action status while the driver still believes
a physically broken link is connected.

**Initial conditions:** BCON is connected and armed; Beam A and B software
interlocks are Enabled, A is running DC, and B remains OFF at the default
watchdog.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Remove the BCON-side serial cable and, before ten poll failures, select Beam A OFF. | The queued OFF cannot reach BCON. The dashboard must not describe it as firmware-confirmed OFF merely because it entered the queue. | |
| 2. Watch the blue A gate LED until the watchdog expires. | A may remain physically ON until the 1500 ms watchdog trip, then turns OFF from firmware safety rather than the failed Beam OFF command. | |
| 3. While the indicator is still green, record the physical PVX LEDs, attempt `Toggle PVX C Enable`, and request Beam B ON. | The immediate PVX FC06 fails or is reported indeterminate and no definite failed toggle changes a PVX LED; the physical LEDs resolve the external latch truth before any retry. If A OFF is still pending, B is busy-rejected; otherwise its unreachable write fails. Neither outcome leaves optimistic success or a replayable B request. | |
| 4. Select the armed/ON toggle to request disarm before auto-disconnect. | Because confirmed all-off cannot be obtained, disarm reports failure and does not falsely clear the armed/output state as confirmed. | |
| 5. Select `Disable All Beams` and then E-stop before auto-disconnect. | Each BCON all-off attempt reports unconfirmed/uncertain state. The log never says firmware confirmed a command it could not receive. | |
| 6. Wait for auto-disconnect, restore the cable, and reconnect. | Local gate state clears on disconnect, fresh firmware state is OFF after watchdog, none of the failed-window commands replays, and the physical PVX LED vector remains as directly observed in step 3. | |

### BCON-7.4 - BCON power removal and restoration

**Description:** Verify immediate physical de-energization and both early and
late dashboard recovery paths.

**Initial conditions:** BCON is connected and armed; A DC and C long train are
active. The laptop adapter remains powered and enumerated.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Record the physical PVX LED vector, then shut off BCON power. | The BCON LCD/backlight and every blue gate LED go dark immediately. No gate-output cable is connected to a PVX pulser. The independently powered PVX LEDs remain visible and unchanged. | |
| 2. Observe the dashboard until the first error. | It does not invent a firmware interlock/overcurrent fault; it reports communication failure and marks retained data stale/unknown. | |
| 3. Restore BCON power before ten consecutive failures. | Firmware boots with gates/blue gate LEDs low and modes OFF. If the serial session survives, later full polling recovers without replaying the prior modes. | |
| 4. Wait for two successful snapshots. | Connection is healthy, all channel outputs remain OFF, and the UI no longer shows stale A/C output. | |
| 5. Start A DC again, remove power, and leave it off through auto-disconnect. | Physical state goes dark immediately; after ten failures the dashboard turns red and disarms local state. | |
| 6. Restore power after auto-disconnect. | BCON boots safe and remains unconnected until the operator selects Reconnect. | |
| 7. Reconnect and inspect logs/state. | One clean connection occurs; no stale writes or duplicate poll workers appear; all gate modes/outputs remain OFF, no PVX request replays, and all physical PVX LEDs still match step 1. | |

### BCON-7.5 - Laptop USB adapter removal and COM reassignment

**Description:** Verify loss of the Windows serial device and recovery when it
returns on the same or a different COM number.

**Initial conditions:** BCON is connected and armed with A DC active. Record the
adapter's current COM number.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Remove the serial adapter cable from the testing laptop. | The COM handle becomes invalid; host writes/polls fail; BCON remains powered and shuts A off only when its watchdog expires. | |
| 2. Wait for driver auto-disconnect. | The indicator turns red after bounded failures; the log identifies serial/communication loss rather than a BCON interlock trip. | |
| 3. Reinsert the adapter and record its assigned COM number. | Windows enumerates the adapter. No output mode appears on BCON. | |
| 4. If Windows assigned a different number, update and save the `BeamPulse` COM mapping through the approved selector/config flow; otherwise retain the existing mapping. Restart the test laptop and launch the dashboard. | Reconnection uses the explicitly recorded port and reads fresh all-off state; the dashboard neither assumes the old number nor cross-routes another device. | |

### BCON-7.6 - Link or power loss during connect and confirmed shutoff

**Description:** Exercise removal at transaction boundaries without deadlock or
false confirmation.

**Initial conditions:** BCON is intentionally disconnected in the UI. Hardware
is initially powered and cabled.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Select Reconnect, then remove BCON power during the 4.5 s settle interval. | The attempt terminates as failed, the button returns to Reconnect, the UI remains responsive, and no orphan poll worker starts. | |
| 2. Restore power, reconnect, start A DC, and confirm its blue gate LED is on. | A runs normally from a fresh connection and command. | |
| 3. Remove the BCON-side serial cable immediately before selecting `Disconnect`. | The driver cannot confirm its pre-close ALL_OFF and explicitly logs reliance on the firmware watchdog; it never logs a false confirmation. | |
| 4. Observe A and LCD. | A turns off only when the watchdog expires; LCD shows `WDG:NO`. The dashboard is red/disarmed but does not assert the physical off time without evidence. | |
| 5. Restore the cable and reconnect. | Fresh output state is all OFF, software interlocks are Disabled, and no pre-disconnect command replays. | |

### BCON-7.7 - Maximum watchdog exposes UI-versus-physical uncertainty

**Description:** Verify that dashboard auto-disconnect cannot be equated with
physical gate shutoff when the configured watchdog is 60000 ms.

**Initial conditions:** Every BCON Output cable is disconnected from every PVX pulser. BCON is connected and
idle; set watchdog to 60000 ms and confirm the write. Arm, enable Beam A's software interlock, and run A
in DC.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Remove the BCON-side serial cable and keep BCON powered. | A can legitimately remain physically HIGH because the 60000 ms firmware watchdog has not expired. | |
| 2. Wait for ten host poll failures and driver auto-disconnect. | The indicator turns red and software-arm permission resets after roughly 5-7+ s, while blue A may still be solid ON. Hardware-derived mode/output state becomes explicitly disconnected or unknown rather than being cleared as confirmed fact. | |
| 3. Compare dashboard wording with the LED/LCD. | The dashboard marks BCON hardware state unknown/unconfirmed, not confirmed OFF. Any OFF/Disabled presentation that conceals the still-high blue A LED is a critical defect. | |
| 4. Restore the cable and reconnect before 60000 ms has elapsed; observe whether this fixture resets BCON on port open. | The test records either a hardware reset to safe OFF or a live DC state. The first fresh poll must reflect the observed hardware; reconnect must not assume all-off. | |
| 5. Select `Disable All Beams` as soon as communication is healthy. | Firmware confirms all-off and blue A goes dark; no stale DC reappears. | |
| 6. Repeat the loss without reconnecting and wait through the configured 60000 ms watchdog. | Blue A eventually goes dark and LCD shows `WDG:NO`; this physical timeout, not dashboard auto-disconnect, is the all-off evidence. | |
| 7. Restore the cable, reconnect, set watchdog to 1500 ms, and confirm all-off/disarm. | The common default and safe idle state are restored. | |

## Suite 8 - Startup, configuration-file, and COM-port resilience

**Description:** Manipulate every startup input that can prevent or misroute
Beam Pulse construction, then verify a recoverable and honestly reported state.

**Initial conditions:** Back up `usr/usr_data/com_ports.json`,
`usr/usr_data/main_control_config.json`, and `usr/usr_data/pane_state.json`.
Keep the original COM mapping written down. Restore each approved file before
moving to an unrelated case. No output-producing action is permitted during
startup. Make the mandatory setting/log changes as soon as the UI appears; if
an auto-connect failure completes first, repeat it with `Reconnect` after those
changes so the in-scope evidence is unsuppressed.

### BCON-8.1 - Missing and partial COM-port configuration

**Description:** Verify first-run selection, blank-port handling, and safe dummy
assignment without silently losing the BeamPulse mapping.

**Initial conditions:** Dashboard is closed. Move the backed-up
`usr/usr_data/com_ports.json` aside.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Start the dashboard process. | The log states that no COM-port configuration was found; the selector opens with blank choices rather than crashing. | |
| 2. Leave one or more entries blank, select Submit, and answer No to dummy-port substitution. | The selector remains open and no dashboard/BCON connection starts. | |
| 3. Set BeamPulse to the real BCON COM, assign approved dummy values to blank out-of-scope entries as setup, and submit. | The real BeamPulse selection is preserved, saved, and used for BCON auto-connect; no assertion is made about unrelated subsystem behavior. | |
| 4. Immediately apply the mandatory safety/logging settings after the dashboard opens. | The three excluded settings remain disabled and BCON/Knob logging remains enabled despite the startup-file test. | |
| 5. Quit, replace the COM file with a valid partial dictionary that omits `BeamPulse`, and relaunch. | The selector shows BeamPulse blank and uses the same explicit blank/dummy workflow; no arbitrary COM is assumed. | |
| 6. Restore the approved COM file and relaunch. | The known BeamPulse port is preselected and connects normally. | |

### BCON-8.2 - Malformed JSON and wrong top-level COM types

**Description:** Verify schema resilience for syntactically invalid and
structurally invalid COM data.

**Initial conditions:** Dashboard is closed and the valid COM file is backed up.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Replace the COM file with malformed JSON and start the process. | A Config error is logged; startup falls back to an empty selector and remains usable. | |
| 2. Complete selection with the correct BeamPulse COM and dummy unrelated ports. | The dashboard can start and BCON can connect after explicit user selection. | |
| 3. Close the dashboard, set the file content to JSON `null`, and relaunch. | Startup rejects the wrong top-level type and falls back to an empty mapping; it does not crash while taking `len()` or building selectors. | |
| 4. Repeat with a JSON list and a JSON string. | Each wrong type is reported and recovered identically; `.get()` is never called on an invalid type. | |
| 5. Restore the approved file and relaunch. | Normal selection and BCON connection return with no persistent corruption. | |

### BCON-8.3 - Stale, invalid, busy, and wrong-device BeamPulse COM

**Description:** Partition startup port failures at open, ownership, and Modbus
validation stages.

**Initial conditions:** Dashboard is closed. Keep BCON outputs OFF and retain a
known-good adapter/port for recovery.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Save a nonexistent/stale COM name for BeamPulse and submit startup. | Serial open fails promptly; Beam Pulse still constructs, shows red/Reconnect, and logs the port error without crashing the dashboard. | |
| 2. Select a present COM whose device does not implement BCON Modbus slave 1. | Open may succeed, but the post-settle register validation fails; the UI never reports BCON connected. | |
| 3. Open the real BCON COM in an approved serial utility, then launch with that COM selected. | Exclusive-open failure is clear and bounded; no second owner or partial poll worker is created. | |
| 4. Close the utility and select Reconnect. | The same configured port now connects normally and starts one poll worker. | |
| 5. Inspect logs for all variants. | Invalid name, busy port, and nonresponding/wrong device are distinguishable enough to diagnose; none is mislabeled a physical Arm interlock fault. | |
| 6. Restore the approved COM mapping. | Subsequent launches use the known-good port. | |

### BCON-8.4 - Hardware state matrix during auto-connect

**Description:** Verify safe construction and recovery for every physical
startup arrangement.

**Initial conditions:** Use the approved COM file. Fully close the dashboard
between rows and reapply mandatory safety/logging settings on every launch.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Launch with BCON powered, the BCON-side serial cable and laptop USB adapter present, DB15 toggle cables connected, every BCON Output cable disconnected from every PVX pulser, and physical Arm Beams OFF. | Transport connects green; safety reports interlock locked; all gate outputs remain OFF; no mode auto-applies and no physical PVX LED changes. | |
| 2. Launch with BCON power OFF but the laptop adapter present. | The valid COM opens but Modbus validation fails after settle; the dashboard remains usable and red. Power restoration plus Reconnect recovers. | |
| 3. Launch with BCON powered but its BCON-side serial cable removed. | The result is a nonresponding-firmware connection failure; LCD eventually reads `WDG:NO`; restoring the cable plus Reconnect recovers. | |
| 4. Launch with the laptop adapter absent and its old COM saved. | Serial open fails clearly; inserting the adapter does not silently connect to another port. Reconnect succeeds only when the configured COM exists. | |
| 5. Begin launch with BCON off, then power it during the 4.5 s settle interval. | The outcome is deterministic: either validation succeeds after a complete boot or fails and requires one explicit Reconnect; no half-connected state or duplicate worker remains. | |
| 6. Launch with BCON previously left watchdog-safe or interlock-safe. | Connection feeds the watchdog and reports the current interlock; firmware boots/recovers with all gates low, modes OFF, and no old mode replay. | |

### BCON-8.5 - Other startup files and manual Beam Pulse availability

**Description:** Verify that missing/corrupt Main Control and pane-state files
cannot hide or partially initialize the manual BCON controls.

**Initial conditions:** Dashboard is closed. Approved backups exist.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Remove `usr/usr_data/main_control_config.json` and launch. | Numeric defaults are recreated/loaded safely; all Beam Pulse controls render. The three excluded boolean settings still default enabled and are manually disabled before testing. | |
| 2. Repeat with malformed and wrong-shaped Main Control JSON. | Invalid numeric content is normalized or reported without preventing Beam Pulse/Main Control construction. No excluded guard behavior is exercised. | |
| 3. Remove `usr/usr_data/pane_state.json` and launch. | Default layout loads and Beam Pulse/Main Control remain visible and usable. | |
| 4. Repeat with malformed and structurally wrong pane-state data. | A clear Config/layout error is logged and startup falls back safely; the dashboard does not crash or place Beam Pulse controls irretrievably off-screen. | |
| 5. After each launch, inspect Manual Control, Arm Beams, Disable All, and the BCON portion of E-stop. | The manual controls are visible and correctly gated for the current connection state; no action crashes or falsely claims BCON all-off. | |
| 6. Restore all approved configuration files. | A clean relaunch returns to the common baseline with one BCON connection. | |

### BCON-8.6 - COM configuration save failure

**Description:** Verify that a startup selection used only in memory is not
misrepresented as durably saved.

**Initial conditions:** Dashboard is closed. Back up the approved COM file, then
make the test copy or its approved containing directory non-writable without
changing the selected BCON hardware.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Launch the selector, choose the correct BeamPulse COM, and submit. | The save failure is logged clearly. Startup may use the explicit in-memory selection, but it does not claim the file was saved. | |
| 2. Apply the mandatory settings/log setup and observe BCON connection. | BeamPulse uses only the selection just submitted and behaves normally if that COM is correct. | |
| 3. Quit, restore write permission without replacing file content, and relaunch. | The selector shows the last actually persisted value, proving the failed save was not durable. | |
| 4. Submit the approved mapping while writable and relaunch once more. | Save succeeds, the correct BeamPulse port persists, and one normal BCON connection starts. | |
| 5. Restore the original approved file and permissions. | No read-only test artifact remains. | |

## Suite 9 - Logging, acknowledgements, and semantic consistency

**Description:** Verify that the durable session log, Messages pane, event line,
Main Control action line, and firmware acknowledgement tell one chronological
story without suppression, false success, or stale hardware certainty.

**Initial conditions:** Common initial conditions apply. File-log level is
VERBOSE, the green recording indicator is ON, both BCON and Knob Box HV-off log
suppression settings are disabled, and the session-log path is recorded.

### BCON-9.1 - File logging, Clear, and Export controls

**Description:** Prove that evidence remains available even though the Messages
pane retains only its most recent lines.

**Initial conditions:** BCON is connected and idle. Generate one intentional
arm/disarm cycle and one invalid watchdog entry to create known messages.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Locate the live dashboard session log and find the known BCON/Main Control entries. | The durable file contains VERBOSE-through-CRITICAL messages with timestamps, levels, and tags despite the HV subpanel being off. | |
| 2. Select Export in Messages and cancel. | No export is written and logging continues uninterrupted. | |
| 3. Select Export and save to a writable text file. | A success dialog appears and the file contains the currently visible Messages text in order. | |
| 4. Set the UI log level to `VERBOSE` and allow safe BCON polling to generate more than 100 visible lines. | The pane trims older lines, while the durable session log retains the full chronology; Export is not mistaken for the complete session record. | |
| 5. Select Clear and cancel the confirmation. | Visible messages remain. | |
| 6. Select Clear and confirm. | Only the visible pane clears; file recording remains ON and later BCON events appear in both the pane and session file. | |
| 7. Attempt Export to an approved read-only target. | A user-facing Export Error is logged/displayed; no dashboard crash or logging shutdown occurs. | |

### BCON-9.2 - Queued, executed, rejected, and failed command chronology

**Description:** Verify that asynchronous driver behavior never leaves a
premature success as the final operator conclusion.

**Initial conditions:** BCON is connected, armed, and Beam A's software interlock enabled. Configure A
DC and keep physical Arm Beams ON initially.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Turn Beam A ON normally while recording the action line after each change. | The chronology progresses from the operator request to `Command Sent: ...`; firmware `APPLY_STAGED_MODES executed` adds `FW: OK`, but neither transport nor firmware acknowledgement is final success. Only a complete status poll with `completed_at > sent_at` may end as `Command Success: ... \| FW: OK \| Status Poll: OK`. | |
| 2. Turn A OFF and record the same phases through live OFF. | Sent/firmware/poll phases remain distinct. The final success appears only after a strictly later complete poll confirms A mode OFF and output low; no queued or ACK-only phase is called success. | |
| 3. Turn physical Arm Beams OFF and request A DC. | Any initial queued/sent status is followed by `rejected: UNSAFE_INTERLOCK`; the final action outcome remains failure and A remains physically OFF. | |
| 4. Remove the BCON-side serial cable, then request an action during the stale-green window. | Write/confirmation failure supersedes optimistic status; the log never invents an executed firmware action. | |
| 5. Restore/reconnect, enter watchdog `49`, and select Set. | Range rejection is logged without a later false `Set watchdog = 49 ms` success or hardware write. | |
| 6. Select Disable All, restore physical Arm ON, and disarm. | Each action reaches final success only through its eligible all-off poll; the final confirmed safe state is explicit and closes the chronology. | |

### BCON-9.3 - Safety, connection-loss, and recovery log semantics

**Description:** Verify severity, transition deduplication, causal wording, and
recovery evidence.

**Initial conditions:** BCON is connected and idle at the default watchdog.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Turn physical Arm Beams OFF while idle, wait two polls, then turn it ON. | One WARNING names interlock locked; repeated polls do not repeat it. Recovery is visibly/logically identifiable and is not called a reconnect. | |
| 2. Run A DC and turn physical Arm Beams OFF. | One CRITICAL safety entry names interlock locked with active output; it is not mislabeled watchdog, serial, CCS, or pressure. | |
| 3. Restore Arm, clear all state, run A DC, then remove the BCON-side serial cable through auto-disconnect. | Poll/heartbeat errors are bounded; default watchdog physical shutoff and later driver auto-disconnect remain distinct events. | |
| 4. Restore and reconnect. | A fresh connection/recovery entry appears; no old error continues after successful full polls and no duplicate connection worker logs. | |
| 5. Compare timestamps with recorded physical times. | Error, physical shutoff, red indicator, and recovery order is plausible and precise enough to diagnose the event. | |

### BCON-9.4 - Cross-surface truth and interrupted staged command

**Description:** Partition every staged-write/apply failure boundary, detect
mixed snapshots or orphaned staging, and keep placeholder fields from being
presented as real fault sensors.

**Initial conditions:** Every BCON Output cable is disconnected from every PVX pulser. BCON is connected and
armed; A and B software interlocks are enabled and configured DC but outputs are OFF.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. In separate restored iterations, use physical cable timing or the approved serial fault fixture to fail the first staged register write and then a middle/final staged write during `Activate Enabled Beams`. | The operation reports one attributable stage failure, suppresses every remaining stage and APPLY in that batch, and starts fail-closed `ALL_OFF` recovery. It never claims an atomic successful start or lets an old write execute after recovery. | |
| 2. Allow all staging to complete, then interrupt or reject the terminal APPLY before an executed diagnostic is obtained. | An APPLY rejection, missing response, or inconclusive result is failure, not success. Fail-closed recovery requests all-off and the action retains its actual terminal cause. | |
| 3. Allow firmware to report APPLY executed, then remove communication before the required post-command full poll. | The operation can show `FW: OK` but cannot show `Command Success`; after the acknowledgement/poll deadline it becomes timed out/unknown. A later reconnect poll reconciles hardware only and does not retroactively complete the expired operation. | |
| 4. After every interrupted iteration, restore the link, inspect physical blue gate LEDs/LCD, obtain fresh state, and issue an explicit confirmed `Disable All Beams`. | Dashboard state follows actual firmware. Recovery confirmation is new evidence; no partial stage is silently called active or confirmed OFF, and no failure is overwritten by the recovery. | |
| 5. Issue an unrelated fresh apply for only B after recovery. | Only B may start. If an orphaned A stage also starts, record a critical stale-stage defect. | |
| 6. Compare Beam Pulse A/B cards, Main Control lines, LCD rows, and blue gate LEDs after each fresh poll. | Each complete snapshot is internally consistent; no old remaining count or mixed pre/post-command state is presented as one live result. | |
| 7. Inspect any overcurrent/power/gated indications or logs. | Reserved firmware placeholders are not described as tested physical sensors or used to claim hardware health. | |
| 8. Select Disable All and disarm. | Confirmed all-off clears every possible partial stage and restores the common idle state without changing any physical PVX LED. | |

### BCON-9.5 - Operation-token ordering, contention, timeout, and preemption

**Description:** Verify the merged one-operation lifecycle prevents unrelated,
late, or stale events from completing the wrong operator action.

**Initial conditions:** BCON is connected, armed, idle, and A/B software
interlocks are Enabled with valid DC configurations.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Select Beam A ON and, before its required post-command poll, select Beam B ON. | At most one normal Main Control operation is pending. The second normal request is clearly rejected/busy and cannot steal the first token or later appear successful. | |
| 2. With the approved callback/driver fault fixture, admit a normal operation but withhold its sent callback beyond the 1.5 s send deadline. | The awaiting-send phase times out explicitly while awaiting command send; the token is finished as failed/unknown and a late sent/firmware event cannot revive it. | |
| 3. Let a new A operation receive firmware `EXECUTED`, then inject link loss before the next full poll and wait beyond the 1 s acknowledgement/poll deadline. | A stops at `FW: OK` and then becomes timeout/unknown; it never reaches `Status Poll: OK` from a full poll with `completed_at <= sent_at` or from a partial snapshot. | |
| 4. Restore communication and wait for fresh polling without issuing a new A action. | Hardware A state reconciles on Beam Pulse/Main Control surfaces, while the expired action stays expired. Late diagnostics, callbacks, or polls carrying the old token are ignored for operation completion. | |
| 5. Start a normal operation, then use manual Disconnect while it is pending; repeat with sustained loss/auto-disconnect. | Disconnect terminates the pending token as unknown/failed before local connection teardown. Later callbacks from the old operation are ignored, fresh reconnect reconciles hardware, and no action is retroactively successful. | |
| 6. Start a normal Beam A or Activate operation and immediately select `Disable All Beams`; repeat with confirmed disarm. | The safety/stop action preempts the older normal operation, invalidates stale queued writes, and owns the final result. No old ON result can attach to or execute after the all-off/disarm token. | |
| 7. Repeat with E-stop, including a second press while its first result is pending. | E-stop safety work is admitted/preemptive; repeated presses reuse/serialize the pending safety context while still executing the intended redundant BCON attempts. No normal operation starts between them. | |
| 8. Recover with a new confirmed Disable All and disarm, then review token/action chronology. | Each request, send, firmware result, poll result, timeout, disconnect termination, rejection, and preemption is attributable to exactly one operation; final gate state is all OFF and PVX LEDs are unchanged. | |

## Suite 10 - Shutdown, restart, and interaction stress

**Description:** Verify normal and abnormal host termination, serial ownership,
worker cleanup, watchdog fallback, and resistance to rapid operator actions.

**Initial conditions:** Common initial conditions apply. Preserve the final log
from each shutdown because the UI will no longer be available.

### BCON-10.1 - Normal quit controls, cancellation, and active-output cleanup

**Description:** Exercise window close, Ctrl+Q, and Ctrl+W with both Cancel and
confirmed cleanup.

**Initial conditions:** BCON is connected and idle at 1500 ms.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Select the window close control. | A Quit confirmation appears before cleanup begins. | |
| 2. Choose Cancel. | Dashboard, BCON polling, logging, and controls continue unchanged; no all-off/disconnect is sent solely from opening the dialog. | |
| 3. Record the physical PVX LED vector. Arm, enable the A/B software interlocks, run A DC and B long train, then press Ctrl+Q. | The same Quit confirmation appears while live status continues safely behind it. | |
| 4. Confirm quit. | Beam Pulse stops workers, attempts confirmed all-off, closes serial, cancels scheduled updates, and the application exits without hanging. All blue gate LEDs are off; every independently powered PVX LED remains at its recorded state. | |
| 5. Relaunch immediately on the same COM. | The port is released, one auto-connect and one poll worker start, and BCON outputs remain all OFF with no queued replay. | |
| 6. Repeat a confirmed idle shutdown with Ctrl+W. | The alternate shortcut uses the same one-shot cleanup and leaves the port reusable. | |

### BCON-10.2 - Quit during connect, active manual output, and communication fault

**Description:** Detect daemon/thread leaks and deadlocks at each long-running
boundary.

**Initial conditions:** Begin intentionally disconnected, with hardware ready.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Select Reconnect and confirm quit during the 4.5 s settle interval. | The dashboard closes in bounded time; the connecting thread observes shutdown, closes any serial handle, and does not later emit UI work into a destroyed window. | |
| 2. Relaunch, arm, enable Beam A's software interlock, configure A for DC, turn Beam A ON, then confirm quit. | BCON receives confirmed all-off before close when communication is healthy; A goes dark and no later manual command executes. | |
| 3. Relaunch, run A DC, remove the BCON-side serial cable, and confirm quit while poll errors are active. | Shutdown does not deadlock. Failure to confirm all-off is logged explicitly and firmware watchdog turns A off. | |
| 4. Restore hardware and relaunch after each phase. | The COM opens normally, one connection/poll worker set exists, and no queued action replays. | |

### BCON-10.3 - Abnormal dashboard termination and firmware watchdog fallback

**Description:** Verify hardware safety when host cleanup cannot run.

**Initial conditions:** Every BCON Output cable is disconnected from every PVX pulser. BCON watchdog is
confirmed 1500 ms; A is DC and blue A is on.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Terminate the dashboard process through the approved operating-system force-close method without using its Quit dialog. | Host cleanup/all-off cannot be assumed; serial heartbeats stop. | |
| 2. Observe BCON and the independently powered PVX LEDs continuously. | Within the configured watchdog behavior, LCD changes to `WDG:NO`, blue gate A goes dark, modes clear, and A does not reassert. No PVX LED changes when the host or BCON heartbeat is lost. | |
| 3. Relaunch the dashboard on the same port. | Fresh startup reads all channels OFF and restores watchdog communication; no previous host queue survives process termination. | |
| 4. Inspect the prior and new session logs. | The prior file ends abruptly without a false clean-shutdown entry; the new file records a new process and connection. | |
| 5. Select Disable All and disarm. | A confirmed safe baseline is re-established. | |

### BCON-10.4 - Rapid UI, connect, and action stress

**Description:** Find double-connect, duplicate-worker, redraw, and command-order
failures reachable through fast user interaction.

**Initial conditions:** No outputs are attached. Begin from a clean dashboard
launch with BCON powered and correctly configured.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. During startup auto-connect, select the visible Connect control rapidly if it is enabled. | At most one connection operation owns the serial port. The control prevents or safely serializes a second connect; no port corruption or duplicate poll worker results. | |
| 2. Once connected, rapidly alternate Arm/disarm five times, waiting only for each visible result. | Each transition is confirmation-gated and ordered; final state matches the final click; no stale all-off acknowledgement is attached to the wrong action. | |
| 3. Ensure the system is armed, then rapidly toggle the Main Control Beam A/B/C software interlocks in varied order. Separately exercise the Beam Pulse PVX A/B/C buttons while watching all three physical enable LEDs. | Final local software-interlock states match the final clicks without cross-mapping. Each accepted PVX request changes only its matching physical LED; cooldown-rejected clicks change none and are logged rather than concealed. | |
| 4. Configure long visible modes and rapidly select individual Beam buttons, Activate, and Disable All. | The UI remains responsive; final confirmed all-off wins; no earlier queued output reasserts after it. | |
| 5. While statuses update, switch Beam Pulse tabs, scroll, resize, maximize/restore, and enter/exit fullscreen. | Widgets retain channel identity and correct state; no Tk exception, frozen update, duplicate card, or duplicate log stream occurs. | |
| 6. Disconnect/reconnect three times, waiting for completion each time. | Every cycle has one all-off/close/open/poll cycle; the COM is not leaked and old queues are cleared. | |
| 7. Finish with confirmed Disable All and disarm, explicitly toggle any Enabled PVX channel to Disabled on a healthy connection, then inspect LCD, blue gate LEDs, PVX LEDs, UI, and log. | Every gate surface agrees on connected, interlock/watchdog OK, software disarmed, all software interlocks Disabled, and all gate modes/output OFF. Physical PVX A/B/C LEDs independently show Disabled and no worker still changes either state. | |

## Suite 11 - Complete operator flow with injected failure checkpoints

**Description:** Traverse the regular BCON operator path as one continuous
workflow, then repeat it with a deliberate failure at each externally reachable
boundary. Earlier focused cases remain the detailed evidence for each row.

**Initial conditions:** Common initial conditions apply. Prepare the approved
serial fault fixture for sub-transaction boundaries, but prefer user actions
(power switch, cable removal, invalid entry, Arm switch, rapid stop) wherever
they can inject the intended failure safely and repeatably.

### BCON-11.1 - Nominal end-to-end operator flow

| Test steps | Expected results | Notes |
|---|---|---|
| 1. With BCON OFF, observe the independently powered `[Disabled, Disabled, Disabled]` PVX LEDs; power BCON, launch, connect, and wait for a complete snapshot. | PVX LEDs never change; connection and live all-off gate state become healthy from fresh firmware data. | |
| 2. While disarmed, toggle PVX A Enabled then Disabled with more than 150 ms between clicks. | Exactly the physical A LED changes twice; B/C, software arm, software interlocks, and gate state remain unchanged. | |
| 3. Software-arm, enable A/B software interlocks, enter valid A DC and B long-train configs, and select `Activate Enabled Beams`. | Admission/validation, staged writes, APPLY execution, and a strictly later complete poll occur in order. A/B start together and only then does the action reach `Command Success: ... \| FW: OK \| Status Poll: OK`. | |
| 4. Disable A's software interlock while active, then wait for confirmation. | A OFF is sent and A's local interlock remains Enabled until a later poll proves A mode OFF/output low; B continues independently. | |
| 5. Re-enable/configure A, enable C, and select `Activate`. | The new synchronized request uses only current enabled configs; A/B/C map to their own blue gate LEDs/LCD/cards without stale work. | |
| 6. Select Disable All, remain armed, re-enable only C and start/stop it, then request disarm. | Disable All clears interlocks after an all-off poll but leaves arm on. The fresh C action works once. Confirmed disarm later clears arm/interlocks; no action changes PVX. | |
| 7. Intentionally disconnect/reconnect, re-arm, enable only A, run one short manual A pulse, confirm A returns OFF, disarm, and quit normally. | Disconnect/reconnect clears queues; the fresh arm admits only the new manual request; the pulse finishes once; quit releases the port with gates OFF. No PVX toggle is replayed or inferred. | |
| 8. Relaunch, reconnect, explicitly leave every physical PVX LED Disabled, confirm gate all-off/disarmed, and preserve logs. | The full nominal flow ends with distinct verified gate and PVX states and a complete chronological evidence chain. | |

### BCON-11.2 - Failure injected at every regular-flow boundary

For each row, restore the common baseline, follow BCON-11.1 up to the named
checkpoint, inject the failure, record physical/UI/log chronology, recover with
fresh state plus an explicit operator action, and verify nothing failed or
pending replays.

| Checkpoint and injection | Required result | Notes |
|---|---|---|
| Connect: BCON power OFF, BCON-side serial removed, adapter absent/busy, or loss during settle. | Connection remains red/failed with no worker leak or replay; PVX LEDs stay visible and unchanged. | |
| PVX toggle: disconnected BCON, BCON power OFF, stale-green broken link, or second click inside 150 ms. | A definite failed/rejected attempt changes no physical PVX LED and is never queued. A response-lost attempt is explicitly indeterminate until the LED is observed; retry uses that observed state. | |
| Software arm: request while disconnected. | Arm remains false and dependent controls stay gated; reconnect alone does not arm. | |
| Local configuration/admission: blank, nonnumeric, out-of-range duration/count, mode OFF, or no enabled channel. | Validation blocks before any staged write/APPLY and all gate/PVX physical states remain unchanged. | |
| First, middle, or last stage; terminal APPLY; executed diagnostic: remove serial at each boundary. | Remaining batch work is suppressed as appropriate, failure stays attributable, fail-closed all-off is attempted, and no orphaned stage can activate later. | |
| Firmware OK before eligible poll: remove serial after `FW: OK`. | Operation times out/ends unknown without `Status Poll: OK`; later polling reconciles hardware but cannot retroactively complete it. | |
| Second normal action while one is pending. | Second action is rejected/busy and cannot steal the first operation token. | |
| Active software-interlock disable: remove serial before channel OFF. | Local interlock remains Enabled until a new confirmed recovery; watchdog OFF is not command success. | |
| Disable All or disarm: remove serial immediately before selection. | No false all-off/disarm confirmation or premature deferred-state clearing; hardware fallback and later recovery remain distinct. | |
| E-stop: fail both redundant attempts in one iteration, then fail exactly one of the two in another iteration where fixture timing permits. | Both attempt paths remain evident; any one failure is preserved even if the other attempt/poll proves gates OFF. | |
| Physical Arm trip or watchdog expiry during active output. | Firmware gates go/stay OFF and cannot resume without a fresh command; PVX LEDs are unchanged. | |
| Sustained serial loss, BCON power loss, USB loss, or abnormal host exit. | Physical gate truth follows immediate power loss or watchdog; dashboard marks stale/unknown before reconciliation; no command/PVX toggle replays. | |
| Recovery and final restoration. | New confirmed Disable All/disarm establishes gate safety; separate successful PVX toggles establish `[Disabled, Disabled, Disabled]`; logs retain every earlier failure. | |

## Completion Criteria

The Beam Pulse subsystem passes when every in-scope UI control is exercised;
A/B/C are correctly mapped across Main Control, Beam Pulse, BCON LCD, and blue
gate LEDs; all manual-mode and watchdog limits are validated; physical Arm Beams,
power, BCON-side serial, and laptop-adapter faults reach a clear safe or
explicitly uncertain state; all-off confirmation defeats stale queued writes;
and reconnect/restart never replays a prior output command.

Any of the following is a defect: output after a confirmed all-off; a rejected
or partial staged request activated by a later unrelated apply; a dashboard
OFF/healthy claim while physical gate state is unknown or visibly HIGH; a
queued request described as firmware-confirmed; suppressed/misleading safety
logs; an unannounced COM-update limitation; a startup file that crashes instead
of falling back; a shutdown hang or leaked serial owner; a successful PVX
toggle that does not invert exactly its matching physical enable LED; a
definite failed or non-toggle action that changes any PVX LED; or any
discrepancy among the latest fresh gate UI snapshot, action line, durable log,
LCD, blue gate LEDs, and separately observed physical PVX LEDs.

The plan is complete only after the approved configuration files and working
directories are restored; watchdog is confirmed 1500 ms; BCON is
connected and disarmed with all modes/output OFF and Main Control software
interlocks Disabled; every blue gate-output LED is dark; every BCON Output
cable remains disconnected from every PVX pulser; all three DB15 toggle cables
are correctly attached; and the independently powered, physically observed PVX
A/B/C enable LEDs are `[Disabled, Disabled, Disabled]`. CCS remains OFF and no
high-voltage supply has been enabled from the Knob Box.
