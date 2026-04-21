from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from core.project import load_project
from core.resources import (
    resample_resources_to_timestep,
    NASA_HOURLY_MIN_YEAR,
    add_clearness_index,
    add_time_features,
    aggregate_resources,
    fetch_nasa_power_resources,
    load_saved_resources,
    monthly_boxplot_dataframe,
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

st.title("☀️ Resources Setup")

folder = active_project_folder()

if folder is None:
    st.warning("No project selected. Please create or open a project first.")
    st.stop()

project = load_project(folder)
st.success(f"Project: {project.meta.name}")
time_step_minutes = int(project.simulation_time_step_minutes)
st.info(f"Simulation time resolution: **{time_step_minutes} min** — resource data will be resampled to this resolution when simulation runs.")

if "current_resources_df" not in st.session_state:
    st.session_state.current_resources_df = None

if "resource_view_level" not in st.session_state:
    st.session_state.resource_view_level = "yearly"

if "resource_drill_year" not in st.session_state:
    st.session_state.resource_drill_year = None

if "resource_drill_month" not in st.session_state:
    st.session_state.resource_drill_month = None

if "resource_drill_date" not in st.session_state:
    st.session_state.resource_drill_date = None


def _project_root() -> Path:
    return Path("projects")


def _list_projects_with_resources() -> list[str]:
    root = _project_root()
    out: list[str] = []
    if not root.exists():
        return out

    for item in root.iterdir():
        if item.is_dir() and resources_file_path(item).exists():
            out.append(item.name)

    return sorted(out)


def _get_active_df() -> pd.DataFrame | None:
    if st.session_state.current_resources_df is not None:
        return st.session_state.current_resources_df

    saved_path = resources_file_path(folder)
    if saved_path.exists():
        return load_saved_resources(folder)

    return None


def _reset_drill():
    st.session_state.resource_view_level = "yearly"
    st.session_state.resource_drill_year = None
    st.session_state.resource_drill_month = None
    st.session_state.resource_drill_date = None


def _go_back_one_level():
    current = st.session_state.resource_view_level

    if current == "hourly":
        st.session_state.resource_view_level = "daily"
        st.session_state.resource_drill_date = None
        return

    if current == "daily":
        st.session_state.resource_view_level = "monthly"
        st.session_state.resource_drill_month = None
        st.session_state.resource_drill_date = None
        return

    if current == "monthly":
        st.session_state.resource_view_level = "yearly"
        st.session_state.resource_drill_year = None
        st.session_state.resource_drill_month = None
        st.session_state.resource_drill_date = None


def _filter_for_drill(df: pd.DataFrame) -> pd.DataFrame:
    out = add_time_features(df)

    if st.session_state.resource_drill_year is not None:
        out = out[out["year"] == int(st.session_state.resource_drill_year)].copy()

    if st.session_state.resource_drill_month is not None:
        out = out[out["month"] == int(st.session_state.resource_drill_month)].copy()

    if st.session_state.resource_drill_date is not None:
        target = pd.to_datetime(st.session_state.resource_drill_date)
        out = out[out["date"] == target].copy()

    return out.reset_index(drop=True)


def _build_main_view_df(df: pd.DataFrame, view_level: str, metric: str) -> pd.DataFrame:
    filtered = _filter_for_drill(df)
    return aggregate_resources(filtered, level=view_level, metric=metric)


def _normalize_columns(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    out = df.copy()
    for col in cols:
        cmin = out[col].min()
        cmax = out[col].max()
        if pd.isna(cmin) or pd.isna(cmax) or abs(cmax - cmin) < 1e-12:
            out[col] = 0.0
        else:
            out[col] = (out[col] - cmin) / (cmax - cmin)
    return out


def _build_main_chart(df: pd.DataFrame, view_level: str, chart_mode: str):
    chart_df = df.copy()

    if chart_mode == "combined_comparison":
        plot_df = _normalize_columns(chart_df.copy(), ["ghi", "ws50m", "temperature"])
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=plot_df["label"], y=plot_df["ghi"], mode="lines+markers", name="GHI (norm)"))
        fig.add_trace(go.Scatter(x=plot_df["label"], y=plot_df["ws50m"], mode="lines+markers", name="Wind (norm)"))
        fig.add_trace(go.Scatter(x=plot_df["label"], y=plot_df["temperature"], mode="lines+markers", name="Temp (norm)"))
        fig.update_layout(
            title=f"Combined Comparison — {view_level.title()}",
            xaxis_title="Time",
            yaxis_title="Normalized Value",
            height=500,
        )
        return fig

    column_map = {
        "solar_detail": "ghi",
        "wind_detail": "ws50m",
        "temperature_detail": "temperature",
    }

    title_map = {
        "solar_detail": "Solar Detail — GHI (Wh/m²)",
        "wind_detail": "Wind Detail — WS50M (m/s)",
        "temperature_detail": "Temperature Detail (°C)",
    }

    y_col = column_map[chart_mode]

    fig = px.line(
        chart_df,
        x="label",
        y=y_col,
        title=f"{title_map[chart_mode]} — {view_level.title()}",
        markers=True,
    )
    fig.update_layout(height=500)
    return fig


