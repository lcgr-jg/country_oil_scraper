"""Tests for Thailand EPPO Table 2.3-4 current-workbook parsing."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scrapers.thailand_eppo import (  # noqa: E402
    discover_current_column_layout,
    parse_current_eppo,
)

CURRENT_PATH = ROOT / "data" / "raw" / "thailand" / "T02_03_04.xls"


def _current_workbook() -> Path:
    if CURRENT_PATH.exists():
        return CURRENT_PATH
    pytest.skip("No Thailand T02_03_04.xls in data/raw/thailand/")


class TestCurrentWorkbookLayout:
    def test_discovers_monthly_columns_from_headers(self) -> None:
        raw = pd.read_excel(_current_workbook(), sheet_name="tab55", header=None)
        monthly_specs, q1_specs, data_start_row = discover_current_column_layout(raw)

        assert data_start_row == 5
        assert (18, 2026, 4) in monthly_specs
        assert monthly_specs[-1][1:] == (2026, 4)
        assert (5, 2025) in q1_specs

    def test_parses_through_latest_month(self) -> None:
        df = parse_current_eppo(_current_workbook())
        assert df["date"].max() >= pd.Timestamp("2026-04-01")
        assert len(df) == 120

    def test_march_and_april_values_are_distinct(self) -> None:
        df = parse_current_eppo(_current_workbook())
        ker = df[df["product_native"] == "KEROSENE"].set_index("date")["value"]
        assert ker[pd.Timestamp("2026-03-01")] != ker[pd.Timestamp("2026-04-01")]
