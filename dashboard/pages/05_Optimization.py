from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pandas as pd
import streamlit as st

from core.components.config import load_components
from core.economics.evaluator import (
    build_default_economic_assumptions_for_project,
    evaluate_candidate_economics,
)
from core.optimization.design_point import DesignPoint
from core.optimization.insolare_optimizer import (
    load_insolare_optimizer_outputs,
    run_insolare_optimizer,
)
from core.optimization.optimizer import run_optimization_sweep
from core.project import load_project
from core.simulation.run_project_simulation import run_project_simulation
from dashboard.ui.feature_flags import SHOW_INSOLARE_OPTIMIZER_UI
from dashboard.ui.layout import top_bar
from dashboard.ui.sidebar import render_left_panel
from dashboard.ui.state import active_project_name, set_active_project_folder_name


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


def _insolare_csv_path(project_name: str) -> Path:
    return _outputs_dir(project_name) / "insolare_optimizer_summary.csv"


def _insolare_meta_path(project_name: str) -> Path:
    return _outputs_dir(project_name) / "insolare_optimizer_meta.json"


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


def _get_currency_symbol(project_name: str) -> str:
    try:
        project = load_project(Path("projects") / project_name)
        return project.meta.currency_symbol
    except Exception:
        return "₹"


# ============================================================
# MAIN CONTROLS
# ============================================================
projects = _list_projects()

if not projects:
    st.warning("No projects found in the projects folder.")
    st.stop()

def _default_project_index(project_list: list[str]) -> int:
    name = active_project_name()
    if name in project_list:
        return project_list.index(name)
    return 0

selected_project = st.selectbox(
    "Select Project",
    options=projects,
    index=_default_project_index(projects),
)
set_active_project_folder_name(selected_project)

currency_symbol = _get_currency_symbol(selected_project)

# ── Mode selector ────────────────────────────────────────────
# "InSolare Optimizer" mode is hidden behind SHOW_INSOLARE_OPTIMIZER_UI — the
# optimizer itself (core/optimization/insolare_optimizer.py) is untouched,
# only this dashboard entry point is gated. Flip the flag to bring it back.
if SHOW_INSOLARE_OPTIMIZER_UI:
    view_mode = st.radio(
        "Optimizer mode",
        options=["Search Space", "InSolare Optimizer"],
        horizontal=True,
        help=(
            "Search Space: simulates all predefined discrete component options (fast, limited).\n"
            "InSolare Optimizer: continuous search via Differential Evolution — finds globally "
            "optimal sizing without predefined options (~5–10 min)."
        ),
    )
else:
    view_mode = "Search Space"

if SHOW_INSOLARE_OPTIMIZER_UI:
    c1, c2, c3, c4, c5 = st.columns([1.3, 1.5, 1.2, 1.0, 1.0])
else:
    c1, c3, c4, c5 = st.columns([1.3, 1.2, 1.0, 1.0])
    c2 = None

with c1:
    run_search_space = st.button("Run Search Space", use_container_width=True)

if SHOW_INSOLARE_OPTIMIZER_UI:
    with c2:
        run_insolare = st.button("Run InSolare Optimizer", use_container_width=True, type="primary")
else:
    run_insolare = False

with c3:
    load_saved = st.button("Load Saved Outputs", use_container_width=True)

with c4:
    feasible_only = st.checkbox("Feasible Only", value=True)

with c5:
    successful_only = st.checkbox("Successful Runs Only", value=True)

top_n = st.slider("Number of rows to show", min_value=5, max_value=100, value=10, step=5)

optimization_df: pd.DataFrame | None = None
optimization_meta: dict | None = None
run_status = None

# ============================================================
# RUN / LOAD
# ============================================================
if run_search_space:
    progress_bar = st.progress(0.0, text="Starting Search Space optimization…")
    status_text  = st.empty()

    def _on_progress(done: int, total: int) -> None:
        pct = done / total if total > 0 else 0.0
        progress_bar.progress(pct, text=f"Evaluating candidates: {done} / {total}")
        status_text.caption(f"{done}/{total} complete — {total - done} remaining")

    result = run_optimization_sweep(
        project_name=selected_project,
        save_outputs=True,
        progress_callback=_on_progress,
    )
    progress_bar.progress(1.0, text="Search Space optimization complete!")
    status_text.empty()

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
    run_status = "fresh_search_space"

elif run_insolare:
    st.info(
        "InSolare Optimizer running — this takes ~5–10 minutes depending on CPU cores. "
        "Bounds and infeasibility floor are auto-derived from this project's load and components."
    )
    progress_bar = st.progress(0.0, text="Starting InSolare Optimizer…")
    status_text  = st.empty()

    def _on_insolare_progress(gen: int, maxiter: int, convergence: float) -> None:
        pct = min(gen / maxiter, 1.0)
        progress_bar.progress(
            pct,
            text=f"Generation {gen}/{maxiter} — convergence {convergence:.3f}",
        )
        status_text.caption(f"Gen {gen}/{maxiter} complete — population convergence: {convergence:.4f}")

    insolare_result = run_insolare_optimizer(
        project_name=selected_project,
        save_outputs=True,
        progress_callback=_on_insolare_progress,
    )
    progress_bar.progress(1.0, text="InSolare Optimizer complete!")
    status_text.empty()

    optimization_df, optimization_meta = load_insolare_optimizer_outputs(selected_project)
    run_status = "fresh_insolare"

elif load_saved:
    if view_mode == "InSolare Optimizer":
        optimization_df, optimization_meta = load_insolare_optimizer_outputs(selected_project)
    else:
        optimization_df, optimization_meta = _load_saved_optimization_outputs(selected_project)
    run_status = "saved"

