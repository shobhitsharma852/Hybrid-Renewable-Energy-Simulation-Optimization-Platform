import pytest

from core.components.battery import BatteryComponentConfig
from core.components.converter import ConverterComponentConfig
from core.components.grid import GridComponentConfig
from core.simulation.battery_soc import update_battery_state
from core.simulation.dispatch import run_dispatch_step
from core.simulation.wind_model import _compute_total_losses_pct


def test_wind_losses_are_multiplicative():
    total_losses_pct = _compute_total_losses_pct(
        availability_losses_pct=10.0,
        electrical_losses_pct=10.0,
    )

    assert total_losses_pct == pytest.approx(19.0, abs=1e-6)


def test_grid_export_respects_sale_capacity():
    result = run_dispatch_step(
        load_kw=0.0,
        pv_kw=0.0,
        wind_kw=1200.0,  # AC surplus
        current_battery_soc_pct=50.0,
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
        current_battery_soc_pct=50.0,
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


def test_battery_charge_power_scales_with_quantity_strings():
    one_string = update_battery_state(
        current_soc_pct=50.0,
        surplus_kw=1e9,
        deficit_kw=0.0,
        battery_enabled=True,
        quantity_strings=1,
        nominal_capacity_kwh_per_string=1000.0,
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
        nominal_capacity_kwh_per_string=1000.0,
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
        nominal_capacity_kwh_per_string=1000.0,
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
        nominal_capacity_kwh_per_string=1000.0,
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