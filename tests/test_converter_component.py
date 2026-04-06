import pytest

from core.components.converter import (
    ConverterComponentConfig,
    validate_converter_component,
)


# ============================================================
# HELPERS
# ============================================================

def make_valid_converter() -> ConverterComponentConfig:
    return ConverterComponentConfig(
        enabled=True,
        use_search_space=True,
        converter_model_name="System Converter",
        capacity_kw_options=[0.0, 1000.0, 2000.0, 3000.0, 4000.0],
        capital_cost_per_kw=300.0,
        replacement_cost_per_kw=300.0,
        om_cost_per_kw_per_year=0.0,
        inverter_lifetime_years=15,
        inverter_efficiency_pct=95.0,
        rectifier_relative_capacity_pct=100.0,
        rectifier_efficiency_pct=95.0,
        parallel_with_ac_generator=False,
    )


# ============================================================
# MAIN SUCCESS TEST
# ============================================================

def test_validate_converter_component_passes_for_valid_data():
    converter = make_valid_converter()
    validate_converter_component(converter)


# ============================================================
# MODEL NAME TESTS
# ============================================================

def test_validate_converter_component_fails_if_name_empty():
    converter = make_valid_converter()
    converter = ConverterComponentConfig(
        **{**converter.__dict__, "converter_model_name": ""}
    )

    with pytest.raises(ValueError, match="Converter converter_model_name cannot be empty"):
        validate_converter_component(converter)


# ============================================================
# SEARCH SPACE TESTS
# ============================================================

def test_validate_converter_component_fails_if_capacity_options_empty():
    converter = make_valid_converter()
    converter = ConverterComponentConfig(
        **{**converter.__dict__, "capacity_kw_options": []}
    )

    with pytest.raises(ValueError, match="Converter capacity_kw_options cannot be empty"):
        validate_converter_component(converter)


def test_validate_converter_component_fails_if_capacity_option_negative():
    converter = make_valid_converter()
    converter = ConverterComponentConfig(
        **{**converter.__dict__, "capacity_kw_options": [0.0, -1000.0]}
    )

    with pytest.raises(
        ValueError,
        match="Converter capacity_kw_options cannot contain negative values",
    ):
        validate_converter_component(converter)


# ============================================================
# ECONOMIC PARAMETER TESTS
# ============================================================

def test_validate_converter_component_fails_if_capital_cost_negative():
    converter = make_valid_converter()
    converter = ConverterComponentConfig(
        **{**converter.__dict__, "capital_cost_per_kw": -1.0}
    )

    with pytest.raises(ValueError, match="Converter capital_cost_per_kw cannot be negative"):
        validate_converter_component(converter)


def test_validate_converter_component_fails_if_replacement_cost_negative():
    converter = make_valid_converter()
    converter = ConverterComponentConfig(
        **{**converter.__dict__, "replacement_cost_per_kw": -1.0}
    )

    with pytest.raises(
        ValueError,
        match="Converter replacement_cost_per_kw cannot be negative",
    ):
        validate_converter_component(converter)


def test_validate_converter_component_fails_if_om_cost_negative():
    converter = make_valid_converter()
    converter = ConverterComponentConfig(
        **{**converter.__dict__, "om_cost_per_kw_per_year": -1.0}
    )

    with pytest.raises(
        ValueError,
        match="Converter om_cost_per_kw_per_year cannot be negative",
    ):
        validate_converter_component(converter)


# ============================================================
# INVERTER / RECTIFIER TESTS
# ============================================================

def test_validate_converter_component_fails_if_inverter_lifetime_invalid():
    converter = make_valid_converter()
    converter = ConverterComponentConfig(
        **{**converter.__dict__, "inverter_lifetime_years": 0}
    )

    with pytest.raises(
        ValueError,
        match="Converter inverter_lifetime_years must be > 0",
    ):
        validate_converter_component(converter)


def test_validate_converter_component_fails_if_inverter_efficiency_invalid_low():
    converter = make_valid_converter()
    converter = ConverterComponentConfig(
        **{**converter.__dict__, "inverter_efficiency_pct": 0.0}
    )

    with pytest.raises(
        ValueError,
        match="Converter inverter_efficiency_pct must be between 0 and 100",
    ):
        validate_converter_component(converter)


def test_validate_converter_component_fails_if_inverter_efficiency_invalid_high():
    converter = make_valid_converter()
    converter = ConverterComponentConfig(
        **{**converter.__dict__, "inverter_efficiency_pct": 120.0}
    )

    with pytest.raises(
        ValueError,
        match="Converter inverter_efficiency_pct must be between 0 and 100",
    ):
        validate_converter_component(converter)


def test_validate_converter_component_fails_if_rectifier_relative_capacity_invalid_low():
    converter = make_valid_converter()
    converter = ConverterComponentConfig(
        **{**converter.__dict__, "rectifier_relative_capacity_pct": -1.0}
    )

    with pytest.raises(
        ValueError,
        match="Converter rectifier_relative_capacity_pct must be between 0 and 100",
    ):
        validate_converter_component(converter)


def test_validate_converter_component_fails_if_rectifier_relative_capacity_invalid_high():
    converter = make_valid_converter()
    converter = ConverterComponentConfig(
        **{**converter.__dict__, "rectifier_relative_capacity_pct": 120.0}
    )

    with pytest.raises(
        ValueError,
        match="Converter rectifier_relative_capacity_pct must be between 0 and 100",
    ):
        validate_converter_component(converter)


def test_validate_converter_component_fails_if_rectifier_efficiency_invalid_low():
    converter = make_valid_converter()
    converter = ConverterComponentConfig(
        **{**converter.__dict__, "rectifier_efficiency_pct": 0.0}
    )

    with pytest.raises(
        ValueError,
        match="Converter rectifier_efficiency_pct must be between 0 and 100",
    ):
        validate_converter_component(converter)


def test_validate_converter_component_fails_if_rectifier_efficiency_invalid_high():
    converter = make_valid_converter()
    converter = ConverterComponentConfig(
        **{**converter.__dict__, "rectifier_efficiency_pct": 120.0}
    )

    with pytest.raises(
        ValueError,
        match="Converter rectifier_efficiency_pct must be between 0 and 100",
    ):
        validate_converter_component(converter)