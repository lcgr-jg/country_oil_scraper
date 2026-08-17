"""Generate notebooks/23_ukraine_demand_dashboard.ipynb (no saved outputs)."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "notebooks" / "23_ukraine_demand_dashboard.ipynb"


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
        """# Ukraine SSSU Fuel Dashboard

Demand and closing stocks from SSSU **DF_FUEL_USAGE_AND_RESERVES_M**,
via `scripts/update_ukraine.py` → `data/processed/ukraine/ukraine_sssu_fuel.parquet`.

National **Ukraine** rows only; four petroleum products. Series start in **2021**.
Mid-series gaps and the **Feb 2022** stop in stock reporting reflect real SSSU
publication breaks (war / confidentiality), not parser errors.

## Sections
1. **Setup** — load parquet, kt → kbd / kb
2. **Coverage summary** — which months exist per metric × product
3. **Reporting timeline** — when demand vs stocks were last published
4. **Headline demand** — four-product total (kbd)
5. **Native products (demand)** — gaps shown as breaks in the line
6. **Canonical rollup (demand)**
7. **Product stocks (CLOSTLV)** — sparse; stops ~2022-01
8. **Demand + stocks (dual axis)** — per product
9. **Seasonality by year** — limited history (2021 + partial later years)
10. **Product changes (MoM / YoY)** — latest month levels and kbd / % changes
11. **SSSU vs JODI** — optional overlay (UA, where JODI has data)

## Conventions
- Native unit **kt** (thousands of tonnes). Demand → **kbd**; stocks → **kb**.
- Demand indicator: **Fuel used** (`TOTDEMO`). Stocks: **Fuel reserves at end of month** (`CLOSTLV`).
- Plotly lines use `connectgaps=False` so missing months stay visible.
"""
    ),
    code(
        '''from pathlib import Path
import sys

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import ipywidgets as widgets
from IPython.display import display

def _resolve_project_root() -> Path:
    here = Path.cwd()
    for candidate in [here, *here.parents]:
        if (candidate / "scripts" / "update_ukraine.py").exists():
            return candidate
        if (candidate / "country_oil_scraper" / "scripts" / "update_ukraine.py").exists():
            return candidate / "country_oil_scraper"
    raise RuntimeError(f"Could not locate project root from cwd: {here}")

PROJECT_ROOT = _resolve_project_root()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from analytics import cross_source_comparison_chart, seasonality_by_year_chart
from analytics.products import CANONICAL_KIND_LABEL, SUBCATEGORY_TO_PRODUCT_KIND
from analytics.units import convert_series
from reference.ukraine import (
    CHART_PRODUCTS,
    DELIVERY_HEADLINE_NATIVE,
    DISPLAY_LABELS,
    JODI_COMPARE_PANEL_ORDER,
    JODI_COMPARE_SERIES,
    JODI_REF_AREA,
    JODI_STOCKS_PANEL_ORDER,
    SSSU_DEMAND_METRIC,
    SSSU_STOCKS_METRIC,
    SSSU_UNIT_NATIVE,
    UNITS_KIND,
    WAR_DEMAND_GAP_END,
    WAR_DEMAND_GAP_START,
    coverage_by_series,
    seasonality_chart_inputs,
    sssu_series_for_jodi,
)

PARQUET_PATH = PROJECT_ROOT / "data" / "processed" / "ukraine" / "ukraine_sssu_fuel.parquet"

df = pd.read_parquet(PARQUET_PATH)
df["date"] = pd.to_datetime(df["date"])
demand = df[df["metric_type"] == SSSU_DEMAND_METRIC].copy()
stocks = df[df["metric_type"] == SSSU_STOCKS_METRIC].copy()

demand["product_kind"] = demand["product_native"].map(UNITS_KIND)
demand["value_kbd"] = convert_series(
    demand["value"],
    SSSU_UNIT_NATIVE,
    "kbd",
    product_kind=demand["product_kind"],
    date=demand["date"],
)
stocks["product_kind"] = stocks["product_native"].map(UNITS_KIND)
stocks["value_kb"] = convert_series(
    stocks["value"],
    SSSU_UNIT_NATIVE,
    "kb",
    product_kind=stocks["product_kind"],
    date=stocks["date"],
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

coverage = coverage_by_series(df)

print(f"Loaded: {len(df):,} rows  ({df['date'].min().date()} -> {df['date'].max().date()})")
print(f"Demand rows: {len(demand):,}  |  Stock rows: {len(stocks):,}")
if not stocks.empty:
    print(f"Stocks last month: {stocks['date'].max().date()}  (reporting ceased after this)")
'''
    ),
    md("## 2. Coverage summary"),
    code(
        '''display(
    coverage.assign(
        first_month=lambda d: d["first_month"].dt.strftime("%Y-%m"),
        last_month=lambda d: d["last_month"].dt.strftime("%Y-%m"),
    )
)

# Months with no demand row in the documented war gap window
if not demand.empty:
    all_months = pd.date_range(demand["date"].min(), demand["date"].max(), freq="MS")
    reported = set(demand["date"].unique())
    gap_months = [
        m for m in all_months
        if WAR_DEMAND_GAP_START <= m <= WAR_DEMAND_GAP_END and m not in reported
    ]
    print(
        f"Demand gap (no national rows): {WAR_DEMAND_GAP_START.date()} -> "
        f"{WAR_DEMAND_GAP_END.date()}  ({len(gap_months)} calendar months)"
    )
'''
    ),
    md(
        """## 3. Reporting timeline

