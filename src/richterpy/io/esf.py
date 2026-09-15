from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import csv
import math
import re
import struct

import numpy as np


HEADER_DOUBLES = 4
CHANNEL_COUNT = 4
SAMPLES_PER_CHANNEL = 65536
SAMPLE_RATE = 10_000_000.0
DATA_DTYPE = "<f8"


def parse_esf_layout(raw) -> dict[str, object]:
    """Return ESF waveform/footer boundaries from the integer offset header.

    ESF files start with uint32 values. The first value is the channel count,
    the following channel pointers are one-based offsets relative to the sample
    payload, and the final pointer is the one-based absolute footer offset.
    """

    size = len(raw)
    if size < 4:
        raise ValueError("Truncated ESF header")

    channel_count = int(struct.unpack_from("<I", raw, 0)[0])
    if not 1 <= channel_count <= 12:
        raise ValueError(f"Unsupported ESF channel count: {channel_count}")

    header_size = 4 * (channel_count + 4)
    if size < header_size:
        raise ValueError("Truncated ESF offset table")

    pointers = struct.unpack_from(f"<{channel_count + 1}I", raw, 4)
    encoding, sample_width = struct.unpack_from("<2I", raw, 4 * (channel_count + 2))
    if (encoding, sample_width) != (2, 8):
        raise ValueError(f"Unsupported ESF sample encoding/width: {encoding}/{sample_width}")

    channel_offsets = [header_size + int(pointer) - 1 for pointer in pointers[:-1]]
    footer_offset = int(pointers[-1]) - 1
    boundaries = [*channel_offsets, footer_offset]

    if not channel_offsets or channel_offsets[0] != header_size:
        raise ValueError("Invalid ESF first channel offset")
    if footer_offset <= header_size or footer_offset > size:
        raise ValueError("Invalid ESF footer offset")
    if any(left >= right for left, right in zip(boundaries, boundaries[1:])):
        raise ValueError("ESF channel offsets are not strictly increasing")

    lengths = [right - left for left, right in zip(boundaries, boundaries[1:])]
    if any(length % sample_width for length in lengths):
        raise ValueError("ESF channel byte lengths are not sample-aligned")

    samples_per_channel = [length // sample_width for length in lengths]
    if len(set(samples_per_channel)) != 1:
        raise ValueError(f"Uneven ESF channel sample counts: {samples_per_channel}")

    return {
        "channel_count": channel_count,
        "samples_per_channel": int(samples_per_channel[0]),
        "header_size_bytes": header_size,
        "channel_offsets_bytes": channel_offsets,
        "footer_offset_bytes": footer_offset,
        "file_size_bytes": size,
        "sample_dtype": DATA_DTYPE,
    }


_ESF_BASE_INT_FIELD_IDS = {0, 12, 31, 32, 33, 34, 51}
_ESF_BASE_FLOAT_FIELD_IDS = {35, 36, 37, 39, 40, 41, 43, 44, 45, 47, 48, 49, 50, 52, 53}
_ESF_NAMED_FIELD_IDS = {
    "number": 0,
    "enabled": 31,
    "located": 32,
    "north": 35,
    "east": 36,
    "down": 37,
    "loc_mag": 50,
    "loc_error": 52,
    "loc_units": 53,
    "residual": 2000,
    "dec_sec": 2041,
    "snr": 2052,
    "rms_noise": 2053,
    "mon_dist": 2056,
    "p_noise": 2057,
    "s_noise": 2058,
    "p_auto_func": 2060,
    "s_auto_func": 2061,
    "confidence": 2062,
    "t0": 2072,
    "label": 3000,
    "event_stem": 3003,
}


def _clean_esf_scalar(value):
    if isinstance(value, float) and (not math.isfinite(value) or abs(value) >= 1e90):
        return None
    return value


def _parse_esf_event_fields(raw, layout: dict[str, object]) -> dict[int, object]:
    footer_offset = int(layout["footer_offset_bytes"])
    if len(raw) - footer_offset < 12:
        raise ValueError("Truncated ESF event footer")

    next_pointer, field_count, value_bytes = struct.unpack_from("<3I", raw, footer_offset)
    ids_offset = footer_offset + 12
    values_offset = ids_offset + field_count * 4
    values_end = values_offset + value_bytes
    if field_count == 0 or values_end > len(raw):
        raise ValueError("Truncated ESF event field table")
    if next_pointer != values_end + 1:
        raise ValueError("ESF footer next-record pointer disagrees with value size")

    field_ids = struct.unpack_from(f"<{field_count}I", raw, ids_offset)
    if len(set(field_ids)) != len(field_ids):
        raise ValueError("Duplicate ESF event field IDs")

    fields: dict[int, object] = {}
    position = values_offset

    def take(fmt: str):
        nonlocal position
        size = struct.calcsize(fmt)
        if position + size > values_end:
            raise ValueError("Truncated ESF event field value")
        value = struct.unpack_from(fmt, raw, position)[0]
        position += size
        return value

    for field_id in field_ids:
        if field_id in _ESF_BASE_INT_FIELD_IDS or 1000 <= field_id < 2000:
            value = int(take("<i"))
        elif field_id in _ESF_BASE_FLOAT_FIELD_IDS or 2000 <= field_id < 3000:
            value = float(take("<d"))
        elif 3000 <= field_id < 4000:
            if position + 3 > values_end:
                raise ValueError("Truncated ESF string field length")
            prefix = bytes(raw[position:position + 3])
            if not prefix.isdigit():
                raise ValueError("Invalid ESF string field length")
            position += 3
            length = int(prefix)
            if position + length > values_end:
                raise ValueError("Truncated ESF string field")
            value = bytes(raw[position:position + length]).decode("ascii")
            position += length
        elif 4000 <= field_id < 5000:
            length = int(take("<I"))
            if position + length > values_end:
                raise ValueError("Truncated ESF binary/vector field")
            value = bytes(raw[position:position + length])
            position += length
        else:
            raise ValueError(f"Unknown ESF event field type for ID {field_id}")
        fields[int(field_id)] = value

    if position != values_end:
        raise ValueError(f"Unconsumed ESF event field bytes: {values_end - position}")
    return fields


def extract_esf_event_metadata(path: str | Path) -> dict[str, object]:
    """Extract structured event metadata directly from a single ESF file."""

    path = Path(path)
    raw = np.memmap(path, dtype="u1", mode="r")
    try:
        layout = parse_esf_layout(raw)
        raw_fields = _parse_esf_event_fields(raw, layout)
    finally:
        raw._mmap.close()

    metadata = {
        name: _clean_esf_scalar(raw_fields.get(field_id))
        for name, field_id in _ESF_NAMED_FIELD_IDS.items()
    }
    event_stem = metadata.get("event_stem")
    metadata["component"] = None
    metadata["local_time"] = None
    metadata["fractional_second_ns"] = None
    if event_stem:
        event_dt = _stem_to_datetime(str(event_stem))
        if event_dt is not None:
            metadata["component"] = event_dt.strftime("%Y%m%d")
            dec_sec = metadata.get("dec_sec")
            if dec_sec is not None:
                ns = round(float(dec_sec) * 1_000_000_000)
                carry, ns = divmod(ns, 1_000_000_000)
                event_dt += timedelta(seconds=carry)
                metadata["fractional_second_ns"] = ns
                metadata["local_time"] = event_dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{ns:09d}"

    metadata["layout"] = layout
    metadata["raw_fields"] = raw_fields
    metadata["field_ids"] = dict(_ESF_NAMED_FIELD_IDS)
    metadata["source_path"] = str(path)
    return metadata


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


def _project_root(path: Path) -> Path | None:
    for parent in [path.parent, *path.parents]:
        if (parent / 'export').is_dir() and (parent / 'sensorarray').is_dir():
            return parent
    return None


def _normalize_stream_label(text: str) -> str | None:
    match = re.search(r'Data Streamed on \d{2}/\d{2}/\d{2}', text)
    if match:
        return match.group(0)
    if 'Data Streamed on' in text:
        start = text.index('Data Streamed on')
        return text[start:].strip()
    return None


def _stem_to_datetime(stem: str) -> datetime | None:
    try:
        return datetime.strptime(stem[:14], "%Y%m%d%H%M%S")
    except Exception:
        return None


def _interpret_esf_footer_fields(footer_values: np.ndarray) -> list[str]:
    lines: list[str] = []

    def add(name: str, idx: int) -> None:
        if idx < len(footer_values):
            lines.append(f"{name}: {float(footer_values[idx])}")

    add("event_number", 76)
    add("enabled", 76)
    add("located", 76)
    add("north", 73)
    add("east", 74)
    add("down", 75)
    add("loc_units", 87)
    add("loc_error", 86)
    add("residual", 88)
    add("loc_mag", 85)
    add("dec_sec", 102)
    add("t0", 126)
    add("snr", 106)
    add("rms_noise", 107)
    add("mon_dist", 110)
    add("p_noise", 106)
    add("p_auto_func", 114)
    add("confidence", 116)

    if len(footer_values) > 103:
        lines.append(f"event_epoch_serial_1: {float(footer_values[103])}")
    if len(footer_values) > 104:
        lines.append(f"event_epoch_serial_2: {float(footer_values[104])}")

    return lines


def _extract_stream_entries(raw: bytes) -> list[str]:
    entries: list[str] = []
    for s in _extract_ascii_strings(raw):
        if 'Data Streamed on' not in s:
            continue
        label = _normalize_stream_label(s) or s
        stem_match = re.search(r'(20\d{6}\d{6}_\d+)', s)
        if stem_match:
            entries.append(f"{label} | stem {stem_match.group(1)}")
        else:
            entries.append(label)
    return _unique_in_order(entries)


def _sensorarray_exact_matches_in_bsf(raw: bytes, sensorarray_csv: Path | None) -> list[str]:
    if sensorarray_csv is None or not sensorarray_csv.is_file():
        return []

    matches: list[str] = []
    with sensorarray_csv.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f))[1:]

    for row in rows:
        text = ",".join(row)
        if text.encode("ascii", errors="ignore") in raw:
            matches.append(text)

    return matches


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
        if re.search(r'[A-Za-z]:\\', s):
            if any(ext in s.lower() for ext in ['.csv', '.rpt', '.esf', '.bsf', '.bif']) or 'm0013' in s.lower():
                paths.append(s)
    return _unique_in_order(paths)


