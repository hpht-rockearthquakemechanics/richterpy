"""InSite triggered waveform helpers for ESF/BSF files."""

from __future__ import annotations

import argparse
from pathlib import Path

from richterpy.io.bsf import decode_bsf_txt, plot_bsf_png
from richterpy.io.esf import decode_esf_txt, extract_esf, extract_footer_doubles, plot_esf_png

parse_triggered_waveforms = decode_esf_txt


def main() -> None:
    parser = argparse.ArgumentParser(description='Decode InSite triggered waveform files.')
    parser.add_argument('path')
    parser.add_argument('--plot', action='store_true', help='Also write a PNG plot for ESF/BSF inputs')
    args = parser.parse_args()

    path = Path(args.path)
    suffix = path.suffix.lower()
    if suffix == '.esf':
        decode_esf_txt(path)
        if args.plot:
            plot_esf_png(path)
    elif suffix == '.bsf':
        decode_bsf_txt(path)
        if args.plot:
            plot_bsf_png(path)
    else:
        raise SystemExit(f'Unsupported file type: {path.suffix}')


if __name__ == '__main__':
    main()
