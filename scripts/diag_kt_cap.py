"""Diagnostic: quantify the effect of the clearness-index cap on annual PV generation."""
import sys
sys.path.insert(0, ".")
import pandas as pd
import numpy as np

from core.simulation.run_project_simulation import load_project_simulation_inputs
from core.simulation import HybridSystemSimulator, SimulationInputs
from core.optimization.design_point import DesignPoint
from core.optimization.optimizer import _build_candidate_result
from core.optimization.constraints import build_default_constraints_for_project, evaluate_candidate_constraints
from core.economics.evaluator import build_default_economic_assumptions_for_project, evaluate_candidate_economics
from core.components.pv import PVComponentConfig, PVOrientationSettings, PVTemperatureSettings

PROJECT = "test10"
HOMER_NPC = 1_011_321_000
HOMER_CF  = 16.33
CAPACITY  = 8732.0

print("Loading project...")
base        = load_project_simulation_inputs(PROJECT)
constraints = build_default_constraints_for_project(PROJECT)
ea          = build_default_economic_assumptions_for_project(PROJECT, base.components)
df = base.resource_df

# ── 1. Analyse the capped hours ────────────────────────────────────────────
kt_cap = 0.82
n_capped_82  = (df["clearness_index"] > kt_cap).sum()
n_capped_10  = (df["clearness_index"] > 1.0).sum()
n_range      = ((df["clearness_index"] > kt_cap) & (df["clearness_index"] <= 1.0)).sum()
print(f"\nClearness-index analysis:")
print(f"  kt > 0.82:          {n_capped_82} hours/yr")
print(f"  kt > 1.00:          {n_capped_10} hours/yr  (physically impossible — data artefacts)")
print(f"  0.82 < kt <= 1.00:  {n_range}  hours/yr  (legitimate clear-sky hours)")

capped = df[df["clearness_index"] > kt_cap].copy()
capped["our_ghi"]    = capped["clearness_index"].clip(upper=kt_cap) * capped["g0_w_m2"]
capped["ghi_delta"]  = capped["ghi"] - capped["our_ghi"]
total_ghi_diff = capped["ghi_delta"].sum() / 1000  # kWh/m2/yr
est_gen_diff   = total_ghi_diff / 1.0 * 0.8 * CAPACITY  # rough (no tilt/temp)
print(f"\n  GHI suppressed by kt cap: {total_ghi_diff:.1f} kWh/m2/yr")
print(f"  Rough PV gen lost:        {est_gen_diff:,.0f} kWh/yr at {CAPACITY} kW")
print(f"  Rough CF reduction:       {est_gen_diff / (CAPACITY * 8760) * 100:.3f}%")

homer_gen = HOMER_CF / 100 * CAPACITY * 8760
our_gen   = 12_410_355
print(f"\n  Actual gap (HOMER - ours): {homer_gen - our_gen:,.0f} kWh/yr")
print(f"  Fraction explained by kt cap: {est_gen_diff / (homer_gen - our_gen) * 100:.0f}%")


# ── 2. Simulation helper ────────────────────────────────────────────────────
def sim_npc_with_components(components, design):
    inp = SimulationInputs(
        load_df=base.load_df, resource_df=base.resource_df,
        components=components, design=design,
        time_step_hours=base.time_step_hours,
        dispatch_strategy=base.dispatch_strategy,
        latitude_deg=base.latitude_deg,
        longitude_deg=base.longitude_deg,
        timezone_offset_hours=base.timezone_offset_hours,
    )
    s  = HybridSystemSimulator(inp).run()
    ce = evaluate_candidate_constraints(constraints=constraints, components=components,
        design=design, simulation_results=s, time_step_hours=base.time_step_hours)
    ec = evaluate_candidate_economics(project_name=PROJECT, components=components,
        design=design, simulation_results=s, assumptions=ea)
    r  = _build_candidate_result(candidate_id=0, design=design, simulation_results=s,
        constraint_eval=ce, economic_eval=ec)
    pv_gen = s.summary.total_pv_generation_kwh
    cf     = pv_gen / (design.pv_capacity_kw * 8760) * 100
    return r.net_present_cost, pv_gen, cf


