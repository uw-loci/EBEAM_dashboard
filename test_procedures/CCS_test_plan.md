# Cathode Heating (CCS) Subsystem Test Plan

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

Verify the dashboard's Cathode Heating subsystem and its three BK Precision
9104 power supplies and three E5CN temperature-monitor channels through
operator-visible behavior, safe physical fault injection, startup manipulation,
and log review.

This is a solo Cathode Heating plan. It covers CCS behavior only: the Cathode
Heating panel, the 9104 and E5CN drivers, the CCS dummy load setup, CCS COM-port
selection, CCS lookup-table data, and CCS-tagged logs. It does not test Main
Control, Beam Pulse, Vacuum, Beam Energy, Machine Status, or coordination
between subsystems. Main Control is used only to establish the mandatory
settings below and to select CCS COM ports.

The plan is deliberately fault-oriented. A passing system distinguishes a
stored Goal from a value Sent to a 9104 and from a fresh Measured readback;
does not present an open COM port as proof of a responding device; never reports
an unacknowledged output change as confirmed; preserves safe operator control
during partial failures; and makes any uncertain physical output state explicit.

Expected Results are operator-facing pass criteria, so known misleading,
non-finite-input, and lifecycle behaviors remain defect-revealing rather than
being normalized as correct. The exception requested for this plan is 9104
limiting during ramps: the Expected Results intentionally follow the current
driver's final-measurement verification, with no consecutive-limit abort or
last-good restoration.

The following behaviors are excluded. Keep all three settings disabled for the
entire plan and do not execute tests of their behavior:

- `Disable CCS Output on BCON Disconnect`
- `Disable CCS Output if pressure exceeds 1e-05 mbar for 30s`
- `Do not activate Beams if predicted Emission current exceeds 6mA`

## Safety Considerations

- Use the approved `CCS dummy load setup`. With CCS power removed, double-check
  continuity through each load and verify that the Cathode A, B, and C 9104
  leads connect to the correct load before every energized suite.
- Never request or apply a heater voltage/current Goal or Sent value above
  `0.50 V` or `1.99 A` on any individual 9104, and never confirm protections
  above those values. UI-only over-range protection validation is permitted
  only where a case first makes that supply unavailable, so the value cannot
  reach hardware. Keep each energized interval only as long as needed to
  obtain a stable observation. Never leave an energized output unattended.
- Before the first output command after every launch or 9104 power cycle, set
  and confirm OVP at `0.50 V` or lower and OCP at `1.99 A` or lower on all three
  supplies. The dashboard starts with higher software defaults and a power-
  cycled 9104 starts with zeroed preset, setpoints, OVP, and OCP.
- Identify one approved setpoint pair that produces `CV Mode` and one that
  produces `CC Mode` on the CCS dummy load setup, both inside the limits above.
  Record them as `CV_PAIR` and `CC_PAIR`. If either mode cannot be reached
  without crossing the limits, mark only that mode-dependent branch blocked;
  do not alter the load or exceed the limits.
- Keep the Knob Box OFF for the entire plan. After every dashboard launch,
  uncheck `Disable CCS logging when CCS power is off` before any CCS action.
  Keep CCS file recording ON at `VERBOSE` level and preserve the session log.
- After every launch, also uncheck the three excluded settings before enabling
  a CCS output. If any is found enabled, turn all 9104 outputs physically OFF,
  correct the setting, and restart the affected case.
- Treat the dashboard as an operator interface, not an independent safety
  device. USB loss can leave powered 9104 outputs energized at their last
  settings, while CCS power loss resets and de-energizes them.
- Before removing a cable, verify that touching it is safe and that no exposed
  energized conductor can be contacted.
- The 9104 front-panel keys are out of scope except each unit's power switch.
  Use the displays only to observe voltage, current, output, and CV/CC state.
  Confirm preset/OVP/OCP through dashboard command/readback logs; do not
  navigate front-panel menus.
- If an OFF command is unacknowledged, a COM port disappears while output is
  energized, or dashboard and front panel disagree, do not touch output/load
  wiring or leave the station. Remove CCS power and verify zero output before
  normal testing continues. A case that explicitly characterizes live
  communication recovery, shutdown, or restart may delay power removal only
  for its stated observations: one observer must continuously watch the CCS front
  panel/load, a second may touch computer controls.
- Record wall-clock times for physical changes, the first visible fault, the
  first operator-level log, recovery, and any automatic command.
- Back up `usr/usr_data/com_ports.json`, `usr/usr_data/pane_state.json`, and
  `data/lut/power_supply` before file-manipulation cases. Restore approved
  content after each case.

## Outline

1. Safety baseline, normal startup, and UI inventory
2. Manual setpoints, validation, clearing, and nudges
3. Predictions and lookup-table behavior
4. Immediate output and confirmed OFF behavior
5. Ramp Current, Ramp Voltage, limiting, and interruption
6. Protection, slew, and Config-tab controls
7. Live readbacks, CV/CC indication, and difference warnings
8. E5CN temperatures, sensor faults, and transport failures
9. 9104, USB, and total-CCS physical failures
10. Startup, COM-port, configuration-file, and LUT resilience
11. Logging, acknowledgements, and semantic consistency
12. Shutdown, restart, races, and interaction stress

Unless a case states otherwise, begin with the Safety Considerations satisfied;
the dashboard not yet running; CCS power available; the shared 9104 USB
connection and E5CN USB/RS-485 adapter connected; all three dummy thermocouples
installed; and the correct four CCS COM selections known. The CCS dummy load
setup must be connected and mapped before power is applied.

After launch, disable the three excluded settings and CCS log suppression,
enable `VERBOSE` file logging, wait for fresh data, then confirm each 9104 dot
is green only after a valid live readback and confirmed preset 3, OVP, and OCP.
Confirm each E5CN dot is green only after that channel returns a numeric
temperature. Set and confirm OVP at `0.50 V` and OCP at `1.99 A` before enabling
any output. Unless a case requires otherwise, begin with all physical outputs
OFF, output toggles OFF, mode `Immediate Set`, blank Goals and Sent values,
measured power near zero, and dummy thermocouples near room temperature.

For energized cases, use `CV_PAIR` or `CC_PAIR` as directed. Dashboard
temperature text currently renders one decimal, while the E5CN README and
physical input configuration may provide finer resolution. Record each front
panel's configured/displayed resolution as `E5_DISPLAY_RESOLUTION`. Require
the dashboard numeric value to equal the physical reading when rounded to the
dashboard's displayed precision; record a factor-of-ten, decimal-place, or
unexplained resolution mismatch as a defect. Compare dashboard 9104 values
with the corresponding front panel to the displayed resolution and record any
difference. Repeat single-channel functional cases for A, B, and C unless the
case explicitly tests one representative channel; never infer mapping from a
previous run.

Assertions involving Main Control are limited to mandatory setting state and
CCS COM-port application. Do not assess another subsystem's reaction. Do not
activate beams in any case.

Use these exact temporary prediction fixtures where referenced:

`CCS_test_alt.csv`

```csv
beam_current,voltage,heater_current
0.000,0.00,0.00
0.050,0.10,0.50
0.200,0.20,1.00
0.400,0.30,1.50
```

`CCS_test_small_domain.csv`

```csv
beam_current,voltage,heater_current
0.000,0.00,0.00
0.050,0.08,0.40
0.100,0.16,0.80
```

`CCS_test_high_min.csv`

```csv
beam_current,voltage,heater_current
0.100,0.20,1.00
0.200,0.30,1.50
```

## Suite 1 - Safety baseline, normal startup, and UI inventory

**Description:** Establish the isolated, logged, correctly mapped reference
state and inventory every attainable Cathode Heating operator surface.

**Initial conditions:** Common initial conditions apply. The dashboard is not
running at the start of CCS-1.1.

### CCS-1.1 - Dummy-load isolation, continuity, and lead mapping

**Description:** Verify the physical fixture before any 9104 output can be
energized.

**Initial conditions:** Dashboard closed; total CCS power removed; all supply
outputs de-energized.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Identify the approved `CCS dummy load setup` and verify total CCS power is removed. | All 9104 and E5CN displays are dark, and no output conductor is energized. | |
| 2. Check continuity through each dummy load using the approved method. | Cathode A, B, and C load paths each have the expected continuity; no open or unintended short is present. | |
| 3. Trace the positive and return leads from 9104 A to load A. | Both leads terminate on the correct A load with secure polarity and no shared or crossed lead. | |
| 4. Repeat the lead trace for 9104 B and 9104 C. | B and C each connect only to the correctly labeled load. | |
| 5. Inspect the shared 9104 USB connection, E5CN RS-485 network, laptop adapters, and all three dummy thermocouples. | Connectors are seated, strain relieved, and mapped to the intended device group; thermocouples are installed in E5CN units 1, 2, and 3. | |
| 6. Record the approved `CV_PAIR` and `CC_PAIR` values and verify both are at or below 0.50 V and below 2.00 A per 9104. | Both pairs meet the per-supply fixture limits; no output is enabled. | |

### CCS-1.2 - Mandatory settings, logging, and normal cold startup

**Description:** Prove that the dashboard reaches one coherent, fully logged CCS
reference state without relying on other subsystems.

**Initial conditions:** CCS-1.1 passed. Correct CCS COM ports are saved or
available in the startup selector. All 9104 outputs are physically OFF.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Apply CCS power and observe all six device displays before starting the dashboard. | The three 9104s and three E5CNs power normally; no 9104 output is enabled; each E5CN shows a plausible room-temperature value. | |
| 2. Start the dashboard, select the correct `CathodeA PS`, `CathodeB PS`, `CathodeC PS`, and `TempControllers` COM ports, and submit. | The dashboard opens without a Cathode Heating initialization exception. | |
| 4. Immediately uncheck the three excluded settings and `Disable CCS logging when CCS power is off`. | All four settings remain unchecked; Knob Box stays OFF; CCS behavior is not gated by the excluded integrations and CCS logs are not discarded. | |
| 5. Enable file recording at `VERBOSE` and record the session-log path. | The logging indicator shows recording ON and the file is writable. | |
| 6. Observe each 9104 indicator from startup through readiness. | A dot remains red while the handle is merely open or configuration is pending, then turns green only after a valid readback and confirmed preset 3, OVP, and OCP. | |
| 7. Observe each E5CN indicator from startup through the first complete temperature cycle. | Each dot turns green only after its own numeric temperature is available; no channel is declared healthy solely because the adapter opened. | |
| 8. Open each Config tab and set OVP to `0.50 V` and OCP to `1.99 A`. | Each command is acknowledged and read back; the live values show 0.50 V and 1.99 A before any output control is used. | |
| 9. Compare the three dashboard rows with all six front panels. | A/B/C measured values, temperature values, and CV/CC observations map to the correct physical units; all outputs remain OFF. | |
| 10. Inspect the log chronology. | Logs identify each cathode and port, distinguish handle creation from a valid connection, show preset/limit confirmation, and contain no false output-enable message. | |

### CCS-1.3 - Complete Cathode Heating UI inventory

**Description:** Verify every available CCS control and display without changing
hardware state.

**Initial conditions:** CCS-1.2 passed; all connections healthy and outputs OFF.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Inspect Cathode A, B, and C on the `Main` tab. | Each frame has separate 9104 and E5CN comms dots; current and voltage Sent, Goal, Entry, Set, and nudge controls; output toggle; Output Mode selector; STOP RAMP; LUT selector; four prediction fields; measured voltage/current/temperature; and CV/CC indicators. | |
| 2. Open every `Output Mode` selector without changing its value. | Exactly `Immediate Set`, `Ramp Current`, and `Ramp Voltage` are available; `Immediate Set` is selected initially. | |
| 3. Open every `Lookup Table Dataset` selector. | Available CSV filenames appear once per channel; the active valid dataset is selected; opening the list sends no hardware command. | |
| 4. Inspect each `Config` tab. | `Log Power Settings`, OVP, OCP, current slew, voltage slew, voltage-difference threshold, current-difference threshold, overtemperature limit, and overtemperature status are present and associated with the correct cathode. | |
| 5. Check the initial local values after a fresh process launch. | Mode is Immediate; current slew is 0.01 A/s; voltage slew is 0.02 V/s; both difference thresholds are 10%; overtemperature limit is 150 C; Goals, Sent, and predictions are unset until entered. | |
| 6. Inspect the temperature area for an enabled plot. | No temperature plot is presented because plots are disabled in the current build; the numeric temperature remains available. | |
| 7. Scroll, switch every Main/Config tab, resize, maximize/restore, and return to the initial view. | Controls stay aligned with the correct cathode; no duplicate widget, clipped safety state, Tk exception, or hardware command occurs. | |

### CCS-1.4 - Readiness gating and channel independence

**Description:** Verify that controls reflect per-channel command readiness rather
than the existence of any supply handle.

**Initial conditions:** All channels healthy and outputs OFF. Use Cathode B as
the temporary faulted channel.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Record the enabled state of B's Set, nudge, output-toggle, Output Mode, STOP RAMP, LUT, and Config controls. | Set, nudges, output toggle, mode selector, LUT selector, and applicable Config actions are usable while ready; STOP RAMP is disabled while idle. | |
| 2. Switch off only 9104 B with its front-panel power switch. | B loses valid readback and command readiness; B's measured power and CV/CC state clear and its 9104 dot turns red. | |
| 3. Inspect A and C without changing any setting. | A and C remain green, live, and usable; no A/C value, toggle, Goal, or control state changes. | |
| 4. Inspect B's controls after fault detection. | Hardware-command controls are disabled or reject the action without claiming success; local navigation and dataset inspection do not energize hardware. | |
| 5. Restore 9104 B and wait for fresh configuration. | B remains unavailable until a valid readback and preset/OVP/OCP confirmation, then returns green and usable without replaying an output command. | |
| 6. Restore B's confirmed OVP/OCP to 0.50 V/1.99 A if necessary. | The common safe baseline is restored on all three supplies. | |

## Suite 2 - Manual setpoints, validation, clearing, and nudges

**Description:** Exercise every manual current/voltage entry and nudge path while
distinguishing stored Goals from commands actually sent to hardware.

**Initial conditions:** Common initial conditions apply; all outputs OFF and
`Immediate Set` selected. Use one cathode at a time and repeat valid boundary
checks for A, B, and C.

### CCS-2.1 - Valid current Goal staging while output is OFF

**Description:** Verify that valid current requests are stored but not falsely
represented as applied output settings.

**Initial conditions:** Selected cathode ready; OCP 1.99 A; current Goal and Sent
unset; output OFF.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Enter `0` in the current Entry and press `Set`. | Goal shows 0.00 A and current predictions refresh; Sent remains `--`, measured hardware remains unchanged, and no current command is acknowledged. | |
| 2. Enter a finite value inside the safe range, such as `1.00`, and press `Set`. | Goal changes to 1.00 A and predictions refresh; Sent and the 9104 preset/display do not change while output is OFF. | |
| 3. Enter `1.99` and press `Set`. | A value exactly equal to OCP is accepted as a Goal; no hardware set command occurs while OFF. | |
| 4. Review CCS and 9104 logs for all three actions. | The log describes Goal acceptance or prediction work and does not claim the power supply was physically set without a sent command and acknowledgement. | |
| 5. Repeat the staging check on the other two cathodes. | Each Goal changes only its own channel; no cross-channel Sent, prediction, or physical value changes. | |

### CCS-2.2 - Invalid and non-finite current entry

**Description:** Reject current requests that cannot be applied safely or
represented faithfully by the 9104.

**Initial conditions:** Selected cathode has a valid 1.00 A Goal, output OFF,
and OCP 1.99 A.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Enter alphabetic text and press `Set`. | An Invalid Input dialog and channel-specific warning appear; the 1.00 A Goal, predictions, Sent state, and hardware remain unchanged. | |
| 2. Enter `-0.01` and press `Set`. | The negative request is rejected with the current-specific reason; prior state is preserved. | |
| 3. With output OFF, set and confirm OCP at `1.50 A`. | OCP changes safely and the 1.00 A Goal remains unchanged. | |
| 4. Enter `1.51` and press `Set`. | The value above current OCP is rejected before any current command is sent. | |
| 5. Restore OCP to `1.99 A`. | The common safe protection baseline is confirmed. | |
| 6. Enter `nan` and press `Set`. | The non-finite value is rejected; no Goal, prediction, Sent value, or hardware state becomes NaN. | |
| 7. Enter `inf` and press `Set`. | Positive infinity is rejected without an exception or state change. | |
| 8. Enter `-inf` and press `Set`. | Negative infinity is rejected without an exception or state change. | |
| 9. Enter `1.005` and press `Set`. | The excess-precision value is rejected with a resolution explanation; it is not silently rounded to a different Goal or future command. | |
| 10. Enter a whitespace-padded finite value such as ` 1.25 `. | The numeric request is accepted as Goal 1.25 A; Sent and physical state remain unchanged while output is OFF. | |

