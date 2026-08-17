"""
reference.eppo
──────────────
Thailand EPPO (Table 2.3-4) product-label helpers.

The historical and current Excel files use different spellings and hierarchy
depth. ``product_map.csv`` defines the unified primary set; this module
normalizes raw labels to those ``Product_name`` keys and flags which rows
belong in the stitched monthly database.

Used by notebooks, ``scrapers/thailand_eppo.py``, and
``processors/thailand_eppo_sales.py``.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from reference.jodi_compare import (
    build_kind_rollup_jodi_compare,
    panel_order_from_specs,
    sum_natives_series_for_jodi,
)
from reference.loaders import is_primary, load_product_map
from reference.dashboard_helpers import (
    DEFAULT_SEASONALITY_PANELS_CANONICAL,
    default_seasonality_chart_inputs,
)

# Agency key in product_map.csv (not the dataset key in metric_types.yaml).
EPPO_AGENCY_SOURCE = "EPPO"

# Dataset key in metric_types.yaml source_mappings.
EPPO_DATASET_SOURCE = "eppo_petroleum_sales"
SOURCE_ID = EPPO_DATASET_SOURCE

# Canonical metric for Table 2.3-4 (domestic sales only).
EPPO_METRIC_TYPE = "TOTDEMO"

# Native unit in both EPPO workbooks.
EPPO_UNIT_NATIVE = "bbl/d"

# Historical wide-file sub-column headers (row 6) -> product_map Product_name.
_HISTORICAL_SUBHEADER_TO_PRODUCT: dict[str, str] = {
    "REGULAR": " REGULAR",
    "PREMIUM": " PREMIUM",
    "HSD": " HSD",
    "LSD": " LSD",
    "KEROSENE": "KEROSENE",
    "JP": "J.P.",
    "FUELOIL": "FUEL OIL",
    "LPG": "LPG",
}

# Parent totals in the historical file — not persisted in the unified series.
_HISTORICAL_PARENT_HEADERS: frozenset[str] = frozenset({"TOTAL", "GASOLINE", "DIESEL"})


def _eppo_product_names() -> frozenset[str]:
    """All Product_name values for Thailand / EPPO in product_map.csv."""
    pm = load_product_map()
    mask = pm["Source"] == EPPO_AGENCY_SOURCE
    return frozenset(pm.loc[mask, "Product_name"].astype(str).tolist())


def normalize_eppo_product_name(label: object) -> str:
    """
    Map a raw Excel product label to the exact ``Product_name`` key in
    ``product_map.csv``.

    Handles historical spellings (``JP``, ``FUELOIL``, ``REGULAR`` without
    leading space) and passes through current-file labels that already match
    the CSV (e.g. ``' PREMIUM'``, ``'J.P.    '``).
    """
    if label is None:
        return ""
    text = str(label)
    if not text or text.strip().lower() == "nan":
        return ""

    known = _eppo_product_names()

    # Exact match first (preserves leading/trailing spaces from current file).
    if text in known:
        return text

    stripped = text.strip()
    if stripped in known:
        return stripped

    if stripped in _HISTORICAL_SUBHEADER_TO_PRODUCT:
        return _HISTORICAL_SUBHEADER_TO_PRODUCT[stripped]

    # Current file uses trailing spaces on J.P.; CSV key is "J.P."
    if stripped in ("J.P.", "JP"):
        return "J.P."

    # Current-file parent rows without extra normalization.
    if stripped == "DIESEL":
        return "DIESEL  "

    return text


def is_eppo_unified_primary(product_name: str) -> bool:
    """
    True if this product should be stored in the unified monthly parquet.

    Uses ``product_map.csv``: primaries have a real Sub-category; dropped
    detail rows (GASOHOL, U95, fuel grades) and [AGG] parents do not.
    """
    name = normalize_eppo_product_name(product_name)
    if not name or name in {"GASOLINE", "DIESEL  ", "TOTAL"}:
        return False
    try:
        return is_primary(name, EPPO_AGENCY_SOURCE)
    except KeyError:
        return False


def eppo_primary_product_names() -> list[str]:
    """Sorted list of unified primary Product_name keys for EPPO."""
    names = [
        n
        for n in _eppo_product_names()
        if is_eppo_unified_primary(n)
    ]
    return sorted(names, key=lambda s: s.strip())


# Dashboard native-product panel (primary EPPO sales rows only).
CHART_PRODUCTS = eppo_primary_product_names()

DISPLAY_LABELS: dict[str, str] = {p: p.strip() for p in CHART_PRODUCTS}

# LSD is a diesel sub-grade; Thailand notebook drops it from seasonality panels.
SEASONALITY_NATIVE_PRODUCTS: tuple[str, ...] = tuple(
    p for p in CHART_PRODUCTS if p.strip() != "LSD"
)
# Same cross-country default (Gasoline/Diesel/Jet fuel/Kerosene/LPG/Naphtha/Fuel oil).
# Panels absent from Thailand data are dropped at chart time.
SEASONALITY_PANELS_CANONICAL: tuple[str, ...] = DEFAULT_SEASONALITY_PANELS_CANONICAL

JODI_COMPARE_SERIES = build_kind_rollup_jodi_compare(
    EPPO_DATASET_SOURCE,
    merge_jet_into_kerosene=True,
)
JODI_COMPARE_PANEL_ORDER = panel_order_from_specs(JODI_COMPARE_SERIES)


def eppo_series_for_jodi(
    demand: pd.DataFrame,
    series_key: str,
    *,
    value_col: str = "value_kbd",
) -> pd.DataFrame:
    """Aggregate EPPO natives for one Thailand JODI compare panel."""
    return sum_natives_series_for_jodi(
        demand,
        series_key,
        jodi_compare=JODI_COMPARE_SERIES,
        value_col=value_col,
    )


def seasonality_chart_inputs(
    demand: pd.DataFrame,
    demand_canonical: pd.DataFrame,
    *,
    view: str = "native",
    value_col: str = "value_kbd",
) -> tuple[pd.DataFrame, str, list[str], dict[str, str], str]:
    return default_seasonality_chart_inputs(
        demand,
        demand_canonical,
        view=view,
        value_col=value_col,
        native_products=SEASONALITY_NATIVE_PRODUCTS,
        display_labels=DISPLAY_LABELS,
        canonical_panels=SEASONALITY_PANELS_CANONICAL,
        exclude_provisional=True,
        native_suffix="native primaries (observed months)",
    )


__all__ = [
    "CHART_PRODUCTS",
    "DISPLAY_LABELS",
    "EPPO_AGENCY_SOURCE",
    "EPPO_DATASET_SOURCE",
    "SOURCE_ID",
    "JODI_COMPARE_PANEL_ORDER",
    "JODI_COMPARE_SERIES",
    "EPPO_METRIC_TYPE",
    "EPPO_UNIT_NATIVE",
    "eppo_series_for_jodi",
    "seasonality_chart_inputs",
    "normalize_eppo_product_name",
    "is_eppo_unified_primary",
    "eppo_primary_product_names",
]
