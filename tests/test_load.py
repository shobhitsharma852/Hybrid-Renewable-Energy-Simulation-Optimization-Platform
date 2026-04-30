import tempfile
from pathlib import Path

import pandas as pd
import pytest

from core.load import (
    annual_energy_kwh,
    create_weekday_weekend_monthly_load,
    resample_load_to_timestep,
    standardize_load_dataframe,
    validate_hourly_load,
    summarize_load,
    create_constant_load,
    create_daily_profile_load,
    scale_load_to_annual_energy,
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
        validate_hourly_load(df, expect_rows=8760)


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


def test_scale_load_to_annual_energy_hits_target():
    df = make_valid_load_df()

    scaled = scale_load_to_annual_energy(df, 500_000.0)

    assert annual_energy_kwh(scaled) == pytest.approx(500_000.0)
    assert scaled["load_kw"].iloc[0] == pytest.approx(500_000.0 / 8760.0)


def test_summarize_load_uses_actual_timestep():
    timestamps = pd.date_range("2025-01-01 00:00:00", periods=4, freq="30min")
    df = pd.DataFrame({"timestamp": timestamps, "load_kw": [100.0] * 4})

    summary = summarize_load(df)

    assert summary.rows == 4
    assert summary.annual_energy_kwh == pytest.approx(200.0)


def test_resample_load_to_timestep_uses_stepwise_repeat_for_finer_resolution():
    timestamps = pd.date_range("2025-01-01 00:00:00", periods=3, freq="h")
    df = pd.DataFrame({"timestamp": timestamps, "load_kw": [10.0, 20.0, 30.0]})

    out = resample_load_to_timestep(df, 30)

    assert list(out["load_kw"]) == [10.0, 10.0, 20.0, 20.0, 30.0]


def test_create_weekday_weekend_monthly_load_applies_profiles_and_month_scaling():
    weekday = [10.0] * 24
    weekend = [20.0] * 24
    monthly = [1.0] * 12
    monthly[0] = 2.0

    df = create_weekday_weekend_monthly_load(
        weekday_hourly_profile_kw=weekday,
        weekend_hourly_profile_kw=weekend,
        monthly_multipliers=monthly,
        year=2025,
    )

    # 2025-01-01 is a Wednesday, so weekday profile * January multiplier.
    assert df.loc[0, "load_kw"] == pytest.approx(20.0)

    # 2025-01-04 is Saturday 00:00, so weekend profile * January multiplier.
    saturday_midnight = df.loc[df["timestamp"] == pd.Timestamp("2025-01-04 00:00:00")]
    assert float(saturday_midnight["load_kw"].iloc[0]) == pytest.approx(40.0)


def test_create_weekday_weekend_monthly_load_validates_input_lengths():
    with pytest.raises(ValueError, match="weekday_hourly_profile_kw must contain exactly 24 values"):
        create_weekday_weekend_monthly_load(
            weekday_hourly_profile_kw=[1.0] * 23,
            weekend_hourly_profile_kw=[1.0] * 24,
            monthly_multipliers=[1.0] * 12,
        )
