from __future__ import annotations

# ============================================================
# core/simulation/converter_model.py
#
# Purpose:
#   HOMER-style converter model for AC/DC power conversion.
#
# What this file does:
#   1. Convert DC -> AC through inverter efficiency
#   2. Convert AC -> DC through rectifier efficiency
#   3. Enforce inverter / rectifier capacity limits
#   4. Report conversion losses and clipped power
#
# HOMER-style assumptions used:
#   - inverter efficiency is constant
#   - rectifier efficiency is constant
#   - no part-load efficiency curve
#   - no thermal dynamics
#
# Notes:
#   - converter physics only, no dispatch decisions here
#   - dispatch should decide WHEN to call these functions
# ============================================================

from dataclasses import dataclass
from typing import Any

from core.components.converter import ConverterComponentConfig


# ============================================================
# CONSTANTS
# ============================================================

EPSILON: float = 1e-9


# ============================================================
# RESULT OBJECTS
# ============================================================

@dataclass(frozen=True)
class ConverterFlowResult:
    """
    Generic result for one directional conversion.

    For DC -> AC:
        input_power_kw   = DC input consumed
        output_power_kw  = AC output delivered

    For AC -> DC:
        input_power_kw   = AC input consumed
        output_power_kw  = DC output delivered
    """

    requested_power_kw: float
    input_power_kw: float
    output_power_kw: float
    loss_kw: float
    clipped_power_kw: float
    capacity_limit_kw: float
    efficiency_used: float
    direction: str


# ============================================================
# INTERNAL HELPERS
# ============================================================

def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp_non_negative(value: float) -> float:
    return max(0.0, float(value))


def _clamp_efficiency(value: float) -> float:
    """
    Clamp efficiency into a physically meaningful range.
    """
    value = float(value)
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _percent_to_fraction(percent_value: float) -> float:
    return float(percent_value) / 100.0


# ============================================================
# CAPACITY HELPERS
# ============================================================

def get_inverter_capacity_kw(
    converter_config: ConverterComponentConfig,
    selected_capacity_kw: float | None = None,
) -> float:
    """
    Resolve inverter nominal AC output capacity in kW.
    """
    if not converter_config.enabled:
        return 0.0

    if selected_capacity_kw is not None:
        return _clamp_non_negative(selected_capacity_kw)

    if getattr(converter_config, "capacity_kw_options", None):
        return _clamp_non_negative(max(converter_config.capacity_kw_options))

    return 0.0


def get_rectifier_capacity_kw(
    converter_config: ConverterComponentConfig,
    selected_inverter_capacity_kw: float | None = None,
) -> float:
    """
    Resolve rectifier nominal AC input capacity in kW.

    HOMER-style:
        Rectifier capacity is usually defined relative to inverter capacity.

    Supports either:
    - rectifier_relative_capacity_pct
    - rectifier_relative_capacity
    """
    if not converter_config.enabled:
        return 0.0

    inverter_capacity_kw = get_inverter_capacity_kw(
        converter_config=converter_config,
        selected_capacity_kw=selected_inverter_capacity_kw,
    )

    if hasattr(converter_config, "rectifier_relative_capacity_pct"):
        rel_pct = _safe_float(
            converter_config.rectifier_relative_capacity_pct, default=100.0
        )
    elif hasattr(converter_config, "rectifier_relative_capacity"):
        rel_pct = _safe_float(
            converter_config.rectifier_relative_capacity, default=100.0
        )
    else:
        rel_pct = 100.0

    return inverter_capacity_kw * _percent_to_fraction(rel_pct)


def get_inverter_efficiency(
    converter_config: ConverterComponentConfig,
) -> float:
    """
    Resolve inverter efficiency as fraction.
    Accepts either:
    - inverter_efficiency as fraction
    - inverter_efficiency_pct as percent
    """
    if hasattr(converter_config, "inverter_efficiency"):
        value = _safe_float(converter_config.inverter_efficiency, default=0.96)
        # if user stored 96 instead of 0.96
        if value > 1.0:
            value = value / 100.0
        return _clamp_efficiency(value)

    if hasattr(converter_config, "inverter_efficiency_pct"):
        return _clamp_efficiency(
            _percent_to_fraction(
                _safe_float(converter_config.inverter_efficiency_pct, default=96.0)
            )
        )

    return 0.96


def get_rectifier_efficiency(
    converter_config: ConverterComponentConfig,
) -> float:
    """
    Resolve rectifier efficiency as fraction.
    Accepts either:
    - rectifier_efficiency as fraction
    - rectifier_efficiency_pct as percent
    """
    if hasattr(converter_config, "rectifier_efficiency"):
        value = _safe_float(converter_config.rectifier_efficiency, default=0.96)
        if value > 1.0:
            value = value / 100.0
        return _clamp_efficiency(value)

    if hasattr(converter_config, "rectifier_efficiency_pct"):
        return _clamp_efficiency(
            _percent_to_fraction(
                _safe_float(converter_config.rectifier_efficiency_pct, default=96.0)
            )
        )

    return 0.96


