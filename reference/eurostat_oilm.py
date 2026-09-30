"""
reference.eurostat_oilm
───────────────────────
Eurostat monthly oil commodity balance (``nrg_cb_oilm``).

Demand-like series: balance ``GID_OBS`` (gross inland deliveries — observed),
unit thousand tonnes (``THS_T`` / kt).

Used as:
  • official source for geos without a national scraper
  • freshness-ranked companion for geos that already have nationals
    (fresher → official tier; other → benchmark — no double-count in aggregates)
"""

from __future__ import annotations

import logging
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Iterable, Optional, Sequence

import pandas as pd

from reference.dashboard_helpers import (
    DEFAULT_SEASONALITY_PANELS_CANONICAL,
    default_seasonality_chart_inputs,
)
from reference.jodi_compare import JodiCompareSeries

logger = logging.getLogger(__name__)

EUROSTAT_AGENCY_SOURCE = "Eurostat"
EUROSTAT_DATASET_SOURCE = "eurostat_oilm"
SOURCE_ID = EUROSTAT_DATASET_SOURCE
EUROSTAT_METRIC_TYPE = "TOTDEMO"
EUROSTAT_UNIT_NATIVE = "kt"

SDMX21_DATA = "https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data"
DATASET_CB_OILM = "nrg_cb_oilm"
DATASET_STK_OILM = "nrg_stk_oilm"
BALANCE_GID_OBS = "GID_OBS"
UNIT_THS_T = "THS_T"
FREQ_M = "M"

# Shared module constants (per-country YAML still sets country_code / display_name).
COUNTRY_CODE = "EU"
COUNTRY_NAME = "Eurostat"
JODI_REF_AREA = ""

SIEC_MOTOR_GASOLINE = "O4652"
SIEC_MOTOR_GASOLINE_EX_BIO = "O4652XR5210B"
SIEC_GAS_DIESEL_OIL = "O4671"
SIEC_ROAD_DIESEL = "O46711"
SIEC_HEATING_GASOIL = "O46712"
SIEC_GAS_DIESEL_EX_BIO = "O4671XR5220B"
SIEC_JET_KERO = "O4661"
SIEC_FUEL_OIL = "O4680"
SIEC_LPG = "O4630"
SIEC_NAPHTHA = "O4640"
SIEC_OIL_PRODUCTS = "O4600"

SIEC_LABELS: dict[str, str] = {
    SIEC_MOTOR_GASOLINE: "Motor gasoline",
    SIEC_MOTOR_GASOLINE_EX_BIO: "Motor gasoline (ex bio)",
    SIEC_GAS_DIESEL_OIL: "Gas oil and diesel oil",
    SIEC_ROAD_DIESEL: "Road diesel",
    SIEC_HEATING_GASOIL: "Heating and other gasoil",
    SIEC_GAS_DIESEL_EX_BIO: "Gas/diesel oil (ex bio)",
    SIEC_JET_KERO: "Kerosene-type jet fuel",
    SIEC_FUEL_OIL: "Fuel oil",
    SIEC_LPG: "LPG",
    SIEC_NAPHTHA: "Naphtha",
    SIEC_OIL_PRODUCTS: "Oil products (total)",
}

SIEC_TO_CANONICAL: dict[str, str] = {
    SIEC_MOTOR_GASOLINE: "Gasoline",
    SIEC_GAS_DIESEL_OIL: "Diesel",
    SIEC_JET_KERO: "Jet Fuel",
    SIEC_FUEL_OIL: "Fuel Oil",
    SIEC_LPG: "LPG",
    SIEC_NAPHTHA: "Naphtha",
}

SIEC_TO_KIND: dict[str, str] = {
    SIEC_MOTOR_GASOLINE: "gasoline",
    SIEC_MOTOR_GASOLINE_EX_BIO: "gasoline",
    SIEC_GAS_DIESEL_OIL: "diesel",
    SIEC_ROAD_DIESEL: "diesel",
    SIEC_HEATING_GASOIL: "diesel",
    SIEC_GAS_DIESEL_EX_BIO: "diesel",
    SIEC_JET_KERO: "jet",
    SIEC_FUEL_OIL: "fuel_oil",
    SIEC_LPG: "lpg",
    SIEC_NAPHTHA: "naphtha",
}

