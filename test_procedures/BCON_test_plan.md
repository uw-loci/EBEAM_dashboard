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
`CH A/B/C`, `Beam A/B/C`, `Activate Enabled Beams`, and `Disable All Beams`.
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

## Safety Considerations

- **Disconnect every pulser cable from every BCON output before testing. No
  pulser cable may be connected to a BCON output during any case.** Verify this
  physically.
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
- The blue BCON A/B/C LEDs indicate gate-output level, not channel-enable
  state. The LCD also does not display channel-enable state. Do not infer an
  enabled external pulser from either indication.
- Use pulse widths of at least 1000 ms when a person must verify an LED or LCD
  transition.
- Back up `usr/usr_data/com_ports.json`,
  `usr/usr_data/main_control_config.json`, pane-state data, and test configuration
  files before manipulating them. Restore approved files after each suite.
- After any rejected, interrupted, or race-condition command, issue a confirmed
  `Disable All Beams` while communication is healthy or power-cycle BCON. Do
  not continue until all blue output LEDs are off and the LCD shows every
  channel `OFF` with `O:0`.

## Outline

1. Safety baseline, normal startup, and UI inventory
2. Connection lifecycle and watchdog controls
3. Software arming and channel-enable controls
4. Manual channel configuration, modes, and validation
5. Multi-channel activation, all-off, E-stop, and command races
6. Physical Arm Beams interlock and firmware safety recovery
7. BCON power, serial, adapter, and stale-connection failures
8. Startup, configuration-file, and COM-port resilience
9. Logging, acknowledgements, and semantic consistency
10. Shutdown, restart, and interaction stress

Unless a case states otherwise, begin with all Safety Considerations satisfied;
BCON production firmware installed; BCON powered; the BCON-side RS-485 cable
and laptop USB adapter connected; the correct `BeamPulse` COM port selected;
the physical Arm Beams switch ON; and BCON connected with its 1500 ms default
watchdog. Begin disarmed, with all three channel enables disabled, all requested
and active modes OFF, and all blue output LEDs dark.
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
| 1. Physically trace BCON channels A, B, and C and verify that no pulser cable is connected to any BCON output. | All three BCON outputs are visibly unterminated; no downstream pulser can receive a gate signal. | |
| 2. Verify CCS is OFF, every high-voltage supply is disabled, and no high-voltage supply can be enabled by the Knob Box during this plan. | CCS and all high-voltage supplies remain OFF; the test can proceed without energized beam hardware. | |
| 3. Verify the Knob Box Logic Arduino Override from the URL in Safety Considerations is installed, then place the physical Arm Beams switch ON. | The override supplies the active-high Arm Beams interlock signal; no high-voltage enable signal is asserted. | |
| 4. Start the dashboard, select the correct `BeamPulse` COM port, and submit the startup dialog. | The dashboard opens and starts one BCON auto-connect attempt. No Beam Pulse initialization exception occurs. | |
| 5. Before the 4.5 s settle interval ends, open Main Control > Config and uncheck the three excluded settings and both BCON/Knob Box HV-off log-suppression settings. | All five check controls are unchecked before BCON is declared connected. The excluded guards remain inactive, and BCON/Knob Box messages are not suppressed while the HV subpanel is off. | |
| 6. Set the file-log level to `VERBOSE` and verify the Messages recording control indicates ON with a green indicator. | File logging is active and can capture all BCON and Knob Box levels for the rest of the case. | |
| 7. Wait for the 4.5 s firmware settle interval and the first complete register poll. | The BCON indicator becomes green, the button reads `Disconnect`, and the safety label reads `Interlock: ok \| Watchdog: ok`. | |
| 8. Compare the Beam Pulse cards with the BCON LCD and blue LEDs. | A/B/C map one-to-one; each card shows `Status: OFF \| O:0` and `Remaining: 0`; the LCD shows all channels OFF; all blue LEDs are dark. | |
| 9. Inspect Main Control and the session log. | Beam Pulse is disarmed; all CH buttons say Disabled; Beam A/B/C buttons are disabled and OFF; the log identifies the selected port and one successful connection cycle without a Beam Pulse/BCON-tagged error or duplicate poll worker. | |

### BCON-1.2 - Beam Pulse and Main Control operator-surface inventory

**Description:** Verify that all in-scope controls are present, correctly gated,
and usable without layout corruption.

**Initial conditions:** BCON-1.1 passed and the system remains connected,
disarmed, and idle.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Scroll through Beam Pulse and open `Manual Control`. | The connection indicator, interlock/watchdog label, watchdog entry and Set button, and three complete channel cards remain visible and aligned. | |
| 2. Inspect the default A/B/C manual values. | Each mode is `PULSE`, duration is `100`, count is `1`, and count is disabled for single-pulse mode. | |
| 3. Inspect Main Control > Main. | `ARM BEAMS`, `E-STOP: BEAMS & CCS`, CH A/B/C, Beam A/B/C, `Activate Enabled Beams`, `Disable All Beams`, and four Beam Pulse status/action lines are present. | |
| 4. Verify the initial button gating. | `Disable All Beams`, E-stop, and `ARM BEAMS` are usable; CH, Beam A/B/C, and Activate controls that require arming are disabled as designed. | |
| 5. Switch tabs, scroll, resize, maximize/restore, and return to the baseline view. | Controls remain associated with the correct channel; no duplicate widgets, clipped safety state, Tk exception, or state change occurs. | |

## Suite 2 - Connection lifecycle and watchdog controls

**Description:** Exercise every Beam Pulse connection/watchdog action and prove
that requested, applied, rejected, and disconnected states are distinguishable.

**Initial conditions:** Common initial conditions apply. Preserve the log from
each case and restore the watchdog to 1500 ms before leaving the suite.

### BCON-2.1 - Intentional disconnect and reconnect while idle

**Description:** Verify confirmed all-off, local-state clearing, watchdog expiry,
and clean reconnection for an operator-requested disconnect.

