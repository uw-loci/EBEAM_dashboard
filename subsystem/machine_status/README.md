# Machine Status Subsystem

## Overview

Machine Status is a series of non blocking indicators meant to inform and direct the user through the Dashboard checks of the Melt Metal Experiemnt. 

Machine Status does not control hardware directly. It reads live state from the
other dashboard subsystems, evaluates each stage, and turns the status segments
gray, green, or red.

## UI Structure

The bar is drawn as ten arrow-shaped segments:

1. PMON Temperatures OK
2. Pressure Below 1e-4 mbar
3. All Safety Interlocks Pass
4. High Voltage Subpanel On
5. Pressure Below 1e-6 mbar
6. HV Power Supplies Nominal
7. Beam Controller Nominal
8. Cathode Heating
9. Beams Ready
10. Beams On

The order matters. Earlier stages are prerequisites for later stages. A later
green stage can cause earlier incomplete stages to turn red so the operator can
see that the machine has advanced past a missing prerequisite.

## Display State Rules

Each stage has two internal evaluation results:

- A warning condition, used when that stage has detected a known unsafe or
  inconsistent state.
- A ready condition, used when that stage's normal requirement is satisfied.

The final displayed color is calculated in this order:

| Priority | Display | Meaning |
| --- | --- | --- |
| 1 | Red | The stage has a warning condition. This overrides all other results. |
| 2 | Green | The stage is ready and has no warning condition. |
| 3 | Red | The stage is not ready, but a later stage is green. This means the machine is operating beyond an unmet prerequisite. |
| 4 | Gray | The stage is not ready yet, and no later stage has turned green. |

This is the "forced red, green, behind red, gray" flow:

- Forced red: direct warning at that stage.
- Green: that stage's requirement is satisfied.
- Behind red: an earlier stage is incomplete while a later stage is already
  ready or active.
- Gray: not ready yet, but still in the expected startup path.

## How Machine Status Gets Information

Dashboard creates `MachineStatus` after the dashboard frames are available and
passes it two read-only providers:

- A subsystem provider, which returns the dashboard's subsystem dictionary.
- A Main Control provider, which returns the current Main Control panel.

Machine Status runs a background worker roughly every 0.2 seconds. On each pass
it takes a shallow snapshot of the subsystem dictionary, asks the relevant
subsystems for read-only status inputs, evaluates the ten stages, and queues the
UI update back onto the Tk thread with `after()`.

The Machine Status bar reads from:

- Process Monitor: PMON communication and valid temperature telemetry.
- VTRX / Vacuum System: latest valid pressure and whether that pressure reading
  is fresh.
- Interlocks: boolean state of the displayed safety interlocks, including
  "All Interlocks", "HVolt ON", and "G9SP Output".
- Beam Energy: Knob Box connection state, power-supply telemetry, warning
  limits, interlock flags, nominal-operation status, logic communication, and
  hardware arm state.
- Beam Pulse: BCON connection, beam software armed state, active beam output,
  channel enable state, and whether enabled beams are inside the configured
  emission-current limit.
- Cathode Heating: cathode output states, latest clamp temperatures,
  overtemperature limits, and predicted emission currents.
- Main Control: the configured total predicted emission-current limit.

If a subsystem is missing, disconnected, stale, or cannot provide the requested
read-only inputs, Machine Status treats that data as not ready. Evaluation
errors are logged under the "Machine Status" tag and the bar falls back to gray
states until evaluation recovers.

## Stage Reference

### 1. PMON Temperatures OK

Turns green when:

- Process Monitor has at least one required, non-spare temperature channel
  reporting a valid in-range value.

Stays gray or becomes behind-red when:

- Process Monitor is disconnected.
- No required PMON channel has valid data.
- Temperature readings are disconnected, invalid, or outside the accepted
  telemetry range.

### 2. Pressure Below 1e-4 mbar

Turns green when all of the following are true:

- VTRX has a fresh pressure reading.
- The latest valid pressure is strictly below `1e-4 mbar`.

Stays gray or becomes behind-red when:

- Pressure is `1e-4 mbar` or higher.
- The pressure reading is stale.
- No valid VTRX pressure has been received.

### 3. All Safety Interlocks Pass

Turns green when all of the following are true:

- The Interlocks subsystem reports "All Interlocks" as passing.

