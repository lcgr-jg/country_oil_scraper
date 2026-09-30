"""Phase 2 — quantitative IEA vs JODI overlap + Tableau export.

Builds aligned monthly (demand + stocks) and quarterly non-OECD demand panels
on explicit **compare buckets** (apples-to-apples recipes), then exports a wide
CSV with ``iea_value``, ``jodi_value``, ``diff``, ``pct_diff`` for Tableau.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from analytics.iea_jodi_profile import IEA_ISO, IEA_OECD_ISO

# ---------------------------------------------------------------------------
# Compare-bucket registry (apples-to-apples recipes)
# ---------------------------------------------------------------------------
# Why this exists: IEA publishes hierarchy (parent Gas/diesel oil = Auto +
# Heating) and aggregates (Middle distillates ≈ gasoil + kerosene). Blind 1:1
# maps double-count demand and mis-align stocks. Each bucket declares exactly
# which IEA lines and which JODI codes to use.


@dataclass(frozen=True)
class CompareBucket:
    """One comparable concept across IEA and JODI."""

    bucket: str
    label: str
    theme: str  # demand | inventory | both
    role: str  # primary | detail | aggregate | excluded
    iea_products: tuple[str, ...]
    jodi_products: tuple[str, ...]
    jodi_dataset: str  # secondary | primary
    notes: str = ""


# Primary buckets = safe default for explorer / Tableau filters.
COMPARE_BUCKETS: tuple[CompareBucket, ...] = (
    CompareBucket(
        "gasoline",
        "Gasoline",
        "both",
        "primary",
        ("Motor gasoline",),
        ("GASOLINE",),
        "secondary",
    ),
    CompareBucket(
        "gasoil_diesel",
        "Gasoil / diesel",
        "demand",
        "primary",
        # Parent only — Automotive + Heating are children (excluded below).
        ("Gas/diesel oil",),
        ("GASDIES",),
        "secondary",
        "IEA Gas/diesel oil ≈ Automotive diesel + Heating; do not sum children.",
    ),
    CompareBucket(
        "kerosene_total",
        "Kerosene (total)",
        "demand",
        "primary",
        ("Kerosene",),
        ("KEROSENE",),
        "secondary",
        "JODI KEROSENE = JETKERO + other kerosene.",
    ),
    CompareBucket(
        "naphtha",
        "Naphtha",
        "demand",
        "primary",
        ("Naphtha",),
        ("NAPHTHA",),
        "secondary",
    ),
    CompareBucket(
        "lpg",
        "LPG",
        "demand",
        "primary",
        ("LPG and Ethane",),
        ("LPG",),
        "secondary",
        "IEA includes ethane; JODI LPG may not — expect small bias.",
    ),
    CompareBucket(
        "resfuel",
        "Residual fuel oil",
        "both",
        "primary",
        ("Residual fuel oil",),
        ("RESFUEL",),
        "secondary",
    ),
    CompareBucket(
        "other",
        "Other products",
        "demand",
        "primary",
        ("Other non-specified secondary oil products",),
        ("ONONSPEC",),
        "secondary",
        "Looser definitional match.",
    ),
    CompareBucket(
        "total_products",
        "Total oil products",
        "both",
        "primary",
        ("Oil products",),
        ("TOTPRODS",),
        "secondary",
    ),
    CompareBucket(
        "middle_distillates",
        "Middle distillates",
        "inventory",
        "primary",
        ("Middle distillates",),
        # Bridge: IEA MD ≈ JODI gasoil + kerosene stocks.
        ("GASDIES", "KEROSENE"),
        "secondary",
        "JODI side summed: GASDIES + KEROSENE.",
    ),
    CompareBucket(
        "crude",
        "Crude oil",
        "inventory",
        "primary",
        ("Crude oil",),
        ("CRUDEOIL",),
        "primary",
    ),
    # --- detail / excluded (kept for audit, not default compare) ---
    CompareBucket(
        "automotive_diesel_detail",
        "Automotive diesel (IEA detail)",
        "demand",
        "detail",
        ("Automotive diesel",),
        (),
        "secondary",
        "Child of Gas/diesel oil — no direct JODI twin; excluded from primary.",
    ),
    CompareBucket(
        "heating_gasoil_detail",
        "Heating gasoil (IEA detail)",
        "demand",
        "detail",
        ("Heating and other gas oil",),
        (),
        "secondary",
        "Child of Gas/diesel oil — no direct JODI twin; excluded from primary.",
    ),
    CompareBucket(
        "oil_and_crude_agg",
        "Oil and oil products (IEA aggregate)",
        "inventory",
        "aggregate",
        ("Oil and oil products",),
        (),
        "secondary",
        "IEA Crude + Oil products; not comparable to JODI TOTPRODS alone.",
    ),
)

BUCKET_BY_NAME: dict[str, CompareBucket] = {b.bucket: b for b in COMPARE_BUCKETS}
PRIMARY_BUCKETS: frozenset[str] = frozenset(
    b.bucket for b in COMPARE_BUCKETS if b.role == "primary"
)

IEA_STOCK_CATEGORIES: tuple[str, ...] = (
    "Total stocks",
    "Industry stocks",
    "Government stocks",
)

DEFAULT_TABLEAU_PATH = Path("data/processed/iea_jodi_profile/iea_jodi_tableau.csv")
DEFAULT_STATS_PATH = Path("data/processed/iea_jodi_profile/iea_jodi_overlap_stats.csv")


def compare_bucket_rules_table() -> pd.DataFrame:
    """Human-readable mapping rules for the notebook."""
    rows = []
    for b in COMPARE_BUCKETS:
        rows.append(
            {
                "compare_bucket": b.bucket,
                "label": b.label,
                "theme": b.theme,
                "compare_role": b.role,
                "iea_products": " + ".join(b.iea_products) if b.iea_products else "(none)",
                "jodi_products": " + ".join(b.jodi_products) if b.jodi_products else "(none)",
                "jodi_dataset": b.jodi_dataset,
                "notes": b.notes,
            }
        )
    return pd.DataFrame(rows)


def _month_start(series: pd.Series) -> pd.Series:
    s = series.astype(str)
    return pd.to_datetime(s.str.slice(0, 7) + "-01", errors="coerce")


def _quarter_start(series: pd.Series) -> pd.Series:
    s = series.astype(str)
    out = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns]")
    qmask = s.str.match(r"^\d{4}-Q[1-4]$", na=False)
    if qmask.any():
        parts = s[qmask].str.split("-Q", expand=True)
        year = parts[0].astype(int)
        quarter = parts[1].astype(int)
        month = ((quarter - 1) * 3 + 1).astype(str).str.zfill(2)
        out.loc[qmask] = pd.to_datetime(year.astype(str) + "-" + month + "-01")
    return out


def _attach_country_meta(df: pd.DataFrame, iso_col: str = "iso2") -> pd.DataFrame:
    out = df.copy()
    out["is_oecd"] = out[iso_col].isin(set(IEA_OECD_ISO.values()))
    return out


def _iea_product_to_buckets(theme: str) -> dict[str, list[CompareBucket]]:
    """Map each IEA product label to buckets that consume it for a theme."""
    out: dict[str, list[CompareBucket]] = {}
    for b in COMPARE_BUCKETS:
        if b.theme not in (theme, "both"):
            continue
        for prod in b.iea_products:
            out.setdefault(prod, []).append(b)
    return out


def _aggregate_iea_to_buckets(
    raw: pd.DataFrame,
    *,
    theme: str,
    name_col: str,
    value_col: str = "OBS_VALUE",
) -> pd.DataFrame:
    """Collapse IEA product rows into compare buckets (sum if multi-product)."""
    prod_map = _iea_product_to_buckets(theme)
    pieces = []
    for iea_prod, buckets in prod_map.items():
        sub = raw.loc[raw["Product"].eq(iea_prod)].copy()
        if sub.empty:
            continue
        for b in buckets:
            part = sub.copy()
            part["compare_bucket"] = b.bucket
            part["product_label"] = b.label
            part["compare_role"] = b.role
            part["iea_components"] = " + ".join(b.iea_products)
            part["jodi_components"] = (
                " + ".join(b.jodi_products) if b.jodi_products else ""
            )
            part["jodi_dataset"] = b.jodi_dataset
            pieces.append(part)

    if not pieces:
        return pd.DataFrame()

    stacked = pd.concat(pieces, ignore_index=True)
    group_cols = [
        "iso2",
        name_col,
        "date",
        "compare_bucket",
        "product_label",
        "compare_role",
        "iea_components",
        "jodi_components",
        "jodi_dataset",
    ]
    # Preserve stock category when present.
    if "Stock Category" in stacked.columns:
        group_cols.insert(3, "Stock Category")

    out = (
        stacked.groupby(group_cols, as_index=False, observed=True)[value_col]
        .sum(min_count=1)
        .rename(columns={name_col: "country_name", value_col: "iea_value"})
    )
    if "Stock Category" in out.columns:
        out = out.rename(columns={"Stock Category": "stock_category"})
    # Backward-compatible alias used by older notebook cells / Tableau sheets.
    out["product_compare"] = out["compare_bucket"]
    out["iea_product_detail"] = out["iea_components"]
    return out


def load_iea_oecd_demand_monthly(root: Path) -> pd.DataFrame:
    """OECDDEM monthly demand in KBD → compare buckets."""
    path = root / "data" / "raw" / "iea" / "OECDDEM.csv"
    raw = pd.read_csv(
        path,
        usecols=[
            "COUNTRY",
            "Country/Region",
            "Product",
            "FREQUENCY",
            "TIME_PERIOD",
            "OBS_VALUE",
            "UNIT",
        ],
        low_memory=False,
    )
    raw = raw.loc[raw["FREQUENCY"].eq("M") & raw["UNIT"].eq("KBD")].copy()
    raw["iso2"] = raw["COUNTRY"].map(IEA_ISO)
    raw = raw.loc[raw["iso2"].notna()].copy()
    raw["date"] = _month_start(raw["TIME_PERIOD"])
    raw = raw.loc[raw["date"].notna() & raw["OBS_VALUE"].notna()].copy()

    out = _aggregate_iea_to_buckets(raw, theme="demand", name_col="Country/Region")
    out["theme"] = "demand"
    out["stock_category"] = pd.NA
    out["frequency"] = "M"
    out["unit"] = "KBD"
    return _attach_country_meta(out)


def load_iea_non_oecd_demand_quarterly(root: Path) -> pd.DataFrame:
    """NOECDDEM quarterly Oil products → total_products bucket."""
    path = root / "data" / "raw" / "iea" / "NOECDDEM.csv"
    raw = pd.read_csv(
        path,
        usecols=[
            "COUNTRY",
            "Country",
            "Product",
            "FREQUENCY",
            "TIME_PERIOD",
            "OBS_VALUE",
            "UNIT",
        ],
        low_memory=False,
    )
    raw = raw.loc[
        raw["FREQUENCY"].eq("Q")
        & raw["Product"].eq("Oil products")
        & raw["UNIT"].eq("KBD")
    ].copy()
    raw["iso2"] = raw["COUNTRY"].map(IEA_ISO)
    raw = raw.loc[raw["iso2"].notna()].copy()
    raw["date"] = _quarter_start(raw["TIME_PERIOD"])
    raw = raw.loc[raw["date"].notna() & raw["OBS_VALUE"].notna()].copy()
    out = raw.rename(columns={"Country": "country_name", "OBS_VALUE": "iea_value"})
    b = BUCKET_BY_NAME["total_products"]
    out["compare_bucket"] = b.bucket
    out["product_compare"] = b.bucket
    out["product_label"] = b.label
    out["compare_role"] = b.role
    out["iea_components"] = "Oil products"
    out["jodi_components"] = "TOTPRODS"
    out["iea_product_detail"] = "Oil products"
    out["theme"] = "demand"
    out["stock_category"] = pd.NA
    out["frequency"] = "Q"
    out["unit"] = "KBD"
    out["jodi_dataset"] = "secondary"
    return _attach_country_meta(out)


def load_iea_stocks_monthly(root: Path) -> pd.DataFrame:
    """MOSSTOCKS monthly closing stocks in KBBL → compare buckets."""
    path = root / "data" / "raw" / "iea" / "MOSSTOCKS.csv"
    raw = pd.read_csv(
        path,
        usecols=[
            "COUNTRY",
            "Country",
            "Product",
            "Stock Category",
            "FREQUENCY",
            "TIME_PERIOD",
            "OBS_VALUE",
            "UNIT",
        ],
        low_memory=False,
    )
    wanted = {
        p for b in COMPARE_BUCKETS if b.theme in ("inventory", "both") for p in b.iea_products
    }
    raw = raw.loc[
        raw["FREQUENCY"].eq("M")
        & raw["Product"].isin(wanted)
        & raw["Stock Category"].isin(IEA_STOCK_CATEGORIES)
        & raw["UNIT"].eq("KB")
    ].copy()
    raw["iso2"] = raw["COUNTRY"].map(IEA_ISO)
    raw = raw.loc[raw["iso2"].notna()].copy()
    raw["date"] = _month_start(raw["TIME_PERIOD"])
    raw = raw.loc[raw["date"].notna() & raw["OBS_VALUE"].notna()].copy()

    out = _aggregate_iea_to_buckets(raw, theme="inventory", name_col="Country")
    out["theme"] = "inventory"
    out["frequency"] = "M"
    out["unit"] = "KBBL"
    out["iea_product_detail"] = (
        out["iea_components"].astype(str) + " | " + out["stock_category"].astype(str)
    )
    return _attach_country_meta(out)


def _jodi_bucket_frame(
    raw: pd.DataFrame,
    *,
    theme: str,
    value_col: str = "obs_value",
) -> pd.DataFrame:
    """Map / sum JODI energy_product rows into compare buckets."""
    pieces = []
    for b in COMPARE_BUCKETS:
        if b.theme not in (theme, "both"):
            continue
        if not b.jodi_products:
            continue
        sub = raw.loc[raw["energy_product"].isin(b.jodi_products)].copy()
        if sub.empty:
            continue
        gcols = ["iso2", "country_name", "date"]
        if "frequency" in sub.columns:
            gcols.append("frequency")
        part = (
            sub.groupby(gcols, as_index=False, observed=True)[value_col]
            .sum(min_count=1)
            .rename(columns={value_col: "jodi_value"})
        )
        part["compare_bucket"] = b.bucket
        part["product_compare"] = b.bucket
        part["product_label"] = b.label
        part["compare_role"] = b.role
        part["iea_components"] = " + ".join(b.iea_products)
        part["jodi_components"] = " + ".join(b.jodi_products)
        part["jodi_dataset"] = b.jodi_dataset
        pieces.append(part)

    if not pieces:
        return pd.DataFrame()
    return pd.concat(pieces, ignore_index=True)


def load_jodi_demand(root: Path) -> pd.DataFrame:
    """JODI secondary TOTDEMO in KBD → compare buckets (monthly + quarterly)."""
    path = root / "data" / "processed" / "jodi" / "jodi_secondary.parquet"
    raw = pd.read_parquet(
        path,
        columns=[
            "date",
            "ref_area",
            "country_name",
            "energy_product",
            "flow_breakdown",
            "unit_measure",
            "obs_value",
        ],
    )
    raw = raw.loc[
        raw["flow_breakdown"].eq("TOTDEMO") & raw["unit_measure"].eq("KBD")
    ].copy()
    raw["iso2"] = raw["ref_area"].astype(str)
    raw["date"] = pd.to_datetime(raw["date"])
    raw = raw.loc[raw["obs_value"].notna()].copy()
    raw["energy_product"] = raw["energy_product"].astype(str)

    monthly = raw.copy()
    monthly["frequency"] = "M"
    monthly_b = _jodi_bucket_frame(monthly, theme="demand")
    monthly_b["theme"] = "demand"
    monthly_b["stock_category"] = pd.NA
    monthly_b["unit"] = "KBD"

    q = raw.copy()
    q["quarter"] = q["date"].dt.to_period("Q").dt.start_time
    q = (
        q.groupby(
            ["iso2", "country_name", "energy_product", "quarter"],
            as_index=False,
            observed=True,
        )["obs_value"]
        .mean()
        .rename(columns={"quarter": "date"})
    )
    q["frequency"] = "Q"
    q_b = _jodi_bucket_frame(q, theme="demand")
    q_b["theme"] = "demand"
    q_b["stock_category"] = pd.NA
    q_b["unit"] = "KBD"

    out = pd.concat([monthly_b, q_b], ignore_index=True)
    return _attach_country_meta(out)


def load_jodi_stocks(root: Path) -> pd.DataFrame:
    """JODI CLOSTLV → compare buckets (incl. GASDIES+KEROSENE for MD)."""
    sec_path = root / "data" / "processed" / "jodi" / "jodi_secondary.parquet"
    pri_path = root / "data" / "processed" / "jodi" / "jodi_primary.parquet"

    sec = pd.read_parquet(
        sec_path,
        columns=[
            "date",
            "ref_area",
            "country_name",
            "energy_product",
            "flow_breakdown",
            "unit_measure",
            "obs_value",
        ],
    )
    sec = sec.loc[
        sec["flow_breakdown"].eq("CLOSTLV") & sec["unit_measure"].eq("KBBL")
    ].copy()

    pri = pd.read_parquet(
        pri_path,
        columns=[
            "date",
            "ref_area",
            "country_name",
            "energy_product",
            "flow_breakdown",
            "unit_measure",
            "obs_value",
        ],
    )
    pri = pri.loc[
        pri["flow_breakdown"].eq("CLOSTLV") & pri["unit_measure"].eq("KBBL")
    ].copy()

    raw = pd.concat([sec, pri], ignore_index=True)
    raw["iso2"] = raw["ref_area"].astype(str)
    raw["date"] = pd.to_datetime(raw["date"])
    raw = raw.loc[raw["obs_value"].notna()].copy()
    raw["energy_product"] = raw["energy_product"].astype(str)

    out = _jodi_bucket_frame(raw, theme="inventory")
    out["theme"] = "inventory"
    out["stock_category"] = "CLOSTLV (undifferentiated)"
    out["frequency"] = "M"
    out["unit"] = "KBBL"
    return _attach_country_meta(out)


def _merge_iea_jodi(
    iea: pd.DataFrame,
    jodi: pd.DataFrame,
    *,
    join_keys: list[str],
) -> pd.DataFrame:
    """Outer merge IEA and JODI panels on shared keys."""
    iea_extra = [
        "country_name",
        "iea_value",
        "product_label",
        "iea_product_detail",
        "iea_components",
        "jodi_components",
        "compare_role",
        "is_oecd",
        "stock_category",
    ]
    jodi_extra = [
        "country_name",
        "jodi_value",
        "product_label",
        "iea_components",
        "jodi_components",
        "compare_role",
    ]
    iea_cols = list(dict.fromkeys(join_keys + [c for c in iea_extra if c in iea.columns]))
    jodi_cols = list(dict.fromkeys(join_keys + [c for c in jodi_extra if c in jodi.columns]))

    iea_sub = iea[iea_cols].copy()
    jodi_sub = jodi[jodi_cols].copy()

    merged = iea_sub.merge(
        jodi_sub,
        on=join_keys,
        how="outer",
        suffixes=("_iea", "_jodi"),
    )
    for col in (
        "country_name",
        "product_label",
        "compare_role",
        "iea_components",
        "jodi_components",
    ):
        left, right = f"{col}_iea", f"{col}_jodi"
        if left in merged.columns and right in merged.columns:
            merged[col] = merged[left].combine_first(merged[right])
            merged = merged.drop(columns=[left, right])
        elif left in merged.columns:
            merged = merged.rename(columns={left: col})
        elif right in merged.columns:
            merged = merged.rename(columns={right: col})

    merged["diff"] = merged["iea_value"] - merged["jodi_value"]
    merged["pct_diff"] = np.where(
        merged["jodi_value"].notna() & (merged["jodi_value"] != 0),
        100.0 * merged["diff"] / merged["jodi_value"],
        np.nan,
    )
    merged["has_both"] = merged["iea_value"].notna() & merged["jodi_value"].notna()
    merged["abs_diff"] = merged["diff"].abs()
    return merged


def build_overlap_panels(root: Path) -> dict[str, pd.DataFrame]:
    """Build demand + inventory overlap DataFrames on compare buckets."""
    iea_dem_m = load_iea_oecd_demand_monthly(root)
    iea_dem_q = load_iea_non_oecd_demand_quarterly(root)
    iea_stk = load_iea_stocks_monthly(root)
    jodi_dem = load_jodi_demand(root)
    jodi_stk = load_jodi_stocks(root)

    join_keys = [
        "iso2",
        "date",
        "theme",
        "compare_bucket",
        "product_compare",
        "frequency",
        "unit",
        "jodi_dataset",
    ]

    demand_m = _merge_iea_jodi(
        iea_dem_m,
        jodi_dem.loc[jodi_dem["frequency"].eq("M")],
        join_keys=join_keys,
    )
    demand_q = _merge_iea_jodi(
        iea_dem_q,
        jodi_dem.loc[
            jodi_dem["frequency"].eq("Q")
            & jodi_dem["compare_bucket"].eq("total_products")
        ],
        join_keys=join_keys,
    )
    # IEA has Government / Industry / Total; JODI CLOSTLV is undifferentiated.
    # Merge replicates JODI against each IEA stock_category row.
    inventory = _merge_iea_jodi(
        iea_stk,
        jodi_stk,
        join_keys=join_keys,
    )

    combined = pd.concat([demand_m, demand_q, inventory], ignore_index=True)
    combined["date"] = pd.to_datetime(combined["date"])
    combined["year"] = combined["date"].dt.year
    combined["month"] = combined["date"].dt.month
    combined["is_oecd"] = combined["iso2"].isin(set(IEA_OECD_ISO.values()))
    if "compare_bucket" not in combined.columns and "product_compare" in combined.columns:
        combined["compare_bucket"] = combined["product_compare"]
    if "compare_role" not in combined.columns:
        combined["compare_role"] = combined["compare_bucket"].map(
            lambda x: BUCKET_BY_NAME[x].role if x in BUCKET_BY_NAME else "primary"
        )
    stock_cat = (
        combined["stock_category"].fillna("").astype(str)
        if "stock_category" in combined.columns
        else ""
    )
    combined["compare_key"] = (
        combined["theme"].astype(str)
        + "|"
        + combined["compare_bucket"].astype(str)
        + "|"
        + combined["frequency"].astype(str)
        + "|"
        + stock_cat
        + "|"
        + combined["compare_role"].astype(str)
    )
    combined = combined.sort_values(
        ["theme", "iso2", "compare_bucket", "stock_category", "date"]
    ).reset_index(drop=True)
    return {
        "demand_monthly": demand_m,
        "demand_quarterly": demand_q,
        "inventory": inventory,
        "combined": combined,
    }


def build_overlap_stats(combined: pd.DataFrame) -> pd.DataFrame:
    """Series-level fit stats for rows where both sources report."""
    both = combined.loc[combined["has_both"]].copy()
    if both.empty:
        return pd.DataFrame()

    def _stats(g: pd.DataFrame) -> pd.Series:
        x = g["iea_value"].astype(float)
        y = g["jodi_value"].astype(float)
        n = len(g)
        corr = x.corr(y) if n >= 3 and x.std() > 0 and y.std() > 0 else np.nan
        diff = x - y
        return pd.Series(
            {
                "n_obs": n,
                "corr": corr,
                "rmse": float(np.sqrt(np.mean(np.square(diff)))),
                "mean_bias": float(diff.mean()),
                "mean_abs_diff": float(diff.abs().mean()),
                "mean_pct_diff": float(g["pct_diff"].mean()),
                "median_pct_diff": float(g["pct_diff"].median()),
                "first_date": g["date"].min(),
                "last_date": g["date"].max(),
                "iea_last": float(g.sort_values("date")["iea_value"].iloc[-1]),
                "jodi_last": float(g.sort_values("date")["jodi_value"].iloc[-1]),
            }
        )

    group_cols = [
        "iso2",
        "country_name",
        "theme",
        "compare_bucket",
        "product_compare",
        "product_label",
        "compare_role",
        "frequency",
        "unit",
        "stock_category",
        "compare_key",
        "is_oecd",
        "iea_components",
        "jodi_components",
    ]
    group_cols = [c for c in group_cols if c in both.columns]
    stats = (
        both.groupby(group_cols, dropna=False, observed=True)
        .apply(_stats, include_groups=False)
        .reset_index()
    )
    stats = stats.sort_values(["theme", "rmse"], ascending=[True, False]).reset_index(drop=True)
    return stats


def build_tableau_long(combined: pd.DataFrame) -> pd.DataFrame:
    """Unpivot wide overlap panel to long format (Source = IEA / JODI) for Tableau."""
    id_cols = [
        "date",
        "year",
        "month",
        "iso2",
        "country_name",
        "is_oecd",
        "theme",
        "compare_bucket",
        "product_compare",
        "product_label",
        "compare_role",
        "iea_components",
        "jodi_components",
        "iea_product_detail",
        "stock_category",
        "frequency",
        "unit",
        "jodi_dataset",
        "compare_key",
        "iea_value",
        "jodi_value",
        "diff",
        "pct_diff",
        "has_both",
    ]
    id_cols = [c for c in id_cols if c in combined.columns]
    base = combined[id_cols].copy()

    iea_long = base.copy()
    iea_long["source"] = "IEA"
    iea_long["value"] = iea_long["iea_value"]

    jodi_long = base.copy()
    jodi_long["source"] = "JODI"
    jodi_long["value"] = jodi_long["jodi_value"]

    long = pd.concat([iea_long, jodi_long], ignore_index=True)
    long = long.loc[long["value"].notna()].copy()
    long = long.sort_values(
        ["theme", "iso2", "product_compare", "stock_category", "date", "source"]
    ).reset_index(drop=True)
    return long


MEASURE_COLS: tuple[str, ...] = (
    "iea_value",
    "jodi_value",
    "diff",
    "pct_diff",
    "abs_diff",
    "value",
    "corr",
    "rmse",
    "mean_bias",
    "mean_abs_diff",
    "mean_pct_diff",
    "median_pct_diff",
    "iea_last",
    "jodi_last",
)


def _coerce_measures_float64(df: pd.DataFrame) -> pd.DataFrame:
    """Force measure columns to plain float64 so CSV writers emit real numbers.

    Nullable pandas Float64 / object leftovers make Tableau treat the column as
    text under some locales. Empty cells stay blank (not the string 'nan').
    """
    out = df.copy()
    for col in MEASURE_COLS:
        if col not in out.columns:
            continue
        out[col] = pd.to_numeric(out[col], errors="coerce").astype("float64")
    return out


def _write_tableau_csv(
    df: pd.DataFrame,
    path: Path,
    *,
    decimal: str = ".",
    sep: str = ",",
) -> None:
    """Write CSV for Excel / Tableau with plain numeric measures.

    Default is US/UK style: ``.`` decimal, ``,`` field separator, **no**
    thousands separators (so ``1003.41`` never becomes ``1,003.41`` in the file).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(
        path,
        index=False,
        date_format="%Y-%m-%d",
        sep=sep,
        decimal=decimal,
        float_format="%.10g",
        na_rep="",
        quoting=0,  # QUOTE_MINIMAL — do not quote plain numbers
    )


