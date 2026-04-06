from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass
class BatteryChargeDischargeResult:
    battery_charge_kw: float
    battery_discharge_kw: float
    new_soc_pct: float
    stored_energy_kwh: float
    available_charge_space_kwh: float
    available_discharge_energy_kwh: float
    max_charge_power_kw: float
    max_discharge_power_kw: float


def _split_roundtrip_efficiency(roundtrip_efficiency_pct: float) -> tuple[float, float]:
    """
    Split roundtrip efficiency into symmetric charge/discharge efficiencies.
    Example: 90% roundtrip -> ~94.9% charge and ~94.9% discharge.
    """
    eta_rt = max(0.0001, float(roundtrip_efficiency_pct) / 100.0)
    eta = math.sqrt(eta_rt)
    return eta, eta


def _compute_charge_power_limit_kw(
    *,
    nominal_voltage_v: float,
    max_charge_current_a: float,
    quantity_strings: int,
) -> float:
    """
    Compute maximum charge power in kW.

    Assumption:
    - max_charge_current_a is per string
    - quantity_strings are parallel battery strings
    - nominal_voltage_v is the operating bank/string voltage used for power calculation
    """
    voltage = max(0.0, float(nominal_voltage_v))
    current_per_string = max(0.0, float(max_charge_current_a))
    strings = max(0, int(quantity_strings))

    total_current_a = current_per_string * strings
    return (voltage * total_current_a) / 1000.0


def _compute_discharge_power_limit_kw(
    *,
    nominal_voltage_v: float,
    max_discharge_current_a: float,
    quantity_strings: int,
) -> float:
    """
    Compute maximum discharge power in kW.

    Assumption:
    - max_discharge_current_a is per string
    - quantity_strings are parallel battery strings
    - nominal_voltage_v is the operating bank/string voltage used for power calculation
    """
    voltage = max(0.0, float(nominal_voltage_v))
    current_per_string = max(0.0, float(max_discharge_current_a))
    strings = max(0, int(quantity_strings))

    total_current_a = current_per_string * strings
    return (voltage * total_current_a) / 1000.0 


