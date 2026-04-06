from __future__ import annotations

import copy
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, MutableMapping

from core.components.battery import BatteryComponentConfig
from core.components.converter import ConverterComponentConfig
from core.components.grid import GridComponentConfig
from core.components.pv import PVComponentConfig
from core.components.wind import WindComponentConfig


State = MutableMapping[str, Any]

COMPONENT_NAMES = ["PV", "Wind", "Battery", "Converter", "Grid"]

COMPONENT_TO_PREFIXES = {
    "PV": ["pv_"],
    "Wind": ["wind_"],
    "Battery": ["battery_"],
    "Converter": ["converter_"],
    "Grid": ["grid_"],
}

COMPONENT_TO_UI_PREFIXES = {
    "PV": ["ui_pv_"],
    "Wind": ["ui_wind_"],
    "Battery": ["ui_battery_"],
    "Converter": ["ui_converter_"],
    "Grid": ["ui_grid_"],
}

COMPONENT_TO_JSON_KEY = {
    "PV": "pv",
    "Wind": "wind",
    "Battery": "battery",
    "Converter": "converter",
    "Grid": "grid",
}


def default_components_dict() -> dict:
    return {
        "pv": asdict(PVComponentConfig()),
        "wind": asdict(WindComponentConfig()),
        "battery": asdict(BatteryComponentConfig()),
        "converter": asdict(ConverterComponentConfig()),
        "grid": asdict(GridComponentConfig()),
    }


def deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def components_json_path(folder: Path) -> Path:
    return folder / "components.json"


def load_components_dict(folder: Path) -> dict:
    defaults = default_components_dict()
    path = components_json_path(folder)
    if not path.exists():
        return defaults
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(saved, dict):
            return defaults
        return deep_merge(defaults, saved)
    except Exception:
        return defaults


