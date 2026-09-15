"""PCF parsing helpers."""

from __future__ import annotations

from pathlib import Path

from richterpy.io.esf import decode_pcf_txt, extract_pcf_station_records


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
        "p_station_correction": "P_Station_Correction",
        "s_station_correction": "S_Station_Correction",
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
