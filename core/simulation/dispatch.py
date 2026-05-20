from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .battery_soc import update_battery_state
from .converter_model import (
    convert_ac_to_dc,
    convert_dc_to_ac,
    get_inverter_capacity_kw,
    get_inverter_efficiency,
    get_rectifier_capacity_kw,
    get_rectifier_efficiency,
)
from .grid_model import compute_grid_export, compute_grid_import, resolve_grid_limits
from core.controller.config import DEFAULT_DISPATCH_STRATEGY, validate_dispatch_strategy

EPSILON: float = 1e-9
VERY_LARGE_POWER_KW: float = 1e12


@dataclass
class DispatchResult:
    renewable_kw: float
    served_load_kw: float
    unmet_load_kw: float
    excess_energy_kw: float

    battery_charge_kw: float            # DC into battery terminals
    battery_discharge_kw: float         # AC delivered after inverter
    battery_discharge_dc_kw: float      # DC out of battery terminals
    battery_soc_pct: float

    grid_import_kw: float
    grid_export_kw: float

    # Extra visibility for reporting
    wind_to_load_kw: float
    pv_to_load_ac_kw: float

    renewable_charge_stored_kwh: float
    battery_energy_removed_kwh: float

    inverter_loss_kw: float
    rectifier_loss_kw: float


def _safe_getattr(obj: Any, name: str, default: Any) -> Any:
    return getattr(obj, name, default)


def _battery_total_capacity_kwh(
    battery_config: Any,
    selected_battery_quantity: int,
) -> float:
    nominal_capacity_kwh_per_string = float(
        _safe_getattr(battery_config, "nominal_capacity_kwh_per_string", 0.0)
    )
    quantity = max(0, int(selected_battery_quantity))
    return max(0.0, float(quantity) * nominal_capacity_kwh_per_string)


def _stored_energy_from_soc_pct(
    *,
    soc_pct: float,
    battery_config: Any,
    selected_battery_quantity: int,
) -> float:
    total_capacity_kwh = _battery_total_capacity_kwh(
        battery_config=battery_config,
        selected_battery_quantity=selected_battery_quantity,
    )
    soc_pct = max(0.0, min(100.0, float(soc_pct)))
    return total_capacity_kwh * (soc_pct / 100.0)


def _probe_max_battery_charge_kw(
    *,
    current_soc_pct: float,
    battery_config: Any,
    selected_battery_quantity: int,
    time_step_hours: float,
) -> float:
    result = update_battery_state(
        current_soc_pct=current_soc_pct,
        surplus_kw=VERY_LARGE_POWER_KW,
        deficit_kw=0.0,
        battery_enabled=bool(_safe_getattr(battery_config, "enabled", False)),
        quantity_strings=max(0, int(selected_battery_quantity)),
        nominal_capacity_kwh_per_string=float(
            _safe_getattr(battery_config, "nominal_capacity_kwh_per_string", 0.0)
        ),
        nominal_voltage_v=float(_safe_getattr(battery_config, "nominal_voltage_v", 0.0)),
        max_charge_current_a=float(
            _safe_getattr(battery_config, "max_charge_current_a", 0.0)
        ),
        max_discharge_current_a=float(
            _safe_getattr(battery_config, "max_discharge_current_a", 0.0)
        ),
        minimum_soc_pct=float(
            _safe_getattr(battery_config, "minimum_state_of_charge_pct", 0.0)
        ),
        roundtrip_efficiency_pct=float(
            _safe_getattr(battery_config, "roundtrip_efficiency_pct", 100.0)
        ),
        time_step_hours=time_step_hours,
    )
    return max(0.0, result.battery_charge_kw)