### CCS-2.3 - Valid voltage Goal staging and 0.02 V resolution

**Description:** Verify the voltage range, OVP equality, and required 0.02 V
increment while output is OFF.

**Initial conditions:** Selected cathode ready; OVP 0.50 V; voltage Goal and Sent
unset; output OFF.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Enter `0` and press the voltage `Set` button. | Goal shows 0.00 V and predictions refresh; Sent and physical preset/display remain unchanged. | |
| 2. Enter `0.02` and press `Set`. | The minimum nonzero 0.02 V increment is accepted as a Goal only. | |
| 3. Enter `0.20` and press `Set`. | Goal shows 0.20 V; predictions change; no hardware set acknowledgement occurs while OFF. | |
| 4. Enter `0.50` and press `Set`. | A value exactly equal to OVP and divisible by 0.02 is accepted as the Goal. | |
| 5. Review the log and physical display. | Logging distinguishes staged Goal from Sent hardware state; the 9104 remains at its prior preset/output state. | |

### CCS-2.4 - Invalid and non-finite voltage entry

**Description:** Reject negative, over-limit, off-resolution, nonnumeric, and
non-finite voltage requests.

**Initial conditions:** Selected cathode has a valid 0.20 V Goal, output OFF,
and OVP 0.50 V.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Enter alphabetic text and press voltage `Set`. | An Invalid Input dialog appears; prior Goal, predictions, Sent, and hardware are preserved. | |
| 2. Enter `-0.02` and press `Set`. | The negative voltage is rejected with a voltage-specific message. | |
| 3. Enter `0.49` and press `Set`. | The value is rejected because it is not a multiple of 0.02 V, even though it is below OVP. | |
| 4. With output OFF, set and confirm OVP at `0.20 V`. | OVP changes safely and the existing Goal is not sent to hardware. | |
| 5. Enter `0.22` and press `Set`. | The valid-resolution request above current OVP is rejected before any voltage command is sent. | |
| 6. Restore OVP to `0.50 V`. | The common safe protection baseline is confirmed. | |
| 7. Enter `nan` and press `Set`. | NaN is rejected without a Tk exception, corrupted prediction, or hardware command. | |
| 8. Enter `inf` and press `Set`. | Positive infinity is rejected without a Tk exception or state change. | |
| 9. Enter `-inf` and press `Set`. | Negative infinity is rejected without a Tk exception or state change. | |
| 10. Re-enter `0.20`. | The valid Goal is accepted and normal operation remains possible after all rejected inputs. | |

### CCS-2.5 - Current and voltage nudges from unset and boundary states

**Description:** Verify nudge resolution, boundary validation, and per-mode
button gating.

**Initial conditions:** Selected cathode ready and output OFF. Clear both Goals
before step 1.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Press current `+0.01` with current Goal `--`. | Current Goal becomes 0.01 A, predictions refresh, and no hardware command is sent while OFF. | |
| 2. Clear the current Goal, then press current `-0.01`. | The implied negative request is rejected; Goal remains unset and no command is sent. | |
| 3. Press voltage `+0.02` with voltage Goal `--`. | Voltage Goal becomes 0.02 V, predictions refresh, and Sent remains unset. | |
| 4. Clear the voltage Goal, then press voltage `-0.02`. | The implied negative voltage is rejected and prior state remains safe. | |
| 5. Set current Goal to 1.99 A and press `+0.01`. | The over-OCP request is rejected and Goal remains 1.99 A. | |
| 6. Set voltage Goal to 0.50 V and press `+0.02`. | The over-OVP request is rejected and Goal remains 0.50 V. | |
| 7. Select `Ramp Current` while idle. | Current nudges are disabled and voltage nudges remain usable; text Set buttons follow the implemented idle-mode rules. | |
| 8. Select `Ramp Voltage`. | Voltage nudges are disabled and current nudges remain usable. | |
| 9. Return to `Immediate Set`. | Both current and voltage nudges return to their ready state. | |

### CCS-2.6 - Empty-entry clearing while output is OFF

**Description:** Verify explicit Goal clearing and the distinction between Goal,
Sent, and prediction state.

**Initial conditions:** Selected cathode output OFF with valid current and voltage
Goals and at least one populated prediction.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Clear the current Entry text and press current `Set`. | Current Goal and current Sent display clear to `--`; the current warning state clears; voltage Goal remains; predictions recompute from the remaining voltage Goal where possible. | |
| 2. Inspect the physical 9104 preset and output. | No current command or output change occurs because clearing is a local Goal action. | |
| 3. Restore a valid current Goal, then clear the voltage Entry and press voltage `Set`. | Voltage Goal and voltage Sent display clear; current Goal remains; predictions recompute from current where possible; hardware remains unchanged. | |
| 4. Clear both Goals and inspect predictions. | Both Goals and dependent predictions show unavailable state; no plausible stale prediction is presented as current. | |
| 5. Press the output toggle. | Output enable is blocked because required targets are missing; the toggle remains OFF and no 9104 output command is sent. | |

### CCS-2.7 - Setpoint actions while unavailable or transitioning

**Description:** Verify that stale-ready timing and red-state controls cannot
produce a false successful setpoint.

**Initial conditions:** Selected cathode ready, output OFF, with safe Goals.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Switch off the selected 9104 and immediately press one enabled Set or nudge control before the next dashboard refresh. | Any unacknowledged operation fails visibly; Sent and physical state do not change; no success log is emitted. | |
| 2. Wait until the 9104 dot is red and controls are disabled. | Measured V/I and CV/CC clear; hardware-command controls cannot be invoked as normal commands. | |
| 3. Change only the LUT selection while the supply is unavailable. | Predictions may recompute locally from stored Goals; no serial command or false reconnection occurs. | |
| 4. Restore 9104 power and attempt a Set while configuration is still pending. | The command remains unavailable until fresh readback plus preset/OVP/OCP confirmation completes. | |
| 5. After the dot becomes green, send one valid Goal change while output remains OFF. | The Goal changes locally, proving controls recover once; no duplicate command or worker appears. | |

## Suite 3 - Predictions and lookup-table behavior

**Description:** Verify that CCS prediction displays follow the selected dataset
and staged electrical constraints without being confused with measured or
commanded hardware state.

**Initial conditions:** Common initial conditions apply; all outputs OFF, safe
OVP/OCP confirmed, and the approved production LUT restored unless a case says
otherwise.

### CCS-3.1 - Initial unknown state and real zero prediction

**Description:** Distinguish an unavailable prediction from a legitimate
calculated zero.

**Initial conditions:** Fresh dashboard process; selected channel has no current
or voltage Goal.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Inspect Emission, Grid, Heater Voltage, and Heater Current before entering a Goal. | All prediction fields show `--`; unknown prediction is not displayed as 0. | |
| 2. Set a 0.00 A current Goal while output is OFF. | The production LUT produces numeric zero heater current, heater voltage, emission, and grid values where defined; a real zero is displayed as numeric rather than `--`. | |
| 3. Clear the current Goal. | Prediction fields return to `--` because no active constraint remains. | |
| 4. Inspect Sent, Measured, and the 9104 front panel throughout. | No hardware command or physical change accompanies prediction creation or clearing. | |

### CCS-3.2 - Current-only and voltage-only interpolation

**Description:** Verify interpolation from either electrical constraint inside
the safe operating envelope.

**Initial conditions:** Production LUT selected; output OFF; Goals unset.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Enter a safe current Goal between two LUT heater-current rows, such as 1.00 A. | Predicted Heater Current equals the Goal; Heater Voltage, Emission, and Grid are finite interpolated values consistent with the CSV and 72% beam fraction; Sent remains unset. | |
| 2. Independently calculate the expected linear interpolation from the two bracketing CSV rows. | Dashboard values agree to their displayed precision; no unexplained extrapolation or row-order dependency occurs. | |
| 3. Clear current, then enter a safe voltage Goal between two LUT voltage rows, such as 0.20 V. | Predicted Heater Voltage equals the Goal and the other prediction fields follow voltage-keyed interpolation; hardware remains unchanged. | |
| 4. Compare the current-only and voltage-only logs. | Each log identifies the correct cathode and constraint; neither claims a measured value or sent command. | |

### CCS-3.3 - Dual constraints and binding-mode calculation

**Description:** Verify prediction behavior when both heater current and voltage
Goals exist.

**Initial conditions:** Production LUT selected; output OFF; Goals unset.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Set a safe voltage Goal, then a safe current Goal whose predicted voltage is below that voltage limit. | Current is the binding prediction constraint; predicted heater current follows the current Goal and predicted voltage does not exceed the voltage Goal. | |
| 2. Change the current Goal so the voltage Goal becomes binding, remaining within 0.50 V/1.99 A. | Predicted heater voltage follows the voltage limit and predicted current is limited consistently with the LUT. | |
| 3. Clear both Goals, then enter the same pair in the opposite order. | Final predictions are determined by the same constraints, not stale entry order. | |
| 4. Change only one Goal by one valid nudge. | Predictions refresh once from the new active constraints; no unrelated channel or hardware state changes. | |
| 5. Compare Emission and Grid. | Grid is 28% of total predicted emission and values use consistent mA units and rounding. | |

### CCS-3.4 - Dataset selection, recomputation, and channel isolation

**Description:** Verify that changing a valid LUT recomputes local predictions
without changing Goals or sending power commands.

**Initial conditions:** Back up the LUT directory. Add the exact
`CCS_test_alt.csv` fixture defined in the common conditions, then restart the
dashboard. All outputs OFF.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Stage safe current and voltage Goals on Cathode A and record its predictions. | Goals and predictions populate; Sent and physical values remain unchanged. | |
| 2. Select `CCS_test_alt.csv` for Cathode A. | A predictions recompute from the staged constraint; A Goals remain unchanged; no 9104 command is sent. | |
| 3. Inspect Cathodes B and C. | Their selected datasets, Goals, predictions, Sent, and measured values do not change. | |
| 4. Switch A back to the production dataset. | Original production-LUT predictions return to displayed precision without a hardware command. | |
| 5. Restart the dashboard without changing startup ports. | Dataset selection returns to the process startup default because CCS LUT choice is not persisted; no stale output command replays. | |
| 6. Remove the temporary file and restore the approved LUT directory. | The production file set is restored exactly. | |

### CCS-3.5 - Safe above-domain fallback using a temporary LUT

**Description:** Exercise the implemented ES440/Richardson fallback without
exceeding fixture limits.

**Initial conditions:** Back up the LUT directory. Add and select the exact
`CCS_test_small_domain.csv` fixture defined in the common conditions after a
restart. Keep output OFF.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Enter a Goal exactly at the temporary LUT's 0.80 A or 0.16 V maximum. | Prediction uses LUT data and does not issue an above-LUT warning. | |
| 2. Enter `0.18 V`, one valid voltage step above the temporary maximum. | Voltage-controlled prediction uses the current code's ES440/Richardson fallback, displays finite modeled values where available, and logs that the selected LUT domain was exceeded. | |
| 3. Enter `0.81 A`, one current step above the temporary maximum. | Current-controlled fallback is attempted and logged; if the raw uncalibrated ES440 extrapolation yields nonphysical temperature at this low current, prediction clears to `--` rather than fabricating finite emission. | |
| 4. Return to an in-domain Goal. | LUT interpolation resumes and the above-domain state does not remain latched as current evidence. | |
| 5. Restore the production LUT files and restart. | Temporary data no longer appears and production prediction behavior is restored. | |

### CCS-3.6 - Prediction unavailable while electrical control remains independent

**Description:** Verify that prediction failure is visible and does not silently
rewrite an accepted safe Goal.

**Initial conditions:** Add and select the exact `CCS_test_high_min.csv` fixture
defined in the common conditions after restart; output OFF.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Enter 0.50 A or 0.10 V, below the temporary table's minimum domain. | Prediction fields clear to `--` and a channel-specific prediction warning/error is logged; no fabricated value appears. | |
| 2. Inspect the electrical Goal and Sent displays. | The accepted safe electrical Goal remains explicit; Sent stays unset because output is OFF. | |
| 3. Stage the complementary safe Goal and select `Immediate Set`. | Both electrical Goals remain available independently of prediction state; no Beam Pulse or emission-guard behavior is assessed. | |
| 4. Restore and select the production LUT. | Predictions recover from the stored Goals without sending a power command. | |

## Suite 4 - Immediate output and confirmed OFF behavior

**Description:** Exercise immediate output prerequisites, command order, live
changes, acknowledged shutoff, and uncertain output state.

**Initial conditions:** Common initial conditions apply; selected channel in
`Immediate Set` with confirmed safe OVP/OCP. Use `CV_PAIR` unless directed
otherwise and observe the physical 9104 throughout.

### CCS-4.1 - Output-enable prerequisite matrix

**Description:** Verify that output cannot turn on without both safe Goals and
fresh protection readbacks.

**Initial conditions:** Selected channel ready, output OFF, both Goals unset.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Press the output toggle with both Goals unset. | Enable is blocked for missing voltage first; toggle and physical output remain OFF. | |
| 2. Set only a safe voltage Goal and press the toggle. | Enable is blocked for missing current; no preset or output command is acknowledged. | |
| 3. Clear voltage, set only a safe current Goal, and press the toggle. | Enable is blocked for missing voltage; no hardware state changes. | |
| 4. Set both safe Goals, then lower OVP below the stored voltage Goal while output remains OFF. | The new confirmed OVP is displayed; pressing the toggle is rejected because the Goal exceeds live OVP. | |
| 5. Restore OVP, then lower OCP below the stored current Goal. | Output enable is rejected because the current Goal exceeds live OCP. | |
| 6. Restore OVP/OCP to 0.50 V/1.99 A and both Goals to `CV_PAIR`. | Channel is ready for a valid enable and remains physically OFF. | |
| 7. Interrupt communication so live OVP/OCP cannot be read, then attempt enable during the stale-ready window. | Enable fails without SOUT1; the toggle does not falsely show ON and the log identifies unavailable protection/communication. | |

### CCS-4.2 - Immediate ON command order and physical confirmation

**Description:** Verify the implemented safe sequence: current preset, voltage
preset, then output enable.

**Initial conditions:** Selected channel ready and OFF with `CV_PAIR` Goals.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Record the current 9104 preset, front-panel output state, Sent fields, and measured values. | Baseline evidence is captured; physical output and toggle are OFF. | |
| 2. Press the output toggle once. | The driver acknowledges current first and voltage second, performs GETS3/GOVP output-enable preflight, then acknowledges `SOUT1`; the toggle changes ON only after the sequence succeeds. | |
| 3. Observe Sent and Goal fields during and after the command. | Goals remain the requested pair; Sent current and voltage populate only after their respective acknowledgements. | |
| 4. Wait for a fresh measured readback and compare the 9104 front panel. | Dashboard measured V/I and CV/CC agree with the correct physical supply; the output is visibly enabled and remains within 0.50 V/1.99 A. | |
| 5. Inspect the log chronology. | Cathode, values, preset 3, current/voltage acknowledgements, and output enable are ordered and no success precedes its acknowledgement. | |
| 6. Press the toggle OFF and verify the front panel. | `SOUT0` is acknowledged, physical output turns OFF, and only then does the dashboard toggle show OFF. | |
| 7. Repeat the complete ON/OFF sequence for the other two cathodes. | Each toggle controls only its mapped 9104 and load; peers remain unchanged. | |

### CCS-4.3 - Immediate current and voltage changes while ON

**Description:** Verify direct set behavior and correct Sent/Goal/Measured
separation during live output changes.

