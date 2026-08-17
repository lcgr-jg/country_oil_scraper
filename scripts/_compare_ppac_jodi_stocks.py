"""One-off comparison: PPAC-implied stocks vs JODI (not part of pipeline)."""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import pandas as pd

from analytics.india_inventory import (
    JODI_PRODUCT_LABELS,
    STOCK_PANEL_PRODUCTS,
    build_ppac_closing_stocks_summary,
    build_probe_tables,
    coerce_numeric_columns,
    implied_stock_change,
)

t = build_probe_tables(ROOT, anchor="2026-02")
merged = t["merged"]
jodi = coerce_numeric_columns(t["jodi_wide"])

m = merged[merged["jodi_product"].isin(STOCK_PANEL_PRODUCTS)].copy()
m = m[m["ppac_demand"].notna() & m["ppac_refgrout"].notna()].copy()
m["implied_ppac"] = implied_stock_change(m, demand_col="ppac_demand")
m["implied_jodi_dem"] = implied_stock_change(m, demand_col="TOTDEMO")
recent = m[m["TIME_PERIOD"] >= "2025-01"].copy()

print("=== Monthly STOCKCH: PPAC-implied vs JODI reported (kt) ===")
print("Panel products summed by month")
by_m = recent.groupby("TIME_PERIOD", observed=True).agg(
    jodi_STOCKCH=("STOCKCH", "sum"),
    implied_ppac=("implied_ppac", "sum"),
    implied_jodi_dem=("implied_jodi_dem", "sum"),
).round(0)
by_m["gap_ppac_minus_jodi"] = by_m["implied_ppac"] - by_m["jodi_STOCKCH"]
by_m["gap_pct"] = (
    100
    * by_m["gap_ppac_minus_jodi"]
    / by_m["jodi_STOCKCH"].replace(0, np.nan)
).round(1)
print(by_m.tail(16).to_string())
print()

ppac = build_ppac_closing_stocks_summary(ROOT, jodi, anchor="2026-02")
levels = ppac["estimated_levels"]
jstk = jodi[jodi["jodi_product"].isin(STOCK_PANEL_PRODUCTS)][
    ["TIME_PERIOD", "jodi_product", "CLOSTLV", "STOCKCH"]
]

mar = levels[levels["date"] == "2026-03-01"].merge(
    jstk[jstk["TIME_PERIOD"] == pd.Period("2026-03")],
    on="jodi_product",
    how="outer",
)
mar["level_gap"] = mar["estimated_CLOSTLV"] - mar["CLOSTLV"]
mar["label"] = mar["jodi_product"].map(JODI_PRODUCT_LABELS)

print("=== Mar 2026 levels (Feb JODI anchor + PPAC flows) vs JODI CLOSTLV ===")
cols = [
    "label",
    "estimated_CLOSTLV",
    "CLOSTLV",
    "level_gap",
    "implied_STOCKCH_ppac",
    "STOCKCH",
]
print(
    mar[cols]
    .dropna(subset=["CLOSTLV"])
    .round(1)
    .sort_values("level_gap")
    .to_string(index=False)
)
est_sum = mar["estimated_CLOSTLV"].sum()
jodi_sum = mar["CLOSTLV"].sum()
print(
    f"Panel sum est: {est_sum:.0f}  JODI sum: {jodi_sum:.0f}  gap: {est_sum - jodi_sum:.0f} kt"
)
print()

feb = jstk[jstk["TIME_PERIOD"] == pd.Period("2026-02")].set_index("jodi_product")[
    "CLOSTLV"
]
mar_l = jstk[jstk["TIME_PERIOD"] == pd.Period("2026-03")].set_index("jodi_product")[
    "CLOSTLV"
]
jodi_chg = mar_l - feb
ppac_chg = (
    recent[recent["TIME_PERIOD"] == pd.Period("2026-03")]
    .groupby("jodi_product")["implied_ppac"]
    .sum()
)
cmp = pd.DataFrame({"jodi_level_chg": jodi_chg, "ppac_implied_chg": ppac_chg})
cmp["gap"] = cmp["ppac_implied_chg"] - cmp["jodi_level_chg"]
print("=== Feb->Mar change: PPAC implied flow vs JODI level delta ===")
print(cmp.round(1).sort_values("gap").to_string())
print(
    f"Panel sum — PPAC implied: {cmp['ppac_implied_chg'].sum():.0f}  "
    f"JODI levels: {cmp['jodi_level_chg'].sum():.0f}  gap: {cmp['gap'].sum():.0f} kt"
)
print()

apr = recent[recent["TIME_PERIOD"] == pd.Period("2026-04")]
print("=== Apr 2026 PPAC-implied panel STOCKCH sum ===", round(apr["implied_ppac"].sum(), 0))
print()

hist = m[(m["TIME_PERIOD"] >= "2023-01") & (m["TIME_PERIOD"] <= "2026-03")].copy()
hist["flow_gap"] = hist["implied_ppac"] - hist["STOCKCH"]
by_prod = hist.groupby("jodi_product")["flow_gap"].agg(["mean", "std", "count"])
by_prod["mae"] = hist.groupby("jodi_product", observed=True).apply(
    lambda g: g["flow_gap"].abs().mean(), include_groups=False
)
by_prod["label"] = by_prod.index.map(JODI_PRODUCT_LABELS.get)
print("=== 2023-01 to 2026-03 monthly flow gap (PPAC implied - JODI STOCKCH) ===")
print(by_prod[["label", "mean", "std", "mae"]].round(1).sort_values("mae", ascending=False))
monthly_gap = (
    hist.groupby("TIME_PERIOD")["implied_ppac"].sum()
    - hist.groupby("TIME_PERIOD")["STOCKCH"].sum()
)
print("Panel-sum monthly |gap| MAE:", round(monthly_gap.abs().mean(), 0), "kt")
print()

tot = jodi[jodi["jodi_product"] == "TOTPRODS"][["TIME_PERIOD", "CLOSTLV", "STOCKCH"]]
for p in ["2026-02", "2026-03"]:
    row = tot[tot["TIME_PERIOD"] == pd.Period(p)]
    if len(row):
        print(f"TOTPRODS {p}: CLOSTLV={row.CLOSTLV.iloc[0]:.0f}")
chg = (
    tot[tot["TIME_PERIOD"] == pd.Period("2026-03")].CLOSTLV.iloc[0]
    - tot[tot["TIME_PERIOD"] == pd.Period("2026-02")].CLOSTLV.iloc[0]
)
print(f"TOTPRODS Feb->Mar level change: {chg:.0f} kt")
print(f"Panel sum PPAC implied Mar flow: {cmp['ppac_implied_chg'].sum():.0f} kt")

# refgrout source for Mar
panel = ppac["ppac_panel"]
mar_ref = panel[panel["TIME_PERIOD"] == pd.Period("2026-03")][
    ["jodi_product", "refgrout_source", "ppac_refgrout"]
]
print("\nMar refgrout source:", mar_ref.groupby("refgrout_source", observed=True).size().to_dict())
