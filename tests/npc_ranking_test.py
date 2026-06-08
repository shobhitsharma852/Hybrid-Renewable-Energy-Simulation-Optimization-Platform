"""
tests/npc_ranking_test.py

Multi-category NPC ranking test.

Purpose:
  Verify that our hybrid_homer_engine produces economically consistent NPC
  rankings across 6 system configuration categories, mimicking how HOMER Pro
  would rank candidates in an optimization sweep.

Categories:
  1. Grid Only          -- baseline, pure grid import
  2. PV + Grid          -- 4 PV sizes competing to offset grid
  3. Wind + Grid        -- 3 turbine counts using Indian wind resource
  4. PV + Battery + Grid -- 4 combos: 2 PV sizes x 2 battery sizes
  5. PV + Wind + Grid   -- 2 combos: PV + 1 turbine hybrid
  6. Full Hybrid        -- 4 combos: PV + Wind + Battery + Grid

Economics -- Realistic India 2025-26 market rates (USD; 1 USD = Rs 84):
  Grid buy:  $0.12/kWh  (Rs 10/kWh  -- HT commercial tariff, India average)
  Grid sell: $0.036/kWh (Rs  3/kWh  -- net metering rate, most states)

  PV (1-3 MW ground-mount EPC all-in):
      Capital/Replacement  $535/kW    (Rs 44,940/kW ~ Rs 4.5 Cr/MW)
      O&M                   $6/kW/yr  (Rs 504/kW/yr)
      Lifetime              25 years

  Wind (1.5 MW turbine, installed incl. civil + grid connection):
      Capital/Replacement  $893,000/turbine  (Rs 7.5 Cr/turbine)
      O&M                  $23,000/turbine/yr (Rs 19.3 lakh/turbine/yr)
      Lifetime             20 years

  Battery (Li-Ion LFP, 1 MWh per string, installed BESS system):
      Capital/Replacement  $260,000/string   (Rs 2.18 Cr/MWh)
      O&M                   $7,000/string/yr (Rs 5.88 lakh/MWh/yr)
      Throughput           8,000,000 kWh/string (~4,000 LFP cycles x 2 x 1MWh)
      Lifetime             15 years (calendar)

  Converter (bidirectional solar inverter):
      Capital/Replacement  $95/kW  (Rs 7,980/kW)
      Lifetime             15 years

  Project life: 25 years | Real discount rate: 8%
      (~14% nominal borrowing rate - 6% inflation, Fisher equation)

Data source: projects/test_3 (1 GWh/yr load, Indian solar+wind resource)

Checks applied after ranking:
  [C1]  Energy balance passes for every candidate (0 failed rows)
  [C2]  No unmet load for any candidate (grid backs up all deficits)
  [C3]  NPC > 0 for all candidates
  [C4]  More PV => less grid import (within PV+Grid category)
  [C5]  More battery => less grid import (same PV, more storage)
  [C6]  Capital cost is proportional to installed capacity
  [C7]  Renewable fraction increases as more renewable capacity is added
  [C8]  NPC rank == LCOE rank (same served load across candidates)
  [C9]  Grid-Only LCOE equals the grid purchase price (no capital cost)
  [C10] PV addition is economical (NPC(best PV+Grid) < NPC(Grid-Only))
"""

from __future__ import annotations

import sys
import os
import dataclasses
from dataclasses import dataclass
from typing import NamedTuple

# ---------------------------------------------------------------------------
# Ensure project root is on path
# ---------------------------------------------------------------------------
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.components.config import ComponentsConfig
from core.components.pv import PVComponentConfig, PVTemperatureSettings
from core.components.wind import WindComponentConfig, WindPowerCurveSettings
from core.components.battery import BatteryComponentConfig
from core.components.converter import ConverterComponentConfig
from core.components.grid import GridComponentConfig
from core.economics.evaluator import EconomicAssumptions, evaluate_candidate_economics
from core.optimization.design_point import DesignPoint
from core.simulation import HybridSystemSimulator, SimulationInputs
from core.simulation.energy_balance import validate_energy_balance
from core.simulation.run_project_simulation import load_project_simulation_inputs


