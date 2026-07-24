from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / 'src'))

from richterpy.io.esf import *  # noqa: F401,F403


if __name__ == '__main__':
    main()