Stays gray or becomes behind-red when:

- Any safety interlock in the combined all-interlocks check is not passing.
- The G9 interlock controller is disconnected or not reporting usable state.

### 4. High Voltage Subpanel On

Forced red when:

- The G9SP output is on, but the "HVolt ON" interlock is not on.

Turns green when:

- The "HVolt ON" interlock is on.

Stays gray or becomes behind-red when:

- The high-voltage subpanel is not on and the G9SP output is not demanding it.

### 5. Pressure Below 1e-6 mbar

Turns green when all of the following are true:

- VTRX has a fresh pressure reading.
- The latest valid pressure is strictly below `1e-6 mbar`.

Stays gray or becomes behind-red when:

- Pressure is `1e-6 mbar` or higher.
- The pressure reading is stale.
- No valid VTRX pressure has been received.

### 6. HV Power Supplies Nominal

Forced red when any monitored beam-energy supply has a warning-limit fault:

- Measured voltage below the configured minimum.
- Measured voltage at or above the configured maximum.
- Measured current at or above the configured maximum.

Turns green when all of the following are true:

- Beam Energy reports nominal operation from the Knob Box.
- The monitored supply units are communicating.
- Knob Box logic arduino communication is alive.

Stays gray or becomes behind-red when:

- Knob Box data is unavailable.
- One or more monitored supply units are not communicating.
- Beam Energy logic communication is not alive.
- Nominal operation is not reported.

### 7. Beam Controller Nominal

Turns green when all of the following are true:

- Beam Pulse reports BCON connected.
- The `+1 kV` and `-1 kV` Matsusadas are within warning limits.
- The `+1 kV` and `-1 kV` Knob Box interlock flags are clear.
- The Matsusada Monitoring Arduinos are communicating.

Stays gray or becomes behind-red when:

- BCON is disconnected.
- Either `+1 kV` or `-1 kV` has missing data.
- Either `+1 kV` or `-1 kV` is outside its warning limits.
- Either `+1 kV` or `-1 kV` has an interlock flag active.
- Matsusada Monitoring Arduino communication is unavailable.

### 8. Cathode Heating

Forced red when if any of the following are true:

- Any cathode clamp temperature is above its overtemperature limit.
- Any single cathode predicted emission current is at or above the Main Control
  total predicted emission-current limit.

Turns green when:

- At least one of the first three cathode heating outputs is on.

Stays gray or becomes behind-red when:

- No cathode heating output is on.

### 9. Beams Ready

Forced red when:

- The sum of enabled channels' predicted emission currents is at or above the
  configured emission-current limit if enabled.

Turns green when:

- Every earlier stage from PMON Temperatures OK through Cathode Heating is ready
  and not forced red.
- The Beams Armed button in Main Control is active.
- Knob Box reports the hardware arm-beams state is active.

Stays gray or becomes behind-red when:

- Any earlier prerequisite is not ready.
- Beams are not software-armed in Beam Pulse.
- The Beam Energy hardware arm-beams state is not active.

### 10. Beams On

Turns green when:

- Beam Pulse reports at least one active BCON output channel.

Stays gray when:

- No BCON beam output channel is active.

## Logging And Shutdown Behavior

Machine Status logs color transitions under the "Machine Status" tag:

- Green and gray transitions are logged as informational status changes.
- Red transitions are logged as warnings.
- Evaluation failures are logged as errors and recovery is logged when normal
  evaluation resumes.

During dashboard shutdown, Dashboard cancels Machine Status first because the
Machine Status worker reads subsystem state. Pending Tk callbacks are cancelled,
the worker is asked to stop, and a warning is logged if it does not stop within
the short shutdown timeout.

## Important Behavior Notes

- The bar is advisory and dashboard-facing. Hardware interlocks and protection
  are still enforced by the hardware subsystems and controllers.
- Pressure thresholds are strict comparisons. A pressure exactly equal to the
  threshold is not considered below that threshold.
- Stale pressure is treated as not ready for both pressure stages.
- Missing subsystem inputs are treated as not ready.
- Forced red always overrides green, even if the stage's ready condition is also
  true.
- Beams Ready depends on all earlier stages being ready; it is intentionally a
  summary of the full pre-beam path, not only the Beam Pulse arm button.
