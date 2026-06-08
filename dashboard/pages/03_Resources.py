from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from core.project import load_project
from core.resources import (
    NASA_HOURLY_MIN_YEAR,
    add_clearness_index,
    fetch_nasa_power_resources,
    load_saved_resources,
    monthly_climatology,
    monthly_heatmap_table,
    resources_file_path,
    save_resources,
    summarize_resources,
)
from dashboard.ui.layout import top_bar
from dashboard.ui.sidebar import render_left_panel
from dashboard.ui.state import active_project_folder


st.set_page_config(page_title="Resources Setup", page_icon="☀️", layout="wide")

top_bar("Resources")
render_left_panel()

st.title("Resources Setup")

folder = active_project_folder()

if folder is None:
    st.warning("No project selected. Please create or open a project first.")
    st.stop()

project = load_project(folder)
st.success(f"Project: {project.meta.name}")
time_step_minutes = int(project.simulation_time_step_minutes)
st.info(
    f"Simulation time resolution: **{time_step_minutes} min** — "
    "resource data will be resampled to this resolution when simulation runs."
)

if "current_resources_df" not in st.session_state:
    st.session_state.current_resources_df = None


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _get_active_df() -> pd.DataFrame | None:
    if st.session_state.current_resources_df is not None:
        return st.session_state.current_resources_df
    saved_path = resources_file_path(folder)
    if saved_path.exists():
        return load_saved_resources(folder)
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Section 4 helper — Simulation-ready exports + PV/Wind monthly tables + charts
# ──────────────────────────────────────────────────────────────────────────────

