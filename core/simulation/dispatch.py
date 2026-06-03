from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .battery_soc import BatteryState, compute_self_discharge_loss, update_battery_state
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
VERY_LARGE_POWER_KW: float = 1e12  # used to probe maximum charge/discharge power


# ============================================================
# DISPATCH RESULT
# ============================================================

@dataclass
class DispatchResult:
    """
    All outputs from a single dispatch timestep.

    Bus accounting convention:
    - pv_kw              = DC PV generation (before inverter)
    - wind_kw            = AC wind generation
    - battery_charge_kw  = DC power INTO battery terminals
    - battery_discharge_dc_kw = DC power FROM battery terminals
    - battery_discharge_kw    = AC power delivered AFTER inverter
    - grid_import/export_kw   = AC bus

    Energy balance (should hold within floating-point tolerance):
        pv_kw + wind_kw + grid_import_kw + battery_discharge_dc_kw
        =
        served_load_kw + battery_charge_kw + grid_export_kw
        + excess_energy_kw + inverter_loss_kw + rectifier_loss_kw

    updated_battery_state
        Full BatteryState after this step.  The simulator loop reads this
        to carry state into the next step.  Keeping the full state object
        here (rather than just battery_soc_pct) means future fields
        (capacity fade, SoH, cumulative cycles) are automatically forwarded
        without any additional signature changes.

    battery_soc_pct
        Kept as a standalone field for convenience — used directly when
        building HourlySimulationRecord without unpacking the state object.
    """
    renewable_kw: float
    served_load_kw: float
    unmet_load_kw: float
    excess_energy_kw: float

    battery_charge_kw: float            # DC into battery terminals
    battery_discharge_kw: float         # AC delivered after inverter
    battery_discharge_dc_kw: float      # DC out of battery terminals
    battery_soc_pct: float              # convenience copy of updated_battery_state.soc_pct

    grid_import_kw: float
    grid_export_kw: float

    # Extra visibility for renewable fraction tracking in simulator.py
    wind_to_load_kw: float
    pv_to_load_ac_kw: float

    renewable_charge_stored_kwh: float   # renewable energy stored in battery this step
    battery_energy_removed_kwh: float    # energy removed from battery storage this step

    inverter_loss_kw: float
    rectifier_loss_kw: float

    # Full updated BatteryState — simulator carries this forward between steps.
    # Contains: soc_pct, effective_capacity_kwh, cumulative_throughput_kwh, soh_pct.
    updated_battery_state: BatteryState

    # Passive energy lost to self-discharge this step (kWh, not kW —
    # self-discharge happens once per step regardless of step length).
    self_discharge_loss_kwh: float = 0.0


# ============================================================
# INTERNAL HELPERS
# ============================================================

def _safe_getattr(obj: Any, name: str, default: Any) -> Any:
    """Safe attribute read — returns default if attribute is missing."""
    return getattr(obj, name, default)


def _stored_energy_from_soc_pct(
    *,
    soc_pct: float,
    effective_capacity_kwh: float,
) -> float:
    """
    Convert SOC percentage to absolute stored energy (kWh).

    Uses effective_capacity_kwh from BatteryState rather than deriving
    from nominal config, so capacity fade is automatically reflected.
    """
    soc_pct = max(0.0, min(100.0, float(soc_pct)))
    return max(0.0, float(effective_capacity_kwh)) * (soc_pct / 100.0)


