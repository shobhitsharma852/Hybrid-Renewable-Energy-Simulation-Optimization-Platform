"""
tests/homer_pro_vs_our_model.py

Direct comparison: HOMER Pro exported results vs our hybrid_homer_engine.

HOW TO USE:
-----------
Step 1 — Set up the same project in HOMER Pro:
    - Load the same resource CSV (GHI, wind speed, temperature)
    - Set the same load profile
    - Use identical component specs (see MATCH_GUIDE below)
    - Use identical economics (project life, discount rate, costs)
    - Run simulation (single architecture, not optimization)

Step 2 — Export from HOMER Pro:
    - Results tab -> Simulation -> click "Export" button
    - Save the hourly CSV (e.g. "homer_hourly.csv")
    - Note the summary numbers (NPC, LCOE, RF, grid import) from the Results table

Step 3 — Run our model:
    - Run run_project_simulation() on your project
    - The hourly output is saved to projects/<name>/outputs/simulation_hourly.csv

Step 4 — Run this script:
    python tests/homer_pro_vs_our_model.py

MATCH_GUIDE — Exact fields to match between HOMER Pro and our model:
---------------------------------------------------------------------
HOMER Pro setting               | Our model field
--------------------------------|------------------------------------------
Solar: Rated capacity (kW)      | DesignPoint.pv_capacity_kw
Solar: Derating factor (%)      | PVComponentConfig.derating_factor
Solar: Temp coefficient (%/degC)| PVTemperatureSettings.temperature_coefficient_pct_per_degC
Solar: NOCT (degC)              | PVTemperatureSettings.nominal_operating_cell_temp_c
Storage: Nominal capacity (kWh) | BatteryComponentConfig.nominal_capacity_kwh_per_string x quantity
Storage: Roundtrip efficiency(%)|BatteryComponentConfig.roundtrip_efficiency_pct
Storage: Min SOC (%)            | BatteryComponentConfig.minimum_state_of_charge_pct
Storage: Initial SOC (%)        | BatteryComponentConfig.initial_state_of_charge_pct
Converter: Inverter efficiency  | ConverterComponentConfig.inverter_efficiency_pct
Converter: Capacity (kW)        | DesignPoint.converter_capacity_kw
Grid: Electricity price ($/kWh) | EconomicAssumptions.grid_purchase_price_per_kwh
Economics: Real discount rate   | EconomicAssumptions.real_discount_rate_pct
Economics: Project lifetime (yr)| EconomicAssumptions.project_life_years

HOMER Pro column names in exported hourly CSV (typical):
---------------------------------------------------------
  "Solar PV Power Output (kW)"         -> our: pv_kw
  "Wind Power Output (kW)"             -> our: wind_kw
  "Battery State of Charge (%)"        -> our: battery_soc_pct
  "Battery Charge Power (kW)"          -> our: battery_charge_kw
  "Battery Discharge Power (kW)"       -> our: battery_discharge_kw
  "Grid Purchases (kW)"                -> our: grid_import_kw
  "Grid Sales (kW)"                    -> our: grid_export_kw
  "Unmet Electric Load (kW)"           -> our: unmet_load_kw

Column names vary by HOMER Pro version — edit HOMER_COL_MAP below to match yours.
"""

from __future__ import annotations

import sys
import os
from pathlib import Path

import pandas as pd
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


# ---------------------------------------------------------------------------
# CONFIGURATION — edit these paths before running
# ---------------------------------------------------------------------------

# Path to HOMER Pro exported hourly CSV
HOMER_HOURLY_CSV = Path("tests/homer_export/homer_hourly.csv")

# Path to our model's hourly output CSV
OUR_HOURLY_CSV = Path("projects/test_3/outputs/simulation_hourly.csv")

# HOMER Pro summary numbers (read from the Results table manually)
HOMER_SUMMARY = {
    "npc_usd":              None,   # e.g. 9_290_000  (fill in from HOMER results)
    "lcoe_usd_per_kwh":     None,   # e.g. 0.0830
    "renewable_fraction":   None,   # e.g. 0.727
    "total_pv_kwh":         None,   # e.g. 2_867_000
    "total_wind_kwh":       None,   # e.g. 3_567_000
    "total_grid_import_kwh":None,   # e.g. 2_391_000
    "total_battery_throughput_kwh": None,  # e.g. 1_705_000
}