Green = months with at least one published observation for that metric (any product).
Useful for showing the team when SSSU stopped reporting stocks."""
    ),
    code(
        '''def _monthly_presence(frame: pd.DataFrame, metric: str) -> pd.DataFrame:
    sub = frame[frame["metric_type"] == metric]
    if sub.empty:
        return pd.DataFrame(columns=["date", "metric", "present"])
    months = sub.groupby("date").size().reset_index(name="n_products")
    months["metric"] = metric
    months["present"] = 1
    return months[["date", "metric", "present", "n_products"]]

presence = pd.concat(
    [_monthly_presence(df, SSSU_DEMAND_METRIC), _monthly_presence(df, SSSU_STOCKS_METRIC)],
    ignore_index=True,
)
presence["metric_label"] = presence["metric"].map(
    {SSSU_DEMAND_METRIC: "Demand (Fuel used)", SSSU_STOCKS_METRIC: "Stocks (Fuel reserves)"}
)

fig_tl = px.scatter(
    presence,
    x="date",
    y="metric_label",
    size="n_products",
    size_max=18,
    title="SSSU publication timeline — national Ukraine (dot size = products reported)",
    labels={"date": "Month", "metric_label": "Metric", "n_products": "Products"},
)
fig_tl.add_vrect(
    x0=WAR_DEMAND_GAP_START,
    x1=WAR_DEMAND_GAP_END,
    fillcolor="rgba(255,0,0,0.08)",
    line_width=0,
    annotation_text="Demand gap (war)",
    annotation_position="top left",
)
fig_tl.update_layout(height=320)
fig_tl.show()
'''
    ),
    md("## 4. Headline — total demand (kbd)"),
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
    title="Ukraine total petroleum demand — SSSU Fuel used (kbd, 4 products)",
)
fig.update_traces(connectgaps=False)
fig.add_vrect(
    x0=WAR_DEMAND_GAP_START,
    x1=WAR_DEMAND_GAP_END,
    fillcolor="rgba(255,0,0,0.08)",
    line_width=0,
)
fig.show()
'''
    ),
    md("## 5. Native products (demand)"),
    code(
        '''plot_df = demand[demand["product_native"].isin(CHART_PRODUCTS)].copy()
plot_df["label"] = plot_df["product_native"].map(DISPLAY_LABELS)
fig = px.line(
    plot_df,
    x="date",
    y="value_kbd",
    color="label",
    title="Ukraine demand by product — SSSU natives (kbd)",
)
fig.update_traces(connectgaps=False)
fig.add_vrect(
    x0=WAR_DEMAND_GAP_START,
    x1=WAR_DEMAND_GAP_END,
    fillcolor="rgba(255,0,0,0.08)",
    line_width=0,
)
fig.show()
'''
    ),
    md("## 6. Canonical rollup (demand)"),
    code(
        '''fig_c = px.line(
    demand_canonical,
    x="date",
    y="value_kbd",
    color="panel",
    title="Ukraine demand by canonical product (kbd)",
)
fig_c.update_traces(connectgaps=False)
fig_c.add_vrect(
    x0=WAR_DEMAND_GAP_START,
    x1=WAR_DEMAND_GAP_END,
    fillcolor="rgba(255,0,0,0.08)",
    line_width=0,
)
fig_c.show()
'''
    ),
    md(
        """## 7. Product stocks (CLOSTLV)

