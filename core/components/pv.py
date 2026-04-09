from __future__ import annotations

# ============================================================
# core/components/pv.py
#
# Purpose:
#   Define the PV component configuration only.
#
# Scope of this file:
#   1. PV advanced settings classes
#   2. Main PV component configuration
#   3. PV validation logic
#
# What is NOT included here:
#   - wind / battery / converter / grid
#   - project-level grouping
#   - save/load of components.json
#   - PV generation formulas
#
# Why:
#   This file should remain the single source of truth
#   for PV configuration only.
# ============================================================

from dataclasses import dataclass, field


# ============================================================
# SECTION 1 — PV ADVANCED SETTINGS CLASSES
# ============================================================

@dataclass(frozen=True)
class PVMPPTSettings:
    """
    Advanced MPPT settings for the PV component.

    Notes:
    - MPPT = Maximum Power Point Tracker
    - We keep this block in the model now for clean structure
      and future use, even if detailed MPPT simulation may
      come later.
    """

    enabled: bool = False
    lifetime_years: int = 15

    # Allowed values:
    #   "ratio"    -> use PV / converter ratio based sizing
    #   "capacity" -> use direct MPPT capacity sizing
    sizing_mode: str = "ratio"

    # Search-space options used when sizing_mode == "ratio"
    pv_to_conv_ratio_options: list[float] = field(default_factory=lambda: [1.0])

    # Search-space options used when sizing_mode == "capacity"
    capacity_kw_options: list[float] = field(default_factory=lambda: [1.0])

    efficiency_pct: float = 95.0
    use_efficiency_table: bool = False


@dataclass(frozen=True)
class PVOrientationSettings:
    """
    Advanced orientation settings for the PV component.

    These settings affect:
    - solar geometry
    - plane-of-array irradiance
    - energy yield
    """

    enabled: bool = True

    # Ground reflectance / albedo in percent
    ground_reflectance_pct: float = 20.0

    # Allowed values:
    #   "no_tracking"
    #   "single_axis"
    #   "dual_axis"
    tracking_system: str = "no_tracking"

    # If True, simulator may later infer default slope from site/location logic
    use_default_slope: bool = True
    panel_slope_deg: float | None = None

    # If True, simulator may later infer default azimuth from site/location logic
    use_default_azimuth: bool = True
    panel_azimuth_deg: float | None = None

    # Clearness index cap (HOMER-style GHI processing):
    # When True, G0 is computed using HOMER's EoT formula for each hour,
    # Kt = GHI / G0 is capped at kt_max, and effective GHI = Kt_capped × G0.
    # This removes physically impossible GHI values from NASA POWER data.
    # Requires project lat/lon to be passed into SimulationInputs.
    use_clearness_index_cap: bool = False
    kt_max: float = 0.82


@dataclass(frozen=True)
class PVTemperatureSettings:
    """
    Advanced temperature settings for the PV component.

    These settings affect:
    - temperature correction on PV output
    - cell operating temperature behavior
    """

    enabled: bool = True

    # Example: -0.5 means -0.5 % per degC
    temperature_coefficient_pct_per_degC: float = -0.5

    # NOCT = Nominal Operating Cell Temperature
    nominal_operating_cell_temp_c: float = 47.0

    # Efficiency at Standard Test Conditions
    efficiency_stc_pct: float = 13.0


# ============================================================
# SECTION 2 — MAIN PV COMPONENT CLASS
# ============================================================

@dataclass(frozen=True)
class PVComponentConfig:
    """
    Main PV component configuration.

    This is the full PV definition for a project.

    It contains:
    - basic PV settings
    - advanced PV settings blocks
    """

    # Whether PV is enabled in the project
    enabled: bool = True

    # Whether optimizer should use the search space
    # or a fixed single design value later
    use_search_space: bool = True

    # HOMER-like PV capacity search space (kW)
    # Example: [0, 1000, 2000, 3000, 4000]
    capacity_kw_options: list[float] = field(default_factory=lambda: [0.0, 1000.0])

    # Economic parameters
    capital_cost_per_kw: float = 2500.0
    replacement_cost_per_kw: float = 2500.0
    om_cost_per_kw_per_year: float = 10.0
    lifetime_years: int = 25

    # Performance parameter
    derating_factor: float = 0.80

    # Electrical bus for PV connection
    # Usually PV is DC-coupled, but AC is allowed for flexibility
    bus: str = "DC"

    # Advanced grouped settings
    mppt: PVMPPTSettings = field(default_factory=PVMPPTSettings)
    orientation: PVOrientationSettings = field(default_factory=PVOrientationSettings)
    temperature: PVTemperatureSettings = field(default_factory=PVTemperatureSettings)


