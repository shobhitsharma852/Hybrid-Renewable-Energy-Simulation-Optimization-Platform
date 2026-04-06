from __future__ import annotations

import pandas as pd

from core.optimization.design_point import DesignPoint
from core.optimization.optimizer import run_optimization_sweep
from core.simulation.run_project_simulation import run_project_simulation


PROJECT_NAME = "Hybrid"
CANDIDATE_ID = 22


def build_design_from_csv_row(row: pd.Series) -> DesignPoint:
    return DesignPoint(
        pv_capacity_kw=float(row["pv_capacity_kw"]),
        wind_quantity=int(row["wind_quantity"]),
        battery_quantity=int(row["battery_quantity"]),
        converter_capacity_kw=float(row["converter_capacity_kw"]),
    )


def main():
    # 1) Run optimization fresh (no file confusion)
    sweep = run_optimization_sweep(PROJECT_NAME, save_outputs=False)
    df = sweep.to_dataframe()

    row = df.loc[df["candidate_id"].astype(int) == CANDIDATE_ID].iloc[0]

    print("\n=== OPTIMIZER ROW ===")
    print(row[[
        "candidate_id",
        "pv_capacity_kw",
        "wind_quantity",
        "battery_quantity",
        "converter_capacity_kw",
        "annual_capacity_shortage_pct",
        "renewable_fraction_pct",
        "net_present_cost",
        "levelized_cost_of_energy",
        "annual_grid_net_cost",
    ]])

    design = build_design_from_csv_row(row)

    # 2) Run same design directly through detailed simulation
    detailed = run_project_simulation(
        project_name=PROJECT_NAME,
        save_outputs=False,
        design=design,
    )

    s = detailed.summary

    print("\n=== DIRECT DETAILED SIMULATION SUMMARY ===")
    print({
        "total_load_kwh": s.total_load_kwh,
        "total_served_load_kwh": s.total_served_load_kwh,
        "total_unmet_load_kwh": s.total_unmet_load_kwh,
        "total_pv_generation_kwh": s.total_pv_generation_kwh,
        "total_wind_generation_kwh": s.total_wind_generation_kwh,
        "total_grid_import_kwh": s.total_grid_import_kwh,
        "total_grid_export_kwh": s.total_grid_export_kwh,
        "renewable_fraction": s.renewable_fraction,
        "gross_renewable_fraction": s.gross_renewable_fraction,
    })


if __name__ == "__main__":
    main()