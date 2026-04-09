from __future__ import annotations

# ============================================================
# core/simulation/pv_model.py
#
# Purpose:
#   PV generation model for hourly hybrid simulation.
#
# What this file does:
#   1. Compute effective irradiance for the PV array
#   2. Compute PV cell temperature using NOCT method
#   3. Compute HOMER-style PV output with temperature correction
#   4. Provide a clean per-hour PV result object
#
# What this file does NOT do:
#   - full solar geometry / declination / hour angle
#   - Erbs decomposition
#   - HDKR tilted-plane model
#   - converter losses
#   - dispatch decisions
#
# Why:
#   This is the correct next step for your simulator:
#   implement the core HOMER-like PV physics first, and
#   add solar geometry later only if needed.
# ============================================================

from dataclasses import dataclass
from typing import Any

import pandas as pd

from core.components.pv import PVComponentConfig


# ============================================================
# CONSTANTS
# ============================================================

G_STC_KW_PER_M2: float = 1.0
T_CELL_STC_C: float = 25.0

# Very small tolerance to avoid floating issues
EPSILON: float = 1e-9


# ============================================================
# RESULT OBJECT
# ============================================================

@dataclass(frozen=True)
class PVPowerResult:
    """
    Result of PV power calculation for one timestep.
    """

    irradiance_input_value: float
    irradiance_used_kw_per_m2: float
    ambient_temperature_c: float
    cell_temperature_c: float
    rated_capacity_kw: float
    derating_factor: float
    temperature_correction_factor: float
    raw_power_kw: float
    net_power_kw: float


# ============================================================
# INTERNAL HELPERS
# ============================================================

def _safe_float(value: Any, default: float = 0.0) -> float:
    """
    Convert to float safely. If conversion fails, return default.
    """
    try:
        if pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp_non_negative(value: float) -> float:
    """
    Clamp a numeric value to be >= 0.
    """
    return max(0.0, float(value))


def _percent_to_fraction(percent_value: float) -> float:
    """
    Convert percent to fraction.
    Example:
        95 -> 0.95
        -0.5 -> -0.005
    """
    return float(percent_value) / 100.0


def _normalize_irradiance_to_kw_per_m2(irradiance_value: float) -> float:
    """
    Normalize irradiance into kW/m².

    Assumption (FIXED for Case 1):
    - All input irradiance is in W/m²
    - Convert to kW/m²

    This removes all ambiguity and ensures consistency with NASA POWER
    and HOMER inputs.
    """
    irradiance_value = _safe_float(irradiance_value, default=0.0)

    if irradiance_value <= 0.0:
        return 0.0

    # Always treat as W/m²
    return irradiance_value / 1000.0

def _extract_irradiance_from_row(row: pd.Series) -> float:
    """
    Extract irradiance from a resource row.

    Priority:
    1. poa
    2. ghi
    3. ghi_kw_m2
    4. irradiance
    5. irradiance_kw_m2

    Returns irradiance in kW/m² after normalization.
    """
    candidate_columns = [
        "poa",
        "poa_irradiance",
        "poa_kw_m2",
        "ghi",
        "ghi_kw_m2",
        "irradiance",
        "irradiance_kw_m2",
    ]

    for col in candidate_columns:
        if col in row.index:
            return _safe_float(row[col], default=0.0)

    return 0.0


def _extract_ambient_temperature_from_row(row: pd.Series) -> float:
    """
    Extract ambient temperature from a resource row.

    Priority:
    1. temperature
    2. temperature_c
    3. temp_c
    4. ambient_temperature_c
    """
    candidate_columns = [
        "temperature",
        "temperature_c",
        "temp_c",
        "ambient_temperature_c",
    ]

    for col in candidate_columns:
        if col in row.index:
            return _safe_float(row[col], default=25.0)

    return 25.0


# ============================================================
# CORE PV FUNCTIONS
# ============================================================

def compute_cell_temperature_c(
    *,
    ambient_temperature_c: float,
    irradiance_kw_per_m2: float,
    nominal_operating_cell_temp_c: float,
) -> float:
    """
    Compute PV cell temperature using NOCT-based approximation.

    Formula:
        Tc = Ta + ((NOCT - 20) / 800) * Gt(W/m²)

    Since this function takes irradiance in kW/m²,
    internally it converts to W/m².

    Notes:
    - This is the practical engineering approximation commonly
      used in PV simulation.
    - This is the right level for your current simulator stage.
    """
    ambient_temperature_c = float(ambient_temperature_c)
    irradiance_kw_per_m2 = _clamp_non_negative(irradiance_kw_per_m2)
    nominal_operating_cell_temp_c = float(nominal_operating_cell_temp_c)

    irradiance_w_per_m2 = irradiance_kw_per_m2 * 1000.0

    return ambient_temperature_c + (
        (nominal_operating_cell_temp_c - 20.0) / 800.0
    ) * irradiance_w_per_m2


