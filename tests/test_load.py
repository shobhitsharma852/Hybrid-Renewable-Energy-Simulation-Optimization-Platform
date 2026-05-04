import tempfile
from pathlib import Path

import pandas as pd
import pytest

from core.load import (
    LoadGenerationSettings,
    annual_energy_kwh,
    create_weekday_weekend_monthly_profile_load,
    create_weekday_weekend_monthly_load,
    daily_load_summary,
    load_duration_summary,
    load_quality_messages,
    load_generation_settings_file_path,
    load_load_generation_settings,
    monthly_load_summary,
    resample_load_to_timestep,
    save_load_generation_settings,
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


def test_save_and_load_generation_settings_roundtrip():
    weekday_profiles = [[float(month + hour) for hour in range(24)] for month in range(12)]
    weekend_profiles = [[float(100 + month + hour) for hour in range(24)] for month in range(12)]
    settings = LoadGenerationSettings(
        weekday_monthly_profiles_kw=weekday_profiles,
        weekend_monthly_profiles_kw=weekend_profiles,
        daily_variability_pct=10.0,
        timestep_variability_pct=20.0,
        random_seed=123,
        preserve_annual_energy=False,
    )

    with tempfile.TemporaryDirectory() as tmp:
        project_folder = Path(tmp) / "proj1"
        path = save_load_generation_settings(settings, project_folder)
        loaded = load_load_generation_settings(project_folder)

    assert path.name == "load_generation.json"
    assert loaded == settings


def test_load_generation_settings_missing_file_returns_defaults():
    with tempfile.TemporaryDirectory() as tmp:
        project_folder = Path(tmp) / "proj1"
        loaded = load_load_generation_settings(project_folder)

    assert loaded.daily_variability_pct == 10.0
    assert loaded.timestep_variability_pct == 20.0
    assert loaded.random_seed == 42
    assert loaded.preserve_annual_energy is True


def test_load_generation_settings_file_path():
    assert load_generation_settings_file_path("project_x") == Path("project_x") / "load_generation.json"


def test_save_load_generation_settings_rejects_invalid_profiles():
    settings = LoadGenerationSettings(
        weekday_monthly_profiles_kw=[[1.0] * 24 for _ in range(11)],
        weekend_monthly_profiles_kw=[[1.0] * 24 for _ in range(12)],
    )

    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(ValueError, match="weekday_monthly_profiles_kw must contain exactly 12"):
            save_load_generation_settings(settings, Path(tmp) / "proj1")


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


def test_monthly_load_summary_reports_energy_and_load_metrics():
    timestamps = pd.to_datetime([
        "2025-01-31 22:00:00",
        "2025-01-31 23:00:00",
        "2025-02-01 00:00:00",
        "2025-02-01 01:00:00",
    ])
    df = pd.DataFrame({"timestamp": timestamps, "load_kw": [10.0, 30.0, 20.0, 40.0]})

    summary = monthly_load_summary(df)

    assert list(summary["month_name"]) == ["January", "February"]
    assert summary.loc[0, "energy_kwh"] == pytest.approx(40.0)
    assert summary.loc[0, "peak_kw"] == pytest.approx(30.0)
    assert summary.loc[0, "average_kw"] == pytest.approx(20.0)
    assert summary.loc[0, "min_kw"] == pytest.approx(10.0)
    assert summary.loc[1, "energy_kwh"] == pytest.approx(60.0)


def test_monthly_load_summary_uses_actual_timestep_for_energy():
    timestamps = pd.date_range("2025-01-01 00:00:00", periods=4, freq="30min")
    df = pd.DataFrame({"timestamp": timestamps, "load_kw": [100.0] * 4})

    summary = monthly_load_summary(df)

    assert summary.loc[0, "energy_kwh"] == pytest.approx(200.0)


def test_daily_load_summary_reports_energy_and_load_metrics():
    timestamps = pd.date_range("2025-01-01 00:00:00", periods=4, freq="h")
    df = pd.DataFrame({"timestamp": timestamps, "load_kw": [10.0, 20.0, 30.0, 40.0]})

    summary = daily_load_summary(df)

    assert len(summary) == 1
    assert str(summary.loc[0, "date"]) == "2025-01-01"
    assert summary.loc[0, "day_type"] == "Weekday"
    assert summary.loc[0, "energy_kwh"] == pytest.approx(100.0)
    assert summary.loc[0, "peak_kw"] == pytest.approx(40.0)
    assert summary.loc[0, "average_kw"] == pytest.approx(25.0)
    assert summary.loc[0, "min_kw"] == pytest.approx(10.0)


def test_daily_load_summary_uses_actual_timestep_for_energy():
    timestamps = pd.date_range("2025-01-01 00:00:00", periods=4, freq="30min")
    df = pd.DataFrame({"timestamp": timestamps, "load_kw": [100.0] * 4})

    summary = daily_load_summary(df)

    assert summary.loc[0, "energy_kwh"] == pytest.approx(200.0)


def test_load_duration_summary_sorts_descending_and_reports_percent_time():
    df = pd.DataFrame({"load_kw": [30.0, 10.0, 40.0, 20.0]})

    summary = load_duration_summary(df)

    assert list(summary["load_kw"]) == [40.0, 30.0, 20.0, 10.0]
    assert list(summary["rank"]) == [1, 2, 3, 4]
    assert summary.loc[0, "percent_of_time"] == pytest.approx(0.0)
    assert summary.loc[3, "percent_of_time"] == pytest.approx(100.0)


def test_load_quality_messages_pass_for_normal_load():
    df = make_valid_load_df()

    messages = load_quality_messages(df)

    assert messages[0].level == "success"
    assert "passed" in messages[0].message


def test_load_quality_messages_warn_for_zero_energy_and_zero_timesteps():
    df = make_valid_load_df()
    df["load_kw"] = 0.0

    messages = load_quality_messages(df)
    text = " ".join(m.message for m in messages)

    assert any(m.level == "warning" for m in messages)
    assert "Annual load energy is zero" in text
    assert "zero or near-zero" in text


def test_load_quality_messages_warn_for_high_peak_to_average_ratio():
    timestamps = pd.date_range("2025-01-01 00:00:00", periods=10, freq="h")
    df = pd.DataFrame({"timestamp": timestamps, "load_kw": [1.0] * 9 + [100.0]})

    messages = load_quality_messages(df)

    assert any("average load" in m.message for m in messages)


def test_load_quality_messages_note_unseeded_variability():
    df = make_valid_load_df()

    messages = load_quality_messages(
        df,
        variability_enabled=True,
        random_seed_enabled=False,
    )

    assert any("without a random seed" in m.message for m in messages)


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


def test_create_weekday_weekend_monthly_profile_load_uses_month_specific_hourly_values():
    weekday_profiles = [[10.0] * 24 for _ in range(12)]
    weekend_profiles = [[20.0] * 24 for _ in range(12)]
    weekday_profiles[0][8] = 111.0
    weekday_profiles[1][8] = 222.0
    weekend_profiles[0][8] = 333.0

    df = create_weekday_weekend_monthly_profile_load(
        weekday_monthly_profiles_kw=weekday_profiles,
        weekend_monthly_profiles_kw=weekend_profiles,
        year=2025,
    )

    jan_weekday = df.loc[df["timestamp"] == pd.Timestamp("2025-01-01 08:00:00")]
    jan_weekend = df.loc[df["timestamp"] == pd.Timestamp("2025-01-04 08:00:00")]
    feb_weekday = df.loc[df["timestamp"] == pd.Timestamp("2025-02-03 08:00:00")]

    assert float(jan_weekday["load_kw"].iloc[0]) == pytest.approx(111.0)
    assert float(jan_weekend["load_kw"].iloc[0]) == pytest.approx(333.0)
    assert float(feb_weekday["load_kw"].iloc[0]) == pytest.approx(222.0)


def test_create_weekday_weekend_monthly_profile_load_validates_month_count():
    with pytest.raises(ValueError, match="weekday_monthly_profiles_kw must contain exactly 12"):
        create_weekday_weekend_monthly_profile_load(
            weekday_monthly_profiles_kw=[[1.0] * 24 for _ in range(11)],
            weekend_monthly_profiles_kw=[[1.0] * 24 for _ in range(12)],
        )


def test_weekday_weekend_monthly_load_daily_variability_is_repeatable():
    kwargs = {
        "weekday_hourly_profile_kw": [100.0] * 24,
        "weekend_hourly_profile_kw": [100.0] * 24,
        "monthly_multipliers": [1.0] * 12,
        "year": 2025,
        "daily_variability_pct": 10.0,
        "random_seed": 123,
        "preserve_annual_energy": False,
    }

    first = create_weekday_weekend_monthly_load(**kwargs)
    second = create_weekday_weekend_monthly_load(**kwargs)

    pd.testing.assert_frame_equal(first, second)


def test_weekday_weekend_monthly_load_daily_variability_applies_one_multiplier_per_day():
    df = create_weekday_weekend_monthly_load(
        weekday_hourly_profile_kw=[100.0] * 24,
        weekend_hourly_profile_kw=[100.0] * 24,
        monthly_multipliers=[1.0] * 12,
        year=2025,
        daily_variability_pct=10.0,
        random_seed=123,
        preserve_annual_energy=False,
    )

    first_day = df.head(24)
    second_day = df.iloc[24:48]

    assert first_day["load_kw"].nunique() == 1
    assert second_day["load_kw"].nunique() == 1
    assert first_day["load_kw"].iloc[0] != pytest.approx(second_day["load_kw"].iloc[0])


def test_weekday_weekend_monthly_load_timestep_variability_changes_within_day():
    df = create_weekday_weekend_monthly_load(
        weekday_hourly_profile_kw=[100.0] * 24,
        weekend_hourly_profile_kw=[100.0] * 24,
        monthly_multipliers=[1.0] * 12,
        year=2025,
        timestep_variability_pct=10.0,
        random_seed=123,
        preserve_annual_energy=False,
    )

    first_day = df.head(24)

    assert first_day["load_kw"].nunique() > 1


def test_weekday_weekend_monthly_load_variability_can_preserve_annual_energy():
    baseline = create_weekday_weekend_monthly_load(
        weekday_hourly_profile_kw=[100.0] * 24,
        weekend_hourly_profile_kw=[80.0] * 24,
        monthly_multipliers=[1.0, 1.2, 0.9, 1.0, 1.1, 1.2, 1.3, 1.3, 1.1, 1.0, 0.9, 1.0],
        year=2025,
    )
    variable = create_weekday_weekend_monthly_load(
        weekday_hourly_profile_kw=[100.0] * 24,
        weekend_hourly_profile_kw=[80.0] * 24,
        monthly_multipliers=[1.0, 1.2, 0.9, 1.0, 1.1, 1.2, 1.3, 1.3, 1.1, 1.0, 0.9, 1.0],
        year=2025,
        daily_variability_pct=10.0,
        timestep_variability_pct=5.0,
        random_seed=123,
        preserve_annual_energy=True,
    )

    assert annual_energy_kwh(variable) == pytest.approx(annual_energy_kwh(baseline))


def test_weekday_weekend_monthly_load_rejects_negative_variability():
    with pytest.raises(ValueError, match="daily_variability_pct cannot be negative"):
        create_weekday_weekend_monthly_load(
            weekday_hourly_profile_kw=[1.0] * 24,
            weekend_hourly_profile_kw=[1.0] * 24,
            monthly_multipliers=[1.0] * 12,
            daily_variability_pct=-1.0,
        )
