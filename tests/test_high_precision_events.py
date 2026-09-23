import unittest

from obspy import UTCDateTime
from obspy.core.event import Origin
from obspy.core.event.base import Comment

from richterpy.convert.snuffler import high_precision_origin_timestamp


class HighPrecisionEventTests(unittest.TestCase):
    def test_ns_comment_restores_fractional_microsecond(self):
        origin = Origin(
            time=UTCDateTime("2025-04-03T12:28:40.380640Z"),
            latitude=0.0,
            longitude=0.0,
            depth=0.0,
            comments=[Comment(text="ns: 0.8")],
        )
        self.assertAlmostEqual(
            high_precision_origin_timestamp(origin),
            UTCDateTime("2025-04-03T12:28:40.380640Z").timestamp + 0.8e-6,
            places=7,
        )


if __name__ == "__main__":
    unittest.main()
