from __future__ import annotations

from dataclasses import dataclass, field
from itertools import product

from core.components.config import ComponentsConfig
from .design_point import DesignPoint


@dataclass(frozen=True)
class CandidateGenerationResult:
    """
    Stores generated design candidates plus some simple diagnostics.
    """
    candidates: list[DesignPoint] = field(default_factory=list)
    total_raw_combinations: int = 0
    total_valid_candidates: int = 0
    total_filtered_out: int = 0


def _unique_sorted_float_options(values: list[float]) -> list[float]:
    cleaned = sorted({max(0.0, float(v)) for v in values})
    return cleaned if cleaned else [0.0]


def _unique_sorted_int_options(values: list[int]) -> list[int]:
    cleaned = sorted({max(0, int(v)) for v in values})
    return cleaned if cleaned else [0]


def _get_pv_options(components: ComponentsConfig) -> list[float]:
    if not components.pv.enabled:
        return [0.0]
    return _unique_sorted_float_options(components.pv.capacity_kw_options)


def _get_wind_options(components: ComponentsConfig) -> list[int]:
    if not components.wind.enabled:
        return [0]
    return _unique_sorted_int_options(components.wind.quantity_options)


def _get_battery_options(components: ComponentsConfig) -> list[int]:
    if not components.battery.enabled:
        return [0]
    return _unique_sorted_int_options(components.battery.quantity_options)


def _get_converter_options(components: ComponentsConfig) -> list[float]:
    if not components.converter.enabled:
        return [0.0]
    return _unique_sorted_float_options(components.converter.capacity_kw_options)


def _is_obviously_invalid_candidate(candidate: DesignPoint) -> bool:
    """
    Lightweight pre-filter only.

    We are NOT doing full feasibility here.
    We are only removing combinations that are architecturally nonsense.
    """
    # Battery exists but converter is zero -> battery cannot interact with AC load/PV path properly
    if candidate.battery_quantity > 0 and candidate.converter_capacity_kw <= 0.0:
        return True

    # PV exists but converter is zero -> DC PV cannot serve AC load in current architecture
    if candidate.pv_capacity_kw > 0.0 and candidate.converter_capacity_kw <= 0.0:
        return True

    return False


def generate_design_candidates(
    components: ComponentsConfig,
) -> CandidateGenerationResult:
    """
    Build all DesignPoint combinations from component search spaces.

    This is pure candidate generation only.
    No simulation, no economics, no ranking yet.
    """
    pv_options = _get_pv_options(components)
    wind_options = _get_wind_options(components)
    battery_options = _get_battery_options(components)
    converter_options = _get_converter_options(components)

    candidates: list[DesignPoint] = []
    total_raw_combinations = 0

    for pv_capacity_kw, wind_quantity, battery_quantity, converter_capacity_kw in product(
        pv_options,
        wind_options,
        battery_options,
        converter_options,
    ):
        total_raw_combinations += 1

        candidate = DesignPoint(
            pv_capacity_kw=float(pv_capacity_kw),
            wind_quantity=int(wind_quantity),
            battery_quantity=int(battery_quantity),
            converter_capacity_kw=float(converter_capacity_kw),
        )

        if _is_obviously_invalid_candidate(candidate):
            continue

        candidates.append(candidate)

    return CandidateGenerationResult(
        candidates=candidates,
        total_raw_combinations=total_raw_combinations,
        total_valid_candidates=len(candidates),
        total_filtered_out=total_raw_combinations - len(candidates),
    )