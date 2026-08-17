"""Generate notebooks/21_uk_demand_dashboard.ipynb (no saved outputs)."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "notebooks" / "21_uk_demand_dashboard.ipynb"


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
        """# UK DESNZ Demand Dashboard

Demand view of DESNZ **Energy Trends ET 3.13** (inland consumption), from
`scripts/update_uk.py` → `data/processed/uk/uk_energy_trends.parquet`.

## Sections
1. **Setup** — load parquet, kt → kbd
2. **Headline** — total demand (all primaries incl. naphtha + derived Others)
3. **Native products**
4. **Canonical rollup**
5. **Recent trends**
6. **Seasonality by year** — native or canonical
7. **DESNZ vs JODI** — product panels + broad total
8. **Jet fuel vs Kayrros** — ET 3.13 jet fuel vs flight nowcaster
9. **Product stocks** — ET 3.11 CLOSTLV: levels, Feb 2026 baseline, MoM changes
10. **DESNZ vs JODI (stocks)** — ET 3.11 CLOSTLV vs JODI `CLOSTLV` (kb)

## Conventions
- Native unit **kt** (thousand tonnes). Values are already in kt in the parquet.
- **Other products (derived)** = official Total minus the 11 published product columns (aviation spirit, petcoke, wax, misc.).
- Headline includes **naphtha** (refinery / total-demand view).
- Months flagged `[provisional]` in the source ODS appear as `is_provisional=True`.
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
        if (candidate / "scripts" / "update_uk.py").exists():
            return candidate
        if (candidate / "country_oil_scraper" / "scripts" / "update_uk.py").exists():
            return candidate / "country_oil_scraper"
    raise RuntimeError(f"Could not locate project root from cwd: {here}")

PROJECT_ROOT = _resolve_project_root()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from analytics import cross_source_comparison_chart, seasonality_by_year_chart
from analytics.products import CANONICAL_KIND_LABEL, SUBCATEGORY_TO_PRODUCT_KIND
from analytics.units import convert_series
from reference.uk import (
    CHART_PRODUCTS,
    DELIVERY_HEADLINE_NATIVE,
    DISPLAY_LABELS,
    JODI_COMPARE_PANEL_ORDER,
    JODI_COMPARE_SERIES,
    JODI_REF_AREA,
    JODI_STOCKS_COMPARE_SERIES,
    JODI_STOCKS_PANEL_ORDER,
    STOCK_DISPLAY_LABELS,
    STOCK_PRODUCTS,
    STOCK_UNITS_KIND,
    UK_STOCKS_METRIC,
    UK_UNIT_NATIVE,
    UNITS_KIND,
    seasonality_chart_inputs,
    uk_series_for_jodi,
    uk_stocks_series_for_jodi,
)

PARQUET_PATH = PROJECT_ROOT / "data" / "processed" / "uk" / "uk_energy_trends.parquet"

df = pd.read_parquet(PARQUET_PATH)
df["date"] = pd.to_datetime(df["date"])
demand = df[df["metric_type"] == "TOTDEMO"].copy()
demand["product_kind"] = demand["product_native"].map(UNITS_KIND)
demand["value_kbd"] = convert_series(
    demand["value"],
    UK_UNIT_NATIVE,
    "kbd",
    product_kind=demand["product_kind"],
    date=demand["date"],
)

stocks = df[df["metric_type"] == UK_STOCKS_METRIC].copy()
stocks["product_kind"] = stocks["product_native"].map(STOCK_UNITS_KIND)
stocks["value_kb"] = convert_series(
    stocks["value"],
    UK_UNIT_NATIVE,
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

print(f"Loaded: {len(df):,} rows  ({df['date'].min().date()} -> {df['date'].max().date()})")
print(f"Demand natives: {demand['product_native'].nunique()}")
print(f"Provisional demand rows: {int(demand['is_provisional'].sum()):,}")
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
    title="UK total petroleum demand — DESNZ ET 3.13 (kbd, incl. naphtha)",
)
fig.show()
'''
    ),
    md("## 3. Native products"),
    code(
        '''plot_df = demand[demand["product_native"].isin(CHART_PRODUCTS)].copy()
