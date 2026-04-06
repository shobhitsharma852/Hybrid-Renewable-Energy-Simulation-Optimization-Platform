from __future__ import annotations

# ============================================================
# core/components/wind.py
#
# Purpose:
#   Define the Wind Turbine component configuration only.
#
# Scope of this file:
#   1. Wind advanced settings classes
#   2. Main wind component configuration
#   3. Wind validation logic
#
# What is NOT included here:
#   - PV / battery / converter / grid
#   - project-level grouping
#   - save/load of components.json
#   - wind generation simulation formulas
#
# Why:
#   This file should remain the single source of truth
#   for Wind component configuration only.
# ============================================================

from dataclasses import dataclass, field


# ============================================================
# SECTION 1 — WIND ADVANCED SETTINGS CLASSES
# ============================================================

@dataclass(frozen=True)
class WindPowerCurveSettings:
    """
    Advanced power-curve settings for the wind component.

    This table defines how turbine power output changes with wind speed.

    Example:
        wind speed (m/s) -> power output (kW)
        0  -> 0
        4  -> 0
        5  -> 150
        ...
        14 -> 1500
        25 -> 0
    """

    enabled: bool = True

    # X-axis points: wind speed in m/s
    wind_speed_points_mps: list[float] = field(
        default_factory=lambda: [
            0.0, 4.0, 4.01, 5.0, 6.0, 7.0, 8.0, 9.0,
            10.0, 11.0, 12.0, 13.0, 14.0, 16.0, 25.0
        ]
    )

    # Y-axis points: output power in kW
    power_output_points_kw: list[float] = field(
        default_factory=lambda: [
            0.0, 0.0, 80.0, 150.0, 250.0, 400.0, 600.0, 850.0,
            1150.0, 1350.0, 1450.0, 1490.0, 1500.0, 1500.0, 0.0
        ]
    )


@dataclass(frozen=True)
class WindLossSettings:
    """
    Advanced wind loss settings.

    HOMER exposes these losses separately, and they combine
    multiplicatively in the real system.
    """

    enabled: bool = True

    availability_losses_pct: float = 0.0
    turbine_performance_losses_pct: float = 0.0
    environmental_losses_pct: float = 0.0
    other_losses_pct: float = 0.0
    wake_effects_losses_pct: float = 0.0
    electrical_losses_pct: float = 0.0
    curtailment_losses_pct: float = 0.0


@dataclass(frozen=True)
class WindMaintenanceSettings:
    """
    Advanced wind maintenance settings.

    For Phase 1, we only keep the enabled flag.
    A detailed maintenance table can be added later.
    """

    enabled: bool = False


# ============================================================
# SECTION 2 — MAIN WIND COMPONENT CLASS
# ============================================================

@dataclass(frozen=True)
class WindComponentConfig:
    """
    Main wind component configuration.

    This is the full wind turbine definition for a project.

    It contains:
    - basic wind settings
    - advanced wind settings blocks
    """

    # Whether wind is enabled in the project
    enabled: bool = True

    # Whether optimizer should use quantity search space
    use_search_space: bool = True

    # Turbine model name shown in UI / reports
    turbine_model_name: str = "Generic 1.5 MW"

    # Nameplate / rated power of one turbine
    rated_capacity_kw: float = 1500.0

    # Search space in number of turbines
    # Example: [0, 1, 2, 3, 4]
    quantity_options: list[int] = field(default_factory=lambda: [0, 1])

    # Economic parameters per turbine
    capital_cost_per_turbine: float = 3_000_000.0
    replacement_cost_per_turbine: float = 3_000_000.0
    om_cost_per_turbine_per_year: float = 30_000.0

    # Basic site-specific parameters
    lifetime_years: int = 20
    hub_height_m: float = 80.0
    consider_temperature_effects: bool = False

    # Electrical connection bus
    bus: str = "AC"

    # Advanced grouped settings
    power_curve: WindPowerCurveSettings = field(default_factory=WindPowerCurveSettings)
    losses: WindLossSettings = field(default_factory=WindLossSettings)
    maintenance: WindMaintenanceSettings = field(default_factory=WindMaintenanceSettings)