# ---------------------------------------------------------------------------
# SECTION 1: TEST ECONOMICS
# ---------------------------------------------------------------------------

ASSUMPTIONS = EconomicAssumptions(
    project_life_years=25.0,
    real_discount_rate_pct=8.0,        # ~14% nominal - 6% inflation (Fisher)
    grid_purchase_price_per_kwh=0.12,  # Rs 10/kWh — India HT commercial avg
    grid_export_price_per_kwh=0.036,   # Rs 3/kWh  — net metering sell-back
)

# Grid config used by all candidates
GRID_CFG = GridComponentConfig(
    enabled=True,
    grid_power_price_per_kwh=0.12,     # Rs 10/kWh
    grid_sellback_price_per_kwh=0.036, # Rs 3/kWh
    purchase_capacity_kw=999_999.0,
    sale_capacity_kw=999_999.0,
)

# PV template — Rs 4.5 Cr/MW EPC (ground-mount, India 2025-26)
def _pv_cfg(pv_kw: float) -> PVComponentConfig:
    return PVComponentConfig(
        enabled=(pv_kw > 0),
        capacity_kw_options=[0.0, max(1.0, pv_kw)],
        capital_cost_per_kw=535.0,      # $535/kW  (Rs 44,940/kW ~ Rs 4.5 Cr/MW)
        replacement_cost_per_kw=535.0,
        om_cost_per_kw_per_year=6.0,    # $6/kW/yr (Rs 504/kW/yr)
        lifetime_years=25,
        derating_factor=0.80,           # India dust/soiling derating
        temperature=PVTemperatureSettings(
            enabled=True,
            temperature_coefficient_pct_per_degC=-0.5,
            nominal_operating_cell_temp_c=47.0,
        ),
    )


# Wind template — 1.5 MW turbine, Rs 7.5 Cr/turbine installed (India 2025-26)
def _wind_cfg(n_turbines: int) -> WindComponentConfig:
    return WindComponentConfig(
        enabled=(n_turbines > 0),
        rated_capacity_kw=1_500.0,
        quantity_options=[0, max(1, n_turbines)],
        capital_cost_per_turbine=893_000.0,     # $893k/turbine (Rs 7.5 Cr)
        replacement_cost_per_turbine=893_000.0,
        om_cost_per_turbine_per_year=23_000.0,  # $23k/yr (Rs 19.3 lakh/yr)
        lifetime_years=20,
        hub_height_m=80.0,
    )


# Battery template — Li-Ion LFP, Rs 2.18 Cr/MWh installed (India 2025-26)
def _bat_cfg(n_strings: int) -> BatteryComponentConfig:
    return BatteryComponentConfig(
        enabled=(n_strings > 0),
        nominal_capacity_kwh_per_string=1_000.0,
        quantity_options=[0, max(1, n_strings)],
        roundtrip_efficiency_pct=90.0,
        minimum_state_of_charge_pct=20.0,
        initial_state_of_charge_pct=100.0,
        capital_cost_per_string=260_000.0,      # $260k/MWh (Rs 2.18 Cr/MWh)
        replacement_cost_per_string=260_000.0,
        om_cost_per_string_per_year=7_000.0,    # $7k/MWh/yr (Rs 5.88 lakh/yr)
        throughput_kwh=8_000_000.0,             # LFP ~4,000 cycles x 2 x 1,000 kWh
        lifetime_years=15,
        self_discharge_rate_pct_per_day=0.05,
        replacement_degradation_limit_pct=20.0,
    )


# Converter template — Rs 7,980/kW bidirectional solar inverter (India 2025-26)
def _conv_cfg(capacity_kw: float) -> ConverterComponentConfig:
    return ConverterComponentConfig(
        enabled=(capacity_kw > 0),
        capacity_kw_options=[0.0, max(1.0, capacity_kw)],
        capital_cost_per_kw=95.0,       # $95/kW (Rs 7,980/kW)
        replacement_cost_per_kw=95.0,
        om_cost_per_kw_per_year=0.0,
        inverter_lifetime_years=15,
        inverter_efficiency_pct=95.0,
        rectifier_efficiency_pct=95.0,
        rectifier_relative_capacity_pct=100.0,
    )


