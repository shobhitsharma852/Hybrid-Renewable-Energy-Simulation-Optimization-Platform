import streamlit as st

from core.components.wind import (
    WindComponentConfig,
    WindLossSettings,
    WindMaintenanceSettings,
    WindPowerCurveSettings,
    validate_wind_component,
)


DEFAULT_WIND = WindComponentConfig()
DEFAULT_LOSSES = DEFAULT_WIND.losses
DEFAULT_POWER_CURVE = DEFAULT_WIND.power_curve
DEFAULT_MAINTENANCE = DEFAULT_WIND.maintenance


def _parse_int_list(text: str) -> list[int]:
    values = []
    for item in text.split(","):
        item = item.strip()
        if item:
            values.append(int(item))
    return values


def _parse_float_list(text: str) -> list[float]:
    values = []
    for item in text.split(","):
        item = item.strip()
        if item:
            values.append(float(item))
    return values


def _select_index(options: list[str], value: str) -> int:
    try:
        return options.index(value)
    except ValueError:
        return 0


def render_wind_component_panel(currency_symbol: str = "₹") -> None:
    st.header("🌬 Wind Turbine")

    st.subheader("Basic Settings")

    c1, c2 = st.columns(2)

    with c1:
        enabled = st.checkbox(
            "Enable Wind",
            value=st.session_state.get("ui_wind_enabled", DEFAULT_WIND.enabled),
            key="ui_wind_enabled",
        )

        use_search_space = st.checkbox(
            "Use Search Space",
            value=st.session_state.get("ui_wind_use_search_space", DEFAULT_WIND.use_search_space),
            key="ui_wind_use_search_space",
        )

        turbine_model_name = st.text_input(
            "Turbine Model Name",
            value=st.session_state.get("ui_wind_turbine_model_name", DEFAULT_WIND.turbine_model_name),
            key="ui_wind_turbine_model_name",
        )

        rated_capacity_kw = st.number_input(
            "Rated Capacity (kW)",
            min_value=1.0,
            value=float(st.session_state.get("ui_wind_rated_capacity_kw", DEFAULT_WIND.rated_capacity_kw)),
            step=100.0,
            key="ui_wind_rated_capacity_kw",
        )

        quantity_options_text = st.text_input(
            "Quantity Search Space",
            value=st.session_state.get(
                "wind_quantity_options_text",
                ",".join(str(v) for v in DEFAULT_WIND.quantity_options),
            ),
            key="ui_wind_quantity_options_text",
        )

        hub_height_m = st.number_input(
            "Hub Height (m)",
            min_value=1.0,
            value=float(st.session_state.get("ui_wind_hub_height_m", DEFAULT_WIND.hub_height_m)),
            key="ui_wind_hub_height_m",
        )

    with c2:
        capital_cost = st.number_input(
            f"Capital Cost per Turbine ({currency_symbol})",
            min_value=0.0,
            value=float(
                st.session_state.get(
                    "wind_capital_cost_per_turbine",
                    DEFAULT_WIND.capital_cost_per_turbine,
                )
            ),
            key="ui_wind_capital_cost_per_turbine",
        )

        replacement_cost = st.number_input(
            f"Replacement Cost per Turbine ({currency_symbol})",
            min_value=0.0,
            value=float(
                st.session_state.get(
                    "wind_replacement_cost_per_turbine",
                    DEFAULT_WIND.replacement_cost_per_turbine,
                )
            ),
            key="ui_wind_replacement_cost_per_turbine",
        )

        om_cost = st.number_input(
            f"O&M Cost per Turbine per Year ({currency_symbol})",
            min_value=0.0,
            value=float(
                st.session_state.get(
                    "wind_om_cost_per_turbine_per_year",
                    DEFAULT_WIND.om_cost_per_turbine_per_year,
                )
            ),
            key="ui_wind_om_cost_per_turbine_per_year",
        )

        lifetime = st.number_input(
            "Lifetime (years)",
            min_value=1,
            value=int(st.session_state.get("ui_wind_lifetime_years", DEFAULT_WIND.lifetime_years)),
            key="ui_wind_lifetime_years",
        )

        bus_options = ["AC", "DC"]
        bus = st.selectbox(
            "Electrical Bus",
            bus_options,
            index=_select_index(bus_options, str(st.session_state.get("ui_wind_bus", DEFAULT_WIND.bus))),
            key="ui_wind_bus",
        )

        consider_temperature_effects = st.checkbox(
            "Consider Ambient Temperature Effects",
            value=st.session_state.get(
                "wind_consider_temperature_effects",
                DEFAULT_WIND.consider_temperature_effects,
            ),
            key="ui_wind_consider_temperature_effects",
        )

    st.subheader("Advanced Settings")

    with st.expander("Power Curve", expanded=False):
        wind_speed_text = st.text_area(
            "Wind Speed Points (m/s)",
            value=st.session_state.get(
                "wind_wind_speed_text",
                ",".join(str(v) for v in DEFAULT_POWER_CURVE.wind_speed_points_mps),
            ),
            key="ui_wind_wind_speed_text",
        )

        power_output_text = st.text_area(
            "Power Output (kW)",
            value=st.session_state.get(
                "wind_power_output_text",
                ",".join(str(v) for v in DEFAULT_POWER_CURVE.power_output_points_kw),
            ),
            key="ui_wind_power_output_text",
        )

    with st.expander("Turbine Losses", expanded=False):
        c1, c2 = st.columns(2)

        with c1:
            availability_losses = st.number_input(
                "Availability Losses (%)",
                min_value=0.0,
                max_value=100.0,
                value=float(
                    st.session_state.get(
                        "wind_availability_losses_pct",
                        DEFAULT_LOSSES.availability_losses_pct,
                    )
                ),
                key="ui_wind_availability_losses_pct",
            )

            turbine_losses = st.number_input(
                "Turbine Performance Losses (%)",
                min_value=0.0,
                max_value=100.0,
                value=float(
                    st.session_state.get(
                        "wind_turbine_performance_losses_pct",
                        DEFAULT_LOSSES.turbine_performance_losses_pct,
                    )
                ),
                key="ui_wind_turbine_performance_losses_pct",
            )

            environmental_losses = st.number_input(
                "Environmental Losses (%)",
                min_value=0.0,
                max_value=100.0,
                value=float(
                    st.session_state.get(
                        "wind_environmental_losses_pct",
                        DEFAULT_LOSSES.environmental_losses_pct,
                    )
                ),
                key="ui_wind_environmental_losses_pct",
            )

            other_losses = st.number_input(
                "Other Losses (%)",
                min_value=0.0,
                max_value=100.0,
                value=float(st.session_state.get("ui_wind_other_losses_pct", DEFAULT_LOSSES.other_losses_pct)),
                key="ui_wind_other_losses_pct",
            )

        with c2:
            wake_losses = st.number_input(
                "Wake Effects Losses (%)",
                min_value=0.0,
                max_value=100.0,
                value=float(
                    st.session_state.get(
                        "wind_wake_effects_losses_pct",
                        DEFAULT_LOSSES.wake_effects_losses_pct,
                    )
                ),
                key="ui_wind_wake_effects_losses_pct",
            )

            electrical_losses = st.number_input(
                "Electrical Losses (%)",
                min_value=0.0,
                max_value=100.0,
                value=float(
                    st.session_state.get(
                        "wind_electrical_losses_pct",
                        DEFAULT_LOSSES.electrical_losses_pct,
                    )
                ),
                key="ui_wind_electrical_losses_pct",
            )

            curtailment_losses = st.number_input(
                "Curtailment Losses (%)",
                min_value=0.0,
                max_value=100.0,
                value=float(
                    st.session_state.get(
                        "wind_curtailment_losses_pct",
                        DEFAULT_LOSSES.curtailment_losses_pct,
                    )
                ),
                key="ui_wind_curtailment_losses_pct",
            )

    with st.expander("Maintenance", expanded=False):
        maintenance_enabled = st.checkbox(
            "Enable Maintenance Schedule",
            value=st.session_state.get("ui_wind_maintenance_enabled", DEFAULT_MAINTENANCE.enabled),
            key="ui_wind_maintenance_enabled",
        )

    st.divider()

    if st.button("Validate Wind Configuration", key="ui_wind_validate_button"):
        try:
            quantity_options = _parse_int_list(quantity_options_text)
            wind_speed_points = _parse_float_list(wind_speed_text)
            power_output_points = _parse_float_list(power_output_text)

            power_curve = WindPowerCurveSettings(
                enabled=True,
                wind_speed_points_mps=wind_speed_points,
                power_output_points_kw=power_output_points,
            )

            losses = WindLossSettings(
                enabled=True,
                availability_losses_pct=availability_losses,
                turbine_performance_losses_pct=turbine_losses,
                environmental_losses_pct=environmental_losses,
                other_losses_pct=other_losses,
                wake_effects_losses_pct=wake_losses,
                electrical_losses_pct=electrical_losses,
                curtailment_losses_pct=curtailment_losses,
            )

            maintenance = WindMaintenanceSettings(enabled=maintenance_enabled)

            wind = WindComponentConfig(
                enabled=enabled,
                use_search_space=use_search_space,
                turbine_model_name=turbine_model_name,
                rated_capacity_kw=rated_capacity_kw,
                quantity_options=quantity_options,
                capital_cost_per_turbine=capital_cost,
                replacement_cost_per_turbine=replacement_cost,
                om_cost_per_turbine_per_year=om_cost,
                lifetime_years=lifetime,
                hub_height_m=hub_height_m,
                consider_temperature_effects=consider_temperature_effects,
                bus=bus,
                power_curve=power_curve,
                losses=losses,
                maintenance=maintenance,
            )

            validate_wind_component(wind)
            st.success("Wind configuration is valid")
            with st.expander("Preview Wind Configuration", expanded=False):
                st.json(wind.__dict__)

        except Exception as e:
            st.error(f"Validation failed: {e}")


