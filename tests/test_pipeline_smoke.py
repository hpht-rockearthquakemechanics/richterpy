from __future__ import annotations

import csv
import struct
import tempfile
import unittest
from pathlib import Path

import numpy as np
from obspy import read_events, read_inventory

from richterpy.convert.events import convert_events
from richterpy.convert.snuffler import build_master_stream
from richterpy.convert.stations import convert_stations
from richterpy.io.atf import build_atf_stream
from richterpy.io.bsf import build_bsf_stream
from richterpy.io.pcf import convert_pcf_to_csv


def _write_station_csv(path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "Instrument_Number",
                "North",
                "East",
                "Down",
                "Orientation_N",
                "Orientation_E",
                "Orientation_D",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "Instrument_Number": 1,
                "North": 0.0,
                "East": 0.0,
                "Down": 0.0,
                "Orientation_N": 0.0,
                "Orientation_E": 0.0,
                "Orientation_D": 1.0,
            }
        )


def _write_event_csv(path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["Number", "Component", "Date", "LocalTime", "North", "East", "Down", "Loc_Units", "Loc_Mag"],
        )
        writer.writeheader()
        writer.writerow(
            {
                "Number": 1,
                "Component": "20250403",
                "Date": "03/04/2025",
                "LocalTime": "14:28:40.3806408",
                "North": 0.0,
                "East": 0.0,
                "Down": 0.0,
                "Loc_Units": 0.001,
                "Loc_Mag": -3.0,
            }
        )


def _length_value(values: list[str]) -> bytes:
    return "".join(f"{len(value):03d}{value}" for value in values).encode("ascii")


def _synthetic_station_record() -> bytes:
    values = (
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
        0.001,
        0.0,
        1.0,
        1.0,
        5.0,
        1.0,
        5_000_000.0,
        1.0,
    )
    return struct.pack("<14d", *values) + (b"\x00" * 32) + _length_value(["S001", "richter", "Sensor"])


class PipelineSmokeTests(unittest.TestCase):
    def test_o1_raw_stream_and_station_csv_to_obspy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            station_csv = root / "stations.csv"
            station_xml = root / "stations.xml"
            _write_station_csv(station_csv)
            convert_stations(csv_path=station_csv, output_path=station_xml)

            wve = root / "richter-m.00001.wve"
            wve.write_text(
                "Sampling rate: 1000\nStart DateTime: 03042025 142840.000000\nChannels acquired: 1;2;3;4\n",
                encoding="utf-8",
            )
            data = np.arange(16, dtype="<u2")
            (root / "richter-m.00001.srm").write_bytes(b"\x00" * 8 + data.tobytes())

            inventory = read_inventory(str(station_xml))
            stream = build_master_stream(str(root), station_channel_map={"S01": "NDZ"})
            stream_data = [np.asarray(trace.data).copy() for trace in stream]
            stream_channels = [trace.stats.channel for trace in stream]
            del stream

        self.assertEqual(len(inventory.networks[0].stations), 1)
        self.assertEqual(len(stream_data), 4)
        self.assertEqual(stream_channels[0], "NDZ")

    def test_o2_raw_stream_and_pcf_metadata_to_obspy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pcf_path = root / "sample.pcf"
            station_csv = root / "stations.pcf.csv"
            station_xml = root / "stations.pcf.xml"
            pcf_path.write_bytes(b"prefix" + _synthetic_station_record())

            convert_pcf_to_csv(pcf_path, output_path=station_csv)
            convert_stations(csv_path=station_csv, output_path=station_xml)
            inventory = read_inventory(str(station_xml))

        self.assertEqual(inventory.networks[0].stations[0].channels[0].code, "NDZ")

    def test_o3_triggered_waveforms_to_obspy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bsf = root / "20250403_142840.bsf"
            payload = np.array([1.0, 2.0, 3.0], dtype="<f8").tobytes()
            bsf.write_bytes(b"\x00" * 421 + payload)

            atf = root / "event_01.atf"
            atf.write_text(
                "ATF Synthetic\nDate=03-04-2025; Time=14:28:40.125; TSamp=0.25; TracePoints=3; AmpToVolts=2.0\n"
                "[TraceData]\n1.0\n2.0\n3.0\n",
                encoding="utf-8",
            )

            bsf_stream = build_bsf_stream(bsf)
            atf_stream = build_atf_stream(atf)
            bsf_data = [np.asarray(trace.data).copy() for trace in bsf_stream]
            atf_data = [np.asarray(trace.data).copy() for trace in atf_stream]
            del bsf_stream, atf_stream

        self.assertEqual(len(bsf_data), 1)
        self.assertEqual(len(atf_data), 1)

    def test_o4_event_csv_to_obspy_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            event_csv = root / "events.csv"
            event_xml = root / "events.xml"
            _write_event_csv(event_csv)

            convert_events(csv_path=event_csv, output_path=event_xml)
            catalog = read_events(str(event_xml))

        self.assertEqual(len(catalog), 1)
        self.assertEqual(catalog[0].origins[0].time.microsecond, 380640)
        self.assertIn("ns: 0.8", {comment.text for comment in catalog[0].origins[0].comments})


if __name__ == "__main__":
    unittest.main()
