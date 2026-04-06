from __future__ import annotations

import pandas as pd

from core.components.pv import PVComponentConfig, PVTemperatureSettings
from core.simulation.pv_model import simulate_pv_timeseries


def main() -> None:
    # ------------------------------------------------------------
    # Sample hourly resource data for PV-only testing
    # ------------------------------------------------------------
    resource_df = pd.DataFrame(
        {
            "timestamp": pd.date_range("2025-01-01 06:00:00", periods=8, freq="h"),
            "ghi": [0.0, 0.2, 0.4, 0.7, 1.0, 0.8, 0.3, 0.0],
            "temperature_c": [18.0, 20.0, 24.0, 29.0, 34.0, 32.0, 26.0, 22.0],
        }
    )

    # ------------------------------------------------------------
    # PV config
    # ------------------------------------------------------------
    pv_config = PVComponentConfig(
        enabled=True,
        capacity_kw_options=[100.0],
        derating_factor=0.95,
        temperature=PVTemperatureSettings(
            enabled=True,
            temperature_coefficient_pct_per_degC=-0.4,
            nominal_operating_cell_temp_c=45.0,
        ),
    )

    # ------------------------------------------------------------
    # Run PV simulation only
    # ------------------------------------------------------------
    pv_df = simulate_pv_timeseries(
        resource_df=resource_df,
        pv_config=pv_config,
        selected_capacity_kw=100.0,
    )

    print("\n--- PV Manual Test Results ---")
    print(pv_df.to_string(index=False))

    print("\n--- PV Summary ---")
    print(f"Total PV Generation (kWh): {pv_df['pv_power_kw'].sum():.3f}")
    print(f"Max PV Power (kW): {pv_df['pv_power_kw'].max():.3f}")
    print(f"Max Cell Temperature (°C): {pv_df['cell_temperature_c'].max():.3f}")


if __name__ == "__main__":
    main()