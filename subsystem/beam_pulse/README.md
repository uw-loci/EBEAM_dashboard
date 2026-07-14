# Beam Pulse Subsystem

`BeamPulseSubsystem` is the dashboard-facing control layer for the BCON beam
pulser. It owns the Beam Pulse subpanel UI, BCON driver connection, channel
configuration validation, dashboard-software-interlock activation, CSV sequence playback, and the
software checks that run before output-producing BCON commands.

Main Control is the operator control surface for most beam actions. Beam Pulse
keeps the hardware-facing state and reports live status back to Main Control.

## Top-Level Flow

```mermaid
flowchart TD
    Main["main.py<br/>COM-port selection"] --> Dashboard["dashboard.py<br/>EBEAMSystemDashboard"]

    Dashboard -->|"creates Beam Pulse frame<br/>port key: BeamPulse"| BeamPulse["BeamPulseSubsystem<br/>beam_pulse.py"]
    Dashboard -->|"creates and wires"| MainControl["MainControlPanel<br/>subsystem/main_control"]
    Dashboard --> BeamEnergy["Beam Energy"]
    Dashboard --> Cathode["Cathode Heating"]

    MainControl -->|"Arm/Disarm, Beam A/B/C,<br/>Activate Enabled Beams / Disable All Beams, Beams E-stop"| BeamPulse
    BeamPulse -->|"channel output status,<br/>armed state, action feedback"| MainControl
    MainControl -->|"emission limit and software-interlock providers"| BeamPulse
    Cathode -->|"predicted emission currents"| MainControl
    BeamPulse -->|"manual disconnect check,<br/>disconnect notification"| MainControl
    MainControl -->|"BCON-connected provider,<br/>guard setting, turn_off_all_beams()"| Cathode

    BeamEnergy -->|"+20kV current E-stop callback"| MainControl
    MainControl -->|"turn_off_all_beams()"| Cathode

    BeamPulse -->|"high-level channel activation/stop calls"| Driver["BCONDriver<br/>instrumentctl/BCON"]
    Driver <-->|"raw pyserial Modbus RTU<br/>FC03 reads, FC06 writes"| Firmware["BCON firmware"]
    Driver -->|"connected / regs / wrote / error / command_result"| Queue["Beam Pulse UI queue"]
    Queue -->|"Tk after(), 200 ms"| BeamPulse
```

## UI Structure

Beam Pulse itself has a compact status bar and two tabs.

- Status bar: BCON connection indicator, hardware interlock/watchdog text,
  watchdog setting entry, event log line, and Connect/Reconnect/Disconnect.
- `Manual Control`: one card per channel A/B/C with mode, pulse duration,
  pulse count, live status, and remaining pulse count.
- `CSV Sequence`: loaded file name, progress, Load CSV, Save Template, Run,
  Stop, and a preview of parsed steps.

Main Control is a separate subpanel, but it is the normal place operators start
beam actions. It hosts ARM BEAMS, BEAMS E-STOP, Beam A/B/C ON/OFF buttons,
dashboard-only Beam A/B/C software interlocks, Activate Enabled Beams / Disable
All Beams, and the four-line beam status/action display. Each Beam Pulse Manual
channel card also has a `PVX Enable Toggle` button for the hardware one-shot
toggle command.

## Code Structure

- `subsystem/beam_pulse/beam_pulse.py`: Tk UI, BCON lifecycle, channel config
  validation, arming state, emission-limit checks, CSV parsing/playback, and
  callback registration for Main Control.
- `instrumentctl/BCON/bcon_driver.py`: register-level Modbus RTU driver. It owns
  the serial port, write queue, register cache, background poll thread, staged
  channel mode writes, command writes, and firmware status reads.
- `subsystem/main_control/main_control.py`: calls Beam Pulse APIs for operator
  actions and receives Beam Pulse callbacks for live status/action displays.

## BCON Interface

BCON communication is register-based Modbus RTU over serial. Beam Pulse creates
a `BCONDriver` when a port is configured; otherwise the subpanel can still be
constructed but cannot connect or send commands.

