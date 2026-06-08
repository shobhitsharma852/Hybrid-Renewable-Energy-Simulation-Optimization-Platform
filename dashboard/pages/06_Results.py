from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from core.components.config import load_components
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
        "soh_pct",
        "effective_capacity_kwh",
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
st.caption(
    "Shows the detailed output of the candidate sent from the Optimization page. "
    "Go to Optimization, select a candidate, and click 'Send Selected Candidate to Results'."
)

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

col_refresh, col_info = st.columns([1, 2])

with col_refresh:
    load_saved = st.button("Refresh Results", use_container_width=True)

with col_info:
    st.info(
        "To update results: go to **Optimization** page → select a candidate → "
        "click **Send Selected Candidate to Results**."
    )

hourly_df: pd.DataFrame | None = None
summary_dict: dict | None = None

# ============================================================
# LOAD SAVED OUTPUTS ONLY
# Results always reads from files saved by the Optimization page.
# Running simulation with the raw max-search-space design is intentionally
# removed — use Optimization -> Send to Results for correct candidate output.
# ============================================================
hourly_df, summary_dict = _load_saved_outputs(selected_project)

if hourly_df is None or summary_dict is None:
    st.warning(
        "No simulation outputs found for this project yet.  \n"
        "**Steps to generate results:**  \n"
        "1. Go to the **Optimization** page  \n"
        "2. Run the optimization sweep  \n"
        "3. Select a candidate from the ranked table  \n"
        "4. Click **Send Selected Candidate to Results**  \n"
        "Then come back here to view the detailed output."
    )
    st.stop()

hourly_df = _prepare_chart_df(hourly_df)

st.success("Showing results for the last candidate sent from the Optimization page.")

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

m1, m2, m3, m4, m5 = st.columns(5)
m6, m7, m8, m9 = st.columns(4)

# Net RF = renewable energy served to load / total load (our primary calculation)
net_rf  = _safe_metric(summary_dict, "renewable_fraction")
# Gross RF = renewable generation / (renewable + grid import) — matches HOMER Pro display
pv_kwh  = _safe_metric(summary_dict, "total_pv_generation_kwh")
wind_kwh= _safe_metric(summary_dict, "total_wind_generation_kwh")
grid_imp= _safe_metric(summary_dict, "total_grid_import_kwh")
total_gen = pv_kwh + wind_kwh + grid_imp
gross_rf = (pv_kwh + wind_kwh) / total_gen if total_gen > 0 else 0.0

m1.metric("Total Load (kWh)",  f"{_safe_metric(summary_dict, 'total_load_kwh'):,.2f}")
m2.metric("Served Load (kWh)", f"{_safe_metric(summary_dict, 'total_served_load_kwh'):,.2f}")
m3.metric("Unmet Load (kWh)",  f"{_safe_metric(summary_dict, 'total_unmet_load_kwh'):,.2f}")
m4.metric("Net RF",  f"{net_rf:.1%}",  help="Renewable energy directly served to load / total load")
m5.metric("Gross RF (HOMER)", f"{gross_rf:.1%}", help="Renewable generation / (renewable + grid import) — matches HOMER Pro's Renewable Fraction display")

m6.metric("PV Generation (kWh)",   f"{_safe_metric(summary_dict, 'total_pv_generation_kwh'):,.2f}")
m7.metric("Wind Generation (kWh)", f"{_safe_metric(summary_dict, 'total_wind_generation_kwh'):,.2f}")
m8.metric("Grid Import (kWh)",     f"{_safe_metric(summary_dict, 'total_grid_import_kwh'):,.2f}")
m9.metric("Grid Export (kWh)",     f"{_safe_metric(summary_dict, 'total_grid_export_kwh'):,.2f}")

m9, m10, m11, m12 = st.columns(4)
m9.metric("Battery Charge (kWh)", f"{_safe_metric(summary_dict, 'total_battery_charge_kwh'):,.2f}")
m10.metric("Battery Discharge (kWh)", f"{_safe_metric(summary_dict, 'total_battery_discharge_kwh'):,.2f}")
m11.metric("Inverter Loss (kWh)", f"{_safe_metric(summary_dict, 'total_inverter_loss_kwh'):,.2f}")
m12.metric("Rectifier Loss (kWh)", f"{_safe_metric(summary_dict, 'total_rectifier_loss_kwh'):,.2f}")

m13, m14, m15, m16 = st.columns(4)
m13.metric(
    "Final State of Health (%)",
    f"{_safe_metric(summary_dict, 'final_soh_pct', default=100.0):.2f}",
    help="Battery SoH at the end of the simulation year. 100% = no degradation.",
)
m14.metric(
    "Min Capacity (kWh)",
    f"{_safe_metric(summary_dict, 'min_effective_capacity_kwh'):,.2f}",
    help="Lowest effective capacity seen during the year after all aging.",
)
m15.metric(
    "Total Throughput (kWh)",
    f"{_safe_metric(summary_dict, 'total_battery_throughput_kwh'):,.2f}",
    help="Total energy cycled through the battery (charge + discharge halves).",
)
m16.metric(
    "Self-discharge Loss (kWh)",
    f"{_safe_metric(summary_dict, 'total_self_discharge_loss_kwh'):,.2f}",
    help="Energy lost passively to self-discharge over the year.",
)

# ============================================================
# CHARTS
# ============================================================
st.subheader("Charts")

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
    [
        "Load vs Served",
        "PV & Wind",
        "Battery",
        "Grid",
        "Unmet / Excess",
        "Battery Health",
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

with tab6:
    has_health_data = (
        "soh_pct" in hourly_df.columns
        and "effective_capacity_kwh" in hourly_df.columns
    )

    if not has_health_data:
        st.info(
            "Battery health columns (soh_pct, effective_capacity_kwh) are not present "
            "in the saved outputs. Re-run the simulation to generate them."
        )
    else:
        st.caption(
            "State of Health (SoH) and effective capacity over the simulation year. "
            "A flat line at 100% / nominal capacity means aging was disabled or negligible. "
            "Enable Replacement Degradation Limit, Cycle Life A, or Calendar Fade in the "
            "Components panel to see degradation."
        )

        soh_chart = _chart_frame(hourly_df, ["soh_pct"])
        if soh_chart is not None:
            st.subheader("State of Health (%)")
            st.line_chart(soh_chart)

        cap_chart = _chart_frame(hourly_df, ["effective_capacity_kwh"])
        if cap_chart is not None:
            st.subheader("Effective Capacity (kWh)")
            st.line_chart(cap_chart)

        # Show min/final summary inline so the numbers are visible alongside the chart.
        final_soh = _safe_metric(summary_dict, "final_soh_pct", default=100.0)
        min_cap = _safe_metric(summary_dict, "min_effective_capacity_kwh")
        throughput = _safe_metric(summary_dict, "total_battery_throughput_kwh")

        hc1, hc2, hc3 = st.columns(3)
        hc1.metric("Final SoH (%)", f"{final_soh:.2f}")
        hc2.metric("Min Capacity (kWh)", f"{min_cap:,.2f}")
        hc3.metric("Total Throughput (kWh)", f"{throughput:,.2f}")
