#!/usr/bin/env python3
"""
HOMER Pro Comparison Test
=========================
Verifies that hybrid_homer_engine produces outputs matching HOMER Pro formulas.

Each test case uses analytically hand-computed expected values.
All expected values are derived from the documented HOMER Pro equations.

Run from the project root:
    python tests/homer_pro_comparison.py
"""
from __future__ import annotations

import math
import sys
from dataclasses import dataclass

sys.path.insert(0, ".")

import pandas as pd

from core.components.battery import BatteryComponentConfig
from core.components.config import ComponentsConfig
from core.components.converter import ConverterComponentConfig
from core.components.grid import GridComponentConfig
from core.components.pv import PVComponentConfig, PVTemperatureSettings
from core.components.wind import WindComponentConfig
from core.optimization.design_point import DesignPoint
from core.simulation import HybridSystemSimulator, SimulationInputs
from core.simulation.battery_soc import BatteryState, update_battery_state
from core.simulation.dispatch import run_dispatch_step
from core.simulation.energy_balance import validate_energy_balance
from core.simulation.pv_model import compute_cell_temperature_c, compute_pv_power_output


# ??? HOMER Pro constants ?????????????????????????????????????????????????????
ETA_RT   = 0.90               # roundtrip efficiency (fraction)
ETA_HALF = math.sqrt(ETA_RT)  # eta_charge = eta_discharge = sqrt(eta_rt) ? 0.94868
ETA_INV  = 0.95               # inverter efficiency
ETA_RECT = 0.95               # rectifier efficiency
CAP_KWH  = 1000.0             # battery nominal capacity (kWh)
MIN_SOC  = 20.0               # minimum SOC (%)
MIN_KWH  = CAP_KWH * MIN_SOC / 100.0  # 200 kWh ? energy floor
INV_KW   = 2000.0             # inverter capacity (kW) ? large, not limiting
VOLT     = 600.0              # battery nominal voltage
TOL      = 0.01               # tolerance for comparisons (kWh / kW / %)


# ??? Test result type ????????????????????????????????????????????????????????

@dataclass
class TR:
    name: str
    passed: bool
    expected: float
    actual: float
    deviation: float
    unit: str = ""

    def __str__(self) -> str:
        tag = "PASS" if self.passed else "FAIL"
        return (
            f"  [{tag}] {self.name}\n"
            f"         Expected : {self.expected:.6f} {self.unit}\n"
            f"         Got      : {self.actual:.6f} {self.unit}\n"
            f"         Deviation: {self.deviation:.6f} {self.unit}"
        )


def chk(name: str, expected: float, actual: float, unit: str = "", tol: float = TOL) -> TR:
    dev = abs(actual - expected)
    return TR(name, dev <= tol, expected, actual, dev, unit)


def chk_zero(name: str, actual: float, unit: str = "", tol: float = 1e-9) -> TR:
    return chk(name, 0.0, actual, unit, tol)


def flag(name: str, condition: bool, expected: float, actual: float, unit: str = "") -> TR:
    """Inequality / range check."""
    dev = abs(actual - expected)
    return TR(name, condition, expected, actual, dev, unit)


# ??? Component config factories ??????????????????????????????????????????????

def _bat(min_soc: float = MIN_SOC, eta_pct: float = 90.0,
         init_soc: float = 100.0, self_dis: float = 0.0) -> BatteryComponentConfig:
    return BatteryComponentConfig(
        enabled=True,
        nominal_voltage_v=VOLT,
        nominal_capacity_kwh_per_string=CAP_KWH,
        roundtrip_efficiency_pct=eta_pct,
        max_charge_current_a=10_000.0,   # very high ? hardware limit not active
        max_discharge_current_a=10_000.0,
        minimum_state_of_charge_pct=min_soc,
        initial_state_of_charge_pct=init_soc,
        self_discharge_rate_pct_per_day=self_dis,
        throughput_kwh=1e12,             # infinite ? no degradation
        # turn off all fade mechanisms so they don't interfere
        cycle_life_a=0.0,
        cycle_life_beta=0.0,
        calendar_fade_pct_per_year=0.0,
        replacement_degradation_limit_pct=20.0,
    )


def _conv() -> ConverterComponentConfig:
    return ConverterComponentConfig(
        enabled=True,
        inverter_efficiency_pct=ETA_INV * 100.0,
        rectifier_efficiency_pct=ETA_RECT * 100.0,
        rectifier_relative_capacity_pct=100.0,
        capacity_kw_options=[INV_KW],
    )


def _grid() -> GridComponentConfig:
    return GridComponentConfig(
        enabled=True,
        purchase_capacity_kw=1e9,
        sale_capacity_kw=1e9,
    )


