"""Aggregate warehouse series across multiple countries."""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from analytics.core.loader import (
    load_demand_canonical,
    load_jodi_compare_panels,
    load_kayrros_series,
    load_official_demand,
)
from warehouse.country_hooks import load_reference
from warehouse.registry import get_country


def _month_periods(df: pd.DataFrame) -> pd.Series:
    return pd.to_datetime(df["date"]).dt.to_period("M")


def country_reporting_summary(country_ids: list[str]) -> pd.DataFrame:
    """Latest reported month per country (from canonical demand)."""
    rows: list[dict[str, object]] = []
    for cid in country_ids:
        cfg = get_country(cid)
        sl = load_demand_canonical(cid)
        if sl.empty:
            rows.append(
                {
                    "country_id": cid,
                    "country_name": cfg.display_name,
                    "latest_date": pd.NaT,
                    "latest_month": None,
                }
            )
            continue
        latest = pd.to_datetime(sl["date"]).max()
        rows.append(
            {
                "country_id": cid,
                "country_name": cfg.display_name,
                "latest_date": latest,
                "latest_month": latest.to_period("M"),
            }
        )
    out = pd.DataFrame(rows)
    if not out.empty and out["latest_date"].notna().any():
        out["latest_month_label"] = out["latest_date"].dt.strftime("%Y-%m")
    else:
        out["latest_month_label"] = None
    return out


def full_coverage_months(country_ids: list[str]) -> set[pd.Period]:
    """Calendar months where every selected country has at least one canonical row."""
    month_sets: list[set[pd.Period]] = []
    for cid in country_ids:
        sl = load_demand_canonical(cid)
        if sl.empty:
            return set()
        month_sets.append(set(_month_periods(sl).unique()))
    if not month_sets:
        return set()
    return set.intersection(*month_sets)


def balanced_through_date(country_ids: list[str]) -> pd.Timestamp | None:
    """Earliest latest-report date across countries (safe aggregate end)."""
    summary = country_reporting_summary(country_ids)
    if summary.empty or summary["latest_date"].isna().any():
        return None
    return pd.Timestamp(summary["latest_date"].min())


def filter_to_full_coverage_months(
    df: pd.DataFrame,
    months: set[pd.Period],
) -> pd.DataFrame:
    if df.empty or not months or "date" not in df.columns:
        return df
    mask = _month_periods(df).isin(months)
    return df.loc[mask].copy()


def reporting_metadata(country_ids: list[str]) -> dict[str, object]:
    """Summary for dashboard: per-country latest dates and balanced end."""
    by_country = country_reporting_summary(country_ids)
    months = full_coverage_months(country_ids)
    balanced = balanced_through_date(country_ids)
    balanced_label = balanced.strftime("%Y-%m") if balanced is not None else None
    return {
        "by_country": by_country,
        "full_coverage_months": months,
        "balanced_through": balanced,
        "balanced_through_label": balanced_label,
        "n_countries": len(country_ids),
    }


def multi_country_display_name(country_ids: list[str]) -> str:
    """Short title for charts and exports."""
    names = [get_country(cid).display_name for cid in country_ids]
    if len(names) == 1:
        return names[0]
    if len(names) <= 3:
        return " + ".join(names)
    return f"{names[0]} + {len(names) - 1} others ({len(names)} countries)"


def export_slug(country_ids: list[str]) -> str:
    """Filesystem-safe prefix for multi-country CSV/HTML exports."""
    if len(country_ids) == 1:
        return country_ids[0]
    head = "_".join(sorted(country_ids)[:3])
    if len(country_ids) > 3:
        return f"multi_{head}_plus{len(country_ids) - 3}"
    return f"multi_{head}"


def _sum_panels(
    frames: list[pd.DataFrame],
    *,
    panel_col: str = "panel",
) -> pd.DataFrame:
    if not frames:
        return pd.DataFrame(columns=["date", panel_col, "value_kbd", "is_provisional"])
    combined = pd.concat(frames, ignore_index=True)
    return (
        combined.groupby(["date", panel_col], as_index=False)
        .agg(
            value_kbd=("value_kbd", "sum"),
            is_provisional=("is_provisional", "max"),
        )
        .sort_values("date")
    )


