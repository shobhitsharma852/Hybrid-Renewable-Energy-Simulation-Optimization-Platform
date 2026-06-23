# Hybrid HOMER Engine — Technical Presentation Master Blueprint

Audit date: 18 June 2026

## 1. What this presentation must prove

The presentation should not be a dashboard tour. It should prove, in sequence:

1. What hybrid-system design problem the project solves.
2. How raw project, load, weather, and component inputs are validated.
3. How every simulation time step converts resources into electrical power.
4. How power is dispatched across the AC bus, DC bus, battery, converter, grid, and load.
5. How physical and electrical balance is checked.
6. How annual technical KPIs and lifecycle economics are calculated.
7. How candidate systems are generated, tested for feasibility, and ranked.
8. Which equations reproduce HOMER Pro methodology.
9. Which equations are project-specific approximations or extensions.
10. What has been validated, what currently fails, and what must be improved.

Use four labels throughout the presentation:

- **HOMER-aligned:** Equation and interpretation follow current HOMER documentation.
- **HOMER-inspired:** Same engineering idea, but the implementation is simplified or extended.
- **Project-specific:** A deliberate modeling or software-design decision made in this engine.
- **Planned:** A configuration field or feature exists, but the physics is not yet active.

Do not call the complete engine an exact clone of HOMER Pro. A defensible claim is:

> The project is an independent Python hybrid-energy simulation and grid-search optimization engine. Its PV, wind, lifecycle-economics, and time-step energy-flow structure are based substantially on published HOMER methods, while several battery, tariff, reliability, and KPI definitions remain simplified or require direct HOMER-export calibration.

---

## 2. Recommended presentation sequence

### Part A — Problem, scope, and architecture

#### Slide 1 — Title

**Design and Validation of a Python-Based Hybrid Renewable Energy Simulation and Optimization Engine**

Subtitle:

**PV–Wind–Battery–Converter–Grid Modeling Using HOMER-Inspired Time-Step Calculations**

#### Slide 2 — Problem statement

Hybrid systems have coupled design decisions:

- Renewable generation changes every time step.
- Load changes every time step.
- PV and battery are primarily DC-side components.
- Wind, load, and grid are AC-side components.
- Converter capacity and efficiency constrain cross-bus power flow.
- Battery SOC couples the current time step to all future time steps.
- The technically feasible system is not necessarily the least-cost system.

The model must therefore simulate chronology before it can compare economics.

#### Slide 3 — Project objectives

- Build a transparent Python alternative for hybrid-system analysis.
- Support PV, wind, BESS, bidirectional conversion, and grid exchange.
- Simulate operation at configurable time resolutions.
- enforce physical limits and energy balance.
- Evaluate reliability, renewable contribution, NPC, and LCOE.
- Search component combinations and rank feasible designs.
- Compare equations and selected outputs with HOMER Pro.

#### Slide 4 — Current scope

Implemented:

- Project setup and economics.
- Imported or synthetic load profiles.
- NASA POWER solar, wind, and temperature resources.
- PV, wind, BESS, converter, and grid models.
- Renewable-first dispatch.
- Hourly/sub-hourly simulation.
- Grid-search candidate generation.
- Reliability/reserve constraints.
- NPC and LCOE evaluation.
- CSV/JSON output and Streamlit result visualization.

Not yet complete:

- Time-of-use and real-time tariffs.
- Demand charges.
- Grid outage schedules.
- Detailed emissions reporting.
- Alternative dispatch strategies.
- PV tracking behavior.
- Converter part-load efficiency curves.
- Direct automated HOMER-export regression.

#### Slide 5 — End-to-end architecture

```text
Streamlit dashboard
        |
        v
Project JSON + Components JSON + Load CSV + Resources CSV
        |
        v
Schema validation, timestamp validation, scaling, and resampling
        |
        v
Candidate generator: PV x Wind x Battery x Converter search space
        |
        v
Chronological simulator
  resource models -> dispatch controller -> battery state update
        |
        v
Energy-balance validation + annual KPI aggregation
        |
        v
Feasibility constraints + lifecycle economics
        |
        v
NPC-ranked candidate table + detailed selected-candidate results
```

Core code areas:

- `core/project.py`: project metadata and economics schema.
- `core/load.py`: load import, generation, quality checks, scaling, resampling.
- `core/resources.py`: NASA POWER data, validation, resampling, clearness index.
- `core/components/`: component configuration and input validation.
- `core/simulation/`: resource-to-power models, dispatch, battery state, results.
- `core/economics/evaluator.py`: lifecycle cost calculations.
- `core/optimization/`: candidate generation, constraints, simulation, ranking.
- `dashboard/pages/`: user workflow and visualization.

---

