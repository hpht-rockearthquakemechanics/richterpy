from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / 'src'))

from richterpy.convert.stations import convert_stations, main, valid_experiment_code


if __name__ == '__main__':
    main()
