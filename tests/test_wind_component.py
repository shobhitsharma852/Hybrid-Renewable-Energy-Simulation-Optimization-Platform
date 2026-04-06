import pytest

from core.components.wind import (
    WindPowerCurveSettings,
    WindLossSettings,
    WindMaintenanceSettings,
    WindComponentConfig,
    validate_wind_component,
)


# ============================================================
# HELPERS
# ============================================================

def make_valid_wind() -> WindComponentConfig:
    return WindComponentConfig(
        enabled=True,
        use_search_space=True,
        turbine_model_name="Generic 1.5 MW",
        rated_capacity_kw=1500.0,
        quantity_options=[0, 1, 2, 3, 4],
        capital_cost_per_turbine=3_000_000.0,
        replacement_cost_per_turbine=3_000_000.0,
        om_cost_per_turbine_per_year=30_000.0,
        lifetime_years=20,
        hub_height_m=80.0,
        consider_temperature_effects=False,
        bus="AC",
        power_curve=WindPowerCurveSettings(
            enabled=True,
            wind_speed_points_mps=[
                0.0, 4.0, 4.01, 5.0, 6.0, 7.0, 8.0, 9.0,
                10.0, 11.0, 12.0, 13.0, 14.0, 16.0, 25.0
            ],
            power_output_points_kw=[
                0.0, 0.0, 80.0, 150.0, 250.0, 400.0, 600.0, 850.0,
                1150.0, 1350.0, 1450.0, 1490.0, 1500.0, 1500.0, 0.0
            ],
        ),
        losses=WindLossSettings(
            enabled=True,
            availability_losses_pct=0.0,
            turbine_performance_losses_pct=0.0,
            environmental_losses_pct=0.0,
            other_losses_pct=0.0,
            wake_effects_losses_pct=0.0,
            electrical_losses_pct=0.0,
            curtailment_losses_pct=0.0,
        ),
        maintenance=WindMaintenanceSettings(
            enabled=False,
        ),
    )


# ============================================================
# MAIN SUCCESS TEST
# ============================================================

def test_validate_wind_component_passes_for_valid_data():
    wind = make_valid_wind()
    validate_wind_component(wind)


# ============================================================
# BASIC WIND TESTS
# ============================================================

def test_validate_wind_component_fails_if_name_empty():
    wind = make_valid_wind()
    wind = WindComponentConfig(**{**wind.__dict__, "turbine_model_name": ""})

    with pytest.raises(ValueError, match="Wind turbine_model_name cannot be empty"):
        validate_wind_component(wind)


def test_validate_wind_component_fails_if_rated_capacity_invalid():
    wind = make_valid_wind()
    wind = WindComponentConfig(**{**wind.__dict__, "rated_capacity_kw": 0.0})

    with pytest.raises(ValueError, match="Wind rated_capacity_kw must be > 0"):
        validate_wind_component(wind)


def test_validate_wind_component_fails_if_quantity_options_empty():
    wind = make_valid_wind()
    wind = WindComponentConfig(**{**wind.__dict__, "quantity_options": []})

    with pytest.raises(ValueError, match="Wind quantity_options cannot be empty"):
        validate_wind_component(wind)


def test_validate_wind_component_fails_if_quantity_options_negative():
    wind = make_valid_wind()
    wind = WindComponentConfig(**{**wind.__dict__, "quantity_options": [0, 1, -2]})

    with pytest.raises(ValueError, match="Wind quantity_options cannot contain negative values"):
        validate_wind_component(wind)


def test_validate_wind_component_fails_if_capital_cost_negative():
    wind = make_valid_wind()
    wind = WindComponentConfig(**{**wind.__dict__, "capital_cost_per_turbine": -1.0})

    with pytest.raises(ValueError, match="Wind capital_cost_per_turbine cannot be negative"):
        validate_wind_component(wind)


def test_validate_wind_component_fails_if_replacement_cost_negative():
    wind = make_valid_wind()
    wind = WindComponentConfig(**{**wind.__dict__, "replacement_cost_per_turbine": -1.0})

    with pytest.raises(ValueError, match="Wind replacement_cost_per_turbine cannot be negative"):
        validate_wind_component(wind)


def test_validate_wind_component_fails_if_om_cost_negative():
    wind = make_valid_wind()
    wind = WindComponentConfig(**{**wind.__dict__, "om_cost_per_turbine_per_year": -1.0})

    with pytest.raises(ValueError, match="Wind om_cost_per_turbine_per_year cannot be negative"):
        validate_wind_component(wind)


