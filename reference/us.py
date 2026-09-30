"""
reference.us
────────────
EIA Weekly Petroleum Status Report (WPSR) — US product supplied.

Not a scrape: reads ``doe_fundamental_dashboard/data/eia_weekly.sqlite``.
Weekly kb/d is converted to calendar-month kb/d by attributing each week’s
daily rate across the seven week days, summing kb in the month, then dividing
by the number of covered days in that month (MTD days for an unfinished month;
full calendar length once every day is covered).
"""

from __future__ import annotations

from pathlib import Path
from typing import FrozenSet

import pandas as pd

from reference.jodi_compare import JodiCompareSeries

EIA_AGENCY_SOURCE = "EIA"
EIA_DATASET_SOURCE = "us_eia_product_supplied"
EIA_METRIC_TYPE = "TOTDEMO"
EIA_UNIT_NATIVE = "kbd"

COUNTRY_CODE = "US"
COUNTRY_NAME = "United States"
SOURCE_ID = EIA_DATASET_SOURCE
JODI_REF_AREA = "US"

CODING_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EIA_SQLITE = (
    CODING_ROOT / "doe_fundamental_dashboard" / "data" / "eia_weekly.sqlite"
)

PRODUCT_GASOLINE = "Gasoline"
PRODUCT_DISTILLATES = "Distillates"
PRODUCT_JET_KERO = "Jet/Kero"
PRODUCT_RESID = "Resid"
PRODUCT_OTHER_OIL = "Other Oil"
PRODUCT_TOTAL_OIL = "Total oil demand"

# EIA series IDs (weekly product supplied, kb/d).
SERIES_BY_PRODUCT: dict[str, str] = {
    PRODUCT_GASOLINE: "WGFUPUS2",  # finished motor gasoline
    PRODUCT_DISTILLATES: "WDIUPUS2",
    PRODUCT_JET_KERO: "WKJUPUS2",
    PRODUCT_RESID: "WREUPUS2",
    PRODUCT_OTHER_OIL: "WWOUP_NUS_2",
    PRODUCT_TOTAL_OIL: "WRPUPUS2",  # aggregate sanity line (not in canonical sum)
}

DEMAND_PRODUCTS: tuple[str, ...] = (
    PRODUCT_GASOLINE,
    PRODUCT_DISTILLATES,
    PRODUCT_JET_KERO,
    PRODUCT_RESID,
    PRODUCT_OTHER_OIL,
)

STORED_NATIVES: tuple[str, ...] = DEMAND_PRODUCTS + (PRODUCT_TOTAL_OIL,)

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

CHART_PRODUCTS: tuple[str, ...] = STORED_NATIVES

DISPLAY_LABELS: dict[str, str] = {
    PRODUCT_GASOLINE: "Gasoline (finished)",
    PRODUCT_DISTILLATES: "Distillates",
    PRODUCT_JET_KERO: "Jet / kerosene",
    PRODUCT_RESID: "Residual fuel oil",
    PRODUCT_OTHER_OIL: "Other oil",
    PRODUCT_TOTAL_OIL: "Total oil demand (WRPUPUS2)",
}

UNITS_KIND: dict[str, str] = {
    PRODUCT_GASOLINE: "gasoline",
    PRODUCT_DISTILLATES: "diesel",
    PRODUCT_JET_KERO: "jet",
    PRODUCT_RESID: "fuel_oil",
    PRODUCT_OTHER_OIL: "other",
    PRODUCT_TOTAL_OIL: "other",
}

SEASONALITY_NATIVE_PRODUCTS: tuple[str, ...] = DEMAND_PRODUCTS

SEASONALITY_PANELS_CANONICAL: tuple[str, ...] = (
    "Gasoline",
    "Diesel",
    "Jet fuel",
    "Fuel oil",
)

GASOLINE_JODI_NATIVES: FrozenSet[str] = frozenset({PRODUCT_GASOLINE})
DIESEL_JODI_NATIVES: FrozenSet[str] = frozenset({PRODUCT_DISTILLATES})
JET_JODI_NATIVES: FrozenSet[str] = frozenset({PRODUCT_JET_KERO})
FUEL_OIL_JODI_NATIVES: FrozenSet[str] = frozenset({PRODUCT_RESID})

JODI_COMPARE_SERIES: dict[str, JodiCompareSeries] = {
    "gasoline": JodiCompareSeries(
        "gasoline", "GASOLINE", "Gasoline", GASOLINE_JODI_NATIVES
    ),
    "diesel": JodiCompareSeries(
        "diesel", "GASDIES", "Diesel", DIESEL_JODI_NATIVES
    ),
    "jet_fuel": JodiCompareSeries(
        "jet_fuel", "JETKERO", "Jet fuel", JET_JODI_NATIVES
    ),
    "fuel_oil": JodiCompareSeries(
        "fuel_oil", "RESFUEL", "Fuel oil", FUEL_OIL_JODI_NATIVES
    ),
}

JODI_COMPARE_PANEL_ORDER: tuple[str, ...] = (
    "Gasoline",
    "Diesel",
    "Jet fuel",
    "Fuel oil",
)


def resolve_eia_sqlite(path: Path | None = None) -> Path:
    db = Path(path) if path is not None else DEFAULT_EIA_SQLITE
    if not db.is_file():
        raise FileNotFoundError(
            f"EIA sqlite missing: {db}. "
            "Sync doe_fundamental_dashboard EIA weekly store first."
        )
    return db


def eia_series_for_jodi(
    demand: pd.DataFrame,
    series_key: str,
    *,
    value_col: str = "value",
) -> pd.DataFrame:
    """Aggregate EIA native rows for one JODI compare panel."""
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
    "EIA_AGENCY_SOURCE",
    "EIA_DATASET_SOURCE",
    "EIA_METRIC_TYPE",
    "EIA_UNIT_NATIVE",
    "COUNTRY_CODE",
    "COUNTRY_NAME",
    "SOURCE_ID",
    "JODI_REF_AREA",
    "DEFAULT_EIA_SQLITE",
    "PRODUCT_GASOLINE",
    "PRODUCT_DISTILLATES",
    "PRODUCT_JET_KERO",
    "PRODUCT_RESID",
    "PRODUCT_OTHER_OIL",
    "PRODUCT_TOTAL_OIL",
    "SERIES_BY_PRODUCT",
    "DEMAND_PRODUCTS",
    "STORED_NATIVES",
    "CANONICAL_COLUMNS",
    "CHART_PRODUCTS",
    "DISPLAY_LABELS",
    "UNITS_KIND",
    "SEASONALITY_NATIVE_PRODUCTS",
    "SEASONALITY_PANELS_CANONICAL",
    "JODI_COMPARE_SERIES",
    "JODI_COMPARE_PANEL_ORDER",
    "resolve_eia_sqlite",
    "eia_series_for_jodi",
]