**Initial conditions:** Selected channel ON in Immediate Set at a safe pair below
the maxima.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Increase current Goal by 0.01 A using the nudge. | One current command is acknowledged; current Goal and Sent update; voltage Goal/Sent stay unchanged; measured current follows according to the active CV/CC condition. | |
| 2. Enter a different safe current and press `Set`. | The current command applies immediately, predictions refresh, and no voltage command is falsely logged. | |
| 3. Increase voltage Goal by 0.02 V using the nudge. | One voltage command is acknowledged; voltage Goal and Sent update; current Goal/Sent stay unchanged. | |
| 4. Enter a different safe voltage multiple of 0.02 and press `Set`. | The voltage applies immediately; measured/front-panel values settle within the fixture limits. | |
| 5. Submit an invalid current. | Request is rejected without disturbing energized hardware's last valid setpoints or output state. | |
| 6. Submit an invalid voltage. | Request is rejected without disturbing energized hardware's last valid setpoints or output state. | |
| 7. Turn output OFF. | Acknowledged shutoff returns the channel to the safe baseline. | |

### CCS-4.4 - Zero setpoints and output-state semantics

**Description:** Verify that a commanded ON state with zero electrical output is
not confused with an OFF command.

**Initial conditions:** Selected channel ready and OFF; set both Goals to zero.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Press the output toggle ON. | Current 0, voltage 0, then SOUT1 are acknowledged; the toggle/front-panel output state shows enabled even though measured V/I are zero. | |
| 2. Inspect CV/CC and difference-warning displays. | Mode follows the live GETD response; percent-difference warnings remain inactive because Sent is zero. | |
| 3. Press the output toggle OFF. | SOUT0 is acknowledged and both physical and dashboard output state become OFF. | |
| 4. Inspect the log. | Output enable/disable is distinguished from electrical zero; no log claims zero measurement proves OFF. | |

### CCS-4.5 - Clearing a Goal while output remains energized

**Description:** Expose the local-display and physical-state consequences of an
empty Set action while ON.

**Initial conditions:** Selected channel ON in Immediate Set at a safe nonzero
pair.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Clear the current Entry and press current `Set`. | Current Goal and Sent UI clear and its warning resets, but no current or OFF command is sent; physical output continues at the last applied settings. | |
| 2. Compare Measured current and the 9104 front panel with the cleared fields. | Fresh measured/physical current remains visible and exposes that clearing the local field did not change hardware. | |
| 3. Clear the voltage Entry and press voltage `Set`. | Voltage Goal/Sent clear locally while physical voltage and output continue unchanged. | |
| 4. Press the output toggle OFF. | Unconditional SOUT0 succeeds despite missing Goals and the physical output turns OFF. | |
| 5. Press the toggle ON without restoring Goals. | Re-enable is blocked for missing targets; no stale values are replayed. | |
| 6. Restore safe Goals before continuing. | The channel returns to a coherent OFF baseline. | |

### CCS-4.6 - Exploratory partial enable sequence failure

**Description:** Characterize communication/power interruption at immediate-
enable phases without treating inability to hit a sub-second phase as a product
failure. Attempt each phase no more than three times and record an unattained
phase as blocked/exploratory.

**Initial conditions:** Two observers are available where practical. Selected
channel OFF with safe Goals; preserve logs for each repetition.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Attempt an enable interruption before the current-set acknowledgement, with at most three repetitions. | When attained, no Sent current, Sent voltage, or confirmed ON state appears; physical output remains OFF and failure identifies the current phase. | |
| 2. Restore/configure the supply, reset it OFF, and attempt interruption after current acknowledgement but before voltage acknowledgement. | When attained, current may be stored in preset 3, voltage is not confirmed, SOUT1 is not issued, and the toggle remains OFF. | |
| 3. Restore/reset and attempt interruption after voltage acknowledgement but before SOUT1 acknowledgement. | When attained, both preset values may be stored, but output is not presented as confirmed ON without SOUT1 acknowledgement. | |
| 4. Restore/reset and attempt interruption after physical SOUT1 but before/while its response is lost. | When attained, the physically energized but unconfirmed state is reported as uncertain rather than presented as confirmed OFF; current behavior that only logs a generic enable failure is a defect. | |
| 5. Restore the same COM and wait for readiness after each repetition. | No stored Goal or partial preset is automatically replayed and no automatic SOUT1 occurs. | |
| 6. Issue a healthy confirmed OFF or remove CCS power before leaving the case. | Physical output is verified OFF and dashboard state is reconciled. | |

### CCS-4.7 - Failed OFF acknowledgement and conservative toggle state

**Description:** Verify that the UI does not claim OFF when the 9104 cannot
acknowledge `SOUT0`.

**Initial conditions:** Selected channel ON at a safe pair. Prepare to remove
the shared 9104 USB connection and observe the front panel.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Remove the 9104 USB connection and immediately press the ON-looking toggle before it disables. | The supply remains physically energized at its last settings; SOUT0 cannot be acknowledged; the toggle remains ON and a CRITICAL uncertain-output message names the cathode. | |
| 2. Wait for all 9104 ports to be recognized as absent. | Measured power clears and command controls disable, but the affected toggle/Goals/Sent retain their last commanded state; E5CN data remains live. | |
| 3. Reconnect USB with the same COM numbers and wait for readiness. | Fresh readback and preset/limit confirmation restore controls; no SOUT1 or ramp is replayed and the still-energized physical state is observable. | |
| 4. Press the ON-looking toggle once after recovery. | A healthy SOUT0 is acknowledged, physical output turns OFF, and the toggle finally changes OFF. | |
| 5. Inspect logs across the entire sequence. | The record distinguishes failed OFF, uncertain state, communication loss, recovery, and later confirmed OFF; it never records the first OFF attempt as successful. | |

### CCS-4.8 - Protection changes incompatible with an energized Goal

**Description:** Verify that a protection edit cannot silently invalidate an
active output contract and characterize the current code's lack of a Goal
compatibility check.

**Initial conditions:** Selected channel ON at 0.30 V or lower and 1.50 A or
lower, within `CV_PAIR` or `CC_PAIR` as appropriate.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Set OVP below the active voltage Goal while continuously observing the front panel. | Current code sends, acknowledges, and confirms the lower OVP without comparing the active Goal and does not issue SOUT0 automatically. | |
| 2. Restore OVP to a safe value above the active voltage Goal. | OVP is acknowledged/read back without changing the setpoint or toggle. | |
| 3. Set OCP below the active current Goal. | Current code confirms the lower OCP without a Goal check or automatic OFF. | |
| 4. Restore OCP to a safe value above the active current Goal. | OCP is acknowledged/read back without changing the setpoint or toggle. | |
| 5. Compare physical output/setpoints with the toggle and dashboard-confirmed protections after each incompatible edit. | Any physical protection trip is visible in front-panel/Measured evidence; because CCS does not query GOUT, the toggle may remain ON as commanded belief and must not be interpreted as physical confirmation. | |
| 6. Turn output OFF and restore 0.50 V/1.99 A limits. | Confirmed safe baseline is restored. | |

## Suite 5 - Ramp Current, Ramp Voltage, limiting, and interruption

**Description:** Verify both implemented ramp sequences, UI gating, cross-mode
changes, STOP semantics, current code's final-only limiting behavior, and fault
handling.

**Initial conditions:** Common initial conditions apply. Set current slew to an
approved value such as 0.20 A/s and voltage slew to 0.04 V/s to make steps
observable while remaining within the fixture limits. All outputs begin OFF.

### CCS-5.1 - Output Mode selector semantics and idle gating

**Description:** Verify all mode selections and their operator-visible control
rules.

**Initial conditions:** Selected channel ready and idle with safe Goals.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Select `Ramp Current`. | Selector shows Ramp Current; current is the ramp-controlled quantity; idle current nudges are disabled, voltage nudges remain usable, and STOP remains disabled. | |
| 2. Select `Ramp Voltage`. | Voltage becomes ramp-controlled; voltage nudges are disabled and current nudges remain usable. | |
| 3. Select `Immediate Set`. | Ramp status clears and both nudge groups return to their normal ready state. | |
| 4. Review the log messages for all three choices. | Messages identify output mode and the correct controlled quantity; none incorrectly calls every selection a voltage mode. | |

### CCS-5.2 - Ramp Current enable sequence and completion

**Description:** Verify target voltage, safe zero-current preset, output enable,
and stepped current ramp.

**Initial conditions:** Selected channel OFF; safe nonzero Goals chosen to reach
the intended mode; `Ramp Current` selected.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Press the output toggle ON while observing Sent fields and the front panel. | Target voltage is acknowledged first, current 0 is acknowledged second, GETS3/GOVP preflight succeeds, SOUT1 is acknowledged, then the current ramp starts. | |
| 2. Inspect controls during the ramp. | Set and nudge controls and Output Mode are disabled; STOP RAMP is enabled; the output toggle continues to represent ON. | |
| 3. Observe at least three ramp steps. | Sent current advances at the configured cadence without exceeding the target; Goal remains fixed; measured/front-panel current follows the load response; Sent voltage remains the target. | |
| 4. Wait for completion and final verification. | Final current is verified within 0.10 A of target, completion is logged, STOP disables, and normal idle controls return. | |
| 5. Compare final dashboard and 9104 state. | Output remains ON at the requested constraints; measured values and CV/CC agree with the front panel. | |
| 6. Turn output OFF. | SOUT0 is acknowledged and the channel returns safely OFF. | |

### CCS-5.3 - Ramp Voltage enable sequence and completion

**Description:** Verify target current, safe zero-voltage preset, output enable,
and stepped voltage ramp.

**Initial conditions:** Selected channel OFF with safe nonzero Goals; `Ramp
Voltage` selected.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Press the output toggle ON while observing Sent fields and the front panel. | Target current is acknowledged first, voltage 0 is acknowledged second, GETS3/GOVP preflight succeeds, SOUT1 is acknowledged, then voltage steps begin. | |
| 2. Observe at least three voltage steps. | Sent voltage advances at the configured cadence and never exceeds the Goal; Goal remains fixed; measured/front-panel response follows; Sent current stays at target. | |
| 3. Inspect control gating during the ramp. | Set/nudges and mode selector are disabled and STOP is active; UI remains responsive. | |
| 4. Wait for completion and final verification. | Final voltage is verified within 0.20 V of target, completion is logged, and idle controls return. | |
| 5. Turn output OFF. | Confirmed SOUT0 returns physical and dashboard state OFF. | |

### CCS-5.4 - Upward, downward, and equal-target ramps

**Description:** Verify ramp direction and the one-step/equal-target edge in
both controlled quantities.

**Initial conditions:** Selected channel ON at a safe midpoint; perform current
branches in Ramp Current and voltage branches in Ramp Voltage.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Set a higher safe controlled Goal. | Sent values move monotonically upward without overshoot and final verification uses the new Goal. | |
| 2. After completion, set a lower safe controlled Goal. | Sent values move monotonically downward without dropping below target. | |
| 3. After completion, submit the current Goal again. | At most one no-change/equal-target step and final verification occur; no division error, endless worker, or output toggle change occurs. | |
| 4. Repeat all three steps for the other ramp mode. | Current and voltage ramps show equivalent direction handling with their own tolerances and units. | |
| 5. Turn output OFF. | Safe baseline is restored. | |

### CCS-5.5 - Cross-quantity changes while ramp mode is active

**Description:** Verify the implemented immediate non-controlled update followed
by re-ramping of the controlled quantity.

**Initial conditions:** Selected channel ON, idle after a completed ramp, with
both safe Goals present.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. In `Ramp Current`, change voltage by one valid 0.02 V increment. | New voltage is set immediately, then current ramps back toward its stored current Goal; command order and Sent fields make both phases visible. | |
| 2. Wait for completion, then change the current Goal. | Current alone ramps toward the new target; voltage remains at its Goal. | |
| 3. Switch to `Ramp Voltage` after all ramp activity stops. | Mode changes only while idle and appropriate nudge gating updates. | |
| 4. Change current by a safe 0.01 A increment. | Current is set immediately, then voltage ramps back toward its stored voltage Goal. | |
| 5. Wait for completion, then change the voltage Goal. | Voltage alone ramps toward the new target. | |
| 6. Turn output OFF. | Confirmed OFF ends the case. | |

### CCS-5.6 - STOP RAMP early, mid-ramp, and near completion

**Description:** Verify that STOP halts setpoint stepping but does not imply
output disable or Goal completion.

**Initial conditions:** Selected channel OFF with a ramp requiring multiple
steps.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Start Ramp Current and press `STOP RAMP` immediately after the first Sent step. | Further current steps stop; output remains physically ON; Goal remains the requested endpoint; Sent/measured retain the last applied value; STOP action is logged. | |
| 2. Turn output OFF, restart the ramp, and stop near the midpoint. | The same semantics hold at a different point; no generic limit/failure message mislabels the operator stop. | |
| 3. Turn output OFF, restart, and stop after the last set step but before final verification. | Worker exits without falsely logging a verified completion; output remains ON until separately disabled. | |
| 4. Repeat one representative STOP branch in Ramp Voltage. | Voltage stepping halts, output stays ON, and Goal/Sent/Measured remain distinct. | |
| 5. After each stop, press the output toggle OFF. | SOUT0 is required and acknowledged separately; only then do physical output and toggle show OFF. | |

### CCS-5.7 - Output OFF request during an active ramp

**Description:** Verify that the output toggle stops the worker and performs an
acknowledged shutoff.

**Initial conditions:** A multi-step ramp is active and output is ON.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Press the ON-looking output toggle during a middle ramp step. | The ramp stop signal is set, SOUT0 is sent through the unconditional OFF path, and no later ramp step is applied after confirmed shutoff. | |
| 2. Observe the front panel and dashboard. | Physical output turns OFF; toggle changes OFF only after acknowledgement; STOP disables and idle controls recover. | |
| 3. Wait longer than two former step intervals. | No stale ramp step, final target, or SOUT1 replays. | |

### CCS-5.8 - Current ramp under CV limitation

**Description:** Verify the current implementation's final-only response when a
current ramp cannot reach its target because voltage is binding.

**Initial conditions:** Configure the approved safe dummy-load condition that
places the supply in CV limitation during Ramp Current. Targets remain at or
below 0.50 V and below 2.00 A.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Start Ramp Current toward a safe target that the load cannot reach at the fixed voltage. | Driver continues issuing every planned current set step; it does not stop after consecutive CV observations and does not restore a last-good setpoint. | |
| 2. Observe Sent, Measured, and front-panel mode throughout. | Sent current reaches the requested setting while measured current remains voltage-limited and the front panel/dashboard show CV consistently. | |
| 3. Wait for final verification. | After all Sent steps reach the requested setting, measured current more than 0.10 A from target produces callback failure and the implemented `aborted before reaching the requested setpoint` warning; record that wording as final-measurement failure, not early step abortion. | |
| 4. Inspect output and controls after the warning. | Output and toggle remain ON; last sent setpoint remains; STOP disables and idle controls return; no automatic SOUT0 occurs. | |
| 5. Turn output OFF and restore the normal approved pair. | Confirmed OFF and safe baseline are restored. | |

### CCS-5.9 - Voltage ramp under CC limitation

**Description:** Verify the current implementation's final-only response when a
voltage ramp cannot reach its target because current is binding.

**Initial conditions:** Configure the approved safe dummy-load condition that
places the supply in CC limitation during Ramp Voltage.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Start Ramp Voltage toward a safe target that the load cannot reach at the fixed current. | Driver continues issuing all planned voltage steps; it does not stop on consecutive CC observations or restore a last-good setpoint. | |
| 2. Observe Sent, Measured, and front-panel mode. | Sent voltage reaches the requested setting while measured voltage remains current-limited and dashboard/front panel show CC consistently. | |
| 3. Wait for final verification. | After all Sent steps reach the requested setting, measured voltage more than 0.20 V from target produces failure and the implemented ramp-aborted warning; no early limit abort or last-good restore occurred. | |
| 4. Inspect state after failure. | Output/toggle remain ON, last sent setting remains, and controls re-enable without an automatic OFF. | |
| 5. Turn output OFF and restore normal safe Goals. | Physical and UI state return OFF. | |

### CCS-5.10 - Communication and individual-power loss during a ramp

**Description:** Verify the different physical consequences of USB loss and a
9104 power-cycle while the worker is active.