**Initial conditions:** BCON is connected, disarmed, and idle.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Select `Disconnect` in Beam Pulse. | Pending writes are cleared, firmware confirms `ALL_OFF`, the serial port closes, the indicator turns red, and the button reads `Reconnect`. | |
| 2. Inspect Beam Pulse and Main Control immediately. | Software arm, local output state, and all channel-enable mirrors are false. | |
| 3. Observe BCON without reconnecting for longer than 1500 ms. | BCON remains powered; all LEDs stay dark; LCD changes to `WDG:NO` while `INT:OK` remains. | |
| 4. Inspect the log. | The log distinguishes firmware `ALL_OFF` confirmation, intentional user disconnect, and driver disconnect. | |
| 5. Select `Reconnect` once. | The button is disabled and shows `Connecting...` during the attempt; one connection worker opens the configured port. | |
| 6. Wait through settle and one complete poll. | The indicator returns green, LCD returns to `WDG:OK INT:OK`, all channels remain OFF/disabled, and no prior mode or queued command replays. | |

### BCON-2.2 - Reconnect with a valid COM port but no responding BCON

**Description:** Distinguish a present serial adapter from a responding BCON
firmware endpoint.

**Initial conditions:** Intentionally disconnect through the UI. Leave the
laptop USB adapter connected so its COM port still exists.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Remove the BCON-side RJ45 serial cable and select `Reconnect`. | The COM port opens, the button shows the connecting state, and the driver waits through its firmware settle interval. | |
| 2. Wait for the connection attempt to finish. | The register validation read fails, the indicator remains red, the button returns to `Reconnect`, and the dashboard remains responsive. | |
| 3. Inspect the log and BCON. | The log reports a connection/test-read failure rather than `BCON connected`; BCON remains powered, LEDs off, and eventually `WDG:NO`. | |
| 4. Restore the BCON-side serial cable and select `Reconnect`. | One clean connection succeeds. | |
| 5. Repeat steps 1-4 with BCON power removed instead of the BCON-side serial cable. | The dashboard again reports no responding firmware, does not hang, and reconnects cleanly only after power is restored. | |

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

**Initial conditions:** No pulser cables are attached. BCON is connected at the
1500 ms watchdog, software armed, CH A enabled, and Channel A is visibly running
DC.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Confirm blue A LED is solid ON and LCD/UI report A DC before changing the watchdog. | The active-output baseline is fresh and unambiguous. | |
| 2. Set watchdog to `50` ms and watch the blue A LED and LCD continuously. | Firmware accepts `R0=50`, then the sub-cadence watchdog forces active A low, clears its mode/enable, and prevents automatic reassertion. | |
| 3. Compare the LCD, Beam Pulse safety label/card, Main Control lines, and logs for several host cycles. | Every surface eventually reflects OFF. Any watchdog expiry missed because polling itself feeds the watchdog, oscillating safety label, stale green output, or missing shutoff record is captured as a defect. | |
| 4. Select `Disable All Beams`, set watchdog to `1500`, and wait for confirmation. | A confirmed all-off clears any latent request; normal `WDG:OK` operation returns and all LEDs remain dark. | |

### BCON-2.6 - Intentional disconnect while outputs are active

**Description:** Verify that the healthy-link Disconnect action obtains confirmed
all-off before closing the serial port.

**Initial conditions:** No pulser cables are connected. BCON is connected and
armed at the 1500 ms watchdog; A DC and B long PULSE_TRAIN are active.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Select `Disconnect` while A/B are active. | The driver confirms `ALL_OFF` before closing; blue A/B LEDs go dark, the output/enable mirrors clear, software arm resets, and the indicator turns red. | |
| 2. Inspect the action/event lines in Main Control and the log. | They distinguish confirmed all-off from serial close and intentional disconnect; no stale ON or unconfirmed shutdown wording remains. | |
| 3. Reconnect and wait for fresh registers. | A/B/C remain OFF/disabled and no pre-disconnect command replays. | |

## Suite 3 - Software arming and channel-enable controls

**Description:** Verify the software permission gate and explicit firmware-backed
channel-enable controls without confusing them with the physical interlock or
gate-output LEDs.

**Initial conditions:** Common initial conditions apply.

### BCON-3.1 - Software arm and confirmed disarm semantics

**Description:** Show that arming changes permission only and that disarming is
gated on confirmed BCON all-off.

**Initial conditions:** BCON is connected, physical Arm Beams is ON, and the
system is disarmed and idle.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Select the Arm Beams toggle. | The toggle changes to its armed/ON image or `BEAMS ARMED` text; CH A/B/C and Activate become usable; Beam A/B/C remain disabled because their channels are not enabled. | |
| 2. Inspect BCON LEDs/LCD and the Beam Pulse cards. | Arming alone sends no hardware arm, mode, enable, or output command. All channels remain OFF and all blue LEDs remain dark. | |
| 3. Inspect the action line and log. | They identify software-only arming and do not claim that a channel, pulser, CCS, or high-voltage supply was enabled. | |
| 4. Select the armed/ON toggle again. | Disarm obtains a confirmed `ALL_OFF`, clears output and channel-enable state, then changes the toggle to its unarmed/OFF image or text. | |
| 5. Repeat arm/disarm while already idle. | The operation is idempotent, produces coherent acknowledgements, and leaves no LED, enable, mode, or queued write active. | |

### BCON-3.2 - Arm request while BCON is disconnected

**Description:** Verify that an open, responding BCON connection is required for
software arming.

**Initial conditions:** Intentionally disconnect BCON through Beam Pulse.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Select the Arm Beams toggle. | Arming fails; the toggle remains visually unarmed/OFF (or reads `ARM BEAMS`); CH, Beam, and Activate controls remain disabled. | |
| 2. Inspect the action line and log. | Both state `Failed to arm beams` and identify the serial port/device connection reason; no success follows. | |
| 3. Reconnect BCON and wait for a fresh healthy snapshot. | Reconnection alone does not arm, enable, or activate any channel. | |
| 4. Select the Arm Beams toggle. | Software arming now succeeds exactly once and the control becomes visually armed/ON. | |
| 5. Disarm and confirm all-off before ending the case. | The system returns to the common idle state. | |

