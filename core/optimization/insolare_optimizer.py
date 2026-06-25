"""
core/optimization/insolare_optimizer.py

InSolare Optimizer — continuous search using scipy differential_evolution.

Unlike the Search Space optimizer (which enumerates user-defined discrete options),
the InSolare Optimizer finds the globally optimal component sizing without requiring
predefined options.  It can discover e.g. PV=8,732 kW even when the search space
only lists [2000, 3000, 4000] kW.

Design variables:
  pv_capacity_kw      — continuous float
  wind_quantity       — integer  (integrality handled natively by scipy >= 1.9)
  battery_quantity    — integer
  converter_capacity_kw — continuous float

Objective: minimise NPC.
Feasibility: any infeasible design scores above the infeasibility_floor so a
             feasible design always beats an infeasible one.

Usage:
    from core.optimization.insolare_optimizer import run_insolare_optimizer
    result = run_insolare_optimizer("my_project")
    print(result.optimal_npc, result.optimal_design)
"""
from __future__ import annotations

import json
import os
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field, asdict
from pathlib import Path

import numpy as np
from scipy.optimize import differential_evolution

from core.economics.evaluator import (
    EconomicAssumptions,
    build_default_economic_assumptions_for_project,
    evaluate_candidate_economics,
)
from core.optimization.constraints import (
    OptimizationConstraints,
    build_default_constraints_for_project,
    evaluate_candidate_constraints,
)
from core.optimization.design_point import DesignPoint
from core.optimization.optimizer import (
    CandidateSimulationResult,
    OptimizationSweepResult,
    _build_candidate_result,
)
from core.simulation.run_project_simulation import load_project_simulation_inputs


# ============================================================
# SECTION 1 — MODULE-LEVEL WORKER STATE
# Must be at module level (not inside a function) for Windows
# multiprocessing pickling to work correctly.
# ============================================================

_worker_ctx: dict = {}


def _insolare_worker_init(
    base_inputs,
    constraints: OptimizationConstraints,
    economic_assumptions: EconomicAssumptions,
    project_name: str,
    infeasibility_floor: float,
) -> None:
    """Runs once per worker process — loads shared project data into memory."""
    global _worker_ctx
    _worker_ctx = {
        "base": base_inputs,
        "constraints": constraints,
        "ea": economic_assumptions,
        "project_name": project_name,
        "infeasibility_floor": infeasibility_floor,
    }


def _insolare_objective(x: np.ndarray) -> float:
    """
    Top-level picklable objective function for scipy DE workers.

    Returns NPC for feasible designs.
    Returns infeasibility_floor + violation for infeasible designs,
    so any feasible design always beats any infeasible one.
    """
    from core.simulation import HybridSystemSimulator, SimulationInputs

    pv_kw   = float(x[0])
    n_wind  = int(round(float(x[1])))
    n_batt  = int(round(float(x[2])))
    conv_kw = float(x[3])

    base        = _worker_ctx["base"]
    constraints = _worker_ctx["constraints"]
    ea          = _worker_ctx["ea"]
    pname       = _worker_ctx["project_name"]
    floor       = _worker_ctx["infeasibility_floor"]

    design = DesignPoint(
        pv_capacity_kw=pv_kw,
        wind_quantity=n_wind,
        battery_quantity=n_batt,
        converter_capacity_kw=conv_kw,
    )

    try:
        sim_inputs = SimulationInputs(
            load_df=base.load_df,
            resource_df=base.resource_df,
            components=base.components,
            design=design,
            time_step_hours=base.time_step_hours,
            dispatch_strategy=base.dispatch_strategy,
            latitude_deg=base.latitude_deg,
            longitude_deg=base.longitude_deg,
            timezone_offset_hours=base.timezone_offset_hours,
        )

        sim = HybridSystemSimulator(sim_inputs).run()

        ce = evaluate_candidate_constraints(
            constraints=constraints,
            components=base.components,
            design=design,
            simulation_results=sim,
            time_step_hours=base.time_step_hours,
        )

        econ = evaluate_candidate_economics(
            project_name=pname,
            components=base.components,
            design=design,
            simulation_results=sim,
            assumptions=ea,
        )

        npc = float(econ.net_present_cost)

        if ce.is_feasible:
            return npc

        # Infeasible: normalized violations guide DE toward the feasible region.
        shortage_violation_pct = max(
            0.0,
            ce.annual_capacity_shortage_pct
            - constraints.max_annual_capacity_shortage_pct,
        )
        renewable_violation_pct = max(
            0.0,
            constraints.min_renewable_fraction_pct
            - ce.renewable_fraction_pct,
        )
        return (
            floor
            + shortage_violation_pct * 1e12
            + renewable_violation_pct * 1e11
        )

    except Exception:
        return _worker_ctx["infeasibility_floor"] + 1e15


