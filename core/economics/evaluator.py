from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.components.config import ComponentsConfig
from core.optimization.design_point import DesignPoint
from core.project import load_project


EPSILON: float = 1e-9


@dataclass(frozen=True)
class EconomicAssumptions:
    project_life_years: float = 20.0
    real_discount_rate_pct: float = 8.0
    grid_purchase_price_per_kwh: float = 0.0
    grid_export_price_per_kwh: float = 0.0


@dataclass(frozen=True)
class ComponentCostBreakdown:
    """Per-component NPC breakdown matching HOMER Pro's cost summary table."""
    capital: float = 0.0
    replacement_pv: float = 0.0
    om_pv: float = 0.0
    salvage_pv: float = 0.0

    @property
    def total_npc(self) -> float:
        return self.capital + self.replacement_pv + self.om_pv - self.salvage_pv


@dataclass(frozen=True)
class EconomicEvaluation:
    # --- Summary totals ---
    direct_capital_cost: float
    annual_fixed_om_cost: float
    annual_grid_net_cost: float

    replacement_cost_present_value: float
    salvage_value_present_value: float

    annualized_capital_cost: float
    annualized_total_cost: float

    net_present_cost: float
    levelized_cost_of_energy: float

    # --- Per-component breakdowns (HOMER-style cost table) ---
    pv_breakdown: ComponentCostBreakdown = field(default_factory=ComponentCostBreakdown)
    wind_breakdown: ComponentCostBreakdown = field(default_factory=ComponentCostBreakdown)
    battery_breakdown: ComponentCostBreakdown = field(default_factory=ComponentCostBreakdown)
    converter_breakdown: ComponentCostBreakdown = field(default_factory=ComponentCostBreakdown)
    grid_breakdown: ComponentCostBreakdown = field(default_factory=ComponentCostBreakdown)


# ---------------------------------------------------------------------------
# Low-level financial math
# ---------------------------------------------------------------------------

def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _first_numeric_attr(obj: Any, names: list[str], default: float = 0.0) -> float:
    if obj is None:
        return float(default)

    for name in names:
        if hasattr(obj, name):
            value = getattr(obj, name)
            try:
                if value is not None:
                    return float(value)
            except Exception:
                continue

    return float(default)


def _capital_recovery_factor(real_discount_rate_pct: float, project_life_years: float) -> float:
    i = max(0.0, float(real_discount_rate_pct)) / 100.0
    n = max(0.0, float(project_life_years))

    if n <= 0.0:
        return 0.0

    if i <= EPSILON:
        return 1.0 / n

    return i * ((1.0 + i) ** n) / (((1.0 + i) ** n) - 1.0)


def _annuity_factor(real_discount_rate_pct: float, project_life_years: float) -> float:
    """Present value of a uniform annual payment of 1 over project life (= 1/CRF)."""
    crf = _capital_recovery_factor(real_discount_rate_pct, project_life_years)
    if crf <= EPSILON:
        return float(project_life_years)
    return 1.0 / crf


def _replacement_present_value(
    replacement_cost: float,
    component_lifetime_years: float,
    project_life_years: float,
    real_discount_rate_pct: float,
) -> float:
    """
    PV of all mid-life component replacements.

    Replacements occur at years L, 2L, 3L, ... strictly before project end N.
    Each discounted back to year 0 at the real discount rate.
    """
    if replacement_cost <= EPSILON or component_lifetime_years <= EPSILON:
        return 0.0

    r = max(0.0, real_discount_rate_pct) / 100.0
    n_replacements = math.ceil(project_life_years / component_lifetime_years) - 1

    total = 0.0
    for k in range(1, n_replacements + 1):
        year = k * component_lifetime_years
        if r > EPSILON:
            total += replacement_cost / (1.0 + r) ** year
        else:
            total += replacement_cost

    return total


