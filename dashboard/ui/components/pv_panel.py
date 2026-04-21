import streamlit as st

from core.components.pv import (
    PVMPPTSettings,
    PVOrientationSettings,
    PVTemperatureSettings,
    PVComponentConfig,
    validate_pv_component,
)


def _parse_float_list(text: str) -> list[float]:
    values: list[float] = []
    for item in text.split(","):
        cleaned = item.strip()
        if not cleaned:
            continue
        values.append(float(cleaned))
    return values


def render_pv_component_panel() -> None:

    st.header("☀️ Solar PV")

    # ---------------------------------------------------------
    # BASIC SETTINGS
    # ---------------------------------------------------------
    st.subheader("Basic Settings")

    c1, c2 = st.columns(2)

    with c1:

        enabled = st.checkbox(
            "Enable PV",
            value=st.session_state.get("ui_pv_enabled", False),
            key="ui_pv_enabled",
        )

        use_search_space = st.checkbox(
            "Use Search Space",
            value=st.session_state.get("ui_pv_use_search_space", True),
            key="ui_pv_use_search_space",
        )
        capacity_kw_options_text = st.text_input(
            "PV Capacity Search Space (kW)",
            value="0, 1000, 2000, 3000",
            key="ui_pv_capacity_kw_options_text",
        )

        derating_factor = st.number_input(
            "Derating Factor",
            min_value=0.01,
            max_value=1.0,
            value=0.80,
            step=0.01,
            key="ui_pv_derating_factor",
        )

    with c2:

        capital_cost_per_kw = st.number_input(
            "Capital Cost per kW",
            min_value=0.0,
            value=2500.0,
            key="ui_pv_capital_cost_per_kw",
        )

        replacement_cost_per_kw = st.number_input(
            "Replacement Cost per kW",
            min_value=0.0,
            value=2500.0,
            key="ui_pv_replacement_cost_per_kw",
        )

        om_cost_per_kw_per_year = st.number_input(
            "O&M Cost per kW per Year",
            min_value=0.0,
            value=10.0,
            key="ui_pv_om_cost_per_kw_per_year",
        )

        lifetime_years = st.number_input(
            "Lifetime (years)",
            min_value=1,
            value=25,
            key="ui_pv_lifetime_years",
        )

        bus = st.selectbox(
            "Bus",
            ["DC", "AC"],
            index=0,
            key="ui_pv_bus",
        )

    # ---------------------------------------------------------
    # ADVANCED SETTINGS
    # ---------------------------------------------------------
    st.subheader("Advanced Settings")

    # ------------------ MPPT ------------------

    with st.expander("MPPT Settings"):

        mppt_enabled = st.checkbox(
            "Enable MPPT",
            value=st.session_state.get("ui_pv_mppt_enabled", False),
            key="ui_pv_mppt_enabled",
        )

        mppt_lifetime_years = st.number_input(
            "MPPT Lifetime (years)",
            min_value=1,
            value=15,
            key="ui_pv_mppt_lifetime_years",
        )

        mppt_sizing_mode = st.selectbox(
            "MPPT Sizing Mode",
            ["ratio", "capacity"],
            index=0,
            key="ui_pv_mppt_sizing_mode",
        )

        pv_to_conv_ratio_options_text = st.text_input(
            "PV-to-Converter Ratio Options",
            value="1.0",
            key="ui_pv_pv_to_conv_ratio_options_text",
        )

        mppt_capacity_kw_options_text = st.text_input(
            "MPPT Capacity Options (kW)",
            value="1.0",
            key="ui_pv_mppt_capacity_kw_options_text",
        )

        mppt_efficiency_pct = st.number_input(
            "MPPT Efficiency (%)",
            min_value=0.01,
            max_value=100.0,
            value=95.0,
            key="ui_pv_mppt_efficiency_pct",
        )

        use_efficiency_table = st.checkbox(
            "Use Efficiency Table",
            value=st.session_state.get("ui_pv_use_efficiency_table", False),
            key="ui_pv_use_efficiency_table",
        )

    # ------------------ ORIENTATION ------------------

    with st.expander("Orientation Settings", expanded=False):

        orientation_enabled = st.checkbox(
            "Enable Orientation Model",
            value=st.session_state.get("ui_pv_orientation_enabled", True),
            key="ui_pv_orientation_enabled",
        )

        ground_reflectance_pct = st.number_input(
            "Ground Reflectance (%)",
            min_value=0.0,
            max_value=100.0,
            value=20.0,
            key="ui_pv_ground_reflectance_pct",
        )

        tracking_system = st.selectbox(
            "Tracking System",
            ["no_tracking", "single_axis", "dual_axis"],
            key="ui_pv_tracking_system",
        )

        use_default_slope = st.checkbox(
            "Use Default Slope",
            value=st.session_state.get("ui_pv_use_default_slope", True),
            key="ui_pv_use_default_slope",
        )

        panel_slope_deg = st.number_input(
            "Panel Slope (deg)",
            min_value=0.0,
            max_value=90.0,
            value=25.0,
            disabled=use_default_slope,
            key="ui_pv_panel_slope_deg",
        )

        use_default_azimuth = st.checkbox(
            "Use Default Azimuth",
            value=st.session_state.get("ui_pv_use_default_azimuth", True),
            key="ui_pv_use_default_azimuth",
        )
        panel_azimuth_deg = st.number_input(
            "Panel Azimuth (deg)",
            min_value=-180.0,
            max_value=180.0,
            value=180.0,
            disabled=use_default_azimuth,
            key="ui_pv_panel_azimuth_deg",
        )

        st.divider()
        use_clearness_index_cap = st.checkbox(
            "Use Clearness Index Cap (HOMER-matched GHI processing)",
            value=st.session_state.get("ui_pv_use_clearness_index_cap", False),
            key="ui_pv_use_clearness_index_cap",
            help=(
                "When ON: effective GHI = min(Kt, kt_max) x G0. "
                "Requires clearness index columns in the saved resources CSV "
                "(compute them on the Resources page). "
                "Reduces PV error vs HOMER from ~1% to ~0.07%."
            ),
        )

        kt_max = st.number_input(
            "Kt Max (clearness index cap)",
            min_value=0.50,
            max_value=1.00,
            value=st.session_state.get("ui_pv_kt_max", 0.82),
            step=0.01,
            disabled=not use_clearness_index_cap,
            key="ui_pv_kt_max",
            help="Standard Duffie & Beckman clear-sky maximum = 0.82. HOMER uses this value.",
        )

    # ------------------ TEMPERATURE ------------------

    with st.expander("Temperature Settings", expanded=False):

        temperature_enabled = st.checkbox(
            "Enable Temperature Model",
            value=st.session_state.get("ui_pv_temperature_enabled", True),
            key="ui_pv_temperature_enabled",
        )

        temperature_coefficient_pct_per_degC = st.number_input(
            "Temperature Coefficient (% per °C)",
            min_value=-5.0,
            max_value=1.0,
            value=-0.5,
            key="ui_pv_temperature_coefficient_pct_per_degC",
        )

        nominal_operating_cell_temp_c = st.number_input(
            "NOCT (°C)",
            min_value=1.0,
            value=45.0,
            key="ui_pv_nominal_operating_cell_temp_c",
        )

        efficiency_stc_pct = st.number_input(
            "Efficiency at STC (%)",
            min_value=0.01,
            max_value=100.0,
            value=13.0,
            key="ui_pv_efficiency_stc_pct",
        )

    # ---------------------------------------------------------
    # VALIDATE CONFIG
    # ---------------------------------------------------------

    st.divider()

    if st.button("Validate PV Configuration"):

        try:

            capacity_kw_options = _parse_float_list(capacity_kw_options_text)
            pv_to_conv_ratio_options = _parse_float_list(pv_to_conv_ratio_options_text)
            mppt_capacity_kw_options = _parse_float_list(mppt_capacity_kw_options_text)

            mppt = PVMPPTSettings(
                enabled=mppt_enabled,
                lifetime_years=mppt_lifetime_years,
                sizing_mode=mppt_sizing_mode,
                pv_to_conv_ratio_options=pv_to_conv_ratio_options,
                capacity_kw_options=mppt_capacity_kw_options,
                efficiency_pct=mppt_efficiency_pct,
                use_efficiency_table=use_efficiency_table,
            )

            orientation = PVOrientationSettings(
                enabled=orientation_enabled,
                ground_reflectance_pct=ground_reflectance_pct,
                tracking_system=tracking_system,
                use_default_slope=use_default_slope,
                panel_slope_deg=None if use_default_slope else panel_slope_deg,
                use_default_azimuth=use_default_azimuth,
                panel_azimuth_deg=None if use_default_azimuth else panel_azimuth_deg,
                use_clearness_index_cap=use_clearness_index_cap,
                kt_max=float(kt_max),
            )

            temperature = PVTemperatureSettings(
                enabled=temperature_enabled,
                temperature_coefficient_pct_per_degC=temperature_coefficient_pct_per_degC,
                nominal_operating_cell_temp_c=nominal_operating_cell_temp_c,
                efficiency_stc_pct=efficiency_stc_pct,
            )

            pv = PVComponentConfig(
                enabled=enabled,
                use_search_space=use_search_space,
                capacity_kw_options=capacity_kw_options,
                capital_cost_per_kw=capital_cost_per_kw,
                replacement_cost_per_kw=replacement_cost_per_kw,
                om_cost_per_kw_per_year=om_cost_per_kw_per_year,
                lifetime_years=lifetime_years,
                derating_factor=derating_factor,
                bus=bus,
                mppt=mppt,
                orientation=orientation,
                temperature=temperature,
            )

            validate_pv_component(pv)

            st.success("PV configuration is valid.")
            with st.expander("Preview PV Configuration", expanded=False):
                st.json(pv.__dict__)

        except Exception as e:

            st.error(f"PV configuration validation failed: {e}")