def update_battery_state(
    *,
    current_soc_pct: float,
    surplus_kw: float,
    deficit_kw: float,
    battery_enabled: bool,
    quantity_strings: int,
    nominal_capacity_kwh_per_string: float,
    nominal_voltage_v: float,
    max_charge_current_a: float,
    max_discharge_current_a: float,
    minimum_soc_pct: float,
    roundtrip_efficiency_pct: float,
    time_step_hours: float = 1.0,
) -> BatteryChargeDischargeResult:
    """
    Energy-based battery update for one simulation time step with current-based power limits.

    Rules:
    - If surplus exists, battery charges.
    - If deficit exists, battery discharges.
    - SOC is updated using actual energy movement.
    - Battery cannot exceed 100% SOC or go below minimum SOC.
    - Charge/discharge power is also limited by current and voltage.
    """

    if not battery_enabled or quantity_strings <= 0:
        return BatteryChargeDischargeResult(
            battery_charge_kw=0.0,
            battery_discharge_kw=0.0,
            new_soc_pct=float(current_soc_pct),
            stored_energy_kwh=0.0,
            available_charge_space_kwh=0.0,
            available_discharge_energy_kwh=0.0,
            max_charge_power_kw=0.0,
            max_discharge_power_kw=0.0,
        )

    total_capacity_kwh = float(quantity_strings) * float(nominal_capacity_kwh_per_string)
    total_capacity_kwh = max(0.0, total_capacity_kwh)

    if total_capacity_kwh <= 0.0:
        return BatteryChargeDischargeResult(
            battery_charge_kw=0.0,
            battery_discharge_kw=0.0,
            new_soc_pct=float(current_soc_pct),
            stored_energy_kwh=0.0,
            available_charge_space_kwh=0.0,
            available_discharge_energy_kwh=0.0,
            max_charge_power_kw=0.0,
            max_discharge_power_kw=0.0,
        )

    eta_charge, eta_discharge = _split_roundtrip_efficiency(roundtrip_efficiency_pct)

    current_soc_pct = max(0.0, min(100.0, float(current_soc_pct)))
    minimum_soc_pct = max(0.0, min(100.0, float(minimum_soc_pct)))
    time_step_hours = max(1e-9, float(time_step_hours))

    stored_energy_kwh = total_capacity_kwh * (current_soc_pct / 100.0)
    min_allowed_energy_kwh = total_capacity_kwh * (minimum_soc_pct / 100.0)
    max_allowed_energy_kwh = total_capacity_kwh

    available_charge_space_kwh = max(0.0, max_allowed_energy_kwh - stored_energy_kwh)
    available_discharge_energy_kwh = max(0.0, stored_energy_kwh - min_allowed_energy_kwh)

    current_charge_limit_kw = _compute_charge_power_limit_kw(
        nominal_voltage_v=nominal_voltage_v,
        max_charge_current_a=max_charge_current_a,
        quantity_strings=quantity_strings,
    )

    current_discharge_limit_kw = _compute_discharge_power_limit_kw(
        nominal_voltage_v=nominal_voltage_v,
        max_discharge_current_a=max_discharge_current_a,
        quantity_strings=quantity_strings,
    )

    battery_charge_kw = 0.0
    battery_discharge_kw = 0.0

    # Charge case
    if surplus_kw > 0.0 and available_charge_space_kwh > 0.0:
        requested_charge_kw = max(0.0, float(surplus_kw))
        requested_charge_kwh = requested_charge_kw * time_step_hours

        # Energy-space-based input limit:
        # to store X kWh in battery, input needed is X / eta_charge
        max_input_energy_kwh_from_space = available_charge_space_kwh / eta_charge
        max_input_power_kw_from_space = max_input_energy_kwh_from_space / time_step_hours

        actual_charge_kw = min(
            requested_charge_kw,
            current_charge_limit_kw,
            max_input_power_kw_from_space,
        )

        actual_input_energy_kwh = actual_charge_kw * time_step_hours
        actual_stored_energy_kwh = actual_input_energy_kwh * eta_charge

        stored_energy_kwh += actual_stored_energy_kwh
        battery_charge_kw = actual_charge_kw

    # Discharge case
    elif deficit_kw > 0.0 and available_discharge_energy_kwh > 0.0:
        requested_discharge_kw = max(0.0, float(deficit_kw))
        requested_discharge_kwh = requested_discharge_kw * time_step_hours

        # Energy-availability-based output limit:
        # if we remove X kWh from battery, useful output is X * eta_discharge
        max_output_energy_kwh_from_energy = available_discharge_energy_kwh * eta_discharge
        max_output_power_kw_from_energy = max_output_energy_kwh_from_energy / time_step_hours

        actual_discharge_kw = min(
            requested_discharge_kw,
            current_discharge_limit_kw,
            max_output_power_kw_from_energy,
        )

        actual_output_energy_kwh = actual_discharge_kw * time_step_hours
        actual_removed_energy_kwh = actual_output_energy_kwh / eta_discharge

        stored_energy_kwh -= actual_removed_energy_kwh
        battery_discharge_kw = actual_discharge_kw

    stored_energy_kwh = max(min_allowed_energy_kwh, min(max_allowed_energy_kwh, stored_energy_kwh))
    new_soc_pct = 100.0 * stored_energy_kwh / total_capacity_kwh

    return BatteryChargeDischargeResult(
        battery_charge_kw=battery_charge_kw,
        battery_discharge_kw=battery_discharge_kw,
        new_soc_pct=new_soc_pct,
        stored_energy_kwh=stored_energy_kwh,
        available_charge_space_kwh=max(0.0, max_allowed_energy_kwh - stored_energy_kwh),
        available_discharge_energy_kwh=max(0.0, stored_energy_kwh - min_allowed_energy_kwh),
        max_charge_power_kw=current_charge_limit_kw,
        max_discharge_power_kw=current_discharge_limit_kw,
    )