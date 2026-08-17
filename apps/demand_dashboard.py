"""
Interactive country demand dashboard — central warehouse + cross-source views.

Run from project root::

    streamlit run apps/demand_dashboard.py

On first load the app syncs ``data/warehouse/oil_demand.duckdb`` from country
parquets (and JODI / Kayrros when present). Rebuilds automatically when any
input parquet is newer than the warehouse file.
"""

from __future__ import annotations

import io
import sys
import zipfile
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from analytics import seasonality_by_year_chart  # noqa: E402
from analytics.core import (  # noqa: E402
    available_months,
    build_jodi_comparison_figure,
    build_kayrros_jet_figure,
    build_trading_notes,
    coverage_by_product,
    detect_episodic_divergences,
    format_divergence_notes,
    headline_total,
    product_change_table,
    structural_notes,
    warehouse_status,
)
from analytics.core.dashboard_copy import (
    jodi_compare_caption,
    kayrros_jet_caption,
    seasonality_caption,
)
from analytics.core.multi_country import (  # noqa: E402
    country_driver_table,
    country_total_driver_table,
    export_slug,
    load_country_bundle,
    multi_country_display_name,
    top_moving_panels,
)
from warehouse.country_hooks import (
    call_seasonality_chart_inputs,
    load_reference,
    resolve_jet_product_native,
)
from warehouse.consolidate import ensure_warehouse  # noqa: E402
from warehouse.registry import get_country, list_countries  # noqa: E402
from warehouse.regions import get_region, list_regions  # noqa: E402
from reference.dashboard_helpers import resolve_product_labels
from analytics.reports.html_export import snapshot_to_html  # noqa: E402


def _month_label(ts: pd.Timestamp) -> str:
    return pd.Timestamp(ts).strftime("%Y-%m")


def _track_figure(fig: go.Figure, bucket: list[go.Figure]) -> None:
    """Store a copy before Streamlit renders (avoids post-render color loss in HTML)."""
    bucket.append(go.Figure(fig))


def _format_dates_for_csv(df: pd.DataFrame) -> pd.DataFrame:
    """ISO date strings for CSV export (avoids locale-dependent Excel parsing)."""
    out = df.copy()
    for col in ("date", "month"):
        if col in out.columns:
            out[col] = pd.to_datetime(out[col]).dt.strftime("%Y-%m-%d")
    return out


def _csv_bytes(df: pd.DataFrame) -> bytes:
    if df.empty:
        return b""
    return _format_dates_for_csv(df).to_csv(index=False).encode("utf-8")