# ============================================================
# SECTION 3 — VALIDATION FUNCTIONS
# ============================================================

def _validate_non_negative_list(values: list[float], name: str) -> None:
    """
    Ensure a list is not empty and contains only non-negative values.
    """
    if not values:
        raise ValueError(f"{name} cannot be empty")

    for v in values:
        if v < 0:
            raise ValueError(f"{name} cannot contain negative values")


def validate_pv_mppt_settings(mppt: PVMPPTSettings) -> None:
    """
    Validate PV MPPT settings.
    """
    if mppt.lifetime_years <= 0:
        raise ValueError("PV MPPT lifetime_years must be > 0")

    if mppt.sizing_mode not in {"ratio", "capacity"}:
        raise ValueError("PV MPPT sizing_mode must be 'ratio' or 'capacity'")

    _validate_non_negative_list(
        mppt.pv_to_conv_ratio_options,
        "PV MPPT pv_to_conv_ratio_options",
    )
    _validate_non_negative_list(
        mppt.capacity_kw_options,
        "PV MPPT capacity_kw_options",
    )

    if not (0 < mppt.efficiency_pct <= 100):
        raise ValueError("PV MPPT efficiency_pct must be between 0 and 100")


def validate_pv_orientation_settings(orientation: PVOrientationSettings) -> None:
    """
    Validate PV orientation settings.
    """
    if not (0 <= orientation.ground_reflectance_pct <= 100):
        raise ValueError("PV ground_reflectance_pct must be between 0 and 100")

    if orientation.tracking_system not in {"no_tracking", "single_axis", "dual_axis"}:
        raise ValueError(
            "PV tracking_system must be one of: no_tracking, single_axis, dual_axis"
        )

    if not orientation.use_default_slope:
        if orientation.panel_slope_deg is None:
            raise ValueError(
                "PV panel_slope_deg is required when use_default_slope is False"
            )
        if not (0 <= orientation.panel_slope_deg <= 90):
            raise ValueError("PV panel_slope_deg must be between 0 and 90")

    if not orientation.use_default_azimuth:
        if orientation.panel_azimuth_deg is None:
            raise ValueError(
                "PV panel_azimuth_deg is required when use_default_azimuth is False"
            )
        if not (-180 <= orientation.panel_azimuth_deg <= 180):
            raise ValueError("PV panel_azimuth_deg must be between -180 and 180")


def validate_pv_temperature_settings(temp: PVTemperatureSettings) -> None:
    """
    Validate PV temperature settings.
    """
    if not (-5.0 <= temp.temperature_coefficient_pct_per_degC <= 1.0):
        raise ValueError("PV temperature_coefficient_pct_per_degC looks unrealistic")

    if temp.nominal_operating_cell_temp_c <= 0:
        raise ValueError("PV nominal_operating_cell_temp_c must be > 0")

    if not (0 < temp.efficiency_stc_pct <= 100):
        raise ValueError("PV efficiency_stc_pct must be between 0 and 100")


def validate_pv_component(pv: PVComponentConfig) -> None:
    """
    Validate the full PV component configuration.
    """
    _validate_non_negative_list(pv.capacity_kw_options, "PV capacity_kw_options")

    if pv.capital_cost_per_kw < 0:
        raise ValueError("PV capital_cost_per_kw cannot be negative")

    if pv.replacement_cost_per_kw < 0:
        raise ValueError("PV replacement_cost_per_kw cannot be negative")

    if pv.om_cost_per_kw_per_year < 0:
        raise ValueError("PV om_cost_per_kw_per_year cannot be negative")

    if pv.lifetime_years <= 0:
        raise ValueError("PV lifetime_years must be > 0")

    if not (0 < pv.derating_factor <= 1):
        raise ValueError("PV derating_factor must be between 0 and 1")

    if pv.bus not in {"AC", "DC"}:
        raise ValueError("PV bus must be 'AC' or 'DC'")

    validate_pv_mppt_settings(pv.mppt)
    validate_pv_orientation_settings(pv.orientation)
    validate_pv_temperature_settings(pv.temperature)