from __future__ import annotations

import argparse
import glob
import os
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict
from zoneinfo import ZoneInfo

experiment = 'm0013'
metadataFolder = 'data'
dataFolder = 'data'
OUTPUT_MODE = 'snuffler'

ACQUISITION_GROUP_CHANNELS = {
    'richter-m': [1, 2, 3, 4],
    'richter-s1': [5, 6, 7, 8],
    'richter-s2': [9, 10, 11, 12],
}


def wve_file_to_metadata(wvefilepath: str) -> Dict[str, Any]:
    from obspy import UTCDateTime

    metadata = {'Volt_range__V': 5.0}
    try:
        with open(wvefilepath, 'r') as f:
            lines = f.read().split('\n')
        for line in lines:
            if ':' in line:
                key, val = line.split(':', 1)
                key = key.strip().replace(' ', '_').replace('(', '_').replace(')', '')
                val = val.strip()
                if 'Channels_acquired' in key:
                    metadata['Channels_acquired'] = [int(c) for c in val.split(';') if c.strip().isdigit()]
                elif 'Volt_range' in key:
                    metadata['Volt_range__V'] = float(val)
                elif 'Sampling_rate' in key:
                    metadata['Sampling_rate__Hz'] = float(val)
                elif 'Start_DateTime' in key:
                    try:
                        dt_naive = datetime.strptime(val, '%d%m%Y %H%M%S.%f')
                        rome_tz = ZoneInfo('Europe/Rome')
                        dt_rome = dt_naive.replace(tzinfo=rome_tz)
                        dt_utc = dt_rome.astimezone(ZoneInfo('UTC'))
                        metadata['Start_DateTime'] = UTCDateTime(dt_utc)
                    except Exception as e:
                        print(f"Time parsing error: {e}")
                        pass
    except Exception as e:
        print(f"Metadata error: {e}")
    return metadata


def build_station_channel_map(obspy_inventory) -> Dict[str, str]:
    station_channel_map: Dict[str, str] = {}
    for network in obspy_inventory:
        for station in network.stations:
            if station.channels:
                station_channel_map[station.code] = station.channels[0].code
    return station_channel_map


def channel_numbers_for_srm(srm_filepath: str, num_channels: int) -> list[int]:
    basename = os.path.basename(srm_filepath).lower()
    for prefix, channels in ACQUISITION_GROUP_CHANNELS.items():
        if basename.startswith(prefix):
            return channels[:num_channels]
    return list(range(1, num_channels + 1))