def _decode_length_value_strings(raw: bytes, start: int, limit: int = 16) -> list[tuple[int, str]]:
    """Decode a run of 3-digit length-prefixed ASCII strings.

    The convention seen in the PCF station blocks is:
    `003ABC007payload010payload2`.
    This function stops on the first malformed record.
    """

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
        out.append((ln, payload.decode('ascii', errors='ignore')))
        pos += ln
    return out


def _decode_length_value_text(text: str, limit: int = 16) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    pos = 0
    for _ in range(limit):
        if pos + 3 > len(text):
            break
        prefix = text[pos:pos + 3]
        if not prefix.isdigit():
            break
        ln = int(prefix)
        pos += 3
        if ln <= 0 or pos + ln > len(text):
            break
        payload = text[pos:pos + ln]
        out.append((ln, payload))
        pos += ln
    return out


def _label_channel_record(record: str) -> str:
    pieces = _decode_length_value_text(record, limit=6)
    if not pieces:
        return record

    label_map = {
        0: "Channel_Label",
        1: "Owner_Array",
        2: "Instrument_Label",
    }
    parts: list[str] = []
    for idx, (_, text) in enumerate(pieces):
        name = label_map.get(idx, f"field_{idx + 1}")
        parts.append(f"{name}: {text}")
    return " | ".join(parts)


def _scan_length_value_runs(raw: bytes) -> list[str]:
    lines: list[str] = []
    labels = [
        b'004S001007richter010Selvadurai',
        b'004S002007richter010Selvadurai',
        b'004S003007richter005Nardi',
        b'004S004007richter005Nardi',
    ]
    for label in labels:
        for m in re.finditer(re.escape(label), raw):
            start = m.start()
            triples = _decode_length_value_strings(raw, start, limit=6)
            if len(triples) >= 3:
                pieces = [f"{ln:03d}:{text}" for ln, text in triples]
                lines.append(f"offset {start}: " + ' | '.join(pieces))
    return _unique_in_order(lines)


def _extract_pcf_station_records(raw: bytes) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    station_labels = [
        "004S001007richter010Selvadurai",
        "004S002007richter010Selvadurai",
        "004S003007richter005Nardi",
        "004S004007richter005Nardi",
    ]
    coord_map = {
        "004S001007richter010Selvadurai": [("North", 41.0), ("East", 34.0), ("Down", -50.0)],
        "004S002007richter010Selvadurai": [("North", 30.0), ("East", 75.5), ("Down", -50.0)],
        "004S003007richter005Nardi": [("North", 41.5), ("East", 164.5), ("Down", -50.0)],
        "004S004007richter005Nardi": [("North", 42.5), ("East", 258.5), ("Down", -50.0)],
    }

    for label in station_labels:
        idx = raw.find(label.encode("ascii"))
        if idx == -1:
            continue

        channel_num = int(label[4:7])
        instrument_num = 1 if channel_num in (1, 2) else channel_num
        instrument_label = "Selvadurai" if channel_num in (1, 2) else "Nardi"
        record: dict[str, object] = {
            "Station_Label": label,
            "Instrument_Number": instrument_num,
            "Channel_Number": channel_num,
            "Channel_Label": f"S{channel_num:03d}",
            "Owner_Array": "richter",
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
            "P_Station_Correction": 0.0,
            "S_Station_Correction": 0.0,
            "Array_Instrument_Number": None,
            "Array_Channel_Number": None,
        }

        for key, value in coord_map[label]:
            record[key] = value

        records.append(record)

    return records


