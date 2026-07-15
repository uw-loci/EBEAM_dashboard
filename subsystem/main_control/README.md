# Main Control Subsystem

## Overview

`main_control.py` implements the Main Control dashboard subpanel. It is the
operator-facing coordination layer for beam actions, subsystem configuration,
and the high-level beam status display.

Main Control does not own BCON serial communication or cathode power-supply
control directly. Instead, it calls the other subsystem APIs and mirrors their
state back into a compact operator panel.

At runtime it is responsible for:

- Building the Main Control `Main` and `Config` tabs.
- Providing ARM BEAMS, BEAMS E-STOP, Beam A/B/C, Beam A/B/C software interlock,
  Activate Enabled Beams, and Disable All Beams controls.
- Displaying Beam A/B/C output status and the result of the latest beam action.
- Saving dashboard layout and updating COM-port assignments through Dashboard
  callbacks.
- Owning the configurable total predicted emission-current limit value that Beam
  Pulse uses before output-producing commands.
- Coordinating Beam Pulse, Beam Energy, and Cathode Heating safety behavior.

## UI Structure

Main Control is a two-tab subpanel.

### `Main` Tab

- Setup script dropdown.
- Beam A/B/C ON/OFF buttons.
- Beam A/B/C Interlock Disabled/Enabled buttons, which are dashboard-only software
  interlocks. They do not read or write BCON enable-toggle registers.
- Activate Enabled Beams and Disable All Beams buttons.
- ARM BEAMS / BEAMS ARMED toggle.
- Four-line beam status/action display:
  - Lines 1-3 show Beam A/B/C output state only.
  - Line 4 shows the latest action result or failure reason.
- BEAMS E-STOP button.

### `Config` Tab

- COM-port configuration dropdowns.
- Save Layout button.
- Launch Log Post-processor button.
- UI log-level and file log-level dropdowns.
- Disable CCS Output on BCON Disconnect toggle.
- Disable Beams if pressure exceeds 10^-5 mbar toggle.
- Disable CCS Output after the configured grace period above 10^-5 mbar
  control.
- Total Max Emission Current control.
- 20kV Bertan Current Limit for E-Stop Trigger control.
- F1 keyboard shortcut hint.

## Code Structure

- `MainControlPanel.__init__()` stores dashboard callbacks, loads the saved
  emission-current limit, initializes local status state, and builds the UI.
- `create_main_control_notebook()` builds the `Main` and `Config` tabs.
- `create_beam_output_status_panel()` builds the Beam A/B/C output lines and
  latest-action line.
- `wire_beam_pulse()` registers Main Control as the callback target for Beam
  Pulse output/action status updates, gives Beam Pulse the emission-limit, VTRX
  pressure, and dashboard-software-interlock providers, and wires BCON
  disconnect notifications into Cathode Heating.
- `wire_beam_energy()` registers the Beam Energy +20 kV current E-stop callback.
- `wire_vtrx()` registers the VTRX pressure callback used by the high-pressure
  beam-disable guard.
- `create_com_port_frame()`, `apply_com_port_changes()`, and related helpers
  manage COM-port selection through the parent Dashboard.
- `set_total_max_emission_current_limit()` validates and persists the emission
  limit through `usr/main_control_config.py`.
- `set_vtrx_ccs_disable_grace_period()` validates and persists the VTRX
  high-pressure CCS shutdown grace period through `usr/main_control_config.py`.
- `set_beams_estop_current_limit()` validates the operator-entered +20 kV
  E-stop current limit, persists it through `usr/main_control_config.py`, and
  applies the runtime value to Beam Energy.
- `toggle_disable_ccs_output_on_bcon_disconnect()` updates the runtime
  BCON/CCS guard setting and propagates it to Cathode Heating.

## Major Action Handlers