## 3. Project setup module

### Inputs

- Project name, author, and description.
- Latitude, longitude, and timezone.
- Nominal discount rate and inflation.
- Project lifetime.
- Allowed annual capacity shortage.
- Simulation time step in minutes.
- Dispatch strategy.
- Display currency.

### Validation

- Latitude: `-90 <= latitude <= 90`.
- Longitude: `-180 <= longitude <= 180`.
- Non-empty timezone.
- Project lifetime greater than zero.
- Nominal discount rate and inflation non-negative.
- Nominal discount rate must not be below inflation.
- Simulation time step greater than zero.
- Supported dispatch strategy currently equals `renewable_first`.

### Fisher real discount rate

HOMER-aligned:

```text
i = (i_nominal - f) / (1 + f)
```

where all rates are fractions:

- `i`: real discount rate.
- `i_nominal`: nominal discount rate.
- `f`: expected inflation rate.

The code stores percentages, so it uses the equivalent percentage form:

```text
real_rate_pct =
    (nominal_rate_pct - inflation_rate_pct)
    / (1 + inflation_rate_pct / 100)
```

---

## 4. Load module

### Supported load paths

1. Upload an existing load CSV.
2. Generate a constant load.
3. Generate a 24-hour profile.
4. Generate weekday/weekend profiles.
5. Define separate hourly profiles for every month.

### Automatic import pipeline

- Detect timestamp and demand columns.
- Parse multiple timestamp formats.
- Convert demand to numeric values.
- Sort chronologically.
- Reject duplicate timestamps.
- Reject invalid or negative demand values.
- Verify a uniform time interval.

### Energy conversion

For a constant time step:

```text
E_load = sum(P_load,t * delta_t)
```

where:

- `P_load,t` is load in kW.
- `delta_t` is the time step in hours.
- `E_load` is energy in kWh.

### Annual-energy scaling

```text
scale_factor = target_annual_energy / current_annual_energy
P_scaled,t = P_original,t * scale_factor
```

This preserves the profile shape while matching a known annual consumption.

### Synthetic variability

Project-specific HOMER-style stochastic load:

```text
P_t = P_base(month, day_type, hour) * D_day * V_t
```

```text
D_day ~ max(0, Normal(1, sigma_daily))
V_t   ~ max(0, Normal(1, sigma_timestep))
```

with:

```text
sigma = variability_percentage / 100
```

If “preserve annual energy” is enabled, the randomized profile is rescaled to the deterministic baseline annual energy.

### Resampling

- Finer time steps: forward/stepwise hold.
- Coarser time steps: arithmetic mean power.
- Energy is preserved when the time-step factor is applied correctly.

### Validation evidence

Tests cover:

- CSV auto-detection.
- Timestamp parsing.
- Duplicate and uneven timestamps.
- Annual-energy scaling.
- Constant and synthetic load creation.
- Reproducible random seeds.
- Energy preservation after variability.
- Time-step-independent annual energy.

---

## 5. Resource module

### Resource variables

- `ghi`: global horizontal irradiance.
- `ws50m`: wind speed at 50 m.
- `temperature`: ambient temperature.

### Data source

NASA POWER hourly API:

- `ALLSKY_SFC_SW_DWN`
- `WS50M`
- `T2M`

The downloader:

- Splits long year ranges into chunks.
- Downloads chunks in parallel.
- Detects NASA `-999` fill values.
- Trims invalid beginning/end periods.
- Rejects unexpected fill values inside the valid time series.

### Resource validation

- Required columns must exist.
- Timestamps must parse.
- Numeric columns must be finite.
- GHI and wind speed cannot be negative.
- Duplicate timestamps are rejected.

### Resource resampling

GHI, wind speed, and temperature are linearly interpolated for finer time steps. GHI is clipped to non-negative values.

### Critical timestamp requirement

Solar geometry assumes timestamps represent civil/local standard time. Every resource file must therefore carry explicit time-basis metadata:

- UTC
- civil local standard time
- daylight-saving local time
- local solar time

This is currently a known weakness. A legacy `test_3` resource file appears UTC-like because its mean solar peak occurs near timestamp hour 07:00, but the project interprets it as Asia/Kolkata civil time. That causes a large full-year tilted-PV mismatch.

---

## 6. Solar geometry, clearness index, and PV generation

This should be the most detailed technical section.

### 6.1 Solar declination

HOMER/Duffie–Beckman form:

```text
delta = 23.45 * sin[(360/365) * (284 + n)]
```

where `n` is day of year.

### 6.2 Equation of time and solar time

```text
t_s = t_c + longitude/15 - timezone_offset + E
```

```text
omega = 15 * (t_s - 12)
```

where:

