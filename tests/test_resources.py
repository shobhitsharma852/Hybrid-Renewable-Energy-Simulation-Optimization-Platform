import tempfile
from pathlib import Path

import pandas as pd
import pytest

from core.resources import (
    validate_resources_dataframe,
    summarize_resources,
    filter_resources_by_year,
    save_resources,
    load_saved_resources,
)


def make_valid_resources_df():
    ts = pd.date_range("2025-01-01 00:00:00", periods=48, freq="h")
    return pd.DataFrame({
        "timestamp": ts,
        "ghi": [500.0] * 48,
        "ws50m": [5.5] * 48,
        "temperature": [25.0] * 48,
    })


def test_validate_resources_dataframe_passes():
    df = make_valid_resources_df()
    out = validate_resources_dataframe(df)
    assert len(out) == 48


def test_validate_resources_dataframe_fails_missing_column():
    df = make_valid_resources_df().drop(columns=["ws50m"])
    with pytest.raises(ValueError):
        validate_resources_dataframe(df)


def test_validate_resources_dataframe_fails_negative_ghi():
    df = make_valid_resources_df()
    df.loc[0, "ghi"] = -1
    with pytest.raises(ValueError):
        validate_resources_dataframe(df)


def test_validate_resources_dataframe_fails_negative_wind():
    df = make_valid_resources_df()
    df.loc[0, "ws50m"] = -1
    with pytest.raises(ValueError):
        validate_resources_dataframe(df)


def test_summarize_resources():
    df = make_valid_resources_df()
    s = summarize_resources(df)
    assert s.rows == 48
    assert s.ghi_mean == 500.0
    assert s.ws50m_mean == 5.5
    assert s.temperature_mean == 25.0


def test_filter_resources_by_year():
    ts = pd.date_range("2024-12-31 00:00:00", periods=48, freq="h")
    df = pd.DataFrame({
        "timestamp": ts,
        "ghi": [500.0] * 48,
        "ws50m": [5.5] * 48,
        "temperature": [25.0] * 48,
    })
    df = validate_resources_dataframe(df)
    out = filter_resources_by_year(df, 2025, 2025)
    assert (out["timestamp"].dt.year == 2025).all()


def test_save_and_load_resources_roundtrip():
    df = make_valid_resources_df()

    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / "proj1"
        save_resources(df, folder)
        df2 = load_saved_resources(folder)

    assert len(df2) == len(df)
    assert abs(df2["ghi"].mean() - 500.0) < 1e-9