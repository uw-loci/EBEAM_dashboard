# Inter-Subsystem Integration Test Plan

## Purpose

Verify coordinated behavior for Main Control, Beam Pulse (BCON), Cathode Heating
(CCS), Vacuum (VTRX), Process Monitor (PMON), Interlocks (SIC), Machine Status,
and Laser Monitor using only the controls approved for this truncated plan.

The only permitted VTRX actions are: connect VTRX at its fixed live reading of
`1200 mbar`; disconnect VTRX to create stale data; and change local threshold
constants before launching the dashboard. Do not alter a VTRX packet, sensor
value, state bit, error code, valve, or vacuum hardware.

Use these pre-launch profiles while VTRX reports fixed fresh `1200 mbar`:

| Profile | Main Control beam and CCS limits | Machine Status pressure limits | Intended result |
|---|---|---|---|
| `SAFE_1200` | `1200.1 mbar` | `1200.1 mbar` | Main Control and pressure stages treat 1200 mbar as safe/below. |
| `EQUAL_1200` | `1200 mbar` | `1200 mbar` | Main Control treats equality as safe; strict-below pressure stages are not ready. |
| `UNSAFE_1200` | `1199.9 mbar` | `1199.9 mbar` | Main Control treats 1200 mbar as high; pressure stages are not ready. |

Change only these constants while the dashboard is closed, and restore them
after the profile launch:

- `VTRX_BEAM_DISABLE_PRESSURE_LIMIT_MBAR` and
  `VTRX_CCS_DISABLE_PRESSURE_LIMIT_MBAR` in
  `subsystem/main_control/main_control.py`.
- `PRESSURE_1E_4_MBAR` and `PRESSURE_1E_6_MBAR` in
  `subsystem/machine_status/machine_status.py`.

The following behavior is authoritative:

- Main Control VTRX guards use `pressure > limit`; equality is safe.
- Machine Status pressure stages use `pressure < threshold`; equality is not
  ready.
- Stale VTRX pressure blocks new guarded output, immediately stops active BCON
  output when its Beam guard is enabled, and starts the configured CCS grace
  timer when its CCS guard is enabled.
- `E-STOP: BEAMS & CCS` commands BCON and CCS only. It does not command a
  high-voltage supply off.
- The physical Knob Box Arm Beams switch is the sole permitted Knob Box action.
  It is exercised through the required Logic Arduino Override and must never
  assert a high-voltage enable.
- Laser Monitor exchanges a complete `STATE beams=<0|1> radiation=<0|1>` line
  every 500 ms. This plan tests only the live-BCON-driven `beams` state.

A pass requires physical fixture evidence, fresh dashboard state, Main Control
action line, subsystem event line, Machine Status, Laser Monitor evidence, and
durable log to agree. A queued command is not a confirmed hardware result.

## Safety Considerations

- **Disconnect every pulser cable from BCON A, B, and C for the entire plan.**
  Use only BCON LCD/register state and blue LEDs to observe gate output.
- **Use CCS dummy loads only.** Verify wiring, fusing, polarity, OVP/OCP, and
  immediate physical CCS power removal before enabling a 9104 output.
- **No high-voltage supply may be energized.** Do not operate any Knob Box
  high-voltage enable, CCS Power, telemetry, comparator, reset, or COM control.
  Do not change Beam Energy limits or the +20 kV E-stop setting.
- Install the Knob Box Logic Arduino Override specified in
  `bcon_subsystem_test.md` before using physical Arm Beams. Confirm that it
  supplies only the active-high BCON interlock signal.
- Use PMON dummy sensors only where permitted by `pmon_subsystem_test.md`. Use
  the approved SIC fixture, E-stops, door fixture, HVolt-monitor fixture, and
  physical reset procedure. Keep G9SP output isolated from energized HV.
- Install approved Laser Monitor firmware from the sibling firmware workspace.
  Serial protocol fixtures and Laser USB faults are permitted. Do not
  intentionally test or alter the radiation indicator.
- Restore default source constants (`1e-5`, `1e-4`, and `1e-6 mbar`), files,
  protections, connections, and physical outputs after every profile/fault.
- If physical CCS state disagrees with its dashboard toggle, a BCON LED remains
  high after all-off, or output is uncertain, stop the test case, remove appropriate
  physical power, verify zero output, and record the mismatch.

## Outline

1. Integrated baseline, permitted scope, and mapping
2. Main Control settings, E-stop, and BCON-to-CCS coordination
3. VTRX fixed-pressure profiles and stale-data handling
4. Cathode Heating, emission guard, and BCON coordination
5. Beam Pulse manual controls and Arm Beams interlock
6. PMON actions and Machine Status source behavior
7. SIC physical inputs and Machine Status source behavior
8. Complete Machine Status evaluation
9. Laser Monitor firmware, serial transport, and beams-on integration
10. Startup, configuration, logging, and general dashboard behavior
11. Shutdown, abnormal recovery, and restoration

Unless stated otherwise,
start with `SAFE_1200`;
connected fresh VTRX at fixed 1200 mbar;
BCON connected at confirmed 1500 ms watchdog;
Knob Box Logic Arduino Override installed;
physical Arm Beams ON;
BCON disarmed with channels disabled/OFF;
BCON LEDs dark; CCS outputs OFF;
PMON/SIC healthy; Laser Monitor connected;
and high-voltage equipment de-energized.
Keep Knob Box controls/telemetry untouched.
Use verbose file logging with recording ON.

## Suite 1 - Integrated baseline, permitted scope, and mapping

**Description:** Establish the safe fixed-pressure fixture and prove permitted
physical paths and excluded controls are understood.

**Initial conditions:** Dashboard closed. Backups of source constants,
configuration files, and CCS/Laser Monitor fixtures are available.

### INTER-1.1 - Fixture isolation and fixed-pressure startup

**Description:** Confirm the truncated fixture is safe before any dashboard
output-producing command is used.

**Initial conditions:** Apply `SAFE_1200` while dashboard is closed. BCON, CCS,
PMON, SIC, VTRX, and Laser Monitor fixture power is initially removed.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Trace BCON A/B/C and verify no pulser cable is attached. | Every BCON output is visibly unterminated; no pulser can receive a gate. | |
| 2. Verify high-voltage sources are de-energized and isolated. | No high voltage can energize during this plan. | |
| 3. With CCS power removed, verify dummy-load wiring, protections, and emergency physical power removal. | The approved dummy-load fixture is ready and outputs are zero. | |
| 4. Install the Logic Arduino Override and turn physical Arm Beams ON. | BCON receives the active-high interlock signal only; no high-voltage enable is asserted. | |
| 5. Restore allowed fixture power, connect VTRX at fixed 1200 mbar, and start Laser Monitor firmware. | BCON LEDs and CCS outputs remain OFF; Laser Monitor beams-on is OFF. | |
| 6. Start dashboard with approved COM mappings and wait for fresh snapshots. | Connected subsystems identify current data without startup traceback, duplicate worker, output command, or Knob Box manipulation. | |
| 7. Set verbose file logging and recording ON. | Durable evidence is available for every in-scope subsystem. | |

### INTER-1.2 - Allowed and excluded operator-surface inventory

**Description:** Verify retained panels are visible while prohibited actions are
explicitly omitted.

**Initial conditions:** INTER-1.1 passed; all outputs OFF and BCON disarmed.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Inspect Main Control Main and Config tabs. | Allowed BCON/CCS/VTRX/emission controls and status lines are visible; do not alter +20 kV E-stop control. | |
| 2. Inspect Beam Pulse connection and Manual Control tabs. | Connect/Disconnect, watchdog, manual A/B/C modes, ARM, channel controls, Activate, Disable All, and E-stop are visible. No CSV control is selected. | |
| 3. Inspect Cathode Heating, Vacuum, Process Monitor, Interlocks, Machine Status, and Messages. | Retained controls/displays are visible, mapped, and readable without a command. | |
| 4. Observe Beam Energy only as a passive Machine Status source. | Existing telemetry may be observed, but no Knob Box switch, simulation, COM, limit, reset, or output control is changed. | |
| 5. Switch tabs, resize panes, maximize/restore, and return to baseline. | Controls remain correctly associated; no command, duplicated callback, or Tk error occurs. | |


