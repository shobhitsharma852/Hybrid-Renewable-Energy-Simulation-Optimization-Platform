from pathlib import Path
import tempfile

import pytest

from core.components.pv import (
    PVMPPTSettings,
    PVOrientationSettings,
    PVTemperatureSettings,
    PVComponentConfig,
)
from core.components.wind import (
    WindPowerCurveSettings,
    WindLossSettings,
    WindMaintenanceSettings,
    WindComponentConfig,
)
from core.components.battery import BatteryComponentConfig
from core.components.converter import ConverterComponentConfig
from core.components.grid import GridComponentConfig

from core.components.config import (
    ComponentsConfig,
    components_to_dict,
    components_from_dict,
    save_components,
    load_components,
    components_file_path,
)


# ============================================================
# HELPERS
# ============================================================

def make_valid_pv() -> PVComponentConfig:
    return PVComponentConfig(
        enabled=True,
        use_search_space=True,
        capacity_kw_options=[0.0, 1000.0, 2000.0],
        capital_cost_per_kw=2500.0,
        replacement_cost_per_kw=2500.0,
        om_cost_per_kw_per_year=10.0,
        lifetime_years=25,
        derating_factor=0.80,
        bus="DC",
        mppt=PVMPPTSettings(
            enabled=False,
            lifetime_years=15,
            sizing_mode="ratio",
            pv_to_conv_ratio_options=[1.0, 1.1],
            capacity_kw_options=[1000.0],
            efficiency_pct=95.0,
            use_efficiency_table=False,
        ),
        orientation=PVOrientationSettings(
            enabled=True,
            ground_reflectance_pct=20.0,
            tracking_system="no_tracking",
            use_default_slope=True,
            panel_slope_deg=None,
            use_default_azimuth=True,
            panel_azimuth_deg=None,
        ),
        temperature=PVTemperatureSettings(
            enabled=True,
            temperature_coefficient_pct_per_degC=-0.5,
            nominal_operating_cell_temp_c=47.0,
            efficiency_stc_pct=13.0,
        ),
    )


def make_valid_wind() -> WindComponentConfig:
    return WindComponentConfig(
        enabled=True,
        use_search_space=True,
        turbine_model_name="Generic 1.5 MW",
        rated_capacity_kw=1500.0,
        quantity_options=[0, 1, 2],
        capital_cost_per_turbine=3_000_000.0,
        replacement_cost_per_turbine=3_000_000.0,
        om_cost_per_turbine_per_year=30_000.0,
        lifetime_years=20,
        hub_height_m=80.0,
        consider_temperature_effects=False,
        bus="AC",
        power_curve=WindPowerCurveSettings(
            enabled=True,
            wind_speed_points_mps=[
                0.0, 4.0, 4.01, 5.0, 6.0, 7.0, 8.0, 9.0,
                10.0, 11.0, 12.0, 13.0, 14.0, 16.0, 25.0
            ],
            power_output_points_kw=[
                0.0, 0.0, 80.0, 150.0, 250.0, 400.0, 600.0, 850.0,
                1150.0, 1350.0, 1450.0, 1490.0, 1500.0, 1500.0, 0.0
            ],
        ),
        losses=WindLossSettings(
            enabled=True,
            availability_losses_pct=0.0,
            turbine_performance_losses_pct=0.0,
            environmental_losses_pct=0.0,
            other_losses_pct=0.0,
            wake_effects_losses_pct=0.0,
            electrical_losses_pct=0.0,
            curtailment_losses_pct=0.0,
        ),
        maintenance=WindMaintenanceSettings(
            enabled=False,
        ),
    )


def make_valid_battery() -> BatteryComponentConfig:
    return BatteryComponentConfig(
        enabled=True,
        use_search_space=True,
        battery_model_name="Generic 1MWh Li-Ion",
        quantity_options=[0, 5, 10],
        nominal_voltage_v=600.0,
        nominal_capacity_kwh_per_string=1000.0,
        roundtrip_efficiency_pct=90.0,
        max_charge_current_a=1670.0,
        max_discharge_current_a=5000.0,
        string_size=1,
        initial_state_of_charge_pct=100.0,
        minimum_state_of_charge_pct=20.0,
        throughput_kwh=3_000_000.0,
        capital_cost_per_string=700_000.0,
        replacement_cost_per_string=700_000.0,
        om_cost_per_string_per_year=10_000.0,
        lifetime_years=15,
    )


