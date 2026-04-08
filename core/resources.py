from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pandas as pd
import requests


NASA_POWER_URL = "https://power.larc.nasa.gov/api/temporal/hourly/point"
NASA_HOURLY_MIN_YEAR = 2001


@dataclass(frozen=True)
class ResourceSummary:
    rows: int
    ghi_mean: float
    ws50m_mean: float
    temperature_mean: float
    start_timestamp: pd.Timestamp
    end_timestamp: pd.Timestamp


def project_inputs_dir(project_folder: str | Path) -> Path:
    path = Path(project_folder) / "inputs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def resources_file_path(project_folder: str | Path) -> Path:
    return project_inputs_dir(project_folder) / "resources.csv"


def validate_resources_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    required = ["timestamp", "ghi", "ws50m", "temperature"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required resource columns: {missing}")

    out = df.copy()

    out["timestamp"] = pd.to_datetime(out["timestamp"], errors="coerce")
    if out["timestamp"].isna().any():
        raise ValueError("Invalid timestamp values found in resources data")

    for col in ["ghi", "ws50m", "temperature"]:
        out[col] = pd.to_numeric(out[col], errors="coerce")

    if out[["ghi", "ws50m", "temperature"]].isna().any().any():
        raise ValueError("Non-numeric or missing values found in resources data")

    if (out["ghi"] < 0).any():
        raise ValueError("GHI cannot be negative")

    if (out["ws50m"] < 0).any():
        raise ValueError("Wind speed cannot be negative")

    out = out.sort_values("timestamp").reset_index(drop=True)

    if out["timestamp"].duplicated().any():
        raise ValueError("Duplicate timestamps found in resources data")

    diffs = out["timestamp"].diff().dropna()
    if not diffs.empty and not (diffs == pd.Timedelta(hours=1)).all():
        raise ValueError("Resources timestamps must be strictly hourly")

    return out


def summarize_resources(df: pd.DataFrame) -> ResourceSummary:
    out = validate_resources_dataframe(df)
    return ResourceSummary(
        rows=len(out),
        ghi_mean=float(out["ghi"].mean()),
        ws50m_mean=float(out["ws50m"].mean()),
        temperature_mean=float(out["temperature"].mean()),
        start_timestamp=pd.Timestamp(out["timestamp"].min()),
        end_timestamp=pd.Timestamp(out["timestamp"].max()),
    )


def filter_resources_by_year(df: pd.DataFrame, start_year: int, end_year: int) -> pd.DataFrame:
    if end_year < start_year:
        raise ValueError("end_year must be >= start_year")

    out = validate_resources_dataframe(df)
    years = out["timestamp"].dt.year
    out = out[(years >= start_year) & (years <= end_year)].copy()

    if out.empty:
        raise ValueError("No resource data found in the selected year range")

    return out.reset_index(drop=True)


def _clamp_hourly_year_range(start_year: int, end_year: int) -> tuple[int, int]:
    if end_year < start_year:
        raise ValueError("end_year must be >= start_year")

    actual_start_year = max(int(start_year), NASA_HOURLY_MIN_YEAR)
    actual_end_year = int(end_year)

    if actual_end_year < actual_start_year:
        raise ValueError(
            f"NASA POWER hourly data is only supported from {NASA_HOURLY_MIN_YEAR} onward."
        )

    return actual_start_year, actual_end_year


def _year_chunks(start_year: int, end_year: int, chunk_years: int = 5) -> list[tuple[int, int]]:
    chunks: list[tuple[int, int]] = []
    current = start_year

    while current <= end_year:
        chunk_end = min(current + chunk_years - 1, end_year)
        chunks.append((current, chunk_end))
        current = chunk_end + 1

    return chunks


def _fetch_nasa_power_chunk(
    lat: float,
    lon: float,
    start_year: int,
    end_year: int,
    timeout: int = 60,
) -> pd.DataFrame:
    start = f"{start_year}0101"
    end = f"{end_year}1231"

    params = {
        "parameters": "ALLSKY_SFC_SW_DWN,WS50M,T2M",
        "community": "RE",
        "longitude": lon,
        "latitude": lat,
        "start": start,
        "end": end,
        "format": "JSON",
        "time-standard": "LST",
    }

    resp = requests.get(NASA_POWER_URL, params=params, timeout=timeout)
    resp.raise_for_status()

    data = resp.json()

    try:
        p = data["properties"]["parameter"]
        ghi = p["ALLSKY_SFC_SW_DWN"]
        ws50m = p["WS50M"]
        t2m = p["T2M"]
    except KeyError as e:
        raise ValueError(f"Unexpected NASA POWER response format: missing {e}")

    timestamps = sorted(ghi.keys())

    df = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(timestamps, format="%Y%m%d%H"),
            "ghi": [ghi[t] for t in timestamps],
            "ws50m": [ws50m[t] for t in timestamps],
            "temperature": [t2m[t] for t in timestamps],
        }
    )

    return validate_resources_dataframe(df)


