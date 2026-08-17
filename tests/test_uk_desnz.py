"""Tests for UK DESNZ Energy Trends ODS parser."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pandas as pd
import pytest

from reference.loaders import load_product_map
from reference.uk import (
    CONSUMPTION_PRODUCTS,
    DERIVED_OTHERS_NATIVE,
    RECORD_STOCKS,
    STOCK_PRODUCTS,
    TOTAL_NATIVE,
    UK_CONSUMPTION_METRIC,
    UK_STOCKS_METRIC,
    UK_UNIT_NATIVE,
    append_derived_others,
    is_uk_stored,
    parse_consumption_sheet,
    parse_energy_trends_workbook,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_ODS = PROJECT_ROOT / "data" / "raw" / "uk" / "Oil___Oil_Products_MAY_26.ods"


@pytest.fixture(scope="module")
def raw_path() -> Path:
    if RAW_ODS.exists():
        return RAW_ODS
    pytest.skip(f"Missing fixture: {RAW_ODS}")


@pytest.fixture(scope="module")
def readable_path(raw_path: Path) -> Path:
    if os.access(raw_path, os.R_OK):
        return raw_path
    tmp = Path(os.environ["TEMP"]) / "uk_energy_trends_may26.ods"
    shutil.copy2(raw_path, tmp)
    return tmp


@pytest.fixture(scope="module")
def consumption(readable_path: Path) -> pd.DataFrame:
    return parse_consumption_sheet(readable_path)


@pytest.fixture(scope="module")
def workbook(readable_path: Path) -> pd.DataFrame:
    return parse_energy_trends_workbook(readable_path)


def test_product_map_has_desnz_rows():
    pm = load_product_map()
    desnz = pm[pm["Source"] == "DESNZ"]
    assert len(desnz) >= 15


def test_consumption_products_present(consumption: pd.DataFrame):
    natives = set(consumption["product_native"])
    for product in CONSUMPTION_PRODUCTS:
        assert product in natives
    assert TOTAL_NATIVE in natives


def test_derived_others_reconciles_to_total(consumption: pd.DataFrame):
    with_derived = append_derived_others(consumption)
    date = pd.Timestamp("2025-10-01")
    total = consumption.loc[
        (consumption["date"] == date) & (consumption["product_native"] == TOTAL_NATIVE),
        "value",
    ].iloc[0]
    parts = with_derived.loc[with_derived["date"] == date, "value"].sum()
    assert total == pytest.approx(parts, rel=0, abs=0.01)


def test_workbook_row_counts(workbook: pd.DataFrame):
    assert len(workbook) > 5000
    assert workbook["product_native"].nunique() == 14


def test_workbook_date_ranges(workbook: pd.DataFrame, consumption: pd.DataFrame):
    assert consumption["date"].min() == pd.Timestamp("1998-01-01")
    stocks = workbook[workbook["_record_kind"] == RECORD_STOCKS]
    assert stocks["date"].min() == pd.Timestamp("1995-01-01")


def test_scraper_overlapping_names_get_both_metrics(readable_path: Path):
    """Petrol/Jet fuel/etc. must appear under TOTDEMO and CLOSTLV."""
    from scrapers.uk_desnz import UkDesnzScraper

    df = UkDesnzScraper(data_dir=PROJECT_ROOT / "data").parse(
        "energy_trends", readable_path
    )
    demand = df[df["metric_type"] == UK_CONSUMPTION_METRIC]
    stocks = df[df["metric_type"] == UK_STOCKS_METRIC]
    for native in ("Petrol", "Jet fuel", "Burning oil", "Gas oil"):
        assert native in set(demand["product_native"]), native
        assert native in set(stocks["product_native"]), native
    assert demand["product_native"].nunique() == len(
        {DERIVED_OTHERS_NATIVE, *CONSUMPTION_PRODUCTS}
    )


def test_scraper_finalize(readable_path: Path):
    from scrapers.uk_desnz import UkDesnzScraper

    df = UkDesnzScraper(data_dir=PROJECT_ROOT / "data").parse(
        "energy_trends", readable_path
    )
    assert df["unit"].eq(UK_UNIT_NATIVE).all()
    assert df["country"].eq("GB").all()
    assert set(df["metric_type"]) == {UK_CONSUMPTION_METRIC, UK_STOCKS_METRIC}
    assert all(is_uk_stored(n) for n in df["product_native"])
    assert TOTAL_NATIVE not in set(df["product_native"])
    assert DERIVED_OTHERS_NATIVE in set(df["product_native"])


def test_processor_bootstrap(readable_path: Path, tmp_path: Path):
    from processors.uk_energy_trends import build_from_historical, load

    df = build_from_historical(readable_path)
    assert df["product_canonical"].notna().all()
    assert df["category"].notna().all()
    assert (df["product_native"] == DERIVED_OTHERS_NATIVE).any()

    from processors.uk_energy_trends import save

    save(df, tmp_path)
    loaded = load(tmp_path)
    assert loaded is not None
    assert len(loaded) == len(df)
