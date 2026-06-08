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

    # DoD-based cycle damage tracking (Miner's rule).
    # cumulative_cycle_damage accumulates from 0 (new) toward 1 (EOL by cycling).
    # At 1.0 the battery has consumed its full cycle life at the DoD it was cycled at.
    # Only active when BatteryComponentConfig.cycle_life_a > 0.
    cumulative_cycle_damage: float = 0.0

    # SOC (%) at the start of the current half-cycle (last direction reversal).
    # -1.0 = tracking not yet started (no charge or discharge has occurred).
    # On the first active step this is set to the pre-dispatch SOC.
    half_cycle_soc_pct: float = -1.0

    # Direction of the most recent active half-cycle.
    # 0 = idle / not yet started, 1 = charging, -1 = discharging.
    half_cycle_direction: int = 0


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
# SECTION 2 — CAPACITY FADE
# ============================================================

def apply_capacity_fade(
    *,
    battery_state: BatteryState,
    nominal_capacity_kwh: float,
    end_of_life_soh_pct: float,
    capacity_fade_pct_per_efc: float = 0.0,
    cumulative_calendar_fade_pct: float = 0.0,
    dod_fade_pct: float = 0.0,
) -> BatteryState:
    """
    Apply linear capacity fade to battery_state based on cycling and calendar aging.

    Called once per timestep after dispatch, using the updated cumulative throughput.
    Returns a new BatteryState with effective_capacity_kwh and soh_pct updated.
    If both fade rates are zero, returns battery_state unchanged (zero-cost path).

    FADE MODEL
    ----------
    We use a linear approximation to the full Arrhenius / power-law aging model
    (Schmalstieg et al. 2014).  It is the same approach used in HOMER Pro's
    simplified battery degradation mode and in Lazard LCOS v7.0:

        cycle_fade_pct    = capacity_fade_pct_per_efc × EFC
        calendar_fade_pct = calendar_fade_pct_per_year × elapsed_years
        soh_pct           = 100 - max(cycle_fade_pct, calendar_fade_pct)

    WHY max() AND NOT ADDITION
    --------------------------
    HOMER Pro's rule: "End of life determined by calendar or cycling degradation,
    whichever is greater."  Adding the two fades would double-count: a battery
    that reaches EOL via cycling at year 10 and would have reached EOL via calendar
    at year 12 has NOT suffered 2× degradation — it failed once, at year 10.
    max() correctly captures "whichever mechanism gets there first."
    As future steps add Arrhenius calendar aging (temperature-dependent) and
    Rainflow cycle counting (DoD-dependent), the combining rule stays max().

    EFC (Equivalent Full Cycle):
        EFC = cumulative_throughput_kwh / (2 × nominal_capacity_kwh)

    The factor of 2 in the EFC denominator:
        One full cycle = one full charge (nominal_capacity_kwh) plus one full
        discharge (nominal_capacity_kwh) = 2 × nominal_capacity_kwh of throughput.
        Dividing total throughput by this converts kWh-cycled to full-cycle count.
    References: IEEE 2030.2.1; Xu et al. (2016) Applied Energy.

    SOC RECLAMPING AFTER CAPACITY SHRINK
    ------------------------------------
    When effective_capacity_kwh decreases, absolute stored energy (kWh) stays
    the same but the SOC percentage rises.  If stored energy would exceed the
    new (smaller) capacity, SOC is clamped to 100%:
        stored_kwh  = old_capacity × (old_soc_pct / 100)
        new_soc_pct = min(100, 100 × stored_kwh / new_capacity)

    EOL CLAMP
    ---------
    Capacity is clamped at end_of_life_soh_pct — below EOL the battery would
    be replaced.  Replacement economics (cost, timing) are computed separately
    by the economics evaluator using lifetime_years and throughput_kwh.

    Parameters
    ----------
    battery_state : BatteryState
        Current state AFTER dispatch (contains updated cumulative_throughput_kwh).
    nominal_capacity_kwh : float
        Battery's original rated capacity (constant throughout simulation).
        = nominal_capacity_kwh_per_string × n_strings.
        Used as the EFC denominator and as the 100%-SoH reference.
    elapsed_hours : float
        Total simulation hours elapsed so far (used for calendar aging).
        Typically (hour_index + 1) × time_step_hours.
    end_of_life_soh_pct : float
        SoH floor — capacity will not fall below this × nominal.
        Typically 80.0 per IEC 62619:2022.
    capacity_fade_pct_per_efc : float, optional
        % capacity lost per EFC (simple EFC model).  0.0 = disabled.
        Disable when using the DoD model (cycle_life_a > 0) to avoid double-counting.
    cumulative_calendar_fade_pct : float, optional
        Total calendar capacity lost (%) accumulated from simulation start.
        Computed by the simulator — either as rate × elapsed_years (fixed-rate model)
        or as the Arrhenius-integrated sum (temperature-dependent model).
        0.0 = calendar aging disabled (default).
    dod_fade_pct : float, optional
        Pre-computed fade from DoD-based cycle damage:
            dod_fade_pct = cumulative_cycle_damage × replacement_degradation_limit_pct
        0.0 = DoD model disabled (default).  Included in the max() combining rule.

    Returns
    -------
    BatteryState with updated soc_pct, effective_capacity_kwh, soh_pct.
    cumulative_throughput_kwh is carried forward unchanged.

    References
    ----------
    Schmalstieg et al. (2014) J. Power Sources 309:86-95
    Pelletier et al. (2017) J. Power Sources 359:468-479
    NREL/TP-5400-74010 — BESS degradation modeling
    IEC 62619:2022 — Safety requirements for secondary lithium cells
    Xu et al. (2016) Applied Energy 177:537-545
    """
    # Fast path: all fade mechanisms disabled — return unchanged.
    if capacity_fade_pct_per_efc <= 0.0 and cumulative_calendar_fade_pct <= 0.0 and dod_fade_pct <= 0.0:
        return battery_state

    if nominal_capacity_kwh <= 0.0:
        return battery_state

    # ---- Cycle fade (EFC model) ----
    # EFC = total throughput / (2 × nominal capacity).
    # The 2× denominator accounts for both charge and discharge halves of each cycle.
    efc = battery_state.cumulative_throughput_kwh / (2.0 * nominal_capacity_kwh)
    cycle_fade_pct = capacity_fade_pct_per_efc * efc

    # ---- Calendar fade ----
    # cumulative_calendar_fade_pct is the total calendar capacity lost (%) from
    # simulation start, pre-computed by the simulator.  For a fixed rate:
    #   cumulative = rate × elapsed_years
    # For Arrhenius (temperature-dependent):
    #   cumulative = Σ_steps rate(T_i) × dt_i / 8760
    # Either way, we receive the total here — no elapsed_hours needed.
    calendar_fade_pct = max(0.0, float(cumulative_calendar_fade_pct))

    # ---- Combined SoH — max() rule, then clamped at EOL floor ----
    # All three fade mechanisms compete; the most advanced mechanism "wins."
    # HOMER Pro rule: "EOL by calendar or cycling degradation, whichever is greater."
    # Adding the three fades would double-count — max() is physically correct.
    # The EOL floor stops further degradation in the model; replacement economics
    # are handled separately by the evaluator via lifetime_years / throughput_kwh.
    dominant_fade_pct = max(cycle_fade_pct, calendar_fade_pct, dod_fade_pct)
    new_soh_pct = max(
        float(end_of_life_soh_pct),
        min(100.0, 100.0 - dominant_fade_pct),
    )

    # Scale effective capacity proportionally to SoH.
    new_effective_capacity_kwh = nominal_capacity_kwh * (new_soh_pct / 100.0)

    # ---- SOC reclamp ----
    # Absolute stored energy is unchanged; SOC% rises when capacity shrinks.
    # Cap at 100% (excess would be unphysical — treated as if battery is full).
    old_stored_kwh = battery_state.effective_capacity_kwh * (battery_state.soc_pct / 100.0)
    if new_effective_capacity_kwh > 0.0:
        new_soc_pct = min(100.0, 100.0 * old_stored_kwh / new_effective_capacity_kwh)
    else:
        new_soc_pct = 0.0

    return BatteryState(
        soc_pct=new_soc_pct,
        effective_capacity_kwh=new_effective_capacity_kwh,
        cumulative_throughput_kwh=battery_state.cumulative_throughput_kwh,
        soh_pct=new_soh_pct,
        # Cycle damage tracking is not modified by capacity fade — carried through.
        cumulative_cycle_damage=battery_state.cumulative_cycle_damage,
        half_cycle_soc_pct=battery_state.half_cycle_soc_pct,
        half_cycle_direction=battery_state.half_cycle_direction,
    )


