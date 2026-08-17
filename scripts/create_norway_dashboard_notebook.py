"""Generate notebooks/25_norway_demand_dashboard.ipynb (no saved outputs)."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "notebooks" / "25_norway_demand_dashboard.ipynb"


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
        """# Norway SSB Demand Dashboard

Monthly petroleum product sales from Statistics Norway **Table 3**, via
`scripts/update_norway.py` → `data/processed/norway/norway_ssb_sales.parquet`.

History is stitched from three StatBank tables (**03687** → **11174** → **13585**).
Stored values use **petroleum incl. bio components** on the current table (best
match to JODI product lines).

## Sections
1. **Setup** — load parquet, ML → kbd
2. **Coverage** — first/last month per native product
3. **Headline demand** — canonical total (kbd)
4. **Native products (current taxonomy)**
5. **Kerosene breakdown** — heating vs light heating vs jet (kept separate)
6. **Canonical rollup**
7. **Recent trends** — MoM / YoY snapshot
8. **Seasonality by year**
9. **SSB vs JODI** — TOTDEMO panels; kerosene vs **X_OTHKERO** (not combined KEROSENE)
10. **Jet fuel vs Kayrros** — SSB jet kerosene vs flight nowcaster (`scope='NO'`)
11. **EV adoption** — new registrations + fleet stock ([Robbie Andrew](https://robbieandrew.github.io/EV/), SSB 07849)
12. **EV vs road fuel** — BEV share vs gasoline + road diesel demand
13. **Impact snapshot** — YoY changes and correlation from 2011

## Conventions
- Native unit **ML** (million litres). Charts use **kbd**.
- All rows are SSB preliminary monthly figures (`is_provisional=True`).
- Monthly diesel/marine figures from **2020** onward were revised by SSB and are
  not comparable to earlier monthly series (vertical line on charts).
- JODI kerosene panel compares derived **X_OTHKERO** to Norway **heating kerosene**
  natives only — jet fuel is a separate panel vs **JETKERO**.
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
        if (candidate / "scripts" / "update_norway.py").exists():
            return candidate
        if (candidate / "country_oil_scraper" / "scripts" / "update_norway.py").exists():
            return candidate / "country_oil_scraper"
    raise RuntimeError(f"Could not locate project root from cwd: {here}")

PROJECT_ROOT = _resolve_project_root()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from analytics import cross_source_comparison_chart, seasonality_by_year_chart
from analytics.products import CANONICAL_KIND_LABEL, SUBCATEGORY_TO_PRODUCT_KIND
from analytics.units import convert_series
from reference.norway import (
    CHART_PRODUCTS,
    CURRENT_ERA_FROM,
    DISPLAY_LABELS,
    EV_ANALYSIS_FROM,
    EV_REGISTRATIONS_URL,
    JODI_COMPARE_PANEL_ORDER,
    JODI_COMPARE_SERIES,
    JODI_REF_AREA,
    KEROSENE_BREAKDOWN_NATIVES,
    MONTHLY_REVISION_FROM,
    ROAD_FUEL_NATIVES,
    SSB_METRIC_TYPE,
    SSB_UNIT_NATIVE,
    UNITS_KIND,
    coverage_by_series,
    add_plotly_date_vline,
    ev_road_fuel_panel,
    fleet_road_fuel_panel,
    fleet_to_monthly,
    load_ev_registrations,
    load_norway_fleet_composition,
    road_fuel_series,
    seasonality_chart_inputs,
    ssb_series_for_jodi,
)

PARQUET_PATH = PROJECT_ROOT / "data" / "processed" / "norway" / "norway_ssb_sales.parquet"

df = pd.read_parquet(PARQUET_PATH)
df["date"] = pd.to_datetime(df["date"])
demand = df[df["metric_type"] == SSB_METRIC_TYPE].copy()

demand["product_kind"] = demand["product_native"].map(UNITS_KIND)
demand["value_kbd"] = convert_series(
    demand["value"],
    SSB_UNIT_NATIVE,
    "kbd",
    product_kind=demand["product_kind"],
    date=demand["date"],
)

demand_canonical = (
    demand[demand["product_canonical"].notna()]
    .groupby(["date", "product_canonical", "is_provisional"], as_index=False)["value_kbd"]
    .sum()
)
demand_canonical["panel"] = demand_canonical["product_canonical"].map(
    lambda s: CANONICAL_KIND_LABEL.get(SUBCATEGORY_TO_PRODUCT_KIND.get(s, ""), s)
)

coverage = coverage_by_series(demand)

print(f"Loaded: {len(df):,} rows  ({df['date'].min().date()} -> {df['date'].max().date()})")
print(f"Products: {demand['product_native'].nunique()} natives")
print(f"All rows provisional: {demand['is_provisional'].all()}")
'''
    ),
    md("## 2. Coverage — native product history"),
    code(
        '''display(
    coverage.assign(
        first_month=lambda d: d["first_month"].dt.strftime("%Y-%m"),
        last_month=lambda d: d["last_month"].dt.strftime("%Y-%m"),
    )
)
print(
    "Bridge-era split (2010–2020): Heating and lighting kerosene vs Light heating oils. "
    "Current era (2021+): combined heating kerosene line."
)
'''
    ),
    md("## 3. Headline — total demand (canonical, kbd)"),
    code(
        '''headline_ts = (
    demand_canonical.groupby(["date", "is_provisional"], as_index=False)["value_kbd"]
    .sum()
    .sort_values("date")
)
fig = px.line(
    headline_ts,
    x="date",
    y="value_kbd",
    title="Norway total petroleum demand — SSB Table 3 (canonical sum, kbd)",
)
fig.update_traces(connectgaps=False)
add_plotly_date_vline(
    fig,
    MONTHLY_REVISION_FROM,
    annotation_text="SSB monthly revision from 2020",
    line_dash="dash",
    line_color="gray",
)
add_plotly_date_vline(
    fig,
    CURRENT_ERA_FROM,
    annotation_text="Current table 13585",
    line_dash="dot",
    line_color="steelblue",
)
fig.show()
'''
    ),
    md("## 4. Native products — current taxonomy (kbd)"),
    code(
        '''plot_df = demand[demand["product_native"].isin(CHART_PRODUCTS)].copy()
plot_df["label"] = plot_df["product_native"].map(DISPLAY_LABELS)
fig = px.line(
    plot_df,
    x="date",
    y="value_kbd",
    color="label",
    title="Norway demand by product — SSB natives (current taxonomy, kbd)",
)
fig.update_traces(connectgaps=False)
add_plotly_date_vline(fig, MONTHLY_REVISION_FROM, line_dash="dash", line_color="gray")
fig.show()
'''
    ),
    md(
        """## 5. Kerosene breakdown

Heating-related lines are kept separate from **jet kerosene** so you can see how
bridge-era split products compare before the 2021 combined label."""
    ),
    code(
        '''kero_df = demand[demand["product_native"].isin(KEROSENE_BREAKDOWN_NATIVES)].copy()
kero_df["label"] = kero_df["product_native"].map(DISPLAY_LABELS)
fig_k = px.line(
    kero_df,
    x="date",
    y="value_kbd",
    color="label",
    title="Norway kerosene breakdown — heating vs jet (kbd)",
)
fig_k.update_traces(connectgaps=False)
add_plotly_date_vline(fig_k, CURRENT_ERA_FROM, line_dash="dot", line_color="steelblue")
fig_k.show()
'''
    ),
    md("## 6. Canonical rollup (kbd)"),
    md(
        """**Note:** If diesel shows a ~2× plateau in 2010–2016, re-run
        `python scripts/update_norway.py --bootstrap`. Legacy table **03687**
        coarse ``Diesel`` was being summed alongside bridge-era auto-diesel
        splits — now dropped when finer natives exist for that month."""
    ),
    code(
        '''fig_c = px.line(
    demand_canonical,
    x="date",
    y="value_kbd",
    color="panel",
    title="Norway demand by canonical product (kbd)",
)
fig_c.update_traces(connectgaps=False)
add_plotly_date_vline(fig_c, MONTHLY_REVISION_FROM, line_dash="dash", line_color="gray")
fig_c.show()
'''
    ),
    md("## 7. Recent trends (latest month MoM / YoY)"),
    code(
        '''def _product_change_rows(
    frame: pd.DataFrame,
    *,
    product_col: str,
    labels: dict[str, str] | None = None,
) -> list[dict[str, object]]:
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


view_picker = widgets.Dropdown(
    options=[("Native (current taxonomy)", "native"), ("Canonical", "canonical")],
    value="native",
    description="View:",
)


def show_recent_changes(view: str = "native") -> None:
    if view == "native":
        frame = demand[demand["product_native"].isin(CHART_PRODUCTS)].copy()
        rows = _product_change_rows(
            frame, product_col="product_native", labels=DISPLAY_LABELS
        )
    else:
        frame = demand_canonical[demand_canonical["panel"].notna()].copy()
        rows = _product_change_rows(frame, product_col="panel")

    total = (
        demand_canonical.groupby("date", as_index=False)["value_kbd"]
        .sum()
        .assign(_key="Total (canonical)")
    )
    rows.extend(_product_change_rows(total, product_col="_key"))
    tbl = pd.DataFrame(rows).sort_values("level_kbd", ascending=False)
    display(
        tbl.assign(month=lambda d: d["month"].dt.strftime("%Y-%m")).round(
            {"level_kbd": 1, "mom_kbd": 1, "yoy_kbd": 1, "mom_pct": 1, "yoy_pct": 1}
        )
    )


widgets.interact(show_recent_changes, view=view_picker)
'''
    ),
    md("## 8. Seasonality by year"),
    code(
        '''season_view = widgets.Dropdown(
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
        default_visible_prior_years=5,
        units_label="kbd",
        title=f"Norway demand — seasonality ({suffix})",
    )
    fig.show()


widgets.interact(plot_seasonality, view=season_view)
'''
    ),
    md(
        """## 9. SSB vs JODI (NO, TOTDEMO, kbd)

- **Kerosene panel:** JODI derived **X_OTHKERO** (KEROSENE − JETKERO) vs Norway
  **heating kerosene** natives — not a combined kerosene rollup.
- **Jet panel:** JODI **JETKERO** vs Norway **Jet kerosene**.
- Overlap is strongest from **2021** (current SSB table). Requires JODI secondary
  parquet with derived X_OTHKERO rows (`python scripts/update_jodi.py --bootstrap`)."""
    ),
    code(
        '''JODI_PARQUET = PROJECT_ROOT / "data" / "processed" / "jodi" / "jodi_secondary.parquet"

if not JODI_PARQUET.exists():
    print(f"[skip] JODI parquet not found: {JODI_PARQUET}")
    print("       Run: python scripts/update_jodi.py --bootstrap")
else:
    jodi = pd.read_parquet(JODI_PARQUET)
    jodi["date"] = pd.to_datetime(jodi["date"])
    jodi_lookup = {spec.jodi_energy_product: spec.panel for spec in JODI_COMPARE_SERIES.values()}
    jodi_codes = set(jodi_lookup)

    ssb_panels = []
    for key in JODI_COMPARE_SERIES:
        sl = ssb_series_for_jodi(demand, key, value_col="value_kbd")
        if sl.empty:
            continue
        spec = JODI_COMPARE_SERIES[key]
        ssb_panels.append(sl.assign(panel=spec.panel))
    ssb_panel = pd.concat(ssb_panels, ignore_index=True) if ssb_panels else pd.DataFrame()

    jodi_no = jodi[
        (jodi["ref_area"] == JODI_REF_AREA)
        & (jodi["flow_breakdown"] == "TOTDEMO")
        & (jodi["unit_measure"] == "KBD")
        & (jodi["energy_product"].isin(jodi_codes))
    ].copy()
    jodi_no["panel"] = jodi_no["energy_product"].map(jodi_lookup)
    jodi_no["value_kbd"] = jodi_no["obs_value"]

    panels = [p for p in JODI_COMPARE_PANEL_ORDER if p in set(ssb_panel.get("panel", []))]
    if jodi_no.empty:
        print("[skip] No JODI NO TOTDEMO rows in parquet.")
    elif not panels:
        print("[skip] No overlapping SSB panels.")
    else:
        fig = cross_source_comparison_chart(
            df_a=ssb_panel,
            df_b=jodi_no,
            products=panels,
            product_col_a="panel",
            product_col_b="panel",
            value_col_a="value_kbd",
            value_col_b="value_kbd",
            label_a="SSB",
            label_b="JODI",
            title="Norway TOTDEMO — SSB vs JODI (kbd; kerosene = X_OTHKERO vs heating kero)",
            units_label="kbd",
        )
        fig.show()

    # Focused kerosene + jet breakdown vs JODI (2021+ overlap)
    focus = ["Kerosene (non-jet)", "Jet fuel"]
    focus = [p for p in focus if p in panels]
    if focus and not jodi_no.empty and not ssb_panel.empty:
        fig2 = cross_source_comparison_chart(
            df_a=ssb_panel[ssb_panel["panel"].isin(focus)],
            df_b=jodi_no[jodi_no["panel"].isin(focus)],
            products=focus,
            product_col_a="panel",
            product_col_b="panel",
            value_col_a="value_kbd",
            value_col_b="value_kbd",
            label_a="SSB",
            label_b="JODI",
            title="Norway — kerosene / jet JODI breakdown (2021+ recommended)",
            units_label="kbd",
        )
        fig2.show()
'''
    ),
    md(
        """## 10. Jet fuel vs Kayrros

SSB **Jet kerosene** (Table 3 product deliveries) vs the Kayrros flight-based
nowcaster (`scope='NO'`, ISO departure country). Kayrros tracks in-flight burn;
SSB reports product sales — useful sanity check, not a one-for-one match
(tankering, stocks, domestic vs international uplift). Requires
`kayros/jet_fuel/data/jet_fuel.duckdb`."""
    ),
    code(
        '''import os
from plotly.subplots import make_subplots

from reference.norway import PRODUCT_JET_KEROSENE

KAYROS_ROOT = PROJECT_ROOT.parent / "kayros" / "jet_fuel"
DB_PATH = KAYROS_ROOT / "data" / "jet_fuel.duckdb"
KAYROS_SCOPE = "NO"

if not DB_PATH.exists():
    print(f"[skip] Kayrros DB not found at {DB_PATH}")
    print("       Build/update kayros/jet_fuel/data/jet_fuel.duckdb first.")
else:
    if str(KAYROS_ROOT) not in sys.path:
        sys.path.insert(0, str(KAYROS_ROOT))
    os.environ.setdefault("JET_FUEL_DB_PATH", str(DB_PATH))
    from src.export import get_consumption  # noqa: E402

    ssb_jet = (
        demand[demand["product_native"] == PRODUCT_JET_KEROSENE]
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
        ssb_jet.rename(columns={"kbd": "ssb_kbd"})
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
            "Jet kbd — SSB vs Kayrros",
            "Gap (Kayrros − SSB)",
        ),
    )
    fig.add_trace(
        go.Scatter(
            x=ssb_jet["date"],
            y=ssb_jet["kbd"],
            name="SSB jet kerosene",
            mode="lines",
        ),
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
            y=overlap["kay_kbd"] - overlap["ssb_kbd"],
            name="Kayrros − SSB",
            mode="lines",
            line=dict(dash="dot"),
        ),
        row=2,
        col=1,
    )
    fig.update_layout(height=620, title="Norway jet fuel: SSB vs Kayrros nowcaster")
    fig.update_yaxes(title_text="kbd", row=1, col=1)
    fig.update_yaxes(title_text="kbd", row=2, col=1)
    add_plotly_date_vline(fig, MONTHLY_REVISION_FROM, line_dash="dash", line_color="gray")
    fig.show()

    if overlap.empty:
        print(f"[warn] No overlapping months — check scope={KAYROS_SCOPE!r}")
    else:
        gap = overlap["kay_kbd"] - overlap["ssb_kbd"]
        summary = pd.DataFrame(
            {
                "mean_kbd": {
                    "SSB jet": overlap["ssb_kbd"].mean(),
                    "Kayrros": overlap["kay_kbd"].mean(),
                },
                "mean_abs_gap_kbd": gap.abs().mean(),
                "mean_pct_gap": (gap / overlap["ssb_kbd"].replace(0, np.nan) * 100).mean(),
            },
            index=["value"],
        ).T.round(1)
        print(f"Overlapping months: {len(overlap)}")
        display(summary)
