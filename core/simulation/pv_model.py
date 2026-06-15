from __future__ import annotations

# ============================================================
# core/simulation/pv_model.py
#
# Purpose:
#   PV generation model for hourly hybrid simulation.
#
# What this file does:
#   1. Resolve panel tilt and azimuth from config
#   2. Compute POA irradiance via Erbs decomposition + HDKR tilted-plane model
#   3. Compute PV cell temperature using NOCT method
#   4. Compute HOMER-style PV output with optional temperature correction
#   5. Provide a clean per-hour PV result object
# ============================================================

import math
from dataclasses import dataclass
from typing import Any

import pandas as pd

from core.components.pv import PVComponentConfig


# ============================================================
# CONSTANTS
# ============================================================

G_STC_KW_PER_M2: float = 1.0
T_CELL_STC_C: float = 25.0

# Small tolerance to guard against divide-by-zero
EPSILON: float = 1e-9

# Solar constant (W/m²) used for extraterrestrial radiation
SOLAR_CONSTANT_W_M2: float = 1367.0


# ============================================================
# RESULT OBJECT
# ============================================================

@dataclass(frozen=True)
class PVPowerResult:
    """Result of PV power calculation for one timestep."""

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
    """Convert to float safely; return default on failure."""
    try:
        if pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp_non_negative(value: float) -> float:
    return max(0.0, float(value))


def _percent_to_fraction(percent_value: float) -> float:
    return float(percent_value) / 100.0


def _normalize_irradiance_to_kw_per_m2(irradiance_value: float) -> float:
    """
    Normalize irradiance from W/m² to kW/m².
    All resource-file irradiance values are assumed to be in W/m².
    """
    irradiance_value = _safe_float(irradiance_value, default=0.0)
    if irradiance_value <= 0.0:
        return 0.0
    return irradiance_value / 1000.0


def _extract_irradiance_from_row(row: pd.Series) -> float:
    """
    Extract GHI (W/m²) from a resource row.

    Priority: poa > ghi > ghi_kw_m2 > irradiance > irradiance_kw_m2
    """
    for col in ("poa", "poa_irradiance", "poa_kw_m2", "ghi", "ghi_kw_m2",
                "irradiance", "irradiance_kw_m2"):
        if col in row.index:
            return _safe_float(row[col], default=0.0)
    return 0.0


def _extract_ambient_temperature_from_row(row: pd.Series) -> float:
    """Extract ambient temperature (°C) from a resource row."""
    for col in ("temperature", "temperature_c", "temp_c", "ambient_temperature_c"):
        if col in row.index:
            return _safe_float(row[col], default=25.0)
    return 25.0


# ============================================================
# SOLAR GEOMETRY
# ============================================================

def _day_of_year(timestamp: pd.Timestamp) -> int:
    return int(timestamp.dayofyear)


def _solar_declination_deg(day_of_year: int) -> float:
    """Solar declination (degrees) via Cooper's equation."""
    return 23.45 * math.sin(math.radians(360.0 / 365.0 * (284 + day_of_year)))


def _equation_of_time_hours(day_of_year: int) -> float:
    """
    Equation of time in hours — Spencer approximation.

    E [min] = 9.87 sin2B − 7.53 cosB − 1.5 sinB  →  divide by 60 for hours.

    Note: the D&B / HOMER-documented formula (3.82×...) is more accurate
    astronomically, but empirical testing shows HOMER's internal PV calculation
    behaves closer to this Spencer form (switching to D&B increased the tilted-
    panel error from +0.39% to +2.85% vs HOMER). We keep Spencer here so that
    solar-geometry output matches HOMER's observable results.
    """
    B = math.radians(360.0 / 365.0 * (day_of_year - 1))
    eot_minutes = (9.87 * math.sin(2 * B)
                   - 7.53 * math.cos(B)
                   - 1.5  * math.sin(B))
    return eot_minutes / 60.0


