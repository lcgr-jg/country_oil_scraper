"""
reference.china
───────────────
SCI (SCI99) China oil datapack — national monthly product consumption.

Not a web scrape: reads national frames already cached by ``sci_api``
(``consumption_national`` + ``kerosene_refueling_national``).

Derived product
---------------
``X_OTHKERO = Kerosene − Jet fuel (domestic)`` (clamped at 0), same idea as
JODI's non-jet kerosene split. Headline SCI ``Kerosene`` stays in the native
frame for the JODI ``KEROSENE`` overlay; only the derived residual maps to
canonical Kerosene so jet is not double-counted.
"""

from __future__ import annotations

from pathlib import Path
from typing import FrozenSet

import pandas as pd

from reference.jodi_compare import JodiCompareSeries

SCI_AGENCY_SOURCE = "SCI"
SCI_DATASET_SOURCE = "china_sci_consumption"
SCI_METRIC_TYPE = "TOTDEMO"
SCI_UNIT_NATIVE = "kt"

COUNTRY_CODE = "CN"
COUNTRY_NAME = "China"
SOURCE_ID = SCI_DATASET_SOURCE
JODI_REF_AREA = "CN"

# Sibling repo under Coding/ — sci_api owns fetch + cache.
CODING_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCI_CACHE_ROOT = CODING_ROOT / "sci_api" / "data" / "cache"

PRODUCT_GASOLINE = "Gasoline"
PRODUCT_DIESEL = "Diesel"
PRODUCT_KEROSENE = "Kerosene"
PRODUCT_NAPHTHA = "Naphtha"
PRODUCT_RESIDUE = "Residue"
PRODUCT_VGO = "VGO"
PRODUCT_JET_TOTAL = "Jet fuel (total)"
PRODUCT_JET_DOMESTIC = "Jet fuel (domestic)"
PRODUCT_JET_INTL = "Jet fuel (international)"
PRODUCT_X_OTHKERO = "X_OTHKERO"

CONSUMPTION_PRODUCTS: tuple[str, ...] = (
    PRODUCT_GASOLINE,
    PRODUCT_DIESEL,
    PRODUCT_KEROSENE,
    PRODUCT_NAPHTHA,
    PRODUCT_RESIDUE,
    PRODUCT_VGO,
)

JET_PRODUCTS: tuple[str, ...] = (
    PRODUCT_JET_TOTAL,
    PRODUCT_JET_DOMESTIC,
    PRODUCT_JET_INTL,
)

STORED_NATIVES: tuple[str, ...] = CONSUMPTION_PRODUCTS + JET_PRODUCTS + (
    PRODUCT_X_OTHKERO,
)

CANONICAL_COLUMNS: list[str] = [
    "date",
    "country",
    "country_name",
    "source",
    "metric_type",
    "product_native",
    "product",
    "value",
    "unit",
    "is_provisional",
    "source_file",
    "updated_at",
]

CHART_PRODUCTS: tuple[str, ...] = (
    PRODUCT_GASOLINE,
    PRODUCT_DIESEL,
    PRODUCT_KEROSENE,
    PRODUCT_JET_TOTAL,
    PRODUCT_JET_DOMESTIC,
    PRODUCT_JET_INTL,
    PRODUCT_X_OTHKERO,
    PRODUCT_NAPHTHA,
    PRODUCT_RESIDUE,
    PRODUCT_VGO,
)

DISPLAY_LABELS: dict[str, str] = {
    PRODUCT_GASOLINE: "Gasoline",
    PRODUCT_DIESEL: "Diesel",
    PRODUCT_KEROSENE: "Kerosene (headline)",
    PRODUCT_JET_TOTAL: "Jet fuel",
    PRODUCT_JET_DOMESTIC: "Jet fuel (domestic)",
    PRODUCT_JET_INTL: "Jet fuel (international)",
    PRODUCT_X_OTHKERO: "Kerosene (non-jet)",
    PRODUCT_NAPHTHA: "Naphtha",
    PRODUCT_RESIDUE: "Fuel oil / residue",
    PRODUCT_VGO: "VGO",
}

# Density kinds for analytics.units (warehouse convert_series).
UNITS_KIND: dict[str, str] = {
    PRODUCT_GASOLINE: "gasoline",
    PRODUCT_DIESEL: "diesel",
    PRODUCT_KEROSENE: "kerosene",
    PRODUCT_NAPHTHA: "naphtha",
    PRODUCT_RESIDUE: "fuel_oil",
    PRODUCT_VGO: "other",
    PRODUCT_JET_TOTAL: "jet",
    PRODUCT_JET_DOMESTIC: "jet",
    PRODUCT_JET_INTL: "jet",
    PRODUCT_X_OTHKERO: "kerosene",
}

