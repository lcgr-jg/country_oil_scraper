"""Generate notebooks/16_taiwan_demand_dashboard.ipynb (no saved outputs)."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "notebooks" / "16_taiwan_demand_dashboard.ipynb"


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
        """# Taiwan MOEA Demand Dashboard

Demand view of MOEA Table **5-04** (petroleum products consumption by product),
from `scripts/update_taiwan.py` → `data/processed/taiwan/taiwan_moea_consumption.parquet`.

## Sections
1. **Setup** — load parquet, ktoe → kbd
2. **Headline** — all primaries incl. naphtha (petchem)
3. **Native products**
4. **Canonical rollup**
5. **Recent trends**
6. **Seasonality by year** (native / canonical toggle)
7. **MOEA vs JODI**
8. **Jet fuel vs Kayrros**

## Conventions
- Native unit **ktoe** (千公噸油當量, thousand tonnes oil equivalent).
- Years **2007–2024** are annual totals expanded to flat monthly imputations (`is_provisional=True`).
- True monthly detail from **2025** onward (`is_provisional=False`).
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
        if (candidate / "scripts" / "update_taiwan.py").exists():
            return candidate
        if (candidate / "country_oil_scraper" / "scripts" / "update_taiwan.py").exists():
            return candidate / "country_oil_scraper"
    raise RuntimeError(f"Could not locate project root from cwd: {here}")

PROJECT_ROOT = _resolve_project_root()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from analytics import cross_source_comparison_chart, seasonality_by_year_chart
from analytics.products import (
    CANONICAL_AGGREGATE_LABELS,
    CANONICAL_KIND_LABEL,
    SUBCATEGORY_TO_PRODUCT_KIND,
)
from analytics.units import convert_series
from reference.taiwan import (
    CHART_PRODUCTS,
    DELIVERY_HEADLINE_NATIVE,
    DISPLAY_LABELS,
    JODI_COMPARE_PANEL_ORDER,
    JODI_COMPARE_SERIES,
    MOEA_UNIT_NATIVE,
    UNITS_KIND,
    moea_series_for_jodi,
    seasonality_chart_inputs,
)

PARQUET_PATH = PROJECT_ROOT / "data" / "processed" / "taiwan" / "taiwan_moea_consumption.parquet"