def _pv(with_temp: bool = False, rated_kw: float = 1000.0,
        derating: float = 0.8) -> PVComponentConfig:
    return PVComponentConfig(
        enabled=True,
        capacity_kw_options=[rated_kw],
        derating_factor=derating,
        temperature=PVTemperatureSettings(enabled=with_temp),
    )


def _state(soc: float = 80.0) -> BatteryState:
    return BatteryState(soc_pct=soc, effective_capacity_kwh=CAP_KWH)


def _step(**kw) -> object:
    kw.setdefault("battery_config", _bat())
    kw.setdefault("converter_config", _conv())
    kw.setdefault("grid_config", _grid())
    kw.setdefault("selected_battery_quantity", 1)
    kw.setdefault("selected_converter_capacity_kw", INV_KW)
    kw.setdefault("time_step_hours", 1.0)
    return run_dispatch_step(**kw)


# ??? TEST 1: PV output formula ????????????????????????????????????????????????

def test_pv_formula() -> list[TR]:
    """
    HOMER Pro PV equation:
        Ppv = Ypv ? fpv ? (GT / GSTC) ? [1 + ?P ? (Tc ? TSTC)]
        Tc  = Ta + (NOCT ? 20) / 800 ? GT(W/m?)
    where GT is in kW/m?, GSTC = 1.0 kW/m?, TSTC = 25?C.
    """
    res = []

    # 1a ? no temp effects, half-peak irradiance
    # Ppv = 1000 ? 0.8 ? 0.5 ? 1.0 = 400 kW
    _, _, pv = compute_pv_power_output(
        rated_capacity_kw=1000.0, derating_factor=0.8,
        irradiance_kw_per_m2=0.5, reference_irradiance_kw_per_m2=1.0,
        cell_temperature_c=25.0, reference_cell_temp_c=25.0,
        temperature_coefficient_pct_per_degC=-0.5,
        temperature_effect_enabled=False,
    )
    res.append(chk("PV no-temp: GHI=500 W/m?, derating=0.8 -> 400 kW", 400.0, pv, "kW"))

    # 1b ? STC conditions (no temp penalty)
    # Ppv = 1000 ? 0.8 ? 1.0 ? 1.0 = 800 kW
    _, _, pv_stc = compute_pv_power_output(
        rated_capacity_kw=1000.0, derating_factor=0.8,
        irradiance_kw_per_m2=1.0, reference_irradiance_kw_per_m2=1.0,
        cell_temperature_c=25.0, reference_cell_temp_c=25.0,
        temperature_coefficient_pct_per_degC=-0.5,
        temperature_effect_enabled=False,
    )
    res.append(chk("PV STC: GHI=1000, Tc=25?C (temp disabled) -> 800 kW", 800.0, pv_stc, "kW"))

    # 1c ? NOCT cell temperature: Tc = 35 + (47?20)/800?1000 = 68.75?C
    tc = compute_cell_temperature_c(
        ambient_temperature_c=35.0,
        irradiance_kw_per_m2=1.0,
        nominal_operating_cell_temp_c=47.0,
    )
    res.append(chk("PV NOCT Tc: Ta=35?C, GHI=1000 -> Tc=68.75?C", 68.75, tc, "?C", tol=0.001))

    # 1d ? with temperature effects: temp_factor = 1+(?0.005)?(68.75?25) = 0.78125
    # Ppv = 1000 ? 0.8 ? 1.0 ? 0.78125 = 625 kW
    _, _, pv_hot = compute_pv_power_output(
        rated_capacity_kw=1000.0, derating_factor=0.8,
        irradiance_kw_per_m2=1.0, reference_irradiance_kw_per_m2=1.0,
        cell_temperature_c=68.75, reference_cell_temp_c=25.0,
        temperature_coefficient_pct_per_degC=-0.5,
        temperature_effect_enabled=True,
    )
    res.append(chk("PV with temp: Tc=68.75?C, ?P=?0.5%/?C -> 625 kW", 625.0, pv_hot, "kW"))

    # 1e ? zero irradiance -> zero output
    _, _, pv_zero = compute_pv_power_output(
        rated_capacity_kw=1000.0, derating_factor=0.8,
        irradiance_kw_per_m2=0.0, reference_irradiance_kw_per_m2=1.0,
        cell_temperature_c=25.0, reference_cell_temp_c=25.0,
        temperature_coefficient_pct_per_degC=-0.5,
        temperature_effect_enabled=True,
    )
    res.append(chk_zero("PV: GHI=0 -> 0 kW output", pv_zero, "kW"))

    # 1f ? proportionality: 75% irradiance -> 75% of no-temp peak
    _, _, pv_75 = compute_pv_power_output(
        rated_capacity_kw=1000.0, derating_factor=0.8,
        irradiance_kw_per_m2=0.75, reference_irradiance_kw_per_m2=1.0,
        cell_temperature_c=25.0, reference_cell_temp_c=25.0,
        temperature_coefficient_pct_per_degC=-0.5,
        temperature_effect_enabled=False,
    )
    res.append(chk("PV: linear irradiance scaling (75%) -> 600 kW", 600.0, pv_75, "kW"))

    return res