def _extract_selected_x(selection_event) -> list:
    if selection_event is None:
        return []

    try:
        points = selection_event.selection.points
    except Exception:
        try:
            points = selection_event["selection"]["points"]
        except Exception:
            return []

    xs = []
    for p in points:
        if isinstance(p, dict):
            xs.append(p.get("x"))
        else:
            try:
                xs.append(p["x"])
            except Exception:
                pass
    return xs


def _show_download_buttons(raw_df: pd.DataFrame, aggregated_df: pd.DataFrame):
    d1, d2 = st.columns(2)

    with d1:
        st.download_button(
            "Download Raw Resources CSV",
            data=raw_df.to_csv(index=False).encode("utf-8"),
            file_name="resources_raw.csv",
            mime="text/csv",
            use_container_width=True,
        )

    with d2:
        st.download_button(
            "Download Aggregated View CSV",
            data=aggregated_df.to_csv(index=False).encode("utf-8"),
            file_name="resources_aggregated.csv",
            mime="text/csv",
            use_container_width=True,
        )


def _show_comparison_section(active_df: pd.DataFrame):
    st.divider()
    st.subheader("Compare Multiple Locations Side-by-Side")

    available_projects = _list_projects_with_resources()
    active_name = Path(folder).name
    compare_candidates = [p for p in available_projects if p != active_name]

    c1, c2, c3 = st.columns(3)

    with c1:
        compare_projects = st.multiselect(
            "Additional Projects to Compare",
            options=compare_candidates,
            default=[],
        )

    with c2:
        compare_level = st.selectbox(
            "Comparison View",
            options=["yearly", "monthly", "monthly_climatology"],
            index=2,
        )

    with c3:
        compare_variable = st.selectbox(
            "Comparison Variable",
            options=["ghi", "ws50m", "temperature"],
            index=0,
        )

    if not compare_projects:
        st.info("Select one or more saved projects to compare locations.")
        return

    frames: list[pd.DataFrame] = []

    base_name = active_name
    if compare_level == "monthly_climatology":
        base_df = monthly_climatology(active_df)[["label", compare_variable]].copy()
    else:
        base_df = aggregate_resources(active_df, level=compare_level, metric="mean")[["label", compare_variable]].copy()
    base_df["project_name"] = base_name
    frames.append(base_df)

    for proj_name in compare_projects:
        proj_folder = Path("projects") / proj_name
        proj_df = load_saved_resources(proj_folder)
        if compare_level == "monthly_climatology":
            agg = monthly_climatology(proj_df)[["label", compare_variable]].copy()
        else:
            agg = aggregate_resources(proj_df, level=compare_level, metric="mean")[["label", compare_variable]].copy()
        agg["project_name"] = proj_name
        frames.append(agg)

    compare_df = pd.concat(frames, ignore_index=True)

    title_map = {
        "ghi": "GHI (Wh/m²)",
        "ws50m": "WS50M (m/s)",
        "temperature": "Temperature (°C)",
    }

    fig = px.line(
        compare_df,
        x="label",
        y=compare_variable,
        color="project_name",
        markers=True,
        title=f"{title_map[compare_variable]} Comparison — {compare_level.replace('_', ' ').title()}",
    )
    fig.update_layout(height=500)
    st.plotly_chart(fig, use_container_width=True)

    st.dataframe(compare_df.head(200), use_container_width=True)

    st.download_button(
        "Download Comparison CSV",
        data=compare_df.to_csv(index=False).encode("utf-8"),
        file_name="resource_location_comparison.csv",
        mime="text/csv",
        use_container_width=True,
    )