# ============================================================
# SECTION 3 — TEMPERATURE CAPACITY CORRECTION
# ============================================================

# Boltzmann constant (eV/K) — used for Arrhenius calendar aging scaling.
_KB_EV_PER_K: float = 8.617333e-5


def compute_arrhenius_calendar_rate(
    *,
    base_calendar_fade_pct_per_year: float,
    ambient_temperature_c: float,
    activation_energy_ev: float,
    reference_temperature_c: float = 25.0,
) -> float:
    """
    Scale a fixed calendar fade rate by the Arrhenius temperature factor.

    Returns the effective calendar fade rate (%/year) at the given ambient temperature.
    Multiply by (time_step_hours / 8760) to get the per-step fade contribution.

    FORMULA
    -------
    The normalised Arrhenius scaling factor (relative to reference temperature):

        scale(T) = exp( Ea/kB × (1/T_ref_K − 1/T_K) )

    where Ea is activation energy (eV), kB is Boltzmann constant (eV/K).

    This form has a useful property: at T = T_ref the exponent is zero → scale = 1.0,
    so the base rate is returned unchanged at the reference temperature.

    WHY NORMALISED FORM
    -------------------
    HOMER Pro's ASM uses B×exp(−Ea/kBT) with a pre-exponential B whose units depend
    on the specific aging model (often s^−0.5 for a diffusion-limited fit).  The
    normalised form avoids requiring the user to know B from a lab-fit — they only
    need Ea and the rate at their reference temperature.  The two are equivalent if
    the user sets base_rate = B×exp(−Ea/(kB×T_ref)).

    TYPICAL VALUES
    --------------
    Li-Ion NMC/NCA: Ea ≈ 0.7 eV (Schmalstieg et al. 2014, J. Power Sources 309:86-95)
    LFP:            Ea ≈ 0.6 eV
    At T_ref = 25°C with Ea = 0.7 eV:
        T = 35°C → scale ≈ 1.8  (80% faster)
        T = 45°C → scale ≈ 3.2  (3× faster)
        T =  0°C → scale ≈ 0.09 (90% slower)

    Parameters
    ----------
    base_calendar_fade_pct_per_year : float
        Nominal calendar fade rate (%/year) at reference_temperature_c.
    ambient_temperature_c : float
        Current ambient temperature (°C) from the resource data.
    activation_energy_ev : float
        Arrhenius activation energy (eV).
    reference_temperature_c : float
        Temperature (°C) at which base_calendar_fade_pct_per_year was measured.
        Default 25°C (standard lab conditions).

    Returns
    -------
    float
        Effective calendar fade rate (%/year) at ambient_temperature_c.
    """
    t_k = ambient_temperature_c + 273.15
    t_ref_k = reference_temperature_c + 273.15

    # Guard against physically impossible temperatures that could cause division by zero.
    if t_k <= 0.0 or t_ref_k <= 0.0:
        return base_calendar_fade_pct_per_year

    exponent = (activation_energy_ev / _KB_EV_PER_K) * (1.0 / t_ref_k - 1.0 / t_k)
    scale = math.exp(exponent)
    return base_calendar_fade_pct_per_year * scale


