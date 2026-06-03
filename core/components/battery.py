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

    # Fraction of rated capacity lost per Equivalent Full Cycle (EFC).
    # EFC = cumulative_throughput_kwh / (2 × nominal_capacity_kwh_per_string × n_strings).
    # One EFC = one full charge PLUS one full discharge of nominal capacity;
    # the factor of 2 in the denominator converts total throughput to full cycles.
    #
    # Typical values (linear approximation to 80% SoH EOL):
    #   Li-Ion NMC:  0.0033–0.0067 %/EFC  →  80% SoH at 3,000–6,000 EFC
    #   LiFePO4:     0.0010–0.0020 %/EFC  →  80% SoH at 10,000–20,000 EFC
    #   Lead-acid:   0.050–0.100  %/EFC   →  80% SoH at 200–400 EFC
    #
    # Set to 0.0 (default) to disable cycle-based fade — backward compatible.
    # References: Schmalstieg et al. (2014) J. Power Sources 309:86-95;
    #             NREL/TP-5400-74010; Pelletier et al. (2017) J. Power Sources.
    capacity_fade_pct_per_equivalent_full_cycle: float = 0.0

    # Annual capacity loss due to calendar aging (% per year).
    # Occurs even when the battery is at rest; driven by electrolyte decomposition
    # and SEI (solid-electrolyte interphase) layer growth at the anode.
    # Follows approximate Arrhenius scaling — roughly doubles per 10 °C rise.
    #
    # Typical values:
    #   Li-Ion at 25 °C:  1.5–2.5 %/year
    #   Li-Ion at 35 °C:  3.0–4.0 %/year
    #   Lead-acid:        2.0–3.0 %/year
    #
    # Set to 0.0 (default) to disable calendar aging — backward compatible.
    # References: Schmalstieg et al. (2014); Xu et al. (2016) Applied Energy;
    #             NREL/TP-5400-74010.
    calendar_fade_pct_per_year: float = 0.0

    # State of Health (%) below which the battery is considered at end of life.
    # When SoH falls to this threshold, effective_capacity_kwh stops degrading
    # further in the simulation (it is clamped here); replacement economics are
    # handled separately in the economics evaluator via lifetime_years and
    # throughput_kwh.
    #
    # IEC 62619:2022 standard: 80% for Li-Ion.
    # Some manufacturers specify 70% for LiFePO4 due to its flatter fade curve.
    # Reference: IEC 62619:2022 — Safety requirements for secondary lithium cells.
    end_of_life_soh_pct: float = 80.0

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

    if not (0.0 <= battery.capacity_fade_pct_per_equivalent_full_cycle <= 100.0):
        raise ValueError(
            "Battery capacity_fade_pct_per_equivalent_full_cycle must be between 0 and 100"
        )

    if not (0.0 <= battery.calendar_fade_pct_per_year <= 100.0):
        raise ValueError("Battery calendar_fade_pct_per_year must be between 0 and 100")

    # EOL must be strictly less than 100 to allow any cycling, and >= 0.
    if not (0.0 <= battery.end_of_life_soh_pct < 100.0):
        raise ValueError(
            "Battery end_of_life_soh_pct must be >= 0 and < 100"
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