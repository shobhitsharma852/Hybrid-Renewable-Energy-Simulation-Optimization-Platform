from __future__ import annotations

from core.components.converter import ConverterComponentConfig
from core.simulation.converter_model import (
    convert_ac_to_dc,
    convert_dc_to_ac,
    get_inverter_capacity_kw,
    get_rectifier_capacity_kw,
)


def main() -> None:
    converter = ConverterComponentConfig(
        enabled=True,
        capacity_kw_options=[100.0],
        inverter_efficiency_pct=96.0,
        rectifier_efficiency_pct=95.0,
        rectifier_relative_capacity_pct=80.0,
    )

    inverter_capacity_kw = get_inverter_capacity_kw(converter)
    rectifier_capacity_kw = get_rectifier_capacity_kw(converter)

    print("\n--- Converter Configuration ---")
    print(f"Inverter capacity (kW): {inverter_capacity_kw:.3f}")
    print(f"Rectifier capacity (kW): {rectifier_capacity_kw:.3f}")
    print(f"Inverter efficiency (%): {converter.inverter_efficiency_pct:.2f}")
    print(f"Rectifier efficiency (%): {converter.rectifier_efficiency_pct:.2f}")

    print("\n--- DC -> AC Test Cases ---")
    dc_requests = [0.0, 50.0, 100.0, 120.0]

    for requested_dc in dc_requests:
        result = convert_dc_to_ac(
            requested_dc_power_kw=requested_dc,
            converter_config=converter,
        )
        print(
            f"Requested DC: {requested_dc:8.3f} kW | "
            f"DC Used: {result.input_power_kw:8.3f} kW | "
            f"AC Out: {result.output_power_kw:8.3f} kW | "
            f"Loss: {result.loss_kw:8.3f} kW | "
            f"Clipped: {result.clipped_power_kw:8.3f} kW"
        )

    print("\n--- AC -> DC Test Cases ---")
    ac_requests = [0.0, 40.0, 80.0, 100.0]

    for requested_ac in ac_requests:
        result = convert_ac_to_dc(
            requested_ac_power_kw=requested_ac,
            converter_config=converter,
        )
        print(
            f"Requested AC: {requested_ac:8.3f} kW | "
            f"AC Used: {result.input_power_kw:8.3f} kW | "
            f"DC Out: {result.output_power_kw:8.3f} kW | "
            f"Loss: {result.loss_kw:8.3f} kW | "
            f"Clipped: {result.clipped_power_kw:8.3f} kW"
        )


if __name__ == "__main__":
    main()