from __future__ import annotations

"""
Tests that the renewable fraction tracking is correct for both hourly
and sub-hourly time steps.

Bug that was fixed:
  In HybridSystemSimulator.run(), direct_renewable_to_load_kwh and
  renewable_battery_discharge_kwh were accumulated in kW instead of kWh
  (missing * time_step_hours). For hourly simulations (dt=1.0) this was
  invisible; for sub-hourly runs it inflated effective_renewable_fraction.
"""

import pytest
import pandas as pd

from core.components.battery import BatteryComponentConfig
from core.components.converter import ConverterComponentConfig
from core.components.grid import GridComponentConfig
from core.components.pv import PVComponentConfig
from core.components.wind import (
    WindComponentConfig,
    WindPowerCurveSettings,
    WindLossSettings,
    WindMaintenanceSettings,
)
from core.components.config import ComponentsConfig
from core.optimization.design_point import DesignPoint
from core.simulation import HybridSystemSimulator, SimulationInputs


# ============================================================
# SHARED HELPERS
# ============================================================

def _wind_only_components() -> ComponentsConfig:
    """
    PV disabled.
    Wind: hub_height=50m (== DEFAULT_REFERENCE_HEIGHT_M) so no shear
    correction is applied, no losses, default power curve.
    Battery disabled.
    Grid: unlimited purchase, no export.
    """
    return ComponentsConfig(
        pv=PVComponentConfig(enabled=False),
        wind=WindComponentConfig(
            enabled=True,
            hub_height_m=50.0,          # equals reference height, so no shear
            consider_temperature_effects=False,
            power_curve=WindPowerCurveSettings(),   # default curve
            losses=WindLossSettings(
                availability_losses_pct=0.0,
                turbine_performance_losses_pct=0.0,
                environmental_losses_pct=0.0,
                other_losses_pct=0.0,
                wake_effects_losses_pct=0.0,
                electrical_losses_pct=0.0,
                curtailment_losses_pct=0.0,
            ),
            maintenance=WindMaintenanceSettings(enabled=False),
        ),
        battery=BatteryComponentConfig(enabled=False),
        converter=ConverterComponentConfig(inverter_efficiency_pct=100.0, rectifier_efficiency_pct=100.0),
        grid=GridComponentConfig(
            enabled=True,
            purchase_capacity_kw=999_999.0,
            sale_capacity_kw=0.0,
        ),
    )


def _design(wind_quantity: int = 1) -> DesignPoint:
    return DesignPoint(
        pv_capacity_kw=0.0,
        wind_quantity=wind_quantity,
        battery_quantity=0,
        converter_capacity_kw=1000.0,
    )


# ============================================================
# BUG 1: direct_renewable_to_load_kwh needs * dt
# ============================================================

