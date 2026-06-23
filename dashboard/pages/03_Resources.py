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
    project_file_name = "".join(
        char if char.isalnum() or char in {"-", "_"} else "_"
        for char in project.meta.name.strip()
    ) or "project"

    year_min = int(df["_ts"].dt.year.min())
    year_max = int(df["_ts"].dt.year.max())
    years_label = (
        f"{year_min}–{year_max}" if year_min != year_max else str(year_min)
    )

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
    # Solar and Wind buttons output a HOMER-compatible average year (8,760 rows).
    # When multi-year data is loaded, each hourly slot is the mean across all years —
    # so HOMER detects "Time step: 60 min" and its monthly profile matches ours.
    # For a single-year dataset the average year equals the year itself.

    # Build HOMER-compatible average year (8,760 rows).
    # Group by (month, hour-of-day) across all years — Feb 29 is included in the
    # February mean so the monthly averages exactly match the profile tables below.
    # Each calendar day in the output repeats the month's mean diurnal profile;
    # HOMER's monthly display then matches our model to the last decimal place.
    df_avg = df.copy()
    df_avg["_hour"] = df_avg["_ts"].dt.hour

    avg_by_mh = (
        df_avg
        .groupby(["_month", "_hour"], as_index=False)
        .agg(ghi_avg=("ghi", "mean"), ws50m_avg=("ws50m", "mean"), temp_avg=("temperature", "mean"))
    )

    # Expand to 8,760 rows using standard non-leap calendar (Feb = 28 days)
    _ref_days = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    ref_rows: list[dict] = []
    for m, n_days in enumerate(_ref_days, start=1):
        mh = avg_by_mh[avg_by_mh["_month"] == m].set_index("_hour")
        for _ in range(n_days):
            for h in range(24):
                ref_rows.append({
                    "ghi_avg":   float(mh.at[h, "ghi_avg"])   if h in mh.index else 0.0,
                    "ws50m_avg": float(mh.at[h, "ws50m_avg"]) if h in mh.index else 0.0,
                    "temp_avg":  float(mh.at[h, "temp_avg"])  if h in mh.index else 0.0,
                })

    avg_grp = pd.DataFrame(ref_rows)
    ref_ts = pd.date_range("2001-01-01", periods=8760, freq="h")
    avg_year_ok = len(avg_grp) == 8760
    if avg_year_ok:
        avg_grp["ref_ts"] = ref_ts.strftime("%Y-%m-%d %H:%M")

    n_years = year_max - year_min + 1
    avg_label = f"{years_label} avg" if n_years > 1 else str(year_min)

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
        if avg_year_ok:
            pv_csv = pd.DataFrame({
                "timestamp":      avg_grp["ref_ts"],
                "ghi_kwh_per_m2": (avg_grp["ghi_avg"] / 1000.0).round(6),
            })
            solar_caption = (
                f"8,760 rows ({avg_label})  |  GHI in kWh/m²  |  "
                "HOMER Pro: Resources → Solar GHI"
            )
        else:
            # Fallback to raw export if groupby row count is unexpected
            pv_csv = pd.DataFrame({
                "timestamp":      df["_ts"].dt.strftime("%Y-%m-%d %H:%M"),
                "ghi_kwh_per_m2": (df["ghi"] / 1000.0).round(6),
            })
            solar_caption = "GHI / 1000 → kWh/m²  |  timestamp: yyyy-mm-dd hh:mm"
        st.download_button(
            "Download Solar CSV  (kWh/m²)",
            data=pv_csv.to_csv(index=False).encode("utf-8"),
            file_name=f"solar_resource_{project_file_name}.csv",
            mime="text/csv",
            use_container_width=True,
        )
        st.caption(solar_caption)

    with c3:
        if avg_year_ok:
            wind_csv = pd.DataFrame({
                "timestamp":      avg_grp["ref_ts"],
                "wind_speed_mps": avg_grp["ws50m_avg"].round(4),
            })
            wind_caption = (
                f"8,760 rows ({avg_label})  |  wind speed in m/s  |  "
                "HOMER Pro: Resources → Wind (anemometer height = 50 m)"
            )
        else:
            wind_csv = pd.DataFrame({
                "timestamp":      df["_ts"].dt.strftime("%Y-%m-%d %H:%M"),
                "wind_speed_mps": df["ws50m"].round(4),
            })
            wind_caption = "Wind speed in m/s  |  timestamp: yyyy-mm-dd hh:mm"
        st.download_button(
            "Download Wind CSV  (m/s)",
            data=wind_csv.to_csv(index=False).encode("utf-8"),
            file_name=f"wind_resource_{project_file_name}.csv",
            mime="text/csv",
            use_container_width=True,
        )
        st.caption(wind_caption)

    # ── Temperature CSV (HOMER: Resources → Temperature) ─────────────────────
    t1, t2, t3 = st.columns([1, 1, 1])
    with t1:
        if avg_year_ok:
            temp_csv = pd.DataFrame({
                "timestamp":     avg_grp["ref_ts"],
                "temperature_c": avg_grp["temp_avg"].round(3),
            })
            temp_caption = (
                f"8,760 rows ({avg_label})  |  ambient temperature in °C  |  "
                "HOMER Pro: Resources → Temperature → Import time series"
            )
        else:
            temp_csv = pd.DataFrame({
                "timestamp":     df["_ts"].dt.strftime("%Y-%m-%d %H:%M"),
                "temperature_c": df["temperature"].round(3),
            })
            temp_caption = "Ambient temperature in °C  |  timestamp: yyyy-mm-dd hh:mm"
        st.download_button(
            "Download Temperature CSV  (°C)",
            data=temp_csv.to_csv(index=False).encode("utf-8"),
            file_name=f"temperature_{project_file_name}.csv",
            mime="text/csv",
            use_container_width=True,
        )
        st.caption(temp_caption)

    # ── Build monthly temperature table ──────────────────────────────────────
    has_temp = "temperature" in df.columns
    temp_rows = []
    if has_temp:
        for m in range(1, 13):
            mdf_t = df[df["_month"] == m]
            temp_rows.append({
                "Month":               month_names[m - 1],
                "Avg Temperature (°C)": round(float(mdf_t["temperature"].mean()), 2),
            })
    temp_table  = pd.DataFrame(temp_rows)
    ann_temp    = float(temp_table["Avg Temperature (°C)"].mean()) if has_temp else 0.0

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
            legend=dict(
                orientation="h",
                yanchor="top",
                y=-0.18,
                xanchor="center",
                x=0.5,
            ),
            height=420,
            bargap=0.25,
            margin=dict(t=60, b=60),
        )
        st.plotly_chart(pv_fig, use_container_width=True)
        st.caption(
            f"Each bar is the long-term monthly average computed across all {year_max - year_min + 1} years "
            f"of data ({years_label}). More years = more stable and representative monthly profile."
        )

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
            margin=dict(t=60),
        )
        st.plotly_chart(wind_fig, use_container_width=True)
        st.caption(
            f"Each bar is the long-term monthly average computed across all {year_max - year_min + 1} years "
            f"of data ({years_label}). More years = more stable and representative monthly profile."
        )

    # ── Temperature monthly table + chart ────────────────────────────────────
    if has_temp and not temp_table.empty:
        st.divider()
        st.markdown("#### Monthly Temperature Profile")

        tm_left, tm_right = st.columns([1, 2])

        with tm_left:
            st.dataframe(
                temp_table,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Avg Temperature (°C)": st.column_config.NumberColumn(format="%.2f"),
                },
            )
            st.caption(f"Annual Average: **{ann_temp:.2f} °C**")

        with tm_right:
            temp_fig = go.Figure()
            temp_fig.add_trace(go.Bar(
                x=month_abbr,
                y=temp_table["Avg Temperature (°C)"].tolist(),
                name="Avg Temperature (°C)",
                marker_color="#e74c3c",
            ))
            temp_fig.update_layout(
                title=f"Monthly Temperature Profile  —  Annual Avg: {ann_temp:.2f} °C",
                xaxis_title="Month",
                yaxis_title="Average Temperature (°C)",
                height=380,
                bargap=0.25,
                margin=dict(t=60),
            )
            st.plotly_chart(temp_fig, use_container_width=True)
            st.caption(
                f"Monthly average ambient temperature from NASA POWER ({years_label}). "
                "These values match what HOMER Pro shows as 'Daily Temperature' in Resources → Temperature."
            )


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
                df_new, trim_warning = fetch_nasa_power_resources(
                    lat=lat,
                    lon=lon,
                    start_year=int(start_year),
                    end_year=int(end_year),
                )
            st.session_state.current_resources_df = df_new
            st.success("NASA POWER resource data downloaded successfully.")
            if trim_warning:
                st.warning(trim_warning)
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
