from __future__ import annotations

from dataclasses import dataclass
import math


# ============================================================
# SECTION 0 — BATTERY RUNTIME STATE
# ============================================================

@dataclass
class BatteryState:
    """
    Mutable per-step battery state carried through the simulation loop.

    WHY THIS EXISTS
    ---------------
    Previously only `current_battery_soc_pct: float` was passed between
    steps.  Every new battery feature (capacity fade, SoH, rainflow cycle
    counting, temperature aging) would have required adding another bare
    float to the signatures of run_dispatch_step, run_controller_step, and
    the simulator loop.

    Centralising all runtime battery state here means that adding new
    physics only requires:
      1. A new field on BatteryState.
      2. The one function that updates that field.
    No signature changes needed anywhere else in the pipeline.

    Fields
    ------
    soc_pct
        Current state of charge (0–100 %).
        Updated every timestep after charge / discharge / self-discharge.

    effective_capacity_kwh
        Actual usable energy capacity at the current point in battery life.
        Starts at nominal (n_strings × kWh_per_string).
        Once capacity fade is implemented this will shrink each year as the
        battery ages, so all downstream physics must read capacity from
        THIS field — never from the config's nominal value directly.

    cumulative_throughput_kwh
        Total energy cycled through the battery since simulation start.
        Updated each step.  Used for:
          • mid-simulation replacement checks (throughput life = lifetime_kwh / annual_throughput)
          • end-of-year accounting in SimulationSummary
        Does NOT include self-discharge loss (passive, not a cycle).

    soh_pct
        State of Health expressed as a percentage of original capacity.
        100 = brand-new battery.  ~80 = typical end-of-life threshold for
        Li-Ion (IEC 62619 / manufacturer datasheets).
        Defaults to 100 until capacity fade is implemented; the field is
        here now so future code has a place to write to without needing
        another signature change.
    """
    soc_pct: float
    effective_capacity_kwh: float
    cumulative_throughput_kwh: float = 0.0
    soh_pct: float = 100.0


# ============================================================
# SECTION 1 — RESULT DATACLASS FOR CHARGE / DISCHARGE STEP
# ============================================================

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

    # kWh of energy that physically passed through the battery this step.
    # = charge input kWh  OR  discharge output kWh  (only one occurs per step).
    # Used to track cumulative throughput for degradation / replacement timing.
    # Reference: HOMER Pro battery replacement methodology (NREL/TP-710-42565).
    throughput_kwh_this_step: float = 0.0


# ============================================================
# SECTION 2 — SELF-DISCHARGE
# ============================================================

def compute_self_discharge_loss(
    *,
    current_soc_pct: float,
    total_capacity_kwh: float,
    minimum_soc_pct: float,
    self_discharge_rate_pct_per_day: float,
    time_step_hours: float,
) -> tuple[float, float]:
    """
    Compute passive energy lost to self-discharge over one timestep.

    Self-discharge reduces stored energy proportionally to how much is stored,
    but cannot take SOC below minimum_soc_pct (battery cannot self-discharge
    below its protection threshold).

    Formula:
        loss = stored_energy × rate_per_day × (dt_hours / 24)

    Reference: HOMER Pro Battery → Self-Discharge Rate parameter.
    Typical values: Li-Ion 0.05–0.1 %/day, Lead-acid 0.1–0.3 %/day.

    Returns
    -------
    (new_soc_pct, actual_loss_kwh)
    """
    if self_discharge_rate_pct_per_day <= 0.0 or total_capacity_kwh <= 0.0:
        return current_soc_pct, 0.0

    current_soc_pct = max(0.0, min(100.0, float(current_soc_pct)))
    minimum_soc_pct = max(0.0, min(100.0, float(minimum_soc_pct)))

    stored_kwh = total_capacity_kwh * (current_soc_pct / 100.0)
    min_stored_kwh = total_capacity_kwh * (minimum_soc_pct / 100.0)

    # Self-discharge is proportional to stored energy, scaled to the timestep length.
    loss_fraction = (self_discharge_rate_pct_per_day / 100.0) * (time_step_hours / 24.0)
    loss_kwh = stored_kwh * loss_fraction

    # Clamp: SOC cannot fall below the minimum protection threshold.
    new_stored_kwh = max(min_stored_kwh, stored_kwh - loss_kwh)
    actual_loss_kwh = stored_kwh - new_stored_kwh
    new_soc_pct = 100.0 * new_stored_kwh / total_capacity_kwh

    return new_soc_pct, actual_loss_kwh


