from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO
import io
import json
import random
import re
import warnings

import pandas as pd


@dataclass(frozen=True)
class LoadSummary:
    rows: int
    annual_energy_kwh: float
    peak_kw: float
    average_kw: float
    min_kw: float


@dataclass(frozen=True)
class LoadGenerationSettings:
    method: str = "weekday_weekend_monthly"
    weekday_monthly_profiles_kw: list[list[float]] | None = None
    weekend_monthly_profiles_kw: list[list[float]] | None = None
    daily_variability_pct: float = 10.0
    timestep_variability_pct: float = 20.0
    random_seed: int | None = 42
    preserve_annual_energy: bool = True


@dataclass(frozen=True)
class LoadQualityMessage:
    level: str
    message: str


def project_inputs_dir(project_folder: str | Path) -> Path:
    path = Path(project_folder) / "inputs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_generation_settings_file_path(project_folder: str | Path) -> Path:
    return Path(project_folder) / "load_generation.json"


def load_file_path(project_folder: str | Path) -> Path:
    return project_inputs_dir(project_folder) / "load.csv"


def default_monthly_profiles(default_kw: float) -> list[list[float]]:
    return [[float(default_kw)] * 24 for _ in range(12)]


_RE_TIME_ONLY  = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?$")
_RE_DATE_ONLY  = re.compile(
    r"^\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4}$"   # DD-MM-YYYY / MM-DD-YYYY
    r"|^\d{4}[\/\-\.]\d{1,2}[\/\-\.]\d{1,2}$"     # YYYY-MM-DD
)
_RE_ISO_DATE_PREFIX = re.compile(r"^\d{4}[\/\-\.]\d{1,2}[\/\-\.]\d{1,2}")
_RE_PLAIN_NUMBER = re.compile(r"^[+-]?\d+(\.\d+)?$")
# Keywords that hint a column contains load/power/energy values
_LOAD_KEYWORDS = {
    "load", "demand", "consumption", "power", "energy",
    "kw", "kwh", "active", "import", "export", "usage",
}


def _parse_timestamp_series(
    values: pd.Series,
    *,
    prefer_dayfirst: bool = True,
) -> pd.Series:
    """
    Parse timestamps without corrupting ISO dates.

    Pandas can turn ISO strings like 2025-01-13 into NaT when dayfirst=True.
    Saved engine files use ISO, while user uploads often use DD-MM-YYYY, so parse
    ISO-looking rows as year-first and keep day-first as the default otherwise.
    """
    series = pd.Series(values).copy()

    if pd.api.types.is_datetime64_any_dtype(series):
        return pd.to_datetime(series, errors="coerce")

    text = series.astype(str).str.strip()
    plain_number_mask = text.str.match(_RE_PLAIN_NUMBER)
    valid_text = series.notna() & text.ne("") & ~plain_number_mask
    iso_mask = valid_text & text.str.match(_RE_ISO_DATE_PREFIX)

    parsed = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]")

    def _safe_parse_datetime(text_values: pd.Series, *, dayfirst: bool) -> pd.Series:
        try:
            return pd.to_datetime(
                text_values,
                dayfirst=dayfirst,
                errors="coerce",
            )
        except (OverflowError, ValueError, AssertionError):
            return pd.Series(pd.NaT, index=text_values.index, dtype="datetime64[ns]")

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")

        if iso_mask.any():
            parsed.loc[iso_mask] = _safe_parse_datetime(
                text.loc[iso_mask], dayfirst=False
            )

        non_iso_mask = valid_text & ~iso_mask
        if non_iso_mask.any():
            parsed.loc[non_iso_mask] = _safe_parse_datetime(
                text.loc[non_iso_mask], dayfirst=prefer_dayfirst
            )

        # Last chance for mixed files: fill only failed rows using the opposite
        # day/month preference, preserving the primary interpretation when valid.
        failed_mask = valid_text & parsed.isna()
        if failed_mask.any():
            parsed.loc[failed_mask] = _safe_parse_datetime(
                text.loc[failed_mask], dayfirst=not prefer_dayfirst
            )

    return parsed


