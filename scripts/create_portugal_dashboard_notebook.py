"""Generate notebooks/20_portugal_demand_dashboard.ipynb (no saved outputs)."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "notebooks" / "20_portugal_demand_dashboard.ipynb"


def md(text: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": text.splitlines(keepends=True)}


def code(text: str) -> dict:
    return {
        "cell_type": "code",
        "metadata": {},
        "source": text.splitlines(keepends=True),
        "outputs": [],
        "execution_count": None,
    }


cells = [
    md(
        """# Portugal DGEG Demand Dashboard

Demand view of DGEG **Monthly Sales of Oil Products**, from
`scripts/update_portugal.py` → `data/processed/portugal/portugal_dgeg_sales.parquet`.

## Sections
1. **Setup** — load parquet, tonnes → kbd
2. **Headline** — total demand (all stored products incl. naphtha, petcoke, bitumen)
3. **Native products**
4. **Canonical rollup**
5. **Recent trends**
6. **Seasonality by year** — market segments (native) or canonical
7. **DGEG vs JODI** — gasoline, diesel, gasoil, jet, LPG, fuel oil composites
8. **Jet fuel vs Kayrros** — `Aviation | Jet fuel` vs flight nowcaster

## Conventions
- Native unit **t** (tonnes). Convert via kt → kbd using `analytics.units`.
- Memo Fuel, Biofuels, and LPG sub-rows are not stored.
- Current-year workbooks are flagged `is_provisional=True`.
"""
    ),
    code(
        '''from pathlib import Path
import sys

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import ipywidgets as widgets
from IPython.display import display

def _resolve_project_root() -> Path:
    here = Path.cwd()
    for candidate in [here, *here.parents]:
        if (candidate / "scripts" / "update_portugal.py").exists():
            return candidate
        if (candidate / "country_oil_scraper" / "scripts" / "update_portugal.py").exists():
            return candidate / "country_oil_scraper"
    raise RuntimeError(f"Could not locate project root from cwd: {here}")

PROJECT_ROOT = _resolve_project_root()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from analytics import cross_source_comparison_chart, seasonality_by_year_chart
from analytics.products import CANONICAL_KIND_LABEL, SUBCATEGORY_TO_PRODUCT_KIND
from analytics.units import convert_series
from reference.portugal import (
    CHART_PRODUCTS,
    DELIVERY_HEADLINE_NATIVE,
    DISPLAY_LABELS,
    JODI_COMPARE_PANEL_ORDER,
    JODI_COMPARE_SERIES,
    SEASONALITY_PANELS_CANONICAL,
    UNITS_KIND,
    dgeg_series_for_jodi,
    seasonality_chart_inputs,
)

PARQUET_PATH = PROJECT_ROOT / "data" / "processed" / "portugal" / "portugal_dgeg_sales.parquet"

df = pd.read_parquet(PARQUET_PATH)
df["date"] = pd.to_datetime(df["date"])
demand = df[df["metric_type"] == "TOTDEMO"].copy()
demand["product_kind"] = demand["product_native"].map(UNITS_KIND)
demand["value_kbd"] = convert_series(
    demand["value"] / 1000,
    "kt",
    "kbd",
    product_kind=demand["product_kind"],
    date=demand["date"],
)

headline = demand[demand["product_native"].isin(DELIVERY_HEADLINE_NATIVE)].copy()
demand_canonical = (
    demand[demand["product_canonical"].notna()]
    .groupby(["date", "product_canonical", "is_provisional"], as_index=False)["value_kbd"]
    .sum()
)
demand_canonical["panel"] = demand_canonical["product_canonical"].map(
    lambda s: CANONICAL_KIND_LABEL.get(SUBCATEGORY_TO_PRODUCT_KIND.get(s, ""), s)
)

print(f"Loaded: {len(df):,} rows  ({df['date'].min().date()} -> {df['date'].max().date()})")
print(f"Stored natives: {demand['product_native'].nunique()}")
print(f"Provisional rows: {int(demand['is_provisional'].sum()):,}")
print(f"Headline natives: {len(DELIVERY_HEADLINE_NATIVE)}")
'''
    ),
    md("## 2. Headline — total demand (kbd)"),
    code(
        '''headline_ts = (
    headline.groupby(["date", "is_provisional"], as_index=False)["value_kbd"]
    .sum()
    .sort_values("date")
)
fig = px.line(
    headline_ts,
    x="date",
    y="value_kbd",
    color="is_provisional",
    title="Portugal total petroleum demand — DGEG (kbd, all stored products)",
)
fig.show()
'''
    ),
    md("## 3. Native products (selected chart lines)"),
    code(
        '''plot_df = demand[demand["product_native"].isin(CHART_PRODUCTS)].copy()
plot_df["label"] = plot_df["product_native"].map(DISPLAY_LABELS)
fig = px.line(
    plot_df,
    x="date",
    y="value_kbd",
    color="label",
    line_dash=plot_df["is_provisional"].map({True: "dot", False: "solid"}),
    title="Portugal demand by product — DGEG natives (kbd)",
)
fig.show()
'''
    ),
    md("## 4. Canonical rollup"),
    code(
        '''fig_c = px.line(
    demand_canonical,
    x="date",
    y="value_kbd",
    color="panel",
    line_dash=demand_canonical["is_provisional"].map({True: "dot", False: "solid"}),
    title="Portugal demand by canonical product (kbd)",
)
fig_c.show()
'''
    ),
    md("## 5. Recent trends (last 24 months)"),
    code(
        '''cutoff = demand["date"].max() - pd.DateOffset(months=23)
recent = demand[demand["date"] >= cutoff].copy()
recent["label"] = recent["product_native"].map(DISPLAY_LABELS)

def _mom_yoy(g: pd.DataFrame) -> pd.Series:
    g = g.sort_values("date")
    return pd.Series({
        "last_kbd": g["value_kbd"].iloc[-1],
        "mom_pct": (g["value_kbd"].iloc[-1] / g["value_kbd"].iloc[-2] - 1) * 100
        if len(g) >= 2 else np.nan,
        "yoy_pct": (g["value_kbd"].iloc[-1] / g["value_kbd"].iloc[-13] - 1) * 100
        if len(g) >= 13 else np.nan,
    })

snap = (
    recent.groupby("product_native", group_keys=False)
    .apply(_mom_yoy, include_groups=False)
    .reset_index()
)
snap["label"] = snap["product_native"].map(DISPLAY_LABELS)
display(snap.sort_values("last_kbd", ascending=False).round(1))
'''
    ),
    md(
        """## 6. Seasonality by year