'''
    ),
    md(
        """## 11. EV adoption — registrations vs fleet stock

**New registrations** (monthly): [Robbie Andrew](https://robbieandrew.github.io/EV/)
— BEV share uses a 3-month rolling mean for Tesla delivery spikes.

**Fleet composition** (annual, year-end stock): SSB table **07849** — registered
private cars by fuel. Better lagged indicator for road-fuel displacement than
new-sales share alone. SSB ``Other fuel`` includes plug-in/non-plug-in hybrids
from ~2016 when hybrid categories were split out."""
    ),
    code(
        '''ev = load_ev_registrations(project_root=PROJECT_ROOT)
ev_plot = ev[ev["date"] >= EV_ANALYSIS_FROM].copy()

print(
    f"EV registrations: {ev['date'].min().date()} -> {ev['date'].max().date()}  "
    f"({len(ev):,} months)"
)
print(f"Source: {EV_REGISTRATIONS_URL}")

# Stacked area — new registrations by powertrain (vehicles)
stack_cols = {
    "bev_new": "BEV",
    "phev_new": "Plug-in hybrid",
    "hybrid_new": "Non-plugin hybrid",
    "petrol_new": "Petrol only",
    "diesel_only_new": "Diesel only",
}
stack_df = ev_plot.melt(
    id_vars=["date"],
    value_vars=list(stack_cols),
    var_name="powertrain",
    value_name="registrations",
)
stack_df["powertrain"] = stack_df["powertrain"].map(stack_cols)
fig_ev = px.area(
    stack_df,
    x="date",
    y="registrations",
    color="powertrain",
    title="Norway new vehicle registrations by powertrain (monthly)",
    labels={"registrations": "New registrations", "date": ""},
)
fig_ev.update_layout(hovermode="x unified")
fig_ev.show()

