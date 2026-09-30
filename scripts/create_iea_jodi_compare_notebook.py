"""Generate notebooks/28_iea_vs_jodi_comparison.ipynb (no saved outputs)."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "notebooks" / "28_iea_vs_jodi_comparison.ipynb"


def md(text: str) -> dict:
    return {
        "cell_type": "markdown",
        "metadata": {},
        "source": text.splitlines(keepends=True),
        "id": None,
    }


def code(text: str) -> dict:
    return {
        "cell_type": "code",
        "metadata": {},
        "source": text.splitlines(keepends=True),
        "outputs": [],
        "execution_count": None,
        "id": None,
    }


cells = [
    md(
        """# IEA vs JODI — coverage, concepts, scraper gaps

Phase 1 profile of **IEA Monthly Oil Statistics** (`data/raw/iea/`) against
**JODI** processed parquets, plus which countries your national scrapers still miss.

Uses `analytics/iea_jodi_profile.py` (read-only — no warehouse writes).
"""
    ),
    code(
        r'''from pathlib import Path
import sys

import pandas as pd
from IPython.display import display, Markdown

pd.set_option("display.max_rows", 200)
pd.set_option("display.max_colwidth", 80)


def _resolve_project_root() -> Path:
    here = Path.cwd()
    for candidate in [here, *here.parents]:
        if (candidate / "analytics" / "iea_jodi_profile.py").exists():
            return candidate
        nested = candidate / "country_oil_scraper"
        if (nested / "analytics" / "iea_jodi_profile.py").exists():
            return nested
    raise RuntimeError(f"Could not locate project root from cwd: {here}")


ROOT = _resolve_project_root()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analytics.iea_jodi_profile import (
    CONCEPT_ROWS,
    coverage_summary,
    load_scraper_countries,
    profile_iea,
    profile_jodi,
    pros_cons_table,
    scraper_gap_tables,
)

scrapers = load_scraper_countries(ROOT)
iea = profile_iea(ROOT)
jodi = profile_jodi(ROOT)
gaps = scraper_gap_tables(iea, jodi, scrapers)

print("ROOT:", ROOT)
print("scrapers:", len(scrapers), "| IEA ISO countries:", len(iea["iea_countries_all"]), "| JODI:", jodi["meta"]["n_countries"])
'''
    ),
    md("## 1. Concept map — what each source actually publishes"),
    code(
        r'''display(pd.DataFrame(CONCEPT_ROWS))
display(Markdown("### Pros / cons"))
display(pros_cons_table())
'''
    ),
    md(
        """## 2. Coverage summary

Counts are **ISO-mapped countries** (IEA regional aggregates excluded).
Inventories: IEA = MOSSTOCKS reporters; JODI = secondary `CLOSTLV`.
"""
    ),
    code(
        r'''summary = coverage_summary(iea, jodi, scrapers)
display(summary)

display(Markdown("### Your national scrapers"))
display(gaps["scraper_coverage"])
'''
    ),
    md(
        """## 3. Inventories — SPR vs commercial disaggregation

| Source | Split |
|--------|--------|
| **IEA MOSSTOCKS** | Government stocks (SPR-like) / Industry stocks / Total stocks |
| **IEA balances** | `CSGOV` (government) + `CSNATTER` (national territory) |
| **JODI** | `CLOSTLV` only — **no** SPR vs commercial |

Table below: OECD reporters in MOSSTOCKS and whether each category has data.
"""
    ),
    code(
        r'''inv = iea["inventory_disaggregation"].copy()
# Show presence flags first; n_obs columns prove non-empty history.
show = inv[
    [
        "iso2",
        "Country",
        "has_government_spr",
        "has_industry",
        "has_total",
        "Government stocks",
        "Industry stocks",
        "Total stocks",
    ]
].rename(
    columns={
        "Government stocks": "n_obs_government",
        "Industry stocks": "n_obs_industry",
        "Total stocks": "n_obs_total",
    }
)
display(Markdown(
    f"**IEA stock panel:** {len(show)} countries · "
    f"SPR/gov: {int(show['has_government_spr'].sum())} · "
    f"Industry: {int(show['has_industry'].sum())} · "
    f"Total: {int(show['has_total'].sum())}"
))
display(show)

display(Markdown("### JODI stock concept (no SPR split)"))
jodi_stk = jodi["countries"][
    ["iso2", "jodi_name", "has_clostlv_products", "has_clostlv_crude"]
]
display(Markdown(
    f"Secondary CLOSTLV: {int(jodi_stk['has_clostlv_products'].sum())} · "
    f"Primary CLOSTLV: {int(jodi_stk['has_clostlv_crude'].sum())}"
))
display(jodi_stk.loc[jodi_stk["has_clostlv_products"] | jodi_stk["has_clostlv_crude"]].head(20))
print("…", int((jodi_stk["has_clostlv_products"] | jodi_stk["has_clostlv_crude"]).sum()), "countries with any CLOSTLV (showing first 20)")
'''
    ),
    md(
        """## 4. Demand & balances availability

