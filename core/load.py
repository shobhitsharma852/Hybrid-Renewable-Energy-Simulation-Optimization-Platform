from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO
import io

import pandas as pd


@dataclass(frozen=True)
class LoadSummary:
    rows: int
    annual_energy_kwh: float
    peak_kw: float
    average_kw: float
    min_kw: float


def project_inputs_dir(project_folder: str | Path) -> Path:
    path = Path(project_folder) / "inputs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_file_path(project_folder: str | Path) -> Path:
    return project_inputs_dir(project_folder) / "load.csv"


def _rename_load_columns(df: pd.DataFrame) -> pd.DataFrame:
    col_map: dict[str, str] = {}

    for c in df.columns:
        lc = str(c).strip().lower()

        if lc in {"timestamp", "time", "datetime", "date_time", "date-time"}:
            col_map[c] = "timestamp"
        elif lc in {"load", "load_kw", "demand", "demand_kw", "power", "kw"}:
            col_map[c] = "load_kw"

    return df.rename(columns=col_map)


def standardize_load_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(df, pd.DataFrame):
        raise TypeError("Input must be a pandas DataFrame")

    out = _rename_load_columns(df.copy())

    if "timestamp" not in out.columns or "load_kw" not in out.columns:
        raise ValueError(
            "Load data must contain timestamp and load columns "
            "(for example: timestamp, load_kw)"
        )

    out = out[["timestamp", "load_kw"]].copy()

    out["timestamp"] = pd.to_datetime(out["timestamp"], errors="coerce")
    if out["timestamp"].isna().any():
        raise ValueError("Some timestamp values are invalid")

    out["load_kw"] = pd.to_numeric(out["load_kw"], errors="coerce")
    if out["load_kw"].isna().any():
        raise ValueError("Some load values are non-numeric")

    out = out.sort_values("timestamp").reset_index(drop=True)

    if out["timestamp"].duplicated().any():
        raise ValueError("Duplicate timestamps found in load data")

    if (out["load_kw"] < 0).any():
        raise ValueError("Load values cannot be negative")

    return out


def infer_time_step_hours(df: pd.DataFrame) -> float:
    """Detect the uniform timestep in hours from a load or resource dataframe."""
    diffs = df["timestamp"].diff().dropna()
    if diffs.empty:
        return 1.0
    unique = diffs.unique()
    if len(unique) != 1:
        raise ValueError(
            f"Timestamps are not evenly spaced — found multiple intervals: {unique}"
        )
    return unique[0].total_seconds() / 3600.0


def validate_hourly_load(
    df: pd.DataFrame,
    expect_rows: int | None = None,
    time_step_hours: float | None = None,
) -> pd.DataFrame:
    """
    Validate a load dataframe at any timestep resolution.

    Parameters
    ----------
    expect_rows:
        If given, check exact row count. Pass None to skip (default).
    time_step_hours:
        If given, validate that detected interval matches. Pass None to accept any.
    """
    if expect_rows is not None and len(df) != expect_rows:
        raise ValueError(f"Expected {expect_rows} rows, got {len(df)}")

    diffs = df["timestamp"].diff().dropna()
    if diffs.empty:
        return df

    unique = diffs.unique()
    if len(unique) != 1:
        raise ValueError(
            f"Load timestamps are not evenly spaced — found multiple intervals: {unique}"
        )

    if time_step_hours is not None:
        detected = unique[0].total_seconds() / 3600.0
        if abs(detected - float(time_step_hours)) > 1e-6:
            raise ValueError(
                f"Expected {time_step_hours}h interval, detected {detected}h in load data"
            )

    return df


