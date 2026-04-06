from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass


STANDARD_AIR_DENSITY_KG_PER_M3 = 1.225
DEFAULT_WIND_SHEAR_EXPONENT = 0.14
DEFAULT_REFERENCE_HEIGHT_M = 50.0


@dataclass
class WindPowerResult:
    wind_speed_ref_mps: float
    wind_speed_hub_mps: float
    single_turbine_output_kw: float
    gross_total_output_kw: float
    net_total_output_kw: float
    total_losses_pct: float
    air_density_correction_factor: float


def _adjust_wind_speed_to_hub_height(
    *,
    wind_speed_ref_mps: float,
    reference_height_m: float,
    hub_height_m: float,
    shear_exponent: float = DEFAULT_WIND_SHEAR_EXPONENT,
) -> float:
    """
    Adjust wind speed from reference height to turbine hub height
    using the power law wind profile.
    """
    wind_speed_ref_mps = float(wind_speed_ref_mps)
    reference_height_m = float(reference_height_m)
    hub_height_m = float(hub_height_m)
    shear_exponent = float(shear_exponent)

    if wind_speed_ref_mps <= 0.0:
        return 0.0

    if reference_height_m <= 0.0:
        raise ValueError("reference_height_m must be > 0.")

    if hub_height_m <= 0.0:
        raise ValueError("hub_height_m must be > 0.")

    return wind_speed_ref_mps * (hub_height_m / reference_height_m) ** shear_exponent


def _interpolate_power_from_curve(
    *,
    wind_speed_mps: float,
    speed_points: list[float],
    power_points: list[float],
) -> float:
    """
    Piecewise linear interpolation on the turbine power curve.
    Returns the power output for a single turbine.
    """
    if not speed_points or not power_points:
        return 0.0

    if len(speed_points) != len(power_points):
        raise ValueError("speed_points and power_points must have the same length.")

    if len(speed_points) < 2:
        raise ValueError("Wind power curve must contain at least two points.")

    # Ensure curve is sorted by wind speed
    for i in range(1, len(speed_points)):
        if float(speed_points[i]) < float(speed_points[i - 1]):
            raise ValueError("Wind speed points must be sorted in ascending order.")

    wind_speed_mps = float(wind_speed_mps)

    if wind_speed_mps <= float(speed_points[0]):
        return float(power_points[0])

    if wind_speed_mps >= float(speed_points[-1]):
        return float(power_points[-1])

    idx = bisect_right(speed_points, wind_speed_mps)

    x0 = float(speed_points[idx - 1])
    x1 = float(speed_points[idx])
    y0 = float(power_points[idx - 1])
    y1 = float(power_points[idx])

    if x1 == x0:
        return y0

    fraction = (wind_speed_mps - x0) / (x1 - x0)
    return y0 + fraction * (y1 - y0)

'''
Example interpolation steps for wind speed 6.5 m/s:

wind_speed_mps = 6.5
speed_points = [4, 5, 6, 7, 8]
power_points = [0, 100, 250, 450, 700]

Step 1
Lists are not empty.

Step 2
Both lists have same length.

Step 3
There are at least 2 points.

Step 4
Speed points are sorted.

Step 5
Wind speed 6.5 is not below first point and not above last point.

Step 6
Find where 6.5 fits:
between 6 and 7

Step 7
Take surrounding values:

x0 = 6, x1 = 7
y0 = 250, y1 = 450

Step 8
Compute fraction:
(6.5 − 6)/(7−6)=0.5

Step 9
Compute power:
250+0.5×(450−250)=350

Final output:
350 kW'''

def _compute_total_losses_pct(
    *,
    availability_losses_pct: float = 0.0,
    turbine_performance_losses_pct: float = 0.0,
    environmental_losses_pct: float = 0.0,
    other_losses_pct: float = 0.0,
    wake_effects_losses_pct: float = 0.0,
    electrical_losses_pct: float = 0.0,
    curtailment_losses_pct: float = 0.0,
) -> float:
    """
    Combine all losses multiplicatively and return the equivalent total loss
    percentage, clamped between 0 and 100%.

    Example:
    10% and 10% losses => net factor = 0.9 * 0.9 = 0.81
    => total loss = 19%
    """
    loss_values_pct = [
        float(availability_losses_pct),
        float(turbine_performance_losses_pct),
        float(environmental_losses_pct),
        float(other_losses_pct),
        float(wake_effects_losses_pct),
        float(electrical_losses_pct),
        float(curtailment_losses_pct),
    ]

    net_factor = 1.0

    for loss_pct in loss_values_pct:
        clamped_loss_pct = max(0.0, min(100.0, loss_pct))
        net_factor *= (1.0 - clamped_loss_pct / 100.0)

    total_losses_pct = (1.0 - net_factor) * 100.0
    return max(0.0, min(100.0, total_losses_pct))