# ============================================================
# SECTION 2 — CONFIG DATACLASSES
# ============================================================

@dataclass
class InsolareOptimizerBounds:
    """Search bounds for each design variable."""
    pv_kw_min:       float = 0.0
    pv_kw_max:       float = 15000.0
    wind_min:        int   = 0
    wind_max:        int   = 4
    battery_min:     int   = 0
    battery_max:     int   = 40
    converter_kw_min: float = 0.0
    converter_kw_max: float = 6000.0


@dataclass
class InsolareOptimizerConfig:
    """DE algorithm parameters."""
    popsize:        int   = 15     # actual population = popsize × n_vars (= 60)
    maxiter:        int   = 50     # generations → ~3,000 total evals at popsize=15
    tol:            float = 1e-3   # tighter than scipy default (0.01)
    mutation_min:   float = 0.5
    mutation_max:   float = 1.0
    recombination:  float = 0.7
    seed:           int   = 42
    # Auto-expand bounds if optimum hits the upper boundary
    expand_if_binding:      bool = True
    max_expand_rounds:      int  = 2
    binding_frac_threshold: float = 0.05   # "within 5% of upper bound"


# ============================================================
# SECTION 3 — RESULT DATACLASS
# ============================================================

@dataclass
class InsolareOptimizerResult:
    """Full result of one InSolare Optimizer run."""
    project_name:             str
    bounds_used:              InsolareOptimizerBounds
    config_used:              InsolareOptimizerConfig
    constraints_used:         OptimizationConstraints
    economic_assumptions_used: EconomicAssumptions
    infeasibility_floor:      float

    optimal_design:    DesignPoint
    optimal_npc:       float
    optimal_candidate: CandidateSimulationResult

    de_success:  bool
    de_message:  str
    de_nit:      int    # generations completed
    de_nfev:     int    # total simulation calls

    bounds_expanded: bool = False
    expand_rounds:   int  = 0


# ============================================================
# SECTION 4 — AUTO-DERIVE BOUNDS
# ============================================================