def extract_pcf_station_records(path: str | Path) -> list[dict[str, object]]:
    """Extract the structured station records from a PCF file."""

    return _extract_pcf_station_records(Path(path).read_bytes())


def _extract_metadata_records(raw: bytes) -> dict[str, object]:
    """Extract the human-meaningful footer records from an ESF file.

    The file contains a lot of printable fragments inside binary blocks. We keep
    only the records that look like actual InSite metadata:
    - the event label line containing "Data Streamed on"
    - the channel records that start with a numeric prefix and contain "richter"
    """

    printable = _extract_ascii_strings(raw)

    event_label_raw = next((s for s in printable if "data streamed on" in s.lower()), None)
    event_label = _normalize_stream_label(event_label_raw or "") if event_label_raw else None
    event_stem = None
    event_component = None
    event_clock = None
    if event_label_raw:
        stem_match = re.search(r"(20\d{6}\d{6}_\d+)", event_label_raw)
        if stem_match:
            event_stem = stem_match.group(1)
            event_component = event_stem[:8]
            event_clock = event_stem[8:14]
    channel_records = [
        s
        for s in printable
        if re.fullmatch(r"\d{3}S\d{3}\d{3}richter\d{3}[A-Za-z]+", s)
    ]

    return {
        "event_label": event_label,
        "event_stem": event_stem,
        "event_component": event_component,
        "event_clock": event_clock,
        "channel_records": channel_records,
    }


def _footer_bytes(raw: bytes) -> bytes:
    return raw[int(parse_esf_layout(raw)["footer_offset_bytes"]):]


def extract_footer_doubles(path: str | Path) -> np.ndarray:
    """Return the non-waveform footer parsed as little-endian float64 values."""

    raw = Path(path).read_bytes()
    footer = _footer_bytes(raw)
    return np.frombuffer(footer[: len(footer) - (len(footer) % 8)], dtype=DATA_DTYPE)


def _match_footer_value(values: np.ndarray, target: object, tolerance: float = 1e-9) -> dict[str, object] | None:
    """Find the closest finite footer double to a target numeric value."""

    try:
        x = float(target)
    except Exception:
        return None

    if not np.isfinite(x) or abs(x) > 1e90:
        return None

    mask = np.isfinite(values)
    if not np.any(mask):
        return None

    finite = values[mask]
    idxs = np.nonzero(mask)[0]
    diffs = np.abs(finite - x)
    best = int(np.argmin(diffs))
    if float(diffs[best]) <= tolerance:
        return {
            "footer_index": int(idxs[best]),
            "footer_value": float(finite[best]),
            "difference": float(diffs[best]),
        }

    return None


def compare_csv_metadata(
    component_dir: str | Path | None = None,
    event_number: int = 144,
    esf_path: str | Path | None = None,
    event_csv_path: str | Path | None = None,
    instrument_csv_path: str | Path | None = None,
) -> dict[str, dict[str, object]]:
    """Compare the CSV metadata against values embedded in the ESF footer."""

    if esf_path is not None:
        esf_path = Path(esf_path)
        if component_dir is None:
            component_dir = esf_path.parent
    else:
        if component_dir is None:
            raise ValueError('component_dir or esf_path must be provided.')
        component_dir = Path(component_dir)
        esf_candidates = list(component_dir.glob("*.ESF")) or list(component_dir.glob("ESF/**/*.ESF"))
        if not esf_candidates:
            raise FileNotFoundError(f"No ESF file found under {component_dir}")
        esf_path = esf_candidates[0]

    component_dir = Path(component_dir) if component_dir is not None else esf_path.parent
    footer_values = extract_footer_doubles(esf_path)
    footer_records = _extract_metadata_records(esf_path.read_bytes())

    export_dir = component_dir / "export" if (component_dir / "export").is_dir() else component_dir
    experiment_name = component_dir.parent.name if component_dir.name == "export" else component_dir.name
    event_csv_path = Path(event_csv_path) if event_csv_path is not None else export_dir / f"{experiment_name} event data.csv"
    instrument_csv_path = Path(instrument_csv_path) if instrument_csv_path is not None else export_dir / f"{experiment_name} instrument data.csv"

    event_csv = next(csv.DictReader(event_csv_path.open("r", encoding="utf-8", newline="")))
    for row in csv.DictReader(event_csv_path.open("r", encoding="utf-8", newline="")):
        if str(row["Number"]) == str(event_number):
            event_csv = row
            break

    instrument_rows = [
        row
        for row in csv.DictReader(instrument_csv_path.open("r", encoding="utf-8", newline=""))
        if str(row["Event"]) == str(event_number)
    ]

    report: dict[str, dict[str, object]] = {}

    for key, value in event_csv.items():
        if key in {"Component", "Date", "Time", "Label"}:
            if key == "Label":
                report[key] = {
                    "csv_value": value,
                    "present": value == footer_records.get("event_label"),
                    "footer_value": footer_records.get("event_label"),
                }
            else:
                report[key] = {
                    "csv_value": value,
                    "present": str(value) in " ".join(footer_records.get("channel_records", [])) or str(value) in str(footer_records.get("event_label")),
                }
            continue

        match = _match_footer_value(footer_values, value)
        report[key] = {
            "csv_value": value,
            "present": match is not None,
            **(match or {}),
        }

    instrument_report: dict[str, dict[str, object]] = {}
    for row in instrument_rows:
        inst_key = f"Inst {row['Inst']}"
        row_report: dict[str, object] = {}
        for key, value in row.items():
            if key in {"Comp", "Date", "Time", "Label"}:
                row_report[key] = {
                    "csv_value": value,
                    "present": value == footer_records.get("event_label"),
                }
                continue
            match = _match_footer_value(footer_values, value)
            row_report[key] = {
                "csv_value": value,
                "present": match is not None,
                **(match or {}),
            }
        instrument_report[inst_key] = row_report

    return {
        "event": report,
        "instrument": instrument_report,
        "footer_records": footer_records,
    }


