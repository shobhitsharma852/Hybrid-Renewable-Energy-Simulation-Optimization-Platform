from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from dashboard.ui.layout import top_bar
from dashboard.ui.sidebar import render_left_panel
from core.optimization.design_point import DesignPoint
from core.optimization.optimizer import run_optimization_sweep
from core.simulation.run_project_simulation import run_project_simulation


st.set_page_config(
    page_title="Optimization",
    page_icon="📈",
    layout="wide",
)

top_bar("Optimization")
render_left_panel()

st.title("Optimization & Best Solutions")
st.caption("Compare candidate systems, filter feasible solutions, and send one selected candidate to the Results page for detailed analysis.")


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


def _optimization_csv_path(project_name: str) -> Path:
    return _outputs_dir(project_name) / "optimization_candidate_summary.csv"


def _optimization_meta_path(project_name: str) -> Path:
    return _outputs_dir(project_name) / "optimization_meta.json"


def _load_saved_optimization_outputs(project_name: str) -> tuple[pd.DataFrame | None, dict | None]:
    csv_path = _optimization_csv_path(project_name)
    meta_path = _optimization_meta_path(project_name)

    df = None
    meta = None

    if csv_path.exists():
        df = pd.read_csv(csv_path)

    if meta_path.exists():
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

    return df, meta


def _safe_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if pd.isna(value):
        return False
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}
    return bool(value)


def _safe_float(value, default: float = 0.0) -> float:
    try:
        if pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def _safe_int(value, default: int = 0) -> int:
    try:
        if pd.isna(value):
            return default
        return int(float(value))
    except Exception:
        return default


def _build_design_point_from_row(row: pd.Series) -> DesignPoint:
    return DesignPoint(
        pv_capacity_kw=_safe_float(row.get("pv_capacity_kw", 0.0)),
        wind_quantity=_safe_int(row.get("wind_quantity", 0)),
        battery_quantity=_safe_int(row.get("battery_quantity", 0)),
        converter_capacity_kw=_safe_float(row.get("converter_capacity_kw", 0.0)),
    )


