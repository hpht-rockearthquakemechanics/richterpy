"""PCF parsing helpers."""

from __future__ import annotations

from pathlib import Path
import re
import struct


def _extract_ascii_strings(raw: bytes, min_len: int = 4) -> list[str]:
    strings: list[str] = []
    current: list[str] = []
    for byte in raw:
        if 32 <= byte <= 126:
            current.append(chr(byte))
            continue
        if len(current) >= min_len:
            strings.append("".join(current).strip())
        current = []
    if len(current) >= min_len:
        strings.append("".join(current).strip())
    return strings


def _unique_in_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _normalize_stream_label(text: str) -> str | None:
    match = re.search(r"Data Streamed on \d{2}/\d{2}/\d{2}", text)
    if match:
        return match.group(0)
    if "Data Streamed on" in text:
        start = text.index("Data Streamed on")
        return text[start:].strip()
    return None


def _extract_stream_entries(raw: bytes) -> list[str]:
    entries: list[str] = []
    for s in _extract_ascii_strings(raw):
        if "Data Streamed on" not in s:
            continue
        label = _normalize_stream_label(s) or s
        stem_match = re.search(r"(20\d{6}\d{6}_\d+)", s)
        if stem_match:
            entries.append(f"{label} | stem {stem_match.group(1)}")
        else:
            entries.append(label)
    return _unique_in_order(entries)


def _exact_numeric_hits(raw: bytes, value: float) -> list[str]:
    hits: list[str] = []
    for label, pat in [
        ("f64le", struct.pack("<d", value)),
        ("f64be", struct.pack(">d", value)),
        ("f32le", struct.pack("<f", value)),
        ("f32be", struct.pack(">f", value)),
    ]:
        idx = raw.find(pat)
        if idx != -1:
            hits.append(f"{label}@{idx}")
    return hits


def _extract_windows_paths(raw: bytes) -> list[str]:
    paths: list[str] = []
    for s in _extract_ascii_strings(raw):
        if re.search(r"[A-Za-z]:\\", s):
            if any(ext in s.lower() for ext in [".csv", ".rpt", ".esf", ".bsf", ".bif"]) or "insitelab_projects" in s.lower():
                paths.append(s)
    return _unique_in_order(paths)


def _decode_length_value_strings(raw: bytes, start: int, limit: int = 16) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    pos = start
    for _ in range(limit):
        if pos + 3 > len(raw):
            break
        prefix = raw[pos:pos + 3]
        if not prefix.isdigit():
            break
        ln = int(prefix)
        pos += 3
        if ln <= 0 or pos + ln > len(raw):
            break
        payload = raw[pos:pos + ln]
        if not all(32 <= b <= 126 for b in payload):
            break
        out.append((ln, payload.decode("ascii", errors="ignore")))
        pos += ln
    return out


def _scan_length_value_runs(raw: bytes) -> list[str]:
    lines: list[str] = []
    for start, *_ in _candidate_station_runs(raw):
        triples = _decode_length_value_strings(raw, start, limit=6)
        if len(triples) >= 3:
            pieces = [f"{ln:03d}:{text}" for ln, text in triples]
            lines.append(f"offset {start}: " + " | ".join(pieces))
    return _unique_in_order(lines)


def _encoded_length_value_run(values: list[str]) -> str:
    return "".join(f"{len(value):03d}{value}" for value in values)