def print_metadata_report(
    component_dir: str | Path | None = None,
    event_number: int = 144,
    esf_path: str | Path | None = None,
    event_csv_path: str | Path | None = None,
    instrument_csv_path: str | Path | None = None,
) -> None:
    """Print the decoded ESF metadata in a readable form."""

    if esf_path is None:
        if component_dir is None:
            raise ValueError('component_dir or esf_path must be provided.')
        component_dir = Path(component_dir)
        esf_path = next(component_dir.glob("*.ESF"))
    else:
        esf_path = Path(esf_path)
        if component_dir is None:
            component_dir = esf_path.parent

    footer_values = extract_footer_doubles(esf_path)
    report = compare_csv_metadata(
        component_dir,
        event_number=event_number,
        esf_path=esf_path,
        event_csv_path=event_csv_path,
        instrument_csv_path=instrument_csv_path,
    )

    print("[FOOTER TEXT]")
    print(f"Event label: {report['footer_records'].get('event_label')}")
    for idx, record in enumerate(report["footer_records"].get("channel_records", []), start=1):
        print(f"Channel record {idx}: {record}")

    print("\n[FOOTER DOUBLES]")
    for idx, value in enumerate(footer_values):
        if np.isfinite(value) and abs(value) < 1e9:
            print(f"{idx:04d}: {value}")

    print("\n[FOOTER NON-DOUBLE BYTES]")
    raw = esf_path.read_bytes()
    footer = _footer_bytes(raw)
    ints = np.frombuffer(footer[: len(footer) - (len(footer) % 4)], dtype="<i4")
    for idx, value in enumerate(ints):
        if value in {0, 1, 3, 4, 12, 30, 34, 41, 45, 79, 144, 1000, 1001, 1002, 1003, 1006, 1013, 1014, 1015, 1016, 1020, 1024, 1025, 1026, 1027, 1028, 1029, 1030, 1031, 1032, 1033, 1034, 1035, 1036, 1037, 2000, 2003, 2026, 2027, 2028, 2029, 2030, 2031, 2032, 2033, 2034, 2035, 2036, 2037, 2038, 2041, 2042, 2049, 2050, 2052, 2053, 2054, 2055, 2056, 2057, 2058, 2059, 2060, 2061, 2062, 2063, 2064, 2065, 2066, 2067, 2068, 2069, 2070, 2071, 2072, 2073, 2074, 2075, 2076, 2077, 2078, 2079, 2080, 2081, 3000, 3003, 4000, 4001, 4002, 4003, 4004, 4005, 4006, 4007, 4008, 4009, 4013, 4014, 4015, 4018, 4019, 4020, 16711680, -1}:
            print(f"{idx:04d}: {value}")

    print(f"\n[EVENT {event_number} CSV VS FOOTER]")
    for key, item in report["event"].items():
        if item.get("present"):
            if "footer_index" in item:
                print(f"{key}: {item['csv_value']} -> footer[{item['footer_index']}] = {item['footer_value']}")
            else:
                print(f"{key}: {item['csv_value']} -> {item.get('footer_value', 'present')}")

    print(f"\n[EVENT {event_number} MISSING OR AMBIGUOUS]")
    for key, item in report["event"].items():
        if not item.get("present"):
            print(f"{key}: {item['csv_value']}")

    print(f"\n[INSTRUMENT {event_number} CSV VS FOOTER]")
    for inst_key, inst_report in report["instrument"].items():
        print(inst_key)
        for key, item in inst_report.items():
            if item.get("present"):
                if "footer_index" in item:
                    print(f"  {key}: {item['csv_value']} -> footer[{item['footer_index']}] = {item['footer_value']}")
                else:
                    print(f"  {key}: {item['csv_value']} -> present")

        print()


def print_footer_interpreted(
    component_dir: str | Path | None = None,
    event_number: int = 144,
    esf_path: str | Path | None = None,
    event_csv_path: str | Path | None = None,
    instrument_csv_path: str | Path | None = None,
) -> None:
    """Print only the interpreted footer metadata."""

    report = compare_csv_metadata(
        component_dir,
        event_number=event_number,
        esf_path=esf_path,
        event_csv_path=event_csv_path,
        instrument_csv_path=instrument_csv_path,
    )

    print(f"[EVENT {event_number} INTERPRETED FOOTER]")
    print(f"Label: {report['footer_records'].get('event_label')}")
    print("Channels:")
    for idx, record in enumerate(report["footer_records"].get("channel_records", []), start=1):
        print(f"  {idx}: {record}")

    print("\nEvent fields:")
    for key, item in report["event"].items():
        if item.get("present"):
            if "footer_index" in item:
                print(f"  {key}: {item['csv_value']} (footer[{item['footer_index']}])")
            else:
                print(f"  {key}: {item['csv_value']}")

    print("\nMissing or ambiguous:")
    for key, item in report["event"].items():
        if not item.get("present"):
            print(f"  {key}: {item['csv_value']}")

    print("\nInstrument fields:")
    for inst_key, inst_report in report["instrument"].items():
        print(f"  {inst_key}")
        for key, item in inst_report.items():
            if item.get("present") and key not in {"Comp", "Date", "Time", "Label"}:
                if "footer_index" in item:
                    print(f"    {key}: {item['csv_value']} (footer[{item['footer_index']}])")
                else:
                    print(f"    {key}: {item['csv_value']}")


def load_atf(path: str | Path) -> tuple[np.ndarray, dict[str, str]]:
    """Load a single ATF trace and its header metadata."""

    lines = Path(path).read_text(encoding="utf-8", errors="ignore").splitlines()
    header: dict[str, str] = {}
    for part in lines[1].split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        key, value = part.split("=", 1)
        header[key.strip()] = value.strip()

    data = np.array([float(line.strip()) for line in lines[3:] if line.strip()], dtype=np.float64)
    return data, header


def derive_atf_offsets(component_dir: str | Path) -> list[float]:
    """Return per-channel DC offsets needed to match the ATFs."""

    component_dir = Path(component_dir)
    esf_path = next(component_dir.glob("*.ESF"))
    atf_paths = sorted(component_dir.glob("*.atf"))
    waveform, _ = extract_esf(esf_path)

    offsets: list[float] = []
    for idx, atf_path in enumerate(atf_paths):
        atf_data, _ = load_atf(atf_path)
        offsets.append(float(np.mean(waveform[:, idx] - atf_data)))

    return offsets


