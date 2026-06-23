"""
tests/test_pv_transposition_compare.py

Compare annual PV generation between:
  - HDKR (current model)
  - Isotropic / Liu-Jordan (HOMER Pro's model)

Uses test10 (Dhule) resource data so results are directly comparable to HOMER.
"""
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import math
import pandas as pd

from core.simulation.pv_model import (
    _integrated_g0_h_w_m2, _extraterrestrial_radiation_w_m2,
    _solar_declination_deg, _equation_of_time_hours, _solar_hour_angle_deg,
    _cos_zenith, _cos_angle_of_incidence, _erbs_diffuse_fraction,
    _resolve_panel_angles, compute_cell_temperature_c,
    compute_pv_power_output, compute_pv_power_from_resource_row,
    EPSILON,
)
from core.simulation.run_project_simulation import load_project_simulation_inputs


def _compute_poa_isotropic(
    ghi_w_m2: float,
    timestamp: pd.Timestamp,
    latitude_deg: float,
    longitude_deg: float,
    slope_deg: float,
    surface_az_DnB_deg: float,
    ground_reflectance_pct: float = 20.0,
    timezone_offset_hours: float = 0.0,
) -> float:
    """Liu-Jordan isotropic sky model (same as HOMER Pro uses internally)."""
    if ghi_w_m2 <= 0.0:
        return 0.0
    slope_r = math.radians(slope_deg)
    if slope_r < EPSILON:
        return float(ghi_w_m2)

    lat_r = math.radians(latitude_deg)
    az_r  = math.radians(surface_az_DnB_deg)
    day_n = timestamp.dayofyear
    dec_r = math.radians(_solar_declination_deg(day_n))
    omega_r = math.radians(_solar_hour_angle_deg(timestamp, longitude_deg, timezone_offset_hours))

    cos_z = _cos_zenith(lat_r, dec_r, omega_r)
    if cos_z <= 0.0:
        return 0.0

    G0   = _extraterrestrial_radiation_w_m2(day_n)
    G0_h = _integrated_g0_h_w_m2(lat_r, dec_r, G0, omega_r)

    kt = max(0.0, min(ghi_w_m2 / G0_h, 1.0)) if G0_h > EPSILON else 0.0
    fd = _erbs_diffuse_fraction(kt)
    diffuse_h = fd * ghi_w_m2
    beam_h    = max(0.0, ghi_w_m2 - diffuse_h)

    _COS_Z_FLOOR = 0.01745
    cos_theta = _cos_angle_of_incidence(lat_r, dec_r, omega_r, slope_r, az_r)
    r_b = max(0.0, cos_theta) / max(cos_z, _COS_Z_FLOOR)

    cos_beta = math.cos(slope_r)

    # --- Isotropic diffuse (Liu-Jordan) --- no circumsolar, no horizon term
    beam_poa      = beam_h * r_b
    diffuse_poa   = diffuse_h * (1.0 + cos_beta) / 2.0
    reflected_poa = ghi_w_m2 * (ground_reflectance_pct / 100.0) * (1.0 - cos_beta) / 2.0

    return max(0.0, beam_poa + diffuse_poa + reflected_poa)


