# Plan: Fix G9SP Active SIC Light

## Context

The "G9SP Active" indicator light on the Interlocks dashboard is showing incorrect status. The current condition ties the light to `sitsf_bits[12]` — the **Safety Input Terminal Status Flag** for input 12, which is wired to a momentary push button. This is the wrong signal to use: the status flag reflects whether the input _terminal has a hardware error_, and a momentary button can cause transient or unexpected states there.

The correct indicator of whether the G9SP safety controller is active is `g9_active`, which is already computed in `g9_driver.py` as the AND of the **Safety Output Terminal Status Flag** and **Safety Output Terminal Data Flag** for output bit 4:
```python
binary_data['sotsf'][4] & binary_data['sotdf'][4]  # g9_active
```
This correctly reflects whether the G9SP output is both ON and error-free (i.e., the controller is in its active run state).

## Root Cause

In `interlocks.py` lines 331–335:
```python
# make sure that the data output indicates button and been pressed and the input is not off/error
if g9_active == sitsf_bits[12] == 1:
    self.update_interlock("G9SP Active", True, all_good)
else:
    self.update_interlock("G9SP Active", False, all_good)
```

The condition `sitsf_bits[12] == 1` reads the **input status flag** for bit 12 (the momentary SIC button input). If the button is momentary or its terminal has any status issue, this flag can be 0, causing the light to incorrectly show red even when the G9SP controller is fully active.

## Fix

**File:** `subsystem/interlocks/interlocks.py`
**Lines:** 331–335

Remove the erroneous `sitsf_bits[12]` check. The G9SP Active light should depend only on `g9_active`:

```python
# G9SP Active is determined solely by the output terminal state
self.update_interlock("G9SP Active", True, g9_active)
```

`update_interlock` computes `(safety & data) == 1` internally, so passing `True, g9_active` means:
- Green when `g9_active == 1` (output is ON and error-free)
- Red when `g9_active == 0`

## Critical Files

- `subsystem/interlocks/interlocks.py` — lines 331–335 (the buggy condition)
- `instrumentctl/G9SP_interlock/g9_driver.py` — line 253 (where `g9_active` is computed, no change needed)

## Decision: Decouple from `all_good`

Confirmed: the G9SP Active light should reflect only the G9SP's own output state. It will be green whenever `g9_active == 1`, independent of other interlocks. The separate "All Interlocks" indicator covers the combined status.

## Verification

1. Run the dashboard with the G9SP connected.
2. With the system in normal operation (G9SP active), verify the "G9SP Active" light turns green.
3. Trigger a safety stop (e.g., press E-STOP) — the G9SP output should deactivate, turning the light red.
4. Confirm the light no longer flickers based on momentary button state.
