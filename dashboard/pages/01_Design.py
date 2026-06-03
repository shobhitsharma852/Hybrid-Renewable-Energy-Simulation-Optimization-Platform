import os

import pandas as pd
import streamlit as st

from dashboard.ui.layout import top_bar
from dashboard.ui.sidebar import render_left_panel
from dashboard.ui.state import active_project_folder, set_active_project
from core.project import (
    Project,
    ProjectEconomics,
    ProjectLoadSettings,
    ProjectLocation,
    ProjectMeta,
    load_project,
    save_project,
)

top_bar("Design")
render_left_panel()

st.markdown("## DESIGN")

# ----------------------------------------------------------------
# Currency options — symbol, ISO code, display label
# ----------------------------------------------------------------
CURRENCY_OPTIONS: list[tuple[str, str, str]] = [
    ("₹", "INR", "₹  INR — Indian Rupee"),
    ("$",  "USD", "$  USD — US Dollar"),
    ("€",  "EUR", "€  EUR — Euro"),
    ("£",  "GBP", "£  GBP — British Pound"),
    ("¥",  "JPY", "¥  JPY — Japanese Yen"),
    ("¥",  "CNY", "¥  CNY — Chinese Yuan"),
]
_CURRENCY_LABELS = [c[2] for c in CURRENCY_OPTIONS]

# ----------------------------------------------------------------
# Project open / create
# ----------------------------------------------------------------
projects_dir = "projects"
existing: list[str] = []
if os.path.exists(projects_dir):
    for n in os.listdir(projects_dir):
        if os.path.exists(os.path.join(projects_dir, n, "project.json")):
            existing.append(n)
existing = sorted(existing)

pick = st.selectbox("Open existing project", ["(New Project)"] + existing)

loaded = None
if pick != "(New Project)":
    folder = set_active_project(pick)
    try:
        loaded = load_project(folder)
        st.success(f"Loaded: {pick}")
    except Exception as e:
        st.error(f"Failed to load: {e}")
else:
    folder = None

# ----------------------------------------------------------------
# Project meta
# ----------------------------------------------------------------
name   = st.text_input("Name",        value=(loaded.meta.name        if loaded else ""))
author = st.text_input("Author",      value=(loaded.meta.author      if loaded else ""))
desc   = st.text_area ("Description", value=(loaded.meta.description if loaded else ""), height=120)

# Currency selector — shown prominently so the user sets it first
_loaded_sym  = loaded.meta.currency_symbol if loaded else "₹"
_loaded_name = loaded.meta.currency_name   if loaded else "INR"
_default_currency_idx = next(
    (i for i, c in enumerate(CURRENCY_OPTIONS) if c[0] == _loaded_sym and c[1] == _loaded_name),
    0,
)
_selected_label = st.selectbox(
    "Currency",
    options=_CURRENCY_LABELS,
    index=_default_currency_idx,
    help=(
        "All cost inputs and outputs will be shown in this currency. "
        "No conversion is performed — enter all cost values in this currency."
    ),
)
_selected_currency = next(c for c in CURRENCY_OPTIONS if c[2] == _selected_label)
currency_symbol = _selected_currency[0]
currency_name   = _selected_currency[1]

st.caption(f"Currency set to: **{currency_name}** ({currency_symbol})  —  enter all component costs in {currency_name}.")

# ----------------------------------------------------------------
# Financial + Location
# ----------------------------------------------------------------
c1, c2 = st.columns([1.1, 1.0], gap="large")

with c1:
    st.subheader("Financial Assumptions")
    discount = st.number_input(
        "Nominal discount rate (%)",
        min_value=0.0, max_value=100.0,
        value=float(loaded.economics.nominal_discount_rate_pct if loaded else 10.0),
        step=0.25,
        help="Before inflation. The real rate is derived using the Fisher equation.",
    )
    inflation = st.number_input(
        "Inflation rate (%)",
        min_value=0.0, max_value=100.0,
        value=float(loaded.economics.inflation_rate_pct if loaded else 6.0),
        step=0.25,
    )
    shortage = st.number_input(
        "Annual capacity shortage (%)",
        min_value=0.0, max_value=100.0,
        value=float(loaded.economics.annual_capacity_shortage if loaded else 0.0),
        step=0.10,
    )
    life = st.number_input(
        "Project lifetime (years)",
        min_value=1, max_value=100,
        value=int(loaded.economics.project_lifetime_years if loaded else 25),
        step=1,
    )

with c2:
    st.subheader("Location")
    lat = st.number_input(
        "Latitude",  min_value=-90.0,  max_value=90.0,
        value=float(loaded.location.lat if loaded else 25.2812),
        step=0.0001, format="%.6f",
    )
    lon = st.number_input(
        "Longitude", min_value=-180.0, max_value=180.0,
        value=float(loaded.location.lon if loaded else 71.0524),
        step=0.0001, format="%.6f",
    )
    tz = st.text_input("Timezone", value=(loaded.location.timezone if loaded else "Asia/Kolkata"))

    df_map = pd.DataFrame([{"lat": float(lat), "lon": float(lon)}])
    st.map(df_map, zoom=5)

# ----------------------------------------------------------------
# Simulation settings
# ----------------------------------------------------------------
st.markdown("---")
st.subheader("Simulation Settings")

default_ts = int(loaded.simulation_time_step_minutes) if loaded else 60
time_step_minutes = st.number_input(
    "Simulation time resolution (minutes)",
    min_value=1, max_value=60,
    value=default_ts,
    step=1,
    help="Any value from 1 to 60. Load and resource data will be resampled to this resolution automatically.",
)

st.markdown("---")

# ----------------------------------------------------------------
# Save
# ----------------------------------------------------------------
if st.button("Save Project", type="primary"):
    if not name.strip():
        st.error("Project Name is required.")
    elif discount < inflation:
        st.error("Nominal discount rate must be >= inflation rate (real rate would be negative).")
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
        st.success(f"Saved: {path}")