def load_srm_to_stream(srm_filepath, wve_filepath, station_channel_map=None):
    import numpy as np
    from obspy import Stream, Trace, UTCDateTime

    meta = wve_file_to_metadata(wve_filepath)
    if not meta:
        print(f"❌ Could not read WVE for {os.path.basename(srm_filepath)}")
        return Stream()

    fs = meta.get('Sampling_rate__Hz', 10000000.0)
    start_time = meta.get('Start_DateTime', UTCDateTime())
    num_channels = 4
    acquired_channels = meta.get('Channels_acquired') or channel_numbers_for_srm(srm_filepath, num_channels)

    file_size = os.path.getsize(srm_filepath)
    HEADER_SIZE = 8
    data_size_bytes = file_size - HEADER_SIZE
    total_samples = data_size_bytes // 2
    if total_samples % num_channels != 0:
        print(f"⚠️ Warning: File {os.path.basename(srm_filepath)} appears truncated.")
        total_samples = (total_samples // num_channels) * num_channels

    samples_per_channel = total_samples // num_channels
    print(f"Loading: {os.path.basename(srm_filepath)} | Start: {start_time}")

    try:
        mapped_data = np.memmap(srm_filepath, dtype='<u2', mode='r', offset=HEADER_SIZE)
        if mapped_data.size > total_samples:
            mapped_data = mapped_data[:total_samples]
        data_matrix = mapped_data.reshape(-1, num_channels)
    except Exception as e:
        print(f"Error mapping file: {e}")
        return Stream()

    st = Stream()
    for i in range(num_channels):
        station_code = f'S{i+1:02d}'
        channel_code = 'JPZ'
        if station_channel_map:
            channel_code = station_channel_map.get(station_code, channel_code)

        stats = {
            'network': 'RC',
            'station': station_code,
            'location': 'RAW',
            'channel': channel_code,
            'sampling_rate': fs,
            'starttime': start_time,
            'npts': samples_per_channel,
        }
        if i < len(acquired_channels):
            stats['channel_number'] = acquired_channels[i]
        else:
            stats['channel_number'] = i + 1
        tr = Trace(data=data_matrix[:, i], header=stats)
        st.append(tr)
    return st


def get_high_precision_events(obspy_catalog):
    from pyrocko import model

    pyrocko_events = []
    for ev_obs in obspy_catalog:
        origin = ev_obs.preferred_origin() or ev_obs.origins[0]
        lat, lon, depth = origin.latitude, origin.longitude, origin.depth

        mag = 0.0
        if ev_obs.magnitudes:
            pref_mag = ev_obs.preferred_magnitude() or ev_obs.magnitudes[0]
            mag = pref_mag.mag

        final_time = high_precision_origin_timestamp(origin)

        ev_pyr = model.Event(
            lat=lat, lon=lon, depth=depth, time=final_time,
            magnitude=mag, name=str(ev_obs.resource_id)
        )
        pyrocko_events.append(ev_pyr)
    return pyrocko_events


def high_precision_origin_timestamp(origin) -> float:
    final_time = origin.time.timestamp
    for comment in origin.comments:
        text = comment.text
        if text and text.startswith('ns'):
            try:
                # Historical QuakeML comments use "ns" for the fractional
                # microsecond part left after Python datetime parsing.
                residual_us = Decimal(text.split(':', 1)[1].strip())
                return final_time + float(residual_us * Decimal('0.000001'))
            except (InvalidOperation, ValueError) as e:
                print(f"Failed to parse comment '{text}': {e}")
    return final_time


def build_master_stream(data_folder: str, station_channel_map=None) -> Stream:
    from obspy import Stream

    print("\n--- 🔍 Searching for Data Waveforms ---")
    srm_files = sorted(glob.glob(os.path.join(data_folder, '*.srm')))

    if not srm_files:
        print(f"❌ No .srm files found in directory: {data_folder}")
        return Stream()

    print(f"Found {len(srm_files)} SRM files. Assembling master stream...")
    master_stream = Stream()
    for srm_path in srm_files:
        wve_path = srm_path.replace('.srm', '.wve')
        if os.path.exists(wve_path):
            st_segment = load_srm_to_stream(srm_path, wve_path, station_channel_map=station_channel_map)
            master_stream += st_segment
        else:
            print(f"⚠️ Missing .wve file for {os.path.basename(srm_path)}, skipping.")

    master_stream.sort(['starttime'])
    return master_stream


def analyze_stream_with_obspy(master_stream: Stream) -> None:
    import obspy

    print("\n--- ObsPy Stream Summary ---")
    print(master_stream)
    for tr in master_stream:
        print(
            f"{tr.id} | {tr.stats.starttime} -> {tr.stats.endtime} | "
            f"{tr.stats.npts} samples @ {tr.stats.sampling_rate} Hz"
        )

    try:
        master_stream.plot()
    except Exception as e:
        print(f"⚠️ Could not open ObsPy plot: {e}")


def run_workflow(
    experiment_id: str | None = experiment,
    metadata_root: str = 'data',
    data_root: str = dataFolder,
    output_mode: str = OUTPUT_MODE,
    station_xml_path: str | Path | None = None,
    event_xml_path: str | Path | None = None,
) -> None:
    import obspy
    from obspy import Stream
    from pyrocko import obspy_compat, trace

    obspy_compat.plant()

    global experiment, metadataFolder, dataFolder, OUTPUT_MODE

    if experiment_id is None:
        if station_xml_path is not None:
            experiment_id = Path(station_xml_path).stem
        elif event_xml_path is not None:
            experiment_id = Path(event_xml_path).stem.replace(' event data', '')
        else:
            raise ValueError('Either experiment_id or explicit station_xml_path/event_xml_path must be provided.')

    experiment = experiment_id
    if station_xml_path is None:
        station_xml_path = Path(metadata_root) / 'playground' / f'{experiment}.stations.csv.xml'
    else:
        station_xml_path = Path(station_xml_path)

    if event_xml_path is None:
        event_xml_path = Path(metadata_root) / 'playground' / f'{experiment}.events.csv.xml'
    else:
        event_xml_path = Path(event_xml_path)

    metadataFolder = str(Path(station_xml_path).parent)
    dataFolder = data_root
    OUTPUT_MODE = output_mode

    print('--- 📚 Loading Catalog and Station Metadata ---')

    obspy_catalog = obspy.read_events(event_xml_path, format='QUAKEML')
    pyrocko_events = get_high_precision_events(obspy_catalog)

    obspy_inventory = obspy.read_inventory(station_xml_path, format='STATIONXML')
    station_channel_map = build_station_channel_map(obspy_inventory)
    pyrocko_stations = obspy_inventory.to_pyrocko_stations()

    master_stream = build_master_stream(dataFolder, station_channel_map=station_channel_map)
    if len(master_stream) == 0:
        print('❌ No valid waveform data could be loaded.')
    elif OUTPUT_MODE == 'snuffler':
        print('\n✅ All data segments successfully loaded. Parsing to Pyrocko...')
        pyrocko_traces = master_stream.to_pyrocko_traces()
        print('\n🚀 Launching Snuffler UI... Look at your desktop!')
        trace.snuffle(pyrocko_traces, stations=pyrocko_stations, events=pyrocko_events)
    elif OUTPUT_MODE == 'obspy':
        analyze_stream_with_obspy(master_stream)
    else:
        raise ValueError(f'Unknown OUTPUT_MODE: {OUTPUT_MODE}')


def main() -> None:
    parser = argparse.ArgumentParser(description='Run InSite data workflow for Snuffler/ObsPy.')
    parser.add_argument('experiment', nargs='?', default=None)
    parser.add_argument('--metadata-root', default='data')
    parser.add_argument('--data-root', default=dataFolder)
    parser.add_argument('--station-xml-path', help='Explicit StationXML input path')
    parser.add_argument('--event-xml-path', help='Explicit QuakeML input path')
    parser.add_argument('--output-mode', default=OUTPUT_MODE, choices=['snuffler', 'obspy'])
    args = parser.parse_args()
    experiment_id = args.experiment
    if experiment_id is None and not args.station_xml_path and not args.event_xml_path:
        experiment_id = experiment
    run_workflow(
        experiment_id,
        metadata_root=args.metadata_root,
        data_root=args.data_root,
        output_mode=args.output_mode,
        station_xml_path=args.station_xml_path,
        event_xml_path=args.event_xml_path,
    )


if __name__ == '__main__':
    main()