# Stored natives: headline + road/heating detail (detail lines are AGG in product_map).
STORED_SIEC: tuple[str, ...] = (
    SIEC_MOTOR_GASOLINE,
    SIEC_GAS_DIESEL_OIL,
    SIEC_ROAD_DIESEL,
    SIEC_HEATING_GASOIL,
    SIEC_JET_KERO,
    SIEC_FUEL_OIL,
    SIEC_LPG,
    SIEC_NAPHTHA,
)

SPIKE_SIEC = STORED_SIEC

UNITS_KIND: dict[str, str] = dict(SIEC_TO_KIND)

CHART_PRODUCTS: tuple[str, ...] = STORED_SIEC
SEASONALITY_NATIVE_PRODUCTS: tuple[str, ...] = STORED_SIEC
DISPLAY_LABELS: dict[str, str] = dict(SIEC_LABELS)
JET_PRODUCT_NATIVE = SIEC_JET_KERO

GASOLINE_JODI_NATIVES = frozenset({SIEC_MOTOR_GASOLINE})
DIESEL_JODI_NATIVES = frozenset({SIEC_GAS_DIESEL_OIL})
JET_JODI_NATIVES = frozenset({SIEC_JET_KERO})
LPG_JODI_NATIVES = frozenset({SIEC_LPG})
NAPHTHA_JODI_NATIVES = frozenset({SIEC_NAPHTHA})
FUEL_OIL_JODI_NATIVES = frozenset({SIEC_FUEL_OIL})

JODI_COMPARE_SERIES: dict[str, JodiCompareSeries] = {
    "gasoline": JodiCompareSeries(
        "gasoline", "GASOLINE", "Gasoline", GASOLINE_JODI_NATIVES
    ),
    "diesel": JodiCompareSeries(
        "diesel", "GASDIES", "Diesel", DIESEL_JODI_NATIVES
    ),
    "jet_fuel": JodiCompareSeries(
        "jet_fuel", "JETKERO", "Jet fuel", JET_JODI_NATIVES
    ),
    "lpg": JodiCompareSeries("lpg", "LPG", "LPG", LPG_JODI_NATIVES),
    "naphtha": JodiCompareSeries(
        "naphtha", "NAPHTHA", "Naphtha", NAPHTHA_JODI_NATIVES
    ),
    "fuel_oil": JodiCompareSeries(
        "fuel_oil", "RESFUEL", "Fuel oil", FUEL_OIL_JODI_NATIVES
    ),
}

JODI_COMPARE_PANEL_ORDER: tuple[str, ...] = (
    "Gasoline",
    "Diesel",
    "Jet fuel",
    "LPG",
    "Naphtha",
    "Fuel oil",
)

# geo → (country_id, display_name). Aggregates omitted.
GEO_CATALOG: dict[str, tuple[str, str]] = {
    "AL": ("albania", "Albania"),
    "AT": ("austria", "Austria"),
    "BE": ("belgium", "Belgium"),
    "BG": ("bulgaria", "Bulgaria"),
    "CY": ("cyprus", "Cyprus"),
    "CZ": ("czechia", "Czechia"),
    "DE": ("germany", "Germany"),
    "DK": ("denmark", "Denmark"),
    "EE": ("estonia", "Estonia"),
    "EL": ("greece", "Greece"),
    "ES": ("spain", "Spain"),
    "FI": ("finland", "Finland"),
    "FR": ("france", "France"),
    "GE": ("georgia", "Georgia"),
    "HR": ("croatia", "Croatia"),
    "HU": ("hungary", "Hungary"),
    "IE": ("ireland", "Ireland"),
    "IT": ("italy", "Italy"),
    "LT": ("lithuania", "Lithuania"),
    "LU": ("luxembourg", "Luxembourg"),
    "LV": ("latvia", "Latvia"),
    "MD": ("moldova", "Moldova"),
    "ME": ("montenegro", "Montenegro"),
    "MK": ("north_macedonia", "North Macedonia"),
    "MT": ("malta", "Malta"),
    "NL": ("netherlands", "Netherlands"),
    "NO": ("norway", "Norway"),
    "PL": ("poland", "Poland"),
    "PT": ("portugal", "Portugal"),
    "RO": ("romania", "Romania"),
    "RS": ("serbia", "Serbia"),
    "SE": ("sweden", "Sweden"),
    "SI": ("slovenia", "Slovenia"),
    "SK": ("slovakia", "Slovakia"),
    "TR": ("turkiye", "Türkiye"),
}