### INTER-1.3 - Cross-device channel and source mapping

**Description:** Prove A/B/C and permitted source relationships cannot be
silently cross-routed.

**Initial conditions:** Outputs OFF. PMON/SIC fixtures and fixed VTRX are
healthy.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Stage distinct safe CCS Goal pairs for A, B, and C without output. | Each Goal and predicted-current provider changes only its matching cathode. | |
| 2. Software-arm BCON, enable CH A/B/C one at a time, then disable all/disarm. | Main Control, Beam Pulse, BCON LCD/register state, and logs map A/B/C consistently; LEDs remain dark. | |
| 3. Change one permitted PMON input and one SIC input in separate iterations. | Only matching PMON/SIC indicator and dependent Machine Status stage changes. | |
| 4. Disconnect/reconnect VTRX without changing fixed 1200 mbar. | Vacuum freshness and dependent guards/status change source state without cross-routing another subsystem. | |


## Suite 2 - Main Control settings, E-stop, and BCON-to-CCS coordination

**Description:** Exercise retained Main Control settings and shutdown paths
without touching Knob Box-dependent controls.

**Initial conditions:** `SAFE_1200`; BCON/CCS connected; outputs OFF; emission
limit set to a known safe value.

### INTER-2.1 - Retained shutoff-setting controls and persistence

**Description:** Verify the four allowed settings are independent, validated,
and truthfully persisted.

**Initial conditions:** Back up `usr/usr_data/main_control_config.json`.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Inspect BCON-disconnect, VTRX Beam, VTRX CCS, and emission settings. | Labels identify target/enabled state; no +20 kV setting is changed. | |
| 2. Toggle each allowed checkbox OFF then ON independently. | Only its associated guard changes; other guards/values remain unchanged. | |
| 3. Set valid emission limits and CCS grace durations, then attempt blank, nonfinite, negative, and out-of-range values. | Valid values take effect; invalid values are rejected without replacing an active safe value. | |
| 4. Relaunch and inspect settings. | Numeric settings reload correctly; runtime-only checkbox behavior follows implementation and is not falsely reported persisted. | |
| 5. Restore approved values and guard enables. | Baseline settings return with no output start. | |

### INTER-2.2 - Combined E-stop scope and idempotency

**Description:** Verify user E-stop shuts BCON and CCS down without a Knob Box
or high-voltage action.

**Initial conditions:** In separate iterations use idle/disarmed and active
BCON A plus CCS A/B dummy-load states; VTRX `SAFE_1200`.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Press `E-STOP: BEAMS & CCS` while idle/disarmed. | BCON all-off and reachable CCS OFF paths run safely; no high-voltage or Knob Box command is issued. | |
| 2. Start BCON A DC and CCS A/B output, then press E-stop. | BCON confirms all-off and active CCS outputs receive OFF; LEDs/dummy loads reach zero or remain explicitly uncertain. | |
| 3. Press E-stop repeatedly. | Each press creates at most one bounded attempt; attempts do not overlap and no stale output appears. | |
| 4. Make one 9104 Power Supply unavailable and press E-stop. | BCON and each CCS result remain separately attributable; failure is not summarized as confirmed combined safe state. | |
| 5. Restore communication and obtain confirmed BCON/CCS OFF. | No pre-E-stop output, enable, or ramp replays. | |

### INTER-2.3 - BCON manual disconnect with active CCS

**Description:** Verify BCON-disconnect guard orders CCS protection and does
not infer physical OFF.

**Initial conditions:** BCON A OFF; CCS A active on dummy load;
BCON-disconnect guard enabled.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Select BCON Disconnect and cancel confirmation. | BCON stays connected and CCS A remains at its physical state. | |
| 2. Select Disconnect again and approve. | CCS A confirms OFF. | |
| 3. Restore BCON and fresh CCS readbacks. | Recovery does not enable CCS or BCON output automatically. | |
| 4. Disable the `CCS Output off on BCON Disconnect` setting in main Control Config, activate CCS A, and disconnect BCON. | CCS A remains physically active because guard is disabled; state is shown truthfully then manually shut down. | |

### INTER-2.4 - Short BCON loss, watchdog, and stale-command truth

**Description:** Exercise physical BCON loss before watchdog stop and dashboard
auto-disconnect.

**Initial conditions:** BCON A DC and CCS A ON; watchdog `5000 ms`;
BCON-disconnect guard enabled; VTRX `SAFE_1200`.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Remove BCON serial cable and, before auto-disconnect, request Beam A OFF and Disable All in separate iterations. | No unreachable command is firmware-confirmed; physical state remains authoritative until watchdog/fresh readback proves it. | |
| 2. Restore cable within 1 s, before watchdog expiry. | Fresh polling reconciles state without disconnect callback, CCS shutdown, duplicate worker, or replay. | |
| 3. Repeat and restore after watchdog but before ten failed polls. | Firmware A OFF is distinct from host connection; any still-powered CCS A remains truthfully shown. | |
| 4. Leave cable absent through ten failed 500 ms polls. | Driver disconnects after roughly 5-7 s; BCON is unavailable and guard invokes one CCS all-off path. | |
| 5. Reconnect, verify physical zero, and inspect chronology. | Watchdog, disconnect, CCS action, operator command, and recovery are separately logged. | |

## Suite 3 - VTRX fixed-pressure profiles and stale-data handling

**Description:** Test VTRX integration using only fixed 1200 mbar, pre-launch
constants, and intentional stale data.

**Initial conditions:** Dashboard is closed before every profile change. No
VTRX pressure, packet, error, switch, valve, or hardware simulation is used.

### INTER-3.1 - Fixed-pressure profile startup semantics

**Description:** Verify labels, live pressure, and Machine Status use intended
comparison semantics for all profiles.

**Initial conditions:** Run separate launches with `SAFE_1200`, `EQUAL_1200`,
and `UNSAFE_1200`; VTRX remains connected at fresh 1200 mbar.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Launch with `SAFE_1200` and wait for fresh VTRX data. | Main Control permits eligible guarded commands; both pressure stages are green when other prerequisites permit. | |
| 2. Launch with `EQUAL_1200` and inspect before output commands. | Main Control treats equality safe; pressure stages are not green because they require strictly below. | |
| 3. Launch with `UNSAFE_1200` and inspect guards/status. | Main Control identifies fresh high pressure; pressure stages are not ready and no default/stale value is called safe. | |
| 4. Compare labels/logs in all launches. | Main Control says exceeds/above and Machine Status behavior says below; reversed equality semantics are defects. | |
| 5. Restore `SAFE_1200` before the next suite. | The approved temporary profile is applied and no dashboard instance remains open. | |

### INTER-3.2 - High fixed pressure with active BCON and CCS

**Description:** Verify `UNSAFE_1200` invokes immediate Beam protection and CCS
grace behavior without pressure simulation.

**Initial conditions:** Launch with `UNSAFE_1200`; BCON A DC active; CCS A/B
active on dummy loads; VTRX Beam/CCS guards enabled; grace set to 5 s.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Allow first fresh 1200 mbar callback. | BCON all-off is requested once for unsafe episode; A LED goes dark and channel enables clear. | |
| 2. Observe CCS for 5 s. | Existing outputs remain on only during grace; new CCS enable is blocked immediately. | |
| 3. Observe first callback at or after expiry. | Active CCS channels receive OFF; dummy-load output reaches zero or remains explicitly uncertain. | |
| 4. Hold same 1200 mbar for several callbacks. | BCON is not repeatedly re-commanded after confirmed all-off; unresolved CCS failure remains attributable. | |
| 5. Relaunch with `SAFE_1200`. | Fresh safe data clears latch/timer; no BCON or CCS output resumes. | |

### INTER-3.3 - Equality and new-command behavior at 1200 mbar

**Description:** Verify equality is Main Control safe while strict Machine
Status pressure stages remain not ready.

