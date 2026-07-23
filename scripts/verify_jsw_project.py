from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_DIR = Path("projects/jsw")
SIMULATION_PATH = PROJECT_DIR / "outputs" / "simulation_hourly.csv"
SCADA_PATH = PROJECT_DIR / "inputs" / "scada_actual.csv"


def _metrics(frame: pd.DataFrame) -> dict[str, float | int | str]:
    error_kw = frame["model_ac_power_kw"] - frame["scada_ac_power_kw"]
    interval_hours = 1.0 / 60.0
    scada_energy_mwh = float(
        frame["scada_ac_power_kw"].sum() * interval_hours / 1000.0
    )
    model_energy_mwh = float(
        frame["model_ac_power_kw"].sum() * interval_hours / 1000.0
    )
    return {
        "records": int(len(frame)),
        "scada_energy_mwh": scada_energy_mwh,
        "model_energy_mwh": model_energy_mwh,
        "energy_difference_mwh": model_energy_mwh - scada_energy_mwh,
        "energy_difference_pct": (
            100.0 * (model_energy_mwh - scada_energy_mwh) / scada_energy_mwh
        ),
        "mae_kw": float(np.abs(error_kw).mean()),
        "rmse_kw": float(math.sqrt(np.square(error_kw).mean())),
        "mean_bias_kw": float(error_kw.mean()),
        "correlation": float(
            frame["model_ac_power_kw"].corr(frame["scada_ac_power_kw"])
        ),
        "scada_peak_kw": float(frame["scada_ac_power_kw"].max()),
        "model_peak_kw": float(frame["model_ac_power_kw"].max()),
    }


def main() -> None:
    simulation = pd.read_csv(SIMULATION_PATH, parse_dates=["timestamp"])
    scada = pd.read_csv(SCADA_PATH, parse_dates=["timestamp"])
    model = simulation[["timestamp", "grid_export_kw"]].rename(
        columns={"grid_export_kw": "model_ac_power_kw"}
    )
    comparison = scada.merge(model, on="timestamp", how="inner", validate="one_to_one")
    if len(comparison) != len(scada) or len(comparison) != len(simulation):
        raise ValueError("Simulation and SCADA timestamps are not fully aligned")

    comparison["error_kw"] = (
        comparison["model_ac_power_kw"] - comparison["scada_ac_power_kw"]
    )
    comparison["absolute_error_kw"] = comparison["error_kw"].abs()
    comparison["date"] = comparison["timestamp"].dt.strftime("%Y-%m-%d")

    daily = {
        date: _metrics(group)
        for date, group in comparison.groupby("date", sort=True)
    }
    summary = {
        "project": "jsw",
        "resolution_minutes": 1,
        "comparison_boundary": (
            "Model grid_export_kw after the 95% converter versus the sum of "
            "12 inverter SCADA Total Active Power channels"
        ),
        "overall": _metrics(comparison),
        "daily": daily,
    }

    output_dir = PROJECT_DIR / "outputs"
    comparison.to_csv(output_dir / "scada_verification_1min.csv", index=False)
    (output_dir / "scada_verification_1min_summary.json").write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