**Initial conditions:** Selected channel ramping at safe values; capture exact
last Sent and front-panel readings.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Remove the shared 9104 USB cable during a middle ramp step. | All three COM ports disappear; the selected supply remains physically energized at its last applied setting; the ramp fails after bounded retries and does not send further steps. | |
| 2. Inspect dashboard ramp/output state. | Measured values clear and controls disable; Goal/Sent/toggle remain; no cleanup OFF is falsely claimed and no automatic ramp resume occurs. | |
| 3. Restore USB with the same COM numbers, wait for readiness, then issue a confirmed OFF. | Reconnect/configuration occurs once; no target replay occurs; SOUT0 safely turns off the still-powered output. | |
| 4. Start a new ramp, then switch off only the selected 9104. | That physical output and display turn off and the unit loses preset/setpoints/protections; its ramp fails, while the other two 9104 channels remain live. | |
| 5. Restore the individual supply. | Fresh readback causes preset 3 and safe protections to be re-applied before green; setpoints/output are not restored; the stale ON toggle remains until a healthy OFF reconciliation. | |
| 6. Press the ON-looking toggle once after recovery. | SOUT0 is acknowledged at zeroed hardware, and the dashboard toggle becomes OFF without energizing the output. | |

### CCS-5.11 - Cleared controlled Goal followed by a cross-mode change

**Description:** Exercise the nuanced failure path in which an energized ramp
mode no longer has the stored target needed for its follow-up ramp.

**Initial conditions:** Selected channel ON and idle in Ramp Current with both
Goals present.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Clear the current Goal using the empty current Entry. | Current Goal/Sent clear locally; physical output remains at its last setting and voltage Goal remains. | |
| 2. Change the voltage Goal by a safe valid increment. | The immediate voltage phase may apply, but the missing current target prevents a valid follow-up current ramp; an explicit error is shown/logged and no worker runs with a None target. | |
| 3. Verify output state and issue confirmed OFF. | Any partial change is visible in Sent/measured/front-panel evidence; SOUT0 returns the system safe. | |
| 4. Restore both Goals, enable in Ramp Voltage, then clear the voltage Goal. | Physical output remains energized while the controlled Goal clears locally. | |
| 5. Change current by a safe increment. | The missing voltage target prevents a valid follow-up voltage ramp and is reported without a background exception or false completion. | |
| 6. Issue confirmed OFF and restore Goals. | Safe coherent baseline is restored. | |

## Suite 6 - Protection, slew, and Config-tab controls

**Description:** Exercise every Config-tab input, confirmation path, local
setting, query action, and unavailable-state response within the fixture limits.

**Initial conditions:** Common initial conditions apply; all outputs OFF. Never
leave a confirmed OVP above 0.50 V or OCP at or above 2.00 A.

### CCS-6.1 - OVP input validation and confirmed readback

**Description:** Verify missing, invalid, boundary, precision, and acknowledged
OVP behavior.

**Initial conditions:** Selected 9104 ready with OVP 0.50 V and output OFF.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Leave the OVP Entry empty and press `Set`. | A missing-input error appears and logs the correct cathode; live OVP remains 0.50 V. | |
| 2. Enter alphabetic text and press `Set`. | The value is rejected as nonnumeric with no hardware command or live-value change. | |
| 3. Enter `0.01`. | The value below the implemented minimum is rejected and OVP remains 0.50 V. | |
| 4. Enter `0.02`. | The code-supported lower boundary is sent, acknowledged, read back as 0.02 V, and committed only after confirmation; UI guidance must not contradict its acceptance. | |
| 5. Restore `0.50`. | Hardware readback and live display confirm 0.50 V and the Entry clears. | |
| 6. Enter `0.025`. | Excess precision is rejected rather than silently quantized to a different protection value. | |
| 7. Enter `nan`. | NaN is rejected before hardware conversion; no exception, NaN display, or protection change occurs. | |
| 8. Enter `inf`. | Positive infinity is rejected before hardware conversion and live OVP remains safe. | |
| 9. Enter `-inf`. | Negative infinity is rejected before hardware conversion and live OVP remains safe. | |
| 10. With the supply unavailable and output physically OFF, enter `84.01`. | The GUI rejects the documented over-range value without attempting hardware access; the safe 0.50 V baseline is preserved after recovery. | |

### CCS-6.2 - OCP input validation and confirmed readback

**Description:** Verify missing, invalid, boundary, precision, and acknowledged
OCP behavior below the 2 A fixture limit.

**Initial conditions:** Selected 9104 ready with OCP 1.99 A and output OFF.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Submit an empty OCP Entry. | Missing-input error names the cathode; live OCP remains 1.99 A. | |
| 2. Submit alphabetic text. | Nonnumeric input is rejected with no hardware change. | |
| 3. Submit `0.09`. | Below-minimum OCP is rejected. | |
| 4. Submit `0.10`. | The code-supported lower boundary is acknowledged and confirmed at 0.10 A; UI guidance agrees with the accepted boundary. | |
| 5. Restore `1.99`. | Live display and physical query confirm 1.99 A before other output tests. | |
| 6. Submit `0.105`. | Excess precision is rejected rather than silently rounded to a different limit. | |
| 7. Submit `nan`. | NaN is rejected without an exception or live-value corruption. | |
| 8. Submit `inf`. | Positive infinity is rejected without changing OCP. | |
| 9. Submit `-inf`. | Negative infinity is rejected without changing OCP. | |
| 10. With the supply unavailable and output physically OFF, submit `10.01`. | The documented over-range value is rejected by the GUI without changing the safe baseline after recovery. | |

### CCS-6.3 - Protection confirmation failure and power-cycle reapplication

**Description:** Verify that readiness requires fresh, matching protection
confirmation and that a zero-default power cycle does not restore output.

**Initial conditions:** Selected supply OFF with confirmed preset 3, OVP 0.50 V,
OCP 1.99 A, and nonzero staged Goals.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Switch the selected 9104 OFF and verify its COM entry remains present in the OS. | The device display goes dark and hardware output, preset, setpoints, OVP, and OCP lose power; dashboard readback becomes unavailable and dot red. | |
| 2. Switch it ON and watch the physical display before the dashboard finishes configuration. | The 9104 starts with zeroed output/setpoints/protections; dashboard remains red/unready during this interval. | |
| 3. Observe automatic reconnect initialization. | After a valid GETD response, dashboard sets preset 3 and desired OVP/OCP and reads them back; dot turns green only after complete confirmation. | |
| 4. On up to three exploratory repetitions, try to interrupt communication during OVP or OCP confirmation. | If the phase is attained, configuration remains incomplete/red and command controls stay unavailable; otherwise record the sub-second branch as not attained rather than failed. | |
| 5. Restore communication and wait through the retry cooldown. | One later complete configuration succeeds and returns green; no stale voltage/current Goal is sent and output remains physically OFF. | |
| 6. Confirm live OVP/OCP and restore them if needed. | Final baseline is 0.50 V/1.99 A and preset 3 with zero physical output. | |

### CCS-6.4 - Current slew-rate input and observed cadence

**Description:** Verify current slew setting validation, spin control, display,
and effect on Ramp Current timing.

**Initial conditions:** Selected channel ready and OFF; current slew initially
0.01 A/s.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Click the current slew spinbox up arrow while its Entry is blank. | Entry populates with the next valid increment without committing until `Set` is pressed. | |
| 2. Press `Set` with a valid value such as `0.20`. | Live current slew shows 0.20 A/s, Entry clears, and an INFO log uses A/s. | |
| 3. Submit an empty current slew Entry. | Empty input is rejected and the prior 0.20 A/s value remains. | |
| 4. Submit alphabetic text. | Nonnumeric input is rejected and prior slew remains. | |
| 5. Submit `0`. | Zero slew is rejected as nonpositive. | |
| 6. Submit a negative slew. | Negative slew is rejected. | |
| 7. Submit `nan`. | NaN is rejected and cannot reach ramp math. | |
| 8. Submit `inf`. | Infinity is rejected and cannot reach ramp math. | |
| 9. Submit an excess-precision value such as `0.015`. | The value is rejected rather than silently changed to a different displayed rate. | |
| 10. Submit a value above the spinbox's advertised 10.00 A/s range. | The out-of-widget-range value is rejected and prior slew remains. | |
| 11. Start a short safe Ramp Current and time at least three Sent steps. | Step change and approximately one-second cadence correspond to the committed slew; no step causes current at or above 2.00 A. | |
| 12. Stop the ramp, issue confirmed OFF, and restore the planned suite rate. | Output is OFF and configured rate is ready for later cases. | |

### CCS-6.5 - Voltage slew-rate input and observed cadence

**Description:** Verify voltage slew setting validation, spin control, display,
and effect on Ramp Voltage timing.

**Initial conditions:** Selected channel ready and OFF; voltage slew initially
0.02 V/s.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Click the voltage slew spinbox up arrow with a blank Entry. | Entry populates with the next 0.02 V/s increment without immediate commitment. | |
| 2. Set `0.04`. | Live voltage slew becomes 0.04 V/s, Entry clears, and log units are V/s. | |
| 3. Submit an empty voltage slew Entry. | Empty input is rejected and 0.04 V/s remains. | |
| 4. Submit alphabetic text. | Nonnumeric input is rejected and prior slew remains. | |
| 5. Submit `0`. | Zero slew is rejected. | |
| 6. Submit a negative slew. | Negative slew is rejected. | |
| 7. Submit `nan`. | NaN is rejected and cannot reach ramp math. | |
| 8. Submit `inf`. | Infinity is rejected and cannot reach ramp math. | |
| 9. Submit `0.03`. | A value inconsistent with the displayed 0.02 V/s increment is rejected rather than silently accepted. | |
| 10. Submit `0.08`, above the spinbox's advertised 0.06 V/s maximum. | Value is rejected and UI/backend range behavior agrees. | |
| 11. Start a short safe Ramp Voltage and time at least three Sent steps. | Approximately 0.04 V steps occur once per second and never exceed 0.50 V. | |
| 12. Stop, issue confirmed OFF, and restore the planned suite rate. | Physical and dashboard output are OFF. | |

### CCS-6.6 - Difference-warning threshold input controls

**Description:** Verify both voltage and current threshold setters before testing
their live timing behavior.

**Initial conditions:** Selected channel ready and OFF; both live thresholds 10%.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Submit a blank voltage threshold. | A voltage-specific missing error appears and live value stays 10%. | |
| 2. Submit text as the voltage threshold. | Nonnumeric voltage threshold is rejected with no live-value or highlight change. | |
| 3. Submit a negative voltage threshold. | Negative percentage is rejected. | |
| 4. Submit `nan` as the voltage threshold. | NaN is rejected and no warning calculation is corrupted. | |
| 5. Submit `inf` as the voltage threshold. | Infinity is rejected and live threshold remains finite. | |
| 6. Set voltage threshold to `0`. | Live value shows 0%; Entry clears; any prior voltage warning timer/highlight resets. | |
| 7. Set voltage threshold to `2.5`. | Live value shows 2.5%; setting is logged with cathode and measurement type. | |
| 8. Submit a blank current threshold. | A current-specific missing error appears and its prior value remains. | |
| 9. Submit text as the current threshold. | Nonnumeric current threshold is rejected. | |
| 10. Submit a negative current threshold. | Negative percentage is rejected. | |
| 11. Submit `nan` as the current threshold. | NaN is rejected. | |
| 12. Submit `inf` as the current threshold. | Infinity is rejected. | |
| 13. Set current threshold to `0`. | Live value shows 0% and current warning state resets. | |
| 14. Set current threshold to `2.5`. | Current setting commits independently without changing voltage threshold. | |
| 15. Set voltage threshold to a large finite value such as `100`. | Explicit finite percentage displays consistently and no hardware command occurs. | |
| 16. Set current threshold to `100`. | Current threshold updates independently. | |
| 17. Restore voltage threshold to 10%. | Voltage warning baseline is restored. | |
| 18. Restore current threshold to 10%. | Current warning baseline is restored. | |

### CCS-6.7 - Overtemperature-limit input control

**Description:** Verify finite, sensible temperature limit handling and local
status update.

**Initial conditions:** Selected E5CN reading valid near room temperature;
output OFF; overtemperature limit 150 C.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Submit an empty overtemperature Entry. | Invalid input is visible to the operator and logged; 150 C remains active. | |
| 2. Submit alphabetic text. | Input is rejected without altering the limit or status. | |
| 3. Submit a negative value. | Nonsensical negative limit is rejected and cannot force a permanent warning. | |
| 4. Submit `nan`. | NaN is rejected; overtemperature warning cannot be silently disabled. | |
| 5. Submit `inf`. | Positive infinity is rejected and the prior finite limit remains. | |
| 6. Submit `-inf`. | Negative infinity is rejected and the prior finite limit remains. | |
| 7. Set a finite value several degrees above the current temperature. | Live limit updates, Entry reflects the committed value, and status remains Normal. | |
| 8. Restore 150 C. | Normal baseline is restored without a hardware command. | |

### CCS-6.8 - Log Power Settings success, mismatch, and read failure

**Description:** Verify the only explicit Config query and require semantic
comparison of both preset quantities.

**Initial conditions:** Selected 9104 ready, output OFF, safe Goals known.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. With no voltage/current Goals, press `Log Power Settings`. | GETS3 is read once and log reports both actual preset voltage and current with punctuation and units; it does not invent expected values. | |
| 2. Stage Goals equal to preset 3 and press the button. | Log confirms both voltage and current match their Goals. | |
| 3. Change only the staged voltage Goal while output stays OFF, then press the button. | Log reports a voltage mismatch and still reports actual current accurately. | |
| 4. Restore voltage Goal and change only current Goal while OFF, then query. | Log reports a current mismatch rather than declaring settings matched based only on voltage. | |
| 5. Remove communication and press the button during the stale-ready window. | Failed GETS3 is logged as a read failure; no stale settings are reported as fresh. | |
| 6. Wait for red/unavailable state. | `Log Power Settings` is disabled or cannot execute as a ready query. | |
| 7. Restore and query once after readiness. | One fresh response is logged and no duplicate query worker remains. | |

### CCS-6.9 - Config actions while a channel is unavailable

**Description:** Distinguish local-only settings from actions requiring a ready
9104.

**Initial conditions:** Switch off one selected 9104; its E5CN remains healthy
and other supplies stay ready.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Attempt OVP and OCP Set actions after the 9104 dot is red. | Each refuses hardware change and reports the supply unavailable; it does not show a second contradictory success. | |
| 2. Attempt `Log Power Settings`. | Query is disabled or rejected without stale GETS3 data. | |
| 3. Change a local difference threshold and slew value. | Local settings may update explicitly without implying delivery to the unavailable 9104. | |
| 4. Change the finite overtemperature limit. | E5CN-based status follows the local limit because its sensor remains connected; no 9104 connection is implied. | |
| 5. Restore the 9104 and wait for readiness. | Hardware commands remain blocked until configured; local values remain associated only with the intended channel. | |
| 6. Restore all common Config baselines. | OVP 0.50 V, OCP 1.99 A, thresholds 10%, overtemperature 150 C, and planned slew values are established. | |

### CCS-6.10 - Config and LUT actions during an active ramp

**Description:** Verify that Config-tab actions remaining available during a
ramp serialize safely and do not silently alter the active worker's plan.

**Initial conditions:** Selected channel in a multi-step safe ramp with Goals
well below 0.50 V/1.99 A; all other outputs OFF.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Open the selected channel's Config tab during the ramp. | Available Config controls remain associated with the correct channel; ramp status and STOP remain visible/reachable through tab navigation. | |
| 2. Set OVP to a confirmed safe value above the active voltage Goal. | Transaction serializes with ramp traffic, reads back correctly, and neither response is assigned to the wrong command. | |
| 3. Set OCP to a confirmed safe value above the active current Goal. | OCP confirms without starting/stopping output or corrupting a ramp step. | |
| 4. Press `Log Power Settings` during a ramp step. | GETS3 either waits boundedly or reports busy/failure; it does not freeze UI or parse a ramp acknowledgement as settings. | |
| 5. Change the configured slew rate while the current ramp is already active. | Live setting changes for future ramps; the active worker retains the step size captured when it started and does not jump cadence mid-ramp. | |
| 6. Change a difference threshold and finite overtemperature limit. | Local warning settings update without changing output/setpoints or creating a second ramp worker. | |
| 7. Change to another valid LUT. | Predictions recompute locally from Goals; no extra power command is sent. | |
| 8. Press STOP, then issue confirmed OFF and restore common Config values. | Ramp halts, physical output turns OFF only after SOUT0, and all safety baselines return. | |