def _salvage_present_value(
    replacement_cost: float,
    component_lifetime_years: float,
    project_life_years: float,
    real_discount_rate_pct: float,
) -> float:
    """
    PV of salvage value at end of project.

    Remaining useful life at year N is computed from the last installation
    (initial or most recent replacement). Salvage uses straight-line depreciation
    of the replacement cost, matching HOMER Pro's convention.
    """
    if replacement_cost <= EPSILON or component_lifetime_years <= EPSILON or project_life_years <= EPSILON:
        return 0.0

    r = max(0.0, real_discount_rate_pct) / 100.0
    n_replacements = math.ceil(project_life_years / component_lifetime_years) - 1
    last_installation_year = n_replacements * component_lifetime_years
    remaining_life = (last_installation_year + component_lifetime_years) - project_life_years

    if remaining_life <= EPSILON:
        return 0.0

    salvage_fraction = remaining_life / component_lifetime_years

    if r > EPSILON:
        discount = 1.0 / (1.0 + r) ** project_life_years
    else:
        discount = 1.0

    return replacement_cost * salvage_fraction * discount


# ---------------------------------------------------------------------------
# Project / assumptions loading
# ---------------------------------------------------------------------------

def _build_default_assumptions_for_project(
    project_name: str,
    components: ComponentsConfig,
) -> EconomicAssumptions:
    project_dir = Path("projects") / project_name

    project_life_years = 20.0
    real_discount_rate_pct = 8.0

    try:
        project = load_project(project_dir)
        economics = getattr(project, "economics", None)

        project_life_years = _first_numeric_attr(
            economics,
            [
                "project_life_years",
                "analysis_years",
                "lifetime_years",
                "project_lifetime_years",
            ],
            20.0,
        )

        nominal_discount_rate_pct = _first_numeric_attr(
            economics,
            [
                "nominal_discount_rate_pct",
                "discount_rate",
                "discount_rate_pct",
            ],
            10.0,
        )

        inflation_rate_pct = _first_numeric_attr(
            economics,
            ["inflation_rate_pct", "inflation_rate"],
            6.0,
        )

        # Fisher equation: real = (nominal - inflation) / (1 + inflation/100)
        # HOMER Pro applies this conversion internally before all discounting.
        # Reference: NREL/TP-710-42565 p.12; Irving Fisher "Theory of Interest" (1930)
        if inflation_rate_pct > EPSILON:
            real_discount_rate_pct = (
                (nominal_discount_rate_pct - inflation_rate_pct)
                / (1.0 + inflation_rate_pct / 100.0)
            )
        else:
            real_discount_rate_pct = nominal_discount_rate_pct

    except Exception:
        pass

    grid_purchase_price_per_kwh = _first_numeric_attr(
        components.grid,
        [
            "grid_power_price_per_kwh",
            "purchase_price_per_kwh",
            "import_price_per_kwh",
            "buy_price_per_kwh",
            "grid_purchase_tariff_rs_per_kwh",
            "buy_tariff_rs_per_kwh",
        ],
        0.0,
    )

    grid_export_price_per_kwh = _first_numeric_attr(
        components.grid,
        [
            "grid_sellback_price_per_kwh",
            "export_price_per_kwh",
            "sell_price_per_kwh",
            "sellback_price_per_kwh",
            "feed_in_tariff_rs_per_kwh",
            "grid_export_tariff_rs_per_kwh",
        ],
        0.0,
    )

    return EconomicAssumptions(
        project_life_years=max(1.0, project_life_years),
        real_discount_rate_pct=max(0.0, real_discount_rate_pct),
        grid_purchase_price_per_kwh=max(0.0, grid_purchase_price_per_kwh),
        grid_export_price_per_kwh=max(0.0, grid_export_price_per_kwh),
    )


def build_default_economic_assumptions_for_project(
    project_name: str,
    components: ComponentsConfig,
) -> EconomicAssumptions:
    return _build_default_assumptions_for_project(project_name, components)


# ---------------------------------------------------------------------------
# Per-component capital cost helpers (unchanged)
# ---------------------------------------------------------------------------

def _pv_capital_cost(components: ComponentsConfig, design: DesignPoint) -> float:
    rate = _first_numeric_attr(
        components.pv,
        ["capital_cost_per_kw", "capital_cost_rs_per_kw", "capex_per_kw", "installed_cost_per_kw"],
        0.0,
    )
    return max(0.0, design.pv_capacity_kw) * max(0.0, rate)


