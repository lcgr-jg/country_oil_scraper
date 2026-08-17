"""Tests for Ukraine SSSU fuel usage and reserves parser."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from reference.loaders import load_product_map
from reference.ukraine import (
    PETROLEUM_PRODUCTS,
    SSSU_DEMAND_METRIC,
    SSSU_STOCKS_METRIC,
    SSSU_UNIT_NATIVE,
    parse_raw_csv,
    parse_wide_csv,
)
from processors.ukraine_sssu_fuel import _sort_and_clean
from scrapers.ukraine_sssu import UkraineSssuScraper

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WIDE_FIXTURE = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "ukraine"
    / "dataset_2026-06-24T09_39_44.110154041Z_DEFAULT_INTEGRATION_SSSU_DF_FUEL_USAGE_AND_RESERVES_M_LATEST.csv"
)


@pytest.fixture(scope="module")
def wide_parsed() -> pd.DataFrame:
    return _sort_and_clean(parse_raw_csv(WIDE_FIXTURE))


def test_product_map_has_sssu_rows():
    pm = load_product_map()
    sssu = pm[pm["Source"] == "SSSU"]
    assert len(sssu) == len(PETROLEUM_PRODUCTS)


def test_wide_fixture_exists():
    assert WIDE_FIXTURE.exists(), f"missing fixture {WIDE_FIXTURE}"


def test_national_petroleum_only(wide_parsed: pd.DataFrame):
    assert set(wide_parsed["product_native"]) == set(PETROLEUM_PRODUCTS)
    assert wide_parsed["country"].eq("UA").all()
    assert wide_parsed["unit"].eq(SSSU_UNIT_NATIVE).all()


def test_demand_gasoline_jan_2021(wide_parsed: pd.DataFrame):
    row = wide_parsed[
        (wide_parsed["metric_type"] == SSSU_DEMAND_METRIC)
        & (wide_parsed["product_native"] == "Motor gasoline")
        & (wide_parsed["date"] == pd.Timestamp("2021-01-01"))
    ]
    assert len(row) == 1
    assert row.iloc[0]["value"] == pytest.approx(24.6)


def test_demand_gasoline_apr_2026(wide_parsed: pd.DataFrame):
    row = wide_parsed[
        (wide_parsed["metric_type"] == SSSU_DEMAND_METRIC)
        & (wide_parsed["product_native"] == "Motor gasoline")
        & (wide_parsed["date"] == pd.Timestamp("2026-04-01"))
    ]
    assert len(row) == 1
    assert row.iloc[0]["value"] == pytest.approx(26.9)


def test_demand_has_war_gap(wide_parsed: pd.DataFrame):
    gas = wide_parsed[
        (wide_parsed["metric_type"] == SSSU_DEMAND_METRIC)
        & (wide_parsed["product_native"] == "Motor gasoline")
    ].set_index("date")["value"]
    assert pd.Timestamp("2021-12-01") in gas.index
    assert pd.Timestamp("2022-02-01") not in gas.index
    assert pd.Timestamp("2024-12-01") not in gas.index
    assert pd.Timestamp("2025-01-01") in gas.index


def test_stocks_stop_early_2022(wide_parsed: pd.DataFrame):
    stk = wide_parsed[wide_parsed["metric_type"] == SSSU_STOCKS_METRIC]
    assert stk["date"].max() == pd.Timestamp("2022-01-01")
    assert stk["date"].min() == pd.Timestamp("2021-01-01")
    diesel_jan22 = stk[
        (stk["product_native"] == "Gas diesel")
        & (stk["date"] == pd.Timestamp("2022-01-01"))
    ]
    assert len(diesel_jan22) == 1
    assert diesel_jan22.iloc[0]["value"] == pytest.approx(565.7)


def test_canonical_columns_present(wide_parsed: pd.DataFrame):
    assert wide_parsed["product_canonical"].notna().all()
    assert wide_parsed["category"].notna().all()
    assert set(wide_parsed["product_canonical"]) == {
        "Gasoline",
        "Diesel",
        "LPG",
        "Fuel Oil",
    }


def test_scraper_parse_all_cached():
    scraper = UkraineSssuScraper(data_dir=PROJECT_ROOT / "data")
    raw = scraper.parse_all_cached()
    df = _sort_and_clean(raw)
    assert len(df) == 168  # 4 products × (29 demand + 13 stock) months with data
    assert set(df["metric_type"]) == {SSSU_DEMAND_METRIC, SSSU_STOCKS_METRIC}


def test_wide_parser_filters_regions():
    partial = parse_wide_csv(WIDE_FIXTURE)
    assert partial["product_native"].isin(PETROLEUM_PRODUCTS).all()
    assert len(partial) > 0