## Suite 7 - Live readbacks, CV/CC indication, and difference warnings

**Description:** Verify physical/display parity, state-source separation,
mode-specific warning timing, warning clearing, and transient poll contention.

**Initial conditions:** Common initial conditions apply. Use the approved
`CV_PAIR` and `CC_PAIR` without exceeding fixture limits.

### CCS-7.1 - Sent, Goal, Measured, and physical-state separation

**Description:** Prove each displayed value represents its documented source.

**Initial conditions:** Selected channel ready and OFF; preset values recorded.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Stage safe current and voltage Goals while OFF. | Goal fields and predictions change; Sent remains `--` and Measured/front-panel state remains the prior hardware state. | |
| 2. Enable Immediate output. | Sent fields populate in acknowledgement order; Goals remain fixed; Measured updates only from later GETD data. | |
| 3. Change one live Goal. | Goal changes at acceptance, Sent changes at command acknowledgement, and Measured changes only on a fresh poll. | |
| 4. Start a controlled ramp. | Goal stays at endpoint, Sent advances by step, and Measured/front-panel response can lag or be limited. | |
| 5. Stop the ramp and inspect all sources. | Goal, last Sent, fresh Measured, and physical display remain independently truthful; no field is relabeled as another source. | |
| 6. Issue confirmed OFF. | Output state becomes OFF while historical Goals remain stored unless explicitly cleared. | |

### CCS-7.2 - 9104 voltage/current and CV/CC parity on all channels

**Description:** Compare every dashboard readback and mode indication with its
physical 9104 in OFF, CV, and CC conditions.

**Initial conditions:** All channels healthy and OFF.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Record each 9104's OFF-state voltage/current and CV/CC indicators and compare with the dashboard. | Dashboard A/B/C values map to the correct unit and agree to displayed resolution; mode indication does not fabricate an active condition. | |
| 2. Apply `CV_PAIR` to Cathode A and enable output. | A front panel and dashboard both identify CV and show matching V/I; B/C remain unchanged. | |
| 3. Repeat `CV_PAIR` on B and C one at a time. | Each dashboard mode and readback follows only its mapped supply. | |
| 4. Apply `CC_PAIR` to A, B, and C one at a time. | Corresponding physical and dashboard indicators both identify CC and values remain within limits. | |
| 5. Transition one supply between CV and CC without disconnecting. | Dashboard changes only after a fresh GETD response and does not briefly mark both CV and CC green. | |
| 6. Turn every output OFF. | Physical outputs are confirmed OFF and all toggles reconcile. | |

### CCS-7.3 - Voltage-difference warning in CV Mode

**Description:** Verify the 1.5-second voltage warning threshold and single
continuous-breach semantics.

**Initial conditions:** Selected channel ON in stable CV Mode with nonzero Sent
voltage and a stable nonzero measured difference. Calculate
`D = 100 * abs(Measured - Sent) / abs(Sent)` and
`EPS = min(0.1, D / 2)` in percentage points. If no stable nonzero difference
is safely attainable, mark the boundary branch blocked.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Set the voltage threshold to calculated `D` and hold the stable condition longer than 1.5 s. | Voltage box remains normal because difference equal to the threshold does not exceed it. | |
| 2. Set the threshold to `D - EPS` for less than 1.5 s, then restore it to `D + EPS`. | No orange highlight or breach warning occurs; the short timer clears. | |
| 3. Set the threshold to `D - EPS` and hold the same stable condition longer than 1.5 s. | Voltage measured box turns orange and one WARNING reports cathode, measured, Sent, difference, and threshold. | |
| 4. Continue the same breach for at least 3 s. | Highlight remains orange but the same continuous breach does not flood duplicate operator-level warnings. | |
| 5. Set the threshold to `D + EPS`. | Highlight clears and one warning-cleared INFO is logged. | |
| 6. Switch the same electrical discrepancy to CC Mode. | Voltage warning remains inactive because voltage checks are gated to CV. | |
| 7. Turn output OFF and restore threshold 10%. | Warning state/timer clears and output is safely OFF. | |

### CCS-7.4 - Current-difference warning in CC Mode

**Description:** Verify the corresponding current warning path and mode gating.

**Initial conditions:** Selected channel ON in stable CC Mode with nonzero Sent
current and a stable nonzero measured difference. Calculate `D` and `EPS` as in
CCS-7.3 using current. If no stable nonzero difference is safely attainable,
mark the boundary branch blocked.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Set the current threshold to calculated `D` and hold longer than 1.5 s. | Current box remains normal at exact equality. | |
| 2. Set the threshold to `D - EPS` for less than 1.5 s, then restore `D + EPS`. | No persistent highlight or warning is logged. | |
| 3. Set the threshold to `D - EPS` and hold longer than 1.5 s. | Current box turns orange and one complete current-specific WARNING appears. | |
| 4. Remain breached, then set threshold to `D + EPS`. | No duplicate breach flood occurs; recovery clears highlight and logs once. | |
| 5. Change to CV Mode while preserving a current difference. | Current warning clears because current checks are active only in CC. | |
| 6. Turn output OFF and restore threshold 10%. | Warning state clears and safe output state is confirmed. | |

### CCS-7.5 - Warning reset and disabled-condition matrix

**Description:** Exercise every branch that disables or restarts a measured-
output warning.

**Initial conditions:** Selected channel can produce a repeatable warning and is
initially OFF.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Set the relevant threshold to 0% and enable with a nonzero Sent value that differs from Measured. | Any nonzero difference begins the timer and warns only after more than 1.5 s in the correct mode. | |
| 2. Set the relevant Sent quantity to zero. | Warning and timer clear because percent difference from zero is disabled. | |
| 3. Restore nonzero Sent, begin a breach, then change the threshold before 1.5 s. | Timer resets and no stale-duration warning appears. | |
| 4. Begin a breach, then apply a successful new Sent step during a ramp. | Timer resets from the new Sent value; old difference history is not carried across the step. | |
| 5. Begin a breach, then clear that Goal with an empty Set. | Corresponding warning clears immediately even though physical output may remain; the cleared display does not retain orange. | |
| 6. Begin a breach, then remove 9104 communication. | Measured display clears and warning resets; unavailable data is not treated as a numeric breach. | |
| 7. Restore communication and fresh data. | No warning resumes until the current Sent/Measured/mode conditions create a new full-duration breach. | |
| 8. Issue confirmed OFF and restore both thresholds to 10%. | Safe baseline is restored. | |

### CCS-7.6 - Exploratory serial-lock contention and readback freshness

**Description:** Distinguish a transient busy poll from a confirmed disconnect.
Attempt the contention pattern for up to 30 s; absence of an observed busy
cycle is recorded as not attained rather than a failure.

**Initial conditions:** Selected channel ready and stable; file logging VERBOSE.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Rapidly invoke `Log Power Settings` and safe Set actions while the 500 ms poller runs. | UI remains responsive and serial transactions stay serialized; no overlapping response is assigned to the wrong command. | |
| 2. Check for a `serial interface busy` readback cycle during the bounded attempt. | If observed, the first driver lock timeout may be WARNING while the CCS readback-skip record is DEBUG and repeats become VERBOSE; known readiness/green state is not revoked solely by busy. | |
| 3. If a busy cycle was observed, inspect Measured and CV/CC for that cycle. | A transient blank is distinguishable from disconnect; no plausible stale value is presented as newly measured. | |
| 4. Stop rapid actions and wait for two normal cycles. | Fresh readback repopulates values without reconnect/config duplication or a false recovery transition. | |
| 5. Review A/B/C logs and values. | No response, mode, or measurement crosses channel boundaries. | |

## Suite 8 - E5CN temperatures, sensor faults, and transport failures

**Description:** Verify temperature mapping, touch response, overtemperature
semantics, `S.ERR` handling, RS-485 loss, laptop-adapter loss, and recovery.

**Initial conditions:** Common initial conditions apply; all thermocouples
installed near room temperature. Keep 9104 outputs OFF unless a case explicitly
verifies that temperature monitoring does not control them.

### CCS-8.1 - E5CN display mapping and touch response

**Description:** Prove slave-to-cathode mapping using local displays and safe
dummy-thermocouple warming.

**Initial conditions:** E5CN units 1-3 and dashboard temperature dots green.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Record each E5CN front-panel temperature and corresponding A/B/C dashboard value. | Unit 1 maps to A, unit 2 to B, and unit 3 to C; dashboard equals the physical value rounded to its displayed precision and is consistent with recorded `E5_DISPLAY_RESOLUTION` after normal polling latency. | |
| 2. Touch only dummy thermocouple A's insulated output until its display rises several degrees. | E5CN A and dashboard A rise together; B/C remain near their baselines. | |
| 3. Release A and wait for cooling. | A dashboard value follows the physical display downward without latching a stale peak. | |
| 4. Repeat touch/cool behavior for B and C individually. | Each changes only its mapped dashboard row and retains a green comms dot while numeric. | |
| 5. Inspect logs. | Numeric temperature updates are not mislabeled as sensor faults or overtemperature unless the configured limit is actually crossed. | |

### CCS-8.2 - Overtemperature equality, breach, recovery, and output independence

**Description:** Verify threshold comparison and warning/log behavior using the
20-30 C touch range.

**Initial conditions:** Selected thermocouple stable. Set its overtemperature
limit to a reachable finite value above baseline. A 9104 output may be ON at a
safe pair only for the explicit independence step.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. While temperature is stable, set the limit equal to the current dashboard value and do not touch the sensor for one refresh. | Status remains `Normal` and the temperature box remains normal because only values above the limit breach. | |
| 2. Touch the dummy thermocouple until its physical display and dashboard exceed the limit. | Status becomes `OVERTEMP!`, temperature box turns orange, and a CRITICAL log names the correct cathode. | |
| 3. Hold temperature above the limit for several refresh cycles. | Warning remains active without an unbounded duplicate CRITICAL flood; the event remains one continuous breach. | |
| 4. If output was safely enabled for this step, observe it during the breach. | CCS output is not automatically disabled by the solo overtemperature warning; toggle and physical output stay mutually consistent. | |
| 5. Release the thermocouple and wait below the limit. | Status returns `Normal`, orange clears, and recovery is evident in the log without changing output state. | |
| 6. Issue confirmed OFF if used and restore overtemperature limit to 150 C. | Safe common baseline is restored. | |

### CCS-8.3 - Single dummy-thermocouple removal and restoration

**Description:** Verify per-sensor `S.ERR` handling without declaring a whole-
network failure or overtemperature.

**Initial conditions:** All three temperatures numeric and dots green; outputs
OFF.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Remove dummy thermocouple A from E5CN A. | Physical E5CN A shows `S.ERR`; dashboard A shows `ERR`, A temperature dot turns red, and A overtemperature status becomes `N/A` with normal non-overtemp background. | |
| 2. Inspect B/C temperature and all 9104 states. | B/C remain numeric/green and every 9104 remains unaffected; sensor error is not logged as overtemperature. | |
| 3. Inspect E5CN and CCS logs for longer than 10 s. | Error identifies unit/cathode A and sensor-invalid semantics; operator-level repetitions are rate-limited while VERBOSE diagnostics remain available. | |
| 4. Reinstall A's dummy thermocouple. | Physical display becomes numeric; dashboard A returns numeric/green and emits one valid-connection recovery transition. | |
| 5. Repeat removal/restoration for B and C. | Each fault and recovery maps only to its own channel. | |

### CCS-8.4 - Multiple sensor faults and out-of-order recovery

**Description:** Verify independent `S.ERR` state when more than one sensor is
open.

**Initial conditions:** All sensors healthy and outputs OFF.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Remove dummy thermocouples A and C. | E5CN A/C show `S.ERR`; dashboard A/C show ERR/red/N/A; B remains numeric/green. | |
| 2. Remove B as well. | All three show sensor-specific ERR/red while the adapter/network remains present; no false transport-disconnect message replaces the sensor errors. | |
| 3. Restore C first, then A, then B with a fresh reading between actions. | Each channel independently returns numeric/green and logs one recovery; unrecovered channels remain ERR. | |
| 4. Compare final temperatures with all E5CN displays. | Correct A/B/C mapping and normal state are fully restored. | |

### CCS-8.5 - E5CN-side RS-485 network-cable loss

**Description:** Distinguish a silent Modbus network from disappearance of its
laptop COM adapter.

**Initial conditions:** All E5CN values numeric; note the `TempControllers` COM
port in the OS; 9104 outputs OFF.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Remove the RS-485 cable between the USB/RS-485 converter and the E5CN network. | The TempControllers COM port remains enumerated and all E5CNs remain powered with valid local displays. | |
| 2. Observe dashboard values through the driver's retries. | Previously cached values are not presented indefinitely; each channel eventually becomes `-- C`, `N/A`, and red while 9104 data remains live. | |
| 3. Inspect logs for at least 12 s. | Per-unit read/null/no-data failures appear with bounded operator-level cadence; no log falsely calls the COM port absent or a thermocouple `S.ERR`. | |
| 4. Restore the RS-485 cable. | Numeric data resumes automatically without COM selection; each channel returns green after its own fresh read. | |
| 5. Inspect recovery logs. | One valid-connection transition per cathode appears; no duplicate E5CN reader set is started. | |

### CCS-8.6 - Laptop USB/RS-485 adapter removal and same-COM recovery

**Description:** Verify COM disappearance, reconnect attempts, and recovery when
Windows restores the original port.

**Initial conditions:** E5CN system healthy; record the adapter COM number.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Remove the E5CN USB/RS-485 adapter from the testing laptop. | TempControllers COM port disappears; E5CN front panels remain powered/numeric; dashboard temperatures transition to `-- C`/red/N/A. | |
| 2. Inspect 9104 UI and physical outputs. | Power-supply control/readback is unaffected by the E5CN adapter loss. | |
| 3. Inspect logs through at least one reconnect cycle. | Reconnect/read failures identify E5CN/TempControllers and do not claim a sensor-open or 9104 fault. | |
| 4. Reinsert the adapter and verify Windows assigns the same COM number. | Existing E5CN workers reopen the port and numeric readings resume without dashboard restart. | |
| 5. Restart the testing laptop and launch the dashboard. | A/B/C return numeric/green with correct mapping. | |

### CCS-8.7 - Temperature fault during an energized output or ramp

**Description:** Verify that solo CCS temperature monitoring failure remains
visible but does not corrupt 9104 command execution.

**Initial conditions:** One selected 9104 safely ON or ramping; all temperatures
initially valid. The excluded integration guards remain disabled.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Remove the selected channel's dummy thermocouple. | E5CN shows S.ERR and dashboard shows ERR/red/N/A; the 9104 output/ramp continues without a hidden setpoint change or automatic OFF. | |
| 2. Restore the sensor during the same output state. | Fresh temperature/green state returns and no 9104 command is injected. | |
| 3. Cut and restore the E5CN RS-485 cable during a ramp. | Temperature monitoring becomes unavailable and recovers; ramp Sent/Measured power path continues independently and stays within limits. | |
| 4. Stop the ramp if active and issue confirmed OFF. | Safe physical output state is restored. | |
| 5. Review logs. | Temperature faults, ramp events, and recovery are chronologically distinct and no cross-subsystem action is asserted. | |

## Suite 9 - 9104, USB, and total-CCS physical failures

**Description:** Distinguish individual supply power loss, shared USB/COM loss,
and total CCS power loss while idle, energized, and ramping.

**Initial conditions:** Common initial conditions apply. Record the Windows COM
list, physical output state, dashboard toggle, Goals, Sent, Measured, mode,
OVP/OCP, and temperatures immediately before every fault. Use only safe
setpoints.

### CCS-9.1 - Individual 9104 power switch while idle

**Description:** Verify isolated loss and zero-default recovery of each physical
9104.

**Initial conditions:** All outputs OFF; all channels ready; safe Goals may be
staged.

