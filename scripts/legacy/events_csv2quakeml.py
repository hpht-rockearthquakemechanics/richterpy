from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))

from richterpy.convert.events import convert_events, main, valid_experiment_code


if __name__ == '__main__':
    main()