NATIONAL_PRIMARY_IDS: frozenset[str] = frozenset(
    {
        "germany",
        "norway",
        "poland",
        "hungary",
        "portugal",
        "spain",
        "italy",
        "uk",
        "ukraine",
    }
)

SKIP_GEOS: frozenset[str] = frozenset({"EU27_2020", "EA20", "EU28"})

CANONICAL_COLUMNS: list[str] = [
    "date",
    "country",
    "country_name",
    "source",
    "metric_type",
    "product_native",
    "product",
    "value",
    "unit",
    "is_provisional",
    "source_file",
    "updated_at",
]

MASTER_PARQUET_REL = "eurostat/eurostat_oilm_demand.parquet"
MASTER_STOCKS_PARQUET_REL = "eurostat/eurostat_oilm_stocks.parquet"

# Stocks (nrg_stk_oilm) — closing flows only; openings omitted as redundant.
EUROSTAT_STOCKS_SOURCE = "eurostat_oilm_stocks"
EUROSTAT_STOCKS_METRIC = "CLOSTLV"
SIEC_CRUDE = "O4100_TOT"
SIEC_CRUDE_NGL_FEED = "O4100_TOT_4200-4500"
SIEC_OIL_AND_PRODUCTS = "O4000"

STORED_STOCK_SIEC: tuple[str, ...] = (
    SIEC_OIL_AND_PRODUCTS,
    SIEC_CRUDE,
    SIEC_MOTOR_GASOLINE,
    SIEC_GAS_DIESEL_OIL,
    SIEC_ROAD_DIESEL,
    SIEC_HEATING_GASOIL,
    SIEC_JET_KERO,
    SIEC_FUEL_OIL,
    SIEC_LPG,
    SIEC_NAPHTHA,
)

SIEC_LABELS.update(
    {
        SIEC_OIL_AND_PRODUCTS: "Oil and petroleum products",
        SIEC_CRUDE: "Crude oil",
        SIEC_CRUDE_NGL_FEED: "Crude oil, NGL, feedstocks and other hydrocarbons",
    }
)
SIEC_TO_KIND.update(
    {
        SIEC_OIL_AND_PRODUCTS: "other",
        SIEC_CRUDE: "crude",
        SIEC_CRUDE_NGL_FEED: "crude",
    }
)