def _classify_columns(df: pd.DataFrame) -> dict[str, list[str]]:
    """
    Inspect column VALUES (not names) and sort each column into one of:
      'datetime'  — contains full date+time  (e.g. '2024-01-01 06:00')
      'date'      — contains date only       (e.g. '01-01-2024')
      'time'      — contains HH:MM or HH:MM:SS (e.g. '06:00')
      'hour_int'  — integers 0-23 repeating  (hour-of-day column)
      'numeric'   — other positive numeric   (candidate load column)
      'skip'      — serial numbers / IDs / text

    Regex checks (time-only, date-only) run BEFORE full datetime parsing to prevent
    dateutil from mis-classifying "01:00" strings as today-at-01:00 (same-date, no variation
    → skip) instead of a time column.
    """
    buckets: dict[str, list[str]] = {
        "datetime": [], "date": [], "time": [],
        "hour_int": [], "numeric": [], "skip": [],
    }

    for col in df.columns:
        sample = df[col].dropna().head(48)
        str_s  = sample.astype(str).str.strip()

        if len(str_s) == 0:
            buckets["skip"].append(col)
            continue

        # ── 1. Time-only strings: HH:MM or HH:MM:SS ──────────
        # Must run BEFORE datetime parse: dateutil can parse "01:00" as today at 01:00,
        # which has_date_var=False and would fall to skip incorrectly.
        time_hit = str_s.str.match(_RE_TIME_ONLY).mean()
        if time_hit > 0.8:
            buckets["time"].append(col)
            continue

        # ── 2. Date-only strings: DD-MM-YYYY or YYYY-MM-DD ───
        # Check before datetime parse to avoid same-date samples collapsing to skip.
        date_hit = str_s.str.match(_RE_DATE_ONLY).mean()
        if date_hit > 0.8:
            buckets["date"].append(col)
            continue

        # ── 3. Full datetime strings: "2024-01-01 06:00" etc. ─
        parsed = _parse_timestamp_series(str_s, prefer_dayfirst=True)
        hit_rate = parsed.notna().mean()

        if hit_rate > 0.8:
            has_time = (parsed.dt.hour != 0).any() or (parsed.dt.minute != 0).any()
            has_date_var = parsed.dropna().dt.date.nunique() > 1
            # Qualify as datetime if either time or date variation is present;
            # a small sample may have only one unique date (e.g. first 3 rows = same day).
            if has_time or has_date_var:
                buckets["datetime"].append(col)
            else:
                buckets["skip"].append(col)
            continue

        # ── 4. Numeric ─────────────────────────────────────────
        numeric = pd.to_numeric(sample, errors="coerce")
        if numeric.notna().mean() > 0.8 and (numeric.dropna() >= 0).all():
            vals = numeric.dropna().reset_index(drop=True)

            # Serial-number detection: strictly incrementing by 1 from a small start
            if len(vals) > 3:
                diffs = vals.diff().dropna()
                if (diffs == 1).mean() > 0.95 and vals.iloc[0] <= 10:
                    buckets["skip"].append(col)
                    continue

            # Hour-integer detection: values 0-23, ≤24 unique values
            if vals.max() <= 23 and vals.min() >= 0 and vals.nunique() <= 24:
                buckets["hour_int"].append(col)
                continue

            buckets["numeric"].append(col)
            continue

        buckets["skip"].append(col)

    return buckets