def _probe_max_battery_charge_kw(
    *,
    current_soc_pct: float,
    effective_capacity_kwh: float,
    battery_config: Any,
    selected_battery_quantity: int,
    time_step_hours: float,
) -> float:
    """
    Find the maximum power (kW DC) the battery can accept this step.

    Done by calling update_battery_state with an unrealistically large surplus;
    the physics clamps it to the true hardware and energy-space limit.
    The result is used to size rectifier requests before committing.
    """
    result = update_battery_state(
        current_soc_pct=current_soc_pct,
        surplus_kw=VERY_LARGE_POWER_KW,
        deficit_kw=0.0,
        battery_enabled=bool(_safe_getattr(battery_config, "enabled", False)),
        quantity_strings=max(0, int(selected_battery_quantity)),
        effective_capacity_kwh=effective_capacity_kwh,
        nominal_voltage_v=float(_safe_getattr(battery_config, "nominal_voltage_v", 0.0)),
        max_charge_current_a=float(_safe_getattr(battery_config, "max_charge_current_a", 0.0)),
        max_discharge_current_a=float(_safe_getattr(battery_config, "max_discharge_current_a", 0.0)),
        minimum_soc_pct=float(_safe_getattr(battery_config, "minimum_state_of_charge_pct", 0.0)),
        roundtrip_efficiency_pct=float(_safe_getattr(battery_config, "roundtrip_efficiency_pct", 100.0)),
        time_step_hours=time_step_hours,
    )
    return max(0.0, result.battery_charge_kw)


def _probe_max_battery_discharge_kw(
    *,
    current_soc_pct: float,
    effective_capacity_kwh: float,
    battery_config: Any,
    selected_battery_quantity: int,
    time_step_hours: float,
) -> float:
    """
    Find the maximum power (kW DC) the battery can deliver this step.

    Same probe technique as charge: use unrealistically large deficit,
    physics returns the true hardware and SOC-limited maximum.
    """
    result = update_battery_state(
        current_soc_pct=current_soc_pct,
        surplus_kw=0.0,
        deficit_kw=VERY_LARGE_POWER_KW,
        battery_enabled=bool(_safe_getattr(battery_config, "enabled", False)),
        quantity_strings=max(0, int(selected_battery_quantity)),
        effective_capacity_kwh=effective_capacity_kwh,
        nominal_voltage_v=float(_safe_getattr(battery_config, "nominal_voltage_v", 0.0)),
        max_charge_current_a=float(_safe_getattr(battery_config, "max_charge_current_a", 0.0)),
        max_discharge_current_a=float(_safe_getattr(battery_config, "max_discharge_current_a", 0.0)),
        minimum_soc_pct=float(_safe_getattr(battery_config, "minimum_state_of_charge_pct", 0.0)),
        roundtrip_efficiency_pct=float(_safe_getattr(battery_config, "roundtrip_efficiency_pct", 100.0)),
        time_step_hours=time_step_hours,
    )
    return max(0.0, result.battery_discharge_kw)


