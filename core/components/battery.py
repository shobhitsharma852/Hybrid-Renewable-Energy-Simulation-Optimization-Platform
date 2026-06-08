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

    # Calendar fade rate: % of original capacity lost per year from time-based aging,
    # independent of cycling.  0.0 = disabled (replacement economics handled by
    # lifetime_years alone — the default and recommended setting for most projects).
    #
    # When set > 0, the simulator applies this fade every step via the max() rule:
    #     soh = 100 − max(cycle_fade, calendar_fade, dod_fade)
    # so calendar and cycle aging compete rather than accumulate.
    #
    # This is the rate at the REFERENCE temperature (temperature_reference_c, default 25°C).
    # When arrhenius_ea_ev > 0, the actual per-step rate is scaled by the Arrhenius factor
    # so hotter climates degrade the battery faster.
    #
    # Typical values: Li-Ion ≈ 2–3 %/year, Lead-acid ≈ 3–5 %/year.
    # Reference: Pelletier et al. (2017) J. Power Sources 359:468-479.
    calendar_fade_pct_per_year: float = 0.0

    # Arrhenius activation energy (eV) for temperature-dependent calendar aging.
    # 0.0 = disabled: calendar_fade_pct_per_year is applied as a fixed rate (no
    # temperature dependence).
    #
    # When > 0 and a "temperature" column is present in the resource data, the
    # per-step calendar fade rate is scaled by the Arrhenius factor:
    #
    #   scale(T) = exp( Ea/kB × (1/T_ref_K − 1/T_K) )
    #
    # so a battery at T > T_ref ages faster, and at T < T_ref ages slower.
    # At T = temperature_reference_c: scale = 1.0 (same as fixed rate).
    #
    # Typical values: Li-Ion NMC/NCA ≈ 0.7 eV, LFP ≈ 0.6 eV.
    # Reference: Schmalstieg et al. (2014) J. Power Sources 309:86-95.
    arrhenius_ea_ev: float = 0.0

    # Reference temperature (°C) at which calendar_fade_pct_per_year is specified.
    # Only used when arrhenius_ea_ev > 0.  Default 25°C matches standard lab conditions.
    temperature_reference_c: float = 25.0

    # --------------------------------------------------------
    # CYCLE LIFE PARAMETERS  (DoD-dependent aging — HOMER Pro ASM "Cycle Life")
    # --------------------------------------------------------
    # Power-law model: N(DoD) = A × DoD^(-beta)
    # where N(DoD) = number of full cycles to failure at depth-of-discharge DoD.
    #
    # Damage per half-cycle (Miner's rule):
    #     damage = 0.5 / N(DoD) = 0.5 × DoD^beta / A
    # Cumulative damage sums these each time the charge direction reverses.
    # At cumulative damage ≥ 1.0 the battery has reached end of life by cycling.
    #
    # Relationship to replacement_degradation_limit_pct:
    #     cumulative_damage = 1.0 → capacity has lost replacement_degradation_limit_pct %
    # So the DoD model and EFC model share the same EOL definition.
    #
    # HOMER Pro Generic Li-Ion defaults: A = 750, beta = 1.3.
    # Set cycle_life_a = 0 to disable the DoD model and fall back to the simpler
    # EFC model derived from throughput_kwh (no per-cycle DoD tracking).
    #
    # References:
    #   HOMER Pro Help → Advanced Storage Battery Model → Cycle Life.
    #   Lam & Bauer (2013) IEEE Trans. Power Electron. 28(12):5603-5613.
    cycle_life_a: float = 0.0     # Cycles to failure at 100% DoD; 0 = disabled (use EFC model)
    cycle_life_beta: float = 1.3  # Power-law exponent; only used when cycle_life_a > 0

    # --------------------------------------------------------
    # TEMPERATURE EFFECTS
    # --------------------------------------------------------
    # Whether to apply the temperature-based capacity correction each timestep.
    # When False, capacity is unaffected by ambient temperature (fast path).
    # When True, the usable capacity for each hour is scaled by the polynomial:
    #     Capacity(T) = Capacity × (d0 + d1×T + d2×T²)
    # where T is the ambient temperature in °C from the resource file.
    #
    # This is a REVERSIBLE correction — it adjusts dispatch capacity in real time
    # but does NOT permanently degrade the battery.  SoH and throughput tracking
    # are unaffected.
    #
    # Requires a "temperature" column in the resource DataFrame.
    # If the column is missing and this flag is True, the simulator skips the
    # correction silently (safe fallback to standard capacity).
    #
    # Reference: HOMER Pro Advanced Storage Model — Temperature Effects section.
    consider_temperature_effects: bool = False

    # Polynomial coefficients for the temperature capacity correction.
    # HOMER Pro defaults for Generic Li-Ion (from the ASM Temperature Effects panel):
    #   d0 = 0.923     — constant: capacity at 0°C is 92.3% of rated
    #   d1 = 0.00345   — linear:   capacity rises ~0.35%/°C above 0°C
    #   d2 = -3.75e-05 — quadratic: flattens/reduces correction at high temperatures
    #
    # Worked examples at standard temperatures:
    #   T =  0°C → factor = 0.923 + 0       + 0       = 0.923  (92.3% of rated)
    #   T = 25°C → factor = 0.923 + 0.08625 − 0.02344 ≈ 0.9858 (98.6% — NOTE: HOMER
    #              calibrates the polynomial so that factor peaks near 25–35°C; at
    #              exactly 25°C the result is still slightly below 1.0, so the factor
    #              will be clamped to 1.0 if it ever exceeds it)
    #   T = 45°C → factor = 0.923 + 0.15525 − 0.07594 ≈ 1.002  → clamped to 1.0
    capacity_temp_d0: float = 0.923
    capacity_temp_d1: float = 0.00345
    capacity_temp_d2: float = -3.75e-05

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

    if battery.calendar_fade_pct_per_year < 0.0:
        raise ValueError("Battery calendar_fade_pct_per_year cannot be negative")

    if battery.arrhenius_ea_ev < 0.0:
        raise ValueError("Battery arrhenius_ea_ev cannot be negative")

    if battery.arrhenius_ea_ev > 0.0 and battery.calendar_fade_pct_per_year <= 0.0:
        raise ValueError(
            "Battery calendar_fade_pct_per_year must be > 0 when arrhenius_ea_ev > 0 "
            "(Arrhenius scales a base rate — there is nothing to scale if the rate is zero)"
        )

    # cycle_life_a = 0 means DoD model is disabled — valid. If > 0, beta must also be > 0.
    if battery.cycle_life_a < 0.0:
        raise ValueError("Battery cycle_life_a cannot be negative")

    if battery.cycle_life_a > 0.0 and battery.cycle_life_beta <= 0.0:
        raise ValueError(
            "Battery cycle_life_beta must be > 0 when cycle_life_a > 0"
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