| Registers | Purpose |
| --- | --- |
| `0` | Watchdog timeout in ms |
| `1` | Firmware telemetry interval in ms |
| `2` | Command register, including all-off and apply-staged-modes |
| `10/20/30 + offsets` | Channel A/B/C requested mode, pulse ms, count, and PVX enable-toggle command (`+3`) |
| `100+` | System state and diagnostics |
| `103` | Hardware interlock OK |
| `104` | Watchdog OK |
| `110/120/130 + offsets` | Channel A/B/C actual mode, pulse ms, count, remaining, enable-toggle busy (`+4`), power, overcurrent, gated, output level |

The driver sends register snapshots to `BeamPulseSubsystem` through `_ui_queue`
as `("regs", regs)` messages. The subsystem consumes the queue on the Tk main
thread every 200 ms, updates widgets, and forwards live state to Main Control
callbacks.

Driver warning/error logs are also routed through the same UI queue, so BCON
worker-thread diagnostics are displayed through the dashboard logging path
instead of being printed directly from the worker.

On connect, the subsystem applies its preferred defaults:

- Watchdog: `BCONDriver.DEFAULT_WATCHDOG_MS` currently 1500 ms.
- Telemetry: `BCONDriver.DEFAULT_TELEMETRY_MS` currently 500 ms.

The driver uses a short serial read timeout and disconnects itself after a
bounded number of consecutive polling failures. When that happens, Beam Pulse
clears its local armed/output state, updates its UI, and emits
the registered disconnect callback.

## Channel Modes

The current mode set mirrors `BCONMode`:

| Mode | Meaning | Parameters |
| --- | --- | --- |
| `OFF` | Channel output off | Duration/count ignored |
| `DC` | Continuous output while active | Duration/count ignored |
| `PULSE` | Single pulse | Duration must be 1-60000 ms; count is forced to 1 |
| `PULSE_TRAIN` | Multiple pulses | Duration must be 1-60000 ms; count must be 2-10000 |

The UI only allows whole-number text entry for duration/count and validates
again before sending commands. The driver also enforces firmware-facing limits
for pulse duration and count.

## Safety And Guard Rails

There are four layers of safety/status behavior to keep distinct:

- Beam Pulse software arming: `arm_beams()` allows output-producing actions;
  `disarm_beams()` stops CSV playback, commands BCON all-off, and only after
  confirmed all-off clears local output state and disables armed-gated controls.
- BCON firmware safety: hardware interlock and watchdog state remain enforced by
  BCON firmware and are reported through registers.
- Emission-current limit: when enabled, Beam Pulse blocks non-OFF Beam ON,
  Activate Enabled Beams, and CSV step commands when any projected cathode
  prediction is unknown/invalid, or when the projected predicted emission
  current is at or above the Main Control limit. When disabled, Beam Pulse skips
  both prediction validation and the threshold comparison.
- BCON/CCS disconnect guard: Beam Pulse reports BCON disconnects to Main Control. Main Control then
  decides whether Cathode Heating should disable or block CCS output.

### Main Control Arm Beams Button

The Main Control `ARM BEAMS` / `BEAMS ARMED` control is the software
permission switch for Beam Pulse actions. Arming does NOT start output, enable
a channel, turn on cathode heating, or send a hardware arm command to BCON. It
only allows armed-gated Dashboard controls to be used.

When BCON is connected and beams are armed, the operator can:

- Enable a dashboard software interlock for a Beam A/B/C output button.
- Turn an individually software-enabled Beam A/B/C output on from its Dashboard
  button.
- Use `Activate Enabled Beams`, which filters by Main Control's dashboard
  software-interlock provider.
- Run a loaded CSV sequence, when BCON is connected.

Press the same button again while beams are armed to disarm Beam Pulse. Disarm
stops any running CSV sequence, commands all BCON beam channels off when a BCON
driver is available, disables armed-gated controls, and resets Dashboard beam
buttons to OFF. It does not turn off cathode heater power-supply outputs; use
`BEAMS E-STOP` when cathode heater outputs must also be shut off.

### BCON Disconnect Integration

Beam Pulse exposes two disconnect-related hooks for Main Control:

- A manual-disconnect callback, called before an operator-requested BCON
  disconnect proceeds.
