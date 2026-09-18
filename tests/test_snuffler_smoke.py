import unittest

from obspy import UTCDateTime
from obspy.core.event import Origin
from obspy.core.event.base import Comment
from obspy.core.inventory import Channel, Inventory, Network, Station

from richterpy.convert.snuffler import build_station_channel_map, high_precision_origin_timestamp


class SnufflerSmokeTests(unittest.TestCase):
    def test_station_channel_map_is_non_interactive(self):
        inventory = Inventory(
            networks=[
                Network(
                    code="RC",
                    stations=[
                        Station(
                            code="S01",
                            latitude=0.0,
                            longitude=0.0,
                            elevation=0.0,
                            channels=[
                                Channel(
                                    code="NDZ",
                                    location_code="C01",
                                    latitude=0.0,
                                    longitude=0.0,
                                    elevation=0.0,
                                    depth=0.0,
                                )
                            ],
                        )
                    ],
                )
            ],
            source="test",
        )

        self.assertEqual(build_station_channel_map(inventory), {"S01": "NDZ"})

    def test_high_precision_origin_timestamp_is_non_interactive(self):
        origin = Origin(
            time=UTCDateTime("2025-04-03T12:28:40.380640Z"),
            comments=[Comment(text="ns: 0.8")],
        )

        self.assertAlmostEqual(
            high_precision_origin_timestamp(origin),
            UTCDateTime("2025-04-03T12:28:40.380640Z").timestamp + 0.8e-6,
        )


if __name__ == "__main__":
    unittest.main()
