"""Tests for Hungary MEKH OData demand + stocks parsers."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from reference.hungary import (
    CLOSING_STOCK_FLOW,
    MEKH_METRIC_TYPE,
    MEKH_STOCKS_METRIC,
    MEKH_UNIT_NATIVE,
    STORED_NATIVES,
    fetch_closing_stock_rows,
    fetch_gid_observed_rows,
    parse_demand_odata_records,
    parse_stocks_odata_records,
)
from reference.loaders import load_product_map
from scrapers.hungary_mekh import HungaryMekhScraper

PROJECT_ROOT = Path(__file__).resolve().parents[1]
XLSX_FIXTURE = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "hungary"
    / "HaviOlajMerleg_2026-06-23.xlsx"
)

XLSX_JAN_2026 = {
    "LPG": 24.6,
    "Naphtha": 62.1,
    "Total motor gasoline": 105.5,
    "Kerosene type jet fuel": 40.2,
    "Total gas/diesel oil": 259.3,
    "Petroleum coke": 4.5,
    "Other products": 39.5,
}

JODI_STOCKS_JAN_2026 = {
    "Total motor gasoline": 607.0,
    "Total gas/diesel oil": 943.0,
    "Kerosene type jet fuel": 58.0,
    "LPG": 34.0,
    "Naphtha": 118.0,
    "Fuel oil": 35.0,
}


@pytest.fixture(scope="module")
def demand_records() -> list[dict]:
    return fetch_gid_observed_rows()


@pytest.fixture(scope="module")
def stock_records() -> list[dict]:
    return fetch_closing_stock_rows()


@pytest.fixture(scope="module")
def demand_parsed(demand_records: list[dict]) -> pd.DataFrame:
    return parse_demand_odata_records(demand_records)


@pytest.fixture(scope="module")
def stocks_parsed(stock_records: list[dict]) -> pd.DataFrame:
    return parse_stocks_odata_records(stock_records)


def test_product_map_has_mekh_rows():
    pm = load_product_map()
    mekh = pm[pm["Source"] == "MEKH"]
    assert len(mekh) >= len(STORED_NATIVES)


def test_demand_history_starts_2008(demand_parsed: pd.DataFrame):
    assert demand_parsed["date"].min() == pd.Timestamp("2008-01-01")
    assert demand_parsed["date"].max() >= pd.Timestamp("2026-03-01")


def test_stocks_history_starts_2013(stocks_parsed: pd.DataFrame):
    assert stocks_parsed["date"].min() == pd.Timestamp("2013-01-01")
    assert stocks_parsed["date"].max() >= pd.Timestamp("2026-03-01")


def test_stock_records_use_csnatter(stock_records: list[dict]):
    flows = {r["dimension_1"] for r in stock_records}
    assert flows == {CLOSING_STOCK_FLOW}


def test_jan_2026_demand_matches_xlsx(demand_parsed: pd.DataFrame):
    jan = demand_parsed[demand_parsed["date"] == pd.Timestamp("2026-01-01")].set_index(
        "product_native"
    )["value"]
    for product, expected in XLSX_JAN_2026.items():
        assert product in jan.index, f"missing {product}"
        assert jan[product] == pytest.approx(expected, rel=0, abs=0.05)


def test_jan_2026_stocks_near_jodi(stocks_parsed: pd.DataFrame):
    jan = stocks_parsed[stocks_parsed["date"] == pd.Timestamp("2026-01-01")].set_index(
        "product_native"
    )["value"]
    for product, expected in JODI_STOCKS_JAN_2026.items():
        assert product in jan.index, f"missing {product}"
        assert jan[product] == pytest.approx(expected, rel=0, abs=1.0)
    # JODI ONONSPEC = petcoke + others
    ononspec = jan.get("Petroleum coke", 0) + jan.get("Other products", 0)
    assert ononspec == pytest.approx(64.0, abs=1.0)


def test_bio_splits_not_stored_as_natives(demand_parsed: pd.DataFrame):
    jan = set(
        demand_parsed.loc[
            demand_parsed["date"] == pd.Timestamp("2026-01-01"), "product_native"
        ]
    )
    assert all(p in STORED_NATIVES for p in jan)


def test_scraper_finalize(demand_records: list[dict], stock_records: list[dict]):
    scraper = HungaryMekhScraper(data_dir=PROJECT_ROOT / "data")
    demand = scraper.parse_demand_records(demand_records)
    stocks = scraper.parse_stocks_records(stock_records)
    assert demand["unit"].eq(MEKH_UNIT_NATIVE).all()
    assert stocks["unit"].eq(MEKH_UNIT_NATIVE).all()
    assert demand["metric_type"].eq(MEKH_METRIC_TYPE).all()
    assert stocks["metric_type"].eq(MEKH_STOCKS_METRIC).all()
    assert demand["country"].eq("HU").all()


@pytest.mark.skipif(not XLSX_FIXTURE.exists(), reason="missing xlsx fixture")
def test_xlsx_fixture_still_present():
    assert XLSX_FIXTURE.stat().st_size > 1000