def _select_columns(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    present = [c for c in cols if c in df.columns]
    return df[present].copy()


def _build_csv_export_bundle(
    *,
    cfg: object,
    demand: pd.DataFrame,
    demand_canonical: pd.DataFrame,
    headline: pd.DataFrame,
    official_jodi: pd.DataFrame,
    jodi: pd.DataFrame,
    kayrros: pd.DataFrame,
    official_jet: pd.DataFrame,
    change_table: pd.DataFrame | None,
    coverage: pd.DataFrame | None = None,
    canonical_by_country: pd.DataFrame | None = None,
    demand_by_country: pd.DataFrame | None = None,
    country_drivers: pd.DataFrame | None = None,
    multi_country: bool = False,
) -> dict[str, pd.DataFrame]:
    """Datasets available for CSV / ZIP download for the active country or bundle."""
    official_cols = [
        "date",
        "product_native",
        "product_canonical",
        "category",
        "value_native",
        "unit_native",
        "value_kbd",
        "is_provisional",
        "source",
    ]
    panel_cols = ["date", "panel", "value_kbd", "is_provisional"]
    compare_cols = ["date", "panel", "value_kbd", "is_provisional", "source"]

    exports: dict[str, pd.DataFrame] = {}
    if not multi_country:
        exports["official_demand_native"] = _select_columns(demand, official_cols)
    exports["demand_canonical"] = _select_columns(demand_canonical, panel_cols)
    if not headline.empty:
        exports["headline_total"] = _select_columns(
            headline, ["date", "value_kbd", "is_provisional"]
        )
    if not official_jodi.empty:
        exports["jodi_official_panels"] = _select_columns(
            official_jodi.assign(source=getattr(cfg, "official_source_label", "official")),
            compare_cols,
        )
    if not jodi.empty:
        exports["jodi_benchmark"] = _select_columns(
            jodi.assign(source="JODI"),
            compare_cols,
        )
    if not official_jet.empty:
        exports["official_jet"] = _select_columns(
            official_jet.assign(product="jet"),
            official_cols,
        )
    if not kayrros.empty:
        exports["kayrros_jet"] = _select_columns(
            kayrros,
            ["date", "product_canonical", "value_kbd", "source", "source_tier"],
        )
    if change_table is not None and not change_table.empty:
        exports["mom_yoy"] = change_table.copy()
    if coverage is not None and not coverage.empty:
        exports["coverage_by_product"] = coverage.copy()
    if multi_country:
        if canonical_by_country is not None and not canonical_by_country.empty:
            exports["demand_canonical_by_country"] = _select_columns(
                canonical_by_country,
                ["country_id", "country_name", *panel_cols],
            )
        if demand_by_country is not None and not demand_by_country.empty:
            exports["official_demand_by_country"] = _select_columns(
                demand_by_country,
                ["country_id", "country_name", *official_cols],
            )
        if country_drivers is not None and not country_drivers.empty:
            exports["country_drivers"] = country_drivers.copy()
    return exports


def _render_country_drivers(
    *,
    country_ids: list[str],
    canonical_by_country: pd.DataFrame,
    ref_month: pd.Timestamp,
    ref_month_label: str,
    snapshot_tables: dict[str, pd.DataFrame],
    snapshot_figures: list[go.Figure],
) -> pd.DataFrame | None:
    """Multi-country drill-down: which countries drive panel-level MoM / YoY."""
    drivers = country_driver_table(
        country_ids,
        ref_date=ref_month,
        canonical_by_country=canonical_by_country,
    )
    if drivers.empty:
        st.info("No country driver data for the reference month.")
        return None

    totals = country_total_driver_table(
        country_ids,
        ref_date=ref_month,
        canonical_by_country=canonical_by_country,
    )
    top_panels = top_moving_panels(drivers, n=5)
    only_top = st.checkbox(
        "Show only top-moving panels (by |regional MoM|)",
        value=True,
        key="country_drivers_top_panels_only",
    )

    st.caption(
        f"Reference month **{ref_month_label}**. "
        "Shares are each country's contribution to the regional MoM / YoY change (kbd)."
    )

    col_left, col_right = st.columns(2)
    with col_left:
        st.markdown("**Regional total by country**")
        if not totals.empty:
            totals_display = totals.assign(
                month=ref_month_label,
            ).round(
                {
                    "level_kbd": 1,
                    "mom_kbd": 1,
                    "yoy_kbd": 1,
                    "share_mom_pct": 1,
                    "share_yoy_pct": 1,
                }
            )
            st.dataframe(
                totals_display[
                    [
                        "country_name",
                        "level_kbd",
                        "mom_kbd",
                        "share_mom_pct",
                        "yoy_kbd",
                        "share_yoy_pct",
                    ]
                ].rename(
                    columns={
                        "country_name": "Country",
                        "level_kbd": "Level (kbd)",
                        "mom_kbd": "MoM (kbd)",
                        "share_mom_pct": "Share MoM (%)",
                        "yoy_kbd": "YoY (kbd)",
                        "share_yoy_pct": "Share YoY (%)",
                    }
                ),
                use_container_width=True,
                hide_index=True,
            )
            snapshot_tables["Country drivers — totals"] = totals_display

    with col_right:
        st.markdown("**MoM contribution by country**")
        panel_options = top_panels + [
            p for p in sorted(drivers["panel"].unique()) if p not in top_panels
        ]
        selected_panel = st.selectbox(
            "Panel",
            options=panel_options,
            index=0,
            key="country_drivers_panel",
        )
        panel_sl = drivers[drivers["panel"] == selected_panel].copy()
        if panel_sl.empty:
            st.info(f"No data for {selected_panel}.")
        else:
            regional_mom = panel_sl["regional_mom_kbd"].iloc[0]
            panel_sl = panel_sl.sort_values("mom_kbd", ascending=True)
            panel_sl["driver_label"] = panel_sl["country_name"]
            panel_sl["direction"] = np.where(
                panel_sl["mom_kbd"] >= 0, "Increase", "Decrease"
            )
            fig_drv = px.bar(
                panel_sl,
                x="mom_kbd",
                y="driver_label",
                orientation="h",
                color="direction",
                color_discrete_map={"Increase": "#2ca02c", "Decrease": "#d62728"},
                title=(
                    f"{selected_panel} — MoM drivers ({ref_month_label}, "
                    f"regional Δ {regional_mom:,.0f} kbd)"
                ),
                labels={"mom_kbd": "MoM change (kbd)", "driver_label": "Country"},
            )
            fig_drv.update_layout(showlegend=False, yaxis={"categoryorder": "total ascending"})
            _track_figure(fig_drv, snapshot_figures)
            st.plotly_chart(fig_drv, use_container_width=True)

    table_sl = drivers[drivers["panel"].isin(top_panels)] if only_top else drivers
    display_drivers = table_sl.assign(month=ref_month_label).round(
        {
            "level_kbd": 1,
            "prior_m_kbd": 1,
            "prior_y_kbd": 1,
            "mom_kbd": 1,
            "yoy_kbd": 1,
            "regional_level_kbd": 1,
            "regional_mom_kbd": 1,
            "regional_yoy_kbd": 1,
            "share_mom_pct": 1,
            "share_yoy_pct": 1,
        }
    )
    st.markdown("**Country × panel detail**")
    st.dataframe(
        display_drivers[
            [
                "country_name",
                "panel",
                "level_kbd",
                "mom_kbd",
                "share_mom_pct",
                "yoy_kbd",
                "share_yoy_pct",
                "regional_mom_kbd",
            ]
        ].rename(
            columns={
                "country_name": "Country",
                "panel": "Panel",
                "level_kbd": "Level (kbd)",
                "mom_kbd": "MoM (kbd)",
                "share_mom_pct": "Share MoM (%)",
                "yoy_kbd": "YoY (kbd)",
                "share_yoy_pct": "Share YoY (%)",
                "regional_mom_kbd": "Regional MoM (kbd)",
            }
        ),
        use_container_width=True,
        hide_index=True,
    )
    snapshot_tables["Country drivers — detail"] = display_drivers
    return display_drivers


def _zip_csv_bundle(files: dict[str, pd.DataFrame]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, df in files.items():
            payload = _csv_bytes(df)
            if payload:
                zf.writestr(f"{name}.csv", payload)
    return buf.getvalue()


def _render_csv_downloads(
    *,
    export_prefix: str,
    selected_month_label: str,
    view_key: str,
    exports: dict[str, pd.DataFrame],
) -> None:
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    prefix = f"{export_prefix}_{selected_month_label}"

    with st.expander("Download data (CSV)", expanded=False):
        st.caption(
            "Long-format monthly series from the warehouse (kbd unless noted). "
            "Dates are ISO `YYYY-MM-DD`."
        )

        zip_bytes = _zip_csv_bundle(exports)
        if zip_bytes:
            st.download_button(
                label="Download all datasets (ZIP)",
                data=zip_bytes,
                file_name=f"{prefix}_demand_data_{stamp}.zip",
                mime="application/zip",
                help="One CSV per dataset listed below.",
            )

        view_name = (
            "official_demand_native"
            if view_key == "native"
            else "demand_canonical"
        )
        view_df = exports.get(view_name)
        if view_df is not None and not view_df.empty:
            st.download_button(
                label=f"Download current chart view ({view_name})",
                data=_csv_bytes(view_df),
                file_name=f"{prefix}_{view_name}_{stamp}.csv",
                mime="text/csv",
            )

        labels = {
            "official_demand_native": "Official demand (native products)",
            "demand_canonical": "Demand by canonical panel",
            "headline_total": "Headline total (canonical sum)",
            "jodi_official_panels": "JODI compare — official panels",
            "jodi_benchmark": "JODI compare — JODI panels",
            "official_jet": "Official jet fuel series",
            "kayrros_jet": "Kayrros jet fuel",
            "mom_yoy": "MoM / YoY change table",
            "coverage_by_product": "Product coverage (first/last month)",
            "demand_canonical_by_country": "Canonical panels by country",
            "official_demand_by_country": "Official demand by country",
            "country_drivers": "Country drivers (MoM / YoY decomposition)",
        }
        for key, df in exports.items():
            if key == view_name or df.empty:
                continue
            st.download_button(
                label=f"Download {labels.get(key, key)}",
                data=_csv_bytes(df),
                file_name=f"{prefix}_{key}_{stamp}.csv",
                mime="text/csv",
                key=f"csv_{key}",
            )


@st.cache_data(show_spinner=False)
def _load_bundle_frames(country_ids: tuple[str, ...]) -> dict[str, object]:
    return load_country_bundle(list(country_ids))


@st.cache_resource(show_spinner="Syncing warehouse from country parquets…")
def _ensure_warehouse_cached() -> str:
    """Run once per Streamlit server process; skips rebuild when inputs are unchanged."""
    return str(ensure_warehouse())


def _add_revision_vlines(fig: go.Figure, ref_mod: object | None) -> go.Figure:
    if ref_mod is None:
        return fig
    for attr, kwargs in (
        ("MONTHLY_REVISION_FROM", {"line_dash": "dash", "line_color": "gray"}),
        ("CURRENT_ERA_FROM", {"line_dash": "dot", "line_color": "steelblue"}),
    ):
        ts = getattr(ref_mod, attr, None)
        if ts is not None:
            vline_fn = getattr(ref_mod, "add_plotly_date_vline", None)
            if vline_fn is not None:
                vline_fn(fig, pd.Timestamp(ts), **kwargs)
            else:
                fig.add_vline(x=pd.Timestamp(ts), line_dash="dash", line_color="gray")
    return fig


def main() -> None:
    st.set_page_config(
        page_title="Country Oil Demand",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.title("Country Oil Demand Dashboard")

    countries = list_countries(enabled_only=True)
    if not countries:
        st.error("No enabled countries in config/countries.yaml")
        st.stop()

    _ensure_warehouse_cached()
    status = warehouse_status()

    with st.sidebar:
        st.header("Filters")
        scope = st.radio(
            "Scope",
            options=["Single country", "Multi-country aggregate"],
            horizontal=True,
        )
        multi_country = scope.startswith("Multi")
        country_options = [c.country_id for c in countries]
        display_name_fn = lambda cid: get_country(cid).display_name  # noqa: E731

        if not multi_country:
            country_id = st.selectbox(
                "Country",
                options=country_options,
                format_func=display_name_fn,
            )
            country_ids = [country_id]
        else:
            regions = list_regions()
            preset_options = ["custom"] + [r.region_id for r in regions]
            preset_labels = {"custom": "(Custom selection)"}
            preset_labels.update({r.region_id: r.display_name for r in regions})

            if "country_multiselect" not in st.session_state:
                st.session_state.country_multiselect = country_options[:1]

            preset_id = st.selectbox(
                "Region preset",
                options=preset_options,
                format_func=lambda pid: preset_labels.get(pid, pid),
            )
            if preset_id != "custom":
                preset_ids = list(get_region(preset_id).country_ids)
                if st.session_state.get("applied_preset") != preset_id:
                    st.session_state.country_multiselect = preset_ids
                    st.session_state.applied_preset = preset_id

            country_ids = st.multiselect(
                "Countries",
                options=country_options,
                format_func=display_name_fn,
                key="country_multiselect",
            )
            if not country_ids:
                st.warning("Select at least one country.")
                st.stop()
            country_id = country_ids[0]

        bundle_label = multi_country_display_name(country_ids)
        cfg = get_country(country_id)
        ref_mod = load_reference(cfg) if not multi_country else None

        frames = _load_bundle_frames(tuple(sorted(country_ids)))
        demand = frames["demand"]
        if demand.empty:
            st.error(f"No official demand in warehouse for {bundle_label}.")
            st.stop()

        reporting = frames.get("reporting") if multi_country else None
        month_source = (
            frames["demand_canonical"]
            if multi_country and not frames["demand_canonical"].empty
            else demand
        )
        months = available_months(month_source)
        month_options = {_month_label(m): m for m in months}
        selected_month_label = st.selectbox(
            "Reference month",
            options=list(month_options.keys()),
            index=len(month_options) - 1,
        )
        ref_month = month_options[selected_month_label]

        if multi_country:
            product_view = "Canonical rollup"
            view_key = "canonical"
            st.caption("Multi-country mode uses canonical panels only.")
            if reporting:
                with st.expander("Reporting coverage", expanded=True):
                    by_country = reporting["by_country"]
                    st.dataframe(
                        by_country[["country_name", "latest_month_label"]].rename(
                            columns={
                                "country_name": "Country",
                                "latest_month_label": "Latest month",
                            }
                        ),
                        use_container_width=True,
                        hide_index=True,
                    )
                    balanced = reporting.get("balanced_through_label")
                    if balanced:
                        st.caption(
                            f"Balanced aggregate through **{balanced}** "
                            f"(all {reporting['n_countries']} countries reported)."
                        )
                        ahead = by_country[
                            by_country["latest_month_label"].notna()
                            & (by_country["latest_month_label"] > balanced)
                        ]
                        if not ahead.empty:
                            names = ", ".join(
                                f"{row.country_name} ({row.latest_month_label})"
                                for row in ahead.itertuples()
                            )
                            st.caption(
                                f"Newer data exists but is excluded from charts until "
                                f"all countries catch up: {names}."
                            )
        else:
            product_view = st.radio(
                "Product view",
                options=["Native products", "Canonical rollup"],
                horizontal=True,
            )
            view_key = "native" if product_view.startswith("Native") else "canonical"

        use_source_native_labels = st.checkbox(
            "Source-native labels (audit)",
            value=False,
            disabled=view_key != "native",
            help=(
                "Native view only: show exact product_native names from the "
                "warehouse (same strings as Excel / product_map.csv), not "
                "friendly display labels."
            ),
        )

        show_jodi = st.checkbox("JODI comparison", value=True)
        show_kayrros = st.checkbox(
            "Kayrros (jet)",
            value=True,
            disabled=multi_country
            and not any(get_country(cid).kayrros_enabled for cid in country_ids),
        )
        show_seasonality = st.checkbox("Seasonality", value=True)
        show_changes = st.checkbox("MoM / YoY table", value=True)
        show_country_drivers = (
            st.checkbox(
                "Country drivers",
                value=True,
                help=(
                    "Decompose regional MoM / YoY by country and panel "
                    "(multi-country mode only)."
                ),
            )
            if multi_country
            else False
        )

        st.divider()
        st.caption(f"Warehouse: {status.get('rows', 0):,} rows")
        dr = status.get("date_range") or {}
        if dr:
            st.caption(f"Data: {dr.get('min_date')} → {dr.get('max_date')}")

    export_prefix = export_slug(country_ids)
    display_title = bundle_label if multi_country else cfg.display_name
    source_caption = (
        "Official sources (summed across selected countries)"
        if multi_country
        else cfg.official_source_label
    )

    st.subheader(f"{display_title} — {selected_month_label}")
    if multi_country:
        st.caption(
            f"Countries: {', '.join(get_country(cid).display_name for cid in country_ids)} · "
            f"Metric: aggregated kbd (canonical panels)"
        )
        reporting = frames.get("reporting")
        if reporting and reporting.get("balanced_through_label"):
            st.caption(
                f"Charts use months where all {reporting['n_countries']} countries report "
                f"(through {reporting['balanced_through_label']})."
            )
    else:
        st.caption(
            f"Official source: {cfg.official_source_label} · "
            f"Metric: {cfg.demand_metric_type} · Unit: kbd"
        )

    demand_canonical = frames["demand_canonical"]
    official_jodi = frames["official_jodi"]
    jodi = frames["jodi"]
    jodi_panels = frames["jodi_panels"]
    kayrros = frames["kayrros"]
    official_jet = frames.get("official_jet", pd.DataFrame())
    if official_jet is None or (isinstance(official_jet, pd.DataFrame) and official_jet.empty):
        if not multi_country:
            jet_native = resolve_jet_product_native(cfg, ref_mod) or "jet_fuel"
            official_jet = demand[demand["product_native"] == jet_native].copy()
        else:
            official_jet = pd.DataFrame()
    canonical_by_country = frames.get("canonical_by_country", pd.DataFrame())
    demand_by_country = frames.get("demand_by_country", pd.DataFrame())

    snapshot_figures: list[go.Figure] = []
    snapshot_tables: dict[str, pd.DataFrame] = {}
    snapshot_notes: list[str] = []
    change_table_export: pd.DataFrame | None = None
    country_drivers_export: pd.DataFrame | None = None
    coverage_export: pd.DataFrame | None = None

    # ── Coverage ──────────────────────────────────────────────────────────
    if multi_country and "country_id" in demand.columns:
        cov_frames = []
        for cid in country_ids:
            sl = demand[demand["country_id"] == cid]
            if sl.empty:
                continue
            cov = coverage_by_product(sl.drop(columns=["country_id", "country_name"], errors="ignore"))
            cov_frames.append(
                cov.assign(
                    country_id=cid,
                    country_name=get_country(cid).display_name,
                )
            )
        cov = pd.concat(cov_frames, ignore_index=True) if cov_frames else pd.DataFrame()
        coverage_export = cov.assign(
            first_month=lambda d: d["first_month"].dt.strftime("%Y-%m"),
            last_month=lambda d: d["last_month"].dt.strftime("%Y-%m"),
        ) if not cov.empty else pd.DataFrame()
    else:
        cov = coverage_by_product(demand)
        coverage_export = cov.assign(
            first_month=lambda d: d["first_month"].dt.strftime("%Y-%m"),
            last_month=lambda d: d["last_month"].dt.strftime("%Y-%m"),
        )
    with st.expander("Coverage — product history", expanded=False):
        if coverage_export.empty:
            st.info("No coverage data.")
        else:
            st.dataframe(
                coverage_export,
                use_container_width=True,
                hide_index=True,
            )

    # ── Headline total ────────────────────────────────────────────────────
    headline = headline_total(demand_canonical)
    if not headline.empty:
        fig_head = px.line(
            headline,
            x="date",
            y="value_kbd",
            title=f"{display_title} total petroleum demand (canonical, kbd)",
        )
        fig_head.update_traces(connectgaps=False)
        _add_revision_vlines(fig_head, ref_mod)
        _track_figure(fig_head, snapshot_figures)
        st.plotly_chart(fig_head, use_container_width=True)

    # ── Product breakdown ─────────────────────────────────────────────────
    if view_key == "native":
        chart_products = getattr(ref_mod, "CHART_PRODUCTS", None) if ref_mod else None
        display_labels = getattr(ref_mod, "DISPLAY_LABELS", {}) if ref_mod else {}
        plot_df = demand.copy()
        if chart_products:
            plot_df = plot_df[plot_df["product_native"].isin(chart_products)]
        else:
            # Countries without CHART_PRODUCTS (or minimal reference modules):
            # show the largest native series by summed kbd.
            top = (
                demand.groupby("product_native")["value_kbd"]
                .sum()
                .sort_values(ascending=False)
                .head(10)
                .index
            )
            plot_df = plot_df[plot_df["product_native"].isin(top)]
        plot_df["label"] = plot_df["product_native"].map(
            lambda p: resolve_product_labels(
                [p], display_labels, use_source_native=use_source_native_labels
            )[p]
        )
        fig_prod = px.line(
            plot_df,
            x="date",
            y="value_kbd",
            color="label",
            title=f"{display_title} demand by product (native, kbd)",
        )
        product_col = "product_native"
        change_frame = plot_df
        change_labels = (
            None
            if use_source_native_labels
            else display_labels
        )
    else:
        fig_prod = px.line(
            demand_canonical,
            x="date",
            y="value_kbd",
            color="panel",
            title=f"{display_title} demand by canonical product (kbd)",
        )
        product_col = "panel"
        change_frame = demand_canonical[demand_canonical["panel"].notna()]
        change_labels = None

    fig_prod.update_traces(connectgaps=False)
    _add_revision_vlines(fig_prod, ref_mod)
    _track_figure(fig_prod, snapshot_figures)
    st.plotly_chart(fig_prod, use_container_width=True)

    # ── MoM / YoY ─────────────────────────────────────────────────────────
    if show_changes:
        st.markdown("### Product change table (MoM / YoY)")
        total_for_table = headline.assign(_key="Total (canonical)") if not headline.empty else None
        tbl = product_change_table(
            change_frame,
            product_col=product_col if view_key == "native" else "panel",
            ref_date=ref_month,
            labels=change_labels,
            include_total=total_for_table,
        )
        if not tbl.empty:
            display_tbl = tbl.assign(
                month=lambda d: d["month"].dt.strftime("%Y-%m")
            ).round({"level_kbd": 1, "mom_kbd": 1, "yoy_kbd": 1, "mom_pct": 1, "yoy_pct": 1})
            st.dataframe(display_tbl, use_container_width=True, hide_index=True)
            snapshot_tables["MoM / YoY"] = display_tbl
            change_table_export = display_tbl.copy()
            snapshot_notes.extend(
                build_trading_notes(tbl, country_name=display_title, ref_month=ref_month)
            )

    # ── Country drivers (multi-country) ───────────────────────────────────
    if multi_country and show_country_drivers:
        st.markdown("### Country drivers")
        country_drivers_export = _render_country_drivers(
            country_ids=country_ids,
            canonical_by_country=canonical_by_country,
            ref_month=ref_month,
            ref_month_label=selected_month_label,
            snapshot_tables=snapshot_tables,
            snapshot_figures=snapshot_figures,
        )

    # ── Seasonality ─────────────────────────────────────────────────────────
    if show_seasonality:
        st.markdown("### Seasonality by year")
        if multi_country:
            st.caption(
                "Aggregated canonical demand by calendar month; "
                "panels summed across selected countries."
            )
        else:
            st.caption(seasonality_caption(country_id, ref_mod))
        seasonality_fn = (
            None if multi_country else getattr(ref_mod, "seasonality_chart_inputs", None)
        )
        if seasonality_fn is not None:
            season_df, s_product_col, products, labels, suffix = call_seasonality_chart_inputs(
                seasonality_fn,
                demand,
                demand_canonical,
                view=view_key,
                value_col="value_kbd",
            )
        else:
            season_df = change_frame
            s_product_col = product_col if view_key == "native" else "panel"
            products = sorted(season_df[s_product_col].dropna().unique().tolist())
            labels = {p: p for p in products}
            suffix = view_key

        if season_df.empty or not products:
            st.info("No seasonality data for current view.")
        else:
            season_labels = resolve_product_labels(
                products,
                labels,
                use_source_native=(
                    use_source_native_labels and view_key == "native"
                ),
            )
            fig_season = seasonality_by_year_chart(
                season_df,
                products,
                product_col=s_product_col,
                value_col="value_kbd",
                product_labels=season_labels,
                default_visible_prior_years=5,
                units_label="kbd",
                title=f"{display_title} — seasonality ({suffix})",
            )
            _track_figure(fig_season, snapshot_figures)
            st.plotly_chart(fig_season, use_container_width=True)

    # ── JODI ──────────────────────────────────────────────────────────────
    if show_jodi:
        st.markdown("### Official vs JODI")
        if multi_country:
            st.caption(
                "Official warehouse panels and JODI benchmark summed across countries; "
                "only panels available for every selected country are shown."
            )
        else:
            st.caption(jodi_compare_caption(country_id, ref_mod))
        fig_jodi = build_jodi_comparison_figure(
            official_jodi,
            jodi,
            jodi_panels,
            label_official=source_caption if multi_country else cfg.official_source_label,
            title=(
                f"{display_title} TOTDEMO — aggregated official vs JODI (kbd)"
                if multi_country
                else f"{display_title} TOTDEMO — {cfg.official_source_label} vs JODI (kbd)"
            ),
        )
        if fig_jodi is None:
            st.info("JODI comparison unavailable (missing JODI parquet or panel mapping).")
        else:
            _track_figure(fig_jodi, snapshot_figures)
            st.plotly_chart(fig_jodi, use_container_width=True)

    # ── Kayrros ───────────────────────────────────────────────────────────
    if show_kayrros:
        st.markdown("### Jet fuel vs Kayrros")
        if multi_country:
            st.caption(
                "Official jet and Kayrros jet series summed across countries "
                "with Kayrros coverage."
            )
        else:
            st.caption(kayrros_jet_caption(country_id, ref_mod))
        fig_kay = build_kayrros_jet_figure(
            official_jet,
            kayrros,
            label_official=source_caption if multi_country else cfg.official_source_label,
            title=(
                f"{display_title} jet fuel — aggregated official vs Kayrros"
                if multi_country
                else f"{display_title} jet fuel — {cfg.official_source_label} vs Kayrros"
            ),
        )
        if fig_kay is None:
            st.info("Kayrros comparison unavailable (DB missing or no overlap).")
        else:
            _track_figure(fig_kay, snapshot_figures)
            st.plotly_chart(fig_kay, use_container_width=True)

    # ── Divergence notes ──────────────────────────────────────────────────
    st.markdown("### Divergence notes")
    if multi_country:
        st.info(
            "Episodic divergence notes are available in single-country mode only."
        )
        div_df = pd.DataFrame()
    else:
        div_notes = structural_notes(cfg.country_code)

        if show_jodi and not official_jodi.empty and not jodi.empty:
            for panel in jodi_panels[:3]:
                off_sl = official_jodi[official_jodi["panel"] == panel]
                jodi_sl = jodi[jodi["panel"] == panel]
                div_notes.extend(
                    detect_episodic_divergences(
                        cfg.country_code,
                        off_sl,
                        jodi_sl,
                        product_canonical=panel,
                        official_source=cfg.official_source_label,
                        benchmark_source="JODI",
                        ref_date=ref_month,
                    )
                )

        if show_kayrros and not official_jet.empty and not kayrros.empty:
            div_notes.extend(
                detect_episodic_divergences(
                    cfg.country_code,
                    official_jet,
                    kayrros,
                    product_canonical="Jet fuel",
                    official_source=cfg.official_source_label,
                    benchmark_source="Kayrros",
                    ref_date=ref_month,
                    gap_shift_threshold_pp=8.0,
                )
            )

        div_df = format_divergence_notes(div_notes)
        if div_df.empty:
            st.info("No divergence notes for this month.")
        else:
            st.dataframe(div_df, use_container_width=True, hide_index=True)
            snapshot_tables["Divergence notes"] = div_df
            for _, row in div_df.iterrows():
                snapshot_notes.append(str(row["message"]))

    # ── Trading implications ──────────────────────────────────────────────
    if snapshot_notes:
        st.markdown("### Trading implications")
        for note in dict.fromkeys(snapshot_notes):
            st.markdown(f"- {note}")

    # ── Data export (CSV) ─────────────────────────────────────────────────
    csv_exports = _build_csv_export_bundle(
        cfg=cfg,
        demand=demand if not multi_country else pd.DataFrame(),
        demand_canonical=demand_canonical,
        headline=headline,
        official_jodi=official_jodi if show_jodi else pd.DataFrame(),
        jodi=jodi if show_jodi else pd.DataFrame(),
        kayrros=kayrros if show_kayrros else pd.DataFrame(),
        official_jet=official_jet if show_kayrros else pd.DataFrame(),
        change_table=change_table_export if show_changes else None,
        coverage=coverage_export if not coverage_export.empty else None,
        canonical_by_country=canonical_by_country if multi_country else None,
        demand_by_country=demand_by_country if multi_country else None,
        country_drivers=country_drivers_export if multi_country else None,
        multi_country=multi_country,
    )
    _render_csv_downloads(
        export_prefix=export_prefix,
        selected_month_label=selected_month_label,
        view_key=view_key,
        exports=csv_exports,
    )

    # ── HTML snapshot export ──────────────────────────────────────────────
    st.divider()
    html = snapshot_to_html(
        title=f"{display_title} demand snapshot",
        subtitle=f"Reference month: {selected_month_label} · View: {product_view}",
        figures=snapshot_figures,
        tables=snapshot_tables,
        notes=list(dict.fromkeys(snapshot_notes)),
        meta={
            "Country": display_title,
            "Source": source_caption,
        },
    )
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    st.download_button(
        label="Download HTML snapshot",
        data=html,
        file_name=f"{export_prefix}_demand_{selected_month_label}_{stamp}.html",
        mime="text/html",
        help="Exports charts and tables currently included in this view.",
    )


if __name__ == "__main__":
    main()
