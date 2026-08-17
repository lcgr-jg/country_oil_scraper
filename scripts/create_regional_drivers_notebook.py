"""Create notebooks/11_jodi_regional_drivers.ipynb (static analysis, no widgets)."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "notebooks" / "11_jodi_regional_drivers.ipynb"


def md(text: str) -> dict:
    return {
        "cell_type": "markdown",
        "metadata": {},
        "source": [line + "\n" for line in text.split("\n")],
    }


def code(text: str) -> dict:
    return {
        "cell_type": "code",
        "metadata": {},
        "source": [line + "\n" for line in text.split("\n")],
        "outputs": [],
        "execution_count": None,
    }


SETUP = '''from pathlib import Path
import sys

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from IPython.display import display, Markdown
from matplotlib.colors import TwoSlopeNorm

plt.rcParams["figure.figsize"] = (10, 5)
plt.rcParams["axes.grid"] = True
plt.rcParams["grid.alpha"] = 0.3

POS = "#2ca02c"
NEG = "#d62728"
TOTAL = "#4472C4"

# --- analysis config ---
METRICS = ["demand", "stocks"]
METRIC_UNITS = {"demand": "kb/d", "stocks": "mbbl"}
PRODUCT = "TOTPRODS"


def _project_root() -> Path:
    here = Path.cwd()
    for candidate in [here, *here.parents]:
        if (candidate / "scripts" / "update_jodi.py").exists():
            return candidate
        if (candidate / "country_oil_scraper" / "scripts" / "update_jodi.py").exists():
            return candidate / "country_oil_scraper"
    raise RuntimeError(f"Cannot find project root from {here}")


def plot_waterfall(ax, labels, values, title: str) -> None:
    """Country-level changes stacking to a total bar."""
    cum = 0.0
    xs, bs, hs, cs = [], [], [], []
    for val in values:
        xs.append(len(xs))
        if val >= 0:
            bs.append(cum)
            hs.append(val)
        else:
            bs.append(cum + val)
            hs.append(-val)
        cs.append(POS if val >= 0 else NEG)
        cum += val
    ax.bar(xs, hs, bottom=bs, color=cs, edgecolor="white", linewidth=0.5)
    t = len(labels)
    if cum >= 0:
        ax.bar(t, cum, bottom=0, color=TOTAL, edgecolor="white")
    else:
        ax.bar(t, -cum, bottom=cum, color=TOTAL, edgecolor="white")
    ax.set_xticks(list(range(t + 1)))
    ax.set_xticklabels([*labels, "Total"], rotation=45, ha="right")
    ax.set_title(title)
    ax.axhline(0, color="black", linewidth=0.8)


ROOT = _project_root()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analytics.jodi_dashboard import (
    METRIC_LABELS,
    configure,
    CONSOLIDATED_ASIA_PACIFIC,
    GEO_ALIASES,
    GLOBAL_KEY,
    REGION_PREFIX,
    DRIVER_LAG_MONTHS,
    resolve_geography,
    assess_reporter_freshness,
    build_regional_driver_summary,
    build_country_contribution_table,
    build_country_product_breakdown,
    build_balanced_panel,
    get_dashboard_series,
    product_label,
)

# --- geography config (pick one, then Run All) ---
GEOGRAPHY = REGION_PREFIX + CONSOLIDATED_ASIA_PACIFIC
# GEOGRAPHY = REGION_PREFIX + "Europe"
# GEOGRAPHY = REGION_PREFIX + "Middle East"
# GEOGRAPHY = REGION_PREFIX + "North America"
# GEOGRAPHY = "GB"  # single country (JODI ISO; UK → GB alias supported)


def country_contrib_matrix(
    summary: pd.DataFrame,
    geography: str,
    lag_months: int,
    metric: str,
    value_col: str = "yoy_change",
) -> pd.DataFrame:
    frames = []
    for code in summary["product_code"]:
        tbl = build_country_contribution_table(
            geography, code, lag_months=lag_months, metric=metric,
        )
        if tbl.empty:
            continue
        part = tbl[["country", value_col]].copy()
        part["product_code"] = code
        frames.append(part)
    if not frames:
        return pd.DataFrame()
    long = pd.concat(frames, ignore_index=True)
    return long.pivot(index="country", columns="product_code", values=value_col)


def plot_country_product_heatmap(
    matrix: pd.DataFrame, title: str, cbar_label: str,
) -> None:
    col_labels = [product_label(c) for c in matrix.columns]
    row_labels = matrix.index.tolist()
    data = matrix.to_numpy(dtype=float)
    vmax = np.nanmax(np.abs(data))
    norm = TwoSlopeNorm(vmin=-vmax, vcenter=0, vmax=vmax)
    fig, ax = plt.subplots(
        figsize=(max(10, len(matrix.columns) * 1.1), max(6, len(matrix) * 0.35))
    )
    im = ax.imshow(data, aspect="auto", cmap="RdYlGn", norm=norm)
    ax.set_xticks(np.arange(len(col_labels)))
    ax.set_xticklabels(col_labels, rotation=45, ha="right")
    ax.set_yticks(np.arange(len(row_labels)))
    ax.set_yticklabels(row_labels)
    ax.set_title(title)
    cbar = fig.colorbar(im, ax=ax, shrink=0.8)
    cbar.set_label(cbar_label)
    plt.tight_layout()
    plt.show()


PROCESSED = ROOT / "data" / "processed" / "jodi"
df_sec = pd.read_parquet(PROCESSED / "jodi_secondary.parquet")
df_pri = pd.read_parquet(PROCESSED / "jodi_primary.parquet")

COUNTRY_NAMES = (
    pd.concat([df_sec[["ref_area", "country_name"]], df_pri[["ref_area", "country_name"]]])
    .dropna()
    .drop_duplicates("ref_area")
    .set_index("ref_area")["country_name"]
    .astype(str)
    .to_dict()
)

configure(df_sec, df_pri, COUNTRY_NAMES)

_geo_codes, GEO_LABEL = resolve_geography(GEOGRAPHY)
print(f"Region: {GEO_LABEL} ({len(_geo_codes)} mapped countries)")
print(f"Metrics: {', '.join(METRIC_LABELS[m] for m in METRICS)}")
print(f"Lag={DRIVER_LAG_MONTHS} mo | secondary rows={len(df_sec):,}")
'''

LOAD = '''by_metric: dict = {}

for metric in METRICS:
    summary = build_regional_driver_summary(
        GEOGRAPHY, lag_months=DRIVER_LAG_MONTHS, metric=metric,
    )
    contrib = build_country_contribution_table(
        GEOGRAPHY, PRODUCT, lag_months=DRIVER_LAG_MONTHS, metric=metric,
    )
    panel, ref_y, ref_m, peer = build_balanced_panel(
        GEOGRAPHY, PRODUCT, lag_months=DRIVER_LAG_MONTHS, metric=metric,
    )
    fresh = assess_reporter_freshness(
        GEOGRAPHY, PRODUCT, metric, lag_months=DRIVER_LAG_MONTHS,
    )
    in_panel = set(contrib["ref_area"].astype(str)) if not contrib.empty else set()
    audit = fresh.assign(
        in_panel=fresh["ref_area"].astype(str).isin(in_panel),
        latest_month=pd.to_datetime(fresh["latest_date"], errors="coerce").dt.strftime("%Y-%m"),
    )
    by_metric[metric] = {
        "summary": summary,
        "contrib": contrib,
        "panel": panel,
        "ref_month": f"{ref_y}-{ref_m:02d}",
        "peer_month": peer.strftime("%Y-%m") if pd.notna(peer) else "—",
        "audit": audit,
    }
    print(
        f"{METRIC_LABELS[metric]}: {len(summary)} products, "
        f"TOTPRODS panel={len(contrib)} countries (ref {by_metric[metric]['ref_month']})"
    )
'''

REGIONAL = '''for metric in METRICS:
    unit = METRIC_UNITS[metric]
    regional_summary = by_metric[metric]["summary"]
    display(Markdown(f"### {METRIC_LABELS[metric]} — regional summary ({unit})"))

    cols = [
        "product", "month", "level_kb_d", "yoy_change", "yoy_pct",
        "mom_change", "mom_pct", "vs_5y_range", "panel_n", "excluded_n",
    ]
    regional_view = regional_summary[cols].copy()
    regional_view["level_kb_d"] = regional_view["level_kb_d"].round(0)
    regional_view["yoy_change"] = regional_view["yoy_change"].round(0)
    regional_view["mom_change"] = regional_view["mom_change"].round(0)
    regional_view["yoy_pct"] = regional_view["yoy_pct"].round(1)
    regional_view["mom_pct"] = regional_view["mom_pct"].round(1)
    display(regional_view)

    fig, axes = plt.subplots(1, 2, figsize=(14, 5), sharey=True)
    for ax, col, title in zip(
        axes,
        ["yoy_change", "mom_change"],
        [f"YoY change ({unit})", f"MoM change ({unit})"],
    ):
        plot_df = regional_summary.sort_values(col)
        colors = [NEG if v < 0 else POS for v in plot_df[col]]
        ax.barh(plot_df["product"], plot_df[col], color=colors)
        ax.axvline(0, color="black", linewidth=0.8)
        ax.set_title(title)
        ax.set_xlabel(unit)
    fig.suptitle(f"{GEO_LABEL} — {METRIC_LABELS[metric]} by product", y=1.02)
    fig.tight_layout()
    plt.show()
'''

TOTPRODS = '''for metric in METRICS:
    unit = METRIC_UNITS[metric]
    contrib = by_metric[metric]["contrib"]
    ref_month = by_metric[metric]["ref_month"]
    peer_month = by_metric[metric]["peer_month"]

    display(Markdown(
        f"### {METRIC_LABELS[metric]} — {product_label(PRODUCT)} "
        f"({len(contrib)} panel countries, ref {ref_month}, peer {peer_month})"
    ))

    if contrib.empty:
        print("No balanced panel for this product.")
        continue

    country_view = contrib[
        ["country", "level_kb_d", "yoy_change", "mom_change", "yoy_share_pct", "mom_share_pct"]
    ].sort_values("yoy_change").copy()
    for c in ["level_kb_d", "yoy_change", "mom_change"]:
        country_view[c] = country_view[c].round(0)
    for c in ["yoy_share_pct", "mom_share_pct"]:
        country_view[c] = country_view[c].round(0)
    display(country_view)

    fig, axes = plt.subplots(1, 2, figsize=(14, 6), sharey=True)
    plot_df = contrib.sort_values("yoy_change")
    for ax, col, title in zip(
        axes,
        ["yoy_change", "mom_change"],
        [f"YoY contribution ({unit})", f"MoM contribution ({unit})"],
    ):
        colors = [NEG if v < 0 else POS for v in plot_df[col]]
        ax.barh(plot_df["country"], plot_df[col], color=colors)
        ax.axvline(0, color="black", linewidth=0.8)
        ax.set_title(title)
        ax.set_xlabel(unit)
    fig.suptitle(
        f"{GEO_LABEL} — {product_label(PRODUCT)} ({METRIC_LABELS[metric]})",
        y=1.02,
    )
    fig.tight_layout()
    plt.show()
'''

ALL_PRODUCTS = '''for metric in METRICS:
    unit = METRIC_UNITS[metric]
    regional_summary = by_metric[metric]["summary"]
    display(Markdown(f"### {METRIC_LABELS[metric]} — country tables ({unit})"))

    for code in regional_summary["product_code"]:
        tbl = build_country_contribution_table(
            GEOGRAPHY, code, lag_months=DRIVER_LAG_MONTHS, metric=metric,
        )
        ref = regional_summary.loc[regional_summary["product_code"] == code, "month"].iloc[0]
        print(f"\\n{product_label(code)} — ref {ref} — {len(tbl)} countries")
        if tbl.empty:
            print("  (no balanced panel)")
            continue
        show = tbl[["country", "yoy_change", "mom_change", "yoy_share_pct"]].sort_values(
            "yoy_change", ascending=False,
        )
        display(show.round(0))
'''

PANEL_AUDIT = '''for metric in METRICS:
    audit = by_metric[metric]["audit"].sort_values(
        ["in_panel", "flag_lagging", "months_behind_peer"],
        ascending=[False, True, False],
    )
    display(Markdown(f"### {METRIC_LABELS[metric]} — panel audit (TOTPRODS)"))
    display(
        audit[
            ["country", "latest_month", "months_behind_peer", "flag_lagging", "in_panel"]
        ].round({"months_behind_peer": 0})
    )
'''

VIZ_CORE = '''for metric in METRICS:
    unit = METRIC_UNITS[metric]
    regional_summary = by_metric[metric]["summary"]
    contrib = by_metric[metric]["contrib"]
    display(Markdown(f"### {METRIC_LABELS[metric]} — visual summary"))

    fig, ax = plt.subplots(figsize=(9, 7))
    sizes = regional_summary["level_kb_d"].clip(lower=1) / 80
    ax.scatter(
        regional_summary["mom_change"],
        regional_summary["yoy_change"],
        s=sizes,
        c=regional_summary["yoy_change"],
        cmap="RdYlGn",
        alpha=0.85,
        edgecolors="black",
        linewidths=0.5,
    )
    for _, row in regional_summary.iterrows():
        ax.annotate(
            row["product_code"],
            (row["mom_change"], row["yoy_change"]),
            textcoords="offset points",
            xytext=(4, 4),
            fontsize=9,
        )
    ax.axhline(0, color="black", linewidth=0.8)
    ax.axvline(0, color="black", linewidth=0.8)
    ax.set_xlabel(f"MoM change ({unit})")
    ax.set_ylabel(f"YoY change ({unit})")
    ax.set_title(f"{METRIC_LABELS[metric]} — seasonal vs sequential")
    plt.tight_layout()
    plt.show()

    if not contrib.empty:
        wf_yoy = contrib.sort_values("yoy_change")
        wf_mom = contrib.sort_values("mom_change")
        fig, axes = plt.subplots(1, 2, figsize=(16, 6))
        plot_waterfall(
            axes[0],
            wf_yoy["country"].tolist(),
            wf_yoy["yoy_change"].tolist(),
            f"YoY total {wf_yoy['yoy_change'].sum():,.0f} {unit}",
        )
        plot_waterfall(
            axes[1],
            wf_mom["country"].tolist(),
            wf_mom["mom_change"].tolist(),
            f"MoM total {wf_mom['mom_change'].sum():,.0f} {unit}",
        )
        for ax in axes:
            ax.set_ylabel(unit)
        fig.suptitle(f"{product_label(PRODUCT)} — country contributions", y=1.02)
        fig.tight_layout()
        plt.show()

    for value_col, chg_label in [("yoy_change", "YoY"), ("mom_change", "MoM")]:
        matrix = country_contrib_matrix(
            regional_summary, GEOGRAPHY, DRIVER_LAG_MONTHS, metric, value_col=value_col,
        )
        if matrix.empty:
            continue
        plot_country_product_heatmap(
            matrix,
            f"{GEO_LABEL} — {METRIC_LABELS[metric]} country {chg_label} by product ({unit})",
            f"{chg_label} change ({unit})",
        )
'''

VIZ_CONTEXT = '''for metric in METRICS:
    unit = METRIC_UNITS[metric]
    regional_summary = by_metric[metric]["summary"]
    display(Markdown(f"### {METRIC_LABELS[metric]} — level & share context"))

    band = regional_summary.reset_index(drop=True)
    y = np.arange(len(band))
    fig, ax = plt.subplots(figsize=(10, max(5, len(band) * 0.45)))
    for i, row in band.iterrows():
        ax.hlines(i, row["hist_5y_min"], row["hist_5y_max"], color="#cccccc", linewidth=10, zorder=1)
        ax.scatter(row["hist_5y_median"], i, marker="|", color="black", s=120, zorder=2)
        ax.scatter(row["level_kb_d"], i, color="#1f77b4", s=70, zorder=3, label="Current" if i == 0 else "")
    ax.set_yticks(y)
    ax.set_yticklabels(band["product"])
    ax.set_xlabel(f"Level ({unit})")
    ax.set_title(f"Current vs 5y min / median / max")
    ax.legend(loc="lower right")
    plt.tight_layout()
    plt.show()

    top_codes = (
        regional_summary.assign(_abs=regional_summary["yoy_change"].abs())
        .nlargest(4, "_abs")["product_code"]
        .tolist()
    )
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    for ax, code in zip(axes.flat, top_codes):
        tbl = build_country_contribution_table(
            GEOGRAPHY, code, lag_months=DRIVER_LAG_MONTHS, metric=metric,
        )
        if tbl.empty:
            ax.set_visible(False)
            continue
        tbl = tbl.sort_values("yoy_share_pct")
        colors = [NEG if v < 0 else POS for v in tbl["yoy_share_pct"]]
        ax.barh(tbl["country"], tbl["yoy_share_pct"], color=colors)
        ax.axvline(0, color="black", linewidth=0.8)
        ax.set_xlabel("YoY share of panel change (%)")
        ax.set_title(product_label(code))
    fig.suptitle(f"Who drives YoY change — {METRIC_LABELS[metric]}", y=1.01)
    fig.tight_layout()
    plt.show()
'''

VIZ_TRENDS = '''for metric in METRICS:
    unit = METRIC_UNITS[metric]
    contrib = by_metric[metric]["contrib"]
    audit = by_metric[metric]["audit"]
    display(Markdown(f"### {METRIC_LABELS[metric]} — freshness & trends"))

    audit_plot = audit.sort_values("months_behind_peer", ascending=True)
    bar_colors = [
        POS if r.in_panel else (NEG if r.flag_lagging else "#ffbb78")
        for r in audit_plot.itertuples()
    ]
    fig, ax = plt.subplots(figsize=(10, max(5, len(audit_plot) * 0.35)))
    ax.barh(audit_plot["country"], audit_plot["months_behind_peer"], color=bar_colors)
    ax.set_xlabel("Months behind group latest print")
    ax.set_title(f"Reporter freshness — {product_label(PRODUCT)}")
    ax.legend(
        handles=[
            plt.Line2D([0], [0], color=POS, lw=6, label="In balanced panel"),
            plt.Line2D([0], [0], color=NEG, lw=6, label="Lagging / excluded"),
            plt.Line2D([0], [0], color="#ffbb78", lw=6, label="Current, not in panel"),
        ],
        loc="lower right",
    )
    plt.tight_layout()
    plt.show()

    if contrib.empty:
        continue

    top5 = contrib.nlargest(5, "level_kb_d")
    fig, axes = plt.subplots(2, 3, figsize=(15, 8))
    for ax, (_, row) in zip(axes.flat, top5.iterrows()):
        iso = str(row["ref_area"])
        ts = get_dashboard_series(
            PRODUCT, iso, metric, lag_months=DRIVER_LAG_MONTHS,
        ).tail(24)
        ax.plot(ts["date"], ts["value"], color="#1f77b4")
        ax.set_title(row["country"])
        ax.set_ylabel(unit)
        ax.tick_params(axis="x", rotation=45)

    regional_ts = get_dashboard_series(
        PRODUCT, GEOGRAPHY, metric, lag_months=DRIVER_LAG_MONTHS,
    ).tail(24)
    axes.flat[5].plot(regional_ts["date"], regional_ts["value"], color=TOTAL, linewidth=2)
    axes.flat[5].set_title(f"{GEO_LABEL} total")
    axes.flat[5].set_ylabel(unit)
    axes.flat[5].tick_params(axis="x", rotation=45)

    fig.suptitle(f"{product_label(PRODUCT)} — last 24 months ({METRIC_LABELS[metric]})", y=1.02)
    fig.tight_layout()
    plt.show()
'''

DRILLDOWN = '''# --- drill-down config (set after reviewing Sections 3–9) ---
# ISO codes (UK → GB). None = auto-pick largest |YoY| movers on TOTPRODS demand.
DRILL_COUNTRIES: list[str] | None = None  # e.g. ["GB", "DE"]
DRILL_AUTO_N = 3
DRILL_HEADLINE_PRODUCT = "TOTPRODS"


def resolve_drill_countries() -> list[tuple[str, str]]:
    """Return [(ref_area, country_name), ...] to drill into."""
    if DRILL_COUNTRIES:
        codes = [str(GEO_ALIASES.get(c, c)) for c in DRILL_COUNTRIES]
    else:
        contrib = by_metric.get("demand", {}).get("contrib", pd.DataFrame())
        if contrib.empty:
            return []
        n = min(DRILL_AUTO_N, len(contrib))
        top = contrib.loc[contrib["yoy_change"].abs().nlargest(n).index]
        codes = top["ref_area"].astype(str).tolist()
    return [(c, COUNTRY_NAMES.get(c, c)) for c in codes]


drill_targets = resolve_drill_countries()
if not drill_targets:
    print(
        "No drill-down targets — set DRILL_COUNTRIES (e.g. ['GB']) "
        "or ensure regional TOTPRODS panel loaded."
    )
else:
    print("Drill-down:", ", ".join(f"{name} ({code})" for code, name in drill_targets))

for ref_area, country_name in drill_targets:
    display(Markdown(f"# {country_name} ({ref_area})"))

    for metric in METRICS:
        unit = METRIC_UNITS[metric]
        contrib = by_metric[metric]["contrib"]
        display(Markdown(f"## {METRIC_LABELS[metric]} ({unit})"))

        if not contrib.empty:
            match = contrib.loc[contrib["ref_area"].astype(str) == ref_area]
            if not match.empty:
                row = match.iloc[0]
                reg_yoy = contrib["yoy_change"].sum()
                reg_mom = contrib["mom_change"].sum()
                display(Markdown(
                    f"**{product_label(DRILL_HEADLINE_PRODUCT)} vs {GEO_LABEL} panel** — "
                    f"YoY **{row['yoy_change']:,.0f}** {unit} "
                    f"({row['yoy_share_pct']:.0f}% of regional), "
                    f"MoM **{row['mom_change']:,.0f}** {unit} "
                    f"({row['mom_share_pct']:.0f}% of regional). "
                    f"Panel totals: {reg_yoy:,.0f} YoY / {reg_mom:,.0f} MoM {unit}."
                ))

        breakdown = build_country_product_breakdown(
            GEOGRAPHY, ref_area, lag_months=DRIVER_LAG_MONTHS, metric=metric,
        )
        if breakdown.empty:
            print(f"No balanced-panel products for {country_name} ({metric}).")
            continue

        show = breakdown[
            ["product", "month", "level_kb_d", "yoy_change", "mom_change",
             "yoy_share_pct", "mom_share_pct"]
        ].round(0)
        display(Markdown(f"### Product breakdown — which lines moved?"))
        display(show)

        fig, axes = plt.subplots(1, 2, figsize=(14, max(5, len(breakdown) * 0.35)), sharey=True)
        plot_df = breakdown.sort_values("yoy_change")
        for ax, col, title in zip(
            axes,
            ["yoy_change", "mom_change"],
            [f"YoY ({unit})", f"MoM ({unit})"],
        ):
            colors = [NEG if v < 0 else POS for v in plot_df[col]]
            ax.barh(plot_df["product"], plot_df[col], color=colors)
            ax.axvline(0, color="black", linewidth=0.8)
            ax.set_title(title)
            ax.set_xlabel(unit)
        fig.suptitle(f"{country_name} — {METRIC_LABELS[metric]} by product", y=1.02)
        fig.tight_layout()
        plt.show()

        top3 = breakdown.reindex(
            breakdown["yoy_change"].abs().nlargest(min(3, len(breakdown))).index
        )
        if top3.empty:
            continue
        fig, axes = plt.subplots(1, len(top3), figsize=(5 * len(top3), 4), squeeze=False)
        for ax, (_, prow) in zip(axes.flat, top3.iterrows()):
            pcode = prow["product_code"]
            ts = get_dashboard_series(
                pcode, ref_area, metric, lag_months=DRIVER_LAG_MONTHS,
            ).tail(24)
            ax.plot(ts["date"], ts["value"], color="#1f77b4")
            ax.set_title(prow["product_code"])
            ax.set_ylabel(unit)
            ax.tick_params(axis="x", rotation=45)
        fig.suptitle(
            f"{country_name} — top movers, last 24 months ({METRIC_LABELS[metric]})",
            y=1.08,
        )
        fig.tight_layout()
        plt.show()
'''

nb = {
    "nbformat": 4,
    "nbformat_minor": 5,
    "metadata": {
        "kernelspec": {
            "display_name": "Python 3",
            "language": "python",
            "name": "python3",
        },
        "language_info": {"name": "python", "pygments_lexer": "ipython3"},
    },
    "cells": [
        md(
            "# Regional drivers (JODI)\n\n"
            "Static notebook — **pandas** tables and **matplotlib** charts.\n\n"
            "- **Demand** (kb/d) and **ending stocks** (mbbl)\n"
            "- **YoY** — same month vs last year · **MoM** — vs prior month\n"
            "- **Balanced panel** (lag = 0): reporters with ref, YoY, and MoM data\n\n"
            "Edit **`GEOGRAPHY`** and **`METRICS`** in Setup, then **Run All**. "
            "Use **Section 10** to drill into countries flagged in the regional view."
        ),
        md("## 1. Setup"),
        code(SETUP),
        md("## 2. Load data"),
        code(LOAD),
        md("## 3. Regional summary by product"),
        code(REGIONAL),
        md("## 4. TOTPRODS — country contributions"),
        code(TOTPRODS),
        md("## 5. All products — country tables"),
        code(ALL_PRODUCTS),
        md("## 6. Panel audit (TOTPRODS)"),
        code(PANEL_AUDIT),
        md("## 7. Visual summary"),
        code(VIZ_CORE),
        md("## 8. Level & share context"),
        code(VIZ_CONTEXT),
        md("## 9. Freshness & trends"),
        code(VIZ_TRENDS),
        md(
            "## 10. Country drill-down\n\n"
            "After spotting a driver in the heatmap or TOTPRODS table, set **`DRILL_COUNTRIES`** "
            "(e.g. `['GB']`) or leave `None` to auto-pick the top `DRILL_AUTO_N` |YoY| movers."
        ),
        code(DRILLDOWN),
        md(
            "## Notes\n\n"
            "- **`GEOGRAPHY`**: `REGION_PREFIX + \"Europe\"`, `CONSOLIDATED_ASIA_PACIFIC`, "
            "`GLOBAL_KEY`, or ISO code (`GB`; `UK` aliases to `GB`)\n"
            "- **`level_kb_d`**: kb/d for demand, mbbl for stocks\n"
            "- **panel_n** / **excluded_n**: in-panel vs mapped region members\n"
            "- **Share %**: signed share of panel total YoY/MoM change\n"
            "- **Section 10**: product breakdown + history for countries driving regional moves\n"
            "- Time series use JODI country/regional totals (not re-filtered to balanced panel)\n"
            "- Interactive charts: `05_jodi_dashboard.ipynb`"
        ),
    ],
}

OUT.write_text(json.dumps(nb, indent=1), encoding="utf-8")
print(f"Created {OUT}")