- **IEA demand:** `OECDDEM` (monthly/quarterly/annual product detail) vs `NOECDDEM` (mostly Q/A, Oil products).
- **JODI demand:** secondary `TOTDEMO` monthly by product.
- **Balances:** IEA MOS crude/product flows vs JODI primary/secondary flows.
"""
    ),
    code(
        r'''meta_i, meta_j = iea["meta"], jodi["meta"]

display(Markdown("### IEA demand products / frequency"))
print("OECDDEM freq:", meta_i["oecd_demand_freq"], "| products:", len(meta_i["oecd_demand_products"]))
print(meta_i["oecd_demand_products"])
print("NOECDDEM freq:", meta_i["noecd_demand_freq"], "| products:", meta_i["noecd_demand_products"])

display(Markdown("### JODI secondary products / flows"))
print("date range:", meta_j["date_min"], "→", meta_j["date_max"])
print("products:", meta_j["secondary_products"])
print("flows:", meta_j["secondary_flows"])
print("primary flows:", meta_j["primary_flows"])

display(Markdown("### IEA balance flows (product)"))
display(pd.DataFrame(meta_i["product_balance_flows"]))
display(Markdown("### IEA balance flows (crude)"))
display(pd.DataFrame(meta_i["crude_balance_flows"]))

display(Markdown("### Suggested concept joins (for Phase 2)"))
joins = pd.DataFrame(
    [
        {"theme": "Product demand", "iea": "OECDDEM OBS_VALUE (KBD) / MOSPRODBAL GRDEL_INLAND_OBS", "jodi": "secondary TOTDEMO (KBD)"},
        {"theme": "Product stocks (total)", "iea": "MOSSTOCKS Total stocks / CSNATTER", "jodi": "secondary CLOSTLV"},
        {"theme": "SPR / government stocks", "iea": "MOSSTOCKS Government / CSGOV", "jodi": "(none)"},
        {"theme": "Commercial / industry stocks", "iea": "MOSSTOCKS Industry stocks", "jodi": "(none — CLOSTLV mixes)"},
        {"theme": "Crude stocks", "iea": "MOSSTOCKS Crude oil + CS* on crude bal", "jodi": "primary CLOSTLV"},
        {"theme": "Refinery activity", "iea": "MOSCRUDBAL REFININT_OBS", "jodi": "primary REFINOBS"},
    ]
)
display(joins)
'''
    ),
    md(
        """## 5. Countries your scraper is missing vs each source

National scrapers = enabled entries in `config/countries.yaml`.
"""
    ),
    code(
        r'''miss_iea = gaps["missing_vs_iea"]
miss_jodi = gaps["missing_vs_jodi"]
miss_either = gaps["missing_vs_either"]

display(Markdown(
    f"### Missing vs IEA ({len(miss_iea)} countries) — in IEA, not scraped"
))
display(miss_iea)

display(Markdown(
    f"### Missing vs JODI ({len(miss_jodi)} countries) — in JODI, not scraped"
))
display(miss_jodi)

display(Markdown(
    f"### Missing vs either source ({len(miss_either)}) — priority candidates flagged"
))
display(miss_either)

display(Markdown("### Priority candidates (large / liquid markets, not yet scraped)"))
prio = miss_either.loc[miss_either["priority_candidate"]].copy()
display(prio)
display(Markdown(
    f"Scraped today: **{len(scrapers)}** · "
    f"IEA gap: **{len(miss_iea)}** · "
    f"JODI gap: **{len(miss_jodi)}**"
))
'''
    ),
    md(
        """## 6. Phase 2 — quantitative overlap + Tableau export

Aligned on explicit **compare buckets** (apples-to-apples recipes):

- Demand diesel: IEA **Gas/diesel oil only** (not Auto+Heating children) ↔ JODI `GASDIES`
- Stocks middle distillates: IEA **Middle distillates** ↔ JODI `GASDIES + KEROSENE`
- Detail / aggregate IEA lines kept with `compare_role` ≠ `primary` (excluded from default charts)

**Primary Tableau file:** `data/processed/iea_jodi_profile/iea_jodi_tableau.csv`