def aggregate_demand_canonical(
    country_ids: list[str],
    *,
    include_country_column: bool = False,
) -> pd.DataFrame:
    """
    Sum canonical panel demand (kbd) across countries.

    Returns aggregated series by default; set ``include_country_column`` for
    per-country long format (country_id, date, panel, value_kbd, …).
    """
    frames: list[pd.DataFrame] = []
    for cid in country_ids:
        sl = load_demand_canonical(cid)
        if sl.empty:
            continue
        sl = sl.copy()
        sl["country_id"] = cid
        sl["country_name"] = get_country(cid).display_name
        frames.append(sl)
    if not frames:
        return pd.DataFrame(
            columns=["date", "panel", "value_kbd", "is_provisional"]
        )
    combined = pd.concat(frames, ignore_index=True)
    if include_country_column:
        return combined.sort_values(["date", "country_id", "panel"])
    months = full_coverage_months(country_ids)
    if len(country_ids) > 1 and months:
        combined = filter_to_full_coverage_months(combined, months)
    return _sum_panels([combined], panel_col="panel")


def aggregate_official_demand(country_ids: list[str]) -> pd.DataFrame:
    """Concat official demand with ``country_id`` / ``country_name`` columns."""
    frames: list[pd.DataFrame] = []
    for cid in country_ids:
        sl = load_official_demand(cid)
        if sl.empty:
            continue
        sl = sl.copy()
        sl["country_id"] = cid
        sl["country_name"] = get_country(cid).display_name
        frames.append(sl)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).sort_values(
        ["date", "country_id", "product_native"]
    )


def aggregate_jodi_compare_panels(
    country_ids: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """Sum official and JODI compare panels across countries (common panels only)."""
    official_frames: list[pd.DataFrame] = []
    jodi_frames: list[pd.DataFrame] = []
    panel_sets: list[set[str]] = []

    for cid in country_ids:
        official, jodi, panels = load_jodi_compare_panels(cid)
        panel_sets.append(set(panels))
        if not official.empty:
            official_frames.append(official)
        if not jodi.empty:
            jodi_frames.append(jodi)

    off_agg = _sum_panels(official_frames)
    jodi_agg = _sum_panels(jodi_frames)

    months = full_coverage_months(country_ids)
    if len(country_ids) > 1 and months:
        off_agg = filter_to_full_coverage_months(off_agg, months)
        jodi_agg = filter_to_full_coverage_months(jodi_agg, months)

    if panel_sets:
        common = set.intersection(*panel_sets) if len(panel_sets) > 1 else panel_sets[0]
    else:
        common = set()

    order = sorted(common)
    if order:
        off_agg = off_agg[off_agg["panel"].isin(order)]
        jodi_agg = jodi_agg[jodi_agg["panel"].isin(order)]
    return off_agg, jodi_agg, order


def aggregate_kayrros_jet(country_ids: list[str]) -> pd.DataFrame:
    """Sum Kayrros jet fuel (kbd) across countries by month."""
    frames: list[pd.DataFrame] = []
    for cid in country_ids:
        if not get_country(cid).kayrros_enabled:
            continue
        sl = load_kayrros_series(cid, product_canonical="Jet fuel")
        if sl.empty:
            continue
        sl = sl.copy()
        sl["country_id"] = cid
        frames.append(sl)
    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True)
    months = full_coverage_months(country_ids)
    if len(country_ids) > 1 and months:
        combined = filter_to_full_coverage_months(combined, months)
    return (
        combined.groupby(["date", "product_canonical"], as_index=False)["value_kbd"]
        .sum()
        .sort_values("date")
    )


