from __future__ import annotations

import csv
import math
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from richterpy.coordinates import DEFAULT_DATUM, load_datum_config, local_to_geographic
from richterpy.convert.esf_quakeml import convert_esf_quakeml, default_output_path
from richterpy.convert.stations import convert_stations
from richterpy.io.esf import (
    _footer_bytes,
    build_esf_catalog_from_esfs,
    extract_esf,
    extract_esf_event_metadata,
    parse_esf_layout,
    read_esf,
)
from richterpy.io.pcf import convert_pcf_to_csv


def _make_esf(channel_count: int, samples_per_channel: int) -> bytes:
    header_size = 4 * (channel_count + 4)
    data = np.arange(channel_count * samples_per_channel, dtype="<f8").tobytes()
    footer_offset = header_size + len(data)

    field_ids = [3003, 35, 0, 2041, 50, 3000]
    stem = b"20250101000000_1"
    label = b"Synthetic"
    values = (
        f"{len(stem):03d}".encode("ascii")
        + stem
        + struct.pack("<did", 12.5, 7, 0.123456789)
        + struct.pack("<d", -9.9e100)
        + f"{len(label):03d}".encode("ascii")
        + label
    )
    next_record = footer_offset + 12 + len(field_ids) * 4 + len(values) + 1
    footer = struct.pack("<3I", next_record, len(field_ids), len(values))
    footer += struct.pack(f"<{len(field_ids)}I", *field_ids) + values

    pointers = [1 + index * samples_per_channel * 8 for index in range(channel_count)]
    pointers.append(footer_offset + 1)
    header = struct.pack(f"<{channel_count + 4}I", channel_count, *pointers, 2, 8)
    return header + data + footer


