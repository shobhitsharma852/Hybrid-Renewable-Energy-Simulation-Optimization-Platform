from __future__ import annotations

import pandas as pd
import pytest

from core.components.pv import PVComponentConfig, PVTemperatureSettings
from core.simulation.pv_model import (
    compute_cell_temperature_c,
    compute_pv_power_for_timestep,
    compute_pv_power_from_resource_row,
    simulate_pv_timeseries,
)


def make_pv_config(
    *,
    enabled: bool = True,
    derating_factor: float = 0.95,
    temp_coeff_pct_per_degC: float = -0.4,
    noct_c: float = 45.0,
    temp_enabled: bool = True,
) -> PVComponentConfig:
    return PVComponentConfig(
        enabled=enabled,
        capacity_kw_options=[100.0],
        derating_factor=derating_factor,
        temperature=PVTemperatureSettings(
            enabled=temp_enabled,
            temperature_coefficient_pct_per_degC=temp_coeff_pct_per_degC,
            nominal_operating_cell_temp_c=noct_c,
        ),
    )


def test_compute_cell_temperature_increases_with_irradiance() -> None:
    tc_low = compute_cell_temperature_c(
        ambient_temperature_c=25.0,
        irradiance_kw_per_m2=0.2,
        nominal_operating_cell_temp_c=45.0,
    )
    tc_high = compute_cell_temperature_c(
        ambient_temperature_c=25.0,
        irradiance_kw_per_m2=1.0,
        nominal_operating_cell_temp_c=45.0,
    )

    assert tc_high > tc_low
    assert tc_low >= 25.0


def test_zero_irradiance_gives_zero_power() -> None:
    pv = make_pv_config()

    result = compute_pv_power_for_timestep(
        irradiance_input_value=0.0,
        ambient_temperature_c=25.0,
        pv_config=pv,
        selected_capacity_kw=100.0,
    )

    assert result.net_power_kw == pytest.approx(0.0, abs=1e-9)


def test_higher_irradiance_gives_higher_power() -> None:
    pv = make_pv_config()

    low_result = compute_pv_power_for_timestep(
        irradiance_input_value=300.0,
        ambient_temperature_c=25.0,
        pv_config=pv,
        selected_capacity_kw=100.0,
    )
    high_result = compute_pv_power_for_timestep(
        irradiance_input_value=900.0,
        ambient_temperature_c=25.0,
        pv_config=pv,
        selected_capacity_kw=100.0,
    )

    assert high_result.net_power_kw > low_result.net_power_kw


def test_higher_temperature_reduces_power_when_temp_enabled() -> None:
    pv = make_pv_config(temp_enabled=True, temp_coeff_pct_per_degC=-0.4)

    cool_result = compute_pv_power_for_timestep(
        irradiance_input_value=1000.0,
        ambient_temperature_c=20.0,
        pv_config=pv,
        selected_capacity_kw=100.0,
    )
    hot_result = compute_pv_power_for_timestep(
        irradiance_input_value=1000.0,
        ambient_temperature_c=40.0,
        pv_config=pv,
        selected_capacity_kw=100.0,
    )

    assert hot_result.cell_temperature_c > cool_result.cell_temperature_c
    assert hot_result.net_power_kw < cool_result.net_power_kw


def test_temperature_disabled_ignores_temperature_penalty() -> None:
    pv = make_pv_config(temp_enabled=False, temp_coeff_pct_per_degC=-0.4)

    cool_result = compute_pv_power_for_timestep(
        irradiance_input_value=1000.0,
        ambient_temperature_c=20.0,
        pv_config=pv,
        selected_capacity_kw=100.0,
    )
    hot_result = compute_pv_power_for_timestep(
        irradiance_input_value=1000.0,
        ambient_temperature_c=40.0,
        pv_config=pv,
        selected_capacity_kw=100.0,
    )

    assert cool_result.temperature_correction_factor == pytest.approx(1.0)
    assert hot_result.temperature_correction_factor == pytest.approx(1.0)
    assert hot_result.net_power_kw == pytest.approx(cool_result.net_power_kw, rel=1e-9)


def test_disabled_pv_returns_zero_output() -> None:
    pv = make_pv_config(enabled=False)

    result = compute_pv_power_for_timestep(
        irradiance_input_value=1000.0,
        ambient_temperature_c=25.0,
        pv_config=pv,
        selected_capacity_kw=100.0,
    )

    assert result.net_power_kw == pytest.approx(0.0)
    assert result.rated_capacity_kw == pytest.approx(0.0)


def test_w_per_m2_input_is_normalized_to_kw_per_m2() -> None:
    pv = make_pv_config()

    result_w = compute_pv_power_for_timestep(
        irradiance_input_value=1000.0,  # 1000 W/m²
        ambient_temperature_c=25.0,
        pv_config=pv,
        selected_capacity_kw=100.0,
    )

    assert result_w.irradiance_used_kw_per_m2 == pytest.approx(1.0)
    assert result_w.net_power_kw > 0.0


def test_compute_pv_power_from_resource_row() -> None:
    pv = make_pv_config()

    row = pd.Series(
        {
            "ghi": 800.0,
            "temperature_c": 30.0,
        }
    )

    result = compute_pv_power_from_resource_row(
        resource_row=row,
        pv_config=pv,
        selected_capacity_kw=100.0,
    )

    assert result.irradiance_used_kw_per_m2 == pytest.approx(0.8)
    assert result.ambient_temperature_c == pytest.approx(30.0)
    assert result.net_power_kw > 0.0


def test_simulate_pv_timeseries_returns_expected_shape_and_columns() -> None:
    pv = make_pv_config()

    df = pd.DataFrame(
        {
            "timestamp": pd.date_range("2025-01-01 00:00:00", periods=3, freq="h"),
            "ghi": [0.0, 500.0, 1000.0],
            "temperature_c": [20.0, 25.0, 30.0],
        }
    )

    out = simulate_pv_timeseries(
        resource_df=df,
        pv_config=pv,
        selected_capacity_kw=100.0,
    )

    expected_cols = {
        "timestamp",
        "irradiance_input_value",
        "irradiance_used_kw_per_m2",
        "ambient_temperature_c",
        "cell_temperature_c",
        "temperature_correction_factor",
        "pv_power_kw",
    }

    assert len(out) == 3
    assert expected_cols.issubset(set(out.columns))
    assert out.loc[0, "pv_power_kw"] == pytest.approx(0.0)
    assert out.loc[2, "pv_power_kw"] > out.loc[1, "pv_power_kw"]