def save_components_dict(data: dict, folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = components_json_path(folder)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def format_float_list(values: list[float]) -> str:
    return ", ".join(str(v) for v in values)


def format_int_list(values: list[int]) -> str:
    return ", ".join(str(v) for v in values)


def clear_component_widget_keys(state: State, prefixes: list[str] | None = None) -> None:
    if prefixes is None:
        prefixes = ["pv_", "wind_", "battery_", "converter_", "grid_"]
    to_delete = [key for key in list(state.keys()) if any(key.startswith(prefix) for prefix in prefixes)]
    for key in to_delete:
        state.pop(key, None)


def clear_component_ui_keys(state: State, prefixes: list[str] | None = None) -> None:
    if prefixes is None:
        prefixes = ["ui_pv_", "ui_wind_", "ui_battery_", "ui_converter_", "ui_grid_"]
    to_delete = [key for key in list(state.keys()) if any(key.startswith(prefix) for prefix in prefixes)]
    for key in to_delete:
        state.pop(key, None)


def _set_ui(state: State, key: str, value: Any, force: bool = False) -> None:
    ui_key = f"ui_{key}"
    if force or ui_key not in state:
        state[ui_key] = copy.deepcopy(value)


def _read_ui(state: State, key: str) -> Any:
    return state[f"ui_{key}"]


def write_component_to_ui(state: State, selected_component: str, component_data: dict, force: bool = False) -> None:
    if selected_component == "PV":
        pv = component_data
        _set_ui(state, "pv_enabled", pv["enabled"], force)
        _set_ui(state, "pv_use_search_space", pv["use_search_space"], force)
        _set_ui(state, "pv_capacity_kw_options_text", format_float_list(pv["capacity_kw_options"]), force)
        _set_ui(state, "pv_capital_cost_per_kw", pv["capital_cost_per_kw"], force)
        _set_ui(state, "pv_replacement_cost_per_kw", pv["replacement_cost_per_kw"], force)
        _set_ui(state, "pv_om_cost_per_kw_per_year", pv["om_cost_per_kw_per_year"], force)
        _set_ui(state, "pv_lifetime_years", pv["lifetime_years"], force)
        _set_ui(state, "pv_derating_factor", pv["derating_factor"], force)
        _set_ui(state, "pv_bus", pv["bus"], force)

        mppt = pv["mppt"]
        _set_ui(state, "pv_mppt_enabled", mppt["enabled"], force)
        _set_ui(state, "pv_mppt_lifetime_years", mppt["lifetime_years"], force)
        _set_ui(state, "pv_mppt_sizing_mode", mppt["sizing_mode"], force)
        _set_ui(state, "pv_pv_to_conv_ratio_options_text", format_float_list(mppt["pv_to_conv_ratio_options"]), force)
        _set_ui(state, "pv_mppt_capacity_kw_options_text", format_float_list(mppt["capacity_kw_options"]), force)
        _set_ui(state, "pv_mppt_efficiency_pct", mppt["efficiency_pct"], force)
        _set_ui(state, "pv_use_efficiency_table", mppt["use_efficiency_table"], force)

        orientation = pv["orientation"]
        _set_ui(state, "pv_orientation_enabled", orientation["enabled"], force)
        _set_ui(state, "pv_ground_reflectance_pct", orientation["ground_reflectance_pct"], force)
        _set_ui(state, "pv_tracking_system", orientation["tracking_system"], force)
        _set_ui(state, "pv_use_default_slope", orientation["use_default_slope"], force)
        _set_ui(state, "pv_panel_slope_deg", orientation["panel_slope_deg"] if orientation["panel_slope_deg"] is not None else 0.0, force)
        _set_ui(state, "pv_use_default_azimuth", orientation["use_default_azimuth"], force)
        _set_ui(state, "pv_panel_azimuth_deg", orientation["panel_azimuth_deg"] if orientation["panel_azimuth_deg"] is not None else 0.0, force)

        temperature = pv["temperature"]
        _set_ui(state, "pv_temperature_enabled", temperature["enabled"], force)
        _set_ui(state, "pv_temperature_coefficient_pct_per_degC", temperature["temperature_coefficient_pct_per_degC"], force)
        _set_ui(state, "pv_nominal_operating_cell_temp_c", temperature["nominal_operating_cell_temp_c"], force)
        _set_ui(state, "pv_efficiency_stc_pct", temperature["efficiency_stc_pct"], force)
        return

    if selected_component == "Wind":
        wind = component_data
        _set_ui(state, "wind_enabled", wind["enabled"], force)
        _set_ui(state, "wind_use_search_space", wind["use_search_space"], force)
        _set_ui(state, "wind_turbine_model_name", wind["turbine_model_name"], force)
        _set_ui(state, "wind_rated_capacity_kw", wind["rated_capacity_kw"], force)
        _set_ui(state, "wind_quantity_options_text", format_int_list(wind["quantity_options"]), force)
        _set_ui(state, "wind_capital_cost_per_turbine", wind["capital_cost_per_turbine"], force)
        _set_ui(state, "wind_replacement_cost_per_turbine", wind["replacement_cost_per_turbine"], force)
        _set_ui(state, "wind_om_cost_per_turbine_per_year", wind["om_cost_per_turbine_per_year"], force)
        _set_ui(state, "wind_lifetime_years", wind["lifetime_years"], force)
        _set_ui(state, "wind_hub_height_m", wind["hub_height_m"], force)
        _set_ui(state, "wind_consider_temperature_effects", wind["consider_temperature_effects"], force)
        _set_ui(state, "wind_bus", wind["bus"], force)

        power_curve = wind["power_curve"]
        _set_ui(state, "wind_wind_speed_text", format_float_list(power_curve["wind_speed_points_mps"]), force)
        _set_ui(state, "wind_power_output_text", format_float_list(power_curve["power_output_points_kw"]), force)

        losses = wind["losses"]
        _set_ui(state, "wind_availability_losses_pct", losses["availability_losses_pct"], force)
        _set_ui(state, "wind_turbine_performance_losses_pct", losses["turbine_performance_losses_pct"], force)
        _set_ui(state, "wind_environmental_losses_pct", losses["environmental_losses_pct"], force)
        _set_ui(state, "wind_other_losses_pct", losses["other_losses_pct"], force)
        _set_ui(state, "wind_wake_effects_losses_pct", losses["wake_effects_losses_pct"], force)
        _set_ui(state, "wind_electrical_losses_pct", losses["electrical_losses_pct"], force)
        _set_ui(state, "wind_curtailment_losses_pct", losses["curtailment_losses_pct"], force)

        maintenance = wind["maintenance"]
        _set_ui(state, "wind_maintenance_enabled", maintenance["enabled"], force)
        return

    if selected_component == "Battery":
        battery = component_data
        _set_ui(state, "battery_enabled", battery["enabled"], force)
        _set_ui(state, "battery_use_search_space", battery["use_search_space"], force)
        _set_ui(state, "battery_model_name", battery["battery_model_name"], force)
        _set_ui(state, "battery_quantity_options_text", format_int_list(battery["quantity_options"]), force)
        _set_ui(state, "battery_nominal_voltage_v", battery["nominal_voltage_v"], force)
        _set_ui(state, "battery_nominal_capacity_kwh_per_string", battery["nominal_capacity_kwh_per_string"], force)
        _set_ui(state, "battery_roundtrip_efficiency_pct", battery["roundtrip_efficiency_pct"], force)
        _set_ui(state, "battery_max_charge_current_a", battery["max_charge_current_a"], force)
        _set_ui(state, "battery_max_discharge_current_a", battery["max_discharge_current_a"], force)
        _set_ui(state, "battery_string_size", battery["string_size"], force)
        _set_ui(state, "battery_initial_state_of_charge_pct", battery["initial_state_of_charge_pct"], force)
        _set_ui(state, "battery_minimum_state_of_charge_pct", battery["minimum_state_of_charge_pct"], force)
        _set_ui(state, "battery_throughput_kwh", battery["throughput_kwh"], force)
        _set_ui(state, "battery_capital_cost_per_string", battery["capital_cost_per_string"], force)
        _set_ui(state, "battery_replacement_cost_per_string", battery["replacement_cost_per_string"], force)
        _set_ui(state, "battery_om_cost_per_string_per_year", battery["om_cost_per_string_per_year"], force)
        _set_ui(state, "battery_lifetime_years", battery["lifetime_years"], force)
        return

    if selected_component == "Converter":
        converter = component_data
        _set_ui(state, "converter_enabled", converter["enabled"], force)
        _set_ui(state, "converter_use_search_space", converter["use_search_space"], force)
        _set_ui(state, "converter_model_name", converter["converter_model_name"], force)
        _set_ui(state, "converter_capacity_kw_options_text", format_float_list(converter["capacity_kw_options"]), force)
        _set_ui(state, "converter_capital_cost_per_kw", converter["capital_cost_per_kw"], force)
        _set_ui(state, "converter_replacement_cost_per_kw", converter["replacement_cost_per_kw"], force)
        _set_ui(state, "converter_om_cost_per_kw_per_year", converter["om_cost_per_kw_per_year"], force)
        _set_ui(state, "converter_inverter_lifetime_years", converter["inverter_lifetime_years"], force)
        _set_ui(state, "converter_inverter_efficiency_pct", converter["inverter_efficiency_pct"], force)
        _set_ui(state, "converter_rectifier_relative_capacity_pct", converter["rectifier_relative_capacity_pct"], force)
        _set_ui(state, "converter_rectifier_efficiency_pct", converter["rectifier_efficiency_pct"], force)
        _set_ui(state, "converter_parallel_with_ac_generator", converter["parallel_with_ac_generator"], force)
        return

    if selected_component == "Grid":
        grid = component_data
        _set_ui(state, "grid_enabled", grid["enabled"], force)
        _set_ui(state, "grid_power_price_per_kwh", grid["grid_power_price_per_kwh"], force)
        _set_ui(state, "grid_sellback_price_per_kwh", grid["grid_sellback_price_per_kwh"], force)
        _set_ui(state, "grid_sale_capacity_kw", grid["sale_capacity_kw"], force)
        _set_ui(state, "grid_purchase_capacity_kw", grid["purchase_capacity_kw"], force)
        _set_ui(state, "grid_net_metering_enabled", grid["net_metering_enabled"], force)
        _set_ui(state, "grid_co2_emissions_g_per_kwh", grid["co2_emissions_g_per_kwh"], force)
        return

    raise KeyError(f"Unknown component: {selected_component}")


def prepare_component_ui_state(state: State, selected_component: str, force: bool = False) -> None:
    if "_components_draft" not in state:
        return
    json_key = COMPONENT_TO_JSON_KEY[selected_component]
    write_component_to_ui(state, selected_component, state["_components_draft"][json_key], force=force)


def initialize_component_session(state: State, folder: Path) -> None:
    folder_key = str(folder)
    if state.get("_components_loaded_for_folder") != folder_key or "_components_draft" not in state:
        clear_component_widget_keys(state)
        clear_component_ui_keys(state)
        state["_components_draft"] = load_components_dict(folder)
        state["_components_loaded_for_folder"] = folder_key
        state["_last_rendered_component"] = None


def parse_int_list(text: str) -> list[int]:
    values: list[int] = []
    for item in str(text).split(","):
        cleaned = item.strip()
        if cleaned:
            values.append(int(float(cleaned)))
    return values


def parse_float_list(text: str) -> list[float]:
    values: list[float] = []
    for item in str(text).split(","):
        cleaned = item.strip()
        if cleaned:
            values.append(float(cleaned))
    return values


def build_pv_from_state(state: State) -> dict:
    return {
        "enabled": bool(_read_ui(state, "pv_enabled")),
        "use_search_space": bool(_read_ui(state, "pv_use_search_space")),
        "capacity_kw_options": parse_float_list(_read_ui(state, "pv_capacity_kw_options_text")),
        "capital_cost_per_kw": float(_read_ui(state, "pv_capital_cost_per_kw")),
        "replacement_cost_per_kw": float(_read_ui(state, "pv_replacement_cost_per_kw")),
        "om_cost_per_kw_per_year": float(_read_ui(state, "pv_om_cost_per_kw_per_year")),
        "lifetime_years": int(_read_ui(state, "pv_lifetime_years")),
        "derating_factor": float(_read_ui(state, "pv_derating_factor")),
        "bus": str(_read_ui(state, "pv_bus")),
        "mppt": {
            "enabled": bool(_read_ui(state, "pv_mppt_enabled")),
            "lifetime_years": int(_read_ui(state, "pv_mppt_lifetime_years")),
            "sizing_mode": str(_read_ui(state, "pv_mppt_sizing_mode")),
            "pv_to_conv_ratio_options": parse_float_list(_read_ui(state, "pv_pv_to_conv_ratio_options_text")),
            "capacity_kw_options": parse_float_list(_read_ui(state, "pv_mppt_capacity_kw_options_text")),
            "efficiency_pct": float(_read_ui(state, "pv_mppt_efficiency_pct")),
            "use_efficiency_table": bool(_read_ui(state, "pv_use_efficiency_table")),
        },
        "orientation": {
            "enabled": bool(_read_ui(state, "pv_orientation_enabled")),
            "ground_reflectance_pct": float(_read_ui(state, "pv_ground_reflectance_pct")),
            "tracking_system": str(_read_ui(state, "pv_tracking_system")),
            "use_default_slope": bool(_read_ui(state, "pv_use_default_slope")),
            "panel_slope_deg": None if bool(_read_ui(state, "pv_use_default_slope")) else float(_read_ui(state, "pv_panel_slope_deg")),
            "use_default_azimuth": bool(_read_ui(state, "pv_use_default_azimuth")),
            "panel_azimuth_deg": None if bool(_read_ui(state, "pv_use_default_azimuth")) else float(_read_ui(state, "pv_panel_azimuth_deg")),
        },
        "temperature": {
            "enabled": bool(_read_ui(state, "pv_temperature_enabled")),
            "temperature_coefficient_pct_per_degC": float(_read_ui(state, "pv_temperature_coefficient_pct_per_degC")),
            "nominal_operating_cell_temp_c": float(_read_ui(state, "pv_nominal_operating_cell_temp_c")),
            "efficiency_stc_pct": float(_read_ui(state, "pv_efficiency_stc_pct")),
        },
    }


def build_wind_from_state(state: State) -> dict:
    return {
        "enabled": bool(_read_ui(state, "wind_enabled")),
        "use_search_space": bool(_read_ui(state, "wind_use_search_space")),
        "turbine_model_name": str(_read_ui(state, "wind_turbine_model_name")),
        "rated_capacity_kw": float(_read_ui(state, "wind_rated_capacity_kw")),
        "quantity_options": parse_int_list(_read_ui(state, "wind_quantity_options_text")),
        "capital_cost_per_turbine": float(_read_ui(state, "wind_capital_cost_per_turbine")),
        "replacement_cost_per_turbine": float(_read_ui(state, "wind_replacement_cost_per_turbine")),
        "om_cost_per_turbine_per_year": float(_read_ui(state, "wind_om_cost_per_turbine_per_year")),
        "lifetime_years": int(_read_ui(state, "wind_lifetime_years")),
        "hub_height_m": float(_read_ui(state, "wind_hub_height_m")),
        "consider_temperature_effects": bool(_read_ui(state, "wind_consider_temperature_effects")),
        "bus": str(_read_ui(state, "wind_bus")),
        "power_curve": {
            "enabled": True,
            "wind_speed_points_mps": parse_float_list(_read_ui(state, "wind_wind_speed_text")),
            "power_output_points_kw": parse_float_list(_read_ui(state, "wind_power_output_text")),
        },
        "losses": {
            "enabled": True,
            "availability_losses_pct": float(_read_ui(state, "wind_availability_losses_pct")),
            "turbine_performance_losses_pct": float(_read_ui(state, "wind_turbine_performance_losses_pct")),
            "environmental_losses_pct": float(_read_ui(state, "wind_environmental_losses_pct")),
            "other_losses_pct": float(_read_ui(state, "wind_other_losses_pct")),
            "wake_effects_losses_pct": float(_read_ui(state, "wind_wake_effects_losses_pct")),
            "electrical_losses_pct": float(_read_ui(state, "wind_electrical_losses_pct")),
            "curtailment_losses_pct": float(_read_ui(state, "wind_curtailment_losses_pct")),
        },
        "maintenance": {
            "enabled": bool(_read_ui(state, "wind_maintenance_enabled")),
        },
    }


def build_battery_from_state(state: State) -> dict:
    return {
        "enabled": bool(_read_ui(state, "battery_enabled")),
        "use_search_space": bool(_read_ui(state, "battery_use_search_space")),
        "battery_model_name": str(_read_ui(state, "battery_model_name")),
        "quantity_options": parse_int_list(_read_ui(state, "battery_quantity_options_text")),
        "nominal_voltage_v": float(_read_ui(state, "battery_nominal_voltage_v")),
        "nominal_capacity_kwh_per_string": float(_read_ui(state, "battery_nominal_capacity_kwh_per_string")),
        "roundtrip_efficiency_pct": float(_read_ui(state, "battery_roundtrip_efficiency_pct")),
        "max_charge_current_a": float(_read_ui(state, "battery_max_charge_current_a")),
        "max_discharge_current_a": float(_read_ui(state, "battery_max_discharge_current_a")),
        "string_size": int(_read_ui(state, "battery_string_size")),
        "initial_state_of_charge_pct": float(_read_ui(state, "battery_initial_state_of_charge_pct")),
        "minimum_state_of_charge_pct": float(_read_ui(state, "battery_minimum_state_of_charge_pct")),
        "throughput_kwh": float(_read_ui(state, "battery_throughput_kwh")),
        "capital_cost_per_string": float(_read_ui(state, "battery_capital_cost_per_string")),
        "replacement_cost_per_string": float(_read_ui(state, "battery_replacement_cost_per_string")),
        "om_cost_per_string_per_year": float(_read_ui(state, "battery_om_cost_per_string_per_year")),
        "lifetime_years": int(_read_ui(state, "battery_lifetime_years")),
    }


def build_converter_from_state(state: State) -> dict:
    return {
        "enabled": bool(_read_ui(state, "converter_enabled")),
        "use_search_space": bool(_read_ui(state, "converter_use_search_space")),
        "converter_model_name": str(_read_ui(state, "converter_model_name")),
        "capacity_kw_options": parse_float_list(_read_ui(state, "converter_capacity_kw_options_text")),
        "capital_cost_per_kw": float(_read_ui(state, "converter_capital_cost_per_kw")),
        "replacement_cost_per_kw": float(_read_ui(state, "converter_replacement_cost_per_kw")),
        "om_cost_per_kw_per_year": float(_read_ui(state, "converter_om_cost_per_kw_per_year")),
        "inverter_lifetime_years": int(_read_ui(state, "converter_inverter_lifetime_years")),
        "inverter_efficiency_pct": float(_read_ui(state, "converter_inverter_efficiency_pct")),
        "rectifier_relative_capacity_pct": float(_read_ui(state, "converter_rectifier_relative_capacity_pct")),
        "rectifier_efficiency_pct": float(_read_ui(state, "converter_rectifier_efficiency_pct")),
        "parallel_with_ac_generator": bool(_read_ui(state, "converter_parallel_with_ac_generator")),
    }


def build_grid_from_state(state: State) -> dict:
    return {
        "enabled": bool(_read_ui(state, "grid_enabled")),
        "grid_power_price_per_kwh": float(_read_ui(state, "grid_power_price_per_kwh")),
        "grid_sellback_price_per_kwh": float(_read_ui(state, "grid_sellback_price_per_kwh")),
        "sale_capacity_kw": float(_read_ui(state, "grid_sale_capacity_kw")),
        "purchase_capacity_kw": float(_read_ui(state, "grid_purchase_capacity_kw")),
        "net_metering_enabled": bool(_read_ui(state, "grid_net_metering_enabled")),
        "co2_emissions_g_per_kwh": float(_read_ui(state, "grid_co2_emissions_g_per_kwh")),
    }


def build_component_from_state(state: State, selected_component: str) -> dict:
    if selected_component == "PV":
        return build_pv_from_state(state)
    if selected_component == "Wind":
        return build_wind_from_state(state)
    if selected_component == "Battery":
        return build_battery_from_state(state)
    if selected_component == "Converter":
        return build_converter_from_state(state)
    if selected_component == "Grid":
        return build_grid_from_state(state)
    raise KeyError(f"Unknown component: {selected_component}")


def sync_selected_component_to_draft(state: State, selected_component: str) -> tuple[bool, str | None]:
    if "_components_draft" not in state:
        return False, "Missing _components_draft in session state."
    try:
        json_key = COMPONENT_TO_JSON_KEY[selected_component]
        built = build_component_from_state(state, selected_component)
        state["_components_draft"][json_key] = built
        state.pop("_components_sync_note", None)
        return True, None
    except Exception as exc:
        state["_components_sync_note"] = (
            f"{selected_component} draft sync skipped. Using last valid values. Details: {exc}"
        )
        return False, str(exc)


def sync_last_rendered_component_before_switch(state: State) -> tuple[bool, str | None]:
    previous_component = state.get("_last_rendered_component")
    if previous_component not in COMPONENT_TO_JSON_KEY:
        return False, None
    return sync_selected_component_to_draft(state, previous_component)


def save_current_component(folder: Path, state: State, selected_component: str) -> Path:
    sync_selected_component_to_draft(state, selected_component)
    saved_on_disk = load_components_dict(folder)
    json_key = COMPONENT_TO_JSON_KEY[selected_component]
    saved_on_disk[json_key] = copy.deepcopy(state["_components_draft"][json_key])
    path = save_components_dict(saved_on_disk, folder)
    state["_components_draft"][json_key] = copy.deepcopy(saved_on_disk[json_key])
    return path


def reload_saved_current_component(state: State, folder: Path, selected_component: str) -> None:
    saved_on_disk = load_components_dict(folder)
    json_key = COMPONENT_TO_JSON_KEY[selected_component]
    state["_components_draft"][json_key] = copy.deepcopy(saved_on_disk[json_key])
    clear_component_ui_keys(state, COMPONENT_TO_UI_PREFIXES[selected_component])
    prepare_component_ui_state(state, selected_component, force=True)


def load_default_current_component(state: State, selected_component: str) -> None:
    defaults = default_components_dict()
    json_key = COMPONENT_TO_JSON_KEY[selected_component]
    state["_components_draft"][json_key] = copy.deepcopy(defaults[json_key])
    clear_component_ui_keys(state, COMPONENT_TO_UI_PREFIXES[selected_component])
    prepare_component_ui_state(state, selected_component, force=True)