# ??? TEST 2: Battery SOC physics ?????????????????????????????????????????????

def _bat_call(soc: float, surplus: float, deficit: float,
              min_soc: float = MIN_SOC, eta: float = 90.0) -> object:
    return update_battery_state(
        current_soc_pct=soc, surplus_kw=surplus, deficit_kw=deficit,
        battery_enabled=True, quantity_strings=1,
        effective_capacity_kwh=CAP_KWH,
        nominal_voltage_v=VOLT,
        max_charge_current_a=10_000.0,
        max_discharge_current_a=10_000.0,
        minimum_soc_pct=min_soc,
        roundtrip_efficiency_pct=eta,
        time_step_hours=1.0,
    )


def test_battery_soc() -> list[TR]:
    """
    HOMER Pro battery SOC model (symmetric efficiency):
        eta_charge = eta_discharge = sqrt(eta_roundtrip)
        stored += charge_in  ? eta_charge ? dt     (charge)
        stored -= dc_out ? dt / eta_discharge       (discharge)
    """
    res = []

    # 2a ? Charge from 50%, 200 kW in for 1 h
    # delta_stored = 200 ? sqrt(0.9) = 189.737 kWh
    # new_stored   = 500 + 189.737  = 689.737 kWh -> 68.974%
    r = _bat_call(50.0, 200.0, 0.0)
    exp_stored = 500.0 + 200.0 * ETA_HALF
    exp_soc    = exp_stored / CAP_KWH * 100.0
    res.append(chk("Battery charge: SOC after 200 kW ? 1 h (from 50%)", exp_soc, r.new_soc_pct, "%"))
    res.append(chk("Battery charge: actual charge power = 200 kW", 200.0, r.battery_charge_kw, "kW"))

    # 2b ? Discharge from 80%, request 300 kW DC
    # available = 800 ? 200 = 600 kWh; max_dc = 600 ? sqrt(0.9) = 569 kW >> 300 OK
    # removed   = 300 / sqrt(0.9) = 316.228 kWh
    # new_stored = 800 ? 316.228 = 483.772 kWh -> 48.377%
    r2 = _bat_call(80.0, 0.0, 300.0)
    exp_removed = 300.0 / ETA_HALF
    exp_soc2    = (800.0 - exp_removed) / CAP_KWH * 100.0
    res.append(chk("Battery discharge: SOC after 300 kW DC ? 1 h (from 80%)", exp_soc2, r2.new_soc_pct, "%"))
    res.append(chk("Battery discharge: actual DC output = 300 kW", 300.0, r2.battery_discharge_kw, "kW"))

    # 2c ? Energy-limited discharge: SOC=25%, request 100 kW but only 50 kWh above floor
    # available = 250 ? 200 = 50 kWh
    # max_dc    = 50 ? sqrt(0.9) = 47.434 kW  (energy-limited, not current-limited)
    # removed   = 47.434 / sqrt(0.9) = 50 kWh -> new_stored = 200 kWh = min floor -> SOC = 20%
    r3 = _bat_call(25.0, 0.0, 100.0)
    exp_max_dc = (250.0 - MIN_KWH) * ETA_HALF   # 50 ? sqrt(0.9) ? 47.434 kW
    res.append(chk("Battery discharge: energy-limited DC output", exp_max_dc, r3.battery_discharge_kw, "kW"))
    res.append(chk("Battery discharge: hits min SOC floor after energy-limit", MIN_SOC, r3.new_soc_pct, "%"))

    # 2d ? Lossless (100% roundtrip): stored += 100 exactly
    r4 = _bat_call(50.0, 100.0, 0.0, min_soc=0.0, eta=100.0)
    res.append(chk("Battery charge: 100% roundtrip -> lossless -> 60%", 60.0, r4.new_soc_pct, "%"))

    # 2e ? Roundtrip efficiency check:
    # charge 100 kW ? 1 h -> stored += 100?sqrt(0.9)
    # discharge 100 kW DC ? 1 h -> stored -= 100/sqrt(0.9)
    # net change = 100?sqrt(0.9) ? 100/sqrt(0.9) = 100?(0.9?1)/sqrt(0.9) < 0  (energy lost)
    r5 = _bat_call(50.0, 100.0, 0.0, min_soc=0.0)
    r6 = _bat_call(r5.new_soc_pct, 0.0, 100.0, min_soc=0.0)
    exp_stored_after = 500.0 + 100.0 * ETA_HALF - 100.0 / ETA_HALF
    act_stored_after = r6.new_soc_pct / 100.0 * CAP_KWH
    res.append(chk("Battery roundtrip: stored energy after charge+discharge", exp_stored_after, act_stored_after, "kWh"))

    # 2f ? Roundtrip loss fraction = 1 ? eta_rt = 10% of energy transacted
    # After charging 100 kWh-in then discharging 100 kWh-out (DC):
    # stored_change = 100?sqrt(0.9) - 100/sqrt(0.9) = 100?(0.9-1)/sqrt(0.9)
    # = -10/sqrt(0.9) ? -10.541 kWh lost from storage for each 100 kWh transacted
    energy_lost_expected = 100.0 * ETA_HALF - 100.0 / ETA_HALF   # negative number
    energy_lost_actual   = act_stored_after - 500.0
    res.append(chk("Battery roundtrip: energy lost per 100 kWh transacted", energy_lost_expected, energy_lost_actual, "kWh"))

    return res