class TestDirectRenewableTimestepScaling:
    """
    Scenario: 1 turbine, ws50m=5.0 m/s, hub_height=50m (no shear).
    Default power curve gives exactly 150 kW at 5.0 m/s.
    Load = 200 kW. Grid fills the 50 kW gap.

    Expected renewable fraction = 150 / 200 = 0.75.

    Before the fix, sub-hourly runs would compute:
        direct_renewable = 150 (kW, not kWh per step)
        total after 2 half-hour steps = 300 (wrong)
        served_load = 200 * 0.5 * 2 = 200 kWh (correct)
        fraction = min(1.0, 300/200) = 1.0  # wrong
    """

    def test_hourly_baseline_fraction(self):
        """1 step at dt=1.0 should give fraction = 0.75."""
        inputs = SimulationInputs(
            load_df=pd.DataFrame({"load_kw": [200.0]}),
            resource_df=pd.DataFrame({"ws50m": [5.0]}),
            components=_wind_only_components(),
            design=_design(),
            time_step_hours=1.0,
        )
        results = HybridSystemSimulator(inputs).run()
        s = results.summary

        assert s.total_load_kwh == pytest.approx(200.0, abs=1e-3)
        assert s.total_served_load_kwh == pytest.approx(200.0, abs=1e-3)
        assert s.total_wind_generation_kwh == pytest.approx(150.0, abs=1.0)
        # 150 kW wind all goes to load, grid covers remaining 50 kW
        assert s.total_grid_import_kwh == pytest.approx(50.0, abs=1.0)
        assert s.renewable_fraction == pytest.approx(0.75, abs=0.01)

    def test_30min_matches_hourly_fraction(self):
        """
        Same physical scenario at dt=0.5 (2 steps) must give the same
        renewable fraction as the hourly run.
        """
        components = _wind_only_components()
        design = _design()

        # Hourly reference
        inputs_1h = SimulationInputs(
            load_df=pd.DataFrame({"load_kw": [200.0]}),
            resource_df=pd.DataFrame({"ws50m": [5.0]}),
            components=components,
            design=design,
            time_step_hours=1.0,
        )
        fraction_1h = HybridSystemSimulator(inputs_1h).run().summary.renewable_fraction

        # 30-min: 2 identical half-hour steps represent the same 1-hour window
        inputs_30min = SimulationInputs(
            load_df=pd.DataFrame({"load_kw": [200.0, 200.0]}),
            resource_df=pd.DataFrame({"ws50m": [5.0, 5.0]}),
            components=components,
            design=design,
            time_step_hours=0.5,
        )
        fraction_30min = HybridSystemSimulator(inputs_30min).run().summary.renewable_fraction

        assert fraction_1h == pytest.approx(fraction_30min, abs=1e-6), (
            f"Renewable fraction differs between dt=1h ({fraction_1h:.6f}) "
            f"and dt=0.5h ({fraction_30min:.6f})"
        )

    def test_15min_matches_hourly_fraction(self):
        """Same check at dt=0.25 (4 steps per hour)."""
        components = _wind_only_components()
        design = _design()

        inputs_1h = SimulationInputs(
            load_df=pd.DataFrame({"load_kw": [200.0]}),
            resource_df=pd.DataFrame({"ws50m": [5.0]}),
            components=components,
            design=design,
            time_step_hours=1.0,
        )
        fraction_1h = HybridSystemSimulator(inputs_1h).run().summary.renewable_fraction

        inputs_15min = SimulationInputs(
            load_df=pd.DataFrame({"load_kw": [200.0] * 4}),
            resource_df=pd.DataFrame({"ws50m": [5.0] * 4}),
            components=components,
            design=design,
            time_step_hours=0.25,
        )
        fraction_15min = HybridSystemSimulator(inputs_15min).run().summary.renewable_fraction

        assert fraction_1h == pytest.approx(fraction_15min, abs=1e-6), (
            f"Renewable fraction differs between dt=1h ({fraction_1h:.6f}) "
            f"and dt=0.25h ({fraction_15min:.6f})"
        )

    def test_total_energy_is_time_step_independent(self):
        """
        Total load, wind generation, and grid import kWh must be identical
        regardless of whether we use 1×1h or 2×0.5h steps.
        """
        components = _wind_only_components()
        design = _design()

        s_1h = HybridSystemSimulator(SimulationInputs(
            load_df=pd.DataFrame({"load_kw": [200.0]}),
            resource_df=pd.DataFrame({"ws50m": [5.0]}),
            components=components,
            design=design,
            time_step_hours=1.0,
        )).run().summary

        s_30min = HybridSystemSimulator(SimulationInputs(
            load_df=pd.DataFrame({"load_kw": [200.0, 200.0]}),
            resource_df=pd.DataFrame({"ws50m": [5.0, 5.0]}),
            components=components,
            design=design,
            time_step_hours=0.5,
        )).run().summary

        assert s_1h.total_load_kwh == pytest.approx(s_30min.total_load_kwh, abs=1e-6)
        assert s_1h.total_wind_generation_kwh == pytest.approx(s_30min.total_wind_generation_kwh, abs=1e-6)
        assert s_1h.total_grid_import_kwh == pytest.approx(s_30min.total_grid_import_kwh, abs=1e-6)
        assert s_1h.total_served_load_kwh == pytest.approx(s_30min.total_served_load_kwh, abs=1e-6)


