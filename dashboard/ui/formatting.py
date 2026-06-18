from __future__ import annotations

import math
import re
from typing import Any

import streamlit as st


_NUMBER_CLEAN_RE = re.compile(r"[,\s₹$]")


def format_number(value: float | int, decimals: int = 2) -> str:
    numeric = float(value)
    if not math.isfinite(numeric):
        numeric = 0.0
    if decimals <= 0:
        return f"{int(round(numeric)):,}"
    return f"{numeric:,.{decimals}f}"


def parse_formatted_number(text: str) -> float:
    cleaned = _NUMBER_CLEAN_RE.sub("", str(text)).strip()
    if cleaned == "":
        raise ValueError("Enter a numeric value")
    return float(cleaned)


def _sync_formatted_number(
    *,
    text_key: str,
    value_key: str,
    error_key: str,
    min_value: float | int | None,
    max_value: float | int | None,
    decimals: int,
    as_int: bool,
) -> None:
    try:
        parsed = parse_formatted_number(st.session_state.get(text_key, ""))
        if min_value is not None and parsed < float(min_value):
            raise ValueError(f"Value must be at least {format_number(min_value, decimals)}")
        if max_value is not None and parsed > float(max_value):
            raise ValueError(f"Value must be at most {format_number(max_value, decimals)}")

        value: Any = int(round(parsed)) if as_int else float(parsed)
        st.session_state[value_key] = value
        st.session_state[text_key] = format_number(value, decimals)
        st.session_state.pop(error_key, None)
    except Exception as exc:
        st.session_state[error_key] = str(exc)


def formatted_number_input(
    label: str,
    *,
    key: str,
    value: float | int,
    min_value: float | int | None = None,
    max_value: float | int | None = None,
    decimals: int = 2,
    as_int: bool = False,
    help: str | None = None,
    disabled: bool = False,
) -> float | int:
    if key not in st.session_state:
        st.session_state[key] = int(value) if as_int else float(value)

    text_key = f"{key}__formatted"
    error_key = f"{key}__format_error"
    if text_key not in st.session_state:
        st.session_state[text_key] = format_number(st.session_state[key], decimals)

    st.text_input(
        label,
        key=text_key,
        help=help,
        disabled=disabled,
        on_change=_sync_formatted_number,
        kwargs={
            "text_key": text_key,
            "value_key": key,
            "error_key": error_key,
            "min_value": min_value,
            "max_value": max_value,
            "decimals": decimals,
            "as_int": as_int,
        },
    )

    if error_key in st.session_state:
        st.error(st.session_state[error_key])

    return st.session_state[key]