# ??? TEST 3: Single-step dispatch ????????????????????????????????????????????

def test_dispatch() -> list[TR]:
    """
    Dispatch (renewable-first, HOMER-style).

    PV -> DC bus, Wind -> AC bus, Battery -> DC bus, Converter bridges DC?AC.
    Energy balance per step:
        PV_dc + wind_ac + bat_discharge_dc + grid_import
        = load_served + bat_charge_dc + grid_export + excess + inv_loss + rect_loss
    """
    res = []

    # 3a ? PV meets load fully (PV < load/eta, so no surplus)
    # PV=400 kW DC, Load=600 kW AC, Bat=100% SOC
    # PV->load: DC_needed=600/0.95=631.58 > 400 -> use all 400 kW DC -> AC=380, rem_load=220
    # Bat->load: DC=220/0.95=231.58, AC=220, inv_loss+=11.58
    r = _step(load_kw=600.0, pv_kw=400.0, wind_kw=0.0, battery_state=_state(100.0))
    pv_ac = 400.0 * ETA_INV  # 380
    bat_dc = (600.0 - pv_ac) / ETA_INV  # 231.578...
    exp_inv_loss = (400.0 + bat_dc) * (1.0 - ETA_INV)
    res += [
        chk("Dispatch PV+bat: load fully served", 600.0, r.served_load_kw, "kW"),
        chk_zero("Dispatch PV+bat: unmet load = 0", r.unmet_load_kw, "kW"),
        chk_zero("Dispatch PV+bat: grid import = 0", r.grid_import_kw, "kW"),
        chk("Dispatch PV+bat: battery discharge DC", bat_dc, r.battery_discharge_dc_kw, "kW"),
        chk("Dispatch PV+bat: inverter loss", exp_inv_loss, r.inverter_loss_kw, "kW"),
    ]

    # 3b ? PV surplus charges battery
    # PV=800 kW DC, Load=300 kW AC, Bat=20% SOC (has charging space)
    # PV->load: DC=300/0.95=315.79, AC=300; PV_surplus=800?315.79=484.21 kW DC->battery
    # No bat discharge (rem_load=0)
    r2 = _step(load_kw=300.0, pv_kw=800.0, wind_kw=0.0, battery_state=_state(20.0))
    dc_for_load = 300.0 / ETA_INV  # 315.789
    surplus_dc  = 800.0 - dc_for_load  # 484.211
    exp_inv2    = dc_for_load * (1.0 - ETA_INV)   # only PV->load path; surplus is DC direct
    res += [
        chk("Dispatch PV surplus: load served", 300.0, r2.served_load_kw, "kW"),
        chk("Dispatch PV surplus: battery charge = surplus DC", surplus_dc, r2.battery_charge_kw, "kW"),
        chk("Dispatch PV surplus: inverter loss (PV->load only)", exp_inv2, r2.inverter_loss_kw, "kW"),
        chk_zero("Dispatch PV surplus: grid import = 0", r2.grid_import_kw, "kW"),
    ]

    # 3c ? Battery-only covers load
    # PV=0, Load=300 kW AC, Bat=80% SOC
    # Bat DC=300/0.95=315.789, AC=300, inv_loss=15.789
    # removed = 315.789/sqrt(0.9) = 332.89 kWh -> new_stored=800-332.89=467.11 kWh
    r3 = _step(load_kw=300.0, pv_kw=0.0, wind_kw=0.0, battery_state=_state(80.0))
    dc3 = 300.0 / ETA_INV
    inv3 = dc3 * (1.0 - ETA_INV)
    removed3 = dc3 / ETA_HALF
    exp_soc3 = (800.0 - removed3) / CAP_KWH * 100.0
    res += [
        chk("Dispatch bat-only: load served", 300.0, r3.served_load_kw, "kW"),
        chk("Dispatch bat-only: discharge DC", dc3, r3.battery_discharge_dc_kw, "kW"),
        chk("Dispatch bat-only: discharge AC", 300.0, r3.battery_discharge_kw, "kW"),
        chk("Dispatch bat-only: inverter loss", inv3, r3.inverter_loss_kw, "kW"),
        chk("Dispatch bat-only: new SOC%", exp_soc3, r3.battery_soc_pct, "%"),
        chk_zero("Dispatch bat-only: grid import = 0", r3.grid_import_kw, "kW"),
    ]

    # 3d ? Grid import covers remaining deficit (battery at min SOC)
    # PV=100 kW, Load=500 kW, Bat=20% (min, can't discharge)
    # PV->load: AC=95 kW; rem_load=405; bat can't discharge -> grid import=405 kW
    r4 = _step(load_kw=500.0, pv_kw=100.0, wind_kw=0.0, battery_state=_state(20.0))
    pv4_ac = 100.0 * ETA_INV  # 95
    exp_grid4 = 500.0 - pv4_ac  # 405
    res += [
        chk("Dispatch grid import: covers deficit when bat at min SOC", exp_grid4, r4.grid_import_kw, "kW"),
        chk_zero("Dispatch grid import: no battery discharge at min SOC", r4.battery_discharge_kw, "kW"),
        chk("Dispatch grid import: load fully served", 500.0, r4.served_load_kw, "kW"),
    ]

    # 3e ? Energy balance across 6 scenarios
    scenarios = [
        (400.0, 0.0, 600.0, 50.0, "PV shortage + battery"),
        (800.0, 0.0, 300.0, 50.0, "PV surplus -> battery"),
        (0.0, 500.0, 700.0, 60.0, "Wind + battery"),
        (200.0, 100.0, 500.0, 40.0, "PV + wind + battery"),
        (0.0, 0.0, 300.0, 100.0, "Battery only"),
        (1200.0, 0.0, 300.0, 20.0, "Large PV -> export"),
    ]
    for pv, wind, load, soc, label in scenarios:
        r = _step(load_kw=load, pv_kw=pv, wind_kw=wind, battery_state=_state(soc))
        supply = pv + wind + r.battery_discharge_dc_kw + r.grid_import_kw
        demand = (r.served_load_kw + r.battery_charge_kw + r.grid_export_kw
                  + r.excess_energy_kw + r.inverter_loss_kw + r.rectifier_loss_kw)
        imbalance = abs(supply - demand)
        res.append(TR(
            f"Energy balance: {label}", passed=(imbalance <= 1e-9),
            expected=0.0, actual=imbalance, deviation=imbalance, unit="kW",
        ))

    return res


