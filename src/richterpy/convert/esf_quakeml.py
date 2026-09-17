from __future__ import annotations

import argparse
from pathlib import Path

from richterpy.io.esf import build_esf_catalog_from_esfs


def default_output_path(path: str | Path) -> Path:
    """Return the default QuakeML output path for an ESF file or directory."""

    path = Path(path)
    if path.is_dir():
        return path / "events.xml"
    return path.with_suffix(".xml")


def convert_esf_quakeml(
    path: str | Path,
    output_path: str | Path | None = None,
    *,
    datum_config: str | Path | None = None,
    local_unit_m: float | None = None,
):
    """Build a QuakeML catalog directly from ESF files."""

    path = Path(path)
    output_path = default_output_path(path) if output_path is None else Path(output_path)
    catalog = build_esf_catalog_from_esfs(
        path,
        output_path=output_path,
        datum_config=datum_config,
        local_unit_m=local_unit_m,
    )
    print(f"--> ESF QuakeML with {len(catalog)} events written to {output_path}.")
    return catalog


def main() -> None:
    parser = argparse.ArgumentParser(description="Build QuakeML directly from ESF event files.")
    parser.add_argument("path", help="ESF file or directory containing ESF files")
    parser.add_argument("--output-path", help="Explicit QuakeML output path")
    parser.add_argument("--datum-config", help="INI file with [datum] latitude/longitude/elevation_m/local_unit_m")
    parser.add_argument("--local-unit-m", type=float, help="Override meters per local coordinate unit")
    args = parser.parse_args()

    convert_esf_quakeml(
        args.path,
        output_path=args.output_path,
        datum_config=args.datum_config,
        local_unit_m=args.local_unit_m,
    )


if __name__ == "__main__":
    main()