| Test steps | Expected results | Notes |
| --- | --- | --- |
| 1. Switch off 9104 A and inspect the OS COM list. | A display goes dark and its device stops responding; the adapter COM remains enumerated; B/C remain powered. | |
| 2. Observe dashboard fault detection. | A Measured V/I clear, CV/CC gray, A 9104 dot turns red, and A command controls disable; A Goals/Sent/toggle are preserved; B/C remain ready. | |
| 3. Inspect logs for longer than 10 s. | Errors identify A and invalid/no readback with bounded operator-level cadence; no B/C or E5CN fault is asserted. | |
| 4. Switch A back ON and observe its front panel before recovery. | Physical output and displayed voltage/current start at zero; subsequent dashboard logs show preset 3 and OVP/OCP being reapplied rather than read from front-panel menus. | |
| 5. Wait for fresh readback and dashboard configuration. | Preset 3 and desired OVP/OCP are re-applied and confirmed before A turns green; voltage/current setpoints and output remain zero. | |
| 6. Compare staged/dashboard state with physical state. | Preserved Goals/Sent are not replayed; measured/front-panel zero exposes any stale historical display. | |
| 7. Repeat the complete power-cycle for B and C. | Each fault remains isolated and recovers through its own configuration path. | |

### CCS-9.2 - Individual 9104 power switch while output is ON

**Description:** Verify conservative commanded-state handling when a power cycle
physically turns off and resets one energized supply.

**Initial conditions:** Selected channel safely ON with nonzero Goals; peers
OFF and healthy.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Switch off only the energized 9104. | Its output and display go dark immediately; dashboard eventually loses Measured/readiness but retains the ON toggle, Goals, and Sent because OFF was not acknowledged. | |
| 2. Verify the dummy load and peer supplies. | Selected load de-energizes; B/C remain unchanged; no software OFF success is logged. | |
| 3. Switch the supply back ON. | Physical output and displayed voltage/current are zero; dashboard re-applies preset 3 and safe OVP/OCP only. | |
| 4. Wait until the 9104 dot is green. | Toggle still shows commanded ON while physical output is OFF; no SOUT1 or stored setpoint is replayed. | |
| 5. Press the ON-looking toggle once. | Healthy SOUT0 is acknowledged at the zeroed supply and dashboard toggle becomes OFF without energizing it. | |
| 6. Press toggle ON only after verifying safe Goals, then press OFF. | A fresh operator command applies current, voltage, and SOUT1; subsequent confirmed SOUT0 restores OFF. | |

### CCS-9.3 - Supply-side shared 9104 USB removal while idle

**Description:** Verify that removing USB at the supply side removes all three
COM ports and leaves E5CN monitoring intact.

**Initial conditions:** All outputs OFF; all 9104s/E5CNs healthy; record three
9104 COM numbers.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Unplug the shared 9104 USB connection at the supply side. | All three 9104 COM ports disappear from Windows; supplies stay powered with their prior OFF/setpoint/protection displays; TempControllers COM remains. | |
| 2. Observe all three dashboard channels. | Every 9104 dot turns red, Measured V/I clear, CV/CC gray, and command controls disable; E5CN temperatures remain numeric/green. | |
| 3. Inspect Goals, Sent, toggles, and local Config values. | Historical requested/commanded state is preserved but not presented as fresh Measured data; toggles remain OFF. | |
| 4. Review logs for a reconnect interval. | Serial/disconnected messages name A/B/C and old ports; reconnect attempts are bounded and no temperature fault is logged. | |
| 5. Reconnect at the supply side with the same COM numbers. | Each driver reopens, proves GETD, confirms preset/OVP/OCP, and returns green once; no SOUT1 or ramp replays. | |
| 6. Confirm all physical outputs OFF and safe protections. | Baseline is coherent across dashboard and front panels. | |

### CCS-9.4 - Laptop-side shared 9104 USB removal while idle

**Description:** Verify equivalent all-port disappearance from the testing-
laptop end.

**Initial conditions:** All outputs OFF and healthy.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Unplug the shared 9104 USB cable at the testing laptop. | All three 9104 COM ports disappear just as in supply-side removal; powered supplies retain physical settings; E5CN remains connected. | |
| 2. Compare UI and logs with CCS-9.3. | Same all-9104 loss semantics occur without a false total-power or E5CN error. | |
| 3. Reinsert the cable and verify the same COM numbers return. | Automatic reopen/configuration restores all three channels without restart or output replay. | |
| 4. Verify one valid-connection transition per supply. | Recovery is neither omitted nor duplicated; physical outputs remain OFF. | |

### CCS-9.5 - Shared 9104 USB loss while outputs are energized

**Description:** Verify the hazardous distinction that communication loss does
not remove power or disable physical outputs.

**Initial conditions:** At least one selected channel safely ON; other outputs
may remain OFF. Emergency CCS power removal is immediately available.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Record the energized 9104 display, output indicator, Goals, Sent, and Measured values. | A complete pre-fault state is captured within limits. | |
| 2. Remove the shared USB cable at either end. | All three COM ports disappear, but the energized supply remains physically ON at its last setpoints and continues powering its dummy load. | |
| 3. Observe dashboard after detection. | Measured values clear and controls disable; ON toggle/Goals/Sent remain as commanded-state history; E5CN monitoring stays live. | |
| 4. Attempt OFF once during the stale-enabled interval. | If SOUT0 cannot be acknowledged, toggle remains ON and CRITICAL uncertain-output logging appears; no false OFF is shown. | |
| 5. Reconnect with the same COM numbers while continuously watching the front panel. | Driver reconnect/configuration does not issue SOUT1, does not resume a ramp, and does not change retained physical output/setpoints except confirmed preset/protection setup. | |
| 6. After readiness, press the ON-looking toggle once. | Acknowledged SOUT0 turns the physical output OFF and reconciles the UI. | |
| 7. Verify every other supply physically OFF. | No peer was enabled by reconnect or reconfiguration. | |

### CCS-9.6 - Total CCS power removal while idle

**Description:** Verify simultaneous silent-device behavior, preserved COM
enumeration, zero-default recovery, and independent reinitialization.

**Initial conditions:** All outputs OFF; Goals may be staged; all devices
healthy.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Remove total CCS power without disconnecting laptop adapters. | All 9104 and E5CN displays go dark and all heater outputs de-energize. | |
| 2. Observe the dashboard through device timeouts. | All 9104 Measured/modes and E5CN temperatures become unavailable; six comms dots turn red; power toggles/Goals/Sent are not silently rewritten. | |
| 3. Inspect logs. | Error wording matches the recorded topology: device-silent/invalid-read when COMs remain, or disconnected/reopen behavior when they disappear; repeats use bounded operator cadence. | |
| 4. Restore total CCS power. | 9104s and E5CNs boot; 9104 outputs and displayed V/I start at zero; dashboard logs reapplication of preset/OVP/OCP and E5CNs return local numeric readings. | |
| 5. Observe dashboard recovery. | Each 9104 becomes green only after preset 3 and desired protections are confirmed; each E5CN becomes green after its numeric read. | |
| 6. Inspect staged state and physical displays. | Stored Goals/Sent are not replayed; all physical outputs and setpoints remain zero; no automatic SOUT1 occurs. | |
| 7. Restore OVP/OCP to 0.50 V/1.99 A if needed. | Full safe baseline is confirmed. | |

### CCS-9.7 - Total CCS power removal while output is ON

**Description:** Verify the physical OFF reset and stale commanded ON state after
a full power cycle.

**Initial conditions:** One selected output safely ON; other outputs OFF.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Remove total CCS power. | All physical outputs de-energize and displays go dark; dashboard cannot receive an OFF acknowledgement and therefore preserves the selected ON toggle/Goals/Sent. | |
| 2. Restore total power and observe the selected 9104. | It boots at zero output/setpoints/protections and remains physically OFF while dashboard reconfigures preset/limits. | |
| 3. Wait for all six comms dots to recover. | No old setpoint, SOUT1, or ramp is replayed; selected dashboard toggle can remain ON as conservative commanded-state history. | |
| 4. Compare dashboard and physical state explicitly. | Measured/front-panel zero and output-OFF evidence expose the stale ON toggle; the discrepancy is not logged as a confirmed OFF. | |
| 5. Press the ON-looking toggle once. | SOUT0 is acknowledged and dashboard toggle becomes OFF without energizing the zeroed supply. | |
| 6. Restore safe Goals only through fresh operator actions if further testing is needed. | No recovery action silently turns output on. | |

### CCS-9.8 - Exploratory actions during stale-green and confirmed-red windows

**Description:** Exercise relevant UI actions across the short detection window
and stable unavailable state. Attempt each stale-window action no more than
three times; record a missed sub-poll window as not attained.

**Initial conditions:** Selected channel ready and OFF with safe Goals; prepare
an individual 9104 power-off fault.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Switch off the supply and immediately press current Set before the dot changes. | Unacknowledged current action fails without changing Sent or logging false success; physical device remains off. | |
| 2. Restore the supply and wait for green. | Safe configured baseline returns without command replay. | |
| 3. Switch off the supply and immediately press voltage Set. | Unacknowledged voltage action fails without changing Sent or logging false success. | |
| 4. Restore the supply and wait for green. | Safe configured baseline returns. | |
| 5. Switch off the supply and immediately press one nudge. | Nudge cannot become a false acknowledged hardware change. | |
| 6. Restore the supply and wait for green. | Baseline returns once. | |
| 7. Switch off the supply and immediately press the output toggle. | SOUT1 is not confirmed and toggle does not change ON. | |
| 8. Restore the supply and wait for green. | No SOUT1 replays during recovery. | |
| 9. Switch off the supply and immediately press `Log Power Settings`. | Failed/stale GETS3 is not reported as a valid current settings snapshot. | |
| 10. Wait until the dot is red, then inspect Set/nudge/toggle/query controls. | Hardware actions are disabled or explicitly unavailable. | |
| 11. Change Output Mode and LUT while red. | Local selection may change predictably, but no serial command or false recovery occurs. | |
| 12. Inspect STOP RAMP while no worker exists. | STOP RAMP is disabled and cannot be invoked as an idle hardware action. | |
| 13. Restore supply and repeat one Set during configuration-pending state. | Hardware commands remain gated until green. | |

### CCS-9.9 - Combined faults and out-of-order recovery

**Description:** Verify independent state tracking when 9104 and E5CN failures
overlap.

**Initial conditions:** All outputs OFF and all devices healthy.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Switch off 9104 A and remove dummy thermocouple C. | Only A power-supply state and C temperature state fault; remaining four device-channel states stay healthy. | |
| 2. Remove  the E5CN RS-485 cable while A and C remain faulted. | All temperatures become unavailable through transport semantics; A 9104 remains independently unavailable and B/C 9104s remain healthy. | |
| 3. Restore 9104 A first. | A preset/protections recover and power dot turns green without affecting temperature failures. | |
| 4. Restore RS-485 with C thermocouple still removed. | A/B temperatures recover numeric/green; C resolves to S.ERR/ERR/red, preserving the underlying sensor fault. | |
| 5. Restore C thermocouple last. | C numeric/green state returns with one valid transition; all states are coherent. | |
| 6. Review logs and physical displays. | Fault causes and recovery order remain distinguishable; no false all-clear appears between steps. | |

### CCS-9.10 - Total CCS power removal during an active ramp

**Description:** Verify simultaneous ramp interruption, 9104 reset, E5CN loss,
six-device recovery, and stale-toggle reconciliation after a full power cut.

**Initial conditions:** One representative channel is in a multi-step safe ramp;
other outputs OFF; all temperatures numeric; total CCS power control immediately
available.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Record active ramp Goal, last Sent/Measured values, front-panel output/mode, and all three temperatures. | Complete pre-fault evidence is captured within per-supply limits. | |
| 2. Remove total CCS power during a middle ramp step. | All physical outputs de-energize and all six displays go dark. | |
| 3. Observe dashboard and worker termination. | Ramp ends with failure/stop evidence, no further Sent step occurs, all Measured power/temperature data becomes unavailable, and the affected ON toggle/Goal/Sent history remains conservative. | |
| 4. Restore total CCS power. | 9104 outputs/V/I start at zero; preset 3 and safe protections are reapplied before green; E5CN channels return only after numeric reads. | |
| 5. Wait longer than two former ramp intervals. | No ramp step, final target, or SOUT1 resumes automatically. | |
| 6. Press the affected ON-looking toggle once after readiness. | SOUT0 is acknowledged at the physically OFF supply and toggle becomes OFF without energizing it. | |
| 7. Confirm 0.50 V/1.99 A limits, all outputs OFF, and logs. | Fault, worker termination, six-device recovery, no replay, and reconciliation are chronologically distinct. | |

## Suite 10 - Startup, COM-port, configuration-file, and LUT resilience

**Description:** Exercise hardware availability at launch, startup selection,
malformed/missing files, wrong port assignments, live COM changes, hot-plug
number changes, LUT validation, and pane-state recovery.

**Initial conditions:** Outputs physically OFF before every restart. Back up all
files listed in Safety Considerations and restore them after each case.

### CCS-10.1 - CCS hardware-state startup matrix

**Description:** Verify that startup remains usable and never falsely enables
controls for absent devices.

**Initial conditions:** Correct port mapping is available. Begin each numbered
hardware scenario from a separate restart with outputs confirmed OFF; a
restoration row immediately following a fault remains in that same launch.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Start with all CCS power removed but adapters connected. | Dashboard opens; all CCS data remains unavailable/red; device-silent logs are accurate; no output command occurs. | |
| 2. Restore power while dashboard remains open. | E5CN numeric data and 9104 configured readiness recover automatically on the same ports without restart or SOUT1. | |
| 3. Restart with shared 9104 USB absent. | Dashboard opens with all three 9104 channels unavailable and E5CN live; missing COMs do not crash subsystem initialization. | |
| 4. Reconnect USB with the saved COM numbers. | Constructor-created 9104 driver objects reopen the returned ports, validate GETD, and complete preset/protection confirmation without restart. | |
| 5. Restart with only 9104 B switched OFF. | A/C become ready; B remains red/unavailable; temperature monitoring remains live. | |
| 6. Restore B. | Only B performs its recovery/config sequence. | |
| 7. Restart with E5CN RS-485 cut but its adapter present. | Dashboard does not treat an open adapter as valid temperature data; all E5 dots remain red/-- while 9104s are usable. | |
| 8. Restart with the E5CN laptop adapter absent. | Temperature initialization failure is contained; 9104 controls remain usable; no false all-connected claim occurs. | |
| 9. Reinsert the same E5CN adapter without restarting. | Because no E5CN workers were retained after failed startup, current code remains unavailable until live reinitialization or restart. | |
| 10. Restore the complete baseline and restart once. | All six devices recover normally with one worker set each. | |

### CCS-10.2 - Missing, malformed, empty, and partial COM-port configuration

**Description:** Verify editable startup fallback for common
`com_ports.json` failures.

**Initial conditions:** Dashboard closed and outputs OFF. Back up
`usr/usr_data/com_ports.json`.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Remove `com_ports.json` and launch. | Config log reports no file; startup selector opens with editable blank choices rather than crashing. | |
| 2. Submit with CCS and other fields blank, choose `No` when offered dummy ports. | Selector remains open and no dashboard starts. | |
| 3. Select correct CCS ports, complete required remaining selections, and submit. | Configuration saves and dashboard starts with correct CCS mapping. | |
| 4. Close, replace file with malformed JSON, and relaunch. | Parse error is logged and selector falls back to an editable empty configuration. | |
| 5. Replace file with an empty object and relaunch. | Selector opens with blanks and supports normal completion. | |
| 6. Replace file with a partial object containing only one CCS key. | Saved key appears; missing keys remain blank and can be corrected without KeyError. | |
| 7. Restore the approved file. | Original mappings are preserved for subsequent cases. | |

### CCS-10.3 - Wrong top-level JSON types and semantically invalid values

**Description:** Require graceful recovery from syntactically valid but
structurally invalid configuration.

**Initial conditions:** Dashboard closed, outputs OFF, configuration backed up.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Set the JSON top level to `null` and launch. | Invalid structure is logged and startup falls back to an editable selector; process does not fail at length or attribute access. | |
| 2. Repeat with a JSON list. | Same graceful fallback occurs. | |
| 3. Repeat with a JSON string. | String top level is rejected without an attribute-access crash. | |
| 4. Repeat with a JSON number. | Numeric top level is rejected without a length/type crash. | |
| 5. Use an object with a null CCS port value. | Null port is rejected/blank and can be corrected; no driver receives None as a selected device endpoint. | |
| 6. Use an object with a numeric CCS port value. | Numeric pseudo-port is rejected before serial initialization. | |
| 7. Use an object with a whitespace-only CCS port value. | Whitespace-only endpoint is treated as blank and cannot become a false configured connection. | |
| 8. Restore approved JSON and launch. | Normal startup proves no persistent corruption. | |