def build_pv_component_from_state(
    *,
    enabled: bool,
    use_search_space: bool,
    capacity_kw_options_text: str,
    capital_cost_per_kw: float,
    replacement_cost_per_kw: float,
    om_cost_per_kw_per_year: float,
    lifetime_years: int,
    derating_factor: float,
    bus: str,
    mppt_enabled: bool,
    mppt_lifetime_years: int,
    mppt_sizing_mode: str,
    pv_to_conv_ratio_options_text: str,
    mppt_capacity_kw_options_text: str,
    mppt_efficiency_pct: float,
    use_efficiency_table: bool,
    orientation_enabled: bool,
    ground_reflectance_pct: float,
    tracking_system: str,
    use_default_slope: bool,
    panel_slope_deg: float,
    use_default_azimuth: bool,
    panel_azimuth_deg: float,
    use_clearness_index_cap: bool,
    kt_max: float,
    temperature_enabled: bool,
    temperature_coefficient_pct_per_degC: float,
    nominal_operating_cell_temp_c: float,
    efficiency_stc_pct: float,
) -> PVComponentConfig:
    capacity_kw_options = _parse_float_list(capacity_kw_options_text)
    pv_to_conv_ratio_options = _parse_float_list(pv_to_conv_ratio_options_text)
    mppt_capacity_kw_options = _parse_float_list(mppt_capacity_kw_options_text)

    mppt = PVMPPTSettings(
        enabled=mppt_enabled,
        lifetime_years=int(mppt_lifetime_years),
        sizing_mode=mppt_sizing_mode,
        pv_to_conv_ratio_options=pv_to_conv_ratio_options,
        capacity_kw_options=mppt_capacity_kw_options,
        efficiency_pct=float(mppt_efficiency_pct),
        use_efficiency_table=use_efficiency_table,
    )

    orientation = PVOrientationSettings(
        enabled=orientation_enabled,
        ground_reflectance_pct=float(ground_reflectance_pct),
        tracking_system=tracking_system,
        use_default_slope=use_default_slope,
        panel_slope_deg=None if use_default_slope else float(panel_slope_deg),
        use_default_azimuth=use_default_azimuth,
        panel_azimuth_deg=None if use_default_azimuth else float(panel_azimuth_deg),
        use_clearness_index_cap=use_clearness_index_cap,
        kt_max=float(kt_max),
    )

    temperature = PVTemperatureSettings(
        enabled=temperature_enabled,
        temperature_coefficient_pct_per_degC=float(temperature_coefficient_pct_per_degC),
        nominal_operating_cell_temp_c=float(nominal_operating_cell_temp_c),
        efficiency_stc_pct=float(efficiency_stc_pct),
    )

    return PVComponentConfig(
        enabled=enabled,
        use_search_space=use_search_space,
        capacity_kw_options=capacity_kw_options,
        capital_cost_per_kw=float(capital_cost_per_kw),
        replacement_cost_per_kw=float(replacement_cost_per_kw),
        om_cost_per_kw_per_year=float(om_cost_per_kw_per_year),
        lifetime_years=int(lifetime_years),
        derating_factor=float(derating_factor),
        bus=bus,
        mppt=mppt,
        orientation=orientation,
        temperature=temperature,
    )