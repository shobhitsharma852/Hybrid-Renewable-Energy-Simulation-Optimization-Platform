import streamlit as st

from core.components.grid import (
    GridComponentConfig,
    validate_grid_component,
)


DEFAULT_GRID = GridComponentConfig()


def render_grid_component_panel() -> None:
    st.header("🔌 Grid")

    st.subheader("Basic Settings")

    enabled = st.checkbox(
        "Enable Grid",
        value=st.session_state.get("ui_grid_enabled", DEFAULT_GRID.enabled),
        key="ui_grid_enabled",
    )

    st.subheader("Simple Rates")

    c1, c2 = st.columns(2)

    with c1:
        grid_power_price_per_kwh = st.number_input(
            "Grid Power Price ($/kWh)",
            min_value=0.0,
            value=float(
                st.session_state.get(
                    "grid_power_price_per_kwh",
                    DEFAULT_GRID.grid_power_price_per_kwh,
                )
            ),
            step=0.01,
            format="%.4f",
            key="ui_grid_power_price_per_kwh",
        )

    with c2:
        grid_sellback_price_per_kwh = st.number_input(
            "Grid Sellback Price ($/kWh)",
            min_value=0.0,
            value=float(
                st.session_state.get(
                    "grid_sellback_price_per_kwh",
                    DEFAULT_GRID.grid_sellback_price_per_kwh,
                )
            ),
            step=0.01,
            format="%.4f",
            key="ui_grid_sellback_price_per_kwh",
        )

    st.subheader("Grid Import / Export Limits")

    c3, c4 = st.columns(2)

    with c3:
        sale_capacity_kw = st.number_input(
            "Maximum Grid Sale Capacity (kW)",
            min_value=0.0,
            value=float(st.session_state.get("ui_grid_sale_capacity_kw", DEFAULT_GRID.sale_capacity_kw)),
            step=100.0,
            key="ui_grid_sale_capacity_kw",
        )

    with c4:
        purchase_capacity_kw = st.number_input(
            "Maximum Grid Purchase Capacity (kW)",
            min_value=0.0,
            value=float(
                st.session_state.get(
                    "grid_purchase_capacity_kw",
                    DEFAULT_GRID.purchase_capacity_kw,
                )
            ),
            step=100.0,
            key="ui_grid_purchase_capacity_kw",
        )

    st.subheader("Net Metering")

    net_metering_enabled = st.checkbox(
        "Enable Net Metering",
        value=st.session_state.get("ui_grid_net_metering_enabled", DEFAULT_GRID.net_metering_enabled),
        key="ui_grid_net_metering_enabled",
    )

    st.subheader("Grid Emissions")

    co2_emissions_g_per_kwh = st.number_input(
        "CO₂ Emissions (g/kWh)",
        min_value=0.0,
        value=float(
            st.session_state.get(
                "grid_co2_emissions_g_per_kwh",
                DEFAULT_GRID.co2_emissions_g_per_kwh,
            )
        ),
        step=1.0,
        key="ui_grid_co2_emissions_g_per_kwh",
    )

    st.divider()

    if st.button(
        "Validate Grid Configuration",
        type="primary",
        key="ui_grid_validate_button",
    ):
        try:
            grid = GridComponentConfig(
                enabled=enabled,
                grid_power_price_per_kwh=float(grid_power_price_per_kwh),
                grid_sellback_price_per_kwh=float(grid_sellback_price_per_kwh),
                sale_capacity_kw=float(sale_capacity_kw),
                purchase_capacity_kw=float(purchase_capacity_kw),
                net_metering_enabled=net_metering_enabled,
                co2_emissions_g_per_kwh=float(co2_emissions_g_per_kwh),
            )

            validate_grid_component(grid)
            st.success("Grid configuration is valid.")

            with st.expander("Preview Grid Configuration", expanded=True):
                st.json(grid.__dict__)

        except Exception as e:
            st.error(f"Grid configuration validation failed: {e}")


def build_grid_component_from_state(
    *,
    enabled: bool,
    grid_power_price_per_kwh: float,
    grid_sellback_price_per_kwh: float,
    sale_capacity_kw: float,
    purchase_capacity_kw: float,
    net_metering_enabled: bool,
    co2_emissions_g_per_kwh: float,
) -> GridComponentConfig:
    return GridComponentConfig(
        enabled=enabled,
        grid_power_price_per_kwh=float(grid_power_price_per_kwh),
        grid_sellback_price_per_kwh=float(grid_sellback_price_per_kwh),
        sale_capacity_kw=float(sale_capacity_kw),
        purchase_capacity_kw=float(purchase_capacity_kw),
        net_metering_enabled=net_metering_enabled,
        co2_emissions_g_per_kwh=float(co2_emissions_g_per_kwh),
    )