- `t_s`: solar time.
- `t_c`: civil time at the midpoint of the time step.
- `E`: equation of time in hours.
- `omega`: solar hour angle.

Implementation nuance:

- `resources.py` uses HOMER’s documented Duffie–Beckman/Spencer-series equation.
- `pv_model.py` uses the common `9.87 sin(2B) - 7.53 cos(B) - 1.5 sin(B)` approximation because repository comparison work found closer observed HOMER parity for tilted panels.
- This difference must be reconciled in a future cleanup so resource preprocessing and PV simulation share one explicitly validated convention.

### 6.3 Extraterrestrial normal irradiance

```text
G_on = G_sc * [1 + 0.033 cos(B)]
```

with:

```text
G_sc = 1367 W/m²
```

### 6.4 Time-step-average extraterrestrial horizontal irradiance

```text
G0_bar = (12/pi) * G_on *
[
 cos(phi) cos(delta) (sin(omega_2) - sin(omega_1))
 + (omega_2 - omega_1) sin(phi) sin(delta)
]
```

The integration interval is clipped to sunrise and sunset hour angles. This prevents nighttime portions of partial daylight hours from distorting the clearness index.

### 6.5 Clearness index

```text
K_t = GHI / G0_bar
```

Optional artifact cap:

```text
K_t,effective = min(K_t, K_t,max)
GHI_effective = K_t,effective * G0_bar
```

Default configurable cap: `K_t,max = 0.82`.

Purpose:

- Detect or limit physically suspicious GHI values near sunrise/sunset.
- Prevent exaggerated beam decomposition and tilted-plane gain.

### 6.6 Erbs decomposition

Diffuse fraction:

```text
if K_t <= 0.22:
    f_d = 1 - 0.09 K_t

if 0.22 < K_t <= 0.80:
    f_d = 0.9511 - 0.1604 K_t + 4.388 K_t²
          - 16.638 K_t³ + 12.336 K_t⁴

if K_t > 0.80:
    f_d = 0.165
```

```text
G_diffuse,h = f_d * GHI
G_beam,h = GHI - G_diffuse,h
```

### 6.7 Tilt and azimuth

- Default slope: absolute site latitude.
- Default azimuth: south-facing.
- HOMER/Duffie–Beckman azimuth convention:
  - `0°`: south.
  - positive: west.
  - negative: east.

The full incidence-angle equation is implemented from Duffie and Beckman.

### 6.8 HDKR plane-of-array radiation

Beam ratio:

```text
R_b = max(0, cos(theta)) / max(cos(theta_z), cos(89°))
```

Anisotropy index:

```text
A_i = G_beam,h / (G_on cos(theta_z))
```

Horizon-brightening factor:

```text
f = sqrt(G_beam,h / GHI)
```

Diffuse tilted irradiance:

```text
G_diffuse,T =
G_diffuse,h *
[
 (1 - A_i) * (1 + cos(beta))/2
 * (1 + f sin³(beta/2))
 + A_i R_b
]
```

Beam tilted irradiance:

```text
G_beam,T = G_beam,h * R_b
```

Ground-reflected irradiance:

```text
G_ground,T = GHI * rho_g * (1 - cos(beta))/2
```

Total plane-of-array irradiance:

```text
G_T = G_beam,T + G_diffuse,T + G_ground,T
```

### 6.9 Cell temperature

Current project implementation:

```text
T_c = T_a + [(NOCT - 20) / 800] * G_T(W/m²)
```

This is a common NOCT approximation, but it is simpler than HOMER Pro’s documented cell-temperature energy-balance model, which also accounts for maximum-power-point efficiency. Therefore label this **HOMER-inspired**, not exact HOMER parity.

### 6.10 PV output

HOMER-aligned power equation:

```text
P_PV =
Y_PV * f_PV * (G_T / G_STC)
* [1 + alpha_P (T_c - T_c,STC)]
```

where:

- `Y_PV`: selected PV rated capacity.
- `f_PV`: derating factor.
- `G_T`: plane-of-array irradiance.
- `G_STC = 1 kW/m²`.
- `alpha_P`: temperature coefficient as fraction per degree Celsius.
- `T_c,STC = 25°C`.

If temperature effects are disabled, the correction factor equals one.

### 6.11 PV validation

The repository’s hand-calculated comparison passes:

- Zero-irradiance behavior.
- Linear irradiance scaling.
- Derating.
- STC output.
- NOCT temperature calculation used by this project.
- Temperature coefficient application.

The latest full-year `test_3` reference fails because the resource time basis/reference data are inconsistent with the current tilted-plane geometry path. Treat that as an unresolved validation-data issue.

### 6.12 PV features not yet active

