from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pandas as pd
import requests


NASA_POWER_URL = "https://power.larc.nasa.gov/api/temporal/hourly/point"
NASA_HOURLY_MIN_YEAR = 2001

# Solar constant (W/m²) — HOMER uses 1367
SOLAR_CONSTANT_W_PER_M2: float = 1367.0


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
    if not diffs.empty:
        unique = diffs.unique()
        if len(unique) != 1:
            raise ValueError("Resources timestamps are not evenly spaced")

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


def resample_resources_to_timestep(
    df: pd.DataFrame,
    time_step_minutes: int,
) -> pd.DataFrame:
    """
    Resample a resource dataframe (hourly or any resolution) to the target timestep.

    Uses linear interpolation for all columns (GHI, wind speed, temperature).
    GHI is clipped to >= 0 after interpolation.
    Clearness index columns (g0_w_m2, clearness_index) are re-interpolated
    the same way if present.

    Parameters
    ----------
    df:
        Resource dataframe with at least timestamp, ghi, ws50m, temperature columns.
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
    resampled = resampled.reindex(new_index)

    if "ghi" in resampled.columns:
        resampled["ghi"] = resampled["ghi"].clip(lower=0.0)
    if "ws50m" in resampled.columns:
        resampled["ws50m"] = resampled["ws50m"].clip(lower=0.0)

    resampled = resampled.reset_index().rename(columns={"index": "timestamp"})
    return resampled.reset_index(drop=True)


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
    # Preserve optional clearness index columns if already computed
    for col in ["g0_w_m2", "clearness_index"]:
        if col in df.columns:
            out[col] = df[col].values
    path = resources_file_path(project_folder)
    out.to_csv(path, index=False)
    return path


def load_saved_resources(project_folder: str | Path) -> pd.DataFrame:
    path = resources_file_path(project_folder)
    if not path.exists():
        raise FileNotFoundError(f"Saved resources file not found in: {project_folder}")

    df = pd.read_csv(path)
    return validate_resources_dataframe(df)


# ============================================================
# CLEARNESS INDEX (Kt) COMPUTATION
# ============================================================

def _eot_homer_hours(n: int) -> float:
    """
    Equation of time using HOMER's documented formula (Spencer / Duffie-Beckman).

    E = 3.82 * (0.000075 + 0.001868*cosB - 0.032077*sinB
                          - 0.014615*cos2B - 0.04089*sin2B)

    where B = (360/365)*(n-1) degrees converted to radians.
    Returns E in hours.
    """
    B = math.radians(360.0 / 365.0 * (n - 1))
    return 3.82 * (
        0.000075
        + 0.001868 * math.cos(B)
        - 0.032077 * math.sin(B)
        - 0.014615 * math.cos(2 * B)
        - 0.04089  * math.sin(2 * B)
    )


def _compute_g0_for_timestamp(
    ts: pd.Timestamp,
    lat: float,
    lon: float,
    timezone_offset_hours: float,
) -> float:
    """
    Compute extraterrestrial horizontal irradiance G0 (W/m²) averaged over one hourly timestep.

    Uses HOMER's documented solar-time equation and the Duffie & Beckman /
    HOMER time-step average form for extraterrestrial horizontal radiation.

    Why this matters:
    - A midpoint-only approximation is close, but it is not the same as HOMER.
    - HOMER integrates extraterrestrial horizontal radiation over the whole time step
      using the hour angle at the beginning and end of the step.
    - This produces noticeably closer HOMER parity for capped-Kt workflows.
    """
    n = ts.timetuple().tm_yday
    E = _eot_homer_hours(n)

    lat_r = math.radians(lat)
    dec_r = math.radians(23.45 * math.sin(math.radians(360.0 / 365.0 * (n - 81))))

    B = math.radians(360.0 / 365.0 * (n - 1))
    e0 = 1.0 + 0.033 * math.cos(B)
    g_on = SOLAR_CONSTANT_W_PER_M2 * e0

    # HOMER works in civil time and converts to solar time. For an hourly step,
    # compute the hour angle at the beginning and end of the hour, then integrate.
    civil_hour_start = float(ts.hour)
    civil_hour_end = civil_hour_start + 1.0

    solar_hour_start = civil_hour_start + lon / 15.0 - timezone_offset_hours + E
    solar_hour_end = civil_hour_end + lon / 15.0 - timezone_offset_hours + E

    hour_angle_start_deg = 15.0 * (solar_hour_start - 12.0)
    hour_angle_end_deg = 15.0 * (solar_hour_end - 12.0)

    # Clip the hour-angle interval to the daylight interval so night-time and
    # sunrise/sunset partial hours are handled correctly.
    cos_ws = -math.tan(lat_r) * math.tan(dec_r)

    if cos_ws >= 1.0:
        return 0.0

    if cos_ws <= -1.0:
        sunset_hour_angle_r = math.pi
    else:
        sunset_hour_angle_r = math.acos(cos_ws)

    daylight_start_deg = -math.degrees(sunset_hour_angle_r)
    daylight_end_deg = math.degrees(sunset_hour_angle_r)

    clipped_start_deg = max(daylight_start_deg, min(daylight_end_deg, hour_angle_start_deg))
    clipped_end_deg = max(daylight_start_deg, min(daylight_end_deg, hour_angle_end_deg))

    if clipped_end_deg <= clipped_start_deg:
        return 0.0

    w1 = math.radians(clipped_start_deg)
    w2 = math.radians(clipped_end_deg)

    g0_avg = (12.0 / math.pi) * g_on * (
        math.cos(lat_r) * math.cos(dec_r) * (math.sin(w2) - math.sin(w1))
        + (w2 - w1) * math.sin(lat_r) * math.sin(dec_r)
    )

    return max(0.0, g0_avg)


def add_clearness_index(
    df: pd.DataFrame,
    lat: float,
    lon: float,
    timezone_offset_hours: float = 5.5,
) -> pd.DataFrame:
    """
    Add G0 and clearness index (Kt) columns to a resources DataFrame.

    Columns added:
        g0_w_m2          — extraterrestrial horizontal irradiance (W/m²)
        clearness_index  — Kt = GHI / G0  (0 when sun is below horizon)

    Parameters
    ----------
    df                    : validated resources DataFrame
    lat                   : site latitude in degrees North
    lon                   : site longitude in degrees East
    timezone_offset_hours : hours east of UTC (e.g. India = 5.5)

    Notes
    -----
    - Uses HOMER's documented EoT formula for solar time.
    - Kt is NOT capped here — the cap (kt_max) is applied in the PV model
      so different projects can use different cap values without re-downloading.
    - Kt > 1 physically means the NASA data has a spurious high value for that hour.
    """
    out = validate_resources_dataframe(df).copy()

    out["g0_w_m2"] = out["timestamp"].apply(
        lambda t: _compute_g0_for_timestamp(t, lat, lon, timezone_offset_hours)
    )

    out["clearness_index"] = out.apply(
        lambda r: r["ghi"] / r["g0_w_m2"] if r["g0_w_m2"] > 10.0 else 0.0,
        axis=1,
    )

    return out