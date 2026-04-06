import tempfile
from pathlib import Path

import pandas as pd
import pytest

from core.load import (
    standardize_load_dataframe,
    validate_hourly_load,
    summarize_load,
    create_constant_load,
    create_daily_profile_load,
    save_load,
    load_saved_load,
)


def make_valid_load_df(n: int = 8760) -> pd.DataFrame:
    ts = pd.date_range("2025-01-01 00:00:00", periods=n, freq="h")
    return pd.DataFrame({
        "timestamp": ts,
        "load_kw": [150.0] * n,
    })


def test_standardize_valid_dataframe():
    df = make_valid_load_df()
    out = standardize_load_dataframe(df)

    assert list(out.columns) == ["timestamp", "load_kw"]
    assert len(out) == 8760


def test_validate_hourly_load_passes():
    df = make_valid_load_df()
    out = validate_hourly_load(df)

    assert len(out) == 8760


def test_validate_hourly_load_fails_wrong_rows():
    df = make_valid_load_df(8759)

    with pytest.raises(ValueError):
        validate_hourly_load(df)


def test_negative_load_fails():
    df = make_valid_load_df()
    df.loc[0, "load_kw"] = -1.0

    with pytest.raises(ValueError):
        standardize_load_dataframe(df)


def test_load_summary_correct():
    df = make_valid_load_df()
    s = summarize_load(df)

    assert s.rows == 8760
    assert s.annual_energy_kwh == 150.0 * 8760
    assert s.peak_kw == 150.0
    assert s.average_kw == 150.0
    assert s.min_kw == 150.0


def test_create_constant_load():
    df = create_constant_load(100.0, year=2025)

    assert len(df) == 8760
    assert df["load_kw"].iloc[0] == 100.0
    assert df["load_kw"].iloc[-1] == 100.0


def test_create_daily_profile_load():
    profile = [float(i) for i in range(24)]
    df = create_daily_profile_load(profile, year=2025)

    assert len(df) == 8760
    assert df["load_kw"].iloc[0] == 0.0
    assert df["load_kw"].iloc[1] == 1.0
    assert df["load_kw"].iloc[23] == 23.0
    assert df["load_kw"].iloc[24] == 0.0


def test_save_and_load_roundtrip():
    df = make_valid_load_df()

    with tempfile.TemporaryDirectory() as tmp:
        project_folder = Path(tmp) / "proj1"
        save_load(df, project_folder)
        df2 = load_saved_load(project_folder)

    assert len(df2) == 8760
    assert abs(df2["load_kw"].sum() - df["load_kw"].sum()) < 1e-9