def build_wind_component_from_state(
    *,
    enabled: bool,
    use_search_space: bool,
    turbine_model_name: str,
    rated_capacity_kw: float,
    quantity_options_text: str,
    capital_cost_per_turbine: float,
    replacement_cost_per_turbine: float,
    om_cost_per_turbine_per_year: float,
    lifetime_years: int,
    hub_height_m: float,
    consider_temperature_effects: bool,
    bus: str,
    wind_speed_text: str,
    power_output_text: str,
    availability_losses_pct: float,
    turbine_performance_losses_pct: float,
    environmental_losses_pct: float,
    other_losses_pct: float,
    wake_effects_losses_pct: float,
    electrical_losses_pct: float,
    curtailment_losses_pct: float,
    maintenance_enabled: bool,
) -> WindComponentConfig:
    quantity_options = _parse_int_list(quantity_options_text)
    wind_speed_points = _parse_float_list(wind_speed_text)
    power_output_points = _parse_float_list(power_output_text)

    power_curve = WindPowerCurveSettings(
        enabled=True,
        wind_speed_points_mps=wind_speed_points,
        power_output_points_kw=power_output_points,
    )

    losses = WindLossSettings(
        enabled=True,
        availability_losses_pct=availability_losses_pct,
        turbine_performance_losses_pct=turbine_performance_losses_pct,
        environmental_losses_pct=environmental_losses_pct,
        other_losses_pct=other_losses_pct,
        wake_effects_losses_pct=wake_effects_losses_pct,
        electrical_losses_pct=electrical_losses_pct,
        curtailment_losses_pct=curtailment_losses_pct,
    )

    maintenance = WindMaintenanceSettings(enabled=maintenance_enabled)

    return WindComponentConfig(
        enabled=enabled,
        use_search_space=use_search_space,
        turbine_model_name=turbine_model_name,
        rated_capacity_kw=rated_capacity_kw,
        quantity_options=quantity_options,
        capital_cost_per_turbine=capital_cost_per_turbine,
        replacement_cost_per_turbine=replacement_cost_per_turbine,
        om_cost_per_turbine_per_year=om_cost_per_turbine_per_year,
        lifetime_years=lifetime_years,
        hub_height_m=hub_height_m,
        consider_temperature_effects=consider_temperature_effects,
        bus=bus,
        power_curve=power_curve,
        losses=losses,
        maintenance=maintenance,
    )