# ??? TEST 4: 3-hour end-to-end simulation ????????????????????????????????????

def test_3hour_simulation() -> list[TR]:
    """
    Hand-computed HOMER Pro expected values for a known 3-hour scenario.

    System: PV(1 MW, 80% derating, NO temp) + Battery(1 MWh, 90% rt, 20% min)
            + Converter(2 MW, 95%/95%) + Grid (unlimited) ? no wind.

    Hour | GHI (W/m?) | Load (kW) | Expected behaviour
    -----|------------|-----------|--------------------
      0  |    500     |    600    | PV->load(380kW), Bat->load(220kW), no grid
      1  |      0     |    400    | Bat->load(400kW), no grid
      2  |    750     |    200    | PV->load(200kW), PV surplus->Bat, no grid

    Expected SOC trace:   100% -> 75.59% -> 31.21% -> 68.15%
    """
    res = []

    components = ComponentsConfig(
        pv=PVComponentConfig(
            enabled=True,
            capacity_kw_options=[1000.0],
            derating_factor=0.8,
            temperature=PVTemperatureSettings(enabled=False),   # disable for clean numbers
        ),
        wind=WindComponentConfig(enabled=False),
        battery=_bat(init_soc=100.0, self_dis=0.0),
        converter=_conv(),
        grid=_grid(),
    )

    load_df     = pd.DataFrame({"load_kw": [600.0, 400.0, 200.0]})
    resource_df = pd.DataFrame({
        "ghi":         [500.0,  0.0, 750.0],
        "temperature": [ 25.0, 20.0,  30.0],
        "ws50m":       [  0.0,  0.0,   0.0],
    })
    design = DesignPoint(
        pv_capacity_kw=1000.0, wind_quantity=0,
        battery_quantity=1, converter_capacity_kw=INV_KW,
    )
    sim_results = HybridSystemSimulator(SimulationInputs(
        load_df=load_df, resource_df=resource_df,
        components=components, design=design, time_step_hours=1.0,
    )).run()

    df = sim_results.to_dataframe()
    s  = sim_results.summary

    # ?? Hand-computed HOMER Pro expected values ??????????????????????????????

    # Hour 0: PV_dc=400, Load=600
    #   Step2 PV->load: DC_used=400 (< 600/0.95), AC=400?0.95=380, inv_loss=20, rem=220
    #   Step5 Bat->load: DC=220/0.95, AC=220, inv_loss+=220/0.95?0.05, rem=0
    pv_h0      = 1000.0 * 0.8 * 0.5                           # 400 kW DC
    bat_dc_h0  = (600.0 - pv_h0 * ETA_INV) / ETA_INV         # 220/0.95 = 231.578...
    bat_ac_h0  = bat_dc_h0 * ETA_INV                          # ? 220 kW
    inv_h0     = (pv_h0 + bat_dc_h0) * (1.0 - ETA_INV)       # ? 31.579 kW
    removed_h0 = bat_dc_h0 / ETA_HALF
    stored_h0  = CAP_KWH - removed_h0
    soc_h0     = stored_h0 / CAP_KWH * 100.0

    # Hour 1: PV=0, Load=400
    #   Bat->load: DC=400/0.95, AC=400, inv_loss=(400/0.95)?0.05
    bat_dc_h1  = 400.0 / ETA_INV                              # 421.053
    inv_h1     = bat_dc_h1 * (1.0 - ETA_INV)                  # 21.053
    removed_h1 = bat_dc_h1 / ETA_HALF
    stored_h1  = stored_h0 - removed_h1
    soc_h1     = stored_h1 / CAP_KWH * 100.0

    # Hour 2: PV_dc=600, Load=200
    #   PV->load: DC=200/0.95=210.526, AC=200, inv_loss=10.526
    #   PV surplus = 600?210.526 = 389.474 kW -> battery DC direct (no inverter)
    pv_h2          = 1000.0 * 0.8 * 0.75                      # 600 kW DC
    dc_for_load_h2 = 200.0 / ETA_INV                          # 210.526
    bat_charge_h2  = pv_h2 - dc_for_load_h2                   # 389.474
    inv_h2         = dc_for_load_h2 * (1.0 - ETA_INV)         # 10.526 (PV->bat is DC direct)
    stored_h2      = stored_h1 + bat_charge_h2 * ETA_HALF
    soc_h2         = stored_h2 / CAP_KWH * 100.0

    # ?? Hourly checks ????????????????????????????????????????????????????????
    res += [
        # Hour 0
        chk("H0: PV DC output",            pv_h0,     df["pv_kw"].iloc[0],                   "kW"),
        chk("H0: load served",             600.0,     df["served_load_kw"].iloc[0],           "kW"),
        chk("H0: battery discharge DC",    bat_dc_h0, df["battery_discharge_dc_kw"].iloc[0],  "kW"),
        chk("H0: battery discharge AC",    bat_ac_h0, df["battery_discharge_kw"].iloc[0],     "kW"),
        chk("H0: inverter loss",           inv_h0,    df["inverter_loss_kw"].iloc[0],         "kW"),
        chk("H0: battery SOC%",            soc_h0,    df["battery_soc_pct"].iloc[0],          "%"),
        chk_zero("H0: grid import = 0",               df["grid_import_kw"].iloc[0],           "kW"),

        # Hour 1
        chk("H1: PV DC output",            0.0,       df["pv_kw"].iloc[1],                   "kW"),
        chk("H1: load served",             400.0,     df["served_load_kw"].iloc[1],           "kW"),
        chk("H1: battery discharge DC",    bat_dc_h1, df["battery_discharge_dc_kw"].iloc[1],  "kW"),
        chk("H1: battery discharge AC",    400.0,     df["battery_discharge_kw"].iloc[1],     "kW"),
        chk("H1: inverter loss",           inv_h1,    df["inverter_loss_kw"].iloc[1],         "kW"),
        chk("H1: battery SOC%",            soc_h1,    df["battery_soc_pct"].iloc[1],          "%"),
        chk_zero("H1: grid import = 0",               df["grid_import_kw"].iloc[1],           "kW"),

        # Hour 2
        chk("H2: PV DC output",            pv_h2,       df["pv_kw"].iloc[2],                 "kW"),
        chk("H2: load served",             200.0,       df["served_load_kw"].iloc[2],         "kW"),
        chk("H2: battery charge DC",       bat_charge_h2, df["battery_charge_kw"].iloc[2],   "kW"),
        chk("H2: inverter loss",           inv_h2,      df["inverter_loss_kw"].iloc[2],       "kW"),
        chk("H2: battery SOC%",            soc_h2,      df["battery_soc_pct"].iloc[2],        "%"),
        chk_zero("H2: grid import = 0",                  df["grid_import_kw"].iloc[2],        "kW"),
    ]

    # ?? Per-hour energy balance ???????????????????????????????????????????????
    for i in range(3):
        row = df.iloc[i]
        supply = (row["pv_kw"] + row["wind_kw"]
                  + row["battery_discharge_dc_kw"] + row["grid_import_kw"])
        demand = (row["served_load_kw"] + row["battery_charge_kw"]
                  + row["grid_export_kw"] + row["excess_energy_kw"]
                  + row["inverter_loss_kw"] + row["rectifier_loss_kw"])
        imb = abs(supply - demand)
        res.append(TR(
            f"Energy balance: hour {i}", passed=(imb <= 1e-9),
            expected=0.0, actual=imb, deviation=imb, unit="kW",
        ))

    # ?? Annual summary ????????????????????????????????????????????????????????
    min_soc_expected = min(soc_h0, soc_h1, soc_h2)   # soc_h1 is the trough
    res += [
        chk("Summary: total load",          1200.0,               s.total_load_kwh,              "kWh"),
        chk("Summary: total served load",   1200.0,               s.total_served_load_kwh,        "kWh"),
        chk("Summary: total PV",            pv_h0 + 0.0 + pv_h2,  s.total_pv_generation_kwh,     "kWh"),
        chk_zero("Summary: unmet load",                            s.total_unmet_load_kwh,         "kWh"),
        chk_zero("Summary: grid import",                           s.total_grid_import_kwh,        "kWh"),
        chk("Summary: final SOC%",          soc_h2,               s.final_battery_soc_pct,        "%"),
        chk("Summary: min SOC%",            min_soc_expected,     s.min_battery_soc_pct,          "%"),
    ]

    return res


