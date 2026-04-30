from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from core.components.config import load_components
from core.simulation.run_project_simulation import run_project_simulation
from dashboard.ui.state import get_state


# ============================================================
# PAGE CONFIG
# ============================================================
st.set_page_config(
    page_title="Simulation Results",
    page_icon="📊",
    layout="wide",
)
st.logo("dashboard/assets/insolare_logo.png", size="large")
st.markdown(
    """
    <style>
    [data-testid="stSidebarHeader"] img {
        max-width: 100% !important;
        width: 100% !important;
        height: auto !important;
    }
    [data-testid="stSidebarHeader"] {
        padding: 0 1rem !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# HELPERS
# ============================================================
def _project_root() -> Path:
    return Path("projects")


def _list_projects() -> list[str]:
    root = _project_root()
    if not root.exists():
        return []

    projects: list[str] = []
    for item in root.iterdir():
        if item.is_dir() and (item / "project.json").exists():
            projects.append(item.name)

    return sorted(projects)


def _outputs_dir(project_name: str) -> Path:
    return Path("projects") / project_name / "outputs"


def _hourly_output_path(project_name: str) -> Path:
    return _outputs_dir(project_name) / "simulation_hourly.csv"


def _summary_output_path(project_name: str) -> Path:
    return _outputs_dir(project_name) / "simulation_summary.json"


def _load_saved_outputs(project_name: str) -> tuple[pd.DataFrame | None, dict | None]:
    hourly_path = _hourly_output_path(project_name)
    summary_path = _summary_output_path(project_name)

    hourly_df = None
    summary_dict = None

    if hourly_path.exists():
        hourly_df = pd.read_csv(hourly_path)

    if summary_path.exists():
        with open(summary_path, "r", encoding="utf-8") as f:
            summary_dict = json.load(f)

    return hourly_df, summary_dict


def _safe_metric(summary: dict | None, key: str, default: float = 0.0) -> float:
    if not summary:
        return default

    value = summary.get(key, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _prepare_chart_df(hourly_df: pd.DataFrame) -> pd.DataFrame:
    df = hourly_df.copy()

    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")

    if "hour_index" in df.columns:
        df["hour_index"] = pd.to_numeric(df["hour_index"], errors="coerce")

    numeric_cols = [
        "load_kw",
        "served_load_kw",
        "pv_kw",
        "wind_kw",
        "battery_soc_pct",
        "battery_charge_kw",
        "battery_discharge_kw",
        "grid_import_kw",
        "grid_export_kw",
        "unmet_load_kw",
        "excess_energy_kw",
    ]

    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


def _chart_frame(hourly_df: pd.DataFrame, value_columns: list[str]) -> pd.DataFrame | None:
    index_column = "timestamp" if "timestamp" in hourly_df.columns else "hour_index"
    cols = [c for c in [index_column, *value_columns] if c in hourly_df.columns]

    if len(cols) < 2 or index_column not in cols:
        return None

    return hourly_df[cols].set_index(index_column)


def _get_default_project_index(projects: list[str]) -> int:
    """
    Default selection priority:
    1. active project from dashboard ui_state.project_name
    2. 'Hybrid' if present
    3. first project
    """
    ui = get_state()
    active_project_name = (ui.project_name or "").strip()

    if active_project_name in projects:
        return projects.index(active_project_name)

    if "Hybrid" in projects:
        return projects.index("Hybrid")

    return 0


def build_system_architecture_lines(project_name: str) -> list[str]:
    """
    Read saved project component configuration and build a simple
    system architecture summary showing only enabled components.
    """
    components = load_components(Path("projects") / project_name)
    lines: list[str] = []

    if components.grid.enabled:
        lines.append(f"Grid ({components.grid.purchase_capacity_kw:,.0f} kW)")

    if components.pv.enabled:
        pv_kw = max(components.pv.capacity_kw_options) if components.pv.capacity_kw_options else 0.0
        lines.append(f"Generic flat plate PV ({pv_kw:,.0f} kW)")

    if components.wind.enabled:
        qty = max(components.wind.quantity_options) if components.wind.quantity_options else 0
        rated_kw = float(components.wind.rated_capacity_kw)
        total_kw = qty * rated_kw
        lines.append(
            f"{components.wind.turbine_model_name} ({qty} x {rated_kw:,.0f} kW = {total_kw:,.0f} kW)"
        )

    if components.battery.enabled:
        qty = max(components.battery.quantity_options) if components.battery.quantity_options else 0
        per_string_kwh = float(components.battery.nominal_capacity_kwh_per_string)
        total_kwh = qty * per_string_kwh
        lines.append(
            f"Battery ({qty} x {per_string_kwh:,.0f} kWh = {total_kwh:,.0f} kWh)"
        )

    if components.converter.enabled:
        conv_kw = max(components.converter.capacity_kw_options) if components.converter.capacity_kw_options else 0.0
        lines.append(f"System Converter ({conv_kw:,.0f} kW)")

    if not lines:
        lines.append("No enabled components found.")

    return lines


# ============================================================
# TITLE
# ============================================================
st.title("Simulation Results")
st.caption("Run a saved project simulation and review hourly outputs, summary metrics, and charts.")

projects = _list_projects()

if not projects:
    st.warning("No projects found in the projects folder.")
    st.stop()

default_project_index = _get_default_project_index(projects)

selected_project = st.selectbox(
    "Select Project",
    options=projects,
    index=default_project_index,
)

col_run, col_saved = st.columns([1, 1])

with col_run:
    run_now = st.button("Run Simulation", use_container_width=True)

with col_saved:
    load_saved = st.button("Load Saved Outputs", use_container_width=True)

hourly_df: pd.DataFrame | None = None
summary_dict: dict | None = None
run_status = None

# ============================================================
# RUN / LOAD
# ============================================================
if run_now:
    with st.spinner(f"Running simulation for project: {selected_project}"):
        results = run_project_simulation(
            project_name=selected_project,
            save_outputs=True,
        )
        hourly_df = results.to_dataframe()
        summary_dict = results.summary.__dict__
        run_status = "fresh"

elif load_saved:
    hourly_df, summary_dict = _load_saved_outputs(selected_project)
    run_status = "saved"

else:
    hourly_df, summary_dict = _load_saved_outputs(selected_project)
    run_status = "auto-saved"

if hourly_df is None or summary_dict is None:
    st.info("No saved outputs found yet. Click 'Run Simulation' to generate results.")
    st.stop()

hourly_df = _prepare_chart_df(hourly_df)

# ============================================================
# STATUS
# ============================================================
if run_status == "fresh":
    st.success("Simulation completed and outputs saved.")
elif run_status == "saved":
    st.success("Loaded saved simulation outputs.")
elif run_status == "auto-saved":
    st.info("Showing latest saved outputs.")

# ============================================================
# SYSTEM ARCHITECTURE
# ============================================================
st.subheader("System Architecture")

try:
    architecture_lines = build_system_architecture_lines(selected_project)
    architecture_text = "  \n".join(architecture_lines)
    st.markdown(architecture_text)
except Exception as e:
    st.warning(f"Could not load system architecture: {e}")

# ============================================================
# OUTPUT FILE INFO
# ============================================================
with st.expander("Output Files", expanded=False):
    st.write(f"Hourly CSV: `{_hourly_output_path(selected_project)}`")
    st.write(f"Summary JSON: `{_summary_output_path(selected_project)}`")

# ============================================================
# SUMMARY METRICS
# ============================================================
st.subheader("Key Metrics")

m1, m2, m3, m4 = st.columns(4)
m5, m6, m7, m8 = st.columns(4)

m1.metric("Total Load (kWh)", f"{_safe_metric(summary_dict, 'total_load_kwh'):,.2f}")
m2.metric("Served Load (kWh)", f"{_safe_metric(summary_dict, 'total_served_load_kwh'):,.2f}")
m3.metric("Unmet Load (kWh)", f"{_safe_metric(summary_dict, 'total_unmet_load_kwh'):,.2f}")
m4.metric("Renewable Fraction", f"{_safe_metric(summary_dict, 'renewable_fraction'):.3f}")

m5.metric("PV Generation (kWh)", f"{_safe_metric(summary_dict, 'total_pv_generation_kwh'):,.2f}")
m6.metric("Wind Generation (kWh)", f"{_safe_metric(summary_dict, 'total_wind_generation_kwh'):,.2f}")
m7.metric("Grid Import (kWh)", f"{_safe_metric(summary_dict, 'total_grid_import_kwh'):,.2f}")
m8.metric("Grid Export (kWh)", f"{_safe_metric(summary_dict, 'total_grid_export_kwh'):,.2f}")

m9, m10, m11, m12 = st.columns(4)
m9.metric("Battery Charge (kWh)", f"{_safe_metric(summary_dict, 'total_battery_charge_kwh'):,.2f}")
m10.metric("Battery Discharge (kWh)", f"{_safe_metric(summary_dict, 'total_battery_discharge_kwh'):,.2f}")
m11.metric("Inverter Loss (kWh)", f"{_safe_metric(summary_dict, 'total_inverter_loss_kwh'):,.2f}")
m12.metric("Rectifier Loss (kWh)", f"{_safe_metric(summary_dict, 'total_rectifier_loss_kwh'):,.2f}")

# ============================================================
# CHARTS
# ============================================================
st.subheader("Charts")

tab1, tab2, tab3, tab4, tab5 = st.tabs(
    [
        "Load vs Served",
        "PV & Wind",
        "Battery",
        "Grid",
        "Unmet / Excess",
    ]
)

with tab1:
    chart_df = _chart_frame(hourly_df, ["load_kw", "served_load_kw"])
    if chart_df is not None:
        st.line_chart(chart_df)
    else:
        st.warning("Required columns for load chart not found.")

with tab2:
    chart_df = _chart_frame(hourly_df, ["pv_kw", "wind_kw"])
    if chart_df is not None:
        st.line_chart(chart_df)
    else:
        st.warning("Required columns for PV/Wind chart not found.")

with tab3:
    chart_df = _chart_frame(hourly_df, ["battery_soc_pct", "battery_charge_kw", "battery_discharge_kw"])
    if chart_df is not None:
        st.line_chart(chart_df)
    else:
        st.warning("Required columns for battery chart not found.")

with tab4:
    chart_df = _chart_frame(hourly_df, ["grid_import_kw", "grid_export_kw"])
    if chart_df is not None:
        st.line_chart(chart_df)
    else:
        st.warning("Required columns for grid chart not found.")

with tab5:
    chart_df = _chart_frame(hourly_df, ["unmet_load_kw", "excess_energy_kw"])
    if chart_df is not None:
        st.line_chart(chart_df)
    else:
        st.warning("Required columns for unmet/excess chart not found.")