SEASONALITY_NATIVE_PRODUCTS: tuple[str, ...] = (
    PRODUCT_GASOLINE,
    PRODUCT_DIESEL,
    PRODUCT_JET_TOTAL,
    PRODUCT_X_OTHKERO,
    PRODUCT_NAPHTHA,
    PRODUCT_RESIDUE,
)

SEASONALITY_PANELS_CANONICAL: tuple[str, ...] = (
    "Gasoline",
    "Diesel",
    "Jet fuel",
    "Kerosene",
    "Naphtha",
    "Fuel oil",
)

# JODI CN has no JETKERO — only KEROSENE. Overlay SCI headline kerosene.
GASOLINE_JODI_NATIVES: FrozenSet[str] = frozenset({PRODUCT_GASOLINE})
DIESEL_JODI_NATIVES: FrozenSet[str] = frozenset({PRODUCT_DIESEL})
KEROSENE_JODI_NATIVES: FrozenSet[str] = frozenset({PRODUCT_KEROSENE})

JODI_COMPARE_SERIES: dict[str, JodiCompareSeries] = {
    "gasoline": JodiCompareSeries(
        "gasoline", "GASOLINE", "Gasoline", GASOLINE_JODI_NATIVES
    ),
    "diesel": JodiCompareSeries(
        "diesel", "GASDIES", "Diesel", DIESEL_JODI_NATIVES
    ),
    "kerosene": JodiCompareSeries(
        "kerosene", "KEROSENE", "Kerosene", KEROSENE_JODI_NATIVES
    ),
}

JODI_COMPARE_PANEL_ORDER: tuple[str, ...] = (
    "Gasoline",
    "Diesel",
    "Kerosene",
)


def resolve_sci_cache_dir(cache_root: Path | None = None) -> Path:
    """Return the stamped SCI cache directory (via ``latest.txt`` or newest stamp)."""
    root = Path(cache_root) if cache_root is not None else DEFAULT_SCI_CACHE_ROOT
    if not root.is_dir():
        raise FileNotFoundError(
            f"SCI cache root missing: {root}. "
            "Run sci_api/fetch_data.py --history first."
        )
    latest_txt = root / "latest.txt"
    if latest_txt.exists():
        stamp = latest_txt.read_text(encoding="utf-8").strip()
        path = root / stamp
        if path.is_dir():
            return path
    stamped = sorted(
        (p for p in root.iterdir() if p.is_dir() and p.name.isdigit()),
        key=lambda p: p.name,
    )
    if not stamped:
        raise FileNotFoundError(f"No stamped SCI cache folders under {root}")
    return stamped[-1]


def sci_series_for_jodi(
    demand: pd.DataFrame,
    series_key: str,
    *,
    value_col: str = "value",
) -> pd.DataFrame:
    """Aggregate SCI native rows for one JODI compare panel."""
    spec = JODI_COMPARE_SERIES[series_key]
    sl = demand[demand["product_native"].isin(spec.natives)]
    if sl.empty:
        return pd.DataFrame(columns=["date", value_col, "is_provisional"])
    return (
        sl.groupby(["date", "is_provisional"], as_index=False)[value_col]
        .sum()
        .sort_values("date")
    )


__all__ = [
    "SCI_AGENCY_SOURCE",
    "SCI_DATASET_SOURCE",
    "SCI_METRIC_TYPE",
    "SCI_UNIT_NATIVE",
    "COUNTRY_CODE",
    "COUNTRY_NAME",
    "SOURCE_ID",
    "JODI_REF_AREA",
    "DEFAULT_SCI_CACHE_ROOT",
    "PRODUCT_GASOLINE",
    "PRODUCT_DIESEL",
    "PRODUCT_KEROSENE",
    "PRODUCT_NAPHTHA",
    "PRODUCT_RESIDUE",
    "PRODUCT_VGO",
    "PRODUCT_JET_TOTAL",
    "PRODUCT_JET_DOMESTIC",
    "PRODUCT_JET_INTL",
    "PRODUCT_X_OTHKERO",
    "CONSUMPTION_PRODUCTS",
    "JET_PRODUCTS",
    "STORED_NATIVES",
    "CANONICAL_COLUMNS",
    "CHART_PRODUCTS",
    "DISPLAY_LABELS",
    "UNITS_KIND",
    "SEASONALITY_NATIVE_PRODUCTS",
    "SEASONALITY_PANELS_CANONICAL",
    "JODI_COMPARE_SERIES",
    "JODI_COMPARE_PANEL_ORDER",
    "resolve_sci_cache_dir",
    "sci_series_for_jodi",
]