# ??? TEST 5: Full-year project simulations ????????????????????????????????????

def test_existing_projects() -> list[TR]:
    """
    Run test_2 (wind-only, no battery) and test_3 (PV + battery) for a full
    year and verify HOMER Pro-equivalent sanity checks:
      ? Energy balance passes (0 failed rows)
      ? Capacity shortage ? 0% (grid always covers deficit)
      ? Project-specific generation levels match stored outputs
    """
    from core.simulation.run_project_simulation import run_project_simulation

    res = []

    # Known reference values (from last saved outputs)
    refs = {
        "test_2": {
            "total_wind_kwh":  3_567_755.9,
            "renewable_frac":  0.3838,
            "total_load_kwh":  8_760_000.0,
        },
        "test_3": {
            "total_pv_kwh":    4_305_372.0,
            "renewable_frac":  0.457,
            "final_soh_pct":   97.7,
        },
    }

    for proj in ["test_2", "test_3"]:
        try:
            sr = run_project_simulation(proj, save_outputs=False)
            df = sr.to_dataframe()
            s  = sr.summary

            # Energy balance
            bal, _ = validate_energy_balance(df)
            res.append(TR(
                f"{proj}: energy balance ? 0 failed rows",
                passed=(bal.failed_rows == 0),
                expected=0.0, actual=float(bal.failed_rows),
                deviation=float(bal.failed_rows), unit="rows",
            ))
            res.append(TR(
                f"{proj}: energy balance ? max imbalance ? 1e-6 kW",
                passed=(bal.max_abs_mismatch_kw <= 1e-6),
                expected=0.0, actual=bal.max_abs_mismatch_kw,
                deviation=bal.max_abs_mismatch_kw, unit="kW",
            ))

            # Capacity shortage
            res.append(TR(
                f"{proj}: capacity shortage ? 0%",
                passed=(s.annual_capacity_shortage_pct < 0.001),
                expected=0.0, actual=s.annual_capacity_shortage_pct,
                deviation=s.annual_capacity_shortage_pct, unit="%",
            ))

            # Project-specific checks (5% tolerance against saved reference)
            if proj == "test_2":
                ref_wind = refs["test_2"]["total_wind_kwh"]
                res.append(TR(
                    f"{proj}: total wind generation (ref {ref_wind/1e6:.2f} GWh)",
                    passed=(abs(s.total_wind_generation_kwh - ref_wind) / ref_wind < 0.001),
                    expected=ref_wind,
                    actual=s.total_wind_generation_kwh,
                    deviation=abs(s.total_wind_generation_kwh - ref_wind),
                    unit="kWh",
                ))
                res.append(TR(
                    f"{proj}: renewable fraction (ref {refs['test_2']['renewable_frac']:.4f})",
                    passed=(abs(s.renewable_fraction - refs["test_2"]["renewable_frac"]) < 0.005),
                    expected=refs["test_2"]["renewable_frac"],
                    actual=s.renewable_fraction,
                    deviation=abs(s.renewable_fraction - refs["test_2"]["renewable_frac"]),
                    unit="fraction",
                ))
                res.append(chk_zero(
                    f"{proj}: PV generation = 0 (wind-only project)",
                    s.total_pv_generation_kwh, "kWh",
                ))

            if proj == "test_3":
                ref_pv = refs["test_3"]["total_pv_kwh"]
                res.append(TR(
                    f"{proj}: total PV generation (ref {ref_pv/1e6:.2f} GWh)",
                    passed=(abs(s.total_pv_generation_kwh - ref_pv) / ref_pv < 0.001),
                    expected=ref_pv,
                    actual=s.total_pv_generation_kwh,
                    deviation=abs(s.total_pv_generation_kwh - ref_pv),
                    unit="kWh",
                ))
                res.append(TR(
                    f"{proj}: renewable fraction (ref {refs['test_3']['renewable_frac']:.3f})",
                    passed=(abs(s.renewable_fraction - refs["test_3"]["renewable_frac"]) < 0.005),
                    expected=refs["test_3"]["renewable_frac"],
                    actual=s.renewable_fraction,
                    deviation=abs(s.renewable_fraction - refs["test_3"]["renewable_frac"]),
                    unit="fraction",
                ))
                ref_soh = refs["test_3"]["final_soh_pct"]
                res.append(TR(
                    f"{proj}: final SOH% (ref {ref_soh:.1f}%)",
                    passed=(abs(s.final_soh_pct - ref_soh) < 0.5),
                    expected=ref_soh, actual=s.final_soh_pct,
                    deviation=abs(s.final_soh_pct - ref_soh), unit="%",
                ))

        except Exception as exc:
            res.append(TR(
                f"{proj}: EXCEPTION ? {exc}",
                passed=False, expected=0.0, actual=-1.0, deviation=999.0,
            ))

    return res


