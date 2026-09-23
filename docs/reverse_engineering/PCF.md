# PCF Reverse-Engineering Notes

This document records the currently understood parts of InSite `.pcf` project files.
It is intentionally a living description: update it when parser refinements reveal more structure.

## Scope

The current parser focuses on station metadata needed to build StationXML.
It does not claim to decode every PCF record type.

Implemented parser: `src/richterpy/io/pcf.py`.

## Station Record Discovery

Station records are found by scanning for length-prefixed ASCII triplets:

- `Channel_Label`, usually like `S001`
- `Owner_Array`, for example `richter`
- `Instrument_Label`, for example `Selvadurai` or `Nardi`

The full station label is the concatenated length-value run, for example:

```text
004S001007richter010Selvadurai
```

The parser no longer relies on hardcoded station labels or coordinates.

## Numeric Station Block

Immediately before each station label run, the parser expects a numeric station block.

Current interpretation:

```text
offset relative to label: -144 bytes
type: 14 little-endian float64 values
```

Decoded values:

| Index | Field |
|---:|---|
| 0 | `North` |
| 1 | `East` |
| 2 | `Down` |
| 3 | `Orientation_N` |
| 4 | `Orientation_E` |
| 5 | `Orientation_D` |
| 6 | `Local_Unit_M` |
| 7 | `P_Station_Correction` |
| 8 | `On` |
| 9 | `Gain` |
| 10 | `Vmax` |
| 11 | `LowFreq` |
| 12 | `HighFreq` |
| 13 | `Axis_Number` |

Validation currently rejects blocks with invalid `Local_Unit_M` or implausibly large values.

## Station Header Integers

Immediately before the numeric station block, the parser reads a small integer header.

Current interpretation:

```text
offset relative to label: -176 bytes
type: 8 little-endian int32 values
```

Decoded values:

| Int index | Field |
|---:|---|
| 5 | `Instrument_Number` |
| 6 | `Channel_Number` |

The same values are currently also used as `Array_Instrument_Number` and `Array_Channel_Number`.

## StationXML Channel Mapping

`src/richterpy/convert/stations.py` converts orientation vectors to SEED-style channel suffixes by dominant absolute component:

| Dominant orientation component | Channel suffix |
|---|---|
| `Orientation_D` | `Z` |
| `Orientation_N` | `2` |
| `Orientation_E` | `1` |

The full channel code is currently `ND<suffix>`, for example `NDZ`, `ND1`, or `ND2`.
Polarity sign is ignored in the channel code.

## Known Validation

Validated against `data/m0013/m0013.pcf`:

- 4 station records found.
- Station coordinates and local units match expected project values.
- Channel 4 orientation is decoded as `(0.0, -1.0, 0.0)`, producing channel `ND1`.

## Currently Not Understood

The following PCF binary content is known to exist or is likely present, but is not currently decoded into a stable schema:

- Global project header structure.
- Project-level metadata such as project name, creation date, acquisition configuration, and processing settings.
- Exact meaning of most integer values in the 8-int station header.
- Whether the station header contains separate instrument, channel, array, axis, or enable-state fields beyond the two currently used integers.
- Record boundaries for the whole file. Current parsing is pattern-based around station labels rather than a complete top-level record iterator.
- Any checksum, version marker, record count, or table-of-contents structure if present.
- Relationship between PCF station blocks and any additional instrument/sensor calibration records elsewhere in the file.
- Full semantics of `Motion`, `Axis_Number`, `Gain`, `Vmax`, `LowFreq`, and `HighFreq`; these are extracted but not yet used beyond preservation.
- Whether local coordinate datum/reference-frame information is stored in PCF or only known externally.
- Whether string records outside station labels carry meaningful metadata currently ignored by the parser.
- How PCF structure varies across InSite versions and experiments.

## Open Questions

- Meaning of all 8 station header integers.
- Whether station orientation polarity should be preserved in StationXML dip/azimuth fields.
- Additional PCF record types beyond station metadata.
- Validation against PCF files from other experiments.
