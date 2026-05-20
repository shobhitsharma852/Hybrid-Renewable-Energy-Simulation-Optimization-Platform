from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pandas as pd

from core.economics.evaluator import (
    EconomicAssumptions,
    build_default_economic_assumptions_for_project,
    evaluate_candidate_economics,
)
from core.optimization.candidate_generator import generate_design_candidates
from core.optimization.constraints import (
    OptimizationConstraints,
    build_default_constraints_for_project,
    evaluate_candidate_constraints,
)
from core.optimization.design_point import DesignPoint
from core.simulation import HybridSystemSimulator, SimulationInputs
from core.simulation.energy_balance import validate_energy_balance
from core.simulation.run_project_simulation import load_project_simulation_inputs


EPSILON: float = 1e-9


@dataclass(frozen=True)
class CandidateSimulationResult:
    candidate_id: int
    design: DesignPoint

    total_load_kwh: float = 0.0
    total_served_load_kwh: float = 0.0
    total_unmet_load_kwh: float = 0.0
    unmet_load_pct: float = 0.0

    total_excess_energy_kwh: float = 0.0
    total_pv_generation_kwh: float = 0.0
    total_wind_generation_kwh: float = 0.0
    total_grid_import_kwh: float = 0.0
    total_grid_export_kwh: float = 0.0
    total_battery_charge_kwh: float = 0.0
    total_battery_discharge_kwh: float = 0.0

    renewable_fraction: float = 0.0
    gross_renewable_fraction: float = 0.0

    annual_capacity_shortage_pct: float = 0.0
    renewable_fraction_pct: float = 0.0
    max_required_operating_reserve_kw: float = 0.0
    min_available_operating_reserve_kw: float = 0.0
    reserve_shortfall_hours: int = 0

    passes_capacity_shortage: bool = False
    passes_renewable_fraction: bool = False
    passes_operating_reserve: bool = False
    is_feasible: bool = False
    failure_reasons: tuple[str, ...] = field(default_factory=tuple)

    direct_capital_cost: float = 0.0
    annual_fixed_om_cost: float = 0.0
    annual_grid_net_cost: float = 0.0
    replacement_cost_present_value: float = 0.0
    salvage_value_present_value: float = 0.0
    annualized_capital_cost: float = 0.0
    annualized_total_cost: float = 0.0
    net_present_cost: float = 0.0
    levelized_cost_of_energy: float = 0.0

    energy_balance_passes: bool = False
    energy_balance_failed_rows: int = 0
    energy_balance_max_abs_mismatch_kw: float = 0.0

    run_success: bool = True
    error_message: str | None = None