| Method | Purpose |
| --- | --- |
| `handle_arm_beams()` | Toggles Beam Pulse software arming and updates Main Control button state. |
| `handle_beams_off()` | Makes two redundant BCON all-off attempts, turns off cathode heating outputs, and defers beam/disarmed UI changes until the post-ack BCON poll. |
| `toggle_individual_beam_with_status()` | Turns one Beam A/B/C output on or off using the current Beam Pulse manual channel configuration. |
| `_toggle_beam_software_interlock()` | Toggles one dashboard-only Beam A/B/C interlock. If its output is active, it queues that channel OFF and waits for the next BCON status poll to confirm it. |
| `handle_activate_enabled_beams()` | Starts locally software-enabled/manual-configured Beam Pulse channels together. |
| `handle_disable_all_beams()` | Requests BCON all-off, then clears dashboard software interlocks only after the post-ack poll confirms all channels OFF. |
| `_on_channel_status_update()` | Mirrors live BCON channel output state into Beam A/B/C buttons and status lines. |
| `_handle_action_feedback()` | Converts Beam Pulse action callbacks into the latest-action status line. |
| `_handle_bcon_disconnected()` | Terminates any pending BCON operation as indeterminate, then disables CCS output through Cathode Heating when the guard is enabled. |
| `_handle_vtrx_pressure_update()` | Handles each valid VTRX pressure reading, including Beam Pulse high-pressure disable and CCS grace-period shutdown checks. |

## Subsystem Relationships

### Beam Pulse

Beam Pulse owns the BCON driver, manual channel configurations, CSV sequence
playback, firmware register polling, and output-producing command checks.

Main Control calls Beam Pulse for operator actions:

- `arm_beams()` / `disarm_beams()`
- `get_beams_armed_status()`
- `send_channel_config(channel_index)`
- `send_channel_off(channel_index)`
- `activate_enabled_beams()`
- `disable_all_beams()`
- `stop_all_channels()`

Beam Pulse calls back into Main Control with:

- Live channel output status.
- Software armed status.
- Action feedback and firmware acknowledgement text.
- Manual-disconnect confirmation requests.
- BCON disconnect notifications.

### Cathode Heating

Main Control uses Cathode Heating in three ways:

- It exposes `get_predicted_emission_currents_ma()` to Beam Pulse so Beam Pulse
  can block output commands, when the emission-current limit is enabled, if
  projected cathode emission predictions are unknown/invalid or would exceed the
  configured total predicted emission-current limit.
- It exposes the VTRX pressure guard setting, threshold, and latest valid VTRX
  pressure to Beam Pulse so output commands are blocked while pressure is above
  1e-5 mbar.
- During BEAMS E-STOP, Main Control calls `turn_off_all_beams()` to turn off the
  cathode heating power-supply outputs.
- When the BCON-disconnect guard is enabled, Main Control also calls
  `turn_off_all_beams()` if BCON disconnects while any cathode output is active.
  The same setting is passed to Cathode Heating so it can block new CCS output
  enables while BCON is disconnected.
- When VTRX pressure rises above 1e-5 mbar or becomes stale while CCS output is
  active, Main Control starts a CCS shutdown grace-period timer. While the timer
  is active, Cathode Heating blocks new CCS output enables; if pressure does not
  recover before the timer elapses, Main Control calls `turn_off_all_beams()`.

### Beam Energy

Beam Energy owns Knob Box monitoring and warning thresholds. Main Control owns
the 20kV Bertan Current Limit for E-Stop Trigger setting: it validates and
persists the entry, sends the numeric value to Beam Energy, and registers a
callback with Beam Energy through `set_beams_estop_callback()`. Beam Energy uses
the Main Control-provided value during each Knob Box poll; when +20 kV current
reaches that value, it calls Main Control's BEAMS E-STOP path.

### VTRX

VTRX reports each valid pressure reading to Main Control. When the high-pressure
beam-disable guard is enabled, Main Control calls Beam Pulse `disable_all_beams()`
on the first pressure reading above 1e-5 mbar and waits for pressure to recover
to 1e-5 mbar or below before it can trigger again.