# ── 3. Build a modified PV config with kt cap disabled ─────────────────────
orig_pv = base.components.pv
new_orientation = PVOrientationSettings(
    enabled=orig_pv.orientation.enabled,
    ground_reflectance_pct=orig_pv.orientation.ground_reflectance_pct,
    tracking_system=orig_pv.orientation.tracking_system,
    use_default_slope=orig_pv.orientation.use_default_slope,
    panel_slope_deg=orig_pv.orientation.panel_slope_deg,
    use_default_azimuth=orig_pv.orientation.use_default_azimuth,
    panel_azimuth_deg=orig_pv.orientation.panel_azimuth_deg,
    use_clearness_index_cap=False,   # <── disable kt cap
    kt_max=orig_pv.orientation.kt_max,
)
from core.components.pv import PVMPPTSettings
new_pv_no_cap = PVComponentConfig(
    enabled=orig_pv.enabled,
    use_search_space=orig_pv.use_search_space,
    capacity_kw_options=orig_pv.capacity_kw_options,
    optimizer_kw_min=orig_pv.optimizer_kw_min,
    optimizer_kw_max=orig_pv.optimizer_kw_max,
    optimizer_set_limits=orig_pv.optimizer_set_limits,
    capital_cost_per_kw=orig_pv.capital_cost_per_kw,
    replacement_cost_per_kw=orig_pv.replacement_cost_per_kw,
    om_cost_per_kw_per_year=orig_pv.om_cost_per_kw_per_year,
    lifetime_years=orig_pv.lifetime_years,
    derating_factor=orig_pv.derating_factor,
    bus=orig_pv.bus,
    mppt=orig_pv.mppt,
    orientation=new_orientation,
    temperature=orig_pv.temperature,
)


# ── 4. Also test with temperature correction disabled ──────────────────────
new_temp_off = PVTemperatureSettings(
    enabled=False,
    temperature_coefficient_pct_per_degC=orig_pv.temperature.temperature_coefficient_pct_per_degC,
    nominal_operating_cell_temp_c=orig_pv.temperature.nominal_operating_cell_temp_c,
    efficiency_stc_pct=orig_pv.temperature.efficiency_stc_pct,
)
new_pv_no_temp = PVComponentConfig(
    enabled=orig_pv.enabled,
    use_search_space=orig_pv.use_search_space,
    capacity_kw_options=orig_pv.capacity_kw_options,
    optimizer_kw_min=orig_pv.optimizer_kw_min,
    optimizer_kw_max=orig_pv.optimizer_kw_max,
    optimizer_set_limits=orig_pv.optimizer_set_limits,
    capital_cost_per_kw=orig_pv.capital_cost_per_kw,
    replacement_cost_per_kw=orig_pv.replacement_cost_per_kw,
    om_cost_per_kw_per_year=orig_pv.om_cost_per_kw_per_year,
    lifetime_years=orig_pv.lifetime_years,
    derating_factor=orig_pv.derating_factor,
    bus=orig_pv.bus,
    mppt=orig_pv.mppt,
    orientation=orig_pv.orientation,   # original (kt cap ON)
    temperature=new_temp_off,
)


# ── 5. Run all four variants ────────────────────────────────────────────────
from copy import copy
import dataclasses

def replace_components_pv(comps, new_pv):
    return dataclasses.replace(comps, pv=new_pv)

design = DesignPoint(pv_capacity_kw=CAPACITY, wind_quantity=1, battery_quantity=24, converter_capacity_kw=3000.0)

print("\nRunning simulations (HOMER design, 8732 kW)...")
comps_orig    = base.components
comps_no_cap  = replace_components_pv(comps_orig, new_pv_no_cap)
comps_no_temp = replace_components_pv(comps_orig, new_pv_no_temp)

print("  [1/3] Baseline (kt cap ON, temp ON)...")
npc1, gen1, cf1 = sim_npc_with_components(comps_orig, design)
print("  [2/3] kt cap OFF (temp ON)...")
npc2, gen2, cf2 = sim_npc_with_components(comps_no_cap, design)
print("  [3/3] kt cap ON, temp OFF...")
npc3, gen3, cf3 = sim_npc_with_components(comps_no_temp, design)

print()
print("=" * 70)
print("Variant                     CF%    PV Gen kWh      NPC INR      vs HOMER")
print("-" * 70)
print(f"HOMER Pro (reference)     {HOMER_CF:.2f}%  {homer_gen:12,.0f}             0")
print(f"Baseline (cap+temp)       {cf1:.2f}%  {gen1:12,.0f}  {npc1:12,.0f}  {npc1-HOMER_NPC:+12,.0f}")
print(f"kt cap OFF                {cf2:.2f}%  {gen2:12,.0f}  {npc2:12,.0f}  {npc2-HOMER_NPC:+12,.0f}")
print(f"Temperature OFF           {cf3:.2f}%  {gen3:12,.0f}  {npc3:12,.0f}  {npc3-HOMER_NPC:+12,.0f}")

print()
print("Delta from baseline:")
print(f"  kt cap OFF:    CF {cf2-cf1:+.2f}%  Gen {gen2-gen1:+,.0f} kWh  NPC {npc2-npc1:+,.0f} INR")
print(f"  Temp OFF:      CF {cf3-cf1:+.2f}%  Gen {gen3-gen1:+,.0f} kWh  NPC {npc3-npc1:+,.0f} INR")
