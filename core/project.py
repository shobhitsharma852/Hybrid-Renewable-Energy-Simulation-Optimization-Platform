from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict
import json

from core.controller.config import DEFAULT_DISPATCH_STRATEGY, validate_dispatch_strategy


@dataclass(frozen=True)
class ProjectMeta:
    name: str
    author: str = ""
    description: str = ""


@dataclass(frozen=True)
class ProjectLocation:
    lat: float
    lon: float
    timezone: str = "UTC"


@dataclass(frozen=True)
class ProjectEconomics:
    discount_rate: float = 8.0
    inflation_rate: float = 2.0
    project_lifetime_years: int = 25
    annual_capacity_shortage: float = 0.0


@dataclass(frozen=True)
class ProjectLoadSettings:
    scaled_annual_energy_kwh: float | None = None


@dataclass(frozen=True)
class Project:
    meta: ProjectMeta
    location: ProjectLocation
    economics: ProjectEconomics
    load: ProjectLoadSettings = ProjectLoadSettings()
    version: str = "1.0"
    simulation_time_step_minutes: int = 60
    dispatch_strategy: str = DEFAULT_DISPATCH_STRATEGY


def validate_project(project: Project) -> None:
    if not project.meta.name.strip():
        raise ValueError("Project name cannot be empty")

    if not (-90.0 <= project.location.lat <= 90.0):
        raise ValueError("Latitude must be between -90 and 90")

    if not (-180.0 <= project.location.lon <= 180.0):
        raise ValueError("Longitude must be between -180 and 180")

    tz = project.location.timezone.strip()
    if not tz:
        raise ValueError("Timezone cannot be empty")

    if project.economics.project_lifetime_years <= 0:
        raise ValueError("Project lifetime must be > 0 years")

    if project.economics.discount_rate < 0:
        raise ValueError("Discount rate must be >= 0")

    if project.economics.inflation_rate < 0:
        raise ValueError("Inflation rate must be >= 0")

    if project.economics.annual_capacity_shortage < 0:
        raise ValueError("Annual capacity shortage must be >= 0")

    if (
        project.load.scaled_annual_energy_kwh is not None
        and project.load.scaled_annual_energy_kwh <= 0
    ):
        raise ValueError("scaled_annual_energy_kwh must be > 0 when provided")

    if project.simulation_time_step_minutes <= 0:
        raise ValueError("simulation_time_step_minutes must be > 0")

    validate_dispatch_strategy(project.dispatch_strategy)


def project_to_dict(project: Project) -> Dict[str, Any]:
    validate_project(project)
    return asdict(project)


def project_from_dict(data: Dict[str, Any]) -> Project:
    meta = ProjectMeta(**data["meta"])
    location = ProjectLocation(**data["location"])
    economics = ProjectEconomics(**data["economics"])
    load = ProjectLoadSettings(**data.get("load", {}))
    project = Project(
        meta=meta,
        location=location,
        economics=economics,
        load=load,
        version=data.get("version", "1.0"),
        simulation_time_step_minutes=int(data.get("simulation_time_step_minutes", 60)),
        dispatch_strategy=str(data.get("dispatch_strategy", DEFAULT_DISPATCH_STRATEGY)),
    )
    validate_project(project)
    return project


def slugify_project_name(name: str) -> str:
    clean = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in name.strip())
    return clean or "untitled_project"


def project_file_path(folder: str | Path) -> Path:
    return Path(folder) / "project.json"


def save_project(project: Project, folder: str | Path) -> Path:
    validate_project(project)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = project_file_path(folder)
    path.write_text(json.dumps(project_to_dict(project), indent=2), encoding="utf-8")
    return path


def load_project(folder: str | Path) -> Project:
    path = project_file_path(folder)
    if not path.exists():
        raise FileNotFoundError(f"project.json not found in: {Path(folder)}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return project_from_dict(data)