def _apply_battery_charge(
    *,
    current_soc_pct: float,
    charge_input_kw: float,
    effective_capacity_kwh: float,
    battery_config: Any,
    selected_battery_quantity: int,
    time_step_hours: float,
) -> tuple[float, float, float]:
    """
    Commit a charge action and return the resulting state change.

    Returns
    -------
    (new_soc_pct, actual_charge_input_kw_dc, stored_energy_delta_kwh)

    stored_energy_delta_kwh is the NET energy added to storage
    (after charge efficiency loss) — used for renewable fraction accounting.
    """
    # Record stored energy before so we can compute the delta afterwards.
    old_stored_kwh = _stored_energy_from_soc_pct(
        soc_pct=current_soc_pct,
        effective_capacity_kwh=effective_capacity_kwh,
    )

    result = update_battery_state(
        current_soc_pct=current_soc_pct,
        surplus_kw=max(0.0, float(charge_input_kw)),
        deficit_kw=0.0,
        battery_enabled=bool(_safe_getattr(battery_config, "enabled", False)),
        quantity_strings=max(0, int(selected_battery_quantity)),
        effective_capacity_kwh=effective_capacity_kwh,
        nominal_voltage_v=float(_safe_getattr(battery_config, "nominal_voltage_v", 0.0)),
        max_charge_current_a=float(_safe_getattr(battery_config, "max_charge_current_a", 0.0)),
        max_discharge_current_a=float(_safe_getattr(battery_config, "max_discharge_current_a", 0.0)),
        minimum_soc_pct=float(_safe_getattr(battery_config, "minimum_state_of_charge_pct", 0.0)),
        roundtrip_efficiency_pct=float(_safe_getattr(battery_config, "roundtrip_efficiency_pct", 100.0)),
        time_step_hours=time_step_hours,
    )

    # Delta = new stored energy minus old stored energy.
    # max(0) guards against floating-point underflow.
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
    effective_capacity_kwh: float,
    battery_config: Any,
    selected_battery_quantity: int,
    time_step_hours: float,
) -> tuple[float, float, float]:
    """
    Commit a discharge action and return the resulting state change.

    Returns
    -------
    (new_soc_pct, actual_dc_output_kw_from_battery, removed_energy_kwh_from_storage)

    removed_energy_kwh_from_storage is the energy taken OUT of the storage
    (more than what is delivered, due to discharge efficiency losses).
    Used for renewable energy tracking in the simulator.
    """
    old_stored_kwh = _stored_energy_from_soc_pct(
        soc_pct=current_soc_pct,
        effective_capacity_kwh=effective_capacity_kwh,
    )

    result = update_battery_state(
        current_soc_pct=current_soc_pct,
        surplus_kw=0.0,
        deficit_kw=max(0.0, float(requested_dc_output_kw)),
        battery_enabled=bool(_safe_getattr(battery_config, "enabled", False)),
        quantity_strings=max(0, int(selected_battery_quantity)),
        effective_capacity_kwh=effective_capacity_kwh,
        nominal_voltage_v=float(_safe_getattr(battery_config, "nominal_voltage_v", 0.0)),
        max_charge_current_a=float(_safe_getattr(battery_config, "max_charge_current_a", 0.0)),
        max_discharge_current_a=float(_safe_getattr(battery_config, "max_discharge_current_a", 0.0)),
        minimum_soc_pct=float(_safe_getattr(battery_config, "minimum_state_of_charge_pct", 0.0)),
        roundtrip_efficiency_pct=float(_safe_getattr(battery_config, "roundtrip_efficiency_pct", 100.0)),
        time_step_hours=time_step_hours,
    )

    # Energy removed from storage = old minus new (always non-negative).
    removed_energy_kwh = max(0.0, old_stored_kwh - result.stored_energy_kwh)

    return (
        result.new_soc_pct,
        result.battery_discharge_kw,
        removed_energy_kwh,
    )


# ============================================================
# MAIN DISPATCH STEP
# ============================================================