# Mapping: HOMER Pro CSV column name -> our column name
# Edit the left side (keys) to match your actual HOMER Pro export column headers.
HOMER_COL_MAP = {
    "Solar PV Power Output (kW)":        "pv_kw",
    "Wind Power Output (kW)":            "wind_kw",
    "Battery State of Charge (%)":       "battery_soc_pct",
    "Battery Charge Power (kW)":         "battery_charge_kw",
    "Battery Discharge Power (kW)":      "battery_discharge_kw",
    "Grid Purchases (kW)":               "grid_import_kw",
    "Grid Sales (kW)":                   "grid_export_kw",
    "Unmet Electric Load (kW)":          "unmet_load_kw",
    "AC Primary Load (kW)":              "load_kw",
}

# Tolerance for hourly comparison (kW) — small differences OK due to rounding
HOURLY_TOLERANCE_KW = 1.0

# Tolerance for annual totals comparison (%)
ANNUAL_TOLERANCE_PCT = 1.0

# Tolerance for economics comparison (%)
ECON_TOLERANCE_PCT = 2.0


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def _safe(s: str) -> str:
    return s.encode("ascii", "replace").decode("ascii")


def _print_section(title: str) -> None:
    print(_safe("=" * 72))
    print(_safe(f"  {title}"))
    print(_safe("=" * 72))


def _pct_diff(our: float, homer: float) -> float:
    if abs(homer) < 1e-9:
        return 0.0 if abs(our) < 1e-9 else float("inf")
    return abs(our - homer) / abs(homer) * 100.0


def _status(diff_pct: float, tol: float) -> str:
    return "[PASS]" if diff_pct <= tol else "[FAIL]"


# ---------------------------------------------------------------------------
# SECTION 1: Load both hourly CSVs
# ---------------------------------------------------------------------------

def load_both_csvs() -> tuple[pd.DataFrame, pd.DataFrame]:
    if not HOMER_HOURLY_CSV.exists():
        print(_safe(f"\n  [SKIP] HOMER hourly CSV not found at: {HOMER_HOURLY_CSV}"))
        print(_safe(f"  Export from HOMER Pro: Results -> Simulation -> Export"))
        print(_safe(f"  Save to: {HOMER_HOURLY_CSV}"))
        return pd.DataFrame(), pd.DataFrame()

    if not OUR_HOURLY_CSV.exists():
        print(_safe(f"\n  [SKIP] Our model output not found at: {OUR_HOURLY_CSV}"))
        print(_safe(f"  Run: python -m core.simulation.run_project_simulation test_3"))
        return pd.DataFrame(), pd.DataFrame()

    homer_df = pd.read_csv(HOMER_HOURLY_CSV)
    our_df = pd.read_csv(OUR_HOURLY_CSV)

    # Rename HOMER columns to our naming convention
    rename = {k: v for k, v in HOMER_COL_MAP.items() if k in homer_df.columns}
    homer_df = homer_df.rename(columns=rename)

    print(_safe(f"  HOMER rows: {len(homer_df)}, Our rows: {len(our_df)}"))

    if len(homer_df) != len(our_df):
        print(_safe(f"  [WARN] Row count mismatch — results may not be comparable"))

    return homer_df, our_df


# ---------------------------------------------------------------------------
# SECTION 2: Annual totals comparison
# ---------------------------------------------------------------------------

def compare_annual_totals(homer_df: pd.DataFrame, our_df: pd.DataFrame) -> list[dict]:
    """Sum each hourly column and compare totals."""
    checks = []

    metrics = [
        ("pv_kw",               "PV Generation (MWh)"),
        ("wind_kw",             "Wind Generation (MWh)"),
        ("grid_import_kw",      "Grid Import (MWh)"),
        ("grid_export_kw",      "Grid Export (MWh)"),
        ("battery_charge_kw",   "Battery Charge (MWh)"),
        ("battery_discharge_kw","Battery Discharge (MWh)"),
        ("unmet_load_kw",       "Unmet Load (MWh)"),
    ]

    for col, label in metrics:
        our_val = our_df[col].sum() / 1000.0 if col in our_df.columns else None
        homer_val = homer_df[col].sum() / 1000.0 if col in homer_df.columns else None

        if our_val is None or homer_val is None:
            checks.append({"label": label, "our": our_val, "homer": homer_val,
                           "diff_pct": None, "pass": None, "note": "column missing"})
            continue

        diff_pct = _pct_diff(our_val, homer_val)
        checks.append({
            "label": label,
            "our": our_val,
            "homer": homer_val,
            "diff_pct": diff_pct,
            "pass": diff_pct <= ANNUAL_TOLERANCE_PCT,
            "note": "",
        })

    return checks