# ============================================================
# BUG 2: renewable_battery_discharge_kwh needs * dt
# ============================================================

class TestBatteryRenewableFractionTimestepScaling:
    """
    Scenario: wind charges battery fully in step 1, battery serves load in step 2.
    With 100% roundtrip efficiency all served energy is renewable, fraction = 1.0.

    But with partial renewable mix (wind + grid in step 1, battery in step 2):
    battery stores both renewable and grid energy, so the share tracked through
    renewable_battery_discharge_kwh must scale correctly with dt.
    """

    @staticmethod
    def _battery_components() -> ComponentsConfig:
        return ComponentsConfig(
            pv=PVComponentConfig(enabled=False),
            wind=WindComponentConfig(
                enabled=True,
                hub_height_m=50.0,
                consider_temperature_effects=False,
                power_curve=WindPowerCurveSettings(),
                losses=WindLossSettings(
                    availability_losses_pct=0.0,
                    turbine_performance_losses_pct=0.0,
                    environmental_losses_pct=0.0,
                    other_losses_pct=0.0,
                    wake_effects_losses_pct=0.0,
                    electrical_losses_pct=0.0,
                    curtailment_losses_pct=0.0,
                ),
                maintenance=WindMaintenanceSettings(enabled=False),
            ),
            battery=BatteryComponentConfig(
                enabled=True,
                nominal_capacity_kwh_per_string=500.0,
                nominal_voltage_v=600.0,
                max_charge_current_a=500.0,
                max_discharge_current_a=500.0,
                minimum_state_of_charge_pct=0.0,
                initial_state_of_charge_pct=50.0,
                roundtrip_efficiency_pct=100.0,
            ),
            converter=ConverterComponentConfig(
                inverter_efficiency_pct=100.0,
                rectifier_efficiency_pct=100.0,
            ),
            grid=GridComponentConfig(enabled=False),
        )

    def test_battery_renewable_fraction_consistent_across_timesteps(self):
        """
        2-step scenario:
          Step 1 (charge): wind = 150 kW, load = 0 kW, all wind stored in battery
          Step 2 (discharge): wind = 0 kW, load = 100 kW, battery serves load

        With 100% roundtrip eff, all served energy is renewable, fraction = 1.0
        for both dt=1.0 and dt=0.5.
        """
        components = self._battery_components()
        design = DesignPoint(
            pv_capacity_kw=0.0,
            wind_quantity=1,
            battery_quantity=1,
            converter_capacity_kw=1000.0,
        )

        # hourly: 2 steps of 1h
        inputs_1h = SimulationInputs(
            load_df=pd.DataFrame({"load_kw": [0.0, 100.0]}),
            resource_df=pd.DataFrame({"ws50m": [5.0, 0.0]}),
            components=components,
            design=design,
            time_step_hours=1.0,
        )
        s_1h = HybridSystemSimulator(inputs_1h).run().summary

        # 30-min: 4 steps of 0.5h (same physical scenario)
        inputs_30min = SimulationInputs(
            load_df=pd.DataFrame({"load_kw": [0.0, 0.0, 100.0, 100.0]}),
            resource_df=pd.DataFrame({"ws50m": [5.0, 5.0, 0.0, 0.0]}),
            components=components,
            design=design,
            time_step_hours=0.5,
        )
        s_30min = HybridSystemSimulator(inputs_30min).run().summary

        assert s_1h.total_served_load_kwh == pytest.approx(s_30min.total_served_load_kwh, abs=1e-3)
        assert s_1h.renewable_fraction == pytest.approx(s_30min.renewable_fraction, abs=1e-6), (
            f"Battery renewable fraction differs: dt=1h ({s_1h.renewable_fraction:.6f}) "
            f"vs dt=0.5h ({s_30min.renewable_fraction:.6f})"
        )
