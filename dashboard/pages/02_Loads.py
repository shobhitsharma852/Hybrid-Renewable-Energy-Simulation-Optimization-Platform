import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from core.project import Project, load_project, save_project
from core.load import (
    LoadGenerationSettings,
    read_uploaded_load,
    create_constant_load,
    create_daily_profile_load,
    load_load_generation_settings,
    create_weekday_weekend_monthly_profile_load,
    save_load_generation_settings,
    scale_load_to_annual_energy,
    resample_load_to_timestep,
    save_load,
    summarize_load,
    daily_load_summary,
    load_duration_summary,
    load_quality_messages,
    monthly_load_summary,
    load_file_path,
)
from dashboard.ui.state import active_project_folder
from dashboard.ui.sidebar import render_left_panel
from dashboard.ui.layout import top_bar

top_bar("Load")
render_left_panel()

MONTH_LABELS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

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
        "Weekday/Weekend + Monthly",
    ]
)

# Persist generated load across reruns
if "current_load_df" not in st.session_state:
    st.session_state.current_load_df = None

load_df = None


def _default_monthly_profile_table(default_kw: float) -> pd.DataFrame:
    data = {"Hour": list(range(24))}
    for month in MONTH_LABELS:
        data[month] = [float(default_kw)] * 24
    return pd.DataFrame(data)


def _monthly_profiles_to_table(profiles: list[list[float]]) -> pd.DataFrame:
    data = {"Hour": list(range(24))}
    for month, monthly_profile in zip(MONTH_LABELS, profiles):
        data[month] = [float(v) for v in monthly_profile]
    return pd.DataFrame(data)


