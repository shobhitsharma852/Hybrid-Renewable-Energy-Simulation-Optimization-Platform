from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from core.components.config import ComponentsConfig
from core.optimization.design_point import DesignPoint
from .dispatch import run_dispatch_step
from .pv_model import compute_pv_power_from_resource_row
from .results import (
    HourlySimulationRecord,
    SimulationResults,
    SimulationSummary,
)
from .wind_model import (
    compute_wind_power_output,
    DEFAULT_REFERENCE_HEIGHT_M,
    DEFAULT_WIND_SHEAR_EXPONENT,
    STANDARD_AIR_DENSITY_KG_PER_M3,
)

EPSILON: float = 1e-9


@dataclass
class SimulationInputs:
    load_df: pd.DataFrame
    resource_df: pd.DataFrame
    components: ComponentsConfig
    design: DesignPoint
    time_step_hours: float = 1.0


class HybridSystemSimulator:
    def __init__(self, inputs: SimulationInputs):
        self.inputs = inputs

    def run(self) -> SimulationResults:
        load_df = self.inputs.load_df.copy()
        resource_df = self.inputs.resource_df.copy()
        components = self.inputs.components
        design = self.inputs.design

        n = min(len(load_df), len(resource_df))
        hourly_records: list[HourlySimulationRecord] = []

        current_battery_soc_pct = (
            components.battery.initial_state_of_charge_pct
            if components.battery.enabled and design.battery_quantity > 0
            else 0.0
        )

        renewable_energy_in_battery_kwh = 0.0
        total_direct_renewable_to_load_kwh = 0.0
        total_renewable_from_battery_to_load_kwh = 0.0

        for hour_index in range(n):
            load_kw = self._get_load_kw(load_df, hour_index)
            pv_kw = self._get_pv_kw(resource_df, hour_index, components)
            wind_kw = self._get_wind_kw(resource_df, hour_index, components)

            dispatch = run_dispatch_step(
                load_kw=load_kw,
                pv_kw=pv_kw,
                wind_kw=wind_kw,
                current_battery_soc_pct=current_battery_soc_pct,
                battery_config=components.battery,
                converter_config=components.converter,
                grid_config=components.grid,
                selected_battery_quantity=design.battery_quantity,
                selected_converter_capacity_kw=design.converter_capacity_kw,
                time_step_hours=self.inputs.time_step_hours,
            )

            current_battery_soc_pct = dispatch.battery_soc_pct

            direct_renewable_to_load_kwh = (
                dispatch.wind_to_load_kw + dispatch.pv_to_load_ac_kw
            )
            total_direct_renewable_to_load_kwh += direct_renewable_to_load_kwh

            renewable_energy_in_battery_kwh += dispatch.renewable_charge_stored_kwh

            renewable_battery_discharge_kwh = 0.0
            if (
                dispatch.battery_energy_removed_kwh > EPSILON
                and dispatch.battery_discharge_kw > EPSILON
            ):
                renewable_share_in_removed_energy = min(
                    1.0,
                    renewable_energy_in_battery_kwh / dispatch.battery_energy_removed_kwh,
                )

                renewable_battery_discharge_kwh = (
                    dispatch.battery_discharge_kw * renewable_share_in_removed_energy
                )

                renewable_energy_in_battery_kwh -= (
                    dispatch.battery_energy_removed_kwh
                    * renewable_share_in_removed_energy
                )
                renewable_energy_in_battery_kwh = max(
                    0.0,
                    renewable_energy_in_battery_kwh,
                )

            total_renewable_from_battery_to_load_kwh += renewable_battery_discharge_kwh

            hourly_records.append(
                HourlySimulationRecord(
                    hour_index=hour_index,
                    load_kw=load_kw,
                    pv_kw=pv_kw,
                    wind_kw=wind_kw,
                    renewable_kw=dispatch.renewable_kw,
                    served_load_kw=dispatch.served_load_kw,
                    excess_energy_kw=dispatch.excess_energy_kw,
                    unmet_load_kw=dispatch.unmet_load_kw,
                    battery_charge_kw=dispatch.battery_charge_kw,
                    battery_discharge_kw=dispatch.battery_discharge_kw,
                    battery_discharge_dc_kw=dispatch.battery_discharge_dc_kw,
                    battery_soc_pct=dispatch.battery_soc_pct,
                    grid_import_kw=dispatch.grid_import_kw,
                    grid_export_kw=dispatch.grid_export_kw,
                    inverter_loss_kw=dispatch.inverter_loss_kw,
                    rectifier_loss_kw=dispatch.rectifier_loss_kw,
                )
            )

        summary = self._build_summary(
            hourly_records=hourly_records,
            total_direct_renewable_to_load_kwh=total_direct_renewable_to_load_kwh,
            total_renewable_from_battery_to_load_kwh=total_renewable_from_battery_to_load_kwh,
        )

        return SimulationResults(
            hourly_records=hourly_records,
            summary=summary,
        )

    def _get_load_kw(self, load_df: pd.DataFrame, hour_index: int) -> float:
        if "load_kw" in load_df.columns:
            return float(load_df.iloc[hour_index]["load_kw"])
        if "load" in load_df.columns:
            return float(load_df.iloc[hour_index]["load"])
        raise ValueError("Load dataframe must contain 'load_kw' or 'load' column.")

    def _get_pv_kw(
        self,
        resource_df: pd.DataFrame,
        hour_index: int,
        components: ComponentsConfig,
    ) -> float:
        if not components.pv.enabled:
            return 0.0

        selected_pv_capacity_kw = max(0.0, float(self.inputs.design.pv_capacity_kw))
        if selected_pv_capacity_kw <= 0.0:
            return 0.0

        row = resource_df.iloc[hour_index]

        result = compute_pv_power_from_resource_row(
            resource_row=row,
            pv_config=components.pv,
            selected_capacity_kw=selected_pv_capacity_kw,
        )

        return result.net_power_kw

    def _get_wind_kw(
        self,
        resource_df: pd.DataFrame,
        hour_index: int,
        components: ComponentsConfig,
    ) -> float:
        if not components.wind.enabled:
            return 0.0

        quantity = max(0, int(self.inputs.design.wind_quantity))
        if quantity <= 0:
            return 0.0

        row = resource_df.iloc[hour_index]

        wind_speed_ref_mps = (
            float(row["ws50m"])
            if "ws50m" in resource_df.columns
            else 0.0
        )

        # Air density: only apply temperature correction if the flag is enabled
        if components.wind.consider_temperature_effects and "temperature" in resource_df.columns:
            temperature_c = float(row["temperature"])
            air_density_kg_per_m3 = STANDARD_AIR_DENSITY_KG_PER_M3 * (288.15 / (temperature_c + 273.15))
        else:
            air_density_kg_per_m3 = STANDARD_AIR_DENSITY_KG_PER_M3

        speed_points = components.wind.power_curve.wind_speed_points_mps
        power_points = components.wind.power_curve.power_output_points_kw
        losses = components.wind.losses

        result = compute_wind_power_output(
            wind_speed_ref_mps=wind_speed_ref_mps,
            quantity=quantity,
            hub_height_m=components.wind.hub_height_m,
            speed_points=speed_points,
            power_points=power_points,
            reference_height_m=DEFAULT_REFERENCE_HEIGHT_M,
            shear_exponent=DEFAULT_WIND_SHEAR_EXPONENT,
            air_density_kg_per_m3=air_density_kg_per_m3,
            availability_losses_pct=losses.availability_losses_pct,
            turbine_performance_losses_pct=losses.turbine_performance_losses_pct,
            environmental_losses_pct=losses.environmental_losses_pct,
            other_losses_pct=losses.other_losses_pct,
            wake_effects_losses_pct=losses.wake_effects_losses_pct,
            electrical_losses_pct=losses.electrical_losses_pct,
            curtailment_losses_pct=losses.curtailment_losses_pct,
        )

        return result.net_total_output_kw

    def _build_summary(
        self,
        *,
        hourly_records: list[HourlySimulationRecord],
        total_direct_renewable_to_load_kwh: float,
        total_renewable_from_battery_to_load_kwh: float,
    ) -> SimulationSummary:
        summary = SimulationSummary()
        dt = self.inputs.time_step_hours

        for r in hourly_records:
            summary.total_load_kwh += r.load_kw * dt
            summary.total_served_load_kwh += r.served_load_kw * dt
            summary.total_unmet_load_kwh += r.unmet_load_kw * dt
            summary.total_excess_energy_kwh += r.excess_energy_kw * dt
            summary.total_pv_generation_kwh += r.pv_kw * dt
            summary.total_wind_generation_kwh += r.wind_kw * dt
            summary.total_grid_import_kwh += r.grid_import_kw * dt
            summary.total_grid_export_kwh += r.grid_export_kw * dt
            summary.total_battery_charge_kwh += r.battery_charge_kw * dt
            summary.total_battery_discharge_kwh += r.battery_discharge_kw * dt
            summary.total_battery_discharge_dc_kwh += r.battery_discharge_dc_kw * dt
            summary.total_inverter_loss_kwh += r.inverter_loss_kw * dt
            summary.total_rectifier_loss_kwh += r.rectifier_loss_kw * dt

        gross_renewable_generation_kwh = (
            summary.total_pv_generation_kwh + summary.total_wind_generation_kwh
        )

        if summary.total_served_load_kwh > 0:
            gross_renewable_fraction = min(
                1.0,
                gross_renewable_generation_kwh / summary.total_served_load_kwh,
            )
        else:
            gross_renewable_fraction = 0.0
            

        renewable_served_to_load_kwh = (
            total_direct_renewable_to_load_kwh
            + total_renewable_from_battery_to_load_kwh
        )

        if summary.total_served_load_kwh > 0:
            effective_renewable_fraction = min(
                1.0,
                renewable_served_to_load_kwh / summary.total_served_load_kwh,
            )
        else:
            effective_renewable_fraction = 0.0

        summary.renewable_fraction = effective_renewable_fraction
        summary.gross_renewable_fraction = gross_renewable_fraction
        summary.direct_renewable_to_load_kwh = total_direct_renewable_to_load_kwh
        summary.renewable_from_battery_to_load_kwh = total_renewable_from_battery_to_load_kwh

        return summary