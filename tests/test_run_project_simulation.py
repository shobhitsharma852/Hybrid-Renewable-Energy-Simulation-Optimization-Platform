from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from core.simulation.run_project_simulation import (
    load_project_simulation_inputs,
    run_project_simulation,
    save_simulation_outputs,
)


def test_load_project_simulation_inputs() -> None:
    inputs = load_project_simulation_inputs("Hybrid")

    assert inputs is not None
    assert inputs.load_df is not None
    assert inputs.resource_df is not None
    assert inputs.components is not None

    assert isinstance(inputs.load_df, pd.DataFrame)
    assert isinstance(inputs.resource_df, pd.DataFrame)

    assert len(inputs.load_df) > 0
    assert len(inputs.resource_df) > 0


def test_run_project_simulation_returns_results() -> None:
    results = run_project_simulation(
        project_name="Hybrid",
        save_outputs=False,
    )

    hourly_df = results.to_dataframe()

    assert results is not None
    assert hourly_df is not None
    assert len(hourly_df) > 0

    expected_columns = {
        "hour_index",
        "load_kw",
        "pv_kw",
        "wind_kw",
        "renewable_kw",
        "served_load_kw",
        "excess_energy_kw",
        "unmet_load_kw",
        "battery_charge_kw",
        "battery_discharge_kw",
        "battery_discharge_dc_kw",
        "battery_soc_pct",
        "grid_import_kw",
        "grid_export_kw",
        "inverter_loss_kw",
        "rectifier_loss_kw",
    }

    assert expected_columns.issubset(set(hourly_df.columns))


def test_save_simulation_outputs_creates_files() -> None:
    project_name = "Hybrid"

    results = run_project_simulation(
        project_name=project_name,
        save_outputs=False,
    )

    hourly_path, summary_path = save_simulation_outputs(
        project_name=project_name,
        results=results,
    )

    assert hourly_path.exists()
    assert summary_path.exists()

    saved_hourly_df = pd.read_csv(hourly_path)
    assert len(saved_hourly_df) > 0

    with open(summary_path, "r", encoding="utf-8") as f:
        summary_data = json.load(f)

    assert isinstance(summary_data, dict)
    assert "total_load_kwh" in summary_data
    assert "renewable_fraction" in summary_data


def test_run_project_simulation_with_save_outputs_creates_files() -> None:
    project_name = "Hybrid"

    results = run_project_simulation(
        project_name=project_name,
        save_outputs=True,
    )

    assert results is not None

    outputs_dir = Path("projects") / project_name / "outputs"
    hourly_path = outputs_dir / "simulation_hourly.csv"
    summary_path = outputs_dir / "simulation_summary.json"

    assert hourly_path.exists()
    assert summary_path.exists()