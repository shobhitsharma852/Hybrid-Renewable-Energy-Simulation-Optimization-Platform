from __future__ import annotations

from typing import TYPE_CHECKING, Any

# TYPE_CHECKING guard — same circular-import reason as engine.py.
# `from __future__ import annotations` makes all annotations lazy strings,
# so BatteryState is never evaluated at runtime here.
if TYPE_CHECKING:
    from core.simulation.battery_soc import BatteryState

from core.simulation.dispatch import DispatchResult, run_dispatch_step


def run_renewable_first_step(
    *,
    load_kw: float,
    pv_kw: float,
    wind_kw: float,
    # Carries all mutable battery runtime state (SOC, effective capacity, throughput, SoH).
    # Using a dataclass instead of a bare float so future battery features (capacity fade,
    # rainflow cycle counting, temperature aging) only need a new field here — no signature
    # surgery across the entire call chain.
    battery_state: BatteryState,
    battery_config: Any,
    converter_config: Any,
    grid_config: Any,
    selected_battery_quantity: int,
    selected_converter_capacity_kw: float,
    time_step_hours: float = 1.0,
) -> DispatchResult:
    return run_dispatch_step(
        load_kw=load_kw,
        pv_kw=pv_kw,
        wind_kw=wind_kw,
        battery_state=battery_state,
        battery_config=battery_config,
        converter_config=converter_config,
        grid_config=grid_config,
        selected_battery_quantity=selected_battery_quantity,
        selected_converter_capacity_kw=selected_converter_capacity_kw,
        time_step_hours=time_step_hours,
        dispatch_strategy="renewable_first",
    )