**Native** view rolls up Internal market, Marine bunkers, and Aviation segments.
By default only the **last 5 calendar years before the current year**, plus the
current year, are visible; older years stay in the legend (click to toggle on).
"""
    ),
    code(
        '''DEFAULT_SEASONALITY_VIEW = "native"
view_picker = widgets.Dropdown(
    options=[("Market segments (native)", "native"), ("Canonical panels", "canonical")],
    value=DEFAULT_SEASONALITY_VIEW,
    description="View:",
)

def plot_seasonality(view: str = DEFAULT_SEASONALITY_VIEW) -> None:
    season_df, product_col, products, labels, suffix = seasonality_chart_inputs(
        demand, demand_canonical, view=view, value_col="value_kbd"
    )
    if season_df.empty:
        print("[skip] No rows for seasonality.")
        return
    fig = seasonality_by_year_chart(
        season_df,
        products,
        product_col=product_col,
        value_col="value_kbd",
        product_labels=labels,
        default_visible_prior_years=5,
        units_label="kbd",
        title=f"Portugal demand — seasonality ({suffix})",
    )
    fig.show()

widgets.interact(plot_seasonality, view=view_picker)
'''
    ),
    md("## 7. DGEG vs JODI (PT, TOTDEMO, kbd)"),
    code(
        '''JODI_PARQUET = PROJECT_ROOT / "data" / "processed" / "jodi" / "jodi_secondary.parquet"

if not JODI_PARQUET.exists():
    print(f"[skip] JODI parquet not found: {JODI_PARQUET}")
    print("       Run: python scripts/update_jodi.py")
else:
    jodi = pd.read_parquet(JODI_PARQUET)
    jodi["date"] = pd.to_datetime(jodi["date"])
    jodi_lookup = {spec.jodi_energy_product: spec.panel for spec in JODI_COMPARE_SERIES.values()}
    jodi_codes = set(jodi_lookup)

    dgeg_panels = []
    for key in JODI_COMPARE_SERIES:
        sl = dgeg_series_for_jodi(demand, key, value_col="value_kbd")
        if sl.empty:
            continue
        spec = JODI_COMPARE_SERIES[key]
        dgeg_panels.append(sl.assign(panel=spec.panel))
    dgeg_panel = pd.concat(dgeg_panels, ignore_index=True) if dgeg_panels else pd.DataFrame()

    jodi_pt = jodi[
        (jodi["ref_area"] == "PT")
        & (jodi["flow_breakdown"] == "TOTDEMO")
        & (jodi["unit_measure"] == "KBD")
        & (jodi["energy_product"].isin(jodi_codes))
    ].copy()
    jodi_pt["panel"] = jodi_pt["energy_product"].map(jodi_lookup)
    jodi_pt["value_kbd"] = jodi_pt["obs_value"]

    panels = [p for p in JODI_COMPARE_PANEL_ORDER if p in set(dgeg_panel.get("panel", []))]
    if not panels:
        print("[skip] No overlapping JODI panels.")
    else:
        fig = cross_source_comparison_chart(
            df_a=dgeg_panel,
            df_b=jodi_pt,
            products=panels,
            product_col_a="panel",
            product_col_b="panel",
            value_col_a="value_kbd",
            value_col_b="value_kbd",
            label_a="DGEG",
            label_b="JODI",
            title="Portugal TOTDEMO — DGEG vs JODI (kbd)",
            units_label="kbd",
        )
        fig.show()
'''
    ),
    md(
        """## 8. Jet fuel vs Kayrros