def _clean_monthly_profile_table(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["Hour"] = list(range(24))
    for month in MONTH_LABELS:
        out[month] = pd.to_numeric(out[month], errors="coerce").fillna(0.0).clip(lower=0.0)
    return out[["Hour", *MONTH_LABELS]]


def _monthly_profile_table_to_profiles(df: pd.DataFrame) -> list[list[float]]:
    clean_df = _clean_monthly_profile_table(df)
    return [
        [float(v) for v in clean_df[month].tolist()]
        for month in MONTH_LABELS
    ]


def _apply_monthly_profile_editor_changes(
    table_key: str,
    editor_key: str,
    copy_to_right_key: str,
    copy_to_weekend_key: str | None = None,
) -> None:
    editor_state = st.session_state.get(editor_key, {})
    edited_rows = editor_state.get("edited_rows", {})
    if not edited_rows:
        return

    table = _clean_monthly_profile_table(st.session_state[table_key])
    copy_to_right = bool(st.session_state.get(copy_to_right_key, False))

    for row_key, changes in edited_rows.items():
        row_idx = int(row_key)
        for month, value in changes.items():
            if month == "Hour" or month not in MONTH_LABELS:
                continue

            new_value = max(0.0, float(value))
            month_idx = MONTH_LABELS.index(month)
            target_months = MONTH_LABELS[month_idx:] if copy_to_right else [month]
            for target_month in target_months:
                table.loc[row_idx, target_month] = new_value

    st.session_state[table_key] = table

    if copy_to_weekend_key and bool(st.session_state.get(copy_to_weekend_key, False)):
        st.session_state.weekend_monthly_profile_table = table.copy()


def _handle_copy_weekdays_to_weekends_toggle() -> None:
    enabled = bool(st.session_state.get("monthly_profile_copy_to_weekend", False))
    was_enabled = bool(st.session_state.get("_monthly_profile_copy_to_weekend_prev", False))

    if enabled and not was_enabled:
        st.session_state["_weekend_monthly_profile_table_backup"] = (
            st.session_state.weekend_monthly_profile_table.copy()
        )
        st.session_state.weekend_monthly_profile_table = (
            st.session_state.weekday_monthly_profile_table.copy()
        )
    elif not enabled and was_enabled:
        backup = st.session_state.get("_weekend_monthly_profile_table_backup")
        if backup is not None:
            st.session_state.weekend_monthly_profile_table = backup.copy()

    st.session_state["_monthly_profile_copy_to_weekend_prev"] = enabled


def _render_annual_energy_scaling() -> None:
    scaling_enabled = project.load.scaled_annual_energy_kwh is not None

    with st.expander("Annual Energy Scaling", expanded=scaling_enabled):
        scale_enabled = st.checkbox(
            "Scale saved load to annual energy target",
            value=scaling_enabled,
            help="Scale the saved load profile to a target annual energy while preserving its shape.",
            key="annual_energy_scaling_enabled",
        )

        scale_target_default = (
            float(project.load.scaled_annual_energy_kwh)
            if project.load.scaled_annual_energy_kwh is not None
            else 100000.0
        )
        scaled_annual_energy_kwh = st.number_input(
            "Target annual energy (kWh)",
            min_value=1.0,
            value=scale_target_default,
            step=1000.0,
            disabled=not scale_enabled,
            key="annual_energy_scaling_target",
        )

        if st.button("Save Annual Energy Scaling", key="save_annual_energy_scaling"):
            try:
                updated_project = Project(
                    meta=project.meta,
                    location=project.location,
                    economics=project.economics,
                    load=type(project.load)(
                        scaled_annual_energy_kwh=(
                            float(scaled_annual_energy_kwh) if scale_enabled else None
                        )
                    ),
                    version=project.version,
                    simulation_time_step_minutes=project.simulation_time_step_minutes,
                )
                save_project(updated_project, folder)
                st.success("Annual energy scaling settings saved.")
                st.rerun()
            except Exception as e:
                st.error(f"Could not save annual energy scaling settings: {e}")


def _render_monthly_load_comparison(df: pd.DataFrame) -> None:
    try:
        monthly_df = monthly_load_summary(df)
    except Exception as e:
        st.warning(f"Could not build monthly load comparison: {e}")
        return

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Bar(
            x=monthly_df["month_name"],
            y=monthly_df["energy_kwh"],
            name="Energy (kWh)",
            marker_color="#3b82f6",
            opacity=0.78,
            hovertemplate="%{x}<br>Energy: %{y:,.0f} kWh<extra></extra>",
        ),
        secondary_y=False,
    )

    for column, label, color in [
        ("peak_kw", "Peak Load (kW)", "#ef4444"),
        ("average_kw", "Average Load (kW)", "#16a34a"),
        ("min_kw", "Minimum Load (kW)", "#7c3aed"),
    ]:
        fig.add_trace(
            go.Scatter(
                x=monthly_df["month_name"],
                y=monthly_df[column],
                name=label,
                mode="lines+markers",
                line={"color": color, "width": 2},
                marker={"size": 7},
                hovertemplate=f"%{{x}}<br>{label}: %{{y:,.2f}}<extra></extra>",
            ),
            secondary_y=True,
        )

    fig.update_layout(
        height=460,
        margin={"l": 20, "r": 20, "t": 35, "b": 20},
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "xanchor": "left",
            "x": 0,
        },
        hovermode="x unified",
        bargap=0.28,
    )
    fig.update_xaxes(title_text="Month")
    fig.update_yaxes(title_text="Energy (kWh)", secondary_y=False, rangemode="tozero")
    fig.update_yaxes(title_text="Load (kW)", secondary_y=True, rangemode="tozero")

    st.subheader("Monthly Load Comparison")
    st.plotly_chart(fig, use_container_width=True)

    table_df = monthly_df.rename(
        columns={
            "month_name": "Month",
            "energy_kwh": "Energy (kWh)",
            "peak_kw": "Peak Load (kW)",
            "average_kw": "Average Load (kW)",
            "min_kw": "Minimum Load (kW)",
        }
    )
    st.dataframe(
        table_df[["Month", "Energy (kWh)", "Peak Load (kW)", "Average Load (kW)", "Minimum Load (kW)"]],
        use_container_width=True,
        hide_index=True,
    )


def _render_daily_load_comparison(df: pd.DataFrame) -> None:
    try:
        daily_df = daily_load_summary(df)
    except Exception as e:
        st.warning(f"Could not build daily load comparison: {e}")
        return

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Bar(
            x=daily_df["date"],
            y=daily_df["energy_kwh"],
            name="Daily Energy (kWh)",
            marker_color="#3b82f6",
            opacity=0.72,
            hovertemplate="%{x}<br>Energy: %{y:,.0f} kWh<extra></extra>",
        ),
        secondary_y=False,
    )
    for column, label, color in [
        ("peak_kw", "Daily Peak (kW)", "#ef4444"),
        ("average_kw", "Daily Average (kW)", "#16a34a"),
    ]:
        fig.add_trace(
            go.Scatter(
                x=daily_df["date"],
                y=daily_df[column],
                name=label,
                mode="lines",
                line={"color": color, "width": 2},
                hovertemplate=f"%{{x}}<br>{label}: %{{y:,.2f}}<extra></extra>",
            ),
            secondary_y=True,
        )

    fig.update_layout(
        height=460,
        margin={"l": 20, "r": 20, "t": 35, "b": 20},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "left", "x": 0},
        hovermode="x unified",
        bargap=0.05,
    )
    fig.update_xaxes(title_text="Date")
    fig.update_yaxes(title_text="Energy (kWh)", secondary_y=False, rangemode="tozero")
    fig.update_yaxes(title_text="Load (kW)", secondary_y=True, rangemode="tozero")

    st.subheader("Daily Load Comparison")
    st.plotly_chart(fig, use_container_width=True)

    table_df = daily_df.rename(
        columns={
            "date": "Date",
            "day_type": "Day Type",
            "energy_kwh": "Energy (kWh)",
            "peak_kw": "Peak Load (kW)",
            "average_kw": "Average Load (kW)",
            "min_kw": "Minimum Load (kW)",
        }
    )
    st.dataframe(
        table_df[["Date", "Day Type", "Energy (kWh)", "Peak Load (kW)", "Average Load (kW)", "Minimum Load (kW)"]],
        use_container_width=True,
        hide_index=True,
    )