def compute_temperature_correction_factor(
    *,
    ambient_temperature_c: float,
    d0: float,
    d1: float,
    d2: float,
) -> float:
    """
    Compute the reversible temperature capacity correction factor.

    Formula (HOMER Pro Advanced Storage Model — Temperature Effects):
        factor = d0 + d1×T + d2×T²
    where T is ambient temperature in °C.

    The factor is clamped to [0.01, 1.0]:
    - Cannot exceed 1.0: temperature cannot raise capacity above its rated value.
    - Cannot go below 0.01: prevents zero/negative capacity at extreme cold.

    HOMER Pro Generic Li-Ion defaults: d0=0.923, d1=0.00345, d2=-3.75e-05.

    Returns
    -------
    float
        Dimensionless correction factor to multiply against effective_capacity_kwh.
        Apply as: dispatch_capacity = battery_state.effective_capacity_kwh × factor.
    """
    t = float(ambient_temperature_c)
    factor = d0 + d1 * t + d2 * t * t
    # Clamp: temperature cannot give the battery more than its rated capacity,
    # and a factor ≤ 0 would make dispatch nonsensical.
    return max(0.01, min(1.0, factor))


# ============================================================
# SECTION 4 — DOD-BASED CYCLE DAMAGE (MINER'S RULE)
# ============================================================

