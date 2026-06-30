from __future__ import annotations

import pandas as pd


def infer_step_minutes(index: pd.DatetimeIndex) -> float:
    """Return the uniform timestep in minutes from a DatetimeIndex."""
    diffs = index.to_series().diff().dropna()
    if diffs.empty:
        return 60.0
    return diffs.iloc[0].total_seconds() / 60.0


def resampled_end(
    source_last: pd.Timestamp,
    source_step_minutes: float,
    target_step_minutes: int,
) -> pd.Timestamp:
    """
    Compute the correct end timestamp for an upsampled date_range so the
    last source interval is fully covered.

    When upsampling (target < source), the last source timestamp marks only
    the START of its interval. Without extension pd.date_range stops there,
    dropping the remaining sub-steps — e.g. hourly 23:00 resampled to 15-min
    loses 23:15, 23:30, 23:45 (3 rows short per year of data).

    For downsampling or same-resolution, the original end is returned unchanged.
    """
    if target_step_minutes < source_step_minutes:
        return (
            source_last
            + pd.Timedelta(minutes=source_step_minutes)
            - pd.Timedelta(minutes=target_step_minutes)
        )
    return source_last