**Initial conditions:** Launch with `EQUAL_1200`; VTRX fresh at 1200 mbar;
BCON/CCS idle and connected.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Stage below-limit cathode prediction, arm BCON, enable CH A, and request Beam A. | Main Control pressure guard permits fresh request; success still needs BCON acknowledgement. | |
| 2. Enable CCS A at safe dummy-load Goal. | VTRX CCS guard permits output because 1200 equals, not exceeds, its limit. | |
| 3. Inspect Machine Status pressure stages. | Both pressure stages are not green at equality under temporary strict-below constants. | |
| 4. Disable BCON output and CCS A. | Confirmed physical zero returns before profile change. | |

### INTER-3.4 - VTRX disconnect, stale guards, and recovery

**Description:** Verify stale data behaves unsafe without changing VTRX
physical pressure.

**Initial conditions:** `SAFE_1200`; BCON A DC and CCS A active; both VTRX
guards enabled; grace 5 s.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Disconnect VTRX and observe beyond 3 s freshness. | Vacuum shows stale/no-data; pressure stages are not ready; retained 1200 mbar is not presented fresh. | |
| 2. Observe BCON after stale is reported. | Beam guard requests one all-off for stale episode; LED/readback distinguishes request from physical result. | |
| 3. Observe CCS through stale-data grace. | New CCS enable is blocked; active output receives OFF on expiry or remains explicitly uncertain. | |
| 4. Reconnect VTRX without changing reading and wait for fresh 1200 mbar. | Fresh data clears stale/timer under `SAFE_1200`; no output or blocked request replays. | |
| 5. Repeat disconnect while outputs are idle. | Stale status remains visible and new guarded Beam/CCS starts fail closed. | |

### INTER-3.5 - Vacuum UI and source-profile restoration

**Description:** Exercise retained Vacuum actions and ensure temporary source
edits cannot leak into later cases.

**Initial conditions:** VTRX connected at fixed 1200 mbar; copied writable plot
destination available; at least one nondefault profile has been used.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Select each Vacuum time window and return to default. | Plot/window labels update without changing VTRX source, guard, or output. | |
| 2. Save Plot, cancel, save to copied writable path, then try unwritable path. | Cancel is inert; valid plot saves; write failure is explicit and polling remains responsive. | |
| 3. Close dashboard and restore default source constants. | Main Control returns to `1e-5`; Machine Status returns to `1e-4` and `1e-6 mbar`. | |
| 4. Inspect source diff and relaunch at fixed 1200 mbar. | Only approved constants changed and are restored; default policy reports expected high/not-ready result. | |



### INTER-3.6 - Fresh VTRX recovery cancels an active CCS countdown

**Description:** Verify fresh good VTRX data received before grace expiry clears the
CCS shutdown timer and prevents a delayed output OFF.

**Initial conditions:** Launch with `SAFE_1200`; BCON connected; CCS A active on
dummy load; VTRX CCS guard enabled; grace duration set to 10 s; BCON output OFF.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Disconnect VTRX and wait beyond the 3 s freshness interval until the stale-data CCS countdown is visibly/logged active. | CCS A remains physically ON during 10 s grace, new CCS output is blocked, and evidence names stale VTRX data/countdown. | |
| 2. With at least 2 s remaining before recorded countdown deadline, reconnect VTRX and wait for one fresh fixed 1200 mbar reading. | Fresh `SAFE_1200` data clears stale state/countdown; CCS A remains physically ON and countdown warnings stop. | |
| 3. Wait past original recorded 10 s deadline plus one VTRX update interval. | No deferred CCS OFF is sent, no dummy-load output drops, and no old timer/action line reappears. | |
| 4. Request a fresh permitted CCS B ON action, then turn B OFF. | Fresh good VTRX data permits new guarded action; no stale timer blocks it or causes delayed OFF. | |
| 5. Turn CCS A OFF and restore approved grace setting. | Dummy-load outputs are zero and no timer remains active. | |


## Suite 4 - Cathode Heating, emission guard, and BCON coordination

**Description:** Test CCS UI/physical behavior and projected-emission integration
without using Knob Box control or Beam Energy limits.

**Initial conditions:** Apply `SAFE_1200` before launch; BCON connected; CCS
dummy loads ready; emission guard enabled; no output active.

### INTER-4.1 - Complete CCS action sweep on dummy loads

**Description:** Exercise retained CCS Main and Config actions while observing
their effect on BCON eligibility and state truth.

**Initial conditions:** Use copied approved LUT and low-energy `CROSS_CCS_PAIR`.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Set Current and Voltage Goals and use both permitted nudges for A, B, and C. | Only selected cathode Goal changes; invalid/nonfinite entry is rejected without physical output change. | |
| 2. Select each available CCS mode, configure valid slew/protection settings, and apply a safe Goal. | Mode, staged settings, sent command, readback, and dummy-load state remain distinct. | |
| 3. Toggle each cathode Output ON then OFF in separate iterations. | ON/OFF acknowledgement and physical dummy-load state agree; no BCON or high-voltage request is implied. | |
| 4. Start each ramp mode and select STOP RAMP. | Worker stops without being mislabeled output OFF; separate OFF obtains zero output. | |
| 5. Select Log Power Settings and inspect Messages. | Evidence names the correct cathode and no Knob Box action is fabricated. | |

### INTER-4.2 - Known-LUT projected-channel emission guard matrix

**Description:** Verify the guard evaluates only projected output channels, not
all configured cathodes, and includes an already-active BCON channel.

**Initial conditions:** Install and select the documented `CCS_test_alt.csv`
fixture for A, B, and C. Set only each cathode Voltage Goal to `0.30 V`; each
must display predicted Emission `0.56 mA` (internal value `0.400 / 0.72 =
0.5556 mA`). Confirm no prediction is `--`, VTRX is `SAFE_1200`, BCON is armed,
and all BCON outputs are OFF. Use the exact emission-limit values in the table;
do not calculate substitute limits.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Set Main Control emission limit to `0.50 mA`; enable only CH A; request Beam A and Activate Enabled Beams in separate runs. | Each start is blocked before a BCON write: A's `0.5556 mA` prediction is at/above `0.50 mA`; the feedback/log names projected total and limit. | |
| 2. Set Main Control emission limit to `1.00 mA`; enable CH A and CH B; select Activate Enabled Beams. | A and B are individually below `1.00 mA`, but their projected `1.1112 mA` total blocks the complete activation before a BCON write; neither channel partially starts. | |
| 3. Set Main Control emission limit to `1.20 mA`; leave CH C disabled/OFF, enable CH A and CH B, and select Activate Enabled Beams. | A+B projected total `1.1112 mA` is permitted; C stays OFF and its `0.5556 mA` does not count even though all three configured predictions total `1.6668 mA`, above the limit. | |
| 4. Turn A and B OFF; retain `1.00 mA` limit. Start CH A and confirm it is active, then enable CH B and request only Beam B. | B start is blocked before BCON write because active A plus requested B projects `1.1112 mA`, at/above `1.00 mA`; A remains truthfully active until explicitly stopped. | |
| 5. Turn all BCON channels OFF, disable the emission guard, retain the `0.50 mA` limit, and repeat Beam A request. | Only the emission guard is bypassed; VTRX, BCON interlock, and connection checks remain active. | |
| 6. Restore the emission guard, approved production LUTs/Goals, and confirmed all-off. | Baseline returns with no blocked/staged request replay. | |

### INTER-4.3 - Live Goal and prediction changes during Beam output

**Description:** Find retrospective shutdown, stale prediction, and cross-channel
errors caused by CCS Goal changes after a Beam starts.

**Initial conditions:** Beam A DC active on isolated BCON output; CCS A ON;
known below-limit A prediction; emission guard enabled.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Change A Goal to create prediction above limit. | Existing Beam A state is not falsely rewritten; future Beam/Activate requests use current projected total. | |
| 2. Clear A Current Goal while retaining a LUT known to support voltage-only prediction. | Heater/readback remains physically truthful; prediction recomputes from remaining Voltage Goal without old Current Goal. | |
| 3. Clear A Voltage Goal as well. | Heater remains at last command, both Goals are unset, and prediction is unavailable rather than zero/stale. | |
| 4. Attempt Beam B, Activate Enabled Beams, and fresh A Beam request. | Future guarded output fails closed on unavailable/unsafe prediction before BCON write. | |
| 5. Stop Beam A and CCS A, then explicitly restore valid Goals. | Outputs reach zero; prediction returns only after explicit staging and nothing restarts. | |

