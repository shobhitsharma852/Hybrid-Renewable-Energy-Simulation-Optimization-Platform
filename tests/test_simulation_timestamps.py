from __future__ import annotations

import os
import uuid
from pathlib import Path

import pandas as pd
import pytest

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
    ProjectLoadSettings,
    ProjectLocation,
    ProjectMeta,
    save_project,
)
from core.optimization.design_point import DesignPoint
from core.resources import save_resources
from core.simulation import HybridSystemSimulator, SimulationInputs
from core.simulation.run_project_simulation import load_project_simulation_inputs
from core.load import annual_energy_kwh


def _make_test_root(label: str) -> Path:
    root = Path("test_runtime") / f"{label}_{uuid.uuid4().hex}"
    root.mkdir(parents=True, exist_ok=False)
    return root


def _simulation_components() -> ComponentsConfig:
    return ComponentsConfig(
        pv=PVComponentConfig(enabled=False),
        wind=WindComponentConfig(enabled=False),
        battery=BatteryComponentConfig(enabled=False),
        converter=ConverterComponentConfig(),
        grid=GridComponentConfig(enabled=True),
    )


def _write_test_project(project_dir: Path) -> None:
    save_project(
        Project(
            meta=ProjectMeta(name=project_dir.name),
            location=ProjectLocation(lat=0.0, lon=0.0, timezone="UTC"),
            economics=ProjectEconomics(),
            load=ProjectLoadSettings(),
            simulation_time_step_minutes=15,
        ),
        project_dir,
    )
    save_components(_simulation_components(), project_dir)


def test_simulation_results_include_real_timestamps() -> None:
    timestamps = pd.date_range("2025-01-01 00:00:00", periods=4, freq="15min")
    inputs = SimulationInputs(
        load_df=pd.DataFrame({"timestamp": timestamps, "load_kw": [100.0] * 4}),
        resource_df=pd.DataFrame(
            {
                "timestamp": timestamps,
                "ghi": [0.0] * 4,
                "ws50m": [0.0] * 4,
                "temperature": [25.0] * 4,
            }
        ),
        components=_simulation_components(),
        design=DesignPoint(
            pv_capacity_kw=0.0,
            wind_quantity=0,
            battery_quantity=0,
            converter_capacity_kw=0.0,
        ),
        time_step_hours=0.25,
    )

    results = HybridSystemSimulator(inputs).run()
    hourly_df = results.to_dataframe()

    assert "timestamp" in hourly_df.columns
    assert list(pd.to_datetime(hourly_df["timestamp"])) == list(timestamps)


def test_simulator_fails_when_load_and_resources_have_different_lengths() -> None:
    load_timestamps = pd.date_range("2025-01-01 00:00:00", periods=4, freq="h")
    resource_timestamps = pd.date_range("2025-01-01 00:00:00", periods=3, freq="h")

    inputs = SimulationInputs(
        load_df=pd.DataFrame({"timestamp": load_timestamps, "load_kw": [100.0] * 4}),
        resource_df=pd.DataFrame(
            {
                "timestamp": resource_timestamps,
                "ghi": [0.0] * 3,
                "ws50m": [0.0] * 3,
                "temperature": [25.0] * 3,
            }
        ),
        components=_simulation_components(),
        design=DesignPoint(
            pv_capacity_kw=0.0,
            wind_quantity=0,
            battery_quantity=0,
            converter_capacity_kw=0.0,
        ),
    )

    with pytest.raises(ValueError, match="same number of timesteps"):
        HybridSystemSimulator(inputs).run()


def test_renewable_served_to_load_summary_is_populated() -> None:
    timestamps = pd.date_range("2025-01-01 00:00:00", periods=1, freq="h")
    components = ComponentsConfig(
        pv=PVComponentConfig(enabled=False),
        wind=WindComponentConfig(
            enabled=True,
            quantity_options=[1],
            power_curve=WindComponentConfig().power_curve,
        ),
        battery=BatteryComponentConfig(enabled=False),
        converter=ConverterComponentConfig(),
        grid=GridComponentConfig(enabled=True),
    )

    inputs = SimulationInputs(
        load_df=pd.DataFrame({"timestamp": timestamps, "load_kw": [100.0]}),
        resource_df=pd.DataFrame(
            {
                "timestamp": timestamps,
                "ghi": [0.0],
                "ws50m": [12.0],
                "temperature": [25.0],
            }
        ),
        components=components,
        design=DesignPoint(
            pv_capacity_kw=0.0,
            wind_quantity=1,
            battery_quantity=0,
            converter_capacity_kw=0.0,
        ),
    )

    summary = HybridSystemSimulator(inputs).run().summary

    assert summary.annual_capacity_shortage_pct == pytest.approx(0.0)
    assert summary.renewable_served_to_load_kwh == pytest.approx(
        summary.direct_renewable_to_load_kwh
        + summary.renewable_from_battery_to_load_kwh
    )
    assert summary.renewable_served_to_load_kwh > 0.0


