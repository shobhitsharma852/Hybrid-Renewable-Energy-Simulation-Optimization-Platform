from __future__ import annotations

# ============================================================
# core/simulation/grid_model.py
#
# Purpose:
#   Grid interaction model for hourly hybrid simulation.
#
# What this file does:
#   1. Resolve grid limits from config (import / export capacity)
#   2. Compute grid export given available surplus AC power
#   3. Compute grid import given remaining unmet load
#   4. Provide clean result objects for each operation
#
# What this file does NOT do:
#   - time-of-use tariff scheduling
#   - demand charge tracking
#   - net metering credit accumulation
#   - grid outage / reliability modelling
#   - dispatch priority decisions (those stay in dispatch.py)
#
# Why:
#   Grid logic was previously inline in dispatch.py.
#   Separating it here follows the same pattern as pv_model.py
#   and wind_model.py, and makes it easy to extend with TOU
#   tariffs, demand charges, or outage schedules later.
# ============================================================

from dataclasses import dataclass
from typing import Any


# ============================================================
# CONSTANTS
# ============================================================

EPSILON: float = 1e-9
VERY_LARGE_POWER_KW: float = 1e12


# ============================================================
# RESULT OBJECTS
# ============================================================

@dataclass(frozen=True)
class GridLimits:
    """
    Resolved import / export capacity limits from grid config.
    """
    enabled: bool
    allow_import: bool
    allow_export: bool
    import_limit_kw: float
    export_limit_kw: float


@dataclass(frozen=True)
class GridExportResult:
    """
    Result of one grid export step.
    """
    grid_export_kw: float
    excess_energy_kw: float


@dataclass(frozen=True)
class GridImportResult:
    """
    Result of one grid import step.
    """
    grid_import_kw: float
    remaining_unmet_load_kw: float


# ============================================================
# INTERNAL HELPERS
# ============================================================

def _safe_getattr(obj: Any, name: str, default: Any) -> Any:
    return getattr(obj, name, default)


# ============================================================
# CORE GRID FUNCTIONS
# ============================================================

def resolve_grid_limits(grid_config: Any) -> GridLimits:
    """
    Extract and resolve import / export limits from grid config.

    Parameters
    ----------
    grid_config:
        GridComponentConfig instance (or any object with the
        expected attributes).

    Returns
    -------
    GridLimits
        Resolved operational limits for this timestep.
    """
    enabled = bool(_safe_getattr(grid_config, "enabled", False))
    allow_import = bool(_safe_getattr(grid_config, "allow_import", enabled))
    allow_export = bool(_safe_getattr(grid_config, "allow_export", enabled))

    sale_capacity_kw_raw = _safe_getattr(grid_config, "sale_capacity_kw", None)
    purchase_capacity_kw_raw = _safe_getattr(grid_config, "purchase_capacity_kw", None)

    export_limit_kw = (
        VERY_LARGE_POWER_KW
        if sale_capacity_kw_raw is None
        else max(0.0, float(sale_capacity_kw_raw))
    )

    import_limit_kw = (
        VERY_LARGE_POWER_KW
        if purchase_capacity_kw_raw is None
        else max(0.0, float(purchase_capacity_kw_raw))
    )

    return GridLimits(
        enabled=enabled,
        allow_import=allow_import,
        allow_export=allow_export,
        import_limit_kw=import_limit_kw,
        export_limit_kw=export_limit_kw,
    )


def compute_grid_export(
    *,
    available_surplus_ac_kw: float,
    pv_curtailed_dc_kw: float,
    limits: GridLimits,
) -> GridExportResult:
    """
    Compute how much surplus AC power is exported to the grid,
    and how much becomes excess (curtailed) energy.

    Parameters
    ----------
    available_surplus_ac_kw:
        Total surplus AC power available for export (wind surplus
        + PV surplus after inverter conversion).
    pv_curtailed_dc_kw:
        PV DC power that could not pass through the inverter
        (inverter capacity clipping). Always treated as excess.
    limits:
        Resolved grid limits from resolve_grid_limits().

    Returns
    -------
    GridExportResult
    """
    available_surplus_ac_kw = max(0.0, float(available_surplus_ac_kw))
    pv_curtailed_dc_kw = max(0.0, float(pv_curtailed_dc_kw))

    if limits.allow_export and available_surplus_ac_kw > EPSILON:
        grid_export_kw = min(available_surplus_ac_kw, limits.export_limit_kw)
        excess_energy_kw = (available_surplus_ac_kw - grid_export_kw) + pv_curtailed_dc_kw
    else:
        grid_export_kw = 0.0
        excess_energy_kw = available_surplus_ac_kw + pv_curtailed_dc_kw

    return GridExportResult(
        grid_export_kw=grid_export_kw,
        excess_energy_kw=excess_energy_kw,
    )


def compute_grid_import(
    *,
    remaining_load_kw: float,
    limits: GridLimits,
) -> GridImportResult:
    """
    Compute how much power is imported from the grid to cover
    remaining unmet load after renewables and battery dispatch.

    Parameters
    ----------
    remaining_load_kw:
        Unmet load remaining after all local sources have been
        dispatched.
    limits:
        Resolved grid limits from resolve_grid_limits().

    Returns
    -------
    GridImportResult
    """
    remaining_load_kw = max(0.0, float(remaining_load_kw))

    if remaining_load_kw > EPSILON and limits.allow_import:
        grid_import_kw = min(remaining_load_kw, limits.import_limit_kw)
        remaining_unmet_load_kw = max(0.0, remaining_load_kw - grid_import_kw)
    else:
        grid_import_kw = 0.0
        remaining_unmet_load_kw = remaining_load_kw

    return GridImportResult(
        grid_import_kw=grid_import_kw,
        remaining_unmet_load_kw=remaining_unmet_load_kw,
    )
