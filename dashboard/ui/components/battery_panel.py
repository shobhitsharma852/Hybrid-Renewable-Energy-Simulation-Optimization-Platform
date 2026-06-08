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


def render_battery_component_panel(currency_symbol: str = "₹") -> None:
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

        self_discharge_rate_pct_per_day = st.number_input(
            "Self-Discharge Rate (%/day)",
            min_value=0.0,
            max_value=100.0,
            value=float(
                st.session_state.get(
                    "battery_self_discharge_rate_pct_per_day",
                    DEFAULT_BATTERY.self_discharge_rate_pct_per_day,
                )
            ),
            step=0.01,
            format="%.3f",
            help="Li-Ion typical: 0.05–0.1 %/day. Lead-acid: 0.1–0.3 %/day.",
            key="ui_battery_self_discharge_rate_pct_per_day",
        )

    st.subheader("Capacity Fade")
    st.caption(
        "How much capacity can the battery lose before it is replaced? "
        "The simulator derives the fade rate automatically from Throughput (kWh) and Nominal Capacity — "
        "no manual %/EFC calculation needed. "
        "Set to 0 to disable capacity fade entirely."
    )

    cf1, cf2 = st.columns(2)

    with cf1:
        replacement_degradation_limit_pct = st.number_input(
            "Replacement Degradation Limit (%)",
            min_value=0.0,
            max_value=99.0,
            value=float(
                st.session_state.get(
                    "battery_replacement_degradation_limit_pct",
                    DEFAULT_BATTERY.replacement_degradation_limit_pct,
                )
            ),
            step=1.0,
            format="%.1f",
            help=(
                "Battery is replaced when it has lost this much of its original capacity. "
                "20% means replace at 80% State of Health (IEC 62619 standard for Li-Ion). "
                "Same as HOMER Pro's 'Replacement degradation limit (%)' field."
            ),
            key="ui_battery_replacement_degradation_limit_pct",
        )

    with cf2:
        calendar_fade_pct_per_year = st.number_input(
            "Calendar Fade (%/year)",
            min_value=0.0,
            max_value=20.0,
            value=float(
                st.session_state.get(
                    "ui_battery_calendar_fade_pct_per_year",
                    DEFAULT_BATTERY.calendar_fade_pct_per_year,
                )
            ),
            step=0.5,
            format="%.2f",
            help=(
                "Capacity lost per year from time-based (calendar) aging, independent of cycling. "
                "0 = disabled (replacement handled by Lifetime (years) alone — recommended default). "
                "Typical: Li-Ion 2–3 %/yr, Lead-acid 3–5 %/yr. "
                "This rate applies at the Arrhenius reference temperature."
            ),
            key="ui_battery_calendar_fade_pct_per_year",
        )

    if calendar_fade_pct_per_year > 0.0:
        st.caption(
            "Arrhenius temperature scaling — scale the calendar fade rate with ambient temperature. "
            "Requires a 'temperature' column in the resource data. "
            "Set Activation Energy = 0 to disable (fixed rate regardless of temperature)."
        )
        arr1, arr2 = st.columns(2)
        with arr1:
            arrhenius_ea_ev = st.number_input(
                "Activation Energy Ea (eV)",
                min_value=0.0,
                max_value=2.0,
                value=float(
                    st.session_state.get(
                        "ui_battery_arrhenius_ea_ev",
                        DEFAULT_BATTERY.arrhenius_ea_ev,
                    )
                ),
                step=0.05,
                format="%.3f",
                help=(
                    "Arrhenius activation energy (eV). 0 = disabled (fixed rate). "
                    "Li-Ion NMC/NCA typical: 0.7 eV. LFP typical: 0.6 eV."
                ),
                key="ui_battery_arrhenius_ea_ev",
            )
        with arr2:
            temperature_reference_c = st.number_input(
                "Reference Temperature (°C)",
                min_value=-40.0,
                max_value=60.0,
                value=float(
                    st.session_state.get(
                        "ui_battery_temperature_reference_c",
                        DEFAULT_BATTERY.temperature_reference_c,
                    )
                ),
                step=5.0,
                format="%.1f",
                help=(
                    "Temperature at which the Calendar Fade rate above was measured. "
                    "Default 25°C (standard lab conditions)."
                ),
                key="ui_battery_temperature_reference_c",
            )
    else:
        arrhenius_ea_ev = DEFAULT_BATTERY.arrhenius_ea_ev
        temperature_reference_c = DEFAULT_BATTERY.temperature_reference_c

    st.subheader("Cycle Life (DoD-Dependent Aging)")
    st.caption(
        "Power-law model: N(DoD) = A × DoD^(−beta) cycles to failure. "
        "Each time the charge direction reverses, one half-cycle is counted using Miner's rule. "
        "Set Cycle Life A = 0 to disable and use the simpler EFC model (derived from Throughput)."
    )

    cl1, cl2 = st.columns(2)

    with cl1:
        cycle_life_a = st.number_input(
            "Cycle Life A (cycles at 100% DoD)",
            min_value=0.0,
            value=float(
                st.session_state.get(
                    "ui_battery_cycle_life_a",
                    DEFAULT_BATTERY.cycle_life_a,
                )
            ),
            step=50.0,
            format="%.0f",
            help=(
                "Cycles to failure at 100% depth of discharge. "
                "HOMER Pro Generic Li-Ion default: 750. "
                "Set to 0 to disable DoD-dependent aging (use Throughput-based EFC model instead)."
            ),
            key="ui_battery_cycle_life_a",
        )

    with cl2:
        cycle_life_beta = st.number_input(
            "Cycle Life Beta (power-law exponent)",
            min_value=0.1,
            value=float(
                st.session_state.get(
                    "ui_battery_cycle_life_beta",
                    DEFAULT_BATTERY.cycle_life_beta,
                )
            ),
            step=0.1,
            format="%.2f",
            help=(
                "Exponent in N(DoD) = A × DoD^(−beta). "
                "Higher beta = steeper penalty for deep cycling. "
                "HOMER Pro Generic Li-Ion default: 1.3."
            ),
            key="ui_battery_cycle_life_beta",
        )

    st.subheader("Temperature Effects")
    st.caption(
        "Scale usable battery capacity with ambient temperature each hour. "
        "Requires a 'temperature' column in the resource data. "
        "Uses HOMER Pro's polynomial: Capacity(T) = Capacity × (d0 + d1·T + d2·T²). "
        "The correction is reversible — it does not permanently degrade the battery."
    )

    consider_temperature_effects = st.checkbox(
        "Enable Temperature Capacity Correction",
        value=st.session_state.get(
            "ui_battery_consider_temperature_effects",
            DEFAULT_BATTERY.consider_temperature_effects,
        ),
        key="ui_battery_consider_temperature_effects",
    )

    if consider_temperature_effects:
        ct1, ct2, ct3 = st.columns(3)
        with ct1:
            capacity_temp_d0 = st.number_input(
                "d0 (constant)",
                value=float(
                    st.session_state.get(
                        "ui_battery_capacity_temp_d0",
                        DEFAULT_BATTERY.capacity_temp_d0,
                    )
                ),
                step=0.01,
                format="%.4f",
                help="Constant term. Li-Ion HOMER default: 0.923 (capacity at 0°C = 92.3% of rated).",
                key="ui_battery_capacity_temp_d0",
            )
        with ct2:
            capacity_temp_d1 = st.number_input(
                "d1 (linear, per °C)",
                value=float(
                    st.session_state.get(
                        "ui_battery_capacity_temp_d1",
                        DEFAULT_BATTERY.capacity_temp_d1,
                    )
                ),
                step=0.0001,
                format="%.5f",
                help="Linear coefficient. Li-Ion HOMER default: 0.00345.",
                key="ui_battery_capacity_temp_d1",
            )
        with ct3:
            capacity_temp_d2 = st.number_input(
                "d2 (quadratic, per °C²)",
                value=float(
                    st.session_state.get(
                        "ui_battery_capacity_temp_d2",
                        DEFAULT_BATTERY.capacity_temp_d2,
                    )
                ),
                step=0.000001,
                format="%.6f",
                help="Quadratic coefficient. Li-Ion HOMER default: -3.75e-05.",
                key="ui_battery_capacity_temp_d2",
            )
    else:
        capacity_temp_d0 = DEFAULT_BATTERY.capacity_temp_d0
        capacity_temp_d1 = DEFAULT_BATTERY.capacity_temp_d1
        capacity_temp_d2 = DEFAULT_BATTERY.capacity_temp_d2

    st.subheader("Cost Settings")

    c3, c4, c5 = st.columns(3)

    with c3:
        capital_cost_per_string = st.number_input(
            f"Capital Cost per String ({currency_symbol})",
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
            f"Replacement Cost per String ({currency_symbol})",
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
            f"O&M Cost per String per Year ({currency_symbol})",
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
                self_discharge_rate_pct_per_day=float(self_discharge_rate_pct_per_day),
                replacement_degradation_limit_pct=float(replacement_degradation_limit_pct),
                calendar_fade_pct_per_year=float(calendar_fade_pct_per_year),
                arrhenius_ea_ev=float(arrhenius_ea_ev),
                temperature_reference_c=float(temperature_reference_c),
                cycle_life_a=float(cycle_life_a),
                cycle_life_beta=float(cycle_life_beta),
                consider_temperature_effects=bool(consider_temperature_effects),
                capacity_temp_d0=float(capacity_temp_d0),
                capacity_temp_d1=float(capacity_temp_d1),
                capacity_temp_d2=float(capacity_temp_d2),
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
    self_discharge_rate_pct_per_day: float,
    replacement_degradation_limit_pct: float,
    calendar_fade_pct_per_year: float,
    arrhenius_ea_ev: float,
    temperature_reference_c: float,
    cycle_life_a: float,
    cycle_life_beta: float,
    consider_temperature_effects: bool,
    capacity_temp_d0: float,
    capacity_temp_d1: float,
    capacity_temp_d2: float,
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
        self_discharge_rate_pct_per_day=float(self_discharge_rate_pct_per_day),
        replacement_degradation_limit_pct=float(replacement_degradation_limit_pct),
        calendar_fade_pct_per_year=float(calendar_fade_pct_per_year),
        arrhenius_ea_ev=float(arrhenius_ea_ev),
        temperature_reference_c=float(temperature_reference_c),
        cycle_life_a=float(cycle_life_a),
        cycle_life_beta=float(cycle_life_beta),
        consider_temperature_effects=bool(consider_temperature_effects),
        capacity_temp_d0=float(capacity_temp_d0),
        capacity_temp_d1=float(capacity_temp_d1),
        capacity_temp_d2=float(capacity_temp_d2),
        capital_cost_per_string=float(capital_cost_per_string),
        replacement_cost_per_string=float(replacement_cost_per_string),
        om_cost_per_string_per_year=float(om_cost_per_string_per_year),
        lifetime_years=int(lifetime_years),
    )