def _auto_derive_bounds(base_inputs, config: InsolareOptimizerConfig) -> InsolareOptimizerBounds:
    """
    Derive sensible search bounds from the project load profile and component specs.

    Uses conservative estimates so the true optimum always sits interior to bounds.
    The binding-bound check in run_insolare_optimizer catches any remaining edge cases.
    """
    load_df    = base_inputs.load_df
    components = base_inputs.components

    annual_load_kwh = float(load_df["load_kw"].sum()) * base_inputs.time_step_hours
    daily_load_kwh  = annual_load_kwh / 365.0
    peak_load_kw    = float(load_df["load_kw"].max())

    # PV bounds — use component Set Limits if configured, else auto-derive
    pv = components.pv
    if not pv.enabled:
        pv_kw_min = pv_kw_max = 0.0
    elif not pv.use_search_space and pv.optimizer_set_limits:
        pv_kw_min = pv.optimizer_kw_min
        pv_kw_max = pv.optimizer_kw_max
    else:
        # 2× energy-balance at a conservative 16% CF so bound is never too tight for low-yield sites
        pv_kw_min = 0.0
        pv_kw_max = round(2.0 * annual_load_kwh / (0.16 * 8760), -2)
        pv_kw_max = max(pv_kw_max, 5000.0)

    # Battery bounds — use component Set Limits if configured, else auto-derive
    bat = components.battery
    if not bat.enabled:
        battery_min = battery_max = 0
    elif not bat.use_search_space and bat.optimizer_set_limits:
        battery_min = bat.optimizer_qty_min
        battery_max = bat.optimizer_qty_max
    else:
        usable_per_string = (
            bat.nominal_capacity_kwh_per_string
            * (1.0 - bat.minimum_state_of_charge_pct / 100.0)
        ) if bat.enabled else 1000.0
        battery_min = 0
        battery_max = max(int(2.5 * daily_load_kwh / usable_per_string) + 5, 20)

    # Wind bounds — use component Set Limits if configured, else auto-derive
    wnd = components.wind
    if not wnd.use_search_space and wnd.optimizer_set_limits:
        wind_min = wnd.optimizer_qty_min
        wind_max = wnd.optimizer_qty_max
    elif wnd.enabled and wnd.quantity_options:
        wind_min = 0
        wind_max = max(max(wnd.quantity_options) * 2, 4)
    else:
        wind_min = 0
        wind_max = 0 if not wnd.enabled else 4

    # Converter bounds — use component Set Limits if configured, else auto-derive
    conv = components.converter
    if not conv.enabled:
        conv_kw_min = conv_kw_max = 0.0
    elif not conv.use_search_space and conv.optimizer_set_limits:
        conv_kw_min = conv.optimizer_kw_min
        conv_kw_max = conv.optimizer_kw_max
    else:
        conv_kw_min = 0.0
        conv_kw_max = round(max(1.5 * peak_load_kw, 0.5 * pv_kw_max), -2)
        conv_kw_max = max(conv_kw_max, 3000.0)

    return InsolareOptimizerBounds(
        pv_kw_min=pv_kw_min,
        pv_kw_max=pv_kw_max,
        wind_min=wind_min,
        wind_max=wind_max,
        battery_min=battery_min,
        battery_max=battery_max,
        converter_kw_min=conv_kw_min,
        converter_kw_max=conv_kw_max,
    )


def _compute_infeasibility_floor(
    base_inputs,
    bounds: InsolareOptimizerBounds,
    economic_assumptions: EconomicAssumptions,
) -> float:
    """
    Compute a scale-aware infeasibility floor well above plausible feasible NPC.
    """
    c = base_inputs.components
    max_capex = (
        bounds.pv_kw_max  * c.pv.capital_cost_per_kw
        + bounds.wind_max * c.wind.capital_cost_per_turbine
        + bounds.battery_max * c.battery.capital_cost_per_string
        + bounds.converter_kw_max * c.converter.capital_cost_per_kw
    )
    annual_load_kwh = (
        float(base_inputs.load_df["load_kw"].sum())
        * float(base_inputs.time_step_hours)
    )
    project_life_years = float(economic_assumptions.project_life_years)
    grid_price = max(
        1.0,
        float(getattr(c.grid, "grid_power_price_per_kwh", 0.0)),
    )
    lifetime_grid_cost_scale = annual_load_kwh * project_life_years * grid_price
    return max(1e18, (max_capex + lifetime_grid_cost_scale) * 1e6)


# ============================================================
# SECTION 5 — BINDING-BOUND CHECK
# ============================================================

def _binding_bound_indices(
    x: np.ndarray,
    bounds: list[tuple[float, float]],
    frac: float = 0.05,
) -> list[int]:
    """Return indices where the optimum is within frac of the upper bound."""
    binding = []
    for i, (lo, hi) in enumerate(bounds):
        if hi > lo and (hi - float(x[i])) / (hi - lo) <= frac:
            binding.append(i)
    return binding


def _explicit_upper_bound_mask(base_inputs) -> list[bool]:
    """True where the user explicitly requested a hard optimizer upper limit."""
    c = base_inputs.components
    return [
        bool(c.pv.enabled and not c.pv.use_search_space and c.pv.optimizer_set_limits),
        bool(c.wind.enabled and not c.wind.use_search_space and c.wind.optimizer_set_limits),
        bool(c.battery.enabled and not c.battery.use_search_space and c.battery.optimizer_set_limits),
        bool(
            c.converter.enabled
            and not c.converter.use_search_space
            and c.converter.optimizer_set_limits
        ),
    ]