def _show_resources_output(df: pd.DataFrame, ts_minutes: int = 60):
    summary = summarize_resources(df)

    st.divider()
    st.subheader("Resource Summary")

    a1, a2, a3, a4, a5 = st.columns(5)
    a1.metric("Rows", f"{summary.rows:,}")
    a2.metric("Mean GHI (Wh/m²)", f"{summary.ghi_mean:.2f}")
    a3.metric("Mean WS50M (m/s)", f"{summary.ws50m_mean:.2f}")
    a4.metric("Mean Temp (°C)", f"{summary.temperature_mean:.2f}")
    a5.metric("Coverage", f"{summary.start_timestamp.year}–{summary.end_timestamp.year}")

    st.subheader("Raw Preview (Original Hourly Data)")
    preview_df = df.head(24).rename(
        columns={
            "ghi": "ghi_wh_per_m2",
            "ws50m": "ws50m_mps",
            "temperature": "temperature_c",
        }
    )
    st.dataframe(preview_df, use_container_width=True)

    # ── Resampled preview ──────────────────────────────────────────────────
    if ts_minutes != 60:
        st.divider()
        try:
            steps_per_day = round(24 * 60 / ts_minutes)
            rs_df = resample_resources_to_timestep(df, ts_minutes)
            st.subheader(
                f"Resampled Preview — {ts_minutes} min resolution  "
                f"| {len(rs_df):,} rows | Mean GHI: {rs_df['ghi'].mean():.2f} Wh/m² "
                f"| Mean Wind: {rs_df['ws50m'].mean():.2f} m/s"
            )
            st.caption(f"First {steps_per_day} rows = first 24 hours at {ts_minutes}-min resolution")
            st.dataframe(
                rs_df.head(steps_per_day).rename(
                    columns={"ghi": "ghi_wh_per_m2", "ws50m": "ws50m_mps", "temperature": "temperature_c"}
                ),
                use_container_width=True,
            )
            st.subheader(f"First Day Chart — {ts_minutes} min steps")
            chart_rs = rs_df.head(steps_per_day).set_index("timestamp")[["ghi", "ws50m", "temperature"]]
            st.line_chart(chart_rs, use_container_width=True)
        except Exception as e:
            st.warning(f"Could not resample for preview: {e}")

    # ── Clearness Index ───────────────────────────────────────────────────
    st.divider()
    st.subheader("Clearness Index (HOMER-Matched GHI Processing)")
    st.caption(
        "Computes G0 (extraterrestrial irradiance) and Kt = GHI / G0 for each hour "
        "using HOMER's documented equation of time formula. When saved, the PV model "
        "can use Kt-capped GHI to match HOMER output within ~0.07%."
    )

    if "clearness_index" in df.columns and "g0_w_m2" in df.columns:
        daytime = df[df["g0_w_m2"] > 10]
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Daytime Hours", f"{len(daytime):,}")
        k2.metric("Mean Kt (daytime)", f"{daytime['clearness_index'].mean():.4f}")
        k3.metric("Hours Kt > 0.82", f"{(daytime['clearness_index'] > 0.82).sum()}")
        k4.metric("Max Kt", f"{daytime['clearness_index'].max():.4f}")
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
            with st.spinner("Computing G0 and Kt for each hour using HOMER EoT formula..."):
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

    st.divider()
    st.subheader("Long-Term Analysis")

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        view_level = st.selectbox(
            "View Level",
            options=["yearly", "monthly", "daily", "hourly"],
            index=["yearly", "monthly", "daily", "hourly"].index(st.session_state.resource_view_level),
        )

    with c2:
        metric = st.selectbox(
            "Aggregation",
            options=["mean", "sum"],
            index=0,
        )

    with c3:
        chart_mode = st.selectbox(
            "Chart Mode",
            options=["combined_comparison", "solar_detail", "wind_detail", "temperature_detail"],
            index=0,
        )

    with c4:
        heatmap_variable = st.selectbox(
            "Heatmap / Box Variable",
            options=["ghi", "ws50m", "temperature"],
            index=0,
        )

    st.session_state.resource_view_level = view_level

    nav1, nav2, nav3 = st.columns(3)
    with nav1:
        if st.button("⬅ Back One Level", use_container_width=True):
            _go_back_one_level()
            st.rerun()

    with nav2:
        if st.button("⟳ Reset Drilldown", use_container_width=True):
            _reset_drill()
            st.rerun()

    with nav3:
        st.caption(
            f"Current Drill: "
            f"Year={st.session_state.resource_drill_year}, "
            f"Month={st.session_state.resource_drill_month}, "
            f"Date={st.session_state.resource_drill_date}"
        )

    filtered_for_view = _filter_for_drill(df)

    f1, f2, f3 = st.columns(3)

    all_years = sorted(add_time_features(df)["year"].unique().tolist())
    with f1:
        manual_year = st.selectbox(
            "Manual Year Focus (optional)",
            options=["All"] + [str(y) for y in all_years],
            index=0 if st.session_state.resource_drill_year is None else [str(y) for y in all_years].index(str(st.session_state.resource_drill_year)) + 1,
        )

    if manual_year != "All":
        st.session_state.resource_drill_year = int(manual_year)
    elif view_level == "yearly":
        st.session_state.resource_drill_year = None

    filtered_after_year = _filter_for_drill(df)
    tf = add_time_features(filtered_after_year)

    month_map = {
        1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
        7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec",
    }
    month_options = sorted(tf["month"].unique().tolist()) if not tf.empty else []

    with f2:
        manual_month = st.selectbox(
            "Manual Month Focus (optional)",
            options=["All"] + [f"{m:02d} - {month_map[m]}" for m in month_options],
            index=0 if st.session_state.resource_drill_month is None else month_options.index(int(st.session_state.resource_drill_month)) + 1 if int(st.session_state.resource_drill_month) in month_options else 0,
        )

    if manual_month != "All":
        st.session_state.resource_drill_month = int(manual_month.split(" - ")[0])
    elif view_level in {"yearly", "monthly"}:
        st.session_state.resource_drill_month = None

    filtered_after_month = _filter_for_drill(df)
    tf2 = add_time_features(filtered_after_month)
    date_options = sorted(tf2["date"].dt.date.unique().tolist()) if not tf2.empty else []

    with f3:
        manual_date = st.selectbox(
            "Manual Day Focus (optional)",
            options=["All"] + date_options,
            index=0 if st.session_state.resource_drill_date is None else date_options.index(pd.to_datetime(st.session_state.resource_drill_date).date()) + 1 if pd.to_datetime(st.session_state.resource_drill_date).date() in date_options else 0,
        )

    if manual_date != "All":
        st.session_state.resource_drill_date = pd.to_datetime(manual_date)
    elif view_level in {"yearly", "monthly", "daily"}:
        st.session_state.resource_drill_date = None

    main_df = _build_main_view_df(df, view_level=view_level, metric=metric)
    fig = _build_main_chart(main_df, view_level=view_level, chart_mode=chart_mode)

    st.markdown("### Main Resource Chart")
    selection_event = st.plotly_chart(
        fig,
        use_container_width=True,
        key="resources_main_chart",
        on_select="rerun",
        selection_mode=("points", "box", "lasso"),
    )

    selected_x = _extract_selected_x(selection_event)

    drill_c1, drill_c2 = st.columns(2)

    with drill_c1:
        if view_level == "yearly" and selected_x:
            if st.button("Drill Down to Monthly from Selection", use_container_width=True):
                try:
                    st.session_state.resource_drill_year = int(float(selected_x[0]))
                    st.session_state.resource_drill_month = None
                    st.session_state.resource_drill_date = None
                    st.session_state.resource_view_level = "monthly"
                    st.rerun()
                except Exception:
                    st.warning("Could not interpret selected year.")

        elif view_level == "monthly" and selected_x:
            if st.button("Drill Down to Daily from Selection", use_container_width=True):
                try:
                    ts = pd.to_datetime(selected_x[0])
                    st.session_state.resource_drill_year = int(ts.year)
                    st.session_state.resource_drill_month = int(ts.month)
                    st.session_state.resource_drill_date = None
                    st.session_state.resource_view_level = "daily"
                    st.rerun()
                except Exception:
                    st.warning("Could not interpret selected month.")

        elif view_level == "daily" and selected_x:
            if st.button("Drill Down to Hourly from Selection", use_container_width=True):
                try:
                    ts = pd.to_datetime(selected_x[0])
                    st.session_state.resource_drill_year = int(ts.year)
                    st.session_state.resource_drill_month = int(ts.month)
                    st.session_state.resource_drill_date = pd.to_datetime(ts.date())
                    st.session_state.resource_view_level = "hourly"
                    st.rerun()
                except Exception:
                    st.warning("Could not interpret selected day.")

    with drill_c2:
        if selected_x:
            st.caption(f"Selected points: {selected_x[:3]}{' ...' if len(selected_x) > 3 else ''}")
        else:
            st.caption("Select a point or range on the chart to drill down.")

    st.markdown("### Aggregated Data Preview")
    st.dataframe(main_df.head(200), use_container_width=True)

    _show_download_buttons(df, main_df)

    variable_title_map = {
        "ghi": "GHI (Wh/m²)",
        "ws50m": "WS50M (m/s)",
        "temperature": "Temperature (°C)",
    }

    st.divider()
    st.subheader("Monthly Heatmap")

    heatmap_metric = st.selectbox("Heatmap Aggregation", options=["mean", "sum"], index=0)
    heatmap_table = monthly_heatmap_table(df, variable=heatmap_variable, metric=heatmap_metric)

    heatmap_fig = px.imshow(
        heatmap_table,
        aspect="auto",
        color_continuous_scale="Viridis",
        labels=dict(x="Month", y="Year", color=variable_title_map[heatmap_variable]),
        title=f"Monthly Heatmap — {variable_title_map[heatmap_variable]} ({heatmap_metric})",
    )
    heatmap_fig.update_layout(height=500)
    st.plotly_chart(heatmap_fig, use_container_width=True)

    st.divider()
    st.subheader("Month-wise Box Plot")

    box_metric = st.selectbox("Box Plot Aggregation", options=["mean", "sum"], index=0)
    box_df = monthly_boxplot_dataframe(df, variable=heatmap_variable, metric=box_metric)

    box_fig = px.box(
        box_df,
        x="month_name",
        y="value",
        points="outliers",
        title=f"Month-wise Box Plot — {variable_title_map[heatmap_variable]} ({box_metric})",
    )
    box_fig.update_layout(
        height=500,
        xaxis_title="Month",
        yaxis_title=variable_title_map[heatmap_variable],
    )
    st.plotly_chart(box_fig, use_container_width=True)

    st.divider()
    st.subheader("Monthly Climatology")

    clim_df = monthly_climatology(df)

    clim_fig = go.Figure()
    clim_fig.add_trace(go.Scatter(x=clim_df["label"], y=clim_df["ghi"], mode="lines+markers", name="GHI (Wh/m²)"))
    clim_fig.add_trace(go.Scatter(x=clim_df["label"], y=clim_df["ws50m"], mode="lines+markers", name="Wind (m/s)"))
    clim_fig.add_trace(go.Scatter(x=clim_df["label"], y=clim_df["temperature"], mode="lines+markers", name="Temp (°C)"))
    clim_fig.update_layout(title="Monthly Climatology (All Years)", height=500)
    st.plotly_chart(clim_fig, use_container_width=True)

    st.download_button(
        "Download Monthly Climatology CSV",
        data=clim_df.to_csv(index=False).encode("utf-8"),
        file_name="monthly_climatology.csv",
        mime="text/csv",
        use_container_width=True,
    )

    _show_comparison_section(df)

    st.divider()
    if st.button("Save Resources to Project", type="primary", use_container_width=True):
        try:
            path = save_resources(df, folder)
            st.success(f"Resources saved successfully: {path}")
            st.rerun()
        except Exception as e:
            st.error(f"Failed to save resources: {e}")


