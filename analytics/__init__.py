"""
analytics
─────────
Cross-cutting analytic helpers for country-oil dashboards.

Modules
-------
  units    Conversion between volume / mass / rate units.
  products Maps source-native product labels to canonical kinds.
  charts   Reusable plotly small-multiples chart builders.
  unified  Load national + JODI parquets into one frame (Phase 5a).
  jodi_dashboard  JODI multi-product dashboard data layer (notebook 05).

Quick start
-----------
  from analytics import (
      convert, convert_series,            # units.py
      infer_product_kind,                 # products.py
      SUBCATEGORY_TO_PRODUCT_KIND,        # products.py — shared with unified
      load_unified,                       # unified.py
      clear_unified_caches,
      clear_products_caches,             # products.py — after editing product_map.csv
      seasonality_by_year_chart,          # charts.py
      cross_source_comparison_chart,
  )
"""

from .units import (
    convert,
    convert_series,
    available_units,
    BBL_PER_TONNE,
    BBL_PER_M3,
    KB_PER_ML,
    KB_PER_KL,
)
from .products import (
    infer_product_kind,
    PRODUCT_KIND_MAP,
    CANONICAL_KIND_LABEL,
    CANONICAL_AGGREGATE_LABELS,
    DCCEEW_LABEL_TO_KIND,
    JODI_LABEL_TO_KIND,
    PPAC_LABEL_TO_KIND,
    EPPO_LABEL_TO_KIND,
    SUBCATEGORY_TO_PRODUCT_KIND,
    clear_products_caches,
)
from .charts import (
    seasonality_by_year_chart,
    cross_source_comparison_chart,
    cross_source_gap_chart,
)
from .unified import load_unified, clear_unified_caches
from .jodi_dashboard import (
    configure as configure_jodi_dashboard,
    DRIVER_LAG_MONTHS,
    build_regional_driver_summary,
    build_country_contribution_table,
)

__all__ = [
    # units
    "convert",
    "convert_series",
    "available_units",
    "BBL_PER_TONNE",
    "BBL_PER_M3",
    "KB_PER_ML",
    "KB_PER_KL",
    # products
    "infer_product_kind",
    "PRODUCT_KIND_MAP",
    "CANONICAL_KIND_LABEL",
    "CANONICAL_AGGREGATE_LABELS",
    "DCCEEW_LABEL_TO_KIND",
    "JODI_LABEL_TO_KIND",
    "PPAC_LABEL_TO_KIND",
    "EPPO_LABEL_TO_KIND",
    "SUBCATEGORY_TO_PRODUCT_KIND",
    "clear_products_caches",
    # charts
    "seasonality_by_year_chart",
    "cross_source_comparison_chart",
    "cross_source_gap_chart",
    # unified
    "load_unified",
    "clear_unified_caches",
    # jodi_dashboard
    "configure_jodi_dashboard",
    "DRIVER_LAG_MONTHS",
    "build_regional_driver_summary",
    "build_country_contribution_table",
]