### INTER-4.4 - CCS transport/power loss and BCON coordination

**Description:** Verify physically powered dummy loads are not treated as OFF
when CCS communications fail.

**Initial conditions:** CCS A/B active on dummy loads; BCON A active; VTRX
`SAFE_1200`; physical CCS emergency power removal available.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Remove A individual CCS communication/power path and attempt Goal change and Output toggle. | No unavailable 9104 command is falsely acknowledged; physical A state remains observed or explicitly uncertain. | |
| 2. Remove shared CCS transport while A/B are active. | Each channel retains separate uncertainty; no response is cross-routed and no peer is falsely called OFF. | |
| 3. Press combined E-stop while CCS communication is unavailable. | BCON all-off remains separate; every reachable CCS OFF attempt is logged and physical mitigation is required for uncertainty. | |
| 4. Remove physical CCS power if any dummy-load output remains active. | Zero output is established and recorded as physical mitigation, not software acknowledgement. | |
| 5. Restore paths, readbacks, protections, and outputs OFF. | No stale CCS Goal, BCON output, or worker resumes. | |

### INTER-4.5 - Temperature/overtemperature and Machine Status behavior

**Description:** Verify CCS temperature status is not confused with hardware
shutdown command.

**Initial conditions:** Stable dummy or approved E5CN temperature T available;
CCS output OFF; record approved overtemperature limit.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Set overtemperature limit to T plus margin, exactly T, and T minus margin. | Below/equality remain Normal; only T above configured limit warns/force-reds Cathode Heating status. | |
| 2. Enable CCS A at safe Goal while temperature is below limit. | Cathode Heating may become ready from real output; no BCON or Knob Box control changes. | |
| 3. Set limit below stable T while CCS A remains on. | Temperature/alarm and Machine Status are truthful; no shutdown is claimed without actual OFF command/readback. | |
| 4. Restore approved limit, turn CCS A OFF, and verify zero. | Temperature/status recovery and physical OFF are separately evidenced. | |

### INTER-4.6 - BCON disconnect guard across CCS modes

**Description:** Verify BCON loss stops Immediate and ramping CCS work only when
the allowed guard is enabled.

**Initial conditions:** In separate runs use CCS A/B/C Immediate and ramp modes;
BCON connected; BCON-disconnect guard enabled.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Start one permitted CCS mode, then select BCON Disconnect and approve. | Ramps stop and active outputs receive OFF before BCON closes, or disconnect is blocked with explicit uncertainty. | |
| 2. Restore BCON and repeat with physical BCON serial loss through auto-disconnect. | Watchdog/host loss and later CCS guard action are distinct; no CCS worker survives confirmed all-off. | |
| 3. Disable guard, repeat with CCS A active, and disconnect BCON. | CCS remains physically active until explicit CCS OFF; disabled policy is visible in logs/status. | |
| 4. Restore guard, BCON, CCS readbacks, and zero output. | Normal guarded state returns without automatic restart. | |


### INTER-4.7 - Invalid lookup-table CSV and zero-prediction blocking

**Description:** Verify malformed CCS lookup-table CSV data and a displayed
zero predicted emission cannot authorize a BCON output start.

**Initial conditions:** Emission guard enabled; VTRX `SAFE_1200`; BCON connected,
armed as needed, and all outputs OFF. Use copied CCS lookup-table fixtures only;
this is not Beam Pulse CSV testing.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. In separate reload/restart iterations, select/load a copied empty, malformed, unreadable, wrong-header, missing-column, nonnumeric, or nonfinite CCS lookup-table CSV for Cathode A. | The LUT is rejected or A prediction is explicitly unavailable; dashboard remains responsive and does not retain a stale valid A prediction under the invalid fixture. | |
| 2. Stage CH A while its prediction is unavailable, then request Beam A and Activate Enabled Beams in separate iterations. | Channel enable may remain only a non-output staging state, but every non-OFF Beam request fails closed before a BCON write and names A prediction unavailable. | |
| 3. Load an approved valid-shaped zero-output LUT fixture that displays A predicted emission exactly `0.00 mA`, then stage A and request Beam A/Activate in separate iterations. | A zero prediction is invalid for beam authorization in this plan and must be rejected before BCON write. If a zero value is accepted as a valid safe prediction, record a safety defect with the sent/acknowledged evidence. | |
| 4. Select Beam A OFF and Disable All after each iteration. | OFF paths remain available regardless of LUT/prediction validity and obtain confirmed physical OFF. | |
| 5. Restore the approved production LUT and below-limit Goal, then recalculate. | A valid prediction returns only from explicit restoration; no CCS or BCON output starts automatically. | |

## Suite 5 - Beam Pulse manual controls and Arm Beams interlock

**Description:** Exercise every retained Beam Pulse manual path, excluding the
entire CSV tab, and prove hardware interlock behavior using Logic Override.

**Initial conditions:** `SAFE_1200`; Logic Override installed; physical Arm
Beams ON; BCON LEDs dark; watchdog 1500 ms.

### INTER-5.1 - Connection, watchdog, and manual A/B/C configuration

**Description:** Verify BCON manual controls are bounded and correctly mapped.

**Initial conditions:** BCON connected/disarmed; channels disabled.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Inspect Connect/Disconnect state, interlock/watchdog label, and watchdog Set. | State is current; initial watchdog/interlock text agrees with LCD/register data. | |
| 2. Set valid 1500 ms watchdog, then attempt below-minimum, above-maximum, blank, and nonnumeric values. | Valid value is confirmed; invalid values are rejected without misleading success/unsafe hardware write. | |
| 3. Configure A/B/C for OFF, DC, PULSE, and PULSE TRAIN with valid duration/count partitions. | Each channel retains its configuration; invalid duration/count is rejected before output action. | |
| 4. Configure visually distinct values for A/B/C and inspect cards/LCD/log. | Channel identity remains one-to-one and no output starts during configuration. | |

### INTER-5.2 - ARM, channel enable, manual output, Activate, and all-off

**Description:** Exercise retained Main Control and Beam Pulse manual output
actions with isolated BCON outputs.

**Initial conditions:** Known below-limit predictions; VTRX `SAFE_1200`; BCON
connected; physical Arm Beams ON.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Select ARM BEAMS, then enable/disable CH A/B/C in combinations. | Software arm/channel-enable state changes as designed; arming alone produces no gate output. | |
| 2. Request each valid manual mode on A, B, and C in separate iterations. | Only selected channel LCD/card/LED/register changes after firmware acknowledgement. | |
| 3. Enable selected A/C and use Activate Enabled Beams. | One guarded preflight evaluates enabled set; only eligible selected channels start. | |
| 4. Select individual Beam OFF, Disable All Beams, and disarm in separate iterations. | OFF/all-off are physically confirmed; disarm clears permitted staging/enables and never commands CCS/HV. | |
| 5. Press combined E-stop from disarmed state. | BCON and CCS stop idempotently; high-voltage requests and Knob Box state remain untouched. | |

### INTER-5.3 - Physical Arm Beams interlock with Logic Override

**Description:** Verify physical Arm Beams remains an independent BCON
permission gate and cannot create a latent start.

**Initial conditions:** BCON connected; Logic Override confirmed; software arm
available; outputs OFF.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Turn physical Arm Beams OFF and wait for fresh BCON state. | LCD/dashboard show unsafe interlock; LEDs remain dark while transport can stay connected. | |
| 2. Software-arm, configure A DC, attempt CH A enable and Activate. | Unsafe interlock rejects/clears enable/output; no blue A LED appears. | |
| 3. Turn Arm Beams ON without new BCON output command. | Interlock returns healthy but no mode, enable, or output resumes automatically. | |
| 4. Start A DC, then turn Arm Beams OFF while active. | Firmware forces A low; dashboard/Laser beams-on reconcile from live BCON state without calling it VTRX/CCS shutdown. | |
| 5. Restore Arm ON, issue fresh A command, then Disable All and disarm. | Only fresh command starts A; final BCON state is confirmed OFF/disabled. | |

### INTER-5.4 - BCON cable, power, and stale-state recovery

**Description:** Test physical BCON loss without allowing stale manual state to
become new output request.

