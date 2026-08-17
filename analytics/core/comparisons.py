"""Cross-source comparison helpers (official vs JODI vs Kayrros)."""

from __future__ import annotations

from typing import Optional

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from analytics.charts import cross_source_comparison_chart

_OFFICIAL_COLOR = "#636efa"
_KAYRROS_COLOR = "#EF553B"
_GAP_COLOR = "#9467bd"


def build_jodi_comparison_figure(
    official: pd.DataFrame,
    jodi: pd.DataFrame,
    panels: list[str],
    *,
    label_official: str,
    title: str,
) -> Optional[go.Figure]:
    if official.empty or jodi.empty or not panels:
        return None
    return cross_source_comparison_chart(
        df_a=official,
        df_b=jodi,
        products=panels,
        product_col_a="panel",
        product_col_b="panel",
        value_col_a="value_kbd",
        value_col_b="value_kbd",
        label_a=label_official,
        label_b="JODI",
        title=title,
        units_label="kbd",
    )


def build_kayrros_jet_figure(
    official_jet: pd.DataFrame,
    kayrros: pd.DataFrame,
    *,
    label_official: str,
    title: str = "Jet fuel — official vs Kayrros",
) -> Optional[go.Figure]:
    """Two-row chart: levels + gap (Kayrros − official)."""
    if official_jet.empty or kayrros.empty:
        return None

    off = official_jet.sort_values("date")[["date", "value_kbd"]].rename(
        columns={"value_kbd": "official_kbd"}
    )
    kay = kayrros.sort_values("date")[["date", "value_kbd"]].rename(
        columns={"value_kbd": "kayrros_kbd"}
    )
    overlap = off.merge(kay, on="date", how="inner").sort_values("date")
    if overlap.empty:
        return None

    overlap["gap_kbd"] = overlap["kayrros_kbd"] - overlap["official_kbd"]

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        subplot_titles=("Jet kbd — official vs Kayrros", "Gap (Kayrros − official)"),
    )
    fig.add_trace(
        go.Scatter(
            x=overlap["date"],
            y=overlap["official_kbd"],
            name=label_official,
            mode="lines",
            line=dict(color=_OFFICIAL_COLOR, width=2),
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=overlap["date"],
            y=overlap["kayrros_kbd"],
            name="Kayrros",
            mode="lines",
            line=dict(color=_KAYRROS_COLOR, width=2),
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=overlap["date"],
            y=overlap["gap_kbd"],
            name="Kayrros - official",
            mode="lines",
            line=dict(color=_GAP_COLOR, width=2),
        ),
        row=2,
        col=1,
    )
    fig.update_layout(height=620, title=title)
    fig.update_yaxes(title_text="kbd", row=1, col=1)
    fig.update_yaxes(title_text="kbd", row=2, col=1)
    return fig


def median_gap_pct(
    official: pd.DataFrame,
    benchmark: pd.DataFrame,
    *,
    value_col: str = "value_kbd",
    date_col: str = "date",
    months: int = 12,
) -> Optional[float]:
    """(official - benchmark) / benchmark * 100 over overlapping recent months."""
    off = official[[date_col, value_col]].rename(columns={value_col: "off"})
    bench = benchmark[[date_col, value_col]].rename(columns={value_col: "bench"})
    merged = off.merge(bench, on=date_col, how="inner").sort_values(date_col)
    if merged.empty:
        return None
    tail = merged.tail(months)
    bench_vals = tail["bench"].replace(0, pd.NA)
    gaps = (tail["off"] - tail["bench"]) / bench_vals * 100
    return float(gaps.dropna().median()) if gaps.notna().any() else None
