from __future__ import annotations

import math
import os

import pandas as pd
import streamlit as st

from core.project import (
    Project,
    ProjectEconomics,
    ProjectLoadSettings,
    ProjectLocation,
    ProjectMeta,
    load_project,
    save_project,
)
from dashboard.ui.layout import top_bar
from dashboard.ui.sidebar import render_left_panel
from dashboard.ui.state import active_project_folder, set_active_project

st.set_page_config(page_title="Project Setup", page_icon="🏗️", layout="wide")

top_bar("Project Setup")
render_left_panel()

st.title("Project Setup")
st.caption("Configure your project before moving to Load, Resources, Components, and Optimization.")

# ──────────────────────────────────────────────────────────────────────────────
# Currency options
# ──────────────────────────────────────────────────────────────────────────────
CURRENCY_OPTIONS: list[tuple[str, str, str]] = [
    ("₹", "INR", "INR — Indian Rupee"),
    ("$",  "USD", "USD — US Dollar"),
    ("€",  "EUR", "EUR — Euro"),
    ("£",  "GBP", "GBP — British Pound"),
    ("¥",  "JPY", "JPY — Japanese Yen"),
    ("¥",  "CNY", "CNY — Chinese Yuan"),
]
_CURRENCY_LABELS = [c[2] for c in CURRENCY_OPTIONS]


def _fisher_real_rate(nominal: float, inflation: float) -> float:
    """Real rate = (nominal - inflation) / (1 + inflation/100)."""
    if (1.0 + inflation / 100.0) == 0:
        return 0.0
    return (nominal - inflation) / (1.0 + inflation / 100.0)


def _crf(real_rate_pct: float, years: int) -> float:
    """Capital Recovery Factor."""
    r = real_rate_pct / 100.0
    n = float(years)
    if n <= 0:
        return 0.0
    if abs(r) < 1e-9:
        return 1.0 / n
    return r * (1.0 + r) ** n / ((1.0 + r) ** n - 1.0)


# ──────────────────────────────────────────────────────────────────────────────
# STEP 1 — Open or Create Project
# ──────────────────────────────────────────────────────────────────────────────
st.divider()
st.markdown("##### `STEP 1`")
st.subheader("Open or Create Project")

projects_dir = "projects"
existing: list[str] = []
if os.path.exists(projects_dir):
    for n in os.listdir(projects_dir):
        if os.path.exists(os.path.join(projects_dir, n, "project.json")):
            existing.append(n)
existing = sorted(existing)

pick = st.selectbox("Select existing project or start new", ["(New Project)"] + existing)

loaded = None
if pick != "(New Project)":
    folder = set_active_project(pick)
    try:
        loaded = load_project(folder)
        st.success(f"Project loaded: **{pick}**")
    except Exception as e:
        st.error(f"Failed to load: {e}")
else:
    folder = None

# ──────────────────────────────────────────────────────────────────────────────
# STEP 2 — Project Details
# ──────────────────────────────────────────────────────────────────────────────
st.divider()
st.markdown("##### `STEP 2`")
st.subheader("Project Details")

c_name, c_cur = st.columns(2)

with c_name:
    name   = st.text_input("Project Name",   value=(loaded.meta.name        if loaded else ""))
    author = st.text_input("Author",         value=(loaded.meta.author      if loaded else ""))
    desc   = st.text_area( "Description",    value=(loaded.meta.description if loaded else ""), height=100)

with c_cur:
    _loaded_sym  = loaded.meta.currency_symbol if loaded else "₹"
    _loaded_name = loaded.meta.currency_name   if loaded else "INR"
    _default_idx = next(
        (i for i, c in enumerate(CURRENCY_OPTIONS) if c[0] == _loaded_sym and c[1] == _loaded_name),
        0,
    )
    _sel_label = st.selectbox(
        "Currency",
        options=_CURRENCY_LABELS,
        index=_default_idx,
        help="All cost inputs and outputs will use this currency. No conversion is applied — enter all component costs in this currency.",
    )
    _sel_cur = next(c for c in CURRENCY_OPTIONS if c[2] == _sel_label)
    currency_symbol = _sel_cur[0]
    currency_name   = _sel_cur[1]
    st.caption(f"Currency: **{currency_name}** ({currency_symbol})  —  enter all component costs in {currency_name}.")

# ──────────────────────────────────────────────────────────────────────────────
# STEP 3 — Financial Assumptions
# ──────────────────────────────────────────────────────────────────────────────
st.divider()
st.markdown("##### `STEP 3`")
st.subheader("Financial Assumptions")
st.caption(
    "The real discount rate is derived automatically from nominal rate and inflation "
    "using the Fisher equation: real = (nominal − inflation) / (1 + inflation/100). "
    "This is the rate used internally for all NPC and LCOE calculations."
)

f1, f2 = st.columns(2)

