from __future__ import annotations

import argparse
import math
import sys
import time
from dataclasses import replace
from pathlib import Path

import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


from core.components.config import validate_components_config
from core.economics.evaluator import evaluate_candidate_economics
from core.simulation import HybridSystemSimulator
from core.simulation.energy_balance import validate_energy_balance
from core.simulation.run_project_simulation import load_project_simulation_inputs


SCENARIOS: tuple[tuple[str, str, dict[str, object]], ...] = (
    (
        "baseline_efc",
        "Saved project settings: EFC cycle fade only",
        {},
    ),
    (
        "no_simulated_fade",
        "No EFC, DoD, calendar, Arrhenius, or temperature-capacity effect",
        {
            "throughput_kwh": 0.0,
            "calendar_fade_pct_per_year": 0.0,
            "arrhenius_ea_ev": 0.0,
            "cycle_life_a": 0.0,
            "consider_temperature_effects": False,
        },
    ),
    (
        "efc_short_life_extreme",
        "EFC only; lifetime throughput reduced 10x",
        {
            "throughput_kwh": 300_000.0,
            "calendar_fade_pct_per_year": 0.0,
            "arrhenius_ea_ev": 0.0,
            "cycle_life_a": 0.0,
            "consider_temperature_effects": False,
        },
    ),
    (
        "fixed_calendar_2pct",
        "EFC plus fixed 2%/year calendar fade",
        {
            "calendar_fade_pct_per_year": 2.0,
            "arrhenius_ea_ev": 0.0,
            "cycle_life_a": 0.0,
            "consider_temperature_effects": False,
        },
    ),
    (
        "fixed_calendar_20pct_extreme",
        "EFC plus fixed 20%/year calendar fade",
        {
            "calendar_fade_pct_per_year": 20.0,
            "arrhenius_ea_ev": 0.0,
            "cycle_life_a": 0.0,
            "consider_temperature_effects": False,
        },
    ),
    (
        "arrhenius_ea_0_7",
        "EFC plus 2%/year at 25C, Arrhenius Ea=0.7 eV",
        {
            "calendar_fade_pct_per_year": 2.0,
            "arrhenius_ea_ev": 0.7,
            "temperature_reference_c": 25.0,
            "cycle_life_a": 0.0,
            "consider_temperature_effects": False,
        },
    ),
    (
        "arrhenius_ea_1_2_extreme",
        "EFC plus 2%/year at 25C, Arrhenius Ea=1.2 eV",
        {
            "calendar_fade_pct_per_year": 2.0,
            "arrhenius_ea_ev": 1.2,
            "temperature_reference_c": 25.0,
            "cycle_life_a": 0.0,
            "consider_temperature_effects": False,
        },
    ),
    (
        "dod_miner_typical",
        "DoD/Miner cycle fade (A=750, beta=1.3); EFC automatically disabled",
        {
            "calendar_fade_pct_per_year": 0.0,
            "arrhenius_ea_ev": 0.0,
            "cycle_life_a": 750.0,
            "cycle_life_beta": 1.3,
            "consider_temperature_effects": False,
        },
    ),
    (
        "dod_miner_short_life_extreme",
        "DoD/Miner cycle fade with extreme short life (A=50, beta=0.5)",
        {
            "calendar_fade_pct_per_year": 0.0,
            "arrhenius_ea_ev": 0.0,
            "cycle_life_a": 50.0,
            "cycle_life_beta": 0.5,
            "consider_temperature_effects": False,
        },
    ),
    (
        "temperature_polynomial_default",
        "Reversible temperature-capacity flag with saved d0/d1/d2",
        {
            "consider_temperature_effects": True,
        },
    ),
    (
        "temperature_capacity_70pct_extreme",
        "Extreme constant 70% temperature-capacity factor",
        {
            "consider_temperature_effects": True,
            "capacity_temp_d0": 0.70,
            "capacity_temp_d1": 0.0,
            "capacity_temp_d2": 0.0,
        },
    ),
    (
        "all_extreme",
        "Extreme DoD, calendar/Arrhenius, and 70% temperature capacity together",
        {
            "calendar_fade_pct_per_year": 20.0,
            "arrhenius_ea_ev": 1.2,
            "temperature_reference_c": 25.0,
            "cycle_life_a": 50.0,
            "cycle_life_beta": 0.5,
            "consider_temperature_effects": True,
            "capacity_temp_d0": 0.70,
            "capacity_temp_d1": 0.0,
            "capacity_temp_d2": 0.0,
        },
    ),
)


def _pct_change(value: float, baseline: float) -> float:
    if abs(baseline) <= 1e-12:
        return math.nan
    return (value - baseline) / abs(baseline) * 100.0


def _effective_battery_life_years(battery, design, annual_throughput_kwh: float) -> float:
    calendar_life = max(1.0, float(battery.lifetime_years))
    if battery.throughput_kwh <= 0.0 or annual_throughput_kwh <= 0.0:
        return calendar_life
    bank_lifetime_throughput = float(battery.throughput_kwh) * max(
        1, int(design.battery_quantity)
    )
    return max(1.0, min(calendar_life, bank_lifetime_throughput / annual_throughput_kwh))