def _expand_bounds(
    scipy_bounds: list[tuple[float, float]],
    binding_indices: list[int],
    grow: float = 1.5,
) -> list[tuple[float, float]]:
    """Expand upper bounds for binding variables by grow factor."""
    new_bounds = list(scipy_bounds)
    for i in binding_indices:
        lo, hi = scipy_bounds[i]
        new_bounds[i] = (lo, hi * grow)
    return new_bounds


# ============================================================
# SECTION 6 — FINAL CANDIDATE EVALUATION (MAIN PROCESS)
# ============================================================

def _evaluate_optimal_in_main_process(
    *,
    base_inputs,
    constraints: OptimizationConstraints,
    economic_assumptions: EconomicAssumptions,
    project_name: str,
    optimal_design: DesignPoint,
) -> CandidateSimulationResult:
    """
    Run one full simulation for the optimal design in the main process.
    This produces the complete CandidateSimulationResult needed for the
    dashboard table and "Send to Results" button.
    """
    from core.simulation import HybridSystemSimulator, SimulationInputs

    sim_inputs = SimulationInputs(
        load_df=base_inputs.load_df,
        resource_df=base_inputs.resource_df,
        components=base_inputs.components,
        design=optimal_design,
        time_step_hours=base_inputs.time_step_hours,
        dispatch_strategy=base_inputs.dispatch_strategy,
        latitude_deg=base_inputs.latitude_deg,
        longitude_deg=base_inputs.longitude_deg,
        timezone_offset_hours=base_inputs.timezone_offset_hours,
    )

    sim_results  = HybridSystemSimulator(sim_inputs).run()
    constraint_eval = evaluate_candidate_constraints(
        constraints=constraints,
        components=base_inputs.components,
        design=optimal_design,
        simulation_results=sim_results,
        time_step_hours=base_inputs.time_step_hours,
    )
    economic_eval = evaluate_candidate_economics(
        project_name=project_name,
        components=base_inputs.components,
        design=optimal_design,
        simulation_results=sim_results,
        assumptions=economic_assumptions,
    )

    return _build_candidate_result(
        candidate_id=1,
        design=optimal_design,
        simulation_results=sim_results,
        constraint_eval=constraint_eval,
        economic_eval=economic_eval,
    )


# ============================================================
# SECTION 7 — MAIN OPTIMIZER FUNCTION
# ============================================================