# ??? Runner ??????????????????????????????????????????????????????????????????

def main() -> None:
    sections = [
        (
            "1. PV Output Formula  (HOMER: Ppv = Ypv ? fpv ? GT/GSTC ? temp_factor)",
            test_pv_formula,
        ),
        (
            "2. Battery SOC Physics  (HOMER: eta_half = sqrt(eta_rt), symmetric split)",
            test_battery_soc,
        ),
        (
            "3. Single-Step Dispatch  (renewable-first, energy balance across 6 scenarios)",
            test_dispatch,
        ),
        (
            "4. 3-Hour End-to-End Simulation  (hand-computed vs simulator, 0 grid needed)",
            test_3hour_simulation,
        ),
        (
            "5. Full-Year Projects  (test_2 wind-only, test_3 PV+battery ? energy balance & KPIs)",
            test_existing_projects,
        ),
    ]

    print("=" * 72)
    print("  HOMER PRO COMPARISON TEST ? hybrid_homer_engine")
    print("=" * 72)

    all_results: list[TR] = []
    for title, fn in sections:
        print(f"\n{title}")
        print("-" * 72)
        section_results = fn()
        for r in section_results:
            print(r)
        all_results.extend(section_results)

    passed = sum(1 for r in all_results if r.passed)
    total  = len(all_results)
    failed = [r for r in all_results if not r.passed]

    print("\n" + "=" * 72)
    print(f"  RESULT: {passed}/{total} tests passed", end="")

    if not failed:
        print("  ?  All PASS  OK")
        print("  Engine matches HOMER Pro formulas for PV, battery, dispatch, and energy balance.")
    else:
        print(f"  ?  {len(failed)} FAIL  FAIL")
        print(f"\n  FAILED TESTS ({len(failed)}):")
        for r in failed:
            print(f"\n    FAIL {r.name}")
            print(f"      Expected : {r.expected:.6f} {r.unit}")
            print(f"      Got      : {r.actual:.6f} {r.unit}")
            print(f"      Deviation: {r.deviation:.6f} {r.unit}")

    print("=" * 72)
    sys.exit(0 if not failed else 1)


if __name__ == "__main__":
    main()
