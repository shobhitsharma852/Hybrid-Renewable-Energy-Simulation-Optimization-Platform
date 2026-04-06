from __future__ import annotations

import pytest

from core.components.converter import ConverterComponentConfig
from core.simulation.converter_model import (
    convert_ac_to_dc,
    convert_dc_to_ac,
    get_inverter_capacity_kw,
    get_inverter_efficiency,
    get_rectifier_capacity_kw,
    get_rectifier_efficiency,
)


def make_converter(
    *,
    enabled: bool = True,
    capacity_kw: float = 100.0,
    inverter_efficiency_pct: float = 96.0,
    rectifier_efficiency_pct: float = 95.0,
    rectifier_relative_capacity_pct: float = 80.0,
) -> ConverterComponentConfig:
    return ConverterComponentConfig(
        enabled=enabled,
        capacity_kw_options=[capacity_kw],
        inverter_efficiency_pct=inverter_efficiency_pct,
        rectifier_efficiency_pct=rectifier_efficiency_pct,
        rectifier_relative_capacity_pct=rectifier_relative_capacity_pct,
    )


def test_get_inverter_capacity_kw() -> None:
    converter = make_converter(capacity_kw=120.0)
    assert get_inverter_capacity_kw(converter) == pytest.approx(120.0)


def test_get_rectifier_capacity_kw_from_relative_percent() -> None:
    converter = make_converter(
        capacity_kw=100.0,
        rectifier_relative_capacity_pct=80.0,
    )
    assert get_rectifier_capacity_kw(converter) == pytest.approx(80.0)


def test_efficiency_helpers_return_expected_values() -> None:
    converter = make_converter(
        inverter_efficiency_pct=96.0,
        rectifier_efficiency_pct=95.0,
    )
    assert get_inverter_efficiency(converter) == pytest.approx(0.96)
    assert get_rectifier_efficiency(converter) == pytest.approx(0.95)


def test_dc_to_ac_zero_request_returns_zero() -> None:
    converter = make_converter()

    result = convert_dc_to_ac(
        requested_dc_power_kw=0.0,
        converter_config=converter,
    )

    assert result.input_power_kw == pytest.approx(0.0)
    assert result.output_power_kw == pytest.approx(0.0)
    assert result.loss_kw == pytest.approx(0.0)
    assert result.clipped_power_kw == pytest.approx(0.0)


def test_ac_to_dc_zero_request_returns_zero() -> None:
    converter = make_converter()

    result = convert_ac_to_dc(
        requested_ac_power_kw=0.0,
        converter_config=converter,
    )

    assert result.input_power_kw == pytest.approx(0.0)
    assert result.output_power_kw == pytest.approx(0.0)
    assert result.loss_kw == pytest.approx(0.0)
    assert result.clipped_power_kw == pytest.approx(0.0)


def test_dc_to_ac_without_clipping() -> None:
    converter = make_converter(
        capacity_kw=100.0,
        inverter_efficiency_pct=96.0,
    )

    result = convert_dc_to_ac(
        requested_dc_power_kw=50.0,
        converter_config=converter,
    )

    assert result.input_power_kw == pytest.approx(50.0)
    assert result.output_power_kw == pytest.approx(48.0)
    assert result.loss_kw == pytest.approx(2.0)
    assert result.clipped_power_kw == pytest.approx(0.0)


def test_dc_to_ac_with_clipping() -> None:
    converter = make_converter(
        capacity_kw=100.0,
        inverter_efficiency_pct=96.0,
    )

    result = convert_dc_to_ac(
        requested_dc_power_kw=120.0,
        converter_config=converter,
    )

    expected_max_dc_input = 100.0 / 0.96
    expected_ac_output = 100.0
    expected_loss = expected_max_dc_input - expected_ac_output
    expected_clipped = 120.0 - expected_max_dc_input

    assert result.input_power_kw == pytest.approx(expected_max_dc_input)
    assert result.output_power_kw == pytest.approx(expected_ac_output)
    assert result.loss_kw == pytest.approx(expected_loss)
    assert result.clipped_power_kw == pytest.approx(expected_clipped)


def test_ac_to_dc_without_clipping() -> None:
    converter = make_converter(
        capacity_kw=100.0,
        rectifier_efficiency_pct=95.0,
        rectifier_relative_capacity_pct=80.0,
    )

    result = convert_ac_to_dc(
        requested_ac_power_kw=40.0,
        converter_config=converter,
    )

    assert result.input_power_kw == pytest.approx(40.0)
    assert result.output_power_kw == pytest.approx(38.0)
    assert result.loss_kw == pytest.approx(2.0)
    assert result.clipped_power_kw == pytest.approx(0.0)


def test_ac_to_dc_with_clipping() -> None:
    converter = make_converter(
        capacity_kw=100.0,
        rectifier_efficiency_pct=95.0,
        rectifier_relative_capacity_pct=80.0,
    )

    result = convert_ac_to_dc(
        requested_ac_power_kw=100.0,
        converter_config=converter,
    )

    expected_ac_input = 80.0
    expected_dc_output = 76.0
    expected_loss = 4.0
    expected_clipped = 20.0

    assert result.input_power_kw == pytest.approx(expected_ac_input)
    assert result.output_power_kw == pytest.approx(expected_dc_output)
    assert result.loss_kw == pytest.approx(expected_loss)
    assert result.clipped_power_kw == pytest.approx(expected_clipped)


def test_disabled_converter_returns_zero_and_blocks_flow() -> None:
    converter = make_converter(enabled=False)

    dc_result = convert_dc_to_ac(
        requested_dc_power_kw=50.0,
        converter_config=converter,
    )
    ac_result = convert_ac_to_dc(
        requested_ac_power_kw=50.0,
        converter_config=converter,
    )

    assert dc_result.output_power_kw == pytest.approx(0.0)
    assert ac_result.output_power_kw == pytest.approx(0.0)


def test_converter_handles_full_percent_inputs() -> None:
    converter = make_converter(
        inverter_efficiency_pct=96.0,
        rectifier_efficiency_pct=95.0,
    )

    dc_result = convert_dc_to_ac(
        requested_dc_power_kw=50.0,
        converter_config=converter,
    )
    ac_result = convert_ac_to_dc(
        requested_ac_power_kw=40.0,
        converter_config=converter,
    )

    assert dc_result.output_power_kw == pytest.approx(48.0)
    assert ac_result.output_power_kw == pytest.approx(38.0)