def _render_load_duration_curve(df: pd.DataFrame) -> None:
    try:
        duration_df = load_duration_summary(df)
    except Exception as e:
        st.warning(f"Could not build load duration curve: {e}")
        return

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=duration_df["percent_of_time"],
            y=duration_df["load_kw"],
            name="Load (kW)",
            mode="lines",
            line={"color": "#2563eb", "width": 2},
            hovertemplate="%{x:.1f}% of time<br>Load: %{y:,.2f} kW<extra></extra>",
        )
    )
    fig.update_layout(
        height=460,
        margin={"l": 20, "r": 20, "t": 35, "b": 20},
        hovermode="x",
    )
    fig.update_xaxes(title_text="Percent of Time Load Is Met or Exceeded")
    fig.update_yaxes(title_text="Load (kW)", rangemode="tozero")

    st.subheader("Load Duration Curve")
    st.plotly_chart(fig, use_container_width=True)
    st.dataframe(
        duration_df.rename(
            columns={
                "rank": "Rank",
                "percent_of_time": "Percent of Time",
                "load_kw": "Load (kW)",
            }
        ).head(500),
        use_container_width=True,
        hide_index=True,
    )


def _render_load_quality_checks(df: pd.DataFrame) -> None:
    daily_variability_pct = float(st.session_state.get("load_daily_variability_pct", 0.0))
    timestep_variability_pct = float(st.session_state.get("load_timestep_variability_pct", 0.0))
    variability_enabled = daily_variability_pct > 0 or timestep_variability_pct > 0
    random_seed_enabled = bool(st.session_state.get("load_random_seed_enabled", True))

    messages = load_quality_messages(
        df,
        variability_enabled=variability_enabled,
        random_seed_enabled=random_seed_enabled,
    )

    st.subheader("Load Quality Checks")
    for item in messages:
        if item.level == "warning":
            st.warning(item.message)
        elif item.level == "success":
            st.success(item.message)
        else:
            st.info(item.message)


def _prepare_simulation_ready_load(df: pd.DataFrame, ts_minutes: int) -> pd.DataFrame:
    preview_df = df.copy()
    if ts_minutes > 0 and len(preview_df) > 1:
        diffs = preview_df["timestamp"].diff().dropna()
        current_step_minutes = diffs.iloc[0].total_seconds() / 60.0
        if abs(current_step_minutes - float(ts_minutes)) > 1e-9:
            preview_df = resample_load_to_timestep(preview_df, ts_minutes)

    if project.load.scaled_annual_energy_kwh is not None:
        preview_df = scale_load_to_annual_energy(
            preview_df,
            float(project.load.scaled_annual_energy_kwh),
        )

    return preview_df


def _render_simulation_ready_preview(df: pd.DataFrame, ts_minutes: int) -> None:
    try:
        preview_df = _prepare_simulation_ready_load(df, ts_minutes)
        preview_summary = summarize_load(preview_df)
    except Exception as e:
        st.warning(f"Could not prepare simulation-ready load preview: {e}")
        return

    st.divider()
    st.subheader("Simulation-Ready Load Preview")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Rows", f"{preview_summary.rows:,}")
    c2.metric("Peak Load (kW)", f"{preview_summary.peak_kw:.2f}")
    c3.metric("Average Load (kW)", f"{preview_summary.average_kw:.2f}")
    c4.metric("Annual Energy (kWh)", f"{preview_summary.annual_energy_kwh:,.0f}")

    preview_modes = ["Monthly", "Daily", "Load Duration"]
    if hasattr(st, "segmented_control"):
        preview_mode = st.segmented_control(
            "Preview Mode",
            preview_modes,
            default="Monthly",
            key="load_preview_mode",
        )
    else:
        preview_mode = st.radio(
            "Preview Mode",
            preview_modes,
            index=0,
            horizontal=True,
            key="load_preview_mode",
        )

    if preview_mode == "Monthly":
        _render_monthly_load_comparison(preview_df)
    elif preview_mode == "Daily":
        _render_daily_load_comparison(preview_df)
    else:
        _render_load_duration_curve(preview_df)

    _render_load_quality_checks(preview_df)

    st.subheader("Simulation-Ready Data Preview")
    st.dataframe(preview_df.head(24), use_container_width=True)


