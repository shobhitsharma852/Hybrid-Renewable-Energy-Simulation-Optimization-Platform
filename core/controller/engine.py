from __future__ import annotations

from typing import Any

from .config import DEFAULT_DISPATCH_STRATEGY, validate_dispatch_strategy


def run_controller_step(
    *,
    load_kw: float,
    pv_kw: float,
    wind_kw: float,
    current_battery_soc_pct: float,
    battery_config: Any,
    converter_config: Any,
    grid_config: Any,
    selected_battery_quantity: int,
    selected_converter_capacity_kw: float,
    time_step_hours: float = 1.0,
    dispatch_strategy: str = DEFAULT_DISPATCH_STRATEGY,
) -> Any:
    strategy = validate_dispatch_strategy(dispatch_strategy)

    if strategy == "renewable_first":
        from .renewable_first import run_renewable_first_step

        return run_renewable_first_step(
            load_kw=load_kw,
            pv_kw=pv_kw,
            wind_kw=wind_kw,
            current_battery_soc_pct=current_battery_soc_pct,
            battery_config=battery_config,
            converter_config=converter_config,
            grid_config=grid_config,
            selected_battery_quantity=selected_battery_quantity,
            selected_converter_capacity_kw=selected_converter_capacity_kw,
            time_step_hours=time_step_hours,
        )

    raise ValueError(f"Unsupported dispatch_strategy: {dispatch_strategy}")
