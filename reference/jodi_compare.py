"""
Shared helpers for official-vs-JODI compare panels.

Country reference modules define ``JODI_COMPARE_SERIES`` and a
``{source}_series_for_jodi`` function. This module holds the dataclass and
aggregation helpers used by Thailand (kind rollup), Australia (aggregate
labels), and India (explicit native lists).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import FrozenSet

import pandas as pd

from analytics.products import (
    CANONICAL_AGGREGATE_LABELS,
    CANONICAL_KIND_LABEL,
    PRODUCT_KIND_MAP,
)


@dataclass(frozen=True)
class JodiCompareSeries:
    key: str
    jodi_energy_product: str
    panel: str
    natives: FrozenSet[str]


def sum_natives_series_for_jodi(
    demand: pd.DataFrame,
    series_key: str,
    *,
    jodi_compare: dict[str, JodiCompareSeries],
    value_col: str = "value_kbd",
) -> pd.DataFrame:
    """Sum explicit ``product_native`` rows for one JODI compare panel."""
    spec = jodi_compare[series_key]
    sl = demand[demand["product_native"].isin(spec.natives)]
    if sl.empty:
        return pd.DataFrame(columns=["date", value_col, "is_provisional"])
    return (
        sl.groupby(["date", "is_provisional"], as_index=False)[value_col]
        .sum()
        .sort_values("date")
    )


def build_aggregate_label_jodi_compare(source_id: str) -> dict[str, JodiCompareSeries]:
    """
    Build JODI compare specs from ``CANONICAL_AGGREGATE_LABELS`` intersection.

    Used when the official source publishes one aggregate native label per
    canonical kind (DCCEEW ``*: total`` rows).
    """
    official = CANONICAL_AGGREGATE_LABELS[source_id]
    jodi = CANONICAL_AGGREGATE_LABELS["jodi"]
    kinds = sorted(set(official) & set(jodi))
    out: dict[str, JodiCompareSeries] = {}
    for kind in kinds:
        panel = CANONICAL_KIND_LABEL.get(kind, kind.replace("_", " ").title())
        out[kind] = JodiCompareSeries(
            key=kind,
            jodi_energy_product=jodi[kind],
            panel=panel,
            natives=frozenset({official[kind]}),
        )
    return out


def build_kind_rollup_jodi_compare(
    source_id: str,
    *,
    merge_jet_into_kerosene: bool = False,
) -> dict[str, JodiCompareSeries]:
    """
    Build JODI compare specs by rolling up all natives sharing a product kind.

    Used for EPPO Thailand: gasoline = REGULAR + PREMIUM; kerosene panel can
    include jet (J.P.) to match JODI ``KEROSENE`` parent aggregate.
    """
    official_kinds = set(CANONICAL_AGGREGATE_LABELS[source_id])
    jodi = CANONICAL_AGGREGATE_LABELS["jodi"]
    kinds = sorted(official_kinds & set(jodi))
    mapping = PRODUCT_KIND_MAP[source_id]

    out: dict[str, JodiCompareSeries] = {}
    for kind in kinds:
        kinds_to_sum = {kind}
        if merge_jet_into_kerosene and kind == "kerosene" and "jet" in official_kinds:
            kinds_to_sum.add("jet")
        natives = frozenset(n for n, k in mapping.items() if k in kinds_to_sum)
        panel = CANONICAL_KIND_LABEL.get(kind, kind.replace("_", " ").title())
        out[kind] = JodiCompareSeries(
            key=kind,
            jodi_energy_product=jodi[kind],
            panel=panel,
            natives=natives,
        )
    return out


def panel_order_from_specs(specs: dict[str, JodiCompareSeries]) -> tuple[str, ...]:
    """Stable panel order following canonical kind sort order."""
    return tuple(specs[k].panel for k in sorted(specs))


__all__ = [
    "JodiCompareSeries",
    "build_aggregate_label_jodi_compare",
    "build_kind_rollup_jodi_compare",
    "panel_order_from_specs",
    "sum_natives_series_for_jodi",
]