def _prepare_display_df(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    expected_numeric = [
        "economic_rank",
        "technical_rank",
        "candidate_id",
        "pv_capacity_kw",
        "wind_quantity",
        "battery_quantity",
        "converter_capacity_kw",
        "annual_capacity_shortage_pct",
        "renewable_fraction_pct",
        "reserve_shortfall_hours",
        "direct_capital_cost",
        "annual_grid_net_cost",
        "annualized_total_cost",
        "net_present_cost",
        "levelized_cost_of_energy",
    ]

    for col in expected_numeric:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")

    if "is_feasible" in out.columns:
        out["is_feasible"] = out["is_feasible"].apply(_safe_bool)

    if "run_success" in out.columns:
        out["run_success"] = out["run_success"].apply(_safe_bool)

    return out


def _apply_filters(
    df: pd.DataFrame,
    feasible_only: bool,
    successful_only: bool,
    top_n: int,
) -> pd.DataFrame:
    filtered = df.copy()

    if feasible_only and "is_feasible" in filtered.columns:
        filtered = filtered[filtered["is_feasible"] == True]

    if successful_only and "run_success" in filtered.columns:
        filtered = filtered[filtered["run_success"] == True]

    filtered = filtered.head(top_n).copy()
    return filtered


def _metric_value(meta: dict | None, key: str, default=0):
    if not meta:
        return default
    return meta.get(key, default)


# ============================================================
# MAIN CONTROLS
# ============================================================
projects = _list_projects()

if not projects:
    st.warning("No projects found in the projects folder.")
    st.stop()

selected_project = st.selectbox(
    "Select Project",
    options=projects,
    index=projects.index("Hybrid") if "Hybrid" in projects else 0,
)

c1, c2, c3, c4 = st.columns([1.2, 1.2, 1.0, 1.0])

with c1:
    run_optimization = st.button("Run Optimization", use_container_width=True)

with c2:
    load_saved = st.button("Load Saved Optimization Outputs", use_container_width=True)

with c3:
    feasible_only = st.checkbox("Feasible Only", value=True)

with c4:
    successful_only = st.checkbox("Successful Runs Only", value=True)

top_n = st.slider("Number of rows to show", min_value=5, max_value=100, value=10, step=5)

optimization_df: pd.DataFrame | None = None
optimization_meta: dict | None = None
run_status = None

# ============================================================
# RUN / LOAD
# ============================================================
if run_optimization:
    with st.spinner(f"Running optimization for project: {selected_project}"):
        result = run_optimization_sweep(
            project_name=selected_project,
            save_outputs=True,
        )
        optimization_df = result.to_dataframe()
        optimization_meta = {
            "project_name": result.project_name,
            "constraints_used": result.constraints_used.__dict__,
            "economic_assumptions_used": result.economic_assumptions_used.__dict__,
            "total_raw_combinations": result.total_raw_combinations,
            "total_valid_candidates": result.total_valid_candidates,
            "total_filtered_out": result.total_filtered_out,
            "successful_runs": sum(1 for x in result.candidate_results if x.run_success),
            "failed_runs": sum(1 for x in result.candidate_results if not x.run_success),
            "feasible_candidates": sum(1 for x in result.candidate_results if x.is_feasible),
        }
        run_status = "fresh"

elif load_saved:
    optimization_df, optimization_meta = _load_saved_optimization_outputs(selected_project)
    run_status = "saved"

else:
    optimization_df, optimization_meta = _load_saved_optimization_outputs(selected_project)
    run_status = "auto"

if optimization_df is None or optimization_df.empty:
    st.info("No optimization outputs found yet. Click 'Run Optimization' to generate results.")
    st.stop()

optimization_df = _prepare_display_df(optimization_df)

if run_status == "fresh":
    st.success("Optimization completed and outputs saved.")
elif run_status == "saved":
    st.success("Loaded saved optimization outputs.")
else:
    st.info("Showing latest saved optimization outputs.")

# ============================================================
# SUMMARY CARDS
# ============================================================
st.subheader("Optimization Summary")

s1, s2, s3, s4, s5, s6 = st.columns(6)

s1.metric("Raw Combinations", f"{_metric_value(optimization_meta, 'total_raw_combinations', 0):,}")
s2.metric("Valid Candidates", f"{_metric_value(optimization_meta, 'total_valid_candidates', 0):,}")
s3.metric("Filtered Out", f"{_metric_value(optimization_meta, 'total_filtered_out', 0):,}")
s4.metric("Successful Runs", f"{_metric_value(optimization_meta, 'successful_runs', 0):,}")
s5.metric("Failed Runs", f"{_metric_value(optimization_meta, 'failed_runs', 0):,}")
s6.metric("Feasible Candidates", f"{_metric_value(optimization_meta, 'feasible_candidates', 0):,}")

best_npc = (
    optimization_df.loc[optimization_df["is_feasible"] == True, "net_present_cost"].min()
    if "is_feasible" in optimization_df.columns and "net_present_cost" in optimization_df.columns
    else None
)
best_lcoe = (
    optimization_df.loc[optimization_df["is_feasible"] == True, "levelized_cost_of_energy"].min()
    if "is_feasible" in optimization_df.columns and "levelized_cost_of_energy" in optimization_df.columns
    else None
)

k1, k2 = st.columns(2)
k1.metric("Best Feasible NPC", f"{best_npc:,.2f}" if pd.notna(best_npc) else "N/A")
k2.metric("Best Feasible LCOE", f"{best_lcoe:,.4f}" if pd.notna(best_lcoe) else "N/A")

# ============================================================
# TABLE
# ============================================================
st.subheader("Top Candidate Systems")

filtered_df = _apply_filters(
    optimization_df,
    feasible_only=feasible_only,
    successful_only=successful_only,
    top_n=top_n,
)

if filtered_df.empty:
    st.warning("No rows match the selected filters.")
    st.stop()

display_columns = [
    c for c in [
        "economic_rank",
        "candidate_id",
        "pv_capacity_kw",
        "wind_quantity",
        "battery_quantity",
        "converter_capacity_kw",
        "is_feasible",
        "annual_capacity_shortage_pct",
        "renewable_fraction_pct",
        "net_present_cost",
        "levelized_cost_of_energy",
        "annualized_total_cost",
        "direct_capital_cost",
        "annual_grid_net_cost",
        "failure_reasons",
    ]
    if c in filtered_df.columns
]

st.dataframe(
    filtered_df[display_columns],
    use_container_width=True,
    hide_index=True,
)

# ============================================================
# CANDIDATE DETAIL
# ============================================================
st.subheader("Candidate Detail")

candidate_options = filtered_df["candidate_id"].dropna().astype(int).tolist()
selected_candidate_id = st.selectbox(
    "Select Candidate ID for Detail View",
    options=candidate_options,
)

selected_row = optimization_df.loc[
    optimization_df["candidate_id"].astype(int) == int(selected_candidate_id)
].iloc[0]

detail_left, detail_right = st.columns([1.1, 1.2])

with detail_left:
    st.markdown("### Selected Design")
    st.write(f"**Candidate ID:** {int(selected_row['candidate_id'])}")
    if "economic_rank" in selected_row.index:
        st.write(f"**Economic Rank:** {int(selected_row['economic_rank'])}")
    st.write(f"**PV Capacity (kW):** {_safe_float(selected_row.get('pv_capacity_kw')):,.2f}")
    st.write(f"**Wind Quantity:** {_safe_int(selected_row.get('wind_quantity'))}")
    st.write(f"**Battery Quantity:** {_safe_int(selected_row.get('battery_quantity'))}")
    st.write(f"**Converter Capacity (kW):** {_safe_float(selected_row.get('converter_capacity_kw')):,.2f}")
    st.write(f"**Feasible:** {_safe_bool(selected_row.get('is_feasible'))}")
    st.write(f"**Failure Reasons:** {selected_row.get('failure_reasons', '')}")

with detail_right:
    st.markdown("### Technical & Economic Summary")
    d1, d2 = st.columns(2)
    d3, d4 = st.columns(2)
    d5, d6 = st.columns(2)

    d1.metric("Capacity Shortage (%)", f"{_safe_float(selected_row.get('annual_capacity_shortage_pct')):,.4f}")
    d2.metric("Renewable Fraction (%)", f"{_safe_float(selected_row.get('renewable_fraction_pct')):,.4f}")
    d3.metric("NPC", f"{_safe_float(selected_row.get('net_present_cost')):,.2f}")
    d4.metric("LCOE", f"{_safe_float(selected_row.get('levelized_cost_of_energy')):,.4f}")
    d5.metric("Annualized Total Cost", f"{_safe_float(selected_row.get('annualized_total_cost')):,.2f}")
    d6.metric("Direct Capital Cost", f"{_safe_float(selected_row.get('direct_capital_cost')):,.2f}")

extra1, extra2, extra3 = st.columns(3)
extra1.metric("Annual Grid Net Cost", f"{_safe_float(selected_row.get('annual_grid_net_cost')):,.2f}")
extra2.metric("Reserve Shortfall Hours", f"{_safe_int(selected_row.get('reserve_shortfall_hours')):,}")
extra3.metric("Run Success", str(_safe_bool(selected_row.get('run_success'))))

# ============================================================
# SEND TO RESULTS PAGE
# ============================================================
st.markdown("---")
st.subheader("Open This Candidate in Results Page")

st.caption(
    "This will run a detailed simulation for the selected candidate and save it into the normal Results output files. "
    "Then the Results page will show that candidate in detail."
)

if st.button("Send Selected Candidate to Results", type="primary", use_container_width=True):
    design = _build_design_point_from_row(selected_row)

    with st.spinner("Running detailed simulation for selected candidate..."):
        run_project_simulation(
            project_name=selected_project,
            save_outputs=True,
            design=design,
        )

    st.success(
        f"Candidate {int(selected_candidate_id)} has been simulated and saved to the Results output files. "
        f"Open the Results page to inspect hourly charts and KPIs."
    )

# ============================================================
# SAVED FILES INFO
# ============================================================
with st.expander("Optimization Output Files", expanded=False):
    st.write(f"Summary CSV: `{_optimization_csv_path(selected_project)}`")
    st.write(f"Meta JSON: `{_optimization_meta_path(selected_project)}`")