# BEV share — raw vs 3-month smoothed
fig_share = go.Figure()
fig_share.add_trace(
    go.Scatter(
        x=ev_plot["date"],
        y=ev_plot["bev_share_new"] * 100,
        name="BEV share (raw)",
        line=dict(width=1, color="rgba(31,119,180,0.35)"),
    )
)
fig_share.add_trace(
    go.Scatter(
        x=ev_plot["date"],
        y=ev_plot["bev_share_new_3m"] * 100,
        name="BEV share (3m avg)",
        line=dict(width=2.5, color="rgb(31,119,180)"),
    )
)
fig_share.add_trace(
    go.Scatter(
        x=ev_plot["date"],
        y=ev_plot["plugin_share_new_3m"] * 100,
        name="Plug-in share (BEV+PHEV, 3m avg)",
        line=dict(width=2, dash="dot", color="rgb(44,160,44)"),
    )
)
fig_share.update_layout(
    title="Norway — BEV share of new car registrations",
    yaxis_title="Share of new registrations (%)",
    hovermode="x unified",
)
add_plotly_date_vline(
    fig_share,
    pd.Timestamp("2011-01-01"),
    annotation_text="Nissan Leaf",
    line_dash="dot",
    line_color="gray",
)
fig_share.show()

# ── Fleet stock (SSB 07849, annual) ───────────────────────────────────────
fleet, fleet_shares = load_norway_fleet_composition(project_root=PROJECT_ROOT)
fleet_plot = fleet[fleet["date"] >= pd.Timestamp("2008-12-01")].copy()
fuel_labels = {
    "petrol": "Petrol",
    "diesel": "Diesel",
    "bev": "Battery electric",
    "other_fuel": "Other (incl. hybrid)",
    "gas": "Gas",
    "paraffin": "Paraffin",
}
fleet_plot["fuel_label"] = fleet_plot["fuel"].map(fuel_labels).fillna(fleet_plot["fuel"])

