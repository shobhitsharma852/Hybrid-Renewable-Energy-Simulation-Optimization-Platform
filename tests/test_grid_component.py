import pytest

from core.components.grid import (
    GridComponentConfig,
    validate_grid_component,
)


# ============================================================
# HELPERS
# ============================================================

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


# ============================================================
# MAIN SUCCESS TEST
# ============================================================

def test_validate_grid_component_passes_for_valid_data():
    grid = make_valid_grid()
    validate_grid_component(grid)


# ============================================================
# TARIFF TESTS
# ============================================================

def test_validate_grid_component_fails_if_grid_power_price_negative():
    grid = make_valid_grid()
    grid = GridComponentConfig(
        **{**grid.__dict__, "grid_power_price_per_kwh": -0.01}
    )

    with pytest.raises(ValueError, match="Grid grid_power_price_per_kwh must be >= 0"):
        validate_grid_component(grid)


def test_validate_grid_component_fails_if_sellback_price_negative():
    grid = make_valid_grid()
    grid = GridComponentConfig(
        **{**grid.__dict__, "grid_sellback_price_per_kwh": -0.01}
    )

    with pytest.raises(ValueError, match="Grid grid_sellback_price_per_kwh must be >= 0"):
        validate_grid_component(grid)


# ============================================================
# LIMIT TESTS
# ============================================================

def test_validate_grid_component_fails_if_sale_capacity_negative():
    grid = make_valid_grid()
    grid = GridComponentConfig(
        **{**grid.__dict__, "sale_capacity_kw": -1.0}
    )

    with pytest.raises(ValueError, match="Grid sale_capacity_kw must be >= 0"):
        validate_grid_component(grid)


def test_validate_grid_component_fails_if_purchase_capacity_negative():
    grid = make_valid_grid()
    grid = GridComponentConfig(
        **{**grid.__dict__, "purchase_capacity_kw": -1.0}
    )

    with pytest.raises(ValueError, match="Grid purchase_capacity_kw must be >= 0"):
        validate_grid_component(grid)


def test_validate_grid_component_allows_none_sale_capacity():
    grid = make_valid_grid()
    grid = GridComponentConfig(
        **{**grid.__dict__, "sale_capacity_kw": None}
    )

    validate_grid_component(grid)


def test_validate_grid_component_allows_none_purchase_capacity():
    grid = make_valid_grid()
    grid = GridComponentConfig(
        **{**grid.__dict__, "purchase_capacity_kw": None}
    )

    validate_grid_component(grid)


# ============================================================
# EMISSIONS TESTS
# ============================================================

def test_validate_grid_component_fails_if_co2_negative():
    grid = make_valid_grid()
    grid = GridComponentConfig(
        **{**grid.__dict__, "co2_emissions_g_per_kwh": -1.0}
    )

    with pytest.raises(ValueError, match="Grid co2_emissions_g_per_kwh must be >= 0"):
        validate_grid_component(grid)