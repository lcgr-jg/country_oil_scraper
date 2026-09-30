"""
Eurostat nrg_cb_oilm spike: DE/FR/NL levels, DE vs BAFA, freshness vs warehouse.

Writes scripts/scratch/_eurostat_oilm_spike.json for the canvas.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analytics.core.loader import load_official_demand  # noqa: E402
from analytics.units import convert_series  # noqa: E402
from reference.eurostat_oilm import (  # noqa: E402
    DE_BAFA_COMPARE,
    SPIKE_SIEC,
    WAREHOUSE_GEO,
    fetch_gid_obs_geos,
    latest_month_by_geo,
)
from warehouse.registry import list_countries  # noqa: E402

OUT = Path(__file__).with_name("_eurostat_oilm_spike.json")

SPIKE_GEOS = ("DE", "FR", "NL")
# Geos we try for freshness (warehouse overlap + FR/NL gap-fill targets).
FRESHNESS_GEOS = ("DE", "FR", "NL", "ES", "IT", "PL", "PT", "HU", "NO", "BE", "AT", "SE")


def _quarter_series(df: pd.DataFrame, siec: str, geo: str) -> list[dict]:
    sl = df[(df["geo"] == geo) & (df["siec"] == siec) & (df["date"] >= "2020-01-01")].copy()
    if sl.empty:
        return []
    sl = sl.dropna(subset=["value_kbd"]).sort_values("date")
    # Keep chart payload small: month-end points since 2022.
    sl = sl[sl["date"] >= "2022-01-01"]
    return [
        {"date": r.date.strftime("%Y-%m"), "kbd": round(float(r.value_kbd), 1)}
        for r in sl.itertuples()
    ]


def attach_kbd(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    kind = out["product_kind"].fillna("other")
    out["value_kbd"] = convert_series(
        out["value_ths_t"], "kt", "kbd", product_kind=kind, date=out["date"]
    )
    return out


def bafa_compare(es: pd.DataFrame) -> list[dict]:
    dem = load_official_demand("germany").copy()
    dem["date"] = pd.to_datetime(dem["date"]).dt.to_period("M").dt.to_timestamp()
    rows = []
    de = es[es["geo"] == "DE"]
    for siec, natives in DE_BAFA_COMPARE.items():
        if siec not in SPIKE_SIEC:
            continue
        a = de[de["siec"] == siec][["date", "value_ths_t", "value_kbd"]].rename(
            columns={"value_ths_t": "es_kt", "value_kbd": "es_kbd"}
        )
        b = (
            dem[dem["product_native"].isin(natives)]
            .groupby("date", as_index=False)
            .agg(bafa_t=("value_native", "sum"), bafa_kbd=("value_kbd", "sum"))
        )
        b["bafa_kt"] = b["bafa_t"] / 1000.0
        m = a.merge(b, on="date").dropna()
        m = m[m["date"] >= "2020-01-01"]
        if m.empty:
            continue
        pct = 100.0 * (m["bafa_kt"] - m["es_kt"]) / m["es_kt"]
        # chart: quarterly downsample since 2022
        chart = m[m["date"] >= "2022-01-01"].copy()
        chart_pts = [
            {
                "date": r.date.strftime("%Y-%m"),
                "eurostat_kbd": round(float(r.es_kbd), 1),
                "bafa_kbd": round(float(r.bafa_kbd), 1),
            }
            for r in chart.itertuples()
        ]
        rows.append(
            {
                "siec": siec,
                "label": de.loc[de["siec"] == siec, "siec_label"].iloc[0]
                if (de["siec"] == siec).any()
                else siec,
                "bafa_natives": sorted(natives),
                "n": int(len(m)),
                "start": m["date"].min().strftime("%Y-%m"),
                "end": m["date"].max().strftime("%Y-%m"),
                "med_pct": round(float(pct.median()), 1),
                "corr": round(float(m["bafa_kt"].corr(m["es_kt"])), 3),
                "es_med_kbd": round(float(m["es_kbd"].median()), 1),
                "bafa_med_kbd": round(float(m["bafa_kbd"].median()), 1),
                "chart": chart_pts,
            }
        )
    return rows


def warehouse_freshness() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for cfg in list_countries(enabled_only=True):
        geo = WAREHOUSE_GEO.get(cfg.country_id)
        dem = load_official_demand(cfg.country_id)
        if dem.empty:
            continue
        latest = pd.to_datetime(dem["date"]).max()
        out[cfg.country_id] = {
            "display_name": cfg.display_name,
            "official_source": cfg.official_source_label,
            "geo": geo,
            "latest_month": latest.strftime("%Y-%m"),
            "latest_date": latest.strftime("%Y-%m-%d"),
            "n_rows": int(len(dem)),
        }
    return out


def main() -> None:
    print("Fetching Eurostat GID_OBS for", FRESHNESS_GEOS)
    es_raw = fetch_gid_obs_geos(FRESHNESS_GEOS, start="2018-01")
    es = attach_kbd(es_raw)
    es_spike = es[es["siec"].isin(SPIKE_SIEC)].copy()

    es_latest = latest_month_by_geo(es)
    wh = warehouse_freshness()

    # Freshness join table
    freshness_rows = []
    es_by_geo = {r["geo"]: r for r in es_latest.to_dict("records")}
    for geo in FRESHNESS_GEOS:
        es_row = es_by_geo.get(geo, {})
        # warehouse countries that map to this geo
        wh_matches = [v for v in wh.values() if v.get("geo") == geo]
        wh_latest = max((w["latest_month"] for w in wh_matches), default=None)
        wh_src = ", ".join(f"{w['official_source']}" for w in wh_matches) or None
        es_m = es_row.get("latest_month")
        lead = None
        if es_m and wh_latest:
            lead = "eurostat" if es_m > wh_latest else ("official" if wh_latest > es_m else "tie")
        elif es_m and not wh_latest:
            lead = "eurostat_only"
        freshness_rows.append(
            {
                "geo": geo,
                "eurostat_latest": es_m,
                "warehouse_latest": wh_latest,
                "warehouse_source": wh_src,
                "lead": lead,
            }
        )

    # Latest levels for FR/NL/DE spike basket
    levels = []
    for geo in SPIKE_GEOS:
        sub = es_spike[es_spike["geo"] == geo].dropna(subset=["value_kbd"])
        if sub.empty:
            continue
        latest = sub["date"].max()
        snap = sub[sub["date"] == latest]
        for r in snap.itertuples():
            levels.append(
                {
                    "geo": geo,
                    "month": latest.strftime("%Y-%m"),
                    "siec": r.siec,
                    "label": r.siec_label,
                    "canonical": r.product_canonical,
                    "kbd": round(float(r.value_kbd), 1),
                    "kt": round(float(r.value_ths_t), 1),
                }
            )

    # Small multi-country gasoline/diesel charts
    charts = {}
    for siec, key in (("O4652", "gasoline"), ("O4671", "gas_diesel"), ("O4661", "jet")):
        charts[key] = {
            geo: _quarter_series(es_spike, siec, geo) for geo in SPIKE_GEOS
        }

    payload = {
        "generated": pd.Timestamp.utcnow().isoformat(),
        "dataset": "nrg_cb_oilm",
        "balance": "GID_OBS",
        "unit_native": "THS_T",
        "product_map": [
            {
                "siec": s.siec,
                "label": s.label,
                "product_canonical": s.product_canonical,
                "product_kind": s.product_kind,
            }
            for s in __import__("reference.eurostat_oilm", fromlist=["series_specs"]).series_specs()
        ],
        "de_bafa_compare": bafa_compare(es_spike),
        "freshness": freshness_rows,
        "warehouse_freshness": wh,
        "latest_levels": levels,
        "charts": charts,
        "eurostat_coverage_geos": sorted(es["geo"].dropna().unique().tolist()),
    }
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print("Wrote", OUT)
    print("Eurostat latest by geo:")
    print(es_latest.to_string(index=False))
    print("\nFreshness lead counts:", pd.Series([r["lead"] for r in freshness_rows]).value_counts().to_dict())
    for row in payload["de_bafa_compare"]:
        print(
            f"DE {row['siec']} {row['label']}: med%={row['med_pct']} corr={row['corr']} "
            f"({row['start']}..{row['end']})"
        )


if __name__ == "__main__":
    main()
