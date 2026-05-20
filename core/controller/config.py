from __future__ import annotations

from typing import Literal, get_args


DispatchStrategy = Literal["renewable_first"]
DEFAULT_DISPATCH_STRATEGY: DispatchStrategy = "renewable_first"
VALID_DISPATCH_STRATEGIES: tuple[str, ...] = get_args(DispatchStrategy)


def validate_dispatch_strategy(value: str) -> DispatchStrategy:
    strategy = str(value).strip().lower()
    if strategy not in VALID_DISPATCH_STRATEGIES:
        valid = ", ".join(VALID_DISPATCH_STRATEGIES)
        raise ValueError(f"dispatch_strategy must be one of: {valid}")
    return strategy  # type: ignore[return-value]
