from __future__ import annotations

from pathlib import Path
import streamlit as st
from .state import active_project_folder


def _exists(p: Path | None, rel: str) -> bool:
    if p is None:
        return False
    return (p / rel).exists()


def render_left_panel():
    
    st.sidebar.markdown("### REQUIRED CHANGES")

    p = active_project_folder()

    has_project = _exists(p, "project.json")
    has_load = _exists(p, "inputs/load.csv")
    has_renew = _exists(p, "inputs/resources.csv")
    has_power = _exists(p, "components.json")   # fixed path

    if not has_project:
        st.sidebar.error("Create or open a project")
    else:
        st.sidebar.success("Project selected")

    if not has_load:
        st.sidebar.error("Add a load")
    else:
        st.sidebar.success("Load added")

    if not has_renew:
        st.sidebar.error("Add a renewable energy source")
    else:
        st.sidebar.success("Renewable source added")

    if not has_power:
        st.sidebar.error("Add a power source")
    else:
        st.sidebar.success("Power source added")

    st.sidebar.markdown("---")
    st.sidebar.caption("Hybrid HOMER Engine (MVP)")