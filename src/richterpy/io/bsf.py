"""BSF parsing and plotting helpers."""

from __future__ import annotations

import re
from pathlib import Path

from richterpy.io.esf import SAMPLES_PER_CHANNEL, decode_bsf_txt, plot_bsf_png

MAX_BSF_CHANNELS = 12


def _locate_bif(path: str | Path) -> tuple[Path, Path]:
    path = Path(path)

    if path.is_file() and path.suffix.lower() == ".bif":
        return path, path.parent

    if path.is_dir():
        index_dir = path if path.name.lower() == "index" else path / "index"
        if index_dir.is_dir():
            bif_candidates = sorted(index_dir.glob("*.BIF")) + sorted(index_dir.glob("*.bif"))
            if bif_candidates:
                bif_path = bif_candidates[0]
                return bif_path, index_dir.parent

        bif_candidates = sorted(path.rglob("*.BIF")) + sorted(path.rglob("*.bif"))
        for bif_path in bif_candidates:
            if bif_path.parent.name.lower() == "index":
                return bif_path, bif_path.parent.parent

    raise FileNotFoundError(f"No .BIF manifest found under {path}")


def _extract_bsf_paths_from_bif(bif_path: str | Path, base_dir: str | Path | None = None) -> list[Path]:
    bif_path = Path(bif_path)
    base_dir = Path(base_dir) if base_dir is not None else bif_path.parent
    raw_text = bif_path.read_text(encoding="utf-8", errors="ignore")
    paths: list[Path] = []
    for line in raw_text.splitlines():
        line = line.strip()
        match = re.match(r"^\s*\d+\s*:\s*(.+?)\s*#\s*$", line)
        if not match:
            continue
        candidate = match.group(1).strip().strip('"').strip("'")
        candidate = candidate.lstrip("\\/")
        if not candidate:
            continue
        candidate_path = Path(candidate)
        if not candidate_path.is_absolute() and not re.match(r"^(?:[A-Za-z]:\\|\\\\)", candidate):
            candidate_path = base_dir / candidate_path
        paths.append(candidate_path.resolve())
    return list(dict.fromkeys(paths))


def _detect_starttime(path: Path):
    from datetime import datetime, timedelta

    from obspy import UTCDateTime

    m = re.fullmatch(r"(?P<sec>\d{2})_(?P<subsec>\d{4})", path.stem)
    if m:
        try:
            minute = int(path.parent.name)
            hour = int(path.parent.parent.name)
            day = int(path.parent.parent.parent.name)
            month = int(path.parent.parent.parent.parent.name)
            year = int(path.parent.parent.parent.parent.parent.name)
            sec = int(m.group("sec"))
            subsec = int(m.group("subsec"))
            dt = datetime(year, month, day, hour, minute, sec) + timedelta(microseconds=subsec * 100)
            return UTCDateTime(dt)
        except Exception:
            pass

    stem = path.stem
    for pattern, fmt in (
        (r"(\d{8})_(\d{6})", "%Y%m%d_%H%M%S"),
        (r"(\d{14})", "%Y%m%d%H%M%S"),
    ):
        m = re.search(pattern, stem)
        if m:
            value = m.group(0)
            try:
                return UTCDateTime(datetime.strptime(value, fmt))
            except Exception:
                continue
    return UTCDateTime(0)


def _infer_bsf_layout(payload_size: int, station_channel_map: dict[str, str] | None = None) -> tuple[int, int]:
    if station_channel_map:
        numeric_suffixes: list[int] = []
        for station_code in station_channel_map:
            match = re.fullmatch(r"S(\d{2})", station_code)
            if match:
                numeric_suffixes.append(int(match.group(1)))
        if numeric_suffixes:
            channel_count = max(numeric_suffixes)
            if channel_count > MAX_BSF_CHANNELS:
                raise ValueError(
                    f"BSF channel_count {channel_count} exceeds maximum supported {MAX_BSF_CHANNELS}"
                )
            numerator = payload_size - 32 * (channel_count - 1)
            if numerator <= 0 or numerator % channel_count != 0:
                raise ValueError(
                    f"Cannot infer BSF samples_per_channel from payload={payload_size} and channels={channel_count}"
                )
            samples_per_channel = numerator // channel_count
            if samples_per_channel > SAMPLES_PER_CHANNEL:
                raise ValueError(
                    f"BSF samples_per_channel {samples_per_channel} exceeds maximum supported {SAMPLES_PER_CHANNEL}"
                )
            return channel_count, samples_per_channel

    candidates: list[tuple[int, int]] = []
    for channel_count in range(1, MAX_BSF_CHANNELS + 1):
        numerator = payload_size - 32 * (channel_count - 1)
        if numerator <= 0 or numerator % channel_count != 0:
            continue
        samples_per_channel = numerator // channel_count
        if 1 <= samples_per_channel <= SAMPLES_PER_CHANNEL:
            candidates.append((channel_count, samples_per_channel))

    if not candidates:
        raise ValueError(f"Cannot infer BSF layout from payload size {payload_size}")

    candidates.sort(key=lambda item: (abs(item[1] - SAMPLES_PER_CHANNEL), item[0]))
    return candidates[0]