def export_tableau_csv(
    root: Path,
    *,
    wide_path: Path | None = None,
    long_path: Path | None = None,
    stats_path: Path | None = None,
    decimal: str = ".",
    sep: str = ",",
) -> dict[str, Path]:
    """Write Tableau-ready CSVs and return output paths.

    Defaults: US/UK Excel/Tableau (``.`` decimal, ``,`` field sep). Measures are
    coerced to float64 and written without thousands separators.
    """
    wide_path = wide_path or (root / DEFAULT_TABLEAU_PATH)
    long_path = long_path or wide_path.with_name("iea_jodi_tableau_long.csv")
    stats_path = stats_path or (root / DEFAULT_STATS_PATH)

    panels = build_overlap_panels(root)
    combined = _coerce_measures_float64(panels["combined"])
    stats = _coerce_measures_float64(build_overlap_stats(combined))
    long = _coerce_measures_float64(build_tableau_long(combined))

    for path in (wide_path, long_path, stats_path):
        path.parent.mkdir(parents=True, exist_ok=True)

    # Tableau-friendly column order (wide = primary compare file).
    wide_cols = [
        "date",
        "year",
        "month",
        "iso2",
        "country_name",
        "is_oecd",
        "theme",
        "compare_bucket",
        "product_compare",
        "product_label",
        "compare_role",
        "iea_components",
        "jodi_components",
        "iea_product_detail",
        "stock_category",
        "frequency",
        "unit",
        "jodi_dataset",
        "compare_key",
        "iea_value",
        "jodi_value",
        "diff",
        "pct_diff",
        "abs_diff",
        "has_both",
    ]
    wide_cols = [c for c in wide_cols if c in combined.columns]
    _write_tableau_csv(
        combined[wide_cols], wide_path, decimal=decimal, sep=sep
    )

    long_cols = [
        "date",
        "year",
        "month",
        "iso2",
        "country_name",
        "is_oecd",
        "theme",
        "compare_bucket",
        "product_compare",
        "product_label",
        "compare_role",
        "iea_components",
        "jodi_components",
        "stock_category",
        "frequency",
        "unit",
        "compare_key",
        "source",
        "value",
        "iea_value",
        "jodi_value",
        "diff",
        "pct_diff",
        "has_both",
    ]
    long_cols = [c for c in long_cols if c in long.columns]
    _write_tableau_csv(long[long_cols], long_path, decimal=decimal, sep=sep)

    if not stats.empty:
        _write_tableau_csv(stats, stats_path, decimal=decimal, sep=sep)

    return {"wide": wide_path, "long": long_path, "stats": stats_path}