plot_df["label"] = plot_df["product_native"].map(DISPLAY_LABELS)
fig = px.line(
    plot_df,
    x="date",
    y="value_kbd",
    color="label",
    line_dash=plot_df["is_provisional"].map({True: "dot", False: "solid"}),
    title="UK demand by product — DESNZ natives (kbd)",
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
    title="UK demand by canonical product (kbd)",
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

By default only the **last 5 calendar years before the current year**, plus the
current year, are visible; older years stay in the legend (click to toggle on).
"""
    ),
    code(
        '''DEFAULT_SEASONALITY_VIEW = "native"
view_picker = widgets.Dropdown(
    options=[("Native products", "native"), ("Canonical panels", "canonical")],
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
        title=f"UK demand — seasonality ({suffix})",
    )
    fig.show()

widgets.interact(plot_seasonality, view=view_picker)
'''
    ),
    md("## 7. DESNZ vs JODI (GB, TOTDEMO, kbd)"),
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

    uk_panels = []
    for key in JODI_COMPARE_SERIES:
        sl = uk_series_for_jodi(demand, key, value_col="value_kbd")
        if sl.empty:
            continue
        spec = JODI_COMPARE_SERIES[key]
        uk_panels.append(sl.assign(panel=spec.panel))
    uk_panel = pd.concat(uk_panels, ignore_index=True) if uk_panels else pd.DataFrame()

    jodi_gb = jodi[
        (jodi["ref_area"] == JODI_REF_AREA)
        & (jodi["flow_breakdown"] == "TOTDEMO")
        & (jodi["unit_measure"] == "KBD")
        & (jodi["energy_product"].isin(jodi_codes))
    ].copy()
    jodi_gb["panel"] = jodi_gb["energy_product"].map(jodi_lookup)
    jodi_gb["value_kbd"] = jodi_gb["obs_value"]

    panels = [p for p in JODI_COMPARE_PANEL_ORDER if p in set(uk_panel.get("panel", []))]
    if not panels:
        print("[skip] No overlapping JODI panels.")
    else:
        fig = cross_source_comparison_chart(
            df_a=uk_panel,
            df_b=jodi_gb,
            products=panels,
            product_col_a="panel",
            product_col_b="panel",
            value_col_a="value_kbd",
            value_col_b="value_kbd",
            label_a="DESNZ",
            label_b="JODI",
            title="UK TOTDEMO — DESNZ vs JODI (kbd)",
            units_label="kbd",
        )
        fig.show()

    uk_headline_total = headline.groupby("date", as_index=False)["value_kbd"].sum()
    jodi_totprods = jodi[
        (jodi["ref_area"] == JODI_REF_AREA)
        & (jodi["flow_breakdown"] == "TOTDEMO")
        & (jodi["unit_measure"] == "KBD")
        & (jodi["energy_product"] == "TOTPRODS")
    ][["date", "obs_value"]].copy()
    if not jodi_totprods.empty:
        jodi_totprods = jodi_totprods.rename(columns={"obs_value": "jodi_kbd"})
        broad = uk_headline_total.merge(jodi_totprods, on="date", how="inner")
        fig2 = go.Figure()
        fig2.add_trace(
            go.Scatter(
                x=broad["date"],
                y=broad["value_kbd"],
                name="DESNZ headline",
                mode="lines",
            )
        )
        fig2.add_trace(
            go.Scatter(
                x=broad["date"],
                y=broad["jodi_kbd"],
                name="JODI TOTPRODS",
                mode="lines",
            )
        )
        fig2.update_layout(
            title="Broad total — DESNZ headline vs JODI TOTPRODS (kbd)",
            yaxis_title="kbd",
        )
        fig2.show()
    else:
        print("[skip] JODI TOTPRODS not available for GB.")
'''
    ),
    md(
        """## 8. Jet fuel vs Kayrros

DESNZ **Jet fuel** (ET 3.13 inland consumption) vs the Kayrros flight-based
nowcaster (`scope='GB'`, ISO departure country). Kayrros tracks in-flight burn;
DESNZ reports product consumption — useful sanity check, not a one-for-one match.
"""
    ),
    code(
        '''import os
from plotly.subplots import make_subplots

KAYROS_ROOT = PROJECT_ROOT.parent / "kayros" / "jet_fuel"
DB_PATH = KAYROS_ROOT / "data" / "jet_fuel.duckdb"
KAYROS_SCOPE = "GB"
JET_NATIVE = "Jet fuel"

if not DB_PATH.exists():
    print(f"[skip] Kayrros DB not found at {DB_PATH}")
    print("       Build/update kayros/jet_fuel/data/jet_fuel.duckdb first.")
else:
    if str(KAYROS_ROOT) not in sys.path:
        sys.path.insert(0, str(KAYROS_ROOT))
    os.environ.setdefault("JET_FUEL_DB_PATH", str(DB_PATH))
    from src.export import get_consumption  # noqa: E402

    desnz_jet = (
        demand[demand["product_native"] == JET_NATIVE]
        .sort_values("date")
        .loc[:, ["date", "value_kbd"]]
        .rename(columns={"value_kbd": "kbd"})
    )

    kayrros = (
        get_consumption(
            scope_type="country",
            scope=KAYROS_SCOPE,
            country_match="code",
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
        desnz_jet.rename(columns={"kbd": "desnz_kbd"})
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
            "Jet kbd — DESNZ vs Kayrros",
            "Gap (Kayrros − DESNZ)",
        ),
    )
    fig.add_trace(
        go.Scatter(x=desnz_jet["date"], y=desnz_jet["kbd"], name="DESNZ jet", mode="lines"),
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
            y=overlap["kay_kbd"] - overlap["desnz_kbd"],
            name="Kayrros − DESNZ",
            mode="lines",
            line=dict(dash="dot"),
        ),
        row=2,
        col=1,
    )
    fig.update_layout(height=620, title="UK jet fuel: DESNZ vs Kayrros nowcaster")
    fig.update_yaxes(title_text="kbd", row=1, col=1)
    fig.update_yaxes(title_text="kbd", row=2, col=1)
    fig.show()

    if overlap.empty:
        print(f"[warn] No overlapping months — check scope={KAYROS_SCOPE!r}")
    else:
        gap = overlap["kay_kbd"] - overlap["desnz_kbd"]
        summary = pd.DataFrame(
            {
                "mean_kbd": {
                    "DESNZ jet": overlap["desnz_kbd"].mean(),
                    "Kayrros": overlap["kay_kbd"].mean(),
                },
                "mean_abs_gap_kbd": gap.abs().mean(),
                "mean_pct_gap": (gap / overlap["desnz_kbd"].replace(0, np.nan) * 100).mean(),
            },
            index=["value"],
        ).T.round(1)
        print(f"Overlapping months: {len(overlap)}")
        display(summary)
'''
    ),
    md(
        """## 9. Product stocks (CLOSTLV)

DESNZ **ET 3.11** closing stocks — month-end inventories in **mbbl** (kb ÷ 1000).

Baseline for the post–late-Feb 2026 window: **Feb 2026** closing level. MoM change = stock draw (negative) or build (positive).
"""
    ),
    code(
        '''if stocks.empty:
    print("[skip] No CLOSTLV rows — run: python scripts/update_uk.py")
else:
    WAR_BASELINE = pd.Timestamp("2026-02-01")

    stk = stocks[stocks["product_native"].isin(STOCK_PRODUCTS)].copy()
    stk = stk.sort_values(["product_native", "date"])
    stk["value_mbbl"] = stk["value_kb"] / 1000.0
    stk["delta_kb"] = stk.groupby("product_native")["value_kb"].diff()
    stk["delta_mbbl"] = stk["delta_kb"] / 1000.0
    stk["label"] = stk["product_native"].map(STOCK_DISPLAY_LABELS)

    baseline = (
        stk[stk["date"] == WAR_BASELINE]
        .set_index("product_native")["value_mbbl"]
    )
    latest_date = stk["date"].max()
    latest = stk[stk["date"] == latest_date].set_index("product_native")["value_mbbl"]

    chg = (latest - baseline).rename("change_mbbl_since_feb2026")
    summary = pd.DataFrame({"feb_2026_mbbl": baseline, "latest_mbbl": latest}).join(chg)
    summary["latest_month"] = latest_date.strftime("%Y-%m")
    display(summary.sort_values("change_mbbl_since_feb2026").round(3))

    total = (
        stocks[stocks["product_native"].isin(STOCK_PRODUCTS)]
        .groupby("date", as_index=False)["value_kb"]
        .sum()
    )
    total["value_mbbl"] = total["value_kb"] / 1000.0
    total = total.sort_values("date")
    total["delta_mbbl"] = total["value_mbbl"].diff()

    recent = total[total["date"] >= "2025-10-01"]
    fig = px.line(
        recent,
        x="date",
        y="value_mbbl",
        title="UK total product stocks (mbbl)",
        markers=True,
    )
    fig.add_shape(
        type="line",
        x0=WAR_BASELINE,
        x1=WAR_BASELINE,
        y0=0,
        y1=1,
        yref="paper",
        line=dict(color="gray", width=1, dash="dash"),
    )
    fig.add_annotation(
        x=WAR_BASELINE,
        y=1.02,
        xref="x",
        yref="paper",
        text="Feb 2026 baseline",
        showarrow=False,
        font=dict(color="gray", size=11),
    )
    fig.update_layout(height=420, template="plotly_white", yaxis_title="mbbl")
    fig.show()

    mom = stk[stk["date"] >= "2025-10-01"].copy()
    fig2 = px.bar(
        mom,
        x="date",
        y="delta_mbbl",
        color="label",
        barmode="relative",
        title="MoM stock change by product (mbbl)",
        labels={"label": "product"},
    )
    fig2.update_layout(height=460, template="plotly_white")
    fig2.show()
'''
    ),
    md(
        """## 10. DESNZ vs JODI (CLOSTLV, kb)

Side-by-side **closing stocks** from DESNZ ET 3.11 vs JODI secondary `CLOSTLV`
for Great Britain (`GB`). Both series are in **thousand barrels** (DESNZ kt →
kb in setup = JODI `KBBL`).

Comparable panels: gasoline, diesel + gas oil → `GASDIES`, jet, burning oil →
`X_OTHKERO`, other products → `ONONSPEC`. JODI also publishes `TOTPRODS` for a
headline total comparison.
"""
    ),
    code(
        '''JODI_PARQUET = PROJECT_ROOT / "data" / "processed" / "jodi" / "jodi_secondary.parquet"

if stocks.empty:
    print("[skip] No CLOSTLV rows in uk_energy_trends.parquet")
elif not JODI_PARQUET.exists():
    print(f"[skip] JODI parquet not found at {JODI_PARQUET}")
    print("       Run: python scripts/update_jodi.py")
else:
    jodi = pd.read_parquet(JODI_PARQUET)
    jodi["date"] = pd.to_datetime(jodi["date"])

    desnz_parts = []
    jodi_codes = []
    for key in JODI_STOCKS_COMPARE_SERIES:
        sl = uk_stocks_series_for_jodi(stocks, key, value_col="value_kb")
        if sl.empty:
            continue
        sl = sl.groupby("date", as_index=False)["value_kb"].sum()
        sl["panel"] = JODI_STOCKS_COMPARE_SERIES[key].panel
        desnz_parts.append(sl[["date", "panel", "value_kb"]])
        jodi_codes.append(JODI_STOCKS_COMPARE_SERIES[key].jodi_energy_product)

    desnz_panel = pd.concat(desnz_parts, ignore_index=True)

    jodi_gb = jodi[
        (jodi["ref_area"] == JODI_REF_AREA)
        & (jodi["flow_breakdown"] == "CLOSTLV")
        & (jodi["unit_measure"] == "KBBL")
        & (jodi["energy_product"].isin(jodi_codes))
    ].copy()
    code_to_panel = {
        spec.jodi_energy_product: spec.panel
        for spec in JODI_STOCKS_COMPARE_SERIES.values()
    }
    jodi_gb["panel"] = jodi_gb["energy_product"].map(code_to_panel)
    jodi_gb["value_kb"] = jodi_gb["obs_value"]

    panels = [p for p in JODI_STOCKS_PANEL_ORDER if p in desnz_panel["panel"].unique()]

    fig = cross_source_comparison_chart(
        df_a=desnz_panel,
        df_b=jodi_gb,
        products=panels,
        product_col_a="panel",
        product_col_b="panel",
        value_col_a="value_kb",
        value_col_b="value_kb",
        label_a="DESNZ",
        label_b="JODI",
        title="UK CLOSTLV — DESNZ vs JODI (kb = KBBL)",
        units_label="kb",
        cols=2,
        panel_height=280,
    )
    fig.show()

    cutoff_24 = desnz_panel["date"].max() - pd.DateOffset(months=23)
    print("\\nMean |gap| over last 24 months (kb):")
    for panel in panels:
        d = desnz_panel.loc[desnz_panel["panel"] == panel].set_index("date")["value_kb"]
        j = jodi_gb.loc[jodi_gb["panel"] == panel].set_index("date")["value_kb"]
        merged = pd.concat([d, j], axis=1, keys=["desnz", "jodi"]).dropna()
        merged = merged.loc[merged.index >= cutoff_24]
        if merged.empty:
            continue
        gap = (merged["desnz"] - merged["jodi"]).abs().mean()
        pct = gap / merged["jodi"].abs().mean() * 100
        print(f"  {panel:12s}  mean|gap| = {gap:>8,.0f} kb  ({pct:5.1f}% of JODI level)")

    desnz_compare_total = (
        desnz_panel.groupby("date", as_index=False)["value_kb"].sum()
        .rename(columns={"value_kb": "desnz_kb"})
    )
    jodi_compare_total = (
        jodi_gb.groupby("date", as_index=False)["value_kb"].sum()
        .rename(columns={"value_kb": "jodi_kb"})
    )
    desnz_all_total = (
        stocks[stocks["product_native"].isin(STOCK_PRODUCTS)]
        .groupby("date", as_index=False)["value_kb"]
        .sum()
        .rename(columns={"value_kb": "desnz_kb"})
    )
    jodi_totprods = (
        jodi[
            (jodi["ref_area"] == JODI_REF_AREA)
            & (jodi["flow_breakdown"] == "CLOSTLV")
            & (jodi["unit_measure"] == "KBBL")
            & (jodi["energy_product"] == "TOTPRODS")
        ][["date", "obs_value"]]
        .rename(columns={"obs_value": "jodi_kb"})
    )

    cmp = desnz_compare_total.merge(jodi_compare_total, on="date", how="inner")
    fig2 = go.Figure()
    fig2.add_trace(
        go.Scatter(
            x=cmp["date"],
            y=cmp["desnz_kb"],
            name="DESNZ (§10 product set)",
            line=dict(color="#1f77b4"),
        )
    )
    fig2.add_trace(
        go.Scatter(
            x=cmp["date"],
            y=cmp["jodi_kb"],
            name="JODI (§10 product set)",
            line=dict(color="#ff7f0e"),
        )
    )
    fig2.update_layout(
        title="Total closing stocks — DESNZ vs JODI (same products as panels, kb)",
        height=420,
        template="plotly_white",
        yaxis_title="kb",
        hovermode="x unified",
    )
    fig2.show()

    broad = desnz_all_total.merge(jodi_totprods, on="date", how="inner")
    fig3 = go.Figure()
    fig3.add_trace(
        go.Scatter(
            x=broad["date"],
            y=broad["desnz_kb"],
            name="DESNZ (all ET 3.11 products)",
            line=dict(color="#1f77b4"),
        )
    )
    fig3.add_trace(
        go.Scatter(
            x=broad["date"],
            y=broad["jodi_kb"],
            name="JODI TOTPRODS",
            line=dict(color="#ff7f0e"),
        )
    )
    fig3.update_layout(
        title="Broad total — DESNZ (all ET 3.11 products) vs JODI TOTPRODS (kb)",
        height=420,
        template="plotly_white",
        yaxis_title="kb",
        hovermode="x unified",
    )
    fig3.show()

    war_start = pd.Timestamp("2026-02-01")
    recent = cmp[cmp["date"] >= war_start].copy()
    if not recent.empty:
        recent["gap_kb"] = recent["desnz_kb"] - recent["jodi_kb"]
        print(f"\\nSince {war_start.date()} (comparable product total, kb):")
        print(f"  Latest month     : {recent['date'].max().strftime('%Y-%m')}")
        print(f"  DESNZ            : {recent.iloc[-1]['desnz_kb']:,.0f} kb")
        print(f"  JODI             : {recent.iloc[-1]['jodi_kb']:,.0f} kb")
        print(f"  DESNZ − JODI     : {recent.iloc[-1]['gap_kb']:+,.0f} kb")
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
