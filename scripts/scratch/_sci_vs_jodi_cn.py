"""One-off: SCI China consumption vs JODI CN TOTDEMO. Not a pipeline."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from analytics.units import convert_series

ROOT = Path(__file__).resolve().parents[2]
SCI = Path(r"c:\Users\luiscarlos.gaitan\OneDrive - Jain Global\Coding\sci_api\data\cache\20260911")
OUT = ROOT / "scripts" / "scratch" / "_sci_jodi_cn_compare.json"

KIND = {
    "Gasoline": "gasoline",
    "Diesel": "diesel",
    "Kerosene": "kerosene",
    "Naphtha": "naphtha",
    "Residue": "fuel_oil",
    "VGO": "other",
    "Jet fuel (total)": "jet",
    "Jet fuel (domestic)": "jet",
    "Jet fuel (international)": "jet",
}


def sci_kbd() -> pd.DataFrame:
    cons = pd.read_parquet(SCI / "consumption_national.parquet")
    jet = pd.read_parquet(SCI / "kerosene_refueling_national.parquet")
    sci = pd.concat([cons, jet], ignore_index=True)
    sci["date"] = pd.to_datetime(dict(year=sci["year"], month=sci["month"], day=1))
    sci["kind"] = sci["product"].map(KIND)
    sci = sci[sci["kind"].notna()].copy()
    sci["sci_kbd"] = convert_series(
        sci["consumption_kt"], "kt", "kbd", product_kind=sci["kind"], date=sci["date"]
    )
    return sci


def jodi_cn_kbd() -> pd.DataFrame:
    raw = pd.read_parquet(ROOT / "data" / "processed" / "jodi" / "jodi_secondary.parquet")
    raw = raw[
        (raw["ref_area"].astype(str) == "CN")
        & (raw["flow_breakdown"].astype(str) == "TOTDEMO")
        & (raw["unit_measure"].astype(str) == "KBD")
        & raw["obs_value"].notna()
    ].copy()
    raw["date"] = pd.to_datetime(raw["date"])
    raw["energy_product"] = raw["energy_product"].astype(str)
    # Prefer official (1) then estimate (2) then white-but-numeric (3).
    raw = raw.sort_values(["date", "energy_product", "assessment_code"])
    return raw.drop_duplicates(["date", "energy_product"], keep="first")


def pair_frame(sci: pd.DataFrame, jodi: pd.DataFrame, sci_p: str, jodi_p: str) -> pd.DataFrame:
    a = sci[sci["product"] == sci_p][["date", "sci_kbd"]]
    b = jodi[jodi["energy_product"] == jodi_p][["date", "obs_value"]].rename(
        columns={"obs_value": "jodi_kbd"}
    )
    m = a.merge(b, on="date", how="inner").dropna()
    if m.empty:
        return m
    m["pct"] = (m["sci_kbd"] - m["jodi_kbd"]) / m["jodi_kbd"] * 100
    return m


def summarize(m: pd.DataFrame) -> dict:
    return {
        "n": int(len(m)),
        "start": m["date"].min().strftime("%Y-%m"),
        "end": m["date"].max().strftime("%Y-%m"),
        "sci_med": round(float(m["sci_kbd"].median()), 1),
        "jodi_med": round(float(m["jodi_kbd"].median()), 1),
        "med_pct": round(float(m["pct"].median()), 1),
        "p25_pct": round(float(m["pct"].quantile(0.25)), 1),
        "p75_pct": round(float(m["pct"].quantile(0.75)), 1),
        "corr": round(float(m["sci_kbd"].corr(m["jodi_kbd"])), 3),
        "latest_date": m["date"].max().strftime("%Y-%m"),
        "latest_sci": round(float(m.loc[m["date"].idxmax(), "sci_kbd"]), 1),
        "latest_jodi": round(float(m.loc[m["date"].idxmax(), "jodi_kbd"]), 1),
        "latest_pct": round(float(m.loc[m["date"].idxmax(), "pct"]), 1),
    }


def to_series(m: pd.DataFrame) -> list[dict]:
    return [
        {
            "date": d.strftime("%Y-%m"),
            "sci_kbd": round(float(s), 1),
            "jodi_kbd": round(float(j), 1),
        }
        for d, s, j in zip(m["date"], m["sci_kbd"], m["jodi_kbd"])
    ]


def sci_sum(sci: pd.DataFrame, products: list[str]) -> pd.DataFrame:
    return sci[sci["product"].isin(products)].groupby("date", as_index=False)["sci_kbd"].sum()


def jodi_sum(jodi: pd.DataFrame, products: list[str]) -> pd.DataFrame:
    return (
        jodi[jodi["energy_product"].isin(products)]
        .groupby("date", as_index=False)["obs_value"]
        .sum()
        .rename(columns={"obs_value": "jodi_kbd"})
    )


def main() -> None:
    sci = sci_kbd()
    jodi = jodi_cn_kbd()

    k = sci[sci["product"] == "Kerosene"][["date", "consumption_kt", "sci_kbd"]].rename(
        columns={"consumption_kt": "kero_kt", "sci_kbd": "kero_kbd"}
    )
    d = sci[sci["product"] == "Jet fuel (domestic)"][["date", "consumption_kt", "sci_kbd"]].rename(
        columns={"consumption_kt": "dom_kt", "sci_kbd": "dom_kbd"}
    )
    t = sci[sci["product"] == "Jet fuel (total)"][["date", "consumption_kt", "sci_kbd"]].rename(
        columns={"consumption_kt": "tot_kt", "sci_kbd": "tot_kbd"}
    )
    i = sci[sci["product"] == "Jet fuel (international)"][
        ["date", "consumption_kt", "sci_kbd"]
    ].rename(columns={"consumption_kt": "intl_kt", "sci_kbd": "intl_kbd"})
    ident = k.merge(d, on="date").merge(t, on="date").merge(i, on="date")
    ident["kero_over_dom"] = ident["kero_kt"] / ident["dom_kt"]
    ident["kero_over_tot"] = ident["kero_kt"] / ident["tot_kt"]
    ident["year"] = ident["date"].dt.year

    print("JETKERO rows", int((jodi["energy_product"] == "JETKERO").sum()))
    print("=== SCI kerosene vs jet ===")
    print(ident.groupby("year")[["kero_over_dom", "kero_over_tot"]].median().round(3).to_string())
    near_dom = int((ident["kero_over_dom"].sub(1).abs() < 0.05).sum())
    near_tot = int((ident["kero_over_tot"].sub(1).abs() < 0.05).sum())
    print(f"kero ~ domestic jet (±5%): {near_dom}/{len(ident)}")
    print(f"kero ~ jet total (±5%): {near_tot}/{len(ident)}")

    pairs = [
        ("Gasoline", "GASOLINE"),
        ("Diesel", "GASDIES"),
        ("Naphtha", "NAPHTHA"),
        ("Residue", "RESFUEL"),
        ("Kerosene", "KEROSENE"),
        ("Jet fuel (total)", "KEROSENE"),
        ("Jet fuel (domestic)", "KEROSENE"),
        ("VGO", "ONONSPEC"),
    ]
    pair_out = []
    pair_series = {}
    print("=== pairs ===")
    for sp, jp in pairs:
        m = pair_frame(sci, jodi, sp, jp)
        if m.empty:
            print(sp, "vs", jp, "NO OVERLAP")
            continue
        rec = {"sci": sp, "jodi": jp, **summarize(m)}
        pair_out.append(rec)
        pair_series[f"{sp} vs {jp}"] = to_series(m)
        print(
            f"{sp:22} vs {jp:10} n={rec['n']:3} {rec['start']}..{rec['end']} "
            f"SCI {rec['sci_med']:8.1f} JODI {rec['jodi_med']:8.1f} "
            f"med% {rec['med_pct']:+6.1f} corr {rec['corr']:.3f} "
            f"latest {rec['latest_pct']:+.1f}%"
        )

    basket_specs = [
        (
            "Gasoline+Diesel+Jet total vs GASOLINE+GASDIES+KEROSENE",
            ["Gasoline", "Diesel", "Jet fuel (total)"],
            ["GASOLINE", "GASDIES", "KEROSENE"],
        ),
        (
            "Gasoline+Diesel+Kerosene vs GASOLINE+GASDIES+KEROSENE",
            ["Gasoline", "Diesel", "Kerosene"],
            ["GASOLINE", "GASDIES", "KEROSENE"],
        ),
        (
            "SCI 5 products vs TOTPRODS",
            ["Gasoline", "Diesel", "Kerosene", "Naphtha", "Residue"],
            ["TOTPRODS"],
        ),
        (
            "SCI 5 + VGO vs TOTPRODS",
            ["Gasoline", "Diesel", "Kerosene", "Naphtha", "Residue", "VGO"],
            ["TOTPRODS"],
        ),
        (
            "SCI 5 vs TOTPRODS minus LPG",
            ["Gasoline", "Diesel", "Kerosene", "Naphtha", "Residue"],
            None,
        ),
    ]
    basket_out = []
    basket_series = {}
    print("=== baskets ===")
    for name, sprod, jprod in basket_specs:
        a = sci_sum(sci, sprod)
        if jprod is None:
            tot = jodi_sum(jodi, ["TOTPRODS"])
            lpg = jodi_sum(jodi, ["LPG"]).rename(columns={"jodi_kbd": "lpg"})
            b = tot.merge(lpg, on="date", how="left")
            b["jodi_kbd"] = b["jodi_kbd"] - b["lpg"].fillna(0)
            b = b[["date", "jodi_kbd"]]
        else:
            b = jodi_sum(jodi, jprod)
        m = a.merge(b, on="date", how="inner").dropna()
        m["pct"] = (m["sci_kbd"] - m["jodi_kbd"]) / m["jodi_kbd"] * 100
        rec = {"name": name, **summarize(m)}
        basket_out.append(rec)
        basket_series[name] = to_series(m)
        print(
            f"{name}\n  n={rec['n']} {rec['start']}..{rec['end']} "
            f"SCI {rec['sci_med']} vs JODI {rec['jodi_med']} "
            f"med% {rec['med_pct']:+.1f} corr {rec['corr']:.3f} latest {rec['latest_pct']:+.1f}%"
        )

    ident_series = [
        {
            "date": d.strftime("%Y-%m"),
            "kero_kt": round(float(kero), 1),
            "dom_kt": round(float(dom), 1),
            "tot_kt": round(float(tot), 1),
        }
        for d, kero, dom, tot in zip(ident["date"], ident["kero_kt"], ident["dom_kt"], ident["tot_kt"])
    ]

    payload = {
        "summary": {
            "sci_range": [sci["date"].min().strftime("%Y-%m"), sci["date"].max().strftime("%Y-%m")],
            "jodi_range": [jodi["date"].min().strftime("%Y-%m"), jodi["date"].max().strftime("%Y-%m")],
            "kero_jet": {
                "n": int(len(ident)),
                "near_dom_5pct": near_dom,
                "near_tot_5pct": near_tot,
                "median_kero_over_dom_by_year": {
                    str(int(y)): round(float(v), 3)
                    for y, v in ident.groupby("year")["kero_over_dom"].median().items()
                },
                "median_kero_over_tot_by_year": {
                    str(int(y)): round(float(v), 3)
                    for y, v in ident.groupby("year")["kero_over_tot"].median().items()
                },
            },
            "pairs": pair_out,
            "baskets": basket_out,
        },
        "pair_series": pair_series,
        "basket_series": basket_series,
        "ident_series": ident_series,
    }
    OUT.write_text(json.dumps(payload, default=str), encoding="utf-8")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