# ---------------------------------------------------------------------------
# Interactive notebook explorer (filters + Plotly)
# ---------------------------------------------------------------------------

MEASURE_OPTIONS: dict[str, str] = {
    "Levels (IEA vs JODI)": "levels",
    "Difference (IEA − JODI)": "diff",
    "% difference vs JODI": "pct_diff",
}


def filter_overlap(
    combined: pd.DataFrame,
    *,
    countries: list[str] | None = None,
    theme: str | None = "demand",
    products: list[str] | None = None,
    stock_categories: list[str] | None = None,
    frequency: str | None = "M",
    both_only: bool = True,
    primary_only: bool = True,
    date_start: str | pd.Timestamp | None = None,
    date_end: str | pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Filter the wide overlap panel for charting.

    ``products`` are compare_bucket ids (e.g. ``gasoil_diesel``, ``gasoline``).
    ``primary_only`` keeps apples-to-apples buckets (excludes IEA diesel children
    and Oil-and-oil-products aggregate).
    """
    out = combined.copy()
    out["date"] = pd.to_datetime(out["date"])

    if countries:
        out = out.loc[out["iso2"].isin(countries)]
    if theme:
        out = out.loc[out["theme"].eq(theme)]
    if products:
        bucket_col = "compare_bucket" if "compare_bucket" in out.columns else "product_compare"
        out = out.loc[out[bucket_col].isin(products)]
    if frequency:
        out = out.loc[out["frequency"].eq(frequency)]
    if both_only and "has_both" in out.columns:
        out = out.loc[out["has_both"].astype(bool)]
    if primary_only and "compare_role" in out.columns:
        out = out.loc[out["compare_role"].eq("primary")]

    if theme == "inventory" and stock_categories:
        out = out.loc[out["stock_category"].isin(stock_categories)]

    if date_start is not None:
        out = out.loc[out["date"] >= pd.Timestamp(date_start)]
    if date_end is not None:
        out = out.loc[out["date"] <= pd.Timestamp(date_end)]

    sort_cols = [c for c in ["iso2", "compare_bucket", "product_compare", "stock_category", "date"] if c in out.columns]
    return out.sort_values(sort_cols).reset_index(drop=True)


def overlap_to_plot_long(
    filtered: pd.DataFrame,
    *,
    measure: str = "levels",
) -> pd.DataFrame:
    """Turn filtered wide overlap into long rows for Plotly.

    ``measure``:
      - ``levels`` → IEA / JODI value columns
      - ``diff`` / ``pct_diff`` → single series (still labelled by source concept)
    """
    if filtered.empty:
        return filtered.copy()

    base_cols = [
        "date",
        "iso2",
        "country_name",
        "theme",
        "compare_bucket",
        "product_compare",
        "stock_category",
        "frequency",
        "unit",
    ]
    base_cols = [c for c in base_cols if c in filtered.columns]

    if measure == "levels":
        iea = filtered[base_cols + ["iea_value"]].rename(columns={"iea_value": "value"})
        iea["series"] = "IEA"
        jodi = filtered[base_cols + ["jodi_value"]].rename(columns={"jodi_value": "value"})
        jodi["series"] = "JODI"
        long = pd.concat([iea, jodi], ignore_index=True)
        long = long.loc[long["value"].notna()].copy()
    elif measure in ("diff", "pct_diff"):
        col = measure
        long = filtered[base_cols + [col]].rename(columns={col: "value"}).copy()
        long["series"] = "IEA - JODI" if measure == "diff" else "% diff vs JODI"
        long = long.loc[long["value"].notna()].copy()
    else:
        raise ValueError(f"Unknown measure {measure!r}; expected levels|diff|pct_diff")

    bucket = long["compare_bucket"] if "compare_bucket" in long.columns else long["product_compare"]
    long["legend"] = (
        long["iso2"].astype(str)
        + " | "
        + long["series"].astype(str)
        + " | "
        + bucket.astype(str)
    )
    if "stock_category" in long.columns:
        sc = long["stock_category"].fillna("").astype(str)
        mask = sc.ne("") & sc.ne("nan")
        long.loc[mask, "legend"] = long.loc[mask, "legend"] + " | " + sc[mask]

    return long.sort_values(["legend", "date"]).reset_index(drop=True)


def build_iea_jodi_compare_chart(
    combined: pd.DataFrame,
    *,
    countries: list[str] | None = None,
    theme: str = "demand",
    products: list[str] | None = None,
    stock_categories: list[str] | None = None,
    frequency: str = "M",
    measure: str = "levels",
    both_only: bool = True,
    primary_only: bool = True,
    date_start: str | pd.Timestamp | None = None,
    date_end: str | pd.Timestamp | None = None,
    title: str | None = None,
) -> "go.Figure":
    """Build a Plotly time-series comparing IEA vs JODI under the given filters."""
    import plotly.express as px
    import plotly.graph_objects as go

    filtered = filter_overlap(
        combined,
        countries=countries,
        theme=theme,
        products=products,
        stock_categories=stock_categories,
        frequency=frequency,
        both_only=both_only,
        primary_only=primary_only,
        date_start=date_start,
        date_end=date_end,
    )
    long = overlap_to_plot_long(filtered, measure=measure)

    if long.empty:
        fig = go.Figure()
        fig.update_layout(
            title="No rows match the current filters",
            template="plotly_white",
            height=360,
        )
        fig.add_annotation(
            text="Widen countries / products / date range, or turn off 'both sources only'.",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
        )
        return fig

    unit = ""
    if "unit" in long.columns and long["unit"].notna().any():
        unit = str(long["unit"].dropna().iloc[0])

    y_title = {
        "levels": f"Value ({unit})" if unit else "Value",
        "diff": f"IEA - JODI ({unit})" if unit else "IEA - JODI",
        "pct_diff": "% difference vs JODI",
    }.get(measure, "Value")

    bucket_col = "compare_bucket" if "compare_bucket" in long.columns else "product_compare"
    if bucket_col not in long.columns:
        bucket_col = "product_compare"

    fig = px.line(
        long,
        x="date",
        y="value",
        color="legend",
        hover_data={
            "iso2": True,
            "country_name": True,
            "product_compare": True,
            "series": True,
            "legend": False,
        },
        title=title
        or (
            f"IEA vs JODI — {theme} | {measure} | "
            f"{', '.join(products or ['all buckets'])}"
        ),
    )
    fig.update_layout(
        template="plotly_white",
        height=480,
        legend_title_text="",
        yaxis_title=y_title,
        xaxis_title="",
        hovermode="x unified",
        margin=dict(l=60, r=20, t=60, b=40),
    )
    fig.update_traces(line=dict(width=2))
    return fig


def make_iea_jodi_explorer(combined: pd.DataFrame):
    """Return an ipywidgets UI that filters and charts the overlap panel.

    Defaults to ``compare_role=primary`` buckets only (apples-to-apples).
    """
    import ipywidgets as widgets
    from IPython.display import display

    df = combined.copy()
    df["date"] = pd.to_datetime(df["date"])
    if "compare_bucket" not in df.columns:
        df["compare_bucket"] = df["product_compare"]

    country_opts = (
        df[["iso2", "country_name"]]
        .drop_duplicates()
        .sort_values("iso2")
        .assign(label=lambda d: d["iso2"] + " — " + d["country_name"].astype(str))
    )
    country_map = dict(zip(country_opts["label"], country_opts["iso2"]))

    # Bucket picker: show label, store bucket id. Prefer primary role options.
    bucket_meta = (
        df[["compare_bucket", "product_label", "compare_role", "theme"]]
        .drop_duplicates()
        .dropna(subset=["compare_bucket"])
    )

    def _bucket_options(theme: str, primary_only: bool) -> list[tuple[str, str]]:
        sub = bucket_meta.loc[bucket_meta["theme"].eq(theme)]
        if primary_only and "compare_role" in sub.columns:
            sub = sub.loc[sub["compare_role"].eq("primary")]
        rows = []
        for _, r in sub.sort_values("compare_bucket").iterrows():
            label = f"{r['compare_bucket']} — {r['product_label']}"
            rows.append((label, r["compare_bucket"]))
        return rows

    stock_opts = sorted(
        s
        for s in df["stock_category"].dropna().astype(str).unique().tolist()
        if s and s != "nan" and s != "CLOSTLV (undifferentiated)"
    )
    freq_opts = sorted(df["frequency"].dropna().unique().tolist()) or ["M", "Q"]
    theme_opts = sorted(df["theme"].dropna().unique().tolist()) or ["demand", "inventory"]

    dmin = df["date"].min()
    dmax = df["date"].max()
    default_start = max(dmin, pd.Timestamp(dmax) - pd.DateOffset(years=5))

    default_country_labels = []
    for iso in ("DE", "US", "JP", "GB", "FR"):
        matches = country_opts.loc[country_opts["iso2"].eq(iso), "label"]
        if not matches.empty:
            default_country_labels = [matches.iloc[0]]
            break
    if not default_country_labels and not country_opts.empty:
        default_country_labels = [country_opts["label"].iloc[0]]

    initial_theme = "demand" if "demand" in theme_opts else theme_opts[0]
    initial_buckets = _bucket_options(initial_theme, primary_only=True)
    default_bucket_vals = []
    for prefer in ("gasoline", "gasoil_diesel", "total_products", "middle_distillates"):
        if any(v == prefer for _, v in initial_buckets):
            default_bucket_vals = [prefer]
            break
    if not default_bucket_vals and initial_buckets:
        default_bucket_vals = [initial_buckets[0][1]]

    default_stocks = (
        ["Total stocks"] if "Total stocks" in stock_opts else stock_opts[:1]
    )

    w_style = {"description_width": "120px"}
    w_layout = widgets.Layout(width="560px")

    countries_w = widgets.SelectMultiple(
        options=list(country_map.keys()),
        value=tuple(default_country_labels),
        description="Countries:",
        style=w_style,
        layout=widgets.Layout(width="560px", height="140px"),
    )
    theme_w = widgets.Dropdown(
        options=theme_opts,
        value=initial_theme,
        description="Theme:",
        style=w_style,
        layout=w_layout,
    )
    products_w = widgets.SelectMultiple(
        options=initial_buckets,
        value=tuple(default_bucket_vals),
        description="Buckets:",
        style=w_style,
        layout=widgets.Layout(width="560px", height="140px"),
    )
    stocks_w = widgets.SelectMultiple(
        options=stock_opts,
        value=tuple(default_stocks),
        description="Stock cat.:",
        style=w_style,
        layout=widgets.Layout(width="560px", height="90px"),
        disabled=True,
    )
    freq_w = widgets.Dropdown(
        options=freq_opts,
        value="M" if "M" in freq_opts else freq_opts[0],
        description="Frequency:",
        style=w_style,
        layout=w_layout,
    )
    measure_w = widgets.Dropdown(
        options=list(MEASURE_OPTIONS.keys()),
        value="Levels (IEA vs JODI)",
        description="Measure:",
        style=w_style,
        layout=w_layout,
    )
    both_w = widgets.Checkbox(
        value=True,
        description="Both sources only (has_both)",
        indent=False,
    )
    primary_w = widgets.Checkbox(
        value=True,
        description="Primary buckets only (apples-to-apples)",
        indent=False,
    )
    start_w = widgets.DatePicker(
        description="From:",
        value=default_start.date(),
        style=w_style,
    )
    end_w = widgets.DatePicker(
        description="To:",
        value=dmax.date(),
        style=w_style,
    )
    status_w = widgets.HTML(value="")
    out = widgets.Output()

    def _refresh_bucket_options(*_change) -> None:
        opts = _bucket_options(theme_w.value, primary_only=primary_w.value)
        products_w.options = opts
        # Keep selection if still valid; else pick first primary.
        keep = [v for v in products_w.value if v in {o[1] for o in opts}]
        if not keep and opts:
            prefer = "middle_distillates" if theme_w.value == "inventory" else "gasoline"
            keep = [prefer] if prefer in {o[1] for o in opts} else [opts[0][1]]
        products_w.value = tuple(keep)
        stocks_w.disabled = theme_w.value != "inventory"

    theme_w.observe(_refresh_bucket_options, names="value")
    primary_w.observe(_refresh_bucket_options, names="value")

    def _render(*_args) -> None:
        with out:
            out.clear_output(wait=True)
            isos = [country_map[lbl] for lbl in countries_w.value]
            measure_key = MEASURE_OPTIONS[measure_w.value]
            stock_cats = list(stocks_w.value) if theme_w.value == "inventory" else None
            buckets = list(products_w.value)
            fig = build_iea_jodi_compare_chart(
                df,
                countries=isos or None,
                theme=theme_w.value,
                products=buckets or None,
                stock_categories=stock_cats,
                frequency=freq_w.value,
                measure=measure_key,
                both_only=both_w.value,
                primary_only=primary_w.value,
                date_start=start_w.value,
                date_end=end_w.value,
            )
            n = len(
                filter_overlap(
                    df,
                    countries=isos or None,
                    theme=theme_w.value,
                    products=buckets or None,
                    stock_categories=stock_cats,
                    frequency=freq_w.value,
                    both_only=both_w.value,
                    primary_only=primary_w.value,
                    date_start=start_w.value,
                    date_end=end_w.value,
                )
            )
            status_w.value = (
                f"<b>{n:,}</b> wide rows | measure=<code>{measure_key}</code> | "
                f"countries={', '.join(isos) or '-'} | "
                f"buckets={', '.join(buckets) or '-'}"
            )
            fig.show()

    for w in (
        countries_w,
        theme_w,
        products_w,
        stocks_w,
        freq_w,
        measure_w,
        both_w,
        primary_w,
        start_w,
        end_w,
    ):
        w.observe(_render, names="value")

    controls = widgets.VBox(
        [
            widgets.HTML(
                "<b>IEA vs JODI explorer</b> — primary buckets avoid diesel double-counting "
                "and map Middle distillates to JODI GASDIES+KEROSENE"
            ),
            countries_w,
            theme_w,
            products_w,
            stocks_w,
            freq_w,
            measure_w,
            both_w,
            primary_w,
            widgets.HBox([start_w, end_w]),
            status_w,
        ]
    )
    display(controls, out)
    _render()
    return controls

