from __future__ import annotations

import pandas as pd

from core.components.config import load_components
from core.simulation import HybridSystemSimulator, SimulationInputs
from core.simulation.energy_balance import (
    get_failed_energy_balance_rows,
    validate_energy_balance,
)


def main() -> None:
    load_df = pd.DataFrame(
        {
            "load_kw": [
                700,
                800,
                900,
                850,
                500,
                450,
                400,
                550,
                600,
                850,
                950,
                1100,
            ]
        }
    )

    resource_df = pd.DataFrame(
        {
            "ghi": [0, 0, 150, 350, 700, 1000, 850, 500, 250, 80, 0, 0],
            "temperature_c": [20, 21, 23, 27, 32, 36, 35, 31, 28, 25, 23, 22],
            "ws50m": [3.0, 4.5, 5.5, 6.5, 7.5, 8.0, 7.0, 8.5, 9.0, 5.0, 3.5, 2.5],
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
    hourly_df = results.to_dataframe()

    print("\n--- Hourly Simulation Output ---")
    print(hourly_df.to_string(index=False))

    print("\n--- Energy Balance Check (with explicit losses) ---")
    check_result, balance_df = validate_energy_balance(
        hourly_df,
        tolerance_kw=1e-6,
        include_losses=True,
    )

    print(check_result)
    print(balance_df.to_string(index=False))

    failed_df = get_failed_energy_balance_rows(balance_df, tolerance_kw=1e-6)

    print("\n--- Failed Rows ---")
    if failed_df.empty:
        print("No failed rows.")
    else:
        print(failed_df.to_string(index=False))


if __name__ == "__main__":
    main()