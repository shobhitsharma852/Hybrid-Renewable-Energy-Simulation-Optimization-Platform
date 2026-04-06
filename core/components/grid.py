from __future__ import annotations

# ============================================================
# core/components/grid.py
#
# Purpose:
#   Define the Grid component configuration only.
#
# Scope of this file:
#   1. Main grid component configuration
#   2. Grid validation logic
#
# What is NOT included here:
#   - PV / wind / battery / converter
#   - project-level grouping
#   - save/load of components.json
#   - real-time tariff matrices
#   - scheduled tariff matrices
#   - reliability heatmaps
#   - grid extension modeling
#
# Why:
#   For Version 1, Grid is intentionally kept simple and flat.
#   We only store the core parameters needed for:
#       - grid import
#       - grid export
#       - cost calculation
#       - emissions calculation
#       - basic dispatch constraints
# ============================================================

from dataclasses import dataclass
from typing import Optional


# ============================================================
# SECTION 1 — MAIN GRID COMPONENT CLASS
# ============================================================

@dataclass(frozen=True)
class GridComponentConfig:
    """
    Main grid component configuration.

    This is the full grid definition for a project.

    Design choice for Version 1:
    - Keep grid configuration flat
    - Do NOT split into advanced settings yet
    - Store only the most important tariff / limit / emission fields

    Notes:
    - grid_power_price_per_kwh:
        price to import electricity from the grid

    - grid_sellback_price_per_kwh:
        price received when exporting electricity to the grid

    - sale_capacity_kw:
        maximum export power allowed to the grid

    - purchase_capacity_kw:
        maximum import power allowed from the grid

    - net_metering_enabled:
        whether exported electricity is treated under net metering logic

    - co2_emissions_g_per_kwh:
        grid emission intensity for environmental reporting
    """

    # --------------------------------------------------------
    # BASIC ENABLE SETTING
    # --------------------------------------------------------

    # Whether grid is enabled in the project
    enabled: bool = True

    # --------------------------------------------------------
    # SIMPLE TARIFF PARAMETERS
    # --------------------------------------------------------

    # Grid purchase price ($/kWh)
    grid_power_price_per_kwh: float = 0.10

    # Grid sellback price ($/kWh)
    grid_sellback_price_per_kwh: float = 0.05

    # --------------------------------------------------------
    # GRID IMPORT / EXPORT LIMITS
    # --------------------------------------------------------

    # Maximum export power to grid (kW)
    # None means no explicit limit
    sale_capacity_kw: Optional[float] = 999_999.0

    # Maximum import power from grid (kW)
    # None means no explicit limit
    purchase_capacity_kw: Optional[float] = 999_999.0

    # --------------------------------------------------------
    # NET METERING
    # --------------------------------------------------------

    # Whether net metering is enabled
    net_metering_enabled: bool = False

    # --------------------------------------------------------
    # EMISSIONS
    # --------------------------------------------------------

    # Grid CO2 emissions intensity (g/kWh)
    co2_emissions_g_per_kwh: float = 632.0


# ============================================================
# SECTION 2 — MAIN VALIDATION FUNCTION
# ============================================================

def validate_grid_component(grid: GridComponentConfig) -> None:
    """
    Validate the full grid component configuration.

    Raises:
        ValueError: if any configuration value is invalid
    """

    # --------------------------------------------------------
    # TARIFF PARAMETERS
    # --------------------------------------------------------
    if grid.grid_power_price_per_kwh < 0:
        raise ValueError("Grid grid_power_price_per_kwh must be >= 0")

    if grid.grid_sellback_price_per_kwh < 0:
        raise ValueError("Grid grid_sellback_price_per_kwh must be >= 0")

    # --------------------------------------------------------
    # IMPORT / EXPORT LIMITS
    # --------------------------------------------------------
    if grid.sale_capacity_kw is not None and grid.sale_capacity_kw < 0:
        raise ValueError("Grid sale_capacity_kw must be >= 0")

    if grid.purchase_capacity_kw is not None and grid.purchase_capacity_kw < 0:
        raise ValueError("Grid purchase_capacity_kw must be >= 0")

    # --------------------------------------------------------
    # EMISSIONS
    # --------------------------------------------------------
    if grid.co2_emissions_g_per_kwh < 0:
        raise ValueError("Grid co2_emissions_g_per_kwh must be >= 0")