### BCON-3.3 - Independent CH A/B/C enable mapping

**Description:** Verify each channel-enable control, Beam-button gating, and the
absence of a false gate-output indication.

**Initial conditions:** BCON is connected, armed, idle, and all CH states are
disabled.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Select `CH A: Disabled`. | Only CH A becomes Enabled; only Beam A becomes usable; B and C remain disabled. No blue gate LED turns on and LCD modes remain OFF. | |
| 2. Select `CH B: Disabled`. | Only CH B additionally becomes Enabled and Beam B becomes usable; A is unchanged and C remains disabled. | |
| 3. Select `CH C: Disabled`. | CH C additionally becomes Enabled and all three Beam buttons are usable; no output mode starts. | |
| 4. Disable CH B. | Only CH B and Beam B return to disabled/OFF appearance; A and C remain enabled. | |
| 5. Disarm. | Confirmed all-off clears all three channel enables, disables all Beam buttons, and all LEDs/LCD rows are OFF. | |

### BCON-3.4 - Disabling a channel while it is active

**Description:** Verify that disabling an active channel also commands its gate
mode OFF and cannot affect another channel.

**Initial conditions:** BCON is connected and armed. CH A and CH B are enabled;
A is configured DC, B is configured for a long pulse, and C is disabled.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Turn Beam A ON in DC and Beam B ON with a pulse of at least 5000 ms. | Blue LEDs A and B turn on; the corresponding LCD/UI rows report the correct independent modes. | |
| 2. Select `CH A: Enabled` to disable A. | Firmware confirms the A enable change and queues A OFF; A's blue LED goes dark and its mode becomes OFF. B continues its configured pulse without restart or interruption. | |
| 3. Inspect Main Control and Beam Pulse after a fresh poll. | CH A is Disabled, Beam A is disabled/OFF, CH B remains Enabled, and B's remaining/output state agrees with hardware. | |
| 4. Disable CH B while its pulse is still active. | B transitions OFF and its blue LED goes dark; no later queued apply reactivates A or B. | |
| 5. Select `Disable All Beams` and disarm. | Confirmed all-off restores the common idle state. | |

## Suite 4 - Manual channel configuration, modes, and validation

**Description:** Exercise every channel-card control, all supported modes, limit
boundaries, live locks, and one-to-one physical/UI mapping.

**Initial conditions:** Common initial conditions apply. Arm and enable only the
channel required by each case. Use `Disable All Beams` between accepted boundary
commands so a long valid pulse cannot carry into the next step.

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
| 5. Arm, enable CH A, configure A for a long DC or pulse, and select Beam A. | Live hardware status appears in `Status`/`Remaining` but does not overwrite the selected next-command mode or values. | |
| 6. Stop A, disable all, and disarm. | The intended configuration remains available after controls unlock; hardware status returns OFF and the common idle state is restored. | |

### BCON-4.2 - Pulse-duration validation boundaries

**Description:** Verify whole-millisecond limits before any partial command is
queued.

**Initial conditions:** BCON is connected and armed; CH A is enabled; Channel A
is in `PULSE` but not currently outputting; B and C are disabled and OFF.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Clear A duration and select `Beam A OFF`. | An `Invalid Configuration` dialog says duration must be a whole number of ms; no A LED/mode/write starts. | |
| 2. Enter `0` in duration and select Beam A. | The dialog says duration must be 1-60000 ms; no output command is queued. | |
| 3. Enter `1` in duration and select Beam A. | The command is accepted as one 1 ms pulse and completes safely; it may be too short to see, but register/log state returns OFF without an error. | |
| 4. Enter `60000` in duration, select Beam A, wait for firmware acceptance, then immediately select `Disable All Beams`. | The upper boundary is accepted; confirmed all-off terminates it and no stale 60 s pulse reappears. | |
| 5. Enter `60001` in duration and select Beam A. | The value is rejected before a BCON write; A remains OFF. | |
| 6. Enter a very large digit string and select Beam A. | The value is rejected without overflow, UI freeze, truncated hardware value, or partial write. | |
| 7. Restore duration `1000`, disable all, and disarm. | The system returns to a valid idle configuration. | |

### BCON-4.3 - Pulse-train count validation boundaries

**Description:** Verify the train-only lower bound, firmware upper bound, and
single-pulse count normalization.

**Initial conditions:** BCON is connected and armed; CH A is enabled; A is set to
`PULSE_TRAIN` mode with duration 100 ms, but not actively outputting.

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

**Initial conditions:** BCON is connected and armed. Begin with all CH states
disabled and all modes OFF.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Enable CH A only, configure A as DC, and select Beam A. | Only blue A is solid on; LCD A reads `DC`, `O:1`, `R:0`; Beam Pulse A reads DC/O:1; Main Control A shows ON. B/C remain OFF. | |
| 2. Select Beam A again to turn it OFF. | Only A goes OFF; the blue A LED darkens and all A displays reconcile to OFF. | |
| 3. Configure A as PULSE, duration 1500 ms, and select Beam A. | Only A starts high, reports PULSE with remaining 1 when sampled, then automatically returns OFF after its high interval. | |
| 4. Configure A as PULSE_TRAIN, duration 1000 ms, count 3, and select Beam A. | Only A alternates 1 s high/1 s low; remaining falls 3 to 0 at falling edges; it finishes OFF and unlocks its card. | |
| 5. Disable CH A, enable CH B, configure B as DC, and select Beam B. | Only blue B is solid on and every B display reports DC; A/C remain OFF. | |
| 6. Select Beam B OFF, then run B as PULSE at 1500 ms. | Only B pulses once and automatically returns OFF. | |
| 7. Run B as PULSE_TRAIN at 1000 ms x 3. | Only B alternates, remaining falls to zero, and B finishes OFF. | |
| 8. Disable CH B, enable CH C, configure C as DC, and select Beam C. | Only blue C is solid on and every C display reports DC; A/B remain OFF. | |
| 9. Select Beam C OFF, then run C as PULSE at 1500 ms. | Only C pulses once and automatically returns OFF. | |
| 10. Run C as PULSE_TRAIN at 1000 ms x 3. | Only C alternates, remaining falls to zero, and C finishes OFF. | |
| 11. Compare status while a channel is DC or in a long train. | Its mode/duration/count widgets are locked while running; DC is treated as active even with remaining 0. | |
| 12. Wait for automatic completion or select the Beam button OFF. | The channel unlocks only after a fresh OFF status; no stale ON color or remaining count survives. | |
| 13. Disable all and disarm. | All channels and enables return to the common idle state. | |

