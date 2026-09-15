from __future__ import annotations

import argparse
import re
from pathlib import Path


def valid_experiment_code(code_str: str) -> str:
    pattern = r'^m\d{4}$'
    if not re.match(pattern, code_str):
        msg = f"'{code_str}' is not a valid format. Expected mNNNN (e.g., m1001)."
        raise argparse.ArgumentTypeError(msg)
    return code_str


def convert_stations(
    experiment_id: str | None = None,
    csv_path: str | Path | None = None,
    output_path: str | Path | None = None,
    root: str | Path = 'data',
    datum: object | None = None,
    datum_config: str | Path | None = None,
    local_unit_m: float | None = None,
) -> None:
    import pandas as pd
    from obspy.core.inventory import Inventory, Network, Station, Channel

    from richterpy.coordinates import Datum, local_to_geographic, resolve_datum

    if csv_path is None:
        if experiment_id is None:
            raise ValueError('Either experiment_id or csv_path must be provided.')
        csv_path = Path(root) / experiment_id / 'ae' / 'red' / f'{experiment_id}.csv'
    else:
        csv_path = Path(csv_path)

    if output_path is None:
        output_path = csv_path.with_suffix('.xml')
    else:
        output_path = Path(output_path)

    experiment_label = experiment_id or csv_path.stem
    datum = resolve_datum(datum, datum_config=datum_config, local_unit_m=local_unit_m)

    print(f"--> Loading data from {csv_path}...")

    df = pd.read_csv(csv_path)

    inv = Inventory(networks=[], source='MEERA data reduction.')
    net = Network(code='RC', stations=[], description='Richter network.')

    def orientation_to_subsource(orientation_n, orientation_e, orientation_d):
        components = {
            'Z': abs(float(orientation_d)),
            '2': abs(float(orientation_n)),
            '1': abs(float(orientation_e)),
        }
        return max(components, key=components.get)

    for _, row in df.iterrows():
        row_unit_m = datum.local_unit_m
        if 'Local_Unit_M' in row and pd.notna(row['Local_Unit_M']):
            row_unit_m = float(row['Local_Unit_M'])
        row_datum = Datum(datum.latitude, datum.longitude, datum.elevation, row_unit_m)
        geo = local_to_geographic(row['North'], row['East'], row['Down'], row_datum)
        sta = Station(
            code='S0' + str(row['Instrument_Number']),
            latitude=geo['latitude'],
            longitude=geo['longitude'],
            elevation=geo['elevation'],
        )

        band = 'N'
        source = 'D'
        subsource = orientation_to_subsource(
            row['Orientation_N'],
            row['Orientation_E'],
            row['Orientation_D'],
        )

        cha = Channel(
            code=band + source + subsource,
            location_code='C0' + str(row['Instrument_Number']),
            latitude=sta.latitude,
            longitude=sta.longitude,
            elevation=sta.elevation,
            depth=-sta.elevation,
            sample_rate=10**7,
        )

        sta.channels.append(cha)
        net.stations.append(sta)

    inv.networks.append(net)
    inv.write(output_path, format='stationxml', validate=True)
    print(f"--> StationXML for {experiment_label} written to {output_path}.")


def main() -> None:
    parser = argparse.ArgumentParser(description='Run an experiment stations conversion based on a code.')
    parser.add_argument('experiment', nargs='?', type=valid_experiment_code, help='The experiment code (mNNNN)')
    parser.add_argument('--csv-path', help='Explicit input CSV path')
    parser.add_argument('--output-path', help='Explicit StationXML output path')
    parser.add_argument('--root', default='data', help='Base data directory used with experiment codes')
    parser.add_argument('--datum-latitude', type=float, help='Datum latitude in degrees')
    parser.add_argument('--datum-longitude', type=float, help='Datum longitude in degrees')
    parser.add_argument('--datum-elevation', type=float, help='Datum elevation in meters')
    parser.add_argument('--datum-config', help='INI file with [datum] latitude/longitude/elevation_m/local_unit_m')
    parser.add_argument('--local-unit-m', type=float, help='Meters per local coordinate unit; default is 0.001')
    args = parser.parse_args()
    datum = None
    datum_values = (args.datum_latitude, args.datum_longitude, args.datum_elevation)
    if args.datum_config and any(value is not None for value in datum_values):
        parser.error('--datum-config cannot be combined with explicit datum latitude/longitude/elevation')
    if any(value is not None for value in datum_values):
        if not all(value is not None for value in datum_values):
            parser.error('--datum-latitude, --datum-longitude, and --datum-elevation must be provided together')
        datum = {'latitude': args.datum_latitude, 'longitude': args.datum_longitude, 'elevation': args.datum_elevation}
    convert_stations(
        args.experiment,
        csv_path=args.csv_path,
        output_path=args.output_path,
        root=args.root,
        datum=datum,
        datum_config=args.datum_config,
        local_unit_m=args.local_unit_m,
    )


if __name__ == '__main__':
    main()