def _probe_max_battery_discharge_kw(
    *,
    current_soc_pct: float,
    battery_config: Any,
    selected_battery_quantity: int,
    time_step_hours: float,
) -> float:
    result = update_battery_state(
        current_soc_pct=current_soc_pct,
        surplus_kw=0.0,
        deficit_kw=VERY_LARGE_POWER_KW,
        battery_enabled=bool(_safe_getattr(battery_config, "enabled", False)),
        quantity_strings=max(0, int(selected_battery_quantity)),
        nominal_capacity_kwh_per_string=float(
            _safe_getattr(battery_config, "nominal_capacity_kwh_per_string", 0.0)
        ),
        nominal_voltage_v=float(_safe_getattr(battery_config, "nominal_voltage_v", 0.0)),
        max_charge_current_a=float(
            _safe_getattr(battery_config, "max_charge_current_a", 0.0)
        ),
        max_discharge_current_a=float(
            _safe_getattr(battery_config, "max_discharge_current_a", 0.0)
        ),
        minimum_soc_pct=float(
            _safe_getattr(battery_config, "minimum_state_of_charge_pct", 0.0)
        ),
        roundtrip_efficiency_pct=float(
            _safe_getattr(battery_config, "roundtrip_efficiency_pct", 100.0)
        ),
        time_step_hours=time_step_hours,
    )
    return max(0.0, result.battery_discharge_kw)


def _apply_battery_charge(
    *,
    current_soc_pct: float,
    charge_input_kw: float,
    battery_config: Any,
    selected_battery_quantity: int,
    time_step_hours: float,
) -> tuple[float, float, float]:
    """
    Returns:
        (new_soc_pct, actual_charge_input_kw_dc, stored_energy_delta_kwh)
    """
    old_stored_kwh = _stored_energy_from_soc_pct(
        soc_pct=current_soc_pct,
        battery_config=battery_config,
        selected_battery_quantity=selected_battery_quantity,
    )

    result = update_battery_state(
        current_soc_pct=current_soc_pct,
        surplus_kw=max(0.0, float(charge_input_kw)),
        deficit_kw=0.0,
        battery_enabled=bool(_safe_getattr(battery_config, "enabled", False)),
        quantity_strings=max(0, int(selected_battery_quantity)),
        nominal_capacity_kwh_per_string=float(
            _safe_getattr(battery_config, "nominal_capacity_kwh_per_string", 0.0)
        ),
        nominal_voltage_v=float(_safe_getattr(battery_config, "nominal_voltage_v", 0.0)),
        max_charge_current_a=float(
            _safe_getattr(battery_config, "max_charge_current_a", 0.0)
        ),
        max_discharge_current_a=float(
            _safe_getattr(battery_config, "max_discharge_current_a", 0.0)
        ),
        minimum_soc_pct=float(
            _safe_getattr(battery_config, "minimum_state_of_charge_pct", 0.0)
        ),
        roundtrip_efficiency_pct=float(
            _safe_getattr(battery_config, "roundtrip_efficiency_pct", 100.0)
        ),
        time_step_hours=time_step_hours,
    )

    stored_delta_kwh = max(0.0, result.stored_energy_kwh - old_stored_kwh)

    return (
        result.new_soc_pct,
        result.battery_charge_kw,
        stored_delta_kwh,
    )


def _apply_battery_discharge(
    *,
    current_soc_pct: float,
    requested_dc_output_kw: float,
    battery_config: Any,
    selected_battery_quantity: int,
    time_step_hours: float,
) -> tuple[float, float, float]:
    """
    Returns:
        (new_soc_pct, actual_dc_output_kw_from_battery, removed_energy_kwh_from_storage)
    """
    old_stored_kwh = _stored_energy_from_soc_pct(
        soc_pct=current_soc_pct,
        battery_config=battery_config,
        selected_battery_quantity=selected_battery_quantity,
    )

    result = update_battery_state(
        current_soc_pct=current_soc_pct,
        surplus_kw=0.0,
        deficit_kw=max(0.0, float(requested_dc_output_kw)),
        battery_enabled=bool(_safe_getattr(battery_config, "enabled", False)),
        quantity_strings=max(0, int(selected_battery_quantity)),
        nominal_capacity_kwh_per_string=float(
            _safe_getattr(battery_config, "nominal_capacity_kwh_per_string", 0.0)
        ),
        nominal_voltage_v=float(_safe_getattr(battery_config, "nominal_voltage_v", 0.0)),
        max_charge_current_a=float(
            _safe_getattr(battery_config, "max_charge_current_a", 0.0)
        ),
        max_discharge_current_a=float(
            _safe_getattr(battery_config, "max_discharge_current_a", 0.0)
        ),
        minimum_soc_pct=float(
            _safe_getattr(battery_config, "minimum_state_of_charge_pct", 0.0)
        ),
        roundtrip_efficiency_pct=float(
            _safe_getattr(battery_config, "roundtrip_efficiency_pct", 100.0)
        ),
        time_step_hours=time_step_hours,
    )

    removed_energy_kwh = max(0.0, old_stored_kwh - result.stored_energy_kwh)

    return (
        result.new_soc_pct,
        result.battery_discharge_kw,
        removed_energy_kwh,
    )