DGEG **Aviation | Jet fuel** vs the Kayrros flight-based nowcaster
(`scope='Portugal'`). Kayrros tracks in-flight burn; DGEG reports product
sales — useful sanity check, not a one-for-one match.
"""
    ),
    code(
        '''import os
from plotly.subplots import make_subplots

KAYROS_ROOT = PROJECT_ROOT.parent / "kayros" / "jet_fuel"
DB_PATH = KAYROS_ROOT / "data" / "jet_fuel.duckdb"
KAYROS_SCOPE = "Portugal"
JET_NATIVE = "Aviation | Jet fuel"

if not DB_PATH.exists():
    print(f"[skip] Kayrros DB not found at {DB_PATH}")
    print("       Build/update kayros/jet_fuel/data/jet_fuel.duckdb first.")
else:
    if str(KAYROS_ROOT) not in sys.path:
        sys.path.insert(0, str(KAYROS_ROOT))
    os.environ.setdefault("JET_FUEL_DB_PATH", str(DB_PATH))
    from src.export import get_consumption  # noqa: E402

    dgeg_jet = (
        demand[demand["product_native"] == JET_NATIVE]
        .sort_values("date")
        .loc[:, ["date", "value_kbd"]]
        .rename(columns={"value_kbd": "kbd"})
    )

    kayrros = (
        get_consumption(
            scope_type="country",
            scope=KAYROS_SCOPE,
            freq="monthly",
            metric="avg_kbd",
            drop_incomplete=True,
        )
        .rename(columns={"period_start": "date", "value": "kbd"})
        .loc[:, ["date", "kbd"]]
        .sort_values("date")
        .reset_index(drop=True)
    )

    overlap = (
        dgeg_jet.rename(columns={"kbd": "dgeg_kbd"})
        .merge(kayrros.rename(columns={"kbd": "kay_kbd"}), on="date", how="inner")
        .sort_values("date")
    )

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        row_heights=[0.62, 0.38],
        subplot_titles=(
            "Jet kbd — DGEG vs Kayrros",
            "Gap (Kayrros − DGEG)",
        ),
    )
    fig.add_trace(
        go.Scatter(x=dgeg_jet["date"], y=dgeg_jet["kbd"], name="DGEG jet", mode="lines"),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(x=kayrros["date"], y=kayrros["kbd"], name="Kayrros", mode="lines"),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=overlap["date"],
            y=overlap["kay_kbd"] - overlap["dgeg_kbd"],
            name="Kayrros − DGEG",
            mode="lines",
            line=dict(dash="dot"),
        ),
        row=2,
        col=1,
    )
    fig.update_layout(height=620, title="Portugal jet fuel: DGEG vs Kayrros nowcaster")
    fig.update_yaxes(title_text="kbd", row=1, col=1)
    fig.update_yaxes(title_text="kbd", row=2, col=1)
    fig.show()

    if overlap.empty:
        print(f"[warn] No overlapping months — check scope={KAYROS_SCOPE!r}")
    else:
        gap = overlap["kay_kbd"] - overlap["dgeg_kbd"]
        summary = pd.DataFrame(
            {
                "mean_kbd": {
                    "DGEG jet": overlap["dgeg_kbd"].mean(),
                    "Kayrros": overlap["kay_kbd"].mean(),
                },
                "mean_abs_gap_kbd": gap.abs().mean(),
                "mean_pct_gap": (gap / overlap["dgeg_kbd"].replace(0, np.nan) * 100).mean(),
            },
            index=["value"],
        ).T.round(1)
        print(f"Overlapping months: {len(overlap)}")
        display(summary)
'''
    ),
]

nb = {
    "nbformat": 4,
    "nbformat_minor": 5,
    "metadata": {
        "kernelspec": {
            "display_name": "Python 3",
            "language": "python",
            "name": "python3",
        },
        "language_info": {
            "name": "python",
            "pygments_lexer": "ipython3",
        },
    },
    "cells": cells,
}

OUT.write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"Wrote {OUT} ({len(cells)} cells)")