Main Control also uses VTRX pressure to protect CCS output. Stale pressure or
pressure above 1e-5 mbar starts the configured CCS grace-period timer only when
CCS output is active. Subsequent unsafe updates log countdown warnings and shut
off active CCS output after the grace period elapses. Recovery to 1e-5 mbar or
below, or CCS output becoming inactive, clears the timer.

### Dashboard

Dashboard creates the Main Control panel, then assigns the shared subsystem
dictionary and wires VTRX, Beam Pulse, and Beam Energy after those subsystems are
created. Main Control also delegates layout saving and COM-port updates back to
Dashboard callbacks.

## Important Behavior Notes

- ARM BEAMS is a Beam Pulse software gate. It does not start output, enable a
  BCON channel, or turn on cathode heating.
- Beam A/B/C ON reads the current mode, duration, and count from the Beam Pulse
  Manual Control tab.
- Beam A/B/C buttons are only enabled when Beam Pulse is armed and the matching
  dashboard software interlock is enabled. These interlocks have no BCON
  firmware readback or write path.
- Dashboard beam actions carry a token through the BCON queue. Only one normal
  action waits at a time; additional clicks remain possible but log a pending
  warning. Sending has a 1.5 s deadline; once the terminal command is sent,
  firmware acknowledgement plus the next full BCON poll have a 1 s deadline.
  A normal-action timeout releases the normal-action lock, logs the token,
  action, channels, elapsed time, and unknown firmware outcome, and leaves
  hardware presentation to the next poll. Safety-action failures/timeouts are
  logged as CRITICAL.
- A BCON disconnect immediately terminates a pending operation as indeterminate,
  logs its token/action/channels, and ignores any later result for that operation.
- Beam A/B/C ON/OFF text, color, and output status lines change only from a
  complete BCON register poll, never directly from a command result.
- Activate Enabled Beams is delegated to Beam Pulse, which filters by those
  dashboard software interlocks and performs output checks before sending the
  synchronized start to BCON.
- Disable All Beams sends BCON `COMMAND=1` to stop output modes/gates. It does
  not issue a PVX enable-toggle command and does not disarm BEAMS ARMED. Main
  Control clears all dashboard interlocks only after the post-ack poll confirms
  all channels OFF.
- Disabling an enabled Beam A/B/C software interlock while that beam output is
  active queues that channel OFF but leaves the interlock visible and clickable
  as Enabled while the normal operation is pending. The selected interlock
  changes to Disabled only after the post-ack BCON status poll reports mode OFF
  and output low; rejection or timeout leaves it enabled.
- Beam A/B/C ON, Activate Enabled Beams, and CSV sequence steps are blocked
  before BCON output commands when the VTRX pressure guard is enabled and the
  latest valid VTRX pressure is greater than 1e-5 mbar.
- BEAMS E-STOP always sends two redundant BCON all-off attempts, begins Cathode
  Heating shutdown immediately, and commits the beam/disarmed UI only after a
  post-ack poll confirms all channels OFF. Any failed attempt remains a CRITICAL
  E-stop failure even if the later attempt and poll turn every channel off.
- Disable CCS Output on BCON Disconnect is a runtime Main Control setting. When
  enabled, an unexpected BCON disconnect turns off active CCS outputs, and a
  manual BCON disconnect asks for confirmation before it shuts those outputs
  down. When disabled, BCON disconnects no longer drive CCS output shutdown or
  block cathode output enable requests.
- Disable Beams if pressure exceeds 10^-5 mbar is a runtime Main Control
  setting. When enabled, a valid VTRX pressure reading greater than 1e-5 mbar
  invalidates any pending operator action, logs a critical message, requests
  BCON all-off without locally changing output state, and waits for polling to
  present the resulting hardware state. It triggers once until pressure recovers
  to 1e-5 mbar or below.
- Disable CCS Output after the configured grace period above 10^-5 mbar applies
  when CCS output is active. The grace-period duration is persisted in Main
  Control config, defaults to 30 seconds, blocks new CCS output enables while
  counting down, and turns off CCS output if pressure remains unsafe until the
  timer elapses.