# ============================================================
# SECTION 3 — EFFICIENCY HELPERS
# ============================================================

def _split_roundtrip_efficiency(roundtrip_efficiency_pct: float) -> tuple[float, float]:
    """
    Split roundtrip efficiency into symmetric charge/discharge efficiencies.

    We assume the loss is split equally between charge and discharge by
    taking the square root of the roundtrip efficiency.
    Example: 90% roundtrip → sqrt(0.90) ≈ 94.87% charge AND 94.87% discharge.

    This is the same approach used in HOMER Pro's generic storage model.
    Reference: HOMER Pro Help → Battery → Roundtrip Efficiency.
    """
    eta_rt = max(0.0001, float(roundtrip_efficiency_pct) / 100.0)
    eta = math.sqrt(eta_rt)
    return eta, eta  # (eta_charge, eta_discharge)


# ============================================================
# SECTION 4 — CURRENT-BASED POWER LIMIT HELPERS
# ============================================================

def _compute_charge_power_limit_kw(
    *,
    nominal_voltage_v: float,
    max_charge_current_a: float,
    quantity_strings: int,
) -> float:
    """
    Compute maximum charge power in kW from string voltage and current ratings.

    Assumptions:
    - max_charge_current_a is the rated current per string.
    - quantity_strings parallel strings share current (total = current × strings).
    - nominal_voltage_v is the operating bank voltage used for power calculation.

    Formula: P_max = V × I_total / 1000
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
    Compute maximum discharge power in kW from string voltage and current ratings.

    Same convention as charge: parallel strings sum their current.
    Formula: P_max = V × I_total / 1000
    """
    voltage = max(0.0, float(nominal_voltage_v))
    current_per_string = max(0.0, float(max_discharge_current_a))
    strings = max(0, int(quantity_strings))

    total_current_a = current_per_string * strings
    return (voltage * total_current_a) / 1000.0


# ============================================================
# SECTION 5 — MAIN BATTERY STEP UPDATE
# ============================================================

