import pytest

from core.components.battery import BatteryComponentConfig
from core.components.converter import ConverterComponentConfig
from core.components.grid import GridComponentConfig
from core.controller.engine import run_controller_step
from core.economics.evaluator import EconomicAssumptions
from core.optimization.optimizer import run_optimization_sweep, save_optimization_sweep_outputs
from core.simulation.battery_soc import BatteryState, update_battery_state
from core.simulation.dispatch import run_dispatch_step
from core.simulation.wind_model import _compute_total_losses_pct


def test_wind_losses_are_multiplicative():
    total_losses_pct = _compute_total_losses_pct(
        availability_losses_pct=10.0,
        electrical_losses_pct=10.0,
    )

    assert total_losses_pct == pytest.approx(19.0, abs=1e-6)


def test_grid_export_respects_sale_capacity():
    # Battery disabled: effective_capacity_kwh=0.0 is harmless but keeps the
    # BatteryState API consistent — dispatch will skip battery logic when disabled.
    result = run_dispatch_step(
        load_kw=0.0,
        pv_kw=0.0,
        wind_kw=1200.0,  # AC surplus
        battery_state=BatteryState(soc_pct=50.0, effective_capacity_kwh=0.0),
        battery_config=BatteryComponentConfig(enabled=False),
        converter_config=ConverterComponentConfig(),
        grid_config=GridComponentConfig(
            enabled=True,
            sale_capacity_kw=700.0,
            purchase_capacity_kw=1000.0,
        ),
        selected_battery_quantity=0,
        selected_converter_capacity_kw=1000.0,
        time_step_hours=1.0,
    )

    assert result.grid_export_kw == pytest.approx(700.0, abs=1e-6)
    assert result.excess_energy_kw == pytest.approx(500.0, abs=1e-6)
    assert result.unmet_load_kw == pytest.approx(0.0, abs=1e-6)


def test_grid_import_respects_purchase_capacity():
    result = run_dispatch_step(
        load_kw=1500.0,
        pv_kw=0.0,
        wind_kw=0.0,
        battery_state=BatteryState(soc_pct=50.0, effective_capacity_kwh=0.0),
        battery_config=BatteryComponentConfig(enabled=False),
        converter_config=ConverterComponentConfig(),
        grid_config=GridComponentConfig(
            enabled=True,
            sale_capacity_kw=700.0,
            purchase_capacity_kw=1000.0,
        ),
        selected_battery_quantity=0,
        selected_converter_capacity_kw=1000.0,
        time_step_hours=1.0,
    )

    assert result.grid_import_kw == pytest.approx(1000.0, abs=1e-6)
    assert result.unmet_load_kw == pytest.approx(500.0, abs=1e-6)
    assert result.served_load_kw == pytest.approx(1000.0, abs=1e-6)


def test_explicit_renewable_first_dispatch_matches_default():
    kwargs = dict(
        load_kw=400.0,
        pv_kw=300.0,
        wind_kw=100.0,
        battery_state=BatteryState(soc_pct=50.0, effective_capacity_kwh=0.0),
        battery_config=BatteryComponentConfig(enabled=False),
        converter_config=ConverterComponentConfig(inverter_efficiency_pct=95.0),
        grid_config=GridComponentConfig(
            enabled=True,
            sale_capacity_kw=700.0,
            purchase_capacity_kw=1000.0,
        ),
        selected_battery_quantity=0,
        selected_converter_capacity_kw=250.0,
        time_step_hours=1.0,
    )

    default_result = run_dispatch_step(**kwargs)
    explicit_result = run_dispatch_step(**kwargs, dispatch_strategy="renewable_first")

    assert explicit_result == default_result


def test_renewable_first_controller_matches_dispatch_executor():
    kwargs = dict(
        load_kw=400.0,
        pv_kw=300.0,
        wind_kw=100.0,
        battery_state=BatteryState(soc_pct=50.0, effective_capacity_kwh=0.0),
        battery_config=BatteryComponentConfig(enabled=False),
        converter_config=ConverterComponentConfig(inverter_efficiency_pct=95.0),
        grid_config=GridComponentConfig(
            enabled=True,
            sale_capacity_kw=700.0,
            purchase_capacity_kw=1000.0,
        ),
        selected_battery_quantity=0,
        selected_converter_capacity_kw=250.0,
        time_step_hours=1.0,
    )

    controller_result = run_controller_step(**kwargs, dispatch_strategy="renewable_first")
    dispatch_result = run_dispatch_step(**kwargs, dispatch_strategy="renewable_first")

    assert controller_result == dispatch_result


def test_unknown_dispatch_strategy_fails_fast():
    with pytest.raises(ValueError, match="dispatch_strategy"):
        run_dispatch_step(
            load_kw=0.0,
            pv_kw=0.0,
            wind_kw=0.0,
            battery_state=BatteryState(soc_pct=50.0, effective_capacity_kwh=0.0),
            battery_config=BatteryComponentConfig(enabled=False),
            converter_config=ConverterComponentConfig(),
            grid_config=GridComponentConfig(enabled=True),
            selected_battery_quantity=0,
            selected_converter_capacity_kw=0.0,
            time_step_hours=1.0,
            dispatch_strategy="grid_first",
        )


