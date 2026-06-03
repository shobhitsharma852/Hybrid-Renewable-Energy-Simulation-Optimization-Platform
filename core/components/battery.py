from __future__ import annotations

# ============================================================
# core/components/battery.py
#
# Purpose:
#   Define the Battery / Storage component configuration only.
#
# Scope of this file:
#   1. Main battery component configuration
#   2. Battery validation logic
#
# What is NOT included here:
#   - PV / wind / converter / grid
#   - project-level grouping
#   - save/load of components.json
#   - battery dispatch / SOC simulation formulas
#
# Why:
#   This file should remain the single source of truth
#   for Battery component configuration only.
# ============================================================

from dataclasses import dataclass, field


# ============================================================
# SECTION 1 — MAIN BATTERY COMPONENT CLASS
# ============================================================

@dataclass(frozen=True)
class BatteryComponentConfig:
    """
    Main battery / storage component configuration.

    This is the full battery definition for a project.

    Design choice for Version 1:
    - Keep battery configuration flat
    - Do NOT split into advanced settings yet
    - Store all important technical, economic, and sizing fields here

    Notes:
    - Search space is based on number of strings, similar to HOMER
    - Total battery energy can later be computed as:
          nominal_capacity_kwh_per_string * quantity
    """

    # --------------------------------------------------------
    # BASIC ENABLE / SEARCH SPACE SETTINGS
    # --------------------------------------------------------

    # Whether battery is enabled in the project
    enabled: bool = True

    # Whether optimizer should use the quantity search space
    use_search_space: bool = True

    # Battery model name shown in UI / reports
    battery_model_name: str = "Generic 1MWh Li-Ion"

    # Search space in number of battery strings
    # Example: [0, 5, 10, 15, 20]
    quantity_options: list[int] = field(default_factory=lambda: [0, 5, 10])

    # --------------------------------------------------------
    # TECHNICAL PARAMETERS
    # --------------------------------------------------------

    # Nominal battery voltage (V)
    nominal_voltage_v: float = 600.0

    # Nominal energy capacity of one string (kWh)
    nominal_capacity_kwh_per_string: float = 1000.0

    # Roundtrip efficiency (%)
    roundtrip_efficiency_pct: float = 90.0

    # Maximum charge current of one string (A)
    max_charge_current_a: float = 1670.0

    # Maximum discharge current of one string (A)
    max_discharge_current_a: float = 5000.0

    # String size multiplier shown in HOMER-like UI
    string_size: int = 1

    # Initial state of charge (%)
    initial_state_of_charge_pct: float = 100.0

    # Minimum state of charge (%)
    minimum_state_of_charge_pct: float = 20.0

    # Lifetime throughput (kWh)
    throughput_kwh: float = 3_000_000.0

    # Self-discharge rate (% of stored energy lost per day when idle).
    # Li-Ion typical: 0.05–0.1 %/day.  Lead-acid typical: 0.1–0.3 %/day.
    # Reference: HOMER Pro Battery → Self-Discharge Rate parameter.
    self_discharge_rate_pct_per_day: float = 0.05

    # --------------------------------------------------------
    # CAPACITY FADE PARAMETERS
    # --------------------------------------------------------

    # How much capacity the battery is allowed to lose before it is replaced (%).
    # This matches HOMER Pro's "Replacement degradation limit (%)" field exactly.
    # A value of 20 means: replace when battery retains only 80% of its original
    # capacity — i.e. State of Health has fallen to 80%.
    #
    # The simulator derives the per-EFC fade rate internally from this value and
    # throughput_kwh so the user never needs to calculate %/EFC directly:
    #
    #   EFC_to_EOL            = throughput_kwh / (2 x nominal_capacity_kwh_per_string)
    #   capacity_fade_pct/EFC = replacement_degradation_limit_pct / EFC_to_EOL
    #
    # Calendar aging (time-based) is handled by the replacement logic in the
    # economics evaluator via lifetime_years.  To avoid double-counting, the
    # simulator combines cycle and calendar fade with max() rather than addition —
    # matching HOMER Pro's rule: "EOL by calendar or cycling, whichever is greater."
    #
    # Typical values:
    #   Li-Ion NMC / NCA:  20 %  (replace at 80% SoH — IEC 62619:2022 standard)
    #   LiFePO4:           20-30 % (flatter fade curve; some specs allow 70% SoH)
    #   Lead-acid:         20-40 % (more aggressive degradation)
    #
    # References: IEC 62619:2022; HOMER Pro "Replacement degradation limit (%)" field;
    #             Schmalstieg et al. (2014) J. Power Sources 309:86-95.
    replacement_degradation_limit_pct: float = 20.0

    # --------------------------------------------------------
    # ECONOMIC PARAMETERS
    # --------------------------------------------------------

    # Capital cost per string
    capital_cost_per_string: float = 700_000.0

    # Replacement cost per string
    replacement_cost_per_string: float = 700_000.0

    # O&M cost per string per year
    om_cost_per_string_per_year: float = 10_000.0

    # Lifetime in years
    lifetime_years: int = 15