@dataclass
class OptimizationSweepResult:
    project_name: str
    constraints_used: OptimizationConstraints
    economic_assumptions_used: EconomicAssumptions
    total_raw_combinations: int = 0
    total_valid_candidates: int = 0
    total_filtered_out: int = 0
    candidate_results: list[CandidateSimulationResult] = field(default_factory=list)

    def to_dataframe(self) -> pd.DataFrame:
        rows: list[dict] = []

        for item in self.candidate_results:
            rows.append(
                {
                    "candidate_id": item.candidate_id,
                    "pv_capacity_kw": item.design.pv_capacity_kw,
                    "wind_quantity": item.design.wind_quantity,
                    "battery_quantity": item.design.battery_quantity,
                    "converter_capacity_kw": item.design.converter_capacity_kw,
                    "total_load_kwh": item.total_load_kwh,
                    "total_served_load_kwh": item.total_served_load_kwh,
                    "total_unmet_load_kwh": item.total_unmet_load_kwh,
                    "unmet_load_pct": item.unmet_load_pct,
                    "total_excess_energy_kwh": item.total_excess_energy_kwh,
                    "total_pv_generation_kwh": item.total_pv_generation_kwh,
                    "total_wind_generation_kwh": item.total_wind_generation_kwh,
                    "total_grid_import_kwh": item.total_grid_import_kwh,
                    "total_grid_export_kwh": item.total_grid_export_kwh,
                    "total_battery_charge_kwh": item.total_battery_charge_kwh,
                    "total_battery_discharge_kwh": item.total_battery_discharge_kwh,
                    "renewable_fraction": item.renewable_fraction,
                    "gross_renewable_fraction": item.gross_renewable_fraction,
                    "annual_capacity_shortage_pct": item.annual_capacity_shortage_pct,
                    "renewable_fraction_pct": item.renewable_fraction_pct,
                    "max_required_operating_reserve_kw": item.max_required_operating_reserve_kw,
                    "min_available_operating_reserve_kw": item.min_available_operating_reserve_kw,
                    "reserve_shortfall_hours": item.reserve_shortfall_hours,
                    "passes_capacity_shortage": item.passes_capacity_shortage,
                    "passes_renewable_fraction": item.passes_renewable_fraction,
                    "passes_operating_reserve": item.passes_operating_reserve,
                    "is_feasible": item.is_feasible,
                    "failure_reasons": " | ".join(item.failure_reasons),
                    "direct_capital_cost": item.direct_capital_cost,
                    "annual_fixed_om_cost": item.annual_fixed_om_cost,
                    "annual_grid_net_cost": item.annual_grid_net_cost,
                    "replacement_cost_present_value": item.replacement_cost_present_value,
                    "salvage_value_present_value": item.salvage_value_present_value,
                    "annualized_capital_cost": item.annualized_capital_cost,
                    "annualized_total_cost": item.annualized_total_cost,
                    "net_present_cost": item.net_present_cost,
                    "levelized_cost_of_energy": item.levelized_cost_of_energy,
                    "energy_balance_passes": item.energy_balance_passes,
                    "energy_balance_failed_rows": item.energy_balance_failed_rows,
                    "energy_balance_max_abs_mismatch_kw": item.energy_balance_max_abs_mismatch_kw,
                    "run_success": item.run_success,
                    "error_message": item.error_message,
                }
            )

        df = pd.DataFrame(rows)

        if df.empty:
            return df

        df = df.sort_values(
            by=[
                "run_success",
                "is_feasible",
                "net_present_cost",
                "levelized_cost_of_energy",
                "annual_capacity_shortage_pct",
                "renewable_fraction_pct",
            ],
            ascending=[False, False, True, True, True, False],
        ).reset_index(drop=True)

        df.insert(0, "economic_rank", range(1, len(df) + 1))
        df.insert(1, "technical_rank", range(1, len(df) + 1))
        return df

    def top_n(self, n: int = 10) -> pd.DataFrame:
        return self.to_dataframe().head(max(1, int(n)))

    def best_solution_summary(self) -> dict[str, object]:
        df = self.to_dataframe()

        summary: dict[str, object] = {
            "project_name": self.project_name,
            "total_candidates": len(self.candidate_results),
            "successful_runs": sum(1 for x in self.candidate_results if x.run_success),
            "failed_runs": sum(1 for x in self.candidate_results if not x.run_success),
            "feasible_candidates": sum(1 for x in self.candidate_results if x.is_feasible),
            "best_feasible": None,
            "lowest_npc": None,
            "lowest_lcoe": None,
            "technical_best": None,
        }

        if df.empty:
            return summary

        def _row_summary(row: pd.Series) -> dict[str, object]:
            return {
                "candidate_id": int(row["candidate_id"]),
                "pv_capacity_kw": float(row["pv_capacity_kw"]),
                "wind_quantity": int(row["wind_quantity"]),
                "battery_quantity": int(row["battery_quantity"]),
                "converter_capacity_kw": float(row["converter_capacity_kw"]),
                "is_feasible": bool(row["is_feasible"]),
                "failure_reasons": str(row["failure_reasons"]),
                "annual_capacity_shortage_pct": float(row["annual_capacity_shortage_pct"]),
                "renewable_fraction_pct": float(row["renewable_fraction_pct"]),
                "net_present_cost": float(row["net_present_cost"]),
                "levelized_cost_of_energy": float(row["levelized_cost_of_energy"]),
                "annualized_total_cost": float(row["annualized_total_cost"]),
                "energy_balance_passes": bool(row["energy_balance_passes"]),
            }

        successful_df = df.loc[df["run_success"] == True].copy()  # noqa: E712
        feasible_df = successful_df.loc[successful_df["is_feasible"] == True].copy()  # noqa: E712

        if not feasible_df.empty:
            summary["best_feasible"] = _row_summary(feasible_df.iloc[0])

            lowest_npc_df = feasible_df.sort_values(
                by=["net_present_cost", "levelized_cost_of_energy"],
                ascending=[True, True],
            )
            summary["lowest_npc"] = _row_summary(lowest_npc_df.iloc[0])

            lowest_lcoe_df = feasible_df.sort_values(
                by=["levelized_cost_of_energy", "net_present_cost"],
                ascending=[True, True],
            )
            summary["lowest_lcoe"] = _row_summary(lowest_lcoe_df.iloc[0])

        if not successful_df.empty:
            technical_df = successful_df.sort_values(
                by=[
                    "annual_capacity_shortage_pct",
                    "reserve_shortfall_hours",
                    "renewable_fraction_pct",
                    "net_present_cost",
                ],
                ascending=[True, True, False, True],
            )
            summary["technical_best"] = _row_summary(technical_df.iloc[0])

        return summary