### BCON-4.5 - Manual mode OFF selected from a Beam A/B/C button

**Description:** Detect contradictory `ON` wording or color when the selected
manual command is actually OFF.

**Initial conditions:** BCON is connected and armed; CH A is enabled; A is
physically OFF.

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

**Initial conditions:** Common initial conditions apply. No pulser cables are
connected; use 1000 ms or longer pulses for visual synchronization checks.

### BCON-5.1 - Activate Enabled Beams filtering and synchronized start

**Description:** Start a mixed configuration, prove disabled channels are
skipped, and compare simultaneous gate edges.

**Initial conditions:** BCON is armed and idle. CH A and CH B are enabled; CH C
is disabled. Configure A DC, B PULSE_TRAIN at 1000 ms x 2, and leave C with an
intentionally invalid train count of 1.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Select `Activate Enabled Beams`. | A and B are validated and staged; disabled C is skipped without its invalid config blocking the action. | |
| 2. Observe the first A/B gate edge. | Blue A and B rise together from the single apply; C remains dark. | |
| 3. Observe B through completion while A remains DC. | B alternates and finishes OFF; A stays solid ON; C remains OFF. LCD, cards, and Main Control lines agree. | |
| 4. Inspect action text and logs. | The sent configuration names only A and B, records firmware apply execution order, and does not claim C ran. | |
| 5. Select `Disable All Beams`. | A immediately goes OFF after confirmed all-off; no channel reactivates. | |
| 6. Enable only CH C, configure C DC, and select Activate All. | Only C starts; A/B remain OFF, proving the one-enabled-channel path. | |
| 7. Disable all, enable A/B/C, give all three valid visible modes, and select Activate All. | All three valid enabled channels start from one synchronized apply and map to their own LEDs/status rows. | |
| 8. Select Disable All and disarm. | Confirmed all-off restores the common idle state. | |

### BCON-5.2 - Invalid enabled config aborts the whole activation

**Description:** Ensure validation is atomic from the operator's perspective.

**Initial conditions:** BCON is armed and all outputs OFF. Enable A, B, and C.
Configure A DC, B PULSE 1000 ms, and C PULSE_TRAIN count 1.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Select `Activate Enabled Beams`. | C validation fails with a clear dialog/action message; no A/B/C parameter, mode, or apply command is sent for this activation. | |
| 2. Watch all blue LEDs and LCD rows through two polls. | All three remain OFF; no partial A or B start occurs. | |
| 3. Disable CH C without fixing its invalid config and select Activate again. | C is skipped; valid A and B start as configured. | |
| 4. Select `Disable All Beams`, then disable CH A and CH B so none are enabled. | Firmware confirms all-off and all CH states become Disabled. | |
| 5. While still armed, select Activate. | The action is skipped with `no enabled channels`; no write or LED transition occurs and channel status lines are not falsely changed. | |
| 6. Disarm. | The common idle state is restored. | |

### BCON-5.3 - Disable All Beams active, idle, armed, and unsafe

**Description:** Verify immediate confirmed all-off independently of software
arm and firmware safety state.

**Initial conditions:** BCON is connected and armed. Enable all channels and
start A DC, B long PULSE, and C long PULSE_TRAIN.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Select `Disable All Beams` while all three are active. | The driver invalidates older queued writes, firmware executes `ALL_OFF`, all blue LEDs go dark, active/staged modes and enables clear, and status is cleared only after confirmation. | |
| 2. Inspect software arm state. | Beam Pulse remains software armed; CH states are Disabled after fresh polling, and Beam A/B/C cannot start until re-enabled. | |
| 3. Select `Disable All Beams` again while idle. | A second confirmed all-off is safe and idempotent; no false error or output transition occurs. | |
| 4. Turn physical Arm Beams OFF and select `Disable All Beams`. | `ALL_OFF` executes even in SAFE_INTERLOCK, clears any latent modes/enables, and leaves every LED off. | |
| 5. Turn physical Arm Beams ON and disarm. | Safety returns healthy without output; the common idle state is restored. | |

### BCON-5.4 - Output command followed immediately by all-off

**Description:** Stress the driver's write epoch so a queued or dequeued ON
cannot execute after confirmed all-off.

**Initial conditions:** BCON is connected and armed; all channels are enabled
and configured DC; all outputs are initially OFF.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Select `Activate Enabled Beams` and immediately select `Disable All Beams` before the next poll cycle if possible. | All-off invalidates/clears pre-stop queued writes and is synchronously confirmed. | |
| 2. Observe all LEDs/LCD rows for at 5 seconds. | No channel turns on after the all-off confirmation; final modes/enables are all zero. A brief pre-confirmation edge, if any, is timestamped. | |
| 3. Repeat with a single `Beam A` ON click immediately followed by Disable All. | A cannot reassert after confirmation; B/C remain unaffected. | |
| 4. Repeat with rapid A, B, and C ON clicks followed by Disable All. | No stale write from any channel survives the all-off epoch. Logs may report stale writes dropped but never report them executed afterward. | |
| 5. Disarm. | The common idle state is restored. | |

### BCON-5.5 - E-stop BCON portion

