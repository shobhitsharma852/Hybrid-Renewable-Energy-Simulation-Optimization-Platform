from __future__ import annotations

import html as _html
import json
import math
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.components.config import load_components
from core.economics.evaluator import (
    build_default_economic_assumptions_for_project,
    evaluate_candidate_economics,
)
from core.optimization.design_point import DesignPoint
from core.project import load_project
from core.simulation.run_project_simulation import run_project_simulation
from dashboard.ui.state import active_project_name, set_active_project_folder_name

EPSILON: float = 1e-9

# ============================================================
# PAGE CONFIG
# ============================================================
st.set_page_config(page_title="Simulation Results", page_icon="📊", layout="wide")
st.logo("dashboard/assets/insolare_logo.png", size="large")
st.markdown("""
<style>
[data-testid="stSidebarHeader"] img { max-width:100%!important; width:100%!important; height:auto!important; }
[data-testid="stSidebarHeader"] { padding:0 1rem!important; }
.block-container { padding-top:0.8rem!important; padding-bottom:1.2rem!important; }
div[data-testid="stTabs"] > div { padding-top:0.4rem!important; gap:0.25rem!important; }
div[data-testid="stTabs"] button p { font-size:1rem!important; font-weight:600!important; }
[data-testid="stMetricLabel"] p { font-size:0.98rem!important; }
[data-testid="stMetricValue"] { font-size:1.55rem!important; }
[data-testid="stCaptionContainer"] p { font-size:0.92rem!important; }
[data-testid="stDataFrame"] { font-size:0.95rem!important; }
</style>
""", unsafe_allow_html=True)


# ============================================================
# FILE PATH HELPERS
# ============================================================
def _list_projects() -> list[str]:
    root = Path("projects")
    if not root.exists():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir() and (p / "project.json").exists())

def _hourly_path(name: str) -> Path:
    return Path("projects") / name / "outputs" / "simulation_hourly.csv"

def _summary_path(name: str) -> Path:
    return Path("projects") / name / "outputs" / "simulation_summary.json"

def _economics_path(name: str) -> Path:
    return Path("projects") / name / "outputs" / "results_economics.json"

def _load_outputs(name: str):
    hp, sp = _hourly_path(name), _summary_path(name)
    hdf   = pd.read_csv(hp) if hp.exists() else None
    sdict = json.loads(sp.read_text("utf-8")) if sp.exists() else None
    return hdf, sdict

def _load_economics(name: str) -> dict | None:
    p = _economics_path(name)
    return json.loads(p.read_text("utf-8")) if p.exists() else None

def _safe(d: dict | None, key: str, default: float = 0.0) -> float:
    if not d:
        return default
    try:
        return float(d.get(key, default))
    except Exception:
        return default

def _get_default_idx(projects: list[str]) -> int:
    name = active_project_name()
    return projects.index(name) if name in projects else 0


def _refresh_results_for_project(project_name: str) -> None:
    """
    Re-run the detailed simulation for whatever candidate (design point) was last
    sent here from the Optimization page, using the CURRENT saved component
    settings. This is what makes "Refresh Results" actually pick up changes like
    toggling consider_temperature_effects on the Components page — previously the
    button just re-read the same static output files without recomputing anything.
    """
    econ_existing = _load_economics(project_name)
    if not econ_existing or "design" not in econ_existing:
        st.warning(
            "No candidate has been sent to Results yet for this project. "
            "Go to the Optimization page and click 'Send Selected Candidate to Results' first."
        )
        return

    with st.spinner("Re-running simulation with current component settings..."):
        try:
            d = econ_existing["design"]
            design = DesignPoint(
                pv_capacity_kw=float(d["pv_capacity_kw"]),
                wind_quantity=int(d["wind_quantity"]),
                battery_quantity=int(d["battery_quantity"]),
                converter_capacity_kw=float(d["converter_capacity_kw"]),
            )

            sim_results = run_project_simulation(
                project_name=project_name,
                save_outputs=True,
                design=design,
            )

            components  = load_components(Path("projects") / project_name)
            assumptions = build_default_economic_assumptions_for_project(
                project_name, components
            )
            econ = evaluate_candidate_economics(
                project_name=project_name,
                components=components,
                design=design,
                simulation_results=sim_results,
                assumptions=assumptions,
            )

            try:
                currency_sym = load_project(Path("projects") / project_name).meta.currency_symbol
            except Exception:
                currency_sym = econ_existing.get("currency_symbol", "$")

            econ_payload = {
                "currency_symbol": currency_sym,
                "project_life_years": assumptions.project_life_years,
                "real_discount_rate_pct": assumptions.real_discount_rate_pct,
                "design": {
                    "pv_capacity_kw": design.pv_capacity_kw,
                    "wind_quantity": design.wind_quantity,
                    "battery_quantity": design.battery_quantity,
                    "converter_capacity_kw": design.converter_capacity_kw,
                },
                "economics": asdict(econ),
            }

            econ_path = _economics_path(project_name)
            econ_path.parent.mkdir(parents=True, exist_ok=True)
            econ_path.write_text(
                json.dumps(econ_payload, indent=2, default=float),
                encoding="utf-8",
            )

            st.success("Results refreshed with current component settings.")
            st.rerun()
        except Exception as exc:
            st.error(f"Could not refresh results: {exc}")


# ============================================================
# RENDER HELPERS
# ============================================================

def _fmt(v: float, dec: int = 0, pre: str = "", suf: str = "") -> str:
    return f"{pre}{v:,.{dec}f}{suf}"


def _crf_from_economics(econ_payload: dict | None) -> float:
    if not econ_payload:
        return 0.0

    eco = econ_payload.get("economics", {})
    npc = float(eco.get("net_present_cost", 0.0) or 0.0)
    annualized = float(eco.get("annualized_total_cost", 0.0) or 0.0)
    if abs(npc) > EPSILON and annualized > EPSILON:
        return annualized / npc

    life = float(econ_payload.get("project_life_years", 0.0) or 0.0)
    rate = float(econ_payload.get("real_discount_rate_pct", 0.0) or 0.0) / 100.0
    if life <= EPSILON:
        return 0.0
    if rate <= EPSILON:
        return 1.0 / life
    return rate * (1.0 + rate) ** life / ((1.0 + rate) ** life - 1.0)


def _money(v: float, cur: str, dec: int = 2) -> str:
    sign = "-" if v < 0 else ""
    return f"{sign}{cur}{abs(v):,.{dec}f}"


def _cost_components_from_economics(
    eco: dict,
    *,
    scale: float = 1.0,
) -> list[dict[str, float | str]]:
    components = [
        ("Wind", "wind_breakdown"),
        ("Battery", "battery_breakdown"),
        ("PV", "pv_breakdown"),
        ("Grid", "grid_breakdown"),
        ("Converter", "converter_breakdown"),
    ]
    rows: list[dict[str, float | str]] = []
    for label, key in components:
        bd = eco.get(key, {}) or {}
        capital = float(bd.get("capital", 0.0) or 0.0) * scale
        replacement = float(bd.get("replacement_pv", 0.0) or 0.0) * scale
        operating = float(bd.get("om_pv", 0.0) or 0.0) * scale
        fuel = 0.0
        salvage = -float(bd.get("salvage_pv", 0.0) or 0.0) * scale
        total = capital + replacement + operating + fuel + salvage
        rows.append({
            "Component": label,
            "Capital": capital,
            "Replacement": replacement,
            "O&M": operating,
            "Fuel": fuel,
            "Salvage": salvage,
            "Total": total,
        })
    return rows


def _cost_system_row(rows: list[dict[str, float | str]]) -> dict[str, float | str]:
    totals = {
        "Component": "Total",
        "Capital": 0.0,
        "Replacement": 0.0,
        "O&M": 0.0,
        "Fuel": 0.0,
        "Salvage": 0.0,
        "Total": 0.0,
    }
    for row in rows:
        for key in ["Capital", "Replacement", "O&M", "Fuel", "Salvage", "Total"]:
            totals[key] = float(totals[key]) + float(row.get(key, 0.0) or 0.0)
    return totals