def _wind_capital_cost(components: ComponentsConfig, design: DesignPoint) -> float:
    rate = _first_numeric_attr(
        components.wind,
        ["capital_cost_per_turbine", "capital_cost_rs_per_turbine", "capex_per_turbine", "installed_cost_per_turbine"],
        0.0,
    )
    return max(0, design.wind_quantity) * max(0.0, rate)


def _battery_capital_cost(components: ComponentsConfig, design: DesignPoint) -> float:
    rate = _first_numeric_attr(
        components.battery,
        ["capital_cost_per_string", "capital_cost_rs_per_string", "capex_per_string", "installed_cost_per_string"],
        0.0,
    )
    return max(0, design.battery_quantity) * max(0.0, rate)


def _converter_capital_cost(components: ComponentsConfig, design: DesignPoint) -> float:
    rate = _first_numeric_attr(
        components.converter,
        ["capital_cost_per_kw", "capital_cost_rs_per_kw", "capex_per_kw", "installed_cost_per_kw"],
        0.0,
    )
    return max(0.0, design.converter_capacity_kw) * max(0.0, rate)


# ---------------------------------------------------------------------------
# Per-component replacement cost helpers (total, not per-unit)
# ---------------------------------------------------------------------------

def _pv_total_replacement_cost(components: ComponentsConfig, design: DesignPoint) -> float:
    rate = _first_numeric_attr(
        components.pv,
        ["replacement_cost_per_kw", "replacement_cost_rs_per_kw"],
        0.0,
    )
    return max(0.0, design.pv_capacity_kw) * max(0.0, rate)


def _wind_total_replacement_cost(components: ComponentsConfig, design: DesignPoint) -> float:
    rate = _first_numeric_attr(
        components.wind,
        ["replacement_cost_per_turbine", "replacement_cost_rs_per_turbine"],
        0.0,
    )
    return max(0, design.wind_quantity) * max(0.0, rate)


def _battery_total_replacement_cost(components: ComponentsConfig, design: DesignPoint) -> float:
    rate = _first_numeric_attr(
        components.battery,
        ["replacement_cost_per_string", "replacement_cost_rs_per_string"],
        0.0,
    )
    return max(0, design.battery_quantity) * max(0.0, rate)


def _converter_total_replacement_cost(components: ComponentsConfig, design: DesignPoint) -> float:
    rate = _first_numeric_attr(
        components.converter,
        ["replacement_cost_per_kw", "replacement_cost_rs_per_kw"],
        0.0,
    )
    return max(0.0, design.converter_capacity_kw) * max(0.0, rate)


# ---------------------------------------------------------------------------
# Per-component lifetime helpers
# ---------------------------------------------------------------------------

def _pv_lifetime_years(components: ComponentsConfig) -> float:
    return max(1.0, _first_numeric_attr(components.pv, ["lifetime_years"], 25.0))


def _wind_lifetime_years(components: ComponentsConfig) -> float:
    return max(1.0, _first_numeric_attr(components.wind, ["lifetime_years"], 20.0))


def _battery_lifetime_years(components: ComponentsConfig, simulation_results=None) -> float:
    """
    Effective battery lifetime = min(calendar_life, throughput_life).

    Matches HOMER Pro's battery replacement timing:
    - Calendar life: user-entered years (e.g. 15 years)
    - Throughput life: lifetime_throughput_kwh / annual_throughput_kwh from simulation

    Whichever limit is hit first triggers a replacement.
    Reference: NREL/TP-710-42565; HOMER Pro Battery documentation.
    """
    calendar_life = max(1.0, _first_numeric_attr(
        components.battery, ["lifetime_years"], 15.0
    ))

    if simulation_results is None:
        return calendar_life

    lifetime_throughput_kwh = _first_numeric_attr(
        components.battery, ["throughput_kwh"], 0.0
    )
    if lifetime_throughput_kwh <= EPSILON:
        return calendar_life

    annual_throughput_kwh = max(0.0, float(
        getattr(getattr(simulation_results, "summary", None),
                "total_battery_throughput_kwh", 0.0)
    ))
    if annual_throughput_kwh <= EPSILON:
        return calendar_life

    throughput_life = lifetime_throughput_kwh / annual_throughput_kwh
    return max(1.0, min(calendar_life, throughput_life))


