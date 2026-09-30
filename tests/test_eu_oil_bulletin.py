"""Smoke tests for EC Oil Bulletin price parsing."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from reference.eu_oil_bulletin import (
    METRIC_PRICE_WITH_TAX,
    METRIC_PRICE_WO_TAX,
    METRIC_TAX_WEDGE,
)
from scrapers.eu_oil_bulletin import EUOilBulletinScraper
import processors.eu_oil_bulletin as processor

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_HISTORY = PROJECT_ROOT / "data" / "raw" / "eu_oil_bulletin"


def _history_path() -> Path:
    paths = sorted(RAW_HISTORY.glob("*History*.xlsx"))
    if not paths:
        paths = sorted(RAW_HISTORY.glob("*.xlsx"))
    if not paths:
        pytest.skip("No Oil Bulletin history workbook under data/raw/eu_oil_bulletin")
    return paths[0]


def test_parse_history_prices_shape():
    scraper = EUOilBulletinScraper(data_dir=PROJECT_ROOT / "data")
    prices, taxes, consumption = scraper.parse_history(_history_path())

    assert not prices.empty
    assert {"date", "country", "metric_type", "product_native", "value", "unit"} <= set(
        prices.columns
    )
    assert METRIC_PRICE_WITH_TAX in set(prices["metric_type"])
    assert METRIC_PRICE_WO_TAX in set(prices["metric_type"])
    assert prices["country"].nunique() >= 20
    # Germany euro95 with-tax should be a positive EUR/1000l series.
    de = prices[
        (prices["country"] == "DE")
        & (prices["metric_type"] == METRIC_PRICE_WITH_TAX)
        & (prices["product_native"] == "Euro-super 95")
    ]
    assert len(de) > 100
    assert (de["value"] > 0).all()
    assert not taxes.empty
    assert not consumption.empty


def test_processor_adds_tax_wedge():
    prices, taxes, consumption = processor.build_from_history(_history_path())
    assert METRIC_TAX_WEDGE in set(prices["metric_type"])
    wedge = prices[prices["metric_type"] == METRIC_TAX_WEDGE]
    # Tax wedge should generally be positive for retail fuels.
    assert wedge["value"].median() > 0
    assert prices["product_canonical"].notna().any()

    monthly = processor.monthly_average_prices(prices)
    assert not monthly.empty
    assert monthly["date"].dt.is_month_start.all()