def main():
    print("Loading test10 (Dhule) inputs ...")
    inputs = load_project_simulation_inputs("test10")

    resource_df  = inputs.resource_df
    pv_config    = inputs.components.pv
    lat          = inputs.latitude_deg
    lon          = inputs.longitude_deg
    tz           = inputs.timezone_offset_hours
    capacity_kw  = 4000.0

    slope_deg, az_DnB = _resolve_panel_angles(pv_config, lat)
    print(f"Tilt: {slope_deg}°  |  Azimuth (D&B): {az_DnB}°  |  Capacity: {capacity_kw} kW")
    print(f"Latitude: {lat}°  |  Longitude: {lon}°  |  TZ offset: {tz} h")
    print()

    total_hdkr = 0.0
    total_iso  = 0.0
    monthly_hdkr = [0.0] * 12
    monthly_iso  = [0.0] * 12

    for _, row in resource_df.iterrows():
        ts = pd.Timestamp(row["timestamp"])
        month_idx = ts.month - 1

        # --- Effective GHI (with clearness-index cap, same as production code) ---
        if (
            pv_config.orientation.use_clearness_index_cap
            and "clearness_index" in row.index
            and "g0_w_m2" in row.index
        ):
            kt  = float(row["clearness_index"])
            g0  = float(row["g0_w_m2"])
            ghi_w_m2 = min(kt, float(pv_config.orientation.kt_max)) * g0
        else:
            ghi_w_m2 = float(row.get("ghi", 0.0))

        temp_c = float(row.get("temperature", 25.0))
        noct   = pv_config.temperature.nominal_operating_cell_temp_c
        alpha  = pv_config.temperature.temperature_coefficient_pct_per_degC
        derating = pv_config.derating_factor

        # ── HDKR (current production model) ─────────────────────────────────────
        hdkr_result = compute_pv_power_from_resource_row(
            resource_row=row,
            pv_config=pv_config,
            selected_capacity_kw=capacity_kw,
            latitude_deg=lat,
            longitude_deg=lon,
            timezone_offset_hours=tz,
        )
        pv_hdkr = hdkr_result.net_power_kw

        # ── Isotropic / Liu-Jordan (HOMER Pro's model) ───────────────────────────
        poa_iso_w  = _compute_poa_isotropic(
            ghi_w_m2=ghi_w_m2,
            timestamp=ts,
            latitude_deg=lat,
            longitude_deg=lon,
            slope_deg=slope_deg,
            surface_az_DnB_deg=az_DnB,
            ground_reflectance_pct=pv_config.orientation.ground_reflectance_pct,
            timezone_offset_hours=tz,
        )
        poa_iso_kw = poa_iso_w / 1000.0
        cell_temp_iso = compute_cell_temperature_c(
            ambient_temperature_c=temp_c,
            irradiance_kw_per_m2=poa_iso_kw,
            nominal_operating_cell_temp_c=noct,
        )
        _, _, pv_iso = compute_pv_power_output(
            rated_capacity_kw=capacity_kw,
            derating_factor=derating,
            irradiance_kw_per_m2=poa_iso_kw,
            reference_irradiance_kw_per_m2=1.0,
            cell_temperature_c=cell_temp_iso,
            reference_cell_temp_c=25.0,
            temperature_coefficient_pct_per_degC=alpha,
            temperature_effect_enabled=pv_config.temperature.enabled,
        )

        total_hdkr += pv_hdkr
        total_iso  += pv_iso
        monthly_hdkr[month_idx] += pv_hdkr
        monthly_iso[month_idx]  += pv_iso

    HOMER_PV = 4_794_641.0

    print(f"{'Month':<10} {'HDKR (kWh)':>14} {'Isotropic (kWh)':>16} {'Diff %':>8}")
    print("-" * 52)
    months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    for i, m in enumerate(months):
        diff = (monthly_hdkr[i] / monthly_iso[i] - 1) * 100 if monthly_iso[i] > 0 else 0
        print(f"{m:<10} {monthly_hdkr[i]:>14,.0f} {monthly_iso[i]:>16,.0f} {diff:>+7.1f}%")

    print("-" * 52)
    diff_total = (total_hdkr / total_iso - 1) * 100
    print(f"{'ANNUAL':<10} {total_hdkr:>14,.0f} {total_iso:>16,.0f} {diff_total:>+7.1f}%")
    print()
    print(f"HOMER Pro result:             {HOMER_PV:>14,.0f} kWh")
    print()
    print(f"HDKR      vs HOMER: {(total_hdkr/HOMER_PV - 1)*100:+.1f}%")
    print(f"Isotropic vs HOMER: {(total_iso /HOMER_PV - 1)*100:+.1f}%")
    print()
    print(f"Conclusion: switching to Isotropic closes the gap from "
          f"{(total_hdkr/HOMER_PV - 1)*100:+.1f}% to "
          f"{(total_iso/HOMER_PV - 1)*100:+.1f}%")


if __name__ == "__main__":
    main()