**Initial conditions:** BCON A DC active on disconnected output; watchdog 1500
ms; Laser Monitor connected; CCS OFF.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Remove BCON serial cable and observe past watchdog expiry. | Firmware drives A low at watchdog expiry; dashboard does not present retained activity as fresh. | |
| 2. Observe until ten failed polls cause auto-disconnect. | Beam Pulse clears arm/channel/output mirrors and does not replay old DC request. | |
| 3. Restore cable without selecting Reconnect, then Reconnect and wait for fresh registers. | Reconnect requires explicit action where implemented; BCON returns all channels OFF/disabled. | |
| 4. Repeat with BCON power loss and laptop USB adapter removal. | Failure cause is correctly classified; host/serial loss is not mislabeled interlock or confirmed all-off. | |
| 5. Restore power/adapter, confirm 1500 ms watchdog, Disable All, and disarm. | Baseline returns with no retained mode, enable, output, or queue. | |

### INTER-5.5 - Manual action races and source-of-truth chronology

**Description:** Find stale queued success and race errors across manual BCON,
Main Control, CCS, and Laser Monitor evidence.

**Initial conditions:** BCON connected; Arm ON; valid safe A/B modes staged;
CCS A on dummy load in selected iterations.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Queue Beam A ON or Activate, then immediately select Disable All or E-stop. | Final confirmed all-off wins; older queued write does not reassert output. | |
| 2. Request A output while physical Arm Beams is OFF. | Optimistic queued/sent line is superseded by firmware rejection; BCON LED/Laser beams indicator stay OFF. | |
| 3. Disconnect BCON during manual request. | Connection failure supersedes optimistic state; no Main/Machine Status/Laser surface claims live Beam output. | |
| 4. Compare request, queue, acknowledgement, register, LED, Laser, Machine Status, and log times. | Requested, accepted/rejected, live output, and shutdown remain chronologically distinct. | |


### INTER-5.6 - Manual Beam Pulse and Main Control emission-guard parity

**Description:** Verify direct Manual Control sends and Main Control Beam/Activate
actions enforce the same emission decision before any BCON write.

**Initial conditions:** Install and select the documented `CCS_test_alt.csv`
fixture for A, B, and C. Set only each cathode Voltage Goal to `0.30 V`; each
must display predicted Emission `0.56 mA` (internal value `0.5556 mA`). VTRX is
`SAFE_1200`; emission guard enabled; BCON armed; and A/B/C DC configurations
staged with all outputs OFF. Use the exact emission-limit values in the table;
do not calculate substitute limits.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Set Main Control emission limit to `0.50 mA`, enable CH A, then use Beam Pulse Manual Control Send/Apply for A and Main Control Beam A in separate runs. | Both output paths reject A before a BCON write because A projects `0.5556 mA`, at/above `0.50 mA`; no blue A LED or Laser beams-on transition occurs. | |
| 2. Set Main Control emission limit to `1.00 mA`. Start A, confirm it is active, then use Manual Control Send/Apply for B and Main Control Beam B in separate runs. | Both B paths block because active A plus requested B projects `1.1112 mA`, at/above `1.00 mA`; A remains active until a separate OFF. | |
| 3. Turn all channels OFF, set Main Control emission limit to `1.20 mA`, leave C disabled/OFF, and start A/B through Manual Control and Activate Enabled Beams in separate runs. | A+B projected total `1.1112 mA` is permitted because only A/B are projected; C stays OFF and its `0.5556 mA` is excluded even though all three configured predictions total `1.6668 mA`, above the limit. | |
| 4. Select individual OFF, Disable All, and disarm after each iteration. | OFF actions bypass emission blocking and return BCON/Laser/Machine Status to confirmed idle. | |

## Suite 6 - PMON actions and Machine Status source behavior

**Description:** Use PMON controls and approved physical actions to exercise
PMON Temperatures OK and its effect on the full dashboard.

**Initial conditions:** PMON COM connected; enabled channels in range; approved
dummy sensor and PMON physical access available.

### INTER-6.1 - PMON baseline, mapping, and Environment Pass

**Description:** Verify PMON values and Environment Pass feed the correct
Machine Status stage.

**Initial conditions:** Record DP16 front-panel values; enabled sensors are
strictly inside their warning bounds.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Wait for two PMON polls and compare enabled rows to DP16 displays. | Enabled values are current/correctly routed; Unassigned remains OFF when disabled. | |
| 2. Inspect Environment Pass, Machine Status, and Messages. | Environment Pass is true; PMON Temperatures OK is green when display ordering permits; logs identify valid readings. | |
| 3. Use approved dummy sensor on one permitted channel and change it gently within safe range. | Only mapped PMON row follows; no BCON, CCS, VTRX, SIC, Laser, or Knob Box state changes. | |

### INTER-6.2 - PMON Config controls, bounds, and persistence

**Description:** Exercise PMON enabled/range actions that alter Machine Status
readiness without modifying hardware outside PMON.

**Initial conditions:** Back up `usr/usr_data/process_monitor_config.json`; one
approved dummy-capable sensor is stable at temperature T.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Toggle each PMON row Enabled OFF then ON, one row at a time. | Selected row shows OFF then waits for fresh data; only that row enters/leaves Environment Pass and logs change. | |
| 2. Set warning bounds with T inside, at equality, and strictly outside. | Inside/equality remain passing; strictly outside turns row orange, makes Environment Pass false, and PMON status not green. | |
| 3. Attempt invalid numeric, reversed, and nonfinite warning/bar ranges. | Invalid configuration is rejected without replacing active safe bounds. | |
| 4. Relaunch and inspect saved valid settings, then restore approved configuration. | Persisted values/enable states reload correctly and baseline is restored. | |

### INTER-6.3 - PMON sensor, power, and transport loss

**Description:** Distinguish single sensor failure from PMON communication loss
and verify Machine Status never calls either healthy.

**Initial conditions:** At least one enabled dummy-capable sensor has recent
valid reading; BCON/CCS outputs OFF.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Remove one approved dummy sensor, then reconnect it. | Its row transitions through ERR/disconnected behavior as implemented; other rows stay current; Environment Pass is false until recovery. | |
| 2. Remove PMON power, then restore it. | Enabled rows become unavailable after retry/disconnect; PMON status is not green; reconnect is rate-limited and automatic where implemented. | |
| 3. Remove PMON RS-485 cable, then laptop USB/RS-485 adapter, in separate iterations. | Transport loss is distinct from sensor overtemperature; dashboard remains responsive and does not flood logs. | |
| 4. Restore all PMON paths and wait for fresh values. | Only fresh valid data restores Environment Pass/PMON status; no unrelated output starts. | |

## Suite 7 - SIC physical inputs and Machine Status source behavior

**Description:** Drive permitted SIC inputs to test All Safety Interlocks Pass
and High Voltage Subpanel On without energizing high voltage.

**Initial conditions:** Approved isolated SIC fixture connected; G9SP Output
off; record physical input/output states; no high-voltage source energized.

### INTER-7.1 - SIC baseline, display-only behavior, and mapping

**Description:** Verify SIC indicators, controller state, and Machine Status
mapping at safe baseline.

**Initial conditions:** SIC COM selected; all fixture inputs healthy; HVolt
monitor feedback off.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Start/refresh SIC and wait for two polls. | Dashboard receives current SIC data without transport error or output command. | |
| 2. Compare every Interlocks-strip indicator to fixture LEDs/status. | E-stops, Door, Vacuum, oil, Water, aggregate, G9SP Output, and HVolt labels map correctly. | |
| 3. Inspect Machine Status. | All Safety Interlocks Pass is green; High Voltage Subpanel On is not green while G9SP Output/HVolt feedback are off. | |
| 4. Navigate, resize, and return while SIC polls. | SIC is display-only in dashboard; no hidden safety-input command or duplicate polling appears. | |

### INTER-7.2 - Ordinary SIC inputs, E-stops, and recovery

**Description:** Exercise permitted physical safety faults and ensure recovery
needs fresh healthy controller snapshot.

