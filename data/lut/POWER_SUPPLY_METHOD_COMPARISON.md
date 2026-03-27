---
header-includes:
	- \usepackage{graphicx}
---

# Power Supply LUT Method Comparison

Date: 3/27/2026
Author: Shobhin Basu

## Objective

This document compares raw and cleaned power-supply LUT outputs for each cleaning method and shows how each cleaning policy changes the LUT shape.

## Raw Data Source

Note on the origin of the current datasets:

- Data was downloaded as CSV from the LUT tab of the Google Sheet used during the July 11, 2025 experiment, and the resulting file was renamed to Raw_Cbmark_Beam_A_07_2025.csv.

Google Sheet link:
[Google Sheet (LUT tab source)](https://docs.google.com/spreadsheets/d/1T73CYgSkFAcI7QR085y3sOdtns9vNCIwv82ZkwADaoQ/edit?usp=sharing)

Current raw data columns:

- beam_current
- voltage
- heater_current

Note: A temporary update was made to `data/lut/clean.py` to run and compare all three cleaning methods during this evaluation.

## Input and Outputs

- Raw input file: [power_supply/Raw_Cbmark_Beam_A_07_2025.csv](power_supply/Raw_Cbmark_Beam_A_07_2025.csv)
- max_beam output: [power_supply/Raw_Cbmark_Beam_A_07_2025__max_beam.csv](power_supply/Raw_Cbmark_Beam_A_07_2025__max_beam.csv)
- min_current_95pct_beam output: [power_supply/Raw_Cbmark_Beam_A_07_2025__min_current_95pct_beam.csv](power_supply/Raw_Cbmark_Beam_A_07_2025__min_current_95pct_beam.csv)
- median_top_band output: [power_supply/Raw_Cbmark_Beam_A_07_2025__median_top_band.csv](power_supply/Raw_Cbmark_Beam_A_07_2025__median_top_band.csv)

## Shared Pre-Processing (Applies to All 3 Methods)

The cleaning workflow has two phases:

1. Pre-processing: parse/filter/round/sort/group the dataset (everything before method-specific duplicate-resolution choices).
2. Method selection: apply Method 1, Method 2, or Method 3 to choose one representative row per voltage bin (each discrete heater-voltage value after rounding).

Below is the algorithm for Phase 1 (pre-processing):

1. Parse each CSV row to numeric values: beam_current, voltage, heater_current.
2. Drop rows with missing/non-numeric values.
3. Drop rows with any negative value.
4. Drop non-operational rows where beam_current <= 0.001 mA, voltage <= 0.001 V, or heater_current <= 0.001 A.
5. Round voltage and heater_current to 2 decimals.
6. Sort all remaining rows by (heater_current, voltage, beam_current).
7. Group all sorted rows by voltage (each discrete heater-voltage value after rounding).

Important interpretation:

- Per-voltage selection happens over the full post-filtered, sorted dataset.
- So "max at a voltage" means max in that full retained dataset after non-operational filtering.

## Method Selection

### Overall Recommendation

Recommended method: Method 2 (`min_current_95pct_beam`).

Overall choice summary:

- The Beam Current vs Voltage curves across Methods 1-3 look very similar, and Method 2 is the most balanced choice because it keeps near-peak beam while reducing heater-current demand.

Rationale:

- It keeps beam current close to peak while reducing heater demand.
- It usually provides the best practical balance for Cathode Heating runtime use.
- It is simpler and more predictable than median-top-band while being more conservative than max-beam.

Method-specific guidance:

- Choose Method 1 (`max_beam`) when maximum beam is the sole priority.
- Choose Method 3 (`median_top_band`) when measurements are especially noisy and you want robust representative points.

\newpage

## Method 1: max_beam

Description:

- Select the highest beam-current point available at each discrete voltage.

Explanation:

- Algorithm:
1. Run the shared pre-processing above.
2. For each voltage bin (each discrete value of voltage after rounding), select the row with maximum beam_current.
3. If there is a tie in beam_current, pick the one with higher heater_current.
4. Emit one cleaned row per voltage, sorted by voltage.
- Goal: practical performance-first approximation.
- Result: one output row per voltage after filtering non-operational rows.

### Graphs

Most important plot: top-left (Beam Current vs Voltage). This is the primary curve to compare method behavior because it shows beam current delivered at each voltage, and that beam current is used downstream to compute emission and grid-current predictions in Cathode Heating.

Raw and cleaned overlay:

\begin{center}
\begin{minipage}[t]{0.48\linewidth}
\centering
\includegraphics[width=\linewidth]{data/lut/power_supply/plots/Raw_Cbmark_Beam_A_07_2025_max_beam_raw_vs_clean_beam_vs_voltage.png}
\end{minipage}\hfill
\begin{minipage}[t]{0.48\linewidth}
\centering
\includegraphics[width=\linewidth]{data/lut/power_supply/plots/Raw_Cbmark_Beam_A_07_2025_max_beam_raw_vs_clean_heater_vs_voltage.png}
\end{minipage}

\vspace{0.6em}

\begin{minipage}[t]{0.48\linewidth}
\centering
\includegraphics[width=\linewidth]{data/lut/power_supply/plots/Raw_Cbmark_Beam_A_07_2025__max_beam_beam_vs_voltage_colored_by_heater.png}
\end{minipage}\hfill
\begin{minipage}[t]{0.48\linewidth}
\centering
\includegraphics[width=\linewidth]{data/lut/power_supply/plots/Raw_Cbmark_Beam_A_07_2025__max_beam_beam_vs_heater.png}
\end{minipage}
\end{center}

### Strengths / Weaknesses

Strengths:

- Maximizes beam output at each voltage bin.
- Very simple behavior that is easy to reason about and validate.
- Useful when absolute beam performance is the primary objective.

Weaknesses:

- Can choose higher-than-necessary heater current for a given voltage.
- More sensitive to optimistic/noisy peak points in a bin.
- May produce less conservative thermal operating points.

\newpage

## Method 2: min_current_95pct_beam

Description:

- Select a near-peak beam point (>=95% of local max) using the lowest heater current.

Explanation:

- Algorithm:
1. Run the shared pre-processing above.
2. For each voltage bin (each discrete value of voltage after rounding), compute max_beam in that bin.
3. Compute threshold = 0.95 * max_beam.
4. Keep candidate rows with beam_current >= threshold.
5. From candidates, select the row with minimum heater_current.
6. If there is a tie in heater_current, pick the one with higher beam_current.
7. Emit one cleaned row per voltage, sorted by voltage.
- Goal: near-peak beam with lower heater burden.
- Result: one output row per voltage after filtering non-operational rows.

### Graphs

Most important plot: top-left (Beam Current vs Voltage). This is the primary curve to compare method behavior because it shows beam current delivered at each voltage, and that beam current is used downstream to compute emission and grid-current predictions in Cathode Heating.

Raw and cleaned overlay:

\begin{center}
\begin{minipage}[t]{0.48\linewidth}
\centering
\includegraphics[width=\linewidth]{data/lut/power_supply/plots/Raw_Cbmark_Beam_A_07_2025_min_current_95pct_beam_raw_vs_clean_beam_vs_voltage.png}
\end{minipage}\hfill
\begin{minipage}[t]{0.48\linewidth}
\centering
\includegraphics[width=\linewidth]{data/lut/power_supply/plots/Raw_Cbmark_Beam_A_07_2025_min_current_95pct_beam_raw_vs_clean_heater_vs_voltage.png}
\end{minipage}

\vspace{0.6em}

\begin{minipage}[t]{0.48\linewidth}
\centering
\includegraphics[width=\linewidth]{data/lut/power_supply/plots/Raw_Cbmark_Beam_A_07_2025__min_current_95pct_beam_beam_vs_voltage_colored_by_heater.png}
\end{minipage}\hfill
\begin{minipage}[t]{0.48\linewidth}
\centering
\includegraphics[width=\linewidth]{data/lut/power_supply/plots/Raw_Cbmark_Beam_A_07_2025__min_current_95pct_beam_beam_vs_heater.png}
\end{minipage}
\end{center}

### Strengths / Weaknesses

Strengths:

- Preserves near-maximum beam while preferring lower heater current.
- Better balance between output and heater burden.
- Often gives smoother, more conservative operating points for runtime.

Weaknesses:

- Requires selecting a threshold (95%), which is policy-dependent.
- Can under-select peak beam in bins with sparse points above threshold.
- Behavior changes if raw data distribution shifts significantly.

\newpage

## Method 3: median_top_band

Description:

- Select a representative upper-performance point by using medians within each voltage bin.

Explanation:

- Algorithm:
1. Run the shared pre-processing above.
2. For each voltage bin (each discrete value of voltage after rounding), compute the median of beam_current values.
3. Keep the top-band rows (rows in the upper half of beam_current values for that voltage bin) where beam_current >= bin median.
4. Compute the median heater_current of that top band.
5. Select the top-band row with heater_current closest to the top-band median heater_current (could be above or below the median).
6. If there is a tie in distance, pick the one with higher beam_current.
7. Emit one cleaned row per voltage, sorted by voltage.
- Goal: robust representative point when a voltage bin has noisy clusters.
- Result: one output row per voltage after filtering non-operational rows.

### Graphs

Most important plot: top-left (Beam Current vs Voltage). This is the primary curve to compare method behavior because it shows beam current delivered at each voltage, and that beam current is used downstream to compute emission and grid-current predictions in Cathode Heating.

Raw and cleaned overlay:

\begin{center}
\begin{minipage}[t]{0.48\linewidth}
\centering
\includegraphics[width=\linewidth]{data/lut/power_supply/plots/Raw_Cbmark_Beam_A_07_2025_median_top_band_raw_vs_clean_beam_vs_voltage.png}
\end{minipage}\hfill
\begin{minipage}[t]{0.48\linewidth}
\centering
\includegraphics[width=\linewidth]{data/lut/power_supply/plots/Raw_Cbmark_Beam_A_07_2025_median_top_band_raw_vs_clean_heater_vs_voltage.png}
\end{minipage}

\vspace{0.6em}

\begin{minipage}[t]{0.48\linewidth}
\centering
\includegraphics[width=\linewidth]{data/lut/power_supply/plots/Raw_Cbmark_Beam_A_07_2025__median_top_band_beam_vs_voltage_colored_by_heater.png}
\end{minipage}\hfill
\begin{minipage}[t]{0.48\linewidth}
\centering
\includegraphics[width=\linewidth]{data/lut/power_supply/plots/Raw_Cbmark_Beam_A_07_2025__median_top_band_beam_vs_heater.png}
\end{minipage}
\end{center}

### Strengths / Weaknesses

Strengths:

- More robust to outliers in voltage bins with noisy clusters.
- Selects a representative operating point from upper-performing samples.
- Can stabilize LUT shape when raw measurements are erratic.

Weaknesses:

- More complex logic than the other two methods.
- May not track true peak performance when top-band spread is broad.
- Median-based selection can be less intuitive for tuning/debugging.

## Cathode Heating Runtime Lookup Order (with Units)

The cleaned LUT is loaded by Cathode Heating with columns:

- beam_current (mA)
- voltage (V)
- heater_current (A)

Runtime lookup flow:

1. User sets heater current (A) or heater voltage (V).
2. If current is set, code may look up voltage from current via heater_current -> voltage.
3. If voltage is set, code may look up current from voltage via voltage -> heater_current.
4. Beam prediction is obtained from voltage via voltage -> (heater_current, beam_current).
5. Grid-current prediction is derived from beam/emission model, not from a direct LUT key lookup:
	- emission_current (mA) = beam_current / 0.72
	- grid_current (mA) = 0.28 * emission_current

Key constraint for runtime safety:

- Cathode Heating expects functional mappings (unique values) for both directions used at runtime.
- In practice this means cleaned LUTs should keep one row per voltage and avoid ambiguous heater_current -> voltage mappings.
