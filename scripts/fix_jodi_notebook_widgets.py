"""Fix widget duplication, debounce callbacks, and notebook section layout."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NB_PATH = ROOT / "notebooks" / "05_jodi_dashboard.ipynb"

IMPORT_CELL = '''"""Bind JODI dashboard core from analytics.jodi_dashboard."""

from analytics.jodi_dashboard import (
    configure,
    PRODUCTS_PRIMARY,
    PRODUCTS_SECONDARY,
    PRODUCT_TO_DATASET,
    REGION_MAP,
    CONSOLIDATED_ASIA_PACIFIC,
    REGION_ORDER,
    GLOBAL_KEY,
    REGION_PREFIX,
    METRIC_LABELS,
    ALL_DASHBOARD_PRODUCT_CODES,
    SEASONALITY_YEARS_BACK,
    SNAPSHOT_HISTORY_YEARS,
    DRIVER_LAG_MONTHS,
    SECONDARY_DEMAND_PRODUCT_CODES,
    resolve_geography,
    metric_spec,
    get_dashboard_series,
    assess_reporter_freshness,
    render_chart,
    get_all_products_series,
    build_product_snapshot_table,
    build_product_snapshot_tables,
    snapshot_month_options,
    style_product_snapshot_table,
    build_regional_driver_summary,
    build_country_contribution_table,
    style_regional_driver_summary,
    style_country_contribution_table,
    build_seasonal_frame,
    render_seasonal_chart,
    render_seasonality_by_year_all_products,
    product_label as _product_label,
)

configure(df_sec, df_pri, COUNTRY_NAMES)

print(
    f"Dashboard core configured "
    f"({len(SECONDARY_DEMAND_PRODUCT_CODES)} secondary products)"
)
'''

WIDGET_HELPERS = '''"""Widget helpers for Sections 5–10. Run once after Section 2 (kernel restart → 1 → 2 → 3)."""

import threading


def _bind_once(widget, handler, *, names: str = "value", tag: str = "default") -> None:
    """Register a widget callback without stacking duplicates on cell re-run."""
    registry = getattr(widget, "_dashboard_handlers", None)
    if registry is None:
        registry = {}
        widget._dashboard_handlers = registry
    old = registry.get(tag)
    if old is not None:
        try:
            widget.unobserve(old, names=names)
        except (ValueError, KeyError):
            pass
    widget.observe(handler, names=names)
    registry[tag] = handler


def _debounce(delay_ms: int = 250):
    """Coalesce rapid widget callbacks into a single render (avoids stacked Output)."""

    def decorator(fn):
        state = {"timer": None, "generation": 0}

        def wrapped(*args, **kwargs):
            state["generation"] += 1
            generation = state["generation"]
            if state["timer"] is not None:
                state["timer"].cancel()

            def fire() -> None:
                if generation == state["generation"]:
                    fn(*args, **kwargs)

            state["timer"] = threading.Timer(delay_ms / 1000.0, fire)
            state["timer"].start()

        wrapped.__name__ = fn.__name__
        wrapped.__doc__ = fn.__doc__
        return wrapped

    return decorator


def _product_dropdown_options() -> list[tuple[str, str]]:
    headline = [
        ("Total oil products (TOTPRODS)", "TOTPRODS"),
        ("Total crude (TOTCRUDE)", "TOTCRUDE"),
    ]
    rest_secondary = sorted(
        [(f"{label} ({code})", code) for code, label in PRODUCTS_SECONDARY.items()
         if code != "TOTPRODS"],
        key=lambda x: x[0].lower(),
    )
    rest_primary = sorted(
        [(f"{label} ({code})", code) for code, label in PRODUCTS_PRIMARY.items()
         if code != "TOTCRUDE"],
        key=lambda x: x[0].lower(),
    )
    return headline + rest_secondary + rest_primary


def _country_dropdown_options() -> list[tuple[str, str]]:
    opts: list[tuple[str, str]] = [("Global Total", GLOBAL_KEY)]
    opts += [(f"{r} (region)", REGION_PREFIX + r) for r in REGION_ORDER]
    present_codes = (
        set(df_sec["ref_area"].astype(str).unique())
        | set(df_pri["ref_area"].astype(str).unique())
    )
    countries = sorted(
        [(COUNTRY_NAMES.get(code, code), code) for code in present_codes if code],
        key=lambda x: x[0].lower(),
    )
    return opts + countries


def _metric_dropdown_options() -> list[tuple[str, str]]:
    return [(label, code) for code, label in METRIC_LABELS.items()]


def _secondary_product_dropdown_options() -> list[tuple[str, str]]:
    headline = [("Total oil products (TOTPRODS)", "TOTPRODS")]
    rest = sorted(
        [(f"{label} ({code})", code) for code, label in PRODUCTS_SECONDARY.items()
         if code != "TOTPRODS"],
        key=lambda x: x[0].lower(),
    )
    return headline + rest


exclude_lagging_cb = widgets.Checkbox(
    value=False,
    description="Exclude lagging reporters from group totals",
    indent=False,
)
lag_months_slider = widgets.IntSlider(
    value=2,
    min=0,
    max=6,
    step=1,
    description="Lag ≥ months:",
    style={"description_width": "initial"},
    layout=widgets.Layout(width="420px"),
)


def _exclusion_kwargs() -> dict:
    return {
        "exclude_lagging": exclude_lagging_cb.value,
        "lag_months": int(lag_months_slider.value),
    }
'''

SECTION5 = '''"""Section 5 — time series chart."""

product_dd = widgets.Dropdown(
    options=_product_dropdown_options(),
    value="TOTPRODS",
    description="Product:",
    style={"description_width": "100px"},
    layout=widgets.Layout(width="420px"),
)
country_dd = widgets.Dropdown(
    options=_country_dropdown_options(),
    value=GLOBAL_KEY,
    description="Country:",
    style={"description_width": "100px"},
    layout=widgets.Layout(width="420px"),
)
metric_dd = widgets.Dropdown(
    options=_metric_dropdown_options(),
    value="demand",
    description="Metric:",
    style={"description_width": "100px"},
    layout=widgets.Layout(width="420px"),
)

ts_out = widgets.Output()


@_debounce(200)
def _render_timeseries(*_change) -> None:
    with ts_out:
        ts_out.clear_output(wait=True)
        render_chart(
            product_dd.value, country_dd.value, metric_dd.value,
            **_exclusion_kwargs(),
        ).show()


ui = widgets.VBox([
    product_dd, country_dd, metric_dd,
    exclude_lagging_cb, lag_months_slider,
])

for _w in (product_dd, country_dd, metric_dd, exclude_lagging_cb, lag_months_slider):
    _bind_once(_w, _render_timeseries, tag="sec5_timeseries")

display(ui, ts_out)
_render_timeseries()
'''

SECTION6 = '''"""Section 6 — seasonality by year (all products)."""

seas_country_dd = widgets.Dropdown(
    options=_country_dropdown_options(),
    value=GLOBAL_KEY,
    description="Country:",
    style={"description_width": "100px"},
    layout=widgets.Layout(width="420px"),
)
seas_metric_dd = widgets.Dropdown(
    options=_metric_dropdown_options(),
    value="demand",
    description="Metric:",
    style={"description_width": "100px"},
    layout=widgets.Layout(width="420px"),
)

seas_out = widgets.Output()


@_debounce(300)
def _render_seasonality_panel(*_change) -> None:
    with seas_out:
        seas_out.clear_output(wait=True)
        render_seasonality_by_year_all_products(
            seas_country_dd.value, seas_metric_dd.value,
            **_exclusion_kwargs(),
        ).show()


seas_ui = widgets.VBox([seas_country_dd, seas_metric_dd])

for _w in (seas_country_dd, seas_metric_dd):
    _bind_once(_w, _render_seasonality_panel, tag="sec6_seasonality")

display(seas_ui, seas_out)
_render_seasonality_panel()
'''

SECTION7 = '''"""Section 7 — product snapshot (YoY vs 5y band)."""

from IPython.display import HTML

snap_country_dd = widgets.Dropdown(
    options=_country_dropdown_options(),
    value=GLOBAL_KEY,
    description="Country:",
    style={"description_width": "100px"},
    layout=widgets.Layout(width="420px"),
)
snap_month_dd = widgets.Dropdown(
    options=snapshot_month_options(GLOBAL_KEY),
    description="Month:",
    style={"description_width": "100px"},
    layout=widgets.Layout(width="420px"),
)
snap_refresh_btn = widgets.Button(description="Refresh", button_style="primary")
snap_status_lbl = widgets.Label(value="")

snap_out = widgets.Output()


def _refresh_snapshot_month_options() -> None:
    opts = snapshot_month_options(snap_country_dd.value)
    with snap_month_dd.hold_trait_notifications():
        snap_month_dd.options = opts
        if opts:
            snap_month_dd.value = opts[0][1]


def _render_snapshot_tables(_=None) -> None:
    geography = snap_country_dd.value
    ref_year, ref_month = snap_month_dd.value
    _, geo_label = resolve_geography(geography)
    month_lbl = f"{ref_year}-{ref_month:02d}"

    with snap_out:
        snap_out.clear_output(wait=True)
        snap_status_lbl.value = "Loading…"
        display(HTML(f"<h4>{geo_label} — {month_lbl}</h4>"))

        tables = build_product_snapshot_tables(
            geography,
            reference_year=ref_year,
            reference_month=ref_month,
            **_exclusion_kwargs(),
        )
        for metric, title in (
            ("demand", "Demand (kb/d)"),
            ("stocks", "Ending stocks (mbbl)"),
        ):
            tbl = tables[metric]
            display(HTML(f"<b>{title}</b>"))
            if tbl.empty or tbl["current"].isna().all():
                display(HTML("<p><i>No data for this selection</i></p>"))
            else:
                display(style_product_snapshot_table(tbl))
        snap_status_lbl.value = "Done."


def _on_snap_country_change(_change) -> None:
    _refresh_snapshot_month_options()


_bind_once(snap_country_dd, _on_snap_country_change, tag="sec7_snapshot_country")
snap_refresh_btn.on_click(_render_snapshot_tables)

snap_ui = widgets.VBox([
    snap_country_dd,
    snap_month_dd,
    widgets.HBox([snap_refresh_btn, snap_status_lbl]),
])

display(snap_ui, snap_out)
_refresh_snapshot_month_options()
_render_snapshot_tables()
'''

SECTION9 = '''"""Section 9 — reporter freshness."""

from IPython.display import HTML

fresh_country_dd = widgets.Dropdown(
    options=_country_dropdown_options(),
    value=GLOBAL_KEY,
    description="Country:",
    style={"description_width": "100px"},
    layout=widgets.Layout(width="420px"),
)
fresh_product_dd = widgets.Dropdown(
    options=_product_dropdown_options(),
    value="TOTPRODS",
    description="Product:",
    style={"description_width": "100px"},
    layout=widgets.Layout(width="420px"),
)
fresh_metric_dd = widgets.Dropdown(
    options=[("Demand", "demand"), ("Ending stocks", "stocks")],
    value="demand",
    description="Metric:",
    style={"description_width": "100px"},
    layout=widgets.Layout(width="420px"),
)

fresh_out = widgets.Output()


@_debounce(200)
def _render_freshness_table(*_change) -> None:
    geography = fresh_country_dd.value
    product = fresh_product_dd.value
    metric = fresh_metric_dd.value
    lag = int(lag_months_slider.value)
    _, geo_label = resolve_geography(geography)

    with fresh_out:
        fresh_out.clear_output(wait=True)
        codes, _ = resolve_geography(geography)
        if len(codes) <= 1:
            display(HTML(
                f"<p><i>{geo_label} is a single country — no peer lag comparison. "
                "Pick a region or Global Total.</i></p>"
            ))
            return

        tbl = assess_reporter_freshness(
            geography, product, metric, lag_months=lag,
        )
        n_lag = int(tbl["flag_lagging"].sum())
        peer = tbl["peer_latest"].iloc[0]
        peer_str = peer.strftime("%Y-%m") if pd.notna(peer) else "—"
        display(HTML(
            f"<h4>{geo_label} — {_product_label(product)} — {METRIC_LABELS[metric]}</h4>"
            f"<p>Group latest month: <b>{peer_str}</b> · "
            f"Lagging (≥{lag} mo behind): <b>{n_lag}</b> / {len(tbl)} countries</p>"
        ))
        show_cols = [
            "country", "ref_area", "latest_date", "peer_latest",
            "months_behind_peer", "flag_lagging",
        ]
        view = tbl[show_cols].copy()
        view["latest_date"] = view["latest_date"].dt.strftime("%Y-%m")
        view["peer_latest"] = view["peer_latest"].dt.strftime("%Y-%m")
        display(
            view.style.format({"months_behind_peer": "{:.0f}"})
            .background_gradient(subset=["months_behind_peer"], cmap="YlOrRd")
            .set_properties(**{"text-align": "left"})
        )
        if exclude_lagging_cb.value and n_lag:
            excluded = ", ".join(
                tbl.loc[tbl["flag_lagging"], "country"].head(8).astype(str)
            )
            display(HTML(
                f"<p><i>Excluded from group totals: {excluded}"
                f"{'…' if n_lag > 8 else ''}</i></p>"
            ))


fresh_ui = widgets.VBox([fresh_country_dd, fresh_product_dd, fresh_metric_dd])

for _w in (fresh_country_dd, fresh_product_dd, fresh_metric_dd):
    _bind_once(_w, _render_freshness_table, tag="sec9_freshness")

display(fresh_ui, fresh_out)
_render_freshness_table()
'''

SECTION10 = '''"""Section 10 — regional demand drivers (button refresh)."""

from IPython.display import HTML

_driver_summary_cache: dict = {"geography": None, "table": None}

driver_country_dd = widgets.Dropdown(
    options=_country_dropdown_options(),
    value=REGION_PREFIX + CONSOLIDATED_ASIA_PACIFIC,
    description="Region:",
    style={"description_width": "100px"},
    layout=widgets.Layout(width="420px"),
)
driver_product_dd = widgets.Dropdown(
    options=_secondary_product_dropdown_options(),
    value="TOTPRODS",
    description="Product:",
    style={"description_width": "100px"},
    layout=widgets.Layout(width="420px"),
)
driver_refresh_btn = widgets.Button(description="Refresh", button_style="primary")
driver_status_lbl = widgets.Label(value="")

driver_out = widgets.Output()


def _load_driver_summary(geography: str):
    if _driver_summary_cache["geography"] != geography:
        _driver_summary_cache["geography"] = geography
        _driver_summary_cache["table"] = build_regional_driver_summary(
            geography, lag_months=DRIVER_LAG_MONTHS,
        )
    return _driver_summary_cache["table"]


def _render_driver_panel(_=None) -> None:
    geography = driver_country_dd.value
    product = driver_product_dd.value
    _, geo_label = resolve_geography(geography)

    with driver_out:
        driver_out.clear_output(wait=True)
        driver_status_lbl.value = "Loading…"
        codes, _ = resolve_geography(geography)
        if len(codes) <= 1:
            display(HTML(
                f"<p><i>{geo_label} is a single country — pick a region or Global Total "
                "for a multi-country driver decomposition.</i></p>"
            ))
            driver_status_lbl.value = ""
            return

        summary = _load_driver_summary(geography)
        contrib = build_country_contribution_table(
            geography, product, lag_months=DRIVER_LAG_MONTHS,
        )

        ref_row = summary.loc[summary["product_code"] == product]
        ref_month = ref_row["month"].iloc[0] if not ref_row.empty else "—"
        panel_n = int(ref_row["panel_n"].iloc[0]) if not ref_row.empty else 0

        display(HTML(
            f"<h4>{geo_label} — secondary demand drivers</h4>"
            f"<p>Balanced panel at lag = {DRIVER_LAG_MONTHS} mo: "
            f"same countries in reference, YoY, and MoM months, all at the group "
            f"latest print. Reference month varies by product. "
            f"For a focused APAC workflow see "
            f"<code>11_jodi_regional_drivers.ipynb</code>.</p>"
        ))

        show_summary = summary[[
            "product", "month", "level_kb_d", "yoy_change", "yoy_pct",
            "mom_change", "mom_pct", "vs_5y_range", "panel_n", "excluded_n",
        ]]
        display(HTML("<h5>All products — regional change (panel totals)</h5>"))
        display(style_regional_driver_summary(show_summary))

        display(HTML(
            f"<h5>{_product_label(product)} — country contributions "
            f"({panel_n} panel members, ref {ref_month})</h5>"
        ))
        if contrib.empty:
            display(HTML("<p><i>No balanced panel for this product.</i></p>"))
        else:
            display(style_country_contribution_table(contrib))
        driver_status_lbl.value = "Done."


driver_refresh_btn.on_click(_render_driver_panel)

driver_ui = widgets.VBox([
    driver_country_dd,
    driver_product_dd,
    widgets.HBox([driver_refresh_btn, driver_status_lbl]),
])

display(driver_ui, driver_out)
_render_driver_panel()
'''

INTRO = """# JODI Dashboard

