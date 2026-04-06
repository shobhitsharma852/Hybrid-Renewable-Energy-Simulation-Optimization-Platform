from __future__ import annotations

import pandas as pd

from core.components.config import load_components
from core.simulation import HybridSystemSimulator, SimulationInputs


def main() -> None:
    # ------------------------------------------------------------
    # 12-hour crafted scenario to exercise multiple operating modes
    #
    # Intended behavior blocks:
    # Hours 0-1  : night / weak wind -> battery discharge likely
    # Hours 2-3  : PV starts, still deficit possible
    # Hours 4-6  : strong PV + some wind -> charge / maybe export
    # Hours 7-8  : strong wind with medium load -> support / maybe charge
    # Hours 9-10 : renewable falls, battery discharges again
    # Hour 11    : weak renewable, high load -> grid import or deeper discharge
    # ------------------------------------------------------------

    load_df = pd.DataFrame(
        {
            "load_kw": [
                700,   # 0
                800,   # 1
                900,   # 2
                850,   # 3
                500,   # 4
                450,   # 5
                400,   # 6
                550,   # 7
                600,   # 8
                850,   # 9
                950,   # 10
                1100,  # 11
            ]
        }
    )

    resource_df = pd.DataFrame(
        {
            # PV profile in W/m2 style input
            "ghi": [
                0,      # 0  night
                0,      # 1  night
                150,    # 2  early morning
                350,    # 3
                700,    # 4
                1000,   # 5  peak PV
                850,    # 6
                500,    # 7
                250,    # 8
                80,     # 9
                0,      # 10
                0,      # 11
            ],
            "temperature_c": [
                20,
                21,
                23,
                27,
                32,
                36,
                35,
                31,
                28,
                25,
                23,
                22,
            ],
            # Wind profile at 50m
            "ws50m": [
                3.0,   # 0  low
                4.5,   # 1
                5.5,   # 2
                6.5,   # 3
                7.5,   # 4
                8.0,   # 5
                7.0,   # 6
                8.5,   # 7  strong wind
                9.0,   # 8  strong wind
                5.0,   # 9
                3.5,   # 10
                2.5,   # 11 weak
            ],
        }
    )

    components = load_components("projects/Hybrid")

    inputs = SimulationInputs(
        load_df=load_df,
        resource_df=resource_df,
        components=components,
    )

    simulator = HybridSystemSimulator(inputs)
    results = simulator.run()

    df = results.to_dataframe()

    print("\n--- Manual Hybrid Simulation Results (12-hour stress scenario) ---")
    print(df.to_string(index=False))

    print("\n--- Summary ---")
    print(results.summary)

    print("\n--- Quick Checks ---")
    print(f"Total Load (kWh): {df['load_kw'].sum():.3f}")
    print(f"Total PV Generation (kWh): {df['pv_kw'].sum():.3f}")
    print(f"Total Wind Generation (kWh): {df['wind_kw'].sum():.3f}")
    print(f"Total Battery Charge (kWh): {df['battery_charge_kw'].sum():.3f}")
    print(f"Total Battery Discharge (kWh): {df['battery_discharge_kw'].sum():.3f}")
    print(f"Total Grid Import (kWh): {df['grid_import_kw'].sum():.3f}")
    print(f"Total Grid Export (kWh): {df['grid_export_kw'].sum():.3f}")
    print(f"Total Unmet Load (kWh): {df['unmet_load_kw'].sum():.3f}")
    print(f"Min Battery SOC (%): {df['battery_soc_pct'].min():.3f}")
    print(f"Max Battery SOC (%): {df['battery_soc_pct'].max():.3f}")

    print("\n--- Mode Flags ---")
    print(f"Any battery charging? {'Yes' if (df['battery_charge_kw'] > 0).any() else 'No'}")
    print(f"Any battery discharging? {'Yes' if (df['battery_discharge_kw'] > 0).any() else 'No'}")
    print(f"Any grid import? {'Yes' if (df['grid_import_kw'] > 0).any() else 'No'}")
    print(f"Any grid export? {'Yes' if (df['grid_export_kw'] > 0).any() else 'No'}")
    print(f"Any unmet load? {'Yes' if (df['unmet_load_kw'] > 0).any() else 'No'}")
    print(f"Any excess energy? {'Yes' if (df['excess_energy_kw'] > 0).any() else 'No'}")


if __name__ == "__main__":
    main()