def accumulate_cycle_damage(
    *,
    battery_state: BatteryState,
    soc_before_step: float,
    battery_charge_kw: float,
    battery_discharge_kw: float,
    cycle_life_a: float,
    cycle_life_beta: float,
) -> BatteryState:
    """
    Detect half-cycle completions and accumulate Miner's rule fatigue damage.

    Call this AFTER each dispatch step (when direction of charging/discharging is known)
    and BEFORE apply_capacity_fade() so that the damage is reflected in the same step.

    HALF-CYCLE MODEL
    ----------------
    A "half-cycle" is one continuous charge or discharge run.  A full cycle =
    one charge + one discharge.  Miner's rule sums fractional damage from each
    half-cycle; at total damage = 1.0 the battery reaches end of life by cycling.

    When the battery switches from charging to discharging (or vice versa), the
    just-completed half-cycle is closed:
        DoD      = |soc_at_reversal − soc_at_start_of_half_cycle| / 100
        damage   = 0.5 / N(DoD)   where N(DoD) = cycle_life_a × DoD^(−cycle_life_beta)
        ∴ damage = 0.5 × DoD^cycle_life_beta / cycle_life_a

    A new half-cycle then starts from the reversal point.

    WHY 0.5 AND NOT 1.0
    --------------------
    N(DoD) is defined in terms of FULL cycles.  Each direction reversal closes one
    HALF of a full cycle, so the fractional damage per half-cycle is 0.5 / N(DoD).

    IDLE TIMESTEPS
    --------------
    When the battery neither charges nor discharges (idle), the current half-cycle
    remains open — idle periods are not direction reversals.

    Parameters
    ----------
    battery_state : BatteryState
        State entering this step (contains half_cycle tracking fields).
    soc_before_step : float
        SOC (%) at the very start of this timestep (pre-dispatch).
        Used as the endpoint of a just-completed half-cycle and the start of the new one.
    battery_charge_kw : float
        Charge power this step (from DispatchResult).  > 0 means charging.
    battery_discharge_kw : float
        Discharge power this step (from DispatchResult).  > 0 means discharging.
    cycle_life_a : float
        Cycles to failure at 100% DoD (config param).  Must be > 0.
    cycle_life_beta : float
        Power-law exponent (config param).  Must be > 0.

    Returns
    -------
    BatteryState with updated cumulative_cycle_damage, half_cycle_soc_pct,
    half_cycle_direction.  All other fields carried through unchanged.
    """
    # Determine this step's direction.
    if battery_charge_kw > 0.0:
        current_direction = 1     # charging
    elif battery_discharge_kw > 0.0:
        current_direction = -1    # discharging
    else:
        current_direction = 0     # idle — no direction change

    prev_direction = battery_state.half_cycle_direction
    cumulative_damage = battery_state.cumulative_cycle_damage
    half_cycle_soc = battery_state.half_cycle_soc_pct

    # --- Not yet tracking: first active step ---
    if half_cycle_soc < 0.0:
        if current_direction != 0:
            # Start tracking from the SOC at the beginning of this step.
            return BatteryState(
                soc_pct=battery_state.soc_pct,
                effective_capacity_kwh=battery_state.effective_capacity_kwh,
                cumulative_throughput_kwh=battery_state.cumulative_throughput_kwh,
                soh_pct=battery_state.soh_pct,
                cumulative_cycle_damage=cumulative_damage,
                half_cycle_soc_pct=soc_before_step,
                half_cycle_direction=current_direction,
            )
        # Still idle — nothing to do.
        return battery_state

    # --- Direction reversal: close the current half-cycle ---
    new_damage = cumulative_damage
    new_half_soc = half_cycle_soc
    new_direction = prev_direction  # default: keep current

    if (
        current_direction != 0
        and prev_direction != 0
        and current_direction != prev_direction
    ):
        # Half-cycle just completed: from half_cycle_soc to soc_before_step.
        dod = abs(soc_before_step - half_cycle_soc) / 100.0
        if dod > 1e-6 and cycle_life_a > 0.0:
            # Miner's rule: damage = 0.5 / N(DoD) = 0.5 × DoD^beta / A.
            # The minimum DoD guard avoids log(0) and meaningless micro-cycles.
            half_cycle_damage = 0.5 * (dod ** cycle_life_beta) / cycle_life_a
            new_damage = cumulative_damage + half_cycle_damage

        # Start the new half-cycle from the reversal point.
        new_half_soc = soc_before_step
        new_direction = current_direction

    elif current_direction != 0:
        # Same direction (or transitioning from idle): keep the half-cycle open.
        new_direction = current_direction

    return BatteryState(
        soc_pct=battery_state.soc_pct,
        effective_capacity_kwh=battery_state.effective_capacity_kwh,
        cumulative_throughput_kwh=battery_state.cumulative_throughput_kwh,
        soh_pct=battery_state.soh_pct,
        cumulative_cycle_damage=new_damage,
        half_cycle_soc_pct=new_half_soc,
        half_cycle_direction=new_direction,
    )


# ============================================================
# SECTION 5 — SELF-DISCHARGE
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
# SECTION 6 — EFFICIENCY HELPERS
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
# SECTION 7 — CURRENT-BASED POWER LIMIT HELPERS
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
# SECTION 8 — MAIN BATTERY STEP UPDATE
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
