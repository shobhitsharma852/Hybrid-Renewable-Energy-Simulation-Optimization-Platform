import streamlit as st

from dashboard.ui.feature_flags import SHOW_INSOLARE_OPTIMIZER_UI
from dashboard.ui.formatting import formatted_number_input
from core.components.converter import (
    ConverterComponentConfig,
    validate_converter_component,
)


DEFAULT_CONVERTER = ConverterComponentConfig()


def _parse_float_list(text: str) -> list[float]:
    values: list[float] = []
    for item in text.split(","):
        cleaned = item.strip()
        if cleaned:
            values.append(float(cleaned))
    return values


def render_converter_component_panel(currency_symbol: str = "₹") -> None:
    st.header("🔄 Converter")

    st.subheader("Basic Settings")

    c1, c2 = st.columns(2)

    with c1:
        enabled = st.checkbox(
            "Enable Converter",
            value=st.session_state.get("ui_converter_enabled", DEFAULT_CONVERTER.enabled),
            key="ui_converter_enabled",
        )

        if SHOW_INSOLARE_OPTIMIZER_UI:
            _sizing_mode_idx = 0 if st.session_state.get("ui_converter_use_search_space", DEFAULT_CONVERTER.use_search_space) else 1
            _sizing_mode = st.radio(
                "Sizing Mode",
                ["Discrete Options", "InSolare Optimizer"],
                index=_sizing_mode_idx,
                horizontal=True,
                key="ui_converter_sizing_mode",
            )
            use_search_space = (_sizing_mode == "Discrete Options")
        else:
            use_search_space = True
        st.session_state["ui_converter_use_search_space"] = use_search_space

        converter_model_name = st.text_input(
            "Converter Model Name",
            value=st.session_state.get("ui_converter_model_name", DEFAULT_CONVERTER.converter_model_name),
            key="ui_converter_model_name",
        )

        if use_search_space:
            capacity_kw_options_text = st.text_input(
                "Capacity Options (kW)",
                value=st.session_state.get(
                    "ui_converter_capacity_kw_options_text",
                    ", ".join(str(v) for v in DEFAULT_CONVERTER.capacity_kw_options),
                ),
                help="Enter comma-separated converter capacity options in kW.",
                key="ui_converter_capacity_kw_options_text",
            )
        else:
            capacity_kw_options_text = st.session_state.get(
                "ui_converter_capacity_kw_options_text",
                ", ".join(str(v) for v in DEFAULT_CONVERTER.capacity_kw_options),
            )
            set_limits = st.checkbox(
                "Set Limits",
                value=st.session_state.get("ui_converter_optimizer_set_limits", False),
                key="ui_converter_optimizer_set_limits",
            )
            if set_limits:
                _ol, _ou = st.columns(2)
                with _ol:
                    st.number_input(
                        "Minimum (kW)",
                        min_value=0.0,
                        value=float(st.session_state.get("ui_converter_optimizer_kw_min", 0.0)),
                        step=100.0,
                        key="ui_converter_optimizer_kw_min",
                    )
                with _ou:
                    st.number_input(
                        "Maximum (kW)",
                        min_value=0.0,
                        value=float(st.session_state.get("ui_converter_optimizer_kw_max", 6000.0)),
                        step=100.0,
                        key="ui_converter_optimizer_kw_max",
                    )

        inverter_lifetime_years = st.number_input(
            "Inverter Lifetime (years)",
            min_value=1,
            value=int(
                st.session_state.get(
                    "converter_inverter_lifetime_years",
                    DEFAULT_CONVERTER.inverter_lifetime_years,
                )
            ),
            step=1,
            key="ui_converter_inverter_lifetime_years",
        )

    with c2:
        capital_cost_per_kw = formatted_number_input(
            f"Capital Cost per kW ({currency_symbol})",
            key="ui_converter_capital_cost_per_kw",
            min_value=0.0,
            value=float(st.session_state.get("ui_converter_capital_cost_per_kw", DEFAULT_CONVERTER.capital_cost_per_kw)),
        )

        replacement_cost_per_kw = formatted_number_input(
            f"Replacement Cost per kW ({currency_symbol})",
            key="ui_converter_replacement_cost_per_kw",
            min_value=0.0,
            value=float(
                st.session_state.get(
                    "converter_replacement_cost_per_kw",
                    DEFAULT_CONVERTER.replacement_cost_per_kw,
                )
            ),
        )

        om_cost_per_kw_per_year = formatted_number_input(
            f"O&M Cost per kW per Year ({currency_symbol})",
            key="ui_converter_om_cost_per_kw_per_year",
            min_value=0.0,
            value=float(
                st.session_state.get(
                    "converter_om_cost_per_kw_per_year",
                    DEFAULT_CONVERTER.om_cost_per_kw_per_year,
                )
            ),
        )

    st.subheader("Inverter / Rectifier Settings")

    c3, c4, c5 = st.columns(3)

    with c3:
        inverter_efficiency_pct = st.number_input(
            "Inverter Efficiency (%)",
            min_value=0.01,
            max_value=100.0,
            value=float(
                st.session_state.get(
                    "converter_inverter_efficiency_pct",
                    DEFAULT_CONVERTER.inverter_efficiency_pct,
                )
            ),
            step=0.5,
            key="ui_converter_inverter_efficiency_pct",
        )

    with c4:
        rectifier_relative_capacity_pct = st.number_input(
            "Rectifier Relative Capacity (%)",
            min_value=0.0,
            max_value=100.0,
            value=float(
                st.session_state.get(
                    "converter_rectifier_relative_capacity_pct",
                    DEFAULT_CONVERTER.rectifier_relative_capacity_pct,
                )
            ),
            step=1.0,
            key="ui_converter_rectifier_relative_capacity_pct",
        )

    with c5:
        rectifier_efficiency_pct = st.number_input(
            "Rectifier Efficiency (%)",
            min_value=0.01,
            max_value=100.0,
            value=float(
                st.session_state.get(
                    "converter_rectifier_efficiency_pct",
                    DEFAULT_CONVERTER.rectifier_efficiency_pct,
                )
            ),
            step=0.5,
            key="ui_converter_rectifier_efficiency_pct",
        )

    parallel_with_ac_generator = st.checkbox(
        "Parallel with AC Generator",
        value=st.session_state.get(
            "converter_parallel_with_ac_generator",
            DEFAULT_CONVERTER.parallel_with_ac_generator,
        ),
        key="ui_converter_parallel_with_ac_generator",
    )

    st.divider()

    if st.button(
        "Validate Converter Configuration",
        type="primary",
        key="ui_converter_validate_button",
    ):
        try:
            capacity_kw_options = _parse_float_list(capacity_kw_options_text)

            converter = ConverterComponentConfig(
                enabled=enabled,
                use_search_space=use_search_space,
                converter_model_name=converter_model_name,
                capacity_kw_options=capacity_kw_options,
                capital_cost_per_kw=float(capital_cost_per_kw),
                replacement_cost_per_kw=float(replacement_cost_per_kw),
                om_cost_per_kw_per_year=float(om_cost_per_kw_per_year),
                inverter_lifetime_years=int(inverter_lifetime_years),
                inverter_efficiency_pct=float(inverter_efficiency_pct),
                rectifier_relative_capacity_pct=float(rectifier_relative_capacity_pct),
                rectifier_efficiency_pct=float(rectifier_efficiency_pct),
                parallel_with_ac_generator=parallel_with_ac_generator,
            )

            validate_converter_component(converter)
            st.success("Converter configuration is valid.")

            with st.expander("Preview Converter Configuration", expanded=False):
                st.json(converter.__dict__)

        except Exception as e:
            st.error(f"Converter configuration validation failed: {e}")