# Disabled PV (used when PV is absent)
_PV_OFF = _pv_cfg(0.0)
# Disabled Wind (used when wind is absent)
_WIND_OFF = _wind_cfg(0)
# Disabled Battery
_BAT_OFF = _bat_cfg(0)
# Disabled Converter
_CONV_OFF = _conv_cfg(0.0)


# ---------------------------------------------------------------------------
# SECTION 2: CANDIDATE DEFINITIONS
# ---------------------------------------------------------------------------

@dataclass
class CandidateSpec:
    """Defines one system configuration to simulate and rank."""
    category: str
    label: str
    pv_kw: float
    wind_n: int
    bat_n: int
    # converter sized externally based on PV; 0 = disabled (AC-only sources)
    conv_kw: float


def _make_candidates() -> list[CandidateSpec]:
    specs: list[CandidateSpec] = []

    # ---- Category 1: Grid Only ----
    specs.append(CandidateSpec("1-Grid Only", "Grid Only", 0, 0, 0, 0))

    # ---- Category 2: PV + Grid ----
    for pv in (500.0, 1000.0, 2000.0, 3000.0):
        specs.append(CandidateSpec(
            "2-PV+Grid", f"PV {int(pv)} kW",
            pv_kw=pv, wind_n=0, bat_n=0, conv_kw=pv,
        ))

    # ---- Category 3: Wind + Grid ----
    for n in (1, 2, 3):
        specs.append(CandidateSpec(
            "3-Wind+Grid", f"{n} Turbine(s)",
            pv_kw=0, wind_n=n, bat_n=0, conv_kw=0,  # wind is AC-bus, no converter needed
        ))

    # ---- Category 4: PV + Battery + Grid ----
    for pv, bat in ((1000.0, 2), (1000.0, 5), (2000.0, 2), (2000.0, 5)):
        specs.append(CandidateSpec(
            "4-PV+Bat+Grid", f"PV {int(pv)} kW + {bat} bat",
            pv_kw=pv, wind_n=0, bat_n=bat, conv_kw=pv,
        ))

    # ---- Category 5: PV + Wind + Grid ----
    specs.append(CandidateSpec(
        "5-PV+Wind+Grid", "PV 1000 + 1 Turbine",
        pv_kw=1000, wind_n=1, bat_n=0, conv_kw=1000,
    ))
    specs.append(CandidateSpec(
        "5-PV+Wind+Grid", "PV 2000 + 2 Turbines",
        pv_kw=2000, wind_n=2, bat_n=0, conv_kw=2000,
    ))

    # ---- Category 6: Full Hybrid (PV + Wind + Battery + Grid) ----
    for pv, bat in ((1000.0, 2), (1000.0, 5), (2000.0, 2), (2000.0, 5)):
        specs.append(CandidateSpec(
            "6-Full Hybrid", f"PV {int(pv)} + 1T + {bat} bat",
            pv_kw=pv, wind_n=1, bat_n=bat, conv_kw=pv,
        ))

    return specs


# ---------------------------------------------------------------------------
# SECTION 3: SIMULATION RUNNER
# ---------------------------------------------------------------------------

@dataclass
class CandidateResult:
    spec: CandidateSpec
    # Simulation outputs
    total_load_kwh: float = 0.0
    total_pv_kwh: float = 0.0
    total_wind_kwh: float = 0.0
    total_grid_import_kwh: float = 0.0
    total_grid_export_kwh: float = 0.0
    total_battery_charge_kwh: float = 0.0
    total_battery_discharge_kwh: float = 0.0
    total_unmet_kwh: float = 0.0
    renewable_fraction: float = 0.0
    energy_balance_failed_rows: int = 0
    energy_balance_max_mismatch: float = 0.0
    # Economics
    direct_capital_cost: float = 0.0
    annual_grid_cost: float = 0.0
    npc: float = 0.0
    lcoe: float = 0.0
    error: str | None = None


