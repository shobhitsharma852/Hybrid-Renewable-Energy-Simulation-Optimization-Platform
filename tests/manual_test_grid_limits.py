from core.components.battery import BatteryComponentConfig
from core.components.converter import ConverterComponentConfig
from core.components.grid import GridComponentConfig
from core.simulation.dispatch import run_dispatch_step


def main():
    print("\n--- EXPORT CASE ---")
    export_result = run_dispatch_step(
        load_kw=0.0,
        pv_kw=0.0,
        wind_kw=1200.0,
        current_battery_soc_pct=50.0,
        battery_config=BatteryComponentConfig(enabled=False),
        converter_config=ConverterComponentConfig(),
        grid_config=GridComponentConfig(
            enabled=True,
            sale_capacity_kw=700.0,
            purchase_capacity_kw=1000.0,
        ),
        selected_battery_quantity=0,
        selected_converter_capacity_kw=1000.0,
        time_step_hours=1.0,
    )

    print(f"Grid export (kW): {export_result.grid_export_kw:.2f}")
    print(f"Excess energy (kW): {export_result.excess_energy_kw:.2f}")
    print(f"Unmet load (kW): {export_result.unmet_load_kw:.2f}")

    print("\n--- IMPORT CASE ---")
    import_result = run_dispatch_step(
        load_kw=1500.0,
        pv_kw=0.0,
        wind_kw=0.0,
        current_battery_soc_pct=50.0,
        battery_config=BatteryComponentConfig(enabled=False),
        converter_config=ConverterComponentConfig(),
        grid_config=GridComponentConfig(
            enabled=True,
            sale_capacity_kw=700.0,
            purchase_capacity_kw=1000.0,
        ),
        selected_battery_quantity=0,
        selected_converter_capacity_kw=1000.0,
        time_step_hours=1.0,
    )

    print(f"Grid import (kW): {import_result.grid_import_kw:.2f}")
    print(f"Unmet load (kW): {import_result.unmet_load_kw:.2f}")
    print(f"Served load (kW): {import_result.served_load_kw:.2f}")


if __name__ == "__main__":
    main()