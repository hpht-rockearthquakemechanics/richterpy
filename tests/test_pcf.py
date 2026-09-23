from __future__ import annotations

import csv
from pathlib import Path
import struct
import tempfile
import unittest

from richterpy.coordinates import load_datum_config, local_to_geographic
from richterpy.convert.stations import convert_stations
from richterpy.io.pcf import convert_pcf_to_csv, decode_pcf_txt, extract_pcf_station_records


def _length_value(values: list[str]) -> bytes:
    return "".join(f"{len(value):03d}{value}" for value in values).encode("ascii")


def _synthetic_station_record(
    channel_label: str,
    owner_array: str,
    instrument_label: str,
    values: tuple[float, ...],
) -> bytes:
    assert len(values) == 14
    return struct.pack("<14d", *values) + (b"\x00" * 32) + _length_value([channel_label, owner_array, instrument_label])


class PCFExtractionTests(unittest.TestCase):
    def test_extracts_dynamic_station_record_from_numeric_block(self):
        raw = b"prefix" + _synthetic_station_record(
            "S005",
            "custom",
            "Geo",
            (
                10.0,
                20.0,
                -30.0,
                0.0,
                -1.0,
                0.0,
                0.001,
                0.2,
                1.0,
                2.0,
                10.0,
                1.0,
                5_000_000.0,
                2.0,
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.pcf"
            path.write_bytes(raw)
            records = extract_pcf_station_records(path)

        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["Station_Label"], "004S005006custom003Geo")
        self.assertEqual(record["Channel_Number"], 5)
        self.assertEqual(record["Owner_Array"], "custom")
        self.assertEqual(record["Instrument_Label"], "Geo")
        self.assertEqual(record["North"], 10.0)
        self.assertEqual(record["East"], 20.0)
        self.assertEqual(record["Down"], -30.0)
        self.assertEqual(record["Orientation_E"], -1.0)
        self.assertEqual(record["Local_Unit_M"], 0.001)
        self.assertEqual(record["Axis_Number"], 2.0)
        self.assertEqual(record["Motion"], 1.0)

    def test_skips_station_record_with_invalid_local_unit(self):
        raw = _synthetic_station_record(
            "S005",
            "custom",
            "Geo",
            (
                10.0,
                20.0,
                -30.0,
                0.0,
                -1.0,
                0.0,
                0.0,
                0.2,
                1.0,
                2.0,
                10.0,
                1.0,
                5_000_000.0,
                2.0,
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.pcf"
            path.write_bytes(raw)
            self.assertEqual(extract_pcf_station_records(path), [])

    def test_no_station_pcf_bytes_are_empty_and_csv_raises(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "empty.pcf"
            path.write_bytes(b"not a station block")
            self.assertEqual(extract_pcf_station_records(path), [])
            with self.assertRaises(ValueError):
                convert_pcf_to_csv(path, output_path=Path(directory) / "stations.csv")

    def test_decode_synthetic_pcf_report_uses_dynamic_station_labels(self):
        raw = _synthetic_station_record(
            "S005",
            "custom",
            "Geo",
            (
                10.0,
                20.0,
                -30.0,
                0.0,
                -1.0,
                0.0,
                0.001,
                0.2,
                1.0,
                2.0,
                10.0,
                1.0,
                5_000_000.0,
                2.0,
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.pcf"
            path.write_bytes(raw)
            report_path = decode_pcf_txt(path)
            report = report_path.read_text(encoding="utf-8")

        self.assertIn("004S005006custom003Geo", report)
        self.assertIn("North: 10.0", report)
        self.assertIn("Local_Unit_M: 0.001", report)

    def test_real_m0013_pcf_station_records_if_available(self):
        root = Path(__file__).resolve().parents[1]
        path = root / "data/m0013/m0013.pcf"
        if not path.exists():
            self.skipTest("Local m0013 PCF file is not installed")

        records = extract_pcf_station_records(path)
        self.assertEqual(len(records), 4)
        by_channel = {record["Channel_Label"]: record for record in records}
        self.assertEqual(by_channel["S001"]["North"], 41.0)
        self.assertEqual(by_channel["S002"]["Instrument_Number"], 2)
        self.assertEqual(by_channel["S002"]["Array_Instrument_Number"], 2)
        self.assertEqual(by_channel["S002"]["Array_Channel_Number"], 2)
        self.assertEqual(by_channel["S001"]["East"], 34.0)
        self.assertEqual(by_channel["S001"]["Down"], -50.0)
        self.assertEqual(by_channel["S004"]["North"], 42.5)
        self.assertEqual(by_channel["S004"]["East"], 258.5)
        self.assertEqual(by_channel["S004"]["Orientation_N"], 0.0)
        self.assertEqual(by_channel["S004"]["Orientation_E"], -1.0)
        self.assertEqual(by_channel["S004"]["Orientation_D"], 0.0)
        self.assertEqual(by_channel["S004"]["Local_Unit_M"], 0.001)
        self.assertEqual(by_channel["S004"]["Axis_Number"], 2.0)

    def test_convert_real_m0013_pcf_to_csv_if_available(self):
        root = Path(__file__).resolve().parents[1]
        path = root / "data/m0013/m0013.pcf"
        if not path.exists():
            self.skipTest("Local m0013 PCF file is not installed")

        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "stations.csv"
            convert_pcf_to_csv(path, output_path=output_path)
            with output_path.open(newline="", encoding="utf-8") as source:
                rows = list(csv.DictReader(source))

        self.assertEqual(len(rows), 4)
        self.assertIn("Local_Unit_M", rows[0])
        row4 = next(row for row in rows if row["Channel_Label"] == "S004")
        self.assertEqual(float(row4["East"]), 258.5)
        self.assertEqual(float(row4["Orientation_E"]), -1.0)
        self.assertEqual(float(row4["Local_Unit_M"]), 0.001)
        self.assertEqual(float(row4["Axis_Number"]), 2.0)

    def test_real_m0013_pcf_to_stationxml_if_available(self):
        from obspy import read_inventory

        root = Path(__file__).resolve().parents[1]
        path = root / "data/m0013/m0013.pcf"
        config_path = root / "config/MEERA.ini"
        if not path.exists():
            self.skipTest("Local m0013 PCF file is not installed")

        with tempfile.TemporaryDirectory() as directory:
            csv_path = Path(directory) / "stations.csv"
            xml_path = Path(directory) / "stations.xml"
            convert_pcf_to_csv(path, output_path=csv_path)
            convert_stations(csv_path=csv_path, output_path=xml_path, datum_config=config_path)
            inventory = read_inventory(str(xml_path))

        self.assertEqual(len(inventory.networks), 1)
        network = inventory.networks[0]
        self.assertEqual(len(network.stations), 4)
        stations = {station.code: station for station in network.stations}
        s04 = stations["S04"]
        geo = local_to_geographic(42.5, 258.5, -50.0, load_datum_config(config_path))
        self.assertAlmostEqual(s04.latitude, geo["latitude"])
        self.assertAlmostEqual(s04.longitude, geo["longitude"])
        self.assertAlmostEqual(s04.elevation, geo["elevation"])
        self.assertEqual(len(s04.channels), 1)
        self.assertEqual(s04.channels[0].code, "ND1")
        self.assertAlmostEqual(s04.channels[0].depth, -geo["elevation"])

    def test_decode_real_m0013_pcf_report_if_available(self):
        root = Path(__file__).resolve().parents[1]
        path = root / "data/m0013/m0013.pcf"
        if not path.exists():
            self.skipTest("Local m0013 PCF file is not installed")

        with tempfile.TemporaryDirectory() as directory:
            copy_path = Path(directory) / "sample.pcf"
            copy_path.write_bytes(path.read_bytes())
            report_path = decode_pcf_txt(copy_path)
            report = report_path.read_text(encoding="utf-8")

        self.assertIn("[PROJECT PATHS]", report)
        self.assertIn("[STREAM ENTRIES]", report)
        self.assertIn("[STATION/CHANNEL METADATA]", report)
        self.assertIn("[LENGTH-VALUE RUNS]", report)
        self.assertIn("S004", report)


if __name__ == "__main__":
    unittest.main()