def _get_project_dir(project_name: str) -> Path:
    project_dir = Path("projects") / project_name
    if not project_dir.exists():
        raise FileNotFoundError(f"Project folder not found: {project_dir}")
    return project_dir


def _ensure_outputs_dir(project_name: str) -> Path:
    outputs_dir = _get_project_dir(project_name) / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    return outputs_dir


def _build_candidate_result(
    *,
    candidate_id: int,
    design: DesignPoint,
    simulation_results,
    constraint_eval,
    economic_eval,
) -> CandidateSimulationResult:
    summary = simulation_results.summary
    balance_result, _ = validate_energy_balance(simulation_results.to_dataframe())

    total_load_kwh = float(summary.total_load_kwh)
    total_unmet_load_kwh = float(summary.total_unmet_load_kwh)

    unmet_load_pct = (
        total_unmet_load_kwh / total_load_kwh if total_load_kwh > EPSILON else 0.0
    )

    return CandidateSimulationResult(
        candidate_id=candidate_id,
        design=design,
        total_load_kwh=total_load_kwh,
        total_served_load_kwh=float(summary.total_served_load_kwh),
        total_unmet_load_kwh=total_unmet_load_kwh,
        unmet_load_pct=unmet_load_pct,
        total_excess_energy_kwh=float(summary.total_excess_energy_kwh),
        total_pv_generation_kwh=float(summary.total_pv_generation_kwh),
        total_wind_generation_kwh=float(summary.total_wind_generation_kwh),
        total_grid_import_kwh=float(summary.total_grid_import_kwh),
        total_grid_export_kwh=float(summary.total_grid_export_kwh),
        total_battery_charge_kwh=float(summary.total_battery_charge_kwh),
        total_battery_discharge_kwh=float(summary.total_battery_discharge_kwh),
        renewable_fraction=float(summary.renewable_fraction),
        gross_renewable_fraction=float(summary.gross_renewable_fraction),
        annual_capacity_shortage_pct=float(constraint_eval.annual_capacity_shortage_pct),
        renewable_fraction_pct=float(constraint_eval.renewable_fraction_pct),
        max_required_operating_reserve_kw=float(constraint_eval.max_required_operating_reserve_kw),
        min_available_operating_reserve_kw=float(constraint_eval.min_available_operating_reserve_kw),
        reserve_shortfall_hours=int(constraint_eval.reserve_shortfall_hours),
        passes_capacity_shortage=bool(constraint_eval.passes_capacity_shortage),
        passes_renewable_fraction=bool(constraint_eval.passes_renewable_fraction),
        passes_operating_reserve=bool(constraint_eval.passes_operating_reserve),
        is_feasible=bool(constraint_eval.is_feasible),
        failure_reasons=tuple(constraint_eval.failure_reasons),
        direct_capital_cost=float(economic_eval.direct_capital_cost),
        annual_fixed_om_cost=float(economic_eval.annual_fixed_om_cost),
        annual_grid_net_cost=float(economic_eval.annual_grid_net_cost),
        replacement_cost_present_value=float(economic_eval.replacement_cost_present_value),
        salvage_value_present_value=float(economic_eval.salvage_value_present_value),
        annualized_capital_cost=float(economic_eval.annualized_capital_cost),
        annualized_total_cost=float(economic_eval.annualized_total_cost),
        net_present_cost=float(economic_eval.net_present_cost),
        levelized_cost_of_energy=float(economic_eval.levelized_cost_of_energy),
        energy_balance_passes=balance_result.failed_rows == 0,
        energy_balance_failed_rows=int(balance_result.failed_rows),
        energy_balance_max_abs_mismatch_kw=float(balance_result.max_abs_mismatch_kw),
        run_success=True,
        error_message=None,
    )


