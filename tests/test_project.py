import tempfile
from pathlib import Path
import pytest

from core.project import (
    Project,
    ProjectMeta,
    ProjectLocation,
    ProjectEconomics,
    save_project,
    load_project,
)


def test_save_load_roundtrip():
    p = Project(
        meta=ProjectMeta(name="Demo", author="Shobhit", description="Test"),
        location=ProjectLocation(lat=25.2812, lon=71.0524, timezone="Asia/Kolkata"),
        economics=ProjectEconomics(
            discount_rate=8.0,
            inflation_rate=2.0,
            project_lifetime_years=25,
            annual_capacity_shortage=0.0,
        ),
    )

    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / "proj1"
        save_project(p, folder)
        p2 = load_project(folder)

    assert p2.meta.name == "Demo"
    assert p2.meta.author == "Shobhit"
    assert p2.location.timezone == "Asia/Kolkata"
    assert abs(p2.location.lat - 25.2812) < 1e-9
    assert abs(p2.location.lon - 71.0524) < 1e-9
    assert p2.economics.discount_rate == 8.0
    assert p2.economics.project_lifetime_years == 25


def test_invalid_lat_raises():
    p = Project(
        meta=ProjectMeta(name="Bad"),
        location=ProjectLocation(lat=120.0, lon=71.0, timezone="Asia/Kolkata"),
        economics=ProjectEconomics(),
    )

    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(ValueError):
            save_project(p, Path(tmp) / "x")


def test_invalid_lon_raises():
    p = Project(
        meta=ProjectMeta(name="Bad"),
        location=ProjectLocation(lat=25.0, lon=200.0, timezone="Asia/Kolkata"),
        economics=ProjectEconomics(),
    )

    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(ValueError):
            save_project(p, Path(tmp) / "x")


def test_empty_project_name_raises():
    p = Project(
        meta=ProjectMeta(name=""),
        location=ProjectLocation(lat=25.0, lon=71.0, timezone="Asia/Kolkata"),
        economics=ProjectEconomics(),
    )

    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(ValueError):
            save_project(p, Path(tmp) / "x")


def test_negative_discount_rate_raises():
    p = Project(
        meta=ProjectMeta(name="BadRate"),
        location=ProjectLocation(lat=25.0, lon=71.0, timezone="Asia/Kolkata"),
        economics=ProjectEconomics(discount_rate=-1.0),
    )

    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(ValueError):
            save_project(p, Path(tmp) / "x")


def test_empty_timezone_raises():
    p = Project(
        meta=ProjectMeta(name="BadTZ"),
        location=ProjectLocation(lat=25.0, lon=71.0, timezone=""),
        economics=ProjectEconomics(),
    )

    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(ValueError):
            save_project(p, Path(tmp) / "x")