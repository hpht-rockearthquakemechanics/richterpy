from __future__ import annotations

import argparse
import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo


def valid_experiment_code(code_str: str) -> str:
    pattern = r'^m\d{4}$'
    if not re.match(pattern, code_str):
        msg = f"'{code_str}' is not a valid format. Expected mNNNN (e.g., m1001)."
        raise argparse.ArgumentTypeError(msg)
    return code_str


def timestamp_to_datetime_ns(Timestamp: str):
    parts = Timestamp.split('.')
    main_time_string = parts[0]
    sub_seconds_string = parts[1]

    naive_dt = datetime.strptime(
        f"{main_time_string}.{sub_seconds_string[:6]}",
        '%d/%m/%Y %H:%M:%S.%f'
    )

    rome_tz = ZoneInfo('Europe/Rome')
    aware_dt = naive_dt.replace(tzinfo=rome_tz)

    nanoseconds_str = sub_seconds_string[6:]
    if nanoseconds_str:
        nanoseconds = Decimal('0.' + nanoseconds_str)
    else:
        nanoseconds = Decimal(0)

    return aware_dt, nanoseconds


def convert_events(
    experiment_id: str | None = None,
    csv_path: str | Path | None = None,
    output_path: str | Path | None = None,
    root: str | Path = 'data',
) -> None:
    import pandas as pd
    from obspy import UTCDateTime
    from obspy.core.event import Catalog, Event, Origin, Magnitude
    from obspy.core.event.base import Comment

    if csv_path is None:
        if experiment_id is None:
            raise ValueError('Either experiment_id or csv_path must be provided.')
        csv_path = Path(root) / experiment_id / 'ae' / 'red' / f'{experiment_id} event data.csv'
    else:
        csv_path = Path(csv_path)

    if output_path is None:
        output_path = csv_path.with_suffix('.xml')
    else:
        output_path = Path(output_path)

    experiment_label = experiment_id or csv_path.stem.replace(' event data', '')

    print(f"--> Loading data from {csv_path}...")

    df = pd.read_csv(csv_path)
    df['Loc_Mag'] = pd.to_numeric(df['Loc_Mag'], errors='coerce')
    df.dropna(subset=['Loc_Mag'], inplace=True)

    Datum = {
        'latitude': 41.828272066465786,
        'longitude': 12.515104006116623,
        'elevation': 0.001,
    }

    cat = Catalog()

    for _, row in df.iterrows():
        Timestamp = row['Date'] + ' ' + row['LocalTime']
        dt, ns = timestamp_to_datetime_ns(Timestamp)

        origin = Origin(
            time=UTCDateTime(dt),
            comments=[Comment(text=f'ns: {ns}')],
            latitude=Datum['latitude'] - row['North'] * 9.009e-9,
            longitude=Datum['longitude'] - row['East'] * 1.209e-8,
            depth=-(Datum['elevation'] + row['Down'] * 1e-6),
        )

        magnitude = Magnitude(
            mag=row['Loc_Mag'],
            magnitude_type='Local Magnitude',
        )

        event = Event(
            origins=[origin],
            magnitudes=[magnitude],
            resource_id=str(row['Component']) + str(row['Number']).zfill(5),
        )

        cat.append(event)

    cat.write(output_path, format='QUAKEML')
    print(f"--> QuakeML for {experiment_label} written to {output_path}.")


def main() -> None:
    parser = argparse.ArgumentParser(description='Run an experiment events conversion based on a code.')
    parser.add_argument('experiment', nargs='?', type=valid_experiment_code, help='The experiment code (mNNNN)')
    parser.add_argument('--csv-path', help='Explicit input CSV path')
    parser.add_argument('--output-path', help='Explicit QuakeML output path')
    parser.add_argument('--root', default='data', help='Base data directory used with experiment codes')
    args = parser.parse_args()
    convert_events(args.experiment, csv_path=args.csv_path, output_path=args.output_path, root=args.root)


if __name__ == '__main__':
    main()