def run_optimization_sweep(
    project_name: str,
    save_outputs: bool = True,
    constraints: OptimizationConstraints | None = None,
    economic_assumptions: EconomicAssumptions | None = None,
) -> OptimizationSweepResult:
    base_inputs = load_project_simulation_inputs(project_name=project_name)
    candidate_generation = generate_design_candidates(base_inputs.components)

    constraints_used = (
        constraints
        if constraints is not None
        else build_default_constraints_for_project(project_name)
    )

    economic_assumptions_used = (
        economic_assumptions
        if economic_assumptions is not None
        else build_default_economic_assumptions_for_project(project_name, base_inputs.components)
    )

    sweep_result = OptimizationSweepResult(
        project_name=project_name,
        constraints_used=constraints_used,
        economic_assumptions_used=economic_assumptions_used,
        total_raw_combinations=candidate_generation.total_raw_combinations,
        total_valid_candidates=candidate_generation.total_valid_candidates,
        total_filtered_out=candidate_generation.total_filtered_out,
    )

    for candidate_id, design in enumerate(candidate_generation.candidates, start=1):
        try:
            sim_inputs = SimulationInputs(
                load_df=base_inputs.load_df,
                resource_df=base_inputs.resource_df,
                components=base_inputs.components,
                design=design,
                time_step_hours=base_inputs.time_step_hours,
                dispatch_strategy=base_inputs.dispatch_strategy,
            )

            simulator = HybridSystemSimulator(sim_inputs)
            simulation_results = simulator.run()

            constraint_eval = evaluate_candidate_constraints(
                constraints=constraints_used,
                components=base_inputs.components,
                design=design,
                simulation_results=simulation_results,
                time_step_hours=base_inputs.time_step_hours,
            )

            economic_eval = evaluate_candidate_economics(
                project_name=project_name,
                components=base_inputs.components,
                design=design,
                simulation_results=simulation_results,
                assumptions=economic_assumptions_used,
            )

            candidate_result = _build_candidate_result(
                candidate_id=candidate_id,
                design=design,
                simulation_results=simulation_results,
                constraint_eval=constraint_eval,
                economic_eval=economic_eval,
            )

        except Exception as exc:
            candidate_result = CandidateSimulationResult(
                candidate_id=candidate_id,
                design=design,
                run_success=False,
                is_feasible=False,
                error_message=str(exc),
            )

        sweep_result.candidate_results.append(candidate_result)

    if save_outputs:
        save_optimization_sweep_outputs(sweep_result)

    return sweep_result


def save_optimization_sweep_outputs(
    sweep_result: OptimizationSweepResult,
) -> tuple[Path, Path]:
    outputs_dir = _ensure_outputs_dir(sweep_result.project_name)

    csv_path = outputs_dir / "optimization_candidate_summary.csv"
    meta_path = outputs_dir / "optimization_meta.json"

    df = sweep_result.to_dataframe()
    df.to_csv(csv_path, index=False)

    meta = {
        "project_name": sweep_result.project_name,
        "constraints_used": asdict(sweep_result.constraints_used),
        "economic_assumptions_used": asdict(sweep_result.economic_assumptions_used),
        "total_raw_combinations": sweep_result.total_raw_combinations,
        "total_valid_candidates": sweep_result.total_valid_candidates,
        "total_filtered_out": sweep_result.total_filtered_out,
        "successful_runs": sum(1 for x in sweep_result.candidate_results if x.run_success),
        "failed_runs": sum(1 for x in sweep_result.candidate_results if not x.run_success),
        "feasible_candidates": sum(1 for x in sweep_result.candidate_results if x.is_feasible),
        "best_solution_summary": sweep_result.best_solution_summary(),
    }

    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=4)

    return csv_path, meta_path