def fetch_nasa_power_resources(
    lat: float,
    lon: float,
    start_year: int,
    end_year: int,
    timeout: int = 60,
    chunk_years: int = 5,
) -> pd.DataFrame:
    actual_start_year, actual_end_year = _clamp_hourly_year_range(start_year, end_year)

    parts: list[pd.DataFrame] = []
    for chunk_start, chunk_end in _year_chunks(actual_start_year, actual_end_year, chunk_years):
        chunk_df = _fetch_nasa_power_chunk(
            lat=lat,
            lon=lon,
            start_year=chunk_start,
            end_year=chunk_end,
            timeout=timeout,
        )
        parts.append(chunk_df)

    if not parts:
        raise ValueError("No NASA POWER resource data could be downloaded.")

    combined = pd.concat(parts, ignore_index=True)
    combined = (
        combined.sort_values("timestamp")
        .drop_duplicates(subset=["timestamp"])
        .reset_index(drop=True)
    )

    return validate_resources_dataframe(combined)


def add_time_features(df: pd.DataFrame) -> pd.DataFrame:
    out = validate_resources_dataframe(df)
    ts = out["timestamp"]

    out["year"] = ts.dt.year
    out["month"] = ts.dt.month
    out["month_name"] = ts.dt.strftime("%b")
    out["day"] = ts.dt.day
    out["date"] = pd.to_datetime(ts.dt.date)
    out["day_of_year"] = ts.dt.dayofyear
    out["hour"] = ts.dt.hour
    out["year_month"] = ts.dt.to_period("M").astype(str)
    return out


def aggregate_resources(
    df: pd.DataFrame,
    level: Literal["yearly", "monthly", "daily", "hourly"],
    metric: Literal["mean", "sum"] = "mean",
) -> pd.DataFrame:
    out = add_time_features(df)

    if metric not in {"mean", "sum"}:
        raise ValueError("metric must be 'mean' or 'sum'")

    agg_func = "mean" if metric == "mean" else "sum"

    if level == "yearly":
        grouped = (
            out.groupby("year", as_index=False)[["ghi", "ws50m", "temperature"]]
            .agg(agg_func)
            .rename(columns={"year": "label"})
        )
        grouped["label"] = grouped["label"].astype(str)
        return grouped

    if level == "monthly":
        grouped = (
            out.groupby(["year", "month"], as_index=False)[["ghi", "ws50m", "temperature"]]
            .agg(agg_func)
        )
        grouped["label"] = pd.to_datetime(
            grouped["year"].astype(str) + "-" + grouped["month"].astype(str).str.zfill(2) + "-01"
        )
        return grouped.sort_values("label").reset_index(drop=True)

    if level == "daily":
        grouped = (
            out.groupby("date", as_index=False)[["ghi", "ws50m", "temperature"]]
            .agg(agg_func)
            .rename(columns={"date": "label"})
        )
        return grouped.sort_values("label").reset_index(drop=True)

    if level == "hourly":
        grouped = out[["timestamp", "ghi", "ws50m", "temperature"]].copy()
        grouped = grouped.rename(columns={"timestamp": "label"})
        return grouped.sort_values("label").reset_index(drop=True)

    raise ValueError("level must be one of: yearly, monthly, daily, hourly")


def monthly_climatology(df: pd.DataFrame) -> pd.DataFrame:
    out = add_time_features(df)

    grouped = (
        out.groupby(["month", "month_name"], as_index=False)[["ghi", "ws50m", "temperature"]]
        .mean()
        .sort_values("month")
        .reset_index(drop=True)
    )

    grouped["label"] = grouped["month_name"]
    return grouped[["month", "month_name", "label", "ghi", "ws50m", "temperature"]]


def monthly_heatmap_table(
    df: pd.DataFrame,
    variable: Literal["ghi", "ws50m", "temperature"],
    metric: Literal["mean", "sum"] = "mean",
) -> pd.DataFrame:
    out = add_time_features(df)
    agg_func = "mean" if metric == "mean" else "sum"

    grouped = (
        out.groupby(["year", "month"], as_index=False)[[variable]]
        .agg(agg_func)
        .rename(columns={variable: "value"})
    )

    pivot = grouped.pivot(index="year", columns="month", values="value")
    pivot = pivot.reindex(columns=list(range(1, 13)))
    pivot.columns = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    return pivot


def monthly_boxplot_dataframe(
    df: pd.DataFrame,
    variable: Literal["ghi", "ws50m", "temperature"],
    metric: Literal["mean", "sum"] = "mean",
) -> pd.DataFrame:
    out = add_time_features(df)
    agg_func = "mean" if metric == "mean" else "sum"

    grouped = (
        out.groupby(["year", "month", "month_name"], as_index=False)[[variable]]
        .agg(agg_func)
        .rename(columns={variable: "value"})
        .sort_values(["month", "year"])
        .reset_index(drop=True)
    )

    month_order = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    grouped["month_name"] = pd.Categorical(grouped["month_name"], categories=month_order, ordered=True)
    return grouped


def save_resources(df: pd.DataFrame, project_folder: str | Path) -> Path:
    out = validate_resources_dataframe(df)
    path = resources_file_path(project_folder)
    out.to_csv(path, index=False)
    return path


def load_saved_resources(project_folder: str | Path) -> pd.DataFrame:
    path = resources_file_path(project_folder)
    if not path.exists():
        raise FileNotFoundError(f"Saved resources file not found in: {project_folder}")

    df = pd.read_csv(path)
    return validate_resources_dataframe(df)