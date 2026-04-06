from __future__ import annotations

from dataclasses import asdict, dataclass, field
import pandas as pd


@dataclass
class HourlySimulationRecord:
    hour_index: int
    load_kw: float
    pv_kw: float
    wind_kw: float
    renewable_kw: float
    served_load_kw: float
    excess_energy_kw: float
    unmet_load_kw: float

    # Battery reporting
    battery_charge_kw: float                 # DC into battery terminals
    battery_discharge_kw: float             # AC delivered after inverter
    battery_discharge_dc_kw: float          # DC out of battery terminals
    battery_soc_pct: float

    # Grid
    grid_import_kw: float
    grid_export_kw: float

    # Converter losses
    inverter_loss_kw: float = 0.0
    rectifier_loss_kw: float = 0.0


@dataclass
class SimulationSummary:
    total_load_kwh: float = 0.0
    total_served_load_kwh: float = 0.0
    total_unmet_load_kwh: float = 0.0
    total_excess_energy_kwh: float = 0.0

    total_pv_generation_kwh: float = 0.0
    total_wind_generation_kwh: float = 0.0

    total_grid_import_kwh: float = 0.0
    total_grid_export_kwh: float = 0.0

    total_battery_charge_kwh: float = 0.0              # DC into battery
    total_battery_discharge_kwh: float = 0.0           # AC delivered from battery path
    total_battery_discharge_dc_kwh: float = 0.0        # DC out of battery

    total_inverter_loss_kwh: float = 0.0
    total_rectifier_loss_kwh: float = 0.0

    renewable_fraction: float = 0.0

    # Extra reporting metrics
    gross_renewable_fraction: float = 0.0
    direct_renewable_to_load_kwh: float = 0.0
    renewable_from_battery_to_load_kwh: float = 0.0
    renewable_served_to_load_kwh: float = 0.0


@dataclass
class SimulationResults:
    hourly_records: list[HourlySimulationRecord] = field(default_factory=list)
    summary: SimulationSummary = field(default_factory=SimulationSummary)

    def to_dataframe(self) -> pd.DataFrame:
        return pd.DataFrame([asdict(record) for record in self.hourly_records])