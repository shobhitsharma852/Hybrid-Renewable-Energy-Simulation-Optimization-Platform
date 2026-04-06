from __future__ import annotations

# ============================================================
# core/components/converter.py
#
# Purpose:
#   Define the Converter component configuration only.
#
# Scope of this file:
#   1. Main converter component configuration
#   2. Converter validation logic
#
# What is NOT included here:
#   - PV / wind / battery / grid
#   - project-level grouping
#   - save/load of components.json
#   - detailed dispatch / AC-DC simulation formulas
#   - cost multiplier popup logic
#
# Why:
#   This file should remain the single source of truth
#   for Converter component configuration only.
# ============================================================

from dataclasses import dataclass, field


# ============================================================
# SECTION 1 — MAIN CONVERTER COMPONENT CLASS
# ============================================================

@dataclass(frozen=True)
class ConverterComponentConfig:
    """
    Main converter component configuration.

    This is the full converter definition for a project.

    Design choice for Version 1:
    - Keep converter configuration flat
    - Do NOT split into advanced settings yet
    - Store all important technical, economic, and sizing fields here

    Notes:
    - Search space is based on converter capacity in kW
    - Inverter side represents DC -> AC conversion
    - Rectifier side represents AC -> DC conversion
    """

    # --------------------------------------------------------
    # BASIC ENABLE / SEARCH SPACE SETTINGS
    # --------------------------------------------------------

    # Whether converter is enabled in the project
    enabled: bool = True

    # Whether optimizer should use the capacity search space
    use_search_space: bool = True

    # Converter model name shown in UI / reports
    converter_model_name: str = "System Converter"

    # Search space in converter capacity (kW)
    # Example: [0, 1000, 2000, 3000, 4000, 5000]
    capacity_kw_options: list[float] = field(default_factory=lambda: [0.0, 1000.0])

    # --------------------------------------------------------
    # ECONOMIC PARAMETERS
    # --------------------------------------------------------

    # Capital cost per kW
    capital_cost_per_kw: float = 300.0

    # Replacement cost per kW
    replacement_cost_per_kw: float = 300.0

    # O&M cost per kW per year
    om_cost_per_kw_per_year: float = 0.0

    # --------------------------------------------------------
    # INVERTER / RECTIFIER PARAMETERS
    # --------------------------------------------------------

    # Inverter lifetime (years)
    inverter_lifetime_years: int = 15

    # DC -> AC efficiency (%)
    inverter_efficiency_pct: float = 95.0

    # AC -> DC relative capacity (%)
    rectifier_relative_capacity_pct: float = 100.0

    # AC -> DC efficiency (%)
    rectifier_efficiency_pct: float = 95.0

    # Whether converter can operate in parallel with AC generator
    parallel_with_ac_generator: bool = False


# ============================================================
# SECTION 2 — VALIDATION HELPERS
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


# ============================================================
# SECTION 3 — MAIN VALIDATION FUNCTION
# ============================================================

def validate_converter_component(converter: ConverterComponentConfig) -> None:
    """
    Validate the full converter component configuration.

    Raises:
        ValueError: if any configuration value is invalid
    """

    # --------------------------------------------------------
    # MODEL NAME
    # --------------------------------------------------------
    if not converter.converter_model_name.strip():
        raise ValueError("Converter converter_model_name cannot be empty")

    # --------------------------------------------------------
    # SEARCH SPACE / CAPACITY
    # --------------------------------------------------------
    _validate_non_negative_float_list(
        converter.capacity_kw_options,
        "Converter capacity_kw_options",
    )

    # --------------------------------------------------------
    # ECONOMIC PARAMETERS
    # --------------------------------------------------------
    if converter.capital_cost_per_kw < 0:
        raise ValueError("Converter capital_cost_per_kw cannot be negative")

    if converter.replacement_cost_per_kw < 0:
        raise ValueError("Converter replacement_cost_per_kw cannot be negative")

    if converter.om_cost_per_kw_per_year < 0:
        raise ValueError("Converter om_cost_per_kw_per_year cannot be negative")

    # --------------------------------------------------------
    # INVERTER / RECTIFIER PARAMETERS
    # --------------------------------------------------------
    if converter.inverter_lifetime_years <= 0:
        raise ValueError("Converter inverter_lifetime_years must be > 0")

    if not (0 < converter.inverter_efficiency_pct <= 100):
        raise ValueError("Converter inverter_efficiency_pct must be between 0 and 100")

    if not (0 <= converter.rectifier_relative_capacity_pct <= 100):
        raise ValueError(
            "Converter rectifier_relative_capacity_pct must be between 0 and 100"
        )

    if not (0 < converter.rectifier_efficiency_pct <= 100):
        raise ValueError("Converter rectifier_efficiency_pct must be between 0 and 100")