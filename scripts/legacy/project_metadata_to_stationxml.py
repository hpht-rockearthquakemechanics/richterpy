from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))

from richterpy.obspy.station_inventory import build_station_inventory, main, valid_experiment_code


if __name__ == '__main__':
    main()