- `single_axis` and `dual_axis` values are validated but do not change geometry.
- MPPT configuration is stored but its efficiency/table is not applied in PV generation.
- Spectral, soiling, mismatch, degradation, snow, shading, and bifacial effects are represented only indirectly through the derating factor.

---

## 7. Wind module

### 7.1 Hub-height wind speed

HOMER-aligned power law:

```text
U_hub = U_ref * (z_hub / z_ref)^alpha
```

Current defaults:

- `z_ref = 50 m`.
- `alpha = 0.14`.

### 7.2 Turbine power curve

For a speed between two tabulated points:

```text
fraction = (U - U_0) / (U_1 - U_0)
P(U) = P_0 + fraction * (P_1 - P_0)
```

The power curve explicitly represents cut-in, rated, and cut-out behavior.

### 7.3 Air-density correction

```text
P_density_corrected = P_curve * (rho / rho_0)
```

```text
rho_0 = 1.225 kg/m³
```

When the optional temperature effect is enabled:

```text
rho ≈ rho_0 * 288.15 / (T_celsius + 273.15)
```

This temperature-only density correction does not yet include pressure or altitude.

### 7.4 Multiple turbines and losses

```text
P_gross = quantity * P_single
```

Losses are combined multiplicatively:

```text
net_factor = product(1 - L_i)
L_total = 1 - net_factor
P_net = P_gross * net_factor
```

Example:

```text
10% availability loss and 10% electrical loss
net_factor = 0.90 * 0.90 = 0.81
total loss = 19%, not 20%
```

### Wind limitations

- Only the power-law shear model is active.
- No logarithmic-law roughness model.
- No pressure/altitude density model.
- Wake effects are a user-entered loss percentage, not a wake-flow model.
- Maintenance configuration is stored but not chronologically simulated.

---

## 8. Converter module

### DC to AC

```text
P_AC,out = P_DC,in * eta_inv
```

The inverter capacity is defined as maximum AC output:

```text
P_DC,in,max = P_inv,rated / eta_inv
```

### AC to DC

```text
P_DC,out = P_AC,in * eta_rect
```

The rectifier capacity is defined as maximum AC input:

```text
P_rect,rated =
P_inv,rated * rectifier_relative_capacity
```

### Important solved issue

The same physical inverter/rectifier capacity is shared by all conversion paths within a time step. PV-to-load and battery-to-load cannot each independently use the full inverter rating.

### Limitations

- Constant efficiency only.
- No part-load efficiency curve.
- No reactive power.
- No voltage-dependent behavior.
- “Parallel with AC generator” is stored but not operationally modeled.

---

## 9. Battery energy storage system

### 9.1 State variables

The battery is carried between time steps as a `BatteryState`:

- SOC.
- Effective capacity.
- Cumulative throughput.
- State of health.
- Cumulative cycle damage.
- Half-cycle start SOC.
- Current half-cycle direction.

This replaced an earlier bare-SOC design and allowed degradation features without repeatedly changing function signatures.

### 9.2 Nominal capacity

```text
C_nominal = capacity_per_string * number_of_strings
```

### 9.3 Symmetric efficiency split

Project modeling assumption:

```text
eta_charge = eta_discharge = sqrt(eta_roundtrip)
```

Example:

```text
eta_roundtrip = 0.90
eta_charge = eta_discharge = 0.94868
```

The hand-calculation tests use this assumption consistently. It should be described as a transparent simplification unless an exact HOMER storage-model setting is independently confirmed.

### 9.4 SOC and stored energy

```text
E_stored = C_effective * SOC/100
```

Charge:

```text
E_stored,new =
E_stored + P_charge * delta_t * eta_charge
```

Discharge:

```text
E_stored,new =
E_stored - P_discharge * delta_t / eta_discharge
```

```text
SOC_new = 100 * E_stored,new / C_effective
```

### 9.5 Charge/discharge power limits

```text
P_max = V_nominal * I_per_string * number_of_strings / 1000
```

Actual charge power is the minimum of:

- available surplus.
- current-based power limit.
- energy-space limit.

Actual discharge power is the minimum of:

- remaining deficit.
- current-based power limit.
- energy available above minimum SOC.

### 9.6 Self-discharge

```text
loss =
E_stored * self_discharge_rate_per_day * delta_t/24
```

SOC is not allowed below the configured minimum SOC.

### 9.7 Equivalent full cycles and fade

Current project throughput convention:

```text
throughput_step =
(P_charge + P_discharge,DC) * delta_t
```

```text
EFC = cumulative_throughput / (2 * C_nominal)
```

Simple cycle fade:

```text
cycle_fade_pct = fade_pct_per_EFC * EFC
```

Calendar fade:

