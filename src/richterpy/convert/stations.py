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
) -> None:
    import pandas as pd
    from obspy.core.inventory import Inventory, Network, Station, Channel

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

    print(f"--> Loading data from {csv_path}...")

    df = pd.read_csv(csv_path)

    Datum = {
        'latitude': 41.828272066465786,
        'longitude': 12.515104006116623,
        'elevation': 0.001,
    }

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
        sta = Station(
            code='S0' + str(row['Instrument_Number']),
            latitude=Datum['latitude'] - row['North'] * 9.009e-9,
            longitude=Datum['longitude'] - row['East'] * 1.209e-8,
            elevation=Datum['elevation'] + row['Down'] * 1e-6,
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
    args = parser.parse_args()
    convert_stations(args.experiment, csv_path=args.csv_path, output_path=args.output_path, root=args.root)


if __name__ == '__main__':
    main()