**Description:** Verify only the in-scope confirmed BCON all-off and Beam Pulse
disarm portion of the mixed-system E-stop.

**Initial conditions:** CCS and every high-voltage supply are verified OFF. BCON
is armed with A DC, B long PULSE, and C long PULSE_TRAIN active.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Select `E-STOP: BEAMS & CCS`. | Main Control requests immediate confirmed BCON all-off; all blue LEDs go dark and all active/staged modes/enables clear. | |
| 2. Observe Beam Pulse/Main Control state after confirmation. | Beam Pulse is disarmed; Beam and CH controls reset to OFF/Disabled; the action line states that all beams were disabled. | |
| 3. Inspect BCON acknowledgements and log. | All-off/disarm acknowledgements are coherent and no earlier queued ON executes later. Duplicate shutdown requests, if present, do not cause a false failure or re-enable. | |
| 4. Verify scope boundaries. | CCS and all high-voltage supplies are still OFF. Their internal integration behavior is not evaluated or changed for this case. | |
| 5. Press E-stop again while BCON is idle/disarmed. | The BCON portion remains safely idempotent and the dashboard stays responsive. | |

## Suite 6 - Physical Arm Beams interlock and firmware safety recovery

**Description:** Exercise the active-high Knob Box interlock before, during, and
after commands, including latent staged-mode and unsafe-enable hazards.

**Initial conditions:** Common initial conditions apply. The required Logic
Arduino Override is installed. Keep BCON serial communication connected unless
a step says otherwise.

### BCON-6.1 - Interlock OFF at connection and output rejection

**Description:** Distinguish a healthy transport connection from firmware
permission to drive a gate.

**Initial conditions:** Turn physical Arm Beams OFF before starting or
reconnecting the dashboard. All channels are OFF.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Connect BCON and wait for a complete poll. | The connection indicator is green, while the safety label reads `Interlock: locked`; LCD reads `INT:NO`; every blue LED remains off. | |
| 2. Select the Arm Beams toggle. | Software arming succeeds; it does not change LCD, interlock, or output. | |
| 3. Configure A for DC in Manual Control, attempt to enable CH A, then select `Activate Enabled Beams`. | CH A is rejected or immediately cleared while the interlock is unsafe; Activate reports no eligible channel. No blue A output is allowed. | |
| 4. Compare the log, action line, Beam Pulse card, and LCD after two polls. | The unsafe manual request and its blocked/rejected result are traceable; A is OFF/O:0 everywhere and no success message overwrites the safety result. | |
| 5. Select `Disable All Beams` before turning the switch ON. | Confirmed all-off clears the rejected staged request and any enable state even while interlock is unsafe. | |
| 6. Turn Arm Beams ON. | LCD/dashboard return to interlock OK without automatically enabling or starting A. | |
| 7. Disarm. | The common idle state is restored. | |

### BCON-6.2 - Interlock trip during active DC and pulse train

**Description:** Verify immediate physical shutoff, register reconciliation,
abort semantics, and no automatic restart.

**Initial conditions:** BCON is connected and armed. Enable A and B; run A DC
and B PULSE_TRAIN with 2000 ms duration and at least 5 pulses.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Confirm A and B are in a high phase, then turn physical Arm Beams OFF. | Firmware immediately stops timers and forces blue A/B low; C stays low. LCD updates to `INT:NO` and all channel modes OFF within its refresh behavior. | |
| 2. Wait for one complete dashboard snapshot. | Beam Pulse cards and Main Control lines show A/B OFF, remaining cleared, and channel enables Disabled. The connection remains green because serial communication is healthy. | |
| 3. Inspect software arm and controls. | Software arm remains armed as a separate permission state; no physical output or enable silently returns. | |
| 4. Inspect the log. | One CRITICAL safety-transition entry identifies `interlock locked` because output was active; repeated polls do not flood identical entries. | |
| 5. Turn physical Arm Beams ON and observe for two polls without another command. | Interlock returns OK, but A/B do not reassert and all LEDs stay dark. Recovery is visible and traceable; absence of a recovery log is recorded as a semantic gap. | |
| 6. Issue a fresh enable and output command to A. | Only the freshly commanded A may start; B remains OFF. | |
| 7. Disable all and disarm. | The common idle state is restored. | |

### BCON-6.3 - Interlock trip while idle and switch bounce

**Description:** Verify warning severity, bounded logs, and immunity to repeated
hardware edges.

**Initial conditions:** BCON is connected, armed, and idle with all CH states
disabled.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Turn physical Arm Beams OFF while idle. | LCD shows `INT:NO`, the dashboard shows locked, all LEDs remain off, and the safety transition is WARNING rather than CRITICAL. | |
| 2. Turn it ON, then cycle OFF/ON five times at a deliberate observable rate. | Each sampled state is physically safe; no mode, enable, or output appears; the UI remains responsive. | |
| 3. Inspect Knob Box and BCON logs. | Arm signal transitions use consistent ON/OFF semantics; safety entries correspond to observed unsafe edges without per-poll flooding or reversed wording. | |
| 4. End with the switch ON and wait for two polls. | LCD and dashboard stabilize at `INT:OK`; every channel remains OFF/disabled. | |
| 5. Disarm. | Confirmed all-off returns the common idle state. | |

### BCON-6.4 - Channel-enable attempt while already unsafe

**Description:** Detect an enable latch that can be set while firmware is held
in SAFE_INTERLOCK.

**Initial conditions:** BCON is connected and software armed; all outputs and
enables are OFF. Turn physical Arm Beams OFF and wait until locked is displayed.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Select `CH A: Disabled` while interlock remains OFF. | A safety-preserving implementation rejects or immediately clears the enable; CH A must not remain enabled through an unsafe state. | |
| 2. Wait for two polls and compare Main Control with firmware-backed status. | CH A and Beam A remain Disabled/OFF. Any accepted/persistent enable while `INT:NO` is a defect. | |
| 3. Turn physical Arm Beams ON without sending an output command. | No gate output starts. CH A must not emerge enabled solely because of an unsafe-state write. | |
| 4. Select `Disable All Beams` and disarm. | Confirmed all-off clears any unexpected latch and restores the common idle state. | |