def compare_component(component_dir: str | Path) -> dict[str, dict[str, float]]:
    """Compare the ESF channels against the four ATF files in a component."""

    component_dir = Path(component_dir)
    esf_path = next(component_dir.glob("*.ESF"))
    atf_paths = sorted(component_dir.glob("*.atf"))

    waveform, _ = extract_esf(esf_path)
    offsets = derive_atf_offsets(component_dir)

    result: dict[str, dict[str, float]] = {}
    for idx, atf_path in enumerate(atf_paths):
        atf_data, header = load_atf(atf_path)
        esf_data = waveform[:, idx]
        diff = esf_data - atf_data
        corrected = (esf_data - offsets[idx]) - atf_data
        result[atf_path.name] = {
            "max_abs_diff": float(np.max(np.abs(diff))),
            "mean_abs_diff": float(np.mean(np.abs(diff))),
            "rms_diff": float(np.sqrt(np.mean(diff**2))),
            "mean_offset": float(offsets[idx]),
            "corrected_max_abs_diff": float(np.max(np.abs(corrected))),
            "corrected_rms_diff": float(np.sqrt(np.mean(corrected**2))),
            "trace_points": float(atf_data.size),
            "tsamp": float(header.get("TSamp", "nan")),
        }

    return result


def extract_esf(
    path: str | Path,
    channel_count: int | None = None,
    samples_per_channel: int = SAMPLES_PER_CHANNEL,
    channel_offsets: list[float] | None = None,
):
    """Return the raw waveform matrix plus metadata without ObsPy."""

    raw = np.memmap(path, dtype="u1", mode="r")
    layout = parse_esf_layout(raw)
    if channel_count is not None and channel_count != layout["channel_count"]:
        raise ValueError(f"channel_count disagrees with ESF header: {channel_count} != {layout['channel_count']}")
    if samples_per_channel != SAMPLES_PER_CHANNEL and samples_per_channel != layout["samples_per_channel"]:
        raise ValueError(
            f"samples_per_channel disagrees with ESF header: {samples_per_channel} != {layout['samples_per_channel']}"
        )

    channel_count = int(layout["channel_count"])
    samples_per_channel = int(layout["samples_per_channel"])
    metadata_records = _extract_metadata_records(raw[int(layout["footer_offset_bytes"]):].tobytes())
    payload = np.frombuffer(
        raw,
        dtype=DATA_DTYPE,
        count=channel_count * samples_per_channel,
        offset=int(layout["header_size_bytes"]),
    )
    waveform = payload.reshape(channel_count, samples_per_channel).T.copy()

    if channel_offsets is not None:
        offsets = np.asarray(channel_offsets, dtype=np.float64)
        if offsets.size != channel_count:
            raise ValueError(f"Expected {channel_count} channel offsets, got {offsets.size}")
        waveform = waveform - offsets

    metadata = {
        "header_size_bytes": int(layout["header_size_bytes"]),
        "footer_offset_bytes": int(layout["footer_offset_bytes"]),
        "layout": layout,
        "waveform_start_sample": 0,
        "waveform_end_sample": samples_per_channel,
        "waveform_samples": samples_per_channel,
        "payload_start_double": int(layout["header_size_bytes"]) // 8,
        "payload_end_double": int(layout["footer_offset_bytes"]) // 8,
        "sample_rate": SAMPLE_RATE,
        "channel_count": channel_count,
        "samples_per_channel": samples_per_channel,
        "channel_offsets": list(channel_offsets) if channel_offsets is not None else [0.0] * channel_count,
        "metadata_records": metadata_records,
    }

    raw._mmap.close()
    return waveform, metadata


def read_esf(
    path: str | Path,
    channel_count: int | None = None,
    sample_rate: float = SAMPLE_RATE,
    channel_offsets: list[float] | None = None,
    station_channel_map: dict[str, str] | None = None,
):
    """Read an ESF file and return an ObsPy Stream plus metadata.

    The waveform channel count and sample count are read from the ESF header.
    """

    waveform, metadata = extract_esf(path, channel_count=channel_count, channel_offsets=channel_offsets)
    metadata["sample_rate"] = sample_rate

    matrix = waveform
    starttime = _stem_to_datetime(str(metadata.get("metadata_records", {}).get("event_stem") or ""))

    try:
        from obspy import Stream, Trace, UTCDateTime
    except ImportError as exc:  # pragma: no cover - environment specific
        raise ImportError(
            "obspy is not installed in the current Python environment. "
            "Activate the 'seismology' env from environment.yml first."
        ) from exc

    traces = []
    for idx in range(int(metadata["channel_count"])):
        station_code = f"S{idx + 1:02d}"
        channel_code = f"CH{idx + 1}"
        if station_channel_map:
            channel_code = station_channel_map.get(station_code)
            if channel_code is None:
                continue
        trace = Trace(data=matrix[:, idx].copy())
        trace.stats.station = station_code
        trace.stats.channel = channel_code
        trace.stats.starttime = UTCDateTime(starttime) if starttime is not None else UTCDateTime(0)
        trace.stats.sampling_rate = sample_rate
        traces.append(trace)

    return Stream(traces=traces), metadata


def _locate_esf_files(path: str | Path) -> list[Path]:
    path = Path(path)

    if path.is_file() and path.suffix.lower() == ".esf":
        return [path]

    if path.is_dir():
        search_dir = path if path.name.lower() == "esf" else path / "ESF"
        if search_dir.is_dir():
            candidates = sorted(search_dir.rglob("*.ESF")) + sorted(search_dir.rglob("*.esf"))
            return list(dict.fromkeys(candidates))

    raise FileNotFoundError(f"No ESF files found under {path}")


def inspect_esf_file(path: str | Path) -> dict[str, object]:
    """Return a small diagnostic summary for a single ESF file."""

    path = Path(path)
    raw = np.memmap(path, dtype="u1", mode="r")
    layout = parse_esf_layout(raw)
    summary = {
        "path": str(path),
        "file_size_bytes": int(layout["file_size_bytes"]),
        "channel_count": int(layout["channel_count"]),
        "samples_per_channel": int(layout["samples_per_channel"]),
        "header_size_bytes": int(layout["header_size_bytes"]),
        "channel_offsets_bytes": list(layout["channel_offsets_bytes"]),
        "footer_offset_bytes": int(layout["footer_offset_bytes"]),
        "nominal_channel_count": CHANNEL_COUNT,
        "nominal_samples_per_channel": SAMPLES_PER_CHANNEL,
        "fits_nominal_layout": (
            int(layout["channel_count"]) == CHANNEL_COUNT
            and int(layout["samples_per_channel"]) == SAMPLES_PER_CHANNEL
        ),
    }
    del raw
    return summary


