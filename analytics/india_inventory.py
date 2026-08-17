"""
India petroleum inventory probe — PPAC trade/production vs JODI stocks.

Builds a monthly product panel from PPAC (refinery output, imports, exports,
consumption) and compares implied stock change to JODI STOCKCH / CLOSTLV.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from reference.india import (
    ONONSPEC_PPAC,
    PPAC_TO_JODI_CLEAN,
    attach_jodi_product,
    load_ppac_production_from_dir,
    load_ppac_trade_from_dirs,
    parse_pt_production_pdf,
    parse_pt_trade_pdf,
    rollup_to_jodi_products,
)

# Non-overlapping JODI products for stock panels (exclude TOTPRODS / parent KEROSENE).
STOCK_PANEL_PRODUCTS: tuple[str, ...] = (
    "LPG",
    "GASOLINE",
    "GASDIES",
    "JETKERO",
    "X_OTHKERO",
    "NAPHTHA",
    "RESFUEL",
    "ONONSPEC",
)

JODI_PRODUCT_LABELS: dict[str, str] = {
    "LPG": "LPG",
    "GASOLINE": "Gasoline",
    "GASDIES": "Diesel (HSD)",
    "JETKERO": "Jet fuel",
    "X_OTHKERO": "Kerosene (non-jet)",
    "KEROSENE_NONJET": "Kerosene (non-jet)",
    "NAPHTHA": "Naphtha",
    "RESFUEL": "Fuel oil",
    "ONONSPEC": "Other products",
    "ONONSPEC_BASKET": "Other products",
    "TOTPRODS": "Total products",
    "TOTPRODS_SYN": "Total (sum of panel)",
}

JODI_FLOWS = [
    "REFGROUT",
    "TOTIMPSB",
    "TOTEXPSB",
    "TOTDEMO",
    "STOCKCH",
    "CLOSTLV",
    "STATDIFF",
    "IPTRANSF",
    "PTRANSF",
]

PPAC_SUPPLY_COLS = [
    "ppac_refgrout",
    "ppac_imports",
    "ppac_exports",
    "ppac_demand",
]

DERIVED_NUMERIC_COLS = [
    "implied_STOCKCH_jodi_dem",
    "implied_STOCKCH_ppac_dem",
    "stockch_gap_jodi_dem",
    "jodi_bal_resid",
    "jodi_d_CLOSTLV",
]


def coerce_numeric_columns(
    df: pd.DataFrame,
    columns: list[str] | None = None,
) -> pd.DataFrame:
    """
    Cast flow / balance columns to float64.

    JODI pivot can yield object columns with pd.NA; arithmetic then produces
    object dtypes and groupby mean/std fails on NAType.
    """
    out = df.copy()
    if columns is None:
        columns = [
            c
            for c in out.columns
            if c in JODI_FLOWS
            or c in PPAC_SUPPLY_COLS
            or c in DERIVED_NUMERIC_COLS
        ]
    for col in columns:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    return out


def resolve_project_root(start: Path | None = None) -> Path:
    here = start or Path.cwd()
    for candidate in [here, *here.parents]:
        if (candidate / "scripts" / "update_jodi.py").exists():
            return candidate
        nested = candidate / "country_oil_scraper"
        if (nested / "scripts" / "update_jodi.py").exists():
            return nested
    raise RuntimeError(f"Could not locate country_oil_scraper root from {here}")


def load_jodi_india_wide(
    jodi_parquet: Path,
    *,
    unit: str = "KTONS",
    ref_area: str = "IN",
) -> pd.DataFrame:
    """Pivot JODI secondary India to one row per (month, product) with flow columns."""
    raw = pd.read_parquet(jodi_parquet)
    sub = raw[(raw["ref_area"] == ref_area) & (raw["unit_measure"] == unit)].copy()
    sub["TIME_PERIOD"] = pd.PeriodIndex(sub["date"], freq="M")
    wide = sub.pivot_table(
        index=["TIME_PERIOD", "energy_product"],
        columns="flow_breakdown",
        values="obs_value",
        aggfunc="first",
        observed=True,
    ).reset_index()
    wide.columns.name = None
    wide = wide.rename(columns={"energy_product": "jodi_product"})
    return coerce_numeric_columns(wide, columns=[c for c in JODI_FLOWS if c in wide.columns])


def _add_kerosene_nonjet(jodi_wide: pd.DataFrame) -> pd.DataFrame:
    """Synthesise KEROSENE_NONJET = KEROSENE - JETKERO for PPAC SKO compare."""
    flow_cols = [c for c in JODI_FLOWS if c in jodi_wide.columns]
    ker = jodi_wide[jodi_wide["jodi_product"] == "KEROSENE"].set_index("TIME_PERIOD")
    jet = jodi_wide[jodi_wide["jodi_product"] == "JETKERO"].set_index("TIME_PERIOD")
    if ker.empty or jet.empty:
        return jodi_wide
    common = ker.index.intersection(jet.index)
    rows = []
    for period in common:
        row = {"TIME_PERIOD": period, "jodi_product": "KEROSENE_NONJET"}
        for col in flow_cols:
            row[col] = ker.loc[period, col] - jet.loc[period, col]
        rows.append(row)
    if not rows:
        return jodi_wide
    return pd.concat([jodi_wide, pd.DataFrame(rows)], ignore_index=True)


def load_ppac_consumption(ppac_parquet: Path) -> pd.DataFrame:
    dem = pd.read_parquet(ppac_parquet)
    dem = dem[~dem["is_total_row"].fillna(False)].copy()
    dem["date"] = pd.to_datetime(dem["date"])
    return rollup_to_jodi_products(dem.rename(columns={"value_000mt": "value_000mt"}))


def _rollup_trade_flows(trade: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    imp = (
        rollup_to_jodi_products(trade[trade["trade_flow"] == "imports"])
        .rename(columns={"value_000mt": "ppac_imports"})
        .drop(columns=["metric_type", "trade_flow"], errors="ignore")
    )
    exp = (
        rollup_to_jodi_products(trade[trade["trade_flow"] == "exports"])
        .rename(columns={"value_000mt": "ppac_exports"})
        .drop(columns=["metric_type", "trade_flow"], errors="ignore")
    )
    return imp, exp


def _merge_supply_components(
    ref: pd.DataFrame,
    imp: pd.DataFrame,
    exp: pd.DataFrame,
    dem: pd.DataFrame,
) -> pd.DataFrame:
    for _df in (ref, imp, exp, dem):
        _df["date"] = pd.to_datetime(_df["date"])
    panel = ref.merge(imp, on=["date", "jodi_product"], how="outer")
    panel = panel.merge(exp, on=["date", "jodi_product"], how="outer")
    panel = panel.merge(dem, on=["date", "jodi_product"], how="outer")
    panel["TIME_PERIOD"] = pd.PeriodIndex(panel["date"], freq="M")
    return coerce_numeric_columns(
        panel.sort_values(["jodi_product", "date"]),
        columns=[c for c in PPAC_SUPPLY_COLS if c in panel.columns],
    )


def build_ppac_supply_panel(
    trade_dir: Path,
    production_dir: Path,
    consumption_parquet: Path,
) -> pd.DataFrame:
    """Wide PPAC panel: refgrout, imports, exports, ppac_demand by jodi_product × month."""
    trade = load_ppac_trade_from_dirs(trade_dir)
    prod = load_ppac_production_from_dir(production_dir)
    dem = load_ppac_consumption(consumption_parquet)

    imp, exp = _rollup_trade_flows(trade)
    ref = (
        rollup_to_jodi_products(prod)
        .rename(columns={"value_000mt": "ppac_refgrout"})
        .drop(columns=["metric_type"], errors="ignore")
    )
    dem = dem.rename(columns={"value_000mt": "ppac_demand"}).drop(
        columns=["metric_type"], errors="ignore"
    )
    return _merge_supply_components(ref, imp, exp, dem)


def build_ppac_supply_panel_extended(
    project_root: Path | None = None,
    *,
    trade_pdf: Path | str | None = None,
    production_pdf: Path | str | None = None,
    fill_production_from_jodi: bool = True,
) -> pd.DataFrame:
    """
    PPAC supply panel through the latest Excel + flash PDF months.

    Production Excel often lags (e.g. only through Sep 2025); April refinery
    output comes from the PPAC PDF. Where Excel production is missing but trade
    and demand exist, ``fill_production_from_jodi`` uses JODI ``REFGROUT`` for
    that month only (flagged in ``refgrout_source``).
    """
    from reference.india import upsert_monthly

    root = resolve_project_root(project_root)
    trade_dir = root / "data/raw/india/trade"
    prod_dir = root / "data/raw/india/production"
    dem_path = root / "data/processed/india/india_pt_consumption.parquet"

    trade_path = Path(
        trade_pdf or trade_dir / "1779378989_PT_import.pdf"
    )
    prod_path = Path(
        production_pdf
        or prod_dir / "1779779011_PT_POL_production_current.pdf"
    )

    trade = load_ppac_trade_from_dirs(trade_dir)
    if trade_path.exists():
        trade = upsert_monthly(
            trade,
            parse_pt_trade_pdf(trade_path),
            ["date", "product", "trade_flow"],
        )

    prod = load_ppac_production_from_dir(prod_dir)
    if prod_path.exists():
        prod = upsert_monthly(
            prod,
            parse_pt_production_pdf(prod_path),
            ["date", "product"],
        )

    dem = load_ppac_consumption(dem_path)
    dem = dem.rename(columns={"value_000mt": "ppac_demand"}).drop(
        columns=["metric_type"], errors="ignore"
    )
    imp, exp = _rollup_trade_flows(trade)
    ref = (
        rollup_to_jodi_products(prod)
        .rename(columns={"value_000mt": "ppac_refgrout"})
        .drop(columns=["metric_type"], errors="ignore")
    )
    panel = _merge_supply_components(ref, imp, exp, dem)

    panel["refgrout_source"] = np.where(
        panel["ppac_refgrout"].notna(), "ppac", pd.NA
    )

    if fill_production_from_jodi:
        jodi_wide = load_jodi_india_wide(
            root / "data/processed/jodi/jodi_secondary.parquet"
        )
        jref = jodi_wide[jodi_wide["jodi_product"].isin(STOCK_PANEL_PRODUCTS)][
            ["TIME_PERIOD", "jodi_product", "REFGROUT"]
        ].rename(columns={"REFGROUT": "jodi_refgrout"})
        panel = panel.merge(jref, on=["TIME_PERIOD", "jodi_product"], how="left")
        missing = panel["ppac_refgrout"].isna() & panel["jodi_refgrout"].notna()
        panel.loc[missing, "ppac_refgrout"] = panel.loc[missing, "jodi_refgrout"]
        panel.loc[missing, "refgrout_source"] = "jodi_fill"
        panel = panel.drop(columns=["jodi_refgrout"])

    return panel


def merge_ppac_jodi(
    ppac_panel: pd.DataFrame,
    jodi_wide: pd.DataFrame,
) -> pd.DataFrame:
    """Join PPAC supply panel with JODI flow columns."""
    jodi = _add_kerosene_nonjet(jodi_wide)
    merged = ppac_panel.merge(jodi, on=["TIME_PERIOD", "jodi_product"], how="inner")
    return merged


def implied_stock_change(
    df: pd.DataFrame,
    *,
    demand_col: str = "jodi_TOTDEMO",
) -> pd.Series:
    """
    PPAC refinery + trade − demand. Positive = stock build (JODI convention).
    """
    return (
        df["ppac_refgrout"].fillna(0)
        + df["ppac_imports"].fillna(0)
        - df["ppac_exports"].fillna(0)
        - df[demand_col].fillna(0)
    )


def _col(df: pd.DataFrame, name: str) -> pd.Series:
    if name in df.columns:
        return pd.to_numeric(df[name], errors="coerce").fillna(0.0)
    return pd.Series(0.0, index=df.index, dtype="float64")


def jodi_balance_residual(df: pd.DataFrame) -> pd.Series:
    """JODI closure: supply − TOTDEMO (should be ~0 minus statdiff semantics)."""
    return (
        _col(df, "REFGROUT")
        + _col(df, "TOTIMPSB")
        - _col(df, "TOTEXPSB")
        - _col(df, "IPTRANSF")
        - _col(df, "PTRANSF")
        + _col(df, "STOCKCH")
        + _col(df, "STATDIFF")
        - _col(df, "TOTDEMO")
    )


def cumulative_draw_since(
    df: pd.DataFrame,
    anchor: str | pd.Period,
    *,
    stock_col: str = "STOCKCH",
    level_col: str = "CLOSTLV",
    product: str = "TOTPRODS",
) -> dict[str, float | None]:
    """
    Cumulative inventory draw (kt) from anchor month (exclusive) through latest.

    Draw reported as positive kt (stocks fell).
    """
    anchor_p = pd.Period(anchor, freq="M")
    sub = df[df["jodi_product"] == product].sort_values("TIME_PERIOD")
    if sub.empty:
        return {"flow_draw_kt": None, "level_draw_kt": None, "months": 0}

    after = sub[sub["TIME_PERIOD"] > anchor_p]
    if after.empty:
        return {"flow_draw_kt": None, "level_draw_kt": None, "months": 0}

    if stock_col in after.columns:
        flow_draw = -float(pd.to_numeric(after[stock_col], errors="coerce").fillna(0).sum())
    else:
        flow_draw = None

    level_draw = None
    if level_col in sub.columns:
        close_anchor = sub.loc[sub["TIME_PERIOD"] == anchor_p, level_col]
        close_latest = after.iloc[-1][level_col]
        if len(close_anchor):
            a = pd.to_numeric(close_anchor.iloc[0], errors="coerce")
            b = pd.to_numeric(close_latest, errors="coerce")
            if pd.notna(a) and pd.notna(b):
                level_draw = float(a) - float(b)

    return {
        "flow_draw_kt": flow_draw,
        "level_draw_kt": level_draw,
        "months": int(len(after)),
        "latest_period": str(after["TIME_PERIOD"].iloc[-1]),
    }


def build_closing_stocks_summary(
    jodi_wide: pd.DataFrame,
    *,
    anchor: str = "2026-02",
    include_april_implied: pd.DataFrame | None = None,
) -> dict[str, pd.DataFrame | str | float | None]:
    """
    Japan §8-style table: Feb 2026 closing level → latest JODI month, by product.

    Change = latest CLOSTLV − Feb CLOSTLV (negative = draw). Units: kt (KTONS).

    If ``include_april_implied`` is the ``by_jodi_product`` frame from
    ``build_april_implied_inventory``, adds ``implied_stockch_apr2026_kt`` and
    ``change_kt_incl_apr_implied`` (level change through latest JODI month plus
    April PPAC-implied flow — April has no JODI CLOSTLV yet).
    """
    anchor_p = pd.Period(anchor, freq="M")
    wide = coerce_numeric_columns(jodi_wide.copy())

    if "CLOSTLV" not in wide.columns:
        raise ValueError("jodi_wide has no CLOSTLV column")

    stk = wide[wide["jodi_product"].isin(STOCK_PANEL_PRODUCTS)].copy()
    stk = stk[stk["CLOSTLV"].notna()].copy()
    if stk.empty:
        raise ValueError("No CLOSTLV rows for stock panel products")

    stk["date"] = stk["TIME_PERIOD"].dt.to_timestamp()
    stk = stk.sort_values(["jodi_product", "date"])
    stk["delta_CLOSTLV"] = stk.groupby("jodi_product")["CLOSTLV"].diff()
    stk["product_label"] = stk["jodi_product"].map(JODI_PRODUCT_LABELS)

    latest_p = stk["TIME_PERIOD"].max()
    latest_date = latest_p.to_timestamp()

    baseline = (
        stk[stk["TIME_PERIOD"] == anchor_p]
        .set_index("jodi_product")["CLOSTLV"]
    )
    latest = (
        stk[stk["TIME_PERIOD"] == latest_p]
        .set_index("jodi_product")["CLOSTLV"]
    )

    chg = (latest - baseline).rename("change_kt_since_feb2026")
    summary = pd.DataFrame(
        {
            "feb_2026_kt": baseline,
            "latest_kt": latest,
        }
    ).join(chg)
    summary["latest_month"] = str(latest_p)
    summary.index = summary.index.map(
        lambda c: JODI_PRODUCT_LABELS.get(c, c)
    )

    # Total from JODI TOTPRODS (official aggregate, not sum of panel).
    tot_rows = wide[wide["jodi_product"] == "TOTPRODS"].copy()
    if tot_rows.empty:
        by_date = stk.groupby("date", as_index=False)["CLOSTLV"].sum()
        tot_label = "Total (panel sum)"
    else:
        tot_rows["date"] = tot_rows["TIME_PERIOD"].dt.to_timestamp()
        by_date = tot_rows[["date", "CLOSTLV"]].sort_values("date")
        tot_label = "Total products"

    tot_feb = float(
        pd.to_numeric(
            by_date.loc[by_date["date"] == anchor_p.to_timestamp(), "CLOSTLV"],
            errors="coerce",
        ).iloc[0]
    )
    tot_latest = float(
        pd.to_numeric(
            by_date.loc[by_date["date"] == latest_date, "CLOSTLV"],
            errors="coerce",
        ).iloc[0]
    )
    grand_change = tot_latest - tot_feb

    if include_april_implied is not None and not include_april_implied.empty:
        apr = include_april_implied.set_index("jodi_product")["implied_STOCKCH_kt"]
        # Align index labels after summary already renamed to display labels
        apr_by_label = {}
        for code, val in apr.items():
            apr_by_label[JODI_PRODUCT_LABELS.get(code, code)] = val
        summary["implied_stockch_apr2026_kt"] = pd.Series(apr_by_label)
        summary["change_kt_incl_apr_implied"] = (
            summary["change_kt_since_feb2026"]
            + summary["implied_stockch_apr2026_kt"].fillna(0)
        )
        grand_change_incl_apr = grand_change + float(
            include_april_implied["implied_STOCKCH_kt"].fillna(0).sum()
        )
    else:
        grand_change_incl_apr = None

    summary_sorted = summary.sort_values("change_kt_since_feb2026")
    summary_sorted["total_change_kt"] = grand_change
    if grand_change_incl_apr is not None:
        summary_sorted["total_incl_apr_implied_kt"] = grand_change_incl_apr

    total_row = pd.DataFrame(
        [
            {
                "feb_2026_kt": tot_feb,
                "latest_kt": tot_latest,
                "change_kt_since_feb2026": grand_change,
                "latest_month": str(latest_p),
                "total_change_kt": grand_change,
            }
        ],
        index=[tot_label],
    )
    if grand_change_incl_apr is not None:
        total_row["implied_stockch_apr2026_kt"] = float(
            include_april_implied["implied_STOCKCH_kt"].fillna(0).sum()
        )
        total_row["change_kt_incl_apr_implied"] = grand_change_incl_apr
        total_row["total_incl_apr_implied_kt"] = grand_change_incl_apr

    summary_out = pd.concat([summary_sorted, total_row])

    return {
        "summary": summary_out,
        "stocks_long": stk,
        "totals_by_date": by_date.sort_values("date"),
        "anchor_period": str(anchor_p),
        "latest_period": str(latest_p),
        "grand_change_kt": grand_change,
        "grand_change_incl_apr_implied_kt": grand_change_incl_apr,
    }


def build_ppac_closing_stocks_summary(
    project_root: Path | None = None,
    jodi_wide: pd.DataFrame | None = None,
    *,
    anchor: str = "2026-02",
    fill_production_from_jodi: bool = True,
) -> dict[str, pd.DataFrame | str | float | None]:
    """
    Japan §8-style table using **PPAC-timely** supply and demand.

    PPAC does not publish stock levels. Feb month-end **levels** come from JODI
    ``CLOSTLV`` (anchor only). Changes after Feb are **PPAC-implied** monthly
    ``STOCKCH`` (refinery + trade − demand), including PDF months when Excel lags.

    Estimated latest level = Feb JODI level + sum(PPAC implied flows since Feb).
    """
    anchor_p = pd.Period(anchor, freq="M")
    root = resolve_project_root(project_root)
    if jodi_wide is None:
        jodi_wide = load_jodi_india_wide(
            root / "data/processed/jodi/jodi_secondary.parquet"
        )

    panel = build_ppac_supply_panel_extended(
        root,
        fill_production_from_jodi=fill_production_from_jodi,
    )
    wide = coerce_numeric_columns(jodi_wide.copy())

    # Feb anchor levels (JODI only).
    jodi_stk = wide[wide["jodi_product"].isin(STOCK_PANEL_PRODUCTS)].copy()
    feb_levels = (
        jodi_stk[jodi_stk["TIME_PERIOD"] == anchor_p]
        .set_index("jodi_product")["CLOSTLV"]
    )

    # PPAC implied stock change by month (panel products with demand).
    ppac = panel[panel["jodi_product"].isin(STOCK_PANEL_PRODUCTS)].copy()
    # Demand-only months (e.g. May flash) lack trade/production — skip for balance.
    ppac = ppac[
        ppac["ppac_demand"].notna() & ppac["ppac_refgrout"].notna()
    ].copy()
    ppac["implied_STOCKCH_ppac"] = implied_stock_change(
        ppac, demand_col="ppac_demand"
    )
    ppac["product_label"] = ppac["jodi_product"].map(JODI_PRODUCT_LABELS)

    after = ppac[ppac["TIME_PERIOD"] > anchor_p].copy()
    if after.empty:
        raise ValueError(f"No PPAC months after {anchor} for implied stocks")

    latest_p = after["TIME_PERIOD"].max()

    # One column per month (e.g. implied_2026-03_kt).
    month_cols: dict[str, pd.Series] = {}
    for period, grp in after.groupby("TIME_PERIOD", observed=True):
        col = f"implied_{period}_kt"
        month_cols[col] = grp.set_index("jodi_product")["implied_STOCKCH_ppac"]

    change_ppac = (
        after.groupby("jodi_product", observed=True)["implied_STOCKCH_ppac"]
        .sum()
        .rename("change_kt_since_feb_ppac")
    )

    summary = pd.DataFrame({"feb_2026_kt_jodi_anchor": feb_levels}).join(change_ppac)
    for col, series in month_cols.items():
        summary[col] = series
    summary["latest_est_kt"] = summary["feb_2026_kt_jodi_anchor"] + summary[
        "change_kt_since_feb_ppac"
    ]
    summary["latest_month"] = str(latest_p)

    # JODI reference through its latest published month (for comparison).
    jodi_latest_p = jodi_stk[jodi_stk["CLOSTLV"].notna()]["TIME_PERIOD"].max()
    if jodi_latest_p > anchor_p:
        jodi_latest = (
            jodi_stk[jodi_stk["TIME_PERIOD"] == jodi_latest_p]
            .set_index("jodi_product")["CLOSTLV"]
        )
        summary["jodi_latest_kt"] = jodi_latest
        summary["change_kt_jodi_levels"] = jodi_latest - feb_levels

    summary.index = summary.index.map(lambda c: JODI_PRODUCT_LABELS.get(c, c))
    summary_sorted = summary.sort_values("change_kt_since_feb_ppac")

    grand_change = float(summary_sorted["change_kt_since_feb_ppac"].sum())
    tot_feb = float(feb_levels.sum())
    tot_latest_est = float(summary_sorted["latest_est_kt"].sum())
    summary_sorted["total_change_kt"] = grand_change

    total_row = pd.DataFrame(
        [
            {
                "feb_2026_kt_jodi_anchor": tot_feb,
                "change_kt_since_feb_ppac": grand_change,
                "latest_est_kt": tot_latest_est,
                "latest_month": str(latest_p),
                "total_change_kt": grand_change,
            }
        ],
        index=["Total (panel sum)"],
    )
    for col in month_cols:
        if col in summary_sorted.columns:
            total_row[col] = float(summary_sorted[col].sum())

    summary_out = pd.concat([summary_sorted, total_row])

    # Estimated level path for charts.
    flows = after[
        [
            "date",
            "TIME_PERIOD",
            "jodi_product",
            "product_label",
            "implied_STOCKCH_ppac",
            "refgrout_source",
        ]
    ].copy()
    levels = []
    for prod in STOCK_PANEL_PRODUCTS:
        base = feb_levels.get(prod, np.nan)
        if pd.isna(base):
            continue
        sub = after[after["jodi_product"] == prod]
        levels.append(
            {
                "date": anchor_p.to_timestamp(),
                "jodi_product": prod,
                "product_label": JODI_PRODUCT_LABELS.get(prod, prod),
                "estimated_CLOSTLV": base,
                "implied_STOCKCH_ppac": np.nan,
            }
        )
        running = float(base)
        for _, row in sub.sort_values("date").iterrows():
            running += float(row["implied_STOCKCH_ppac"])
            levels.append(
                {
                    "date": row["date"],
                    "jodi_product": prod,
                    "product_label": JODI_PRODUCT_LABELS.get(prod, prod),
                    "estimated_CLOSTLV": running,
                    "implied_STOCKCH_ppac": row["implied_STOCKCH_ppac"],
                }
            )
    levels_df = pd.DataFrame(levels).sort_values(["jodi_product", "date"])
    totals_est = (
        levels_df.groupby("date", as_index=False)["estimated_CLOSTLV"]
        .sum()
        .rename(columns={"estimated_CLOSTLV": "estimated_CLOSTLV"})
    )

    return {
        "summary": summary_out,
        "ppac_flows": flows,
        "estimated_levels": levels_df,
        "totals_estimated_by_date": totals_est,
        "ppac_panel": panel,
        "anchor_period": str(anchor_p),
        "latest_ppac_period": str(latest_p),
        "latest_jodi_period": str(jodi_latest_p),
        "grand_change_ppac_kt": grand_change,
        "source_note": (
            "Feb levels: JODI CLOSTLV. Monthly changes: PPAC refinery/trade/demand "
            "(PDF + Excel; JODI REFGROUT fill when PPAC production missing)."
        ),
    }


def sum_jodi_totprods_from_components(jodi_wide: pd.DataFrame) -> pd.DataFrame:
    """
    Sum product-level JODI flows to a synthetic TOTPRODS series (excl. double-count).
    """
    products = list(PPAC_TO_JODI_CLEAN.values()) + ["ONONSPEC_BASKET"]
    sub = jodi_wide[jodi_wide["jodi_product"].isin(products)].copy()
    flow_cols = [c for c in JODI_FLOWS if c in sub.columns]
    agg = sub.groupby("TIME_PERIOD", as_index=False)[flow_cols].sum()
    agg["jodi_product"] = "TOTPRODS_SYN"
    return agg


def build_april_implied_inventory(
    project_root: Path | None = None,
    *,
    period: str = "2026-04",
    trade_pdf: str | None = None,
    production_pdf: str | None = None,
) -> dict[str, pd.DataFrame]:
    """
    Implied April stock change using PPAC demand + trade/production PDFs.

    JODI typically lags; this uses PPAC consumption (demand) and flash PDFs for
    refinery output and imports/exports when Excel has not caught up.

    Returns
    -------
    ppac_long : product-level supply + demand (native PPAC keys)
    by_jodi : rolled to JODI product codes with implied_STOCKCH
    headline : one-row totals (mapped products + crude note)
    """
    root = resolve_project_root(project_root)
    target = pd.Period(period, freq="M")
    target_date = target.to_timestamp()

    trade_path = Path(
        trade_pdf or root / "data/raw/india/trade/1779378989_PT_import.pdf"
    )
    prod_path = Path(
        production_pdf
        or root / "data/raw/india/production/1779779011_PT_POL_production_current.pdf"
    )
    dem_path = root / "data/processed/india/india_pt_consumption.parquet"

    dem = pd.read_parquet(dem_path)
    dem = dem[~dem["is_total_row"].fillna(False)].copy()
    dem["date"] = pd.to_datetime(dem["date"])
    dem = dem[dem["date"] == target_date]
    dem = attach_jodi_product(dem)

    trade = parse_pt_trade_pdf(trade_path)
    prod = parse_pt_production_pdf(prod_path)

    imp = rollup_to_jodi_products(trade[trade["trade_flow"] == "imports"]).rename(
        columns={"value_000mt": "imports_kt"}
    )
    exp = rollup_to_jodi_products(trade[trade["trade_flow"] == "exports"]).rename(
        columns={"value_000mt": "exports_kt"}
    )
    ref = rollup_to_jodi_products(prod).rename(columns={"value_000mt": "refgrout_kt"})
    dem_j = (
        dem.groupby("jodi_product", as_index=False)["value_000mt"]
        .sum()
        .rename(columns={"value_000mt": "demand_kt"})
    )

    by_jodi = ref.merge(imp, on="jodi_product", how="outer")
    by_jodi = by_jodi.merge(exp, on="jodi_product", how="outer")
    by_jodi = by_jodi.merge(dem_j, on="jodi_product", how="outer")
    by_jodi["TIME_PERIOD"] = str(target)

    for c in ("refgrout_kt", "imports_kt", "exports_kt", "demand_kt"):
        by_jodi[c] = by_jodi[c].fillna(0)

    # Positive = stock build (JODI); negative implied_STOCKCH = draw
    by_jodi["implied_STOCKCH_kt"] = (
        by_jodi["refgrout_kt"]
        + by_jodi["imports_kt"]
        - by_jodi["exports_kt"]
        - by_jodi["demand_kt"]
    )
    by_jodi["implied_draw_kt"] = -by_jodi["implied_STOCKCH_kt"]

    mapped = by_jodi[by_jodi["jodi_product"].notna()].copy()
    headline = pd.DataFrame(
        [
            {
                "period": str(target),
                "products_included": int(len(mapped)),
                "refgrout_kt": mapped["refgrout_kt"].sum(),
                "imports_kt": mapped["imports_kt"].sum(),
                "exports_kt": mapped["exports_kt"].sum(),
                "demand_kt": mapped["demand_kt"].sum(),
                "implied_STOCKCH_kt": mapped["implied_STOCKCH_kt"].sum(),
                "implied_draw_kt": mapped["implied_draw_kt"].sum(),
                "note": (
                    "Product-only balance; crude oil trade excluded. "
                    "Demand = PPAC PT consumption; supply = PPAC PDF refinery + product trade."
                ),
            }
        ]
    )

    ppac_long = dem[["product", "value_000mt", "jodi_product"]].merge(
        trade.assign(metric=lambda d: d["trade_flow"]),
        on="product",
        how="outer",
    )

    return {
        "by_jodi_product": by_jodi.sort_values("implied_draw_kt", ascending=False),
        "headline": headline,
        "trade_pdf": trade,
        "production_pdf": prod,
        "demand": dem,
        "ppac_long": ppac_long,
    }


def gap_diagnostics_summary(
    merged: pd.DataFrame,
    products: list[str] | None = None,
) -> pd.DataFrame:
    """
    Mean / std of stock-change gaps by product (float-safe; skips all-NaN groups).
    """
    products = products or ["GASDIES", "GASOLINE", "LPG", "KEROSENE_NONJET"]
    frame = coerce_numeric_columns(merged)
    diag = frame[frame["jodi_product"].isin(products)].copy()
    if diag.empty:
        return pd.DataFrame()

    diag["gap_ppac_dem"] = diag["implied_STOCKCH_ppac_dem"] - diag["STOCKCH"]
    summary = (
        diag.groupby("jodi_product", observed=True)[
            ["stockch_gap_jodi_dem", "gap_ppac_dem"]
        ]
        .agg(["mean", "std", "count"])
        .round(1)
    )
    return summary


def build_probe_tables(
    project_root: Path | None = None,
    *,
    anchor: str = "2026-02",
) -> dict[str, pd.DataFrame]:
    """
    Load all sources and return diagnostic DataFrames for the inventory notebook.
    """
    root = resolve_project_root(project_root)
    jodi_path = root / "data/processed/jodi/jodi_secondary.parquet"
    ppac_dem = root / "data/processed/india/india_pt_consumption.parquet"
    trade_dir = root / "data/raw/india/trade"
    prod_dir = root / "data/raw/india/production"

    jodi_wide = load_jodi_india_wide(jodi_path)
    ppac = build_ppac_supply_panel(trade_dir, prod_dir, ppac_dem)
    merged = merge_ppac_jodi(ppac, jodi_wide)

    merged["implied_STOCKCH_jodi_dem"] = implied_stock_change(
        merged, demand_col="TOTDEMO"
    )
    merged["implied_STOCKCH_ppac_dem"] = implied_stock_change(
        merged, demand_col="ppac_demand"
    )
    merged["stockch_gap_jodi_dem"] = (
        merged["implied_STOCKCH_jodi_dem"] - merged["STOCKCH"]
    )
    merged["jodi_bal_resid"] = jodi_balance_residual(merged)
    if "CLOSTLV" in merged.columns:
        merged["jodi_d_CLOSTLV"] = merged.groupby("jodi_product")["CLOSTLV"].diff()
    merged = coerce_numeric_columns(merged)

    tot = sum_jodi_totprods_from_components(jodi_wide)
    draws = pd.DataFrame(
        [
            {
                "product": "TOTPRODS",
                **cumulative_draw_since(
                    jodi_wide, anchor, product="TOTPRODS"
                ),
            },
            {
                "product": "TOTPRODS_SYN",
                **cumulative_draw_since(
                    tot.rename(columns={"jodi_product": "jodi_product"}),
                    anchor,
                    product="TOTPRODS_SYN",
                ),
            },
        ]
    )

    return {
        "ppac_panel": ppac,
        "jodi_wide": jodi_wide,
        "merged": merged,
        "jodi_totprods_syn": tot,
        "cumulative_draws": draws,
    }
