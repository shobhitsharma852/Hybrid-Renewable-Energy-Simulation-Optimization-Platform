from __future__ import annotations

from pathlib import Path

import streamlit as st

from dashboard.ui.components.battery_panel import render_battery_component_panel
from dashboard.ui.components.converter_panel import render_converter_component_panel
from dashboard.ui.components.grid_panel import render_grid_component_panel
from dashboard.ui.components.pv_panel import render_pv_component_panel
from dashboard.ui.components.wind_panel import render_wind_component_panel
from core.project import load_project
from dashboard.ui.components_state import (
    COMPONENT_NAMES,
    COMPONENT_TO_JSON_KEY,
    initialize_component_session,
    load_default_current_component,
    prepare_component_ui_state,
    reload_saved_current_component,
    save_components_dict,
    save_current_component,
    sync_last_rendered_component_before_switch,
    sync_selected_component_to_draft,
)
from dashboard.ui.layout import top_bar
from dashboard.ui.sidebar import render_left_panel
from dashboard.ui.state import active_project_folder


st.set_page_config(
    page_title="Components",
    page_icon="🧩",
    layout="wide",
)


def _resolve_project_folder() -> Path | None:
    folder = active_project_folder()
    if folder is None:
        return None
    return Path(folder)


def _sync_component_before_switch() -> None:
    sync_last_rendered_component_before_switch(st.session_state)


def _get_currency_symbol(folder: Path) -> str:
    try:
        return load_project(folder).meta.currency_symbol
    except Exception:
        return "₹"


def _save_all_components(folder: Path, state: dict) -> Path:
    """Sync all 5 components from UI to draft then save the full dict at once."""
    for name in COMPONENT_NAMES:
        sync_selected_component_to_draft(state, name)
    import copy
    return save_components_dict(copy.deepcopy(state["_components_draft"]), folder)


def _render_system_summary(state: dict, currency_symbol: str) -> None:
    """One-glance table showing all 5 components' status, sizes, and key costs."""
    draft = state.get("_components_draft", {})
    if not draft:
        return

    rows = []

    # PV
    pv = draft.get("pv", {})
    pv_opts = pv.get("capacity_kw_options", [0])
    rows.append({
        "Component": "PV Solar",
        "Status": "Enabled" if pv.get("enabled") else "Disabled",
        "Search Space": f"{pv_opts} kW",
        "Max Size": f"{max(pv_opts):,.0f} kW",
        f"Capital ({currency_symbol})": f"{pv.get('capital_cost_per_kw', 0):,.0f}/kW",
        "Lifetime": f"{pv.get('lifetime_years', 0)} yr",
    })

    # Wind
    wind = draft.get("wind", {})
    wind_opts = wind.get("quantity_options", [0])
    rated = wind.get("rated_capacity_kw", 0)
    rows.append({
        "Component": "Wind",
        "Status": "Enabled" if wind.get("enabled") else "Disabled",
        "Search Space": f"{wind_opts} turbines",
        "Max Size": f"{max(wind_opts) * rated:,.0f} kW",
        f"Capital ({currency_symbol})": f"{wind.get('capital_cost_per_turbine', 0):,.0f}/turbine",
        "Lifetime": f"{wind.get('lifetime_years', 0)} yr",
    })

    # Battery
    bat = draft.get("battery", {})
    bat_opts = bat.get("quantity_options", [0])
    cap_per = bat.get("nominal_capacity_kwh_per_string", 0)
    rows.append({
        "Component": "Battery",
        "Status": "Enabled" if bat.get("enabled") else "Disabled",
        "Search Space": f"{bat_opts} strings",
        "Max Size": f"{max(bat_opts) * cap_per:,.0f} kWh",
        f"Capital ({currency_symbol})": f"{bat.get('capital_cost_per_string', 0):,.0f}/string",
        "Lifetime": f"{bat.get('lifetime_years', 0)} yr",
    })

    # Converter
    conv = draft.get("converter", {})
    conv_opts = conv.get("capacity_kw_options", [0])
    rows.append({
        "Component": "Converter",
        "Status": "Enabled" if conv.get("enabled") else "Disabled",
        "Search Space": f"{conv_opts} kW",
        "Max Size": f"{max(conv_opts):,.0f} kW",
        f"Capital ({currency_symbol})": f"{conv.get('capital_cost_per_kw', 0):,.0f}/kW",
        "Lifetime": f"{conv.get('inverter_lifetime_years', 0)} yr",
    })

    # Grid
    grid = draft.get("grid", {})
    rows.append({
        "Component": "Grid",
        "Status": "Enabled" if grid.get("enabled") else "Disabled",
        "Search Space": "N/A",
        "Max Size": f"{grid.get('purchase_capacity_kw', 0):,.0f} kW import",
        f"Capital ({currency_symbol})": f"{grid.get('grid_power_price_per_kwh', 0):.4f}/kWh buy",
        "Lifetime": "N/A",
    })

    import pandas as pd
    df = pd.DataFrame(rows).set_index("Component")
    st.dataframe(df, use_container_width=True)


