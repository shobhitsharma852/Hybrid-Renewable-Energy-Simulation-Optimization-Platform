from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from core.components.config import load_components
from core.load import load_saved_load
from core.optimization.design_point import DesignPoint
from core.simulation import HybridSystemSimulator, SimulationInputs


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

    components = load_components(project_dir)
    load_df = load_saved_load(project_dir)

    resource_path = inputs_dir / "resources.csv"
    if not resource_path.exists():
        raise FileNotFoundError(f"resources.csv not found at: {resource_path}")

    resource_df = pd.read_csv(resource_path)

    selected_design = design if design is not None else _build_default_design_point(components)

    return SimulationInputs(
        load_df=load_df,
        resource_df=resource_df,
        components=components,
        design=selected_design,
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