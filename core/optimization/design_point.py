from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DesignPoint:
    pv_capacity_kw: float
    wind_quantity: int
    battery_quantity: int
    converter_capacity_kw: float