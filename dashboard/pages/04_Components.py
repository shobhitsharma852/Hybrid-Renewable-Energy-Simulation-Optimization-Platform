from __future__ import annotations

from pathlib import Path

import streamlit as st

from dashboard.ui.components.battery_panel import render_battery_component_panel
from dashboard.ui.components.converter_panel import render_converter_component_panel
from dashboard.ui.components.grid_panel import render_grid_component_panel
from dashboard.ui.components.pv_panel import render_pv_component_panel
from dashboard.ui.components.wind_panel import render_wind_component_panel
from dashboard.ui.components_state import (
    COMPONENT_NAMES,
    initialize_component_session,
    load_default_current_component,
    prepare_component_ui_state,
    reload_saved_current_component,
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


def _render_selected_component(selected_component: str) -> None:
    if selected_component == "PV":
        render_pv_component_panel()
    elif selected_component == "Wind":
        render_wind_component_panel()
    elif selected_component == "Battery":
        render_battery_component_panel()
    elif selected_component == "Converter":
        render_converter_component_panel()
    elif selected_component == "Grid":
        render_grid_component_panel()


# ============================================================
# PAGE UI
# ============================================================

top_bar("Components")
render_left_panel()

st.title("⚙️ Components")

folder = _resolve_project_folder()
if folder is None:
    st.warning("Please select a project first.")
    st.stop()

initialize_component_session(st.session_state, folder)

project_name_for_display = folder.name.replace("_", " ")
st.success(f"Project: {project_name_for_display}")

st.divider()

selected_component = st.radio(
    "Select Component",
    COMPONENT_NAMES,
    horizontal=True,
    key="components_selected_component",
    on_change=_sync_component_before_switch,
)

st.divider()

prepare_component_ui_state(st.session_state, selected_component)
_render_selected_component(selected_component)

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