def _candidate_station_runs(raw: bytes) -> list[tuple[int, str, str, str, str]]:
    candidates: list[tuple[int, str, str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for match in re.finditer(rb"\d{3}S\d{3}", raw):
        start = match.start()
        triples = _decode_length_value_strings(raw, start, limit=4)
        if len(triples) < 3:
            continue
        values = [value for _, value in triples[:3]]
        channel_label, owner_array, instrument_label = values
        if not re.fullmatch(r"S\d{3}", channel_label):
            continue
        key = (channel_label, owner_array, instrument_label)
        if key in seen:
            continue
        seen.add(key)
        station_label = _encoded_length_value_run(values)
        candidates.append((start, station_label, channel_label, owner_array, instrument_label))
    return candidates


def _read_station_numeric_block(raw: bytes, label_offset: int) -> dict[str, float] | None:
    start = label_offset - 144
    if start < 0 or start + 112 > len(raw):
        return None
    values = struct.unpack("<14d", raw[start:start + 112])
    local_unit_m = values[6]
    if not (0 < local_unit_m < 1):
        return None
    if any(abs(value) > 10_000_000 for value in values):
        return None
    return {
        "North": values[0],
        "East": values[1],
        "Down": values[2],
        "Orientation_N": values[3],
        "Orientation_E": values[4],
        "Orientation_D": values[5],
        "Local_Unit_M": local_unit_m,
        "P_Station_Correction": values[7],
        "On": values[8],
        "Gain": values[9],
        "Vmax": values[10],
        "LowFreq": values[11],
        "HighFreq": values[12],
        "Axis_Number": values[13],
    }


def _read_station_header(raw: bytes, label_offset: int) -> dict[str, int] | None:
    start = label_offset - 176
    if start < 0 or start + 32 > len(raw):
        return None
    values = struct.unpack("<8i", raw[start:start + 32])
    instrument_number = values[5]
    channel_number = values[6]
    if instrument_number <= 0 or channel_number <= 0:
        return None
    return {
        "Instrument_Number": instrument_number,
        "Channel_Number": channel_number,
        "Array_Instrument_Number": instrument_number,
        "Array_Channel_Number": channel_number,
    }


def _decode_length_prefixed_records(raw: bytes, start: int, limit: int = 16) -> list[str]:
    lines: list[str] = []
    pos = start
    for idx in range(limit):
        if pos + 4 > len(raw):
            break
        ln = int.from_bytes(raw[pos:pos + 4], "little", signed=False)
        if ln <= 0 or pos + 4 + ln > len(raw):
            break
        payload = raw[pos + 4:pos + 4 + ln]
        if ln == 12:
            lines.append(f"record {idx}: len=12 ints={struct.unpack('<3i', payload)}")
        elif ln == 24:
            lines.append(f"record {idx}: len=24 doubles={struct.unpack('<3d', payload)}")
        elif all((32 <= b <= 126) or b in {9, 10, 13} for b in payload):
            lines.append(f"record {idx}: len={ln} text={payload.decode('ascii', errors='ignore')}")
        else:
            lines.append(f"record {idx}: len={ln} hex={payload[:48].hex(' ')}")
        pos += 4 + ln
    return lines


def _extract_pcf_station_records(raw: bytes) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for idx, label, channel_label, owner_array, instrument_label in _candidate_station_runs(raw):
        header_values = _read_station_header(raw, idx) or {}
        numeric_values = _read_station_numeric_block(raw, idx)
        if numeric_values is None:
            continue
        channel_num = int(header_values.get("Channel_Number", int(channel_label[1:])))
        record: dict[str, object] = {
            "Station_Label": label,
            "Instrument_Number": header_values.get("Instrument_Number", channel_num),
            "Channel_Number": channel_num,
            "Channel_Label": channel_label,
            "Owner_Array": owner_array,
            "Instrument_Label": instrument_label,
            "On": 1.0,
            "Gain": 1.0,
            "Sensitivity": 1.0,
            "Vmax": 10.0,
            "LowFreq": 1.0,
            "HighFreq": 5000000.0,
            "Orientation_N": 0.0,
            "Orientation_E": 0.0,
            "Orientation_D": 1.0,
            "Motion": 1.0,
            "Local_Unit_M": 0.001,
            "P_Station_Correction": 0.0,
            "S_Station_Correction": 0.0,
            "Array_Instrument_Number": header_values.get("Array_Instrument_Number"),
            "Array_Channel_Number": header_values.get("Array_Channel_Number"),
        }
        record.update(numeric_values)
        records.append(record)
    return records


def extract_pcf_station_records(path: str | Path) -> list[dict[str, object]]:
    """Extract structured station records from a PCF file."""

    return _extract_pcf_station_records(Path(path).read_bytes())


def decode_pcf_txt(path: str | Path) -> Path:
    """Write a human-readable PCF summary next to the source file."""

    path = Path(path)
    raw = path.read_bytes()
    lines: list[str] = []
    lines.append(f"FILE: {path}")
    lines.append(f"SIZE: {len(raw)} bytes")
    lines.append("")
    lines.append("[PROJECT PATHS]")
    lines.extend(_extract_windows_paths(raw))
    lines.append("")
    lines.append("[STREAM ENTRIES]")
    lines.extend(_extract_stream_entries(raw))
    lines.append("")
    lines.append("[STATION/CHANNEL METADATA]")
    for record in _extract_pcf_station_records(raw):
        label = str(record["Station_Label"])
        idx = raw.find(label.encode("ascii"))
        if idx == -1:
            continue
        lines.append(f"{label} @offset {idx}")
        for key in ("Instrument_Number", "Instrument_Label", "Channel_Number", "Channel_Label", "Owner_Array"):
            lines.append(f"  {key}: {record[key]}")
        for ln, text in _decode_length_value_strings(raw, idx, limit=6):
            lines.append(f"  {ln:03d}:{text}")
        for key in (
            "North", "East", "Down", "On", "Gain", "Sensitivity", "Vmax", "LowFreq", "HighFreq",
            "Orientation_N", "Orientation_E", "Orientation_D", "Motion", "Axis_Number", "P_Station_Correction",
            "S_Station_Correction", "Local_Unit_M", "Array_Instrument_Number", "Array_Channel_Number",
        ):
            value = record[key]
            if value is None:
                lines.append(f"  {key}: unknown")
                continue
            hits = _exact_numeric_hits(raw, value)
            suffix = ", ".join(hits) if hits else "none"
            lines.append(f"  {key}: {value} -> {suffix}")
    lines.append("")
    lines.append("[CHANNEL CONFIG ROWS]")
    for row in raw.decode("ascii", errors="ignore").split("\r"):
        s = row.strip()
        if re.fullmatch(r"(?:1,1,0\.017,5,100,35,,,,,,|2,1,0\.011,5,100,35,,,,,,|3,1,0\.194,5,100,35,,,,,,|4,1,0\.01,5,100,35,,,,,,)", s):
            lines.append(s)
    lines.append("")
    lines.append("[CHANNEL/STYLE BLOCK]")
    for row in raw.decode("ascii", errors="ignore").split("\r"):
        row = row.strip()
        if re.fullmatch(r"(?:[0-9]+,Arial,[^\r\n]*|richter-m,[^\r\n]*|Channel [0-9]{2}[^\r\n]*)", row):
            lines.append(row)
    lines.append("")
    lines.append("[LENGTH-VALUE RUNS]")
    runs = _scan_length_value_runs(raw)
    lines.extend(runs if runs else ["none"])
    lines.append("")
    lines.append("[EVENT BLOCK SAMPLE]")
    stem_match = re.search(rb"20\d{12}_\d+", raw)
    stem_idx = stem_match.start() if stem_match else -1
    if stem_idx != -1:
        record_idx = raw.find(b"\x0c\x00\x00\x00\x01\x00\x00\x00\x02\x00\x00\x00\x04\x00\x00\x00", stem_idx)
        if record_idx != -1:
            lines.extend(_decode_length_prefixed_records(raw, record_idx, limit=20))
        else:
            lines.append(f"event stem found at {stem_idx}, but no record cluster was located")
    else:
        lines.append("event stem not found")
    lines.append("")
    lines.append("[RAW HEX WINDOWS]")
    for off in [0, 421, 524709, 1049453, 1573997]:
        if off < len(raw):
            lines.append(f"offset {off}: {raw[off:off + 96].hex(' ')}")

    output_path = Path(f"{path}.txt")
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path


def _normalize_station_dataframe(df):
    rename_map = {
        "instrument_number": "Instrument_Number",
        "channel_number": "Channel_Number",
        "channel_label": "Channel_Label",
        "owner_array": "Owner_Array",
        "instrument_label": "Instrument_Label",
        "north": "North",
        "east": "East",
        "down": "Down",
        "orientation_n": "Orientation_N",
        "orientation_e": "Orientation_E",
        "orientation_d": "Orientation_D",
        "axis_number": "Axis_Number",
        "p_station_correction": "P_Station_Correction",
        "s_station_correction": "S_Station_Correction",
        "local_unit_m": "Local_Unit_M",
        "array_instrument_number": "Array_Instrument_Number",
        "array_channel_number": "Array_Channel_Number",
    }
    df = df.rename(columns={col: rename_map.get(col, col) for col in df.columns})

    if "Instrument_Number" not in df.columns and "Array_Instrument_Number" in df.columns:
        df["Instrument_Number"] = df["Array_Instrument_Number"]
    if "Channel_Number" not in df.columns and "Array_Channel_Number" in df.columns:
        df["Channel_Number"] = df["Array_Channel_Number"]
    if "Channel_Label" not in df.columns and "Channel_Number" in df.columns:
        df["Channel_Label"] = df["Channel_Number"].apply(lambda x: f"S{int(x):03d}")
    if "Owner_Array" not in df.columns:
        df["Owner_Array"] = "richter"
    if "Instrument_Label" not in df.columns:
        df["Instrument_Label"] = ""
    for col, default in {
        "Orientation_N": 0.0,
        "Orientation_E": 0.0,
        "Orientation_D": 1.0,
        "P_Station_Correction": 0.0,
        "S_Station_Correction": 0.0,
        "Local_Unit_M": 0.001,
        "Axis_Number": 2.0,
    }.items():
        if col not in df.columns:
            df[col] = default

    required = ["Instrument_Number", "North", "East", "Down", "Orientation_N", "Orientation_E", "Orientation_D"]
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"PCF-derived CSV is missing required columns: {', '.join(missing)}")

    return df


def convert_pcf_to_csv(path: str | Path, output_path: str | Path | None = None) -> Path:
    """Convert a PCF file into a normalized station CSV.

    This reuses ``decode_pcf_txt(...)`` and converts the structured station
    metadata blocks from the generated report into the CSV schema expected by
    ``convert_stations()``.
    """

    path = Path(path)
    output_path = Path(output_path) if output_path is not None else path.with_suffix(".csv")

    import pandas as pd

    df = _normalize_station_dataframe(pd.DataFrame(extract_pcf_station_records(path)))

    with output_path.open("w", encoding="utf-8", newline="") as f:
        df.to_csv(f, index=False)

    return output_path