# ============================================================
# CORE CONVERSION FUNCTIONS
# ============================================================

def convert_dc_to_ac(
    *,
    requested_dc_power_kw: float,
    converter_config: ConverterComponentConfig,
    selected_inverter_capacity_kw: float | None = None,
) -> ConverterFlowResult:
    """
    Convert DC power to AC through inverter.

    HOMER-style logic:
        AC_out = DC_in * eta_inv

    Capacity convention used here:
        inverter capacity is AC output capacity

    Therefore:
        AC_out <= inverter_capacity_kw

    So maximum DC input processable is:
        DC_in_max = inverter_capacity_kw / eta_inv
    """
    requested_dc_power_kw = _clamp_non_negative(requested_dc_power_kw)

    if not converter_config.enabled or requested_dc_power_kw <= EPSILON:
        return ConverterFlowResult(
            requested_power_kw=requested_dc_power_kw,
            input_power_kw=0.0,
            output_power_kw=0.0,
            loss_kw=0.0,
            clipped_power_kw=0.0,
            capacity_limit_kw=0.0,
            efficiency_used=0.0,
            direction="dc_to_ac",
        )

    inverter_capacity_kw = get_inverter_capacity_kw(
        converter_config=converter_config,
        selected_capacity_kw=selected_inverter_capacity_kw,
    )
    inverter_efficiency = get_inverter_efficiency(converter_config)

    if inverter_capacity_kw <= EPSILON or inverter_efficiency <= EPSILON:
        return ConverterFlowResult(
            requested_power_kw=requested_dc_power_kw,
            input_power_kw=0.0,
            output_power_kw=0.0,
            loss_kw=0.0,
            clipped_power_kw=requested_dc_power_kw,
            capacity_limit_kw=inverter_capacity_kw,
            efficiency_used=inverter_efficiency,
            direction="dc_to_ac",
        )

    max_dc_input_kw = inverter_capacity_kw / inverter_efficiency
    actual_dc_input_kw = min(requested_dc_power_kw, max_dc_input_kw)
    ac_output_kw = actual_dc_input_kw * inverter_efficiency
    loss_kw = actual_dc_input_kw - ac_output_kw
    clipped_dc_kw = requested_dc_power_kw - actual_dc_input_kw

    return ConverterFlowResult(
        requested_power_kw=requested_dc_power_kw,
        input_power_kw=actual_dc_input_kw,
        output_power_kw=ac_output_kw,
        loss_kw=loss_kw,
        clipped_power_kw=clipped_dc_kw,
        capacity_limit_kw=inverter_capacity_kw,
        efficiency_used=inverter_efficiency,
        direction="dc_to_ac",
    )


def convert_ac_to_dc(
    *,
    requested_ac_power_kw: float,
    converter_config: ConverterComponentConfig,
    selected_inverter_capacity_kw: float | None = None,
) -> ConverterFlowResult:
    """
    Convert AC power to DC through rectifier.

    HOMER-style logic:
        DC_out = AC_in * eta_rec

    Capacity convention used here:
        rectifier capacity is AC input capacity

    Therefore:
        AC_in <= rectifier_capacity_kw
    """
    requested_ac_power_kw = _clamp_non_negative(requested_ac_power_kw)

    if not converter_config.enabled or requested_ac_power_kw <= EPSILON:
        return ConverterFlowResult(
            requested_power_kw=requested_ac_power_kw,
            input_power_kw=0.0,
            output_power_kw=0.0,
            loss_kw=0.0,
            clipped_power_kw=0.0,
            capacity_limit_kw=0.0,
            efficiency_used=0.0,
            direction="ac_to_dc",
        )

    rectifier_capacity_kw = get_rectifier_capacity_kw(
        converter_config=converter_config,
        selected_inverter_capacity_kw=selected_inverter_capacity_kw,
    )
    rectifier_efficiency = get_rectifier_efficiency(converter_config)

    if rectifier_capacity_kw <= EPSILON or rectifier_efficiency <= EPSILON:
        return ConverterFlowResult(
            requested_power_kw=requested_ac_power_kw,
            input_power_kw=0.0,
            output_power_kw=0.0,
            loss_kw=0.0,
            clipped_power_kw=requested_ac_power_kw,
            capacity_limit_kw=rectifier_capacity_kw,
            efficiency_used=rectifier_efficiency,
            direction="ac_to_dc",
        )

    actual_ac_input_kw = min(requested_ac_power_kw, rectifier_capacity_kw)
    dc_output_kw = actual_ac_input_kw * rectifier_efficiency
    loss_kw = actual_ac_input_kw - dc_output_kw
    clipped_ac_kw = requested_ac_power_kw - actual_ac_input_kw

    return ConverterFlowResult(
        requested_power_kw=requested_ac_power_kw,
        input_power_kw=actual_ac_input_kw,
        output_power_kw=dc_output_kw,
        loss_kw=loss_kw,
        clipped_power_kw=clipped_ac_kw,
        capacity_limit_kw=rectifier_capacity_kw,
        efficiency_used=rectifier_efficiency,
        direction="ac_to_dc",
    )