import streamlit as st

from core.components.battery import (
    BatteryComponentConfig,
    validate_battery_component,
)


DEFAULT_BATTERY = BatteryComponentConfig()


def _parse_int_list(text: str) -> list[int]:
    values: list[int] = []
    for item in text.split(","):
        cleaned = item.strip()
        if cleaned:
            values.append(int(cleaned))
    return values


def render_battery_component_panel() -> None:
    st.header("🔋 Battery / Storage")

    st.subheader("Basic Settings")

    c1, c2 = st.columns(2)

    with c1:
        enabled = st.checkbox(
            "Enable Battery",
            value=st.session_state.get("ui_battery_enabled", DEFAULT_BATTERY.enabled),
            key="ui_battery_enabled",
        )

        use_search_space = st.checkbox(
            "Use Search Space",
            value=st.session_state.get("ui_battery_use_search_space", DEFAULT_BATTERY.use_search_space),
            key="ui_battery_use_search_space",
        )

        battery_model_name = st.text_input(
            "Battery Model Name",
            value=st.session_state.get("ui_battery_model_name", DEFAULT_BATTERY.battery_model_name),
            key="ui_battery_model_name",
        )

        quantity_options_text = st.text_input(
            "Battery Quantity Search Space (# strings)",
            value=st.session_state.get(
                "battery_quantity_options_text",
                ", ".join(str(v) for v in DEFAULT_BATTERY.quantity_options),
            ),
            help="Enter comma-separated battery string quantities.",
            key="ui_battery_quantity_options_text",
        )

        nominal_voltage_v = st.number_input(
            "Nominal Voltage (V)",
            min_value=1.0,
            value=float(st.session_state.get("ui_battery_nominal_voltage_v", DEFAULT_BATTERY.nominal_voltage_v)),
            step=10.0,
            key="ui_battery_nominal_voltage_v",
        )

        nominal_capacity_kwh_per_string = st.number_input(
            "Nominal Capacity per String (kWh)",
            min_value=0.01,
            value=float(
                st.session_state.get(
                    "battery_nominal_capacity_kwh_per_string",
                    DEFAULT_BATTERY.nominal_capacity_kwh_per_string,
                )
            ),
            step=100.0,
            key="ui_battery_nominal_capacity_kwh_per_string",
        )

        roundtrip_efficiency_pct = st.number_input(
            "Roundtrip Efficiency (%)",
            min_value=0.01,
            max_value=100.0,
            value=float(
                st.session_state.get(
                    "battery_roundtrip_efficiency_pct",
                    DEFAULT_BATTERY.roundtrip_efficiency_pct,
                )
            ),
            step=1.0,
            key="ui_battery_roundtrip_efficiency_pct",
        )

        string_size = st.number_input(
            "String Size",
            min_value=1,
            value=int(st.session_state.get("ui_battery_string_size", DEFAULT_BATTERY.string_size)),
            step=1,
            key="ui_battery_string_size",
        )

    with c2:
        max_charge_current_a = st.number_input(
            "Max Charge Current (A)",
            min_value=0.01,
            value=float(st.session_state.get("ui_battery_max_charge_current_a", DEFAULT_BATTERY.max_charge_current_a)),
            step=10.0,
            key="ui_battery_max_charge_current_a",
        )

        max_discharge_current_a = st.number_input(
            "Max Discharge Current (A)",
            min_value=0.01,
            value=float(
                st.session_state.get(
                    "battery_max_discharge_current_a",
                    DEFAULT_BATTERY.max_discharge_current_a,
                )
            ),
            step=10.0,
            key="ui_battery_max_discharge_current_a",
        )

        initial_state_of_charge_pct = st.number_input(
            "Initial State of Charge (%)",
            min_value=0.0,
            max_value=100.0,
            value=float(
                st.session_state.get(
                    "battery_initial_state_of_charge_pct",
                    DEFAULT_BATTERY.initial_state_of_charge_pct,
                )
            ),
            step=1.0,
            key="ui_battery_initial_state_of_charge_pct",
        )

        minimum_state_of_charge_pct = st.number_input(
            "Minimum State of Charge (%)",
            min_value=0.0,
            max_value=100.0,
            value=float(
                st.session_state.get(
                    "battery_minimum_state_of_charge_pct",
                    DEFAULT_BATTERY.minimum_state_of_charge_pct,
                )
            ),
            step=1.0,
            key="ui_battery_minimum_state_of_charge_pct",
        )

        throughput_kwh = st.number_input(
            "Throughput (kWh)",
            min_value=0.0,
            value=float(st.session_state.get("ui_battery_throughput_kwh", DEFAULT_BATTERY.throughput_kwh)),
            step=10_000.0,
            key="ui_battery_throughput_kwh",
        )

        lifetime_years = st.number_input(
            "Lifetime (years)",
            min_value=1,
            value=int(st.session_state.get("ui_battery_lifetime_years", DEFAULT_BATTERY.lifetime_years)),
            step=1,
            key="ui_battery_lifetime_years",
        )

    st.subheader("Cost Settings")

    c3, c4, c5 = st.columns(3)

    with c3:
        capital_cost_per_string = st.number_input(
            "Capital Cost per String",
            min_value=0.0,
            value=float(
                st.session_state.get(
                    "battery_capital_cost_per_string",
                    DEFAULT_BATTERY.capital_cost_per_string,
                )
            ),
            step=10_000.0,
            key="ui_battery_capital_cost_per_string",
        )

    with c4:
        replacement_cost_per_string = st.number_input(
            "Replacement Cost per String",
            min_value=0.0,
            value=float(
                st.session_state.get(
                    "battery_replacement_cost_per_string",
                    DEFAULT_BATTERY.replacement_cost_per_string,
                )
            ),
            step=10_000.0,
            key="ui_battery_replacement_cost_per_string",
        )

    with c5:
        om_cost_per_string_per_year = st.number_input(
            "O&M Cost per String per Year",
            min_value=0.0,
            value=float(
                st.session_state.get(
                    "battery_om_cost_per_string_per_year",
                    DEFAULT_BATTERY.om_cost_per_string_per_year,
                )
            ),
            step=1000.0,
            key="ui_battery_om_cost_per_string_per_year",
        )

    st.divider()

    if st.button(
        "Validate Battery Configuration",
        type="primary",
        key="ui_battery_validate_button",
    ):
        try:
            quantity_options = _parse_int_list(quantity_options_text)

            battery = BatteryComponentConfig(
                enabled=enabled,
                use_search_space=use_search_space,
                battery_model_name=battery_model_name,
                quantity_options=quantity_options,
                nominal_voltage_v=float(nominal_voltage_v),
                nominal_capacity_kwh_per_string=float(nominal_capacity_kwh_per_string),
                roundtrip_efficiency_pct=float(roundtrip_efficiency_pct),
                max_charge_current_a=float(max_charge_current_a),
                max_discharge_current_a=float(max_discharge_current_a),
                string_size=int(string_size),
                initial_state_of_charge_pct=float(initial_state_of_charge_pct),
                minimum_state_of_charge_pct=float(minimum_state_of_charge_pct),
                throughput_kwh=float(throughput_kwh),
                capital_cost_per_string=float(capital_cost_per_string),
                replacement_cost_per_string=float(replacement_cost_per_string),
                om_cost_per_string_per_year=float(om_cost_per_string_per_year),
                lifetime_years=int(lifetime_years),
            )

            validate_battery_component(battery)
            st.success("Battery configuration is valid.")

            with st.expander("Preview Battery Configuration", expanded=False):
                st.json(battery.__dict__)

        except Exception as e:
            st.error(f"Battery configuration validation failed: {e}")