Filter Tableau / explorer with `compare_role = primary` and inventory `stock_category = Total stocks`.
"""
    ),
    code(
        r'''from analytics.iea_jodi_overlap import (
    build_overlap_panels,
    build_overlap_stats,
    compare_bucket_rules_table,
    export_tableau_csv,
)

display(Markdown("### Compare-bucket mapping rules"))
display(compare_bucket_rules_table())

# US/UK Excel defaults: sep=',', decimal='.'
paths = export_tableau_csv(ROOT)
panels = build_overlap_panels(ROOT)
combined = panels["combined"]
stats = build_overlap_stats(combined)

display(Markdown("### Export paths"))
for k, p in paths.items():
    print(f"  {k}: {p.relative_to(ROOT)}")

sample_line = paths["wide"].read_text(encoding="utf-8").splitlines()[1]
print("sample row:", sample_line[:180], "...")

primary = combined.loc[combined["compare_role"].eq("primary")]
display(Markdown(
    f"**Overlap rows:** {len(combined):,} · "
    f"primary: {len(primary):,} · "
    f"both sources (primary): {int(primary['has_both'].sum()):,} · "
    f"stats series: {len(stats):,}"
))

display(Markdown("### Overlap stats — primary demand (worst |median % diff|)"))
show_stats = (
    stats.loc[stats["theme"].eq("demand") & stats["frequency"].eq("M") & stats["compare_role"].eq("primary")]
    .assign(abs_med=lambda d: d["median_pct_diff"].abs())
    .sort_values("abs_med", ascending=False)
    .head(15)
)
display(show_stats.drop(columns=["abs_med"], errors="ignore"))

display(Markdown("### DE sanity — gasoil demand + middle distillate stocks"))
for bucket, theme, stock_cat in (
    ("gasoil_diesel", "demand", None),
    ("middle_distillates", "inventory", "Total stocks"),
):
    q = combined.loc[
        (combined["iso2"] == "DE")
        & (combined["compare_bucket"] == bucket)
        & (combined["theme"] == theme)
        & (combined["has_both"])
    ]
    if stock_cat:
        q = q.loc[q["stock_category"] == stock_cat]
    print(bucket, "median pct_diff", round(float(q["pct_diff"].median()), 2) if len(q) else "n/a", "n=", len(q))
    display(q[["date", "iea_value", "jodi_value", "diff", "pct_diff", "iea_components", "jodi_components"]].tail(3))
'''
    ),
    md(
        """## 7. Interactive explorer — filter and chart IEA vs JODI

Use the widgets below to pick **countries**, **theme**, **products**, **stock category**
(inventory), **frequency**, **measure**, and a **date range**. The Plotly chart updates
when filters change.

Requires Section 6 (`combined` overlap panel). Re-run this cell only once per session
to avoid duplicate widgets.
"""
    ),
    code(
        r'''from analytics.iea_jodi_overlap import make_iea_jodi_explorer

# Uses `combined` from Section 6. If you skipped export, rebuild panels:
if "combined" not in globals():
    from analytics.iea_jodi_overlap import build_overlap_panels
    combined = build_overlap_panels(ROOT)["combined"]
    print("rebuilt combined from build_overlap_panels()")

make_iea_jodi_explorer(combined)
'''
    ),
    md(
        """## 8. Takeaways for the nowcast (Phase 3)

IEA is an **occasional benchmark only** (paywall). Day-to-day nowcast:

1. **Demand backbone:** JODI `TOTDEMO` + national scrapers as early prints  
2. **POC implemented:** `notebooks/29_demand_nowcast_poc.ipynb` (DE/JP/KR/AU × gasoline & gasoil)  
3. **Inventories later:** national CLOSTLV → JODI (still no IEA dependency)  
4. **Tableau nowcast file:** `data/processed/demand_nowcast/demand_nowcast_poc_tableau.csv`
"""
    ),
    code(
        r'''# Optional CSV export of Phase 1 gap tables
EXPORT_GAPS = False

if EXPORT_GAPS:
    out = ROOT / "data" / "processed" / "iea_jodi_profile"
    out.mkdir(parents=True, exist_ok=True)
    summary.to_csv(out / "coverage_summary.csv", index=False)
    gaps["missing_vs_iea"].to_csv(out / "missing_vs_iea.csv", index=False)
    gaps["missing_vs_jodi"].to_csv(out / "missing_vs_jodi.csv", index=False)
    gaps["missing_vs_either"].to_csv(out / "missing_vs_either.csv", index=False)
    iea["inventory_disaggregation"].to_csv(out / "iea_inventory_disaggregation.csv", index=False)
    print("wrote gap tables to", out)
else:
    print("Phase 2 Tableau CSV already written by export_tableau_csv() above.")
'''
    ),
]


for i, c in enumerate(cells):
    c["id"] = f"c{i:02d}"

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
    "cells": cells,
}

OUT.write_text(json.dumps(nb, indent=1), encoding="utf-8")
print(f"wrote {OUT.relative_to(ROOT)}")