def _run_candidate(
    spec: CandidateSpec,
    load_df,
    resource_df,
) -> CandidateResult:
    result = CandidateResult(spec=spec)
    try:
        design = DesignPoint(
            pv_capacity_kw=spec.pv_kw,
            wind_quantity=spec.wind_n,
            battery_quantity=spec.bat_n,
            converter_capacity_kw=spec.conv_kw,
        )
        components = ComponentsConfig(
            pv=_pv_cfg(spec.pv_kw),
            wind=_wind_cfg(spec.wind_n),
            battery=_bat_cfg(spec.bat_n),
            converter=_conv_cfg(spec.conv_kw),
            grid=GRID_CFG,
        )
        inputs = SimulationInputs(
            load_df=load_df,
            resource_df=resource_df,
            components=components,
            design=design,
        )
        sim = HybridSystemSimulator(inputs)
        sim_results = sim.run()

        # Energy balance check
        hourly_df = sim_results.to_dataframe()
        balance, _ = validate_energy_balance(hourly_df)

        # Economics
        econ = evaluate_candidate_economics(
            project_name="test_3",
            components=components,
            design=design,
            simulation_results=sim_results,
            assumptions=ASSUMPTIONS,
        )

        s = sim_results.summary
        result.total_load_kwh = s.total_load_kwh
        result.total_pv_kwh = s.total_pv_generation_kwh
        result.total_wind_kwh = s.total_wind_generation_kwh
        result.total_grid_import_kwh = s.total_grid_import_kwh
        result.total_grid_export_kwh = s.total_grid_export_kwh
        result.total_battery_charge_kwh = s.total_battery_charge_kwh
        result.total_battery_discharge_kwh = s.total_battery_discharge_kwh
        result.total_unmet_kwh = s.total_unmet_load_kwh
        result.renewable_fraction = s.renewable_fraction
        result.energy_balance_failed_rows = balance.failed_rows
        result.energy_balance_max_mismatch = balance.max_abs_mismatch_kw
        result.direct_capital_cost = econ.direct_capital_cost
        result.annual_grid_cost = econ.annual_grid_net_cost
        result.npc = econ.net_present_cost
        result.lcoe = econ.levelized_cost_of_energy

    except Exception as exc:
        result.error = str(exc)

    return result


# ---------------------------------------------------------------------------
# SECTION 4: VERIFICATION CHECKS
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str


