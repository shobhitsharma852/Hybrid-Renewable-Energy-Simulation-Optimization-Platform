from core.simulation.wind_model import compute_wind_power_output

speed_points = [0, 4, 5, 6, 7, 8, 10, 12, 14, 24.99, 25]
power_points = [0, 0, 150, 300, 500, 800, 1200, 1500, 1500, 1500, 0]

test_wind_speeds = [2, 4, 5.5, 8, 9, 12, 15, 30]

print("\n--- Wind Model Manual Test ---\n")

for ws in test_wind_speeds:
    result = compute_wind_power_output(
        wind_speed_ref_mps=ws,
        quantity=2,
        hub_height_m=80.0,
        speed_points=speed_points,
        power_points=power_points,
        reference_height_m=50.0,
        shear_exponent=0.14,
        air_density_kg_per_m3=1.225,
        availability_losses_pct=2,
        turbine_performance_losses_pct=1,
        environmental_losses_pct=1,
        other_losses_pct=0,
        wake_effects_losses_pct=2,
        electrical_losses_pct=1,
        curtailment_losses_pct=0,
    )

    print(f"Wind Speed at 50m: {result.wind_speed_ref_mps:.2f} m/s")
    print(f"Wind Speed at Hub Height: {result.wind_speed_hub_mps:.2f} m/s")
    print(f"Single Turbine Output: {result.single_turbine_output_kw:.2f} kW")
    print(f"Gross Total Output: {result.gross_total_output_kw:.2f} kW")
    print(f"Net Total Output: {result.net_total_output_kw:.2f} kW")
    print(f"Total Losses: {result.total_losses_pct:.2f}%")
    print(f"Air Density Correction Factor: {result.air_density_correction_factor:.4f}")
    print("-" * 50)