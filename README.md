# RichterPy

Richter/InSite data tools for waveform parsing and metadata conversion.

## Pipeline Stages

This project follows the `RICHTER.md` flow:

- `B -> O1 -> O`: raw streams and handwritten station metadata
- `B & C -> O2 -> O`: raw streams and PCF station metadata
- `E -> O3 -> O`: BSF or ESF or ATF streams, PCF station metadata, ESF event metadata
- `G -> O4 -> O`: event locations
- `O -> P`: optional Pyrocko/Snuffler export

## Binary Layout

For the files in `data/20250403/`, the `.ESF` file is structured as:

1. `4` little-endian `float64` header values
2. `4` consecutive waveform blocks
3. `65536` samples per channel
4. `float64` waveform data
5. footer metadata stored as a mixed binary block

So the main waveform payload is:

- `channel_count = 4`
- `samples_per_channel = 65536`
- `sample_rate = 10_000_000.0`

## What Is Decoded

The parser currently extracts:

- waveform matrix `(65536, 4)`
- event label text
- channel records like `004S001007richter010Selvadurai`
- footer doubles such as location, magnitude, noise, and confidence
- packed `int32` event metadata such as event number, flags, and counters

## Files

- `src/richterpy/insite/project_metadata.py`: PCF/project metadata helpers
- `src/richterpy/insite/event_waveforms.py`: ESF/BSF waveform helpers
- `src/richterpy/obspy/station_inventory.py`: ObsPy station inventory output
- `src/richterpy/obspy/event_catalog.py`: ObsPy event catalog output
- `src/richterpy/pyrocko/snuffler_export.py`: optional Pyrocko export
- `src/richterpy/io/esf.py`: low-level ESF/BSF/PCF parser and plotting helpers
- `src/richterpy/`: canonical package source tree
- `richterpy/__init__.py`: import shim for working-tree use
- `esf_waveforms_to_obspy.py`: legacy-compatible ESF waveform CLI
- `project_metadata_to_stationxml.py`: project metadata to StationXML CLI
- `event_data_to_quakeml.py`: event metadata to QuakeML CLI
- `insite_waveforms_to_snuffler.py`: InSite waveform to Snuffler CLI
- `esf_to_obspy.py`: legacy wrapper around `richterpy.io.esf`
- `esf_interactive.ipynb`: interactive notebook for inspection

## Usage

### Examples

Read ESF waveform data directly:

```python
from richterpy.io.esf import extract_esf

waveform, metadata = extract_esf('data/20250403/20250403_0144.ESF')
```

Write an ESF metadata report:

```python
from richterpy.io.esf import decode_esf_txt

decode_esf_txt('data/m0013/ESF/20250403/20250403_0001.ESF')
```

Plot ESF waveforms:

```python
from richterpy.io.esf import plot_esf_png

plot_esf_png('data/m0013/ESF/20250403/20250403_0001.ESF')
```

Build an ObsPy stream from ESF:

```python
from richterpy.io.esf import read_esf

stream, metadata = read_esf('data/20250403/20250403_0144.ESF')
```

Convert PCF project metadata to StationXML (`C -> O2`):

```bash
python project_metadata_to_stationxml.py m0013
python project_metadata_to_stationxml.py --csv-path /path/to/custom.csv --output-path /tmp/custom.xml
```

Convert event CSV metadata to QuakeML (`E -> O3`):

```bash
python event_data_to_quakeml.py m0013
python event_data_to_quakeml.py --csv-path /path/to/custom-event.csv --output-path /tmp/custom-event.xml
```

Export triggered waveforms to Snuffler (`O -> P`):

```bash
python insite_waveforms_to_snuffler.py m0013 --output-mode snuffler
python insite_waveforms_to_snuffler.py --station-xml-path /path/to/station.xml --event-xml-path /path/to/event.xml --data-root /path/to/waveforms
```

Print a decoded ESF report:

```bash
python esf_waveforms_to_obspy.py data/20250403/20250403_0144.ESF --report
python esf_waveforms_to_obspy.py --esf-path "/path/to/custom.ESF" --component-dir "/path/to/component" --event-csv-path "/path/to/event data.csv" --instrument-csv-path "/path/to/instrument data.csv" --report
```

Installed console commands:

```bash
richter-project-metadata data/m0013/m0013.pcf
richter-event-waveforms data/m0013/ESF/20250403/20250403_0001.ESF --plot
richter-stationxml m0013
richter-quakeml m0013
richter-snuffler m0013 --output-mode obspy
richter-esf data/m0013/ESF/20250403/20250403_0001.ESF --report
```

Legacy compatibility commands still work:

```bash
python esf_to_obspy.py data/20250403/20250403_0144.ESF --report
python stations_csv2stationxml.py m0013
python events_csv2quakeml.py m0013
python insitedata2snuffler.py m0013 --output-mode obspy
```

### Stage Notes

- `B` data is currently handled by the low-level readers in `src/richterpy/io/`.
- `C` is represented by `src/richterpy/insite/project_metadata.py` and `src/richterpy/obspy/station_inventory.py`.
- `E` is represented by `src/richterpy/insite/event_waveforms.py` and `src/richterpy/obspy/event_catalog.py`.
- `G` is reserved for `src/richterpy/insite/location_reports.py`.
- `O1`, `O2`, `O3`, and `O4` are the ObsPy-facing conversion layers.
- `P` is the optional Pyrocko/Snuffler export path.

## Notes

- The ATF files are optional.
- When present, they are useful for calibration and verification.
- The ESF parser works standalone without them.
- The CLI entrypoints accept explicit path overrides for CSV, XML, waveform, and report companion files.

## Tests

- Minimal smoke tests live under `tests/`.
- Run them with `pytest` from the repository root.
- `tests/test_snuffler_smoke.py` is a small Pyrocko Snuffler smoke script, so it may open an interactive window when executed.