def _run_checks(results: list[CandidateResult]) -> list[CheckResult]:
    checks: list[CheckResult] = []

    def chk(name: str, condition: bool, detail: str) -> None:
        checks.append(CheckResult(name, condition, detail))

    successful = [r for r in results if r.error is None]

    # [C1] Energy balance passes for every candidate
    failed_eb = [r for r in successful if r.energy_balance_failed_rows > 0]
    chk(
        "[C1] Energy balance",
        len(failed_eb) == 0,
        (
            f"All {len(successful)} candidates pass"
            if not failed_eb
            else f"FAILED: {len(failed_eb)} candidates have balance errors: "
                 + ", ".join(r.spec.label for r in failed_eb)
        ),
    )

    # [C2] No unmet load
    unmet = [r for r in successful if r.total_unmet_kwh > 1.0]
    chk(
        "[C2] No unmet load",
        len(unmet) == 0,
        (
            f"All {len(successful)} candidates have no unmet load"
            if not unmet
            else f"FAILED: unmet load > 1 kWh in " + ", ".join(r.spec.label for r in unmet)
        ),
    )

    # [C3] NPC > 0 for all candidates
    neg_npc = [r for r in successful if r.npc <= 0]
    chk(
        "[C3] NPC > 0",
        len(neg_npc) == 0,
        (
            f"All {len(successful)} candidates have positive NPC"
            if not neg_npc
            else f"FAILED: non-positive NPC in " + ", ".join(r.spec.label for r in neg_npc)
        ),
    )

    # [C4] More PV => less grid import (within PV+Grid category)
    pv_grid = [r for r in successful if r.spec.category == "2-PV+Grid"]
    pv_grid_sorted = sorted(pv_grid, key=lambda r: r.spec.pv_kw)
    c4_pass = True
    c4_detail = "Monotonic: "
    for i in range(len(pv_grid_sorted) - 1):
        a, b = pv_grid_sorted[i], pv_grid_sorted[i + 1]
        if b.total_grid_import_kwh > a.total_grid_import_kwh + 1.0:
            c4_pass = False
            c4_detail += f"FAILED at PV {int(a.spec.pv_kw)}->{int(b.spec.pv_kw)} kW. "
    if c4_pass:
        vals = " -> ".join(f"{int(r.total_grid_import_kwh/1000)}k" for r in pv_grid_sorted)
        c4_detail = f"Grid import decreases with PV: {vals} kWh"
    chk("[C4] More PV => less grid import", c4_pass, c4_detail)

    # [C5] More battery => less grid import (same PV, compare bat=2 vs bat=5)
    pb_grid = [r for r in successful if r.spec.category == "4-PV+Bat+Grid"]
    c5_pass = True
    c5_pairs = []
    for pv in (1000.0, 2000.0):
        low_bat = next((r for r in pb_grid if r.spec.pv_kw == pv and r.spec.bat_n == 2), None)
        hi_bat = next((r for r in pb_grid if r.spec.pv_kw == pv and r.spec.bat_n == 5), None)
        if low_bat and hi_bat:
            ok = hi_bat.total_grid_import_kwh <= low_bat.total_grid_import_kwh + 1.0
            c5_pairs.append(
                f"PV{int(pv)}kW 2bat({int(low_bat.total_grid_import_kwh/1000)}k) "
                f"vs 5bat({int(hi_bat.total_grid_import_kwh/1000)}k) kWh"
                + ("" if ok else " [FAIL]")
            )
            if not ok:
                c5_pass = False
    chk(
        "[C5] More battery => less grid import",
        c5_pass,
        " | ".join(c5_pairs) if c5_pairs else "No battery candidates found",
    )

    # [C6] Capital cost proportional to installed capacity
    # For PV+Grid: capital should increase with PV size
    pv_caps = sorted(pv_grid, key=lambda r: r.spec.pv_kw)
    c6_pass = all(
        pv_caps[i + 1].direct_capital_cost > pv_caps[i].direct_capital_cost
        for i in range(len(pv_caps) - 1)
    )
    chk(
        "[C6] Capital cost proportional to capacity",
        c6_pass,
        (
            "Capital costs increase with PV size: "
            + " -> ".join(f"${int(r.direct_capital_cost/1000)}k" for r in pv_caps)
            if c6_pass
            else "FAILED: capital cost not monotonic with PV size"
        ),
    )

    # [C7] Renewable fraction increases with more renewables
    grid_only = next((r for r in successful if r.spec.category == "1-Grid Only"), None)
    best_pv = max(pv_grid, key=lambda r: r.spec.pv_kw) if pv_grid else None
    c7_pass = True
    c7_detail = ""
    if grid_only and best_pv:
        c7_pass = best_pv.renewable_fraction > grid_only.renewable_fraction
        c7_detail = (
            f"Grid-Only RF={grid_only.renewable_fraction:.1%}, "
            f"PV3000 RF={best_pv.renewable_fraction:.1%}"
        )
    chk("[C7] RF increases with renewables", c7_pass, c7_detail)

    # [C8] NPC rank == LCOE rank
    # All candidates serve the same load; LCOE = NPC * CRF / served_load
    # so LCOE rank should match NPC rank exactly
    ranked_npc = sorted(successful, key=lambda r: r.npc)
    ranked_lcoe = sorted(successful, key=lambda r: r.lcoe)
    c8_pass = all(
        ranked_npc[i].spec.label == ranked_lcoe[i].spec.label
        for i in range(len(ranked_npc))
    )
    chk(
        "[C8] NPC rank == LCOE rank",
        c8_pass,
        "NPC and LCOE rankings are identical" if c8_pass else "Rankings differ",
    )

    # [C9] Grid-Only LCOE = grid purchase price (no capital cost)
    if grid_only:
        expected = ASSUMPTIONS.grid_purchase_price_per_kwh
        actual = grid_only.lcoe
        tol = 0.001
        c9_pass = abs(actual - expected) < tol
        chk(
            "[C9] Grid-Only LCOE = grid price",
            c9_pass,
            f"Expected {expected:.4f}, got {actual:.4f} $/kWh",
        )

    # [C10] Adding PV is economical (NPC < Grid-Only)
    if grid_only and pv_grid:
        best_pv_r = min(pv_grid, key=lambda r: r.npc)
        c10_pass = best_pv_r.npc < grid_only.npc
        chk(
            "[C10] Best PV+Grid < Grid-Only NPC",
            c10_pass,
            (
                f"Best PV ({best_pv_r.spec.label}): NPC=${best_pv_r.npc/1e6:.2f}M "
                f"vs Grid-Only: ${grid_only.npc/1e6:.2f}M"
            ),
        )

    return checks