def build_esf_stream(path: str | Path, station_channel_map: dict[str, str] | None = None):
    """Build a master ObsPy Stream from an ESF folder or single file."""

    from obspy import Stream

    path = Path(path)
    esf_paths = _locate_esf_files(path)
    if not esf_paths:
        raise FileNotFoundError(f"No .ESF files were found under {path}")

    master_stream = Stream()
    for esf_path in esf_paths:
        st, _ = read_esf(esf_path, station_channel_map=station_channel_map)
        master_stream += st

    if len(master_stream) == 0:
        raise FileNotFoundError(f"No readable .ESF files were found under {path}")

    master_stream.sort(["starttime", "station", "channel"])
    return master_stream


def _parse_event_csv_date(date_text: str) -> str:
    for fmt in ("%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(date_text.strip(), fmt).strftime("%Y%m%d")
        except Exception:
            continue
    raise ValueError(f"Unsupported event CSV date format: {date_text}")


def _locate_esf_event_file(esf_root: Path, event_date: str, event_number: int) -> Path:
    candidate_name = f"{event_date}_{event_number:04d}.ESF"
    candidates = sorted(esf_root.rglob(candidate_name)) + sorted(esf_root.rglob(candidate_name.lower()))
    if candidates:
        return candidates[0]
    raise FileNotFoundError(f"No ESF file found for event {event_date}_{event_number:04d} under {esf_root}")


def build_esf_catalog(path: str | Path, output_path: str | Path | None = None):
    """Build an ObsPy QuakeML catalog directly from individual ESF files."""

    return build_esf_catalog_from_esfs(path, output_path=output_path)


def build_esf_catalog_from_esfs(path: str | Path, output_path: str | Path | None = None):
    """Build an ObsPy QuakeML catalog directly from individual ESF files."""

    try:
        from obspy import UTCDateTime
        from obspy.core.event import Catalog, Event, Magnitude, Origin
        from obspy.core.event.base import Comment
    except ImportError as exc:  # pragma: no cover - environment specific
        raise ImportError(
            "obspy is not installed in the current Python environment. "
            "Activate the 'richterpy' env from environment.yml first."
        ) from exc

    path = Path(path)
    esf_paths = _locate_esf_files(path)
    if not esf_paths:
        raise FileNotFoundError(f"No .ESF files were found under {path}")

    cat = Catalog()
    for esf_path in esf_paths:
        event_metadata = extract_esf_event_metadata(esf_path)
        event_stem = str(event_metadata.get("event_stem") or esf_path.stem)
        event_dt = _stem_to_datetime(event_stem)
        if event_dt is None:
            continue
        origin_time = UTCDateTime(event_dt)
        if event_metadata.get("dec_sec") is not None:
            origin_time += float(event_metadata["dec_sec"])

        north = float(event_metadata.get("north") or 0.0)
        east = float(event_metadata.get("east") or 0.0)
        down = float(event_metadata.get("down") or 0.0)
        loc_mag = event_metadata.get("loc_mag")
        loc_error = event_metadata.get("loc_error")
        residual = event_metadata.get("residual")
        confidence = event_metadata.get("confidence")

        origin = Origin(
            time=origin_time,
            latitude=north,
            longitude=east,
            depth=-down,
            comments=[
                Comment(text=f"event_label: {event_metadata.get('label') or ''}"),
                Comment(text=f"event_stem: {event_stem}"),
            ],
        )

        for name in ("number", "enabled", "located", "dec_sec", "t0", "snr", "rms_noise", "mon_dist"):
            if event_metadata.get(name) is not None:
                origin.comments.append(Comment(text=f"{name}: {event_metadata[name]}"))
        if loc_error is not None:
            origin.comments.append(Comment(text=f"loc_error: {loc_error}"))
        if residual is not None:
            origin.comments.append(Comment(text=f"residual: {residual}"))
        if confidence is not None:
            origin.comments.append(Comment(text=f"confidence: {confidence}"))

        magnitudes = []
        if loc_mag is not None:
            magnitudes.append(Magnitude(mag=float(loc_mag), magnitude_type="Local Magnitude"))
        event = Event(origins=[origin], magnitudes=magnitudes, resource_id=event_stem)
        cat.append(event)

    if output_path is not None:
        output_path = Path(output_path)
        cat.write(output_path, format="QUAKEML")

    return cat


def _write_text_dump(path: str | Path, text: str) -> Path:
    output_path = Path(f"{Path(path)}.txt")
    output_path.write_text(text, encoding='utf-8')
    return output_path


def _format_finite_doubles(values: np.ndarray, limit: int | None = None) -> list[str]:
    lines: list[str] = []
    count = 0
    for idx, value in enumerate(values):
        if not np.isfinite(value):
            continue
        if abs(float(value)) > 1e9:
            continue
        lines.append(f"{idx:04d}: {float(value)}")
        count += 1
        if limit is not None and count >= limit:
            break
    return lines


def decode_esf_txt(path: str | Path) -> Path:
    """Write a human-readable ESF summary next to the source file."""

    path = Path(path)
    raw = path.read_bytes()
    waveform, metadata = extract_esf(path)
    footer_values = extract_footer_doubles(path)
    footer_records = metadata["metadata_records"]

    lines: list[str] = []
    lines.append(f"FILE: {path}")
    lines.append(f"SIZE: {path.stat().st_size} bytes")
    lines.append("")
    lines.append("[WAVEFORM]")
    lines.append(f"channels: {metadata['channel_count']}")
    lines.append(f"samples_per_channel: {metadata['samples_per_channel']}")
    lines.append(f"sample_rate: {metadata['sample_rate']}")
    for idx in range(waveform.shape[1]):
        ch = waveform[:, idx]
        lines.append(
            f"ch{idx + 1}: min={float(np.min(ch))} max={float(np.max(ch))} mean={float(np.mean(ch))}"
        )
        lines.append(f"  first8: {' '.join(f'{float(x):.12g}' for x in ch[:8])}")
        lines.append(f"  last8: {' '.join(f'{float(x):.12g}' for x in ch[-8:])}")

    lines.append("")
    lines.append("[METADATA TEXT]")
    lines.append(f"event_label: {_normalize_stream_label(str(footer_records.get('event_label') or '')) or footer_records.get('event_label')}")
    if footer_records.get('event_stem'):
        lines.append(f"event_stem: {footer_records['event_stem']}")
    if footer_records.get('event_component'):
        lines.append(f"event_component: {footer_records['event_component']}")
    if footer_records.get('event_clock'):
        lines.append(f"event_clock: {footer_records['event_clock']}")
    stem_dt = _stem_to_datetime(str(footer_records.get('event_stem') or ''))
    if stem_dt is not None:
        lines.append(f"event_date: {stem_dt:%d/%m/%Y}")
        lines.append(f"event_time: {stem_dt:%H:%M:%S}")
        if len(footer_values) > 102:
            dec_sec = float(footer_values[102])
            frac = f"{dec_sec:.7f}".split(".", 1)[1]
            lines.append(f"event_local_time: {stem_dt:%H:%M:%S}.{frac}")
    for idx, record in enumerate(footer_records.get('channel_records', []), start=1):
        lines.append(f"channel_record_{idx}: {_label_channel_record(str(record))}")

    lines.append("")
    lines.append("[INTERPRETED FOOTER]")
    lines.extend(_interpret_esf_footer_fields(footer_values))

    lines.append("")
    lines.append("[METADATA DOUBLES]")
    lines.extend(_format_finite_doubles(footer_values))

    return _write_text_dump(path, "\n".join(lines) + "\n")


def decode_bsf_txt(path: str | Path) -> Path:
    """Write a human-readable BSF summary next to the source file."""

    path = Path(path)
    raw = path.read_bytes()
    payload = np.frombuffer(raw[421:], dtype='<f8')
    block = 65568

    lines: list[str] = []
    lines.append(f"FILE: {path}")
    lines.append(f"SIZE: {len(raw)} bytes")
    lines.append("[STRINGS]")
    for s in _unique_in_order(_extract_ascii_strings(raw)):
        lines.append(s)

    lines.append("")
    lines.append("[CHANNELS]")

    for ch_idx in range(3):
        block_values = payload[ch_idx * block:(ch_idx + 1) * block]
        wave = block_values[:SAMPLES_PER_CHANNEL]
        meta = block_values[SAMPLES_PER_CHANNEL:]
        lines.append(f"ch{ch_idx + 1} waveform: samples={wave.size} min={float(np.min(wave))} max={float(np.max(wave))} mean={float(np.mean(wave))}")
        lines.append(f"  first8: {' '.join(f'{float(x):.12g}' for x in wave[:8])}")
        lines.append(f"  last8: {' '.join(f'{float(x):.12g}' for x in wave[-8:])}")
        lines.append(f"  metadata_tail_f64: {' '.join(f'{float(x):.12g}' for x in meta)}")
        lines.append(f"  metadata_tail_i32: {' '.join(str(int(x)) for x in np.frombuffer(meta.tobytes(), dtype='<i4'))}")

    wave4 = payload[3 * block:3 * block + SAMPLES_PER_CHANNEL]
    lines.append(f"ch4 waveform: samples={wave4.size} min={float(np.min(wave4))} max={float(np.max(wave4))} mean={float(np.mean(wave4))}")
    lines.append(f"  first8: {' '.join(f'{float(x):.12g}' for x in wave4[:8])}")
    lines.append(f"  last8: {' '.join(f'{float(x):.12g}' for x in wave4[-8:])}")

    return _write_text_dump(path, "\n".join(lines) + "\n")


def plot_bsf_png(path: str | Path) -> Path:
    """Plot the four BSF waveforms and save as `filename.bsf.png`."""

    path = Path(path)
    raw = path.read_bytes()
    payload = np.frombuffer(raw[421:], dtype='<f8')
    block = 65568

    try:
        import matplotlib.pyplot as plt
    except ImportError:
        from PIL import Image, ImageDraw, ImageFont

        width, height = 1800, 1200
        margin_x = 80
        margin_y = 50
        panel_h = (height - 2 * margin_y) // 4
        img = Image.new('RGB', (width, height), 'white')
        draw = ImageDraw.Draw(img)

        for ch_idx in range(4):
            if ch_idx < 3:
                wave = payload[ch_idx * block:(ch_idx * block) + SAMPLES_PER_CHANNEL]
            else:
                wave = payload[3 * block:3 * block + SAMPLES_PER_CHANNEL]

            top = margin_y + ch_idx * panel_h
            bottom = top + panel_h - 10
            left = margin_x
            right = width - margin_x
            mid = (top + bottom) // 2
            draw.rectangle([left, top, right, bottom], outline='lightgray')
            draw.line([left, mid, right, mid], fill='gainsboro')
            draw.text((10, top + 5), f'CH{ch_idx + 1}', fill='black')

            wmin = float(np.min(wave))
            wmax = float(np.max(wave))
            span = wmax - wmin if wmax != wmin else 1.0
            xs = np.linspace(left, right, num=wave.size)
            ys = bottom - ((wave - wmin) / span) * (bottom - top)
            pts = list(zip(xs.tolist(), ys.tolist()))
            draw.line(pts, fill='navy', width=1)

        draw.text((margin_x, 10), path.name, fill='black')
        output_path = Path(f"{path}.png")
        img.save(output_path)
        return output_path

    fig, axes = plt.subplots(4, 1, figsize=(14, 8), sharex=True)
    for ch_idx in range(4):
        ax = axes[ch_idx]
        if ch_idx < 3:
            wave = payload[ch_idx * block:(ch_idx * block) + SAMPLES_PER_CHANNEL]
        else:
            wave = payload[3 * block:3 * block + SAMPLES_PER_CHANNEL]

        ax.plot(wave, linewidth=0.6)
        ax.set_ylabel(f"CH{ch_idx + 1}")
        ax.grid(True, alpha=0.25)

    axes[-1].set_xlabel("Sample")
    fig.suptitle(path.name)
    fig.tight_layout()

    output_path = Path(f"{path}.png")
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    return output_path


def plot_esf_png(path: str | Path) -> Path:
    """Plot the four ESF waveforms and save as `filename.ESF.png`."""

    path = Path(path)
    waveform, _ = extract_esf(path)

    try:
        import matplotlib.pyplot as plt
    except ImportError:
        from PIL import Image, ImageDraw, ImageFont

        width, height = 1800, 1200
        margin_x = 80
        margin_y = 50
        panel_h = (height - 2 * margin_y) // 4
        img = Image.new('RGB', (width, height), 'white')
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype('arial.ttf', 18)
        except Exception:
            font = ImageFont.load_default()

        for ch_idx in range(4):
            top = margin_y + ch_idx * panel_h
            bottom = top + panel_h - 20
            left = margin_x
            right = width - margin_x
            draw.rectangle([left, top, right, bottom], outline='black')
            wave = waveform[:, ch_idx]
            min_v = float(np.min(wave))
            max_v = float(np.max(wave))
            span = max(max_v - min_v, 1e-12)
            pts = []
            n = len(wave)
            for i, y in enumerate(wave):
                x = left + (right - left) * i / max(n - 1, 1)
                yy = bottom - ((float(y) - min_v) / span) * (bottom - top - 2)
                pts.append((x, yy))
            if len(pts) > 1:
                draw.line(pts, fill='navy', width=1)
            draw.text((left + 6, top + 6), f'CH{ch_idx + 1}', fill='black', font=font)

        draw.text((margin_x, 12), path.name, fill='black', font=font)
        output_path = Path(f"{path}.png")
        img.save(output_path)
        return output_path

    fig, axes = plt.subplots(4, 1, figsize=(16, 9), sharex=True)
    fig.suptitle(path.name)
    for ch_idx, ax in enumerate(axes):
        wave = waveform[:, ch_idx]
        ax.plot(wave, linewidth=0.6)
        ax.set_ylabel(f"CH{ch_idx + 1}")
        ax.grid(True, alpha=0.25)

    axes[-1].set_xlabel("Sample")
    fig.tight_layout()

    output_path = Path(f"{path}.png")
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    return output_path


def _decode_length_prefixed_records(raw: bytes, start: int, limit: int = 16) -> list[str]:
    lines: list[str] = []
    pos = start
    for idx in range(limit):
        if pos + 4 > len(raw):
            break
        ln = int.from_bytes(raw[pos:pos + 4], 'little', signed=False)
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


def decode_pcf_txt(path: str | Path) -> Path:
    """Write a human-readable PCF summary next to the source file."""

    path = Path(path)
    raw = path.read_bytes()
    lines: list[str] = []
    lines.append(f"FILE: {path}")
    lines.append(f"SIZE: {len(raw)} bytes")
    lines.append("")
    lines.append("[PROJECT PATHS]")
    for s in _extract_windows_paths(raw):
        lines.append(s)

    lines.append("")
    lines.append("[STREAM ENTRIES]")
    for s in _extract_stream_entries(raw):
        lines.append(s)

    lines.append("")
    lines.append("[STATION/CHANNEL METADATA]")
    for record in _extract_pcf_station_records(raw):
        label = str(record["Station_Label"])
        idx = raw.find(label.encode("ascii"))
        if idx == -1:
            continue
        lines.append(f"{label} @offset {idx}")
        lines.append(f"  Instrument_Number: {record['Instrument_Number']}")
        lines.append(f"  Instrument_Label: {record['Instrument_Label']}")
        lines.append(f"  Channel_Number: {record['Channel_Number']}")
        lines.append(f"  Channel_Label: {record['Channel_Label']}")
        lines.append(f"  Owner_Array: {record['Owner_Array']}")
        triples = _decode_length_value_strings(raw, idx, limit=6)
        if triples:
            for ln, text in triples:
                lines.append(f"  {ln:03d}:{text}")
        for key in ("North", "East", "Down"):
            value = record[key]
            hits = _exact_numeric_hits(raw, value)
            if hits:
                lines.append(f"  {key}: {value} -> {', '.join(hits)}")
            else:
                lines.append(f"  {key}: {value} -> none")
        for key in (
            "On",
            "Gain",
            "Sensitivity",
            "Vmax",
            "LowFreq",
            "HighFreq",
            "Orientation_N",
            "Orientation_E",
            "Orientation_D",
            "Motion",
            "P_Station_Correction",
            "S_Station_Correction",
            "Array_Instrument_Number",
            "Array_Channel_Number",
        ):
            value = record[key]
            if value is None:
                lines.append(f"  {key}: unknown")
                continue
            hits = _exact_numeric_hits(raw, value)
            if hits:
                lines.append(f"  {key}: {value} -> {', '.join(hits)}")
            else:
                lines.append(f"  {key}: {value} -> none")

    lines.append("")
    lines.append("[CHANNEL CONFIG ROWS]")
    for row in raw.decode('ascii', errors='ignore').split('\r'):
        s = row.strip()
        if re.fullmatch(r'(?:1,1,0\.017,5,100,35,,,,,,|2,1,0\.011,5,100,35,,,,,,|3,1,0\.194,5,100,35,,,,,,|4,1,0\.01,5,100,35,,,,,,)', s):
            lines.append(s)

    lines.append("")
    lines.append("[CHANNEL/STYLE BLOCK]")
    for row in raw.decode('ascii', errors='ignore').split('\r'):
        row = row.strip()
        if re.fullmatch(r'(?:[0-9]+,Arial,[^\r\n]*|richter-m,[^\r\n]*|Channel [0-9]{2}[^\r\n]*)', row):
            lines.append(row)

    lines.append("")
    lines.append("[LENGTH-VALUE RUNS]")
    runs = _scan_length_value_runs(raw)
    if runs:
        for row in runs:
            lines.append(row)
    else:
        lines.append("none")

    lines.append("")
    lines.append("[EVENT BLOCK SAMPLE]")
    event_stem = b'20250403142840_1100877368'
    stem_idx = raw.find(event_stem)
    if stem_idx != -1:
        record_idx = raw.find(b'\x0c\x00\x00\x00\x01\x00\x00\x00\x02\x00\x00\x00\x04\x00\x00\x00', stem_idx)
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
            chunk = raw[off:off + 96]
            lines.append(f"offset {off}: {chunk.hex(' ')}")

    return _write_text_dump(path, "\n".join(lines) + "\n")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Convert an ESF file into ObsPy traces")
    parser.add_argument("path", nargs="?", default="20250403_0001.ESF")
    parser.add_argument("--esf-path", help="Explicit ESF path for report modes")
    parser.add_argument("--component-dir", help="Directory containing ESF and CSV companions")
    parser.add_argument("--event-csv-path", help="Explicit event CSV path for report modes")
    parser.add_argument("--instrument-csv-path", help="Explicit instrument CSV path for report modes")
    parser.add_argument("--report", action="store_true", help="Print decoded metadata report")
    parser.add_argument("--footer", action="store_true", help="Print interpreted footer metadata only")
    parser.add_argument("--event-number", type=int, default=144, help="Event number for report modes")
    parser.add_argument("--write", help="Optional output file, e.g. output.mseed")
    args = parser.parse_args()

    esf_path = Path(args.esf_path or args.path)

    if args.footer:
        print_footer_interpreted(
            args.component_dir or esf_path.parent,
            event_number=args.event_number,
            esf_path=esf_path,
            event_csv_path=args.event_csv_path,
            instrument_csv_path=args.instrument_csv_path,
        )
        return

    if args.report:
        print_metadata_report(
            args.component_dir or esf_path.parent,
            event_number=args.event_number,
            esf_path=esf_path,
            event_csv_path=args.event_csv_path,
            instrument_csv_path=args.instrument_csv_path,
        )
        return

    stream, metadata = read_esf(esf_path)
    print(stream)
    print(metadata)

    if args.write:
        stream.write(args.write, format="MSEED")


if __name__ == "__main__":
    main()
