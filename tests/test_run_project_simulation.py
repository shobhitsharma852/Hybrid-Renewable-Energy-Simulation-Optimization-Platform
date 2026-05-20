from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from core.controller.config import DEFAULT_DISPATCH_STRATEGY
from core.components.battery import BatteryComponentConfig
from core.components.config import ComponentsConfig, save_components
from core.components.converter import ConverterComponentConfig
from core.components.grid import GridComponentConfig
from core.components.pv import PVComponentConfig
from core.components.wind import WindComponentConfig
from core.load import save_load
from core.project import (
    Project,
    ProjectEconomics,
    ProjectLocation,
    ProjectMeta,
    save_project,
)
from core.resources import save_resources
from core.simulation.energy_balance import validate_energy_balance
from core.simulation.run_project_simulation import (
    load_project_simulation_inputs,
    _project_dispatch_strategy,
    run_project_simulation,
    save_simulation_outputs,
)


def _make_test_root() -> Path:
    root = Path("test_runtime") / f"run_project_{uuid.uuid4().hex}"
    root.mkdir(parents=True, exist_ok=False)
    return root


def _write_runnable_project(project_root: Path, project_name: str = "runnable_project") -> Path:
    project_dir = project_root / "projects" / project_name

    save_project(
        Project(
            meta=ProjectMeta(name=project_name),
            location=ProjectLocation(lat=21.1, lon=70.3, timezone="Asia/Kolkata"),
            economics=ProjectEconomics(),
        ),
        project_dir,
    )

    save_components(
        ComponentsConfig(
            pv=PVComponentConfig(enabled=True, capacity_kw_options=[50.0]),
            wind=WindComponentConfig(enabled=False),
            battery=BatteryComponentConfig(enabled=False),
            converter=ConverterComponentConfig(enabled=True, capacity_kw_options=[50.0]),
            grid=GridComponentConfig(enabled=True),
        ),
        project_dir,
    )

    timestamps = pd.date_range("2025-01-01 00:00:00", periods=4, freq="h")
    save_load(
        pd.DataFrame({"timestamp": timestamps, "load_kw": [100.0, 120.0, 80.0, 90.0]}),
        project_dir,
    )
    save_resources(
        pd.DataFrame(
            {
                "timestamp": timestamps,
                "ghi": [0.0, 300.0, 700.0, 100.0],
                "ws50m": [4.0, 5.0, 6.0, 4.5],
                "temperature": [24.0, 26.0, 31.0, 27.0],
            }
        ),
        project_dir,
    )

    return project_dir


def _with_cwd(path: Path, func):
    original_cwd = Path.cwd()
    try:
        os.chdir(path)
        return func()
    finally:
        os.chdir(original_cwd)


def test_project_dispatch_strategy_defaults_for_legacy_project_object() -> None:
    legacy_project = SimpleNamespace()

    assert _project_dispatch_strategy(legacy_project) == DEFAULT_DISPATCH_STRATEGY


def test_load_project_simulation_inputs() -> None:
    project_name = "runnable_project"
    project_root = _make_test_root()
    _write_runnable_project(project_root, project_name)

    inputs = _with_cwd(
        project_root,
        lambda: load_project_simulation_inputs(project_name),
    )

    assert inputs is not None
    assert inputs.load_df is not None
    assert inputs.resource_df is not None
    assert inputs.components is not None

    assert isinstance(inputs.load_df, pd.DataFrame)
    assert isinstance(inputs.resource_df, pd.DataFrame)

    assert len(inputs.load_df) > 0
    assert len(inputs.resource_df) > 0


def test_run_project_simulation_returns_results() -> None:
    project_name = "runnable_project"
    project_root = _make_test_root()
    _write_runnable_project(project_root, project_name)

    results = _with_cwd(
        project_root,
        lambda: run_project_simulation(
            project_name=project_name,
            save_outputs=False,
        ),
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


def test_run_project_simulation_passes_energy_balance() -> None:
    project_name = "runnable_project"
    project_root = _make_test_root()
    _write_runnable_project(project_root, project_name)

    results = _with_cwd(
        project_root,
        lambda: run_project_simulation(
            project_name=project_name,
            save_outputs=False,
        ),
    )

    check_result, _ = validate_energy_balance(results.to_dataframe())

    assert check_result.failed_rows == 0
    assert check_result.max_abs_mismatch_kw <= check_result.tolerance_kw


def test_save_simulation_outputs_creates_files() -> None:
    project_name = "runnable_project"
    project_root = _make_test_root()
    _write_runnable_project(project_root, project_name)

    results = _with_cwd(
        project_root,
        lambda: run_project_simulation(
            project_name=project_name,
            save_outputs=False,
        ),
    )

    hourly_path, summary_path = _with_cwd(
        project_root,
        lambda: save_simulation_outputs(
            project_name=project_name,
            results=results,
        ),
    )
    hourly_path = project_root / hourly_path
    summary_path = project_root / summary_path

    assert hourly_path.exists()
    assert summary_path.exists()

    saved_hourly_df = pd.read_csv(hourly_path)
    assert len(saved_hourly_df) > 0

    with open(summary_path, "r", encoding="utf-8") as f:
        summary_data = json.load(f)

    assert isinstance(summary_data, dict)
    assert "total_load_kwh" in summary_data
    assert "renewable_fraction" in summary_data
    assert "annual_capacity_shortage_pct" in summary_data
    assert "final_battery_soc_pct" in summary_data
    assert "energy_balance" in summary_data
    assert summary_data["energy_balance"]["failed_rows"] == 0


def test_run_project_simulation_with_save_outputs_creates_files() -> None:
    project_name = "runnable_project"
    project_root = _make_test_root()
    _write_runnable_project(project_root, project_name)

    results = _with_cwd(
        project_root,
        lambda: run_project_simulation(
            project_name=project_name,
            save_outputs=True,
        ),
    )

    assert results is not None

    outputs_dir = project_root / "projects" / project_name / "outputs"
    hourly_path = outputs_dir / "simulation_hourly.csv"
    summary_path = outputs_dir / "simulation_summary.json"

    assert hourly_path.exists()
    assert summary_path.exists()