class ESFMetadataTests(unittest.TestCase):
    def test_default_datum_uses_millimeter_local_units(self):
        geo = local_to_geographic(1000.0, 2000.0, 3000.0, DEFAULT_DATUM)
        self.assertAlmostEqual(geo["latitude"], DEFAULT_DATUM.latitude - 1.0 * 9.009e-6)
        self.assertAlmostEqual(geo["longitude"], DEFAULT_DATUM.longitude - 2.0 * 1.209e-5)
        self.assertAlmostEqual(geo["elevation"], DEFAULT_DATUM.elevation - 3.0)
        self.assertAlmostEqual(geo["depth"], 3.0 - DEFAULT_DATUM.elevation)
        self.assertEqual(geo["local_unit_m"], 0.001)

    def test_meera_datum_config(self):
        config_path = Path(__file__).resolve().parents[1] / "config/MEERA.ini"
        datum = load_datum_config(config_path)
        self.assertEqual(datum, DEFAULT_DATUM)

    def test_synthetic_variable_layouts_and_tagged_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            for channel_count, samples_per_channel in [(1, 17), (3, 5), (4, 65536), (12, 23)]:
                with self.subTest(channel_count=channel_count, samples_per_channel=samples_per_channel):
                    path = Path(directory) / "sample.ESF"
                    raw = _make_esf(channel_count, samples_per_channel)
                    path.write_bytes(raw)

                    layout = parse_esf_layout(raw)
                    self.assertEqual(layout["channel_count"], channel_count)
                    self.assertEqual(layout["samples_per_channel"], samples_per_channel)
                    self.assertEqual(_footer_bytes(raw), raw[layout["footer_offset_bytes"]:])

                    waveform, info = extract_esf(path)
                    self.assertEqual(waveform.shape, (samples_per_channel, channel_count))
                    self.assertEqual(info["footer_offset_bytes"], layout["footer_offset_bytes"])
                    np.testing.assert_array_equal(waveform.T.ravel(), np.arange(channel_count * samples_per_channel))

                    metadata = extract_esf_event_metadata(path)
                    self.assertEqual(metadata["number"], 7)
                    self.assertEqual(metadata["north"], 12.5)
                    self.assertIsNone(metadata["loc_mag"])
                    self.assertEqual(metadata["local_time"], "2025-01-01T00:00:00.123456789")

    def test_event_metadata_uses_footer_only_path(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.ESF"
            path.write_bytes(_make_esf(2, 17))
            with patch("richterpy.io.esf.np.memmap", side_effect=AssertionError("memmap should not be used")):
                metadata = extract_esf_event_metadata(path)
        self.assertEqual(metadata["number"], 7)
        self.assertEqual(metadata["north"], 12.5)

    def test_read_esf_uses_memmap_backed_trace_data(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.ESF"
            path.write_bytes(_make_esf(2, 17))
            stream, metadata = read_esf(path)
            self.assertEqual(len(stream), 2)
            self.assertIsInstance(stream[0].data, np.memmap)
            data = np.asarray(stream[0].data).copy()
            del stream
        self.assertEqual(metadata["channel_count"], 2)
        np.testing.assert_array_equal(data, np.arange(17, dtype=np.float64))

    def test_real_samples_if_available(self):
        root = Path(__file__).resolve().parents[1]
        cases = [
            (root / "data/m0013/ESF/20250403/20250403_0001.ESF", 4, 65536, 2097184, 1),
            (root / "data/m0013/ESF/20250403/20250403_0429.ESF", 4, 30349, 971200, 429),
        ]
        if not all(path.exists() for path, *_ in cases):
            self.skipTest("Local ESF validation files are not installed")

        for path, channels, samples, footer, number in cases:
            with self.subTest(path=path.name):
                metadata = extract_esf_event_metadata(path)
                self.assertEqual(metadata["layout"]["channel_count"], channels)
                self.assertEqual(metadata["layout"]["samples_per_channel"], samples)
                self.assertEqual(metadata["layout"]["footer_offset_bytes"], footer)
                self.assertEqual(metadata["number"], number)

    def test_real_channel_pick_metadata_if_available(self):
        root = Path(__file__).resolve().parents[1]
        event_path = root / "data/m0013/ESF/20250403/20250403_0001.ESF"
        instrument_csv_path = root / "data/m0013/export/m0013 instrument data.csv"
        if not event_path.exists():
            self.skipTest("Local ESF validation file is not installed")
        if not instrument_csv_path.exists():
            self.skipTest("Local instrument CSV validation file is not installed")

        metadata = extract_esf_event_metadata(event_path)
        channel_metadata = metadata["channel_metadata"]
        with instrument_csv_path.open(newline="", encoding="utf-8-sig") as source:
            rows = [row for row in csv.DictReader(source) if int(row["Event"]) == 1]
        self.assertEqual(len(channel_metadata), 4)
        by_inst = {int(row["Inst"]): row for row in rows}
        for channel in channel_metadata:
            row = by_inst[channel["index"]]
            if row["Ptimepick"]:
                self.assertAlmostEqual(channel["p_timepick"], float(row["Ptimepick"]))
                self.assertAlmostEqual(channel["tp_timepick"], float(row["TPtimepick"]))
                self.assertAlmostEqual(channel["ts_timepick"], float(row["TStimepick"]))
            else:
                self.assertIsNone(channel.get("p_timepick"))
                self.assertIsNone(channel.get("tp_timepick"))
                self.assertIsNone(channel.get("ts_timepick"))

    def test_event_one_matches_csv_if_available(self):
        root = Path(__file__).resolve().parents[1] / "data/m0013"
        event_path = root / "ESF/20250403/20250403_0001.ESF"
        csv_path = root / "export/m0013 event data.csv"
        if not event_path.exists() or not csv_path.exists():
            self.skipTest("Local CSV/ESF validation files are not installed")

        metadata = extract_esf_event_metadata(event_path)
        with csv_path.open(newline="", encoding="utf-8-sig") as source:
            rows = {(row["Component"], int(row["Number"])): row for row in csv.DictReader(source)}
        row = rows[(metadata["component"], metadata["number"])]
        columns = {
            "north": "North",
            "east": "East",
            "down": "Down",
            "loc_error": "Loc_Error",
            "residual": "Residual",
            "loc_mag": "Loc_Mag",
            "dec_sec": "Dec_Sec",
            "t0": "T0",
            "snr": "SNR",
            "rms_noise": "RMS_Noise",
            "mon_dist": "Mon_Dist",
            "p_auto_func": "P_AutoFunc",
            "confidence": "Confidence",
        }
        for key, column in columns.items():
            expected = float(row[column])
            self.assertTrue(math.isclose(metadata[key], expected, rel_tol=1e-10, abs_tol=1e-12), (key, metadata[key], expected))

        catalog = build_esf_catalog_from_esfs(event_path)
        self.assertEqual(len(catalog), 1)
        self.assertEqual(len(catalog[0].picks), 0)
        origin = catalog[0].origins[0]
        self.assertIsNone(origin.latitude)
        self.assertIsNone(origin.longitude)
        self.assertIsNone(origin.depth)
        comments = {comment.text for comment in origin.comments}
        self.assertIn(f"north: {metadata['north']}", comments)
        self.assertIn(f"east: {metadata['east']}", comments)
        self.assertIn(f"down: {metadata['down']}", comments)
        self.assertIn(f"loc_units: {metadata['loc_units']}", comments)

    def test_catalog_uses_explicit_datum_if_provided(self):
        root = Path(__file__).resolve().parents[1] / "data/m0013"
        event_path = root / "ESF/20250403/20250403_0001.ESF"
        if not event_path.exists():
            self.skipTest("Local ESF validation file is not installed")

        metadata = extract_esf_event_metadata(event_path)
        catalog = build_esf_catalog_from_esfs(event_path, datum=DEFAULT_DATUM)
        origin = catalog[0].origins[0]
        geo = local_to_geographic(metadata["north"], metadata["east"], metadata["down"], DEFAULT_DATUM)
        self.assertAlmostEqual(origin.latitude, geo["latitude"])
        self.assertAlmostEqual(origin.longitude, geo["longitude"])
        self.assertAlmostEqual(origin.depth, geo["depth"])

    def test_catalog_uses_stationxml_for_pick_waveform_ids_if_available(self):
        from obspy import read_events

        root = Path(__file__).resolve().parents[1]
        event_path = root / "data/m0013/ESF/20250403/20250403_0001.ESF"
        pcf_path = root / "data/m0013/m0013.pcf"
        config_path = root / "config/MEERA.ini"
        if not event_path.exists() or not pcf_path.exists():
            self.skipTest("Local ESF/PCF validation files are not installed")

        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            station_csv = directory_path / "stations.csv"
            station_xml = directory_path / "stations.xml"
            event_xml = directory_path / "events.xml"
            convert_pcf_to_csv(pcf_path, output_path=station_csv)
            convert_stations(csv_path=station_csv, output_path=station_xml, datum_config=config_path)
            catalog = build_esf_catalog_from_esfs(
                event_path,
                output_path=event_xml,
                datum_config=config_path,
                inventory_path=station_xml,
            )
            roundtrip = read_events(str(event_xml))

        self.assertEqual(len(catalog[0].picks), 3)
        self.assertEqual(len(catalog[0].origins[0].arrivals), 3)
        picks = {(pick.waveform_id.station_code, pick.waveform_id.channel_code): pick for pick in catalog[0].picks}
        self.assertIn(("S01", "NDZ"), picks)
        self.assertIn(("S02", "NDZ"), picks)
        self.assertIn(("S04", "ND1"), picks)
        self.assertAlmostEqual(picks[("S01", "NDZ")].time - catalog[0].origins[0].time, 0.001496)
        self.assertEqual(len(roundtrip[0].picks), 3)
        self.assertEqual(len(roundtrip[0].origins[0].arrivals), 3)

    def test_catalog_uses_datum_config_if_provided(self):
        root = Path(__file__).resolve().parents[1]
        event_path = root / "data/m0013/ESF/20250403/20250403_0001.ESF"
        config_path = root / "config/MEERA.ini"
        if not event_path.exists():
            self.skipTest("Local ESF validation file is not installed")

        metadata = extract_esf_event_metadata(event_path)
        catalog = build_esf_catalog_from_esfs(event_path, datum_config=config_path)
        origin = catalog[0].origins[0]
        geo = local_to_geographic(metadata["north"], metadata["east"], metadata["down"], load_datum_config(config_path))
        self.assertAlmostEqual(origin.latitude, geo["latitude"])
        self.assertAlmostEqual(origin.longitude, geo["longitude"])
        self.assertAlmostEqual(origin.depth, geo["depth"])

    def test_esf_quakeml_converter_writes_output(self):
        from obspy import read_events

        root = Path(__file__).resolve().parents[1]
        event_path = root / "data/m0013/ESF/20250403/20250403_0001.ESF"
        config_path = root / "config/MEERA.ini"
        if not event_path.exists():
            self.skipTest("Local ESF validation file is not installed")

        metadata = extract_esf_event_metadata(event_path)
        geo = local_to_geographic(metadata["north"], metadata["east"], metadata["down"], load_datum_config(config_path))
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "events.xml"
            catalog = convert_esf_quakeml(event_path, output_path=output_path, datum_config=config_path)
            self.assertEqual(len(catalog), 1)
            self.assertTrue(output_path.exists())
            self.assertGreater(output_path.stat().st_size, 0)

            roundtrip = read_events(str(output_path))
            self.assertEqual(len(roundtrip), 1)
            origin = roundtrip[0].origins[0]
            self.assertAlmostEqual(origin.latitude, geo["latitude"])
            self.assertAlmostEqual(origin.longitude, geo["longitude"])
            self.assertAlmostEqual(origin.depth, geo["depth"])
            comments = {comment.text for comment in origin.comments}
            self.assertIn(f"north: {metadata['north']}", comments)
            self.assertIn(f"east: {metadata['east']}", comments)
            self.assertIn(f"down: {metadata['down']}", comments)
            self.assertIn("local_unit_m: 0.001", comments)

    def test_esf_quakeml_default_output_path(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(default_output_path(directory), Path(directory) / "events.xml")
        self.assertEqual(default_output_path("sample.ESF"), Path("sample.xml"))

    def test_esf_directory_quakeml_roundtrip_if_available(self):
        from obspy import read_events

        root = Path(__file__).resolve().parents[1]
        source_paths = [
            root / "data/m0013/ESF/20250403/20250403_0001.ESF",
            root / "data/m0013/ESF/20250403/20250403_0002.ESF",
        ]
        config_path = root / "config/MEERA.ini"
        if not all(path.exists() for path in source_paths):
            self.skipTest("Local ESF validation files are not installed")

        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            for source_path in source_paths:
                (directory_path / source_path.name).write_bytes(source_path.read_bytes())
            output_path = directory_path / "events.xml"
            catalog = convert_esf_quakeml(directory_path, output_path=output_path, datum_config=config_path)
            roundtrip = read_events(str(output_path))

        self.assertEqual(len(catalog), 2)
        self.assertEqual(len(roundtrip), 2)
        self.assertEqual([str(event.resource_id) for event in catalog], sorted(str(event.resource_id) for event in catalog))
        for event in roundtrip:
            origin = event.origins[0]
            self.assertIsNotNone(origin.latitude)
            self.assertIsNotNone(origin.longitude)
            self.assertIn("local_unit_m: 0.001", {comment.text for comment in origin.comments})


if __name__ == "__main__":
    unittest.main()