def compute_temperature_correction_factor(
    *,
    cell_temperature_c: float,
    reference_cell_temp_c: float,
    temperature_coefficient_pct_per_degC: float,
    temperature_effect_enabled: bool,
) -> float:
    """
    Compute PV temperature correction factor.

    HOMER-style factor:
        1 + alpha_p * (Tc - Tc,stc)

    where alpha_p is used as a fraction per °C.

    In your config it is stored in percent per °C,
    for example:
        -0.5 means -0.5 % / °C
    so we convert it to:
        -0.005 / °C
    """
    if not temperature_effect_enabled:
        return 1.0

    alpha_fraction_per_degC = _percent_to_fraction(
        temperature_coefficient_pct_per_degC
    )

    factor = 1.0 + alpha_fraction_per_degC * (
        float(cell_temperature_c) - float(reference_cell_temp_c)
    )

    # Prevent negative output due to extreme/unrealistic temperatures
    return max(0.0, factor)


def compute_pv_power_output(
    *,
    rated_capacity_kw: float,
    derating_factor: float,
    irradiance_kw_per_m2: float,
    reference_irradiance_kw_per_m2: float,
    cell_temperature_c: float,
    reference_cell_temp_c: float,
    temperature_coefficient_pct_per_degC: float,
    temperature_effect_enabled: bool,
) -> tuple[float, float, float]:
    """
    Compute PV output using HOMER-style PV equation.

    Equation:
        Ppv = Ypv * fpv * (Gt / Gstc) * (1 + alpha_p * (Tc - Tc,stc))

    Returns:
        (
            temperature_correction_factor,
            raw_power_before_clamp_kw,
            final_power_kw,
        )
    """
    rated_capacity_kw = _clamp_non_negative(rated_capacity_kw)
    derating_factor = max(0.0, min(1.0, float(derating_factor)))
    irradiance_kw_per_m2 = _clamp_non_negative(irradiance_kw_per_m2)
    reference_irradiance_kw_per_m2 = max(
        EPSILON,
        float(reference_irradiance_kw_per_m2),
    )

    temp_factor = compute_temperature_correction_factor(
        cell_temperature_c=cell_temperature_c,
        reference_cell_temp_c=reference_cell_temp_c,
        temperature_coefficient_pct_per_degC=temperature_coefficient_pct_per_degC,
        temperature_effect_enabled=temperature_effect_enabled,
    )

    raw_power_kw = (
        rated_capacity_kw
        * derating_factor
        * (irradiance_kw_per_m2 / reference_irradiance_kw_per_m2)
        * temp_factor
    )

    final_power_kw = max(0.0, raw_power_kw)

    return temp_factor, raw_power_kw, final_power_kw


# ============================================================
# PROJECT-FACING API
# ============================================================