# ---------------------------------------------------------------------------
# SECTION 3: Hour-by-hour comparison
# ---------------------------------------------------------------------------

def compare_hourly(homer_df: pd.DataFrame, our_df: pd.DataFrame) -> dict:
    """Compare each hour individually and find worst mismatches."""
    n = min(len(homer_df), len(our_df))
    results = {}

    columns_to_check = [
        ("pv_kw",               "PV (kW)"),
        ("grid_import_kw",      "Grid Import (kW)"),
        ("battery_soc_pct",     "Battery SOC (%)"),
        ("battery_charge_kw",   "Battery Charge (kW)"),
        ("battery_discharge_kw","Battery Discharge (kW)"),
    ]

    for col, label in columns_to_check:
        if col not in homer_df.columns or col not in our_df.columns:
            results[label] = {"available": False}
            continue

        our_vals = our_df[col].values[:n]
        homer_vals = homer_df[col].values[:n]
        diff = np.abs(our_vals - homer_vals)
        worst_hour = int(np.argmax(diff))

        results[label] = {
            "available": True,
            "max_diff": float(diff.max()),
            "mean_diff": float(diff.mean()),
            "worst_hour": worst_hour,
            "our_at_worst": float(our_vals[worst_hour]),
            "homer_at_worst": float(homer_vals[worst_hour]),
            "pass": float(diff.max()) <= HOURLY_TOLERANCE_KW,
        }

    return results


# ---------------------------------------------------------------------------
# SECTION 4: Economics comparison (HOMER summary table vs our evaluator)
# ---------------------------------------------------------------------------

def compare_economics(our_summary_json: Path) -> list[dict]:
    """Compare NPC, LCOE, RF from HOMER summary vs our simulation_summary.json."""
    import json

    checks = []

    if not any(v is not None for v in HOMER_SUMMARY.values()):
        print(_safe("  [SKIP] Fill in HOMER_SUMMARY at top of this script with"))
        print(_safe("         values from the HOMER Pro Results tab, then re-run."))
        return checks

    if not our_summary_json.exists():
        print(_safe(f"  [SKIP] Our summary not found: {our_summary_json}"))
        return checks

    with open(our_summary_json) as f:
        our = json.load(f)

    pairs = [
        ("total_pv_kwh",         "PV Generation (kWh)",    our.get("total_pv_generation_kwh")),
        ("total_grid_import_kwh","Grid Import (kWh)",       our.get("total_grid_import_kwh")),
        ("renewable_fraction",   "Renewable Fraction",      our.get("renewable_fraction")),
        ("total_battery_throughput_kwh","Battery Throughput (kWh)", our.get("total_battery_throughput_kwh")),
    ]

    for key, label, our_val in pairs:
        homer_val = HOMER_SUMMARY.get(key)
        if homer_val is None or our_val is None:
            continue
        diff_pct = _pct_diff(our_val, homer_val)
        checks.append({
            "label": label,
            "our": our_val,
            "homer": homer_val,
            "diff_pct": diff_pct,
            "pass": diff_pct <= ANNUAL_TOLERANCE_PCT,
        })

    # NPC comparison (if provided)
    if HOMER_SUMMARY.get("npc_usd") and HOMER_SUMMARY.get("lcoe_usd_per_kwh"):
        print(_safe("  NPC and LCOE must be compared from the economics evaluator output,"))
        print(_safe("  not the simulation_summary.json. Run evaluate_candidate_economics()"))
        print(_safe("  and compare its net_present_cost and levelized_cost_of_energy."))

    return checks


# ---------------------------------------------------------------------------
# SECTION 5: Print results
# ---------------------------------------------------------------------------

