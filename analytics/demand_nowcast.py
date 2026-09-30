"""Phase 3 POC — national demand early prints vs JODI settle.

Working set (no IEA dependency):
  Countries: Germany, Japan, Korea, Australia
  Buckets:   gasoline, gasoil_diesel  (aligned with iea_jodi_overlap.compare_buckets)

Reads processed country parquets + JODI secondary parquet directly so the
POC does not require a fresh DuckDB warehouse rebuild.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from analytics.products import PRODUCT_KIND_MAP
from analytics.units import convert_series
from warehouse.country_hooks import (
    build_official_jodi_panels,
    exclude_aggregate_total_rows,
    load_reference,
    normalize_official_frame,
    prepare_values_for_conversion,
    resolve_jodi_ref_area,
    resolve_source_id,
    resolve_unit_native,
)
from warehouse.registry import get_country

# ---------------------------------------------------------------------------
# POC scope
# ---------------------------------------------------------------------------

POC_COUNTRY_IDS: tuple[str, ...] = ("germany", "japan", "korea", "australia")

# Map each country's JODI_COMPARE_SERIES key → Phase-2 compare_bucket id.
SERIES_KEY_TO_BUCKET: dict[str, dict[str, str]] = {
    "germany": {"gasoline": "gasoline", "diesel": "gasoil_diesel"},
    "japan": {"gasoline": "gasoline", "gas_diesel": "gasoil_diesel"},
    "korea": {"gasoline": "gasoline", "diesel": "gasoil_diesel"},
    "australia": {"gasoline": "gasoline", "diesel": "gasoil_diesel"},
}

BUCKET_LABELS: dict[str, str] = {
    "gasoline": "Gasoline",
    "gasoil_diesel": "Gasoil / diesel",
}

JODI_CODE_BY_BUCKET: dict[str, str] = {
    "gasoline": "GASOLINE",
    "gasoil_diesel": "GASDIES",
}

DEFAULT_TABLEAU_PATH = Path(
    "data/processed/demand_nowcast/demand_nowcast_poc_tableau.csv"
)
DEFAULT_LEAD_PATH = Path(
    "data/processed/demand_nowcast/demand_nowcast_lead_summary.csv"
)


@dataclass(frozen=True)
class PocSeries:
    country_id: str
    iso2: str
    display_name: str
    official_source: str
    series_key: str
    compare_bucket: str
    jodi_energy_product: str
    panel: str


def resolve_project_root(cwd: Path | None = None) -> Path:
    here = cwd or Path.cwd()
    for candidate in [here, *here.parents]:
        if (candidate / "analytics" / "demand_nowcast.py").exists():
            return candidate
        nested = candidate / "country_oil_scraper"
        if (nested / "analytics" / "demand_nowcast.py").exists():
            return nested
    raise RuntimeError(f"Could not locate country_oil_scraper root from {here}")


def list_poc_series() -> list[PocSeries]:
    rows: list[PocSeries] = []
    for country_id in POC_COUNTRY_IDS:
        cfg = get_country(country_id)
        ref = load_reference(cfg)
        compare = getattr(ref, "JODI_COMPARE_SERIES", {}) or {}
        key_map = SERIES_KEY_TO_BUCKET[country_id]
        for series_key, bucket in key_map.items():
            if series_key not in compare:
                continue
            spec = compare[series_key]
            rows.append(
                PocSeries(
                    country_id=country_id,
                    iso2=resolve_jodi_ref_area(cfg, ref),
                    display_name=cfg.display_name,
                    official_source=cfg.official_source_label or resolve_source_id(cfg, ref),
                    series_key=series_key,
                    compare_bucket=bucket,
                    jodi_energy_product=spec.jodi_energy_product,
                    panel=spec.panel,
                )
            )
    return rows


def _load_official_demand_kbd(root: Path, country_id: str) -> pd.DataFrame:
    """Load country parquet TOTDEMO rows converted to value_kbd."""
    cfg = get_country(country_id)
    path = Path(cfg.parquet_path)
    if not path.is_absolute():
        path = root / path
    if not path.exists():
        # Fallback when registry root differs from notebook root.
        rel = path.name
        alt = root / "data" / "processed" / country_id / rel
        path = alt if alt.exists() else path
    if not path.exists():
        raise FileNotFoundError(f"Official parquet missing for {country_id}: {path}")

    ref = load_reference(cfg)
    df = pd.read_parquet(path)
    df["date"] = pd.to_datetime(df["date"])
    df = normalize_official_frame(df, cfg)
    df = exclude_aggregate_total_rows(df)
    df = df.loc[df["metric_type"].eq(cfg.demand_metric_type)].copy()
    if df.empty:
        return df

    unit_native = resolve_unit_native(cfg, ref)
    if unit_native is None and "unit" in df.columns and df["unit"].notna().any():
        unit_series = df["unit"].astype(str)
    else:
        unit_series = unit_native

    units_kind = getattr(ref, "UNITS_KIND", None) if ref is not None else None
    if units_kind is not None:
        product_kind = df["product_native"].map(units_kind)
    else:
        source_id = resolve_source_id(cfg, ref)
        mapping = PRODUCT_KIND_MAP.get(source_id, {})
        product_kind = df["product_native"].map(lambda x: mapping.get(x))

    prep, prep_unit = prepare_values_for_conversion(df, unit_series)
    df = prep.copy()
    df["value_kbd"] = convert_series(
        df["value"],
        prep_unit,
        "kbd",
        product_kind=product_kind,
        date=df["date"],
    )
    if "is_provisional" not in df.columns:
        df["is_provisional"] = False
    return df


def load_official_bucket_panels(root: Path, country_id: str) -> pd.DataFrame:
    """Official demand aggregated to POC compare buckets (kbd)."""
    cfg = get_country(country_id)
    ref = load_reference(cfg)
    demand = _load_official_demand_kbd(root, country_id)
    panels = build_official_jodi_panels(demand, cfg, ref=ref)
    if panels.empty:
        return panels

    key_map = SERIES_KEY_TO_BUCKET[country_id]
    compare = getattr(ref, "JODI_COMPARE_SERIES", {}) or {}
    # panel label → (series_key, bucket)
    panel_to_bucket: dict[str, tuple[str, str]] = {}
    for series_key, bucket in key_map.items():
        if series_key not in compare:
            continue
        panel_to_bucket[compare[series_key].panel] = (series_key, bucket)

    out = panels.loc[panels["panel"].isin(panel_to_bucket)].copy()
    out["series_key"] = out["panel"].map(lambda p: panel_to_bucket[p][0])
    out["compare_bucket"] = out["panel"].map(lambda p: panel_to_bucket[p][1])
    out["product_label"] = out["compare_bucket"].map(BUCKET_LABELS)
    out["country_id"] = country_id
    out["iso2"] = resolve_jodi_ref_area(cfg, ref)
    out["country_name"] = cfg.display_name
    out["official_source"] = cfg.official_source_label or resolve_source_id(cfg, ref)
    out["source"] = "official"
    out["source_tier"] = "early_print"
    out["jodi_energy_product"] = out["compare_bucket"].map(JODI_CODE_BY_BUCKET)
    out = out.rename(columns={"value_kbd": "value"})
    return out.sort_values("date").reset_index(drop=True)


def load_jodi_bucket_panels(root: Path, country_ids: list[str] | None = None) -> pd.DataFrame:
    """JODI TOTDEMO KBD for POC countries/buckets."""
    country_ids = list(country_ids or POC_COUNTRY_IDS)
    series = [s for s in list_poc_series() if s.country_id in country_ids]
    iso_set = {s.iso2 for s in series}
    codes = {s.jodi_energy_product for s in series}

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
            "assessment_code",
            "assessment_label",
        ],
    )
    raw = raw.loc[
        raw["flow_breakdown"].eq("TOTDEMO")
        & raw["unit_measure"].eq("KBD")
        & raw["ref_area"].isin(iso_set)
        & raw["energy_product"].isin(codes)
        & raw["obs_value"].notna()
    ].copy()
    raw["date"] = pd.to_datetime(raw["date"])
    raw["iso2"] = raw["ref_area"].astype(str)
    raw["energy_product"] = raw["energy_product"].astype(str)
    # Drop JODI's verbose country_name so meta display_name wins cleanly.
    raw = raw.drop(columns=["country_name"], errors="ignore")

    # Attach bucket / country metadata from PocSeries.
    meta = pd.DataFrame(
        [
            {
                "iso2": s.iso2,
                "country_id": s.country_id,
                "country_name": s.display_name,
                "official_source": s.official_source,
                "series_key": s.series_key,
                "compare_bucket": s.compare_bucket,
                "product_label": BUCKET_LABELS[s.compare_bucket],
                "jodi_energy_product": s.jodi_energy_product,
                "panel": s.panel,
            }
            for s in series
        ]
    )
    out = raw.merge(
        meta,
        left_on=["iso2", "energy_product"],
        right_on=["iso2", "jodi_energy_product"],
        how="inner",
    )
    out["value"] = pd.to_numeric(out["obs_value"], errors="coerce")
    out["source"] = "JODI"
    out["source_tier"] = "settle"
    out["is_provisional"] = out.get("assessment_code", pd.Series(index=out.index)).astype(
        str
    ).isin(["2", "3"])
    keep = [
        "date",
        "iso2",
        "country_id",
        "country_name",
        "official_source",
        "compare_bucket",
        "product_label",
        "series_key",
        "jodi_energy_product",
        "panel",
        "value",
        "source",
        "source_tier",
        "is_provisional",
        "assessment_code",
        "assessment_label",
    ]
    keep = [c for c in keep if c in out.columns]
    return out[keep].sort_values(["iso2", "compare_bucket", "date"]).reset_index(drop=True)


def build_nowcast_long(root: Path) -> pd.DataFrame:
    """Long panel: official early_print + JODI settle for all POC series."""
    official_frames = []
    for country_id in POC_COUNTRY_IDS:
        try:
            official_frames.append(load_official_bucket_panels(root, country_id))
        except FileNotFoundError as exc:
            print(f"skip {country_id}: {exc}")
    official = pd.concat(official_frames, ignore_index=True) if official_frames else pd.DataFrame()
    jodi = load_jodi_bucket_panels(root)

    cols = [
        "date",
        "iso2",
        "country_id",
        "country_name",
        "official_source",
        "compare_bucket",
        "product_label",
        "series_key",
        "jodi_energy_product",
        "panel",
        "value",
        "source",
        "source_tier",
        "is_provisional",
    ]
    pieces = []
    if not official.empty:
        pieces.append(official[[c for c in cols if c in official.columns]])
    if not jodi.empty:
        pieces.append(jodi[[c for c in cols if c in jodi.columns]])
    if not pieces:
        return pd.DataFrame(columns=cols)

    out = pd.concat(pieces, ignore_index=True)
    out["date"] = pd.to_datetime(out["date"])
    out["year"] = out["date"].dt.year
    out["month"] = out["date"].dt.month
    out["unit"] = "KBD"
    out["legend"] = (
        out["iso2"].astype(str)
        + " | "
        + out["source_tier"].astype(str)
        + " | "
        + out["compare_bucket"].astype(str)
    )
    return out.sort_values(["iso2", "compare_bucket", "source_tier", "date"]).reset_index(
        drop=True
    )


def build_nowcast_wide(long: pd.DataFrame) -> pd.DataFrame:
    """Wide compare: official vs JODI on same row + gap metrics."""
    if long.empty:
        return long

    off = long.loc[long["source_tier"].eq("early_print")].rename(
        columns={"value": "official_value", "is_provisional": "official_provisional"}
    )
    jodi = long.loc[long["source_tier"].eq("settle")].rename(
        columns={"value": "jodi_value", "is_provisional": "jodi_provisional"}
    )
    # Join only on identity keys — avoid brittle label mismatches.
    keys = ["date", "iso2", "compare_bucket"]
    meta_cols = [
        "country_id",
        "country_name",
        "official_source",
        "product_label",
        "series_key",
        "jodi_energy_product",
        "panel",
        "unit",
        "year",
        "month",
    ]
    off_meta = [c for c in meta_cols if c in off.columns]
    jodi_keep = keys + ["jodi_value", "jodi_provisional"]
    merged = off[keys + off_meta + ["official_value", "official_provisional"]].merge(
        jodi[jodi_keep],
        on=keys,
        how="outer",
    )
    # Fill metadata from either side when one source is missing.
    for col in off_meta:
        if col not in merged.columns:
            continue
        if f"{col}_x" in merged.columns:
            merged[col] = merged[f"{col}_x"].combine_first(merged.get(f"{col}_y"))
            merged = merged.drop(columns=[c for c in (f"{col}_x", f"{col}_y") if c in merged.columns])

    merged["diff"] = merged["official_value"] - merged["jodi_value"]
    merged["pct_diff"] = np.where(
        merged["jodi_value"].notna() & (merged["jodi_value"] != 0),
        100.0 * merged["diff"] / merged["jodi_value"],
        np.nan,
    )
    merged["has_both"] = merged["official_value"].notna() & merged["jodi_value"].notna()
    merged["abs_diff"] = merged["diff"].abs()
    merged["is_nowcast_month"] = merged["official_value"].notna() & merged["jodi_value"].isna()
    return merged.sort_values(["iso2", "compare_bucket", "date"]).reset_index(drop=True)


def build_lead_summary(wide: pd.DataFrame) -> pd.DataFrame:
    """Publication lead of official vs JODI + overlap fit stats."""
    rows = []
    if wide.empty:
        return pd.DataFrame()

    for (iso2, bucket), g in wide.groupby(["iso2", "compare_bucket"], observed=True):
        off_dates = g.loc[g["official_value"].notna(), "date"]
        jodi_dates = g.loc[g["jodi_value"].notna(), "date"]
        both = g.loc[g["has_both"]].copy()
        off_max = off_dates.max() if len(off_dates) else pd.NaT
        jodi_max = jodi_dates.max() if len(jodi_dates) else pd.NaT
        lead_months = (
            (off_max.to_period("M") - jodi_max.to_period("M")).n
            if pd.notna(off_max) and pd.notna(jodi_max)
            else np.nan
        )
        nowcast_months = g.loc[g["is_nowcast_month"], "date"].sort_values()
        row = {
            "iso2": iso2,
            "country_name": g["country_name"].dropna().iloc[0] if g["country_name"].notna().any() else iso2,
            "official_source": g["official_source"].dropna().iloc[0]
            if g["official_source"].notna().any()
            else "",
            "compare_bucket": bucket,
            "product_label": BUCKET_LABELS.get(bucket, bucket),
            "official_last": off_max,
            "jodi_last": jodi_max,
            "lead_months": lead_months,
            "n_overlap": int(len(both)),
            "n_nowcast_months": int(g["is_nowcast_month"].sum()),
            "nowcast_from": nowcast_months.min() if len(nowcast_months) else pd.NaT,
            "nowcast_to": nowcast_months.max() if len(nowcast_months) else pd.NaT,
        }
        if len(both) >= 3:
            x = both["official_value"].astype(float)
            y = both["jodi_value"].astype(float)
            diff = x - y
            row.update(
                {
                    "corr": float(x.corr(y)) if x.std() > 0 and y.std() > 0 else np.nan,
                    "rmse": float(np.sqrt(np.mean(np.square(diff)))),
                    "mean_bias": float(diff.mean()),
                    "median_pct_diff": float(both["pct_diff"].median()),
                }
            )
        else:
            row.update(
                {"corr": np.nan, "rmse": np.nan, "mean_bias": np.nan, "median_pct_diff": np.nan}
            )
        rows.append(row)

    out = pd.DataFrame(rows).sort_values(["lead_months", "iso2"], ascending=[False, True])
    return out.reset_index(drop=True)


def build_nowcast_tracker(wide: pd.DataFrame) -> pd.DataFrame:
    """Operational tracker: prefer official when present, else JODI.

    ``value_nowcast`` = official early print when available, else JODI settle.
    ``value_status`` explains which source fills the month.
    """
    out = wide.copy()
    out["value_nowcast"] = out["official_value"].combine_first(out["jodi_value"])
    out["value_status"] = np.where(
        out["is_nowcast_month"],
        "early_print_only",
        np.where(
            out["has_both"],
            "official+jodi",
            np.where(out["jodi_value"].notna(), "jodi_only", "official_only"),
        ),
    )
    return out


def export_nowcast_csvs(
    root: Path,
    *,
    long_path: Path | None = None,
    wide_path: Path | None = None,
    lead_path: Path | None = None,
) -> dict[str, Path]:
    """Write Tableau-ready nowcast CSVs (US/UK decimal format)."""
    wide_path = wide_path or (root / DEFAULT_TABLEAU_PATH)
    long_path = long_path or wide_path.with_name("demand_nowcast_poc_long.csv")
    lead_path = lead_path or (root / DEFAULT_LEAD_PATH)

    long = build_nowcast_long(root)
    wide = build_nowcast_tracker(build_nowcast_wide(long))
    lead = build_lead_summary(wide)

    for path in (wide_path, long_path, lead_path):
        path.parent.mkdir(parents=True, exist_ok=True)

    wide.to_csv(wide_path, index=False, date_format="%Y-%m-%d", float_format="%.10g", na_rep="")
    long.to_csv(long_path, index=False, date_format="%Y-%m-%d", float_format="%.10g", na_rep="")
    lead.to_csv(lead_path, index=False, date_format="%Y-%m-%d", float_format="%.10g", na_rep="")
    return {"wide": wide_path, "long": long_path, "lead": lead_path}


def make_nowcast_explorer(long: pd.DataFrame, wide: pd.DataFrame | None = None):
    """ipywidgets explorer for official vs JODI nowcast series."""
    import ipywidgets as widgets
    import plotly.express as px
    import plotly.graph_objects as go
    from IPython.display import display

    df = long.copy()
    df["date"] = pd.to_datetime(df["date"])
    if wide is None:
        wide = build_nowcast_wide(df)

    country_opts = (
        df[["iso2", "country_name"]]
        .drop_duplicates()
        .sort_values("iso2")
        .assign(label=lambda d: d["iso2"] + " — " + d["country_name"].astype(str))
    )
    country_map = dict(zip(country_opts["label"], country_opts["iso2"]))
    bucket_opts = [
        (f"{b} — {BUCKET_LABELS.get(b, b)}", b)
        for b in sorted(df["compare_bucket"].dropna().unique())
    ]

    w_style = {"description_width": "110px"}
    countries_w = widgets.SelectMultiple(
        options=list(country_map.keys()),
        value=tuple(country_opts["label"].head(2).tolist()),
        description="Countries:",
        style=w_style,
        layout=widgets.Layout(width="520px", height="110px"),
    )
    buckets_w = widgets.SelectMultiple(
        options=bucket_opts,
        value=tuple(b for _, b in bucket_opts),
        description="Buckets:",
        style=w_style,
        layout=widgets.Layout(width="520px", height="80px"),
    )
    mode_w = widgets.Dropdown(
        options=[
            ("Levels (official vs JODI)", "levels"),
            ("Nowcast tracker (combined)", "tracker"),
            ("% diff official vs JODI", "pct_diff"),
        ],
        value="levels",
        description="View:",
        style=w_style,
        layout=widgets.Layout(width="520px"),
    )
    status_w = widgets.HTML()
    out = widgets.Output()

    def _render(*_args) -> None:
        with out:
            out.clear_output(wait=True)
            isos = [country_map[x] for x in countries_w.value]
            buckets = list(buckets_w.value)
            mode = mode_w.value
            if mode == "levels":
                plot_df = df.loc[
                    df["iso2"].isin(isos) & df["compare_bucket"].isin(buckets)
                ].copy()
                if plot_df.empty:
                    go.Figure().update_layout(title="No data").show()
                    return
                fig = px.line(
                    plot_df,
                    x="date",
                    y="value",
                    color="legend",
                    title="Official early print vs JODI settle (kbd)",
                )
            elif mode == "tracker":
                plot_df = wide.loc[
                    wide["iso2"].isin(isos) & wide["compare_bucket"].isin(buckets)
                ].copy()
                plot_df = build_nowcast_tracker(plot_df)
                plot_df["legend"] = (
                    plot_df["iso2"] + " | tracker | " + plot_df["compare_bucket"]
                )
                fig = px.line(
                    plot_df.dropna(subset=["value_nowcast"]),
                    x="date",
                    y="value_nowcast",
                    color="legend",
                    hover_data=["value_status", "official_value", "jodi_value"],
                    title="Nowcast tracker (official when available, else JODI)",
                )
            else:
                plot_df = wide.loc[
                    wide["iso2"].isin(isos)
                    & wide["compare_bucket"].isin(buckets)
                    & wide["has_both"]
                ].copy()
                plot_df["legend"] = plot_df["iso2"] + " | pct_diff | " + plot_df["compare_bucket"]
                fig = px.line(
                    plot_df,
                    x="date",
                    y="pct_diff",
                    color="legend",
                    title="% difference: official - JODI",
                )
            fig.update_layout(template="plotly_white", height=460, legend_title_text="")
            status_w.value = (
                f"countries={', '.join(isos)} | buckets={', '.join(buckets)} | view={mode}"
            )
            fig.show()

    for w in (countries_w, buckets_w, mode_w):
        w.observe(_render, names="value")
    display(
        widgets.VBox(
            [
                widgets.HTML(
                    "<b>Demand nowcast POC</b> — national scrapers lead; JODI settles. No IEA."
                ),
                countries_w,
                buckets_w,
                mode_w,
                status_w,
            ]
        ),
        out,
    )
    _render()