def _show_homer_export_section(df: pd.DataFrame) -> None:
    """
    Three simulation-ready download buttons and monthly summary tables/charts
    for validating resource data before running a simulation.
    """
    st.divider()
    st.markdown("##### `STEP 4`")
    st.subheader("Simulation-Ready Exports")
    st.caption(
        "Download resource files in standard simulation formats. "
        "Verify the monthly tables and charts below before running a simulation."
    )

    df = df.copy()
    df["_ts"]    = pd.to_datetime(df["timestamp"])
    df["_month"] = df["_ts"].dt.month

    month_names = [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ]
    month_abbr = [m[:3] for m in month_names]

    # Days actually present per month (handles leap years and partial datasets)
    hours_per_month = df.groupby("_month").size()
    days_per_month  = {m: hours_per_month.get(m, 24 * 30) / 24.0 for m in range(1, 13)}

    has_kt = "clearness_index" in df.columns and "g0_w_m2" in df.columns

    # ── Build monthly PV table ────────────────────────────────────────────────
    pv_rows = []
    for m in range(1, 13):
        mdf     = df[df["_month"] == m]
        sum_ghi = mdf["ghi"].sum()
        daily   = sum_ghi / 1000.0 / days_per_month[m]
        if has_kt:
            sum_g0 = mdf["g0_w_m2"].sum()
            kt = round(sum_ghi / sum_g0, 3) if sum_g0 > 0 else 0.0
        else:
            kt = None
        pv_rows.append({
            "Month":                          month_names[m - 1],
            "Clearness Index":                kt if kt is not None else "—",
            "Daily Radiation (kWh/m²/day)":   round(daily, 3),
        })
    pv_table  = pd.DataFrame(pv_rows)
    ann_daily = pv_table["Daily Radiation (kWh/m²/day)"].mean()

    # ── Build monthly Wind table ──────────────────────────────────────────────
    wind_rows = []
    for m in range(1, 13):
        mdf = df[df["_month"] == m]
        wind_rows.append({
            "Month":        month_names[m - 1],
            "Average (m/s)": round(mdf["ws50m"].mean(), 3),
        })
    wind_table = pd.DataFrame(wind_rows)
    ann_ws     = wind_table["Average (m/s)"].mean()

    # ── Three download buttons ────────────────────────────────────────────────
    c1, c2, c3 = st.columns(3)

    with c1:
        raw_out = df.drop(columns=["_ts", "_month"], errors="ignore")
        st.download_button(
            "Download Raw Resources CSV",
            data=raw_out.to_csv(index=False).encode("utf-8"),
            file_name="resources_raw.csv",
            mime="text/csv",
            use_container_width=True,
        )
        st.caption("Original hourly data — GHI in Wh/m², wind in m/s, temp in °C")

    with c2:
        pv_csv = pd.DataFrame({
            "timestamp":      df["_ts"].dt.strftime("%Y-%m-%d %H:%M"),
            "ghi_kwh_per_m2": (df["ghi"] / 1000.0).round(6),
        })
        st.download_button(
            "Download Solar CSV  (kWh/m²)",
            data=pv_csv.to_csv(index=False).encode("utf-8"),
            file_name="solar_resource.csv",
            mime="text/csv",
            use_container_width=True,
        )
        st.caption(
            "GHI / 1000 → kWh/m²  |  timestamp: yyyy-mm-dd hh:mm  |  "
            "Import in HOMER Pro: Resources → Solar GHI"
        )

    with c3:
        wind_csv = pd.DataFrame({
            "timestamp":      df["_ts"].dt.strftime("%Y-%m-%d %H:%M"),
            "wind_speed_mps": df["ws50m"].round(4),
        })
        st.download_button(
            "Download Wind CSV  (m/s)",
            data=wind_csv.to_csv(index=False).encode("utf-8"),
            file_name="wind_resource.csv",
            mime="text/csv",
            use_container_width=True,
        )
        st.caption(
            "Wind speed in m/s  |  timestamp: yyyy-mm-dd hh:mm  |  "
            "Import in HOMER Pro: Resources → Wind  (anemometer height = 50 m)"
        )

    # ── PV monthly table + chart ──────────────────────────────────────────────
    st.divider()
    st.markdown("#### Monthly Solar Profile")

    p_left, p_right = st.columns([1, 2])

    with p_left:
        st.dataframe(
            pv_table,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Clearness Index":                st.column_config.NumberColumn(format="%.3f"),
                "Daily Radiation (kWh/m²/day)":   st.column_config.NumberColumn(format="%.3f"),
            },
        )
        st.caption(f"Annual Average: **{ann_daily:.3f} kWh/m²/day**")

    with p_right:
        pv_fig = go.Figure()
        pv_fig.add_trace(go.Bar(
            x=month_abbr,
            y=pv_table["Daily Radiation (kWh/m²/day)"].tolist(),
            name="Daily Radiation (kWh/m²/day)",
            marker_color="#1a5fb4",
            yaxis="y1",
        ))
        if has_kt:
            pv_fig.add_trace(go.Scatter(
                x=month_abbr,
                y=pv_table["Clearness Index"].tolist(),
                name="Clearness Index",
                mode="lines+markers",
                line=dict(color="orange", width=2),
                marker=dict(size=7, color="orange"),
                yaxis="y2",
            ))
        pv_fig.update_layout(
            title=f"Monthly Solar Profile  —  Annual Avg: {ann_daily:.3f} kWh/m²/day",
            xaxis_title="Month",
            yaxis=dict(title="Daily Radiation (kWh/m²/day)", side="left", showgrid=True),
            yaxis2=dict(
                title="Clearness Index",
                side="right",
                overlaying="y",
                range=[0, 1],
                showgrid=False,
            ),
            legend=dict(x=0.01, y=0.99, bgcolor="rgba(255,255,255,0.7)"),
            height=380,
            bargap=0.25,
        )
        st.plotly_chart(pv_fig, use_container_width=True)

    # ── Wind monthly table + chart ────────────────────────────────────────────
    st.divider()
    st.markdown("#### Monthly Wind Profile")

    w_left, w_right = st.columns([1, 2])

    with w_left:
        st.dataframe(
            wind_table,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Average (m/s)": st.column_config.NumberColumn(format="%.3f"),
            },
        )
        st.caption(f"Annual Average: **{ann_ws:.3f} m/s**")

    with w_right:
        wind_fig = go.Figure()
        wind_fig.add_trace(go.Bar(
            x=month_abbr,
            y=wind_table["Average (m/s)"].tolist(),
            name="Average Wind Speed (m/s)",
            marker_color="orange",
        ))
        wind_fig.update_layout(
            title=f"Monthly Wind Profile  —  Annual Avg: {ann_ws:.3f} m/s",
            xaxis_title="Month",
            yaxis_title="Average Wind Speed (m/s)",
            height=380,
            bargap=0.25,
        )
        st.plotly_chart(wind_fig, use_container_width=True)


# ──────────────────────────────────────────────────────────────────────────────
# Section 5 helper — Advanced analysis (collapsible)
# ──────────────────────────────────────────────────────────────────────────────