**Initial conditions:** SIC baseline healthy; G9SP Output off.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Remove/restore VTRX Override, OTRX Override, and Water inputs in separate iterations. | Only documented detail indicators and All Interlocks turn red; recovery requires matching restored input and fresh read. | |
| 2. Press/release/reset internal E-stop using approved physical procedure. | E-STOP Int and All Interlocks turn red; asserted isolated G9SP output de-energizes; no automatic output re-enable follows reset. | |
| 3. Repeat with external E-stop. | E-STOP Ext is correctly named; aggregate and Machine Status fail-safe behavior matches physical fault. | |
| 4. Create Door fault and external E-stop before next SIC poll, then recover one at a time. | Both faults remain until individually healthy/reset; no intermediate all-safe state is displayed. | |

### INTER-7.3 - Door protection and HVolt-monitor forced-red state

**Description:** Verify door semantics and special output-demand/HVolt-feedback
Machine Status rule on isolated fixture.

**Initial conditions:** First-11 SIC inputs healthy; G9SP Output off; door and
HVolt-monitor fixtures available.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. With door open, use approved dummy key to simulate only locked sensor, then change door-unlock position. | Door remains unsafe until every physical channel is healthy; dummy key cannot bypass open-door fault. | |
| 2. Restore door baseline and assert isolated G9SP Output while HVolt feedback remains off. | G9SP Output reflects controller; HVolt ON remains red; High Voltage Subpanel On is forced red without energizing HV. | |
| 3. Apply approved HVolt-monitor ON fixture feedback, then remove it. | HVolt ON and High Voltage Subpanel On become ready only with current feedback and return forced red when demand remains without it. | |
| 4. Reset G9SP Output through approved SIC physical safety path. | Output returns OFF and no residual output-demand/ready indication remains. | |

### INTER-7.4 - SIC power, serial, and wrong-endpoint failures

**Description:** Verify unavailable SIC is distinct from physical input fault.

**Initial conditions:** SIC healthy and G9SP Output off; record adapter COM
identity.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Remove SIC power and observe through connection-failure interval. | Indicators and All Safety Interlocks Pass become unavailable/not ready; stale green is not current. | |
| 2. Restore power and wait for fresh snapshot. | Current physical input state returns with one recovery path and no automatic G9SP Output assertion. | |
| 3. Remove SIC serial cable and laptop adapter in separate iterations. | Transport loss is logged/classified distinctly from E-stop, Door, or Water fault; UI remains responsive. | |
| 4. Configure copied launch with wrong, busy, or non-SIC endpoint. | Connection fails safely without generic healthy status, wrong-device command, or reconnect storm. | |


## Suite 8 - Complete Machine Status evaluation

**Description:** Exercise every Machine Status stage, display priority, source
freshness rule, and advisory boundary using permitted source actions.

**Initial conditions:** `SAFE_1200`; PMON/SIC healthy; passive Knob Box values
observed but never changed; BCON/CCS outputs OFF.

### INTER-8.1 - Ten-stage source and readiness matrix

**Description:** Verify every stage has correct source and Machine Status issues
no hardware command itself.

**Initial conditions:** All permitted sources healthy; passive Knob Box data has
whatever fixed current state the fixture presents.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Verify PMON Temperatures OK from Environment Pass. | Stage 1 reflects PMON only and is green when PMON is healthy. | |
| 2. Verify Pressure Below 1e-4 and Pressure Below 1e-6 under `SAFE_1200`. | Stages 2 and 5 are green only from fresh VTRX plus temporary strict-below thresholds. | |
| 3. Verify All Safety Interlocks Pass and High Voltage Subpanel On. | Stages 3 and 4 reflect SIC aggregate/output/HVolt feedback, not dashboard intent. | |
| 4. Inspect HV Power Supplies Nominal and Beam Controller Nominal. | Stages 6 and 7 reflect passive fixed Knob Box prerequisites plus BCON state; no Knob state is changed to make them pass. | |
| 5. Enable safe CCS A, then arm BCON with physical Arm Beams ON. | Cathode Heating and Beams Ready reflect actual CCS/BCON/prerequisite state, including passive stage-6/7 conditions. | |
| 6. Start and stop BCON A DC on disconnected output. | Beams On follows live BCON activity; Machine Status issues no output command and returns once A is confirmed OFF. | |

### INTER-8.2 - Pressure-stage strictness and stale VTRX behavior

**Description:** Cover both pressure stages at permitted fresh/equality/high/stale
conditions without pressure simulation.

**Initial conditions:** Run separate launches with `SAFE_1200`, `EQUAL_1200`,
and `UNSAFE_1200` as needed.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. With `SAFE_1200`, observe fresh fixed 1200 mbar. | Both pressure stages are green when no direct warning/earlier source issue blocks progression. | |
| 2. With `EQUAL_1200`, observe fresh 1200 mbar. | Both pressure stages are not ready because equality is not below; this does not reverse Main Control equality-safe guard. | |
| 3. With `UNSAFE_1200`, observe fresh 1200 mbar. | Both pressure stages remain not ready and Main Control high-pressure behavior stays separately truthful. | |
| 4. Under `SAFE_1200`, disconnect VTRX beyond 3 s freshness. | Both pressure stages become not ready/behind-red by stage ordering; last 1200 value is not fresh. | |
| 5. Reconnect VTRX and wait for fresh 1200 mbar. | Only a new valid timestamp restores pressure-stage readiness. | |

### INTER-8.3 - Forced red, green, behind red, and gray priority

**Description:** Validate Machine Status display ordering with permitted PMON,
SIC, CCS, VTRX, and BCON actions.

**Initial conditions:** `SAFE_1200`; source baselines healthy; outputs OFF.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Make one enabled PMON sensor outside warning range. | PMON Temperatures OK is not green; later-ready stages may make it behind-red rather than falsely green. | |
| 2. Restore PMON, then assert isolated G9SP Output with HVolt feedback off. | High Voltage Subpanel On is forced red even if otherwise ready. | |
| 3. Restore SIC, then set CCS overtemperature limit below stable T. | Cathode Heating is forced red; unrelated stages retain their own evaluated state. | |
| 4. Restore CCS and turn physical Arm Beams OFF while software arm is on. | Beams Ready is not green; status bar sends no BCON output command. | |
| 5. Restore every source and inspect gray-to-green/red transitions. | Direct warning overrides green; unavailable/not-ready is gray unless later green makes it behind-red. | |

### INTER-8.4 - Beam readiness/on truth and passive Knob prerequisites

**Description:** Prove stages 6, 7, 9, and 10 do not substitute dashboard
intent for hardware/passive-source truth.

**Initial conditions:** Record passive Knob Box stage-6/7 prerequisites without
changing them; `SAFE_1200`; BCON connected/idle.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Inspect stages 6 and 7 before arming BCON. | Each matches current passive Knob Box and BCON inputs; unavailable/non-nominal data remains not ready and is not altered. | |
| 2. Software-arm BCON with physical Arm ON but leave channels OFF. | Beams Ready changes only if every earlier prerequisite, including passive stage-6/7 conditions, is satisfied. | |
| 3. Enable/activate A and compare stage 10 to BCON LED/register and Laser beams-on LED. | Beams On becomes green only from live BCON output; queued request/Laser state alone cannot make it green. | |
| 4. Turn physical Arm OFF during A DC, then restore it. | BCON forced-off clears Beams On; Beams Ready/output does not recover until fresh permitted command and prerequisites. | |
| 5. Disarm and inspect stages. | Summary returns source-accurate idle state without any Knob Box manipulation. | |

### INTER-8.5 - Cross-source availability, logs, and worker recovery

**Description:** Verify Machine Status handles one unavailable provider at a time
and recovers from fresh data without stale all-green state.

**Initial conditions:** Documented baseline; output OFF.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. In separate iterations disconnect VTRX, PMON transport, SIC transport, BCON transport, and CCS transport. | Only dependent stages become unavailable/not ready; unrelated source stages retain latest valid evaluation. | |
| 2. Restore each source one at a time. | Recovery follows fresh source data and one attributable transition; Machine Status issues no hardware command. | |
| 3. Rapidly alternate permitted PMON and SIC faults around status refreshes. | Worker/UI remain responsive; colors/logs show no impossible all-green intermediate after known fault. | |
| 4. Quit/relaunch after fault iterations. | Machine Status worker is canceled before subsystem teardown and restarts once with current source state. | |