### BCON-6.5 - Unsafe manual request must not activate on a later APPLY

**Description:** Verify that a manual output request blocked by an unsafe
interlock cannot be applied by a later, unrelated manual action.

**Initial conditions:** No pulser cables are attached. BCON is connected and
software armed with all channels OFF. Configure A and B for DC in Manual
Control.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Turn physical Arm Beams OFF and wait for `INT:NO`. | Firmware is stably SAFE_INTERLOCK; all LEDs are off. | |
| 2. Attempt to enable CH A and select `Activate Enabled Beams`. | A remains physically OFF and the unsafe manual request is explicitly blocked or rejected. It must not remain capable of later activation. | |
| 3. Turn physical Arm Beams ON and wait for `INT:OK` without issuing all-off. | A remains OFF; recovery alone does not apply the blocked request. | |
| 4. Enable CH B and select `Activate Enabled Beams` to issue a fresh, unrelated manual apply. | Only B may turn on. Blue A must remain dark and A must remain OFF in LCD/UI. If A also starts, record a critical latent-state defect. | |
| 5. Select `Disable All Beams` immediately. | Confirmed all-off turns every LED off and clears all staged/active modes and enables. | |
| 6. Turn Arm OFF, attempt to enable CH A and select Activate, restore Arm, enable only CH B, and select Activate. | The Main Control apply for B starts only B; the earlier blocked A request remains incapable of activation. | |
| 7. Select Disable All and disarm. | Confirmed all-off clears every mode/enable and restores the common idle state. | |

## Suite 7 - BCON power, serial, adapter, and stale-connection failures

**Description:** Compare physical truth with dashboard state across short and
sustained transport loss, power loss, invalid handles, and actions attempted
during the driver's ten-failure detection window.

**Initial conditions:** Common initial conditions apply. Record the configured
watchdog and original Windows COM number. Unless stated otherwise, use the
default 1500 ms watchdog and a DC output so physical gate state is unambiguous.

### BCON-7.1 - BCON-side two-second serial interruption

**Description:** Verify recovery from a deliberate two-second link interruption
that remains below the configured watchdog interval.

**Initial conditions:** BCON is connected and armed; set and confirm the
watchdog at `5000 ms`; CH A is enabled and A is running DC. The USB adapter
remains connected to the laptop.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Remove the BCON-side serial cable for 2 seconds, then restore it. | Because the interruption is below the 5000 ms watchdog, blue A remains solid ON. At most a bounded communication error appears, and a later complete poll recovers without a false disconnect. | |
| 2. Verify the live state after two successful polls. | Connection remains green; A remains DC only if the firmware watchdog never expired; LCD, card, status line, and LED agree. | |
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
| 2. Observe BCON after approximately 1500 ms. | LCD shows `WDG:NO`; blue A/B go dark; timers, active/staged modes, and channel enables clear. | |
| 3. Observe the dashboard before its tenth failed poll. | It must indicate degraded/stale communication rather than silently presenting the last green/ON state as current. Any green healthy indication with no stale warning is a defect. | |
| 4. Wait for ten consecutive failed polls. | The driver auto-disconnects, the indicator turns red, software arm/output/enable mirrors clear, and the button reads `Reconnect`. | |
| 5. Inspect Beam Pulse card/safety text after red disconnect. | No stale mode, remaining count, or `Interlock/Watchdog: ok` text is presented as live. Stale card/safety text is recorded as a defect. | |
| 6. Restore the cable without selecting Reconnect. | BCON remains watchdog-safe and the stopped driver does not falsely turn green or replay writes automatically. | |
| 7. Select `Reconnect` and wait for fresh registers. | Connection and watchdog recover; all channels remain OFF/disabled; no prior DC/train request replays. | |

### BCON-7.3 - Operator commands during the stale-green failure window

**Description:** Detect optimistic action status while the driver still believes
a physically broken link is connected.

**Initial conditions:** BCON is connected and armed; CH A is enabled and A is
running DC at the default watchdog.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Remove the BCON-side serial cable and, before ten poll failures, select Beam A OFF. | The queued OFF cannot reach BCON. The dashboard must not describe it as firmware-confirmed OFF merely because it entered the queue. | |
| 2. Watch the blue A LED until the watchdog expires. | A may remain physically ON until the 1500 ms watchdog trip, then turns OFF from firmware safety rather than the failed Beam OFF command. | |
| 3. While the indicator is still green, attempt a CH toggle and a Beam B ON command. | Immediate CH write fails and is reported. Any merely queued Beam command is later reported failed/dropped; no lasting optimistic success is shown. | |
| 4. Select the armed/ON toggle to request disarm before auto-disconnect. | Because confirmed all-off cannot be obtained, disarm reports failure and does not falsely clear the armed/output state as confirmed. | |
| 5. Select `Disable All Beams` and then E-stop before auto-disconnect. | Each BCON all-off attempt reports unconfirmed/uncertain state. The log never says firmware confirmed a command it could not receive. | |
| 6. Wait for auto-disconnect, restore the cable, and reconnect. | Local state clears on disconnect, fresh firmware state is OFF after watchdog, and none of the failed-window commands replay. | |

### BCON-7.4 - BCON power removal and restoration

**Description:** Verify immediate physical de-energization and both early and
late dashboard recovery paths.

