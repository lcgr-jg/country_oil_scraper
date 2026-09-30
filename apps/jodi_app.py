"""JODI Streamlit MVP — single-page dashboard over analytics.jodi_dashboard.

Run from the project root::

    streamlit run apps/jodi_app.py

Data must exist under data/processed/jodi/ (run scripts/update_jodi.py first).
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

# Project root on sys.path so ``analytics`` imports work regardless of cwd.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from analytics.jodi_dashboard import (  # noqa: E402
    DRIVER_LAG_MONTHS,
    GLOBAL_KEY,
    METRIC_LABELS,
    PRODUCTS_PRIMARY,
    PRODUCTS_SECONDARY,
    REGION_ORDER,
    REGION_PREFIX,
    assess_reporter_freshness,
    build_common_panel,
    build_country_contribution_table,
    build_product_change_summary,
    build_regional_driver_summary,
    configure,
    country_contrib_matrix,
    get_dashboard_series,
    plot_country_product_heatmap_pair,
    plot_country_waterfalls,
    plot_level_vs_5y_band,
    plot_product_change_bars,
    plot_seasonal_vs_sequential,
    plot_signed_hbar_pair,
    plot_top_countries_trends,
    plot_who_drives_yoy,
    product_label,
    render_chart,
    render_seasonality_by_year_all_products,
    resolve_geography,
)

PROCESSED = _ROOT / "data" / "processed" / "jodi"
_AGG_RAW = "Raw sum (whoever reported each month)"
_AGG_EXCLUDE = "Exclude lagging reporters"
_AGG_BALANCED = "Balanced panel (same countries YoY/MoM)"
_METRIC_UNITS = {"demand": "kb/d", "stocks": "mbbl"}
_DRIVER_METRICS = frozenset({"demand", "stocks"})
_POS = "#2ca02c"
_NEG = "#d62728"

# Analytics keeps the column name ``level_kb_d`` for both demand and stocks.
_LEVEL_COL = "level_kb_d"


@st.cache_resource(show_spinner="Loading JODI parquets…")
def _init_dashboard() -> dict:
    """Load parquets once and bind the module singleton."""
    sec_path = PROCESSED / "jodi_secondary.parquet"
    pri_path = PROCESSED / "jodi_primary.parquet"
    if not sec_path.exists() or not pri_path.exists():
        st.error(
            f"JODI parquet not found under `{PROCESSED}`. "
            "Run `python scripts/update_jodi.py` first."
        )
        st.stop()

    df_sec = pd.read_parquet(sec_path)
    df_pri = pd.read_parquet(pri_path)
    country_names = (
        pd.concat(
            [df_sec[["ref_area", "country_name"]], df_pri[["ref_area", "country_name"]]]
        )
        .dropna()
        .drop_duplicates("ref_area")
        .set_index("ref_area")["country_name"]
        .astype(str)
        .to_dict()
    )
    configure(df_sec, df_pri, country_names)
    present_codes = set(df_sec["ref_area"].astype(str)) | set(
        df_pri["ref_area"].astype(str)
    )
    return {
        "secondary_rows": len(df_sec),
        "primary_rows": len(df_pri),
        "countries": len(country_names),
        "country_names": country_names,
        "present_codes": present_codes,
    }


@st.cache_data(show_spinner=False)
def _product_change_summary(
    geography: str,
    metric: str,
    lag_months: int,
    panel_mode: str,
) -> pd.DataFrame:
    return build_product_change_summary(
        geography,
        lag_months=lag_months,
        metric=metric,
        panel_mode=panel_mode,  # type: ignore[arg-type]
    )


@st.cache_data(show_spinner=False)
def _regional_driver_summary(
    geography: str,
    metric: str,
    lag_months: int,
) -> pd.DataFrame:
    return build_regional_driver_summary(
        geography,
        lag_months=lag_months,
        metric=metric,
    )


@st.cache_data(show_spinner=False)
def _country_contribution(
    geography: str,
    product: str,
    metric: str,
    lag_months: int,
) -> pd.DataFrame:
    return build_country_contribution_table(
        geography,
        product,
        lag_months=lag_months,
        metric=metric,
    )


@st.cache_data(show_spinner=False)
def _freshness_table(
    geography: str,
    product: str,
    metric: str,
    lag_months: int,
) -> pd.DataFrame:
    return assess_reporter_freshness(
        geography, product, metric, lag_months=lag_months
    )


def _product_options() -> list[tuple[str, str]]:
    headline = [
        ("Total oil products (TOTPRODS)", "TOTPRODS"),
        ("Total crude (TOTCRUDE)", "TOTCRUDE"),
    ]
    rest_secondary = sorted(
        [
            (f"{label} ({code})", code)
            for code, label in PRODUCTS_SECONDARY.items()
            if code != "TOTPRODS"
        ],
        key=lambda x: x[0].lower(),
    )
    rest_primary = sorted(
        [
            (f"{label} ({code})", code)
            for code, label in PRODUCTS_PRIMARY.items()
            if code != "TOTCRUDE"
        ],
        key=lambda x: x[0].lower(),
    )
    return headline + rest_secondary + rest_primary


def _country_options(
    country_names: dict[str, str],
    present_codes: set[str],
) -> list[tuple[str, str]]:
    opts: list[tuple[str, str]] = [("Global Total", GLOBAL_KEY)]
    opts += [(f"{r} (region)", REGION_PREFIX + r) for r in REGION_ORDER]
    countries = sorted(
        [(country_names.get(code, code), code) for code in present_codes if code],
        key=lambda x: x[0].lower(),
    )
    return opts + countries


def _geo_label(geography: str) -> str:
    _, label = resolve_geography(geography)
    return label


def _is_multi_country(geography: str) -> bool:
    codes, _ = resolve_geography(geography)
    return len(codes) > 1


def _is_secondary(product: str) -> bool:
    return product in PRODUCTS_SECONDARY


def _metric_unit(metric: str) -> str:
    return _METRIC_UNITS.get(metric, metric)


def _driver_metric_ok(metric: str) -> bool:
    """Driver tabs only support demand/stocks (not days-of-cover)."""
    if metric in _DRIVER_METRICS:
        return True
    st.info(
        f"**{METRIC_LABELS.get(metric, metric)}** is not available on this tab. "
        "Pick **Demand** or **Ending stocks** in the sidebar."
    )
    return False


def _trust_banner(
    geography: str,
    metric: str,
    ts_agg: str,
    lag_months: int,
    panel_mode: str,
) -> None:
    """Explain what the current filters mean so numbers are interpretable."""
    geo_label = _geo_label(geography)
    # Banner panel snapshot uses demand when metric is cover (drivers need flow/level).
    panel_metric = metric if metric in _DRIVER_METRICS else "demand"

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Geography", geo_label)
    c2.metric("Metric", METRIC_LABELS.get(metric, metric))
    c3.metric("Time-series mode", ts_agg.split(" (")[0])

    notes: list[str] = []
    if panel_mode == "per_product":
        c4.metric("Balanced panel", "Per product")
        c5.metric("Reference month", "Varies by product")
        notes.append(
            "By-product tab: each product uses **its own** balanced panel "
            "(diesel reporters for diesel, jet for jet). "
            "See **panel_n** per row."
        )
    else:
        panel, _ry, _rm, month_label, excluded_n = build_common_panel(
            geography,
            lag_months=DRIVER_LAG_MONTHS if ts_agg == _AGG_BALANCED else lag_months,
            metric=panel_metric,
            panel_mode=panel_mode,  # type: ignore[arg-type]
        )
        c4.metric("Balanced panel", f"n={len(panel)}")
        c5.metric("Reference month", month_label)
        if excluded_n and len(panel) > 0:
            notes.append(
                f"{excluded_n} countries in this geography are outside the balanced panel."
            )

    if ts_agg == _AGG_RAW:
        notes.append(
            "Time series uses a **raw sum** — YoY moves can reflect missing reporters. "
            "Use **By product** / **Regional drivers** for trustworthy YoY/MoM."
        )
    elif ts_agg == _AGG_EXCLUDE:
        notes.append(
            f"Lagging = more than **{lag_months}** month(s) behind the group's latest print."
        )
    else:
        notes.append(
            "Balanced panel: same countries in reference, prior-year, and prior-month months."
        )
    if notes:
        st.caption(" · ".join(notes))


def _render_change_table(summary: pd.DataFrame, unit: str) -> pd.DataFrame | None:
    """Shared YoY/MoM product table; returns display frame or None if empty."""
    cols = [
        "product",
        "month",
        _LEVEL_COL,
        "yoy_change",
        "yoy_pct",
        "mom_change",
        "mom_pct",
        "vs_5y_range",
        "panel_n",
        "excluded_n",
    ]
    view = summary[cols].copy()
    if view.empty or view[_LEVEL_COL].isna().all():
        return None

    display = view.round({_LEVEL_COL: 0, "yoy_change": 0, "mom_change": 0})
    display["yoy_pct"] = view["yoy_pct"].round(1)
    display["mom_pct"] = view["mom_pct"].round(1)
    display = display.rename(columns={_LEVEL_COL: f"level ({unit})"})
    return display


def _render_time_series(
    product: str,
    geography: str,
    metric: str,
    ts_agg: str,
    lag_months: int,
) -> None:
    exclude = ts_agg in (_AGG_EXCLUDE, _AGG_BALANCED)
    lag = DRIVER_LAG_MONTHS if ts_agg == _AGG_BALANCED else lag_months
    fig = render_chart(
        product,
        geography,
        metric,
        exclude_lagging=exclude,
        lag_months=lag,
    )
    st.plotly_chart(fig, use_container_width=True)

    if _is_multi_country(geography):
        series = get_dashboard_series(
            product,
            geography,
            metric,
            exclude_lagging=exclude,
            lag_months=lag,
        )
        if not series.empty and "n_countries" in series.columns:
            latest = series.dropna(subset=["value"]).tail(1)
            if not latest.empty:
                n = int(latest["n_countries"].iloc[0])
                dt = pd.to_datetime(latest["date"].iloc[0]).strftime("%Y-%m")
                st.caption(
                    f"Latest point **{dt}**: **{n}** countries in the sum. "
                    "If this falls vs last year, check Reporter freshness."
                )

    # Same aggregation as the chart above so YoY seasonality isn't skewed by
    # a different reporter set than the selected time series.
    st.subheader("Seasonality by year")
    st.caption(
        "All products · Jan–Dec overlay by calendar year · "
        "latest year highlighted in red (same aggregation as the chart above)."
    )
    fig_season = render_seasonality_by_year_all_products(
        geography,
        metric,
        exclude_lagging=exclude,
        lag_months=lag,
    )
    st.plotly_chart(fig_season, use_container_width=True)


def _render_by_product(
    geography: str,
    metric: str,
    panel_mode: str,
) -> None:
    if not _driver_metric_ok(metric):
        return

    unit = _metric_unit(metric)
    geo = _geo_label(geography)
    summary = _product_change_summary(
        geography, metric, DRIVER_LAG_MONTHS, panel_mode
    )

    if panel_mode == "per_product":
        panel_ns = summary["panel_n"].dropna()
        if not panel_ns.empty:
            subtitle = (
                f"**{geo}** · **{METRIC_LABELS[metric]}** · "
                f"per-product panels · panel_n "
                f"{int(panel_ns.min())}–{int(panel_ns.max())} "
                f"(median {int(panel_ns.median())}) · lag={DRIVER_LAG_MONTHS} mo"
            )
        else:
            subtitle = (
                f"**{geo}** · **{METRIC_LABELS[metric]}** · "
                f"per-product panels · lag={DRIVER_LAG_MONTHS} mo"
            )
    else:
        panel, _ry, _rm, month_label, excluded_n = build_common_panel(
            geography,
            lag_months=DRIVER_LAG_MONTHS,
            metric=metric,
            panel_mode=panel_mode,  # type: ignore[arg-type]
        )
        subtitle = (
            f"**{geo}** · **{METRIC_LABELS[metric]}** · "
            f"ref **{month_label}** · shared panel **n={len(panel)}** "
            f"({panel_mode.replace('_', ' ')}) · lag={DRIVER_LAG_MONTHS} mo"
        )
        if excluded_n:
            subtitle += f" · **{excluded_n}** excluded"

    st.markdown(subtitle)
    st.caption(
        "YoY = same calendar month last year; MoM = prior month. "
        "Balanced panel = same countries in reference, prior-year, and prior-month months."
    )

    display = _render_change_table(summary, unit)
    if display is None:
        st.warning(f"No balanced-panel {METRIC_LABELS[metric].lower()} data for this selection.")
        return

    st.dataframe(display, use_container_width=True, hide_index=True)

    fig = plot_product_change_bars(
        summary,
        title=f"{geo} — {METRIC_LABELS[metric].lower()} by product",
        unit=unit,
        pos_color=_POS,
        neg_color=_NEG,
    )
    st.pyplot(fig, use_container_width=True)
    plt.close(fig)


def _show_fig(fig: plt.Figure) -> None:
    st.pyplot(fig, use_container_width=True)
    plt.close(fig)


def _render_regional_drivers(
    geography: str,
    product: str,
    metric: str,
) -> None:
    """Notebook 11 visual suite: product summary → country drivers → context."""
    if not _driver_metric_ok(metric):
        return

    unit = _metric_unit(metric)
    geo = _geo_label(geography)
    summary = _regional_driver_summary(geography, metric, DRIVER_LAG_MONTHS)

    st.markdown(
        f"**{geo}** · **{METRIC_LABELS[metric]}** · "
        f"per-product balanced panels · lag={DRIVER_LAG_MONTHS} mo"
    )
    st.caption(
        "Each product uses its own balanced panel at that product's latest print "
        "(notebook 11). YoY = same month last year; MoM = prior month. "
        "Country charts use the sidebar **Product**."
    )

    display = _render_change_table(summary, unit)
    if display is None:
        st.warning(f"No regional driver data for **{geo}** / {METRIC_LABELS[metric]}.")
        return

    with st.expander("Product summary — YoY & MoM", expanded=True):
        st.dataframe(display, use_container_width=True, hide_index=True)
        _show_fig(
            plot_product_change_bars(
                summary,
                title=f"{geo} — {METRIC_LABELS[metric].lower()} by product",
                unit=unit,
                pos_color=_POS,
                neg_color=_NEG,
            )
        )

    with st.expander("Seasonal vs sequential", expanded=True):
        st.caption("Bubble size ∝ level · colour ∝ YoY change.")
        _show_fig(
            plot_seasonal_vs_sequential(
                summary,
                title=f"{METRIC_LABELS[metric]} — seasonal vs sequential",
                unit=unit,
            )
        )

    with st.expander("Current vs 5y range", expanded=False):
        _show_fig(
            plot_level_vs_5y_band(
                summary,
                title="Current vs 5y min / median / max",
                unit=unit,
            )
        )

    multi = _is_multi_country(geography)
    secondary = _is_secondary(product)

    if not multi:
        st.info(
            "Pick a **region** or **Global Total** for country contributions, "
            "heatmaps, waterfalls, and 24‑month trends."
        )
        return

    if not secondary:
        st.info(
            "Country / heatmap / waterfall charts need a **secondary** product "
            "(e.g. TOTPRODS). Change **Product** in the sidebar."
        )
        return

    contrib = _country_contribution(geography, product, metric, DRIVER_LAG_MONTHS)
    if contrib.empty:
        st.warning(
            f"No balanced panel for {product_label(product)} "
            f"({METRIC_LABELS[metric]}) at the group latest print."
        )
        return

    ref = contrib[_LEVEL_COL].sum()
    with st.expander(
        f"Country contributions — {product_label(product)}",
        expanded=True,
    ):
        st.caption(
            f"Panel total **{ref:,.0f}** {unit} · sorted by YoY · "
            f"{len(contrib)} countries"
        )
        show = contrib[
            [
                "country",
                "sub_region",
                _LEVEL_COL,
                "yoy_change",
                "mom_change",
                "yoy_share_pct",
                "mom_share_pct",
            ]
        ].round(
            {
                _LEVEL_COL: 0,
                "yoy_change": 0,
                "mom_change": 0,
                "yoy_share_pct": 0,
                "mom_share_pct": 0,
            }
        )
        show = show.rename(columns={_LEVEL_COL: f"level ({unit})"})
        st.dataframe(show, use_container_width=True, hide_index=True)
        _show_fig(
            plot_signed_hbar_pair(
                contrib,
                label_col="country",
                title=f"{geo} — {product_label(product)} ({METRIC_LABELS[metric]})",
                unit=unit,
            )
        )

    with st.expander("Country waterfalls", expanded=True):
        _show_fig(
            plot_country_waterfalls(
                contrib,
                title=f"{product_label(product)} — country contributions",
                unit=unit,
            )
        )

    with st.expander("Country × product heatmaps", expanded=True):
        codes = summary["product_code"].tolist()
        yoy_m = country_contrib_matrix(
            geography,
            codes,
            lag_months=DRIVER_LAG_MONTHS,
            metric=metric,
            value_col="yoy_change",
        )
        mom_m = country_contrib_matrix(
            geography,
            codes,
            lag_months=DRIVER_LAG_MONTHS,
            metric=metric,
            value_col="mom_change",
        )
        if yoy_m.empty and mom_m.empty:
            st.info("No country×product matrix for this selection.")
        else:
            st.caption("Shared colour scale · left YoY · right MoM.")
            _show_fig(
                plot_country_product_heatmap_pair(
                    yoy_m,
                    mom_m,
                    title=(
                        f"{geo} — {METRIC_LABELS[metric]} country change "
                        f"by product ({unit})"
                    ),
                    unit=unit,
                )
            )

    with st.expander("Who drives YoY change", expanded=False):
        top_codes = (
            summary.assign(_abs=summary["yoy_change"].abs())
            .nlargest(4, "_abs")["product_code"]
            .tolist()
        )
        if top_codes:
            _show_fig(
                plot_who_drives_yoy(
                    geography,
                    top_codes,
                    metric=metric,
                    lag_months=DRIVER_LAG_MONTHS,
                    title=f"Who drives YoY change — {METRIC_LABELS[metric]}",
                )
            )

    with st.expander(f"Last 24 months — {product_label(product)}", expanded=False):
        _show_fig(
            plot_top_countries_trends(
                geography,
                product,
                contrib,
                metric=metric,
                lag_months=DRIVER_LAG_MONTHS,
                unit=unit,
            )
        )


def _render_freshness(
    geography: str,
    product: str,
    metric: str,
    lag_months: int,
) -> None:
    if not _is_multi_country(geography):
        st.info("Freshness comparison needs a region or Global Total.")
        return

    tbl = _freshness_table(geography, product, metric, lag_months)
    if tbl.empty:
        st.warning("No freshness data for this selection.")
        return

    peer = tbl["peer_latest"].iloc[0]
    peer_str = peer.strftime("%Y-%m") if pd.notna(peer) else "—"
    n_lag = int(tbl["flag_lagging"].sum())
    st.caption(
        f"**{_geo_label(geography)}** · {product_label(product)} · "
        f"{METRIC_LABELS[metric]} · group latest print: **{peer_str}** · "
        f"**{n_lag}** / {len(tbl)} flagged lagging (>{lag_months} mo behind)"
    )
    show = tbl[
        [
            "country",
            "latest_date",
            "months_behind_peer",
            "flag_lagging",
        ]
    ].copy()
    show["latest_date"] = pd.to_datetime(show["latest_date"]).dt.strftime("%Y-%m")
    show = show.sort_values(["flag_lagging", "months_behind_peer"], ascending=[False, False])
    st.dataframe(show, use_container_width=True, hide_index=True)


def main() -> None:
    st.set_page_config(
        page_title="JODI Dashboard",
        page_icon="🛢",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.title("JODI Dashboard")
    st.markdown(
        "Interactive view of consolidated JODI data. "
        "All tabs share the sidebar **geography**, **product**, and **metric**. "
        "**By product** / **Regional drivers** use a balanced panel so YoY/MoM "
        "are not skewed by missing reporters."
    )

    ctx = _init_dashboard()
    geo_opts = _country_options(ctx["country_names"], ctx["present_codes"])
    prod_opts = _product_options()
    metric_opts = [(label, code) for code, label in METRIC_LABELS.items()]

    geo_labels = {code: label for label, code in geo_opts}
    prod_labels = {code: label for label, code in prod_opts}
    metric_labels = {code: label for label, code in metric_opts}

    with st.sidebar:
        st.header("Filters")
        geography = st.selectbox(
            "Country / region",
            options=[code for _, code in geo_opts],
            format_func=lambda c: geo_labels[c],
            index=0,
        )
        product = st.selectbox(
            "Product",
            options=[code for _, code in prod_opts],
            format_func=lambda c: prod_labels[c],
            index=0,
            help=(
                "Time series & freshness: any product. "
                "Regional country charts: secondary products only."
            ),
        )
        metric = st.selectbox(
            "Metric",
            options=[code for _, code in metric_opts],
            format_func=lambda c: metric_labels[c],
            index=0,
            help=(
                "By product / Regional drivers support Demand and Ending stocks only."
            ),
        )
        ts_agg = st.radio(
            "Time series aggregation",
            options=[_AGG_RAW, _AGG_EXCLUDE, _AGG_BALANCED],
            index=2,
            help=(
                "Raw sums whoever reported each month. "
                "Exclude lagging drops stale reporters from totals. "
                "Balanced uses lag=0 for the time series (closest to panel logic)."
            ),
        )
        lag_months = st.slider(
            "Lag threshold (months)",
            min_value=0,
            max_value=6,
            value=2,
            help="Used for raw/exclude-lagging time series and the Freshness tab.",
        )
        panel_mode = st.selectbox(
            "Balanced panel mode (By product tab)",
            options=["per_product", "totprods_anchor", "intersection"],
            format_func=lambda m: {
                "per_product": "Per product (diesel panel for diesel, etc.)",
                "totprods_anchor": "Shared — TOTPRODS-anchored",
                "intersection": "Shared — strictest intersection",
            }[m],
        )
        st.divider()
        st.caption(
            f"Loaded {ctx['secondary_rows']:,} secondary + "
            f"{ctx['primary_rows']:,} primary rows · "
            f"{ctx['countries']} countries"
        )

    _trust_banner(geography, metric, ts_agg, lag_months, panel_mode)

    tab_ts, tab_by_prod, tab_regional, tab_fresh = st.tabs(
        [
            "Time series",
            "By product",
            "Regional drivers",
            "Reporter freshness",
        ]
    )

    with tab_ts:
        st.subheader(
            f"{product_label(product)} · {METRIC_LABELS[metric]} · {_geo_label(geography)}"
        )
        _render_time_series(product, geography, metric, ts_agg, lag_months)

    with tab_by_prod:
        st.subheader(f"Secondary products — YoY & MoM ({METRIC_LABELS[metric]})")
        _render_by_product(geography, metric, panel_mode)

    with tab_regional:
        st.subheader(f"Regional drivers — {METRIC_LABELS[metric]} · {_geo_label(geography)}")
        _render_regional_drivers(geography, product, metric)

    with tab_fresh:
        st.subheader(
            f"{product_label(product)} · {METRIC_LABELS[metric]} · {_geo_label(geography)}"
        )
        _render_freshness(geography, product, metric, lag_months)


if __name__ == "__main__":
    main()