```text
calendar_fade_pct =
calendar_fade_pct_per_year * elapsed_years
```

Combined fade:

```text
SOH = 100 - max(cycle_fade, calendar_fade, DoD_fade)
```

SOH is clamped to the configured end-of-life threshold.

### 9.8 Arrhenius calendar aging

```text
scale(T) =
exp[
 Ea/k_B * (1/T_ref,K - 1/T_K)
]
```

```text
effective_calendar_rate(T) =
base_rate * scale(T)
```

### 9.9 Temperature capacity correction

Reversible correction:

```text
capacity_factor(T) = d0 + d1*T + d2*T²
```

```text
C_dispatch = C_effective * capacity_factor(T)
```

The factor changes available capacity for the current time step but does not itself cause permanent degradation.

### 9.10 DoD-dependent cycle damage

```text
N(DoD) = A * DoD^(-beta)
```

At a direction reversal:

```text
damage_half_cycle =
0.5 / N(DoD)
= 0.5 * DoD^beta / A
```

Total cycle damage is accumulated using Miner’s rule.

### Battery limitations and validation warning

- Current throughput accounting is not identical to HOMER Pro’s published definition, which measures change in stored energy after charging losses and before discharging losses.
- Capacity fade is a project extension/simplification, not a proven reproduction of HOMER’s proprietary advanced storage model.
- Battery replacement affects economics, but the simulation does not physically reset battery age/state at replacement events.
- No voltage-versus-SOC curve, rate-capacity effect, kinetic battery model, or electrochemical thermal model.
- Half-cycle reversal logic is simpler than full rainflow counting.

---

## 10. Grid module

### Operational equations

```text
P_grid,export =
min(P_surplus, export_limit)
```

```text
P_excess =
P_surplus - P_grid,export + curtailed_PV
```

```text
P_grid,import =
min(P_remaining_load, import_limit)
```

```text
P_unmet =
P_remaining_load - P_grid,import
```

### Current economics

```text
annual_grid_purchase_cost =
E_grid_import * purchase_price
```

```text
annual_grid_export_revenue =
E_grid_export * sellback_price
```

```text
annual_grid_net_cost =
purchase_cost - export_revenue
```

### Grid limitations

- Flat tariffs only.
- No time-of-use tariff matrix.
- No real-time market price feed.
- No demand charges or monthly peak billing.
- Net-metering flag is stored but not applied as a billing settlement rule.
- No outages or grid availability schedule.
- CO2 intensity is stored but emissions are not calculated in results.

---

## 11. Dispatch controller

### Bus architecture

- PV: DC bus.
- Battery: DC bus.
- Wind: AC bus.
- Load: AC bus.
- Grid: AC bus.
- Converter: bridge between buses.

### Renewable-first sequence

1. Wind serves AC load directly.
2. PV serves load through the inverter.
3. Remaining PV charges the battery directly on the DC bus.
4. Remaining wind charges the battery through the rectifier.
5. Battery serves remaining load through the inverter.
6. Remaining renewable power is exported or curtailed.
7. Grid serves the remaining deficit; any residual becomes unmet load.

Self-discharge is applied before charge/discharge.

### Why chronological simulation is necessary

The decision at time `t` changes:

- SOC at `t+1`.
- energy available during later deficits.
- cumulative throughput.
- degradation.
- battery replacement life.
- renewable energy attribution through storage.

### Current dispatch limitation

Only `renewable_first` exists. HOMER can evaluate multiple dispatch/control strategies, while this engine currently has no:

- load-following generator strategy.
- cycle charging.
- tariff-arbitrage dispatch.
- predictive/model-predictive dispatch.
- demand-charge peak shaving.
- grid-support dispatch.

---

## 12. Energy-balance validation

The engine uses explicit DC/AC conventions and conversion losses:

```text
PV_DC + Wind_AC + Grid_import_AC + Battery_discharge_DC
=
Served_load_AC + Battery_charge_DC + Grid_export_AC
+ Excess + Inverter_loss + Rectifier_loss
```

For every row:

```text
mismatch = supply - demand
```

```text
balance_ok = abs(mismatch) <= 1e-6 kW
```

This test caught earlier mistakes involving:

- AC battery output being mixed with DC battery output.
- omitted inverter losses.
- omitted rectifier losses.
- converter clipping.
- export-limit handling.

---

## 13. Result aggregation

For any power series:

```text
E = sum(P_t * delta_t)
```

Calculated totals include:

- Load and served load.
- Unmet and excess energy.
- PV and wind generation.
- Grid import and export.
- Battery charge/discharge and throughput.
- Inverter, rectifier, and self-discharge losses.
- Final/min/max SOC.
- Final SOH and minimum effective capacity.

### Capacity-shortage KPI currently used

