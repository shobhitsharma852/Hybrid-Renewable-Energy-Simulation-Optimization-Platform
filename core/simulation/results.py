from __future__ import annotations

from dataclasses import asdict, dataclass, field
import pandas as pd


@dataclass
class SimulationTimestepRecord:
    """Simulation outputs for one timestep, regardless of timestep duration."""

    step_index: int
    timestamp: pd.Timestamp | None
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
    inverter_input_dc_kw: float = 0.0
    inverter_output_ac_kw: float = 0.0
    rectifier_input_ac_kw: float = 0.0
    rectifier_output_dc_kw: float = 0.0

    # Battery health fields — populated from BatteryState after each dispatch step.
    # effective_capacity_kwh: actual usable capacity after any future capacity fade;
    #   starts at nominal (n_strings × kWh_per_string) and will shrink year-by-year
    #   once fade is implemented. Stored per-hour so the results DataFrame captures
    #   the degradation curve for reporting and NPC calculations.
    # soh_pct: State of Health as % of original capacity (100 = new, ~80 = EOL Li-Ion).
    #   Reference: IEC 62619, manufacturer datasheets.
    effective_capacity_kwh: float = 0.0
    soh_pct: float = 100.0

    @property
    def hour_index(self) -> int:
        """Deprecated compatibility alias; use ``step_index`` instead."""
        return self.step_index


class HourlySimulationRecord(SimulationTimestepRecord):
    """Deprecated constructor-compatible name for ``SimulationTimestepRecord``."""

    def __init__(
        self,
        *args,
        hour_index: int | None = None,
        step_index: int | None = None,
        **kwargs,
    ) -> None:
        if args:
            if hour_index is not None or step_index is not None:
                raise TypeError(
                    "Do not combine a positional index with hour_index or step_index."
                )
            super().__init__(*args, **kwargs)
            return

        if hour_index is not None and step_index is not None:
            raise TypeError("Provide hour_index or step_index, not both.")

        resolved_index = step_index if step_index is not None else hour_index
        if resolved_index is None:
            raise TypeError("Missing required argument: step_index")

        super().__init__(step_index=resolved_index, **kwargs)


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
    # Total energy cycled through battery over the simulated period.
    # Used for throughput-based replacement timing (min of calendar vs throughput life).
    # Reference: HOMER Pro battery replacement methodology (NREL/TP-710-42565).
    total_battery_throughput_kwh: float = 0.0

    total_inverter_loss_kwh: float = 0.0
    total_rectifier_loss_kwh: float = 0.0
    total_inverter_input_kwh: float = 0.0
    total_inverter_output_kwh: float = 0.0
    total_rectifier_input_kwh: float = 0.0
    total_rectifier_output_kwh: float = 0.0

    renewable_fraction: float = 0.0
    annual_capacity_shortage_pct: float = 0.0
    unmet_load_fraction_pct: float = 0.0
    total_capacity_shortage_kwh: float = 0.0
    total_reserve_shortfall_kwh: float = 0.0
    max_reserve_shortfall_kw: float = 0.0
    reserve_shortfall_hours: int = 0

    # Extra reporting metrics
    gross_renewable_fraction: float = 0.0
    direct_renewable_to_load_kwh: float = 0.0
    renewable_from_battery_to_load_kwh: float = 0.0
    renewable_served_to_load_kwh: float = 0.0

    final_battery_soc_pct: float = 0.0
    min_battery_soc_pct: float = 0.0
    max_battery_soc_pct: float = 0.0

    # Battery health at end of simulation year.
    # final_soh_pct: State of Health (%) of the last timestep record — shows how much
    #   capacity the battery has lost to all aging mechanisms combined.
    # min_effective_capacity_kwh: lowest usable capacity seen during the year.
    final_soh_pct: float = 100.0
    min_effective_capacity_kwh: float = 0.0


@dataclass(init=False)
class SimulationResults:
    timestep_records: list[SimulationTimestepRecord] = field(default_factory=list)
    summary: SimulationSummary = field(default_factory=SimulationSummary)

    def __init__(
        self,
        timestep_records: list[SimulationTimestepRecord] | None = None,
        summary: SimulationSummary | None = None,
        *,
        hourly_records: list[SimulationTimestepRecord] | None = None,
    ) -> None:
        """
        Store per-timestep results.

        ``hourly_records`` remains accepted for compatibility with older callers,
        but new code should use ``timestep_records``.
        """
        if timestep_records is not None and hourly_records is not None:
            raise ValueError("Provide timestep_records or hourly_records, not both.")

        records = timestep_records if timestep_records is not None else hourly_records
        self.timestep_records = list(records) if records is not None else []
        self.summary = summary if summary is not None else SimulationSummary()

    @property
    def hourly_records(self) -> list[SimulationTimestepRecord]:
        """Deprecated compatibility alias; use ``timestep_records`` instead."""
        return self.timestep_records

    @hourly_records.setter
    def hourly_records(self, value: list[SimulationTimestepRecord]) -> None:
        self.timestep_records = value

    def to_dataframe(self) -> pd.DataFrame:
        return pd.DataFrame([asdict(record) for record in self.timestep_records])
