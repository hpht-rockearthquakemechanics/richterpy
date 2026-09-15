from __future__ import annotations

import csv
import math
from pathlib import Path
import struct
import tempfile
import unittest

import numpy as np

from richterpy.io.esf import (
    _footer_bytes,
    build_esf_catalog_from_esfs,
    extract_esf,
    extract_esf_event_metadata,
    parse_esf_layout,
)


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
        self.assertAlmostEqual(catalog[0].origins[0].latitude, metadata["north"])
        self.assertAlmostEqual(catalog[0].origins[0].longitude, metadata["east"])


if __name__ == "__main__":
    unittest.main()
