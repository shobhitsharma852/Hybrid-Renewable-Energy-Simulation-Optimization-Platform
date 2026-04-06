from __future__ import annotations

# ============================================================
# core/components/config.py
#
# Purpose:
#   Project-level grouping and save/load for all component
#   configurations.
#
# Scope of this file:
#   1. ComponentsConfig root object
#   2. Validation of full component set
#   3. Conversion to/from dictionary
#   4. Save/load helpers for components.json
#
# Why:
#   Each individual component file (pv.py, wind.py, battery.py,
#   converter.py, grid.py) defines only that component.
#   This file groups them together into one project-level object.
# ============================================================

from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Dict
import json

from core.components.pv import (
    PVMPPTSettings,
    PVOrientationSettings,
    PVTemperatureSettings,
    PVComponentConfig,
    validate_pv_component,
)
from core.components.wind import (
    WindPowerCurveSettings,
    WindLossSettings,
    WindMaintenanceSettings,
    WindComponentConfig,
    validate_wind_component,
)
from core.components.battery import (
    BatteryComponentConfig,
    validate_battery_component,
)
from core.components.converter import (
    ConverterComponentConfig,
    validate_converter_component,
)
from core.components.grid import (
    GridComponentConfig,
    validate_grid_component,
)


# ============================================================
# SECTION 1 — ROOT COMPONENTS OBJECT
# ============================================================

@dataclass(frozen=True)
class ComponentsConfig:
    """
    Full project-level component configuration.

    This groups together all major microgrid components for one project.
    """

    pv: PVComponentConfig = field(default_factory=PVComponentConfig)
    wind: WindComponentConfig = field(default_factory=WindComponentConfig)
    battery: BatteryComponentConfig = field(default_factory=BatteryComponentConfig)
    converter: ConverterComponentConfig = field(default_factory=ConverterComponentConfig)
    grid: GridComponentConfig = field(default_factory=GridComponentConfig)


# ============================================================
# SECTION 2 — PATH HELPERS
# ============================================================

def components_file_path(project_folder: str | Path) -> Path:
    """
    Return the path to components.json inside a project folder.
    """
    return Path(project_folder) / "components.json"


# ============================================================
# SECTION 3 — VALIDATION
# ============================================================

def validate_components_config(cfg: ComponentsConfig) -> None:
    """
    Validate the full project-level components configuration.
    """
    validate_pv_component(cfg.pv)
    validate_wind_component(cfg.wind)
    validate_battery_component(cfg.battery)
    validate_converter_component(cfg.converter)
    validate_grid_component(cfg.grid)


# ============================================================
# SECTION 4 — TO / FROM DICTIONARY
# ============================================================

def components_to_dict(cfg: ComponentsConfig) -> Dict[str, Any]:
    """
    Convert ComponentsConfig to a JSON-serializable dictionary.
    """
    validate_components_config(cfg)
    return asdict(cfg)


def components_from_dict(data: Dict[str, Any]) -> ComponentsConfig:
    """
    Rebuild ComponentsConfig from a dictionary loaded from JSON.
    """

    # ---------------- PV ----------------
    pv_mppt = PVMPPTSettings(**data["pv"]["mppt"])
    pv_orientation = PVOrientationSettings(**data["pv"]["orientation"])
    pv_temperature = PVTemperatureSettings(**data["pv"]["temperature"])

    pv_data = dict(data["pv"])
    pv_data["mppt"] = pv_mppt
    pv_data["orientation"] = pv_orientation
    pv_data["temperature"] = pv_temperature
    pv = PVComponentConfig(**pv_data)

    # ---------------- WIND ----------------
    wind_power_curve = WindPowerCurveSettings(**data["wind"]["power_curve"])
    wind_losses = WindLossSettings(**data["wind"]["losses"])
    wind_maintenance = WindMaintenanceSettings(**data["wind"]["maintenance"])

    wind_data = dict(data["wind"])
    wind_data["power_curve"] = wind_power_curve
    wind_data["losses"] = wind_losses
    wind_data["maintenance"] = wind_maintenance
    wind = WindComponentConfig(**wind_data)

    # ---------------- BATTERY ----------------
    battery = BatteryComponentConfig(**data["battery"])

    # ---------------- CONVERTER ----------------
    converter = ConverterComponentConfig(**data["converter"])

    # ---------------- GRID ----------------
    grid = GridComponentConfig(**data["grid"])

    cfg = ComponentsConfig(
        pv=pv,
        wind=wind,
        battery=battery,
        converter=converter,
        grid=grid,
    )

    validate_components_config(cfg)
    return cfg


# ============================================================
# SECTION 5 — SAVE / LOAD
# ============================================================

def save_components(cfg: ComponentsConfig, project_folder: str | Path) -> Path:
    """
    Save the full component configuration into components.json.
    """
    validate_components_config(cfg)

    project_folder = Path(project_folder)
    project_folder.mkdir(parents=True, exist_ok=True)

    path = components_file_path(project_folder)
    path.write_text(
        json.dumps(components_to_dict(cfg), indent=2),
        encoding="utf-8",
    )
    return path


def load_components(project_folder: str | Path) -> ComponentsConfig:
    """
    Load the full component configuration from components.json.
    """
    path = components_file_path(project_folder)

    if not path.exists():
        raise FileNotFoundError(f"components.json not found in: {Path(project_folder)}")

    data = json.loads(path.read_text(encoding="utf-8"))
    return components_from_dict(data)