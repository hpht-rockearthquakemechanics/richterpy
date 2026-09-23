# RPT Location Report Notes

This document records the currently understood content of InSite `.RPT` location report files.
Unlike `.pcf` and `.ESF`, this is a text report rather than a binary format, but it captures useful intermediate location-algorithm information that is not present in the exported CSV files.

Observed file: `data/m0013/locations/m00013.RPT`.

## Scope

The report appears to be a log of InSite location runs.
It can contain multiple processing blocks for the same event, likely reflecting repeated processing or changed location settings.

Current observations for `m00013.RPT`:

- 2301 `Processing Event ...` blocks.
- 2037 blocks with a `Final N/E/D` solution.
- 482 unique event numbers, spanning event IDs `1..917`.
- Every event ID present in `data/m0013/export/m0013 event data.csv` is present in the RPT.
- The RPT contains many additional event IDs not present in the exported event CSV.
- Some event IDs repeat up to 10 times.

## Per-Run Header

Each location run starts with a line like:

```text
Processing Event 4 (03-04-2025 14:28:56) in Component 20250403 with 4P and 4S
```

Useful fields:

- Event number.
- Event date/time.
- Component/date folder.
- Number of P picks available at the start of the run.
- Number of S picks available at the start of the run.
- Processing timestamp from the following `Processed ...` line.
- Whether P and S arrivals were used.

## Sensor Information

The report includes sensor coordinates and arrival times:

```text
Sensor Information Used (Units = mm):
C/I    N       E       D       Tp       Ts
```

Useful fields:

- Instrument/channel index.
- Sensor local coordinates in millimetres.
- `Tp`, the P arrival time used by the locator.
- `Ts`, the S arrival time used by the locator.

This is potentially useful for S-pick validation, because the local instrument CSV currently has blank `Stimepick` values for available validation rows, while the RPT contains many non-zero `Ts` values.

## Iterative Location Passes

Each run can contain multiple `PASS #...` sections.

Useful fields:

- Number of independent sensors in the pass.
- Grid-search bounds for `N/E/D`.
- Grid-search located point.
- Outlier factors by arrival, for example `P1=... S1=...`.
- Event source time from mean arrivals.
- Arrival residuals by phase and instrument.
- RMS residual and RMS error.
- Dropped arrivals, for example:

```text
Arrival P1 has largest residual above 100.0 ... dropping arrival!
```

These pass-level details are not present in the CSV event export and could support future quality-control or association diagnostics.

## Final Solution

Runs that converge include a final block like:

```text
Final N=  80.643 E= 170.000 D=  -4.360 with units mm
Number of P-picks = 2
Number of S-picks = 0
Location Magnitude from waveform RMS amplitudes = -1.85
Event Origin Time = 03-04-2025 14:28:56.518
```

Useful fields:

- Final local `N/E/D` in millimetres.
- Final retained P-pick count.
- Final retained S-pick count.
- Location magnitude from waveform RMS amplitudes.
- Event origin time.

For events present in the CSV, the last RPT run often matches the CSV final location/magnitude closely, but the RPT may also contain earlier runs with different retained arrivals and different solutions.

## Potential Uses

- Validate or recover S-pick timing from `Ts` values.
- Inspect which arrivals were dropped during InSite outlier rejection.
- Compare earlier and later repeated location runs for the same event.
- Recover location diagnostics not present in `m0013 event data.csv`.
- Possibly build a future `G -> O4 -> O` location-report converter.

## Currently Not Understood

- Exact units/reference for `Tp`, `Ts`, residuals, and event source time. They appear to be relative timing values, but the reference epoch and scale should be confirmed before using them as catalog picks.
- How repeated runs for the same event should be ordered semantically. The last run often matches CSV output, but this should be validated systematically.
- Whether all RPT event IDs correspond to ESF/BSF/ATF files or include failed/unexported/manual location attempts.
- Meaning of some suffixes in outlier factors, such as `(NP<3)` and `(NS<3)`, beyond the likely interpretation of too few P/S picks.
- Whether `SH-picks` and `SV-picks` can be mapped directly to S phases in ObsPy/Pyrocko.
- Whether origin times in RPT are rounded/truncated relative to CSV/ESF higher-precision times.