def _converter_lifetime_years(components: ComponentsConfig) -> float:
    return max(1.0, _first_numeric_attr(
        components.converter,
        ["inverter_lifetime_years", "lifetime_years"],
        15.0,
    ))


# ---------------------------------------------------------------------------
# Per-component annual O&M cost helpers (unchanged)
# ---------------------------------------------------------------------------

def _pv_fixed_om_cost(components: ComponentsConfig, design: DesignPoint) -> float:
    rate = _first_numeric_attr(
        components.pv,
        ["fixed_om_cost_per_kw_per_year", "om_cost_per_kw_per_year", "fixed_om_per_kw_year", "annual_om_per_kw"],
        0.0,
    )
    return max(0.0, design.pv_capacity_kw) * max(0.0, rate)


def _wind_fixed_om_cost(components: ComponentsConfig, design: DesignPoint) -> float:
    rate = _first_numeric_attr(
        components.wind,
        ["fixed_om_cost_per_turbine_per_year", "om_cost_per_turbine_per_year", "fixed_om_per_turbine_year", "annual_om_per_turbine"],
        0.0,
    )
    return max(0, design.wind_quantity) * max(0.0, rate)


def _battery_fixed_om_cost(components: ComponentsConfig, design: DesignPoint) -> float:
    rate = _first_numeric_attr(
        components.battery,
        ["fixed_om_cost_per_string_per_year", "om_cost_per_string_per_year", "fixed_om_per_string_year", "annual_om_per_string"],
        0.0,
    )
    return max(0, design.battery_quantity) * max(0.0, rate)


def _converter_fixed_om_cost(components: ComponentsConfig, design: DesignPoint) -> float:
    rate = _first_numeric_attr(
        components.converter,
        ["fixed_om_cost_per_kw_per_year", "om_cost_per_kw_per_year", "fixed_om_per_kw_year", "annual_om_per_kw"],
        0.0,
    )
    return max(0.0, design.converter_capacity_kw) * max(0.0, rate)


# ---------------------------------------------------------------------------
# Main evaluation function
# ---------------------------------------------------------------------------