- A disconnect callback, called after Beam Pulse observes that BCON is no longer
  connected.

This keeps the BCON hardware lifecycle inside Beam Pulse while leaving the
cross-subsystem safety decision in Main Control. In the current dashboard
wiring, Main Control uses those hooks to warn the operator before a manual BCON
disconnect would shut down active CCS outputs, and to call Cathode Heating's
`turn_off_all_beams()` path when BCON is lost unexpectedly and the guard is
enabled.

## Main Control API

Main Control calls these Beam Pulse methods:

| Main Control action | Beam Pulse API |
| --- | --- |
| Arm/disarm | `arm_beams()`, `disarm_beams()`, `get_beams_armed_status()` |
| Beams E-stop | `stop_all_channels()`, then `disarm_beams()` |
| Beam A/B/C ON | `send_channel_config(channel_index)` |
| Beam A/B/C OFF | `send_channel_off(channel_index)` |
| Activate Enabled Beams / Disable All Beams | `activate_enabled_beams()`, `disable_all_beams()` |

The Beam Pulse Manual tab invokes `request_pvx_enable_toggle(channel_index)`
directly from each channel's `PVX Enable Toggle` button.

Main Control registers these callbacks/providers on Beam Pulse:

| Registration method | Callback shape | Purpose |
| --- | --- | --- |
| `set_channel_status_callback(callback)` | `callback(ch, mode_code, remaining, config)` | live Beam A/B/C output display |
| `set_activation_interlock_provider(provider)` | `provider() -> iterable[bool]` | Main Control's dashboard-only A/B/C interlocks used by `activate_enabled_beams()` |
| `set_armed_status_callback(callback)` | `callback(armed)` | mirror software armed state |
| `set_action_feedback_callback(callback)` | `callback(event_type, message, outcome, configs)` | action line and firmware acknowledgement display |
| `set_emission_limit_providers(limit, currents)` | callables | emission-limit guard data; `currents()` returns A/B/C values as non-negative finite mA floats or `None` for unknown |
| `set_vtrx_pressure_guard_providers(enabled, pressure, limit, fresh)` | callables | VTRX high-pressure/freshness guard data |
| `set_manual_disconnect_callback(callback)` | `callback() -> bool` | ask Main Control whether a user-requested BCON disconnect may continue |
| `set_disconnect_callback(callback)` | `callback()` | notify Main Control after BCON disconnects |

## Manual And Enabled-Beam Operation

`get_channel_config(ch)` reads the next intended Manual Control config for one
channel. Live BCON status is shown in the status text labels in the channel cards.
When register status shows a channel running, Beam Pulse locks that channel's
mode/duration/count controls until the channel is no longer running. DC mode is
treated as running even though it has no remaining pulse countdown.

`send_channel_config(ch)`:

1. Requires beams to be armed and BCON to be connected.
2. Validates mode, duration, and count.
3. Runs the VTRX pressure and emission-current checks for non-OFF output.
4. Calls `bcon_driver.set_channel_mode(ch + 1, mode, duration_ms, count)`.
5. Updates local output state; register polling remains the hardware truth.

`send_channel_off(ch)` sends OFF command to BCON and does not require arming.

`Activate Enabled Beams` reads all three Manual Control configurations, filters out
channels whose Main Control dashboard software interlock is disabled, blocks
non-OFF output when VTRX pressure is above Main Control's pressure limit or
projected emission current is at or above the configured limit, then calls
`bcon_driver.sync_start(configs)`. The driver stages pulse parameters and
requested modes, then commits them together with the firmware apply command.
The interlock provider is fail-closed: an absent or false entry for a channel
means that channel is skipped rather than started.

`PVX Enable Toggle` writes `1` once to the per-channel command register:
R13 for Beam A, R23 for Beam B, or R33 for Beam C. The firmware self-clears the
register, treats `0` as a no-op, and produces one 100 ms PVX pulse when it
accepts the request. R114/R124/R134 report only whether the corresponding pulse
is currently busy. A second request
while the latest busy status is `1` is rejected by the dashboard before FC06 is
sent. Firmware still protects a race by acknowledging FC06 and recording
`LAST_ERROR=11`.

