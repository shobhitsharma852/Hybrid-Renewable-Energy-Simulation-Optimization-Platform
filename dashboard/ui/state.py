from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import streamlit as st

PROJECTS_DIR = Path("projects")

@dataclass
class UiState:
    project_name: str = ""
    project_folder: str = ""  # str for Streamlit state safety

def get_state() -> UiState:
    if "ui_state" not in st.session_state:
        st.session_state["ui_state"] = UiState()
    return st.session_state["ui_state"]

def set_active_project(name: str) -> Path:
    name = name.strip()
    clean = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in name)
    folder = PROJECTS_DIR / clean
    folder.mkdir(parents=True, exist_ok=True)
    ui = get_state()
    ui.project_name = name
    ui.project_folder = str(folder)
    return folder

def active_project_folder() -> Path | None:
    ui = get_state()
    if not ui.project_folder:
        return None
    return Path(ui.project_folder)