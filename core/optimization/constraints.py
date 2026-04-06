from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core.components.config import ComponentsConfig
from core.optimization.design_point import DesignPoint
from core.project import load_project
from core.simulation.battery_soc import update_battery_state
from core.simulation.converter_model import convert_dc_to_ac


EPSILON: float = 1e-9
VERY_LARGE_POWER_KW: float = 1e12


@dataclass(frozen=True)
class OptimizationConstraints:
    # HOMER-like defaults from your screenshot
    max_annual_capacity_shortage_pct: float = 0.0
    min_renewable_fraction_pct: float = 0.0

    reserve_load_pct: float = 10.0
    reserve_annual_peak_pct: float = 0.0
    reserve_solar_pct: float = 80.0
    reserve_wind_pct: float = 50.0

    enforce_operating_reserve: bool = True


@dataclass(frozen=True)
class ConstraintEvaluation:
    annual_capacity_shortage_pct: float
    renewable_fraction_pct: float

    max_required_operating_reserve_kw: float
    min_available_operating_reserve_kw: float
    reserve_shortfall_hours: int

    passes_capacity_shortage: bool
    passes_renewable_fraction: bool
    passes_operating_reserve: bool

    is_feasible: bool
    failure_reasons: tuple[str, ...]


def _safe_non_negative(value: float) -> float:
    return max(0.0, float(value))


def build_default_constraints_for_project(project_name: str) -> OptimizationConstraints:
    """
    Use project annual capacity shortage if present.
    Keep the rest at HOMER-like defaults from the screen you shared.
    """
    project_dir = Path("projects") / project_name

    try:
        project = load_project(project_dir)
        max_shortage = max(0.0, float(project.economics.annual_capacity_shortage))
    except Exception:
        max_shortage = 0.0

    return OptimizationConstraints(
        max_annual_capacity_shortage_pct=max_shortage,
        min_renewable_fraction_pct=0.0,
        reserve_load_pct=10.0,
        reserve_annual_peak_pct=0.0,
        reserve_solar_pct=80.0,
        reserve_wind_pct=50.0,
        enforce_operating_reserve=True,
    )


def _grid_reserve_headroom_kw(record, grid_config) -> float:
    if not getattr(grid_config, "enabled", False):
        return 0.0

    purchase_capacity_kw = getattr(grid_config, "purchase_capacity_kw", None)

    if purchase_capacity_kw is None:
        return VERY_LARGE_POWER_KW

    return max(0.0, float(purchase_capacity_kw) - float(record.grid_import_kw))


def _battery_additional_reserve_ac_kw(
    *,
    record,
    battery_config,
    converter_config,
    design: DesignPoint,
    time_step_hours: float = 1.0,
) -> float:
    if not getattr(battery_config, "enabled", False):
        return 0.0

    if int(design.battery_quantity) <= 0:
        return 0.0

    probe = update_battery_state(
        current_soc_pct=float(record.battery_soc_pct),
        surplus_kw=0.0,
        deficit_kw=VERY_LARGE_POWER_KW,
        battery_enabled=True,
        quantity_strings=max(0, int(design.battery_quantity)),
        nominal_capacity_kwh_per_string=float(
            getattr(battery_config, "nominal_capacity_kwh_per_string", 0.0)
        ),
        nominal_voltage_v=float(getattr(battery_config, "nominal_voltage_v", 0.0)),
        max_charge_current_a=float(getattr(battery_config, "max_charge_current_a", 0.0)),
        max_discharge_current_a=float(getattr(battery_config, "max_discharge_current_a", 0.0)),
        minimum_soc_pct=float(getattr(battery_config, "minimum_state_of_charge_pct", 0.0)),
        roundtrip_efficiency_pct=float(getattr(battery_config, "roundtrip_efficiency_pct", 100.0)),
        time_step_hours=time_step_hours,
    )

    max_battery_dc_kw = max(0.0, float(probe.battery_discharge_kw))
    if max_battery_dc_kw <= EPSILON:
        return 0.0

    inv_result = convert_dc_to_ac(
        requested_dc_power_kw=max_battery_dc_kw,
        converter_config=converter_config,
        selected_inverter_capacity_kw=float(design.converter_capacity_kw),
    )

    max_possible_battery_ac_kw = max(0.0, float(inv_result.output_power_kw))
    current_battery_ac_kw = max(0.0, float(record.battery_discharge_kw))

    return max(0.0, max_possible_battery_ac_kw - current_battery_ac_kw)


