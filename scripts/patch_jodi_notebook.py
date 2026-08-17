"""Patch 05_jodi_dashboard.ipynb to use analytics.jodi_dashboard."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NB_PATH = ROOT / "notebooks" / "05_jodi_dashboard.ipynb"

IMPORT_CELL = '''"""Bind JODI dashboard core from analytics.jodi_dashboard (Sections 2–4 + seasonal)."""

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

UI_HELPERS_CELL = '''"""Widget helpers shared by Sections 5–10. Re-run only after kernel restart."""

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

SECTION10_CELL = '''"""Section 10 — regional demand drivers (secondary, balanced panel, lag=0)."""

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

driver_out = widgets.Output()


def _load_driver_summary(geography: str):
    if _driver_summary_cache["geography"] != geography:
        _driver_summary_cache["geography"] = geography
        _driver_summary_cache["table"] = build_regional_driver_summary(
            geography, lag_months=DRIVER_LAG_MONTHS,
        )
    return _driver_summary_cache["table"]


def _render_driver_panel(*_change) -> None:
    geography = driver_country_dd.value
    product = driver_product_dd.value
    _, geo_label = resolve_geography(geography)

    with driver_out:
        driver_out.clear_output(wait=True)
        codes, _ = resolve_geography(geography)
        if len(codes) <= 1:
            display(HTML(
                f"<p><i>{geo_label} is a single country — pick a region or Global Total "
                "for a multi-country driver decomposition.</i></p>"
            ))
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
            f"latest print. Reference month varies by product.</p>"
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


driver_ui = widgets.VBox([driver_country_dd, driver_product_dd])

_bind_once(driver_country_dd, _render_driver_panel, tag="sec10_drivers_region")
_bind_once(driver_product_dd, _render_driver_panel, tag="sec10_drivers_product")

display(driver_ui, driver_out)
_render_driver_panel()
'''


def _to_nb_source(text: str) -> list[str]:
    lines = text.split("\n")
    return [line + "\n" for line in lines[:-1]] + ([lines[-1] + "\n"] if lines[-1] else [])


def main() -> None:
    nb = json.loads(NB_PATH.read_text(encoding="utf-8"))

    for cell in nb["cells"]:
        src = "".join(cell.get("source", []))
        if cell["cell_type"] == "markdown" and src.startswith("## 2."):
            cell["source"] = _to_nb_source(
                "## 2. Dashboard core (import)\n\n"
                "Logic lives in `analytics/jodi_dashboard.py`. Run **once** after setup.\n\n"
                "> **Kernel restart** before re-running UI sections (5–10) — otherwise "
                "widgets stack and callbacks multiply."
            )
        if cell["cell_type"] == "markdown" and src.startswith("## 3."):
            cell["source"] = _to_nb_source(
                "## 3. Widget helpers\n\n"
                "Dropdown option lists and lag controls for Sections 5–9."
            )
        if cell["cell_type"] == "markdown" and src.startswith("## 4."):
            cell["source"] = _to_nb_source("## 4. (removed — see Section 2 import)")

    nb["cells"][0]["source"][7] = (
        "> **Workflow**: Kernel restart → run Setup + Sections 2–3 once → run each UI "
        "section (5–10) **once**. Re-running UI cells duplicates widgets.\n"
    )

    nb["cells"][5]["cell_type"] = "code"
    nb["cells"][5]["source"] = _to_nb_source(IMPORT_CELL)
    nb["cells"][5]["outputs"] = []
    nb["cells"][5]["execution_count"] = None

    for idx, stub in [
        (7, "*(Geography resolver — imported from `analytics.jodi_dashboard`)*"),
        (8, "*(Metric resolver — imported from `analytics.jodi_dashboard`)*"),
        (10, "*(Series + chart builders — imported from `analytics.jodi_dashboard`)*"),
        (19, "*(Seasonal frame + chart — imported from `analytics.jodi_dashboard`)*"),
        (20, "*(see Section 2 import)*"),
    ]:
        nb["cells"][idx]["cell_type"] = "markdown"
        nb["cells"][idx]["source"] = _to_nb_source(stub)
        nb["cells"][idx]["outputs"] = []

    nb["cells"][11]["cell_type"] = "code"
    nb["cells"][11]["source"] = _to_nb_source(UI_HELPERS_CELL)
    nb["cells"][11]["outputs"] = []
    nb["cells"][11]["execution_count"] = None

    nb["cells"][25]["source"] = _to_nb_source(SECTION10_CELL)
    nb["cells"][25]["outputs"] = []
    nb["cells"][25]["execution_count"] = None

    NB_PATH.write_text(json.dumps(nb, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Patched {NB_PATH}")


if __name__ == "__main__":
    main()