def _solar_hour_angle_deg(
    timestamp: pd.Timestamp,
    longitude_deg: float,
    timezone_offset_hours: float = 0.0,
) -> float:
    """
    Solar hour angle (degrees) at the centre of the hour interval.

    Resource timestamps are in civil/local standard time (e.g. IST = UTC+5.5).
    The HOMER solar-time formula is:  ts = tc + λ/15 − Zc + EoT
    where tc is civil time, λ is longitude, Zc is hours east of UTC.
    """
    civil_hour = timestamp.hour + timestamp.minute / 60.0 + 0.5
    eot_hours  = _equation_of_time_hours(timestamp.dayofyear)
    solar_time = civil_hour + longitude_deg / 15.0 - timezone_offset_hours + eot_hours
    return (solar_time - 12.0) * 15.0


def _extraterrestrial_radiation_w_m2(day_of_year: int) -> float:
    """
    Extraterrestrial solar radiation G_on (W/m²) — HOMER's documented D&B formula.

    G_on = G_sc × (1 + 0.033 × cos(360n/365))

    Matches resources.py and HOMER. The old 5-term Spencer eccentricity differed
    by up to ±0.22%, which compounded the EoT error on tilted panels.
    """
    B = math.radians(360.0 / 365.0 * (day_of_year - 1))
    return SOLAR_CONSTANT_W_M2 * (1.0 + 0.033 * math.cos(B))


def _cos_zenith(lat_r: float, dec_r: float, omega_r: float) -> float:
    """cos(solar zenith angle)."""
    return (math.sin(lat_r) * math.sin(dec_r)
            + math.cos(lat_r) * math.cos(dec_r) * math.cos(omega_r))


def _cos_angle_of_incidence(
    lat_r: float,
    dec_r: float,
    omega_r: float,
    slope_r: float,
    surface_az_r: float,  # D&B: 0=south, +west, -east
) -> float:
    """
    cos(angle of incidence) for a tilted surface.
    D&B 4th ed., Eq. 1.6.2.
    """
    sd = math.sin(dec_r);   cd = math.cos(dec_r)
    sp = math.sin(lat_r);   cp = math.cos(lat_r)
    co = math.cos(omega_r); so = math.sin(omega_r)
    cb = math.cos(slope_r); sb = math.sin(slope_r)
    cg = math.cos(surface_az_r); sg = math.sin(surface_az_r)
    return (sd * sp * cb
            - sd * cp * sb * cg
            + cd * cp * cb * co
            + cd * sp * sb * cg * co
            + cd * sb * sg * so)


def _integrated_g0_h_w_m2(
    lat_r: float,
    dec_r: float,
    g_on: float,
    omega_center_r: float,
) -> float:
    """
    Time-averaged extraterrestrial horizontal irradiance (W/m²) over one hourly timestep.

    Implements D&B 4th ed. Eq. 2.12.1 with the daylight-window clip (ω1/ω2 → ±ωs):
        Ḡ_o = (12/π) × G_on × [cos(φ)cos(δ)(sin(ω2)−sin(ω1)) + (ω2−ω1)sin(φ)sin(δ)]

    Clipping to ±ωs is essential for sunrise/sunset hours — without it the
    nighttime half of the timestep drags down Ḡ₀, inflating kt, which shifts
    Erbs toward more beam, and that extra beam is amplified by R_b on a south-
    facing tilted panel.  Across ~730 partial-daylight hours/year this
    un-clipped approach over-predicted annual tilt gain by ~0.77%.
    This matches resources.py and the standard D&B/HOMER convention.
    """
    half_step_r = math.pi / 24.0  # 7.5° = half of 15°/hr
    omega1_r = omega_center_r - half_step_r
    omega2_r = omega_center_r + half_step_r

    # Clip integration limits to the daylight window ±ωs (D&B convention)
    cos_ws = -math.tan(lat_r) * math.tan(dec_r)
    if cos_ws >= 1.0:
        return 0.0  # polar night
    omega_s_r = math.pi if cos_ws <= -1.0 else math.acos(cos_ws)  # sunrise/sunset hour angle

    omega1_r = max(omega1_r, -omega_s_r)
    omega2_r = min(omega2_r,  omega_s_r)

    if omega2_r <= omega1_r:
        return 0.0  # full nighttime timestep

    g0_avg = (12.0 / math.pi) * g_on * (
        math.cos(lat_r) * math.cos(dec_r) * (math.sin(omega2_r) - math.sin(omega1_r))
        + (omega2_r - omega1_r) * math.sin(lat_r) * math.sin(dec_r)
    )
    return max(0.0, g0_avg)


