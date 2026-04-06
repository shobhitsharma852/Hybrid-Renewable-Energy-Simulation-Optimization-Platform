from __future__ import annotations

from dashboard.ui.components_state import (
    COMPONENT_TO_JSON_KEY,
    default_components_dict,
    initialize_component_session,
    load_components_dict,
    load_default_current_component,
    prepare_component_ui_state,
    reload_saved_current_component,
    save_components_dict,
    save_current_component,
    sync_last_rendered_component_before_switch,
    sync_selected_component_to_draft,
)


def test_initial_project_load_populates_ui_from_saved_components_json(tmp_path):
    folder = tmp_path / "project_a"
    folder.mkdir()
    data = default_components_dict()
    data["pv"]["enabled"] = False
    data["pv"]["capacity_kw_options"] = [100.0, 200.0]
    save_components_dict(data, folder)

    state: dict = {}
    initialize_component_session(state, folder)
    prepare_component_ui_state(state, "PV")

    assert state["ui_pv_enabled"] is False
    assert state["ui_pv_capacity_kw_options_text"] == "100.0, 200.0"


def test_switch_sync_persists_previous_component_edits(tmp_path):
    folder = tmp_path / "project_b"
    folder.mkdir()
    save_components_dict(default_components_dict(), folder)

    state: dict = {"components_selected_component": "Wind"}
    initialize_component_session(state, folder)
    state["_last_rendered_component"] = "Battery"
    prepare_component_ui_state(state, "Battery")

    state["ui_battery_model_name"] = "My Battery"
    state["ui_battery_lifetime_years"] = 22
    state["ui_battery_quantity_options_text"] = "0, 3, 6"

    ok, err = sync_last_rendered_component_before_switch(state)

    assert ok is True
    assert err is None
    assert state["_components_draft"]["battery"]["battery_model_name"] == "My Battery"
    assert state["_components_draft"]["battery"]["lifetime_years"] == 22
    assert state["_components_draft"]["battery"]["quantity_options"] == [0, 3, 6]


def test_save_current_component_uses_live_ui_state_not_stale_draft(tmp_path):
    folder = tmp_path / "project_c"
    folder.mkdir()
    save_components_dict(default_components_dict(), folder)

    state: dict = {}
    initialize_component_session(state, folder)
    prepare_component_ui_state(state, "Converter")

    state["ui_converter_model_name"] = "Live Converter"
    state["ui_converter_inverter_lifetime_years"] = 30
    state["ui_converter_capacity_kw_options_text"] = "0, 250, 500"

    state["_components_draft"]["converter"]["converter_model_name"] = "Old Converter"
    state["_components_draft"]["converter"]["inverter_lifetime_years"] = 15
    state["_components_draft"]["converter"]["capacity_kw_options"] = [0.0, 1000.0]

    save_current_component(folder, state, "Converter")
    saved = load_components_dict(folder)

    assert saved["converter"]["converter_model_name"] == "Live Converter"
    assert saved["converter"]["inverter_lifetime_years"] == 30
    assert saved["converter"]["capacity_kw_options"] == [0.0, 250.0, 500.0]


def test_reload_saved_current_component_overwrites_ui_values(tmp_path):
    folder = tmp_path / "project_d"
    folder.mkdir()
    data = default_components_dict()
    data["battery"]["enabled"] = False
    data["battery"]["roundtrip_efficiency_pct"] = 80.0
    save_components_dict(data, folder)

    state: dict = {}
    initialize_component_session(state, folder)
    prepare_component_ui_state(state, "Battery")
    state["ui_battery_enabled"] = True
    state["ui_battery_roundtrip_efficiency_pct"] = 95.0

    reload_saved_current_component(state, folder, "Battery")

    assert state["ui_battery_enabled"] is False
    assert state["ui_battery_roundtrip_efficiency_pct"] == 80.0


def test_load_default_current_component_overwrites_ui_values(tmp_path):
    folder = tmp_path / "project_e"
    folder.mkdir()
    data = default_components_dict()
    data["grid"]["enabled"] = False
    data["grid"]["grid_power_price_per_kwh"] = 0.44
    save_components_dict(data, folder)

    state: dict = {}
    initialize_component_session(state, folder)
    prepare_component_ui_state(state, "Grid")
    state["ui_grid_enabled"] = False
    state["ui_grid_power_price_per_kwh"] = 0.44

    load_default_current_component(state, "Grid")
    defaults = default_components_dict()

    assert state["ui_grid_enabled"] == defaults["grid"]["enabled"]
    assert state["ui_grid_power_price_per_kwh"] == defaults["grid"]["grid_power_price_per_kwh"]


def test_wind_sync_uses_new_loss_keys():
    state: dict = {"_components_draft": default_components_dict()}
    state.update(
        {
            "ui_wind_enabled": True,
            "ui_wind_use_search_space": True,
            "ui_wind_turbine_model_name": "Generic 1.5 MW",
            "ui_wind_rated_capacity_kw": 1500.0,
            "ui_wind_quantity_options_text": "0, 1, 2",
            "ui_wind_capital_cost_per_turbine": 3000000.0,
            "ui_wind_replacement_cost_per_turbine": 3000000.0,
            "ui_wind_om_cost_per_turbine_per_year": 30000.0,
            "ui_wind_lifetime_years": 20,
            "ui_wind_hub_height_m": 80.0,
            "ui_wind_consider_temperature_effects": False,
            "ui_wind_bus": "AC",
            "ui_wind_wind_speed_text": "0, 4, 5",
            "ui_wind_power_output_text": "0, 0, 150",
            "ui_wind_availability_losses_pct": 1.0,
            "ui_wind_turbine_performance_losses_pct": 2.0,
            "ui_wind_environmental_losses_pct": 3.0,
            "ui_wind_other_losses_pct": 4.0,
            "ui_wind_wake_effects_losses_pct": 5.0,
            "ui_wind_electrical_losses_pct": 6.0,
            "ui_wind_curtailment_losses_pct": 7.0,
            "ui_wind_maintenance_enabled": True,
        }
    )

    ok, err = sync_selected_component_to_draft(state, "Wind")

    assert ok is True
    assert err is None
    losses = state["_components_draft"]["wind"]["losses"]
    assert losses["turbine_performance_losses_pct"] == 2.0
    assert losses["wake_effects_losses_pct"] == 5.0


def test_each_component_name_maps_to_json_key():
    assert COMPONENT_TO_JSON_KEY == {
        "PV": "pv",
        "Wind": "wind",
        "Battery": "battery",
        "Converter": "converter",
        "Grid": "grid",
    }