def _extract_bsf_waveforms(path: str | Path, station_channel_map: dict[str, str] | None = None) -> tuple[list[object], dict[str, object]]:
    import numpy as np

    path = Path(path)
    file_size = path.stat().st_size
    payload_size = (file_size - 421) // 8
    payload = np.memmap(path, dtype="<f8", mode="r", offset=421, shape=(payload_size,))
    channel_count, samples_per_channel = _infer_bsf_layout(payload.size, station_channel_map=station_channel_map)
    block = samples_per_channel + 32
    expected_size = (channel_count - 1) * block + samples_per_channel
    if payload.size < expected_size:
        raise ValueError(f"BSF payload is too short: {path}")
    if payload.size > expected_size:
        payload = payload[:expected_size]

    waveforms: list[object] = []
    channel_metadata_tail_f64: list[object] = []
    for idx in range(channel_count):
        if idx < channel_count - 1:
            start = idx * block
            waveforms.append(payload[start : start + samples_per_channel])
            channel_metadata_tail_f64.append(payload[start + samples_per_channel : start + block].copy())
        else:
            start = idx * block
            waveforms.append(payload[start : start + samples_per_channel])

    metadata: dict[str, object] = {
        "source_path": str(path),
        "file_size": int(file_size),
        "payload_size_f64": int(payload.size),
        "sample_rate": 10_000_000.0,
        "starttime": _detect_starttime(path),
        "channel_count": channel_count,
        "samples_per_channel": samples_per_channel,
        "channel_metadata_tail_f64": channel_metadata_tail_f64,
    }

    return waveforms, metadata


def read_bsf(path: str | Path, station_channel_map: dict[str, str] | None = None):
    """Read a single BSF file and return an ObsPy Stream plus metadata."""

    from obspy import Stream, Trace

    path = Path(path)
    waveforms, metadata = _extract_bsf_waveforms(path, station_channel_map=station_channel_map)
    traces = []
    for idx, wave in enumerate(waveforms, start=1):
        trace = Trace(data=wave)
        station_code = f"S{idx:02d}"
        channel_code = f"CH{idx}"
        if station_channel_map:
            channel_code = station_channel_map.get(station_code)
            if channel_code is None:
                continue
        trace.stats.station = station_code
        trace.stats.channel = channel_code
        trace.stats.location = "RAW"
        trace.stats.network = "RC"
        trace.stats.starttime = metadata["starttime"]
        trace.stats.sampling_rate = metadata["sample_rate"]
        traces.append(trace)

    return Stream(traces=traces), metadata


def build_bsf_stream(path: str | Path, station_channel_map: dict[str, str] | None = None):
    """Build a master ObsPy Stream from a BSF folder or `.bif` manifest."""

    from obspy import Stream

    path = Path(path)

    if path.is_file() and path.suffix.lower() == ".bsf":
        return read_bsf(path, station_channel_map=station_channel_map)[0]

    bif_path, base_dir = _locate_bif(path)
    bsf_paths = _extract_bsf_paths_from_bif(bif_path, base_dir=base_dir)
    if not bsf_paths:
        raise FileNotFoundError(f"No .bsf paths were listed in {bif_path}")

    master_stream = Stream()
    for bsf_path in bsf_paths:
        if not bsf_path.is_file():
            continue
        st, _ = read_bsf(bsf_path, station_channel_map=station_channel_map)
        master_stream += st

    if len(master_stream) == 0:
        raise FileNotFoundError(f"No readable .bsf files were found via {bif_path}")

    master_stream.sort(["starttime", "station", "channel"])
    return master_stream
