"""ATF parsing and waveform helpers."""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np


def _locate_atf_files(path: str | Path) -> list[Path]:
    path = Path(path)

    if path.is_file() and path.suffix.lower() == ".atf":
        return [path]

    if path.is_dir():
        search_dir = path if path.name.lower() == "esf" else path / "ESF"
        if search_dir.is_dir():
            candidates = sorted(search_dir.rglob("*.ATF")) + sorted(search_dir.rglob("*.atf"))
            return list(dict.fromkeys(candidates))

    raise FileNotFoundError(f"No ATF files found under {path}")


def _detect_atf_starttime(path: Path, header: dict[str, str]):
    from datetime import datetime
    from decimal import Decimal

    from obspy import UTCDateTime

    time_str = header.get("Time")
    date_str = header.get("Date")
    if time_str and date_str:
        try:
            base_time, fractional = (time_str.split(".", 1) + [""])[:2]
            dt = datetime.strptime(f"{date_str} {base_time}", "%d-%m-%Y %H:%M:%S")
            if fractional:
                frac_seconds = Decimal(f"0.{fractional}")
                return UTCDateTime(dt) + float(frac_seconds)
            return UTCDateTime(dt)
        except Exception:
            raise ValueError(f"Cannot parse ATF starttime from header in {path}")

    raise ValueError(f"ATF header missing Date/Time fields in {path}")


def _parse_atf_header(path: Path) -> tuple[dict[str, str], np.ndarray]:
    raw = np.memmap(path, dtype="u1", mode="r")
    text = raw.tobytes().decode("utf-8", errors="ignore")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines or not lines[0].startswith("ATF"):
        raise ValueError(f"Not a valid ATF file: {path}")

    header: dict[str, str] = {}
    trace_start = None
    for idx, line in enumerate(lines):
        if line == "[TraceData]":
            trace_start = idx + 1
            break
        if ";" in line and "=" in line:
            for part in line.split(";"):
                part = part.strip()
                if not part or "=" not in part:
                    continue
                key, value = part.split("=", 1)
                header[key.strip()] = value.strip()

    if trace_start is None:
        raise ValueError(f"ATF trace data section not found: {path}")

    data = np.array([float(line.split()[0]) for line in lines[trace_start:] if line and line[0] not in "["], dtype=np.float64)
    del raw
    return header, data


def _header_float(header: dict[str, str], key: str) -> float | None:
    value = header.get(key)
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def read_atf(path: str | Path, station_channel_map: dict[str, str] | None = None):
    """Read a single ATF file and return an ObsPy Stream plus metadata."""

    from obspy import Stream, Trace

    path = Path(path)
    header, data = _parse_atf_header(path)
    starttime = _detect_atf_starttime(path, header)
    sample_rate = 1.0 / float(header.get("TSamp", "1.0"))

    channel_name = path.stem.split("_")[-1]
    station_code = f"S{int(channel_name):02d}" if channel_name.isdigit() else "S01"
    channel_code = f"CH{channel_name}" if channel_name.isdigit() else "CH1"
    if station_channel_map:
        mapped = station_channel_map.get(station_code)
        if mapped is None:
            return Stream(), {"source_path": str(path), "header": header, "starttime": starttime, "sample_rate": sample_rate}
        channel_code = mapped

    trace = Trace(data=data)
    trace.stats.station = station_code
    trace.stats.channel = channel_code
    trace.stats.location = "RAW"
    trace.stats.network = "RC"
    trace.stats.starttime = starttime
    trace.stats.sampling_rate = sample_rate

    metadata = {
        "source_path": str(path),
        "header": header,
        "starttime": starttime,
        "sample_rate": sample_rate,
        "trace_points": int(header.get("TracePoints", data.size)),
        "time_units": _header_float(header, "TimeUnits"),
        "amp_to_volts": _header_float(header, "AmpToVolts"),
        "trace_max_volts": _header_float(header, "TraceMaxVolts"),
        "ptime": _header_float(header, "PTime"),
        "stime": _header_float(header, "STime"),
    }
    return Stream(traces=[trace]), metadata


def build_atf_stream(path: str | Path, station_channel_map: dict[str, str] | None = None):
    """Build a master ObsPy Stream from an ATF folder or single file."""

    from obspy import Stream

    path = Path(path)
    if path.is_file() and path.suffix.lower() == ".atf":
        return read_atf(path, station_channel_map=station_channel_map)[0]

    atf_paths = _locate_atf_files(path)
    if not atf_paths:
        raise FileNotFoundError(f"No .ATF files were found under {path}")

    master_stream = Stream()
    for atf_path in atf_paths:
        st, _ = read_atf(atf_path, station_channel_map=station_channel_map)
        master_stream += st

    if len(master_stream) == 0:
        raise FileNotFoundError(f"No readable .ATF files were found under {path}")

    master_stream.sort(["starttime", "station", "channel"])
    return master_stream