Month-end fuel reserves. National reporting **stops after Jan 2022** in the current
SSSU release — the flat end of these lines is a real publication break."""
    ),
    code(
        '''if stocks.empty:
    print("[skip] No CLOSTLV rows — run: python scripts/update_ukraine.py --bootstrap")
else:
    plot_stk = stocks[stocks["product_native"].isin(CHART_PRODUCTS)].copy()
    plot_stk["label"] = plot_stk["product_native"].map(DISPLAY_LABELS)
    fig_stk = px.line(
        plot_stk,
        x="date",
        y="value_kb",
        color="label",
        title="Ukraine closing stocks — SSSU fuel reserves (kb)",
    )
    fig_stk.update_traces(connectgaps=False)
    last_stock = stocks["date"].max()
    # add_vline + annotation fails on pd.Timestamp (plotly/pandas 2.x); use shape instead
    fig_stk.add_shape(
        type="line",
        x0=last_stock,
        x1=last_stock,
        y0=0,
        y1=1,
        yref="paper",
        line=dict(dash="dash", color="gray"),
    )
    fig_stk.add_annotation(
        x=last_stock,
        y=1.02,
        yref="paper",
        text="Last stock month",
        showarrow=False,
        yanchor="bottom",
        xanchor="left",
    )
    fig_stk.show()

    latest = stocks["date"].max()
    latest_stk = (
        stocks[stocks["date"] == latest]
        .assign(label=lambda d: d["product_native"].map(DISPLAY_LABELS))
        .sort_values("value_kb", ascending=False)
    )
    display(latest_stk[["label", "value", "value_kb"]])
    print(f"No stock data published after {latest.date()}.")
'''
    ),
    md("## 8. Demand + stocks — pick a product"),
    code(
        '''product_picker = widgets.Dropdown(
    options=[(DISPLAY_LABELS[p], p) for p in CHART_PRODUCTS],
    description="Product:",
)


def plot_demand_vs_stocks(product_native: str) -> None:
    label = DISPLAY_LABELS[product_native]
    d = demand[demand["product_native"] == product_native].sort_values("date")
    s = stocks[stocks["product_native"] == product_native].sort_values("date")

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Scatter(
            x=d["date"],
            y=d["value_kbd"],
            name="Demand (kbd)",
            mode="lines",
            connectgaps=False,
        ),
        secondary_y=False,
    )
    if not s.empty:
        fig.add_trace(
            go.Scatter(
                x=s["date"],
                y=s["value_kb"],
                name="Stocks (kb)",
                mode="lines+markers",
                connectgaps=False,
            ),
            secondary_y=True,
        )
    fig.update_layout(
        title=f"Ukraine — {label}: demand vs closing stocks",
        height=420,
    )
    fig.update_yaxes(title_text="Demand (kbd)", secondary_y=False)
    fig.update_yaxes(title_text="Stocks (kb)", secondary_y=True)
    if not d.empty:
        fig.add_vrect(
            x0=WAR_DEMAND_GAP_START,
            x1=WAR_DEMAND_GAP_END,
            fillcolor="rgba(255,0,0,0.08)",
            line_width=0,
        )
    fig.show()


widgets.interact(plot_demand_vs_stocks, product_native=product_picker)
'''
    ),
    md("## 9. Seasonality by year"),
    code(
        '''view_picker = widgets.Dropdown(
    options=[("Native products", "native"), ("Canonical", "canonical")],
    value="native",
    description="View:",
)


def plot_seasonality(view: str = "native") -> None:
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
        default_visible_prior_years=3,
        units_label="kbd",
        title=f"Ukraine demand — seasonality ({suffix}; sparse years)",
    )
    fig.show()


widgets.interact(plot_seasonality, view=view_picker)
'''
    ),
    md(
        """## 10. Product changes (MoM / YoY)

