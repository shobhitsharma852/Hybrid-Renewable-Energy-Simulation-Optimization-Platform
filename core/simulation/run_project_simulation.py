from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from core.components.config import load_components
from core.load import load_saved_load, resample_load_to_timestep, scale_load_to_annual_energy
from core.optimization.design_point import DesignPoint
from core.project import load_project
from core.controller.config import DEFAULT_DISPATCH_STRATEGY
from core.resources import resample_resources_to_timestep, validate_resources_dataframe
from core.simulation import HybridSystemSimulator, SimulationInputs
from core.simulation.energy_balance import validate_energy_balance


def _get_project_dir(project_name: str) -> Path:
    project_dir = Path("projects") / project_name
    if not project_dir.exists():
        raise FileNotFoundError(f"Project folder not found: {project_dir}")
    return project_dir


def _ensure_outputs_dir(project_name: str) -> Path:
    project_dir = _get_project_dir(project_name)
    outputs_dir = project_dir / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    return outputs_dir


def _project_dispatch_strategy(project) -> str:
    return getattr(project, "dispatch_strategy", DEFAULT_DISPATCH_STRATEGY)


def _build_default_design_point(components) -> DesignPoint:
    """
    Temporary fallback behavior for single simulation mode.
    """
    pv_capacity_kw = (
        max(components.pv.capacity_kw_options)
        if getattr(components.pv, "capacity_kw_options", None)
        else 0.0
    )

    wind_quantity = (
        max(components.wind.quantity_options)
        if getattr(components.wind, "quantity_options", None)
        else 0
    )

    battery_quantity = (
        max(components.battery.quantity_options)
        if getattr(components.battery, "quantity_options", None)
        else 0
    )

    converter_capacity_kw = (
        max(components.converter.capacity_kw_options)
        if getattr(components.converter, "capacity_kw_options", None)
        else 0.0
    )

    return DesignPoint(
        pv_capacity_kw=max(0.0, float(pv_capacity_kw)),
        wind_quantity=max(0, int(wind_quantity)),
        battery_quantity=max(0, int(battery_quantity)),
        converter_capacity_kw=max(0.0, float(converter_capacity_kw)),
    )


def _validate_matching_timestamps(
    load_df: pd.DataFrame,
    resource_df: pd.DataFrame,
) -> None:
    if "timestamp" not in load_df.columns or "timestamp" not in resource_df.columns:
        return

    if len(load_df) != len(resource_df):
        raise ValueError(
            "Load and resource data must have the same number of timesteps after resampling"
        )

    load_timestamps = pd.to_datetime(load_df["timestamp"]).reset_index(drop=True)
    resource_timestamps = pd.to_datetime(resource_df["timestamp"]).reset_index(drop=True)

    load_diffs = load_timestamps.diff().dropna()
    resource_diffs = resource_timestamps.diff().dropna()

    if not load_diffs.equals(resource_diffs):
        raise ValueError(
            "Load and resource timestep spacing does not match after resampling; "
            "simulation requires aligned timesteps"
        )

    load_structure = load_timestamps.dt.strftime("%m-%d %H:%M:%S")
    resource_structure = resource_timestamps.dt.strftime("%m-%d %H:%M:%S")

    if not load_structure.equals(resource_structure):
        raise ValueError(
            "Load and resource timestamps are not structurally aligned after resampling; "
            "simulation requires the same timestep sequence"
        )


def load_project_simulation_inputs(
    project_name: str,
    design: DesignPoint | None = None,
) -> SimulationInputs:
    """
    Load one project's simulation inputs from:

    projects/<project_name>/
        components.json
        inputs/
            load.csv
            resources.csv
    """
    project_dir = _get_project_dir(project_name)
    inputs_dir = project_dir / "inputs"

    project = load_project(project_dir)
    time_step_minutes = int(project.simulation_time_step_minutes)
    time_step_hours = time_step_minutes / 60.0

    components = load_components(project_dir)
    load_df = load_saved_load(project_dir)

    resource_path = inputs_dir / "resources.csv"
    if not resource_path.exists():
        raise FileNotFoundError(f"resources.csv not found at: {resource_path}")

    resource_df = pd.read_csv(resource_path)
    resource_df["timestamp"] = pd.to_datetime(resource_df["timestamp"])
    resource_df = validate_resources_dataframe(resource_df)

    # Resample both datasets to the project's chosen time resolution
    if time_step_minutes != 60:
        load_df = resample_load_to_timestep(load_df, time_step_minutes)
        resource_df = resample_resources_to_timestep(resource_df, time_step_minutes)

    if project.load.scaled_annual_energy_kwh is not None:
        load_df = scale_load_to_annual_energy(
            load_df,
            target_annual_energy_kwh=float(project.load.scaled_annual_energy_kwh),
        )

    _validate_matching_timestamps(load_df, resource_df)

    selected_design = design if design is not None else _build_default_design_point(components)

    return SimulationInputs(
        load_df=load_df,
        resource_df=resource_df,
        components=components,
        design=selected_design,
        time_step_hours=time_step_hours,
        dispatch_strategy=_project_dispatch_strategy(project),
    )


def save_simulation_outputs(
    project_name: str,
    results,
) -> tuple[Path, Path]:
    outputs_dir = _ensure_outputs_dir(project_name)

    hourly_path = outputs_dir / "simulation_hourly.csv"
    summary_path = outputs_dir / "simulation_summary.json"

    hourly_df = results.to_dataframe()
    hourly_df.to_csv(hourly_path, index=False)

    summary_dict = asdict(results.summary)
    balance_result, _ = validate_energy_balance(hourly_df)
    summary_dict["energy_balance"] = asdict(balance_result)

    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary_dict, f, indent=4)

    return hourly_path, summary_path


def run_project_simulation(
    project_name: str,
    save_outputs: bool = True,
    design: DesignPoint | None = None,
):
    inputs = load_project_simulation_inputs(project_name=project_name, design=design)

    simulator = HybridSystemSimulator(inputs)
    results = simulator.run()

    if save_outputs:
        save_simulation_outputs(project_name, results)

    return results