# ============================================================
# ERBS DIFFUSE DECOMPOSITION
# ============================================================

def _erbs_diffuse_fraction(kt: float) -> float:
    """
    Diffuse fraction f_d from clearness index kt (Erbs et al. 1982).

    Returns the fraction of GHI that is diffuse.
    """
    if kt <= 0.22:
        return 1.0 - 0.09 * kt
    if kt <= 0.80:
        return (0.9511 - 0.1604 * kt + 4.388 * kt ** 2
                - 16.638 * kt ** 3 + 12.336 * kt ** 4)
    return 0.165


# ============================================================
# PANEL ANGLE RESOLUTION
# ============================================================

def _resolve_panel_angles(
    pv_config: PVComponentConfig,
    latitude_deg: float,
) -> tuple[float, float]:
    """
    Return (slope_deg, surface_azimuth_D&B_deg).

    HOMER PV azimuth convention: "degrees West of South" — identical to D&B
    (0=south equator-facing, positive=west, negative=east).
    No conversion needed; store the value directly.
    """
    orient = pv_config.orientation

    slope_deg = (
        abs(latitude_deg)
        if (orient.use_default_slope or orient.panel_slope_deg is None)
        else float(orient.panel_slope_deg)
    )

    if orient.use_default_azimuth or orient.panel_azimuth_deg is None:
        surface_az_DnB = 0.0  # south-facing by default
    else:
        # HOMER PV "degrees West of South" == D&B convention directly (no offset)
        surface_az_DnB = float(orient.panel_azimuth_deg)

    return slope_deg, surface_az_DnB


# ============================================================
# HDKR TILTED-PLANE MODEL  (GHI → POA)
# ============================================================