st.divider()
st.subheader("NASA POWER Resource Download")

lat = project.location.lat
lon = project.location.lon

c1, c2, c3, c4 = st.columns(4)
c1.metric("Latitude", f"{lat:.4f}")
c2.metric("Longitude", f"{lon:.4f}")
start_year = c3.number_input("Start Year", min_value=1980, max_value=2100, value=2001, step=1)
end_year = c4.number_input("End Year", min_value=1980, max_value=2100, value=2025, step=1)

st.caption(
    f"NASA POWER hourly data is downloaded in chunks from {NASA_HOURLY_MIN_YEAR} onward. "
    f"If you enter an earlier year, the request is automatically clamped to {NASA_HOURLY_MIN_YEAR}."
)

if st.button("Download from NASA POWER", type="primary"):
    try:
        if end_year < start_year:
            st.error("End year must be greater than or equal to start year.")
        else:
            with st.spinner("Downloading NASA POWER hourly data in chunks..."):
                df = fetch_nasa_power_resources(
                    lat=lat,
                    lon=lon,
                    start_year=int(start_year),
                    end_year=int(end_year),
                )
            st.session_state.current_resources_df = df
            _reset_drill()
            st.success("NASA POWER resource data downloaded successfully.")
    except Exception as e:
        st.session_state.current_resources_df = None
        st.error(f"Could not download NASA POWER data: {e}")

active_df = _get_active_df()

if active_df is not None:
    _show_resources_output(active_df, ts_minutes=time_step_minutes)
else:
    st.info("No downloaded or saved resource data found yet for this project.")