def build_converter_component_from_state(
    *,
    enabled: bool,
    use_search_space: bool,
    converter_model_name: str,
    capacity_kw_options_text: str,
    capital_cost_per_kw: float,
    replacement_cost_per_kw: float,
    om_cost_per_kw_per_year: float,
    inverter_lifetime_years: int,
    inverter_efficiency_pct: float,
    rectifier_relative_capacity_pct: float,
    rectifier_efficiency_pct: float,
    parallel_with_ac_generator: bool,
) -> ConverterComponentConfig:
    capacity_kw_options = _parse_float_list(capacity_kw_options_text)

    return ConverterComponentConfig(
        enabled=enabled,
        use_search_space=use_search_space,
        converter_model_name=converter_model_name,
        capacity_kw_options=capacity_kw_options,
        capital_cost_per_kw=float(capital_cost_per_kw),
        replacement_cost_per_kw=float(replacement_cost_per_kw),
        om_cost_per_kw_per_year=float(om_cost_per_kw_per_year),
        inverter_lifetime_years=int(inverter_lifetime_years),
        inverter_efficiency_pct=float(inverter_efficiency_pct),
        rectifier_relative_capacity_pct=float(rectifier_relative_capacity_pct),
        rectifier_efficiency_pct=float(rectifier_efficiency_pct),
        parallel_with_ac_generator=parallel_with_ac_generator,
    )
