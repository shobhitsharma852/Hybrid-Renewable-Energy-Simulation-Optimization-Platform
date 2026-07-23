# SSNL HOMER / Model Input Values

## Files Created

These files use 2020 measured solar resource values, converted to a non-leap year for model/HOMER alignment. Wind is not included.

| Purpose | File | Rows | Notes |
|---|---:|---:|---|
| Hybrid engine resource | `projects/SSNL/inputs/resources.csv` | 35,040 | 15-min, 2025 timestamps to align with `load.csv`; `ws50m` is set to 0 because wind is excluded |
| HOMER solar import | `projects/SSNL/homer_exports/solar_resource_ssnl_2020.csv` | 8,760 | GHI in kWh/m2 |
| HOMER temperature import | `projects/SSNL/homer_exports/temperature_ssnl_2020.csv` | 8,760 | Ambient temperature in deg C |
| Resource summary | `projects/SSNL/homer_exports/resource_package_summary.json` | - | Provenance and summary statistics |

## Measured Resource Data

| Field | Source | Used As | Notes |
|---|---|---|---|
| GHI | SCADA `GHI_W` | Solar resource | W/m2 in model, kWh/m2 in HOMER solar export |
| Ambient temperature | SCADA `AmbientTemperature` | Temperature resource | Values above 45 C were treated as bad points in the POA validation workflow |
| POA | SCADA `POA` | POA-direct validation only | Not used in `resources.csv` because the normal project/HOMER route starts from GHI |
| Meter power | SCADA meter tag | Excel/SCADA truth | Used in `truth_2020_meter.csv`, not in HOMER resource import |
| Wind speed | Not used | Excluded | `ws50m = 0` only exists in the model file because the engine resource schema requires the column |

## SSNL Project Values Already Present

These are from `projects/SSNL/project.json`.

| Item | Value |
|---|---:|
| Latitude | 22.354956 |
| Longitude | 73.3419 |
| Timezone | Asia/Kolkata |
| Simulation timestep | 15 min |
| Nominal discount rate | 10.0 % |
| Inflation rate | 6.0 % |
| Project lifetime | 25 years |
| Annual capacity shortage | 0.0 % |
| Dispatch strategy | renewable_first |

## Component / Cost Assumptions

Important: SSNL currently has no `components.json`, and SCADA does not contain cost data.
The following values are not measured plant costs. They are the cost assumptions already used
in the existing `dhule`, `dhule_2`, and `khavda` project templates.

| Component | Parameter | Value |
|---|---|---:|
| PV | capital_cost_per_kw | 45,000 INR/kW |
| PV | replacement_cost_per_kw | 30,000 INR/kW |
| PV | om_cost_per_kw_per_year | 600 INR/kW/year |
| PV | lifetime_years | 25 |
| PV | derating_factor | 0.80 |
| PV | temperature_coefficient_pct_per_degC | -0.5 |
| PV | nominal_operating_cell_temp_c | 47 |
| PV | ground_reflectance_pct | 20 |
| PV | kt_max | 0.82 |
| Battery | nominal_capacity_kwh_per_string | 1,000 kWh/string |
| Battery | roundtrip_efficiency_pct | 90 |
| Battery | capital_cost_per_string | 7,000,000 INR/string |
| Battery | replacement_cost_per_string | 5,500,000 INR/string |
| Battery | om_cost_per_string_per_year | 120,000 INR/string/year |
| Battery | lifetime_years | 15 |
| Converter | capital_cost_per_kw | 7,000 INR/kW |
| Converter | replacement_cost_per_kw | 5,000 INR/kW |
| Converter | om_cost_per_kw_per_year | 100 INR/kW/year |
| Converter | inverter_efficiency_pct | 95 |
| Converter | rectifier_efficiency_pct | 95 |
| Converter | inverter_lifetime_years | 15 |
| Grid | grid_power_price_per_kwh | 9 INR/kWh |
| Grid | grid_sellback_price_per_kwh | 2 INR/kWh |
| Grid | sale_capacity_kw | 999,999 kW |
| Grid | purchase_capacity_kw | 999,999 kW |
| Grid | co2_emissions_g_per_kwh | 632 g/kWh |

## What To Enter In HOMER

Use the three HOMER export files from `projects/SSNL/homer_exports`:

| HOMER Section | File | Unit |
|---|---|---|
| Resources -> Solar GHI | `solar_resource_ssnl_2020.csv` | kWh/m2 |
| Resources -> Temperature | `temperature_ssnl_2020.csv` | deg C |

Do not add a wind turbine in HOMER for this SSNL solar-only comparison. In the engine, keep wind disabled or use zero wind quantity.

Then enter the same PV, converter, grid, and any battery sizes/costs in both HOMER and the engine.
Without the same component and cost assumptions, NPC and LCOE cannot be compared fairly.