with f1:
    discount = st.number_input(
        "Nominal discount rate (%)",
        min_value=0.0, max_value=100.0,
        value=float(loaded.economics.nominal_discount_rate_pct if loaded else 10.0),
        step=0.25,
        help="Before inflation. HOMER Pro calls this 'Real Discount Rate' when entered directly. Here we apply the Fisher equation.",
    )
    inflation = st.number_input(
        "Inflation rate (%)",
        min_value=0.0, max_value=100.0,
        value=float(loaded.economics.inflation_rate_pct if loaded else 6.0),
        step=0.25,
    )

with f2:
    life = st.number_input(
        "Project lifetime (years)",
        min_value=1, max_value=100,
        value=int(loaded.economics.project_lifetime_years if loaded else 25),
        step=1,
    )
    shortage = st.number_input(
        "Annual capacity shortage allowed (%)",
        min_value=0.0, max_value=100.0,
        value=float(loaded.economics.annual_capacity_shortage if loaded else 0.0),
        step=0.10,
        help="Maximum allowable unmet load as a percentage of annual load. 0 = no unmet load allowed.",
    )

# Computed values display
real_rate  = _fisher_real_rate(discount, inflation)
crf_val    = _crf(real_rate, int(life))
af_val     = 1.0 / crf_val if crf_val > 1e-9 else float(life)

m1, m2, m3, m4 = st.columns(4)
m1.metric("Real Discount Rate", f"{real_rate:.3f}%", help="Fisher equation result — used for all discounting")
m2.metric("CRF", f"{crf_val:.5f}",  help="Capital Recovery Factor at this real rate and project life")
m3.metric("Annuity Factor", f"{af_val:.3f}", help="Present value factor = 1/CRF")
m4.metric("Project Life", f"{int(life)} years")

if discount < inflation:
    st.error("Nominal discount rate must be >= inflation rate (real rate would be negative).")

# ──────────────────────────────────────────────────────────────────────────────
# STEP 4 — Location
# ──────────────────────────────────────────────────────────────────────────────
st.divider()
st.markdown("##### `STEP 4`")
st.subheader("Location")
st.caption("Location is used for solar geometry calculations (G0, clearness index) and NASA POWER resource download.")

loc1, loc2, loc3 = st.columns(3)
with loc1:
    lat = st.number_input(
        "Latitude",
        min_value=-90.0, max_value=90.0,
        value=float(loaded.location.lat if loaded else 25.2812),
        step=0.0001, format="%.6f",
    )
with loc2:
    lon = st.number_input(
        "Longitude",
        min_value=-180.0, max_value=180.0,
        value=float(loaded.location.lon if loaded else 71.0524),
        step=0.0001, format="%.6f",
    )
with loc3:
    tz = st.text_input(
        "Timezone",
        value=(loaded.location.timezone if loaded else "Asia/Kolkata"),
        help="IANA timezone name. Examples: Asia/Kolkata, UTC, America/New_York",
    )

df_map = pd.DataFrame([{"lat": float(lat), "lon": float(lon)}])
st.map(df_map, zoom=5)

# ──────────────────────────────────────────────────────────────────────────────
# STEP 5 — Simulation Settings & Save
# ──────────────────────────────────────────────────────────────────────────────
st.divider()
st.markdown("##### `STEP 5`")
st.subheader("Simulation Settings")

default_ts = int(loaded.simulation_time_step_minutes) if loaded else 60
time_step_minutes = st.number_input(
    "Simulation time resolution (minutes)",
    min_value=1, max_value=60,
    value=default_ts,
    step=1,
    help="Any value from 1 to 60. Load and resource data are resampled to this resolution automatically at simulation time.",
)
st.caption(f"At {time_step_minutes} min resolution: {int(8760 * 60 / time_step_minutes):,} timesteps per year.")

st.divider()
if st.button("Save Project", type="primary", use_container_width=True):
    if not name.strip():
        st.error("Project Name is required.")
    elif discount < inflation:
        st.error("Fix the discount rate before saving.")
    else:
        folder = set_active_project(name)
        proj = Project(
            meta=ProjectMeta(
                name=name.strip(),
                author=author.strip(),
                description=desc.strip(),
                currency_symbol=currency_symbol,
                currency_name=currency_name,
            ),
            location=ProjectLocation(
                lat=float(lat),
                lon=float(lon),
                timezone=tz.strip() or "UTC",
            ),
            economics=ProjectEconomics(
                nominal_discount_rate_pct=float(discount),
                inflation_rate_pct=float(inflation),
                project_lifetime_years=int(life),
                annual_capacity_shortage=float(shortage),
            ),
            simulation_time_step_minutes=int(time_step_minutes),
        )
        path = save_project(proj, folder)
        st.success(f"Project saved: **{path}**  |  Real discount rate used in simulation: **{real_rate:.3f}%**")
