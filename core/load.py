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


def annual_energy_kwh(df: pd.DataFrame) -> float:
    dt_hours = infer_time_step_hours(df)
    return float(df["load_kw"].sum()) * dt_hours


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

    Uses a stepwise hold for finer timesteps so the load stays piecewise
    constant between source samples. For coarser timesteps, uses the mean
    load over each output interval.

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
    source_time_step_minutes = infer_time_step_hours(
        df.reset_index()[["timestamp", "load_kw"]]
    ) * 60.0

    if abs(source_time_step_minutes - float(time_step_minutes)) <= 1e-9:
        return df.reset_index()[["timestamp", "load_kw"]].reset_index(drop=True)

    new_index = pd.date_range(
        start=df.index[0],
        end=df.index[-1],
        freq=f"{time_step_minutes}min",
    )

    if time_step_minutes < source_time_step_minutes:
        # Repeat the last known load value within each source interval.
        resampled = df.reindex(df.index.union(new_index)).sort_index()
        resampled["load_kw"] = pd.to_numeric(resampled["load_kw"], errors="coerce").ffill()
        resampled = resampled.reindex(new_index)
    else:
        # Aggregate finer data into coarser intervals using mean power.
        resampled = df.resample(f"{time_step_minutes}min").mean().reindex(new_index)

    resampled = resampled.clip(lower=0.0)
    resampled = resampled.reset_index().rename(columns={"index": "timestamp"})
    return resampled[["timestamp", "load_kw"]].reset_index(drop=True)


def scale_load_to_annual_energy(
    df: pd.DataFrame,
    target_annual_energy_kwh: float,
) -> pd.DataFrame:
    if target_annual_energy_kwh <= 0:
        raise ValueError("target_annual_energy_kwh must be > 0")

    current_annual_energy_kwh = annual_energy_kwh(df)
    if current_annual_energy_kwh <= 0:
        raise ValueError("Cannot scale a load profile with zero annual energy")

    scale_factor = float(target_annual_energy_kwh) / current_annual_energy_kwh
    out = df.copy()
    out["load_kw"] = pd.to_numeric(out["load_kw"], errors="coerce") * scale_factor
    return out


def summarize_load(df: pd.DataFrame) -> LoadSummary:
    dt_hours = infer_time_step_hours(df)
    return LoadSummary(
        rows=int(len(df)),
        annual_energy_kwh=float(df["load_kw"].sum()) * dt_hours,
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


def create_weekday_weekend_monthly_load(
    weekday_hourly_profile_kw: list[float],
    weekend_hourly_profile_kw: list[float],
    monthly_multipliers: list[float],
    year: int = 2025,
) -> pd.DataFrame:
    if len(weekday_hourly_profile_kw) != 24:
        raise ValueError("weekday_hourly_profile_kw must contain exactly 24 values")

    if len(weekend_hourly_profile_kw) != 24:
        raise ValueError("weekend_hourly_profile_kw must contain exactly 24 values")

    if len(monthly_multipliers) != 12:
        raise ValueError("monthly_multipliers must contain exactly 12 values")

    weekday_vals = [float(v) for v in weekday_hourly_profile_kw]
    weekend_vals = [float(v) for v in weekend_hourly_profile_kw]
    month_vals = [float(v) for v in monthly_multipliers]

    if any(v < 0 for v in weekday_vals):
        raise ValueError("Weekday profile values cannot be negative")

    if any(v < 0 for v in weekend_vals):
        raise ValueError("Weekend profile values cannot be negative")

    if any(v < 0 for v in month_vals):
        raise ValueError("Monthly multipliers cannot be negative")

    start = pd.Timestamp(f"{year}-01-01 00:00:00")
    end = pd.Timestamp(f"{year + 1}-01-01 00:00:00")
    ts = pd.date_range(start=start, end=end, freq="h", inclusive="left")

    loads: list[float] = []
    for timestamp in ts:
        is_weekend = timestamp.weekday() >= 5
        base_profile = weekend_vals if is_weekend else weekday_vals
        month_multiplier = month_vals[int(timestamp.month) - 1]
        loads.append(base_profile[int(timestamp.hour)] * month_multiplier)

    df = pd.DataFrame({
        "timestamp": ts,
        "load_kw": loads,
    })
    return validate_hourly_load(df, expect_rows=len(ts))


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
