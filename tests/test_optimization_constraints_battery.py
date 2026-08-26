from core.components.battery import BatteryComponentConfig
from core.components.config import ComponentsConfig
from core.components.converter import ConverterComponentConfig
from core.components.grid import GridComponentConfig
from core.optimization.constraints import (
    OptimizationConstraints,
    evaluate_candidate_constraints,
)
from core.optimization.design_point import DesignPoint
from core.simulation.results import (
    SimulationTimestepRecord,
    SimulationResults,
    SimulationSummary,
)


def test_battery_operating_reserve_probe_uses_effective_capacity():
    components = ComponentsConfig(
        battery=BatteryComponentConfig(
            enabled=True,
            quantity_options=[1],
            initial_state_of_charge_pct=80.0,
            minimum_state_of_charge_pct=20.0,
        ),
        converter=ConverterComponentConfig(
            enabled=True,
            capacity_kw_options=[1000.0],
            inverter_efficiency_pct=95.0,
        ),
        grid=GridComponentConfig(enabled=False),
    )
    design = DesignPoint(
        pv_capacity_kw=0.0,
        wind_quantity=0,
        battery_quantity=1,
        converter_capacity_kw=1000.0,
    )
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
                battery_soc_pct=80.0,
                grid_import_kw=0.0,
                grid_export_kw=0.0,
                effective_capacity_kwh=1000.0,
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
            reserve_load_pct=10.0,
            reserve_solar_pct=0.0,
            reserve_wind_pct=0.0,
            enforce_operating_reserve=True,
        ),
        components=components,
        design=design,
        simulation_results=results,
    )

    assert evaluation.passes_operating_reserve is True
    assert evaluation.min_available_operating_reserve_kw > 10.0
