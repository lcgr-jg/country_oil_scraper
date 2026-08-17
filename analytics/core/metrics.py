"""Shared demand metrics — MoM/YoY tables, coverage, headline totals."""

from __future__ import annotations

from typing import Mapping, Optional

import numpy as np
import pandas as pd


def coverage_by_product(
    demand: pd.DataFrame,
    *,
    product_col: str = "product_native",
) -> pd.DataFrame:
    if demand.empty:
        return pd.DataFrame(
            columns=[product_col, "first_month", "last_month", "n_months"]
        )
    g = demand.groupby(product_col)["date"]
    return (
        g.agg(first_month="min", last_month="max", n_months="count")
        .reset_index()
        .sort_values(product_col)
    )


def headline_total(demand_canonical: pd.DataFrame) -> pd.DataFrame:
    if demand_canonical.empty:
        return pd.DataFrame(columns=["date", "value_kbd", "is_provisional"])
    # Sum all panels at each date once. Grouping by is_provisional as well splits
    # months when panels disagree (common after multi-country aggregation).
    return (
        demand_canonical.groupby("date", as_index=False)
        .agg(
            value_kbd=("value_kbd", "sum"),
            is_provisional=("is_provisional", "max"),
        )
        .sort_values("date")
    )


def product_change_table(
    frame: pd.DataFrame,
    *,
    product_col: str,
    ref_date: Optional[pd.Timestamp] = None,
    value_col: str = "value_kbd",
    labels: Optional[Mapping[str, str]] = None,
    include_total: Optional[pd.DataFrame] = None,
    total_label: str = "Total (canonical)",
) -> pd.DataFrame:
    """
    MoM / YoY snapshot for one month (default: latest in frame).

    include_total: optional pre-aggregated series with a synthetic product column.
    """
    rows: list[dict[str, object]] = []
    for product, group in frame.groupby(product_col):
        rows.extend(
            _change_row(
                group,
                product=str(product),
                product_col=product_col,
                ref_date=ref_date,
                value_col=value_col,
                labels=labels,
            )
        )

    if include_total is not None and not include_total.empty:
        total_frame = include_total.copy()
        total_frame[product_col] = total_label
        rows.extend(
            _change_row(
                total_frame,
                product=total_label,
                product_col=product_col,
                ref_date=ref_date,
                value_col=value_col,
                labels=labels,
            )
        )

    if not rows:
        return pd.DataFrame(
            columns=[
                "product",
                "month",
                "level_kbd",
                "mom_kbd",
                "mom_pct",
                "yoy_kbd",
                "yoy_pct",
            ]
        )

    tbl = pd.DataFrame(rows)
    return tbl.sort_values("level_kbd", ascending=False, na_position="last")


def _change_row(
    group: pd.DataFrame,
    *,
    product: str,
    product_col: str,
    ref_date: Optional[pd.Timestamp],
    value_col: str,
    labels: Optional[Mapping[str, str]],
) -> list[dict[str, object]]:
    series = group.sort_values("date")
    if series.empty:
        return []

    ref = ref_date if ref_date is not None else series["date"].iloc[-1]
    at_ref = series.loc[series["date"] == ref]
    if at_ref.empty:
        return []

    level = float(at_ref[value_col].iloc[-1])
    prior_m = series.loc[series["date"] == ref - pd.DateOffset(months=1), value_col]
    prior_y = series.loc[series["date"] == ref - pd.DateOffset(months=12), value_col]

    mom_kbd = level - float(prior_m.iloc[0]) if len(prior_m) else np.nan
    yoy_kbd = level - float(prior_y.iloc[0]) if len(prior_y) else np.nan
    mom_pct = (
        (level / float(prior_m.iloc[0]) - 1) * 100
        if len(prior_m) and float(prior_m.iloc[0]) != 0
        else np.nan
    )
    yoy_pct = (
        (level / float(prior_y.iloc[0]) - 1) * 100
        if len(prior_y) and float(prior_y.iloc[0]) != 0
        else np.nan
    )

    display = (labels or {}).get(product, product)
    return [
        {
            "product": display,
            "month": ref,
            "level_kbd": level,
            "mom_kbd": mom_kbd,
            "mom_pct": mom_pct,
            "yoy_kbd": yoy_kbd,
            "yoy_pct": yoy_pct,
        }
    ]


def filter_to_month(df: pd.DataFrame, month: pd.Timestamp) -> pd.DataFrame:
    month = pd.Timestamp(month).normalize().replace(day=1) + pd.offsets.MonthEnd(0)
    return df[df["date"] == month].copy()


def available_months(demand: pd.DataFrame) -> list[pd.Timestamp]:
    if demand.empty:
        return []
    months = pd.to_datetime(demand["date"].drop_duplicates()).sort_values()
    return list(months)
