"""Generate notebooks/26_iea_oecd_inventories.ipynb (no saved outputs)."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "notebooks" / "26_iea_oecd_inventories.ipynb"


def md(text: str) -> dict:
    return {
        "cell_type": "markdown",
        "metadata": {},
        "source": text.splitlines(keepends=True),
        "id": None,
    }


def code(text: str) -> dict:
    return {
        "cell_type": "code",
        "metadata": {},
        "source": text.splitlines(keepends=True),
        "outputs": [],
        "execution_count": None,
        "id": None,
    }


cells = [
    md(
        """# IEA OECD inventories (MOSSTOCKS)

Closing stocks from `data/raw/iea/MOSSTOCKS.csv`.

Rebuilds the Government / Industry / Total sheet for **every product**, and charts
where stocks sit after the 2022 SPR draws.

- Unit: **mb** (source is kb)
- SPR = Government stocks
- Total (Industry + SPR) = Total stocks
"""
    ),
    code(
        r'''from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from IPython.display import display, Markdown


def _resolve_project_root() -> Path:
    here = Path.cwd()
    for candidate in [here, *here.parents]:
        if (candidate / "data" / "raw" / "iea" / "MOSSTOCKS.csv").exists():
            return candidate
        nested = candidate / "country_oil_scraper"
        if (nested / "data" / "raw" / "iea" / "MOSSTOCKS.csv").exists():
            return nested
    raise RuntimeError(f"Could not locate project root from cwd: {here}")


ROOT = _resolve_project_root()
RAW = ROOT / "data" / "raw" / "iea" / "MOSSTOCKS.csv"

OECD_AGG = {"OECD Total", "OECD Americas", "OECD Europe", "OECD Asia Oceania"}
CAT_GOV, CAT_IND, CAT_TOT = "Government stocks", "Industry stocks", "Total stocks"
PRE_DRAW = "2021-12"

PRODUCT_ORDER = [
    "Crude oil",
    "Primary oil",
    "Oil products",
    "Oil and oil products",
    "Motor gasoline",
    "Middle distillates",
    "Residual fuel oil",
    "Non Crude Oil primary oil products",
    "Other non-specified secondary oil products",
]


def month_label(ym: str) -> str:
    return pd.Timestamp(f"{ym}-01").strftime("%b-%y")


def to_dt(ym: str) -> pd.Timestamp:
    return pd.Timestamp(f"{ym}-01")


stocks = pd.read_csv(
    RAW,
    usecols=["Country", "Product", "Stock Category", "TIME_PERIOD", "OBS_VALUE"],
    low_memory=False,
)
stocks["TIME_PERIOD"] = stocks["TIME_PERIOD"].astype(str)
stocks["OBS_VALUE"] = pd.to_numeric(stocks["OBS_VALUE"], errors="coerce")
stocks["mb"] = stocks["OBS_VALUE"] / 1000.0

products = [p for p in PRODUCT_ORDER if p in set(stocks["Product"])]
products += sorted(set(stocks["Product"]) - set(products))
months_all = sorted(stocks["TIME_PERIOD"].unique())
latest = months_all[-1]

print(f"rows={len(stocks):,}  products={len(products)}  {months_all[0]} -> {latest}")
print(products)
'''
    ),
    md("## Coverage (country counts by month)"),
    code(
        r'''def n_countries(product: str, category: str, month: str) -> int:
    m = (
        (stocks["Product"] == product)
        & (stocks["Stock Category"] == category)
        & (stocks["TIME_PERIOD"] == month)
        & (~stocks["Country"].isin(OECD_AGG))
    )
    return stocks.loc[m, "Country"].nunique()


recent = months_all[-6:]
cov_rows = []
for prod in ["Crude oil", "Oil and oil products"]:
    for cat in [CAT_GOV, CAT_IND, CAT_TOT]:
        row = {"product": prod, "category": cat}
        for m in recent:
            row[m] = n_countries(prod, cat, m)
        cov_rows.append(row)

cov = pd.DataFrame(cov_rows)
display(Markdown(f"Latest month in file: **{latest}** (May-26 can still be incomplete)"))
display(cov)
'''
    ),
    md(
        """## Inventory table