def _auto_detect_load_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Automatically extract 'timestamp' and 'load_kw' from any CSV layout.

    Detection is VALUE-BASED:
      - column headers are used only as a weak secondary hint for the load column
      - works regardless of language, naming convention, or extra columns

    Supported layouts (non-exhaustive):
      1. Single combined datetime column  + load column
      2. Separate date column + time column (HH:MM)  + load column
      3. Separate date column + hour-integer column (0-23)  + load column
      4. Any of the above with extra columns (serial numbers, IDs, etc.)
    """
    out = df.copy()
    buckets = _classify_columns(out)

    # ── Build timestamp ────────────────────────────────────────
    if buckets["datetime"]:
        # Best case: one column already has full datetime
        ts_col = buckets["datetime"][0]
        out["timestamp"] = _parse_timestamp_series(out[ts_col], prefer_dayfirst=True)
        out = out.drop(columns=[c for c in buckets["datetime"] if c != "timestamp"])

    elif buckets["date"] and buckets["time"]:
        # Separate date + HH:MM columns
        date_col = buckets["date"][0]
        time_col = buckets["time"][0]
        combined = (
            out[date_col].astype(str).str.strip()
            + " "
            + out[time_col].astype(str).str.strip()
        )
        out["timestamp"] = _parse_timestamp_series(combined, prefer_dayfirst=True)
        out = out.drop(columns=[date_col, time_col])

    elif buckets["date"] and buckets["hour_int"]:
        # Separate date + integer hour (0, 1, 2, …, 23)
        date_col = buckets["date"][0]
        hour_col = buckets["hour_int"][0]
        hour_str = out[hour_col].apply(lambda h: f"{int(h):02d}:00")
        combined = out[date_col].astype(str).str.strip() + " " + hour_str
        out["timestamp"] = _parse_timestamp_series(combined, prefer_dayfirst=True)
        out = out.drop(columns=[date_col, hour_col])

    # ── Identify the load column ───────────────────────────────
    if "load_kw" not in out.columns:
        candidates = [c for c in buckets["numeric"] if c in out.columns]

        if len(candidates) == 1:
            out = out.rename(columns={candidates[0]: "load_kw"})
        elif len(candidates) > 1:
            # Score by how many load-related keywords appear in the column name
            def _name_score(col: str) -> int:
                lc = col.lower()
                return sum(1 for kw in _LOAD_KEYWORDS if kw in lc)

            candidates.sort(key=_name_score, reverse=True)
            out = out.rename(columns={candidates[0]: "load_kw"})

    return out


def standardize_load_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(df, pd.DataFrame):
        raise TypeError("Input must be a pandas DataFrame")

    if {"timestamp", "load_kw"}.issubset(df.columns):
        out = df.copy()
    else:
        out = _auto_detect_load_columns(df.copy())

    if "timestamp" not in out.columns or "load_kw" not in out.columns:
        raise ValueError(
            "Could not detect timestamp and load columns automatically. "
            "Please ensure the file has a date/time column and a numeric load column."
        )

    out = out[["timestamp", "load_kw"]].copy()

    out["timestamp"] = _parse_timestamp_series(out["timestamp"], prefer_dayfirst=True)
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


def monthly_load_summary(df: pd.DataFrame) -> pd.DataFrame:
    dt_hours = infer_time_step_hours(df)
    out = df.copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"], errors="coerce")
    if out["timestamp"].isna().any():
        raise ValueError("Some timestamp values are invalid")

    out["load_kw"] = pd.to_numeric(out["load_kw"], errors="coerce")
    if out["load_kw"].isna().any():
        raise ValueError("Some load values are non-numeric")

    out["month"] = out["timestamp"].dt.month
    out["month_name"] = out["timestamp"].dt.month_name()

    summary = (
        out.groupby(["month", "month_name"], as_index=False)
        .agg(
            energy_kwh=("load_kw", lambda s: float(s.sum()) * dt_hours),
            peak_kw=("load_kw", "max"),
            average_kw=("load_kw", "mean"),
            min_kw=("load_kw", "min"),
        )
        .sort_values("month")
        .reset_index(drop=True)
    )

    return summary[["month", "month_name", "energy_kwh", "peak_kw", "average_kw", "min_kw"]]


def daily_load_summary(df: pd.DataFrame) -> pd.DataFrame:
    dt_hours = infer_time_step_hours(df)
    out = df.copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"], errors="coerce")
    if out["timestamp"].isna().any():
        raise ValueError("Some timestamp values are invalid")

    out["load_kw"] = pd.to_numeric(out["load_kw"], errors="coerce")
    if out["load_kw"].isna().any():
        raise ValueError("Some load values are non-numeric")

    out["date"] = out["timestamp"].dt.date
    out["day_type"] = out["timestamp"].dt.weekday.map(lambda d: "Weekend" if d >= 5 else "Weekday")

    summary = (
        out.groupby(["date", "day_type"], as_index=False)
        .agg(
            energy_kwh=("load_kw", lambda s: float(s.sum()) * dt_hours),
            peak_kw=("load_kw", "max"),
            average_kw=("load_kw", "mean"),
            min_kw=("load_kw", "min"),
        )
        .sort_values("date")
        .reset_index(drop=True)
    )

    return summary[["date", "day_type", "energy_kwh", "peak_kw", "average_kw", "min_kw"]]


def load_duration_summary(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["load_kw"] = pd.to_numeric(out["load_kw"], errors="coerce")
    if out["load_kw"].isna().any():
        raise ValueError("Some load values are non-numeric")

    sorted_load = out["load_kw"].sort_values(ascending=False).reset_index(drop=True)
    points = len(sorted_load)
    if points == 0:
        return pd.DataFrame(columns=["rank", "percent_of_time", "load_kw"])

    if points == 1:
        percent_of_time = [100.0]
    else:
        percent_of_time = [(idx / (points - 1)) * 100.0 for idx in range(points)]

    return pd.DataFrame({
        "rank": list(range(1, points + 1)),
        "percent_of_time": percent_of_time,
        "load_kw": sorted_load.tolist(),
    })


def load_quality_messages(
    df: pd.DataFrame,
    *,
    variability_enabled: bool = False,
    random_seed_enabled: bool = True,
) -> list[LoadQualityMessage]:
    messages: list[LoadQualityMessage] = []

    try:
        summary = summarize_load(df)
        monthly_df = monthly_load_summary(df)
    except Exception as e:
        return [LoadQualityMessage("warning", f"Load data could not be fully validated: {e}")]

    if summary.rows == 0:
        return [LoadQualityMessage("warning", "Load profile is empty.")]

    if summary.annual_energy_kwh <= 0:
        messages.append(LoadQualityMessage("warning", "Annual load energy is zero."))
    elif summary.annual_energy_kwh < 1_000:
        messages.append(
            LoadQualityMessage(
                "info",
                f"Annual load energy is very low ({summary.annual_energy_kwh:,.0f} kWh).",
            )
        )

    near_zero_months = monthly_df.loc[monthly_df["energy_kwh"] <= 1e-9, "month_name"].tolist()
    if near_zero_months:
        messages.append(
            LoadQualityMessage(
                "warning",
                f"These months have zero load energy: {', '.join(near_zero_months)}.",
            )
        )

    if summary.average_kw > 0:
        peak_to_average = summary.peak_kw / summary.average_kw
        if peak_to_average >= 5.0:
            messages.append(
                LoadQualityMessage(
                    "warning",
                    f"Peak load is {peak_to_average:.1f}x the average load. Check for accidental spikes.",
                )
            )
        elif peak_to_average >= 3.0:
            messages.append(
                LoadQualityMessage(
                    "info",
                    f"Peak load is {peak_to_average:.1f}x the average load.",
                )
            )

    zero_fraction = float((pd.to_numeric(df["load_kw"], errors="coerce") <= 1e-9).mean())
    if zero_fraction >= 0.5:
        messages.append(
            LoadQualityMessage(
                "warning",
                f"{zero_fraction * 100:.0f}% of load timesteps are zero or near-zero.",
            )
        )
    elif zero_fraction >= 0.2:
        messages.append(
            LoadQualityMessage(
                "info",
                f"{zero_fraction * 100:.0f}% of load timesteps are zero or near-zero.",
            )
        )

    if variability_enabled and not random_seed_enabled:
        messages.append(
            LoadQualityMessage(
                "info",
                "Variability is enabled without a random seed, so regenerated loads may differ each time.",
            )
        )

    if not messages:
        messages.append(LoadQualityMessage("success", "Load quality checks passed."))

    return messages


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
    daily_variability_pct: float = 0.0,
    timestep_variability_pct: float = 0.0,
    random_seed: int | None = None,
    preserve_annual_energy: bool = True,
) -> pd.DataFrame:
    if constant_kw < 0:
        raise ValueError("constant_kw cannot be negative")

    if daily_variability_pct > 0 or timestep_variability_pct > 0:
        if expect_rows != 8760:
            raise ValueError("Variable constant loads currently require expect_rows=8760")
        return create_weekday_weekend_monthly_load(
            weekday_hourly_profile_kw=[float(constant_kw)] * 24,
            weekend_hourly_profile_kw=[float(constant_kw)] * 24,
            monthly_multipliers=[1.0] * 12,
            year=year,
            daily_variability_pct=daily_variability_pct,
            timestep_variability_pct=timestep_variability_pct,
            random_seed=random_seed,
            preserve_annual_energy=preserve_annual_energy,
        )

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
    daily_variability_pct: float = 0.0,
    timestep_variability_pct: float = 0.0,
    random_seed: int | None = None,
    preserve_annual_energy: bool = True,
) -> pd.DataFrame:
    if len(hourly_profile_kw) != 24:
        raise ValueError("hourly_profile_kw must contain exactly 24 values")

    vals = [float(v) for v in hourly_profile_kw]
    if any(v < 0 for v in vals):
        raise ValueError("Daily profile values cannot be negative")

    if daily_variability_pct > 0 or timestep_variability_pct > 0:
        if days != 365:
            raise ValueError("Variable daily profile loads currently require days=365")
        return create_weekday_weekend_monthly_load(
            weekday_hourly_profile_kw=vals,
            weekend_hourly_profile_kw=vals,
            monthly_multipliers=[1.0] * 12,
            year=year,
            daily_variability_pct=daily_variability_pct,
            timestep_variability_pct=timestep_variability_pct,
            random_seed=random_seed,
            preserve_annual_energy=preserve_annual_energy,
        )

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
    daily_variability_pct: float = 0.0,
    timestep_variability_pct: float = 0.0,
    random_seed: int | None = None,
    preserve_annual_energy: bool = True,
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

    if any(v < 0 for v in month_vals):
        raise ValueError("Monthly multipliers cannot be negative")

    weekday_monthly_profiles = [
        [hourly_kw * month_multiplier for hourly_kw in weekday_vals]
        for month_multiplier in month_vals
    ]
    weekend_monthly_profiles = [
        [hourly_kw * month_multiplier for hourly_kw in weekend_vals]
        for month_multiplier in month_vals
    ]

    return create_weekday_weekend_monthly_profile_load(
        weekday_monthly_profiles_kw=weekday_monthly_profiles,
        weekend_monthly_profiles_kw=weekend_monthly_profiles,
        year=year,
        daily_variability_pct=daily_variability_pct,
        timestep_variability_pct=timestep_variability_pct,
        random_seed=random_seed,
        preserve_annual_energy=preserve_annual_energy,
    )


def _validate_monthly_hourly_profiles(
    profiles: list[list[float]],
    label: str,
) -> list[list[float]]:
    if len(profiles) != 12:
        raise ValueError(f"{label} must contain exactly 12 monthly profiles")

    out: list[list[float]] = []
    for month_index, monthly_profile in enumerate(profiles, start=1):
        if len(monthly_profile) != 24:
            raise ValueError(
                f"{label} month {month_index} must contain exactly 24 hourly values"
            )
        vals = [float(v) for v in monthly_profile]
        if any(v < 0 for v in vals):
            raise ValueError(f"{label} values cannot be negative")
        out.append(vals)

    return out


def validate_load_generation_settings(settings: LoadGenerationSettings) -> None:
    if settings.method != "weekday_weekend_monthly":
        raise ValueError("Unsupported load generation method")

    weekday_profiles = settings.weekday_monthly_profiles_kw or default_monthly_profiles(50.0)
    weekend_profiles = settings.weekend_monthly_profiles_kw or default_monthly_profiles(30.0)
    _validate_monthly_hourly_profiles(weekday_profiles, "weekday_monthly_profiles_kw")
    _validate_monthly_hourly_profiles(weekend_profiles, "weekend_monthly_profiles_kw")

    if settings.daily_variability_pct < 0:
        raise ValueError("daily_variability_pct cannot be negative")

    if settings.timestep_variability_pct < 0:
        raise ValueError("timestep_variability_pct cannot be negative")

    if settings.random_seed is not None and int(settings.random_seed) < 0:
        raise ValueError("random_seed cannot be negative")


def load_generation_settings_to_dict(
    settings: LoadGenerationSettings,
) -> dict[str, object]:
    validate_load_generation_settings(settings)
    return {
        "method": settings.method,
        "weekday_monthly_profiles_kw": (
            settings.weekday_monthly_profiles_kw or default_monthly_profiles(50.0)
        ),
        "weekend_monthly_profiles_kw": (
            settings.weekend_monthly_profiles_kw or default_monthly_profiles(30.0)
        ),
        "daily_variability_pct": float(settings.daily_variability_pct),
        "timestep_variability_pct": float(settings.timestep_variability_pct),
        "random_seed": settings.random_seed,
        "preserve_annual_energy": bool(settings.preserve_annual_energy),
    }


def load_generation_settings_from_dict(data: dict[str, object]) -> LoadGenerationSettings:
    seed_value = data.get("random_seed", 42)
    settings = LoadGenerationSettings(
        method=str(data.get("method", "weekday_weekend_monthly")),
        weekday_monthly_profiles_kw=data.get("weekday_monthly_profiles_kw"),  # type: ignore[arg-type]
        weekend_monthly_profiles_kw=data.get("weekend_monthly_profiles_kw"),  # type: ignore[arg-type]
        daily_variability_pct=float(data.get("daily_variability_pct", 10.0)),
        timestep_variability_pct=float(data.get("timestep_variability_pct", 20.0)),
        random_seed=None if seed_value is None else int(seed_value),
        preserve_annual_energy=bool(data.get("preserve_annual_energy", True)),
    )
    validate_load_generation_settings(settings)
    return settings


def save_load_generation_settings(
    settings: LoadGenerationSettings,
    project_folder: str | Path,
) -> Path:
    validate_load_generation_settings(settings)
    project_folder = Path(project_folder)
    project_folder.mkdir(parents=True, exist_ok=True)

    path = load_generation_settings_file_path(project_folder)
    path.write_text(
        json.dumps(load_generation_settings_to_dict(settings), indent=2),
        encoding="utf-8",
    )
    return path


def load_load_generation_settings(project_folder: str | Path) -> LoadGenerationSettings:
    path = load_generation_settings_file_path(project_folder)
    if not path.exists():
        return LoadGenerationSettings()

    data = json.loads(path.read_text(encoding="utf-8"))
    return load_generation_settings_from_dict(data)


def create_weekday_weekend_monthly_profile_load(
    weekday_monthly_profiles_kw: list[list[float]],
    weekend_monthly_profiles_kw: list[list[float]],
    year: int = 2025,
    daily_variability_pct: float = 0.0,
    timestep_variability_pct: float = 0.0,
    random_seed: int | None = None,
    preserve_annual_energy: bool = True,
) -> pd.DataFrame:
    weekday_profiles = _validate_monthly_hourly_profiles(
        weekday_monthly_profiles_kw,
        "weekday_monthly_profiles_kw",
    )
    weekend_profiles = _validate_monthly_hourly_profiles(
        weekend_monthly_profiles_kw,
        "weekend_monthly_profiles_kw",
    )
    daily_variability_pct = float(daily_variability_pct)
    timestep_variability_pct = float(timestep_variability_pct)

    if daily_variability_pct < 0:
        raise ValueError("daily_variability_pct cannot be negative")

    if timestep_variability_pct < 0:
        raise ValueError("timestep_variability_pct cannot be negative")

    start = pd.Timestamp(f"{year}-01-01 00:00:00")
    end = pd.Timestamp(f"{year + 1}-01-01 00:00:00")
    ts = pd.date_range(start=start, end=end, freq="h", inclusive="left")

    rng = random.Random(random_seed)
    daily_multipliers: dict[pd.Timestamp, float] = {}

    def _variability_multiplier(percent: float) -> float:
        if percent <= 0:
            return 1.0
        sigma = percent / 100.0
        return max(0.0, rng.gauss(1.0, sigma))

    loads: list[float] = []
    for timestamp in ts:
        is_weekend = timestamp.weekday() >= 5
        month_index = int(timestamp.month) - 1
        base_profile = weekend_profiles[month_index] if is_weekend else weekday_profiles[month_index]
        date_key = pd.Timestamp(timestamp.date())

        if date_key not in daily_multipliers:
            daily_multipliers[date_key] = _variability_multiplier(daily_variability_pct)

        timestep_multiplier = _variability_multiplier(timestep_variability_pct)
        load_kw = (
            base_profile[int(timestamp.hour)]
            * daily_multipliers[date_key]
            * timestep_multiplier
        )
        loads.append(max(0.0, load_kw))

    df = pd.DataFrame({
        "timestamp": ts,
        "load_kw": loads,
    })
    df = validate_hourly_load(df, expect_rows=len(ts))

    if preserve_annual_energy and (daily_variability_pct > 0 or timestep_variability_pct > 0):
        baseline_df = create_weekday_weekend_monthly_profile_load(
            weekday_monthly_profiles_kw=weekday_profiles,
            weekend_monthly_profiles_kw=weekend_profiles,
            year=year,
            preserve_annual_energy=False,
        )
        baseline_energy_kwh = annual_energy_kwh(baseline_df)
        if baseline_energy_kwh > 0:
            df = scale_load_to_annual_energy(df, baseline_energy_kwh)

    return df


def save_load(df: pd.DataFrame, project_folder: str | Path) -> Path:
    path = load_file_path(project_folder)
    out = standardize_load_dataframe(df)
    out["timestamp"] = out["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")
    temp_path = path.with_name(f".{path.name}.tmp")

    try:
        out.to_csv(temp_path, index=False)
        temp_path.replace(path)
    except PermissionError as exc:
        temp_path.unlink(missing_ok=True)
        raise PermissionError(
            f"Cannot save '{path}'. Close this CSV in Excel or any other program, "
            "then click 'Save Load to Project' again."
        ) from exc
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise

    return path


def load_saved_load(project_folder: str | Path) -> pd.DataFrame:
    path = load_file_path(project_folder)
    if not path.exists():
        raise FileNotFoundError(f"Saved load file not found in: {project_folder}")

    df = pd.read_csv(path)
    df = standardize_load_dataframe(df)
    return validate_hourly_load(df)