### CCS-10.4 - Startup selector dummy, close, Return, and save-failure paths

**Description:** Exercise every startup-selector action relevant to CCS.

**Initial conditions:** Missing or empty COM configuration; outputs OFF.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Leave one or more fields blank, submit, and choose `Yes` for dummy ports. | Each blank receives a DUMMY_COM label, selection is saved where writable, and dashboard opens without treating dummy endpoints as real CCS hardware. | |
| 2. Inspect CCS with dummy assignments. | 9104/E5CN dots remain red and controls unavailable; dummy E5 failure is low-severity and no false valid read occurs. | |
| 3. Relaunch selector and press Return after making complete valid selections. | Return performs one Submit equivalent and starts one dashboard instance. | |
| 4. Relaunch and close the selector window without Submit. | No dashboard starts and bootstrap logger closes cleanly. | |
| 5. Make the config destination unwritable using the approved reversible method, then submit valid selections. | Save failure is logged explicitly; current code proceeds with the selected in-memory mapping but does not claim the mapping was persisted. | |
| 6. Relaunch before restoring write access. | Prior failed-save selections are not presented as successfully saved configuration. | |
| 7. Restore write access and approved configuration. | Later launches load normal saved selections. | |

### CCS-10.5 - Stale, duplicate, swapped, busy, and wrong-protocol COM ports

**Description:** Verify that a present/open port is not accepted as proof of the
correct CCS device or channel.

**Initial conditions:** All physical outputs OFF; record real port-to-device
mapping and back up configuration.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Assign a nonexistent stale port to Cathode A and launch. | A remains red/unavailable and logs port-open/reconnect failure; B/C may become ready normally. | |
| 2. Assign the same real 9104 port to A and B. | At most the rightful single open/valid device becomes ready; duplicate assignment does not yield two green channels or duplicate control of one output. | |
| 3. Swap A and B real ports and launch. | Physical display comparison exposes the mapping swap; dashboard must not assert correct A/B identity merely because both protocol endpoints respond. | |
| 4. Assign a dedicated unconnected spare serial adapter or DUMMY_COM label to one CCS slot. | A port label/open endpoint without the expected device remains unready; no malformed response becomes valid zero data or green state. No real CCS device receives wrong-protocol traffic. | |
| 5. Restore correct unique mapping and relaunch. | A/B/C and E5CN mapping are physically verified and all outputs remain OFF. | |

### CCS-10.6 - Runtime Configure COM Ports visibility, rescan, and Apply

**Description:** Verify that Main Control's CCS port UI either performs a real
live reconfiguration or accurately requires restart.

**Initial conditions:** Dashboard healthy on correct ports; outputs OFF.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Select `Configure COM Ports`. | Menu expands, current CCS assignments are visible, available ports are rescanned, and button changes to its Hide label. | |
| 2. Select Hide without editing. | Menu closes and no CCS connection, mapping, or hardware state changes. | |
| 3. Reopen, select the same correct ports, and press `Apply`. | Either one bounded live reconfiguration occurs or UI reports no change; no duplicate drivers, false disconnect, or output command appears. | |
| 4. Change one CCS port to a known invalid port and press Apply. | CCS must receive/reject the change with channel-specific evidence, or the UI must state restart is required; a generic success while old driver remains active fails. | |
| 5. Restore the correct port through the same UI. | Fresh read/config proof is required before green; generic dashboard mapping text alone is insufficient. | |
| 6. Restart and inspect saved startup selection. | Runtime change persistence or nonpersistence is explicit and agrees with logs; correct ports are restored before continuing. | |

### CCS-10.7 - Same-number and changed-number COM hot-plug recovery

**Description:** Verify automatic same-port recovery and the explicit restart
path for new Windows COM numbers.

**Initial conditions:** Outputs OFF; correct current ports saved.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Remove/reinsert shared 9104 USB and confirm original three COM numbers return. | Existing drivers automatically reopen and configure once; no manual Apply or restart is required. | |
| 2. Repeat with Windows assigning new 9104 COM numbers. | Old drivers remain unavailable; dashboard does not silently bind the new ports or claim recovery. | |
| 3. Attempt runtime Apply with the new mappings. | Actual live reconfiguration is proven by physical A/B/C readbacks, or an explicit restart-required result is shown. | |
| 4. If needed, restart with the new correct mappings. | One driver per supply opens the new ports and physical mapping is verified before green. | |
| 5. Repeat same-number/new-number behavior for the E5CN adapter. | Same COM recovers in existing workers; new COM requires successful live reconfiguration or restart. | |
| 6. Restore the fixture's approved port configuration. | Saved mapping and safe baseline are coherent. | |

### CCS-10.8 - Missing and structurally invalid LUT files

**Description:** Verify startup resilience and selector behavior for directory,
header, row, and parse failures.

**Initial conditions:** Outputs OFF; LUT directory backed up.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Rename/remove the LUT directory and launch. | Dashboard and electrical controls still initialize; a missing-directory warning appears; selectors/predictions are empty rather than crashing. | |
| 2. Restore an empty LUT directory and restart. | No dataset is selected; predictions remain `--`; CCS hardware control remains independent. | |
| 3. Add an empty CSV and restart. | File is marked invalid/disabled with warning and cannot produce predictions. | |
| 4. Restart with a CSV missing one required column. | File is disabled and identified by filename; no wrong column is silently substituted. | |
| 5. Restart with a CSV containing an extra column. | Exact-header validation disables the file. | |
| 6. Restart with a duplicate required column. | Ambiguous duplicate header is rejected. | |
| 7. Restart with incorrect header names. | File is rejected with the expected-column warning. | |
| 8. Test an unreadable or syntactically corrupt CSV. | Load failure is contained/logged and other valid datasets remain usable. | |
| 9. Provide one valid and one invalid file, then open the selector and choose invalid. | Invalid name is visually de-emphasized where supported; selection reverts to the prior/first valid dataset and logs the fallback. | |
| 10. Restore the production directory and restart. | Production dataset is selected and predictions operate normally. | |

### CCS-10.9 - Semantically invalid and pathological LUT data

**Description:** Reject values that pass header shape but cannot support safe,
deterministic interpolation.

**Initial conditions:** Outputs OFF; production LUT backed up; use a separate
temporary file for each row.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Test a row `0.100,,0.50` under the required headers. | Dataset is disabled at startup and cannot be selected for predictions. | |
| 2. Test `abc` in the `heater_current` column. | Dataset is rejected as nonnumeric rather than loaded until a later prediction exception. | |
| 3. Test `NaN` in the `beam_current` column. | Non-finite data is rejected; NaN never appears in UI or calculations. | |
| 4. Test `Inf` in the `voltage` column. | Infinite data is rejected and cannot enter interpolation/model math. | |
| 5. Test two rows with the same voltage but conflicting beam/heater values. | Dataset is rejected with a deterministic duplicate/conflict reason; selection does not depend on file row order. | |
| 6. Write the four `CCS_test_alt.csv` rows in reverse order and restart. | Current implementation sorts numeric axes deterministically; displayed interpolation matches the sorted rows and does not rewrite the file. | |
| 7. Test the single row `0.050,0.10,0.50` at its exact coordinate and at one different safe coordinate. | Exact-coordinate prediction may use the single row; a different coordinate is unavailable or follows the explicitly logged above-domain fallback, never a fabricated interpolation slope. | |
| 8. Restore production files and restart. | Normal prediction behavior returns and no temporary filename remains. | |

### CCS-10.10 - LUT removal or edit while dashboard is running

**Description:** Verify the load-once lifecycle and prevent mixed old/new data
claims.

**Initial conditions:** Production LUT loaded; outputs OFF; a safe Goal has a
recorded prediction.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Back up and edit the selected CSV on disk without restarting. | No immediate UI/hardware change occurs because the in-memory table remains active; dashboard does not claim it reloaded the edit. | |
| 2. Re-enter the same Goal. | Prediction remains based on the loaded snapshot for the current process. | |
| 3. Remove the selected file while dashboard remains open. | Existing in-memory selection continues consistently; selector does not imply the missing disk file was revalidated. | |
| 4. Restart with the edited/missing state. | Startup now validates current disk content and updates selector/predictions/logs accordingly. | |
| 5. Restore approved production file and restart. | Original prediction and file state return. | |

### CCS-10.11 - Pane-state file removal, corruption, and CCS visibility

**Description:** Verify that layout configuration failure cannot make CCS
unusable or crash startup.

**Initial conditions:** Outputs OFF; `pane_state.json` backed up.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Remove `pane_state.json` and launch. | Dashboard uses default layout and Cathode Heating is reachable with no restore exception. | |
| 2. Replace it with malformed JSON and relaunch. | Error/fallback is logged; default usable layout appears. | |
| 3. Use a syntactically valid state with missing Cathode Heating entry. | Missing pane data falls back without hiding or duplicating CCS. | |
| 4. Use an approved reversible state with extremely small CCS dimensions. | Dashboard remains recoverable through resize/maximize; safety/status controls can be reached and no initialization crashes. | |
| 5. Save a normal layout and restart. | Cathode pane restores to a usable size. | |
| 6. Restore original pane-state backup. | Approved layout is preserved. | |

### CCS-10.12 - Per-process defaults and nonpersistence

**Description:** Verify which CCS values intentionally reset across a normal
restart.

**Initial conditions:** Outputs OFF. Before closing, set nondefault safe Goals,
mode, slew rates, thresholds, overtemperature limit, and valid alternate LUT.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Record all changed values, then close the dashboard normally. | Shutdown sends OFF, closes devices, and preserves a complete evidence record. | |
| 2. Relaunch with correct ports and immediately restore mandatory disabled/log settings. | No output command occurs during launch. | |
| 3. Inspect Goals, Sent, predictions, toggles, modes, slews, warning thresholds, overtemperature limits, and LUT selections. | Local CCS values return to current process defaults rather than silently claiming persistence. | |
| 4. Observe initial desired OVP/OCP setup, then apply the plan's safe limits. | Startup software defaults are distinguishable from saved hardware state; 0.50 V/1.99 A is confirmed before any output. | |
| 5. Compare physical 9104 setpoints/output. | Normal shutdown left outputs OFF; relaunch does not restore prior electrical Goals or SOUT1. | |

## Suite 11 - Logging, acknowledgements, and semantic consistency

**Description:** Verify CCS evidence source, tags, units, severity, transition
cadence, command chronology, truthful wording, telemetry hygiene, and export.

**Initial conditions:** Common initial conditions apply. Knob Box OFF,
`Disable CCS logging when CCS power is off` unchecked, file recording ON at
`VERBOSE`, and session path recorded.

### CCS-11.1 - CCS logging remains enabled with Knob Box OFF

**Description:** Prove that the mandatory setting preserves orchestration and
both driver log streams while the Knob Box reports CCS power OFF.

**Initial conditions:** All CCS devices healthy and outputs OFF.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Confirm Knob Box remains OFF and log-suppression checkbox remains unchecked. | No CCS power signal is asserted, but logging policy permits CCS records. | |
| 2. Stage one safe Goal, query Log Power Settings, touch one thermocouple, and perform a confirmed ON/OFF cycle. | CCS orchestration, 9104 driver, and E5CN driver events all appear in the Messages pane and file. | |
| 3. Create and recover one brief individual 9104 power fault. | Fault and recovery evidence remains present despite Knob Box OFF. | |
| 4. Search the file for the actions and timestamps. | No queued CCS message was silently discarded because of power-off suppression. | |
| 5. Restart and inspect the setting before further action. | Suppression defaults are treated as nonpersistent; tester re-unchecks the checkbox before continuing. | |

### CCS-11.2 - Source tags, channel identity, port, values, and units

**Description:** Verify that every record can be attributed to the correct
software layer and physical channel.

**Initial conditions:** All channels healthy; outputs OFF; known safe Goals.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Perform a unique current/voltage Goal action on Cathode A. | Orchestration record uses `CCS` and names A with correct value and A/V units. | |
| 2. Enable and disable A. | 9104 records use `CCS-9104` and the Cathode A supply context/port; command/response values and output state are unambiguous. | |
| 3. Touch thermocouple B. | Temperature-driver records use `CCS-E5CN` and identify unit/cathode B with C units; no A/C attribution appears. | |
| 4. Repeat distinguishable actions on C. | C records contain its own identity/port and do not reuse A/B context. | |
| 5. Review capitalization, punctuation, and units. | Voltage, current, temperature, percent, and time units are semantically consistent and machine-searchable. | |

### CCS-11.3 - Successful command chronology and acknowledgement truth

**Description:** Verify that logs distinguish requested, staged, sent,
acknowledged, measured, and confirmed-OFF states.

**Initial conditions:** Selected channel OFF; safe Goals unset.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Stage current and voltage Goals while OFF. | Logs identify local Goal/prediction changes and do not say the physical power supply was set. | |
| 2. Enable Immediate output. | Current send/ACK precedes voltage send/ACK, then GETS3/GOVP preflight precedes SOUT1 success; later GETD is separately identifiable as measured data. | |
| 3. Change one live setpoint. | Request, acknowledgement, Sent update, and later Measured response are not collapsed into one false confirmation. | |
| 4. Press OFF with healthy communication. | SOUT0 acknowledgement precedes `Disabled output` and toggle change; no separate GOUT confirmation is claimed. | |
| 5. Repeat OFF with communication removed during the stale window. | CRITICAL uncertain-state record replaces success; no OFF confirmation appears. | |
| 6. Restore and issue confirmed OFF. | Later real acknowledgement is distinct from the failed attempt. | |

### CCS-11.4 - Connection, loss, repeat cadence, and recovery transitions

**Description:** Verify first-valid evidence, rate-limited persistent errors, and
one recovery log per genuine transition.

**Initial conditions:** All connections healthy long enough to establish valid
state.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Count valid-connection INFO records for all three 9104s and E5CN channels. | One record per channel appears after its first valid read; routine polling does not repeat it. | |
| 2. Switch off one 9104 for at least 22 s. | First operator-level error appears promptly; repeated equivalent errors are limited to about 10 s cadence, with lower-level VERBOSE detail rather than UI flood. | |
| 3. Restore it and wait for configured readiness. | Exactly one new valid-connection transition appears after fresh read/config evidence. | |
| 4. Cut E5CN RS-485 for at least 22 s. | Per-unit failures use bounded operator cadence and accurate no-data/transport semantics. | |
| 5. Restore the cable. | One fresh valid-temperature transition appears per channel; normal polls do not repeat it. | |
| 6. Review the full file at VERBOSE. | Diagnostic repeats remain available without being confused with new operator-level transitions. | |

### CCS-11.5 - Semantic-message defect audit

**Description:** Intentionally reach known wording-sensitive branches and
require messages to describe the actual quantity and action.

**Initial conditions:** Selected channel ready and OFF; safe Goals available.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Stage a current Goal while OFF. | Message says current Goal/staged request, not that the power supply was physically set. | |
| 2. Stage a voltage Goal while OFF. | Message says voltage Goal/staged request, not a sent/acknowledged hardware setting. | |
| 3. Select Ramp Current, Ramp Voltage, and Immediate Set. | Each message says output mode and identifies current, voltage, or immediate correctly; it does not label every choice `voltage mode`. | |
| 4. Make OVP unavailable and attempt voltage validation. | Error names OVP and the GOVP/voltage-validation failure; it does not say OCP or GOCP. | |
| 5. Cause a current-update failure during a controlled fault. | Error says manual current processing, not manual voltage processing. | |
| 6. Query Log Power Settings with a current-only mismatch. | Log reports the current mismatch and includes correctly punctuated voltage/current values. | |
| 7. Inspect severity for every rejected local input. | Validation warnings/errors are proportional and do not claim CRITICAL hardware danger unless output state is actually uncertain. | |

### CCS-11.6 - E5CN connection-claim accuracy

**Description:** Prevent adapter-open state from being logged as proof that all
temperature controllers responded.

**Initial conditions:** Dashboard closed; E5CN adapter connected but RS-485
network cable removed; outputs OFF.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Launch with the correct TempControllers COM port. | Local port may open and read workers may start, but log does not claim `Connected to all temperature controllers` before valid unit 1, 2, and 3 data. | |
| 2. Wait through failed reads. | Dots remain red/values unavailable and logs identify unproven/silent units. | |
| 3. Restore RS-485. | Each unit's first numeric reading establishes its own green/valid transition. | |
| 4. Inspect final connection summary, if any. | An all-connected statement appears only after all three current numeric reads exist. | |

