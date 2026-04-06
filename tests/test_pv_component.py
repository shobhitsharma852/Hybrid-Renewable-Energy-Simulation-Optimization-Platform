import pytest

from core.components.pv import (
    PVMPPTSettings,
    PVOrientationSettings,
    PVTemperatureSettings,
    PVComponentConfig,
    validate_pv_component,
)


# ============================================================
# HELPERS
# ============================================================

def make_valid_pv() -> PVComponentConfig:
    return PVComponentConfig(
        enabled=True,
        use_search_space=True,
        capacity_kw_options=[0.0, 1000.0, 2000.0, 3000.0],
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
            pv_to_conv_ratio_options=[1.0, 1.1, 1.2],
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


# ============================================================
# MAIN SUCCESS TEST
# ============================================================

def test_validate_pv_component_passes_for_valid_data():
    pv = make_valid_pv()
    validate_pv_component(pv)


# ============================================================
# BASIC PV TESTS
# ============================================================

def test_validate_pv_component_fails_if_capacity_options_empty():
    pv = make_valid_pv()
    pv = PVComponentConfig(
        **{**pv.__dict__, "capacity_kw_options": []}
    )
    with pytest.raises(ValueError, match="PV capacity_kw_options cannot be empty"):
        validate_pv_component(pv)


def test_validate_pv_component_fails_if_capacity_option_negative():
    pv = make_valid_pv()
    pv = PVComponentConfig(
        **{**pv.__dict__, "capacity_kw_options": [0.0, -1000.0]}
    )
    with pytest.raises(ValueError, match="PV capacity_kw_options cannot contain negative values"):
        validate_pv_component(pv)


def test_validate_pv_component_fails_if_derating_invalid():
    pv = make_valid_pv()
    pv = PVComponentConfig(
        **{**pv.__dict__, "derating_factor": 1.5}
    )
    with pytest.raises(ValueError, match="PV derating_factor must be between 0 and 1"):
        validate_pv_component(pv)


def test_validate_pv_component_fails_if_bus_invalid():
    pv = make_valid_pv()
    pv = PVComponentConfig(
        **{**pv.__dict__, "bus": "XYZ"}
    )
    with pytest.raises(ValueError, match="PV bus must be 'AC' or 'DC'"):
        validate_pv_component(pv)


def test_validate_pv_component_fails_if_lifetime_invalid():
    pv = make_valid_pv()
    pv = PVComponentConfig(
        **{**pv.__dict__, "lifetime_years": 0}
    )
    with pytest.raises(ValueError, match="PV lifetime_years must be > 0"):
        validate_pv_component(pv)


# ============================================================
# MPPT TESTS
# ============================================================

def test_validate_pv_component_fails_if_mppt_sizing_mode_invalid():
    pv = make_valid_pv()
    bad_mppt = PVMPPTSettings(
        enabled=True,
        lifetime_years=15,
        sizing_mode="wrong_mode",
        pv_to_conv_ratio_options=[1.0],
        capacity_kw_options=[1000.0],
        efficiency_pct=95.0,
        use_efficiency_table=False,
    )
    pv = PVComponentConfig(**{**pv.__dict__, "mppt": bad_mppt})

    with pytest.raises(ValueError, match="PV MPPT sizing_mode must be 'ratio' or 'capacity'"):
        validate_pv_component(pv)


def test_validate_pv_component_fails_if_mppt_efficiency_invalid():
    pv = make_valid_pv()
    bad_mppt = PVMPPTSettings(
        enabled=True,
        lifetime_years=15,
        sizing_mode="ratio",
        pv_to_conv_ratio_options=[1.0],
        capacity_kw_options=[1000.0],
        efficiency_pct=120.0,
        use_efficiency_table=False,
    )
    pv = PVComponentConfig(**{**pv.__dict__, "mppt": bad_mppt})

    with pytest.raises(ValueError, match="PV MPPT efficiency_pct must be between 0 and 100"):
        validate_pv_component(pv)


# ============================================================
# ORIENTATION TESTS
# ============================================================

def test_validate_pv_component_fails_if_tracking_invalid():
    pv = make_valid_pv()
    bad_orientation = PVOrientationSettings(
        enabled=True,
        ground_reflectance_pct=20.0,
        tracking_system="bad_tracking",
        use_default_slope=True,
        panel_slope_deg=None,
        use_default_azimuth=True,
        panel_azimuth_deg=None,
    )
    pv = PVComponentConfig(**{**pv.__dict__, "orientation": bad_orientation})

    with pytest.raises(ValueError, match="PV tracking_system must be one of: no_tracking, single_axis, dual_axis"):
        validate_pv_component(pv)


def test_validate_pv_component_fails_if_ground_reflectance_invalid():
    pv = make_valid_pv()
    bad_orientation = PVOrientationSettings(
        enabled=True,
        ground_reflectance_pct=120.0,
        tracking_system="no_tracking",
        use_default_slope=True,
        panel_slope_deg=None,
        use_default_azimuth=True,
        panel_azimuth_deg=None,
    )
    pv = PVComponentConfig(**{**pv.__dict__, "orientation": bad_orientation})

    with pytest.raises(ValueError, match="PV ground_reflectance_pct must be between 0 and 100"):
        validate_pv_component(pv)


def test_validate_pv_component_fails_if_manual_slope_missing():
    pv = make_valid_pv()
    bad_orientation = PVOrientationSettings(
        enabled=True,
        ground_reflectance_pct=20.0,
        tracking_system="no_tracking",
        use_default_slope=False,
        panel_slope_deg=None,
        use_default_azimuth=True,
        panel_azimuth_deg=None,
    )
    pv = PVComponentConfig(**{**pv.__dict__, "orientation": bad_orientation})

    with pytest.raises(ValueError, match="PV panel_slope_deg is required when use_default_slope is False"):
        validate_pv_component(pv)


def test_validate_pv_component_fails_if_manual_azimuth_missing():
    pv = make_valid_pv()
    bad_orientation = PVOrientationSettings(
        enabled=True,
        ground_reflectance_pct=20.0,
        tracking_system="no_tracking",
        use_default_slope=True,
        panel_slope_deg=None,
        use_default_azimuth=False,
        panel_azimuth_deg=None,
    )
    pv = PVComponentConfig(**{**pv.__dict__, "orientation": bad_orientation})

    with pytest.raises(ValueError, match="PV panel_azimuth_deg is required when use_default_azimuth is False"):
        validate_pv_component(pv)


# ============================================================
# TEMPERATURE TESTS
# ============================================================

def test_validate_pv_component_fails_if_temperature_coefficient_invalid():
    pv = make_valid_pv()
    bad_temp = PVTemperatureSettings(
        enabled=True,
        temperature_coefficient_pct_per_degC=-10.0,
        nominal_operating_cell_temp_c=47.0,
        efficiency_stc_pct=13.0,
    )
    pv = PVComponentConfig(**{**pv.__dict__, "temperature": bad_temp})

    with pytest.raises(ValueError, match="PV temperature_coefficient_pct_per_degC looks unrealistic"):
        validate_pv_component(pv)


def test_validate_pv_component_fails_if_noct_invalid():
    pv = make_valid_pv()
    bad_temp = PVTemperatureSettings(
        enabled=True,
        temperature_coefficient_pct_per_degC=-0.5,
        nominal_operating_cell_temp_c=0.0,
        efficiency_stc_pct=13.0,
    )
    pv = PVComponentConfig(**{**pv.__dict__, "temperature": bad_temp})

    with pytest.raises(ValueError, match="PV nominal_operating_cell_temp_c must be > 0"):
        validate_pv_component(pv)


def test_validate_pv_component_fails_if_efficiency_stc_invalid():
    pv = make_valid_pv()
    bad_temp = PVTemperatureSettings(
        enabled=True,
        temperature_coefficient_pct_per_degC=-0.5,
        nominal_operating_cell_temp_c=47.0,
        efficiency_stc_pct=150.0,
    )
    pv = PVComponentConfig(**{**pv.__dict__, "temperature": bad_temp})

    with pytest.raises(ValueError, match="PV efficiency_stc_pct must be between 0 and 100"):
        validate_pv_component(pv)