**Initial conditions:** BCON is connected and armed; A DC and C long train are
active. The laptop adapter remains powered and enumerated.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Shut off BCON power. | LCD/backlight and every blue LED go dark immediately. No downstream output exists because pulser cables are disconnected. | |
| 2. Observe the dashboard until the first error. | It does not invent a firmware interlock/overcurrent fault; it reports communication failure and marks retained data stale/unknown. | |
| 3. Restore BCON power before ten consecutive failures. | Firmware boots with gates, LEDs, and enables LOW. If the serial session survives, later full polling recovers without replaying the prior modes. | |
| 4. Wait for two successful snapshots. | Connection is healthy, all channels remain OFF/disabled, and the UI no longer shows stale A/C output. | |
| 5. Start A DC again, remove power, and leave it off through auto-disconnect. | Physical state goes dark immediately; after ten failures the dashboard turns red and disarms local state. | |
| 6. Restore power after auto-disconnect. | BCON boots safe and remains unconnected until the operator selects Reconnect. | |
| 7. Reconnect and inspect logs/state. | One clean connection occurs; no stale writes or duplicate poll workers appear; all modes/enables remain OFF. | |

### BCON-7.5 - Laptop USB adapter removal and COM reassignment

**Description:** Verify loss of the Windows serial device and recovery when it
returns on the same or a different COM number.

**Initial conditions:** BCON is connected and armed with A DC active. Record the
adapter's current COM number.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Remove the serial adapter cable from the testing laptop. | The COM handle becomes invalid; host writes/polls fail; BCON remains powered and shuts A off only when its watchdog expires. | |
| 2. Wait for driver auto-disconnect. | The indicator turns red after bounded failures; the log identifies serial/communication loss rather than a BCON interlock trip. | |
| 3. Reinsert the adapter and record its assigned COM number. | Windows enumerates the adapter. No output or channel enable appears on BCON. | |
| 4. Restart the test laptop. Launch the dashboard | Reconnection succeeds on that port and reads fresh all-off state. | |

### BCON-7.6 - Link or power loss during connect and confirmed shutoff

**Description:** Exercise removal at transaction boundaries without deadlock or
false confirmation.

**Initial conditions:** BCON is intentionally disconnected in the UI. Hardware
is initially powered and cabled.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Select Reconnect, then remove BCON power during the 4.5 s settle interval. | The attempt terminates as failed, the button returns to Reconnect, the UI remains responsive, and no orphan poll worker starts. | |
| 2. Restore power, reconnect, start A DC, and confirm its LED is on. | A runs normally from a fresh connection and command. | |
| 3. Remove the BCON-side serial cable immediately before selecting `Disconnect`. | The driver cannot confirm its pre-close ALL_OFF and explicitly logs reliance on the firmware watchdog; it never logs a false confirmation. | |
| 4. Observe A and LCD. | A turns off only when the watchdog expires; LCD shows `WDG:NO`. The dashboard is red/disarmed but does not assert the physical off time without evidence. | |
| 5. Restore the cable and reconnect. | Fresh state is all OFF/disabled and no pre-disconnect command replays. | |

### BCON-7.7 - Maximum watchdog exposes UI-versus-physical uncertainty

**Description:** Verify that dashboard auto-disconnect cannot be equated with
physical gate shutoff when the configured watchdog is 60000 ms.

**Initial conditions:** No pulser cables are connected. BCON is connected and
idle; set watchdog to 60000 ms and confirm the write. Arm, enable A, and run A
in DC.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Remove the BCON-side serial cable and keep BCON powered. | A can legitimately remain physically HIGH because the 60000 ms firmware watchdog has not expired. | |
| 2. Wait for ten host poll failures and driver auto-disconnect. | The indicator turns red and software-arm permission resets after roughly 5-7+ s, while blue A may still be solid ON. Hardware-derived mode/output/enable state becomes explicitly disconnected or unknown rather than being cleared as confirmed fact. | |
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
| 1. Launch with BCON powered, both cables present, and physical Arm Beams OFF. | Transport connects green; safety reports interlock locked; all outputs remain OFF; no mode/enables auto-apply. | |
| 2. Launch with BCON power OFF but the laptop adapter present. | The valid COM opens but Modbus validation fails after settle; the dashboard remains usable and red. Power restoration plus Reconnect recovers. | |
| 3. Launch with BCON powered but its BCON-side serial cable removed. | The result is a nonresponding-firmware connection failure; LCD eventually reads `WDG:NO`; restoring the cable plus Reconnect recovers. | |
| 4. Launch with the laptop adapter absent and its old COM saved. | Serial open fails clearly; inserting the adapter does not silently connect to another port. Reconnect succeeds only when the configured COM exists. | |
| 5. Begin launch with BCON off, then power it during the 4.5 s settle interval. | The outcome is deterministic: either validation succeeds after a complete boot or fails and requires one explicit Reconnect; no half-connected state or duplicate worker remains. | |
| 6. Launch with BCON previously left watchdog-safe or interlock-safe. | Connection feeds the watchdog and reports the current interlock; firmware boots/recovers with all gates and enables OFF and no old mode replay. | |

### BCON-8.6 - Other startup files and manual Beam Pulse availability

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

### BCON-8.7 - COM configuration save failure

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

**Initial conditions:** BCON is connected, armed, and CH A enabled. Configure A
DC and keep physical Arm Beams ON initially.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Turn Beam A ON normally. | The log/action chronology distinguishes request/sent from firmware `APPLY_STAGED_MODES executed`, includes command ordering, and appends an appropriate firmware OK acknowledgement. | |
| 2. Turn A OFF and wait for live OFF. | Queued OFF, executed apply, and register-backed OFF reconcile without contradictory final state. | |
| 3. Turn physical Arm Beams OFF and request A DC. | Any initial queued/sent status is followed by `rejected: UNSAFE_INTERLOCK`; the final action outcome remains failure and A remains physically OFF. | |
| 4. Remove the BCON-side serial cable, then request an action during the stale-green window. | Write/confirmation failure supersedes optimistic status; the log never invents an executed firmware action. | |
| 5. Restore/reconnect, enter watchdog `49`, and select Set. | Range rejection is logged without a later false `Set watchdog = 49 ms` success or hardware write. | |
| 6. Select Disable All, restore physical Arm ON, and disarm. | The final confirmed safe state is explicit and closes the chronology. | |

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