def test_load_project_simulation_inputs_fails_for_misaligned_timestamps() -> None:
    project_name = "timestamp_mismatch_project"
    project_root = _make_test_root("timestamp_mismatch")
    project_dir = project_root / "projects" / project_name
    _write_test_project(project_dir)

    load_timestamps = pd.date_range("2025-01-01 00:00:00", periods=4, freq="h")
    resource_timestamps = pd.date_range("2025-01-01 00:30:00", periods=4, freq="h")

    save_load(
        pd.DataFrame({"timestamp": load_timestamps, "load_kw": [100.0] * 4}),
        project_dir,
    )
    save_resources(
        pd.DataFrame(
            {
                "timestamp": resource_timestamps,
                "ghi": [0.0] * 4,
                "ws50m": [0.0] * 4,
                "temperature": [25.0] * 4,
            }
        ),
        project_dir,
    )

    with pytest.raises(ValueError, match="not structurally aligned after resampling"):
        original_cwd = Path.cwd()
        try:
            # The simulation loader resolves projects relative to the current working directory.
            os.chdir(project_root)
            load_project_simulation_inputs(project_name)
        finally:
            os.chdir(original_cwd)


def test_load_project_simulation_inputs_allows_different_years_with_same_structure(
) -> None:
    project_name = "timestamp_different_year_project"
    project_root = _make_test_root("timestamp_year")
    project_dir = project_root / "projects" / project_name
    _write_test_project(project_dir)

    load_timestamps = pd.date_range("2025-01-01 00:00:00", periods=4, freq="h")
    resource_timestamps = pd.date_range("2001-01-01 00:00:00", periods=4, freq="h")

    save_load(
        pd.DataFrame({"timestamp": load_timestamps, "load_kw": [100.0] * 4}),
        project_dir,
    )
    save_resources(
        pd.DataFrame(
            {
                "timestamp": resource_timestamps,
                "ghi": [0.0] * 4,
                "ws50m": [0.0] * 4,
                "temperature": [25.0] * 4,
            }
        ),
        project_dir,
    )

    original_cwd = Path.cwd()
    try:
        os.chdir(project_root)
        inputs = load_project_simulation_inputs(project_name)
    finally:
        os.chdir(original_cwd)

    assert len(inputs.load_df) == len(inputs.resource_df) == 13


def test_load_project_simulation_inputs_applies_scaled_annual_energy() -> None:
    project_name = "scaled_load_project"
    project_root = _make_test_root("scaled_load")
    project_dir = project_root / "projects" / project_name

    save_project(
        Project(
            meta=ProjectMeta(name=project_name),
            location=ProjectLocation(lat=0.0, lon=0.0, timezone="UTC"),
            economics=ProjectEconomics(),
            load=ProjectLoadSettings(scaled_annual_energy_kwh=500.0),
            simulation_time_step_minutes=15,
        ),
        project_dir,
    )
    save_components(_simulation_components(), project_dir)

    timestamps = pd.date_range("2025-01-01 00:00:00", periods=4, freq="h")
    save_load(
        pd.DataFrame({"timestamp": timestamps, "load_kw": [100.0] * 4}),
        project_dir,
    )
    save_resources(
        pd.DataFrame(
            {
                "timestamp": pd.date_range("2001-01-01 00:00:00", periods=4, freq="h"),
                "ghi": [0.0] * 4,
                "ws50m": [0.0] * 4,
                "temperature": [25.0] * 4,
            }
        ),
        project_dir,
    )

    original_cwd = Path.cwd()
    try:
        os.chdir(project_root)
        inputs = load_project_simulation_inputs(project_name)
    finally:
        os.chdir(original_cwd)

    assert annual_energy_kwh(inputs.load_df) == pytest.approx(500.0)