### CCS-11.7 - Persistent overtemperature log cadence

**Description:** Verify that one continuous thermal breach remains actionable
without flooding the log every 500 ms.

**Initial conditions:** Selected thermocouple and reachable safe overtemperature
limit configured; outputs OFF.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Raise temperature above the limit and hold for 5 s. | One breach transition is logged at CRITICAL and UI remains orange/OVERTEMP. | |
| 2. Continue holding for another 5 s. | No additional CRITICAL transition is emitted for the same continuous breach; UI remains OVERTEMP/orange. | |
| 3. Allow temperature below the limit. | One recovery transition is recorded and highlight clears. | |
| 4. Raise it above again after full recovery. | A new breach produces one new CRITICAL transition every 10s. | |
| 5. Restore 150 C. | Baseline returns Normal. | |

### CCS-11.8 - Invalid-data telemetry hygiene

**Description:** Verify that disconnected, malformed, and sensor-error data
cannot be recorded as plausible physical zero or stale fresh data.

**Initial conditions:** All channels healthy; record current telemetry values.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Switch off one 9104. | Its published heater voltage/current become unavailable/None and UI `--`; no fabricated numeric zero is timestamped as fresh. | |
| 2. Restore it and observe zero-default hardware before configuration completes. | A real numeric zero is accepted only from a valid parsed GETD and remains distinguishable from unavailable state. | |
| 3. Remove one thermocouple. | Clamp-temperature telemetry becomes unavailable/error, not 0 C or last numeric value; UI shows ERR. | |
| 4. Cut RS-485 after restoring the sensor. | Stale cached temperature is eventually cleared to unavailable and not indefinitely republished as current. | |
| 5. Restore all devices. | Fresh numeric telemetry resumes under the correct cathode labels. | |

### CCS-11.9 - Log export and evidence preservation

**Description:** Verify that the operator can preserve CCS evidence from a
mixed success/failure/recovery session.

**Initial conditions:** Generate one accepted Goal, one rejected input, one
confirmed ON/OFF, one 9104 fault/recovery, and one E5CN fault/recovery.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Use the dashboard log export action or `Ctrl+S`. | A save/export action completes without changing CCS state. | |
| 2. Open the exported file using the approved viewer. | All generated events, timestamps, levels, and `CCS`/`CCS-9104`/`CCS-E5CN` tags are present in chronological order. | |
| 3. Compare exported data with the live Messages pane and active file log. | Export does not silently omit errors/recoveries or transform severities. | |
| 4. Cancel a second export. | Cancellation creates no empty misleading evidence file and does not affect recording. | |
| 5. Attempt export to an unwritable destination using an approved reversible setup. | Failure is reported to the operator; ongoing file logging continues and CCS state is unchanged. | |

## Suite 12 - Shutdown, restart, races, and interaction stress

**Description:** Verify bounded lifecycle cleanup, safe normal quit, explicit
abnormal-termination risk, no stale command replay, and UI/thread integrity
under rapid or concurrent actions.

**Initial conditions:** Common initial conditions apply. Use the dummy load and
safe values for every energized branch. Have immediate physical CCS power
removal available.

### CCS-12.1 - Rapid valid/invalid Set, nudge, mode, and LUT actions

**Description:** Look for duplicate callbacks, stale validation, cross-channel
state, and UI exceptions under operator stress.

**Initial conditions:** All outputs OFF and channels ready with safe limits.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Alternate valid and invalid current Set actions ten times on one channel. | Each action produces one acceptance or rejection; no duplicate dialog, lost prior valid Goal, or hardware send occurs while OFF. | |
| 2. Rapidly press current and voltage nudges near but below their limits. | Goals never cross OVP/OCP or fixture limits; increments remain exact and no click affects another channel. | |
| 3. Rapidly switch among the three Output Modes while idle. | Final selector/state agree, control gating matches the final mode, and no ramp/output command starts. | |
| 4. Rapidly alternate two valid LUT selections where temporary safe LUTs are installed. | Final prediction uses the final selection; no power command or stale callback overwrites it later. | |
| 5. Switch Main/Config tabs, scroll, resize, and invoke local Config setters during polling. | UI remains responsive with no Tk traceback, duplicate widget, or corrupted cathode association. | |

### CCS-12.2 - Exploratory rapid toggle and command ordering

**Description:** Verify serialization and safe physical state under repeated
output requests. Treat exact callback interleaving as exploratory and stop
immediately if physical and dashboard state diverge.

**Initial conditions:** Selected channel OFF with safe Immediate Goals.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Click the OFF toggle twice rapidly while continuously observing the front panel. | Any queued ON then OFF/ON sequence is visible in command order; final dashboard and physical state must agree. If final state is ON, issue one confirmed OFF before continuing. | |
| 2. While ON, alternate current and voltage Set actions quickly but within limits. | Serial responses map to the correct command; final Goal/Sent/Measured and front-panel values converge to the final accepted requests. | |
| 3. Press OFF while another Set command is in progress. | OFF is not lost behind a stale later command; after SOUT0 acknowledgement no delayed set or SOUT1 re-energizes output. | |
| 4. Wait at least three poll intervals. | Final physical output remains OFF and logs preserve real command order. | |

### CCS-12.3 - Simultaneous independent channel ramps

**Description:** Verify per-supply worker and UI independence when A, B, and C
ramp concurrently.

**Initial conditions:** All three channels OFF with safe multi-step Goals and
planned slew rates.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Start Ramp Current on A, Ramp Voltage on B, and a different safe ramp on C in quick succession. | Each supply starts one independent ramp thread; channel-specific controls gate correctly and UI remains responsive. | |
| 2. Observe Sent/Measured/front-panel steps for all three. | Values and logs remain on the correct channel; each individual 9104 stays at or below 0.50 V and below 2.00 A. | |
| 3. STOP A only. | A stepping stops and its output remains ON; B/C continue uninterrupted. | |
| 4. Toggle B OFF during its ramp. | B stops and acknowledges OFF; A/C states are unchanged. | |
| 5. Allow C to complete. | C alone logs verified completion and stays ON. | |
| 6. Issue confirmed OFF on all three. | All physical outputs and toggles are OFF with no surviving ramp thread. | |

### CCS-12.4 - Exploratory command-versus-fault and recovery-versus-command races

**Description:** Exercise physical failures at command boundaries and reject
stale queued work after recovery. Attempt each sub-second boundary no more than
three times and record an unattained boundary as blocked/exploratory.

**Initial conditions:** Selected channel safe and ready; repeat each branch from
a confirmed OFF baseline.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Remove individual supply power as a live Set is submitted. | Command either acknowledges before loss and appears in Sent history or fails; it is never ambiguously logged as both, and physical reset returns zero. | |
| 2. Remove shared USB as SOUT1 is submitted. | Confirmed ON requires acknowledgement; lost acknowledgement creates uncertain evidence and no automatic retry/replay after reconnect. | |
| 3. Restore same COM and press Set while preset/limit configuration is pending. | Operator command stays gated behind initialization. | |
| 4. Press output ON at the instant the dot becomes green. | Exactly one fresh sequence uses current Goals and safe confirmed limits; no old command queue executes first. | |
| 5. Cut E5CN RS-485 while changing a 9104 setpoint. | Power command remains independent and bounded; temperature failure is logged separately. | |
| 6. Restore everything and issue confirmed OFF. | Coherent safe baseline returns with no duplicate worker. | |

### CCS-12.5 - Quit cancellation and normal idle shutdown

**Description:** Verify the application quit prompt and complete cleanup while
all outputs are OFF.

**Initial conditions:** All channels healthy and outputs OFF; no ramp active.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Request quit and cancel. | Dashboard remains running; polling, temperatures, controls, and file logging continue exactly once. | |
| 2. Request quit again and confirm. | Update callback cancels, 9104 poller stops, SOUT0 is attempted on every available supply, serial ports close, E5CN readers stop, and window exits within bounded time. | |
| 3. Inspect all physical 9104s. | Every output is OFF; no setpoint changes after exit. | |
| 4. Relaunch immediately with the same ports. | Ports open successfully and exactly one poller plus one E5CN reader per unit runs; no old process/lock retains a port. | |
| 5. Restore mandatory settings and safe limits. | Baseline is ready without automatic output enable. | |

### CCS-12.6 - Normal quit with outputs ON

**Description:** Verify that confirmed application shutdown attempts unconditional
OFF on all supplies, independent of toggle/Goal completeness.

**Initial conditions:** Safely enable one, then two, then all three outputs at
approved pairs; no ramp active.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Confirm each physical output and dashboard toggle ON within limits. | Pre-shutdown state is fully recorded. | |
| 2. Request quit and confirm. | Shutdown sends SOUT0 to each supply before closing its port; UI exits without indefinite lock wait. | |
| 3. Observe all three 9104 front panels during shutdown. | Every physical output turns OFF and stays OFF. | |
| 4. Relaunch and inspect startup state. | Toggles/Goals reset to process defaults and physical outputs remain OFF; no prior SOUT1 replays. | |

### CCS-12.7 - Quit during an active ramp

**Description:** Verify bounded ramp stop, unconditional OFF, and port cleanup.

**Initial conditions:** At least one multi-step safe ramp active; another
channel may be idle or ramping independently.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Confirm quit during a middle ramp step. | Shutdown cancels GUI updates, stops the poller, signals every ramp, attempts SOUT0, and closes ports without waiting indefinitely. | |
| 2. Observe each involved 9104. | No later step occurs after shutdown; every reachable output turns OFF. | |
| 3. Inspect the completed log. | Ramp-stop/close ordering is visible; any bounded join/lock timeout is warned and any failed OFF is CRITICAL. | |
| 4. Relaunch immediately. | One clean worker set starts and no old ramp step or Goal reappears. | |

### CCS-12.8 - Quit while 9104 communication is unavailable

**Description:** Verify bounded exit and explicit physical hazard when SOUT0
cannot reach an energized supply.

**Initial conditions:** One supply safely ON; remove shared 9104 USB so its
physical output remains energized and all three COM ports disappear.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Confirm physical output remains ON and dashboard communication is unavailable. | Hazard state is recorded; E5CN may remain live. | |
| 2. Confirm application quit. | Shutdown finishes within bounded time despite absent ports; failed output-disable attempt is not reported as success and is CRITICAL in the retained log where possible. | |
| 3. Immediately remove total CCS power. | Physical output de-energizes and 9104 resets to zero; fixture is safe before reconnection. | |
| 4. Restore USB, then CCS power, and relaunch. | Same ports open cleanly; 9104 preset/protections are reconfigured; physical output remains OFF and no Goal replays. | |

### CCS-12.9 - Quit during E5CN failure or reconnect

**Description:** Verify bounded temperature-thread cleanup and immediate COM
reuse.

**Initial conditions:** Outputs OFF. Remove E5CN RS-485 or laptop adapter and
allow reader retries to begin.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Confirm quit while E5CN threads are retrying. | Stop signal, bounded joins, and best-effort client close complete without dashboard hang. | |
| 2. Restore the physical connection and relaunch immediately. | TempControllers port can be opened; one reader per unit starts and all numeric values recover. | |
| 3. Repeat while adapter is reinserted during shutdown. | No duplicate reader, stale client, port-in-use error, or cross-process log appears. | |

### CCS-12.10 - Abnormal process termination with output active

**Description:** Expose the highest-risk difference between physical 9104 state
and a new dashboard's default toggle when cleanup never runs.

**Initial conditions:** One 9104 safely ON at a low approved pair; USB remains
connected; tester is ready to remove CCS power immediately.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Record physical output, setpoints, protections, dashboard toggle, Goals, Sent, and Measured. | Pre-termination state is complete and within limits. | |
| 2. Terminate the dashboard process abnormally using the approved test method so normal cleanup cannot run. | No SOUT0 is sent; physical 9104 remains powered and may remain ON at its last settings. | |
| 3. Relaunch without power-cycling the 9104 and restore mandatory settings immediately. | New dashboard initializes its local toggle OFF and does not query GOUT; physical output can still be ON, exposing a dashboard/front-panel contradiction. | |
| 4. Observe initialization without pressing output controls. | Preset/OVP/OCP may be reasserted, but no SOUT1/SOUT0 or old Goal restoration occurs; Measured data reveals nonzero physical output. | |
| 5. Treat the contradiction as unsafe and remove total CCS power. | Physical output turns OFF and hardware resets to zeros. | |
| 6. Restore power and wait for safe configuration. | Physical output remains OFF; dashboard reaches green only after preset/protection confirmation. | |
| 7. Inspect logs available before and after the crash. | Abrupt session boundary and new startup are evident; no record falsely claims normal shutdown or confirmed OFF. | |

### CCS-12.11 - Repeated restart and worker-leak stress

**Description:** Verify stable lifecycle behavior across repeated normal and
faulted launches.

**Initial conditions:** All outputs OFF and physical configuration healthy.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Perform five normal launch/quit cycles, restoring mandatory settings each launch. | Every cycle creates and closes one 9104 poller and one E5CN reader per unit; no port-in-use, delayed old log, or increasing duplicate poll cadence appears. | |
| 2. On one cycle, start with a 9104 off and restore it after launch. | Recovery occurs once and shutdown remains clean. | |
| 3. On another cycle, start with E5CN RS-485 cut and restore it. | Reader recovery occurs once without leaked threads. | |
| 4. Compare responsiveness and log volume from first and final cycles. | No progressive slowdown, duplicate polling, duplicated valid-connection logs, or queue-overflow warning occurs under normal volume. | |
| 5. Verify every physical output OFF after the final quit. | Fixture is safe and no process remains connected. | |

### CCS-12.12 - Final restoration and evidence review

**Description:** Return the fixture and repository to their approved state and
confirm that all failures are traceable.

**Initial conditions:** All planned cases complete or dispositioned.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Issue confirmed OFF to every reachable 9104, then remove total CCS power. | All dummy loads de-energize and all six device displays go dark. | |
| 2. Verify continuity/lead routing has not changed and reinstall every thermocouple/cable. | CCS dummy load setup matches the approved starting configuration. | |
| 3. Restore backed-up `com_ports.json`, `pane_state.json`, and production LUT directory. | Repository/user configuration matches its approved pretest content; no temporary CSV remains. | |
| 4. Restore power, launch once with approved ports, disable mandatory settings/log suppression, and set OVP/OCP to safe values. | All six device channels become valid with correct mapping and every output remains OFF. | |
| 5. Export and archive the final log with test notes and timestamps. | Every failure, recovery, blocked branch, and unexpected behavior has traceable evidence. | |
| 6. Quit normally and verify physical OFF. | No active worker or energized output remains. | |

## Completion Criteria

The solo Cathode Heating plan is complete when:

- Every test case has a result and Notes contain either pass evidence or a
  defect/blocked-reference identifier.
- Every listed physical action has been exercised: total CCS power removal,
  shared 9104 USB removal at both ends, individual 9104 power switches, dummy
  thermocouple touch/removal, E5CN RS-485 removal, and E5CN laptop-adapter
  removal.
- Every attainable Cathode Heating UI control has been exercised in valid,
  invalid, unavailable, and relevant energized/ramping states.
- A/B/C mapping is proven against both 9104 and E5CN front panels.
- Immediate, Ramp Current, Ramp Voltage, STOP, confirmed OFF, failed OFF,
  recovery without stale replay, and safely attainable CV/CC-limited final
  verification have operator-visible evidence; an unsafe/unattainable mode
  branch has a documented blocked disposition instead.
- Missing/malformed configuration and LUT files, wrong/stale/changed COM ports,
  startup hardware states, normal quit, and abnormal termination are
  dispositioned.
- Logs distinguish request, Goal, Sent, acknowledgement, Measured, connection,
  fault, recovery, and uncertain output state with correct channel and units.
- No commanded or measured heater output exceeds 0.50 V or reaches 2.00 A;
  no case activates beams, tests an excluded guard, or evaluates
  cross-subsystem reactions.
- Approved configuration/data files are restored, every thermocouple and cable
  is reinstalled, all 9104 outputs are physically OFF, and the final dashboard
  state agrees with the device displays.