def build_battery_component_from_state(
    *,
    enabled: bool,
    use_search_space: bool,
    battery_model_name: str,
    quantity_options_text: str,
    nominal_voltage_v: float,
    nominal_capacity_kwh_per_string: float,
    roundtrip_efficiency_pct: float,
    max_charge_current_a: float,
    max_discharge_current_a: float,
    string_size: int,
    initial_state_of_charge_pct: float,
    minimum_state_of_charge_pct: float,
    throughput_kwh: float,
    capital_cost_per_string: float,
    replacement_cost_per_string: float,
    om_cost_per_string_per_year: float,
    lifetime_years: int,
) -> BatteryComponentConfig:
    quantity_options = _parse_int_list(quantity_options_text)

    return BatteryComponentConfig(
        enabled=enabled,
        use_search_space=use_search_space,
        battery_model_name=battery_model_name,
        quantity_options=quantity_options,
        nominal_voltage_v=float(nominal_voltage_v),
        nominal_capacity_kwh_per_string=float(nominal_capacity_kwh_per_string),
        roundtrip_efficiency_pct=float(roundtrip_efficiency_pct),
        max_charge_current_a=float(max_charge_current_a),
        max_discharge_current_a=float(max_discharge_current_a),
        string_size=int(string_size),
        initial_state_of_charge_pct=float(initial_state_of_charge_pct),
        minimum_state_of_charge_pct=float(minimum_state_of_charge_pct),
        throughput_kwh=float(throughput_kwh),
        capital_cost_per_string=float(capital_cost_per_string),
        replacement_cost_per_string=float(replacement_cost_per_string),
        om_cost_per_string_per_year=float(om_cost_per_string_per_year),
        lifetime_years=int(lifetime_years),
    )