def _show_load_output(df: pd.DataFrame, ts_minutes: int = 60):
    summary = summarize_load(df)

    st.divider()
    st.subheader("Load Summary (Original Data)")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Rows", f"{summary.rows:,}")
    c2.metric("Peak Load (kW)", f"{summary.peak_kw:.2f}")
    c3.metric("Average Load (kW)", f"{summary.average_kw:.2f}")
    c4.metric("Annual Energy (kWh)", f"{summary.annual_energy_kwh:,.0f}")

    st.subheader("Original Data Preview (first 24 rows)")
    st.dataframe(df.head(24), use_container_width=True)

    _render_simulation_ready_preview(df, ts_minutes)

    st.divider()
    _render_annual_energy_scaling()

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

# -----------------------------
# Weekday / Weekend + Monthly
# -----------------------------
elif method == "Weekday/Weekend + Monthly":
    folder_key = str(folder)
    if st.session_state.get("_load_generation_loaded_for_folder") != folder_key:
        saved_load_settings = load_load_generation_settings(folder)
        st.session_state.weekday_monthly_profile_table = _monthly_profiles_to_table(
            saved_load_settings.weekday_monthly_profiles_kw
            or [[50.0] * 24 for _ in range(12)]
        )
        st.session_state.weekend_monthly_profile_table = _monthly_profiles_to_table(
            saved_load_settings.weekend_monthly_profiles_kw
            or [[30.0] * 24 for _ in range(12)]
        )
        st.session_state["_weekend_monthly_profile_table_backup"] = (
            st.session_state.weekend_monthly_profile_table.copy()
        )
        st.session_state["_monthly_profile_copy_to_weekend_prev"] = False
        st.session_state["monthly_profile_copy_to_weekend"] = False
        st.session_state.load_daily_variability_pct = float(
            saved_load_settings.daily_variability_pct
        )
        st.session_state.load_timestep_variability_pct = float(
            saved_load_settings.timestep_variability_pct
        )
        st.session_state.load_random_seed_enabled = saved_load_settings.random_seed is not None
        st.session_state.load_random_seed = int(saved_load_settings.random_seed or 42)
        st.session_state.load_preserve_annual_energy = bool(
            saved_load_settings.preserve_annual_energy
        )
        st.session_state["_load_generation_loaded_for_folder"] = folder_key

    if "weekday_monthly_profile_table" not in st.session_state:
        st.session_state.weekday_monthly_profile_table = _default_monthly_profile_table(50.0)
    if "weekend_monthly_profile_table" not in st.session_state:
        st.session_state.weekend_monthly_profile_table = _default_monthly_profile_table(30.0)
    col_copy1, col_copy2 = st.columns(2)
    with col_copy1:
        copy_to_right = st.checkbox(
            "Copy edited cells to right",
            value=False,
            help="When a cell changes, copy that value across the same hour for the remaining months.",
            key="monthly_profile_copy_to_right",
        )
    with col_copy2:
        copy_to_weekend = st.checkbox(
            "Copy Weekdays to Weekends",
            value=False,
            help="When checked, weekend values use the weekday table. Uncheck to restore the previous weekend table.",
            key="monthly_profile_copy_to_weekend",
            on_change=_handle_copy_weekdays_to_weekends_toggle,
        )

    column_config = {
        "Hour": st.column_config.NumberColumn("Hour", width="small"),
        **{
            month: st.column_config.NumberColumn(
                month,
                min_value=0.0,
                step=5.0,
                format="%.3f",
            )
            for month in MONTH_LABELS
        },
    }

    tab_weekday, tab_weekend = st.tabs(["Weekdays", "Weekends"])

    with tab_weekday:
        st.data_editor(
            st.session_state.weekday_monthly_profile_table,
            column_config=column_config,
            disabled=["Hour"],
            hide_index=True,
            num_rows="fixed",
            use_container_width=True,
            key="weekday_monthly_profile_editor",
            on_change=_apply_monthly_profile_editor_changes,
            args=(
                "weekday_monthly_profile_table",
                "weekday_monthly_profile_editor",
                "monthly_profile_copy_to_right",
                "monthly_profile_copy_to_weekend",
            ),
        )

    weekday_table = _clean_monthly_profile_table(
        st.session_state.weekday_monthly_profile_table
    )

    if copy_to_weekend:
        st.session_state.weekend_monthly_profile_table = weekday_table.copy()

    with tab_weekend:
        st.data_editor(
            st.session_state.weekend_monthly_profile_table,
            column_config=column_config,
            disabled=True if copy_to_weekend else ["Hour"],
            hide_index=True,
            num_rows="fixed",
            use_container_width=True,
            key="weekend_monthly_profile_editor",
            on_change=_apply_monthly_profile_editor_changes,
            args=(
                "weekend_monthly_profile_table",
                "weekend_monthly_profile_editor",
                "monthly_profile_copy_to_right",
                None,
            ),
        )

    weekend_table = _clean_monthly_profile_table(
        st.session_state.weekend_monthly_profile_table
    )
    if copy_to_weekend:
        weekend_table = weekday_table.copy()
    st.session_state.weekend_monthly_profile_table = weekend_table

    synthetic_year = st.number_input(
        "Synthetic load year",
        min_value=2000,
        max_value=2100,
        value=2025,
        step=1,
    )

    st.write("Variability")
    var_col1, var_col2 = st.columns(2)
    with var_col1:
        daily_variability_pct = st.number_input(
            "Day-to-day variability (%)",
            min_value=0.0,
            max_value=100.0,
            value=float(st.session_state.get("load_daily_variability_pct", 10.0)),
            step=1.0,
            help="Applies one random multiplier to each full day.",
            key="load_daily_variability_pct",
        )
    with var_col2:
        timestep_variability_pct = st.number_input(
            "Timestep variability (%)",
            min_value=0.0,
            max_value=100.0,
            value=float(st.session_state.get("load_timestep_variability_pct", 20.0)),
            step=1.0,
            help="Applies a separate random multiplier to each hourly timestep.",
            key="load_timestep_variability_pct",
        )

    seed_enabled = st.checkbox(
        "Use repeatable random seed",
        value=bool(st.session_state.get("load_random_seed_enabled", True)),
        help="Use the same seed to regenerate the same variable load profile.",
        key="load_random_seed_enabled",
    )
    random_seed = st.number_input(
        "Random seed",
        min_value=0,
        max_value=999999,
        value=int(st.session_state.get("load_random_seed", 42)),
        step=1,
        disabled=not seed_enabled,
        key="load_random_seed",
    )
    preserve_annual_energy = st.checkbox(
        "Preserve annual energy after variability",
        value=bool(st.session_state.get("load_preserve_annual_energy", True)),
        help="Rescale the variable profile back to the seasonal baseline annual energy.",
        key="load_preserve_annual_energy",
    )

    if st.button("Generate Synthetic Yearly Load"):
        try:
            weekday_profiles = _monthly_profile_table_to_profiles(weekday_table)
            weekend_profiles = _monthly_profile_table_to_profiles(weekend_table)
            generation_settings = LoadGenerationSettings(
                method="weekday_weekend_monthly",
                weekday_monthly_profiles_kw=weekday_profiles,
                weekend_monthly_profiles_kw=weekend_profiles,
                daily_variability_pct=float(daily_variability_pct),
                timestep_variability_pct=float(timestep_variability_pct),
                random_seed=int(random_seed) if seed_enabled else None,
                preserve_annual_energy=bool(preserve_annual_energy),
            )

            load_df = create_weekday_weekend_monthly_profile_load(
                weekday_monthly_profiles_kw=weekday_profiles,
                weekend_monthly_profiles_kw=weekend_profiles,
                year=int(synthetic_year),
                daily_variability_pct=float(daily_variability_pct),
                timestep_variability_pct=float(timestep_variability_pct),
                random_seed=int(random_seed) if seed_enabled else None,
                preserve_annual_energy=bool(preserve_annual_energy),
            )
            save_load_generation_settings(generation_settings, folder)
            st.session_state.current_load_df = load_df
            st.success("Synthetic yearly load generated and settings saved successfully.")
        except Exception as e:
            st.session_state.current_load_df = None
            st.error(f"Could not generate synthetic load: {e}")

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
