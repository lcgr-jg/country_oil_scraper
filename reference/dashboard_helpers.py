"""
Shared dashboard helpers for country reference modules.

Keeps ``seasonality_chart_inputs`` implementations consistent across countries
that do not need custom rollups (Spain/Portugal use sheet rollups instead).
"""

from __future__ import annotations

from typing import Mapping, Sequence

import pandas as pd

DEFAULT_SEASONALITY_PANELS_CANONICAL: tuple[str, ...] = (
    "Gasoline",
    "Diesel",
    "Jet fuel",
    "Kerosene",
    "LPG",
    "Naphtha",
    "Fuel oil",
)


def default_seasonality_chart_inputs(
    demand: pd.DataFrame,
    demand_canonical: pd.DataFrame,
    *,
    view: str = "native",
    value_col: str = "value_kbd",
    native_products: Sequence[str],
    display_labels: Mapping[str, str] | None = None,
    canonical_panels: Sequence[str] = DEFAULT_SEASONALITY_PANELS_CANONICAL,
    exclude_provisional: bool = False,
    years_back: int | None = None,
    native_suffix: str = "native products",
    canonical_suffix: str = "canonical products",
) -> tuple[pd.DataFrame, str, list[str], dict[str, str], str]:
    """Standard native / canonical seasonality inputs used by several countries."""
    view = view.strip().lower()
    labels = dict(display_labels or {})

    if view == "native":
        products = [p for p in native_products if p in demand["product_native"].values]
        df = demand[demand["product_native"].isin(products)].copy()
        if exclude_provisional and "is_provisional" in df.columns:
            df = df[~df["is_provisional"].fillna(False)]
        if years_back is not None and not df.empty:
            cutoff = int(df["date"].dt.year.max()) - years_back
            df = df[df["date"].dt.year >= cutoff]
        for p in products:
            labels.setdefault(p, p)
        return df, "product_native", products, labels, native_suffix

    if view == "canonical":
        products = [p for p in canonical_panels if p in demand_canonical["panel"].values]
        df = demand_canonical[demand_canonical["panel"].isin(products)].copy()
        if years_back is not None and not df.empty:
            cutoff = int(df["date"].dt.year.max()) - years_back
            df = df[df["date"].dt.year >= cutoff]
        return df, "panel", products, {p: p for p in products}, canonical_suffix

    raise ValueError(f"view must be 'native' or 'canonical', got {view!r}")


def resolve_product_labels(
    products: Sequence[str],
    friendly_labels: Mapping[str, str] | None,
    *,
    use_source_native: bool,
) -> dict[str, str]:
    """
    Map chart/table keys to display strings.

    Audit mode (``use_source_native=True``) keeps exact ``product_native`` keys
    — including spacing — so panels match Excel / parquet / product_map.csv.
    """
    if use_source_native:
        return {p: p for p in products}
    labels = friendly_labels or {}
    return {p: labels.get(p, p) for p in products}


__all__ = [
    "DEFAULT_SEASONALITY_PANELS_CANONICAL",
    "default_seasonality_chart_inputs",
    "resolve_product_labels",
]
