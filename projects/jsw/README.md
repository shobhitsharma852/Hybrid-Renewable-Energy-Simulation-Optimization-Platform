# JSW PV SCADA validation project

This is a PV-only, one-minute project covering 15–18 July 2026.

## Model boundary

- PV array capacity: 97.2 MWp DC
- Combined inverter/converter capacity: 52.8 MW AC
- Inverter efficiency: 95%
- Effective PV derating factor: 0.6371223755
- Temperature coefficient: -0.5%/°C
- NOCT: 47°C
- Wind and battery: disabled
- Load: zero, so AC production is exported to the grid

The resource file contains measured GHI, measured GTI/POA, ambient
temperature, and the weather-station wind channel averaged across Weather
Stations 1 and 2. The PV model uses the measured `poa` column directly.

`inputs/scada_actual.csv` is the sum of the 12 inverter
`Total Active Power (kW)` channels and is the validation truth at the inverter
AC-output boundary.

The derating factor was calibrated on 15 July. Results from 16–18 July are
independent validation results. Solar feeder 3 was effectively inactive during
all four days, so the effective derating must not be treated as a permanent
plant-wide loss factor until the feeder status and active DC capacity are
confirmed.