def run_dispatch_step(
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
) -> DispatchResult:
    """
    Bus assumptions:
    - PV -> DC bus
    - Battery -> DC bus
    - Wind -> AC bus
    - Load -> AC bus
    - Grid -> AC bus
    - Converter connects DC <-> AC

    Accounting convention:
    - pv_kw = DC PV generation
    - wind_kw = AC wind generation
    - battery_charge_kw = DC power into battery terminals
    - battery_discharge_dc_kw = DC power from battery terminals
    - battery_discharge_kw = AC delivered after inverter

    Energy balance:
        pv_kw + wind_kw + grid_import_kw + battery_discharge_dc_kw
        =
        served_load_kw + battery_charge_kw + grid_export_kw + excess_energy_kw
        + inverter_loss_kw + rectifier_loss_kw

    Important fix in this version:
    - Inverter AC capacity is shared across ALL DC->AC flows in the timestep
    - Rectifier AC-input capacity is shared across ALL AC->DC flows in the timestep
    """
    dispatch_strategy = validate_dispatch_strategy(dispatch_strategy)

    load_kw = max(0.0, float(load_kw))
    pv_kw = max(0.0, float(pv_kw))
    wind_kw = max(0.0, float(wind_kw))
    time_step_hours = max(EPSILON, float(time_step_hours))
    selected_battery_quantity = max(0, int(selected_battery_quantity))
    selected_converter_capacity_kw = max(0.0, float(selected_converter_capacity_kw))

    battery_soc_pct = max(0.0, min(100.0, float(current_battery_soc_pct)))

    battery_enabled = bool(_safe_getattr(battery_config, "enabled", False)) and selected_battery_quantity > 0
    grid_limits = resolve_grid_limits(grid_config)

    # Shared converter budgets for THIS timestep
    remaining_inverter_ac_capacity_kw = get_inverter_capacity_kw(
        converter_config=converter_config,
        selected_capacity_kw=selected_converter_capacity_kw,
    )
    remaining_rectifier_ac_capacity_kw = get_rectifier_capacity_kw(
        converter_config=converter_config,
        selected_inverter_capacity_kw=selected_converter_capacity_kw,
    )

    inverter_loss_kw = 0.0
    rectifier_loss_kw = 0.0

    battery_charge_kw = 0.0
    battery_discharge_kw = 0.0
    battery_discharge_dc_kw = 0.0

    grid_import_kw = 0.0
    grid_export_kw = 0.0

    wind_to_load_kw = 0.0
    pv_to_load_ac_kw = 0.0

    renewable_charge_stored_kwh = 0.0
    battery_energy_removed_kwh = 0.0

    renewable_kw = pv_kw + wind_kw

    remaining_load_kw = load_kw
    remaining_pv_dc_kw = pv_kw
    remaining_wind_ac_kw = wind_kw

    # 1. WIND -> LOAD (AC direct)
    wind_to_load_kw = min(remaining_wind_ac_kw, remaining_load_kw)
    remaining_wind_ac_kw -= wind_to_load_kw
    remaining_load_kw -= wind_to_load_kw

    # 2. PV -> LOAD (DC via SHARED inverter capacity)
    if (
        remaining_load_kw > EPSILON
        and remaining_pv_dc_kw > EPSILON
        and remaining_inverter_ac_capacity_kw > EPSILON
    ):
        inverter_eff = get_inverter_efficiency(converter_config)
        if inverter_eff > EPSILON:
            max_ac_for_pv_to_load_kw = min(
                remaining_load_kw,
                remaining_inverter_ac_capacity_kw,
            )
            requested_dc_for_load_kw = min(
                remaining_pv_dc_kw,
                max_ac_for_pv_to_load_kw / inverter_eff,
            )

            inv_result = convert_dc_to_ac(
                requested_dc_power_kw=requested_dc_for_load_kw,
                converter_config=converter_config,
                selected_inverter_capacity_kw=remaining_inverter_ac_capacity_kw,
            )

            pv_to_load_ac_kw = min(inv_result.output_power_kw, max_ac_for_pv_to_load_kw)
            remaining_load_kw -= pv_to_load_ac_kw
            remaining_pv_dc_kw -= inv_result.input_power_kw
            inverter_loss_kw += inv_result.loss_kw
            remaining_inverter_ac_capacity_kw = max(
                0.0,
                remaining_inverter_ac_capacity_kw - inv_result.output_power_kw,
            )

    # 3. PV SURPLUS -> BATTERY (DC direct, no converter usage)
    if battery_enabled and remaining_pv_dc_kw > EPSILON:
        new_soc_pct, actual_charge_dc_kw, stored_delta_kwh = _apply_battery_charge(
            current_soc_pct=battery_soc_pct,
            charge_input_kw=remaining_pv_dc_kw,
            battery_config=battery_config,
            selected_battery_quantity=selected_battery_quantity,
            time_step_hours=time_step_hours,
        )

        battery_soc_pct = new_soc_pct
        battery_charge_kw += actual_charge_dc_kw
        renewable_charge_stored_kwh += stored_delta_kwh
        remaining_pv_dc_kw -= actual_charge_dc_kw

    # 4. WIND SURPLUS -> BATTERY (AC via SHARED rectifier capacity)
    if (
        battery_enabled
        and remaining_wind_ac_kw > EPSILON
        and remaining_rectifier_ac_capacity_kw > EPSILON
    ):
        max_battery_charge_dc_kw = _probe_max_battery_charge_kw(
            current_soc_pct=battery_soc_pct,
            battery_config=battery_config,
            selected_battery_quantity=selected_battery_quantity,
            time_step_hours=time_step_hours,
        )

        rectifier_eff = get_rectifier_efficiency(converter_config)
        if max_battery_charge_dc_kw > EPSILON and rectifier_eff > EPSILON:
            requested_ac_for_rectifier_kw = min(
                remaining_wind_ac_kw,
                max_battery_charge_dc_kw / rectifier_eff,
                remaining_rectifier_ac_capacity_kw,
            )

            rect_result = convert_ac_to_dc(
                requested_ac_power_kw=requested_ac_for_rectifier_kw,
                converter_config=converter_config,
                selected_inverter_capacity_kw=selected_converter_capacity_kw,
            )

            new_soc_pct, actual_charge_dc_kw, stored_delta_kwh = _apply_battery_charge(
                current_soc_pct=battery_soc_pct,
                charge_input_kw=rect_result.output_power_kw,
                battery_config=battery_config,
                selected_battery_quantity=selected_battery_quantity,
                time_step_hours=time_step_hours,
            )

            battery_soc_pct = new_soc_pct
            battery_charge_kw += actual_charge_dc_kw
            renewable_charge_stored_kwh += stored_delta_kwh
            remaining_wind_ac_kw -= rect_result.input_power_kw
            rectifier_loss_kw += rect_result.loss_kw
            remaining_rectifier_ac_capacity_kw = max(
                0.0,
                remaining_rectifier_ac_capacity_kw - rect_result.input_power_kw,
            )

    # 5. BATTERY -> LOAD (DC via SHARED inverter capacity)
    if (
        battery_enabled
        and remaining_load_kw > EPSILON
        and remaining_inverter_ac_capacity_kw > EPSILON
    ):
        max_battery_dc_output_kw = _probe_max_battery_discharge_kw(
            current_soc_pct=battery_soc_pct,
            battery_config=battery_config,
            selected_battery_quantity=selected_battery_quantity,
            time_step_hours=time_step_hours,
        )

        inverter_eff = get_inverter_efficiency(converter_config)
        if max_battery_dc_output_kw > EPSILON and inverter_eff > EPSILON:
            max_ac_for_battery_to_load_kw = min(
                remaining_load_kw,
                remaining_inverter_ac_capacity_kw,
            )
            requested_dc_from_battery_kw = min(
                max_battery_dc_output_kw,
                max_ac_for_battery_to_load_kw / inverter_eff,
            )

            inv_probe = convert_dc_to_ac(
                requested_dc_power_kw=requested_dc_from_battery_kw,
                converter_config=converter_config,
                selected_inverter_capacity_kw=remaining_inverter_ac_capacity_kw,
            )

            actual_dc_accepted_by_inverter_kw = inv_probe.input_power_kw

            if actual_dc_accepted_by_inverter_kw > EPSILON:
                (
                    new_soc_pct,
                    actual_battery_dc_output_kw,
                    removed_energy_kwh,
                ) = _apply_battery_discharge(
                    current_soc_pct=battery_soc_pct,
                    requested_dc_output_kw=actual_dc_accepted_by_inverter_kw,
                    battery_config=battery_config,
                    selected_battery_quantity=selected_battery_quantity,
                    time_step_hours=time_step_hours,
                )

                battery_soc_pct = new_soc_pct
                battery_energy_removed_kwh += removed_energy_kwh
                battery_discharge_dc_kw += actual_battery_dc_output_kw

                inv_result = convert_dc_to_ac(
                    requested_dc_power_kw=actual_battery_dc_output_kw,
                    converter_config=converter_config,
                    selected_inverter_capacity_kw=remaining_inverter_ac_capacity_kw,
                )

                battery_discharge_kw += inv_result.output_power_kw
                remaining_load_kw -= inv_result.output_power_kw
                inverter_loss_kw += inv_result.loss_kw
                remaining_inverter_ac_capacity_kw = max(
                    0.0,
                    remaining_inverter_ac_capacity_kw - inv_result.output_power_kw,
                )

    # 6. REMAINING PV SURPLUS -> GRID EXPORT OR EXCESS (through remaining inverter only)
    pv_surplus_ac_equivalent_kw = 0.0
    pv_curtailed_dc_kw = 0.0

    if remaining_pv_dc_kw > EPSILON:
        pv_export_result = convert_dc_to_ac(
            requested_dc_power_kw=remaining_pv_dc_kw,
            converter_config=converter_config,
            selected_inverter_capacity_kw=remaining_inverter_ac_capacity_kw,
        )
        pv_surplus_ac_equivalent_kw = pv_export_result.output_power_kw
        inverter_loss_kw += pv_export_result.loss_kw
        pv_curtailed_dc_kw = pv_export_result.clipped_power_kw
        remaining_pv_dc_kw -= pv_export_result.input_power_kw
        remaining_pv_dc_kw = max(0.0, remaining_pv_dc_kw)
        remaining_inverter_ac_capacity_kw = max(
            0.0,
            remaining_inverter_ac_capacity_kw - pv_export_result.output_power_kw,
        )

    available_export_ac_kw = remaining_wind_ac_kw + pv_surplus_ac_equivalent_kw

    export_result = compute_grid_export(
        available_surplus_ac_kw=available_export_ac_kw,
        pv_curtailed_dc_kw=pv_curtailed_dc_kw,
        limits=grid_limits,
    )
    grid_export_kw = export_result.grid_export_kw
    excess_energy_kw = export_result.excess_energy_kw

    # 7. GRID IMPORT
    import_result = compute_grid_import(
        remaining_load_kw=remaining_load_kw,
        limits=grid_limits,
    )
    grid_import_kw = import_result.grid_import_kw

    unmet_load_kw = max(0.0, import_result.remaining_unmet_load_kw)
    served_load_kw = max(0.0, load_kw - unmet_load_kw)

    return DispatchResult(
        renewable_kw=renewable_kw,
        served_load_kw=served_load_kw,
        unmet_load_kw=unmet_load_kw,
        excess_energy_kw=excess_energy_kw,
        battery_charge_kw=battery_charge_kw,
        battery_discharge_kw=battery_discharge_kw,
        battery_discharge_dc_kw=battery_discharge_dc_kw,
        battery_soc_pct=battery_soc_pct,
        grid_import_kw=grid_import_kw,
        grid_export_kw=grid_export_kw,
        wind_to_load_kw=wind_to_load_kw,
        pv_to_load_ac_kw=pv_to_load_ac_kw,
        renewable_charge_stored_kwh=renewable_charge_stored_kwh,
        battery_energy_removed_kwh=battery_energy_removed_kwh,
        inverter_loss_kw=inverter_loss_kw,
        rectifier_loss_kw=rectifier_loss_kw,
    )