fig_fleet = px.area(
    fleet_plot,
    x="date",
    y="fleet_count",
    color="fuel_label",
    title="Norway private-car fleet by fuel (SSB 07849, year-end stock)",
    labels={"fleet_count": "Registered vehicles", "date": ""},
    groupnorm="fraction",
)
fig_fleet.update_layout(hovermode="x unified")
fig_fleet.show()

share_m = fleet_shares.melt(
    id_vars=["date"],
    value_vars=["bev_share_fleet", "plugin_share_fleet"],
    var_name="series",
    value_name="share",
).assign(
    series=lambda d: d["series"].map(
        {
            "bev_share_fleet": "BEV share (fleet)",
            "plugin_share_fleet": "Plug-in share (approx.)",
        }
    ),
    share_pct=lambda d: d["share"] * 100,
)
fig_fleet_share = px.line(
    share_m,
    x="date",
    y="share_pct",
    color="series",
    markers=True,
    title="Norway — BEV / plug-in share of private-car fleet (annual, SSB)",
    labels={"share_pct": "Share of fleet (%)", "date": ""},
)
fig_fleet_share.update_layout(hovermode="x unified")
fig_fleet_share.show()
'''
    ),
    md(
        """## 12. EV adoption vs road fuel demand

**Road fuel** = motor gasoline + auto diesel (dutiable + free). Marine, heating,
and jet excluded.

Primary overlay uses **fleet BEV share** (SSB, stepped within each calendar year)
— a better match to demand than new-sales share. Secondary panels keep the
monthly new-registration view for comparison."""
    ),
    code(
        '''road_fuel = road_fuel_series(demand, value_col="value_kbd")
