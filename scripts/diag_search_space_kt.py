"""Compare all 54 search space combinations: kt_max=0.82 vs kt_max=1.00."""
import sys, dataclasses, itertools
sys.path.insert(0, ".")

from core.simulation.run_project_simulation import load_project_simulation_inputs
from core.simulation import HybridSystemSimulator, SimulationInputs
from core.optimization.design_point import DesignPoint
from core.optimization.optimizer import _build_candidate_result
from core.optimization.constraints import build_default_constraints_for_project, evaluate_candidate_constraints
from core.economics.evaluator import build_default_economic_assumptions_for_project, evaluate_candidate_economics
from core.components.pv import PVOrientationSettings

PROJECT = "test10"
base        = load_project_simulation_inputs(PROJECT)
constraints = build_default_constraints_for_project(PROJECT)
ea          = build_default_economic_assumptions_for_project(PROJECT, base.components)
orig_pv     = base.components.pv

def make_components(kt_max_val):
    new_orient = PVOrientationSettings(
        enabled=orig_pv.orientation.enabled,
        ground_reflectance_pct=orig_pv.orientation.ground_reflectance_pct,
        tracking_system=orig_pv.orientation.tracking_system,
        use_default_slope=orig_pv.orientation.use_default_slope,
        panel_slope_deg=orig_pv.orientation.panel_slope_deg,
        use_default_azimuth=orig_pv.orientation.use_default_azimuth,
        panel_azimuth_deg=orig_pv.orientation.panel_azimuth_deg,
        use_clearness_index_cap=True,
        kt_max=kt_max_val,
    )
    return dataclasses.replace(base.components, pv=dataclasses.replace(orig_pv, orientation=new_orient))

comps82  = make_components(0.82)
comps100 = make_components(1.00)

pv_opts   = [2000, 3000, 4000]
wnd_opts  = [1, 2]
bat_opts  = [2, 4, 6]
conv_opts = [1500, 2500, 3500]

def sim_npc(comps, design):
    inp = SimulationInputs(
        load_df=base.load_df, resource_df=base.resource_df,
        components=comps, design=design,
        time_step_hours=base.time_step_hours,
        dispatch_strategy=base.dispatch_strategy,
        latitude_deg=base.latitude_deg,
        longitude_deg=base.longitude_deg,
        timezone_offset_hours=base.timezone_offset_hours,
    )
    s  = HybridSystemSimulator(inp).run()
    ce = evaluate_candidate_constraints(constraints=constraints, components=comps,
        design=design, simulation_results=s, time_step_hours=base.time_step_hours)
    ec = evaluate_candidate_economics(project_name=PROJECT, components=comps,
        design=design, simulation_results=s, assumptions=ea)
    r  = _build_candidate_result(candidate_id=0, design=design, simulation_results=s,
        constraint_eval=ce, economic_eval=ec)
    return r.net_present_cost, ce.is_feasible

rows = []
total = len(pv_opts) * len(wnd_opts) * len(bat_opts) * len(conv_opts)
done = 0
for pv, wnd, bat, conv in itertools.product(pv_opts, wnd_opts, bat_opts, conv_opts):
    d = DesignPoint(pv_capacity_kw=float(pv), wind_quantity=wnd,
                    battery_quantity=bat, converter_capacity_kw=float(conv))
    npc82,  ok82  = sim_npc(comps82,  d)
    npc100, ok100 = sim_npc(comps100, d)
    rows.append((pv, wnd, bat, conv, npc82, npc100, ok82))
    done += 1
    if done % 9 == 0:
        print(f"  {done}/{total} combinations done...")

rows.sort(key=lambda r: r[4])  # sort by kt=0.82 NPC ascending

print()
print("PV kW  Wind  Bat  Conv kW  |  NPC kt=0.82        NPC kt=1.00      Saving INR | OK")
print("-" * 90)
for pv, wnd, bat, conv, n82, n100, ok in rows:
    feas = "Y" if ok else "N"
    print(f"{pv:>5}  {wnd:>4}  {bat:>3}  {conv:>7}  |  {n82:>15,.0f}    {n100:>15,.0f}   {n82-n100:>10,.0f} | {feas}")

print()
feasible = [r for r in rows if r[6]]
best82  = min(feasible, key=lambda r: r[4])
best100 = min(feasible, key=lambda r: r[5])

print("=" * 70)
print(f"Best (kt=0.82):  PV={best82[0]} kW, Wind={best82[1]}, Bat={best82[2]}, Conv={best82[3]} kW")
print(f"  NPC = {best82[4]:,.0f} INR")
print()
print(f"Best (kt=1.00):  PV={best100[0]} kW, Wind={best100[1]}, Bat={best100[2]}, Conv={best100[3]} kW")
print(f"  NPC = {best100[5]:,.0f} INR")
print()
saving = best82[4] - best100[5]
same   = best82[:4] == best100[:4]
print(f"NPC improvement on best design: INR {saving:,.0f}  ({saving/best82[4]*100:.3f}%)")
print(f"Same optimal design chosen:     {'Yes' if same else 'No -- kt_max changes the winner!'}")
