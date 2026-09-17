from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import numpy as np

from richterpy.io.atf import build_atf_stream, read_atf
from richterpy.io.bsf import build_bsf_stream, read_bsf


class IOSmokeTests(unittest.TestCase):
    def test_read_synthetic_bsf(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "20250403_142840.bsf"
            payload = np.array([1.0, 2.0, 3.0], dtype="<f8").tobytes()
            path.write_bytes(b"\x00" * 421 + payload)
            stream, metadata = read_bsf(path)

        self.assertEqual(len(stream), 1)
        self.assertEqual(metadata["channel_count"], 1)
        self.assertEqual(metadata["samples_per_channel"], 3)
        np.testing.assert_array_equal(stream[0].data, np.array([1.0, 2.0, 3.0]))
        self.assertEqual(stream[0].stats.station, "S01")

    def test_build_bsf_stream_missing_manifest_raises(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(FileNotFoundError):
                build_bsf_stream(directory)

    def test_read_synthetic_atf(self):
        content = "\n".join(
            [
                "ATF Synthetic",
                "Date=03-04-2025; Time=14:28:40.125; TSamp=0.25; TracePoints=3; AmpToVolts=2.0",
                "[TraceData]",
                "1.0",
                "2.5",
                "-3.0",
                "",
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "event_05.atf"
            path.write_text(content, encoding="utf-8")
            stream, metadata = read_atf(path)

        self.assertEqual(len(stream), 1)
        self.assertEqual(stream[0].stats.station, "S05")
        self.assertEqual(stream[0].stats.channel, "CH05")
        self.assertEqual(stream[0].stats.sampling_rate, 4.0)
        self.assertEqual(metadata["trace_points"], 3)
        self.assertEqual(metadata["amp_to_volts"], 2.0)
        np.testing.assert_array_equal(stream[0].data, np.array([1.0, 2.5, -3.0]))

    def test_atf_invalid_and_missing_inputs_raise(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.atf"
            path.write_text("not an atf", encoding="utf-8")
            with self.assertRaises(ValueError):
                read_atf(path)
            with self.assertRaises(FileNotFoundError):
                build_atf_stream(directory)

    def test_wve_srm_modules_import(self):
        import richterpy.io.srm as srm
        import richterpy.io.wve as wve

        self.assertIsNotNone(srm.__doc__)
        self.assertIsNotNone(wve.__doc__)


if __name__ == "__main__":
    unittest.main()