### INTER-8.6 - Advisory status versus protection-action chronology

**Description:** Ensure status color is not mislabeled confirmed shutdown and
protection action is not hidden by static status.

**Initial conditions:** `UNSAFE_1200` run with BCON/CCS active in separate
iterations; outputs isolated/dummy-loaded.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Let fresh 1200 mbar invoke Main Control protection. | Status reports source readiness/warning while BCON/CCS lines separately identify requested, confirmed, or uncertain shutdown. | |
| 2. Cause PMON or SIC fault without BCON/CCS action. | Machine Status changes, but no false beam/CCS shutdown confirmation appears solely from its color. | |
| 3. Resolve source faults and relaunch `SAFE_1200`. | Recovery is source-specific; no prior BCON/CCS output or blocked command replays. | |

## Suite 9 - Laser Monitor firmware, serial transport, and beams-on integration

**Description:** Test approved Laser Monitor firmware/serial behavior and the
live BCON beams-on path. Radiation state is intentionally out of scope.

**Initial conditions:** Approved sibling Laser Monitor firmware installed on
isolated Arduino fixture. Radiation indicator is neither controlled nor assessed.
BCON connected and outputs OFF.

### INTER-9.1 - Connection, protocol baseline, and COM lifecycle

**Description:** Verify startup creates one Laser Monitor worker that maintains
a healthy complete-state exchange.

**Initial conditions:** Valid dedicated Laser Monitor COM selected; serial
protocol monitor/fixture available.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Launch dashboard and wait through Arduino 2 s serial-reset settling. | Laser Monitor connects without blocking dashboard; one worker owns its COM port. | |
| 2. Observe timestamps, OK replies, and the beams field for several normal exchanges. | Driver maintains its documented complete-state exchange about every 500 ms; beams-on remains OFF while BCON is OFF. Do not inspect or assess radiation state. | |
| 3. Inspect logs and dashboard subsystem state. | Connection/error evidence names Laser Monitor and never claims radiation was tested or controlled. | |
| 4. Close/reopen dashboard normally. | Old worker/port closes before new instance starts; beams-on stays physically OFF after reachable shutdown. | |

### INTER-9.2 - Live BCON beams-on mapping to Laser Monitor

**Description:** Prove beams-on follows live any-channel BCON register state,
not software arm, staged configuration, or queued command.

**Initial conditions:** `SAFE_1200`; physical Arm ON; BCON/Laser Monitor healthy;
radiation excluded.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Software-arm BCON and configure A/B/C while outputs remain OFF. | Laser beams-on remains OFF; arm/configuration alone never lights it. | |
| 2. Start A DC then stop A; repeat for B and C separately. | Each live active channel causes beams-on ON after BCON register update; it returns OFF after no-active-channel state. | |
| 3. Use long visible PULSE TRAIN, then let it finish. | Beams-on follows observed active period and clears after live BCON state clears; unobservable short pulse is not falsely claimed tested. | |
| 4. Start A and B together, then stop one and both. | Beams-on stays ON while any channel is active and turns OFF only after last live channel is OFF. | |
| 5. Compare BCON LED/LCD/register, Machine Status Beams On, Laser LED, and logs. | Sources report same live transition order; radiation remains ignored. | |

### INTER-9.3 - Interlock, all-off, and stale-beam indication

**Description:** Find Laser stale beams-on behavior during BCON safety events
and communication loss.

**Initial conditions:** BCON A DC active; Laser Monitor healthy; watchdog 1500
ms; no pulser cable attached.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Turn physical Arm Beams OFF while A active. | BCON forces A low; Laser beams-on clears after corresponding live BCON state transition; recovery does not relight it. | |
| 2. Restart A with fresh command, then use Disable All and combined E-stop separately. | Confirmed BCON all-off drives beams-on OFF; E-stop scope is not mislabeled radiation/HV control. | |
| 3. Restart A, remove BCON serial cable, and timestamp watchdog expiry, Laser LED, and auto-disconnect. | Beams-on must not remain asserted after output is known OFF. If it remains until host auto-disconnect clears stale BCON activity, record defect with duration. | |
| 4. Reconnect BCON/Laser Monitor, obtain fresh all-off, and issue no new Beam command. | Beams-on remains OFF; old beam activity does not replay. | |

### INTER-9.4 - Firmware response, USB, and reconnect failures

**Description:** Exercise permitted Laser serial/firmware fault paths without
changing radiation or Knob Box data.

**Initial conditions:** BCON OFF; approved Laser firmware/protocol fixture can
provide missing, malformed, delayed, and unexpected responses.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Return missing, malformed, unexpected, non-ASCII, and delayed responses separately. | Driver records protocol/transaction failure, marks connection unhealthy, and dashboard callbacks stay responsive. | |
| 2. Restore normal OK response. | Driver reconnects with documented 0.5-5 s backoff, resumes polling, and resynchronizes beams-on without BCON state change. | |
| 3. Unplug/reinsert Laser USB while dashboard runs. | Disconnect/reconnect is explicit; BCON/CCS/PMON/SIC/VTRX remain responsive and no port is cross-assigned. | |
| 4. Hold serial fault over 4 s while BCON is active on isolated output. | Firmware/dashboard watchdog behavior reaches documented beams-on state; physical LED/driver state are recorded without radiation claim. | |
| 5. Restore serial path and confirmed BCON all-off. | Laser beams-on ends OFF and one recovery worker/port remains. | |


### INTER-9.5 - Callback failure, missing driver, and shutdown

**Description:** Verify dashboard Laser wiring faults do not create false success
or affect BCON safety controls.

**Initial conditions:** Approved reversible dependency/callback fault injection;
BCON outputs OFF; radiation remains out of scope.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Launch with missing/invalid Laser COM or unavailable serial dependency. | Startup reports Laser unavailable; BCON/other subsystems remain safe without false connected state. | |
| 2. Inject absent/failing Beam Pulse activity callback wiring. | Missing wiring is logged/visible; Beam output remains truthful and no Laser success is inferred. | |
| 3. Make Laser callback raise during live BCON transition, then recover it. | BCON is unaffected; failure is attributable and next valid transition/resynchronization restores current beams-on state. | |
| 4. Confirm normal quit while BCON A is active, then abnormal dashboard termination in separate run. | Normal quit attempts BCON all-off and Laser beams=0; abnormal loss relies on measured BCON/Laser watchdogs with no software all-off assumed. | |
| 5. Restore normal COM/driver/wiring and relaunch. | Exactly one Laser worker/callback starts; beams-on is OFF until live BCON activity. | |


## Suite 10 - Startup, configuration, logging, and general dashboard behavior

**Description:** Exercise retained startup/configuration and UI/logging paths
without modifying Knob Box/Beam Energy or using Beam Pulse CSV actions.

**Initial conditions:** Back up `com_ports.json`, `main_control_config.json`,
`process_monitor_config.json`, `pane_state.json`, and copied test files.

### INTER-10.1 - Selected configuration startup and mid-session failures

**Description:** Verify relevant files degrade safely and recover without
changing excluded subsystem state.

**Initial conditions:** Dashboard closed; outputs OFF; copied reversible file
fixtures available.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Launch with missing, malformed, wrong-shaped, and read-denied COM configuration fixtures. | Startup selector remains recoverable; no subsystem opens early and invalid value is not plausible COM port. | |
| 2. Repeat for Main Control, PMON, and pane-state configuration files. | Only affected settings/layout/defaults degrade; safety controls remain reachable and no output starts. | |
| 3. Make affected file unwritable/locked, perform allowed Set/Save action, and inspect result. | Persistence error is explicit; in-memory truth is not mislabeled saved and dashboard stays responsive. | |
| 4. Delete/corrupt relevant file during session, then relaunch after restoration. | Current policy stays stable until Set/restart boundary; restored valid file reloads without stale output. | |

### INTER-10.2 - COM selection and live reassignment

**Description:** Verify startup/runtime COM handling cannot cross-route BCON,
CCS, VTRX, PMON, SIC, or Laser Monitor.