def run_dispatch_step(
    *,
    load_kw: float,
    pv_kw: float,
    wind_kw: float,
    battery_state: BatteryState,
    battery_config: Any,
    converter_config: Any,
    grid_config: Any,
    selected_battery_quantity: int,
    selected_converter_capacity_kw: float,
    time_step_hours: float = 1.0,
    dispatch_strategy: str = DEFAULT_DISPATCH_STRATEGY,
) -> DispatchResult:
    """
    Simulate one dispatch timestep for the full hybrid system.

    Bus assumptions:
    - PV  → DC bus
    - Battery → DC bus
    - Wind → AC bus
    - Load → AC bus
    - Grid → AC bus
    - Converter bridges DC ↔ AC

    Dispatch order (renewable_first strategy):
    1. Wind → Load  (AC direct, no converter needed)
    2. PV → Load    (DC via inverter, uses shared inverter capacity)
    3. PV surplus → Battery  (DC direct, no converter)
    4. Wind surplus → Battery  (AC via rectifier, uses shared rectifier capacity)
    5. Battery → Load  (DC via inverter, uses shared inverter capacity)
    6. Remaining surplus → Grid export or curtailment
    7. Remaining deficit → Grid import or unmet load

    Battery state is passed in as BatteryState and returned inside
    DispatchResult.updated_battery_state.  The simulator carries this
    object between steps.  Adding new battery physics (capacity fade,
    SoH update) only requires changes here and in battery_soc.py.

    Important fix (preserved from previous version):
    - Inverter AC capacity is shared across ALL DC→AC flows in the timestep.
    - Rectifier AC-input capacity is shared across ALL AC→DC flows.
    """
    dispatch_strategy = validate_dispatch_strategy(dispatch_strategy)

    # --- INPUT SANITISATION ---
    load_kw = max(0.0, float(load_kw))
    pv_kw = max(0.0, float(pv_kw))
    wind_kw = max(0.0, float(wind_kw))
    time_step_hours = max(EPSILON, float(time_step_hours))
    selected_battery_quantity = max(0, int(selected_battery_quantity))
    selected_converter_capacity_kw = max(0.0, float(selected_converter_capacity_kw))

    # Unpack battery state into local working variables.
    battery_soc_pct = max(0.0, min(100.0, float(battery_state.soc_pct)))
    effective_capacity_kwh = max(0.0, float(battery_state.effective_capacity_kwh))

    # Battery is only active when: enabled in config, at least one string selected,
    # AND the effective capacity is non-zero (guards against zero after full fade).
    battery_enabled = (
        bool(_safe_getattr(battery_config, "enabled", False))
        and selected_battery_quantity > 0
        and effective_capacity_kwh > 0.0
    )
    grid_limits = resolve_grid_limits(grid_config)

    # --- SELF-DISCHARGE ---
    # Applied BEFORE charge/discharge so all subsequent logic sees the
    # already-reduced SOC. This happens every timestep regardless of
    # whether the battery charges or discharges.
    # Reference: HOMER Pro — self-discharge is applied at the start of each step.
    self_discharge_loss_kwh = 0.0
    if battery_enabled:
        battery_soc_pct, self_discharge_loss_kwh = compute_self_discharge_loss(
            current_soc_pct=battery_soc_pct,
            total_capacity_kwh=effective_capacity_kwh,  # from BatteryState, not from config
            minimum_soc_pct=float(_safe_getattr(battery_config, "minimum_state_of_charge_pct", 0.0)),
            self_discharge_rate_pct_per_day=float(
                _safe_getattr(battery_config, "self_discharge_rate_pct_per_day", 0.0)
            ),
            time_step_hours=time_step_hours,
        )

    # --- SHARED CONVERTER BUDGETS FOR THIS TIMESTEP ---
    # Each converter path (PV→load, battery→load, wind→battery) draws from
    # the same physical inverter/rectifier capacity. remaining_* tracks what
    # is still available as each path consumes its share.
    remaining_inverter_ac_capacity_kw = get_inverter_capacity_kw(
        converter_config=converter_config,
        selected_capacity_kw=selected_converter_capacity_kw,
    )
    remaining_rectifier_ac_capacity_kw = get_rectifier_capacity_kw(
        converter_config=converter_config,
        selected_inverter_capacity_kw=selected_converter_capacity_kw,
    )

    # Accumulators — start at zero, filled in by each dispatch step below.
    inverter_loss_kw = 0.0
    rectifier_loss_kw = 0.0

    battery_charge_kw = 0.0
    battery_discharge_kw = 0.0
    battery_discharge_dc_kw = 0.0

    grid_import_kw = 0.0
    grid_export_kw = 0.0

    wind_to_load_kw = 0.0
    pv_to_load_ac_kw = 0.0

    renewable_charge_stored_kwh = 0.0   # renewable kWh stored in battery this step
    battery_energy_removed_kwh = 0.0    # kWh removed from battery storage this step

    renewable_kw = pv_kw + wind_kw      # total generation before dispatch

    # Remaining quantities that haven't been assigned yet — decremented as each
    # dispatch path consumes them.
    remaining_load_kw = load_kw
    remaining_pv_dc_kw = pv_kw
    remaining_wind_ac_kw = wind_kw

    # --------------------------------------------------------
    # STEP 1. WIND → LOAD  (AC direct, no converter loss)
    # --------------------------------------------------------
    wind_to_load_kw = min(remaining_wind_ac_kw, remaining_load_kw)
    remaining_wind_ac_kw -= wind_to_load_kw
    remaining_load_kw -= wind_to_load_kw

    # --------------------------------------------------------
    # STEP 2. PV → LOAD  (DC through shared inverter)
    # --------------------------------------------------------
    if (
        remaining_load_kw > EPSILON
        and remaining_pv_dc_kw > EPSILON
        and remaining_inverter_ac_capacity_kw > EPSILON
    ):
        inverter_eff = get_inverter_efficiency(converter_config)
        if inverter_eff > EPSILON:
            # Maximum AC output we can send to load given current inverter headroom.
            max_ac_for_pv_to_load_kw = min(
                remaining_load_kw,
                remaining_inverter_ac_capacity_kw,
            )
            # Convert AC limit back to DC to know how much PV to request.
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
            # Deduct used inverter capacity so subsequent steps see the remainder.
            remaining_inverter_ac_capacity_kw = max(
                0.0,
                remaining_inverter_ac_capacity_kw - inv_result.output_power_kw,
            )

    # --------------------------------------------------------
    # STEP 3. PV SURPLUS → BATTERY  (DC direct, no converter)
    # --------------------------------------------------------
    if battery_enabled and remaining_pv_dc_kw > EPSILON:
        new_soc_pct, actual_charge_dc_kw, stored_delta_kwh = _apply_battery_charge(
            current_soc_pct=battery_soc_pct,
            charge_input_kw=remaining_pv_dc_kw,
            effective_capacity_kwh=effective_capacity_kwh,
            battery_config=battery_config,
            selected_battery_quantity=selected_battery_quantity,
            time_step_hours=time_step_hours,
        )

        battery_soc_pct = new_soc_pct
        battery_charge_kw += actual_charge_dc_kw
        # All PV energy stored here is renewable — track for renewable fraction.
        renewable_charge_stored_kwh += stored_delta_kwh
        remaining_pv_dc_kw -= actual_charge_dc_kw

    # --------------------------------------------------------
    # STEP 4. WIND SURPLUS → BATTERY  (AC via shared rectifier)
    # --------------------------------------------------------
    if (
        battery_enabled
        and remaining_wind_ac_kw > EPSILON
        and remaining_rectifier_ac_capacity_kw > EPSILON
    ):
        # Probe: how much DC can the battery still accept this step?
        max_battery_charge_dc_kw = _probe_max_battery_charge_kw(
            current_soc_pct=battery_soc_pct,
            effective_capacity_kwh=effective_capacity_kwh,
            battery_config=battery_config,
            selected_battery_quantity=selected_battery_quantity,
            time_step_hours=time_step_hours,
        )

        rectifier_eff = get_rectifier_efficiency(converter_config)
        if max_battery_charge_dc_kw > EPSILON and rectifier_eff > EPSILON:
            # AC input needed to produce the required DC (accounting for rectifier loss).
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
                effective_capacity_kwh=effective_capacity_kwh,
                battery_config=battery_config,
                selected_battery_quantity=selected_battery_quantity,
                time_step_hours=time_step_hours,
            )

            battery_soc_pct = new_soc_pct
            battery_charge_kw += actual_charge_dc_kw
            # Wind energy stored is also renewable — track for renewable fraction.
            renewable_charge_stored_kwh += stored_delta_kwh
            remaining_wind_ac_kw -= rect_result.input_power_kw
            rectifier_loss_kw += rect_result.loss_kw
            remaining_rectifier_ac_capacity_kw = max(
                0.0,
                remaining_rectifier_ac_capacity_kw - rect_result.input_power_kw,
            )

    # --------------------------------------------------------
    # STEP 5. BATTERY → LOAD  (DC via shared inverter)
    # --------------------------------------------------------
    if (
        battery_enabled
        and remaining_load_kw > EPSILON
        and remaining_inverter_ac_capacity_kw > EPSILON
    ):
        # Probe: how much DC can the battery deliver this step?
        max_battery_dc_output_kw = _probe_max_battery_discharge_kw(
            current_soc_pct=battery_soc_pct,
            effective_capacity_kwh=effective_capacity_kwh,
            battery_config=battery_config,
            selected_battery_quantity=selected_battery_quantity,
            time_step_hours=time_step_hours,
        )

        inverter_eff = get_inverter_efficiency(converter_config)
        if max_battery_dc_output_kw > EPSILON and inverter_eff > EPSILON:
            # Max AC we can deliver to load given inverter headroom.
            max_ac_for_battery_to_load_kw = min(
                remaining_load_kw,
                remaining_inverter_ac_capacity_kw,
            )
            # Convert AC limit to DC to know how much to request from battery.
            requested_dc_from_battery_kw = min(
                max_battery_dc_output_kw,
                max_ac_for_battery_to_load_kw / inverter_eff,
            )

            # Probe the inverter first to find how much DC it will actually accept
            # (may be limited by remaining inverter capacity).
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
                    effective_capacity_kwh=effective_capacity_kwh,
                    battery_config=battery_config,
                    selected_battery_quantity=selected_battery_quantity,
                    time_step_hours=time_step_hours,
                )

                battery_soc_pct = new_soc_pct
                battery_energy_removed_kwh += removed_energy_kwh
                battery_discharge_dc_kw += actual_battery_dc_output_kw

                # Run the actual (non-probe) inverter conversion for the committed DC.
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

    # --------------------------------------------------------
    # STEP 6. REMAINING PV SURPLUS → GRID EXPORT OR EXCESS
    # --------------------------------------------------------
    pv_surplus_ac_equivalent_kw = 0.0
    pv_curtailed_dc_kw = 0.0

    if remaining_pv_dc_kw > EPSILON:
        # Convert remaining PV DC to AC for potential export.
        pv_export_result = convert_dc_to_ac(
            requested_dc_power_kw=remaining_pv_dc_kw,
            converter_config=converter_config,
            selected_inverter_capacity_kw=remaining_inverter_ac_capacity_kw,
        )
        pv_surplus_ac_equivalent_kw = pv_export_result.output_power_kw
        inverter_loss_kw += pv_export_result.loss_kw
        # Any DC that could not pass through the inverter is curtailed.
        pv_curtailed_dc_kw = pv_export_result.clipped_power_kw
        remaining_pv_dc_kw -= pv_export_result.input_power_kw
        remaining_pv_dc_kw = max(0.0, remaining_pv_dc_kw)
        remaining_inverter_ac_capacity_kw = max(
            0.0,
            remaining_inverter_ac_capacity_kw - pv_export_result.output_power_kw,
        )

    # Total surplus available for export = unconsumed wind + PV-converted-to-AC.
    available_export_ac_kw = remaining_wind_ac_kw + pv_surplus_ac_equivalent_kw

    export_result = compute_grid_export(
        available_surplus_ac_kw=available_export_ac_kw,
        pv_curtailed_dc_kw=pv_curtailed_dc_kw,
        limits=grid_limits,
    )
    grid_export_kw = export_result.grid_export_kw
    excess_energy_kw = export_result.excess_energy_kw

    # --------------------------------------------------------
    # STEP 7. GRID IMPORT to cover remaining deficit
    # --------------------------------------------------------
    import_result = compute_grid_import(
        remaining_load_kw=remaining_load_kw,
        limits=grid_limits,
    )
    grid_import_kw = import_result.grid_import_kw

    unmet_load_kw = max(0.0, import_result.remaining_unmet_load_kw)
    served_load_kw = max(0.0, load_kw - unmet_load_kw)

    # --------------------------------------------------------
    # BUILD UPDATED BATTERY STATE
    # --------------------------------------------------------
    # Throughput counts only active charge/discharge cycles — self-discharge
    # is tracked separately as a loss, not as a throughput cycle.
    new_cumulative_throughput_kwh = (
        battery_state.cumulative_throughput_kwh
        + (battery_charge_kw + battery_discharge_dc_kw) * time_step_hours
    )

    updated_battery_state = BatteryState(
        soc_pct=battery_soc_pct,
        # Capacity unchanged this step — will be reduced here once capacity fade
        # is implemented (a single update: fade_factor × old_effective_capacity).
        effective_capacity_kwh=effective_capacity_kwh,
        cumulative_throughput_kwh=new_cumulative_throughput_kwh,
        # SoH unchanged this step — will be derived from capacity fade later.
        soh_pct=battery_state.soh_pct,
    )

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
        updated_battery_state=updated_battery_state,
        self_discharge_loss_kwh=self_discharge_loss_kwh,
    )
