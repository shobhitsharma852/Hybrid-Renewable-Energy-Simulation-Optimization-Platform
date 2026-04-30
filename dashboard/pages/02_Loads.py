import streamlit as st
import pandas as pd

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


def _show_load_output(df: pd.DataFrame, ts_minutes: int = 60):
    summary = summarize_load(df)
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
            if project.load.scaled_annual_energy_kwh is not None:
                resampled_df = scale_load_to_annual_energy(
                    resampled_df,
                    float(project.load.scaled_annual_energy_kwh),
                )
            rs_summary = summarize_load(resampled_df)

            r1, r2, r3, r4 = st.columns(4)
            r1.metric("Resampled Rows", f"{rs_summary.rows:,}")
            r2.metric("Peak Load (kW)", f"{rs_summary.peak_kw:.2f}")
            r3.metric("Average Load (kW)", f"{rs_summary.average_kw:.2f}")
            r4.metric("Annual Energy (kWh)", f"{rs_summary.annual_energy_kwh:,.0f}")

            st.caption(f"First {steps_per_day} rows = first 24 hours at {ts_minutes}-min resolution")
            st.dataframe(resampled_df.head(steps_per_day), use_container_width=True)

            st.subheader(f"First Day Chart — {ts_minutes} min steps")
            first_day = resampled_df.head(steps_per_day).copy().reset_index(drop=True)
            st.line_chart(first_day.set_index("timestamp")[["load_kw"]], use_container_width=True)
        except Exception as e:
            st.warning(f"Could not resample for preview: {e}")
    else:
        preview_df = df.copy()
        if project.load.scaled_annual_energy_kwh is not None:
            preview_df = scale_load_to_annual_energy(
                preview_df,
                float(project.load.scaled_annual_energy_kwh),
            )
        st.subheader("Daily Load Charts (First 24 Hours)")
        first_day = preview_df.head(24).copy()
        first_day["hour"] = range(24)
        chart_df = first_day.set_index("hour")[["load_kw"]]

        col1, col2 = st.columns(2)
        with col1:
            st.caption("Line Chart")
            st.line_chart(chart_df, use_container_width=True)
        with col2:
            st.caption("Bar Chart")
            st.bar_chart(chart_df, use_container_width=True)

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
            "Copy weekday changes to weekend",
            value=False,
            help="Keep the weekend table matched to the weekday table after edits.",
            key="monthly_profile_copy_to_weekend",
        )

    if st.button("Copy Weekdays to Weekends"):
        st.session_state.weekend_monthly_profile_table = (
            st.session_state.weekday_monthly_profile_table.copy()
        )
        st.rerun()

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
            disabled=["Hour"],
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
