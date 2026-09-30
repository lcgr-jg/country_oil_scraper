"""
Processor for EC Weekly Oil Bulletin prices and taxes.

Builds tidy parquets under ``data/processed/eu_oil_bulletin/``:
  - eu_oil_bulletin_prices.parquet       (weekly prices + FX + tax wedge)
  - eu_oil_bulletin_taxes.parquet        (VAT / excise / other, effective dates)
  - eu_oil_bulletin_consumption_annual.parquet  (bulletin annual kt; reference only)

Canonical product mapping lives here (not in the scraper) so remaps can be
refreshed without re-downloading.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import pandas as pd

from reference.eu_oil_bulletin import (
    AGENCY_SOURCE,
    CANONICAL_COLUMNS,
    CONSUMPTION_PARQUET_REL,
    MASTER_PARQUET_REL,
    METRIC_PRICE_WITH_TAX,
    METRIC_PRICE_WO_TAX,
    METRIC_TAX_WEDGE,
    TAX_PARQUET_REL,
)
from reference.loaders import load_product_map
from scrapers.eu_oil_bulletin import EUOilBulletinScraper

logger = logging.getLogger(__name__)

_PRODUCT_MAP_SOURCE = AGENCY_SOURCE

COLUMN_ORDER: list[str] = CANONICAL_COLUMNS + [
    "product_code",
    "product_canonical",
    "category",
    "agency",
]

KEY_COLS: list[str] = [
    "date",
    "country",
    "source",
    "metric_type",
    "product_native",
]


def build_from_history(raw_path: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Parse history workbook → (prices_with_wedge, taxes, annual_consumption)."""
    raw_path = Path(raw_path).resolve()
    # Expect .../data/raw/eu_oil_bulletin/*.xlsx → data_dir = .../data
    data_dir = raw_path.parent.parent.parent
    scraper = EUOilBulletinScraper(data_dir=data_dir)
    prices, taxes, consumption = scraper.parse_history(raw_path)
    prices = _enrich(prices)
    prices = _add_tax_wedge(prices)
    taxes = _enrich(taxes)
    consumption = _enrich(consumption)
    prices = _sort_and_clean(prices)
    taxes = _sort_and_clean(taxes)
    consumption = _sort_and_clean(consumption)
    return prices, taxes, consumption


def _enrich(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    # Vectorized map — per-row canonical_* helpers are too slow on ~300k weekly rows.
    pmap = load_product_map()
    src = pmap[pmap["Source"] == _PRODUCT_MAP_SOURCE].copy()
    sub_map = dict(zip(src["Product_name"], src["Sub-category"]))
    cat_map = dict(zip(src["Product_name"], src["Category"]))

    def _clean(v: object) -> object:
        if v is None or (isinstance(v, float) and pd.isna(v)) or v == "-":
            return None
        return v

    out["product_canonical"] = out["product_native"].map(sub_map).map(_clean)
    out["category"] = out["product_native"].map(cat_map).map(_clean)
    return out


def _add_tax_wedge(prices: pd.DataFrame) -> pd.DataFrame:
    """Tax wedge = pump price with taxes − price excluding taxes (same unit)."""
    if prices.empty:
        return prices
    with_tax = prices[prices["metric_type"] == METRIC_PRICE_WITH_TAX]
    wo_tax = prices[prices["metric_type"] == METRIC_PRICE_WO_TAX]
    if with_tax.empty or wo_tax.empty:
        return prices

    keys = ["date", "country", "product_native", "unit"]
    left = with_tax[keys + ["value", "country_name", "country_id", "source",
                            "product", "product_code", "is_provisional",
                            "source_file", "updated_at", "agency",
                            "product_canonical", "category"]].rename(
        columns={"value": "price_with_tax"}
    )
    right = wo_tax[keys + ["value"]].rename(columns={"value": "price_wo_tax"})
    merged = left.merge(right, on=keys, how="inner")
    if merged.empty:
        return prices

    wedge = merged.copy()
    wedge["value"] = wedge["price_with_tax"] - wedge["price_wo_tax"]
    wedge["metric_type"] = METRIC_TAX_WEDGE
    wedge = wedge.drop(columns=["price_with_tax", "price_wo_tax"])
    return pd.concat([prices, wedge], ignore_index=True)


def _sort_and_clean(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"]).dt.normalize()
    for col in COLUMN_ORDER:
        if col not in out.columns:
            out[col] = None
    out = out[COLUMN_ORDER]
    out = out.dropna(subset=["date", "product_native", "value"])
    return out.sort_values(
        ["country", "date", "metric_type", "product_native"]
    ).reset_index(drop=True)


def save(
    prices: pd.DataFrame,
    taxes: pd.DataFrame,
    consumption: pd.DataFrame,
    processed_root: Path,
) -> dict[str, Path]:
    processed_root = Path(processed_root)
    paths: dict[str, Path] = {}

    for rel, frame, label in [
        (MASTER_PARQUET_REL, prices, "prices"),
        (TAX_PARQUET_REL, taxes, "taxes"),
        (CONSUMPTION_PARQUET_REL, consumption, "consumption"),
    ]:
        path = processed_root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(path, index=False)
        paths[label] = path
        logger.info("Saved %s %s (%s rows)", label, path, f"{len(frame):,}")
    return paths


def load_prices(processed_root: Path) -> Optional[pd.DataFrame]:
    path = Path(processed_root) / MASTER_PARQUET_REL
    if not path.exists():
        return None
    return pd.read_parquet(path)


def load_taxes(processed_root: Path) -> Optional[pd.DataFrame]:
    path = Path(processed_root) / TAX_PARQUET_REL
    if not path.exists():
        return None
    return pd.read_parquet(path)


def monthly_average_prices(
    prices: pd.DataFrame,
    *,
    metric_type: str = METRIC_PRICE_WITH_TAX,
    products: Optional[list[str]] = None,
) -> pd.DataFrame:
    """
    Collapse weekly bulletin prices to calendar-month means for joining
    with monthly demand series.
    """
    sl = prices[prices["metric_type"] == metric_type].copy()
    if products is not None:
        sl = sl[sl["product_native"].isin(products)]
    if sl.empty:
        return sl
    sl["month"] = sl["date"].dt.to_period("M").dt.to_timestamp()
    grouped = (
        sl.groupby(
            [
                "month",
                "country",
                "country_name",
                "country_id",
                "product_native",
                "product_canonical",
                "unit",
                "metric_type",
            ],
            dropna=False,
        )["value"]
        .mean()
        .reset_index()
        .rename(columns={"month": "date", "value": "price"})
    )
    return grouped