else:
    # Auto-load based on selected view mode
    if view_mode == "InSolare Optimizer":
        optimization_df, optimization_meta = load_insolare_optimizer_outputs(selected_project)
    else:
        optimization_df, optimization_meta = _load_saved_optimization_outputs(selected_project)
    run_status = "auto"

if optimization_df is None or optimization_df.empty:
    if view_mode == "InSolare Optimizer":
        st.info("No InSolare Optimizer outputs found. Click 'Run InSolare Optimizer' to generate results.")
    else:
        st.info("No optimization outputs found yet. Click 'Run Search Space' to generate results.")
    st.stop()

optimization_df = _prepare_display_df(optimization_df)

if run_status == "fresh_search_space":
    st.success("Search Space optimization completed and outputs saved.")
elif run_status == "fresh_insolare":
    insolare_d = optimization_meta.get("optimal_design", {}) if optimization_meta else {}
    st.success(
        f"InSolare Optimizer complete — "
        f"PV {insolare_d.get('pv_capacity_kw', 0):,.0f} kW / "
        f"{insolare_d.get('battery_quantity', 0)} strings / "
        f"{insolare_d.get('wind_quantity', 0)} wind — "
        f"NPC {currency_symbol} {optimization_meta.get('optimal_npc', 0):,.0f}"
        if optimization_meta else "InSolare Optimizer complete."
    )
elif run_status == "saved":
    st.success(f"Loaded saved {view_mode} outputs.")
else:
    mode_label = "InSolare Optimizer" if view_mode == "InSolare Optimizer" else "Search Space"
    st.info(f"Showing latest saved {mode_label} outputs.")

# ============================================================
# SUMMARY CARDS
# ============================================================
mode_badge = "🔵 InSolare Optimizer" if view_mode == "InSolare Optimizer" else "⬜ Search Space"
st.subheader(f"Optimization Summary — {mode_badge}")

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
k1.metric("Best Feasible NPC", f"{currency_symbol} {best_npc:,.2f}" if pd.notna(best_npc) else "N/A")
k2.metric("Best Feasible LCOE", f"{currency_symbol}/kWh {best_lcoe:,.4f}" if pd.notna(best_lcoe) else "N/A")

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
        "total_capacity_shortage_kwh",
        "total_reserve_shortfall_kwh",
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
    d3.metric("NPC", f"{currency_symbol} {_safe_float(selected_row.get('net_present_cost')):,.2f}")
    d4.metric("LCOE", f"{currency_symbol}/kWh {_safe_float(selected_row.get('levelized_cost_of_energy')):,.4f}")
    d5.metric("Annualized Total Cost", f"{currency_symbol} {_safe_float(selected_row.get('annualized_total_cost')):,.2f}")
    d6.metric("Direct Capital Cost", f"{currency_symbol} {_safe_float(selected_row.get('direct_capital_cost')):,.2f}")

extra1, extra2, extra3, extra4 = st.columns(4)
extra1.metric("Annual Grid Net Cost", f"{currency_symbol} {_safe_float(selected_row.get('annual_grid_net_cost')):,.2f}")
extra2.metric("Capacity Shortage", f"{_safe_float(selected_row.get('total_capacity_shortage_kwh')):,.1f} kWh")
extra3.metric("Reserve Shortfall", f"{_safe_float(selected_row.get('total_reserve_shortfall_kwh')):,.1f} kWh")
extra4.metric("Run Success", str(_safe_bool(selected_row.get('run_success'))))

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

    with st.spinner("Running detailed simulation and computing economics..."):
        sim_results = run_project_simulation(
            project_name=selected_project,
            save_outputs=True,
            design=design,
        )

        # Compute full economics for this candidate and save alongside simulation outputs
        try:
            components   = load_components(Path("projects") / selected_project)
            assumptions  = build_default_economic_assumptions_for_project(
                selected_project, components
            )
            econ = evaluate_candidate_economics(
                project_name=selected_project,
                components=components,
                design=design,
                simulation_results=sim_results,
                assumptions=assumptions,
            )

            # Resolve currency symbol from project metadata
            try:
                currency_sym = load_project(Path("projects") / selected_project).meta.currency_symbol
            except Exception:
                currency_sym = "$"

            econ_payload = {
                "currency_symbol":     currency_sym,
                "project_life_years":  assumptions.project_life_years,
                "real_discount_rate_pct": assumptions.real_discount_rate_pct,
                "design": {
                    "pv_capacity_kw":      design.pv_capacity_kw,
                    "wind_quantity":       design.wind_quantity,
                    "battery_quantity":    design.battery_quantity,
                    "converter_capacity_kw": design.converter_capacity_kw,
                },
                "economics": asdict(econ),
            }

            econ_path = Path("projects") / selected_project / "outputs" / "results_economics.json"
            econ_path.parent.mkdir(parents=True, exist_ok=True)
            econ_path.write_text(
                json.dumps(econ_payload, indent=2, default=float),
                encoding="utf-8",
            )
        except Exception as exc:
            st.warning(f"Simulation saved but economics computation failed: {exc}")

    st.success(
        f"Candidate {int(selected_candidate_id)} simulated and economics saved. "
        f"Open the Results page to inspect hourly charts, KPIs, and NPC breakdown."
    )

# ============================================================
# SAVED FILES INFO
# ============================================================
with st.expander("Optimization Output Files", expanded=False):
    st.write(f"Summary CSV: `{_optimization_csv_path(selected_project)}`")
    st.write(f"Meta JSON: `{_optimization_meta_path(selected_project)}`")