# Closing stock flow codes we persist (all STKCL_* + headline STK_CL).
STKCL_FLOW_LABELS: dict[str, str] = {
    "STK_CL": "Closing stock (headline)",
    "STKCL_NAT": "National territory",
    "STKCL_NAT_GOV": "Government on national territory",
    "STKCL_NAT_SHO": "Stockholding organisation on national territory",
    "STKCL_NAT_OTH": "Other on national territory",
    "STKCL_EUE": "EU emergency (total)",
    "STKCL_EUE_NAT": "EU emergency — national territory",
    "STKCL_EUE_NAT_GOV": "EU emergency — government (national)",
    "STKCL_EUE_NAT_CSE": "EU emergency — central stockholding entity (national)",
    "STKCL_EUE_NAT_EO": "EU emergency — economic operators (national)",
    "STKCL_EUE_NAT_CEO_DIR": "EU emergency — commercial EO under Directive (national)",
    "STKCL_EUE_ABR_EU_OTH_OA": "EU emergency — held abroad in other EU (official agreement)",
    "STKCL_EUE_EU_OTH_IMP": "EU emergency — held abroad in EU, for import into country",
    "STKCL_EUE_EU_OTH_OA": "EU emergency — held for other EU MS (official agreement)",
    "STKCL_EUE_KFDEU": "EU emergency — known foreign EU destination",
    "STKCL_ABR_IMP": "Held abroad — designated for import into country",
    "STKCL_ABR_OA": "Held abroad under official agreement",
    "STKCL_ABR_OA_GOV": "Government stocks held abroad (official agreement)",
    "STKCL_ABR_OA_SHO": "Stockholding org stocks held abroad (official agreement)",
    "STKCL_ABR_OA_OTH": "Other held abroad (official agreement)",
    "STKCL_C_OTH_OA": "Held for other countries under official agreement",
    "STKCL_BA": "Other in bonded areas",
    "STKCL_BAXC_OTH_OA_KFD": "Bonded areas excl. other-country OA and known foreign destination",
    "STKCL_MCL": "Major consumers obligated by law",
    "STKCL_KFD": "Known foreign destination",
    "STKCL_OV": "On board incoming ocean vessels in port / mooring",
    "STKCL_PF": "Pipeline fill",
}

# Coarse bucket for later dashboards / filters (SPR vs commercial vs location).
def stock_bucket_for_flow(stk_flow: str) -> str:
    f = str(stk_flow)
    if f == "STK_CL":
        return "closing_headline"
    if f.startswith("STKCL_EUE"):
        return "emergency_spr"
    if f.startswith("STKCL_ABR"):
        return "held_abroad"
    if f.startswith("STKCL_NAT"):
        return "national_territory"
    if f in {"STKCL_C_OTH_OA"}:
        return "held_for_others"
    if f.startswith("STKCL_BA"):
        return "bonded_areas"
    if f == "STKCL_MCL":
        return "major_consumers"
    if f in {"STKCL_OV", "STKCL_PF"}:
        return "pipeline_vessels"
    if f == "STKCL_KFD":
        return "known_foreign_destination"
    return "other_closing"


STOCK_BUCKET_LABELS: dict[str, str] = {
    "closing_headline": "Closing stock (headline total)",
    "emergency_spr": "EU emergency / SPR obligation",
    "national_territory": "On national territory",
    "held_abroad": "Held abroad",
    "held_for_others": "Held for other countries",
    "bonded_areas": "Bonded areas",
    "major_consumers": "Major consumers (obligated)",
    "pipeline_vessels": "Pipeline fill / vessels in port",
    "known_foreign_destination": "Known foreign destination",
    "other_closing": "Other closing",
}


@dataclass(frozen=True)
class EurostatSeriesSpec:
    siec: str
    label: str
    product_canonical: str
    product_kind: str


def series_specs(siec_codes: Sequence[str] = STORED_SIEC) -> list[EurostatSeriesSpec]:
    out: list[EurostatSeriesSpec] = []
    for code in siec_codes:
        out.append(
            EurostatSeriesSpec(
                siec=code,
                label=SIEC_LABELS.get(code, code),
                product_canonical=SIEC_TO_CANONICAL.get(code, "-"),
                product_kind=SIEC_TO_KIND.get(code, "other"),
            )
        )
    return out


def geo_to_country_id(geo: str) -> Optional[str]:
    meta = GEO_CATALOG.get(geo.strip().upper())
    return meta[0] if meta else None


def country_id_to_geo(country_id: str) -> Optional[str]:
    for geo, (cid, _) in GEO_CATALOG.items():
        if cid == country_id:
            return geo
    return None


def eurostat_only_catalog() -> dict[str, tuple[str, str]]:
    return {
        geo: meta
        for geo, meta in GEO_CATALOG.items()
        if meta[0] not in NATIONAL_PRIMARY_IDS
    }