`disable_all_beams()` calls confirmed `bcon_driver.stop_all()` and clears local
output state only after the BCON all-off command is confirmed. The driver
invalidates pre-existing queued writes during this all-off path, so a Beam
ON/apply write that was queued or already dequeued before the stop request
cannot run after the confirmed `ALL_OFF`.

## CSV Sequences

CSV controls are hosted inside the Beam Pulse `CSV Sequence` tab above the
loaded-step preview. The tab shows the loaded file, progress, and parsed preview.

Accepted columns:

```csv
step,ch,mode,duration_ms,count,dwell_ms
```

Rules:

- Blank lines and lines beginning with `#` are ignored.
- A header line starting with `step` is ignored.
- Rows with the same `step` value are launched together.
- `ch` is `1`, `2`, `3`, or `ALL`.
- `mode` is `OFF`, `DC`, `PULSE`, or `PULSE_TRAIN`.
- Empty `duration_ms` defaults to `100`; empty `count` defaults to `1`.
- `dwell_ms` is the wait after the step before the next step. When multiple
  rows share a step, the last parsed dwell value for that step is used.
- `PULSE_TRAIN` requires `count >= 2`.

Example:

```csv
step,ch,mode,duration_ms,count,dwell_ms
1,1,PULSE,100,1,0
1,2,PULSE,200,1,500
2,ALL,OFF,,,250
3,3,PULSE_TRAIN,50,10,1000
```

Running a sequence requires:

- A loaded CSV file.
- Beams armed.
- Connected BCON driver.
- No currently running sequence worker.

The sequence runner uses a background thread. Each step calls
the Beam Pulse emission-limit check before `bcon_driver.sync_start(configs)`,
then sleeps for the step dwell while checking the stop event. Stop, disarm,
disconnect, and host shutdown all request the worker to stop.

## Threading And Lifecycle

The subsystem keeps GUI work on the Tk main thread and hardware I/O off it:

- `BCONDriver` owns a background poll thread and serial lock.
- `BeamPulseSubsystem` consumes driver messages from `_ui_queue` with
  `parent_frame.after(200, ...)`.
- A CSV sequence uses one background worker thread.
- Auto-connect runs in a daemon thread when a port is supplied.
- The owning Tk toplevel is bound to `<Destroy>` so closing the Dashboard calls
  the same shutdown path as `close_com_ports()`.

Cleanup paths:

- `disconnect()` stops sequence playback, clears local armed/beam status, and
  disconnects the driver.
- `close_com_ports()` is the Dashboard cleanup hook.
- `cancel_updates()` cancels Beam Pulse `after()` callbacks.
- `safe_shutdown(reason)` disarms, turns all beams off, and logs the shutdown.

## Dependencies

- Python standard library: `tkinter`, `threading`, `queue`, `time`, `pathlib`,
  `datetime`, `os`, `sys`.
- Project modules: `instrumentctl.BCON`, `utils.LogLevel`.
- Serial dependency: `pyserial`.
- Hardware: BCON firmware exposing the Modbus RTU register map expected by
  `instrumentctl/BCON/bcon_driver.py`.

## Implementation Notes

- Python API channel indexes are usually 0-based (`0`, `1`, `2` for A/B/C).
  `BCONDriver` channel numbers are 1-based (`1`, `2`, `3`).
- The subsystem creates `presets/` and `sequences/` in the current working
  directory. `sequences/` is used as the default file-dialog location.
- Live hardware mode is displayed in each channel status label but is not pushed
  back into the mode combobox. This preserves the user's intended next command.
- Manual controls are locked while a channel is running, based on live status
  registers. DC is treated as running even though remaining count is zero.
- Most command writes are queued through the driver poll thread. PVX enable-toggle
  requests use an immediate FC06 write; its acknowledgement confirms transport,
  not whether the firmware accepted the toggle. BCON all-off uses the immediate
  confirmed command path.
- The BCON driver tags queued writes with a write epoch. `stop_all()` advances
  that epoch under the serial lock and clears pending queue entries, causing
  stale pre-all-off poll-thread writes to be dropped before they reach the
  serial port.