def aggregate_official_jet(
    country_ids: list[str],
    *,
    jet_product_by_country: Optional[dict[str, str]] = None,
) -> pd.DataFrame:
    """Sum official jet native series (kbd) where configured."""
    frames: list[pd.DataFrame] = []
    for cid in country_ids:
        cfg = get_country(cid)
        ref = load_reference(cfg)
        jet_native = (jet_product_by_country or {}).get(cid)
        if jet_native is None:
            jet_native = cfg.jet_product_native
            if not jet_native and ref is not None:
                jet_native = getattr(ref, "JET_PRODUCT_NATIVE", None) or getattr(
                    ref, "PRODUCT_JET_KEROSENE", None
                )
        if not jet_native:
            continue
        demand = load_official_demand(cid)
        sl = demand[demand["product_native"] == jet_native].copy()
        if sl.empty:
            continue
        sl["country_id"] = cid
        frames.append(sl)
    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True)
    months = full_coverage_months(country_ids)
    if len(country_ids) > 1 and months:
        combined = filter_to_full_coverage_months(combined, months)
    return (
        combined.groupby(["date"], as_index=False)
        .agg(
            value_kbd=("value_kbd", "sum"),
            is_provisional=("is_provisional", "max"),
        )
        .sort_values("date")
    )


def load_country_bundle(country_ids: list[str]) -> dict[str, object]:
    """Load or aggregate all frames used by the demand dashboard."""
    if len(country_ids) == 1:
        cid = country_ids[0]
        demand = load_official_demand(cid)
        demand_canonical = load_demand_canonical(cid)
        official_jodi, jodi, jodi_panels = load_jodi_compare_panels(cid)
        kayrros = load_kayrros_series(cid, product_canonical="Jet fuel")
        cfg = get_country(cid)
        ref = load_reference(cfg)
        jet_native = cfg.jet_product_native
        if not jet_native and ref is not None:
            jet_native = getattr(ref, "JET_PRODUCT_NATIVE", None)
        official_jet = (
            demand[demand["product_native"] == jet_native].copy()
            if jet_native
            else pd.DataFrame()
        )
        return {
            "demand": demand,
            "demand_canonical": demand_canonical,
            "official_jodi": official_jodi,
            "jodi": jodi,
            "jodi_panels": jodi_panels,
            "kayrros": kayrros,
            "official_jet": official_jet,
            "demand_by_country": pd.DataFrame(),
            "canonical_by_country": pd.DataFrame(),
        }

    demand = aggregate_official_demand(country_ids)
    reporting = reporting_metadata(country_ids)
    demand_canonical = aggregate_demand_canonical(country_ids)
    canonical_by_country = aggregate_demand_canonical(
        country_ids, include_country_column=True
    )
    official_jodi, jodi, jodi_panels = aggregate_jodi_compare_panels(country_ids)
    kayrros = aggregate_kayrros_jet(country_ids)
    official_jet = aggregate_official_jet(country_ids)
    return {
        "demand": demand,
        "demand_canonical": demand_canonical,
        "official_jodi": official_jodi,
        "jodi": jodi,
        "jodi_panels": jodi_panels,
        "kayrros": kayrros,
        "official_jet": official_jet,
        "demand_by_country": demand,
        "canonical_by_country": canonical_by_country,
        "reporting": reporting,
    }


def _canonical_by_country_filtered(country_ids: list[str]) -> pd.DataFrame:
    """Per-country canonical panels, limited to full-coverage months."""
    raw = aggregate_demand_canonical(country_ids, include_country_column=True)
    months = full_coverage_months(country_ids)
    if months:
        return filter_to_full_coverage_months(raw, months)
    return raw