def _cost_table_dataframe(rows: list[dict[str, float | str]], cur: str) -> pd.DataFrame:
    display_rows = rows + [_cost_system_row(rows)]
    return pd.DataFrame([
        {
            "Component": row["Component"],
            f"Capital ({cur})": _money(float(row["Capital"]), cur),
            f"Replacement ({cur})": _money(float(row["Replacement"]), cur),
            f"O&M ({cur})": _money(float(row["O&M"]), cur),
            f"Fuel ({cur})": _money(float(row["Fuel"]), cur),
            f"Salvage ({cur})": _money(float(row["Salvage"]), cur),
            f"Total ({cur})": _money(float(row["Total"]), cur),
        }
        for row in display_rows
    ])


def _metric_table(rows: list[tuple[str, str, str]], title: str = "", col1_header: str = "Quantity",
                  stripe: bool = False) -> None:
    """Compact HOMER-style  Quantity | Value | Units  table rendered as HTML.
    stripe=True  → alternating white/#f2f2f2 rows
    stripe=False → all white rows separated by a gray bottom border
    """
    lines = []
    if title:
        lines.append(
            f"<p style='font-weight:700;margin:10px 0 5px 0;font-size:1rem;color:#25324a;'>"
            f"{_html.escape(title)}</p>"
        )
    lines.append(
        "<table style='width:100%;border-collapse:collapse;font-size:0.95rem;line-height:1.35;margin-bottom:10px;'>"
        "<thead><tr style='background:#e8f0fe;'>"
        f"<th style='text-align:left;padding:7px 9px;border:1px solid #c5d4f5;'>{_html.escape(col1_header)}</th>"
        "<th style='text-align:right;padding:7px 9px;border:1px solid #c5d4f5;'>Value</th>"
        "<th style='text-align:left;padding:7px 9px;border:1px solid #c5d4f5;'>Units</th>"
        "</tr></thead><tbody>"
    )
    for i, (qty, val, unit) in enumerate(rows):
        bg = "#ffffff" if not stripe else ("#ffffff" if i % 2 == 0 else "#f2f2f2")
        lines.append(
            f"<tr style='background:{bg};'>"
            f"<td style='padding:7px 9px;border:1px solid #e4eaf8;'>{_html.escape(str(qty))}</td>"
            f"<td style='text-align:right;padding:7px 9px;border:1px solid #e4eaf8;"
            f"font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-weight:600;'>"
            f"{_html.escape(str(val))}</td>"
            f"<td style='padding:7px 9px;border:1px solid #e4eaf8;color:#4b5563;'>"
            f"{_html.escape(str(unit))}</td></tr>"
        )
    lines.append("</tbody></table>")
    st.markdown("".join(lines), unsafe_allow_html=True)


def _energy_table(rows: list[tuple[str, float, float]], col1: str = "Source",
                  bold_last: bool = True) -> None:
    """HOMER-style  col1 | kWh/yr | %  table.
    When bold_last=True the last row is styled as a bold Total row."""
    lines = []
    lines.append(
        "<table style='width:100%;border-collapse:collapse;font-size:0.95rem;line-height:1.35;margin-bottom:10px;'>"
        "<thead><tr style='background:#d4e3f7;'>"
        f"<th style='text-align:left;padding:7px 9px;border:1px solid #b8cfeb;font-weight:700;'>"
        f"{_html.escape(col1)}</th>"
        "<th style='text-align:right;padding:7px 9px;border:1px solid #b8cfeb;font-weight:700;'>kWh/yr</th>"
        "<th style='text-align:right;padding:7px 9px;border:1px solid #b8cfeb;font-weight:700;'>%</th>"
        "</tr></thead><tbody>"
    )
    data_rows = rows[:-1] if bold_last else rows
    for i, (name, kwh, pct) in enumerate(data_rows):
        lines.append(
            f"<tr style='background:#ffffff;'>"
            f"<td style='padding:7px 9px;border:1px solid #e4eaf8;'>{_html.escape(str(name))}</td>"
            f"<td style='text-align:right;padding:7px 9px;border:1px solid #e4eaf8;"
            f"font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-weight:600;'>"
            f"{_html.escape(_fmt(kwh))}</td>"
            f"<td style='text-align:right;padding:7px 9px;border:1px solid #e4eaf8;"
            f"font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-weight:600;'>"
            f"{_html.escape(_fmt(pct, 3))}</td>"
            f"</tr>"
        )
    if bold_last and rows:
        name, kwh, pct = rows[-1]
        lines.append(
            f"<tr style='background:#d4e3f7;font-weight:600;'>"
            f"<td style='padding:7px 9px;border:1px solid #b8cfeb;'>{_html.escape(str(name))}</td>"
            f"<td style='text-align:right;padding:7px 9px;border:1px solid #b8cfeb;"
            f"font-family:ui-monospace,SFMono-Regular,Consolas,monospace;'>{_html.escape(_fmt(kwh))}</td>"
            f"<td style='text-align:right;padding:7px 9px;border:1px solid #b8cfeb;"
            f"font-family:ui-monospace,SFMono-Regular,Consolas,monospace;'>{_html.escape(_fmt(pct, 1))}</td>"
            f"</tr>"
        )
    lines.append("</tbody></table>")
    st.markdown("".join(lines), unsafe_allow_html=True)


def _style_figure(fig: go.Figure) -> go.Figure:
    fig.update_layout(
        font=dict(size=14),
        title_font=dict(size=17),
        legend_font=dict(size=13),
        xaxis=dict(title_font=dict(size=14), tickfont=dict(size=13)),
        yaxis=dict(title_font=dict(size=14), tickfont=dict(size=13)),
        hoverlabel=dict(font_size=14),
    )
    return fig


def _heatmap(values: np.ndarray, title: str, unit: str,
             colorscale: str = "YlOrRd", height: int = 390,
             timestamps: pd.Series | None = None) -> go.Figure:
    """8 760-point 1-D array  →  24 (hour-of-day) × 365 (day-of-year) Plotly heatmap."""
    v = np.asarray(values, dtype=float)
    if timestamps is not None and len(timestamps) == len(v):
        frame = pd.DataFrame({
            "timestamp": pd.to_datetime(timestamps, errors="coerce"),
            "value": v,
        }).dropna(subset=["timestamp"])
        frame["_day"] = frame["timestamp"].dt.dayofyear
        frame["_hour"] = frame["timestamp"].dt.hour
        matrix = (
            frame.groupby(["_hour", "_day"])["value"]
            .mean()
            .unstack("_day")
            .reindex(index=range(24), columns=range(1, 366), fill_value=0.0)
            .fillna(0.0)
            .to_numpy()
        )
    elif len(v) < 8760:
        v = np.pad(v, (0, 8760 - len(v)))
        matrix = v.reshape(365, 24).T
    else:
        v = v[:8760]
        matrix = v.reshape(365, 24).T
    fig = go.Figure(go.Heatmap(
        z=matrix,
        x=list(range(1, 366)),
        y=list(range(24)),
        colorscale=colorscale,
        colorbar=dict(title=dict(text=unit, font=dict(size=13)), tickfont=dict(size=12),
                      thickness=14, len=0.85),
    ))
    fig.update_layout(
        title=dict(text=title, font=dict(size=17)),
        xaxis_title="Day of Year",
        yaxis_title="Hour of Day",
        height=height,
        margin=dict(l=45, r=15, t=35, b=35),
    )
    return _style_figure(fig)


def _monthly_bar(hourly_df: pd.DataFrame, cols: list[str], names: list[str],
                 colors: list[str], title: str, height: int = 360) -> go.Figure:
    """Monthly stacked bar chart from hourly DataFrame."""
    df = hourly_df.copy()
    df["_m"] = pd.to_datetime(df["timestamp"], errors="coerce").dt.month
    timestamps = pd.to_datetime(df["timestamp"], errors="coerce")
    valid_diffs = timestamps.diff().dt.total_seconds().dropna()
    dt_hours = float(valid_diffs.median() / 3600.0) if not valid_diffs.empty else 1.0
    mnames = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    monthly = (
        df.groupby("_m")[cols].sum().reindex(range(1, 13), fill_value=0)
        * dt_hours
    )
    fig = go.Figure()
    for col, name, color in zip(cols, names, colors):
        fig.add_trace(go.Bar(x=mnames, y=monthly[col].values, name=name, marker_color=color))
    fig.update_layout(
        barmode="stack",
        title=dict(text=title, font=dict(size=17)),
        xaxis_title="Month", yaxis_title="Energy (kWh)",
        height=height,
        legend=dict(orientation="h", y=1.08, x=0, font=dict(size=13)),
        margin=dict(l=50, r=10, t=55, b=35),
    )
    return _style_figure(fig)


