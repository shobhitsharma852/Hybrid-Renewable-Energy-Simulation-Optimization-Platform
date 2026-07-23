from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.compare_pv_scada_day import (
    SimpleXlsxReader,
    _find_report,
    _read_numeric_columns,
)


SCADA_ROOT = Path(r"D:\Insolare\AI Class\Model\Homer\Data")
PROJECT_DIR = ROOT_DIR / "projects" / "jsw"
DAY_FOLDERS = {
    15: "15th July",
    16: "16th July",
    17: "17th July",
    18: "18th July",
}


def read_day(day: int, folder_name: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    folder = SCADA_ROOT / folder_name
    inverter_path = _find_report(folder, "Inverter Report")
    weather_path = _find_report(folder, "Weather Report")

    inverter_power: list[np.ndarray] = []
    with SimpleXlsxReader(inverter_path) as workbook:
        inverter_sheets = [
            name
            for name in workbook.sheets
            if name.startswith("ICR") and "_INV" in name
        ]
        for sheet_name in inverter_sheets:
            values = _read_numeric_columns(
                workbook,
                sheet_name,
                {"active_power_kw": "Total Active Power"},
            )
            inverter_power.append(values["active_power_kw"])

    weather_values: list[dict[str, np.ndarray]] = []
    with SimpleXlsxReader(weather_path) as workbook:
        for sheet_name in list(workbook.sheets)[:2]:
            weather_values.append(
                _read_numeric_columns(
                    workbook,
                    sheet_name,
                    {
                        "poa": "GTI Top",
                        "ghi": "GHI",
                        "temperature": "Ambient Temperature",
                        "wind_speed": "Wind Speed",
                    },
                )
            )

    lengths = [len(values) for values in inverter_power]
    lengths.extend(len(values["poa"]) for values in weather_values)
    if min(lengths) != 1440 or min(lengths) != max(lengths):
        raise ValueError(f"{folder_name} does not contain 1,440 aligned records: {lengths}")

    timestamp = pd.date_range(f"2026-07-{day:02d}", periods=1440, freq="1min")
    resources = pd.DataFrame(
        {
            "timestamp": timestamp,
            "ghi": np.mean(
                np.stack([values["ghi"] for values in weather_values]),
                axis=0,
            ),
            # The weather-station wind sensor is retained for completeness.
            # Wind generation is disabled, so this column is not used.
            "ws50m": np.mean(
                np.stack([values["wind_speed"] for values in weather_values]),
                axis=0,
            ),
            "temperature": np.mean(
                np.stack([values["temperature"] for values in weather_values]),
                axis=0,
            ),
            # Measured GTI/POA is consumed directly by the PV model.
            "poa": np.mean(
                np.stack([values["poa"] for values in weather_values]),
                axis=0,
            ),
        }
    )
    truth = pd.DataFrame(
        {
            "timestamp": timestamp,
            "scada_ac_power_kw": np.sum(np.stack(inverter_power), axis=0),
        }
    )
    return resources, truth


def main() -> None:
    resources: list[pd.DataFrame] = []
    truth: list[pd.DataFrame] = []
    for day, folder_name in DAY_FOLDERS.items():
        day_resources, day_truth = read_day(day, folder_name)
        resources.append(day_resources)
        truth.append(day_truth)

    resource_df = pd.concat(resources, ignore_index=True)
    truth_df = pd.concat(truth, ignore_index=True)
    load_df = pd.DataFrame(
        {
            "timestamp": resource_df["timestamp"],
            "load_kw": np.zeros(len(resource_df)),
        }
    )

    inputs_dir = PROJECT_DIR / "inputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    resource_df.to_csv(inputs_dir / "resources.csv", index=False)
    load_df.to_csv(inputs_dir / "load.csv", index=False)
    truth_df.to_csv(inputs_dir / "scada_actual.csv", index=False)

    print(f"Created {len(resource_df):,} one-minute JSW resource rows")
    print(f"SCADA energy: {truth_df['scada_ac_power_kw'].sum() / 60 / 1000:.6f} MWh")


if __name__ == "__main__":
    main()
