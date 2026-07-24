from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / 'src'))

from richterpy.convert.snuffler import (
    analyze_stream_with_obspy,
    build_master_stream,
    build_station_channel_map,
    channel_numbers_for_srm,
    experiment,
    get_high_precision_events,
    load_srm_to_stream,
    main,
    metadataFolder,
    run_workflow,
    wve_file_to_metadata,
)


if __name__ == '__main__':
    main()