# ---------------------------------------------------------------------------
# SECTION 5: PRINTING HELPERS
# ---------------------------------------------------------------------------

def _safe(s: str) -> str:
    """Strip non-ASCII so Windows cp1252 terminal doesn't crash."""
    return s.encode("ascii", "replace").decode("ascii")


def _print_header(title: str) -> None:
    line = "=" * 78
    print(_safe(line))
    print(_safe(f"  {title}"))
    print(_safe(line))


def _print_ranked_table(ranked: list[CandidateResult]) -> None:
    hdr = (
        f"{'Rk':>3}  {'Category':<18} {'Label':<24} "
        f"{'PV':>5} {'Wnd':>3} {'Bat':>3} "
        f"{'NPC($M)':>8} {'LCOE':>7} {'RF':>6} {'Grid(MWh)':>10}"
    )
    sep = "-" * 88
    print(_safe(hdr))
    print(_safe(sep))
    for i, r in enumerate(ranked, 1):
        cat = r.spec.category.split("-", 1)[-1]   # strip numeric prefix
        label = r.spec.label
        pv = f"{int(r.spec.pv_kw)}" if r.spec.pv_kw > 0 else "--"
        wnd = f"{r.spec.wind_n}" if r.spec.wind_n > 0 else "--"
        bat = f"{r.spec.bat_n}" if r.spec.bat_n > 0 else "--"
        npc = f"{r.npc / 1e6:.2f}" if r.error is None else "ERROR"
        lcoe = f"{r.lcoe:.4f}" if r.error is None else "ERROR"
        rf = f"{r.renewable_fraction:.1%}" if r.error is None else "ERR"
        grid = f"{r.total_grid_import_kwh / 1000:.0f}" if r.error is None else "ERR"
        row = (
            f"{i:>3}  {cat:<18} {label:<24} "
            f"{pv:>5} {wnd:>3} {bat:>3} "
            f"{npc:>8} {lcoe:>7} {rf:>6} {grid:>10}"
        )
        print(_safe(row))
    print(_safe(sep))
    print(_safe(f"  Columns: PV=kW, Wnd=turbines, Bat=strings, LCOE=$/kWh, Grid=MWh/yr"))


def _print_checks(checks: list[CheckResult]) -> None:
    pass_count = sum(1 for c in checks if c.passed)
    for c in checks:
        tag = "[PASS]" if c.passed else "[FAIL]"
        print(_safe(f"  {tag}  {c.name}"))
        print(_safe(f"         {c.detail}"))
    print(_safe(""))
    print(_safe(f"  Result: {pass_count}/{len(checks)} checks passed"))


def _print_capital_breakdown(ranked: list[CandidateResult]) -> None:
    """Print capital cost breakdown to verify economics calculations."""
    hdr = (
        f"{'Label':<24} {'Capital($k)':>12} {'GrdCost($/yr)':>14} "
        f"{'NPC($M)':>8}"
    )
    sep = "-" * 65
    print(_safe(hdr))
    print(_safe(sep))
    for r in ranked:
        if r.error:
            continue
        cap = f"{r.direct_capital_cost/1000:.0f}"
        grd = f"{r.annual_grid_cost:.0f}"
        npc = f"{r.npc/1e6:.3f}"
        print(_safe(f"{r.spec.label:<24} {cap:>12} {grd:>14} {npc:>8}"))


