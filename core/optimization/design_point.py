from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DesignPoint:
    pv_capacity_kw: float # it is a float because HOMER Pro allows fractional PV capacity, e.g., 0.5 kW
    wind_quantity: int # it is an int because HOMER Pro only allows whole wind turbines
    battery_quantity: int # it is an int because HOMER Pro only allows whole batteries
    converter_capacity_kw: float # it is a float because HOMER Pro allows fractional converter capacity, e.g., 0.5 kW