Layout: Government countries → Total Gvt → Industry countries → Total Industry → **Total (Industry + SPR)**.

Section totals = **OECD Total** from the file. Country index labels are unique (`G | …` / `I | …`) so styling does not break.
"""
    ),
    code(
        r'''def _wide_countries(product: str, category: str, months: list[str], prefix: str) -> pd.DataFrame:
    sub = stocks[
        (stocks["Product"] == product)
        & (stocks["Stock Category"] == category)
        & (stocks["TIME_PERIOD"].isin(months))
        & (~stocks["Country"].isin(OECD_AGG))
    ]
    if sub.empty:
        return pd.DataFrame(columns=[month_label(m) for m in months])

    wide = (
        sub.pivot_table(index="Country", columns="TIME_PERIOD", values="mb", aggfunc="sum")
        .reindex(columns=months)
        .dropna(how="all")
    )
    wide = wide.sort_values(wide.columns[-1], ascending=False, na_position="last")
    wide.index = [f"{prefix} | {c}" for c in wide.index]
    wide.columns = [month_label(c) for c in wide.columns]
    return wide


def _oecd_total_row(product: str, category: str, months: list[str], label: str) -> pd.DataFrame:
    sub = stocks[
        (stocks["Product"] == product)
        & (stocks["Stock Category"] == category)
        & (stocks["Country"] == "OECD Total")
        & (stocks["TIME_PERIOD"].isin(months))
    ]
    vals = {}
    for m in months:
        hit = sub.loc[sub["TIME_PERIOD"] == m, "mb"]
        vals[month_label(m)] = float(hit.iloc[0]) if len(hit) else np.nan
    return pd.DataFrame([vals], index=[label])


def build_inventory_table(product: str, n_months: int = 7) -> pd.DataFrame:
    months = months_all[-n_months:]
    cols = [month_label(m) for m in months]
    blank = pd.DataFrame([[np.nan] * len(cols)], index=["— Government —"], columns=cols)

    parts = [
        blank,
        _wide_countries(product, CAT_GOV, months, "G"),
        _oecd_total_row(product, CAT_GOV, months, "Total Gvt"),
        pd.DataFrame([[np.nan] * len(cols)], index=["— Industry —"], columns=cols),
        _wide_countries(product, CAT_IND, months, "I"),
        _oecd_total_row(product, CAT_IND, months, "Total Industry"),
        _oecd_total_row(product, CAT_TOT, months, "Total (Industry + SPR)"),
    ]
    out = pd.concat([p for p in parts if p is not None and len(p.columns)])
    out.index.name = product
    return out.round(1)


def show_table(product: str, n_months: int = 7):
    tbl = build_inventory_table(product, n_months=n_months)
    display(Markdown(f"### {product} (mb)"))
    # plain display — avoids Styler issues with section rows
    with pd.option_context("display.max_rows", 200, "display.float_format", "{:,.1f}".format):
        display(tbl)


# preview all products (latest 7 months)
for prod in products:
    show_table(prod, n_months=7)
'''
    ),
    md("## OECD levels since 2019 (post-draw)"),
    code(
        r'''def plot_oecd_levels(product: str, start: str = "2019-01") -> go.Figure:
    sub = stocks[
        (stocks["Country"] == "OECD Total")
        & (stocks["Product"] == product)
        & (stocks["TIME_PERIOD"] >= start)
    ].copy()
    wide = (
        sub.pivot_table(index="TIME_PERIOD", columns="Stock Category", values="mb", aggfunc="sum")
        .sort_index()
    )
    wide.index = pd.to_datetime(wide.index + "-01")

    fig = go.Figure()
    for col, name in [
        (CAT_GOV, "Government (SPR)"),
        (CAT_IND, "Industry"),
        (CAT_TOT, "Total (Industry + SPR)"),
    ]:
        if col in wide.columns:
            fig.add_trace(go.Scatter(x=wide.index, y=wide[col], mode="lines", name=name))

    # add_vline + Timestamp annotations break on some plotly/pandas combos — use shapes
    for x, label in [("2022-01-01", "2022"), (f"{PRE_DRAW}-01", "end-2021")]:
        fig.add_shape(
            type="line",
            x0=x,
            x1=x,
            y0=0,
            y1=1,
            yref="paper",
            line=dict(dash="dot", width=1),
        )
        fig.add_annotation(x=x, y=1.02, yref="paper", text=label, showarrow=False, font=dict(size=10))
    fig.update_layout(
        title=f"OECD Total - {product} (mb)",
        xaxis_title="Month",
        yaxis_title="mb",
        hovermode="x unified",
        height=400,
        template="plotly_white",
    )
    return fig


for prod in ["Crude oil", "Oil and oil products", "Oil products", "Middle distillates", "Motor gasoline"]:
    if prod in products:
        fig = plot_oecd_levels(prod)
        fig.show()
'''
    ),
    md("## Change vs end-2021 (OECD Total, mb)"),
    code(
        r'''# use latest month that has OECD Total for oil-and-oil-products total stocks
end = latest
for m in reversed(months_all):
    hit = stocks[
        (stocks["Country"] == "OECD Total")
        & (stocks["Product"] == "Oil and oil products")
        & (stocks["Stock Category"] == CAT_TOT)
        & (stocks["TIME_PERIOD"] == m)
        & stocks["mb"].notna()
    ]
    if len(hit):
        end = m
        break


def oecd_mb(product: str, category: str, month: str) -> float:
    hit = stocks[
        (stocks["Country"] == "OECD Total")
        & (stocks["Product"] == product)
        & (stocks["Stock Category"] == category)
        & (stocks["TIME_PERIOD"] == month)
    ]["mb"]
    return float(hit.iloc[0]) if len(hit) else np.nan


rows = []
for product in products:
    for cat, label in [(CAT_GOV, "Government (SPR)"), (CAT_IND, "Industry"), (CAT_TOT, "Total (Industry + SPR)")]:
        b, e = oecd_mb(product, cat, PRE_DRAW), oecd_mb(product, cat, end)
        rows.append(
            {
                "product": product,
                "category": label,
                "base_mb": b,
                "latest_mb": e,
                "change_mb": e - b if pd.notna(b) and pd.notna(e) else np.nan,
            }
        )

dd = pd.DataFrame(rows)
display(Markdown(f"**{PRE_DRAW} → {end}**"))
chg = dd.pivot_table(index="product", columns="category", values="change_mb")
chg = chg.reindex(index=products, columns=["Government (SPR)", "Industry", "Total (Industry + SPR)"])
display(chg.round(1))
'''
    ),
    md("## Who drove the government draw?"),
    code(
        r'''def gov_change(product: str, base: str = PRE_DRAW, end_m: str = end) -> pd.DataFrame:
    sub = stocks[
        (stocks["Product"] == product)
        & (stocks["Stock Category"] == CAT_GOV)
        & (~stocks["Country"].isin(OECD_AGG))
        & (stocks["TIME_PERIOD"].isin([base, end_m]))
    ]
    wide = sub.pivot_table(index="Country", columns="TIME_PERIOD", values="mb", aggfunc="sum")
    if base not in wide.columns or end_m not in wide.columns:
        return pd.DataFrame()
    out = pd.DataFrame({"change_mb": wide[end_m] - wide[base]}).dropna()
    return out.sort_values("change_mb")


for prod in ["Crude oil", "Oil and oil products", "Oil products"]:
    ch = gov_change(prod)
    if ch.empty:
        print(prod, ": no data")
        continue
    fig = go.Figure(
        go.Bar(
            x=ch["change_mb"],
            y=ch.index.astype(str),
            orientation="h",
            marker_color=["#c0392b" if v < 0 else "#27ae60" for v in ch["change_mb"]],
        )
    )
    fig.update_layout(
        title=f"Government stocks change — {prod} ({PRE_DRAW} → {end}, mb)",
        xaxis_title="Change (mb)",
        height=max(300, 24 * len(ch) + 80),
        template="plotly_white",
        margin=dict(l=140),
    )
    fig.show()
'''
    ),
    md("## Latest vs end-2021 by product (Total Industry + SPR)"),
    code(
        r'''tot = dd[dd["category"] == "Total (Industry + SPR)"].set_index("product").reindex(products)
fig = go.Figure()
fig.add_trace(go.Bar(name=PRE_DRAW, x=tot.index.astype(str), y=tot["base_mb"]))
fig.add_trace(go.Bar(name=end, x=tot.index.astype(str), y=tot["latest_mb"]))
fig.update_layout(
    barmode="group",
    title="OECD Total (Industry + SPR) by product (mb)",
    yaxis_title="mb",
    xaxis_tickangle=-30,
    height=450,
    template="plotly_white",
)
fig.show()
'''
    ),
    md("## YoY heatmap — Crude oil total stocks"),
    code(
        r'''def yoy_matrix(product: str, category: str, n_months: int = 18) -> pd.DataFrame:
    months = months_all[-n_months:]
    need = set(months)
    for m in months:
        need.add(f"{int(m[:4]) - 1}{m[4:]}")
    sub = stocks[
        (stocks["Product"] == product)
        & (stocks["Stock Category"] == category)
        & (~stocks["Country"].isin(OECD_AGG))
        & (stocks["TIME_PERIOD"].isin(need))
    ]
    full = sub.pivot_table(index="Country", columns="TIME_PERIOD", values="mb", aggfunc="sum")
    yoy = pd.DataFrame(index=full.index)
    for m in months:
        prev = f"{int(m[:4]) - 1}{m[4:]}"
        if prev in full.columns and m in full.columns:
            yoy[month_label(m)] = full[m] - full[prev]
    yoy = yoy.dropna(how="all")
    if len(yoy.columns):
        yoy = yoy.sort_values(yoy.columns[-1], ascending=True, na_position="first")
    return yoy


for product, category in [
    ("Crude oil", CAT_TOT),
    ("Crude oil", CAT_GOV),
    ("Oil and oil products", CAT_TOT),
]:
    yoy = yoy_matrix(product, category)
    if yoy.empty:
        print(product, category, ": empty")
        continue
    fig = px.imshow(
        yoy.values,
        x=list(yoy.columns),
        y=yoy.index.astype(str).tolist(),
        color_continuous_scale="RdBu",
        color_continuous_midpoint=0,
        aspect="auto",
        labels=dict(color="YoY mb"),
        title=f"{product} — {category} YoY (mb)",
    )
    fig.update_layout(height=max(380, 20 * len(yoy) + 100), template="plotly_white")
    fig.show()
'''
    ),
    md("## Optional CSV export"),
    code(
        r'''EXPORT = False

if EXPORT:
    out_dir = ROOT / "data" / "processed" / "iea_inventories"
    out_dir.mkdir(parents=True, exist_ok=True)
    for prod in products:
        safe = prod.lower().replace(" ", "_")
        path = out_dir / f"oecd_stocks_{safe}.csv"
        build_inventory_table(prod, n_months=7).to_csv(path)
        print("wrote", path.relative_to(ROOT))
else:
    print("Set EXPORT = True to write CSVs")
'''
    ),
]


# assign stable ids
for i, c in enumerate(cells):
    c["id"] = f"c{i:02d}"

nb = {
    "nbformat": 4,
    "nbformat_minor": 5,
    "metadata": {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python", "pygments_lexer": "ipython3"},
    },
    "cells": cells,
}

OUT.write_text(json.dumps(nb, indent=1), encoding="utf-8")
print(f"wrote {OUT.relative_to(ROOT)}")
