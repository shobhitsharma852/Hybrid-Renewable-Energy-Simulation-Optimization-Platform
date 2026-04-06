from __future__ import annotations

from dataclasses import dataclass
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
class EconomicEvaluation:
    direct_capital_cost: float
    annual_fixed_om_cost: float
    annual_grid_net_cost: float

    replacement_cost_present_value: float
    salvage_value_present_value: float

    annualized_capital_cost: float
    annualized_total_cost: float

    net_present_cost: float
    levelized_cost_of_energy: float


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

        real_discount_rate_pct = _first_numeric_attr(
            economics,
            [
                "discount_rate",
                "real_discount_rate_pct",
                "discount_rate_pct",
                "nominal_discount_rate_pct",
            ],
            8.0,
        )
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


def _pv_capital_cost(components: ComponentsConfig, design: DesignPoint) -> float:
    rate = _first_numeric_attr(
        components.pv,
        [
            "capital_cost_per_kw",
            "capital_cost_rs_per_kw",
            "capex_per_kw",
            "installed_cost_per_kw",
        ],
        0.0,
    )
    return max(0.0, design.pv_capacity_kw) * max(0.0, rate)


def _wind_capital_cost(components: ComponentsConfig, design: DesignPoint) -> float:
    rate = _first_numeric_attr(
        components.wind,
        [
            "capital_cost_per_turbine",
            "capital_cost_rs_per_turbine",
            "capex_per_turbine",
            "installed_cost_per_turbine",
        ],
        0.0,
    )
    return max(0, design.wind_quantity) * max(0.0, rate)


def _battery_capital_cost(components: ComponentsConfig, design: DesignPoint) -> float:
    rate = _first_numeric_attr(
        components.battery,
        [
            "capital_cost_per_string",
            "capital_cost_rs_per_string",
            "capex_per_string",
            "installed_cost_per_string",
        ],
        0.0,
    )
    return max(0, design.battery_quantity) * max(0.0, rate)


def _converter_capital_cost(components: ComponentsConfig, design: DesignPoint) -> float:
    rate = _first_numeric_attr(
        components.converter,
        [
            "capital_cost_per_kw",
            "capital_cost_rs_per_kw",
            "capex_per_kw",
            "installed_cost_per_kw",
        ],
        0.0,
    )
    return max(0.0, design.converter_capacity_kw) * max(0.0, rate)


def _pv_fixed_om_cost(components: ComponentsConfig, design: DesignPoint) -> float:
    rate = _first_numeric_attr(
        components.pv,
        [
            "fixed_om_cost_per_kw_per_year",
            "om_cost_per_kw_per_year",
            "fixed_om_per_kw_year",
            "annual_om_per_kw",
        ],
        0.0,
    )
    return max(0.0, design.pv_capacity_kw) * max(0.0, rate)


def _wind_fixed_om_cost(components: ComponentsConfig, design: DesignPoint) -> float:
    rate = _first_numeric_attr(
        components.wind,
        [
            "fixed_om_cost_per_turbine_per_year",
            "om_cost_per_turbine_per_year",
            "fixed_om_per_turbine_year",
            "annual_om_per_turbine",
        ],
        0.0,
    )
    return max(0, design.wind_quantity) * max(0.0, rate)


def _battery_fixed_om_cost(components: ComponentsConfig, design: DesignPoint) -> float:
    rate = _first_numeric_attr(
        components.battery,
        [
            "fixed_om_cost_per_string_per_year",
            "om_cost_per_string_per_year",
            "fixed_om_per_string_year",
            "annual_om_per_string",
        ],
        0.0,
    )
    return max(0, design.battery_quantity) * max(0.0, rate)


def _converter_fixed_om_cost(components: ComponentsConfig, design: DesignPoint) -> float:
    rate = _first_numeric_attr(
        components.converter,
        [
            "fixed_om_cost_per_kw_per_year",
            "om_cost_per_kw_per_year",
            "fixed_om_per_kw_year",
            "annual_om_per_kw",
        ],
        0.0,
    )
    return max(0.0, design.converter_capacity_kw) * max(0.0, rate)


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

    summary = simulation_results.summary

    direct_capital_cost = (
        _pv_capital_cost(components, design)
        + _wind_capital_cost(components, design)
        + _battery_capital_cost(components, design)
        + _converter_capital_cost(components, design)
    )

    annual_fixed_om_cost = (
        _pv_fixed_om_cost(components, design)
        + _wind_fixed_om_cost(components, design)
        + _battery_fixed_om_cost(components, design)
        + _converter_fixed_om_cost(components, design)
    )

    annual_grid_purchase_cost = (
        max(0.0, float(summary.total_grid_import_kwh))
        * assumptions_used.grid_purchase_price_per_kwh
    )

    annual_grid_export_revenue = (
        max(0.0, float(summary.total_grid_export_kwh))
        * assumptions_used.grid_export_price_per_kwh
    )

    annual_grid_net_cost = annual_grid_purchase_cost - annual_grid_export_revenue

    # v1 placeholders
    replacement_cost_present_value = 0.0
    salvage_value_present_value = 0.0

    crf = _capital_recovery_factor(
        assumptions_used.real_discount_rate_pct,
        assumptions_used.project_life_years,
    )

    annualized_capital_cost = direct_capital_cost * crf
    annualized_total_cost = (
        annualized_capital_cost
        + annual_fixed_om_cost
        + annual_grid_net_cost
    )

    if crf > EPSILON:
        net_present_cost = (
            annualized_total_cost / crf
            + replacement_cost_present_value
            - salvage_value_present_value
        )
    else:
        net_present_cost = (
            direct_capital_cost
            + (annual_fixed_om_cost + annual_grid_net_cost) * assumptions_used.project_life_years
            + replacement_cost_present_value
            - salvage_value_present_value
        )

    total_served_load_kwh = max(0.0, float(summary.total_served_load_kwh))
    levelized_cost_of_energy = (
        annualized_total_cost / total_served_load_kwh
        if total_served_load_kwh > EPSILON
        else 0.0
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
    )