def make_valid_converter() -> ConverterComponentConfig:
    return ConverterComponentConfig(
        enabled=True,
        use_search_space=True,
        converter_model_name="System Converter",
        capacity_kw_options=[0.0, 1000.0, 2000.0],
        capital_cost_per_kw=300.0,
        replacement_cost_per_kw=300.0,
        om_cost_per_kw_per_year=0.0,
        inverter_lifetime_years=15,
        inverter_efficiency_pct=95.0,
        rectifier_relative_capacity_pct=100.0,
        rectifier_efficiency_pct=95.0,
        parallel_with_ac_generator=False,
    )


def make_valid_grid() -> GridComponentConfig:
    return GridComponentConfig(
        enabled=True,
        grid_power_price_per_kwh=0.10,
        grid_sellback_price_per_kwh=0.05,
        sale_capacity_kw=999_999.0,
        purchase_capacity_kw=999_999.0,
        net_metering_enabled=False,
        co2_emissions_g_per_kwh=632.0,
    )


def make_valid_components_config() -> ComponentsConfig:
    return ComponentsConfig(
        pv=make_valid_pv(),
        wind=make_valid_wind(),
        battery=make_valid_battery(),
        converter=make_valid_converter(),
        grid=make_valid_grid(),
    )


# ============================================================
# DICT CONVERSION TESTS
# ============================================================

def test_components_to_dict_returns_expected_top_level_keys():
    cfg = make_valid_components_config()
    data = components_to_dict(cfg)

    assert set(data.keys()) == {"pv", "wind", "battery", "converter", "grid"}


def test_components_from_dict_roundtrip():
    cfg = make_valid_components_config()
    data = components_to_dict(cfg)
    cfg2 = components_from_dict(data)

    assert cfg2.pv.capacity_kw_options == [0.0, 1000.0, 2000.0]
    assert cfg2.wind.turbine_model_name == "Generic 1.5 MW"
    assert cfg2.battery.battery_model_name == "Generic 1MWh Li-Ion"
    assert cfg2.converter.converter_model_name == "System Converter"
    assert cfg2.grid.grid_power_price_per_kwh == 0.10


# ============================================================
# FILE PATH TEST
# ============================================================

def test_components_file_path_returns_components_json():
    with tempfile.TemporaryDirectory() as tmp:
        path = components_file_path(tmp)
        assert path == Path(tmp) / "components.json"


# ============================================================
# SAVE / LOAD TESTS
# ============================================================

def test_save_and_load_components_roundtrip():
    cfg = make_valid_components_config()

    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / "project_a"

        save_path = save_components(cfg, folder)
        assert save_path.exists()
        assert save_path.name == "components.json"

        cfg2 = load_components(folder)

    assert cfg2.pv.bus == "DC"
    assert cfg2.wind.bus == "AC"
    assert cfg2.battery.roundtrip_efficiency_pct == 90.0
    assert cfg2.converter.inverter_efficiency_pct == 95.0
    assert cfg2.grid.co2_emissions_g_per_kwh == 632.0


def test_load_components_fails_if_file_missing():
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / "missing_project"

        with pytest.raises(FileNotFoundError, match="components.json not found"):
            load_components(folder)


# ============================================================
# VALIDATION THROUGH ROOT SAVE
# ============================================================

def test_save_components_fails_if_nested_component_invalid():
    bad_pv = PVComponentConfig(
        **{
            **make_valid_pv().__dict__,
            "derating_factor": 1.5,
        }
    )

    cfg = ComponentsConfig(
        pv=bad_pv,
        wind=make_valid_wind(),
        battery=make_valid_battery(),
        converter=make_valid_converter(),
        grid=make_valid_grid(),
    )

    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / "project_b"

        with pytest.raises(ValueError, match="PV derating_factor must be between 0 and 1"):
            save_components(cfg, folder)