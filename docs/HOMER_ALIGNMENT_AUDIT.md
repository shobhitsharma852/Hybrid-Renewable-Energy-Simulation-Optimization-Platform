# HOMER Pro Alignment Audit

Audit date: 2026-06-24  
Reference baseline: HOMER Pro 3.16 public documentation

## Corrected in this pass

| Area | Previous behavior | Corrected behavior |
|---|---|---|
| Capacity shortage | Equaled unmet-load energy only | Includes unmet load and operating-reserve shortfall |
| Feasibility | Any reserve-shortfall hour failed independently | Reserve shortfall contributes to the configured annual capacity-shortage allowance |
| LCOE denominator | Served load plus grid sales | Served electrical load only |
| Converter results | Reconstructed inverter flow from all PV generation | Uses converter input/output recorded during dispatch |
| Sub-hourly results | Heatmaps truncated the first 8,760 rows; monthly energy omitted timestep duration | Heatmaps aggregate by day/hour and monthly energy multiplies by timestep duration |
| Continuous optimizer | NumPy/SciPy undeclared; bounds unvalidated; explicit limits could expand | Dependencies declared, bounds validated, explicit upper limits remain hard limits |
| Results readability | Tables and charts used roughly 10–13 px text | Tables, tabs, metrics, legends, axes, and compact plots use an accessible larger scale |

## Strongest current alignment

- Chronological timestep energy balance with explicit AC/DC conversion losses.
- PV and wind production models based on published HOMER-style equations.
- Battery SOC, power limits, self-discharge, throughput life, and lifecycle replacement logic.
- NPC, capital recovery, replacement present value, salvage, and annualized cost.
- Discrete search-space optimization ranked by NPC.
- Operating-reserve requirements based on load, annual peak, solar, and wind.

## Remaining material gaps

1. Direct regression against a versioned HOMER hourly export is still incomplete.
2. Only renewable-first dispatch is operational; HOMER supports more control strategies.
3. Grid modeling is limited to flat buy/sell prices. Time-of-use tariffs, demand charges,
   net-metering settlement, and outages are not operational.
4. Grid CO2 intensity is stored but emissions are not yet calculated or optimized.
5. PV tracking and MPPT settings are exposed more broadly than they are represented in
   dispatch/economics.
6. Converter efficiency is constant rather than part-load dependent.
7. Wind modeling lacks configurable pressure/altitude density correction and broader shear models.
8. Battery aging remains a transparent approximation rather than a proven reproduction of
   HOMER's proprietary advanced storage model.
9. Sensitivity analysis and multi-objective/Pareto optimization are not implemented.
10. The component scope excludes generators, fuel curves, thermal loads, hydrogen, hydro,
    and other HOMER technologies.

## Official definitions used

- Capacity shortage:
  https://homerenergy.com/products/pro/docs/latest/capacity_shortage.html
- Capacity shortage fraction:
  https://homerenergy.com/products/pro/docs/latest/capacity_shortage_fraction.html
- Required operating reserve:
  https://homerenergy.com/products/pro/docs/latest/required_operating_reserve.html
- Levelized cost of energy:
  https://homerenergy.com/products/pro/docs/latest/levelized_cost_of_energy.html
- Battery throughput:
  https://homerenergy.com/products/pro/docs/latest/battery_throughput.html
