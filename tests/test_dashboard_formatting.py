import pytest

from dashboard.ui.formatting import format_number, parse_formatted_number


def test_format_number_uses_western_grouping():
    assert format_number(3_000_000.0) == "3,000,000.00"
    assert format_number(100_000, decimals=0) == "100,000"


def test_parse_formatted_number_accepts_commas_and_currency_symbols():
    assert parse_formatted_number("3,000,000.00") == pytest.approx(3_000_000.0)
    assert parse_formatted_number("₹ 100,000") == pytest.approx(100_000.0)
    assert parse_formatted_number("$1,234.56") == pytest.approx(1_234.56)
