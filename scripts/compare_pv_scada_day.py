from __future__ import annotations

import argparse
import copy
import json
import math
import re
import sys
import zipfile
from dataclasses import replace
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree as ET

import numpy as np
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.components.config import load_components
from core.simulation.pv_model import compute_pv_power_for_timestep


XLSX_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
XLSX_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _column_number(cell_reference: str) -> int:
    match = re.match(r"([A-Z]+)", cell_reference)
    if not match:
        return 0
    result = 0
    for character in match.group(1):
        result = result * 26 + ord(character) - ord("A") + 1
    return result


def _normalise_header(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())


class SimpleXlsxReader:
    """Small read-only XLSX reader for numeric SCADA exports.

    It avoids making this comparison dependent on openpyxl and streams the
    large inverter worksheets instead of loading each complete sheet in memory.
    """

    def __init__(self, path: Path):
        self.path = path
        self.archive = zipfile.ZipFile(path)
        self.shared_strings = self._read_shared_strings()
        self.sheets = self._read_sheet_map()

    def close(self) -> None:
        self.archive.close()

    def __enter__(self) -> "SimpleXlsxReader":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _read_shared_strings(self) -> list[str]:
        try:
            root = ET.parse(self.archive.open("xl/sharedStrings.xml")).getroot()
        except KeyError:
            return []
        values: list[str] = []
        for item in root.iter(f"{{{XLSX_MAIN_NS}}}si"):
            values.append(
                "".join(
                    node.text or ""
                    for node in item.iter(f"{{{XLSX_MAIN_NS}}}t")
                )
            )
        return values

    def _read_sheet_map(self) -> dict[str, str]:
        workbook = ET.parse(self.archive.open("xl/workbook.xml")).getroot()
        relationships = ET.parse(
            self.archive.open("xl/_rels/workbook.xml.rels")
        ).getroot()
        targets = {
            relation.attrib["Id"]: relation.attrib["Target"].replace("\\", "/")
            for relation in relationships
        }
        sheets: dict[str, str] = {}
        for sheet in workbook.iter(f"{{{XLSX_MAIN_NS}}}sheet"):
            relation_id = sheet.attrib[f"{{{XLSX_REL_NS}}}id"]
            target = targets[relation_id].lstrip("/")
            sheets[sheet.attrib["name"]] = (
                target if target.startswith("xl/") else f"xl/{target}"
            )
        return sheets

    def _cell_value(self, cell: ET.Element) -> str | None:
        value_type = cell.attrib.get("t")
        value_node = next(
            (node for node in cell if _local_name(node.tag) == "v"), None
        )
        if value_type == "inlineStr":
            return "".join(
                node.text or "" for node in cell.iter() if _local_name(node.tag) == "t"
            )
        if value_node is None or value_node.text is None:
            return None
        if value_type == "s":
            return self.shared_strings[int(value_node.text)]
        return value_node.text

    def iter_rows(self, sheet_name: str) -> Iterable[dict[int, str | None]]:
        with self.archive.open(self.sheets[sheet_name]) as worksheet:
            for _, element in ET.iterparse(worksheet, events=("end",)):
                if _local_name(element.tag) != "row":
                    continue
                row: dict[int, str | None] = {}
                for cell in element:
                    if _local_name(cell.tag) != "c":
                        continue
                    column = _column_number(cell.attrib.get("r", ""))
                    row[column] = self._cell_value(cell)
                yield row
                element.clear()


def _find_report(folder: Path, name_fragment: str) -> Path:
    matches = [
        path
        for path in folder.glob("*.xlsx")
        if name_fragment.lower() in path.name.lower()
    ]
    if len(matches) != 1:
        raise FileNotFoundError(
            f"Expected one {name_fragment!r} workbook in {folder}, found {len(matches)}"
        )
    return matches[0]