def country_driver_table(
    country_ids: list[str],
    *,
    ref_date: pd.Timestamp,
    canonical_by_country: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    Country × panel MoM / YoY decomposition for multi-country investigation.

    Adds regional totals and each country's share of the regional MoM / YoY
    change (kbd) at ``ref_date``.
    """
    df = canonical_by_country
    if df is None or df.empty:
        df = _canonical_by_country_filtered(country_ids)
    elif len(country_ids) > 1:
        months = full_coverage_months(country_ids)
        if months:
            df = filter_to_full_coverage_months(df, months)

    if df.empty:
        return pd.DataFrame()

    ref = pd.Timestamp(ref_date)
    prior_m = ref - pd.DateOffset(months=1)
    prior_y = ref - pd.DateOffset(months=12)

    def _levels_at(obs_date: pd.Timestamp) -> pd.DataFrame:
        sl = df[pd.to_datetime(df["date"]) == obs_date]
        if sl.empty:
            return pd.DataFrame(
                columns=["country_id", "country_name", "panel", "level_kbd"]
            )
        return (
            sl.groupby(["country_id", "country_name", "panel"], as_index=False)["value_kbd"]
            .sum()
            .rename(columns={"value_kbd": "level_kbd"})
        )

    current = _levels_at(ref)
    if current.empty:
        return pd.DataFrame()

    prior_month = _levels_at(prior_m).rename(columns={"level_kbd": "prior_m_kbd"})
    prior_year = _levels_at(prior_y).rename(columns={"level_kbd": "prior_y_kbd"})

    out = current.merge(
        prior_month, on=["country_id", "country_name", "panel"], how="left"
    ).merge(prior_year, on=["country_id", "country_name", "panel"], how="left")
    out["mom_kbd"] = out["level_kbd"] - out["prior_m_kbd"]
    out["yoy_kbd"] = out["level_kbd"] - out["prior_y_kbd"]
    out["month"] = ref

    regional = out.groupby("panel", as_index=False).agg(
        regional_level_kbd=("level_kbd", "sum"),
        regional_mom_kbd=("mom_kbd", "sum"),
        regional_yoy_kbd=("yoy_kbd", "sum"),
    )
    out = out.merge(regional, on="panel", how="left")
    out["share_mom_pct"] = (
        out["mom_kbd"].div(out["regional_mom_kbd"].replace(0, np.nan)) * 100
    )
    out["share_yoy_pct"] = (
        out["yoy_kbd"].div(out["regional_yoy_kbd"].replace(0, np.nan)) * 100
    )
    panel_rank = (
        out.groupby("panel")["regional_mom_kbd"]
        .first()
        .abs()
        .sort_values(ascending=False)
    )
    rank_map = {panel: rank for rank, panel in enumerate(panel_rank.index)}
    out["_panel_rank"] = out["panel"].map(rank_map)
    return (
        out.sort_values(["_panel_rank", "mom_kbd"], ascending=[True, False])
        .drop(columns="_panel_rank")
        .reset_index(drop=True)
    )


def country_total_driver_table(
    country_ids: list[str],
    *,
    ref_date: pd.Timestamp,
    canonical_by_country: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Country-level totals (all panels summed) for the reference month."""
    detail = country_driver_table(
        country_ids,
        ref_date=ref_date,
        canonical_by_country=canonical_by_country,
    )
    if detail.empty:
        return pd.DataFrame()

    totals = (
        detail.groupby(["country_id", "country_name"], as_index=False)
        .agg(
            level_kbd=("level_kbd", "sum"),
            mom_kbd=("mom_kbd", "sum"),
            yoy_kbd=("yoy_kbd", "sum"),
        )
        .sort_values("mom_kbd", ascending=False)
    )
    totals["month"] = pd.Timestamp(ref_date)
    regional_mom = totals["mom_kbd"].sum()
    regional_yoy = totals["yoy_kbd"].sum()
    totals["share_mom_pct"] = totals["mom_kbd"].div(
        regional_mom if regional_mom else np.nan
    ) * 100
    totals["share_yoy_pct"] = totals["yoy_kbd"].div(
        regional_yoy if regional_yoy else np.nan
    ) * 100
    return totals


def top_moving_panels(
    driver_table: pd.DataFrame,
    *,
    n: int = 5,
    metric: str = "regional_mom_kbd",
) -> list[str]:
    """Panel names with the largest absolute regional MoM (default top ``n``)."""
    if driver_table.empty or metric not in driver_table.columns:
        return []
    ranked = (
        driver_table.groupby("panel", as_index=False)[metric]
        .first()
        .assign(_abs=lambda d: d[metric].abs())
        .sort_values("_abs", ascending=False)
    )
    return ranked["panel"].head(n).tolist()

__all__ = [
    "aggregate_demand_canonical",
    "aggregate_jodi_compare_panels",
    "aggregate_kayrros_jet",
    "aggregate_official_demand",
    "balanced_through_date",
    "country_driver_table",
    "country_reporting_summary",
    "country_total_driver_table",
    "export_slug",
    "filter_to_full_coverage_months",
    "full_coverage_months",
    "load_country_bundle",
    "multi_country_display_name",
    "reporting_metadata",
    "top_moving_panels",
]
