# Beam Pulse Panel — User Test Plan

**Panel location:** Dashboard → Row 2 → "Beam Pulse" frame  
**Version under test:** _(fill in git commit or release tag)_  
**Tester:** ___________________________  
**Date:** ___________________________  
**Hardware required:** BCON controller (Arduino Mega + firmware) connected via USB serial  
**Interlock state required:** Permissive (interlock OK) unless otherwise stated  

---

## How to Use This Document

Each test case follows this structure:

| Field | Meaning |
|---|---|
| **ID** | Unique identifier — reference this in defect reports |
| **Objective** | What behaviour is being verified |
| **Preconditions** | State the dashboard and hardware must be in before starting |
| **Steps** | Numbered actions the tester performs |
| **Expected result** | What should be observed if the software is working correctly |
| **Pass / Fail** | Check one box after running the test |

**Status legend**

- [ ] Not yet run  
- [x] Passed  
- [~] Failed — record notes below the test case  

---

## Table of Contents

1. [Test Setup Checklist](#1-test-setup-checklist)
2. [Connection & Status Indicator Tests](#2-connection--status-indicator-tests)
3. [Arm / Disarm Workflow Tests](#3-arm--disarm-workflow-tests)
4. [Manual Control Tab — Mode Selection](#4-manual-control-tab--mode-selection)
5. [Manual Control Tab — Input Field Validation](#5-manual-control-tab--input-field-validation)
6. [Manual Control Tab — Channel Apply & Status Feedback](#6-manual-control-tab--channel-apply--status-feedback)
7. [Sync Start / Sync Stop Tests](#7-sync-start--sync-stop-tests)
8. [CSV Sequence Tab — Load & Preview](#8-csv-sequence-tab--load--preview)
9. [CSV Sequence Tab — Run & Stop](#9-csv-sequence-tab--run--stop)
10. [Tab Switching & Panel Visibility Tests](#10-tab-switching--panel-visibility-tests)
11. [Safety — Blocked Actions When Not Armed](#11-safety--blocked-actions-when-not-armed)
12. [Watchdog Configuration Tests](#12-watchdog-configuration-tests)
13. [Channel Enable / Disable Tests](#13-channel-enable--disable-tests)
14. [Error Handling & Edge Case Tests](#14-error-handling--edge-case-tests)
15. [Sign-off](#15-sign-off)

---

## 1. Test Setup Checklist

Complete all items before running any test case.

- [ ] Dashboard application launched (`python main.py`)  
- [ ] BCON controller powered on and USB cable plugged in  
- [ ] Correct serial port selected for BCON in the dashboard COM port configuration  
- [ ] Hardware interlock line is in the **permissive** (OK) state  
- [ ] `sequences/` folder contains at least one test CSV file (see Appendix A for a sample)  
- [ ] No active pulses running from a previous test session  
- [ ] "Messages & Errors" panel at the bottom of the dashboard is visible and scrolled to the bottom  
- [ ] Screen resolution allows the full "Beam Pulse" panel to be visible without scrolling  

---

## 2. Connection & Status Indicator Tests

---

### BP-CON-001 — Initial state: BCON indicator is red

**Objective:** Confirm the BCON connection indicator shows disconnected on startup.

**Preconditions:** Dashboard just launched; no connection attempt has been made yet.

**Steps:**
1. Locate the "Beam Pulse" panel in the dashboard.
2. Look at the small circular indicator next to the "BCON" label in the top status bar of the panel.

**Expected result:** The indicator is **red**. The button to the right is labelled "Connect".

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

### BP-CON-002 — Clicking Connect establishes connection

**Objective:** Verify that the Connect button successfully opens the serial port and changes the indicator.

**Preconditions:** BCON controller is plugged in and powered. BP-CON-001 passed.

**Steps:**
1. Click the **Connect** button in the Beam Pulse status bar.
2. Wait up to 5 seconds (firmware boot settle time applies).
3. Observe the circular indicator and the button label.
4. Observe the "Log" text at the right side of the status bar.

**Expected result:**
- Indicator turns **green**.
- Button relabels to **"Disconnect"**.
- Log line shows a message similar to `BCON connected on /dev/ttyUSBx`.
- "Messages & Errors" panel shows the same connection message.

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

### BP-CON-003 — Interlock and watchdog status appear in the status bar

**Objective:** Verify that safety status labels update once connected.

**Preconditions:** BP-CON-002 passed (BCON connected, interlock permissive).

**Steps:**
1. Read the safety label in the Beam Pulse status bar (between the BCON indicator and the Connect/Disconnect button).

**Expected result:** Label shows `Interlock: ok | Watchdog: ok` (no FAULT suffix).

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

### BP-CON-004 — Clicking Disconnect closes the connection

**Objective:** Verify that the Disconnect button closes the serial port.

**Preconditions:** BP-CON-002 passed (BCON connected).

**Steps:**
1. Click **Disconnect**.
2. Observe the indicator and button label.

**Expected result:**
- Indicator returns to **red**.
- Button relabels to **"Reconnect"**.
- Log line shows a disconnection or "connect failed" message.

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

### BP-CON-005 — Reconnect after disconnect restores full operation

**Objective:** Verify that re-opening the connection after a manual disconnect works correctly.

**Preconditions:** BP-CON-004 completed (indicator red, button says "Reconnect").

**Steps:**
1. Click **Reconnect**.
2. Wait up to 5 seconds.

**Expected result:** Indicator turns green, button returns to "Disconnect", safety label shows ok.

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

### BP-CON-006 — Interlock failure reflected in status bar

**Objective:** Confirm the status bar shows a locked interlock state.

**Preconditions:** BCON connected. Test hardware allows de-asserting the interlock line.

**Steps:**
1. With a test lead or interlock simulator, de-assert the hardware interlock.
2. Wait up to 2 seconds.
3. Read the safety label.

**Expected result:** Safety label shows `Interlock: locked`.

4. Restore the interlock to permissive state.

**Expected result after restore:** Safety label returns to `Interlock: ok`.

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

## 3. Arm / Disarm Workflow Tests

> **Note:** In the dashboard the ARM action is initiated from the main control panel (not inside the Beam Pulse panel itself). The Beam Pulse panel reflects the armed state through button enable/disable states.

---

### BP-ARM-001 — Action buttons are disabled before arming

**Objective:** Confirm that all beam-firing buttons are inaccessible when beams are not armed.

**Preconditions:** BCON connected. Beams have **not** been armed in this session.

**Steps:**
1. In the Beam Pulse panel → Manual Control tab, observe:
   - Any "Apply CH1/2/3" buttons (if present in standalone mode)
   - The **Sync Start** button
2. In the CSV Sequence area, observe the **Run Sequence** button.

**Expected result:** All listed buttons appear greyed-out and cannot be clicked.

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

### BP-ARM-002 — Arming enables action buttons

**Objective:** Confirm that arming unlocks the beam-firing buttons.

**Preconditions:** BP-ARM-001 passed.

**Steps:**
1. From the dashboard main control or the ARM command (as per your system procedure), arm the beams.
2. Return to the Beam Pulse panel.
3. Observe the **Sync Start** button state.
4. Observe the **Run Sequence** button (only if a sequence is loaded; otherwise it stays disabled until a sequence is loaded).

**Expected result:**
- **Sync Start** becomes enabled (normal appearance, clickable).
- Log line in Beam Pulse status bar reads something like `ARM command sent`.

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

### BP-ARM-003 — Disarming disables action buttons and stops channels

**Objective:** Confirm that disarming immediately stops all activity and re-disables buttons.

**Preconditions:** Beams are armed (BP-ARM-002 passed). At least one channel is active (pulsing or DC).

**Steps:**
1. Start a channel (e.g., set CH1 to DC and apply).
2. Disarm the beams using the dashboard main control.
3. Observe all three channel status labels in the Manual Control tab.
4. Observe the **Sync Start** button.

**Expected result:**
- All channels show `Status: OFF`.
- **Sync Start** returns to greyed-out state.
- "Messages & Errors" shows `Beams DISARMED`.

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

### BP-ARM-004 — Stop buttons always remain accessible

**Objective:** Confirm that stop/safety actions are not gated by the armed state.

**Preconditions:** Beams are **not** armed.

**Steps:**
1. Observe the **Sync Stop** button in the Beam Pulse panel.
2. Click **Sync Stop**.
3. Observe the **Stop Sequence** button in the CSV area.
4. Click **Stop Sequence**.

**Expected result:**
- Both buttons are **not** greyed out and can be clicked at any time.
- Clicking them does not produce an error dialog; the log may show a stop message.

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

## 4. Manual Control Tab — Mode Selection

---

### BP-MAN-001 — Default mode is PULSE with count field disabled

**Objective:** Verify the initial widget state on the Manual Control tab.

**Preconditions:** Dashboard freshly launched or panel freshly initialized.

**Steps:**
1. Click the **Manual Control** tab in the Beam Pulse panel.
2. For each of the three channel cards (Channel 1, 2, 3), read the Mode drop-down.
3. Observe whether the "Count" entry field is enabled or disabled.

**Expected result:**
- Mode drop-down defaults to **PULSE**.
- The "Count" entry field is **greyed out** (disabled) for all channels.
- The "Duration (ms)" entry shows **100**.

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

### BP-MAN-002 — Selecting OFF disables both Duration and Count fields

**Objective:** Verify widget state when OFF mode is selected.

**Preconditions:** Manual Control tab visible.

**Steps:**
1. Click the Mode drop-down for Channel 1.
2. Select **OFF**.
3. Observe both "Duration (ms)" and "Count" fields.

**Expected result:** Both fields are **greyed out** (disabled).

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

### BP-MAN-003 — Selecting DC disables both Duration and Count fields

**Objective:** Verify widget state when DC mode is selected.

**Preconditions:** Manual Control tab visible.

**Steps:**
1. Click the Mode drop-down for Channel 2.
2. Select **DC**.
3. Observe both "Duration (ms)" and "Count" fields.

**Expected result:** Both fields are **greyed out** (disabled).

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

### BP-MAN-004 — Selecting PULSE enables Duration, keeps Count disabled

**Objective:** Verify widget state when PULSE mode is selected.

**Preconditions:** Channel was in a different mode (e.g., OFF or DC) from a previous test.

**Steps:**
1. Click the Mode drop-down for Channel 3.
2. Select **PULSE**.
3. Observe the "Duration (ms)" and "Count" fields.

**Expected result:**
- "Duration (ms)" becomes **enabled** (white background, editable).
- "Count" remains **greyed out** and its value is reset to `1`.

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

### BP-MAN-005 — Selecting PULSE_TRAIN enables both Duration and Count

**Objective:** Verify widget state when PULSE_TRAIN mode is selected.

**Preconditions:** Manual Control tab visible.

**Steps:**
1. Click the Mode drop-down for Channel 1.
2. Select **PULSE_TRAIN**.
3. Observe the "Duration (ms)" and "Count" fields.

**Expected result:** Both "Duration (ms)" and "Count" become **enabled** (editable).

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

## 5. Manual Control Tab — Input Field Validation

> For all tests in this section: beams must be **armed** (BP-ARM-002) before clicking Apply / Sync Start; otherwise the action is blocked. The validation tests below confirm the error dialogs, so arm first.

---

### BP-VAL-001 — PULSE with valid duration is accepted

**Objective:** Confirm valid PULSE configuration sends to hardware without error.

**Preconditions:** BCON connected, beams armed. CH1 mode set to PULSE.

**Steps:**
1. Set Channel 1 mode to **PULSE**.
2. Enter `150` in the "Duration (ms)" field.
3. Click **Apply CH1** (or trigger Sync Start for CH1 only).

**Expected result:** No error dialog appears. Log shows `Applied CH1: mode=PULSE dur=150ms count=1`.

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

### BP-VAL-002 — PULSE with zero duration shows an error

**Objective:** Confirm that a zero-duration value is rejected.

**Preconditions:** BCON connected, beams armed. CH1 mode set to PULSE.

**Steps:**
1. Set Channel 1 mode to **PULSE**.
2. Clear the "Duration (ms)" field and type `0`.
3. Click **Apply CH1**.

**Expected result:** An "Invalid Configuration" error dialog appears stating duration must be > 0 ms. No Modbus write is sent.

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

### BP-VAL-003 — PULSE with empty duration shows an error

**Objective:** Confirm a blank duration field is rejected.

**Preconditions:** BCON connected, beams armed. CH1 mode set to PULSE.

**Steps:**
1. Set Channel 1 mode to **PULSE**.
2. Clear the "Duration (ms)" field completely (leave it blank).
3. Click **Apply CH1**.

**Expected result:** An "Invalid Configuration" error dialog appears.

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

### BP-VAL-004 — Duration field rejects non-numeric characters

**Objective:** Confirm the duration field only accepts whole numbers.

**Preconditions:** Manual Control tab visible. CH1 mode set to PULSE.

**Steps:**
1. Click into the "Duration (ms)" field for Channel 1.
2. Try to type the letter `a`.
3. Try to type a decimal point `.`.
4. Try to type a negative sign `-`.

**Expected result:** None of those characters appear in the field — the field remains unchanged or empty after each rejected keystroke.

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

### BP-VAL-005 — PULSE_TRAIN with count below 2 shows an error

**Objective:** Confirm that PULSE_TRAIN requires a count of at least 2.

**Preconditions:** BCON connected, beams armed. CH2 mode set to PULSE_TRAIN.

**Steps:**
1. Set Channel 2 mode to **PULSE_TRAIN**.
2. Enter `100` in "Duration (ms)" and `1` in "Count".
3. Click **Apply CH2**.

**Expected result:** An "Invalid Configuration" error dialog appears stating PULSE_TRAIN requires count ≥ 2.

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

### BP-VAL-006 — PULSE_TRAIN with count = 2 is accepted

**Objective:** Confirm count = 2 is the valid minimum for PULSE_TRAIN.

**Preconditions:** BCON connected, beams armed. CH2 mode set to PULSE_TRAIN.

**Steps:**
1. Set Channel 2 mode to **PULSE_TRAIN**.
2. Enter `100` in "Duration (ms)" and `2` in "Count".
3. Click **Apply CH2**.

**Expected result:** No error dialog. Log shows `Applied CH2: mode=PULSE_TRAIN dur=100ms count=2`.

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

### BP-VAL-007 — OFF mode bypasses duration/count validation

**Objective:** Confirm OFF mode does not require valid duration or count values.

**Preconditions:** BCON connected, beams armed.

**Steps:**
1. Set Channel 3 mode to **OFF**.
2. (Duration and count fields should already be disabled — do not change them.)
3. Click **Apply CH3**.

**Expected result:** No error dialog. Log shows `Applied CH3: mode=OFF dur=0ms count=1`.

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

### BP-VAL-008 — DC mode bypasses duration/count validation

**Objective:** Confirm DC mode does not require valid duration or count values.

**Preconditions:** BCON connected, beams armed.

**Steps:**
1. Set Channel 1 mode to **DC**.
2. Click **Apply CH1**.

**Expected result:** No error dialog. Log shows `Applied CH1: mode=DC`.

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

## 6. Manual Control Tab — Channel Apply & Status Feedback

---

### BP-STAT-001 — Status label updates to show running mode

**Objective:** Confirm the channel status label reflects real-time hardware state.

**Preconditions:** BCON connected, beams armed. CH1 set to DC mode.

**Steps:**
1. Set Channel 1 mode to **DC**.
2. Click **Apply CH1**.
3. Wait up to 1 second (one poll cycle = 300 ms).
4. Read the "Status:" label on the Channel 1 card.

**Expected result:** Status label shows `Status: DC | O:1` (output level = 1 in DC mode).

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

### BP-STAT-002 — Remaining count decrements during PULSE_TRAIN

**Objective:** Confirm the "Remaining" label counts down live during a pulse train.

**Preconditions:** BCON connected, beams armed. CH2 set to PULSE_TRAIN, duration=200ms, count=5.

**Steps:**
1. Set Channel 2 mode to **PULSE_TRAIN**, duration `200`, count `5`.
2. Click **Apply CH2**.
3. Observe the "Remaining:" label on the Channel 2 card over the next ~2 seconds.

**Expected result:** "Remaining" starts at `5` and counts down to `0` as pulses complete.

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

### BP-STAT-003 — Channel widgets lock during active pulse

**Objective:** Confirm mode/duration/count fields are not editable while a channel is running.

**Preconditions:** BCON connected, beams armed.

**Steps:**
1. Set Channel 3 to **DC** and click **Apply CH3**.
2. Immediately try to change the Channel 3 Mode drop-down while it is running.
3. Try clicking into the "Duration (ms)" field.

**Expected result:** Mode drop-down and duration/count fields are **greyed out** and cannot be changed while the channel is active.

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

### BP-STAT-004 — Channel widgets unlock after channel stops

**Objective:** Confirm widgets become editable again after a pulse completes.

**Preconditions:** BP-STAT-003 environment — CH3 is currently in DC and locked.

**Steps:**
1. Click **Sync Stop** (or apply OFF mode to CH3 if a per-channel stop is available).
2. Wait up to 1 second for the status poll to update.
3. Try to change the Channel 3 Mode drop-down.

**Expected result:** Mode drop-down becomes **interactive** again. Status label shows `Status: OFF`.

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

### BP-STAT-005 — Duration and count auto-fill from hardware when field is blank

**Objective:** Verify that leaving the duration field blank causes it to auto-populate from the hardware register.

**Preconditions:** BCON connected, at least one prior configuration has been applied to CH1.

**Steps:**
1. Clear the "Duration (ms)" field for Channel 1 completely.
2. Wait up to 1 second (one poll cycle).
3. Read the field again.

**Expected result:** Field auto-fills with the duration value last written to hardware (non-zero).

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

## 7. Sync Start / Sync Stop Tests

---

### BP-SYNC-001 — Sync Start fires all enabled channels simultaneously

**Objective:** Confirm that Sync Start writes parameters and modes for all enabled channels with minimal delay between channels.

**Preconditions:** BCON connected, beams armed. All three channels enabled (green enable indicator). Channels set up differently:
- CH1: PULSE, 100 ms
- CH2: PULSE_TRAIN, 50 ms, count 3
- CH3: DC

**Steps:**
1. Configure channels as above in the Manual Control tab.
2. Click **Sync Start**.
3. Observe all three channel status labels within the next poll cycle.

**Expected result:**
- CH1 shows `Status: PULSE`, Remaining: 1
- CH2 shows `Status: PULSE_TRAIN`, Remaining: 3 (counting down)
- CH3 shows `Status: DC`, O:1
- Log shows `Sync Start: CH1=PULSE(100ms x1), CH2=PULSE_TRAIN(50ms x3), CH3=DC(0ms x1)`

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

### BP-SYNC-002 — Sync Stop turns all channels OFF

**Objective:** Confirm Sync Stop halts all active channels.

**Preconditions:** BP-SYNC-001 completed with channels running (especially DC on CH3 which doesn't stop by itself).

**Steps:**
1. Click **Sync Stop**.
2. Wait up to 1 second.
3. Read all three channel status labels.

**Expected result:** All three channels show `Status: OFF`. Log shows `Sync Stop: all channels -> OFF`.

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

### BP-SYNC-003 — Sync Start skips channels that are hardware-disabled

**Objective:** Confirm that channels with disabled hardware enable are excluded from Sync Start.

**Preconditions:** BCON connected, beams armed. Channel 2 hardware enable has been toggled off (grey indicator).

**Steps:**
1. Disable Channel 2 using the CH Enable toggle for CH2.
2. Confirm the CH2 enable indicator is **grey**.
3. Click **Sync Start**.
4. Read the log message.

**Expected result:** Log shows `Sync Start: CH2 skipped (not enabled)`, and only CH1 and CH3 are started.

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

### BP-SYNC-004 — Sync Start is blocked when not armed

**Objective:** Confirm Sync Start button is non-functional when beams are not armed.

**Preconditions:** Beams are **not** armed.

**Steps:**
1. Observe the **Sync Start** button — it should be greyed out.
2. Attempt to click it (may not be possible if disabled).

**Expected result:** Button does not respond. If somehow clickable, log shows `Action blocked: beams are not armed`.

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

### BP-SYNC-005 — Sync Start with an invalid channel configuration shows error and aborts

**Objective:** Confirm that a validation error for one channel aborts the entire Sync Start operation.

**Preconditions:** BCON connected, beams armed.

**Steps:**
1. Set Channel 1 to **PULSE_TRAIN**, duration `100`, count `1` (invalid — count must be ≥ 2).
2. Set Channel 2 to **PULSE**, duration `200`.
3. Click **Sync Start**.

**Expected result:** An "Invalid Configuration" dialog appears for Channel 1. Neither channel starts pulsing.

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

## 8. CSV Sequence Tab — Load & Preview

---

### BP-CSV-001 — CSV Sequence tab shows placeholder before loading

**Objective:** Confirm initial state of the CSV Sequence tab.

**Preconditions:** Dashboard freshly initialized. No sequence has been loaded.

**Steps:**
1. Click the **CSV Sequence** tab in the Beam Pulse panel.
2. Observe the file label and the preview text area.

**Expected result:**
- File label reads `No sequence loaded` in grey text.
- Progress label is blank.
- Preview text area is empty and read-only.
- "Run Sequence" button is greyed out.

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

### BP-CSV-002 — Loading a valid CSV populates the preview

**Objective:** Confirm a well-formed CSV file is parsed and displayed.

**Preconditions:** A valid test CSV exists (see Appendix A). CSV Sequence tab visible.

**Steps:**
1. Click **Load CSV**.
2. Navigate to the test CSV file and click Open.
3. Observe the file label, progress label, and preview text area.

**Expected result:**
- File label shows the filename and step count, e.g., `test_sequence.csv  (3 steps)`.
- Progress label shows `Ready`.
- Preview area lists one line per channel-row, e.g., `Step 1: CH1 PULSE dur=100ms cnt=1  dwell=500ms`.

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

### BP-CSV-003 — Preview text is read-only

**Objective:** Confirm the user cannot edit the sequence preview.

**Preconditions:** BP-CSV-002 completed (sequence loaded).

**Steps:**
1. Click inside the sequence preview text area.
2. Attempt to type any character.

**Expected result:** No characters appear. The text area is read-only.

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

### BP-CSV-004 — Run Sequence remains disabled after loading when not armed

**Objective:** Confirm that loading a sequence alone does not enable Run Sequence.

**Preconditions:** BP-CSV-002 completed. Beams are **not** armed.

**Steps:**
1. Observe the **Run Sequence** button after loading the CSV.

**Expected result:** Button remains **greyed out**.

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

### BP-CSV-005 — Run Sequence becomes enabled after loading and arming

**Objective:** Confirm Run Sequence is only enabled when both a sequence is loaded AND beams are armed.

**Preconditions:** BP-CSV-002 completed. Beams are **not** yet armed.

**Steps:**
1. Observe **Run Sequence** is greyed out.
2. Arm the beams.
3. Observe **Run Sequence** again.

**Expected result:** **Run Sequence** becomes enabled (normal appearance, clickable).

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

### BP-CSV-006 — Loading an invalid CSV shows an error dialog

**Objective:** Confirm that a malformed CSV produces a user-friendly error.

**Preconditions:** A CSV file with a bad mode name (e.g., `BADMODE`) available for testing.

**Steps:**
1. Click **Load CSV**.
2. Select the malformed CSV file.
3. Observe what happens.

**Expected result:** A "Sequence Load Error" dialog appears describing the problem (e.g., `Unknown mode 'BADMODE' at step 1`). The previously loaded sequence (if any) is not replaced.

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

### BP-CSV-007 — Save Template writes a usable template file

**Objective:** Confirm the Save Template button produces a file that can be loaded without errors.

**Preconditions:** CSV Sequence tab visible.

**Steps:**
1. Click **Save Template**.
2. Choose a save location and filename (e.g., `test_template.csv`).
3. Click **Load CSV** and open the file just saved.
4. Observe the preview.

**Expected result:** Template loads without error. Preview shows the example steps from the template (6 steps across 3 channels including `ALL`).

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

## 9. CSV Sequence Tab — Run & Stop

---

### BP-SEQ-001 — Running a sequence steps through each entry in order

**Objective:** Confirm the sequence player executes steps sequentially.

**Preconditions:** BCON connected, beams armed, a 3-step test sequence loaded (see Appendix A).

**Steps:**
1. Click **Run Sequence**.
2. Observe the progress label.
3. Wait for the sequence to complete.

**Expected result:**
- Progress label updates: `Step 1/3 (#1)` → `Step 2/3 (#2)` → `Step 3/3 (#3)` → `Sequence complete`.
- Hardware channels match each step's configuration during dwell time.
- "Run Sequence" re-enables and "Stop Sequence" disables after completion.

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

### BP-SEQ-002 — Stop Sequence halts playback mid-run

**Objective:** Confirm that clicking Stop Sequence interrupts playback.

**Preconditions:** BCON connected, beams armed. A multi-step sequence with long dwell times loaded (e.g., dwell = 3000 ms per step).

**Steps:**
1. Click **Run Sequence**.
2. While `Step 1/N` is displayed, click **Stop Sequence**.
3. Observe the progress label and channel status labels.

**Expected result:**
- Progress label shows `Sequence stopped`.
- Playback does not continue to step 2.
- "Run Sequence" re-enables.

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

### BP-SEQ-003 — Run Sequence cannot be started twice simultaneously

**Objective:** Confirm that clicking Run Sequence while already running has no effect.

**Preconditions:** BCON connected, beams armed. Long-dwell sequence loaded and running.

**Steps:**
1. Click **Run Sequence** to start.
2. Immediately click **Run Sequence** again (button should still be visible).

**Expected result:** The second click is ignored. Only one sequence worker thread runs. Progress increments normally without doubling.

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

### BP-SEQ-004 — Dwell time is respected between steps

**Objective:** Confirm the sequence pauses between steps for the configured dwell time.

**Preconditions:** BCON connected, beams armed. Test sequence with step 1 dwell = 2000 ms.

**Steps:**
1. Click **Run Sequence**.
2. Note the time when progress label changes from `Step 1/N` to `Step 2/N` (use a stopwatch or clock).

**Expected result:** Transition from step 1 to step 2 takes approximately 2 seconds (±0.2 s).

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

### BP-SEQ-005 — Sequence is blocked when not connected to BCON

**Objective:** Confirm sequence cannot start without an active BCON connection.

**Preconditions:** BCON disconnected. Sequence loaded, beams armed.

**Steps:**
1. Disconnect from BCON (BP-CON-004).
2. Click **Run Sequence**.
3. Observe what happens.

**Expected result:** A warning dialog appears: "Not connected to BCON device."

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

## 10. Tab Switching & Panel Visibility Tests

---

### BP-TAB-001 — Manual Control tab shows beam ON/OFF row and Sync row

**Objective:** Confirm correct panel layout when "Manual Control" tab is active.

**Preconditions:** Dashboard loaded, Beam Pulse panel visible.

**Steps:**
1. Click the **Manual Control** tab.
2. Observe the external control area below/beside the Beam Pulse panel.

**Expected result:**
- Beam A, B, C ON/OFF toggle buttons are **visible**.
- Sync Start / Sync Stop row is **visible**.
- CSV buttons frame (Load CSV / Save Template / Run Sequence / Stop Sequence) is **hidden**.

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

### BP-TAB-002 — CSV Sequence tab hides beam ON/OFF and Sync row; shows CSV buttons

**Objective:** Confirm correct panel layout when "CSV Sequence" tab is active.

**Preconditions:** BP-TAB-001 passed.

**Steps:**
1. Click the **CSV Sequence** tab.
2. Observe the same external control area.

**Expected result:**
- Beam A, B, C ON/OFF buttons are **hidden**.
- Sync Start / Sync Stop row is **hidden**.
- CSV buttons (Load CSV, Save Template, Run Sequence, Stop Sequence) are now **visible**.

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

### BP-TAB-003 — Switching back to Manual tab restores original layout

**Objective:** Confirm the tab switch is reversible without needing a restart.

**Preconditions:** BP-TAB-002 completed (CSV Sequence tab active).

**Steps:**
1. Click the **Manual Control** tab.
2. Observe the external control area.

**Expected result:** Layout matches BP-TAB-001 — Beam ON/OFF and Sync row are visible again; CSV buttons are hidden.

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

### BP-TAB-004 — CH Enable/Disable controls are always visible regardless of tab

**Objective:** Confirm channel enable toggles are accessible from either tab.

**Preconditions:** Dashboard loaded, Beam Pulse panel visible. Test from both tabs.

**Steps:**
1. Note the position of channel enable toggle buttons/indicators.
2. Switch between Manual Control and CSV Sequence tabs.
3. Observe whether the enable controls are present after each switch.

**Expected result:** CH1/2/3 enable buttons remain visible and accessible on both tabs.

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

## 11. Safety — Blocked Actions When Not Armed

> All tests in this section use the dashboard with beams **not armed**.

---

### BP-SAFE-001 — Applying channel config is blocked when not armed

**Preconditions:** BCON connected. Beams **not** armed.

**Steps:**
1. Set Channel 1 mode to PULSE, duration 100.
2. Attempt to apply (click Apply CH1 or equivalent).

**Expected result:** Log shows `Action blocked: beams are not armed`. No Modbus write is sent. No channels activate.

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

### BP-SAFE-002 — Sync Start is blocked when not armed

**Preconditions:** BCON connected. Beams **not** armed.

**Steps:**
1. Click **Sync Start** (button should be greyed out — if not, this is itself a failure).
2. Observe the log.

**Expected result:** Button is non-interactive (greyed out). If somehow activated, log shows blocked message.

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

### BP-SAFE-003 — Run Sequence is blocked when not armed

**Preconditions:** Sequence loaded. Beams **not** armed.

**Steps:**
1. Observe **Run Sequence** button.
2. Note it is greyed out.

**Expected result:** Button is disabled. Sequence cannot be started.

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

### BP-SAFE-004 — Sync Stop works when not armed (safety action)

**Preconditions:** Beams **not** armed.

**Steps:**
1. Click **Sync Stop**.

**Expected result:** Button is enabled and clickable. Log shows `Sync Stop: all channels -> OFF`. No error or dialog.

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

### BP-SAFE-005 — Stop Sequence works when not armed (safety action)

**Preconditions:** Beams **not** armed.

**Steps:**
1. Click **Stop Sequence**.

**Expected result:** Button is enabled. If sequence is running, it halts. If idle, the click is acknowledged without error.

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

## 12. Watchdog Configuration Tests

---

### BP-WDG-001 — Setting a valid watchdog value is accepted

**Objective:** Confirm the watchdog entry and Set button work correctly.

**Preconditions:** BCON connected.

**Steps:**
1. Locate the "Watchdog (ms):" entry in the status bar of the Beam Pulse panel.
2. Clear the field and type `3000`.
3. Click **Set**.
4. Observe the log.

**Expected result:** Log shows `Set watchdog = 3000 ms`. No error dialog.

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

### BP-WDG-002 — Watchdog field auto-fills from hardware after connect

**Objective:** Confirm the watchdog entry reflects the value stored in hardware registers.

**Preconditions:** BCON connected. Watchdog was previously set to a known value (e.g., 2000 ms default).

**Steps:**
1. Clear the watchdog entry field.
2. Wait up to 1 second (one poll cycle).
3. Read the entry field.

**Expected result:** Field auto-fills with the hardware watchdog value (e.g., `2000`).

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

### BP-WDG-003 — Non-numeric watchdog value shows an error

**Objective:** Confirm the watchdog entry rejects non-integer values.

**Preconditions:** BCON connected.

**Steps:**
1. Clear the watchdog entry field.
2. Type `abc`.
3. Click **Set**.

**Expected result:** An "Invalid" error dialog appears stating the value must be an integer. No write is sent to hardware.

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

## 13. Channel Enable / Disable Tests

---

### BP-EN-001 — Enable indicator reflects hardware enable state

**Objective:** Confirm the per-channel enable indicator (green/grey dot) matches true hardware state.

**Preconditions:** BCON connected, beams armed.

**Steps:**
1. Observe the enable indicator for Channel 1 (small circle near the channel card or in the enable row).
2. Toggle Channel 1 enable using the dashboard enable button.
3. Wait up to 1 second.
4. Observe the indicator.

**Expected result:** Indicator changes from **grey** (disabled) to **green** (enabled), or vice versa, matching the command sent.

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

### BP-EN-002 — Overcurrent indicator turns red on an overcurrent event

**Objective:** Confirm the overcurrent status indicator responds to a hardware overcurrent condition.

**Preconditions:** BCON connected. Ability to trigger or simulate an overcurrent condition on the test hardware.

**Steps:**
1. Observe the overcurrent indicator for a channel (small circle — green = OK, red = fault).
2. Trigger the overcurrent condition on the hardware.
3. Wait up to 1 second.
4. Observe the indicator.

**Expected result:** Indicator turns **red** when overcurrent is active, returns to **green** when cleared.

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

### BP-EN-003 — Enable toggle is blocked when not armed

**Objective:** Confirm channel enable cannot be toggled without arming.

**Preconditions:** Beams **not** armed.

**Steps:**
1. Click the enable toggle for Channel 2.

**Expected result:** Log shows `Action blocked: beams are not armed`. Enable state does not change.

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

## 14. Error Handling & Edge Case Tests

---

### BP-ERR-001 — Losing USB connection auto-disconnects BCON

**Objective:** Confirm the panel recovers gracefully when the serial cable is unplugged.

**Preconditions:** BCON connected (indicator green).

**Steps:**
1. Physically unplug the USB cable from the BCON controller.
2. Wait up to 5 seconds (4 consecutive poll failures × 0.3 s each = ~1.2 s plus margin).
3. Observe the indicator and log.

**Expected result:**
- Indicator turns **red** automatically.
- Button relabels to "Reconnect".
- Log shows a Modbus read failure and then a disconnection message.

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

### BP-ERR-002 — Reconnecting after cable unplug restores operation

**Objective:** Confirm a clean reconnect cycle after physical disconnection.

**Preconditions:** BP-ERR-001 completed (cable re-plugged in).

**Steps:**
1. Plug the USB cable back in.
2. Click **Reconnect**.
3. Wait up to 5 seconds.

**Expected result:** Indicator turns green, safety status shows ok, normal operation resumes.

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

### BP-ERR-003 — Loading a CSV when no file is selected does not crash

**Objective:** Confirm the Cancel action in the file dialog is handled gracefully.

**Preconditions:** CSV Sequence tab visible.

**Steps:**
1. Click **Load CSV**.
2. When the file dialog opens, click **Cancel** (do not select a file).
3. Observe the Beam Pulse panel.

**Expected result:** Panel returns to its previous state. No error dialog. No crash.

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

### BP-ERR-004 — Attempting to run a sequence when no sequence is loaded shows a message

**Objective:** Confirm the run action is graceful when `_seq_steps` is empty.

**Preconditions:** BCON connected, beams armed. No CSV loaded (or previously cleared by restart).

**Steps:**
1. Confirm the file label shows "No sequence loaded".
2. If Run Sequence button is somehow enabled, click it.

**Expected result:** Either the button is greyed out (preferred), or an informational dialog appears: "No sequence loaded." No crash occurs.

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

### BP-ERR-005 — Messages & Errors panel receives all Beam Pulse log events

**Objective:** Confirm that events logged in the Beam Pulse panel also appear in the global Messages & Errors frame.

**Preconditions:** BCON connected, beams armed, Messages & Errors panel visible.

**Steps:**
1. Apply any channel configuration (e.g., CH1 DC).
2. Look at the "Messages & Errors" frame at the bottom of the dashboard.

**Expected result:** The apply action log entry (e.g., `Applied CH1: mode=DC`) appears in the Messages & Errors panel.

- [ ] Pass  &nbsp;&nbsp; [ ] Fail

---

## 15. Sign-off

| Role | Name | Signature | Date |
|---|---|---|---|
| Tester | | | |
| Reviewer | | | |
| Approver | | | |

---

**Overall result**

- [ ] All tests passed — panel ready for use  
- [ ] Some tests failed — see defect notes below  

**Defect notes / observations:**

_(Use this space to record any failures, unexpected behaviour, or open questions)_

```
Test ID:
Description:
Steps to reproduce:
Expected:
Actual:
Severity (Low / Medium / High / Critical):

---
```

---

## Appendix A — Sample Test CSV File

Save the following content as `sequences/test_sequence.csv`:

```
# Test Sequence — 3 steps
step,ch,mode,duration_ms,count,dwell_ms
1,1,PULSE,100,1,1000
1,2,DC,,,1000
1,3,OFF,,,1000
2,1,PULSE_TRAIN,50,4,2000
2,2,PULSE_TRAIN,50,4,2000
2,3,OFF,,,2000
3,ALL,OFF,,,500
```

**What to expect when this runs:**
- **Step 1** (dwell 1 s): CH1 fires one 100 ms pulse; CH2 goes DC; CH3 stays OFF
- **Step 2** (dwell 2 s): CH1 and CH2 each fire 4 × 50 ms pulses; CH3 stays OFF
- **Step 3** (dwell 0.5 s): All channels set to OFF

---

## Appendix B — Quick Dashboard Reference

| UI Element | Location | Purpose |
|---|---|---|
| BCON indicator (circle) | Beam Pulse status bar — left | Red = disconnected, Green = connected |
| "Interlock: / Watchdog:" label | Beam Pulse status bar — centre | Live safety status text |
| Connect / Disconnect / Reconnect | Beam Pulse status bar — right | Open or close serial port |
| Log: label | Beam Pulse status bar — far right | Most recent event summary |
| Watchdog (ms) entry + Set | Beam Pulse status bar — second row | Configure firmware watchdog timeout |
| Mode drop-down | Each channel card | Select OFF / DC / PULSE / PULSE_TRAIN |
| Duration (ms) entry | Each channel card | Pulse width for PULSE and PULSE_TRAIN |
| Count entry | Each channel card | Repeat count for PULSE_TRAIN (≥ 2) |
| Status / Remaining labels | Each channel card | Live hardware register readback |
| Sync Start | External control panel | Start all enabled channels together |
| Sync Stop | External control panel | Immediately stop all channels |
| Load CSV | CSV buttons area | Open a `.csv` sequence file |
| Save Template | CSV buttons area | Write a reference template CSV |
| Run Sequence | CSV buttons area | Start the loaded sequence (armed + loaded) |
| Stop Sequence | CSV buttons area | Halt a running sequence (always enabled) |