def _read_numeric_columns(
    workbook: SimpleXlsxReader,
    sheet_name: str,
    requested_headers: dict[str, str],
) -> dict[str, np.ndarray]:
    header_columns: dict[str, int] = {}
    output: dict[str, list[float]] = {key: [] for key in requested_headers}

    for row in workbook.iter_rows(sheet_name):
        if not header_columns:
            normalised = {
                column: _normalise_header(value)
                for column, value in row.items()
                if value is not None
            }
            candidate_columns: dict[str, int] = {}
            for output_name, expected_header in requested_headers.items():
                expected = _normalise_header(expected_header)
                matches = [
                    column
                    for column, header in normalised.items()
                    if header.startswith(expected)
                ]
                if matches:
                    candidate_columns[output_name] = min(matches)
            if len(candidate_columns) == len(requested_headers):
                header_columns = candidate_columns
            continue

        parsed: dict[str, float] = {}
        valid = True
        for output_name, column in header_columns.items():
            try:
                parsed[output_name] = float(row[column])
            except (KeyError, TypeError, ValueError):
                valid = False
                break
        if valid:
            for output_name, value in parsed.items():
                output[output_name].append(value)

    if not header_columns:
        raise ValueError(f"Could not find {requested_headers} in sheet {sheet_name}")
    return {key: np.asarray(values, dtype=float) for key, values in output.items()}


def read_scada_day(scada_folder: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict]:
    inverter_path = _find_report(scada_folder, "Inverter Report")
    weather_path = _find_report(scada_folder, "Weather Report")

    inverter_series: list[np.ndarray] = []
    with SimpleXlsxReader(inverter_path) as workbook:
        inverter_sheets = [
            name
            for name in workbook.sheets
            if re.fullmatch(r"ICR\d+_INV\d+", name)
        ]
        for sheet_name in inverter_sheets:
            values = _read_numeric_columns(
                workbook,
                sheet_name,
                {"active_power_kw": "Total Active Power"},
            )
            inverter_series.append(values["active_power_kw"])

    weather_series: list[dict[str, np.ndarray]] = []
    weather_names: list[str] = []
    with SimpleXlsxReader(weather_path) as workbook:
        for sheet_name in list(workbook.sheets)[:2]:
            weather_series.append(
                _read_numeric_columns(
                    workbook,
                    sheet_name,
                    {
                        "gti_w_m2": "GTI Top",
                        "ambient_temperature_c": "Ambient Temperature",
                    },
                )
            )
            weather_names.append(sheet_name)

    all_lengths = [len(values) for values in inverter_series]
    all_lengths.extend(len(values["gti_w_m2"]) for values in weather_series)
    if not inverter_series or not weather_series:
        raise ValueError("SCADA inverter or weather sheets were not found")
    if min(all_lengths) != max(all_lengths):
        raise ValueError(f"SCADA series lengths are not aligned: {all_lengths}")
    if min(all_lengths) != 1440:
        raise ValueError(f"Expected 1,440 one-minute records, found {min(all_lengths)}")

    scada_power_kw = np.sum(np.stack(inverter_series), axis=0)
    gti_w_m2 = np.mean(
        np.stack([values["gti_w_m2"] for values in weather_series]), axis=0
    )
    ambient_temperature_c = np.mean(
        np.stack(
            [values["ambient_temperature_c"] for values in weather_series]
        ),
        axis=0,
    )
    metadata = {
        "inverter_workbook": str(inverter_path),
        "weather_workbook": str(weather_path),
        "inverter_sheets": len(inverter_series),
        "weather_sheets_used": weather_names,
        "raw_records": len(scada_power_kw),
    }
    return scada_power_kw, gti_w_m2, ambient_temperature_c, metadata