def update_battery_state(
    *,
    current_soc_pct: float,
    surplus_kw: float,
    deficit_kw: float,
    battery_enabled: bool,
    quantity_strings: int,
    effective_capacity_kwh: float,
    nominal_voltage_v: float,
    max_charge_current_a: float,
    max_discharge_current_a: float,
    minimum_soc_pct: float,
    roundtrip_efficiency_pct: float,
    time_step_hours: float = 1.0,
) -> BatteryChargeDischargeResult:
    """
    Energy-based battery update for one simulation time step.

    KEY DESIGN CHANGE vs. previous version
    ---------------------------------------
    The function previously derived `total_capacity_kwh` internally from:
        nominal_capacity_kwh_per_string × quantity_strings

    It now accepts `effective_capacity_kwh` directly from the caller
    (taken from BatteryState).  This decouples energy capacity from the
    number of strings so that:
      • Capacity fade can reduce effective_capacity_kwh year-by-year
        without changing the string count or power limits.
      • Power limits (charge/discharge kW) still use quantity_strings
        via V × I_per_string × n_strings — these are hardware limits
        that do not change with degradation.

    Rules:
    - If surplus exists, battery charges (up to SOC = 100% and current limit).
    - If deficit exists, battery discharges (down to minimum_soc_pct and current limit).
    - SOC is updated using actual energy movement with efficiency losses.
    - Charge OR discharge — never both in the same timestep.
    """

    # Guard: disabled battery or zero strings → return empty result, keep SOC.
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

    # Use effective (possibly fade-reduced) capacity — not nominal from config.
    total_capacity_kwh = max(0.0, float(effective_capacity_kwh))

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

    # Split roundtrip efficiency symmetrically into charge and discharge halves.
    # eta_charge: fraction of input energy that is stored.
    # eta_discharge: fraction of stored energy that is delivered as output.
    eta_charge, eta_discharge = _split_roundtrip_efficiency(roundtrip_efficiency_pct)

    # Clamp inputs to valid ranges before any arithmetic.
    current_soc_pct = max(0.0, min(100.0, float(current_soc_pct)))
    minimum_soc_pct = max(0.0, min(100.0, float(minimum_soc_pct)))
    time_step_hours = max(1e-9, float(time_step_hours))

    # Convert SOC to absolute stored energy for energy-balance calculations.
    stored_energy_kwh = total_capacity_kwh * (current_soc_pct / 100.0)
    min_allowed_energy_kwh = total_capacity_kwh * (minimum_soc_pct / 100.0)
    max_allowed_energy_kwh = total_capacity_kwh  # = 100% SOC

    # Headroom above current stored energy (how much more can be charged in).
    available_charge_space_kwh = max(0.0, max_allowed_energy_kwh - stored_energy_kwh)
    # Energy accessible above the minimum SOC floor (how much can be discharged).
    available_discharge_energy_kwh = max(0.0, stored_energy_kwh - min_allowed_energy_kwh)

    # Hardware power limits from string voltage and rated current.
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

    # --------------------------------------------------------
    # CHARGE CASE: surplus power available AND space in battery
    # --------------------------------------------------------
    if surplus_kw > 0.0 and available_charge_space_kwh > 0.0:
        requested_charge_kw = max(0.0, float(surplus_kw))

        # Energy-space-based input limit:
        # to store X kWh in battery, input needed is X / eta_charge
        # (we lose some energy to heat during charging).
        max_input_energy_kwh_from_space = available_charge_space_kwh / eta_charge
        max_input_power_kw_from_space = max_input_energy_kwh_from_space / time_step_hours

        # Actual charge is the minimum of: requested, current limit, space limit.
        actual_charge_kw = min(
            requested_charge_kw,
            current_charge_limit_kw,
            max_input_power_kw_from_space,
        )

        # Energy actually stored (after charge efficiency loss).
        actual_input_energy_kwh = actual_charge_kw * time_step_hours
        actual_stored_energy_kwh = actual_input_energy_kwh * eta_charge

        stored_energy_kwh += actual_stored_energy_kwh
        battery_charge_kw = actual_charge_kw

    # --------------------------------------------------------
    # DISCHARGE CASE: deficit exists AND energy above minimum SOC
    # --------------------------------------------------------
    elif deficit_kw > 0.0 and available_discharge_energy_kwh > 0.0:
        requested_discharge_kw = max(0.0, float(deficit_kw))

        # Energy-availability-based output limit:
        # if we remove X kWh from battery, useful output is X * eta_discharge
        # (some energy is lost to heat during discharge).
        max_output_energy_kwh_from_energy = available_discharge_energy_kwh * eta_discharge
        max_output_power_kw_from_energy = max_output_energy_kwh_from_energy / time_step_hours

        # Actual discharge is the minimum of: requested, current limit, available limit.
        actual_discharge_kw = min(
            requested_discharge_kw,
            current_discharge_limit_kw,
            max_output_power_kw_from_energy,
        )

        # Energy removed from storage (more than delivered, due to discharge losses).
        actual_output_energy_kwh = actual_discharge_kw * time_step_hours
        actual_removed_energy_kwh = actual_output_energy_kwh / eta_discharge

        stored_energy_kwh -= actual_removed_energy_kwh
        battery_discharge_kw = actual_discharge_kw

    # Final clamp: floating-point rounding can push stored energy slightly out of bounds.
    stored_energy_kwh = max(min_allowed_energy_kwh, min(max_allowed_energy_kwh, stored_energy_kwh))
    new_soc_pct = 100.0 * stored_energy_kwh / total_capacity_kwh

    # Throughput = energy that moved through the battery this step.
    # Only charge OR discharge occurs per step, so summing is safe (one is always 0).
    # Used to track cumulative throughput for degradation / replacement timing.
    throughput_kwh_this_step = (battery_charge_kw + battery_discharge_kw) * time_step_hours

    return BatteryChargeDischargeResult(
        battery_charge_kw=battery_charge_kw,
        battery_discharge_kw=battery_discharge_kw,
        new_soc_pct=new_soc_pct,
        stored_energy_kwh=stored_energy_kwh,
        available_charge_space_kwh=max(0.0, max_allowed_energy_kwh - stored_energy_kwh),
        available_discharge_energy_kwh=max(0.0, stored_energy_kwh - min_allowed_energy_kwh),
        max_charge_power_kw=current_charge_limit_kw,
        max_discharge_power_kw=current_discharge_limit_kw,
        throughput_kwh_this_step=throughput_kwh_this_step,
    )