def _show_advanced_analysis(df: pd.DataFrame) -> None:
    variable_map = {
        "ghi":         "GHI (Wh/m²)",
        "ws50m":       "Wind Speed (m/s)",
        "temperature": "Temperature (°C)",
    }

    col1, col2 = st.columns(2)
    with col1:
        hm_var = st.selectbox(
            "Heatmap Variable",
            options=list(variable_map.keys()),
            format_func=lambda x: variable_map[x],
            key="adv_hm_var",
        )
    with col2:
        hm_metric = st.selectbox(
            "Aggregation",
            options=["mean", "sum"],
            key="adv_hm_metric",
        )

    heatmap_tbl = monthly_heatmap_table(df, variable=hm_var, metric=hm_metric)
    heatmap_fig = px.imshow(
        heatmap_tbl,
        aspect="auto",
        color_continuous_scale="Viridis",
        labels=dict(x="Month", y="Year", color=variable_map[hm_var]),
        title=f"Monthly Heatmap — {variable_map[hm_var]} ({hm_metric})",
    )
    heatmap_fig.update_layout(height=400)
    st.plotly_chart(heatmap_fig, use_container_width=True)

    st.divider()

    # Monthly climatology — GHI on left axis, wind + temp on right
    clim_df = monthly_climatology(df)
    clim_fig = go.Figure()
    clim_fig.add_trace(go.Scatter(
        x=clim_df["label"], y=clim_df["ghi"],
        mode="lines+markers", name="GHI (Wh/m²)", yaxis="y1",
    ))
    clim_fig.add_trace(go.Scatter(
        x=clim_df["label"], y=clim_df["ws50m"],
        mode="lines+markers", name="Wind (m/s)", yaxis="y2",
    ))
    clim_fig.add_trace(go.Scatter(
        x=clim_df["label"], y=clim_df["temperature"],
        mode="lines+markers", name="Temp (°C)", yaxis="y2",
    ))
    clim_fig.update_layout(
        title="Monthly Climatology (All Years)",
        xaxis_title="Month",
        yaxis=dict(title="GHI (Wh/m²)", side="left"),
        yaxis2=dict(title="Wind (m/s) / Temp (°C)", side="right", overlaying="y"),
        height=400,
    )
    st.plotly_chart(clim_fig, use_container_width=True)

    st.download_button(
        "Download Monthly Climatology CSV",
        data=clim_df.to_csv(index=False).encode("utf-8"),
        file_name="monthly_climatology.csv",
        mime="text/csv",
        use_container_width=True,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Main output — Sections 2 → 6
# ──────────────────────────────────────────────────────────────────────────────

def _show_resources_output(df: pd.DataFrame, ts_minutes: int = 60) -> None:

    # ── 2. OVERVIEW ──────────────────────────────────────────────────────────
    st.divider()
    st.markdown("##### `STEP 2`")
    st.subheader("Overview")

    summary = summarize_resources(df)
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Rows",             f"{summary.rows:,}")
    c2.metric("Mean GHI (Wh/m²)", f"{summary.ghi_mean:.2f}")
    c3.metric("Mean WS50M (m/s)", f"{summary.ws50m_mean:.2f}")
    c4.metric("Mean Temp (°C)",   f"{summary.temperature_mean:.2f}")
    c5.metric("Coverage",         f"{summary.start_timestamp.year}–{summary.end_timestamp.year}")

    st.caption("Raw Preview — first 24 rows (original hourly data)")
    preview_df = df.head(24).rename(columns={
        "ghi":         "ghi_wh_per_m2",
        "ws50m":       "ws50m_mps",
        "temperature": "temperature_c",
    })
    st.dataframe(preview_df, use_container_width=True)

    # ── 3. CLEARNESS INDEX ───────────────────────────────────────────────────
    st.divider()
    st.markdown("##### `STEP 3`")
    st.subheader("Clearness Index")
    st.caption(
        "Computes G0 (extraterrestrial irradiance) and Kt = GHI / G0 for each hour "
        "using the standard equation of time formula. "
        "When saved, the PV model uses Kt-capped GHI for accurate power output calculation."
    )

    if "clearness_index" in df.columns and "g0_w_m2" in df.columns:
        daytime = df[df["g0_w_m2"] > 10]
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Daytime Hours",   f"{len(daytime):,}")
        k2.metric("Mean Kt (daytime)", f"{daytime['clearness_index'].mean():.4f}")
        k3.metric("Hours Kt > 0.82",  f"{(daytime['clearness_index'] > 0.82).sum()}")
        k4.metric("Max Kt",           f"{daytime['clearness_index'].max():.4f}")
        st.success("Clearness index columns are present. Save to persist them.")
    else:
        st.info("Clearness index not yet computed for this resource data.")

    tz_offset = st.number_input(
        "Timezone Offset (hours east of UTC)",
        min_value=-12.0,
        max_value=14.0,
        value=5.5,
        step=0.5,
        help="India / IST = 5.5  |  UTC = 0.0  |  China = 8.0",
        key="ui_resources_tz_offset",
    )

    if st.button("Compute Clearness Index", use_container_width=True):
        try:
            with st.spinner("Computing G0 and Kt for each hour using equation of time formula..."):
                df_with_kt = add_clearness_index(
                    df,
                    lat=project.location.lat,
                    lon=project.location.lon,
                    timezone_offset_hours=float(tz_offset),
                )
            st.session_state.current_resources_df = df_with_kt
            st.success(
                f"Clearness index computed for {len(df_with_kt):,} rows. "
                "Click 'Save Resources to Project' below to persist."
            )
            st.rerun()
        except Exception as e:
            st.error(f"Failed to compute clearness index: {e}")

    # ── 4. EXPORT + PV / Wind monthly tables + charts ─────────────────────────
    _show_homer_export_section(df)

    # ── 5. ADVANCED ANALYSIS (collapsible) ───────────────────────────────────
    st.divider()
    st.markdown("##### `STEP 5`")
    with st.expander("Advanced Analysis  —  Monthly Heatmap & Climatology", expanded=False):
        _show_advanced_analysis(df)

    # ── 6. SAVE ───────────────────────────────────────────────────────────────
    st.divider()
    st.markdown("##### `STEP 6`")
    if st.button("Save Resources to Project", type="primary", use_container_width=True):
        try:
            path = save_resources(df, folder)
            st.success(f"Resources saved successfully: {path}")
            st.rerun()
        except Exception as e:
            st.error(f"Failed to save resources: {e}")


# ──────────────────────────────────────────────────────────────────────────────
# SECTION 1: SOURCE — NASA POWER Download
# ──────────────────────────────────────────────────────────────────────────────

st.divider()
st.markdown("##### `STEP 1`")
st.subheader("Get Resource Data — NASA POWER")

lat = project.location.lat
lon = project.location.lon

c1, c2, c3, c4 = st.columns(4)
c1.metric("Latitude",  f"{lat:.4f}")
c2.metric("Longitude", f"{lon:.4f}")
start_year = c3.number_input("Start Year", min_value=1980, max_value=2100, value=2001, step=1)
end_year   = c4.number_input("End Year",   min_value=1980, max_value=2100, value=2025, step=1)

st.caption(
    f"NASA POWER hourly data is downloaded in chunks from {NASA_HOURLY_MIN_YEAR} onward. "
    f"Earlier years are automatically clamped to {NASA_HOURLY_MIN_YEAR}."
)

if st.button("Download from NASA POWER", type="primary", use_container_width=True):
    try:
        if end_year < start_year:
            st.error("End year must be greater than or equal to start year.")
        else:
            with st.spinner("Downloading NASA POWER hourly data..."):
                df_new = fetch_nasa_power_resources(
                    lat=lat,
                    lon=lon,
                    start_year=int(start_year),
                    end_year=int(end_year),
                )
            st.session_state.current_resources_df = df_new
            st.success("NASA POWER resource data downloaded successfully.")
    except Exception as e:
        st.session_state.current_resources_df = None
        st.error(f"Could not download NASA POWER data: {e}")


# ──────────────────────────────────────────────────────────────────────────────
# SECTIONS 2 – 6
# ──────────────────────────────────────────────────────────────────────────────

active_df = _get_active_df()

if active_df is not None:
    _show_resources_output(active_df, ts_minutes=time_step_minutes)
else:
    st.info(
        "No resource data found for this project yet. "
        "Download from NASA POWER above, or save a resource CSV to "
        f"`projects/{Path(folder).name}/inputs/resources.csv`."
    )