Latest published month per product (and total). **MoM** = same series vs prior
calendar month; **YoY** = vs same month one year earlier. Empty cells mean SSSU
did not publish that comparison month (war-gap months are not bridged).
"""
    ),
    code(
        '''def _product_change_rows(
    frame: pd.DataFrame,
    *,
    product_col: str,
    labels: dict[str, str] | None = None,
) -> list[dict[str, object]]:
    """One row per product: level and calendar MoM / YoY in kbd and %."""
    rows: list[dict[str, object]] = []
    for product, group in frame.groupby(product_col):
        series = group.sort_values("date")
        ref_date = series["date"].iloc[-1]
        level = float(series["value_kbd"].iloc[-1])

        prior_m = series.loc[
            series["date"] == ref_date - pd.DateOffset(months=1), "value_kbd"
        ]
        prior_y = series.loc[
            series["date"] == ref_date - pd.DateOffset(months=12), "value_kbd"
        ]

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

        rows.append(
            {
                "product": (labels or {}).get(product, product),
                "month": ref_date,
                "level_kbd": level,
                "mom_kbd": mom_kbd,
                "mom_pct": mom_pct,
                "yoy_kbd": yoy_kbd,
                "yoy_pct": yoy_pct,
            }
        )
    return rows


def build_product_change_table(
    demand_native: pd.DataFrame,
    demand_canonical: pd.DataFrame,
    *,
    view: str = "native",
) -> pd.DataFrame:
    view = view.strip().lower()
    if view == "native":
        frame = demand_native[demand_native["product_native"].isin(CHART_PRODUCTS)].copy()
        rows = _product_change_rows(
            frame,
            product_col="product_native",
            labels=DISPLAY_LABELS,
        )
    elif view == "canonical":
        frame = demand_canonical[demand_canonical["panel"].notna()].copy()
        rows = _product_change_rows(frame, product_col="panel")
    else:
        raise ValueError(f"view must be 'native' or 'canonical', got {view!r}")

    total_series = (
        demand_native.groupby("date", as_index=False)["value_kbd"]
        .sum()
        .rename(columns={"value_kbd": "value_kbd"})
        .assign(_key="Total")
    )
    rows.extend(_product_change_rows(total_series, product_col="_key"))

    out = pd.DataFrame(rows)
    return out.sort_values("level_kbd", ascending=False, ignore_index=True)


change_view_picker = widgets.Dropdown(
    options=[("Native products", "native"), ("Canonical", "canonical")],
    value="native",
    description="View:",
)


def show_product_changes(view: str = "native") -> None:
    tbl = build_product_change_table(demand, demand_canonical, view=view)
    display(
        tbl.assign(month=lambda d: d["month"].dt.strftime("%Y-%m")).round(
            {"level_kbd": 1, "mom_kbd": 1, "yoy_kbd": 1, "mom_pct": 1, "yoy_pct": 1}
        )
    )


widgets.interact(show_product_changes, view=change_view_picker)
'''
    ),
    md("## 11. SSSU vs JODI (UA, where available)"),
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

    sssu_panels = []
    for key in JODI_COMPARE_SERIES:
        sl = sssu_series_for_jodi(demand, key, value_col="value_kbd")
        if sl.empty:
            continue
        spec = JODI_COMPARE_SERIES[key]
        sssu_panels.append(sl.assign(panel=spec.panel))
    sssu_panel = pd.concat(sssu_panels, ignore_index=True) if sssu_panels else pd.DataFrame()

    jodi_ua = jodi[
        (jodi["ref_area"] == JODI_REF_AREA)
        & (jodi["flow_breakdown"] == "TOTDEMO")
        & (jodi["unit_measure"] == "KBD")
        & (jodi["energy_product"].isin(jodi_codes))
    ].copy()
    jodi_ua["panel"] = jodi_ua["energy_product"].map(jodi_lookup)
    jodi_ua["value_kbd"] = jodi_ua["obs_value"]

    panels = [p for p in JODI_COMPARE_PANEL_ORDER if p in set(sssu_panel.get("panel", []))]
    if jodi_ua.empty:
        print("[skip] No JODI UA TOTDEMO rows in parquet.")
    elif not panels:
        print("[skip] No overlapping SSSU panels.")
    else:
        fig = cross_source_comparison_chart(
            df_a=sssu_panel,
            df_b=jodi_ua,
            products=panels,
            product_col_a="panel",
            product_col_b="panel",
            value_col_a="value_kbd",
            value_col_b="value_kbd",
            label_a="SSSU",
            label_b="JODI",
            title="Ukraine TOTDEMO — SSSU vs JODI (kbd; SSSU has publication gaps)",
            units_label="kbd",
        )
        fig.show()
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
