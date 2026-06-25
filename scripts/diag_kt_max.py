"""
Diagnostic: test kt_max = 1.0 (HOMER-equivalent) vs 0.82 (current).

Finding so far:
  Baseline (kt=0.82, temp ON):  CF 16.22%,  NPC +6.29M vs HOMER
  kt cap OFF (raw GHI):         CF 16.29%,  NPC +4.04M vs HOMER
  Remaining gap with cap OFF:   CF +0.04%,  ~29k kWh/yr

This script tests kt_max = 1.0 (cap only at physical impossibility).
"""
import sys, dataclasses
sys.path.insert(0, ".")

from core.simulation.run_project_simulation import load_project_simulation_inputs
from core.simulation import HybridSystemSimulator, SimulationInputs
from core.optimization.design_point import DesignPoint
from core.optimization.optimizer import _build_candidate_result
from core.optimization.constraints import build_default_constraints_for_project, evaluate_candidate_constraints
from core.economics.evaluator import build_default_economic_assumptions_for_project, evaluate_candidate_economics
from core.components.pv import PVComponentConfig, PVOrientationSettings

PROJECT      = "test10"
HOMER_NPC    = 1_011_321_000
HOMER_CF     = 16.33
HOMER_GEN    = HOMER_CF / 100 * 8732 * 8760
BASELINE_NPC = 1_017_609_504
BASELINE_CF  = 16.22

print("Loading project...")
base        = load_project_simulation_inputs(PROJECT)
constraints = build_default_constraints_for_project(PROJECT)
ea          = build_default_economic_assumptions_for_project(PROJECT, base.components)
design = DesignPoint(pv_capacity_kw=8732.0, wind_quantity=1, battery_quantity=24, converter_capacity_kw=3000.0)

orig_pv = base.components.pv

def make_pv_with_kt(kt_max_val, use_cap):
    new_orient = PVOrientationSettings(
        enabled=orig_pv.orientation.enabled,
        ground_reflectance_pct=orig_pv.orientation.ground_reflectance_pct,
        tracking_system=orig_pv.orientation.tracking_system,
        use_default_slope=orig_pv.orientation.use_default_slope,
        panel_slope_deg=orig_pv.orientation.panel_slope_deg,
        use_default_azimuth=orig_pv.orientation.use_default_azimuth,
        panel_azimuth_deg=orig_pv.orientation.panel_azimuth_deg,
        use_clearness_index_cap=use_cap,
        kt_max=kt_max_val,
    )
    return dataclasses.replace(orig_pv, orientation=new_orient)

def sim(components):
    inp = SimulationInputs(
        load_df=base.load_df, resource_df=base.resource_df,
        components=components, design=design,
        time_step_hours=base.time_step_hours,
        dispatch_strategy=base.dispatch_strategy,
        latitude_deg=base.latitude_deg, longitude_deg=base.longitude_deg,
        timezone_offset_hours=base.timezone_offset_hours,
    )
    s  = HybridSystemSimulator(inp).run()
    ce = evaluate_candidate_constraints(constraints=constraints, components=components,
        design=design, simulation_results=s, time_step_hours=base.time_step_hours)
    ec = evaluate_candidate_economics(project_name=PROJECT, components=components,
        design=design, simulation_results=s, assumptions=ea)
    r  = _build_candidate_result(candidate_id=0, design=design, simulation_results=s,
        constraint_eval=ce, economic_eval=ec)
    gen = s.summary.total_pv_generation_kwh
    cf  = gen / (design.pv_capacity_kw * 8760) * 100
    return r.net_present_cost, gen, cf

print("Simulating kt_max = 0.90...")
c90 = dataclasses.replace(base.components, pv=make_pv_with_kt(0.90, True))
npc90, gen90, cf90 = sim(c90)

print("Simulating kt_max = 1.00 (physical limit)...")
c100 = dataclasses.replace(base.components, pv=make_pv_with_kt(1.00, True))
npc100, gen100, cf100 = sim(c100)

print()
print("=" * 72)
print("kt_max sweep — HOMER design (8732 kW PV + 24 bat + 3000 kW conv)")
print("=" * 72)
print(f"{'Variant':<25} {'CF%':>6}  {'PV Gen kWh':>13}  {'NPC INR':>14}  {'vs HOMER':>12}")
print("-" * 72)
print(f"{'HOMER Pro (reference)':<25} {HOMER_CF:>6.2f}  {HOMER_GEN:>13,.0f}  {'—':>14}  {'0':>12}")
print(f"{'kt_max=0.82 (current)':<25} {BASELINE_CF:>6.2f}  {'12,410,355':>13}  {BASELINE_NPC:>14,}  {BASELINE_NPC-HOMER_NPC:>+12,}")
print(f"{'kt_max=0.90':<25} {cf90:>6.2f}  {gen90:>13,.0f}  {npc90:>14,.0f}  {npc90-HOMER_NPC:>+12,.0f}")
print(f"{'kt_max=1.00':<25} {cf100:>6.2f}  {gen100:>13,.0f}  {npc100:>14,.0f}  {npc100-HOMER_NPC:>+12,.0f}")
print(f"{'kt cap OFF':<25} {'16.29':>6}  {'12,461,886':>13}  {'1,015,356,310':>14}  {'+4,035,310':>12}")

print()
print("Gap breakdown:")
gap_total = 80841  # kWh, HOMER vs our baseline
gap_082_to_100 = gen100 - 12_410_355
gap_100_to_off = 12_461_886 - gen100
print(f"  Total gap (HOMER - baseline):          {gap_total:>10,.0f} kWh/yr = 100%")
print(f"  Closed by kt_max 0.82 → 1.00:         {gap_082_to_100:>+10,.0f} kWh/yr = {gap_082_to_100/gap_total*100:.0f}%")
print(f"  Residual (1.00 → no cap):              {gap_100_to_off:>+10,.0f} kWh/yr = {gap_100_to_off/gap_total*100:.0f}%")
remaining = gap_total - gap_082_to_100 - gap_100_to_off
print(f"  Unexplained (solar geometry / other):  {remaining:>+10,.0f} kWh/yr = {remaining/gap_total*100:.0f}%")