panel_reg = ev_road_fuel_panel(demand, ev, value_col="value_kbd")
panel_fleet = fleet_road_fuel_panel(demand, fleet_shares, value_col="value_kbd")

if panel_fleet.empty:
    print("[skip] No overlapping fleet + SSB road fuel months.")
else:
    fig_dual = go.Figure()
    fig_dual.add_trace(
        go.Scatter(
            x=panel_fleet["date"],
            y=panel_fleet["value_kbd"],
            name="Road fuel (kbd)",
            line=dict(color="rgb(214,39,40)", width=2),
            yaxis="y",
        )
    )
    fig_dual.add_trace(
        go.Scatter(
            x=panel_fleet["date"],
            y=panel_fleet["bev_share_fleet"] * 100,
            name="BEV fleet share (%, annual stepped)",
            line=dict(color="rgb(31,119,180)", width=2, dash="dot"),
            yaxis="y2",
        )
    )
    fig_dual.update_layout(
        title="Norway — road fuel demand vs BEV fleet share (2011+)",
        xaxis=dict(title=""),
        yaxis=dict(title="Road fuel (kbd)", side="left"),
        yaxis2=dict(
            title="BEV share of registered fleet (%)",
            overlaying="y",
            side="right",
            range=[0, max(5, panel_fleet["bev_share_fleet"].max() * 120)],
        ),
        hovermode="x unified",
    )
    add_plotly_date_vline(fig_dual, MONTHLY_REVISION_FROM, line_dash="dash", line_color="gray")
    fig_dual.show()