def evaluate_candidate_economics(
    *,
    project_name: str,
    components: ComponentsConfig,
    design: DesignPoint,
    simulation_results,
    assumptions: EconomicAssumptions | None = None,
) -> EconomicEvaluation:
    assumptions_used = (
        assumptions
        if assumptions is not None
        else build_default_economic_assumptions_for_project(project_name, components)
    )

    N = assumptions_used.project_life_years
    r = assumptions_used.real_discount_rate_pct
    summary = simulation_results.summary

    crf = _capital_recovery_factor(r, N)
    af = _annuity_factor(r, N)  # = 1/CRF, present value factor for uniform annual costs

    # --- Capital costs ---
    pv_cap = _pv_capital_cost(components, design)
    wind_cap = _wind_capital_cost(components, design)
    batt_cap = _battery_capital_cost(components, design)
    conv_cap = _converter_capital_cost(components, design)
    direct_capital_cost = pv_cap + wind_cap + batt_cap + conv_cap

    # --- Annual O&M costs ---
    pv_om = _pv_fixed_om_cost(components, design)
    wind_om = _wind_fixed_om_cost(components, design)
    batt_om = _battery_fixed_om_cost(components, design)
    conv_om = _converter_fixed_om_cost(components, design)
    annual_fixed_om_cost = pv_om + wind_om + batt_om + conv_om

    # --- Annual grid net cost ---
    annual_grid_purchase_cost = (
        max(0.0, float(summary.total_grid_import_kwh))
        * assumptions_used.grid_purchase_price_per_kwh
    )
    annual_grid_export_revenue = (
        max(0.0, float(summary.total_grid_export_kwh))
        * assumptions_used.grid_export_price_per_kwh
    )
    annual_grid_net_cost = annual_grid_purchase_cost - annual_grid_export_revenue

    # --- Replacement cost PV (per component) ---
    pv_repl_pv = _replacement_present_value(
        _pv_total_replacement_cost(components, design),
        _pv_lifetime_years(components), N, r,
    )
    wind_repl_pv = _replacement_present_value(
        _wind_total_replacement_cost(components, design),
        _wind_lifetime_years(components), N, r,
    )
    # Battery effective lifetime = min(calendar life, throughput life)
    batt_effective_life = _battery_lifetime_years(components, simulation_results)

    batt_repl_pv = _replacement_present_value(
        _battery_total_replacement_cost(components, design),
        batt_effective_life, N, r,
    )
    conv_repl_pv = _replacement_present_value(
        _converter_total_replacement_cost(components, design),
        _converter_lifetime_years(components), N, r,
    )
    replacement_cost_present_value = pv_repl_pv + wind_repl_pv + batt_repl_pv + conv_repl_pv

    # --- Salvage value PV (per component) ---
    pv_salv_pv = _salvage_present_value(
        _pv_total_replacement_cost(components, design),
        _pv_lifetime_years(components), N, r,
    )
    wind_salv_pv = _salvage_present_value(
        _wind_total_replacement_cost(components, design),
        _wind_lifetime_years(components), N, r,
    )
    batt_salv_pv = _salvage_present_value(
        _battery_total_replacement_cost(components, design),
        batt_effective_life, N, r,
    )
    conv_salv_pv = _salvage_present_value(
        _converter_total_replacement_cost(components, design),
        _converter_lifetime_years(components), N, r,
    )
    salvage_value_present_value = pv_salv_pv + wind_salv_pv + batt_salv_pv + conv_salv_pv

    # --- NPC (HOMER formula) ---
    # NPC = capital + replacement_pv - salvage_pv + (annual_om + annual_grid_net) * annuity_factor
    net_present_cost = (
        direct_capital_cost
        + replacement_cost_present_value
        - salvage_value_present_value
        + (annual_fixed_om_cost + annual_grid_net_cost) * af
    )

    # --- Annualized costs ---
    annualized_capital_cost = direct_capital_cost * crf
    annualized_total_cost = net_present_cost * crf

    # --- LCOE ---
    total_served_load_kwh = max(0.0, float(summary.total_served_load_kwh))
    levelized_cost_of_energy = (
        annualized_total_cost / total_served_load_kwh
        if total_served_load_kwh > EPSILON
        else 0.0
    )

    # --- Per-component breakdowns ---
    pv_breakdown = ComponentCostBreakdown(
        capital=pv_cap,
        replacement_pv=pv_repl_pv,
        om_pv=pv_om * af,
        salvage_pv=pv_salv_pv,
    )
    wind_breakdown = ComponentCostBreakdown(
        capital=wind_cap,
        replacement_pv=wind_repl_pv,
        om_pv=wind_om * af,
        salvage_pv=wind_salv_pv,
    )
    battery_breakdown = ComponentCostBreakdown(
        capital=batt_cap,
        replacement_pv=batt_repl_pv,
        om_pv=batt_om * af,
        salvage_pv=batt_salv_pv,
    )
    converter_breakdown = ComponentCostBreakdown(
        capital=conv_cap,
        replacement_pv=conv_repl_pv,
        om_pv=conv_om * af,
        salvage_pv=conv_salv_pv,
    )
    grid_breakdown = ComponentCostBreakdown(
        capital=0.0,
        replacement_pv=0.0,
        om_pv=annual_grid_net_cost * af,
        salvage_pv=0.0,
    )

    return EconomicEvaluation(
        direct_capital_cost=direct_capital_cost,
        annual_fixed_om_cost=annual_fixed_om_cost,
        annual_grid_net_cost=annual_grid_net_cost,
        replacement_cost_present_value=replacement_cost_present_value,
        salvage_value_present_value=salvage_value_present_value,
        annualized_capital_cost=annualized_capital_cost,
        annualized_total_cost=annualized_total_cost,
        net_present_cost=net_present_cost,
        levelized_cost_of_energy=levelized_cost_of_energy,
        pv_breakdown=pv_breakdown,
        wind_breakdown=wind_breakdown,
        battery_breakdown=battery_breakdown,
        converter_breakdown=converter_breakdown,
        grid_breakdown=grid_breakdown,
    )