def _mean_interval(values: np.ndarray, resolution_minutes: int) -> np.ndarray:
    if len(values) != 1440:
        raise ValueError("A complete one-minute day is required")
    if resolution_minutes <= 0 or 1440 % resolution_minutes != 0:
        raise ValueError("Resolution must divide evenly into 1,440 minutes")
    return values.reshape(1440 // resolution_minutes, resolution_minutes).mean(axis=1)


def compare_day(
    *,
    scada_folder: Path,
    project_folder: Path,
    date: str,
    resolution_minutes: int,
    dc_capacity_kw: float,
    ac_capacity_kw: float,
    inverter_efficiency_pct: float,
    derating_factor: float | None,
    output_folder: Path,
) -> tuple[Path, Path, dict]:
    scada_raw_kw, gti_raw, temperature_raw, source_metadata = read_scada_day(
        scada_folder
    )
    scada_kw = _mean_interval(scada_raw_kw, resolution_minutes)
    gti_w_m2 = _mean_interval(gti_raw, resolution_minutes)
    ambient_temperature_c = _mean_interval(temperature_raw, resolution_minutes)

    components = load_components(project_folder)
    pv_config = replace(
        copy.deepcopy(components.pv),
        enabled=True,
        capacity_kw_options=[float(dc_capacity_kw)],
        derating_factor=(
            float(derating_factor)
            if derating_factor is not None
            else float(components.pv.derating_factor)
        ),
    )

    model_dc_kw: list[float] = []
    model_ac_before_clipping_kw: list[float] = []
    model_ac_kw: list[float] = []
    cell_temperature_c: list[float] = []
    inverter_efficiency = float(inverter_efficiency_pct) / 100.0

    for irradiance, temperature in zip(gti_w_m2, ambient_temperature_c):
        result = compute_pv_power_for_timestep(
            irradiance_input_value=float(irradiance),
            ambient_temperature_c=float(temperature),
            pv_config=pv_config,
            selected_capacity_kw=float(dc_capacity_kw),
        )
        ac_before_clipping = result.net_power_kw * inverter_efficiency
        model_dc_kw.append(result.net_power_kw)
        model_ac_before_clipping_kw.append(ac_before_clipping)
        model_ac_kw.append(min(float(ac_capacity_kw), max(0.0, ac_before_clipping)))
        cell_temperature_c.append(result.cell_temperature_c)

    model_ac = np.asarray(model_ac_kw)
    error_kw = model_ac - scada_kw
    timestamps = pd.date_range(
        date, periods=len(scada_kw), freq=f"{resolution_minutes}min"
    )
    interval_hours = resolution_minutes / 60.0
    scada_energy_mwh = float(scada_kw.sum() * interval_hours / 1000.0)
    model_energy_mwh = float(model_ac.sum() * interval_hours / 1000.0)
    correlation = float(np.corrcoef(model_ac, scada_kw)[0, 1])

    # Diagnostic only: find the equivalent DC capacity that makes this same
    # day's model energy equal SCADA while retaining every other model setting.
    # This is calibration on the evaluated day, not an independent validation.
    base_dc = np.asarray(model_dc_kw)
    lower_capacity_kw = 0.0
    upper_capacity_kw = float(dc_capacity_kw)
    for _ in range(60):
        trial_capacity_kw = (lower_capacity_kw + upper_capacity_kw) / 2.0
        trial_ac = np.minimum(
            float(ac_capacity_kw),
            base_dc * (trial_capacity_kw / dc_capacity_kw) * inverter_efficiency,
        )
        trial_energy_mwh = float(trial_ac.sum() * interval_hours / 1000.0)
        if trial_energy_mwh < scada_energy_mwh:
            lower_capacity_kw = trial_capacity_kw
        else:
            upper_capacity_kw = trial_capacity_kw
    fitted_capacity_kw = (lower_capacity_kw + upper_capacity_kw) / 2.0
    fitted_model_ac = np.minimum(
        float(ac_capacity_kw),
        base_dc * (fitted_capacity_kw / dc_capacity_kw) * inverter_efficiency,
    )
    fitted_error_kw = fitted_model_ac - scada_kw

    comparison = pd.DataFrame(
        {
            "timestamp": timestamps,
            "gti_w_m2": gti_w_m2,
            "ambient_temperature_c": ambient_temperature_c,
            "model_cell_temperature_c": cell_temperature_c,
            "scada_ac_power_kw": scada_kw,
            "model_dc_power_kw": model_dc_kw,
            "model_ac_before_clipping_kw": model_ac_before_clipping_kw,
            "model_ac_power_kw": model_ac,
            "error_kw": error_kw,
            "absolute_error_kw": np.abs(error_kw),
            "same_day_energy_fitted_model_ac_power_kw": fitted_model_ac,
            "same_day_energy_fitted_error_kw": fitted_error_kw,
        }
    )

    summary = {
        "date": date,
        "resolution_minutes": int(resolution_minutes),
        "intervals": len(comparison),
        "dc_capacity_kw": float(dc_capacity_kw),
        "ac_capacity_kw": float(ac_capacity_kw),
        "inverter_efficiency_pct": float(inverter_efficiency_pct),
        "pv_model_settings": {
            "derating_factor": float(pv_config.derating_factor),
            "temperature_enabled": bool(pv_config.temperature.enabled),
            "temperature_coefficient_pct_per_degC": float(
                pv_config.temperature.temperature_coefficient_pct_per_degC
            ),
            "nominal_operating_cell_temp_c": float(
                pv_config.temperature.nominal_operating_cell_temp_c
            ),
        },
        "scada_energy_mwh": scada_energy_mwh,
        "model_energy_mwh": model_energy_mwh,
        "energy_difference_mwh": model_energy_mwh - scada_energy_mwh,
        "energy_difference_pct": 100.0
        * (model_energy_mwh - scada_energy_mwh)
        / scada_energy_mwh,
        "mae_kw": float(np.mean(np.abs(error_kw))),
        "rmse_kw": float(math.sqrt(np.mean(np.square(error_kw)))),
        "mean_bias_kw": float(np.mean(error_kw)),
        "normalised_mae_pct_of_ac_capacity": float(
            100.0 * np.mean(np.abs(error_kw)) / ac_capacity_kw
        ),
        "correlation": correlation,
        "scada_peak_kw": float(np.max(scada_kw)),
        "model_peak_kw": float(np.max(model_ac)),
        "clipped_intervals": int(np.count_nonzero(model_ac >= ac_capacity_kw)),
        "same_day_energy_fit_diagnostic": {
            "warning": (
                "Calibrated on the same day; use another day for validation. "
                "Capacity and derating cannot be identified separately from one day."
            ),
            "equivalent_dc_capacity_kw": float(fitted_capacity_kw),
            "equivalent_derating_factor_at_configured_capacity": float(
                pv_config.derating_factor * fitted_capacity_kw / dc_capacity_kw
            ),
            "model_energy_mwh": float(
                fitted_model_ac.sum() * interval_hours / 1000.0
            ),
            "mae_kw": float(np.mean(np.abs(fitted_error_kw))),
            "rmse_kw": float(math.sqrt(np.mean(np.square(fitted_error_kw)))),
            "mean_bias_kw": float(np.mean(fitted_error_kw)),
            "correlation": float(np.corrcoef(fitted_model_ac, scada_kw)[0, 1]),
            "model_peak_kw": float(np.max(fitted_model_ac)),
        },
        "source": source_metadata,
        "comparison_boundary": (
            "SCADA sum of 12 inverter Total Active Power channels versus PV-model "
            "output after assumed inverter efficiency and 52.8 MW AC clipping"
        ),
    }

    output_folder.mkdir(parents=True, exist_ok=True)
    resolution_suffix = "" if resolution_minutes == 15 else f"_{resolution_minutes}min"
    csv_path = output_folder / f"pv_scada_comparison_{date}{resolution_suffix}.csv"
    json_path = output_folder / f"pv_scada_comparison_{date}{resolution_suffix}_summary.json"
    comparison.to_csv(csv_path, index=False)
    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return csv_path, json_path, summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare one day of the existing PV model against SCADA."
    )
    parser.add_argument("--date", default="2026-07-15")
    parser.add_argument(
        "--resolution-minutes",
        type=int,
        choices=(1, 5, 10, 15, 30, 60),
        default=15,
    )
    parser.add_argument(
        "--scada-folder",
        type=Path,
        default=Path(r"D:\Insolare\AI Class\Model\Homer\Data\15th July"),
    )
    parser.add_argument(
        "--project-folder", type=Path, default=Path("projects/Wind_Generation")
    )
    parser.add_argument("--dc-capacity-kw", type=float, default=97_200.0)
    parser.add_argument("--ac-capacity-kw", type=float, default=52_800.0)
    parser.add_argument("--inverter-efficiency-pct", type=float, default=95.0)
    parser.add_argument(
        "--derating-factor",
        type=float,
        default=None,
        help="Override the saved PV derating factor without modifying components.json.",
    )
    parser.add_argument(
        "--output-folder",
        type=Path,
        default=Path("projects/Wind_Generation/outputs"),
    )
    args = parser.parse_args()

    csv_path, json_path, summary = compare_day(
        scada_folder=args.scada_folder,
        project_folder=args.project_folder,
        date=args.date,
        resolution_minutes=args.resolution_minutes,
        dc_capacity_kw=args.dc_capacity_kw,
        ac_capacity_kw=args.ac_capacity_kw,
        inverter_efficiency_pct=args.inverter_efficiency_pct,
        derating_factor=args.derating_factor,
        output_folder=args.output_folder,
    )
    print(json.dumps(summary, indent=2))
    print(f"Comparison CSV: {csv_path}")
    print(f"Summary JSON: {json_path}")


if __name__ == "__main__":
    main()