Three-dropdown interactive view of the consolidated JODI database:

1. **Product** — secondary or primary series (e.g. TOTPRODS, GASDIES).
2. **Country / region** — single country, a region (including consolidated **Asia Pacific**), or `Global Total`.
3. **Metric** — `Demand`, `Ending stocks`, or `Days of forward demand cover`.

> **Workflow**: Kernel restart → **Clear All Outputs** → run **Sections 1 → 2 → 3** once → run each UI section (**5–10**) once. Re-running UI cells duplicates widgets.

> **Regional drivers**: use `11_jodi_regional_drivers.ipynb` for demand/stocks decomposition (edit `GEOGRAPHY` in Setup).

> **One-time setup**: `pip install ipywidgets>=8.0` (in `requirements.txt`).

> **Scaling later**: logic lives in `analytics/jodi_dashboard.py`; a Streamlit/Dash port is a different UI shell over the same functions.
"""


def _to_nb_source(text: str) -> list[str]:
    lines = text.split("\n")
    return [line + "\n" for line in lines[:-1]] + ([lines[-1] + "\n"] if lines[-1] else [])


def _is_stub(cell: dict) -> bool:
    if cell["cell_type"] != "markdown":
        return False
    src = "".join(cell.get("source", []))
    return src.startswith("*(") or src.startswith("## 4. (removed")


def _clear_outputs(cell: dict) -> None:
    if cell["cell_type"] == "code":
        cell["outputs"] = []
        cell["execution_count"] = None


def main() -> None:
    nb = json.loads(NB_PATH.read_text(encoding="utf-8"))

    nb["cells"][0]["source"] = _to_nb_source(INTRO)

    nb["cells"][4]["source"] = _to_nb_source(
        "## 2. Dashboard core (import)\n\n"
        "Logic lives in `analytics/jodi_dashboard.py`. Run **once** after Section 1."
    )

    nb["cells"][6]["source"] = _to_nb_source(
        "## 3. Widget helpers\n\n"
        "Dropdown lists, debounced callbacks, and lag controls. **Required** before Sections 5–10."
    )

    # Remove stub markdown cells (old sections 4 + moved stubs)
    nb["cells"] = [c for c in nb["cells"] if not _is_stub(c)]

    # Re-find cells by content after deletion
    for cell in nb["cells"]:
        src = "".join(cell.get("source", []))
        if cell["cell_type"] == "code" and src.startswith('"""Bind JODI dashboard'):
            cell["source"] = _to_nb_source(IMPORT_CELL)
            _clear_outputs(cell)
        elif cell["cell_type"] == "code" and (
            "Widget helpers" in src[:120]
        ):
            cell["source"] = _to_nb_source(WIDGET_HELPERS)
            _clear_outputs(cell)
        elif cell["cell_type"] == "code" and (
            "Section 5" in src[:80] or "time series chart" in src[:80]
        ):
            cell["source"] = _to_nb_source(SECTION5)
            _clear_outputs(cell)
        elif cell["cell_type"] == "code" and (
            "Section 6" in src[:80] or "Seasonality-by-year panel" in src[:80]
        ):
            cell["source"] = _to_nb_source(SECTION6)
            _clear_outputs(cell)
        elif cell["cell_type"] == "code" and (
            "Section 7" in src[:80]
            or "Product snapshot tables" in src[:80]
            or "snap_out = widgets.Output()" in src
        ):
            cell["source"] = _to_nb_source(SECTION7)
            _clear_outputs(cell)
        elif cell["cell_type"] == "code" and (
            "Section 9" in src[:80] or "Reporter freshness table" in src[:80]
        ):
            cell["source"] = _to_nb_source(SECTION9)
            _clear_outputs(cell)
        elif cell["cell_type"] == "code" and "Section 10" in src[:80]:
            cell["source"] = _to_nb_source(SECTION10)
            _clear_outputs(cell)
        elif cell["cell_type"] == "code" and "_render_seasonal_now" in src:
            # Section 8 — add debounce to existing cell
            if "@_debounce" not in src:
                src = src.replace(
                    "def _render_seasonal_now(*_change) -> None:",
                    "@_debounce(200)\ndef _render_seasonal_now(*_change) -> None:",
                )
                cell["source"] = _to_nb_source(src)
            _clear_outputs(cell)
        elif cell["cell_type"] == "code":
            _clear_outputs(cell)

    # Clear widget state blob if present (reduces ghost widget restore)
    md = nb.get("metadata", {})
    if "widgets" in md:
        md["widgets"] = {"application/vnd.jupyter.widget-state+json": {"state": {}, "version_major": 2}}

    NB_PATH.write_text(json.dumps(nb, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Fixed {NB_PATH}")


if __name__ == "__main__":
    main()