def run_analysis(project_name: str) -> pd.DataFrame:
    base_inputs = load_project_simulation_inputs(project_name)
    temperature = pd.to_numeric(
        base_inputs.resource_df.get("temperature"), errors="coerce"
    )
    rows: list[dict[str, object]] = []

    print(
        f"Project={project_name} design={base_inputs.design} "
        f"steps={len(base_inputs.load_df):,} dt={base_inputs.time_step_hours:g} h"
    )
    if temperature.notna().any():
        print(
            "Temperature C: "
            f"min={temperature.min():.2f}, mean={temperature.mean():.2f}, "
            f"max={temperature.max():.2f}"
        )

    for scenario_name, description, overrides in SCENARIOS:
        battery = replace(base_inputs.components.battery, **overrides)
        components = replace(base_inputs.components, battery=battery)
        validate_components_config(components)
        scenario_inputs = replace(base_inputs, components=components)

        started = time.perf_counter()
        results = HybridSystemSimulator(scenario_inputs).run()
        elapsed = time.perf_counter() - started
        summary = results.summary
        economics = evaluate_candidate_economics(
            project_name=project_name,
            components=components,
            design=scenario_inputs.design,
            simulation_results=results,
        )
        balance, _ = validate_energy_balance(results.to_dataframe())

        row = {
            "scenario": scenario_name,
            "description": description,
            "throughput_setting_kwh_per_string": battery.throughput_kwh,
            "calendar_fade_pct_per_year": battery.calendar_fade_pct_per_year,
            "arrhenius_ea_ev": battery.arrhenius_ea_ev,
            "cycle_life_a": battery.cycle_life_a,
            "cycle_life_beta": battery.cycle_life_beta,
            "temperature_capacity_enabled": battery.consider_temperature_effects,
            "capacity_temp_d0": battery.capacity_temp_d0,
            "capacity_temp_d1": battery.capacity_temp_d1,
            "capacity_temp_d2": battery.capacity_temp_d2,
            "final_soh_pct": summary.final_soh_pct,
            "final_soc_pct": summary.final_battery_soc_pct,
            "min_effective_capacity_kwh": summary.min_effective_capacity_kwh,
            "grid_import_kwh": summary.total_grid_import_kwh,
            "grid_export_kwh": summary.total_grid_export_kwh,
            "battery_charge_kwh": summary.total_battery_charge_kwh,
            "battery_discharge_kwh": summary.total_battery_discharge_kwh,
            "battery_throughput_kwh": summary.total_battery_throughput_kwh,
            "renewable_fraction_pct": summary.renewable_fraction * 100.0,
            "unmet_load_kwh": summary.total_unmet_load_kwh,
            "effective_battery_life_years": _effective_battery_life_years(
                battery,
                scenario_inputs.design,
                summary.total_battery_throughput_kwh,
            ),
            "npc": economics.net_present_cost,
            "lcoe": economics.levelized_cost_of_energy,
            "energy_balance_failed_rows": balance.failed_rows,
            "runtime_seconds": elapsed,
        }
        rows.append(row)
        print(
            f"{scenario_name:40s} "
            f"SOH={summary.final_soh_pct:7.3f}% "
            f"grid={summary.total_grid_import_kwh:12.0f} kWh "
            f"NPC={economics.net_present_cost:15.0f} "
            f"({elapsed:.2f}s)"
        )

    frame = pd.DataFrame(rows)
    baseline = frame.iloc[0]
    for metric in (
        "grid_import_kwh",
        "grid_export_kwh",
        "battery_discharge_kwh",
        "battery_throughput_kwh",
        "npc",
        "lcoe",
    ):
        frame[f"{metric}_change_pct"] = frame[metric].map(
            lambda value: _pct_change(float(value), float(baseline[metric]))
        )
    frame["final_soh_change_percentage_points"] = (
        frame["final_soh_pct"] - float(baseline["final_soh_pct"])
    )
    return frame


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run non-destructive battery degradation sensitivity scenarios."
    )
    parser.add_argument("--project", default="dhule_60min")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="CSV output path (default: analysis_outputs/<project>_battery_sensitivity.csv)",
    )
    args = parser.parse_args()

    output = args.output or (
        Path("analysis_outputs") / f"{args.project}_battery_sensitivity.csv"
    )
    frame = run_analysis(args.project)
    output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output, index=False)

    display_columns = [
        "scenario",
        "final_soh_pct",
        "final_soh_change_percentage_points",
        "grid_import_kwh_change_pct",
        "battery_discharge_kwh_change_pct",
        "npc_change_pct",
        "lcoe_change_pct",
        "energy_balance_failed_rows",
    ]
    print("\nChange relative to baseline:")
    print(frame[display_columns].to_string(index=False, float_format=lambda x: f"{x:.3f}"))
    print(f"\nSaved: {output.resolve()}")


if __name__ == "__main__":
    main()
