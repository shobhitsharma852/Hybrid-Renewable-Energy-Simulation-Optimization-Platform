from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.components.pv import (
    PVComponentConfig,
    PVOrientationSettings,
    PVTemperatureSettings,
)
from core.simulation.pv_model import simulate_pv_timeseries


DEFAULT_SCADA_DIR = Path(
    r"D:\Insolare\AI Class\Model\Homer\SCADA DATA 2020 TO 2026"
)
DEFAULT_PROJECT_DIR = Path("projects") / "SSNL"

AC_INV_RE = re.compile(r"^AC_Active Output Power Inverter-\d+$")
DC_INV_RE = re.compile(r"^DC_Power Inverter-\d+$")


def _read_scada_csv(path: Path) -> pd.DataFrame:
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        header = [c.strip() for c in fh.readline().strip().split(",")]

    raw = pd.read_csv(
        path,
        header=None,
        skiprows=1,
        names=list(range(100)),
        dtype=str,
        keep_default_na=True,
        na_values=["NaN", "nan", ""],
    )
    out = raw.iloc[:, : len(header)].copy()
    out.columns = header
    return out


def _numeric(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series(np.nan, index=df.index, dtype="float64")
    return pd.to_numeric(df[column], errors="coerce")


def build_scada_year(scada_dir: Path, year: int) -> pd.DataFrame:
    files = sorted(scada_dir.glob(f"{year}-*.csv"))
    if not files:
        raise FileNotFoundError(f"No SCADA CSV files found for {year} in {scada_dir}")

    frames: list[pd.DataFrame] = []
    for path in files:
        df = _read_scada_csv(path)
        timestamp = pd.to_datetime(
            df.iloc[:, 0],
            format="mixed",
            dayfirst=True,
            errors="coerce",
        )

        ac_cols = [c for c in df.columns if AC_INV_RE.match(c)]
        dc_cols = [c for c in df.columns if DC_INV_RE.match(c)]
        ac_df = pd.concat([_numeric(df, c) for c in ac_cols], axis=1)
        dc_df = pd.concat([_numeric(df, c) for c in dc_cols], axis=1)

        frames.append(
            pd.DataFrame(
                {
                    "timestamp": timestamp,
                    "meter_kw": _numeric(
                        df,
                        "Active Power-avg MFM-OUT(Meter Power)",
                    )
                    * 1000.0,
                    "inverter_sum_kw": ac_df.sum(axis=1, min_count=1),
                    "dc_sum_kw": dc_df.sum(axis=1, min_count=1),
                    "n_inv_reporting": ac_df.notna().sum(axis=1),
                    "poa": _numeric(df, "POA"),
                    "ghi": _numeric(df, "GHI_W"),
                    "temperature": _numeric(df, "AmbientTemperature"),
                    "module_temperature": _numeric(df, "Module SurfaceTemperature"),
                }
            )
        )

    merged = (
        pd.concat(frames, ignore_index=True)
        .dropna(subset=["timestamp"])
        .drop_duplicates(subset=["timestamp"], keep="first")
        .sort_values("timestamp")
        .reset_index(drop=True)
    )

    grid = pd.date_range(
        f"{year}-01-01 00:00:00",
        f"{year}-12-31 23:45:00",
        freq="15min",
    )
    merged = merged.set_index("timestamp").reindex(grid)
    merged.index.name = "timestamp"
    return merged.reset_index()


def clean_resource(df: pd.DataFrame) -> pd.DataFrame:
    out = df[["timestamp", "poa", "ghi", "temperature"]].copy()
    out["poa"] = pd.to_numeric(out["poa"], errors="coerce").clip(lower=0.0)
    out["ghi"] = pd.to_numeric(out["ghi"], errors="coerce").clip(lower=0.0)
    out["temperature"] = pd.to_numeric(out["temperature"], errors="coerce")

    # The verified 2020 scan found a few impossible ambient spikes.
    out.loc[out["temperature"] > 45.0, "temperature"] = np.nan

    for col in ["poa", "ghi", "temperature"]:
        out[col] = out[col].interpolate(limit_direction="both")

    return out


def _safe_metric(value: float) -> float | None:
    if math.isfinite(value):
        return float(value)
    return None


def _comparison_metrics(df: pd.DataFrame) -> dict[str, float | None]:
    valid = df["meter_kw"].notna() & df["pv_power_kw"].notna()
    if not valid.any():
        return {
            "mae_kw": None,
            "rmse_kw": None,
            "mbe_kw": None,
            "r2": None,
        }

    err = df.loc[valid, "pv_power_kw"] - df.loc[valid, "meter_kw"].clip(lower=0.0)
    meter = df.loc[valid, "meter_kw"].clip(lower=0.0)
    sse = float((err**2).sum())
    sst = float(((meter - meter.mean()) ** 2).sum())

    return {
        "mae_kw": _safe_metric(float(err.abs().mean())),
        "rmse_kw": _safe_metric(float(np.sqrt((err**2).mean()))),
        "mbe_kw": _safe_metric(float(err.mean())),
        "r2": _safe_metric(1.0 - sse / sst) if sst > 0 else None,
    }


def run_generation(
    *,
    scada_dir: Path,
    project_dir: Path,
    year: int,
    capacity_kw: float,
    derating_factor: float,
    temp_coeff_pct_per_c: float,
    noct_c: float,
) -> dict[str, object]:
    raw = build_scada_year(scada_dir=scada_dir, year=year)
    resource = clean_resource(raw)

    truth = raw[
        [
            "timestamp",
            "meter_kw",
            "inverter_sum_kw",
            "dc_sum_kw",
            "n_inv_reporting",
        ]
    ].copy()

    pv_config = PVComponentConfig(
        enabled=True,
        use_search_space=False,
        capacity_kw_options=[float(capacity_kw)],
        derating_factor=float(derating_factor),
        orientation=PVOrientationSettings(enabled=False),
        temperature=PVTemperatureSettings(
            enabled=True,
            temperature_coefficient_pct_per_degC=float(temp_coeff_pct_per_c),
            nominal_operating_cell_temp_c=float(noct_c),
        ),
    )

    pv = simulate_pv_timeseries(
        resource_df=resource,
        pv_config=pv_config,
        selected_capacity_kw=float(capacity_kw),
        latitude_deg=None,
        longitude_deg=None,
    )

    out = resource.merge(pv, on="timestamp", how="left").merge(
        truth,
        on="timestamp",
        how="left",
    )
    out["meter_kw_clipped"] = out["meter_kw"].clip(lower=0.0)
    out["model_minus_meter_kw"] = out["pv_power_kw"] - out["meter_kw_clipped"]

    dt_hours = 0.25
    model_mwh = float(out["pv_power_kw"].fillna(0.0).sum() * dt_hours / 1000.0)
    meter_mwh = float(out["meter_kw_clipped"].fillna(0.0).sum() * dt_hours / 1000.0)
    fit_derate = (
        float(derating_factor) * meter_mwh / model_mwh
        if model_mwh > 0
        else None
    )

    monthly = (
        out.assign(month=out["timestamp"].dt.to_period("M").astype(str))
        .groupby("month", as_index=False)
        .agg(
            model_mwh=("pv_power_kw", lambda s: float(s.fillna(0.0).sum() * dt_hours / 1000.0)),
            meter_mwh=("meter_kw_clipped", lambda s: float(s.fillna(0.0).sum() * dt_hours / 1000.0)),
            mean_poa=("poa", "mean"),
        )
    )
    monthly["bias_mwh"] = monthly["model_mwh"] - monthly["meter_mwh"]
    monthly["bias_pct"] = np.where(
        monthly["meter_mwh"] > 0,
        monthly["bias_mwh"] / monthly["meter_mwh"] * 100.0,
        np.nan,
    )

    inputs_dir = project_dir / "inputs"
    outputs_dir = project_dir / "outputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    outputs_dir.mkdir(parents=True, exist_ok=True)

    resource_path = inputs_dir / f"resource_{year}_poa_direct.csv"
    truth_path = inputs_dir / f"truth_{year}_meter.csv"
    generation_path = outputs_dir / f"pv_generation_{year}_poa_direct.csv"
    monthly_path = outputs_dir / f"pv_generation_{year}_monthly.csv"
    summary_path = outputs_dir / f"pv_generation_{year}_summary.json"

    resource.to_csv(resource_path, index=False)
    truth.to_csv(truth_path, index=False)
    out.to_csv(generation_path, index=False)
    monthly.to_csv(monthly_path, index=False)

    metrics = _comparison_metrics(out)
    summary: dict[str, object] = {
        "project": project_dir.name,
        "year": year,
        "mode": "measured_poa_direct",
        "note": "POA is used directly by calling simulate_pv_timeseries with latitude_deg=None and longitude_deg=None.",
        "capacity_kw": float(capacity_kw),
        "derating_factor": float(derating_factor),
        "temperature_coefficient_pct_per_c": float(temp_coeff_pct_per_c),
        "noct_c": float(noct_c),
        "rows": int(len(out)),
        "time_step_hours": dt_hours,
        "model_mwh": model_mwh,
        "meter_mwh": meter_mwh,
        "bias_mwh": model_mwh - meter_mwh,
        "bias_pct": ((model_mwh - meter_mwh) / meter_mwh * 100.0)
        if meter_mwh > 0
        else None,
        "peak_model_kw": float(out["pv_power_kw"].max()),
        "peak_meter_kw": float(out["meter_kw_clipped"].max()),
        "energy_fit_derating_factor_for_this_capacity": fit_derate,
        "metrics_on_valid_meter_rows": metrics,
        "files": {
            "resource": str(resource_path),
            "truth": str(truth_path),
            "generation": str(generation_path),
            "monthly": str(monthly_path),
            "summary": str(summary_path),
        },
    }

    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run SSNL PV generation validation using measured SCADA POA directly."
    )
    parser.add_argument("--scada-dir", type=Path, default=DEFAULT_SCADA_DIR)
    parser.add_argument("--project-dir", type=Path, default=DEFAULT_PROJECT_DIR)
    parser.add_argument("--year", type=int, default=2020)
    parser.add_argument("--capacity-kw", type=float, default=10000.0)
    parser.add_argument("--derating-factor", type=float, default=1.0)
    parser.add_argument("--temp-coeff-pct-per-c", type=float, default=-0.5)
    parser.add_argument("--noct-c", type=float, default=47.0)
    args = parser.parse_args()

    summary = run_generation(
        scada_dir=args.scada_dir,
        project_dir=args.project_dir,
        year=args.year,
        capacity_kw=args.capacity_kw,
        derating_factor=args.derating_factor,
        temp_coeff_pct_per_c=args.temp_coeff_pct_per_c,
        noct_c=args.noct_c,
    )

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