def run_insolare_optimizer(
    project_name: str,
    bounds: InsolareOptimizerBounds | None = None,
    config: InsolareOptimizerConfig | None = None,
    constraints: OptimizationConstraints | None = None,
    economic_assumptions: EconomicAssumptions | None = None,
    save_outputs: bool = True,
    progress_callback: Callable[[int, int, float], None] | None = None,
) -> InsolareOptimizerResult:
    """
    Run the InSolare Optimizer for a project.

    Parameters
    ----------
    project_name : str
        Project folder name under projects/.
    bounds : InsolareOptimizerBounds, optional
        Search bounds. Auto-derived from load profile if not provided.
    config : InsolareOptimizerConfig, optional
        DE algorithm parameters. Defaults used if not provided.
    constraints : OptimizationConstraints, optional
        Feasibility constraints. Project defaults used if not provided.
    economic_assumptions : EconomicAssumptions, optional
        Economic assumptions. Project defaults used if not provided.
    save_outputs : bool
        Whether to save CSV + JSON outputs.
    progress_callback : callable, optional
        Called after each DE generation as callback(gen, maxiter, convergence).

    Returns
    -------
    InsolareOptimizerResult
    """
    if config is None:
        config = InsolareOptimizerConfig()

    base_inputs = load_project_simulation_inputs(project_name=project_name)

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

    # Auto-derive bounds if not provided
    bounds_used = bounds if bounds is not None else _auto_derive_bounds(base_inputs, config)

    scipy_bounds = [
        (bounds_used.pv_kw_min,        bounds_used.pv_kw_max),
        (float(bounds_used.wind_min),   float(bounds_used.wind_max)),
        (float(bounds_used.battery_min), float(bounds_used.battery_max)),
        (bounds_used.converter_kw_min,  bounds_used.converter_kw_max),
    ]
    integrality = [False, True, True, False]

    n_workers = min(os.cpu_count() or 1, 16)
    explicit_upper_bounds = _explicit_upper_bound_mask(base_inputs)

    bounds_expanded = False
    expand_rounds   = 0
    de_result       = None

    for expand_round in range(config.max_expand_rounds + 1):
        # Re-compute floor after any bound expansion (bounds affect max CAPEX)
        current_bounds = InsolareOptimizerBounds(
            pv_kw_min=scipy_bounds[0][0],
            pv_kw_max=scipy_bounds[0][1],
            wind_min=int(scipy_bounds[1][0]),
            wind_max=int(scipy_bounds[1][1]),
            battery_min=int(scipy_bounds[2][0]),
            battery_max=int(scipy_bounds[2][1]),
            converter_kw_min=scipy_bounds[3][0],
            converter_kw_max=scipy_bounds[3][1],
        )
        infeasibility_floor = _compute_infeasibility_floor(
            base_inputs,
            current_bounds,
            economic_assumptions_used,
        )

        # Build a generation-level callback that bridges to the user's callback
        _gen_counter = [0]

        def _de_callback(xk, convergence):
            _gen_counter[0] += 1
            if progress_callback is not None:
                progress_callback(_gen_counter[0], config.maxiter, float(convergence))
            return False   # never stop early from callback

        with ProcessPoolExecutor(
            max_workers=n_workers,
            initializer=_insolare_worker_init,
            initargs=(
                base_inputs,
                constraints_used,
                economic_assumptions_used,
                project_name,
                infeasibility_floor,
            ),
        ) as executor:
            de_result = differential_evolution(
                _insolare_objective,
                scipy_bounds,
                integrality=integrality,
                strategy="best1bin",
                maxiter=config.maxiter,
                popsize=config.popsize,
                tol=config.tol,
                mutation=(config.mutation_min, config.mutation_max),
                recombination=config.recombination,
                workers=executor.map,
                updating="deferred",
                polish=False,   # L-BFGS polish ignores integrality — keep off
                seed=config.seed,
                callback=_de_callback,
            )

        # Check for binding upper bounds — expand and re-run if needed
        if config.expand_if_binding:
            binding = _binding_bound_indices(
                de_result.x,
                scipy_bounds,
                frac=config.binding_frac_threshold,
            )
            binding = [
                idx for idx in binding if not explicit_upper_bounds[idx]
            ]
            if binding and expand_round < config.max_expand_rounds:
                scipy_bounds = _expand_bounds(scipy_bounds, binding, grow=1.5)
                bounds_expanded = True
                expand_rounds += 1
                continue   # re-run with wider bounds

        break   # no binding bounds or hit expand limit

    assert de_result is not None

    # Extract optimal design from DE result
    x       = de_result.x
    pv_kw   = float(x[0])
    n_wind  = int(round(float(x[1])))
    n_batt  = int(round(float(x[2])))
    conv_kw = float(x[3])

    optimal_design = DesignPoint(
        pv_capacity_kw=pv_kw,
        wind_quantity=n_wind,
        battery_quantity=n_batt,
        converter_capacity_kw=conv_kw,
    )

    # Full simulation of the winner in the main process for dashboard detail
    optimal_candidate = _evaluate_optimal_in_main_process(
        base_inputs=base_inputs,
        constraints=constraints_used,
        economic_assumptions=economic_assumptions_used,
        project_name=project_name,
        optimal_design=optimal_design,
    )

    result = InsolareOptimizerResult(
        project_name=project_name,
        bounds_used=current_bounds,
        config_used=config,
        constraints_used=constraints_used,
        economic_assumptions_used=economic_assumptions_used,
        infeasibility_floor=infeasibility_floor,
        optimal_design=optimal_design,
        optimal_npc=float(optimal_candidate.net_present_cost),
        optimal_candidate=optimal_candidate,
        de_success=bool(de_result.success),
        de_message=str(de_result.message),
        de_nit=int(de_result.nit),
        de_nfev=int(de_result.nfev),
        bounds_expanded=bounds_expanded,
        expand_rounds=expand_rounds,
    )

    if save_outputs:
        save_insolare_optimizer_outputs(result)

    return result