**Initial conditions:** Outputs OFF; valid, stale, busy, and wrong-endpoint
fixtures available. Do not change Knob Box port.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. At startup, submit blank, dummy, duplicate, stale, and valid values for retained ports. | Invalid selection is recoverable/safe; valid unique mapping starts one correct driver. | |
| 2. At idle, open runtime COM configuration and Apply blank, whitespace, stale, duplicate, and valid values to retained selectors. | Invalid Apply does not replace proven live driver; valid/restart-only result is explicit. | |
| 3. Apply changed BCON/CCS/VTRX/PMON/SIC/Laser port during permitted active/monitored state separately. | Reassignment is safely blocked, needs all-off, or leaves explicit uncertainty; no active dummy load/BCON output is abandoned. | |
| 4. Restore unique approved mappings and fresh data. | Recovery needs current source data and never replays Beam, CCS, or Laser activity. | |

### INTER-10.3 - Messages, recording, export, layout, and semantics

**Description:** Exercise common user actions and ensure events retain source,
severity, chronology, and wording.

**Initial conditions:** Safe baseline log and one each permitted BCON, CCS,
VTRX-stale, PMON, SIC, and Laser event are available.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Select allowed UI/file log levels, toggle recording OFF/ON, and perform one permitted action in each state. | UI/file recording is explicit; safety actions remain truthful when recording is off. | |
| 2. Clear Messages, then trigger permitted event and inspect durable log. | Clear affects view only; durable evidence preserves source/time/severity per recording state. | |
| 3. Export Messages to copied writable path, cancel, then use unwritable path. | Valid export is complete; cancel inert; write failure explicit with no dashboard freeze. | |
| 4. Save/restore layout, run approved inert setup-script fixtures, and launch post-processor success/failure fixtures. | UI remains usable; script/post-processor failure is contained and cannot manipulate hardware. | |
| 5. Compare wording for VTRX equality/stale, BCON watchdog/interlock, CCS uncertainty, SIC fault, Machine Status color, and Laser beams-on. | Text identifies actual source/semantics and never calls status color, queued write, or Laser state confirmed BCON/CCS shutdown. | |

### INTER-10.4 - Permitted startup ordering and unavailable sources

**Description:** Verify safe degraded startup/recovery with retained source-order
variations.

**Initial conditions:** Outputs OFF; `SAFE_1200` selected for iterations needing
VTRX-safe baseline.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Launch with BCON, CCS, VTRX, PMON, SIC, and Laser Monitor absent in separate/combined iterations. | Dashboard is operable in explicit degraded state; unavailable sources are not healthy and guarded output blocks where required. | |
| 2. Restore BCON/CCS/PMON/SIC/Laser in varied permitted orders. | Each recovers from fresh source state; no duplicate worker, cross-port mapping, or output replay occurs. | |
| 3. Restore VTRX only as fixed connected 1200 mbar or leave disconnected. | VTRX recovery/stale follows profile; no packet/pressure simulation is used. | |
| 4. Inspect passive Knob-dependent Machine Status stages throughout. | They remain read-only observations; no control, simulation, or port action changes them. | |

## Suite 11 - Shutdown, abnormal recovery, and restoration

**Description:** Verify normal cleanup, abnormal loss, physical uncertainty, and
final repository/fixture restoration for retained subsystems.

**Initial conditions:** Record source profile, config backups, COM mappings,
physical connections, and fixture revisions. Keep emergency CCS power removal
available.

### INTER-11.1 - Normal quit with active permitted work

**Description:** Ensure orderly shutdown handles manual BCON, CCS, VTRX, PMON,
SIC, Machine Status, and Laser Monitor without high-voltage action.

**Initial conditions:** In separate/combined runs: BCON manual output, CCS
Immediate/Ramp dummy-load output, VTRX stale grace timer, and Laser beams-on
are active.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Confirm normal quit from each supported entry point. | Machine Status stops first; BCON all-off/CCS OFF attempt before close; PMON/SIC/VTRX/Laser workers/ports close safely. | |
| 2. Measure quit confirmation to process exit. | Cleanup completes within 10 s or records exact blocked dependency; no callback accesses destroyed widgets. | |
| 3. Inspect BCON LEDs, CCS dummy loads, and Laser beams-on after exit. | Reachable outputs are physically OFF; unknown CCS is not safe; no high-voltage/Knob action occurred. | |
| 4. Relaunch with safe fixtures. | One clean worker/callback set starts with BCON disarmed, CCS OFF, and Laser beams-on OFF. | |

### INTER-11.2 - Abnormal dashboard termination and physical fallback

**Description:** Establish safety truth when normal dashboard cleanup does not
run.

**Initial conditions:** BCON A DC active on disconnected output; CCS A active
on dummy load; watchdog 1500 ms; Laser Monitor connected.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Terminate dashboard through approved fault injection without quit cleanup. | No software BCON all-off/CCS OFF acknowledgement is assumed. | |
| 2. Observe BCON for at least two watchdog periods. | Firmware watchdog forces BCON output low; time is measured from last valid heartbeat. | |
| 3. Observe CCS and Laser through documented fallback intervals. | CCS may remain energized and is active/unknown; Laser beams-on follows firmware communication watchdog separately. | |
| 4. Remove CCS physical power and verify zero output. | Physical mitigation establishes safe state and is not dashboard acknowledgement. | |
| 5. Restore communications and relaunch. | Fresh state is reconciled before new output request; no stale state replays. | |

### INTER-11.3 - Repeated lifecycle and cross-fault stress

**Description:** Detect leaked workers, stale latches, duplicate callbacks, and
progressively slow cleanup in retained scope.

**Initial conditions:** Safe isolated fixture; choose at least 10 launches and
30 permitted action cycles.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Launch, connect retained sources, exercise BCON and CCS ON/OFF, then quit for at least 10 iterations. | Each iteration begins/ends cleanly; no port busy and worker/callback/log counts do not grow. | |
| 2. Repeat ARM/disarm, Activate/Disable, CCS ramp/stop, VTRX disconnect/reconnect, PMON/SIC fault/recovery, and Laser USB reconnect for at least 30 cycles. | State converges each cycle with no stale latch/queue, channel cross-route, duplicated Laser send, or slowdown. | |
| 3. Review lifecycle logs and cleanup durations. | One intended poller/reconnect/timer family per subsystem remains; cleanup stays at or below twice median of first three clean cycles. | |

### INTER-11.4 - Final restoration and evidence review

**Description:** Return repository and physical fixtures to approved state and
preserve reproducible evidence.

**Initial conditions:** All executable cases complete or deferred with safety/
fixture reason; dashboard closed.

| Test steps | Expected results | Notes |
|---|---|---|
| 1. Restore default VTRX/Machine Status source constants and inspect source diff. | Defaults are exact; no temporary threshold profile remains. | |
| 2. Restore backed-up configs, LUT, pane state, copied script, and file permissions. | Production files/permissions are restored; unrelated user data is untouched. | |
| 3. Restore COM mappings, PMON/SIC inputs, VTRX connection, BCON watchdog, Arm Beams, Laser firmware/USB, CCS protections, and output OFF state. | Bench is post-test: BCON LEDs dark, CCS dummy loads zero, Laser beams-on OFF, HV de-energized. | |
| 4. Perform final nominal launch without enabling output. | Restored config/mappings load; no stale timer, fault, worker, profile, or test fixture alters state. | |
| 5. Export final Messages and preserve logs, source diffs, fixture observations, and defects. | Evidence ties failed/deferred cases to revision, time, expected/actual result, and recovery. | |

## Completion Criteria

- Every case is Passed, Failed with defect identifier, or Deferred with a
  safety/fixture limitation and owner.
- No BCON CSV control, Knob Box control/simulation, Beam Energy control, +20 kV
  E-stop test, VTRX pressure/packet simulation, or Laser radiation transition
  is performed.
- VTRX tests use only connected fixed 1200 mbar, disconnection/staleness, and
  documented pre-launch source thresholds.
- Every Machine Status stage is evaluated from permitted source; stages
  depending on passive Knob Box state are observed without manipulation.
- Every claimed BCON/CCS shutdown has hardware/readback and physical evidence;
  unknown state never counts as pass.
- Defaults, files, COM mappings, fixtures, source constants, BCON watchdog,
  CCS protections, and physical outputs are restored and verified.