def _evaluate_operating_reserve(
    *,
    constraints: OptimizationConstraints,
    components: ComponentsConfig,
    design: DesignPoint,
    simulation_results,
) -> tuple[bool, float, float, int]:
    if not constraints.enforce_operating_reserve:
        return True, 0.0, 0.0, 0

    hourly_records = simulation_results.hourly_records
    if not hourly_records:
        return True, 0.0, 0.0, 0

    annual_peak_load_kw = max(float(r.load_kw) for r in hourly_records)

    max_required_reserve_kw = 0.0
    min_available_reserve_kw = float("inf")
    reserve_shortfall_hours = 0

    for record in hourly_records:
        required_reserve_kw = (
            float(record.load_kw) * constraints.reserve_load_pct / 100.0
            + annual_peak_load_kw * constraints.reserve_annual_peak_pct / 100.0
            + float(record.pv_kw) * constraints.reserve_solar_pct / 100.0
            + float(record.wind_kw) * constraints.reserve_wind_pct / 100.0
        )

        grid_headroom_kw = _grid_reserve_headroom_kw(record, components.grid)

        battery_headroom_kw = _battery_additional_reserve_ac_kw(
            record=record,
            battery_config=components.battery,
            converter_config=components.converter,
            design=design,
            time_step_hours=1.0,
        )

        available_reserve_kw = grid_headroom_kw + battery_headroom_kw

        max_required_reserve_kw = max(max_required_reserve_kw, required_reserve_kw)
        min_available_reserve_kw = min(min_available_reserve_kw, available_reserve_kw)

        if available_reserve_kw + EPSILON < required_reserve_kw:
            reserve_shortfall_hours += 1

    if min_available_reserve_kw == float("inf"):
        min_available_reserve_kw = 0.0

    passes_operating_reserve = reserve_shortfall_hours == 0

    return (
        passes_operating_reserve,
        max_required_reserve_kw,
        min_available_reserve_kw,
        reserve_shortfall_hours,
    )


def evaluate_candidate_constraints(
    *,
    constraints: OptimizationConstraints,
    components: ComponentsConfig,
    design: DesignPoint,
    simulation_results,
) -> ConstraintEvaluation:
    summary = simulation_results.summary

    total_load_kwh = max(0.0, float(summary.total_load_kwh))
    total_unmet_load_kwh = max(0.0, float(summary.total_unmet_load_kwh))

    annual_capacity_shortage_pct = (
        (total_unmet_load_kwh / total_load_kwh) * 100.0
        if total_load_kwh > EPSILON
        else 0.0
    )

    renewable_fraction_pct = max(0.0, float(summary.renewable_fraction) * 100.0)

    passes_capacity_shortage = (
        annual_capacity_shortage_pct <= constraints.max_annual_capacity_shortage_pct + EPSILON
    )

    passes_renewable_fraction = (
        renewable_fraction_pct + EPSILON >= constraints.min_renewable_fraction_pct
    )

    (
        passes_operating_reserve,
        max_required_operating_reserve_kw,
        min_available_operating_reserve_kw,
        reserve_shortfall_hours,
    ) = _evaluate_operating_reserve(
        constraints=constraints,
        components=components,
        design=design,
        simulation_results=simulation_results,
    )

    failure_reasons: list[str] = []

    if not passes_capacity_shortage:
        failure_reasons.append("capacity_shortage_limit_failed")

    if not passes_renewable_fraction:
        failure_reasons.append("minimum_renewable_fraction_failed")

    if not passes_operating_reserve:
        failure_reasons.append("operating_reserve_failed")

    is_feasible = (
        passes_capacity_shortage
        and passes_renewable_fraction
        and passes_operating_reserve
    )

    return ConstraintEvaluation(
        annual_capacity_shortage_pct=annual_capacity_shortage_pct,
        renewable_fraction_pct=renewable_fraction_pct,
        max_required_operating_reserve_kw=max_required_operating_reserve_kw,
        min_available_operating_reserve_kw=min_available_operating_reserve_kw,
        reserve_shortfall_hours=reserve_shortfall_hours,
        passes_capacity_shortage=passes_capacity_shortage,
        passes_renewable_fraction=passes_renewable_fraction,
        passes_operating_reserve=passes_operating_reserve,
        is_feasible=is_feasible,
        failure_reasons=tuple(failure_reasons),
    )