**Description:** Detect mixed snapshots, orphaned staging, and placeholder fields
being presented as real fault sensors.

**Initial conditions:** No pulser cables are connected. BCON is connected and
armed; A and B are enabled and configured DC but OFF.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Select Activate and remove the BCON-side serial cable immediately enough to interrupt the multi-register stage/apply operation. | The log identifies each failed write/command; the action is not treated as an atomic successful start if only part reached firmware. | |
| 2. Restore the cable before the watchdog if safely achievable and wait for fresh state. | The dashboard reads the actual firmware state. A partial staged mode does not silently appear as active or confirmed OFF. | |
| 3. Issue an unrelated fresh apply for only B. | Only B may start. If an orphaned A stage also starts, record a critical stale-stage defect. | |
| 4. Compare Beam Pulse A/B cards, Main Control lines, LCD rows, and blue LEDs after each fresh poll. | Each complete snapshot is internally consistent; no old remaining count or mixed pre/post-command state is presented as one live result. | |
| 5. Inspect any overcurrent/power/gated indications or logs. | Reserved firmware placeholders are not described as tested physical sensors or used to claim hardware health. | |
| 6. Select Disable All and disarm. | Confirmed all-off clears every possible partial stage and restores the common idle state. | |

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
| 3. Arm, enable A/B, run A DC and B long train, then press Ctrl+Q. | The same Quit confirmation appears while live status continues safely behind it. | |
| 4. Confirm quit. | Beam Pulse stops workers, attempts confirmed all-off, closes serial, cancels scheduled updates, and the application exits without hanging. All blue LEDs are off. | |
| 5. Relaunch immediately on the same COM. | The port is released, one auto-connect and one poll worker start, and BCON remains all OFF/disabled with no queued replay. | |
| 6. Repeat a confirmed idle shutdown with Ctrl+W. | The alternate shortcut uses the same one-shot cleanup and leaves the port reusable. | |

### BCON-10.2 - Quit during connect, active manual output, and communication fault

**Description:** Detect daemon/thread leaks and deadlocks at each long-running
boundary.

**Initial conditions:** Begin intentionally disconnected, with hardware ready.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Select Reconnect and confirm quit during the 4.5 s settle interval. | The dashboard closes in bounded time; the connecting thread observes shutdown, closes any serial handle, and does not later emit UI work into a destroyed window. | |
| 2. Relaunch, arm, enable CH A, configure A for DC, turn Beam A ON, then confirm quit. | BCON receives confirmed all-off before close when communication is healthy; A goes dark and no later manual command executes. | |
| 3. Relaunch, run A DC, remove the BCON-side serial cable, and confirm quit while poll errors are active. | Shutdown does not deadlock. Failure to confirm all-off is logged explicitly and firmware watchdog turns A off. | |
| 4. Restore hardware and relaunch after each phase. | The COM opens normally, one connection/poll worker set exists, and no queued action replays. | |

### BCON-10.3 - Abnormal dashboard termination and firmware watchdog fallback

**Description:** Verify hardware safety when host cleanup cannot run.

**Initial conditions:** No pulser cables are connected. BCON watchdog is
confirmed 1500 ms; A is DC and blue A is on.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Terminate the dashboard process through the approved operating-system force-close method without using its Quit dialog. | Host cleanup/all-off cannot be assumed; serial heartbeats stop. | |
| 2. Observe BCON continuously. | Within the configured watchdog behavior, LCD changes to `WDG:NO`, blue A goes dark, modes/enables clear, and A does not reassert. | |
| 3. Relaunch the dashboard on the same port. | Fresh startup reads all channels OFF/disabled and restores watchdog communication; no previous host queue survives process termination. | |
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
| 3. Arm, then rapidly toggle CH A/B/C in varied order. | Final firmware enable states match the final UI states after fresh polls; channels do not cross-map. Rapid-toggle limitations are logged rather than concealed. | |
| 4. Configure long visible modes and rapidly select individual Beam buttons, Activate, and Disable All. | The UI remains responsive; final confirmed all-off wins; no earlier queued output reasserts after it. | |
| 5. While statuses update, switch Beam Pulse tabs, scroll, resize, maximize/restore, and enter/exit fullscreen. | Widgets retain channel identity and correct state; no Tk exception, frozen update, duplicate card, or duplicate log stream occurs. | |
| 6. Disconnect/reconnect three times, waiting for completion each time. | Every cycle has one all-off/close/open/poll cycle; the COM is not leaked and old queues are cleared. | |
| 7. Finish with confirmed Disable All and disarm, then inspect LCD/LED/UI/log. | Every surface agrees on connected, interlock/watchdog OK, software disarmed, all enables disabled, all modes/output OFF, and no worker still changing state. | |

## Completion Criteria

The Beam Pulse subsystem passes when every in-scope UI control is exercised;
A/B/C are correctly mapped across Main Control, Beam Pulse, BCON LCD, and blue
gate LEDs; all manual-mode and watchdog limits are validated; physical Arm Beams,
power, BCON-side serial, and laptop-adapter faults reach a clear safe or
explicitly uncertain state; all-off confirmation defeats stale queued writes;
and reconnect/restart never replays a prior output command.

Any of the following is a defect: output after a confirmed all-off; a rejected
or partial staged request activated by a later unrelated apply; an enable that
persists through an unsafe state; a dashboard
OFF/healthy claim while physical gate state is unknown or visibly HIGH; a
queued request described as firmware-confirmed; suppressed/misleading safety
logs; an unannounced COM-update limitation; a startup file that crashes instead
of falling back; a shutdown hang or leaked serial owner; or any discrepancy
among the latest fresh UI snapshot, action line, durable log, LCD, and LEDs.

The plan is complete only after the approved configuration files and working
directories are restored, watchdog is confirmed 1500 ms, BCON is connected and
disarmed with all modes/enables OFF, every blue output LED is dark, all pulser
cables remain disconnected, CCS remains OFF, and no high-voltage supply has
been enabled from the Knob Box.