if not panel_reg.empty:
    fig_reg = go.Figure()
    fig_reg.add_trace(
        go.Scatter(
            x=panel_reg["date"],
            y=panel_reg["value_kbd"],
            name="Road fuel (kbd)",
            line=dict(color="rgb(214,39,40)", width=2),
            yaxis="y",
        )
    )
    fig_reg.add_trace(
        go.Scatter(
            x=panel_reg["date"],
            y=panel_reg["bev_share_new_3m"] * 100,
            name="BEV new-sales share (3m avg, %)",
            line=dict(color="rgb(44,160,44)", width=2, dash="dot"),
            yaxis="y2",
        )
    )
    fig_reg.update_layout(
        title="Norway — road fuel vs BEV new-sales share (comparison)",
        yaxis=dict(title="Road fuel (kbd)"),
        yaxis2=dict(title="BEV share of new registrations (%)", overlaying="y", side="right", range=[0, 100]),
        hovermode="x unified",
    )
    add_plotly_date_vline(fig_reg, MONTHLY_REVISION_FROM, line_dash="dash", line_color="gray")
    fig_reg.show()

# Indexed levels (Jan 2011 = 100)
if not panel_fleet.empty:
    base = panel_fleet.iloc[0]
    idx = panel_fleet.copy()
    idx["road_fuel_index"] = idx["value_kbd"] / base["value_kbd"] * 100
    idx["bev_fleet_index"] = idx["bev_share_fleet"] / base["bev_share_fleet"] * 100

    fig_idx = px.line(
        idx.melt(
            id_vars=["date"],
            value_vars=["road_fuel_index", "bev_fleet_index"],
            var_name="series",
            value_name="index",
        ).assign(
            series=lambda d: d["series"].map(
                {
                    "road_fuel_index": "Road fuel (kbd)",
                    "bev_fleet_index": "BEV fleet share",
                }
            )
        ),
        x="date",
        y="index",
        color="series",
        title="Norway — indexed road fuel vs BEV fleet share (Jan 2011 = 100)",
        labels={"index": "Index (Jan 2011 = 100)"},
    )
    fig_idx.add_hline(y=100, line_dash="dot", line_color="gray")
    add_plotly_date_vline(fig_idx, MONTHLY_REVISION_FROM, line_dash="dash", line_color="gray")
    fig_idx.show()