```text
annual_capacity_shortage_pct =
100 * unmet_load_energy / total_load_energy
```

Important: this is effectively an unmet-energy fraction. HOMER’s documented capacity-shortage definition also includes operating-reserve shortfall. The optimizer checks reserve shortfalls separately, but the KPI name is currently broader than its implemented formula.

### Renewable tracking

Net/effective renewable fraction:

```text
RF_net =
(direct_renewable_to_load
 + renewable_from_battery_to_load)
/ served_load
```

The model tracks the renewable share stored in the battery so battery discharge is not automatically treated as renewable.

Current gross renewable fraction:

```text
RF_gross =
(PV_generation + wind_generation) / served_load
```

clamped to one.

The dashboard wording currently describes a different denominator. This definition must be standardized before the final defense.

---

## 14. Lifecycle economics

### 14.1 Capital recovery factor

```text
CRF(i,N) =
i(1+i)^N / [(1+i)^N - 1]
```

If `i = 0`:

```text
CRF = 1/N
```

### 14.2 Uniform-series present-worth factor

```text
annuity_factor = 1 / CRF
```

### 14.3 Replacement present value

For replacements at years `kL`:

```text
PV_replacements =
sum[C_replacement / (1+i)^(kL)]
```

for replacement years strictly before the project end.

### 14.4 Salvage value

```text
salvage_fraction =
remaining_component_life / component_lifetime
```

```text
PV_salvage =
C_replacement * salvage_fraction / (1+i)^N
```

The use of replacement cost and linear remaining life follows HOMER’s published convention.

### 14.5 Net present cost

```text
NPC =
initial_capital
+ PV(replacements)
- PV(salvage)
+ [annual_O&M + annual_grid_net_cost] * annuity_factor
```

### 14.6 Annualized cost

```text
C_annualized = NPC * CRF(i,N)
```

### 14.7 LCOE

Current code:

```text
LCOE =
annualized_total_cost
/ (served_load_energy + grid_export_energy)
```

Validation warning:

- The current HOMER Pro 3.16 documentation describes electrical COE using served electrical load, not grid export.
- The project changed its denominator to include exports based on previous parity work.
- This must be settled using a controlled HOMER project with non-zero grid sales before claiming exact HOMER equivalence.
- This denominator difference explains why NPC and LCOE ranking need not be identical in the current test.

---

## 15. Optimization

### 15.1 Search-space generation

Candidate systems are the Cartesian product:

```text
PV options
x wind quantity options
x battery quantity options
x converter capacity options
```

Obvious invalid combinations are removed before simulation, such as:

- PV capacity greater than zero with zero converter capacity.
- Battery quantity greater than zero with zero converter capacity.

### 15.2 Candidate evaluation

For every candidate:

1. Run a full chronological simulation.
2. Validate time-step energy balance.
3. Calculate annual technical KPIs.
4. Test feasibility constraints.
5. Calculate lifecycle economics.
6. Store success/failure diagnostics.

Candidates are evaluated in parallel worker processes.

### 15.3 Reliability constraints

Current feasibility requires:

```text
capacity_shortage <= maximum_allowed
```

```text
renewable_fraction >= minimum_required
```

```text
operating_reserve_shortfall_hours = 0
```

Required operating reserve:

```text
R_required =
load * reserve_load_pct
+ annual_peak_load * reserve_peak_pct
+ PV_output * reserve_solar_pct
+ wind_output * reserve_wind_pct
```

Available reserve:

```text
R_available =
unused_grid_import_capacity
+ additional_battery_discharge_AC_capacity
```

### 15.4 Ranking

Current main sort:

1. Successful simulation first.
2. Feasible candidate first.
3. Lowest NPC.
4. Lowest LCOE.
5. Lowest capacity shortage.
6. Highest renewable fraction.

HOMER similarly presents feasible configurations primarily by NPC, but HOMER’s proprietary optimizer is not reproduced. This engine currently implements exhaustive grid search over user-entered discrete options.

---

## 16. Validation strategy and present evidence

### Layer 1 — Input validation

- Project ranges and economics.
- Load timestamps and values.
- Resource columns and values.
- Component costs, capacities, efficiencies, lifetimes, curves, and percentages.

### Layer 2 — Unit/behavior tests

Latest run:

```text
188 passed
4 failed
192 total
```

The four failures are:

1. Two outdated project tests still call `ProjectEconomics(discount_rate=...)` after the schema changed to `nominal_discount_rate_pct`.
2. Two optimization regression tests use `Test_1`, whose load contains 8,760 rows while resources contain 17,520 rows.

These are test-fixture/schema-maintenance failures, not failures in the core equations exercised by the other 188 tests.

