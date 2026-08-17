"""
reference.australia
───────────────────
DCCEEW petroleum statistics hooks for the central warehouse and dashboard.
"""

from __future__ import annotations

import pandas as pd

from reference.jodi_compare import (
    JodiCompareSeries,
    build_aggregate_label_jodi_compare,
    panel_order_from_specs,
    sum_natives_series_for_jodi,
)
from reference.dashboard_helpers import default_seasonality_chart_inputs

COUNTRY_CODE = "AU"
COUNTRY_NAME = "Australia"
SOURCE_ID = "dceew_petroleum_statistics"
DCCEEW_UNIT_NATIVE = "ML"
DEMAND_METRIC_TYPE = "TOTDEMO"
JODI_REF_AREA = "AU"

CHART_PRODUCTS: tuple[str, ...] = (
    "Diesel oil: total",
    "Automotive gasoline total",
    "Aviation turbine fuel total",
    "Fuel oil",
    "LPG total",
)

DISPLAY_LABELS: dict[str, str] = {
    "Diesel oil: total": "Diesel",
    "Automotive gasoline total": "Gasoline",
    "Aviation turbine fuel total": "Jet fuel",
    "Fuel oil": "Fuel oil",
    "LPG total": "LPG",
}

JET_PRODUCT_NATIVE = "Aviation turbine fuel total"

SEASONALITY_NATIVE_PRODUCTS: tuple[str, ...] = CHART_PRODUCTS
SEASONALITY_PANELS_CANONICAL: tuple[str, ...] = (
    "Gasoline",
    "Diesel",
    "Jet fuel",
    "Fuel oil",
    "LPG",
)
SEASONALITY_YEARS_BACK = 6

JODI_COMPARE_SERIES: dict[str, JodiCompareSeries] = build_aggregate_label_jodi_compare(
    SOURCE_ID
)
JODI_COMPARE_PANEL_ORDER = panel_order_from_specs(JODI_COMPARE_SERIES)


def dceew_series_for_jodi(
    demand: pd.DataFrame,
    series_key: str,
    *,
    value_col: str = "value_kbd",
) -> pd.DataFrame:
    """Aggregate DCCEEW headline natives for one JODI compare panel."""
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
        years_back=SEASONALITY_YEARS_BACK,
    )


__all__ = [
    "CHART_PRODUCTS",
    "COUNTRY_CODE",
    "COUNTRY_NAME",
    "DCCEEW_UNIT_NATIVE",
    "DEMAND_METRIC_TYPE",
    "DISPLAY_LABELS",
    "JET_PRODUCT_NATIVE",
    "JODI_COMPARE_PANEL_ORDER",
    "JODI_COMPARE_SERIES",
    "JODI_REF_AREA",
    "SOURCE_ID",
    "dceew_series_for_jodi",
    "seasonality_chart_inputs",
]
