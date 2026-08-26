from types import SimpleNamespace

import pytest

from core.components.config import ComponentsConfig
from core.components.grid import GridComponentConfig
from core.economics.evaluator import EconomicAssumptions, evaluate_candidate_economics
from core.optimization.constraints import (
    OptimizationConstraints,
    evaluate_candidate_constraints,
)
from core.optimization.design_point import DesignPoint
from core.simulation.results import (
    SimulationResults,
    SimulationSummary,
    SimulationTimestepRecord,
)


def _zero_design() -> DesignPoint:
    return DesignPoint(
        pv_capacity_kw=0.0,
        wind_quantity=0,
        battery_quantity=0,
        converter_capacity_kw=0.0,
    )


def test_capacity_shortage_includes_operating_reserve_shortfall():
    components = ComponentsConfig(grid=GridComponentConfig(enabled=False))
    results = SimulationResults(
        timestep_records=[
            SimulationTimestepRecord(
                step_index=0,
                timestamp=None,
                load_kw=100.0,
                pv_kw=0.0,
                wind_kw=0.0,
                renewable_kw=0.0,
                served_load_kw=100.0,
                excess_energy_kw=0.0,
                unmet_load_kw=0.0,
                battery_charge_kw=0.0,
                battery_discharge_kw=0.0,
                battery_discharge_dc_kw=0.0,
                battery_soc_pct=0.0,
                grid_import_kw=0.0,
                grid_export_kw=0.0,
            )
        ],
        summary=SimulationSummary(
            total_load_kwh=100.0,
            total_served_load_kwh=100.0,
            total_unmet_load_kwh=0.0,
        ),
    )

    evaluation = evaluate_candidate_constraints(
        constraints=OptimizationConstraints(
            max_annual_capacity_shortage_pct=10.0,
            reserve_load_pct=10.0,
            reserve_annual_peak_pct=0.0,
            reserve_solar_pct=0.0,
            reserve_wind_pct=0.0,
            enforce_operating_reserve=True,
        ),
        components=components,
        design=_zero_design(),
        simulation_results=results,
    )

    assert evaluation.total_reserve_shortfall_kwh == pytest.approx(10.0)
    assert evaluation.total_capacity_shortage_kwh == pytest.approx(10.0)
    assert evaluation.annual_capacity_shortage_pct == pytest.approx(10.0)
    assert evaluation.passes_operating_reserve is False
    assert evaluation.is_feasible is True


def test_lcoe_denominator_excludes_grid_sales():
    components = ComponentsConfig()
    assumptions = EconomicAssumptions(
        project_life_years=25.0,
        real_discount_rate_pct=8.0,
        grid_purchase_price_per_kwh=0.0,
        grid_export_price_per_kwh=0.0,
    )
    costed_design = DesignPoint(
        pv_capacity_kw=100.0,
        wind_quantity=0,
        battery_quantity=0,
        converter_capacity_kw=0.0,
    )

    def evaluate(export_kwh: float):
        summary = SimpleNamespace(
            total_grid_import_kwh=0.0,
            total_grid_export_kwh=export_kwh,
            total_served_load_kwh=1000.0,
            total_battery_throughput_kwh=0.0,
        )
        return evaluate_candidate_economics(
            project_name="unused",
            components=components,
            design=costed_design,
            simulation_results=SimpleNamespace(summary=summary),
            assumptions=assumptions,
        )

    no_export = evaluate(0.0)
    with_export = evaluate(500.0)

    assert with_export.annualized_total_cost == pytest.approx(
        no_export.annualized_total_cost
    )
    assert with_export.levelized_cost_of_energy == pytest.approx(
        no_export.levelized_cost_of_energy
    )
