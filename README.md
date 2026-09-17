# RichterPy

Richter/InSite data tools for waveform parsing and metadata conversion.
Vibe-coded with GPT-5.4 and 5.5 in july-september 2026, starting from existing code debugged by humans.

## Pipeline Stages

`RICHTER.md` is the ground truth for pipeline naming.

- `A`: record stream.
- `A1`: `.wve` and `.srm` raw stream files.
- `A2`: `sensorarray/EXPERIMENT.csv` station metadata.
- `B`: make InSite project.
- `B1`: `EXPERIMENT/` project folder with `EXPERIMENT.pcf` and optional exports.
- `C`: trigger events.
- `C1`: triggered event products, including `BSF/`, optional `ESF/`, optional `ATF`, and optional exported CSVs.
- `O`: ObsPy objects and files.
- `P`: optional Pyrocko/Snuffler view/export.

Effective processing stages implemented here:

- `A1 & A2 -> O1 -> O`: raw `.srm/.wve` streams plus station CSV into ObsPy `Stream` and StationXML.
- `A2 & B1 -> O2 -> O`: raw `.srm/.wve` streams plus PCF-derived station metadata into ObsPy `Stream` and StationXML.
- `B1 & C1 -> O3 -> O`: triggered BSF/ESF/ATF streams plus PCF-derived station metadata into ObsPy `Stream`.
- `C1 -> O4 -> O`: ESF-native event metadata into ObsPy `Catalog` / QuakeML.
- `O -> P`: optional Pyrocko/Snuffler visualization.

Stage-to-code mapping:

- `O1`: `richterpy.convert.stations.convert_stations(...)` plus `richterpy.convert.snuffler.build_master_stream(...)`.
- `O2`: `richterpy.io.pcf.convert_pcf_to_csv(...)`, then `convert_stations(...)`, then `build_master_stream(...)`.
- `O3`: `richterpy.io.bsf.build_bsf_stream(...)`, `richterpy.io.esf.build_esf_stream(...)`, or `richterpy.io.atf.build_atf_stream(...)`.
- `O4`: `richterpy.io.esf.build_esf_catalog_from_esfs(...)` or CLI `richter-esf-quakeml`.
- `P`: `richterpy.convert.snuffler` helpers and Pyrocko `trace.snuffle(...)`.

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
- `src/richterpy/io/esf.py`: low-level ESF parser, ESF stream builder, and ESF catalog builder
- `src/richterpy/io/bsf.py`: BSF stream builder
- `src/richterpy/io/atf.py`: ATF stream builder
- `src/richterpy/io/pcf.py`: PCF station metadata extraction and PCF-to-CSV helper
- `src/richterpy/`: canonical package source tree
- `richterpy/__init__.py`: import shim for working-tree use
- `project_metadata_to_stationxml.py`: source-tree wrapper for StationXML conversion
- `event_data_to_quakeml.py`: source-tree wrapper for CSV event metadata to QuakeML
- `esf_to_quakeml.py`: source-tree wrapper for ESF-native QuakeML generation
- `insite_waveforms_to_snuffler.py`: source-tree wrapper for InSite waveform to Snuffler export
- `esf_waveforms_to_obspy.py` / `esf_to_obspy.py`: source-tree wrappers around `richterpy.io.esf`
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

Build StationXML from CSV station metadata (`A2 -> O1`):

```bash
richter-stationxml --csv-path data/m0013/sensorarray/m0013.csv --output-path data/playground/m0013.xml --datum-config config/MEERA.ini
```

Build StationXML from PCF project metadata (`B1 -> O2`):

```python
from richterpy.io.pcf import convert_pcf_to_csv
from richterpy.convert.stations import convert_stations

convert_pcf_to_csv("data/m0013/m0013.pcf", output_path="data/playground/m0013.pcf.csv")
convert_stations(
    csv_path="data/playground/m0013.pcf.csv",
    output_path="data/playground/m0013.xml",
    datum_config="config/MEERA.ini",
)
```

Decode a PCF report for inspection (`B1` diagnostics):

```bash
richter-project-metadata data/m0013/m0013.pcf
```

Convert exported event CSV metadata to QuakeML, when available (`C1 -> O4`, CSV path):

```bash
python event_data_to_quakeml.py --csv-path "data/m0013/export/m0013 event data.csv" --output-path data/playground/m0013.events.xml --datum-config config/MEERA.ini
python event_data_to_quakeml.py --csv-path /path/to/custom-event.csv --output-path /tmp/custom-event.xml --datum-config config/MEERA.ini
```

Convert ESF-native event metadata to QuakeML (`C1 -> O4`, preferred ESF-native path):

```bash
python esf_to_quakeml.py data/m0013/ESF/20250403 --datum-config config/MEERA.ini
python esf_to_quakeml.py data/m0013/ESF/20250403/20250403_0001.ESF --output-path /tmp/event.xml --datum-config config/MEERA.ini
```

Export ObsPy products to Snuffler (`O -> P`):

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
richter-stationxml --csv-path data/m0013/sensorarray/m0013.csv --output-path data/playground/m0013.xml --datum-config config/MEERA.ini
richter-quakeml --csv-path "data/m0013/export/m0013 event data.csv" --output-path data/playground/m0013.events.xml --datum-config config/MEERA.ini
richter-esf-quakeml data/m0013/ESF/20250403 --datum-config config/MEERA.ini
richter-snuffler m0013 --output-mode obspy
richter-esf data/m0013/ESF/20250403/20250403_0001.ESF --report
```

Legacy compatibility commands still work:

```bash
python esf_to_obspy.py data/20250403/20250403_0144.ESF --report
python esf_to_quakeml.py data/m0013/ESF/20250403 --datum-config config/MEERA.ini
python stations_csv2stationxml.py --csv-path data/m0013/sensorarray/m0013.csv --output-path data/playground/m0013.xml --datum-config config/MEERA.ini
python project_metadata_to_stationxml.py --csv-path data/m0013/sensorarray/m0013.csv --output-path data/playground/m0013.xml --datum-config config/MEERA.ini
python events_csv2quakeml.py --csv-path "data/m0013/export/m0013 event data.csv" --output-path data/playground/m0013.events.xml --datum-config config/MEERA.ini
python insitedata2snuffler.py m0013 --output-mode obspy
```

### Stage Notes

- `A1`, `A2`, `B1`, `C1`, `O1`, `O2`, `O3`, `O4`, `O`, and `P` follow `RICHTER.md`.
- `O1`, `O2`, `O3`, and `O4` are the ObsPy-facing conversion layers implemented by this package.
- `P` is the optional Pyrocko/Snuffler export path.

## Notes

- The ATF files are optional.
- When present, they are useful for calibration and verification.
- The ESF parser works standalone without them.
- The CLI entrypoints accept explicit path overrides for CSV, XML, waveform, and report companion files.

## Tests

- Minimal smoke tests live under `tests/`.
- Run the non-interactive tests with `python -m unittest tests.test_pcf tests.test_esf_metadata tests.test_io_smoke` from the repository root.
- `tests/test_snuffler_smoke.py` is a small Pyrocko Snuffler smoke script, so it may open an interactive window when executed.