# ============================================================
# SECTION 3 — VALIDATION FUNCTIONS
# ============================================================

def _validate_non_negative_float_list(values: list[float], name: str) -> None:
    """
    Ensure a float list is not empty and contains only non-negative values.
    """
    if not values:
        raise ValueError(f"{name} cannot be empty")

    for v in values:
        if v < 0:
            raise ValueError(f"{name} cannot contain negative values")


def _validate_non_negative_int_list(values: list[int], name: str) -> None:
    """
    Ensure an integer list is not empty and contains only non-negative values.
    """
    if not values:
        raise ValueError(f"{name} cannot be empty")

    for v in values:
        if v < 0:
            raise ValueError(f"{name} cannot contain negative values")


def validate_wind_power_curve_settings(power_curve: WindPowerCurveSettings) -> None:
    """
    Validate wind power curve settings.
    """
    _validate_non_negative_float_list(
        power_curve.wind_speed_points_mps,
        "Wind power_curve wind_speed_points_mps",
    )
    _validate_non_negative_float_list(
        power_curve.power_output_points_kw,
        "Wind power_curve power_output_points_kw",
    )

    if len(power_curve.wind_speed_points_mps) != len(power_curve.power_output_points_kw):
        raise ValueError(
            "Wind power curve wind_speed_points_mps and power_output_points_kw "
            "must have the same length"
        )

    # Wind speed points should be non-decreasing
    for i in range(1, len(power_curve.wind_speed_points_mps)):
        if power_curve.wind_speed_points_mps[i] < power_curve.wind_speed_points_mps[i - 1]:
            raise ValueError("Wind power curve wind_speed_points_mps must be non-decreasing")


def validate_wind_loss_settings(losses: WindLossSettings) -> None:
    """
    Validate wind loss settings.
    """
    loss_values = [
        losses.availability_losses_pct,
        losses.turbine_performance_losses_pct,
        losses.environmental_losses_pct,
        losses.other_losses_pct,
        losses.wake_effects_losses_pct,
        losses.electrical_losses_pct,
        losses.curtailment_losses_pct,
    ]

    for value in loss_values:
        if not (0 <= value <= 100):
            raise ValueError("All wind loss percentages must be between 0 and 100")


def validate_wind_maintenance_settings(_maintenance: WindMaintenanceSettings) -> None:
    """
    Validate wind maintenance settings.

    Phase 1:
    - only enabled flag exists
    - no extra validation needed yet
    """
    return None


def validate_wind_component(wind: WindComponentConfig) -> None:
    """
    Validate the full wind component configuration.
    """
    if not wind.turbine_model_name.strip():
        raise ValueError("Wind turbine_model_name cannot be empty")

    if wind.rated_capacity_kw <= 0:
        raise ValueError("Wind rated_capacity_kw must be > 0")

    _validate_non_negative_int_list(wind.quantity_options, "Wind quantity_options")

    if wind.capital_cost_per_turbine < 0:
        raise ValueError("Wind capital_cost_per_turbine cannot be negative")

    if wind.replacement_cost_per_turbine < 0:
        raise ValueError("Wind replacement_cost_per_turbine cannot be negative")

    if wind.om_cost_per_turbine_per_year < 0:
        raise ValueError("Wind om_cost_per_turbine_per_year cannot be negative")

    if wind.lifetime_years <= 0:
        raise ValueError("Wind lifetime_years must be > 0")

    if wind.hub_height_m <= 0:
        raise ValueError("Wind hub_height_m must be > 0")

    if wind.bus not in {"AC", "DC"}:
        raise ValueError("Wind bus must be 'AC' or 'DC'")

    validate_wind_power_curve_settings(wind.power_curve)
    validate_wind_loss_settings(wind.losses)
    validate_wind_maintenance_settings(wind.maintenance)