def print_annual_comparison(checks: list[dict]) -> None:
    hdr = f"  {'Metric':<30} {'HOMER Pro':>12} {'Our Model':>12} {'Diff%':>8} {'Status'}"
    sep = "  " + "-" * 68
    print(_safe(hdr))
    print(_safe(sep))
    for c in checks:
        homer_s = f"{c['homer']:.1f}" if c["homer"] is not None else "N/A"
        our_s   = f"{c['our']:.1f}"   if c["our"]   is not None else "N/A"
        diff_s  = f"{c['diff_pct']:.2f}%" if c["diff_pct"] is not None else "N/A"
        status  = _status(c["diff_pct"], ANNUAL_TOLERANCE_PCT) if c["pass"] is not None else "[N/A]"
        print(_safe(f"  {c['label']:<30} {homer_s:>12} {our_s:>12} {diff_s:>8}  {status}"))


def print_hourly_comparison(results: dict) -> None:
    hdr = f"  {'Variable':<24} {'MaxDiff':>9} {'MeanDiff':>9} {'WorstHr':>8} {'Status'}"
    sep = "  " + "-" * 62
    print(_safe(hdr))
    print(_safe(sep))
    for label, r in results.items():
        if not r.get("available"):
            print(_safe(f"  {label:<24} {'-- column not in CSV':>40}"))
            continue
        status = _status(r["max_diff"], HOURLY_TOLERANCE_KW)
        print(_safe(
            f"  {label:<24} {r['max_diff']:>9.3f} {r['mean_diff']:>9.4f} "
            f"{r['worst_hour']:>8}  {status}"
        ))
        if r["max_diff"] > HOURLY_TOLERANCE_KW:
            print(_safe(
                f"    Worst hour {r['worst_hour']}: "
                f"HOMER={r['homer_at_worst']:.2f}  Ours={r['our_at_worst']:.2f}"
            ))


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main() -> None:
    _print_section("HOMER Pro vs Our Model -- Direct Comparison")
    print()

    # Load CSVs
    _print_section("Step 1: Load Hourly Data")
    print()
    homer_df, our_df = load_both_csvs()
    print()

    if homer_df.empty or our_df.empty:
        print(_safe("  Cannot run hourly comparison without both CSV files."))
        print(_safe("  See HOW TO USE at the top of this script."))
        print()
    else:
        # Annual totals
        _print_section("Step 2: Annual Energy Totals (tolerance: 1%)")
        print()
        annual_checks = compare_annual_totals(homer_df, our_df)
        print_annual_comparison(annual_checks)
        print()
        passed = sum(1 for c in annual_checks if c.get("pass"))
        total  = sum(1 for c in annual_checks if c.get("pass") is not None)
        print(_safe(f"  Annual totals: {passed}/{total} within {ANNUAL_TOLERANCE_PCT}%"))
        print()

        # Hour-by-hour
        _print_section("Step 3: Hour-by-Hour Comparison (tolerance: 1 kW)")
        print()
        hourly_results = compare_hourly(homer_df, our_df)
        print_hourly_comparison(hourly_results)
        print()

    # Economics from summary JSON
    _print_section("Step 4: Economics Comparison")
    print()
    our_summary_json = Path("projects/test_3/outputs/simulation_summary.json")
    econ_checks = compare_economics(our_summary_json)
    if econ_checks:
        print_annual_comparison(econ_checks)
        passed = sum(1 for c in econ_checks if c.get("pass"))
        print(_safe(f"\n  Economics: {passed}/{len(econ_checks)} within {ANNUAL_TOLERANCE_PCT}%"))
    print()

    # Instructions summary
    _print_section("What to Do If Numbers Don't Match")
    print()
    print(_safe("  PV generation mismatch:"))
    print(_safe("    Check derating factor, NOCT, temp coefficient are identical."))
    print(_safe("    HOMER uses W/m2 irradiance -- confirm our resource CSV also uses W/m2."))
    print()
    print(_safe("  Grid import mismatch:"))
    print(_safe("    Check dispatch strategy -- HOMER uses load-following by default."))
    print(_safe("    Check converter capacity -- too small limits PV/battery output."))
    print()
    print(_safe("  Battery SOC mismatch:"))
    print(_safe("    Check initial SOC, min SOC, roundtrip efficiency."))
    print(_safe("    HOMER uses sqrt(eta) split for charge/discharge -- we do too."))
    print()
    print(_safe("  NPC mismatch:"))
    print(_safe("    Check: project life, real discount rate, component lifetimes,"))
    print(_safe("    capital costs, O&M costs, replacement costs."))
    print(_safe("    HOMER's real discount rate uses Fisher equation -- we do too."))
    print()


if __name__ == "__main__":
    main()
