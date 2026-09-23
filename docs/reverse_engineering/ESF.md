# ESF Reverse-Engineering Notes

This document records the currently understood parts of InSite `.ESF` event files.
It is intentionally a living description: update it when parser refinements reveal more structure.

Implemented parser: `src/richterpy/io/esf.py`.

## File Layout

An ESF file starts with a little-endian integer offset header, followed by waveform channel payloads and a footer metadata block.

Current header interpretation:

| Position | Type | Meaning |
|---:|---|---|
| 0 | `uint32` | Channel count |
| 1..N | `uint32` | One-based channel offsets relative to waveform payload |
| N+1 | `uint32` | One-based absolute footer offset |
| N+2 | `uint32` | Sample encoding, observed `2` |
| N+3 | `uint32` | Sample width bytes, observed `8` |

Waveform samples are little-endian `float64` values.

The parser reads channel count and sample count from this header instead of assuming fixed `4 x 65536` waveforms.

Validated examples:

| File | Channels | Samples/channel | Footer offset bytes |
|---|---:|---:|---:|
| `20250403_0001.ESF` | 4 | 65536 | 2097184 |
| `20250403_0429.ESF` | 4 | 30349 | 971200 |

## Footer Field Tables

The footer contains field tables. A field table starts with:

```text
uint32 next_pointer
uint32 field_count
uint32 value_bytes
uint32[field_count] field_ids
byte[value_bytes] values
```

Field type is inferred from field ID ranges and known base IDs:

| Field ID range/type | Value type |
|---|---|
| known base int IDs | `int32` |
| `1000 <= id < 2000` | `int32` |
| known base float IDs | `float64` |
| `2000 <= id < 3000` | `float64` |
| `3000 <= id < 4000` | string with explicit length |
| `4000 <= id < 5000` | binary/vector block |

## Event-Level Fields

Current named event fields:

| Name | Field ID |
|---|---:|
| `number` | 0 |
| `enabled` | 31 |
| `located` | 32 |
| `north` | 35 |
| `east` | 36 |
| `down` | 37 |
| `loc_mag` | 50 |
| `loc_error` | 52 |
| `loc_units` | 53 |
| `residual` | 2000 |
| `dec_sec` | 2041 |
| `snr` | 2052 |
| `rms_noise` | 2053 |
| `mon_dist` | 2056 |
| `p_noise` | 2057 |
| `s_noise` | 2058 |
| `p_auto_func` | 2060 |
| `s_auto_func` | 2061 |
| `confidence` | 2062 |
| `t0` | 2072 |
| `label` | 3000 |
| `event_stem` | 3003 |

## Per-Channel Fields

After the main event field table, ESF files can contain one per-channel field table per waveform channel.

Current named per-channel integer fields:

| Name | Field ID |
|---|---:|
| `channel_index` | 0 |
| `sample_count` | 1 |
| `p_timepick_sample_1based` | 4 |
| `enabled` | 6 |
| `located` | 13 |
| `instrument_number` | 14 |
| `channel_number` | 15 |
| `axis_number` | 47 |
| `motion` | 48 |
| `sensor_type` | 51 |
| `pick_valid` | 52 |
| `trigger_sample` | 55 |
| `p_timepick_enabled` | 1001 |
| `tp_timepick_sample_1based` | 1002 |
| `ts_timepick_sample_1based` | 1003 |
| `p_search_enabled` | 1009 |
| `p_search_start_sample` | 1010 |
| `p_search_end_sample` | 1011 |
| `p_window_enabled` | 1012 |
| `p_window_half_width_samples` | 1013 |
| `p_pick_window_enabled` | 1015 |
| `p_pick_window_half_width_samples` | 1016 |
| `p_pick_window_start_sample` | 1017 |
| `p_pick_window_end_sample` | 1018 |
| `p_pick_window_start_sample_alt` | 1019 |
| `p_pick_window_end_sample_alt` | 1020 |
| `s_pick_window_start_sample` | 1021 |
| `s_pick_window_end_sample` | 1022 |

## Pick Timing

Confirmed P-pick mapping:

```text
P pick seconds from event origin = (p_timepick_sample_1based - 1) / 10_000_000
```

This matches:

- `data/m0013/export/m0013 instrument data.csv` field `Ptimepick`
- ATF `PTime` headers for checked companion events

`TPtimepick` and `TStimepick` are currently decoded as sample indices, but their final semantics remain less certain.

S-pick encoding is unconfirmed because available validation rows have blank `Stimepick` values and checked ATF files have `STime = 0`.

## Catalog Semantics

ESF-native catalog building can produce ObsPy `Catalog` / QuakeML.

- Without datum: local `north/east/down/loc_units` stay in origin comments; geographic origin fields are not populated.
- With explicit datum or `datum_config`: geographic latitude/longitude/depth are populated.
- Picks are only created when waveform identity is explicit via `inventory=`, `inventory_path=`, or `waveform_id_map=`.
- Waveform IDs are not fabricated.

## Known Validation Caveats

Full local validation decoded 917 ESFs and checked 413 CSV rows.

Known ESF-vs-CSV mismatches appear to be CSV post-processing/version differences:

- `20250403_0253.ESF`: `SNR`, `RMS_Noise`, `P_Noise`, `P_AutoFunc`
- `20250403_0438.ESF`: `P_AutoFunc`
- `20250403_0440.ESF`: `P_AutoFunc`

Do not remap these fields unless a direct ESF source is found.

## Currently Not Understood

The following ESF binary content is known to exist or is likely present, but is not currently decoded into a stable schema:

- Complete meaning of the `next_pointer` field in all footer field tables.
- Whether footer field tables form a linked list, a nested record structure, or both.
- Complete field-ID dictionary for event-level fields beyond the IDs listed above.
- Complete field-ID dictionary for per-channel fields beyond the IDs listed above.
- Semantics of binary/vector fields with IDs in the `4000..4999` range.
- Semantics of all string fields with IDs in the `3000..3999` range beyond `label` and `event_stem`.
- Meaning of base integer IDs `12`, `33`, `34`, and `51` when present.
- Meaning of base float IDs not currently named, including IDs `39`, `40`, `41`, `43`, `44`, `45`, `47`, `48`, and `49`.
- Exact meaning of `TPtimepick` and `TStimepick`; they are decoded as sample indices but not assigned physical/catalog semantics.
- S-pick encoding. Fields `1021` and `1022` look like S-pick window bounds, but no validated non-empty S pick has been observed.
- Meaning of `trigger_sample` relative to event origin, P pick, and waveform sample zero.
- Whether per-channel string fields after the integer/float portion contain sensor labels, processing state, or other useful metadata.
- Whether waveform payload values are calibrated physical units, volts, or processed amplitudes for all ESF variants.
- How ESF layout and field IDs vary across InSite versions and acquisition/export settings.
- Whether the six ESF-vs-CSV mismatches are caused by CSV post-processing, manual edits, alternate event records, or fields not yet decoded.

## Open Questions

- Confirm S-pick encoding with non-empty `Stimepick` / non-zero ATF `STime` data.
- Decode more per-channel fields and string/vector fields.
- Validate against ESF files from other experiments and software versions.