def resample_load_to_timestep(
    df: pd.DataFrame,
    time_step_minutes: int,
) -> pd.DataFrame:
    """
    Resample a load dataframe to any sub-hourly or custom timestep.

    Uses linear interpolation so the load profile is smooth and annual
    energy is preserved.

    Parameters
    ----------
    df:
        Load dataframe with 'timestamp' and 'load_kw' columns.
    time_step_minutes:
        Target resolution in minutes (e.g. 1, 5, 10, 15, 20, 30, 60).
    """
    if time_step_minutes <= 0:
        raise ValueError("time_step_minutes must be > 0")

    df = df.set_index("timestamp").sort_index()
    new_index = pd.date_range(
        start=df.index[0],
        end=df.index[-1],
        freq=f"{time_step_minutes}min",
    )
    resampled = df.reindex(df.index.union(new_index))
    resampled = resampled.interpolate(method="time")
    resampled = resampled.reindex(new_index).clip(lower=0.0)
    resampled = resampled.reset_index().rename(columns={"index": "timestamp"})
    return resampled[["timestamp", "load_kw"]].reset_index(drop=True)


def summarize_load(df: pd.DataFrame) -> LoadSummary:
    return LoadSummary(
        rows=int(len(df)),
        annual_energy_kwh=float(df["load_kw"].sum()),
        peak_kw=float(df["load_kw"].max()),
        average_kw=float(df["load_kw"].mean()),
        min_kw=float(df["load_kw"].min()),
    )


def read_load_file(file_path: str | Path) -> pd.DataFrame:
    file_path = Path(file_path)

    if not file_path.exists():
        raise FileNotFoundError(f"Load file not found: {file_path}")

    suffix = file_path.suffix.lower()
    if suffix == ".csv":
        raw = pd.read_csv(file_path)
    elif suffix in {".xlsx", ".xls"}:
        raw = pd.read_excel(file_path)
    else:
        raise ValueError("Unsupported file type. Use CSV or Excel.")

    out = standardize_load_dataframe(raw)
    out = validate_hourly_load(out)
    return out


def read_uploaded_load(uploaded_file: BinaryIO, filename: str) -> pd.DataFrame:
    suffix = Path(filename).suffix.lower()
    data = uploaded_file.read()

    if suffix == ".csv":
        raw = pd.read_csv(io.BytesIO(data))
    elif suffix in {".xlsx", ".xls"}:
        raw = pd.read_excel(io.BytesIO(data))
    else:
        raise ValueError("Unsupported file type. Use CSV or Excel.")

    out = standardize_load_dataframe(raw)
    out = validate_hourly_load(out)  # accepts any consistent interval
    return out


def create_constant_load(
    constant_kw: float,
    year: int = 2025,
    expect_rows: int = 8760,
) -> pd.DataFrame:
    if constant_kw < 0:
        raise ValueError("constant_kw cannot be negative")

    ts = pd.date_range(f"{year}-01-01 00:00:00", periods=expect_rows, freq="h")
    df = pd.DataFrame({
        "timestamp": ts,
        "load_kw": [float(constant_kw)] * expect_rows,
    })
    return validate_hourly_load(df, expect_rows=expect_rows)


def create_daily_profile_load(
    hourly_profile_kw: list[float],
    year: int = 2025,
    days: int = 365,
) -> pd.DataFrame:
    if len(hourly_profile_kw) != 24:
        raise ValueError("hourly_profile_kw must contain exactly 24 values")

    vals = [float(v) for v in hourly_profile_kw]
    if any(v < 0 for v in vals):
        raise ValueError("Daily profile values cannot be negative")

    expect_rows = 24 * days
    ts = pd.date_range(f"{year}-01-01 00:00:00", periods=expect_rows, freq="h")
    loads = [vals[i % 24] for i in range(expect_rows)]

    df = pd.DataFrame({
        "timestamp": ts,
        "load_kw": loads,
    })
    return validate_hourly_load(df, expect_rows=expect_rows)


def save_load(df: pd.DataFrame, project_folder: str | Path) -> Path:
    path = load_file_path(project_folder)
    df.to_csv(path, index=False)
    return path


def load_saved_load(project_folder: str | Path) -> pd.DataFrame:
    path = load_file_path(project_folder)
    if not path.exists():
        raise FileNotFoundError(f"Saved load file not found in: {project_folder}")

    df = pd.read_csv(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df = standardize_load_dataframe(df)
    return validate_hourly_load(df)