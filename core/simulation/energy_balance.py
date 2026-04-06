from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


DEFAULT_ENERGY_BALANCE_TOLERANCE_KW: float = 1e-6


@dataclass(frozen=True)
class EnergyBalanceCheckResult:
    total_rows: int
    passed_rows: int
    failed_rows: int
    max_abs_mismatch_kw: float
    mean_abs_mismatch_kw: float
    tolerance_kw: float


def build_energy_balance_dataframe(
    hourly_df: pd.DataFrame,
    *,
    include_losses: bool = True,
) -> pd.DataFrame:
    """
    Correct system-wide electrical balance:

        pv_kw + wind_kw + grid_import_kw + battery_discharge_dc_kw
        =
        served_load_kw + battery_charge_kw + grid_export_kw + excess_energy_kw
        + inverter_loss_kw + rectifier_loss_kw

    Conventions:
    - pv_kw is DC generation from PV
    - wind_kw is AC generation from wind
    - battery_charge_kw is DC into battery terminals
    - battery_discharge_dc_kw is DC from battery terminals
    - battery_discharge_kw is AC delivered after inverter (reporting only)
    """
    required_columns = [
        "pv_kw",
        "wind_kw",
        "grid_import_kw",
        "battery_discharge_dc_kw",
        "served_load_kw",
        "battery_charge_kw",
        "grid_export_kw",
        "excess_energy_kw",
    ]

    missing = [col for col in required_columns if col not in hourly_df.columns]
    if missing:
        raise ValueError(
            f"Hourly dataframe is missing required energy balance columns: {missing}"
        )

    df = hourly_df.copy()

    for col in required_columns:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    if include_losses:
        if "inverter_loss_kw" not in df.columns:
            df["inverter_loss_kw"] = 0.0
        if "rectifier_loss_kw" not in df.columns:
            df["rectifier_loss_kw"] = 0.0

        df["inverter_loss_kw"] = pd.to_numeric(
            df["inverter_loss_kw"], errors="coerce"
        ).fillna(0.0)
        df["rectifier_loss_kw"] = pd.to_numeric(
            df["rectifier_loss_kw"], errors="coerce"
        ).fillna(0.0)
    else:
        df["inverter_loss_kw"] = 0.0
        df["rectifier_loss_kw"] = 0.0

    df["lhs_supply_kw"] = (
        df["pv_kw"]
        + df["wind_kw"]
        + df["grid_import_kw"]
        + df["battery_discharge_dc_kw"]
    )

    df["rhs_demand_kw"] = (
        df["served_load_kw"]
        + df["battery_charge_kw"]
        + df["grid_export_kw"]
        + df["excess_energy_kw"]
        + df["inverter_loss_kw"]
        + df["rectifier_loss_kw"]
    )

    df["mismatch_kw"] = df["lhs_supply_kw"] - df["rhs_demand_kw"]
    df["abs_mismatch_kw"] = df["mismatch_kw"].abs()

    return df


def validate_energy_balance(
    hourly_df: pd.DataFrame,
    *,
    tolerance_kw: float = DEFAULT_ENERGY_BALANCE_TOLERANCE_KW,
    include_losses: bool = True,
) -> tuple[EnergyBalanceCheckResult, pd.DataFrame]:
    tolerance_kw = max(0.0, float(tolerance_kw))

    balance_df = build_energy_balance_dataframe(
        hourly_df,
        include_losses=include_losses,
    )

    balance_df["balance_ok"] = balance_df["abs_mismatch_kw"] <= tolerance_kw

    total_rows = int(len(balance_df))
    passed_rows = int(balance_df["balance_ok"].sum())
    failed_rows = total_rows - passed_rows

    if total_rows > 0:
        max_abs_mismatch_kw = float(balance_df["abs_mismatch_kw"].max())
        mean_abs_mismatch_kw = float(balance_df["abs_mismatch_kw"].mean())
    else:
        max_abs_mismatch_kw = 0.0
        mean_abs_mismatch_kw = 0.0

    result = EnergyBalanceCheckResult(
        total_rows=total_rows,
        passed_rows=passed_rows,
        failed_rows=failed_rows,
        max_abs_mismatch_kw=max_abs_mismatch_kw,
        mean_abs_mismatch_kw=mean_abs_mismatch_kw,
        tolerance_kw=tolerance_kw,
    )

    return result, balance_df


def get_failed_energy_balance_rows(
    balance_df: pd.DataFrame,
    *,
    tolerance_kw: float = DEFAULT_ENERGY_BALANCE_TOLERANCE_KW,
) -> pd.DataFrame:
    tolerance_kw = max(0.0, float(tolerance_kw))

    if "abs_mismatch_kw" not in balance_df.columns:
        raise ValueError(
            "balance_df must contain 'abs_mismatch_kw'. "
            "Call build_energy_balance_dataframe() or validate_energy_balance() first."
        )

    return balance_df.loc[balance_df["abs_mismatch_kw"] > tolerance_kw].copy()