# ============================================================
# SECTION 8 — SAVE OUTPUTS
# ============================================================

def save_insolare_optimizer_outputs(result: InsolareOptimizerResult) -> tuple[Path, Path]:
    """
    Save the InSolare Optimizer result to disk.

    Outputs:
      insolare_optimizer_summary.csv  — same column format as optimization_candidate_summary.csv
      insolare_optimizer_meta.json    — bounds, DE stats, optimal design
    """
    outputs_dir = Path("projects") / result.project_name / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)

    # Build a minimal OptimizationSweepResult with the one optimal candidate so
    # the existing to_dataframe() method generates the correct column format.
    sweep = OptimizationSweepResult(
        project_name=result.project_name,
        constraints_used=result.constraints_used,
        economic_assumptions_used=result.economic_assumptions_used,
        total_raw_combinations=result.de_nfev,
        total_valid_candidates=1,
        total_filtered_out=result.de_nfev - 1,
        candidate_results=[result.optimal_candidate],
    )

    csv_path  = outputs_dir / "insolare_optimizer_summary.csv"
    meta_path = outputs_dir / "insolare_optimizer_meta.json"

    sweep.to_dataframe().to_csv(csv_path, index=False)

    meta = {
        "project_name":    result.project_name,
        "optimizer":       "InsolareOptimizer-DE",
        "bounds_used": {
            "pv_kw_max":       result.bounds_used.pv_kw_max,
            "wind_max":        result.bounds_used.wind_max,
            "battery_max":     result.bounds_used.battery_max,
            "converter_kw_max": result.bounds_used.converter_kw_max,
        },
        "infeasibility_floor": result.infeasibility_floor,
        "de_converged":    result.de_success,
        "de_message":      result.de_message,
        "de_iterations":   result.de_nit,
        "de_evaluations":  result.de_nfev,
        "bounds_expanded": result.bounds_expanded,
        "expand_rounds":   result.expand_rounds,
        "optimal_design": {
            "pv_capacity_kw":      result.optimal_design.pv_capacity_kw,
            "wind_quantity":       result.optimal_design.wind_quantity,
            "battery_quantity":    result.optimal_design.battery_quantity,
            "converter_capacity_kw": result.optimal_design.converter_capacity_kw,
        },
        "optimal_npc": result.optimal_npc,
        # Dashboard-compatible summary fields
        "total_raw_combinations":  result.de_nfev,
        "total_valid_candidates":  1,
        "total_filtered_out":      result.de_nfev - 1,
        "successful_runs":         1,
        "failed_runs":             0,
        "feasible_candidates":     1 if result.optimal_candidate.is_feasible else 0,
        "best_solution_summary": {
            "lowest_npc": {
                "pv_capacity_kw":      result.optimal_design.pv_capacity_kw,
                "wind_quantity":       result.optimal_design.wind_quantity,
                "battery_quantity":    result.optimal_design.battery_quantity,
                "converter_capacity_kw": result.optimal_design.converter_capacity_kw,
                "net_present_cost":    result.optimal_npc,
                "is_feasible":         result.optimal_candidate.is_feasible,
            }
        },
    }

    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=4, default=float)

    return csv_path, meta_path


def load_insolare_optimizer_outputs(project_name: str):
    """Load saved InSolare Optimizer outputs (CSV + meta JSON)."""
    import pandas as pd

    outputs_dir = Path("projects") / project_name / "outputs"
    csv_path    = outputs_dir / "insolare_optimizer_summary.csv"
    meta_path   = outputs_dir / "insolare_optimizer_meta.json"

    df   = pd.read_csv(csv_path)   if csv_path.exists()  else None
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else None

    return df, meta
