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
    datum: object | None = None,
    datum_config: str | Path | None = None,
    local_unit_m: float | None = None,
) -> None:
    import pandas as pd
    from obspy import UTCDateTime
    from obspy.core.event import Catalog, Event, Origin, Magnitude
    from obspy.core.event.base import Comment

    from richterpy.coordinates import Datum, local_to_geographic, resolve_datum

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
    datum = resolve_datum(datum, datum_config=datum_config, local_unit_m=local_unit_m)

    print(f"--> Loading data from {csv_path}...")

    df = pd.read_csv(csv_path)
    df['Loc_Mag'] = pd.to_numeric(df['Loc_Mag'], errors='coerce')
    df.dropna(subset=['Loc_Mag'], inplace=True)

    cat = Catalog()

    for _, row in df.iterrows():
        Timestamp = row['Date'] + ' ' + row['LocalTime']
        dt, ns = timestamp_to_datetime_ns(Timestamp)

        row_unit_m = datum.local_unit_m
        if 'Loc_Units' in row and pd.notna(row['Loc_Units']):
            row_unit_m = float(row['Loc_Units'])
        row_datum = Datum(datum.latitude, datum.longitude, datum.elevation, row_unit_m)
        geo = local_to_geographic(row['North'], row['East'], row['Down'], row_datum)
        origin = Origin(
            time=UTCDateTime(dt),
            comments=[Comment(text=f'ns: {ns}'), Comment(text=f"local_unit_m: {geo['local_unit_m']}")],
            latitude=geo['latitude'],
            longitude=geo['longitude'],
            depth=geo['depth'],
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
    convert_events(
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
