import streamlit as st
import pandas as pd

from dashboard.ui.layout import top_bar
from dashboard.ui.sidebar import render_left_panel
from dashboard.ui.state import set_active_project, active_project_folder
from core.project import (
    ProjectMeta, ProjectLocation, ProjectEconomics, Project,
    save_project, load_project
)

top_bar("Design")
render_left_panel()

st.markdown("## DESIGN")

# project open/create
projects_dir = "projects"
existing = []
import os
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

# defaults
name = st.text_input("Name", value=(loaded.meta.name if loaded else ""))
author = st.text_input("Author", value=(loaded.meta.author if loaded else ""))
desc = st.text_area("Description", value=(loaded.meta.description if loaded else ""), height=120)

c1, c2 = st.columns([1.1, 1.0], gap="large")

with c1:
    st.subheader("Financial Assumptions")
    discount = st.number_input("Discount rate (%)", min_value=0.0, max_value=100.0, value=(loaded.economics.discount_rate if loaded else 8.0), step=0.25)
    inflation = st.number_input("Inflation rate (%)", min_value=0.0, max_value=100.0, value=(loaded.economics.inflation_rate if loaded else 2.0), step=0.25)
    shortage = st.number_input("Annual capacity shortage (%)", min_value=0.0, max_value=100.0, value=(loaded.economics.annual_capacity_shortage if loaded else 0.0), step=0.10)
    life = st.number_input("Project lifetime (years)", min_value=1, max_value=100, value=(loaded.economics.project_lifetime_years if loaded else 25), step=1)

with c2:
    st.subheader("Location")
    lat = st.number_input("Latitude", min_value=-90.0, max_value=90.0, value=(loaded.location.lat if loaded else 25.2812), step=0.0001, format="%.6f")
    lon = st.number_input("Longitude", min_value=-180.0, max_value=180.0, value=(loaded.location.lon if loaded else 71.0524), step=0.0001, format="%.6f")
    tz = st.text_input("Timezone", value=(loaded.location.timezone if loaded else "Asia/Kolkata"))

    # HOMER-like location preview
    df_map = pd.DataFrame([{"lat": float(lat), "lon": float(lon)}])
    st.map(df_map, zoom=5)

st.markdown("---")

if st.button("Save Project", type="primary"):
    if not name.strip():
        st.error("Project Name is required.")
    else:
        folder = set_active_project(name)
        proj = Project(
            meta=ProjectMeta(name=name.strip(), author=author.strip(), description=desc.strip()),
            location=ProjectLocation(lat=float(lat), lon=float(lon), timezone=tz.strip() or "UTC"),
            economics=ProjectEconomics(
                discount_rate=float(discount),
                inflation_rate=float(inflation),
                project_lifetime_years=int(life),
                annual_capacity_shortage=float(shortage),
            ),
        )
        path = save_project(proj, folder)
        st.success(f"Saved: {path}")