def _render_selected_component(selected_component: str, currency_symbol: str) -> None:
    if selected_component == "PV":
        render_pv_component_panel(currency_symbol=currency_symbol)
    elif selected_component == "Wind":
        render_wind_component_panel(currency_symbol=currency_symbol)
    elif selected_component == "Battery":
        render_battery_component_panel(currency_symbol=currency_symbol)
    elif selected_component == "Converter":
        render_converter_component_panel(currency_symbol=currency_symbol)
    elif selected_component == "Grid":
        render_grid_component_panel(currency_symbol=currency_symbol)


# ============================================================
# PAGE UI
# ============================================================

top_bar("Components")
render_left_panel()

st.title("Components")

folder = _resolve_project_folder()
if folder is None:
    st.warning("Please select a project first.")
    st.stop()

initialize_component_session(st.session_state, folder)

project_name_for_display = folder.name.replace("_", " ")
st.success(f"Project: {project_name_for_display}")
currency_symbol = _get_currency_symbol(folder)

# ── System Summary ────────────────────────────────────────────────────────────
st.divider()
st.subheader("System Summary")
st.caption("Live view of all components — updates as you edit. Save All to persist.")
_render_system_summary(st.session_state, currency_symbol)

if st.button("Save All Components", type="primary", use_container_width=True):
    try:
        path = _save_all_components(folder, st.session_state)
        st.success(f"All 5 components saved to: {path}")
    except Exception as e:
        st.error(f"Could not save all components: {e}")

# ── Per-component editor ──────────────────────────────────────────────────────
st.divider()
st.subheader("Edit Component")

selected_component = st.radio(
    "Select Component",
    COMPONENT_NAMES,
    horizontal=True,
    key="components_selected_component",
    on_change=_sync_component_before_switch,
)

st.divider()

prepare_component_ui_state(st.session_state, selected_component)
_render_selected_component(selected_component, currency_symbol)

sync_selected_component_to_draft(st.session_state, selected_component)
st.session_state["_last_rendered_component"] = selected_component

sync_note = st.session_state.get("_components_sync_note")
if sync_note:
    st.caption(f"State sync note: {sync_note}")

st.divider()

c1, c2, c3 = st.columns(3)

with c1:
    if st.button("Save Current Component Settings", type="primary"):
        try:
            path = save_current_component(folder, st.session_state, selected_component)
            st.success(f"{selected_component} settings saved successfully: {path}")
        except Exception as e:
            st.error(f"Could not save {selected_component} settings: {e}")

with c2:
    if st.button("Reload Saved Component Settings"):
        try:
            reload_saved_current_component(st.session_state, folder, selected_component)
            st.success(f"{selected_component} values reloaded from saved project settings.")
            st.rerun()
        except Exception as e:
            st.error(f"Could not reload saved {selected_component} settings: {e}")

with c3:
    if st.button("Load Default Component Settings"):
        try:
            load_default_current_component(st.session_state, selected_component)
            st.success(
                f"{selected_component} values reset to application defaults. "
                f"Click Save if you want to keep them."
            )
            st.rerun()
        except Exception as e:
            st.error(f"Could not load default {selected_component} settings: {e}")