def _http_get(url: str, *, timeout: int = 120) -> bytes:
    req = urllib.request.Request(
        url, headers={"User-Agent": "country-oil-scraper/eurostat-oilm"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def fetch_gid_obs_tsv(
    geo: str,
    *,
    start: str = "2008-01",
    end: Optional[str] = None,
    siec: str = "",
) -> pd.DataFrame:
    """Download ``nrg_cb_oilm`` GID_OBS for one geo as a long frame."""
    geo = geo.strip().upper()
    siec_key = siec.strip() if siec.strip() else ""
    key = f"{FREQ_M}.{BALANCE_GID_OBS}.{siec_key}.{UNIT_THS_T}.{geo}"
    params: dict[str, str] = {"format": "TSV", "startPeriod": start}
    if end:
        params["endPeriod"] = end
    url = f"{SDMX21_DATA}/{DATASET_CB_OILM}/{key}?{urllib.parse.urlencode(params)}"
    logger.info("Eurostat GET %s", url)
    try:
        raw = _http_get(url).decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read()[:300] if hasattr(exc, "read") else b""
        raise RuntimeError(f"Eurostat HTTP {exc.code} for {geo}: {body!r}") from exc

    df = pd.read_csv(StringIO(raw), sep="\t")
    id_col = df.columns[0]
    df = df.rename(columns={id_col: "key"})
    parts = df["key"].str.split(",", expand=True)
    df["freq"] = parts[0]
    df["nrg_bal"] = parts[1]
    df["siec"] = parts[2]
    df["unit"] = parts[3]
    df["geo"] = parts[4]
    time_cols = [
        c
        for c in df.columns
        if c not in {"key", "freq", "nrg_bal", "siec", "unit", "geo"}
    ]
    long = df.melt(
        id_vars=["geo", "siec", "nrg_bal", "unit"],
        value_vars=time_cols,
        var_name="ym",
        value_name="value_ths_t",
    )
    long["date"] = pd.to_datetime(
        long["ym"].astype(str).str.strip(), format="%Y-%m", errors="coerce"
    )
    long["value_ths_t"] = pd.to_numeric(
        long["value_ths_t"]
        .astype(str)
        .str.replace(":", "", regex=False)
        .str.strip(),
        errors="coerce",
    )
    long["siec_label"] = long["siec"].map(SIEC_LABELS).fillna(long["siec"])
    long["product_canonical"] = long["siec"].map(SIEC_TO_CANONICAL)
    long["product_kind"] = long["siec"].map(SIEC_TO_KIND)
    return (
        long.dropna(subset=["date"])
        .sort_values(["geo", "siec", "date"])
        .reset_index(drop=True)
    )


def fetch_gid_obs_geos(
    geos: Iterable[str],
    *,
    start: str = "2008-01",
    end: Optional[str] = None,
) -> pd.DataFrame:
    frames = []
    for g in geos:
        try:
            frames.append(fetch_gid_obs_tsv(g, start=start, end=end))
        except Exception as exc:  # noqa: BLE001 — keep going for other geos
            logger.warning("Skip geo %s: %s", g, exc)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def latest_month_by_geo(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["geo", "latest_month", "n_obs"])
    ok = df.dropna(subset=["value_ths_t"])
    g = (
        ok.groupby("geo", as_index=False)
        .agg(latest_month=("date", "max"), n_obs=("value_ths_t", "count"))
        .sort_values("latest_month", ascending=False)
    )
    g["latest_month"] = g["latest_month"].dt.strftime("%Y-%m")
    return g


def master_parquet_path(root: Path | None = None) -> Path:
    root = root or Path(__file__).resolve().parents[1]
    return root / "data" / "processed" / MASTER_PARQUET_REL


def master_stocks_parquet_path(root: Path | None = None) -> Path:
    root = root or Path(__file__).resolve().parents[1]
    return root / "data" / "processed" / MASTER_STOCKS_PARQUET_REL


def fetch_stk_cl_tsv(
    geo: str,
    *,
    start: str = "2013-01",
    end: Optional[str] = None,
) -> pd.DataFrame:
    """
    Download ``nrg_stk_oilm`` closing stocks for one geo.

    Keeps ``STK_CL`` headline + all ``STKCL_*`` splits; drops opening ``STKOP_*``.
    """
    geo = geo.strip().upper()
    # Key: freq.stk_flow.siec.unit.geo — wildcards on flow + product.
    key = f"{FREQ_M}...{UNIT_THS_T}.{geo}"
    params: dict[str, str] = {"format": "TSV", "startPeriod": start}
    if end:
        params["endPeriod"] = end
    url = f"{SDMX21_DATA}/{DATASET_STK_OILM}/{key}?{urllib.parse.urlencode(params)}"
    logger.info("Eurostat stocks GET %s", url)
    try:
        raw = _http_get(url).decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read()[:300] if hasattr(exc, "read") else b""
        raise RuntimeError(f"Eurostat stocks HTTP {exc.code} for {geo}: {body!r}") from exc

    df = pd.read_csv(StringIO(raw), sep="\t")
    id_col = df.columns[0]
    df = df.rename(columns={id_col: "key"})
    parts = df["key"].str.split(",", expand=True)
    df["freq"] = parts[0]
    df["stk_flow"] = parts[1]
    df["siec"] = parts[2]
    df["unit"] = parts[3]
    df["geo"] = parts[4]
    time_cols = [
        c
        for c in df.columns
        if c not in {"key", "freq", "stk_flow", "siec", "unit", "geo"}
    ]
    long = df.melt(
        id_vars=["geo", "siec", "stk_flow", "unit"],
        value_vars=time_cols,
        var_name="ym",
        value_name="value_ths_t",
    )
    long["date"] = pd.to_datetime(
        long["ym"].astype(str).str.strip(), format="%Y-%m", errors="coerce"
    )
    long["value_ths_t"] = pd.to_numeric(
        long["value_ths_t"]
        .astype(str)
        .str.replace(":", "", regex=False)
        .str.strip(),
        errors="coerce",
    )
    # Closing only.
    flow = long["stk_flow"].astype(str)
    long = long[(flow == "STK_CL") | flow.str.startswith("STKCL_")].copy()
    long["stk_flow_label"] = long["stk_flow"].map(STKCL_FLOW_LABELS).fillna(long["stk_flow"])
    long["stock_bucket"] = long["stk_flow"].map(stock_bucket_for_flow)
    long["siec_label"] = long["siec"].map(SIEC_LABELS).fillna(long["siec"])
    long["product_kind"] = long["siec"].map(SIEC_TO_KIND)
    return (
        long.dropna(subset=["date"])
        .sort_values(["geo", "stk_flow", "siec", "date"])
        .reset_index(drop=True)
    )


def fetch_stk_cl_geos(
    geos: Iterable[str],
    *,
    start: str = "2013-01",
    end: Optional[str] = None,
) -> pd.DataFrame:
    frames = []
    for g in geos:
        try:
            frames.append(fetch_stk_cl_tsv(g, start=start, end=end))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Skip stocks geo %s: %s", g, exc)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def seasonality_chart_inputs(
    demand: pd.DataFrame,
    demand_canonical: pd.DataFrame,
    *,
    view: str = "native",
    value_col: str = "value_kbd",
) -> tuple[pd.DataFrame, str, list[str], dict[str, str], str]:
    return default_seasonality_chart_inputs(
        demand,
        demand_canonical,
        view=view,
        value_col=value_col,
        native_products=SEASONALITY_NATIVE_PRODUCTS,
        display_labels=DISPLAY_LABELS,
        canonical_panels=DEFAULT_SEASONALITY_PANELS_CANONICAL,
    )


def eurostat_series_for_jodi(
    demand: pd.DataFrame,
    series_key: str,
    *,
    value_col: str = "value_kbd",
) -> pd.DataFrame:
    from reference.jodi_compare import sum_natives_series_for_jodi

    return sum_natives_series_for_jodi(
        demand,
        series_key,
        jodi_compare=JODI_COMPARE_SERIES,
        value_col=value_col,
    )