df = pd.read_parquet(PARQUET_PATH)
df["date"] = pd.to_datetime(df["date"])
demand = df[df["metric_type"] == "TOTDEMO"].copy()
demand["product_kind"] = demand["product_native"].map(UNITS_KIND)
demand["value_kbd"] = convert_series(
    demand["value"],
    MOEA_UNIT_NATIVE,
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
print(f"Provisional rows: {int(demand['is_provisional'].sum()):,}")
print(f"Native primaries: {sorted(DELIVERY_HEADLINE_NATIVE)}")
'''
    ),
    md(
        """## 1b. Dataset sanity check — 5-04 consumption vs 5-03 supply

MOEA publishes two related tables in the same monthly workbook bundle:

- **5-04** `按油品別` — **Petroleum Products Consumption** (what we store in the DB)
- **5-03** `油品供給與轉變` — **Supply and Transformation** (= transformation output + imports)

This cell compares **all seven primary products** on **observed monthly rows only** (`is_provisional=False`, 2025+):

1. **Summary table** — mean kbd by source, DB↔5-04 gap, and 5-03/5-04 ratio per product
2. **Latest month snapshot** — side-by-side DB, 5-04, 5-03
3. **Charts** — grouped bar (mean levels), supply/consumption ratio heatmap, small-multiples time series
"""
    ),
    code(
        '''from reference.taiwan import parse_moea_consumption_workbook, parse_moea_supply_workbook
from plotly.subplots import make_subplots

RAW_DIR = PROJECT_ROOT / "data" / "raw" / "taiwan"
PATH_504 = RAW_DIR / "m_5-04石油產品消費(11504)_v113.xlsx"
PATH_503 = RAW_DIR / "m_5-03石油產品供給與轉變(11504)_v113.xlsx"

if not PATH_504.exists() or not PATH_503.exists():
    print(f"[skip] Missing workbook(s): 504={PATH_504.exists()} 503={PATH_503.exists()}")
else:
    def _to_kbd_long(partial: pd.DataFrame) -> pd.DataFrame:
        d = partial.copy()
        d["product_kind"] = d["product_native"].map(UNITS_KIND)
        d["value_kbd"] = convert_series(
            d["value"], MOEA_UNIT_NATIVE, "kbd",
            product_kind=d["product_kind"], date=d["date"],
        )
        return d

    db_obs = demand[~demand["is_provisional"]].copy()
    x504 = _to_kbd_long(parse_moea_consumption_workbook(PATH_504))
    x504 = x504[~x504["is_provisional"]]
    x503 = _to_kbd_long(parse_moea_supply_workbook(PATH_503))
    x503 = x503[~x503["is_provisional"]]

    keys = ["date", "product_native"]
    wide = (
        db_obs[keys + ["value_kbd"]].rename(columns={"value_kbd": "db"})
        .merge(x504[keys + ["value_kbd"]].rename(columns={"value_kbd": "504_cons"}), on=keys, how="outer")
        .merge(x503[keys + ["value_kbd"]].rename(columns={"value_kbd": "503_supply"}), on=keys, how="outer")
    )
    wide["db_vs_504"] = wide["db"] - wide["504_cons"]
    wide["503_over_504"] = wide["503_supply"] / wide["504_cons"]
    wide["label"] = wide["product_native"].map(DISPLAY_LABELS)

    _order = {p: i for i, p in enumerate(CHART_PRODUCTS)}
    _label_order = [DISPLAY_LABELS[p] for p in CHART_PRODUCTS]

    summary = (
        wide.groupby("product_native", as_index=False)
        .agg(
            db_mean_kbd=("db", "mean"),
            cons_504_mean_kbd=("504_cons", "mean"),
            supply_503_mean_kbd=("503_supply", "mean"),
            max_db_gap_kbd=("db_vs_504", lambda s: s.abs().max()),
            supply_over_cons_mean=("503_over_504", "mean"),
        )
        .sort_values("product_native", key=lambda s: s.map(_order))
    )
    summary["product"] = summary["product_native"].map(DISPLAY_LABELS)
    summary_tbl = summary.set_index("product")[
        ["db_mean_kbd", "cons_504_mean_kbd", "supply_503_mean_kbd", "max_db_gap_kbd", "supply_over_cons_mean"]
    ].round(1)

    print("All products — mean kbd over observed months (2025+). DB should match 5-04.")
    display(summary_tbl)

    latest = wide["date"].max()
    snap = (
        wide[wide["date"] == latest]
        .set_index("product_native")[["db", "504_cons", "503_supply", "503_over_504"]]
    )
    snap.index = snap.index.map(DISPLAY_LABELS)
    print(f"\\nLatest observed month ({latest.date()}) — kbd by source:")
    display(snap.reindex(_label_order).round(1))

    print(f"\\nDB vs 5-04 (all products): max |gap| = {wide['db_vs_504'].abs().max():.4f} kbd  (expect 0)")
    print("→ 5-04 is the correct demand/consumption table; 5-03 is domestic supply (refining + imports).")

    plot_df = summary.melt(
        id_vars="product",
        value_vars=["cons_504_mean_kbd", "supply_503_mean_kbd"],
        var_name="source",
        value_name="kbd",
    )
    plot_df["source"] = plot_df["source"].map({
        "cons_504_mean_kbd": "5-04 consumption",
        "supply_503_mean_kbd": "5-03 supply",
    })
    fig_bar = px.bar(
        plot_df,
        x="product",
        y="kbd",
        color="source",
        barmode="group",
        category_orders={"product": _label_order},
        title="Taiwan — mean monthly 5-04 consumption vs 5-03 supply by product (kbd, 2025+)",
        labels={"kbd": "kbd", "product": "Product"},
    )
    fig_bar.show()

    fig_ratio = px.bar(
        summary,
        x="product",
        y="supply_over_cons_mean",
        category_orders={"product": _label_order},
        title="Mean 5-03 supply / 5-04 consumption by product (2025+)",
        labels={"supply_over_cons_mean": "503/504 ratio", "product": "Product"},
    )
    fig_ratio.show()

    heat = wide.pivot(index="date", columns="label", values="503_over_504")[_label_order]
    fig_heat = px.imshow(
        heat.T,
        aspect="auto",
        x=heat.index.strftime("%Y-%m"),
        labels=dict(x="Month", y="Product", color="503/504"),
        title="5-03 supply / 5-04 consumption ratio by product (monthly observed)",
        color_continuous_scale="Blues",
    )
    fig_heat.show()

    n = len(CHART_PRODUCTS)
    fig_grid = make_subplots(
        rows=n, cols=1, shared_xaxes=True, vertical_spacing=0.03,
        subplot_titles=_label_order,
    )
    for i, prod in enumerate(CHART_PRODUCTS, start=1):
        sub = wide[wide["product_native"] == prod].sort_values("date")
        fig_grid.add_trace(
            go.Scatter(x=sub["date"], y=sub["504_cons"], name="5-04 consumption", mode="lines", legendgroup="504", showlegend=(i == 1)),
            row=i, col=1,
        )
        fig_grid.add_trace(
            go.Scatter(x=sub["date"], y=sub["503_supply"], name="5-03 supply", mode="lines", legendgroup="503", showlegend=(i == 1)),
            row=i, col=1,
        )
        fig_grid.add_trace(
            go.Scatter(x=sub["date"], y=sub["db"], name="DB", mode="lines", line=dict(dash="dot"), legendgroup="db", showlegend=(i == 1)),
            row=i, col=1,
        )
    fig_grid.update_layout(
        height=220 * n,
        title="All products — DB vs 5-04 consumption vs 5-03 supply (kbd, monthly observed)",
    )
    fig_grid.update_yaxes(title_text="kbd")
    fig_grid.show()
'''
    ),
    md(
        """## 1c. MOEA 5-03 supply vs JODI (supply & demand, kbd)

Compare MOEA Table **5-03** product supply to JODI on the same seven product buckets as section 7:

- **REFGROUT** — refinery output (supply-side)
- **REFGROUT + TOTIMPSB** — refinery output plus imports
- **TOTDEMO** — product demand (same flow as section 7)

Supply should sit above demand for most products; ratios near 1.0 on the demand benchmark highlight where 5-03 is closer to a demand concept than to refinery output alone (e.g. jet).
"""
    ),
    code(
        '''JODI_PARQUET = PROJECT_ROOT / "data" / "processed" / "jodi" / "jodi_secondary.parquet"
PATH_503 = PROJECT_ROOT / "data" / "raw" / "taiwan" / "m_5-03石油產品供給與轉變(11504)_v113.xlsx"

if not PATH_503.exists():
    print(f"[skip] 5-03 workbook not found at {PATH_503}")
elif not JODI_PARQUET.exists():
    print(f"[skip] JODI parquet not found at {JODI_PARQUET}")
    print("       Run: python scripts/update_jodi.py")
else:
    def _supply_to_kbd(partial: pd.DataFrame) -> pd.DataFrame:
        d = partial.copy()
        d["product_kind"] = d["product_native"].map(UNITS_KIND)
        d["value_kbd"] = convert_series(
            d["value"], MOEA_UNIT_NATIVE, "kbd",
            product_kind=d["product_kind"], date=d["date"],
        )
        return d

    x503 = _supply_to_kbd(parse_moea_supply_workbook(PATH_503))
    x503 = x503[~x503["is_provisional"]]

    supply_panels = []
    for key, spec in JODI_COMPARE_SERIES.items():
        sl = x503[x503["product_native"].isin(spec.natives)]
        if sl.empty:
            continue
        sl = (
            sl.groupby("date", as_index=False)["value_kbd"]
            .sum()
            .assign(panel=spec.panel)
        )
        supply_panels.append(sl)
    supply_panel = pd.concat(supply_panels, ignore_index=True)

    jodi = pd.read_parquet(JODI_PARQUET)
    jodi["date"] = pd.to_datetime(jodi["date"])
    jodi_codes = {spec.jodi_energy_product for spec in JODI_COMPARE_SERIES.values()}
    jodi_lookup = {spec.jodi_energy_product: spec.panel for spec in JODI_COMPARE_SERIES.values()}

    def _jodi_flow_panel(flow: str) -> pd.DataFrame:
        sub = jodi[
            (jodi["ref_area"] == "TW")
            & (jodi["flow_breakdown"] == flow)
            & (jodi["unit_measure"] == "KBD")
            & (jodi["energy_product"].isin(jodi_codes))
        ].copy()
        sub["panel"] = sub["energy_product"].map(jodi_lookup)
        sub["value_kbd"] = sub["obs_value"]
        return sub

    jodi_ref = _jodi_flow_panel("REFGROUT")
    jodi_imp = _jodi_flow_panel("TOTIMPSB")
    jodi_demo = _jodi_flow_panel("TOTDEMO")

    panels = [p for p in JODI_COMPARE_PANEL_ORDER if p in set(supply_panel["panel"])]

    fig_supply = cross_source_comparison_chart(
        df_a=supply_panel,
        df_b=jodi_ref,
        products=panels,
        product_col_a="panel",
        product_col_b="panel",
        value_col_a="value_kbd",
        value_col_b="value_kbd",
        label_a="MOEA 5-03 supply",
        label_b="JODI REFGROUT",
        title="Taiwan — MOEA 5-03 supply vs JODI refinery output (kbd)",
        units_label="kbd",
    )
    fig_supply.show()

    fig_demand = cross_source_comparison_chart(
        df_a=supply_panel,
        df_b=jodi_demo,
        products=panels,
        product_col_a="panel",
        product_col_b="panel",
        value_col_a="value_kbd",
        value_col_b="value_kbd",
        label_a="MOEA 5-03 supply",
        label_b="JODI TOTDEMO",
        title="Taiwan — MOEA 5-03 supply vs JODI demand (kbd)",
        units_label="kbd",
    )
    fig_demand.show()

    keys = ["date", "panel"]
    cmp = (
        supply_panel.rename(columns={"value_kbd": "moea_503"})
        .merge(jodi_ref[keys + ["value_kbd"]].rename(columns={"value_kbd": "jodi_refgrout"}), on=keys, how="inner")
        .merge(jodi_imp[keys + ["value_kbd"]].rename(columns={"value_kbd": "jodi_imports"}), on=keys, how="left")
        .merge(jodi_demo[keys + ["value_kbd"]].rename(columns={"value_kbd": "jodi_totdemo"}), on=keys, how="left")
    )
    cmp["jodi_ref_plus_imp"] = cmp["jodi_refgrout"] + cmp["jodi_imports"].fillna(0)

    summary = (
        cmp.groupby("panel", as_index=False)
        .agg(
            moea_503_mean=("moea_503", "mean"),
            jodi_refgrout_mean=("jodi_refgrout", "mean"),
            jodi_ref_plus_imp_mean=("jodi_ref_plus_imp", "mean"),
            jodi_totdemo_mean=("jodi_totdemo", "mean"),
        )
    )
    summary["503_over_refgrout"] = summary["moea_503_mean"] / summary["jodi_refgrout_mean"]
    summary["503_over_ref_imp"] = summary["moea_503_mean"] / summary["jodi_ref_plus_imp_mean"]
    summary["503_over_totdemo"] = summary["moea_503_mean"] / summary["jodi_totdemo_mean"]
    _panel_order = {p: i for i, p in enumerate(JODI_COMPARE_PANEL_ORDER)}
    summary = summary.sort_values("panel", key=lambda s: s.map(_panel_order))

    print("Mean kbd over overlapping months — MOEA 5-03 vs JODI supply- and demand-side flows:")
    display(summary.round(2))

    ratio_long = summary.melt(
        id_vars="panel",
        value_vars=["503_over_refgrout", "503_over_ref_imp", "503_over_totdemo"],
        var_name="benchmark",
        value_name="ratio",
    ).assign(
        benchmark=lambda d: d["benchmark"].map({
            "503_over_refgrout": "503 / REFGROUT",
            "503_over_ref_imp": "503 / (REFGROUT + imports)",
            "503_over_totdemo": "503 / TOTDEMO",
        })
    )
    fig_ratio = px.bar(
        ratio_long,
        x="panel",
        y="ratio",
        color="benchmark",
        barmode="group",
        category_orders={"panel": panels},
        title="MOEA 5-03 / JODI benchmarks by product (mean ratio)",
        labels={"ratio": "Ratio", "panel": "Product", "benchmark": "Benchmark"},
    )
    fig_ratio.add_hline(y=1.0, line_dash="dot", line_color="gray")
    fig_ratio.show()
'''
    ),
    md("## 2. Headline total (incl. naphtha)"),
    code(
        '''total = headline.groupby(["date", "is_provisional"], as_index=False)["value_kbd"].sum()
obs = total[~total["is_provisional"]]
prov = total[total["is_provisional"]]

fig = go.Figure()
fig.add_trace(go.Scatter(x=obs["date"], y=obs["value_kbd"], mode="lines", name="Observed monthly"))
if len(prov):
    fig.add_trace(go.Scatter(x=prov["date"], y=prov["value_kbd"], mode="lines", name="Annual imputed", line=dict(dash="dot")))
roll = total.groupby("date", as_index=False)["value_kbd"].sum()["value_kbd"].rolling(12, min_periods=6).mean()
fig.add_trace(go.Scatter(x=total["date"], y=roll, mode="lines", name="12m MA", line=dict(color="gray")))
fig.update_layout(title="Taiwan petroleum demand — headline (kbd)", yaxis_title="kbd")
fig.show()
'''
    ),
    md("## 3. Native products"),
    code(
        '''mp = headline[headline["product_native"].isin(CHART_PRODUCTS)].copy()
fig = px.line(
    mp,
    x="date",
    y="value_kbd",
    color="product_native",
    line_dash=mp["is_provisional"].map({True: "dot", False: "solid"}),
    labels={"product_native": "Product", "value_kbd": "kbd"},
    title="Taiwan demand by native product (kbd)",
)
fig.show()
'''
    ),
    md("## 4. Canonical rollup"),
    code(
        '''fig = px.line(
    demand_canonical,
    x="date",
    y="value_kbd",
    color="panel",
    line_dash=demand_canonical["is_provisional"].map({True: "dot", False: "solid"}),
    title="Taiwan demand — canonical products (kbd)",
)
fig.show()
'''
    ),
    md("## 5. Recent trends (last 24 months)"),
    code(
        '''cutoff = headline["date"].max() - pd.DateOffset(months=23)
recent = headline[(headline["date"] >= cutoff) & headline["product_native"].isin(CHART_PRODUCTS)].copy()
pivot = recent.pivot_table(index="date", columns="product_native", values="value_kbd", aggfunc="sum")
mom = pivot.pct_change() * 100
yoy = pivot.pct_change(12) * 100
display(pivot.tail(6).round(1))
print("\\nMoM % (latest month):")
print(mom.iloc[-1].dropna().round(2).to_string())
print("\\nYoY % (latest month):")
print(yoy.iloc[-1].dropna().round(2).to_string())
'''
    ),
    md("## 6. Seasonality by year"),
    code(
        '''DEFAULT_SEASONALITY_VIEW = "canonical"
view_picker = widgets.Dropdown(options=["native", "canonical"], value=DEFAULT_SEASONALITY_VIEW, description="View:")

def plot_seasonality(view: str = DEFAULT_SEASONALITY_VIEW) -> None:
    season_df, product_col, products, labels, suffix = seasonality_chart_inputs(
        view, demand=demand, demand_canonical=demand_canonical
    )
    season_df = season_df[~season_df["is_provisional"]].copy()
    if season_df.empty:
        print("[skip] No observed monthly rows for seasonality yet.")
        return
    fig = seasonality_by_year_chart(
        season_df,
        product_col=product_col,
        products=products,
        value_col="value_kbd",
        product_labels=labels,
        title=f"Taiwan demand — seasonality ({suffix})",
    )
    fig.show()

widgets.interact(plot_seasonality, view=view_picker)
'''
    ),
    md("## 7. MOEA vs JODI (TOTDEMO, kbd)"),
    code(
        '''JODI_PARQUET = PROJECT_ROOT / "data" / "processed" / "jodi" / "jodi_secondary.parquet"
if not JODI_PARQUET.exists():
    print(f"[skip] JODI parquet not found at {JODI_PARQUET}")
else:
    jodi = pd.read_parquet(JODI_PARQUET)
    jodi["date"] = pd.to_datetime(jodi["date"])

    moea_panels = []
    for key, spec in JODI_COMPARE_SERIES.items():
        sl = moea_series_for_jodi(demand, key, value_col="value_kbd")
        if sl.empty:
            continue
        sl = sl.assign(panel=spec.panel)
        moea_panels.append(sl)
    moea_panel = pd.concat(moea_panels, ignore_index=True) if moea_panels else pd.DataFrame()

    jodi_codes = {spec.jodi_energy_product for spec in JODI_COMPARE_SERIES.values()}
    jodi_tw = jodi[
        (jodi["ref_area"] == "TW")
        & (jodi["flow_breakdown"] == "TOTDEMO")
        & (jodi["unit_measure"] == "KBD")
        & (jodi["energy_product"].isin(jodi_codes))
    ].copy()
    jodi_lookup = {spec.jodi_energy_product: spec.panel for spec in JODI_COMPARE_SERIES.values()}
    jodi_tw["panel"] = jodi_tw["energy_product"].map(jodi_lookup)
    jodi_tw["value_kbd"] = jodi_tw["obs_value"]

    panels = [p for p in JODI_COMPARE_PANEL_ORDER if p in set(moea_panel.get("panel", []))]
    fig = cross_source_comparison_chart(
        df_a=moea_panel,
        df_b=jodi_tw,
        products=panels,
        product_col_a="panel",
        product_col_b="panel",
        value_col_a="value_kbd",
        value_col_b="value_kbd",
        label_a="MOEA (Taiwan)",
        label_b="JODI",
        title="Taiwan TOTDEMO — MOEA vs JODI (kbd)",
        units_label="kbd",
    )
    fig.show()
'''
    ),
    md(
        """## 8. Jet fuel vs Kayrros

Three-way check on observed MOEA months (2025+):

- **5-04 consumption** — domestic jet fuel consumption (parquet / Table 5-04)
- **5-03 supply** — jet supply & transformation (Table 5-03 workbook)
- **Kayrros** — flight-based nowcaster (`scope='Taiwan (Province of China)'`)

Kayrros tracks in-flight burn; MOEA 5-04 is very low vs both supply and Kayrros — useful context for which official line item is comparable to the nowcaster.
"""
    ),
    code(
        '''import os

from plotly.subplots import make_subplots
from reference.taiwan import parse_moea_supply_workbook

PATH_503 = PROJECT_ROOT / "data" / "raw" / "taiwan" / "m_5-03石油產品供給與轉變(11504)_v113.xlsx"
KAYROS_ROOT = PROJECT_ROOT.parent / "kayros" / "jet_fuel"
DB_PATH = KAYROS_ROOT / "data" / "jet_fuel.duckdb"
KAYROS_SCOPE = "Taiwan (Province of China)"

if not DB_PATH.exists():
    print(f"[skip] Kayrros DB not found at {DB_PATH}")
    print("       Build/update kayros/jet_fuel/data/jet_fuel.duckdb first.")
else:
    if str(KAYROS_ROOT) not in sys.path:
        sys.path.insert(0, str(KAYROS_ROOT))
    os.environ.setdefault("JET_FUEL_DB_PATH", str(DB_PATH))
    from src.export import get_consumption  # noqa: E402

    jet_cons = demand[
        (demand["product_native"] == "jet_fuel") & (~demand["is_provisional"])
    ].sort_values("date")
    moea_cons = jet_cons.loc[:, ["date", "value_kbd"]].rename(columns={"value_kbd": "kbd"})

    moea_sup = pd.DataFrame(columns=["date", "kbd"])
    if PATH_503.exists():
        x503 = parse_moea_supply_workbook(PATH_503)
        x503 = x503[
            (x503["product_native"] == "jet_fuel") & (~x503["is_provisional"])
        ].copy()
        x503["product_kind"] = x503["product_native"].map(UNITS_KIND)
        x503["value_kbd"] = convert_series(
            x503["value"], MOEA_UNIT_NATIVE, "kbd",
            product_kind=x503["product_kind"], date=x503["date"],
        )
        moea_sup = (
            x503.loc[:, ["date", "value_kbd"]]
            .rename(columns={"value_kbd": "kbd"})
            .sort_values("date")
        )
    else:
        print(f"[warn] 5-03 workbook not found — supply line omitted ({PATH_503.name})")

    now_raw = get_consumption(
        scope_type="country",
        scope=KAYROS_SCOPE,
        freq="monthly",
        metric="avg_kbd",
        drop_incomplete=True,
    )
    kayrros = (
        now_raw.rename(columns={"period_start": "date", "value": "kbd"})
        .loc[:, ["date", "kbd"]]
        .sort_values("date")
        .reset_index(drop=True)
    )

    overlap = (
        moea_cons.rename(columns={"kbd": "cons_kbd"})
        .merge(moea_sup.rename(columns={"kbd": "sup_kbd"}), on="date", how="outer")
        .merge(kayrros.rename(columns={"kbd": "kay_kbd"}), on="date", how="inner")
        .sort_values("date")
    )

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08,
        row_heights=[0.62, 0.38],
        subplot_titles=(
            "Jet kbd — MOEA 5-04 consumption, 5-03 supply, Kayrros",
            "Gap vs Kayrros (kbd)",
        ),
    )
    fig.add_trace(
        go.Scatter(x=moea_cons["date"], y=moea_cons["kbd"], name="MOEA 5-04 consumption", mode="lines"),
        row=1, col=1,
    )
    if not moea_sup.empty:
        fig.add_trace(
            go.Scatter(x=moea_sup["date"], y=moea_sup["kbd"], name="MOEA 5-03 supply", mode="lines"),
            row=1, col=1,
        )
    fig.add_trace(
        go.Scatter(x=kayrros["date"], y=kayrros["kbd"], name="Kayrros", mode="lines"),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=overlap["date"], y=overlap["kay_kbd"] - overlap["cons_kbd"],
            name="Kayrros − 5-04 consumption", mode="lines", line=dict(dash="dot"),
        ),
        row=2, col=1,
    )
    if not moea_sup.empty:
        fig.add_trace(
            go.Scatter(
                x=overlap["date"], y=overlap["kay_kbd"] - overlap["sup_kbd"],
                name="Kayrros − 5-03 supply", mode="lines",
            ),
            row=2, col=1,
        )
    fig.update_layout(height=680, title="Taiwan jet fuel: MOEA consumption & supply vs Kayrros")
    fig.update_yaxes(title_text="kbd", row=1, col=1)
    fig.update_yaxes(title_text="kbd", row=2, col=1)
    fig.show()

    if overlap.empty:
        print(f"[warn] No overlapping months — check scope={KAYROS_SCOPE!r}")
    else:
        stats = {
            "mean_kbd": {
                "5-04 consumption": overlap["cons_kbd"].mean(),
                "5-03 supply": overlap["sup_kbd"].mean() if not moea_sup.empty else float("nan"),
                "Kayrros": overlap["kay_kbd"].mean(),
            },
            "mean_abs_gap_vs_kayrros": {
                "5-04 consumption": (overlap["kay_kbd"] - overlap["cons_kbd"]).abs().mean(),
                "5-03 supply": (overlap["kay_kbd"] - overlap["sup_kbd"]).abs().mean() if not moea_sup.empty else float("nan"),
            },
        }
        summary = pd.DataFrame(stats).round(1)
        print(f"Overlapping months: {len(overlap)}")
        display(summary)

        if not moea_sup.empty:
            print(
                f"Mean supply / consumption: {(overlap['sup_kbd'] / overlap['cons_kbd']).mean():.1f}x  "
                f"(5-03 is domestic supply; 5-04 is a narrow consumption definition)"
            )
'''
    ),
]

nb = {
    "nbformat": 4,
    "nbformat_minor": 5,
    "metadata": {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python"},
    },
    "cells": cells,
}

OUT.write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding="utf-8")
print(f"wrote {OUT}")