def test_validate_wind_component_fails_if_lifetime_invalid():
    wind = make_valid_wind()
    wind = WindComponentConfig(**{**wind.__dict__, "lifetime_years": 0})

    with pytest.raises(ValueError, match="Wind lifetime_years must be > 0"):
        validate_wind_component(wind)


def test_validate_wind_component_fails_if_hub_height_invalid():
    wind = make_valid_wind()
    wind = WindComponentConfig(**{**wind.__dict__, "hub_height_m": 0.0})

    with pytest.raises(ValueError, match="Wind hub_height_m must be > 0"):
        validate_wind_component(wind)


def test_validate_wind_component_fails_if_bus_invalid():
    wind = make_valid_wind()
    wind = WindComponentConfig(**{**wind.__dict__, "bus": "XYZ"})

    with pytest.raises(ValueError, match="Wind bus must be 'AC' or 'DC'"):
        validate_wind_component(wind)


# ============================================================
# POWER CURVE TESTS
# ============================================================

def test_validate_wind_component_fails_if_power_curve_lengths_mismatch():
    wind = make_valid_wind()

    bad_power_curve = WindPowerCurveSettings(
        enabled=True,
        wind_speed_points_mps=[0.0, 4.0, 5.0],
        power_output_points_kw=[0.0, 0.0],
    )

    wind = WindComponentConfig(**{**wind.__dict__, "power_curve": bad_power_curve})

    with pytest.raises(
        ValueError,
        match="Wind power curve wind_speed_points_mps and power_output_points_kw must have the same length",
    ):
        validate_wind_component(wind)


def test_validate_wind_component_fails_if_power_curve_wind_speeds_decreasing():
    wind = make_valid_wind()

    bad_power_curve = WindPowerCurveSettings(
        enabled=True,
        wind_speed_points_mps=[0.0, 5.0, 4.0],
        power_output_points_kw=[0.0, 100.0, 200.0],
    )

    wind = WindComponentConfig(**{**wind.__dict__, "power_curve": bad_power_curve})

    with pytest.raises(ValueError, match="Wind power curve wind_speed_points_mps must be non-decreasing"):
        validate_wind_component(wind)


def test_validate_wind_component_fails_if_power_curve_has_negative_speed():
    wind = make_valid_wind()

    bad_power_curve = WindPowerCurveSettings(
        enabled=True,
        wind_speed_points_mps=[0.0, -1.0, 5.0],
        power_output_points_kw=[0.0, 10.0, 100.0],
    )

    wind = WindComponentConfig(**{**wind.__dict__, "power_curve": bad_power_curve})

    with pytest.raises(ValueError, match="Wind power_curve wind_speed_points_mps cannot contain negative values"):
        validate_wind_component(wind)


def test_validate_wind_component_fails_if_power_curve_has_negative_output():
    wind = make_valid_wind()

    bad_power_curve = WindPowerCurveSettings(
        enabled=True,
        wind_speed_points_mps=[0.0, 4.0, 5.0],
        power_output_points_kw=[0.0, -10.0, 100.0],
    )

    wind = WindComponentConfig(**{**wind.__dict__, "power_curve": bad_power_curve})

    with pytest.raises(ValueError, match="Wind power_curve power_output_points_kw cannot contain negative values"):
        validate_wind_component(wind)


# ============================================================
# LOSS TESTS
# ============================================================

def test_validate_wind_component_fails_if_loss_below_zero():
    wind = make_valid_wind()

    bad_losses = WindLossSettings(
        enabled=True,
        availability_losses_pct=-1.0,
        turbine_performance_losses_pct=0.0,
        environmental_losses_pct=0.0,
        other_losses_pct=0.0,
        wake_effects_losses_pct=0.0,
        electrical_losses_pct=0.0,
        curtailment_losses_pct=0.0,
    )

    wind = WindComponentConfig(**{**wind.__dict__, "losses": bad_losses})

    with pytest.raises(ValueError, match="All wind loss percentages must be between 0 and 100"):
        validate_wind_component(wind)


def test_validate_wind_component_fails_if_loss_above_hundred():
    wind = make_valid_wind()

    bad_losses = WindLossSettings(
        enabled=True,
        availability_losses_pct=0.0,
        turbine_performance_losses_pct=101.0,
        environmental_losses_pct=0.0,
        other_losses_pct=0.0,
        wake_effects_losses_pct=0.0,
        electrical_losses_pct=0.0,
        curtailment_losses_pct=0.0,
    )

    wind = WindComponentConfig(**{**wind.__dict__, "losses": bad_losses})

    with pytest.raises(ValueError, match="All wind loss percentages must be between 0 and 100"):
        validate_wind_component(wind)