### Layer 3 — Hand-calculated HOMER-style checks

Latest comparison:

```text
79 passed
2 failed
81 total
```

Passed:

- Basic PV power equation.
- Project NOCT temperature calculation.
- Battery SOC and efficiency calculations.
- Six single-step dispatch cases.
- Three-hour end-to-end scenario.
- Energy balance.
- Full-year wind reference.

Failed:

- Full-year `test_3` PV generation.
- Full-year `test_3` renewable fraction.

Likely root cause:

- Legacy resource timestamp basis/reference is inconsistent with the new solar-geometry interpretation.

### Layer 4 — Economic ranking scenario

Latest run:

```text
9 passed
1 failed
10 checks total
```

Passed:

- Energy balance for all 18 candidates.
- No unmet load.
- Positive NPC.
- More PV reduces grid import.
- More battery reduces grid import.
- Capital scales with capacity.
- Renewable fraction increases with renewable capacity.
- Grid-only LCOE matches flat grid price.
- Best PV-grid design beats grid-only NPC in the scenario.

Failed:

- “NPC rank equals LCOE rank.”

Reason:

- The test assumes every candidate has the same LCOE denominator.
- Current code adds exported energy to the denominator, so candidates with different exports can have different NPC and LCOE ordering.
- This is a stale/contested test expectation, not sufficient evidence of an optimizer defect.

### Layer 5 — Direct HOMER export comparison

The repository contains `tests/homer_pro_vs_our_model.py`, but:

- The HOMER hourly export file is not present.
- HOMER summary fields are not filled.

Therefore direct hourly and annual parity with an external HOMER run is not yet complete. This should be the highest-priority validation task.

---

## 17. Problems encountered and how they were solved

Use this section as the development story.

### Problem 1 — Fragile timestamp parsing

Issue:

- Different CSV date formats could be misread or ISO dates could be corrupted by day-first parsing.

Solution:

- Added smart timestamp classification and format-aware parsing.
- Added duplicate and regular-interval validation.

### Problem 2 — Slow and incomplete NASA downloads

Issue:

- Long downloads were sequential.
- NASA can return `-999` values at the beginning or end of a requested range.

Solution:

- Parallel chunk downloads.
- Trim invalid boundaries.
- Reject unexpected internal gaps.
- Report exact effective date range.

### Problem 3 — Horizontal GHI was insufficient for tilted PV

Issue:

- Direct use of GHI ignored panel slope, azimuth, beam/diffuse split, and ground reflection.

Solution:

- Added solar geometry.
- Integrated extraterrestrial irradiance across the time step.
- Added clearness index and Erbs decomposition.
- Added HDKR plane-of-array transposition.

### Problem 4 — Sunrise/sunset PV error

Issue:

- Midpoint and unclipped extraterrestrial irradiance distorted `K_t`.
- Near-horizon `R_b` could become unrealistically large.

Solution:

- Clip integration to daylight.
- Use a `cos(89°)` zenith floor.
- Separate integrated extraterrestrial radiation for `K_t` from the instantaneous basis used by the anisotropy index.

### Problem 5 — Energy-balance mismatch

Issue:

- DC and AC battery power were mixed.
- Converter losses were omitted from the balance.

Solution:

- Track battery DC discharge separately from AC-delivered discharge.
- Add inverter and rectifier losses explicitly.
- Validate every row at `1e-6 kW`.

### Problem 6 — Converter capacity double counting

Issue:

- Different power paths could independently consume the full converter rating.

Solution:

- Introduced shared inverter and rectifier capacity budgets for each time step.

### Problem 7 — Grid limits not consistently enforced

Issue:

- Export/import could exceed configured sale/purchase capacity.

Solution:

- Added explicit grid limit resolution and clipping.
- Added regression tests for import and export limits.

### Problem 8 — Wind losses added incorrectly

Issue:

- Adding percentages overstates combined losses.

Solution:

- Multiply remaining-energy factors.

### Problem 9 — Battery power did not scale correctly with strings

Issue:

- Parallel strings increase available current and therefore power.

Solution:

- Use `V * I_per_string * number_of_strings / 1000`.
- Added charge and discharge scaling tests.

### Problem 10 — Bare SOC could not support degradation

Issue:

- Passing only SOC made every new battery feature require interface changes.

Solution:

- Added `BatteryState` with SOC, capacity, throughput, SOH, and cycle tracking.

### Problem 11 — Degradation mechanisms were at risk of double counting

Issue:

- Simply adding calendar and cycle fade can overstate loss when they represent competing end-of-life mechanisms.

Solution:

- Use the dominant `max()` fade mechanism.
- Separate reversible temperature capacity correction from permanent degradation.