def test_battery_charge_power_scales_with_quantity_strings():
    # effective_capacity_kwh = nominal_capacity_kwh_per_string × quantity_strings.
    # Power limits (V × I × n_strings) scale with quantity_strings regardless of
    # capacity, so we can verify scaling with any capacity that fits the SOC range.
    one_string = update_battery_state(
        current_soc_pct=50.0,
        surplus_kw=1e9,
        deficit_kw=0.0,
        battery_enabled=True,
        quantity_strings=1,
        effective_capacity_kwh=1000.0,   # 1 string × 1000 kWh/string
        nominal_voltage_v=600.0,
        max_charge_current_a=100.0,
        max_discharge_current_a=100.0,
        minimum_soc_pct=20.0,
        roundtrip_efficiency_pct=100.0,
        time_step_hours=1.0,
    )

    five_strings = update_battery_state(
        current_soc_pct=50.0,
        surplus_kw=1e9,
        deficit_kw=0.0,
        battery_enabled=True,
        quantity_strings=5,
        effective_capacity_kwh=5000.0,   # 5 strings × 1000 kWh/string
        nominal_voltage_v=600.0,
        max_charge_current_a=100.0,
        max_discharge_current_a=100.0,
        minimum_soc_pct=20.0,
        roundtrip_efficiency_pct=100.0,
        time_step_hours=1.0,
    )

    assert one_string.max_charge_power_kw == pytest.approx(60.0, abs=1e-6)
    assert five_strings.max_charge_power_kw == pytest.approx(300.0, abs=1e-6)
    assert five_strings.max_charge_power_kw == pytest.approx(
        5 * one_string.max_charge_power_kw, abs=1e-6
    )


def test_battery_discharge_power_scales_with_quantity_strings():
    one_string = update_battery_state(
        current_soc_pct=80.0,
        surplus_kw=0.0,
        deficit_kw=1e9,
        battery_enabled=True,
        quantity_strings=1,
        effective_capacity_kwh=1000.0,   # 1 string × 1000 kWh/string
        nominal_voltage_v=600.0,
        max_charge_current_a=100.0,
        max_discharge_current_a=100.0,
        minimum_soc_pct=20.0,
        roundtrip_efficiency_pct=100.0,
        time_step_hours=1.0,
    )

    five_strings = update_battery_state(
        current_soc_pct=80.0,
        surplus_kw=0.0,
        deficit_kw=1e9,
        battery_enabled=True,
        quantity_strings=5,
        effective_capacity_kwh=5000.0,   # 5 strings × 1000 kWh/string
        nominal_voltage_v=600.0,
        max_charge_current_a=100.0,
        max_discharge_current_a=100.0,
        minimum_soc_pct=20.0,
        roundtrip_efficiency_pct=100.0,
        time_step_hours=1.0,
    )

    assert one_string.max_discharge_power_kw == pytest.approx(60.0, abs=1e-6)
    assert five_strings.max_discharge_power_kw == pytest.approx(300.0, abs=1e-6)
    assert five_strings.max_discharge_power_kw == pytest.approx(
        5 * one_string.max_discharge_power_kw, abs=1e-6
    )


def test_optimization_dataframe_includes_output_decision_metrics():
    result = run_optimization_sweep(
        "Test_1",
        save_outputs=False,
        economic_assumptions=EconomicAssumptions(
            project_life_years=25.0,
            real_discount_rate_pct=8.0,
            grid_purchase_price_per_kwh=0.1,
            grid_export_price_per_kwh=0.05,
        ),
    )

    df = result.to_dataframe()

    expected_columns = {
        "annual_capacity_shortage_pct",
        "renewable_fraction_pct",
        "replacement_cost_present_value",
        "salvage_value_present_value",
        "annualized_total_cost",
        "net_present_cost",
        "levelized_cost_of_energy",
        "energy_balance_passes",
        "energy_balance_failed_rows",
        "energy_balance_max_abs_mismatch_kw",
    }

    assert expected_columns.issubset(set(df.columns))
    assert bool(df.iloc[0]["energy_balance_passes"])
    assert int(df.iloc[0]["energy_balance_failed_rows"]) == 0


def test_optimization_best_solution_summary_identifies_key_winners():
    result = run_optimization_sweep(
        "Test_1",
        save_outputs=False,
        economic_assumptions=EconomicAssumptions(
            project_life_years=25.0,
            real_discount_rate_pct=8.0,
            grid_purchase_price_per_kwh=0.1,
            grid_export_price_per_kwh=0.05,
        ),
    )

    summary = result.best_solution_summary()

    assert summary["total_candidates"] == len(result.candidate_results)
    assert summary["successful_runs"] >= 1
    assert summary["feasible_candidates"] >= 1
    assert summary["best_feasible"] is not None
    assert summary["lowest_npc"] is not None
    assert summary["lowest_lcoe"] is not None
    assert summary["technical_best"] is not None

    best_feasible = summary["best_feasible"]
    assert isinstance(best_feasible, dict)
    assert bool(best_feasible["is_feasible"])
    assert bool(best_feasible["energy_balance_passes"])
