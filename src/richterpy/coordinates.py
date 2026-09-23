from __future__ import annotations

from configparser import ConfigParser
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Datum:
    """Geographic reference point for local InSite coordinates.

    ``local_unit_m`` is metres per local coordinate unit. Existing m0013 data
    uses ``0.001``: local North/East/Down values are millimetres.
    """

    latitude: float = 41.828272066465786
    longitude: float = 12.515104006116623
    elevation: float = 0.001
    local_unit_m: float = 0.001


DEFAULT_DATUM = Datum()


def coerce_datum(datum: Datum | dict[str, float] | None = None, *, local_unit_m: float | None = None) -> Datum:
    """Return a Datum from ``None``, a Datum, or a compatible mapping."""

    if datum is None:
        base = DEFAULT_DATUM
    elif isinstance(datum, Datum):
        base = datum
    else:
        base = Datum(
            latitude=float(datum["latitude"]),
            longitude=float(datum["longitude"]),
            elevation=float(datum.get("elevation", datum.get("elevation_m"))),
            local_unit_m=float(datum.get("local_unit_m", DEFAULT_DATUM.local_unit_m)),
        )

    if local_unit_m is None:
        return base
    return Datum(base.latitude, base.longitude, base.elevation, float(local_unit_m))


def load_datum_config(path: str | Path) -> Datum:
    """Load datum settings from an INI file.

    Expected section/key names are compatible with ``config/MEERA.ini``:
    ``[datum] latitude``, ``longitude``, ``elevation_m``, and ``local_unit_m``.
    ``elevation`` is accepted as a fallback for ``elevation_m``.
    """

    path = Path(path)
    parser = ConfigParser()
    read_files = parser.read(path, encoding="utf-8")
    if not read_files:
        raise FileNotFoundError(f"Datum config not found: {path}")
    if not parser.has_section("datum"):
        raise ValueError(f"Datum config is missing [datum]: {path}")

    section = parser["datum"]
    try:
        elevation_text = section.get("elevation_m", section.get("elevation"))
        if elevation_text is None:
            raise KeyError("elevation_m")
        return Datum(
            latitude=section.getfloat("latitude"),
            longitude=section.getfloat("longitude"),
            elevation=float(elevation_text),
            local_unit_m=section.getfloat("local_unit_m", fallback=DEFAULT_DATUM.local_unit_m),
        )
    except (KeyError, ValueError) as exc:
        raise ValueError(f"Invalid datum config [datum] values: {path}") from exc


def resolve_datum(
    datum: Datum | dict[str, float] | None = None,
    *,
    datum_config: str | Path | None = None,
    local_unit_m: float | None = None,
) -> Datum:
    """Resolve explicit datum/config/default values in precedence order."""

    if datum is not None and datum_config is not None:
        raise ValueError("Provide either datum or datum_config, not both")
    base = load_datum_config(datum_config) if datum_config is not None else coerce_datum(datum)
    return coerce_datum(base, local_unit_m=local_unit_m)


def local_to_geographic(north: float, east: float, down: float, datum: Datum | dict[str, float] | None = None) -> dict[str, float]:
    """Convert local North/East/Down coordinates to geographic coordinates.

    The signs preserve the legacy project convention: positive local North/East
    decrease latitude/longitude relative to the datum; positive Down decreases
    elevation and increases ObsPy/QuakeML depth.
    """

    datum = coerce_datum(datum)
    north_m = float(north) * datum.local_unit_m
    east_m = float(east) * datum.local_unit_m
    down_m = float(down) * datum.local_unit_m
    return {
        "latitude": datum.latitude - north_m * 9.009e-6,
        "longitude": datum.longitude - east_m * 1.209e-5,
        "elevation": datum.elevation - down_m,
        "depth": down_m - datum.elevation,
        "local_unit_m": datum.local_unit_m,
    }