def _compute_air_density_correction_factor(
    *,
    air_density_kg_per_m3: float = STANDARD_AIR_DENSITY_KG_PER_M3,
    standard_air_density_kg_per_m3: float = STANDARD_AIR_DENSITY_KG_PER_M3,
) -> float:
    """
    Simple correction factor relative to standard air density.
    For now this is a hook for future realism. Default factor = 1.0.
    """
    air_density_kg_per_m3 = float(air_density_kg_per_m3)
    standard_air_density_kg_per_m3 = float(standard_air_density_kg_per_m3)

    if standard_air_density_kg_per_m3 <= 0.0:
        raise ValueError("standard_air_density_kg_per_m3 must be > 0.")

    if air_density_kg_per_m3 <= 0.0:
        return 1.0

    return air_density_kg_per_m3 / standard_air_density_kg_per_m3


def compute_wind_power_output(
    *,
    wind_speed_ref_mps: float,
    quantity: int,
    hub_height_m: float,
    speed_points: list[float],
    power_points: list[float],
    reference_height_m: float = DEFAULT_REFERENCE_HEIGHT_M,
    shear_exponent: float = DEFAULT_WIND_SHEAR_EXPONENT,
    air_density_kg_per_m3: float = STANDARD_AIR_DENSITY_KG_PER_M3,
    availability_losses_pct: float = 0.0,
    turbine_performance_losses_pct: float = 0.0,
    environmental_losses_pct: float = 0.0,
    other_losses_pct: float = 0.0,
    wake_effects_losses_pct: float = 0.0,
    electrical_losses_pct: float = 0.0,
    curtailment_losses_pct: float = 0.0,
) -> WindPowerResult:
    """
    Compute final wind power output using:
    1. Reference-height wind speed
    2. Hub-height correction
    3. Power curve interpolation
    4. Air density correction
    5. Loss application
    """
    quantity = int(quantity)

    if quantity <= 0:
        return WindPowerResult(
            wind_speed_ref_mps=float(wind_speed_ref_mps),
            wind_speed_hub_mps=0.0,
            single_turbine_output_kw=0.0,
            gross_total_output_kw=0.0,
            net_total_output_kw=0.0,
            total_losses_pct=0.0,
            air_density_correction_factor=1.0,
        )

    wind_speed_hub_mps = _adjust_wind_speed_to_hub_height(
        wind_speed_ref_mps=float(wind_speed_ref_mps),
        reference_height_m=float(reference_height_m),
        hub_height_m=float(hub_height_m),
        shear_exponent=float(shear_exponent),
    )

    base_single_turbine_output_kw = _interpolate_power_from_curve(
        wind_speed_mps=wind_speed_hub_mps,
        speed_points=speed_points,
        power_points=power_points,
    )

    air_density_correction_factor = _compute_air_density_correction_factor(
        air_density_kg_per_m3=float(air_density_kg_per_m3),
        standard_air_density_kg_per_m3=STANDARD_AIR_DENSITY_KG_PER_M3,
    )

    single_turbine_output_kw = base_single_turbine_output_kw * air_density_correction_factor
    gross_total_output_kw = single_turbine_output_kw * quantity

    total_losses_pct = _compute_total_losses_pct(
        availability_losses_pct=availability_losses_pct,
        turbine_performance_losses_pct=turbine_performance_losses_pct,
        environmental_losses_pct=environmental_losses_pct,
        other_losses_pct=other_losses_pct,
        wake_effects_losses_pct=wake_effects_losses_pct,
        electrical_losses_pct=electrical_losses_pct,
        curtailment_losses_pct=curtailment_losses_pct,
    )

    net_total_output_kw = gross_total_output_kw * (1.0 - total_losses_pct / 100.0)

    return WindPowerResult(
        wind_speed_ref_mps=float(wind_speed_ref_mps),
        wind_speed_hub_mps=float(wind_speed_hub_mps),
        single_turbine_output_kw=max(0.0, float(single_turbine_output_kw)),
        gross_total_output_kw=max(0.0, float(gross_total_output_kw)),
        net_total_output_kw=max(0.0, float(net_total_output_kw)),
        total_losses_pct=float(total_losses_pct),
        air_density_correction_factor=float(air_density_correction_factor),
    )