# ============================================================
# SECTION 2 — VALIDATION HELPERS
# ============================================================

def _validate_non_negative_int_list(values: list[int], name: str) -> None:
    """
    Ensure an integer list is not empty and contains only non-negative values.
    """
    if not values:
        raise ValueError(f"{name} cannot be empty")

    for v in values:
        if v < 0:
            raise ValueError(f"{name} cannot contain negative values")


# ============================================================
# SECTION 3 — MAIN VALIDATION FUNCTION
# ============================================================

def validate_battery_component(battery: BatteryComponentConfig) -> None:
    """
    Validate the full battery component configuration.

    Raises:
        ValueError: if any configuration value is invalid
    """

    # --------------------------------------------------------
    # MODEL NAME
    # --------------------------------------------------------
    if not battery.battery_model_name.strip():
        raise ValueError("Battery battery_model_name cannot be empty")

    # --------------------------------------------------------
    # SEARCH SPACE / QUANTITY
    # --------------------------------------------------------
    _validate_non_negative_int_list(
        battery.quantity_options,
        "Battery quantity_options",
    )

    # --------------------------------------------------------
    # TECHNICAL PARAMETERS
    # --------------------------------------------------------
    if battery.nominal_voltage_v <= 0:
        raise ValueError("Battery nominal_voltage_v must be > 0")

    if battery.nominal_capacity_kwh_per_string <= 0:
        raise ValueError("Battery nominal_capacity_kwh_per_string must be > 0")

    if not (0 < battery.roundtrip_efficiency_pct <= 100):
        raise ValueError("Battery roundtrip_efficiency_pct must be between 0 and 100")

    if battery.max_charge_current_a <= 0:
        raise ValueError("Battery max_charge_current_a must be > 0")

    if battery.max_discharge_current_a <= 0:
        raise ValueError("Battery max_discharge_current_a must be > 0")

    if battery.string_size <= 0:
        raise ValueError("Battery string_size must be > 0")

    if not (0 <= battery.initial_state_of_charge_pct <= 100):
        raise ValueError("Battery initial_state_of_charge_pct must be between 0 and 100")

    if not (0 <= battery.minimum_state_of_charge_pct <= 100):
        raise ValueError("Battery minimum_state_of_charge_pct must be between 0 and 100")

    if battery.initial_state_of_charge_pct < battery.minimum_state_of_charge_pct:
        raise ValueError(
            "Battery initial_state_of_charge_pct must be >= minimum_state_of_charge_pct"
        )

    if battery.throughput_kwh < 0:
        raise ValueError("Battery throughput_kwh cannot be negative")

    if not (0.0 <= battery.self_discharge_rate_pct_per_day <= 100.0):
        raise ValueError("Battery self_discharge_rate_pct_per_day must be between 0 and 100")

    # Must be strictly less than 100 (a 100% degradation limit makes no physical sense)
    # and >= 0 (0 = degradation not modelled, no capacity fade applied).
    if not (0.0 <= battery.replacement_degradation_limit_pct < 100.0):
        raise ValueError(
            "Battery replacement_degradation_limit_pct must be >= 0 and < 100"
        )

    # --------------------------------------------------------
    # ECONOMIC PARAMETERS
    # --------------------------------------------------------
    if battery.capital_cost_per_string < 0:
        raise ValueError("Battery capital_cost_per_string cannot be negative")

    if battery.replacement_cost_per_string < 0:
        raise ValueError("Battery replacement_cost_per_string cannot be negative")

    if battery.om_cost_per_string_per_year < 0:
        raise ValueError("Battery om_cost_per_string_per_year cannot be negative")

    if battery.lifetime_years <= 0:
        raise ValueError("Battery lifetime_years must be > 0")