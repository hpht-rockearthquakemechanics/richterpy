"""InSite project metadata (PCF) helpers."""

from __future__ import annotations

import argparse

from richterpy.io.pcf import decode_pcf_txt

parse_project_metadata = decode_pcf_txt


def main() -> None:
    parser = argparse.ArgumentParser(description='Decode an InSite project PCF file.')
    parser.add_argument('path')
    args = parser.parse_args()
    decode_pcf_txt(args.path)


if __name__ == '__main__':
    main()
