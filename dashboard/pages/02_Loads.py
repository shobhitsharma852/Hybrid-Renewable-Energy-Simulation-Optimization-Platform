import streamlit as st
import pandas as pd

from core.project import load_project
from core.load import (
    read_uploaded_load,
    create_constant_load,
    create_daily_profile_load,
    resample_load_to_timestep,
    save_load,
    summarize_load,
    load_file_path,
)
from dashboard.ui.state import active_project_folder
from dashboard.ui.sidebar import render_left_panel
from dashboard.ui.layout import top_bar

top_bar("Load")
render_left_panel()

st.title("⚡ Electric Load Setup")

folder = active_project_folder()

if folder is None:
    st.warning("No project selected. Please create or open a project first.")
    st.stop()

project = load_project(folder)
st.success(f"Project: {project.meta.name}")
time_step_minutes = int(project.simulation_time_step_minutes)
st.info(f"Simulation time resolution: **{time_step_minutes} min** — load data will be resampled to this resolution when simulation runs.")

st.divider()
st.subheader("Select Load Input Method")

method = st.radio(
    "Load Method",
    [
        "Upload CSV",
        "Constant Load",
        "24 Hour Profile",
    ]
)

# Persist generated load across reruns
if "current_load_df" not in st.session_state:
    st.session_state.current_load_df = None

load_df = None


def _show_load_output(df: pd.DataFrame, ts_minutes: int = 60):
    summary = summarize_load(df)
    time_step_hours = ts_minutes / 60.0
    steps_per_day = round(24 * 60 / ts_minutes)

    st.divider()
    st.subheader("Load Summary (Original Data)")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Rows", f"{summary.rows:,}")
    c2.metric("Peak Load (kW)", f"{summary.peak_kw:.2f}")
    c3.metric("Average Load (kW)", f"{summary.average_kw:.2f}")
    c4.metric("Annual Energy (kWh)", f"{summary.annual_energy_kwh:,.0f}")

    st.subheader("Original Data Preview (first 24 rows)")
    st.dataframe(df.head(24), use_container_width=True)

    # ── Resampled preview ──────────────────────────────────────────────────
    if ts_minutes != 60:
        st.divider()
        st.subheader(f"Resampled Preview — {ts_minutes} min resolution")
        try:
            resampled_df = resample_load_to_timestep(df, ts_minutes)
            rs_summary = summarize_load(resampled_df)
            annual_kwh_corrected = float(resampled_df["load_kw"].sum()) * time_step_hours

            r1, r2, r3, r4 = st.columns(4)
            r1.metric("Resampled Rows", f"{rs_summary.rows:,}")
            r2.metric("Peak Load (kW)", f"{rs_summary.peak_kw:.2f}")
            r3.metric("Average Load (kW)", f"{rs_summary.average_kw:.2f}")
            r4.metric("Annual Energy (kWh)", f"{annual_kwh_corrected:,.0f}")

            st.caption(f"First {steps_per_day} rows = first 24 hours at {ts_minutes}-min resolution")
            st.dataframe(resampled_df.head(steps_per_day), use_container_width=True)

            st.subheader(f"First Day Chart — {ts_minutes} min steps")
            first_day = resampled_df.head(steps_per_day).copy().reset_index(drop=True)
            st.line_chart(first_day.set_index("timestamp")[["load_kw"]], use_container_width=True)
        except Exception as e:
            st.warning(f"Could not resample for preview: {e}")
    else:
        st.subheader("Daily Load Charts (First 24 Hours)")
        first_day = df.head(24).copy()
        first_day["hour"] = range(24)
        chart_df = first_day.set_index("hour")[["load_kw"]]

        col1, col2 = st.columns(2)
        with col1:
            st.caption("Line Chart")
            st.line_chart(chart_df, use_container_width=True)
        with col2:
            st.caption("Bar Chart")
            st.bar_chart(chart_df, use_container_width=True)

    if st.button("Save Load to Project", type="primary"):
        try:
            path = save_load(df, folder)
            st.success(f"Load saved successfully: {path}")
            st.rerun()
        except Exception as e:
            st.error(f"Failed to save load: {e}")


# -----------------------------
# CSV Upload
# -----------------------------
if method == "Upload CSV":
    uploaded_file = st.file_uploader(
        "Upload Load File (CSV or Excel)",
        type=["csv", "xlsx", "xls"]
    )

    if uploaded_file is not None:
        try:
            load_df = read_uploaded_load(uploaded_file, uploaded_file.name)
            st.session_state.current_load_df = load_df
            st.success("Load file read and validated successfully.")
        except Exception as e:
            st.session_state.current_load_df = None
            st.error(f"Load validation failed: {e}")

# -----------------------------
# Constant Load
# -----------------------------
elif method == "Constant Load":
    constant_kw = st.number_input(
        "Enter Constant Load (kW)",
        min_value=0.0,
        value=1000.0,
        step=10.0
    )

    if st.button("Generate Load"):
        try:
            load_df = create_constant_load(constant_kw)
            st.session_state.current_load_df = load_df
            st.success("Constant load generated successfully.")
        except Exception as e:
            st.session_state.current_load_df = None
            st.error(f"Could not generate constant load: {e}")

# -----------------------------
# 24 Hour Profile
# -----------------------------
elif method == "24 Hour Profile":
    st.write("Enter 24 hourly values")

    profile = []
    cols = st.columns(6)

    for i in range(24):
        with cols[i % 6]:
            val = st.number_input(
                f"H{i}",
                min_value=0.0,
                value=50.0,
                step=5.0,
                key=f"h{i}"
            )
            profile.append(val)

    if st.button("Generate Yearly Load"):
        try:
            if len(profile) != 24:
                st.error("24-hour profile must contain exactly 24 values.")
            else:
                load_df = create_daily_profile_load(profile)
                st.session_state.current_load_df = load_df
                st.success("8760 hourly load generated successfully from 24-hour profile.")
        except Exception as e:
            st.session_state.current_load_df = None
            st.error(f"Could not generate yearly load: {e}")

# Use persisted dataframe if present
if st.session_state.current_load_df is not None:
    _show_load_output(st.session_state.current_load_df, ts_minutes=time_step_minutes)

# Show already saved load if no current generated load exists
saved_path = load_file_path(folder)
if st.session_state.current_load_df is None and saved_path.exists():
    st.divider()
    st.info("A load is already saved for this project.")
    try:
        saved_df = pd.read_csv(saved_path)
        saved_df["timestamp"] = pd.to_datetime(saved_df["timestamp"], errors="coerce")
        _show_load_output(saved_df, ts_minutes=time_step_minutes)
    except Exception as e:
        st.error(f"Could not read saved load file: {e}")