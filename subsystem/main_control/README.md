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
- Providing ARM BEAMS, BEAMS E-STOP, Beam A/B/C, CH A/B/C enable, and Sync
  Start/Stop controls.
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
- Sync Start and Sync Stop buttons.
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
- Total Max Emission Current control.
- F1 keyboard shortcut hint.

## Code Structure

- `MainControlPanel.__init__()` stores dashboard callbacks, loads the saved
  emission-current limit, initializes local status state, and builds the UI.
- `create_main_control_notebook()` builds the `Main` and `Config` tabs.
- `create_beam_output_status_panel()` builds the Beam A/B/C output lines and
  latest-action line.
- `wire_beam_pulse()` registers Main Control as the callback target for Beam
  Pulse status updates and gives Beam Pulse the emission-limit providers.
- `wire_beam_energy()` registers the Beam Energy +20 kV current E-stop callback.
- `create_com_port_frame()`, `apply_com_port_changes()`, and related helpers
  manage COM-port selection through the parent Dashboard.
- `set_total_max_emission_current_limit()` validates and persists the emission
  limit through `usr/main_control_config.py`.

## Major Action Handlers

| Method | Purpose |
| --- | --- |
| `handle_arm_beams()` | Toggles Beam Pulse software arming and updates Main Control button state. |
| `handle_beams_off()` | Stops all BCON channels, turns off cathode heating outputs, disarms Beam Pulse, resets controls, and posts the E-stop action message. |
| `toggle_individual_beam_with_status()` | Turns one Beam A/B/C output on or off using the current Beam Pulse manual channel configuration. |
| `_toggle_channel_enable()` | Toggles a BCON channel enable state through Beam Pulse. |
| `handle_sync_start()` | Starts all enabled/manual-configured Beam Pulse channels together. |
| `handle_sync_stop()` | Stops synchronized Beam Pulse output. |
| `_on_channel_status_update()` | Mirrors live BCON channel output state into Beam A/B/C buttons and status lines. |
| `_on_channel_enable_status_update()` | Mirrors live BCON channel enable state into CH A/B/C buttons and beam-button availability. |
| `_handle_action_feedback()` | Converts Beam Pulse action callbacks into the latest-action status line. |

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
- `sync_start()`
- `sync_stop_all()`
- `stop_all_channels()`

Beam Pulse calls back into Main Control with:

- Live channel output status.
- Live channel enable status.
- Software armed status.
- Action feedback and firmware acknowledgement text.

### Cathode Heating

Main Control uses Cathode Heating in two ways:

- It exposes `get_predicted_emission_currents_ma()` to Beam Pulse so Beam Pulse
  can block output commands that would exceed the configured total predicted
  emission-current limit.
- During BEAMS E-STOP, Main Control calls `turn_off_all_beams()` to turn off the
  cathode heating power-supply outputs.

### Beam Energy

Beam Energy owns Knob Box monitoring and its warning/E-stop thresholds. Main
Control registers a callback with Beam Energy through `set_beams_estop_callback()`.
When Beam Energy detects that +20 kV current has reached the configured beams
E-stop current limit, it calls Main Control's BEAMS E-STOP path.

### Dashboard

Dashboard creates the Main Control panel, then assigns the shared subsystem
dictionary and wires Beam Pulse and Beam Energy after those subsystems are
created. Main Control also delegates layout saving and COM-port updates back to
Dashboard callbacks.

## Important Behavior Notes

- ARM BEAMS is a Beam Pulse software gate. It does not start output, enable a
  BCON channel, or turn on cathode heating.
- Beam A/B/C ON reads the current mode, duration, and count from the Beam Pulse
  Manual Control tab.
- Beam A/B/C buttons are only enabled when Beam Pulse is armed and the matching
  BCON channel is enabled.
- Sync Start is delegated to Beam Pulse, which filters disabled channels and
  performs output checks before sending the synchronized start to BCON.
- BEAMS E-STOP is the Main Control path that combines BCON stop, Cathode Heating
  output shutdown, Beam Pulse disarm, and Main Control UI reset.
  