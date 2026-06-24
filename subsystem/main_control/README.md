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
- Providing ARM BEAMS, BEAMS E-STOP, Beam A/B/C, CH A/B/C enable,
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
- CH A/B/C enable buttons, which mirror BCON channel enable state.
- Activate Enabled Beams and Disable All Beams buttons.
- ARM BEAMS / BEAMS ARMED toggle.
- Four-line beam status/action display:
  - Lines 1-3 show Beam A/B/C enabled/output state.
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
  Pulse status updates, gives Beam Pulse the emission-limit and VTRX pressure
  guard providers, and wires BCON disconnect notifications into Cathode Heating.
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
| `handle_beams_off()` | Stops all BCON channels, turns off cathode heating outputs, disarms Beam Pulse, resets controls, and posts the E-stop action message. |
| `toggle_individual_beam_with_status()` | Turns one Beam A/B/C output on or off using the current Beam Pulse manual channel configuration. |
| `_toggle_channel_enable()` | Toggles a BCON channel enable state through Beam Pulse. |
| `handle_activate_enabled_beams()` | Starts all enabled/manual-configured Beam Pulse channels together. |
| `handle_disable_all_beams()` | Stops all Beam Pulse output. |
| `_on_channel_status_update()` | Mirrors live BCON channel output state into Beam A/B/C buttons and status lines. |
| `_on_channel_enable_status_update()` | Mirrors live BCON channel enable state into CH A/B/C buttons and beam-button availability. |
| `_handle_action_feedback()` | Converts Beam Pulse action callbacks into the latest-action status line. |
| `_handle_bcon_disconnected()` | Disables CCS output through Cathode Heating when BCON disconnects and the guard is enabled. |
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
- `toggle_channel_enable(channel_index)`
- `activate_enabled_beams()`
- `disable_all_beams()`
- `stop_all_channels()`

Beam Pulse calls back into Main Control with:

- Live channel output status.
- Live channel enable status.
- Software armed status.
- Action feedback and firmware acknowledgement text.
- Manual-disconnect confirmation requests.
- BCON disconnect notifications.

### Cathode Heating

Main Control uses Cathode Heating in three ways:

- It exposes `get_predicted_emission_currents_ma()` to Beam Pulse so Beam Pulse
  can block output commands that would exceed the configured total predicted
  emission-current limit.
- It exposes the VTRX pressure guard setting, threshold, and latest valid VTRX
  pressure to Beam Pulse so output commands are blocked while pressure is above
  1e-5 mbar.
- During BEAMS E-STOP, Main Control calls `turn_off_all_beams()` to turn off the
  cathode heating power-supply outputs.
- When the BCON-disconnect guard is enabled, Main Control also calls
  `turn_off_all_beams()` if BCON disconnects while any cathode output is active.
  The same setting is passed to Cathode Heating so it can block new CCS output
  enables while BCON is disconnected.
- When VTRX pressure rises above 1e-5 mbar, Main Control starts a CCS shutdown
  grace-period timer. While the timer is active, Cathode Heating blocks new CCS
  output enables; if pressure does not recover before the timer elapses, Main
  Control calls `turn_off_all_beams()`.

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

Main Control also uses VTRX pressure to protect CCS output. Pressure above
1e-5 mbar starts the configured CCS grace-period timer. Subsequent high-pressure
updates log countdown warnings and shut off active CCS output after the grace
period elapses. Recovery to 1e-5 mbar or below clears the timer.

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
  BCON channel is enabled.
- Activate Enabled Beams is delegated to Beam Pulse, which filters disabled channels and
  performs output checks before sending the synchronized start to BCON.
- Beam A/B/C ON, Activate Enabled Beams, and CSV sequence steps are blocked
  before BCON output commands when the VTRX pressure guard is enabled and the
  latest valid VTRX pressure is greater than 1e-5 mbar.
- BEAMS E-STOP is the Main Control path that combines BCON stop, Cathode Heating
  output shutdown, Beam Pulse disarm, and Main Control UI reset.
- Disable CCS Output on BCON Disconnect is a runtime Main Control setting. When
  enabled, an unexpected BCON disconnect turns off active CCS outputs, and a
  manual BCON disconnect asks for confirmation before it shuts those outputs
  down. When disabled, BCON disconnects no longer drive CCS output shutdown or
  block cathode output enable requests.
- Disable Beams if pressure exceeds 10^-5 mbar is a runtime Main Control
  setting. When enabled, a valid VTRX pressure reading greater than 1e-5 mbar
  logs a critical message and disables Beam Pulse output once until pressure
  recovers to 1e-5 mbar or below.
- Disable CCS Output after the configured grace period above 10^-5 mbar is
  always active. The grace-period duration is persisted in Main Control config,
  defaults to 30 seconds, blocks new CCS output enables while counting down, and
  turns off CCS output if pressure remains high until the timer elapses.
