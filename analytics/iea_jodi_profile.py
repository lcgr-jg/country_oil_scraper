"""IEA MOS vs JODI coverage / concept profiling for Phase 1 comparison.

Read-only helpers used by ``notebooks/28_iea_vs_jodi_comparison.ipynb``.
No warehouse writes — profiles raw IEA CSVs and processed JODI parquets.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd
import yaml

# ---------------------------------------------------------------------------
# IEA COUNTRY codes → ISO alpha-2 (JODI REF_AREA). Aggregates omitted.
# ---------------------------------------------------------------------------

IEA_OECD_ISO: dict[str, str] = {
    "AUSTRALIA": "AU",
    "AUSTRIA": "AT",
    "BELGIUM": "BE",
    "CANADA": "CA",
    "CHILE": "CL",
    "CZECH": "CZ",
    "DENMARK": "DK",
    "ESTONIA": "EE",
    "FINLAND": "FI",
    "FRANCE": "FR",
    "GERMANY": "DE",
    "GREECE": "GR",
    "HUNGARY": "HU",
    "ICELAND": "IS",
    "IRELAND": "IE",
    "ISRAEL": "IL",
    "ITALY": "IT",
    "JAPAN": "JP",
    "KOREA": "KR",
    "LATVIA": "LV",
    "LITHUANIA": "LT",
    "LUXEMBOURG": "LU",
    "MEXICO": "MX",
    "NETHERLANDS": "NL",
    "NEWZEALAND": "NZ",
    "NORWAY": "NO",
    "POLAND": "PL",
    "PORTUGAL": "PT",
    "SLOVAKIA": "SK",
    "SLOVENIA": "SI",
    "SPAIN": "ES",
    "SWEDEN": "SE",
    "SWITZERLAND": "CH",
    "TURKIYE": "TR",
    "UK": "GB",
    "USA": "US",
}

IEA_NONOECD_ISO: dict[str, str] = {
    "ALBANIA": "AL",
    "ALGERIA": "DZ",
    "ANGOLA": "AO",
    "ARGENTINA": "AR",
    "ARMENIA": "AM",
    "AZERBAIJAN": "AZ",
    "BAHRAIN": "BH",
    "BANGLADESH": "BD",
    "BELARUS": "BY",
    "BENIN": "BJ",
    "BOLIVIA": "BO",
    "BOSNIAHERZ": "BA",
    "BRAZIL": "BR",
    "BRUNEI": "BN",
    "BULGARIA": "BG",
    "CAMBODIA": "KH",
    "CAMEROON": "CM",
    "CHINA": "CN",
    "COLOMBIA": "CO",
    "CONGO_DRC": "CD",
    "CONGO_REPUB": "CG",
    "COSTARICA": "CR",
    "COTEIVOIRE": "CI",
    "CROATIA": "HR",
    "CUBA": "CU",
    "CURACAO": "CW",
    "CYPRUS": "CY",
    "DOMINICANREP": "DO",
    "ECUADOR": "EC",
    "EGYPT": "EG",
    "ELSALVADOR": "SV",
    "ETHIOPIA": "ET",
    "GABON": "GA",
    "GEORGIA": "GE",
    "GHANA": "GH",
    "GIBRALTAR": "GI",
    "GUATEMALA": "GT",
    "HAITI": "HT",
    "HONDURAS": "HN",
    "HONGKONG": "HK",
    "INDIA": "IN",
    "INDONESIA": "ID",
    "IRAN": "IR",
    "IRAQ": "IQ",
    "JAMAICA": "JM",
    "JORDAN": "JO",
    "KAZAKHSTAN": "KZ",
    "KENYA": "KE",
    "KOREADPR": "KP",
    "KOSOVO": "XK",
    "KUWAIT": "KW",
    "KYRGYZSTAN": "KG",
    "LEBANON": "LB",
    "LIBYA": "LY",
    "MALAYSIA": "MY",
    "MALTA": "MT",
    "MOLDOVA": "MD",
    "MONGOLIA": "MN",
    "MONTENEGRO": "ME",
    "MOROCCO": "MA",
    "MOZAMBIQUE": "MZ",
    "MYANMAR": "MM",
    "NEPAL": "NP",
    "NICARAGUA": "NI",
    "NIGERIA": "NG",
    "NORTHMACED": "MK",
    "OMAN": "OM",
    "PAKISTAN": "PK",
    "PANAMA": "PA",
    "PARAGUAY": "PY",
    "PERU": "PE",
    "PHILIPPINES": "PH",
    "QATAR": "QA",
    "ROMANIA": "RO",
    "RUSSIA": "RU",
    "SAUDIARABIA": "SA",
    "SENEGAL": "SN",
    "SERBIA": "RS",
    "SINGAPORE": "SG",
    "SOUTHAFRICA": "ZA",
    "SRILANKA": "LK",
    "SSUDAN": "SS",
    "SUDAN": "SD",
    "SURINAME": "SR",
    "SYRIA": "SY",
    "TAIPEI": "TW",
    "TAJIKISTAN": "TJ",
    "TANZANIA": "TZ",
    "THAILAND": "TH",
    "TRINIDAD": "TT",
    "TUNISIA": "TN",
    "TURKMENISTAN": "TM",
    "UAE": "AE",
    "UKRAINE": "UA",
    "URUGUAY": "UY",
    "UZBEKISTAN": "UZ",
    "VENEZUELA": "VE",
    "VIETNAM": "VN",
    "YEMEN": "YE",
    "ZAMBIA": "ZM",
    "ZIMBABWE": "ZW",
}

IEA_ISO: dict[str, str] = {**IEA_OECD_ISO, **IEA_NONOECD_ISO}

# Regional / multi-country labels in IEA dumps — not comparable to ISO countries.
IEA_AGGREGATE_CODES: frozenset[str] = frozenset(
    {
        "OECDAM",
        "OECDAO",
        "OECDEUR",
        "OECDTOT",
        "OECD_G9",
        "OMR_EURO_4",
        "SCANDINAVIA",
        "BENELUX",
        "USA_50",
        "USA_TERRITORIES",
        "OTH_NON_OECDEUR",
        "LATINAMERIC",
        "F_USSR_X_OECD",
        "F_YUGOSLAVIA_X_OECD",
        "NON_OECDAFR",
        "NON_OECDAO_X_CHINA",
        "NON_OECDEUR",
        "NON_OECDME",
        "NON_OECDTOT",
        "OTH_NON_OECDAFR",
        "OTH_NON_OECDAM",
        "OTH_NON_OECDAO",
    }
)

# Concept cheat-sheet for the notebook (static; not derived from files).
CONCEPT_ROWS: list[dict[str, str]] = [
    {
        "theme": "Demand — products",
        "iea": "OECDDEM monthly product detail; NOECDDEM mostly Q/A Oil products only",
        "jodi": "Secondary TOTDEMO monthly by product (~10 products) worldwide",
    },
    {
        "theme": "Demand — crude",
        "iea": "Via MOSCRUDBAL (direct use / refinery intake), not a stand-alone demand file",
        "jodi": "Primary has no TOTDEMO; crude use via DIRECUSE / REFINOBS",
    },
    {
        "theme": "Inventories — level",
        "iea": "MOSSTOCKS (KB) + balance CSGOV / CSNATTER",
        "jodi": "CLOSTLV only (primary crude + secondary products)",
    },
    {
        "theme": "Inventories — SPR vs commercial",
        "iea": "Government stocks (SPR-like) / Industry stocks / Total",
        "jodi": "No split — single national closing stock",
    },
    {
        "theme": "Balances",
        "iea": "MOSCRUDBAL + MOSPRODBAL (+ MOSPRODSPLIT) full flow tables",
        "jodi": "Primary + secondary standardized flows (trade, stocks, STATDIFF, …)",
    },
    {
        "theme": "Geography",
        "iea": "Rich OECD monthly; non-OECD demand thinner / often quarterly",
        "jodi": "~118 monthly reporters; broader emerging-market panel",
    },
    {
        "theme": "Automation in this repo",
        "iea": "Manual CSV drop under data/raw/iea/ (no scraper yet)",
        "jodi": "Full ETL + warehouse + Streamlit apps",
    },
]


def resolve_project_root(cwd: Path | None = None) -> Path:
    """Walk parents until ``data/raw/iea`` or nested ``country_oil_scraper`` is found."""
    here = cwd or Path.cwd()
    for candidate in [here, *here.parents]:
        if (candidate / "data" / "raw" / "iea").is_dir():
            return candidate
        nested = candidate / "country_oil_scraper"
        if (nested / "data" / "raw" / "iea").is_dir():
            return nested
    raise RuntimeError(f"Could not locate country_oil_scraper root from {here}")


def load_scraper_countries(root: Path) -> pd.DataFrame:
    """Enabled national scrapers from ``config/countries.yaml``."""
    path = root / "config" / "countries.yaml"
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    rows = []
    for key, meta in (cfg.get("countries") or {}).items():
        if not meta.get("enabled", True):
            continue
        rows.append(
            {
                "scraper_key": key,
                "display_name": meta.get("display_name", key),
                "iso2": str(meta.get("jodi_ref_area") or meta.get("country_code") or "").upper(),
                "official_source": meta.get("official_source_label", ""),
            }
        )
    out = pd.DataFrame(rows).sort_values("iso2").reset_index(drop=True)
    if out["iso2"].eq("").any():
        missing = out.loc[out["iso2"].eq(""), "scraper_key"].tolist()
        raise ValueError(f"Scraper countries missing ISO/jodi_ref_area: {missing}")
    return out


def _iea_country_frame(
    path: Path,
    *,
    name_col: str,
    code_col: str = "COUNTRY",
) -> pd.DataFrame:
    cols = [code_col, name_col]
    df = pd.read_csv(path, usecols=cols, low_memory=False).drop_duplicates()
    df = df.rename(columns={code_col: "iea_code", name_col: "iea_name"})
    df["iso2"] = df["iea_code"].map(IEA_ISO)
    df["is_aggregate"] = df["iea_code"].isin(IEA_AGGREGATE_CODES) | df["iso2"].isna()
    return df.sort_values("iea_code").reset_index(drop=True)


def profile_iea(root: Path) -> dict[str, pd.DataFrame | dict]:
    """Load lightweight IEA profiles (countries, products, stock categories, flows)."""
    raw = root / "data" / "raw" / "iea"
    stocks = pd.read_csv(
        raw / "MOSSTOCKS.csv",
        usecols=[
            "COUNTRY",
            "Country",
            "Product",
            "STOCKS_CATEGORY",
            "Stock Category",
            "TIME_PERIOD",
            "FREQUENCY",
            "UNIT",
            "OBS_VALUE",
        ],
        low_memory=False,
    )
    oecd_dem = pd.read_csv(
        raw / "OECDDEM.csv",
        usecols=[
            "COUNTRY",
            "Country/Region",
            "Product",
            "FREQUENCY",
            "TIME_PERIOD",
            "UNIT",
        ],
        low_memory=False,
    )
    noecd_dem = pd.read_csv(
        raw / "NOECDDEM.csv",
        usecols=["COUNTRY", "Country", "Product", "FREQUENCY", "TIME_PERIOD", "UNIT"],
        low_memory=False,
    )
    crude_bal = pd.read_csv(
        raw / "MOSCRUDBAL.csv",
        usecols=["COUNTRY", "Country", "Product", "ENERGY_BALANCE_FLOW", "Flow", "FREQUENCY"],
        low_memory=False,
    )
    prod_bal = pd.read_csv(
        raw / "MOSPRODBAL.csv",
        usecols=["COUNTRY", "Country", "Product", "ENERGY_BALANCE_FLOW", "Flow", "FREQUENCY"],
        low_memory=False,
    )

    stock_countries = _iea_country_frame(raw / "MOSSTOCKS.csv", name_col="Country")
    oecd_countries = _iea_country_frame(raw / "OECDDEM.csv", name_col="Country/Region")
    noecd_countries = _iea_country_frame(raw / "NOECDDEM.csv", name_col="Country")
    bal_countries = _iea_country_frame(raw / "MOSCRUDBAL.csv", name_col="Country")

    # Per-country SPR / Industry / Total presence (any non-null OBS_VALUE).
    sc = stocks.copy()
    sc["iso2"] = sc["COUNTRY"].map(IEA_ISO)
    sc = sc.loc[sc["iso2"].notna() & sc["OBS_VALUE"].notna()]
    inv_presence = (
        sc.groupby(["iso2", "COUNTRY", "Country", "STOCKS_CATEGORY", "Stock Category"], as_index=False)
        .agg(n_obs=("OBS_VALUE", "size"), last_period=("TIME_PERIOD", "max"))
    )
    inv_wide = (
        inv_presence.pivot_table(
            index=["iso2", "Country"],
            columns="Stock Category",
            values="n_obs",
            aggfunc="sum",
            fill_value=0,
        )
        .reset_index()
    )
    for col in ("Government stocks", "Industry stocks", "Total stocks"):
        if col not in inv_wide.columns:
            inv_wide[col] = 0
    inv_wide["has_government_spr"] = inv_wide["Government stocks"] > 0
    inv_wide["has_industry"] = inv_wide["Industry stocks"] > 0
    inv_wide["has_total"] = inv_wide["Total stocks"] > 0

    # Demand countries: OECD monthly product + non-OECD (any freq).
    dem_oecd = oecd_countries.loc[~oecd_countries["is_aggregate"]].copy()
    dem_oecd["dataset"] = "OECDDEM"
    dem_oecd["monthly_product_detail"] = True
    dem_noecd = noecd_countries.loc[~noecd_countries["is_aggregate"]].copy()
    dem_noecd["dataset"] = "NOECDDEM"
    dem_noecd["monthly_product_detail"] = False
    demand_countries = pd.concat([dem_oecd, dem_noecd], ignore_index=True)

    # Union of all mappable IEA country codes across demand + stocks + balances.
    pieces = []
    for label, frame in (
        ("stocks", stock_countries),
        ("oecd_demand", oecd_countries),
        ("nonoecd_demand", noecd_countries),
        ("balances", bal_countries),
    ):
        part = frame.loc[~frame["is_aggregate"], ["iso2", "iea_code", "iea_name"]].copy()
        part["in_" + label] = True
        pieces.append(part)
    iea_all = pieces[0]
    for part in pieces[1:]:
        iea_all = iea_all.merge(part, on=["iso2", "iea_code", "iea_name"], how="outer")
    flag_cols = [c for c in iea_all.columns if c.startswith("in_")]
    # Outer merges leave True/NaN — coerce to bool without fillna downcast warnings.
    for col in flag_cols:
        iea_all[col] = iea_all[col].eq(True)
    iea_all = iea_all.sort_values("iso2").reset_index(drop=True)

    meta = {
        "stocks_unit": sorted(stocks["UNIT"].dropna().unique().tolist()),
        "stocks_freq": sorted(stocks["FREQUENCY"].dropna().unique().tolist()),
        "stocks_products": sorted(stocks["Product"].dropna().unique().tolist()),
        "stocks_categories": (
            stocks[["STOCKS_CATEGORY", "Stock Category"]]
            .drop_duplicates()
            .sort_values("STOCKS_CATEGORY")
            .to_dict("records")
        ),
        "oecd_demand_freq": sorted(oecd_dem["FREQUENCY"].dropna().unique().tolist()),
        "oecd_demand_products": sorted(oecd_dem["Product"].dropna().unique().tolist()),
        "noecd_demand_freq": sorted(noecd_dem["FREQUENCY"].dropna().unique().tolist()),
        "noecd_demand_products": sorted(noecd_dem["Product"].dropna().unique().tolist()),
        "crude_balance_flows": (
            crude_bal[["ENERGY_BALANCE_FLOW", "Flow"]]
            .drop_duplicates()
            .sort_values("ENERGY_BALANCE_FLOW")
            .to_dict("records")
        ),
        "product_balance_flows": (
            prod_bal[["ENERGY_BALANCE_FLOW", "Flow"]]
            .drop_duplicates()
            .sort_values("ENERGY_BALANCE_FLOW")
            .to_dict("records")
        ),
        "stocks_period_min": str(stocks["TIME_PERIOD"].min()),
        "stocks_period_max": str(stocks["TIME_PERIOD"].max()),
    }

    return {
        "meta": meta,
        "stock_countries": stock_countries,
        "oecd_demand_countries": oecd_countries,
        "noecd_demand_countries": noecd_countries,
        "balance_countries": bal_countries,
        "inventory_disaggregation": inv_wide.sort_values("iso2").reset_index(drop=True),
        "demand_countries": demand_countries,
        "iea_countries_all": iea_all,
    }


def profile_jodi(root: Path) -> dict[str, pd.DataFrame | dict]:
    """Country / flow / product profile from processed JODI parquets."""
    proc = root / "data" / "processed" / "jodi"
    sec = pd.read_parquet(
        proc / "jodi_secondary.parquet",
        columns=[
            "date",
            "ref_area",
            "country_name",
            "energy_product",
            "flow_breakdown",
            "unit_measure",
            "obs_value",
        ],
    )
    pri = pd.read_parquet(
        proc / "jodi_primary.parquet",
        columns=[
            "date",
            "ref_area",
            "country_name",
            "energy_product",
            "flow_breakdown",
            "unit_measure",
            "obs_value",
        ],
    )

    countries = (
        sec[["ref_area", "country_name"]]
        .drop_duplicates()
        .rename(columns={"ref_area": "iso2", "country_name": "jodi_name"})
        .sort_values("iso2")
        .reset_index(drop=True)
    )

    def _flow_presence(df: pd.DataFrame, flows: Iterable[str]) -> pd.DataFrame:
        # Cast away categoricals — groupby on cats can inflate index length.
        sub = df.loc[df["flow_breakdown"].isin(list(flows)) & df["obs_value"].notna()].copy()
        sub["ref_area"] = sub["ref_area"].astype(str)
        sub["flow_breakdown"] = sub["flow_breakdown"].astype(str)
        out = (
            sub.groupby(["ref_area", "flow_breakdown"], as_index=False, observed=True)
            .agg(n_obs=("obs_value", "size"), last_date=("date", "max"))
        )
        wide = out.pivot_table(
            index="ref_area",
            columns="flow_breakdown",
            values="n_obs",
            aggfunc="sum",
            fill_value=0,
        )
        return wide.reset_index().rename(columns={"ref_area": "iso2"})

    sec_flows = _flow_presence(sec, ["TOTDEMO", "CLOSTLV", "STOCKCH", "REFGROUT", "TOTIMPSB", "TOTEXPSB"])
    pri_flows = _flow_presence(pri, ["CLOSTLV", "STOCKCH", "INDPROD", "REFINOBS", "DIRECUSE", "TOTIMPSB", "TOTEXPSB"])

    # Countries with any secondary demand / stocks.
    has_demand = set(sec.loc[sec["flow_breakdown"].eq("TOTDEMO") & sec["obs_value"].notna(), "ref_area"])
    has_stocks = set(sec.loc[sec["flow_breakdown"].eq("CLOSTLV") & sec["obs_value"].notna(), "ref_area"])
    has_crude_stocks = set(pri.loc[pri["flow_breakdown"].eq("CLOSTLV") & pri["obs_value"].notna(), "ref_area"])
    countries["has_totdemo"] = countries["iso2"].isin(has_demand)
    countries["has_clostlv_products"] = countries["iso2"].isin(has_stocks)
    countries["has_clostlv_crude"] = countries["iso2"].isin(has_crude_stocks)

    meta = {
        "secondary_products": sorted(sec["energy_product"].dropna().unique().tolist()),
        "secondary_flows": sorted(sec["flow_breakdown"].dropna().unique().tolist()),
        "secondary_units": sorted(sec["unit_measure"].dropna().unique().tolist()),
        "primary_products": sorted(pri["energy_product"].dropna().unique().tolist()),
        "primary_flows": sorted(pri["flow_breakdown"].dropna().unique().tolist()),
        "date_min": str(pd.to_datetime(sec["date"]).min().date()),
        "date_max": str(pd.to_datetime(sec["date"]).max().date()),
        "n_countries": int(countries["iso2"].nunique()),
    }
    return {
        "meta": meta,
        "countries": countries,
        "secondary_flow_presence": sec_flows,
        "primary_flow_presence": pri_flows,
    }


def coverage_summary(
    iea: dict,
    jodi: dict,
    scrapers: pd.DataFrame,
) -> pd.DataFrame:
    """High-level counts: IEA vs JODI vs national scrapers."""
    iea_iso = set(iea["iea_countries_all"]["iso2"].dropna())
    jodi_iso = set(jodi["countries"]["iso2"])
    scrape_iso = set(scrapers["iso2"])
    iea_stock = set(iea["inventory_disaggregation"]["iso2"])
    iea_spr = set(
        iea["inventory_disaggregation"].loc[
            iea["inventory_disaggregation"]["has_government_spr"], "iso2"
        ]
    )
    jodi_dem = set(jodi["countries"].loc[jodi["countries"]["has_totdemo"], "iso2"])
    jodi_stk = set(jodi["countries"].loc[jodi["countries"]["has_clostlv_products"], "iso2"])

    rows = [
        {"metric": "Countries (mappable ISO)", "iea": len(iea_iso), "jodi": len(jodi_iso), "scrapers": len(scrape_iso)},
        {"metric": "Demand reporters", "iea": int((~iea["demand_countries"]["is_aggregate"]).sum()), "jodi": len(jodi_dem), "scrapers": len(scrape_iso)},
        {"metric": "Inventory reporters", "iea": len(iea_stock), "jodi": len(jodi_stk), "scrapers": "see inventory_sources.csv"},
        {"metric": "SPR / government stock split", "iea": len(iea_spr), "jodi": 0, "scrapers": "n/a"},
        {"metric": "In IEA and JODI", "iea": len(iea_iso & jodi_iso), "jodi": len(iea_iso & jodi_iso), "scrapers": "-"},
        {"metric": "Scraper and JODI", "iea": "-", "jodi": len(scrape_iso & jodi_iso), "scrapers": len(scrape_iso & jodi_iso)},
        {"metric": "Scraper and IEA", "iea": len(scrape_iso & iea_iso), "jodi": "-", "scrapers": len(scrape_iso & iea_iso)},
    ]
    return pd.DataFrame(rows)


def missing_vs_source(
    source_countries: pd.DataFrame,
    scrapers: pd.DataFrame,
    *,
    source_name_col: str,
    source_label: str,
) -> pd.DataFrame:
    """Countries present in a source but not covered by national scrapers."""
    scrape_iso = set(scrapers["iso2"])
    src = source_countries.dropna(subset=["iso2"]).copy()
    src = src.loc[~src["iso2"].isin(scrape_iso)].copy()
    src = src.rename(columns={source_name_col: "source_name"})
    src["source"] = source_label
    src["missing_from_scraper"] = True
    keep = ["source", "iso2", "source_name", "missing_from_scraper"]
    extra = [c for c in src.columns if c not in keep and c not in ("iea_code", "jodi_name")]
    # Prefer a stable slim table; keep useful flags if present.
    flag_like = [c for c in src.columns if c.startswith("has_") or c.startswith("in_") or c.startswith("monthly")]
    cols = ["source", "iso2", "source_name"] + flag_like
    cols = [c for c in cols if c in src.columns]
    return src[cols].drop_duplicates("iso2").sort_values("iso2").reset_index(drop=True)


def scraper_gap_tables(
    iea: dict,
    jodi: dict,
    scrapers: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    """Tables of source countries the national scraper fleet does not cover."""
    iea_all = iea["iea_countries_all"].copy()
    iea_all = iea_all.rename(columns={"iea_name": "source_name"})
    jodi_c = jodi["countries"].rename(columns={"jodi_name": "source_name"})

    miss_iea = missing_vs_source(
        iea_all,
        scrapers,
        source_name_col="source_name",
        source_label="IEA",
    )
    miss_jodi = missing_vs_source(
        jodi_c,
        scrapers,
        source_name_col="source_name",
        source_label="JODI",
    )

    # Combined view: missing from scraper for either source.
    scrape_iso = set(scrapers["iso2"])
    combined = (
        pd.concat(
            [
                iea_all.assign(in_iea=True)[["iso2", "source_name", "in_iea"]],
                jodi_c.assign(in_jodi=True)[["iso2", "source_name", "in_jodi"]],
            ],
            ignore_index=True,
        )
        .groupby("iso2", as_index=False)
        .agg(
            source_name=("source_name", "first"),
            in_iea=("in_iea", "any"),
            in_jodi=("in_jodi", "any"),
        )
    )
    combined["in_iea"] = combined["in_iea"].fillna(False)
    combined["in_jodi"] = combined["in_jodi"].fillna(False)
    combined["in_scraper"] = combined["iso2"].isin(scrape_iso)
    missing_either = combined.loc[~combined["in_scraper"]].sort_values("iso2").reset_index(drop=True)

    # Priority-ish: large markets often wanted for demand nowcasts.
    priority_iso = {
        "CN", "US", "SA", "RU", "BR", "CA", "MX", "FR", "NL", "SG", "AE", "IQ",
        "IR", "KW", "QA", "NG", "ZA", "ID", "MY", "VN", "PH", "TR", "SE", "CH",
        "BE", "AT", "DK", "FI", "GR", "IE", "NZ", "CL", "CZ", "RO", "BG",
    }
    missing_either["priority_candidate"] = missing_either["iso2"].isin(priority_iso)

    return {
        "missing_vs_iea": miss_iea,
        "missing_vs_jodi": miss_jodi,
        "missing_vs_either": missing_either,
        "scraper_coverage": scrapers.assign(
            in_iea=lambda d: d["iso2"].isin(set(iea_all["iso2"])),
            in_jodi=lambda d: d["iso2"].isin(set(jodi_c["iso2"])),
        ),
    }


def pros_cons_table() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "dimension": "Geographic breadth",
                "iea_advantage": "Deep OECD product/stock detail",
                "iea_disadvantage": "Non-OECD demand often Q/A + aggregate product",
                "jodi_advantage": "~118 monthly countries incl. many EM",
                "jodi_disadvantage": "Reporting quality/assessment flags vary",
            },
            {
                "dimension": "Product demand detail",
                "iea_advantage": "OECD monthly product slate (OECDDEM)",
                "iea_disadvantage": "NOECDDEM ≈ Oil products only",
                "jodi_advantage": "Consistent monthly product codes worldwide",
                "jodi_disadvantage": "Fewer product splits than IEA MOSPRODSPLIT",
            },
            {
                "dimension": "Inventories",
                "iea_advantage": "Government vs Industry vs Total (SPR-aware)",
                "iea_disadvantage": "OECD-centric MOSSTOCKS panel",
                "jodi_advantage": "Wider country stock panel (CLOSTLV)",
                "jodi_disadvantage": "No SPR vs commercial split",
            },
            {
                "dimension": "Balances",
                "iea_advantage": "Rich MOS crude/product flow taxonomy",
                "iea_disadvantage": "Manual files; not in warehouse yet",
                "jodi_advantage": "ETL’d primary+secondary balance grid",
                "jodi_disadvantage": "Less stock-holder detail than IEA",
            },
            {
                "dimension": "Nowcast / HF blend",
                "iea_advantage": "OECD SPR/commercial + OMR-aligned demand concepts",
                "iea_disadvantage": "Harder to refresh automatically today",
                "jodi_advantage": "Natural monthly backbone for global tracker",
                "jodi_disadvantage": "Lags national agencies; revisions via assessment",
            },
        ]
    )