def compute_poa_from_ghi(
    *,
    ghi_w_m2: float,
    timestamp: pd.Timestamp,
    latitude_deg: float,
    longitude_deg: float,
    slope_deg: float,
    surface_azimuth_D_and_B_deg: float,
    ground_reflectance_pct: float = 20.0,
    timezone_offset_hours: float = 0.0,
) -> float:
    """
    Convert GHI (W/m²) to plane-of-array irradiance (W/m²).

    Uses:
    - Erbs decomposition: GHI → beam_H + diffuse_H
    - HDKR model (Hay–Davies–Klucher–Reindl) for tilted-plane diffuse
    - Ground-reflected component via albedo

    Returns 0 when the sun is below the horizon or GHI ≤ 0.
    Returns GHI unchanged when slope is effectively zero (flat panel).
    """
    if ghi_w_m2 <= 0.0:
        return 0.0

    slope_r = math.radians(slope_deg)

    # Flat panel: POA equals GHI exactly
    if slope_r < EPSILON:
        return float(ghi_w_m2)

    lat_r = math.radians(latitude_deg)
    az_r  = math.radians(surface_azimuth_D_and_B_deg)

    day_n     = _day_of_year(timestamp)
    dec_r     = math.radians(_solar_declination_deg(day_n))
    omega_r   = math.radians(_solar_hour_angle_deg(timestamp, longitude_deg, timezone_offset_hours))

    cos_z = _cos_zenith(lat_r, dec_r, omega_r)

    # Sun below horizon
    if cos_z <= 0.0:
        return 0.0

    # Extraterrestrial radiation and clearness index for Erbs.
    # Use the time-step-integrated Ḡ_o (D&B Eq 2.12.1) — matches HOMER exactly.
    # The midpoint approximation G0×cos(θz) differs near sunrise/sunset and was
    # the source of the remaining ~0.16% annual PV generation gap.
    G0   = _extraterrestrial_radiation_w_m2(day_n)
    G0_h = _integrated_g0_h_w_m2(lat_r, dec_r, G0, omega_r)

    kt = ghi_w_m2 / G0_h if G0_h > EPSILON else 0.0
    kt = max(0.0, min(kt, 1.0))  # physical bounds

    fd = _erbs_diffuse_fraction(kt)
    diffuse_h = fd * ghi_w_m2
    beam_h    = max(0.0, ghi_w_m2 - diffuse_h)

    # Tilt factors
    # pvlib convention (GH 432 / GH 526): floor cos_z at cos(89°) so R_b never
    # blows up near the horizon.  Without this cap, the circumsolar diffuse term
    # (diffuse_h × Ai × R_b) is over-estimated at low sun angles, inflating
    # annual tilt gain by ~1.5–2 % relative to HOMER and every audited HDKR
    # implementation.  The floor corresponds to a zenith angle ceiling of 89°.
    _COS_Z_FLOOR = 0.01745  # cos(89°)
    cos_theta = _cos_angle_of_incidence(lat_r, dec_r, omega_r, slope_r, az_r)
    r_b = max(0.0, cos_theta) / max(cos_z, _COS_Z_FLOOR)

    # ── Beam POA ───────────────────────────────────────────────────────────────
    beam_poa = beam_h * r_b

    # ── HDKR diffuse POA ───────────────────────────────────────────────────────
    # Anisotropy index Ai — use instantaneous G_on × cos_z (normal basis, pvlib
    # convention) rather than integrated Ḡ₀.  The two are algebraically equal
    # for interior hours; for partial sunrise/sunset hours the integrated form
    # distorts Ai because Ḡ₀ ≠ G_on × cos_z at the midpoint.
    G0_h_instant = G0 * max(cos_z, _COS_Z_FLOOR)
    ai = min(1.0, beam_h / G0_h_instant) if G0_h_instant > EPSILON else 0.0

    # Horizon-brightening factor f
    f  = math.sqrt(beam_h / ghi_w_m2) if ghi_w_m2 > EPSILON else 0.0

    cos_beta     = math.cos(slope_r)
    sin_beta_half = math.sin(slope_r / 2.0)

    diffuse_poa = diffuse_h * (
        (1.0 - ai) * (1.0 + cos_beta) / 2.0 * (1.0 + f * sin_beta_half ** 3)
        + ai * r_b
    )

    # ── Ground-reflected POA ───────────────────────────────────────────────────
    rho          = ground_reflectance_pct / 100.0
    reflected_poa = ghi_w_m2 * rho * (1.0 - cos_beta) / 2.0

    return max(0.0, beam_poa + diffuse_poa + reflected_poa)


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
    PV cell temperature via NOCT approximation.

    Tc = Ta + ((NOCT − 20) / 800) × Gt(W/m²)
    """
    irradiance_w_per_m2 = _clamp_non_negative(irradiance_kw_per_m2) * 1000.0
    return float(ambient_temperature_c) + (
        (float(nominal_operating_cell_temp_c) - 20.0) / 800.0
    ) * irradiance_w_per_m2


def compute_temperature_correction_factor(
    *,
    cell_temperature_c: float,
    reference_cell_temp_c: float,
    temperature_coefficient_pct_per_degC: float,
    temperature_effect_enabled: bool,
) -> float:
    """
    HOMER-style temperature correction factor: 1 + αp × (Tc − Tc,STC).

    αp is stored in %/°C and converted to fraction/°C here.
    """
    if not temperature_effect_enabled:
        return 1.0

    alpha = _percent_to_fraction(temperature_coefficient_pct_per_degC)
    factor = 1.0 + alpha * (float(cell_temperature_c) - float(reference_cell_temp_c))
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
    HOMER PV equation: Ppv = Ypv × fpv × (Gt/Gstc) × (1 + αp × (Tc − Tc,stc))

    Returns (temperature_correction_factor, raw_power_kw, final_power_kw).
    """
    rated_capacity_kw              = _clamp_non_negative(rated_capacity_kw)
    derating_factor                = max(0.0, min(1.0, float(derating_factor)))
    irradiance_kw_per_m2           = _clamp_non_negative(irradiance_kw_per_m2)
    reference_irradiance_kw_per_m2 = max(EPSILON, float(reference_irradiance_kw_per_m2))

    temp_factor = compute_temperature_correction_factor(
        cell_temperature_c=cell_temperature_c,
        reference_cell_temp_c=reference_cell_temp_c,
        temperature_coefficient_pct_per_degC=temperature_coefficient_pct_per_degC,
        temperature_effect_enabled=temperature_effect_enabled,
    )

    raw_power_kw   = (rated_capacity_kw * derating_factor
                      * (irradiance_kw_per_m2 / reference_irradiance_kw_per_m2)
                      * temp_factor)
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
    Compute PV power for a single timestep given irradiance in W/m².

    Parameters
    ----------
    irradiance_input_value:
        Effective irradiance (W/m²) — either GHI or POA, already corrected.
    ambient_temperature_c:
        Ambient temperature (°C).
    pv_config:
        PV component configuration.
    selected_capacity_kw:
        Override capacity; defaults to max option if None.
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

    irradiance_kw_per_m2   = _normalize_irradiance_to_kw_per_m2(irradiance_input_value)
    ambient_temperature_c  = _safe_float(ambient_temperature_c, default=25.0)
    temperature_settings   = pv_config.temperature

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
    latitude_deg: float | None = None,
    longitude_deg: float | None = None,
    timezone_offset_hours: float = 0.0,
) -> PVPowerResult:
    """
    Compute PV power from one row of the resource dataframe.

    Irradiance pipeline:
    1. Apply clearness-index cap to raw GHI if configured (removes NASA POWER
       sunrise/sunset artifacts where GHI briefly exceeds G0).
    2. If latitude, longitude, and a timestamp are available, convert effective
       GHI to plane-of-array irradiance using Erbs + HDKR.  Otherwise use
       effective GHI directly (flat-panel or data-less fallback).
    """
    ambient_temperature_c = _extract_ambient_temperature_from_row(resource_row)
    orientation = pv_config.orientation

    # ── Step 1: effective GHI (with optional clearness-index cap) ──────────────
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
        effective_ghi_w_m2 = min(kt, kt_cap) * g0
    else:
        effective_ghi_w_m2 = _extract_irradiance_from_row(resource_row)

    # ── Step 2: GHI → POA (when lat/lon and timestamp are available) ──────────
    if (
        latitude_deg is not None
        and longitude_deg is not None
        and "timestamp" in resource_row.index
    ):
        ts_raw = resource_row["timestamp"]
        if not pd.isna(ts_raw):
            slope_deg, az_DnB = _resolve_panel_angles(pv_config, float(latitude_deg))
            irradiance_input_value = compute_poa_from_ghi(
                ghi_w_m2=effective_ghi_w_m2,
                timestamp=pd.Timestamp(ts_raw),
                latitude_deg=float(latitude_deg),
                longitude_deg=float(longitude_deg),
                slope_deg=slope_deg,
                surface_azimuth_D_and_B_deg=az_DnB,
                ground_reflectance_pct=orientation.ground_reflectance_pct,
                timezone_offset_hours=timezone_offset_hours,
            )
        else:
            irradiance_input_value = effective_ghi_w_m2
    else:
        irradiance_input_value = effective_ghi_w_m2

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
    latitude_deg: float | None = None,
    longitude_deg: float | None = None,
    timezone_offset_hours: float = 0.0,
) -> pd.DataFrame:
    """
    Simulate PV generation for the full resource dataframe.

    Returns a dataframe with columns:
    irradiance_input_value, irradiance_used_kw_per_m2,
    ambient_temperature_c, cell_temperature_c,
    temperature_correction_factor, pv_power_kw
    """
    records: list[dict[str, float]] = []

    for _, row in resource_df.iterrows():
        result = compute_pv_power_from_resource_row(
            resource_row=row,
            pv_config=pv_config,
            selected_capacity_kw=selected_capacity_kw,
            latitude_deg=latitude_deg,
            longitude_deg=longitude_deg,
            timezone_offset_hours=timezone_offset_hours,
        )
        records.append({
            "irradiance_input_value":      result.irradiance_input_value,
            "irradiance_used_kw_per_m2":   result.irradiance_used_kw_per_m2,
            "ambient_temperature_c":       result.ambient_temperature_c,
            "cell_temperature_c":          result.cell_temperature_c,
            "temperature_correction_factor": result.temperature_correction_factor,
            "pv_power_kw":                 result.net_power_kw,
        })

    out = pd.DataFrame(records)

    if "timestamp" in resource_df.columns:
        out.insert(0, "timestamp", resource_df["timestamp"].values)

    return out