def _dod_histogram(hourly_df: pd.DataFrame, height: int = 280) -> go.Figure:
    """Depth-of-Discharge cycle distribution from SOC + discharge timeseries."""
    dod_values: list[float] = []
    if "battery_soc_pct" in hourly_df.columns and "battery_discharge_dc_kw" in hourly_df.columns:
        soc   = hourly_df["battery_soc_pct"].values
        disch = hourly_df["battery_discharge_dc_kw"].values
        in_disch = False
        peak_soc = float(soc[0])
        for i in range(len(soc)):
            if disch[i] > 0.1:
                if not in_disch:
                    in_disch = True
                    peak_soc = float(soc[i - 1]) if i > 0 else float(soc[i])
            else:
                if in_disch:
                    in_disch = False
                    dod = peak_soc - float(soc[i])
                    if dod > 1.0:
                        dod_values.append(dod)

    bins   = list(range(0, 91, 10))
    labels = [f"{b}–{b+10}%" for b in bins[:-1]]
    counts = [0] * len(labels)
    for d in dod_values:
        idx = min(int(d // 10), len(labels) - 1)
        counts[idx] += 1

    fig = go.Figure(go.Bar(x=labels, y=counts, marker_color="#1a5fb4", showlegend=False))
    fig.update_layout(
        title=dict(text="Cycle DoD Distribution", font=dict(size=17)),
        xaxis_title="Depth of Discharge", yaxis_title="Cycles",
        height=height, margin=dict(l=40, r=10, t=35, b=35),
    )
    return _style_figure(fig)


def _monthly_soc_box(hourly_df: pd.DataFrame, height: int = 280) -> go.Figure:
    """Monthly battery SOC box plots."""
    df = hourly_df.copy()
    df["_m"] = pd.to_datetime(df["timestamp"], errors="coerce").dt.month
    mnames = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    fig = go.Figure()
    for m_idx, mname in enumerate(mnames, 1):
        vals = df[df["_m"] == m_idx]["battery_soc_pct"].dropna().values
        fig.add_trace(go.Box(y=vals, name=mname, showlegend=False,
                             marker_color="#1a5fb4", boxmean=True))
    fig.update_layout(
        title=dict(text="Monthly SOC (%)", font=dict(size=17)),
        yaxis_title="SOC (%)", xaxis_title="Month",
        height=height, margin=dict(l=40, r=10, t=35, b=35),
    )
    return _style_figure(fig)


def _cash_flow_chart(econ_payload: dict, components_cfg, summary_dict: dict,
                     cur: str, height: int = 420) -> go.Figure:
    """Year-by-year undiscounted cash flow stacked bar."""
    N      = int(econ_payload.get("project_life_years", 25))
    r_real = float(econ_payload.get("real_discount_rate_pct", 0.0)) / 100.0
    design = econ_payload.get("design", {})
    eco    = econ_payload.get("economics", {})

    pv_kw   = float(design.get("pv_capacity_kw", 0))
    wnd_qty = int(design.get("wind_quantity", 0))
    bat_qty = int(design.get("battery_quantity", 0))
    conv_kw = float(design.get("converter_capacity_kw", 0))

    def _attr(obj, name: str, default: float = 0.0) -> float:
        return float(getattr(obj, name, default)) if obj else default

    # Undiscounted replacement costs (nominal, total for the bank/fleet)
    pv_repl   = pv_kw   * _attr(components_cfg.pv,        "replacement_cost_per_kw")
    wnd_repl  = wnd_qty * _attr(components_cfg.wind,       "replacement_cost_per_turbine")
    bat_repl  = bat_qty * _attr(components_cfg.battery,    "replacement_cost_per_string")
    conv_repl = conv_kw * _attr(components_cfg.converter,  "replacement_cost_per_kw")

    # Capital (year 0)
    pv_cap   = pv_kw   * _attr(components_cfg.pv,        "capital_cost_per_kw")
    wnd_cap  = wnd_qty * _attr(components_cfg.wind,       "capital_cost_per_turbine")
    bat_cap  = bat_qty * _attr(components_cfg.battery,    "capital_cost_per_string")
    conv_cap = conv_kw * _attr(components_cfg.converter,  "capital_cost_per_kw")

    # Component lifetimes
    pv_life   = max(1.0, _attr(components_cfg.pv,       "lifetime_years",         25.0))
    wnd_life  = max(1.0, _attr(components_cfg.wind,      "lifetime_years",         20.0))
    bat_cal   = max(1.0, _attr(components_cfg.battery,   "lifetime_years",         15.0))
    conv_life = max(1.0, _attr(components_cfg.converter, "inverter_lifetime_years", 15.0))

    # Battery effective life (min of calendar and throughput)
    per_str_tput = _attr(components_cfg.battery, "throughput_kwh", 3e6)
    annual_tput  = float(summary_dict.get("total_battery_throughput_kwh", 0))
    if per_str_tput > EPSILON and annual_tput > EPSILON and bat_qty > 0:
        bat_life = min(bat_cal, (per_str_tput * bat_qty) / annual_tput)
    else:
        bat_life = bat_cal

    # Annual flows — use economics JSON values directly (already computed correctly)
    annual_comp_om = float(eco.get("annual_fixed_om_cost", 0))
    annual_grid    = float(eco.get("annual_grid_net_cost",  0))

    years     = list(range(N + 1))
    capital_y = [0.0] * (N + 1)
    repl_y    = [0.0] * (N + 1)
    om_y      = [0.0] * (N + 1)
    grid_y    = [0.0] * (N + 1)
    salvage_y = [0.0] * (N + 1)

    capital_y[0] = pv_cap + wnd_cap + bat_cap + conv_cap
    for yr in range(1, N + 1):
        om_y[yr]   = annual_comp_om
        grid_y[yr] = annual_grid

    # Replacements + salvage per component
    for comp_life, comp_repl in [
        (pv_life,   pv_repl),
        (wnd_life,  wnd_repl),
        (bat_life,  bat_repl),
        (conv_life, conv_repl),
    ]:
        if comp_repl < EPSILON or comp_life < EPSILON:
            continue
        n_repl = math.ceil(N / comp_life) - 1
        for k in range(1, n_repl + 1):
            yr = int(round(k * comp_life))
            if 0 < yr <= N:
                repl_y[yr] += comp_repl
        # Salvage at project end
        last_install = n_repl * comp_life
        remaining    = (last_install + comp_life) - N
        if remaining > EPSILON:
            salvage_y[N] -= comp_repl * (remaining / comp_life)

    fig = go.Figure()
    fig.add_trace(go.Bar(x=years, y=capital_y, name="Capital",     marker_color="#1a5fb4"))
    fig.add_trace(go.Bar(x=years, y=repl_y,    name="Replacement", marker_color="#e5a50a"))
    fig.add_trace(go.Bar(x=years, y=om_y,      name="O&M",         marker_color="#26a269"))
    fig.add_trace(go.Bar(x=years, y=grid_y,    name="Grid",        marker_color="#7a7a7a"))
    fig.add_trace(go.Bar(x=years, y=salvage_y, name="Salvage",     marker_color="#c01c28"))
    fig.update_layout(
        barmode="relative",
        title=dict(text="Annual Cash Flow by Category (Undiscounted Nominal)", font=dict(size=17)),
        xaxis_title="Year", yaxis_title=f"Cost ({cur})",
        height=height,
        legend=dict(orientation="h", y=1.06, x=0, font=dict(size=13)),
        margin=dict(l=60, r=10, t=55, b=35),
    )
    return _style_figure(fig)


def _prepare_hourly(df: pd.DataFrame) -> pd.DataFrame:
    """Parse types and add derived columns (inverter_output_kw, rectifier_output_kw)."""
    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    numeric_cols = [
        "load_kw","pv_kw","wind_kw","renewable_kw",
        "served_load_kw","excess_energy_kw","unmet_load_kw",
        "battery_charge_kw","battery_discharge_kw","battery_discharge_dc_kw","battery_soc_pct",
        "grid_import_kw","grid_export_kw",
        "inverter_loss_kw","rectifier_loss_kw",
        "inverter_input_dc_kw","inverter_output_ac_kw",
        "rectifier_input_ac_kw","rectifier_output_dc_kw",
        "effective_capacity_kwh","soh_pct",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    # New outputs include explicit converter flows. Keep a fallback for older
    # saved simulations that predate those fields.
    pv    = df["pv_kw"].values                  if "pv_kw"                  in df.columns else np.zeros(len(df))
    bddc  = df["battery_discharge_dc_kw"].values if "battery_discharge_dc_kw" in df.columns else np.zeros(len(df))
    iloss = df["inverter_loss_kw"].values        if "inverter_loss_kw"        in df.columns else np.zeros(len(df))
    if "inverter_output_ac_kw" in df.columns:
        df["inverter_output_kw"] = df["inverter_output_ac_kw"]
    else:
        df["inverter_output_kw"] = np.clip(pv + bddc - iloss, 0, None)

    # Rectifier DC output = DC into battery terminals (= battery_charge_kw)
    if "rectifier_output_dc_kw" in df.columns:
        df["rectifier_output_kw"] = df["rectifier_output_dc_kw"]
    else:
        df["rectifier_output_kw"] = (
            df["battery_charge_kw"].values
            if "battery_charge_kw" in df.columns
            else np.zeros(len(df))
        )

    return df


def _arch_summary(project_name: str) -> str:
    """Single-line system architecture caption."""
    try:
        c = load_components(Path("projects") / project_name)
        parts = []
        if c.grid.enabled:
            parts.append("Grid")
        if c.pv.enabled:
            kw = max(c.pv.capacity_kw_options) if c.pv.capacity_kw_options else 0
            parts.append(f"PV {kw:,.0f} kW")
        if c.wind.enabled:
            qty = max(c.wind.quantity_options) if c.wind.quantity_options else 0
            parts.append(f"Wind {qty}×{c.wind.rated_capacity_kw:,.0f} kW")
        if c.battery.enabled:
            qty = max(c.battery.quantity_options) if c.battery.quantity_options else 0
            parts.append(f"Battery {qty}×{c.battery.nominal_capacity_kwh_per_string:,.0f} kWh")
        if c.converter.enabled:
            kw = max(c.converter.capacity_kw_options) if c.converter.capacity_kw_options else 0
            parts.append(f"Converter {kw:,.0f} kW")
        return "  |  ".join(parts)
    except Exception:
        return ""


def _arch_summary_lines(project_name: str, design: dict | None = None) -> list[str]:
    """
    Per-component lines for the HOMER-style architecture header.

    Shows the ACTUAL sizes from the candidate design that was sent to Results
    (design['pv_capacity_kw'], etc. from results_economics.json) — those are
    what the displayed NPC/LCOE/cost-table numbers were computed from. Falls
    back to the max of each component's configured search-space options only
    when no candidate has been sent to Results yet, so the header isn't blank.
    """
    try:
        c = load_components(Path("projects") / project_name)
        design = design or {}
        lines = []
        if c.pv.enabled:
            kw = design.get("pv_capacity_kw")
            if kw is None:
                kw = max(c.pv.capacity_kw_options) if c.pv.capacity_kw_options else 0
            lines.append(f"Generic flat plate PV ({kw:,.0f} kW)")
        if c.wind.enabled:
            qty = design.get("wind_quantity")
            if qty is None:
                qty = max(c.wind.quantity_options) if c.wind.quantity_options else 0
            lines.append(f"Generic {c.wind.rated_capacity_kw / 1000:.1f} MW ({qty:.2f})")
        if c.battery.enabled:
            qty = design.get("battery_quantity")
            if qty is None:
                qty = max(c.battery.quantity_options) if c.battery.quantity_options else 0
            lines.append(
                f"Generic {c.battery.nominal_capacity_kwh_per_string:.0f} kWh "
                f"Li-Ion ({qty:.2f} strings)"
            )
        if c.converter.enabled:
            kw = design.get("converter_capacity_kw")
            if kw is None:
                kw = max(c.converter.capacity_kw_options) if c.converter.capacity_kw_options else 0
            lines.append(f"System Converter ({kw:,.0f} kW)")
        if c.grid.enabled:
            lines.append("Grid")
        return lines
    except Exception:
        return []


# ============================================================
# PAGE TITLE + PROJECT SELECTOR
# ============================================================
st.title("Simulation Results")

projects = _list_projects()
if not projects:
    st.warning("No projects found.")
    st.stop()

c_sel, c_btn, c_info = st.columns([2, 1, 3])
with c_sel:
    selected_project = st.selectbox(
        "Project", options=projects, index=_get_default_idx(projects), label_visibility="collapsed"
    )
    set_active_project_folder_name(selected_project)
with c_btn:
    if st.button(
        "Refresh Results",
        use_container_width=True,
        help="Re-runs the simulation for the last candidate sent here, using the current saved component settings.",
    ):
        _refresh_results_for_project(selected_project)

# ============================================================
# DATA LOADING
# ============================================================
hourly_df, summary_dict = _load_outputs(selected_project)
econ_payload            = _load_economics(selected_project)

if hourly_df is None or summary_dict is None:
    st.warning(
        "No simulation outputs found.  \n"
        "Go to **Optimization** → select a candidate → **Send Selected Candidate to Results**."
    )
    st.stop()

hourly_df = _prepare_hourly(hourly_df)

try:
    components_cfg = load_components(Path("projects") / selected_project)
except Exception:
    components_cfg = None

cur = econ_payload.get("currency_symbol", "₹") if econ_payload else "₹"

# HOMER-style top header: System Architecture (left) + 3 KPIs (right)
_hdr_arch, _hdr_kpi = st.columns([2.5, 1])
with _hdr_arch:
    arch_lines = _arch_summary_lines(
        selected_project, design=(econ_payload or {}).get("design")
    )
    if arch_lines:
        st.markdown(
            "<div style='font-size:0.92rem;line-height:1.75;padding:4px 0;'>"
            "<span style='font-weight:700;'>System Architecture:</span><br>"
            + "<br>".join(f"&nbsp;&nbsp;{_html.escape(ln)}" for ln in arch_lines)
            + "</div>",
            unsafe_allow_html=True,
        )
with _hdr_kpi:
    if econ_payload:
        _eco_h = econ_payload.get("economics", {})
        _npc_h  = float(_eco_h.get("net_present_cost",         0))
        _lcoe_h = float(_eco_h.get("levelized_cost_of_energy", 0))
        # HOMER's "Operating Cost" = total annualized cost minus annualized
        # capital cost (i.e. annualized replacement + O&M + grid, net of
        # annualized salvage) — NOT just raw annual O&M + grid net cost,
        # which omitted annualized replacement/salvage and understated this
        # by ~8.5% vs HOMER Pro on test10.
        _op_h   = float(_eco_h.get("annualized_total_cost", 0)) - float(_eco_h.get("annualized_capital_cost", 0))
        st.markdown(
            "<div style='background:#f0f4ff;border:1px solid #c5d4f5;border-radius:6px;"
            "padding:10px 16px;font-size:0.92rem;line-height:2.0;'>"
            f"<b>Total NPC:</b>&nbsp;&nbsp;{_html.escape(_money(_npc_h,  cur, 0))}<br>"
            f"<b>Levelized COE:</b>&nbsp;&nbsp;{_html.escape(_money(_lcoe_h, cur, 2))}/kWh<br>"
            f"<b>Operating Cost:</b>&nbsp;&nbsp;{_html.escape(_money(_op_h,  cur, 0))}/yr"
            "</div>",
            unsafe_allow_html=True,
        )

st.divider()

with st.expander("Output file paths", expanded=False):
    st.code(str(_hourly_path(selected_project)))
    st.code(str(_summary_path(selected_project)))

# ============================================================
# 9 HOMER-STYLE TABS
# ============================================================
(tab_cost, tab_cash, tab_elec, tab_renew,
 tab_bat, tab_pv, tab_wind, tab_grid, tab_conv) = st.tabs([
    "Cost Summary", "Cash Flow", "Electrical", "Renewable Penetration",
    "Battery", "PV", "Wind", "Grid", "Converter",
])


# ── TAB 1: COST SUMMARY ──────────────────────────────────────────────────────
with tab_cost:
    if not econ_payload:
        st.info("No economics data yet. Go to Optimization → Send to Results.")
    else:
        eco = econ_payload.get("economics", {})
        npc = float(eco.get("net_present_cost", 0))

        controls, chart_area = st.columns([0.9, 5.4], vertical_alignment="top")
        with controls:
            cost_type = st.radio(
                "Cost Type",
                ["Net Present", "Annualized"],
                key="results_cost_type",
            )
            categorize = st.radio(
                "Categorize",
                ["By Component", "By Cost Type"],
                key="results_cost_category",
            )

        scale = _crf_from_economics(econ_payload) if cost_type == "Annualized" else 1.0
        cost_rows = _cost_components_from_economics(eco, scale=scale)
        system_row = _cost_system_row(cost_rows)
        value_label = "Annualized Cost" if cost_type == "Annualized" else "Net Present Cost"
        y_title = f"{value_label} ({cur}/yr)" if cost_type == "Annualized" else f"{value_label} ({cur})"

        if categorize == "By Component":
            x_values = [str(row["Component"]) for row in cost_rows]
            y_values = [float(row["Total"]) for row in cost_rows]
            chart_title = f"{value_label} by Component"
        else:
            x_values = ["Capital", "Operating", "Replacement", "Salvage", "Fuel"]
            y_values = [
                float(system_row["Capital"]),
                float(system_row["O&M"]),
                float(system_row["Replacement"]),
                float(system_row["Salvage"]),
                float(system_row["Fuel"]),
            ]
            chart_title = f"{value_label} by Cost Type"

        with chart_area:
            fig = go.Figure(go.Bar(
                x=x_values,
                y=y_values,
                marker_color="#5aa7d6",
                hovertemplate="%{x}<br>" + y_title + ": %{y:,.2f}<extra></extra>",
            ))
            fig.update_layout(
                title=dict(text=chart_title, font=dict(size=17)),
                xaxis_title="",
                yaxis_title=y_title,
                height=390,
                margin=dict(l=70, r=15, t=45, b=55),
            )
            fig.update_yaxes(zeroline=True, zerolinewidth=1, zerolinecolor="#666666")
            st.plotly_chart(_style_figure(fig), use_container_width=True)

        st.dataframe(
            _cost_table_dataframe(cost_rows, cur),
            use_container_width=True,
            height=260,
            hide_index=True,
        )

# ── TAB 2: CASH FLOW ─────────────────────────────────────────────────────────
with tab_cash:
    if not econ_payload or components_cfg is None:
        st.info("Cash flow requires both economics data and component configuration.")
    else:
        eco  = econ_payload.get("economics", {})
        npc  = float(eco.get("net_present_cost",      0))
        ann  = float(eco.get("annualized_total_cost", 0))
        life = int(econ_payload.get("project_life_years", 25))

        c1, c2, c3, _ = st.columns([1, 1, 1, 2])
        c1.metric("Total NPC",       f"{cur} {npc:,.0f}")
        c2.metric("Annualized Cost", f"{cur} {ann:,.0f}/yr")
        c3.metric("Project Life",    f"{life} years")

        st.plotly_chart(
            _cash_flow_chart(econ_payload, components_cfg, summary_dict, cur, height=450),
            use_container_width=True,
        )


# ── TAB 3: ELECTRICAL ────────────────────────────────────────────────────────
with tab_elec:
    pv_kwh   = _safe(summary_dict, "total_pv_generation_kwh")
    wind_kwh = _safe(summary_dict, "total_wind_generation_kwh")
    bat_dis  = _safe(summary_dict, "total_battery_discharge_kwh")   # AC out
    grid_imp = _safe(summary_dict, "total_grid_import_kwh")
    grid_exp = _safe(summary_dict, "total_grid_export_kwh")
    load_kwh = _safe(summary_dict, "total_load_kwh")
    served   = _safe(summary_dict, "total_served_load_kwh")
    unmet    = _safe(summary_dict, "total_unmet_load_kwh")
    capacity_shortage = _safe(
        summary_dict, "total_capacity_shortage_kwh", unmet
    )
    capacity_shortage_pct = _safe(
        summary_dict,
        "annual_capacity_shortage_pct",
        unmet / max(load_kwh, EPSILON) * 100,
    )
    excess   = _safe(summary_dict, "total_excess_energy_kwh")
    bat_chg  = _safe(summary_dict, "total_battery_charge_kwh")
    bat_dis_dc = _safe(summary_dict, "total_battery_discharge_dc_kwh")
    inv_loss   = _safe(summary_dict, "total_inverter_loss_kwh")
    rect_loss  = _safe(summary_dict, "total_rectifier_loss_kwh")
    net_rf   = _safe(summary_dict, "renewable_fraction")
    gross_rf = _safe(summary_dict, "gross_renewable_fraction")

    # HOMER excludes battery from both Production and Consumption tables.
    # Production = primary sources only (PV, Wind, Grid).
    # Consumption = primary loads only (Load served, Grid Sales).
    # Battery cycling and excess are excluded — they appear in the Quantity/Losses sections.
    prod_total = max(pv_kwh + wind_kwh + grid_imp, EPSILON)
    cons_total = max(served + grid_exp, EPSILON)

    # Battery DC net absorption = energy put in minus energy taken out (DC terminals).
    # Includes internal round-trip losses + storage depletion (net SOC change over the year).
    bat_dc_net = max(0.0, bat_chg - bat_dis_dc)
    # These three terms close the primary energy balance (self-discharge is tracked separately).
    balance_losses = inv_loss + rect_loss + bat_dc_net

    # ── 4-column layout: Production | Consumption | Quantity | Losses ────────
    c1, c2, c3, c4 = st.columns([1.15, 1.0, 1.1, 1.0])

    with c1:
        prod_rows: list[tuple[str, float, float]] = []
        if pv_kwh   > EPSILON: prod_rows.append(("PV Array",       pv_kwh,  pv_kwh  / prod_total * 100))
        if wind_kwh > EPSILON: prod_rows.append(("Wind Turbines",  wind_kwh,wind_kwh / prod_total * 100))
        if grid_imp > EPSILON: prod_rows.append(("Grid Purchases", grid_imp,grid_imp / prod_total * 100))
        prod_rows.append(("Total", prod_total, 100.0))
        _energy_table(prod_rows, "Production")

    with c2:
        cons_rows: list[tuple[str, float, float]] = []
        if served   > EPSILON: cons_rows.append(("AC Primary Load", served,  served   / cons_total * 100))
        if grid_exp > EPSILON: cons_rows.append(("Grid Sales",      grid_exp,grid_exp / cons_total * 100))
        cons_rows.append(("Total", cons_total, 100.0))
        _energy_table(cons_rows, "Consumption")

    with c3:
        _energy_table([
            ("Excess Electricity",  excess,            excess            / prod_total * 100),
            ("Unmet Electric Load", unmet,             unmet             / max(load_kwh, EPSILON) * 100),
            ("Capacity Shortage",   capacity_shortage, capacity_shortage_pct),
        ], "Quantity", bold_last=False)
        _metric_table([
            ("Renewable Fraction", _fmt(net_rf   * 100, 2), "%"),
            ("Gross RF",           _fmt(gross_rf * 100, 2), "%"),
        ])

    with c4:
        _metric_table([
            ("Inverter Losses",     _fmt(inv_loss),       "kWh/yr"),
            ("Rectifier Losses",    _fmt(rect_loss),      "kWh/yr"),
            ("Battery DC Net Loss", _fmt(bat_dc_net),     "kWh/yr"),
            ("Total Losses",        _fmt(balance_losses), "kWh/yr"),
        ], col1_header="Losses")

    # Monthly production chart — primary sources only, matching the Production table above
    avail_sources = [
        (col, name, clr) for col, name, clr in [
            ("pv_kw",          "PV",          "#f6a623"),
            ("wind_kw",        "Wind",        "#26a269"),
            ("grid_import_kw", "Grid Import", "#7a7a7a"),
        ] if col in hourly_df.columns
    ]
    if avail_sources:
        cols, names, colors = zip(*avail_sources)
        st.plotly_chart(
            _monthly_bar(hourly_df, list(cols), list(names), list(colors),
                         "Monthly Electric Production", height=350),
            use_container_width=True,
        )


# ── TAB 4: RENEWABLE PENETRATION ─────────────────────────────────────────────
with tab_renew:
    pv_kwh   = _safe(summary_dict, "total_pv_generation_kwh")
    wind_kwh = _safe(summary_dict, "total_wind_generation_kwh")
    grid_imp = _safe(summary_dict, "total_grid_import_kwh")
    served   = _safe(summary_dict, "total_served_load_kwh")
    load_kwh = _safe(summary_dict, "total_load_kwh")
    unmet    = _safe(summary_dict, "total_unmet_load_kwh")
    excess   = _safe(summary_dict, "total_excess_energy_kwh")
    net_rf   = _safe(summary_dict, "renewable_fraction")
    gross_rf = _safe(summary_dict, "gross_renewable_fraction")
    direct_re= _safe(summary_dict, "direct_renewable_to_load_kwh")
    re_batt  = _safe(summary_dict, "renewable_from_battery_to_load_kwh")

    renew_gen = pv_kwh + wind_kwh
    total_gen = renew_gen + grid_imp
    cap_short = _safe(
        summary_dict,
        "annual_capacity_shortage_pct",
        unmet / load_kwh * 100 if load_kwh > EPSILON else 0.0,
    )
    reserve_shortfall = _safe(summary_dict, "total_reserve_shortfall_kwh")

    left, right = st.columns([1, 1.5])
    with left:
        _metric_table([
            ("Net Renewable Fraction",   _fmt(net_rf * 100, 2),   "%"),
            ("Gross Renewable Fraction", _fmt(gross_rf * 100, 2), "%"),
            ("Renewable Generation",     _fmt(renew_gen),         "kWh/yr"),
            ("  PV",                     _fmt(pv_kwh),            "kWh/yr"),
            ("  Wind",                   _fmt(wind_kwh),          "kWh/yr"),
            ("Grid Import",              _fmt(grid_imp),          "kWh/yr"),
            ("Total Generation",         _fmt(total_gen),         "kWh/yr"),
            ("Direct RE to Load",        _fmt(direct_re),         "kWh/yr"),
            ("RE via Battery to Load",   _fmt(re_batt),           "kWh/yr"),
            ("Excess Energy",            _fmt(excess),            "kWh/yr"),
            ("Unmet Load",               _fmt(unmet),             "kWh/yr"),
            ("Reserve Shortfall",         _fmt(reserve_shortfall), "kWh/yr"),
            ("Capacity Shortage",        _fmt(cap_short, 4),      "%"),
        ], "Renewable Penetration Metrics")

    with right:
        # Excess energy heatmap
        if "excess_energy_kw" in hourly_df.columns:
            st.plotly_chart(
                _heatmap(hourly_df["excess_energy_kw"].values,
                         "Excess / Unserved Energy (kW)", "kW", "YlOrRd", height=420,
                         timestamps=hourly_df["timestamp"]),
                use_container_width=True,
            )
        elif "renewable_kw" in hourly_df.columns:
            st.plotly_chart(
                _heatmap(hourly_df["renewable_kw"].values,
                         "Renewable Power (kW)", "kW", "YlGn", height=420,
                         timestamps=hourly_df["timestamp"]),
                use_container_width=True,
            )


# ── TAB 5: BATTERY ───────────────────────────────────────────────────────────
with tab_bat:
    bat_chg    = _safe(summary_dict, "total_battery_charge_kwh")
    bat_dis    = _safe(summary_dict, "total_battery_discharge_kwh")
    bat_dis_dc = _safe(summary_dict, "total_battery_discharge_dc_kwh")
    throughput = _safe(summary_dict, "total_battery_throughput_kwh")
    final_soh  = _safe(summary_dict, "final_soh_pct", 100.0)
    min_cap    = _safe(summary_dict, "min_effective_capacity_kwh")
    min_soc    = _safe(summary_dict, "min_battery_soc_pct")
    max_soc    = _safe(summary_dict, "max_battery_soc_pct")
    final_soc  = _safe(summary_dict, "final_battery_soc_pct")

    bat_qty      = int(econ_payload.get("design",{}).get("battery_quantity",0)) if econ_payload else 0
    nom_kwh_str  = float(getattr(components_cfg.battery, "nominal_capacity_kwh_per_string", 1000)) if components_cfg else 1000.0
    per_str_tput = float(getattr(components_cfg.battery, "throughput_kwh", 3e6))            if components_cfg else 3e6
    bat_cal_life = float(getattr(components_cfg.battery, "lifetime_years", 15))              if components_cfg else 15.0
    min_soc_cfg  = float(getattr(components_cfg.battery, "minimum_state_of_charge_pct", 20))if components_cfg else 20.0
    rte          = float(getattr(components_cfg.battery, "roundtrip_efficiency_pct", 90))    if components_cfg else 90.0

    if per_str_tput > EPSILON and throughput > EPSILON and bat_qty > 0:
        bat_eff_life = min(bat_cal_life, (per_str_tput * bat_qty) / throughput)
    else:
        bat_eff_life = bat_cal_life

    nominal_cap = bat_qty * nom_kwh_str
    usable_cap  = nominal_cap * (1 - min_soc_cfg / 100.0)
    dc_losses   = max(0.0, bat_chg - bat_dis_dc)   # round-trip DC losses (internal battery only)

    # ── Additional HOMER-style metrics ───────────────────────────────────────
    load_kwh      = _safe(summary_dict, "total_load_kwh")
    avg_load_kw   = load_kwh / 8760.0

    initial_soc   = float(getattr(components_cfg.battery, "initial_state_of_charge_pct", 50)) if components_cfg else 50.0
    string_size   = int(getattr(components_cfg.battery,   "string_size",                   1)) if components_cfg else 1
    bus_voltage_v = float(getattr(components_cfg.battery, "nominal_voltage_v",           600)) if components_cfg else 600.0
    repl_per_str  = float(getattr(components_cfg.battery, "replacement_cost_per_string",   0)) if components_cfg else 0.0
    # Inverter efficiency factor used in HOMER's wear-cost formula (cost per kWh delivered to AC bus)
    inv_eff       = float(getattr(components_cfg.converter, "inverter_efficiency_pct", 95)) / 100.0 if components_cfg else 0.95

    lifetime_throughput = bat_qty * per_str_tput                                  # kWh total for all strings
    # Storage Depletion = net energy the battery released from its pre-charged state over the year
    storage_depletion   = max(0.0, (initial_soc - final_soc) / 100.0) * nominal_cap
    # Autonomy = how long the usable bank sustains average load without any generation
    autonomy            = usable_cap / avg_load_kw if avg_load_kw > EPSILON else 0.0
    total_repl_cost     = bat_qty * repl_per_str
    # HOMER wear cost = replacement cost ÷ (lifetime throughput × inverter efficiency)
    wear_cost           = total_repl_cost / (lifetime_throughput * inv_eff) if lifetime_throughput > EPSILON else 0.0

    t1, t2, t3 = st.columns(3)
    with t1:
        _metric_table([
            ("Batteries",           str(bat_qty),              "qty."),
            ("String Size",         str(string_size),          "batteries"),
            ("Strings in Parallel", str(bat_qty),              "strings"),
            ("Bus Voltage",         _fmt(bus_voltage_v),       "V"),
            ("Nominal Cap.",        _fmt(nominal_cap),         "kWh"),
            ("Usable Cap.",         _fmt(usable_cap),          "kWh"),
            ("Min SOC",             _fmt(min_soc_cfg),         "%"),
            ("Round-trip Eff.",     _fmt(rte),                 "%"),
            ("Calendar Life",       _fmt(bat_cal_life, 1),     "yr"),
            ("Effective Life",      _fmt(bat_eff_life, 2),     "yr"),
        ], "Battery System")
    with t2:
        _metric_table([
            ("Energy In (DC)",      _fmt(bat_chg),              "kWh/yr"),
            ("Energy Out (DC)",     _fmt(bat_dis_dc),           "kWh/yr"),
            ("Energy Out (AC)",     _fmt(bat_dis),    "kWh/yr"),
            ("DC Round-trip Loss",  _fmt(dc_losses),  "kWh/yr"),
            ("Storage Depletion",   _fmt(storage_depletion),    "kWh/yr"),
            ("Annual Throughput",   _fmt(throughput),           "kWh/yr"),
            ("Lifetime Throughput", _fmt(lifetime_throughput),  "kWh"),
        ], "Annual Usage")
    with t3:
        _metric_table([
            ("Autonomy",       _fmt(autonomy, 2),   "hr"),
            ("Wear Cost",      _fmt(wear_cost, 2),  f"{cur}/kWh"),
            ("Final SoH",      _fmt(final_soh, 2),  "%"),
            ("Min Capacity",   _fmt(min_cap, 1),    "kWh"),
            ("Min SOC (sim.)", _fmt(min_soc, 1),    "%"),
            ("Max SOC (sim.)", _fmt(max_soc, 1),    "%"),
            ("Final SOC",      _fmt(final_soc, 1),  "%"),
        ], "Battery Health")

    # SOC heatmap left, DoD histogram + monthly box right
    left, right = st.columns([1.4, 1])
    with left:
        if "battery_soc_pct" in hourly_df.columns:
            st.plotly_chart(
                _heatmap(hourly_df["battery_soc_pct"].values,
                         "Battery State of Charge (%)", "%", "RdYlGn", height=390,
                         timestamps=hourly_df["timestamp"]),
                use_container_width=True,
            )
    with right:
        if "battery_soc_pct" in hourly_df.columns:
            st.plotly_chart(_monthly_soc_box(hourly_df, height=390), use_container_width=True)


# ── TAB 6: PV ────────────────────────────────────────────────────────────────
with tab_pv:
    pv_kwh   = _safe(summary_dict, "total_pv_generation_kwh")
    pv_kw_d  = float(econ_payload.get("design",{}).get("pv_capacity_kw",0)) if econ_payload else 0.0
    pv_cf    = pv_kwh / (pv_kw_d * 8760) * 100 if pv_kw_d > EPSILON else 0.0
    pv_mean  = pv_kwh / 8760
    pv_daily = pv_kwh / 365.0

    pv_life  = float(getattr(components_cfg.pv, "lifetime_years",   25)) if components_cfg else 25.0
    pv_cap_c = float(getattr(components_cfg.pv, "capital_cost_per_kw",     0)) if components_cfg else 0.0
    pv_rep_c = float(getattr(components_cfg.pv, "replacement_cost_per_kw", 0)) if components_cfg else 0.0
    pv_om_c  = float(getattr(components_cfg.pv, "om_cost_per_kw_per_year",  0)) if components_cfg else 0.0

    load_kwh_pv = _safe(summary_dict, "total_load_kwh")
    pv_penetration = pv_kwh / load_kwh_pv * 100 if load_kwh_pv > EPSILON else 0.0

    pv_max_kw = float(hourly_df["pv_kw"].max()) if "pv_kw" in hourly_df.columns else 0.0
    pv_hrs_op = int((hourly_df["pv_kw"] > 0).sum()) if "pv_kw" in hourly_df.columns else 0

    # Levelized cost using capital recovery factor (matches HOMER's NPC-based method)
    proj_life = float(econ_payload.get("project_life_years", 20)) if econ_payload else 20.0
    r_real    = float(econ_payload.get("real_discount_rate_pct", 8.0)) / 100.0 if econ_payload else 0.08
    crf       = (r_real * (1 + r_real) ** proj_life / ((1 + r_real) ** proj_life - 1)) if r_real > EPSILON else 1.0 / proj_life
    pv_n_repl     = max(0, math.ceil(proj_life / pv_life) - 1) if pv_life > EPSILON else 0
    pv_repl_npc   = (pv_kw_d * pv_rep_c
                     * sum(1.0 / (1 + r_real) ** ((i + 1) * pv_life) for i in range(pv_n_repl)))
    pv_ann_cost   = (pv_kw_d * pv_cap_c + pv_repl_npc) * crf + pv_kw_d * pv_om_c
    pv_lcoe       = pv_ann_cost / pv_kwh if pv_kwh > EPSILON else 0.0

    t1, t2 = st.columns(2)
    with t1:
        _metric_table([
            ("Rated Capacity",    _fmt(pv_kw_d),      "kW"),
            ("Mean Output",       _fmt(pv_mean, 1),   "kW"),
            ("Mean Output",       _fmt(pv_daily, 1),  "kWh/d"),
            ("Capacity Factor",   _fmt(pv_cf, 1),     "%"),
            ("Total Production",  _fmt(pv_kwh),       "kWh/yr"),
        ])
    with t2:
        _metric_table([
            ("Minimum Output",    _fmt(0),             "kW"),
            ("Maximum Output",    _fmt(pv_max_kw, 0),  "kW"),
            ("PV Penetration",    _fmt(pv_penetration, 1), "%"),
            ("Hours of Operation",_fmt(pv_hrs_op),     "hrs/yr"),
            ("Levelized Cost",    _fmt(pv_lcoe, 2),    f"{cur}/kWh"),
        ])

    if "pv_kw" in hourly_df.columns:
        st.plotly_chart(
            _heatmap(hourly_df["pv_kw"].values, "PV Power Output", "kW", "YlOrRd",
                     height=390, timestamps=hourly_df["timestamp"]),
            use_container_width=True,
        )


# ── TAB 7: WIND ──────────────────────────────────────────────────────────────
with tab_wind:
    wind_kwh  = _safe(summary_dict, "total_wind_generation_kwh")
    wnd_qty   = int(econ_payload.get("design",{}).get("wind_quantity",0)) if econ_payload else 0
    wnd_rated = float(getattr(components_cfg.wind, "rated_capacity_kw",           1500)) if components_cfg else 1500.0
    wnd_total = wnd_qty * wnd_rated
    wnd_cf    = wind_kwh / (wnd_total * 8760) * 100 if wnd_total > EPSILON else 0.0
    wnd_mean  = wind_kwh / 8760
    wnd_life  = float(getattr(components_cfg.wind, "lifetime_years", 20))         if components_cfg else 20.0
    wnd_cap_c = float(getattr(components_cfg.wind, "capital_cost_per_turbine",     0)) if components_cfg else 0.0
    wnd_rep_c = float(getattr(components_cfg.wind, "replacement_cost_per_turbine", 0)) if components_cfg else 0.0
    wnd_om_c  = float(getattr(components_cfg.wind, "om_cost_per_turbine_per_year",  0)) if components_cfg else 0.0

    load_kwh_wnd   = _safe(summary_dict, "total_load_kwh")
    wnd_penetration = wind_kwh / load_kwh_wnd * 100 if load_kwh_wnd > EPSILON else 0.0

    wnd_max_kw = float(hourly_df["wind_kw"].max()) if "wind_kw" in hourly_df.columns else 0.0
    wnd_hrs_op = int((hourly_df["wind_kw"] > 0).sum()) if "wind_kw" in hourly_df.columns else 0

    # Levelized cost using capital recovery factor (reuse proj_life / crf from PV tab if in scope)
    # proj_life and crf are defined above in the PV tab; recompute here for safety
    _proj_life = float(econ_payload.get("project_life_years", 20)) if econ_payload else 20.0
    _r_real    = float(econ_payload.get("real_discount_rate_pct", 8.0)) / 100.0 if econ_payload else 0.08
    _crf       = (_r_real * (1 + _r_real) ** _proj_life / ((1 + _r_real) ** _proj_life - 1)) if _r_real > EPSILON else 1.0 / _proj_life
    wnd_n_repl    = max(0, math.ceil(_proj_life / wnd_life) - 1) if wnd_life > EPSILON else 0
    wnd_repl_npc  = (wnd_qty * wnd_rep_c
                     * sum(1.0 / (1 + _r_real) ** ((i + 1) * wnd_life) for i in range(wnd_n_repl)))
    wnd_ann_cost  = (wnd_qty * wnd_cap_c + wnd_repl_npc) * _crf + wnd_qty * wnd_om_c
    wnd_lcoe      = wnd_ann_cost / wind_kwh if wind_kwh > EPSILON else 0.0

    t1, t2 = st.columns(2)
    with t1:
        _metric_table([
            ("Total Rated Capacity", _fmt(wnd_total),      "kW"),
            ("Mean Output",          _fmt(wnd_mean, 1),    "kW"),
            ("Capacity Factor",      _fmt(wnd_cf, 1),      "%"),
            ("Total Production",     _fmt(wind_kwh),       "kWh/yr"),
        ])
    with t2:
        _metric_table([
            ("Minimum Output",    _fmt(0),                  "kW"),
            ("Maximum Output",    _fmt(wnd_max_kw, 0),      "kW"),
            ("Wind Penetration",  _fmt(wnd_penetration, 1), "%"),
            ("Hours of Operation",_fmt(wnd_hrs_op),         "hrs/yr"),
            ("Levelized Cost",    _fmt(wnd_lcoe, 2),        f"{cur}/kWh"),
        ])

    if "wind_kw" in hourly_df.columns:
        st.plotly_chart(
            _heatmap(hourly_df["wind_kw"].values, "Wind Turbine Power Output", "kW", "Blues",
                     height=390, timestamps=hourly_df["timestamp"]),
            use_container_width=True,
        )


# ── TAB 8: GRID ──────────────────────────────────────────────────────────────
with tab_grid:
    grid_imp  = _safe(summary_dict, "total_grid_import_kwh")
    grid_exp  = _safe(summary_dict, "total_grid_export_kwh")
    buy_price = float(getattr(components_cfg.grid, "grid_power_price_per_kwh",    9.0)) if components_cfg else 9.0
    sell_price= float(getattr(components_cfg.grid, "grid_sellback_price_per_kwh", 2.0)) if components_cfg else 2.0
    imp_cost  = grid_imp  * buy_price
    exp_rev   = grid_exp  * sell_price
    net_cost  = imp_cost  - exp_rev

    _metric_table([
        ("Grid Import",     _fmt(grid_imp),         "kWh/yr"),
        ("Grid Export",     _fmt(grid_exp),         "kWh/yr"),
        ("Net Flow",        _fmt(grid_imp-grid_exp),"kWh/yr"),
        ("Buy Tariff",      _fmt(buy_price, 2),     f"{cur}/kWh"),
        ("Sell Tariff",     _fmt(sell_price, 2),    f"{cur}/kWh"),
        ("Purchase Cost",   _fmt(imp_cost),         f"{cur}/yr"),
        ("Export Revenue",  _fmt(exp_rev),          f"{cur}/yr"),
        ("Net Annual Cost", _fmt(net_cost),         f"{cur}/yr"),
    ], "Grid Summary")

    c1, c2 = st.columns(2)
    with c1:
        if "grid_import_kw" in hourly_df.columns:
            st.plotly_chart(
                _heatmap(hourly_df["grid_import_kw"].values,
                         "Grid Import (kW)", "kW", "Reds", height=400,
                         timestamps=hourly_df["timestamp"]),
                use_container_width=True,
            )
    with c2:
        if "grid_export_kw" in hourly_df.columns:
            st.plotly_chart(
                _heatmap(hourly_df["grid_export_kw"].values,
                         "Grid Export (kW)", "kW", "Blues", height=400,
                         timestamps=hourly_df["timestamp"]),
                use_container_width=True,
            )


# ── TAB 9: CONVERTER ─────────────────────────────────────────────────────────
with tab_conv:
    inv_loss   = _safe(summary_dict, "total_inverter_loss_kwh")
    rect_loss  = _safe(summary_dict, "total_rectifier_loss_kwh")
    pv_kwh     = _safe(summary_dict, "total_pv_generation_kwh")
    bat_dc_dis = _safe(summary_dict, "total_battery_discharge_dc_kwh")
    bat_chg    = _safe(summary_dict, "total_battery_charge_kwh")

    # Explicit converter flows avoid counting PV sent directly to the battery
    # or curtailed as inverter throughput.
    inv_input = _safe(
        summary_dict,
        "total_inverter_input_kwh",
        pv_kwh + bat_dc_dis,
    )
    inv_output = _safe(
        summary_dict,
        "total_inverter_output_kwh",
        max(0.0, inv_input - inv_loss),
    )
    inv_eff    = inv_output / inv_input * 100 if inv_input > EPSILON else 0.0

    conv_kw      = float(econ_payload.get("design",{}).get("converter_capacity_kw",0)) if econ_payload else 0.0
    conv_life    = float(getattr(components_cfg.converter, "inverter_lifetime_years",  15)) if components_cfg else 15.0
    inv_eff_cfg  = float(getattr(components_cfg.converter, "inverter_efficiency_pct",  95)) if components_cfg else 95.0
    rect_eff_cfg = float(getattr(components_cfg.converter, "rectifier_efficiency_pct", 95)) if components_cfg else 95.0
    rect_eff_frac = rect_eff_cfg / 100.0

    # Derive rectifier DC output from losses + configured efficiency when the
    # tracked flow fields are absent (simulation_summary.json from an older run).
    # Using bat_chg as fallback is wrong — it includes PV→battery DC direct (no rectifier).
    # Correct derivation: DC_out = loss / (1/eff − 1);  AC_in = DC_out / eff
    _rect_dc_from_loss = (rect_loss / (1.0 / rect_eff_frac - 1.0)
                          if rect_eff_frac < 1.0 - EPSILON else 0.0)
    rect_output = _safe(summary_dict, "total_rectifier_output_kwh", _rect_dc_from_loss)
    _rect_ac_from_loss  = rect_output / rect_eff_frac if rect_eff_frac > EPSILON else 0.0
    rect_input  = _safe(summary_dict, "total_rectifier_input_kwh",  _rect_ac_from_loss)
    rect_eff    = rect_output / rect_input * 100 if rect_input > EPSILON else 0.0

    inv_hrs  = int((hourly_df["inverter_output_kw"]  > 0.1).sum()) if "inverter_output_kw"  in hourly_df.columns else 0
    rect_hrs = int((hourly_df["battery_charge_kw"]   > 0.1).sum()) if "battery_charge_kw"   in hourly_df.columns else 0
    inv_cf   = inv_output  / (conv_kw * 8760) * 100 if conv_kw > EPSILON else 0.0
    rect_cf  = rect_output / (conv_kw * 8760) * 100 if conv_kw > EPSILON else 0.0

    c1, c2 = st.columns(2)
    with c1:
        _metric_table([
            ("Capacity",          _fmt(conv_kw),          "kW"),
            ("Rated Efficiency",  _fmt(inv_eff_cfg, 1),   "%"),
            ("DC Input",          _fmt(inv_input),        "kWh/yr"),
            ("AC Output",         _fmt(inv_output),       "kWh/yr"),
            ("Losses",            _fmt(inv_loss),         "kWh/yr"),
            ("Actual Efficiency", _fmt(inv_eff, 2),       "%"),
            ("Hours",             _fmt(inv_hrs, 0),       "hr/yr"),
            ("Capacity Factor",   _fmt(inv_cf, 2),        "%"),
            ("Lifetime",          _fmt(conv_life, 0),     "yr"),
        ], "Inverter (DC to AC)")

        if "inverter_output_kw" in hourly_df.columns:
            st.plotly_chart(
                _heatmap(hourly_df["inverter_output_kw"].values,
                         "Inverter Output (kW)", "kW", "YlOrRd", height=390,
                         timestamps=hourly_df["timestamp"]),
                use_container_width=True,
            )
    with c2:
        _metric_table([
            ("Capacity",          _fmt(conv_kw),           "kW"),
            ("Rated Efficiency",  _fmt(rect_eff_cfg, 1),   "%"),
            ("AC Input",          _fmt(rect_input),        "kWh/yr"),
            ("DC Output",         _fmt(rect_output),       "kWh/yr"),
            ("Losses",            _fmt(rect_loss),         "kWh/yr"),
            ("Actual Efficiency", _fmt(rect_eff, 2),       "%"),
            ("Hours",             _fmt(rect_hrs, 0),       "hr/yr"),
            ("Capacity Factor",   _fmt(rect_cf, 2),        "%"),
        ], "Rectifier (AC to DC)")

        if "rectifier_output_kw" in hourly_df.columns:
            st.plotly_chart(
                _heatmap(hourly_df["rectifier_output_kw"].values,
                         "Rectifier DC Output (kW)", "kW", "Blues", height=390,
                         timestamps=hourly_df["timestamp"]),
                use_container_width=True,
            )