# ---------------------------------------------------------------------------
# SECTION 6: MAIN
# ---------------------------------------------------------------------------

def main() -> None:
    _print_header("NPC RANKING TEST  --  Multi-Category Hybrid System Optimization")
    print()

    # Load test_3 data once (1 GWh/yr constant load, Indian solar+wind resource)
    print(_safe("Loading project data from test_3 ..."))
    base_inputs = load_project_simulation_inputs("test_3")
    load_df = base_inputs.load_df.copy()
    resource_df = base_inputs.resource_df.copy()
    print(_safe(f"  Load rows: {len(load_df)}, Resource rows: {len(resource_df)}"))
    print(_safe(f"  Annual load: {load_df['load_kw'].sum():.0f} kWh"))
    print()

    # Build candidate list
    candidates = _make_candidates()
    print(_safe(f"Running {len(candidates)} candidates across 6 categories ..."))
    print()

    # Run each candidate
    results: list[CandidateResult] = []
    for i, spec in enumerate(candidates, 1):
        print(_safe(f"  [{i:02d}/{len(candidates)}] {spec.category}  |  {spec.label} ..."), end="", flush=True)
        r = _run_candidate(spec, load_df, resource_df)
        results.append(r)
        if r.error:
            print(_safe(f"  ERROR: {r.error[:60]}"))
        else:
            print(_safe(f"  NPC=${r.npc/1e6:.2f}M  LCOE={r.lcoe:.4f}  RF={r.renewable_fraction:.1%}"))

    print()

    # Sort by NPC (ascending)
    successful = [r for r in results if r.error is None]
    failed = [r for r in results if r.error is not None]
    ranked = sorted(successful, key=lambda r: r.npc)

    # Print ranked table
    _print_header("RANKED RESULTS  (sorted by NPC, lowest = best)")
    print()
    _print_ranked_table(ranked)
    print()

    # Print capital cost breakdown
    _print_header("ECONOMICS BREAKDOWN")
    print()
    # Sort breakdown by NPC too
    _print_capital_breakdown(ranked)
    print()
    print(_safe(f"  Realistic India 2025-26 rates | 25yr project | 8% real discount rate"))
    print(_safe(f"  Grid:      $0.12/kWh buy (Rs 10/kWh) | $0.036/kWh sell (Rs 3/kWh)"))
    print(_safe(f"  PV:        $535/kW capital (Rs 4.5 Cr/MW) | $6/kW/yr OM | 25yr life"))
    print(_safe(f"  Wind:      $893k/turbine (Rs 7.5 Cr)    | $23k/yr OM  | 20yr life"))
    print(_safe(f"  Battery:   $260k/MWh (Rs 2.18 Cr/MWh)  | $7k/yr OM   | 15yr life | LFP"))
    print(_safe(f"  Converter: $95/kW (Rs 7,980/kW)         | 15yr life"))
    print()

    # Run verification checks
    _print_header("VERIFICATION CHECKS")
    print()
    checks = _run_checks(results)
    _print_checks(checks)
    print()

    # Failed candidates
    if failed:
        _print_header("FAILED CANDIDATES")
        print()
        for r in failed:
            print(_safe(f"  FAILED: {r.spec.label}  --  {r.error}"))
        print()

    # Final verdict
    pass_count = sum(1 for c in checks if c.passed)
    total = len(checks)
    all_pass = (pass_count == total) and (len(failed) == 0)
    _print_header("FINAL VERDICT")
    print()
    verdict_tag = "[ALL PASS]" if all_pass else "[SOME FAIL]"
    print(_safe(
        f"  {verdict_tag}  {pass_count}/{total} checks passed, "
        f"{len(failed)} simulation errors"
    ))

    # Print top-3 summary
    print()
    print(_safe("  Top 3 candidates:"))
    for i, r in enumerate(ranked[:3], 1):
        print(_safe(
            f"    #{i}  {r.spec.label:<26}  "
            f"NPC=${r.npc/1e6:.2f}M  LCOE=${r.lcoe:.4f}/kWh  RF={r.renewable_fraction:.1%}"
        ))
    print()

    return all_pass


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