'''
    ),
    md(
        """## 13. Impact snapshot — YoY changes and correlation

Compares monthly **YoY % change in road fuel** with changes in **BEV fleet share**
(annual, stepped monthly) and **BEV new-sales share** (3m avg). Negative
correlation with fleet share is the stronger structural signal."""
    ),
    code(
        '''panel = panel_fleet if not panel_fleet.empty else panel_reg

if panel.empty:
    print("[skip] No panel data for impact snapshot.")
else:
    use_fleet = panel is panel_fleet and not panel_fleet.empty
    x_col = "bev_share_fleet_yoy_pp" if use_fleet else "bev_share_yoy_pp"
    x_label = (
        "BEV fleet share YoY change (pp)"
        if use_fleet
        else "BEV new-sales share YoY change (pp, 3m avg)"
    )

    valid = panel.dropna(subset=["road_fuel_yoy_pct", x_col]).copy()
    corr_all = valid["road_fuel_yoy_pct"].corr(valid[x_col])
    post2015 = valid[valid["date"] >= pd.Timestamp("2015-01-01")]
    corr_post2015 = post2015["road_fuel_yoy_pct"].corr(post2015[x_col])

    display(
        pd.DataFrame(
            [
                {
                    "adoption_metric": "fleet" if use_fleet else "new_sales",
                    "period": f"{EV_ANALYSIS_FROM.date()} -> latest",
                    "months": len(valid),
                    "corr_yoy_road_fuel_vs_bev_pp": round(corr_all, 3),
                },
                {
                    "adoption_metric": "fleet" if use_fleet else "new_sales",
                    "period": "2015 -> latest",
                    "months": len(post2015),
                    "corr_yoy_road_fuel_vs_bev_pp": round(corr_post2015, 3),
                },
            ]
        )
    )

    fig_sc = px.scatter(
        valid,
        x=x_col,
        y="road_fuel_yoy_pct",
        hover_data={"date": "|%Y-%m"},
        title=f"Norway — YoY road fuel vs YoY BEV {'fleet' if use_fleet else 'new-sales'} change",
        labels={x_col: x_label, "road_fuel_yoy_pct": "Road fuel YoY change (%)"},
    )
    try:
        import statsmodels  # noqa: F401

        fig_sc = px.scatter(
            valid,
            x=x_col,
            y="road_fuel_yoy_pct",
            hover_data={"date": "|%Y-%m"},
            trendline="ols",
            title=f"Norway — YoY road fuel vs YoY BEV {'fleet' if use_fleet else 'new-sales'} change",
            labels={x_col: x_label, "road_fuel_yoy_pct": "Road fuel YoY change (%)"},
        )
    except ImportError:
        pass
    fig_sc.show()

    if not panel_reg.empty and not panel_fleet.empty:
        both = panel_reg[["date", "road_fuel_yoy_pct", "bev_share_yoy_pp"]].merge(
            panel_fleet[["date", "bev_share_fleet_yoy_pp"]],
            on="date",
            how="inner",
        ).dropna()
        if len(both) > 12:
            print(
                "Correlation (2011+): new-sales share pp",
                round(both["road_fuel_yoy_pct"].corr(both["bev_share_yoy_pp"]), 3),
                "| fleet share pp",
                round(both["road_fuel_yoy_pct"].corr(both["bev_share_fleet_yoy_pp"]), 3),
            )

    latest = panel.iloc[-1]
    if use_fleet:
        print(
            f"Latest month {latest['date'].strftime('%Y-%m')}: "
            f"road fuel {latest['value_kbd']:.1f} kbd, "
            f"BEV fleet share {latest['bev_share_fleet']*100:.1f}%"
        )
    else:
        print(
            f"Latest month {latest['date'].strftime('%Y-%m')}: "
            f"road fuel {latest['value_kbd']:.1f} kbd, "
            f"BEV new-sales share {latest['bev_share_new_3m']*100:.1f}% (3m avg)"
        )
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
