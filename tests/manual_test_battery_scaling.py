from core.simulation.battery_soc import update_battery_state


def show_result(label, result):
    print(f"\n--- {label} ---")
    print(f"Battery charge (kW): {result.battery_charge_kw:.2f}")
    print(f"Battery discharge (kW): {result.battery_discharge_kw:.2f}")
    print(f"New SOC (%): {result.new_soc_pct:.2f}")
    print(f"Stored energy (kWh): {result.stored_energy_kwh:.2f}")
    print(f"Available charge space (kWh): {result.available_charge_space_kwh:.2f}")
    print(f"Available discharge energy (kWh): {result.available_discharge_energy_kwh:.2f}")
    print(f"Max charge power (kW): {result.max_charge_power_kw:.2f}")
    print(f"Max discharge power (kW): {result.max_discharge_power_kw:.2f}")


def main():
    one_string_charge = update_battery_state(
        current_soc_pct=50.0,
        surplus_kw=1e9,
        deficit_kw=0.0,
        battery_enabled=True,
        quantity_strings=1,
        nominal_capacity_kwh_per_string=1000.0,
        nominal_voltage_v=600.0,
        max_charge_current_a=100.0,
        max_discharge_current_a=100.0,
        minimum_soc_pct=20.0,
        roundtrip_efficiency_pct=100.0,
        time_step_hours=1.0,
    )

    five_string_charge = update_battery_state(
        current_soc_pct=50.0,
        surplus_kw=1e9,
        deficit_kw=0.0,
        battery_enabled=True,
        quantity_strings=5,
        nominal_capacity_kwh_per_string=1000.0,
        nominal_voltage_v=600.0,
        max_charge_current_a=100.0,
        max_discharge_current_a=100.0,
        minimum_soc_pct=20.0,
        roundtrip_efficiency_pct=100.0,
        time_step_hours=1.0,
    )

    one_string_discharge = update_battery_state(
        current_soc_pct=80.0,
        surplus_kw=0.0,
        deficit_kw=1e9,
        battery_enabled=True,
        quantity_strings=1,
        nominal_capacity_kwh_per_string=1000.0,
        nominal_voltage_v=600.0,
        max_charge_current_a=100.0,
        max_discharge_current_a=100.0,
        minimum_soc_pct=20.0,
        roundtrip_efficiency_pct=100.0,
        time_step_hours=1.0,
    )

    five_string_discharge = update_battery_state(
        current_soc_pct=80.0,
        surplus_kw=0.0,
        deficit_kw=1e9,
        battery_enabled=True,
        quantity_strings=5,
        nominal_capacity_kwh_per_string=1000.0,
        nominal_voltage_v=600.0,
        max_charge_current_a=100.0,
        max_discharge_current_a=100.0,
        minimum_soc_pct=20.0,
        roundtrip_efficiency_pct=100.0,
        time_step_hours=1.0,
    )

    show_result("1 string - charge case", one_string_charge)
    show_result("5 strings - charge case", five_string_charge)
    show_result("1 string - discharge case", one_string_discharge)
    show_result("5 strings - discharge case", five_string_discharge)


if __name__ == "__main__":
    main()