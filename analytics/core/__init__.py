"""Analytics core — warehouse-backed demand metrics and comparisons."""

from analytics.core.comparisons import (
    build_jodi_comparison_figure,
    build_kayrros_jet_figure,
    median_gap_pct,
)
from analytics.core.divergences import (
    detect_episodic_divergences,
    format_divergence_notes,
    structural_notes,
)
from analytics.core.loader import (
    load_demand_canonical,
    load_jodi_compare_panels,
    load_kayrros_series,
    load_observations,
    load_official_demand,
    warehouse_status,
)
from analytics.core.metrics import (
    available_months,
    coverage_by_product,
    headline_total,
    product_change_table,
)
from analytics.core.trading_notes import build_trading_notes
from warehouse.country_hooks import call_seasonality_chart_inputs

__all__ = [
    "available_months",
    "build_jodi_comparison_figure",
    "build_kayrros_jet_figure",
    "build_trading_notes",
    "call_seasonality_chart_inputs",
    "coverage_by_product",
    "detect_episodic_divergences",
    "format_divergence_notes",
    "headline_total",
    "load_demand_canonical",
    "load_jodi_compare_panels",
    "load_kayrros_series",
    "load_observations",
    "load_official_demand",
    "median_gap_pct",
    "product_change_table",
    "structural_notes",
    "warehouse_status",
]
