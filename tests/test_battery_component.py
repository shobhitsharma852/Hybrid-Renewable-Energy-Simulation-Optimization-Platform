import pytest

from core.components.battery import (
    BatteryComponentConfig,
    validate_battery_component,
)


# ============================================================
# HELPERS
# ============================================================

def make_valid_battery() -> BatteryComponentConfig:
    return BatteryComponentConfig(
        enabled=True,
        use_search_space=True,
        battery_model_name="Generic 1MWh Li-Ion",
        quantity_options=[0, 5, 10, 15, 20],
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


# ============================================================
# MAIN SUCCESS TEST
# ============================================================

def test_validate_battery_component_passes_for_valid_data():
    battery = make_valid_battery()
    validate_battery_component(battery)


# ============================================================
# MODEL NAME TESTS
# ============================================================

def test_validate_battery_component_fails_if_name_empty():
    battery = make_valid_battery()
    battery = BatteryComponentConfig(**{**battery.__dict__, "battery_model_name": ""})

    with pytest.raises(ValueError, match="Battery battery_model_name cannot be empty"):
        validate_battery_component(battery)


# ============================================================
# SEARCH SPACE TESTS
# ============================================================

def test_validate_battery_component_fails_if_quantity_options_empty():
    battery = make_valid_battery()
    battery = BatteryComponentConfig(**{**battery.__dict__, "quantity_options": []})

    with pytest.raises(ValueError, match="Battery quantity_options cannot be empty"):
        validate_battery_component(battery)


def test_validate_battery_component_fails_if_quantity_options_negative():
    battery = make_valid_battery()
    battery = BatteryComponentConfig(**{**battery.__dict__, "quantity_options": [0, 5, -1]})

    with pytest.raises(ValueError, match="Battery quantity_options cannot contain negative values"):
        validate_battery_component(battery)


# ============================================================
# TECHNICAL PARAMETER TESTS
# ============================================================

def test_validate_battery_component_fails_if_nominal_voltage_invalid():
    battery = make_valid_battery()
    battery = BatteryComponentConfig(**{**battery.__dict__, "nominal_voltage_v": 0.0})

    with pytest.raises(ValueError, match="Battery nominal_voltage_v must be > 0"):
        validate_battery_component(battery)


def test_validate_battery_component_fails_if_nominal_capacity_invalid():
    battery = make_valid_battery()
    battery = BatteryComponentConfig(
        **{**battery.__dict__, "nominal_capacity_kwh_per_string": 0.0}
    )

    with pytest.raises(ValueError, match="Battery nominal_capacity_kwh_per_string must be > 0"):
        validate_battery_component(battery)


def test_validate_battery_component_fails_if_roundtrip_efficiency_invalid_low():
    battery = make_valid_battery()
    battery = BatteryComponentConfig(**{**battery.__dict__, "roundtrip_efficiency_pct": 0.0})

    with pytest.raises(
        ValueError,
        match="Battery roundtrip_efficiency_pct must be between 0 and 100",
    ):
        validate_battery_component(battery)


def test_validate_battery_component_fails_if_roundtrip_efficiency_invalid_high():
    battery = make_valid_battery()
    battery = BatteryComponentConfig(**{**battery.__dict__, "roundtrip_efficiency_pct": 120.0})

    with pytest.raises(
        ValueError,
        match="Battery roundtrip_efficiency_pct must be between 0 and 100",
    ):
        validate_battery_component(battery)


def test_validate_battery_component_fails_if_max_charge_current_invalid():
    battery = make_valid_battery()
    battery = BatteryComponentConfig(**{**battery.__dict__, "max_charge_current_a": 0.0})

    with pytest.raises(ValueError, match="Battery max_charge_current_a must be > 0"):
        validate_battery_component(battery)


def test_validate_battery_component_fails_if_max_discharge_current_invalid():
    battery = make_valid_battery()
    battery = BatteryComponentConfig(**{**battery.__dict__, "max_discharge_current_a": 0.0})

    with pytest.raises(ValueError, match="Battery max_discharge_current_a must be > 0"):
        validate_battery_component(battery)


def test_validate_battery_component_fails_if_string_size_invalid():
    battery = make_valid_battery()
    battery = BatteryComponentConfig(**{**battery.__dict__, "string_size": 0})

    with pytest.raises(ValueError, match="Battery string_size must be > 0"):
        validate_battery_component(battery)


def test_validate_battery_component_fails_if_initial_soc_invalid():
    battery = make_valid_battery()
    battery = BatteryComponentConfig(**{**battery.__dict__, "initial_state_of_charge_pct": 120.0})

    with pytest.raises(
        ValueError,
        match="Battery initial_state_of_charge_pct must be between 0 and 100",
    ):
        validate_battery_component(battery)


def test_validate_battery_component_fails_if_minimum_soc_invalid():
    battery = make_valid_battery()
    battery = BatteryComponentConfig(**{**battery.__dict__, "minimum_state_of_charge_pct": -5.0})

    with pytest.raises(
        ValueError,
        match="Battery minimum_state_of_charge_pct must be between 0 and 100",
    ):
        validate_battery_component(battery)


def test_validate_battery_component_fails_if_initial_soc_less_than_minimum_soc():
    battery = make_valid_battery()
    battery = BatteryComponentConfig(
        **{
            **battery.__dict__,
            "initial_state_of_charge_pct": 10.0,
            "minimum_state_of_charge_pct": 20.0,
        }
    )

    with pytest.raises(
        ValueError,
        match="Battery initial_state_of_charge_pct must be >= minimum_state_of_charge_pct",
    ):
        validate_battery_component(battery)


def test_validate_battery_component_fails_if_throughput_negative():
    battery = make_valid_battery()
    battery = BatteryComponentConfig(**{**battery.__dict__, "throughput_kwh": -1.0})

    with pytest.raises(ValueError, match="Battery throughput_kwh cannot be negative"):
        validate_battery_component(battery)


# ============================================================
# ECONOMIC PARAMETER TESTS
# ============================================================

def test_validate_battery_component_fails_if_capital_cost_negative():
    battery = make_valid_battery()
    battery = BatteryComponentConfig(**{**battery.__dict__, "capital_cost_per_string": -1.0})

    with pytest.raises(ValueError, match="Battery capital_cost_per_string cannot be negative"):
        validate_battery_component(battery)


def test_validate_battery_component_fails_if_replacement_cost_negative():
    battery = make_valid_battery()
    battery = BatteryComponentConfig(
        **{**battery.__dict__, "replacement_cost_per_string": -1.0}
    )

    with pytest.raises(ValueError, match="Battery replacement_cost_per_string cannot be negative"):
        validate_battery_component(battery)


def test_validate_battery_component_fails_if_om_cost_negative():
    battery = make_valid_battery()
    battery = BatteryComponentConfig(
        **{**battery.__dict__, "om_cost_per_string_per_year": -1.0}
    )

    with pytest.raises(ValueError, match="Battery om_cost_per_string_per_year cannot be negative"):
        validate_battery_component(battery)


def test_validate_battery_component_fails_if_lifetime_invalid():
    battery = make_valid_battery()
    battery = BatteryComponentConfig(**{**battery.__dict__, "lifetime_years": 0})

    with pytest.raises(ValueError, match="Battery lifetime_years must be > 0"):
        validate_battery_component(battery)