def compute_pv_power_for_timestep(
    *,
    irradiance_input_value: float,
    ambient_temperature_c: float,
    pv_config: PVComponentConfig,
    selected_capacity_kw: float | None = None,
) -> PVPowerResult:
    """
    Compute PV power for a single timestep.

    Parameters
    ----------
    irradiance_input_value:
        Irradiance from resource data. Can be in kW/m² or W/m².
    ambient_temperature_c:
        Ambient temperature in °C.
    pv_config:
        PV component config from your project.
    selected_capacity_kw:
        Specific PV size to simulate. If None, the maximum configured
        capacity option is used.

    Returns
    -------
    PVPowerResult
    """
    if not pv_config.enabled:
        return PVPowerResult(
            irradiance_input_value=_safe_float(irradiance_input_value, 0.0),
            irradiance_used_kw_per_m2=0.0,
            ambient_temperature_c=_safe_float(ambient_temperature_c, 25.0),
            cell_temperature_c=_safe_float(ambient_temperature_c, 25.0),
            rated_capacity_kw=0.0,
            derating_factor=float(pv_config.derating_factor),
            temperature_correction_factor=1.0,
            raw_power_kw=0.0,
            net_power_kw=0.0,
        )

    rated_capacity_kw = (
        max(pv_config.capacity_kw_options)
        if selected_capacity_kw is None
        else float(selected_capacity_kw)
    )

    irradiance_kw_per_m2 = _normalize_irradiance_to_kw_per_m2(
        irradiance_input_value
    )
    ambient_temperature_c = _safe_float(ambient_temperature_c, default=25.0)

    temperature_settings = pv_config.temperature

    if temperature_settings.enabled:
        cell_temperature_c = compute_cell_temperature_c(
            ambient_temperature_c=ambient_temperature_c,
            irradiance_kw_per_m2=irradiance_kw_per_m2,
            nominal_operating_cell_temp_c=temperature_settings.nominal_operating_cell_temp_c,
        )
    else:
        cell_temperature_c = ambient_temperature_c

    temp_factor, raw_power_kw, final_power_kw = compute_pv_power_output(
        rated_capacity_kw=rated_capacity_kw,
        derating_factor=pv_config.derating_factor,
        irradiance_kw_per_m2=irradiance_kw_per_m2,
        reference_irradiance_kw_per_m2=G_STC_KW_PER_M2,
        cell_temperature_c=cell_temperature_c,
        reference_cell_temp_c=T_CELL_STC_C,
        temperature_coefficient_pct_per_degC=temperature_settings.temperature_coefficient_pct_per_degC,
        temperature_effect_enabled=temperature_settings.enabled,
    )

    return PVPowerResult(
        irradiance_input_value=_safe_float(irradiance_input_value, 0.0),
        irradiance_used_kw_per_m2=irradiance_kw_per_m2,
        ambient_temperature_c=ambient_temperature_c,
        cell_temperature_c=cell_temperature_c,
        rated_capacity_kw=rated_capacity_kw,
        derating_factor=float(pv_config.derating_factor),
        temperature_correction_factor=temp_factor,
        raw_power_kw=raw_power_kw,
        net_power_kw=final_power_kw,
    )


def compute_pv_power_from_resource_row(
    *,
    resource_row: pd.Series,
    pv_config: PVComponentConfig,
    selected_capacity_kw: float | None = None,
) -> PVPowerResult:
    """
    Compute PV power directly from one row of the resource dataframe.

    If pv_config.orientation.use_clearness_index_cap is True AND the resource
    row contains 'clearness_index' and 'g0_w_m2' columns (pre-computed by
    add_clearness_index in resources.py), then effective GHI is computed as:

        GHI_eff = min(Kt, kt_max) * G0

    This replicates HOMER's internal GHI processing using the same EoT formula.
    Otherwise raw GHI is used as-is.
    """
    ambient_temperature_c = _extract_ambient_temperature_from_row(resource_row)

    orientation = pv_config.orientation
    use_kt = (
        orientation.use_clearness_index_cap
        and "clearness_index" in resource_row.index
        and "g0_w_m2" in resource_row.index
    )

    if use_kt:
        kt     = _safe_float(resource_row["clearness_index"], default=0.0)
        g0     = _safe_float(resource_row["g0_w_m2"], default=0.0)
        kt_cap = float(orientation.kt_max)
        # Effective GHI (W/m²) = capped Kt × G0
        irradiance_input_value = min(kt, kt_cap) * g0
    else:
        irradiance_input_value = _extract_irradiance_from_row(resource_row)

    return compute_pv_power_for_timestep(
        irradiance_input_value=irradiance_input_value,
        ambient_temperature_c=ambient_temperature_c,
        pv_config=pv_config,
        selected_capacity_kw=selected_capacity_kw,
    )


def simulate_pv_timeseries(
    *,
    resource_df: pd.DataFrame,
    pv_config: PVComponentConfig,
    selected_capacity_kw: float | None = None,
) -> pd.DataFrame:
    """
    Simulate PV generation for the full resource dataframe.

    Returns a dataframe with:
    - irradiance_input_value
    - irradiance_used_kw_per_m2
    - ambient_temperature_c
    - cell_temperature_c
    - temperature_correction_factor
    - pv_power_kw
    """
    records: list[dict[str, float]] = []

    for _, row in resource_df.iterrows():
        result = compute_pv_power_from_resource_row(
            resource_row=row,
            pv_config=pv_config,
            selected_capacity_kw=selected_capacity_kw,
        )

        records.append(
            {
                "irradiance_input_value": result.irradiance_input_value,
                "irradiance_used_kw_per_m2": result.irradiance_used_kw_per_m2,
                "ambient_temperature_c": result.ambient_temperature_c,
                "cell_temperature_c": result.cell_temperature_c,
                "temperature_correction_factor": result.temperature_correction_factor,
                "pv_power_kw": result.net_power_kw,
            }
        )

    out = pd.DataFrame(records)

    if "timestamp" in resource_df.columns:
        out.insert(0, "timestamp", resource_df["timestamp"].values)

    return out