### Problem 12 — Economics lacked lifecycle detail

Issue:

- Initial capital alone cannot rank long-life systems.

Solution:

- Added Fisher real rate, replacement present value, salvage, annual O&M, grid cost/revenue, NPC, annualized cost, and component cost breakdown.

### Problem 13 — Large optimization sweeps were slow

Issue:

- Every candidate needs a full chronological simulation.

Solution:

- Use a process pool and evaluate candidates across available CPU cores.

---

## 18. Improvement roadmap

### Priority 0 — Required before claiming strong HOMER parity

1. Add resource time-basis metadata and convert all timestamps to one internal convention.
2. Regenerate `test_3` with known civil-time resources and update its reference from an actual HOMER export.
3. Complete direct HOMER hourly CSV comparison.
4. Reconcile:
   - capacity shortage versus unmet-energy fraction.
   - battery throughput definition.
   - LCOE denominator.
   - renewable-fraction definition.
   - PV cell-temperature equation.
5. Fix the four stale automated tests.
6. Version validation datasets so reference values cannot silently become stale.

### Priority 1 — Improve real-world decision quality

1. Time-of-use, seasonal, and real-time grid tariffs.
2. Demand charges and contracted-demand penalties.
3. Net-metering settlement rules.
4. Grid outage and reliability schedules.
5. Emissions calculation:

```text
CO2_grid = E_grid_import * emission_factor
```

6. Multiple dispatch strategies and tariff-aware battery control.
7. PV tracking and MPPT behavior.
8. Converter part-load efficiency.
9. Pressure/altitude wind-density correction and configurable shear model.
10. Multi-year simulation with physical battery replacement/reset events.

### Priority 2 — Research-grade extensions

1. Rainflow cycle counting.
2. Electrochemical battery models.
3. Component aging and degradation for PV, wind, and converter.
4. Forecast-based/model-predictive dispatch.
5. Monte Carlo reliability.
6. Multi-year weather and climate uncertainty.
7. Sensitivity analysis across tariffs, costs, resource years, and discount rates.
8. Continuous/metaheuristic optimization in addition to grid search.
9. Pareto optimization for NPC, emissions, renewable fraction, and reliability.
10. API/database-backed project and tariff data.

---

## 19. Suggested final slide

### Main achievement

The project successfully integrates:

- validated input pipelines.
- chronological renewable generation.
- AC/DC-aware dispatch.
- stateful battery behavior.
- time-step energy conservation.
- lifecycle economics.
- discrete system optimization.

### Honest conclusion

The engine is already useful as a transparent research and teaching platform. Its strongest areas are modular architecture, explicit energy-flow accounting, PV/wind equations, lifecycle cost structure, and test coverage. The next milestone is not adding more dashboard controls; it is completing strict definition-by-definition and time-step-by-time-step validation against controlled HOMER Pro exports.

---

## 20. Official reference set

Use these as primary HOMER references:

- HOMER overview and simulation/optimization process:  
  https://homerenergy.com/products/pro/docs/latest/index.html
- Radiation incident on the PV array, solar geometry, Erbs, and HDKR:  
  https://homerenergy.com/products/pro/docs/latest/how_homer_calculates_the_radiation_incident_on_the_pv_array.html
- PV array power output:  
  https://homerenergy.com/products/pro/docs/latest/how_homer_calculates_the_pv_array_power_output.html
- PV cell temperature:  
  https://homerenergy.com/products/pro/docs/latest/how_homer_calculates_the_pv_cell_temperature.html
- Wind turbine output:  
  https://homerenergy.com/products/pro/docs/latest/how_homer_calculates_wind_turbine_power_output.html
- Real discount rate:  
  https://homerenergy.com/products/pro/docs/latest/real_discount_rate.html
- Net present cost:  
  https://homerenergy.com/products/pro/docs/latest/net_present_cost.html
- Annualized cost:  
  https://homerenergy.com/products/pro/docs/latest/annualized_cost.html
- Salvage value:  
  https://homerenergy.com/products/pro/docs/latest/salvage_value.html
- Levelized cost of energy:  
  https://homerenergy.com/products/pro/docs/latest/levelized_cost_of_energy.html
- Battery throughput:  
  https://homerenergy.com/products/pro/docs/latest/battery_throughput.html
- Capacity shortage:  
  https://homerenergy.com/products/pro/docs/latest/capacity_shortage.html

Secondary engineering references already named in the code should be checked before final citation:

- Duffie and Beckman, *Solar Engineering of Thermal Processes*.
- Erbs et al. (1982), diffuse-fraction correlation.
- Schmalstieg et al., lithium-ion aging.
- Miner’s rule for cumulative fatigue damage.
- Relevant NREL storage-degradation reports.

