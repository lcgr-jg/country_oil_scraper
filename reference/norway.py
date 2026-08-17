"""
reference.norway
────────────────
SSB (Statistics Norway) — monthly sales of petroleum products (Table 3).

Live series: StatBank **13585** (2021M01+, preliminary, million litres).
Historical bootstrap stitches closed tables **11174** (2010–2022) and
**03687** (1995–2016M07). Newer tables win on overlapping months.

Primary demand value: ``Deliveries of petroleum products (incl. bio
components)`` on 13585 (best match to JODI product lines). Legacy tables
expose a single ``Deliveries`` content code.
"""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import FrozenSet, Optional
from urllib.parse import quote

import pandas as pd
import requests

logger = logging.getLogger(__name__)

SSB_AGENCY_SOURCE = "SSB"
SSB_DATASET_SOURCE = "norway_ssb_petroleum_sales"
SSB_METRIC_TYPE = "TOTDEMO"
SSB_UNIT_NATIVE = "ML"

COUNTRY_CODE = "NO"
COUNTRY_NAME = "Norway"
SOURCE_ID = SSB_DATASET_SOURCE
JODI_REF_AREA = "NO"

SSB_API_BASE = "https://data.ssb.no/api/pxwebapi/v2/tables"
SSB_STATISTICS_PAGE = (
    "https://www.ssb.no/en/energi-og-industri/olje-og-gass/statistikk/sal-av-petroleumsprodukt"
)

# Current-era StatBank table (Table 3 on the statistics page).
TABLE_CURRENT = "13585"
# Closed monthly series with modern product split.
TABLE_BRIDGE = "11174"
# Closed monthly series with coarse legacy products.
TABLE_LEGACY = "03687"

CONTENTS_PETROLEUM_INCL_BIO = "Petroleum"

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

# ── Current-era product natives (Table 3 / 13585) ───────────────────────────

PRODUCT_MOTOR_GASOLINE = "Motor gasoline"
PRODUCT_AUTO_DIESEL_DUTIABLE = "Auto diesel, dutiable"
PRODUCT_AUTO_DIESEL_FREE = "Auto diesel, free of duty"
PRODUCT_MARINE_GASOIL = "Marine gas oil and diesel"
PRODUCT_HEATING_KERO_COMBINED = (
    "Light heating oils and kerosene for heating and lighting"
)
PRODUCT_HEATING_KERO = "Heating and lighting kerosene"
PRODUCT_LIGHT_HEATING_OILS = "Light heating oils"
PRODUCT_JET_KEROSENE = "Jet kerosene"
PRODUCT_HEAVY_FUEL_OIL = "Heavy distillate and heavy fuel oil"
PRODUCT_OTHER = "Other petroleum products"

# Legacy-era natives (03687) kept distinct for revision-aware charts.
PRODUCT_LEGACY_DIESEL = "Diesel"
PRODUCT_LEGACY_MIDDLE_DISTILLATES = "Other middle distillates"
PRODUCT_LEGACY_KEROSENE = "Kerosene"

CURRENT_NATIVES: frozenset[str] = frozenset(
    {
        PRODUCT_MOTOR_GASOLINE,
        PRODUCT_AUTO_DIESEL_DUTIABLE,
        PRODUCT_AUTO_DIESEL_FREE,
        PRODUCT_MARINE_GASOIL,
        PRODUCT_HEATING_KERO_COMBINED,
        PRODUCT_JET_KEROSENE,
        PRODUCT_HEAVY_FUEL_OIL,
        PRODUCT_OTHER,
    }
)

BRIDGE_EXTRA_NATIVES: frozenset[str] = frozenset(
    {PRODUCT_HEATING_KERO, PRODUCT_LIGHT_HEATING_OILS}
)

LEGACY_EXTRA_NATIVES: frozenset[str] = frozenset(
    {
        PRODUCT_LEGACY_DIESEL,
        PRODUCT_LEGACY_MIDDLE_DISTILLATES,
        PRODUCT_LEGACY_KEROSENE,
    }
)

# When bridge/current tables publish a finer product split, drop coarse legacy
# rows for the same month — otherwise canonical diesel is ~2x in 2010–2016.
LEGACY_SUPERSESSION: tuple[tuple[str, frozenset[str]], ...] = (
    (
        PRODUCT_LEGACY_DIESEL,
        frozenset({PRODUCT_AUTO_DIESEL_DUTIABLE, PRODUCT_AUTO_DIESEL_FREE}),
    ),
    (
        PRODUCT_LEGACY_MIDDLE_DISTILLATES,
        frozenset({PRODUCT_MARINE_GASOIL}),
    ),
    (
        PRODUCT_LEGACY_KEROSENE,
        frozenset(
            {
                PRODUCT_HEATING_KERO,
                PRODUCT_LIGHT_HEATING_OILS,
                PRODUCT_HEATING_KERO_COMBINED,
            }
        ),
    ),
)

STORED_NATIVES: tuple[str, ...] = tuple(
    sorted(CURRENT_NATIVES | BRIDGE_EXTRA_NATIVES | LEGACY_EXTRA_NATIVES)
)

DELIVERY_HEADLINE_NATIVE: frozenset[str] = frozenset(
    n
    for n in STORED_NATIVES
    if n
    not in {
        PRODUCT_LEGACY_DIESEL,
        PRODUCT_LEGACY_MIDDLE_DISTILLATES,
        PRODUCT_LEGACY_KEROSENE,
    }
)

CHART_PRODUCTS: tuple[str, ...] = tuple(
    n for n in STORED_NATIVES if n not in LEGACY_EXTRA_NATIVES
)

DISPLAY_LABELS: dict[str, str] = {
    PRODUCT_MOTOR_GASOLINE: "Gasoline",
    PRODUCT_AUTO_DIESEL_DUTIABLE: "Auto diesel (dutiable)",
    PRODUCT_AUTO_DIESEL_FREE: "Auto diesel (free)",
    PRODUCT_MARINE_GASOIL: "Marine gas oil",
    PRODUCT_HEATING_KERO_COMBINED: "Heating kerosene (combined)",
    PRODUCT_HEATING_KERO: "Heating kerosene",
    PRODUCT_LIGHT_HEATING_OILS: "Light heating oils",
    PRODUCT_JET_KEROSENE: "Jet fuel",
    PRODUCT_HEAVY_FUEL_OIL: "Fuel oil",
    PRODUCT_OTHER: "Other products",
    PRODUCT_LEGACY_DIESEL: "Diesel (legacy)",
    PRODUCT_LEGACY_MIDDLE_DISTILLATES: "Middle distillates (legacy)",
    PRODUCT_LEGACY_KEROSENE: "Kerosene (legacy)",
}

UNITS_KIND: dict[str, str] = {
    PRODUCT_MOTOR_GASOLINE: "gasoline",
    PRODUCT_AUTO_DIESEL_DUTIABLE: "diesel",
    PRODUCT_AUTO_DIESEL_FREE: "diesel",
    PRODUCT_MARINE_GASOIL: "diesel",
    PRODUCT_HEATING_KERO_COMBINED: "kerosene",
    PRODUCT_HEATING_KERO: "kerosene",
    PRODUCT_LIGHT_HEATING_OILS: "kerosene",
    PRODUCT_JET_KEROSENE: "jet",
    PRODUCT_HEAVY_FUEL_OIL: "fuel_oil",
    PRODUCT_OTHER: "other",
    PRODUCT_LEGACY_DIESEL: "diesel",
    PRODUCT_LEGACY_MIDDLE_DISTILLATES: "diesel",
    PRODUCT_LEGACY_KEROSENE: "kerosene",
}

_TIME_RE = re.compile(r"^(\d{4})M(\d{2})$")


@dataclass(frozen=True)
class SsbTableEra:
    table_id: str
    product_dim: str
    contents_code: str
    product_codes: tuple[str, ...]
    priority: int
    label: str
    purchaser_code: str = "00"
    region_code: Optional[str] = None  # only legacy tables use Region=0


TABLE_ERAS: tuple[SsbTableEra, ...] = (
    SsbTableEra(
        TABLE_CURRENT,
        "Produkter",
        CONTENTS_PETROLEUM_INCL_BIO,
        ("01", "02a", "02b", "03", "04+05", "06", "07", "98"),
        priority=3,
        label="current",
    ),
    SsbTableEra(
        TABLE_BRIDGE,
        "PetroleumProd",
        "Petroleum",
        ("03", "04a", "04b", "06a", "06b", "05b", "06c", "10a", "120"),
        priority=2,
        label="bridge",
        region_code="0",
    ),
    SsbTableEra(
        TABLE_LEGACY,
        "PetroleumProd",
        "Petroleum",
        ("03", "04", "05a", "06", "10", "120"),
        priority=1,
        label="legacy",
        region_code="0",
    ),
)

# API product label -> canonical product_native (after era-specific normalisation).
_LABEL_TO_NATIVE: dict[str, str] = {
    "Motor gasoline": PRODUCT_MOTOR_GASOLINE,
    "Auto diesel, dutiable": PRODUCT_AUTO_DIESEL_DUTIABLE,
    "Auto diesel, free of duty": PRODUCT_AUTO_DIESEL_FREE,
    "Marine gas oil and diesel": PRODUCT_MARINE_GASOIL,
    "Light heating oils and kerosene for heating and lighting": (
        PRODUCT_HEATING_KERO_COMBINED
    ),
    "Heating and lighting kerosene": PRODUCT_HEATING_KERO,
    "Light heating oils": PRODUCT_LIGHT_HEATING_OILS,
    "Jet kerosene": PRODUCT_JET_KEROSENE,
    "Jet fuel": PRODUCT_JET_KEROSENE,
    "Heavy distillate and heavy fuel oil": PRODUCT_HEAVY_FUEL_OIL,
    "Heavy fuel oils and distillate": PRODUCT_HEAVY_FUEL_OIL,
    "Heavy fuel oil": PRODUCT_HEAVY_FUEL_OIL,
    "Other petroleum products": PRODUCT_OTHER,
    "Other petroleumproduckts": PRODUCT_OTHER,
    "Diesel": PRODUCT_LEGACY_DIESEL,
    "Other middle distillates": PRODUCT_LEGACY_MIDDLE_DISTILLATES,
    "Kerosene": PRODUCT_LEGACY_KEROSENE,
}


@dataclass(frozen=True)
class JodiCompareSeries:
    key: str
    jodi_energy_product: str
    panel: str
    natives: FrozenSet[str]
    mode: str = "sum"


GASOLINE_JODI_NATIVES: frozenset[str] = frozenset({PRODUCT_MOTOR_GASOLINE})

DIESEL_JODI_NATIVES: frozenset[str] = frozenset(
    {
        PRODUCT_AUTO_DIESEL_DUTIABLE,
        PRODUCT_AUTO_DIESEL_FREE,
        PRODUCT_MARINE_GASOIL,
        PRODUCT_LEGACY_DIESEL,
        PRODUCT_LEGACY_MIDDLE_DISTILLATES,
    }
)

# JODI X_OTHKERO (KEROSENE − JETKERO) vs heating kerosene only — not jet, not
# a combined kerosene rollup, so light vs heating split stays visible in charts.
KEROSENE_JODI_NATIVES: frozenset[str] = frozenset(
    {
        PRODUCT_HEATING_KERO_COMBINED,
        PRODUCT_HEATING_KERO,
        PRODUCT_LEGACY_KEROSENE,
    }
)

JET_JODI_NATIVES: frozenset[str] = frozenset({PRODUCT_JET_KEROSENE})

FUEL_OIL_JODI_NATIVES: frozenset[str] = frozenset({PRODUCT_HEAVY_FUEL_OIL})

OTHER_JODI_NATIVES: frozenset[str] = frozenset({PRODUCT_OTHER})

JODI_COMPARE_SERIES: dict[str, JodiCompareSeries] = {
    "gasoline": JodiCompareSeries(
        "gasoline", "GASOLINE", "Gasoline", GASOLINE_JODI_NATIVES
    ),
    "diesel": JodiCompareSeries(
        "diesel", "GASDIES", "Diesel", DIESEL_JODI_NATIVES
    ),
    "kerosene": JodiCompareSeries(
        "kerosene",
        "X_OTHKERO",
        "Kerosene (non-jet)",
        KEROSENE_JODI_NATIVES,
    ),
    "jet_fuel": JodiCompareSeries(
        "jet_fuel", "JETKERO", "Jet fuel", JET_JODI_NATIVES
    ),
    "fuel_oil": JodiCompareSeries(
        "fuel_oil", "RESFUEL", "Fuel oil", FUEL_OIL_JODI_NATIVES
    ),
    "other": JodiCompareSeries(
        "other", "ONONSPEC", "Other products", OTHER_JODI_NATIVES
    ),
}

JODI_COMPARE_PANEL_ORDER: tuple[str, ...] = (
    "Gasoline",
    "Diesel",
    "Kerosene (non-jet)",
    "Jet fuel",
    "Fuel oil",
    "Other products",
)

# Natives for the kerosene breakdown panel (jet kept separate from heating).
KEROSENE_BREAKDOWN_NATIVES: frozenset[str] = frozenset(
    {
        PRODUCT_HEATING_KERO_COMBINED,
        PRODUCT_HEATING_KERO,
        PRODUCT_LIGHT_HEATING_OILS,
        PRODUCT_LEGACY_KEROSENE,
        PRODUCT_JET_KEROSENE,
    }
)

SEASONALITY_PANELS_CANONICAL: tuple[str, ...] = (
    "Gasoline",
    "Diesel",
    "Kerosene",
    "Jet fuel",
    "Fuel oil",
    "Others",
)

# SSB revision notes for chart annotations.
MONTHLY_REVISION_FROM = pd.Timestamp("2020-01-01")
CURRENT_ERA_FROM = pd.Timestamp("2021-01-01")

# ── EV registrations (Robbie Andrew / SVV + OFV) ─────────────────────────────

EV_REGISTRATIONS_URL = (
    "https://robbieandrew.github.io/EV/data/bilsalg_data.csv"
)
EV_REGISTRATIONS_SOURCE = "robbieandrew_ev_norway"
EV_REGISTRATIONS_CACHE_NAME = "bilsalg_data.csv"
# Nissan Leaf launch — sensible start for adoption vs demand charts.
EV_ANALYSIS_FROM = pd.Timestamp("2011-01-01")

# SSB registered-vehicle fleet by fuel (annual stock, private cars).
SSB_FLEET_TABLE = "07849"
SSB_FLEET_URL = (
    "https://data.ssb.no/api/pxwebapi/v2/tables/07849/data"
    "?lang=en&outputFormat=csv&outputFormatParams=separatorsemicolon,usetexts"
    "&valueCodes[Region]=0"
    "&valueCodes[ContentsCode]=Personbil1"
    "&valueCodes[DrivstoffType]=*"
    "&valueCodes[KjoringensArt]=1"
    "&valueCodes[Tid]=*"
)
SSB_FLEET_SOURCE = "ssb_fleet_composition"
SSB_FLEET_CACHE_NAME = "ssb_07849_private_cars_fleet.csv"

_FLEET_FUEL_LABELS: dict[str, str] = {
    "Petrol": "petrol",
    "Diesel": "diesel",
    "Electricity": "bev",
    "Paraffin": "paraffin",
    "Gas": "gas",
    "Other fuel": "other_fuel",
}

# Road-transport fuels only: gasoline + auto diesel (excludes marine, heating, jet).
ROAD_FUEL_NATIVES: frozenset[str] = frozenset(
    {
        PRODUCT_MOTOR_GASOLINE,
        PRODUCT_AUTO_DIESEL_DUTIABLE,
        PRODUCT_AUTO_DIESEL_FREE,
        PRODUCT_LEGACY_DIESEL,
    }
)

_EV_CSV_COLUMNS: dict[str, str] = {
    "YYYYMM": "yyyymm",
    "Total: New": "total_new",
    "PetrolOnly: New": "petrol_new",
    "DieselOnly: New": "diesel_only_new",
    "BEV: New": "bev_new",
    "Non-plugin hybrid: New": "hybrid_new",
    "Plugin hybrid: New": "phev_new",
    "Total: Used": "total_used",
    "PetrolOnly: Used": "petrol_used",
    "DieselOnly: Used": "diesel_only_used",
    "BEV: Used": "bev_used",
    "Non-plugin hybrid: Used": "hybrid_used",
    "Plugin hybrid: Used": "phev_used",
}


def add_plotly_date_vline(
    fig,
    ts: pd.Timestamp,
    *,
    annotation_text: str | None = None,
    line_dash: str = "dash",
    line_color: str = "gray",
) -> None:
    """Vertical reference line on a datetime x-axis (plotly + pandas 2.x safe).

    ``fig.add_vline`` fails on ``pd.Timestamp`` and ISO strings with recent
    Plotly (internal offset / type mixing). Use ``add_shape`` instead — same
    pattern as ``notebooks/23_ukraine_demand_dashboard.ipynb``.
    """
    x = pd.Timestamp(ts)
    fig.add_shape(
        type="line",
        x0=x,
        x1=x,
        y0=0,
        y1=1,
        yref="paper",
        line=dict(dash=line_dash, color=line_color),
    )
    if annotation_text:
        fig.add_annotation(
            x=x,
            y=1.02,
            yref="paper",
            text=annotation_text,
            showarrow=False,
            yanchor="bottom",
            xanchor="left",
        )


def normalize_product_label(label: object) -> Optional[str]:
    if label is None or (isinstance(label, float) and pd.isna(label)):
        return None
    text = str(label).strip()
    if not text or text.lower().startswith("all product"):
        return None
    return _LABEL_TO_NATIVE.get(text, text)


def parse_ssb_month(value: object) -> Optional[pd.Timestamp]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    match = _TIME_RE.match(text)
    if not match:
        return None
    return pd.Timestamp(int(match.group(1)), int(match.group(2)), 1)


def parse_ssb_api_csv(text: str, *, source_file: str, era: SsbTableEra) -> pd.DataFrame:
    """Parse pivot-friendly CSV from PxWebApi v2."""
    df = pd.read_csv(io.StringIO(text), sep=";", decimal=".")
    if df.empty:
        return _empty_parse_frame()

    df.columns = [str(c).strip().lower() for c in df.columns]
    product_col = next(
        (c for c in df.columns if "product" in c or "produkt" in c),
        df.columns[0],
    )
    month_col = next((c for c in df.columns if c.startswith("month") or c == "tid"), None)
    value_col = next((c for c in df.columns if c == "total" or "value" in c), df.columns[-1])

    rows: list[dict] = []
    for _, rec in df.iterrows():
        native = normalize_product_label(rec[product_col])
        dt = parse_ssb_month(rec[month_col]) if month_col else None
        val = pd.to_numeric(rec[value_col], errors="coerce")
        if native is None or dt is None or pd.isna(val):
            continue
        rows.append(
            {
                "date": dt,
                "product_native": native,
                "value": float(val),
                "source_file": source_file,
                "ssb_table": era.table_id,
                "ssb_era": era.label,
                "ssb_priority": era.priority,
            }
        )
    return pd.DataFrame(rows)


def fetch_ssb_product_series(
    era: SsbTableEra,
    product_code: str,
    *,
    session: Optional[requests.Session] = None,
) -> pd.DataFrame:
    """Download one product time series from StatBank."""
    prod_param = quote(product_code, safe="")
    region_param = ""
    if era.region_code is not None:
        region_param = f"&valueCodes[Region]={era.region_code}"
    params = (
        f"lang=en&outputFormat=csv&outputFormatParams=separatorsemicolon,usetexts"
        f"{region_param}"
        f"&valueCodes[Kjopegrupper]={era.purchaser_code}"
        f"&valueCodes[{era.product_dim}]={prod_param}"
        f"&valueCodes[ContentsCode]={era.contents_code}"
        f"&valueCodes[Tid]=*"
        f"&stub={era.product_dim},Tid,ContentsCode"
    )
    url = f"{SSB_API_BASE}/{era.table_id}/data?{params}"
    client = session or requests
    resp = client.get(url, timeout=120)
    resp.raise_for_status()
    source_file = f"ssb_{era.table_id}_{product_code}.csv"
    return parse_ssb_api_csv(resp.text, source_file=source_file, era=era)


def fetch_era_table(era: SsbTableEra) -> pd.DataFrame:
    """Fetch all configured products for one StatBank era."""
    session = requests.Session()
    session.headers.update({"User-Agent": "country_oil_scraper/1.0 (SSB petroleum sales)"})
    frames = [
        fetch_ssb_product_series(era, code, session=session)
        for code in era.product_codes
    ]
    frames = [f for f in frames if not f.empty]
    if not frames:
        return _empty_parse_frame()
    return pd.concat(frames, ignore_index=True)


def drop_superseded_legacy_natives(df: pd.DataFrame) -> pd.DataFrame:
    """
    Remove legacy coarse products when finer-era natives exist for the same month.

    ``merge_era_tables`` dedupes on (date, product_native) only. Legacy table
    03687 uses labels like ``Diesel`` while bridge table 11174 uses ``Auto
    diesel, dutiable`` — both survive the merge and double-count in canonical
    diesel panels for 2010–2016.
    """
    if df.empty:
        return df

    out = df.copy()
    drop_idx: list[int] = []
    for legacy_native, successors in LEGACY_SUPERSESSION:
        legacy_rows = out[out["product_native"] == legacy_native]
        if legacy_rows.empty:
            continue
        successor_dates = set(
            out.loc[out["product_native"].isin(successors), "date"].unique()
        )
        if not successor_dates:
            continue
        mask = legacy_rows["date"].isin(successor_dates)
        drop_idx.extend(legacy_rows.index[mask].tolist())

    if drop_idx:
        logger.info(
            "Dropped %d superseded legacy SSB rows (2010–2016 stitch fix)",
            len(drop_idx),
        )
        out = out.drop(index=drop_idx).reset_index(drop=True)
    return out


def merge_era_tables(parts: list[pd.DataFrame]) -> pd.DataFrame:
    """
    Merge era tables; higher ``ssb_priority`` wins for overlapping
    (date, product_native) keys.
    """
    merged: dict[tuple[pd.Timestamp, str], dict] = {}
    for part in parts:
        if part.empty:
            continue
        for rec in part.to_dict("records"):
            key = (rec["date"], rec["product_native"])
            existing = merged.get(key)
            if existing is None or rec["ssb_priority"] >= existing["ssb_priority"]:
                merged[key] = rec
    if not merged:
        return _empty_parse_frame()
    frame = pd.DataFrame(list(merged.values()))
    return drop_superseded_legacy_natives(frame)


def parse_table3_workbook(path: Path) -> pd.DataFrame:
    """
    Parse SSB Table 3 xlsx export (single-month snapshot or wide layout).

    Uses the petroleum-incl-bio column when three delivery columns exist.
    """
    path = Path(path)
    xl = pd.ExcelFile(path)
    sheet = xl.sheet_names[0]
    raw = pd.read_excel(path, sheet_name=sheet, header=None)

    # Detect month from header row (e.g. "May 2026" in column 1).
    month_label = None
    for val in raw.iloc[0].tolist():
        if isinstance(val, str) and re.search(r"\d{4}", val):
            month_label = val.strip()
            break
    if month_label is None:
        raise ValueError(f"Could not detect month label in {path.name}")

    dt = pd.to_datetime(month_label, format="%B %Y", errors="coerce")
    if pd.isna(dt):
        dt = pd.to_datetime(month_label, errors="coerce")
    if pd.isna(dt):
        raise ValueError(f"Unparseable month label {month_label!r} in {path.name}")

    header = raw.iloc[1].tolist()
    petroleum_col = None
    for idx, cell in enumerate(header):
        if cell is None or (isinstance(cell, float) and pd.isna(cell)):
            continue
        lower = str(cell).lower()
        if "incl. bio components" in lower or "inkl" in lower and "bio" in lower:
            petroleum_col = idx
            break
    if petroleum_col is None:
        petroleum_col = 2 if raw.shape[1] > 2 else 1

    rows: list[dict] = []
    for i in range(2, len(raw)):
        label = raw.iloc[i, 0]
        native = normalize_product_label(label)
        if native is None:
            continue
        val = pd.to_numeric(raw.iloc[i, petroleum_col], errors="coerce")
        if pd.isna(val):
            continue
        rows.append(
            {
                "date": pd.Timestamp(dt.year, dt.month, 1),
                "product_native": native,
                "value": float(val),
                "source_file": path.name,
                "ssb_table": TABLE_CURRENT,
                "ssb_era": "current",
                "ssb_priority": 3,
            }
        )
    return pd.DataFrame(rows)


def finalize_ssb_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Attach canonical metadata columns expected by the processor."""
    if df.empty:
        return pd.DataFrame(columns=CANONICAL_COLUMNS)

    out = df.copy()
    now = datetime.now(tz=UTC)
    out["country"] = COUNTRY_CODE
    out["country_name"] = COUNTRY_NAME
    out["source"] = SOURCE_ID
    out["metric_type"] = SSB_METRIC_TYPE
    out["product"] = out["product_native"]
    out["unit"] = SSB_UNIT_NATIVE
    out["is_provisional"] = True
    out["updated_at"] = now
    return out


def ssb_series_for_jodi(
    demand: pd.DataFrame,
    series_key: str,
    *,
    value_col: str = "value",
) -> pd.DataFrame:
    """Aggregate SSB natives for one JODI compare panel."""
    spec = JODI_COMPARE_SERIES[series_key]
    sl = demand[demand["product_native"].isin(spec.natives)]
    if sl.empty:
        return pd.DataFrame(columns=["date", value_col, "is_provisional"])
    return (
        sl.groupby(["date", "is_provisional"], as_index=False)[value_col]
        .sum()
        .sort_values("date")
    )


def coverage_by_series(demand: pd.DataFrame) -> pd.DataFrame:
    """First / last month and row count per product_native."""
    if demand.empty:
        return pd.DataFrame(
            columns=["product_native", "first_month", "last_month", "n_months"]
        )
    g = demand.groupby("product_native")["date"]
    return (
        g.agg(first_month="min", last_month="max", n_months="count")
        .reset_index()
        .sort_values("product_native")
    )


def seasonality_chart_inputs(
    demand: pd.DataFrame,
    demand_canonical: pd.DataFrame,
    *,
    view: str = "native",
    value_col: str = "value_kbd",
) -> tuple[pd.DataFrame, str, list[str], dict[str, str], str]:
    view = view.strip().lower()
    if view == "native":
        products = [p for p in CHART_PRODUCTS if p in demand["product_native"].values]
        df = demand[demand["product_native"].isin(products)].copy()
        labels = {p: DISPLAY_LABELS.get(p, p) for p in products}
        return df, "product_native", products, labels, "native products"
    if view == "canonical":
        products = [
            p for p in SEASONALITY_PANELS_CANONICAL if p in demand_canonical["panel"].values
        ]
        df = demand_canonical[demand_canonical["panel"].isin(products)].copy()
        return df, "panel", products, {p: p for p in products}, "canonical products"
    raise ValueError(f"view must be 'native' or 'canonical', got {view!r}")


def parse_ev_registrations_csv(text: str) -> pd.DataFrame:
    """Parse monthly Norway vehicle registrations from Robbie Andrew's CSV."""
    raw = pd.read_csv(io.StringIO(text))
    missing = set(_EV_CSV_COLUMNS) - set(raw.columns)
    if missing:
        raise ValueError(f"EV CSV missing columns: {sorted(missing)}")

    df = raw.rename(columns=_EV_CSV_COLUMNS).copy()
    df["date"] = pd.to_datetime(df["yyyymm"].astype(str), format="%Y%m", errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)

    numeric_cols = [c for c in df.columns if c not in {"yyyymm", "date"}]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    total = df["total_new"].replace(0, pd.NA)
    plug_in = df["bev_new"].fillna(0) + df["phev_new"].fillna(0)
    df["bev_share_new"] = df["bev_new"] / total
    df["phev_share_new"] = df["phev_new"] / total
    df["plugin_share_new"] = plug_in / total
    df["electrified_share_new"] = (
        plug_in + df["hybrid_new"].fillna(0)
    ) / total
    df["ice_share_new"] = (
        df["petrol_new"].fillna(0) + df["diesel_only_new"].fillna(0)
    ) / total

    # 3-month rolling mean — dampens Tesla delivery spikes (see EV page notes).
    for col in ("bev_share_new", "plugin_share_new", "total_new", "bev_new"):
        df[f"{col}_3m"] = df[col].rolling(3, min_periods=1).mean()

    df["source"] = EV_REGISTRATIONS_SOURCE
    return df


def load_ev_registrations(
    *,
    project_root: Path,
    refresh: bool = False,
    session: Optional[requests.Session] = None,
) -> pd.DataFrame:
    """Load EV registration CSV from cache or Robbie Andrew's GitHub pages."""
    cache_dir = Path(project_root) / "data" / "raw" / "norway" / "ev"
    cache_path = cache_dir / EV_REGISTRATIONS_CACHE_NAME
    cache_dir.mkdir(parents=True, exist_ok=True)

    if cache_path.exists() and not refresh:
        text = cache_path.read_text(encoding="utf-8")
    else:
        client = session or requests
        resp = client.get(EV_REGISTRATIONS_URL, timeout=120)
        resp.raise_for_status()
        text = resp.text
        cache_path.write_text(text, encoding="utf-8")
        logger.info("Cached EV registrations to %s", cache_path)

    return parse_ev_registrations_csv(text)


def road_fuel_series(
    demand: pd.DataFrame,
    *,
    value_col: str = "value_kbd",
) -> pd.DataFrame:
    """Monthly road gasoline + road auto diesel (kbd or native unit)."""
    sl = demand[demand["product_native"].isin(ROAD_FUEL_NATIVES)]
    if sl.empty:
        return pd.DataFrame(columns=["date", value_col, "is_provisional"])
    return (
        sl.groupby(["date", "is_provisional"], as_index=False)[value_col]
        .sum()
        .sort_values("date")
    )


def ev_road_fuel_panel(
    demand: pd.DataFrame,
    ev: pd.DataFrame,
    *,
    value_col: str = "value_kbd",
    from_date: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Join road fuel demand with EV registration shares on calendar month."""
    road = road_fuel_series(demand, value_col=value_col)
    if road.empty or ev.empty:
        return pd.DataFrame()

    panel = road.merge(ev, on="date", how="inner")
    start = from_date or EV_ANALYSIS_FROM
    panel = panel[panel["date"] >= start].sort_values("date").reset_index(drop=True)
    panel["road_fuel_yoy_pct"] = panel[value_col].pct_change(12) * 100
    panel["bev_share_yoy_pp"] = (panel["bev_share_new_3m"] - panel["bev_share_new_3m"].shift(12)) * 100
    return panel


def parse_ssb_fleet_csv(text: str) -> pd.DataFrame:
    """Parse SSB 07849 wide CSV — private-car fleet by fuel (year-end stock)."""
    raw = pd.read_csv(io.StringIO(text), sep=";", decimal=".")
    if raw.empty:
        return pd.DataFrame()

    fuel_col = next(c for c in raw.columns if "fuel" in c.lower())
    year_cols = [c for c in raw.columns if re.search(r"\d{4}", str(c))]
    if not year_cols:
        raise ValueError("SSB fleet CSV: no year columns found")

    long = raw.melt(
        id_vars=[fuel_col],
        value_vars=year_cols,
        var_name="year_label",
        value_name="fleet_count",
    )
    long["year"] = long["year_label"].str.extract(r"(\d{4})").astype(int)
    long["date"] = pd.to_datetime(long["year"].astype(str) + "-12-01")
    long["fuel"] = long[fuel_col].map(_FLEET_FUEL_LABELS).fillna(long[fuel_col])
    long["fleet_count"] = pd.to_numeric(long["fleet_count"], errors="coerce")
    long["vehicle_class"] = "private_car"
    long["source"] = SSB_FLEET_SOURCE
    return (
        long.dropna(subset=["fleet_count"])
        .sort_values(["date", "fuel"])
        .reset_index(drop=True)
    )


def enrich_fleet_composition(fleet: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Add fleet shares by year-end private-car stock."""
    if fleet.empty:
        return fleet, pd.DataFrame()

    totals = (
        fleet.groupby("date", as_index=False)["fleet_count"]
        .sum()
        .rename(columns={"fleet_count": "fleet_total"})
    )
    out = fleet.merge(totals, on="date", how="left")
    out["fleet_share"] = out["fleet_count"] / out["fleet_total"].replace(0, pd.NA)

    share_rows: list[dict] = []
    for date, grp in out.groupby("date"):
        total = float(grp["fleet_total"].iloc[0])
        if total == 0:
            continue
        bev = float(grp.loc[grp["fuel"] == "bev", "fleet_count"].sum())
        other = float(grp.loc[grp["fuel"] == "other_fuel", "fleet_count"].sum())
        share_rows.append(
            {
                "date": date,
                "fleet_total": total,
                "bev_share_fleet": bev / total,
                "plugin_share_fleet": (bev + other) / total,
            }
        )
    shares = pd.DataFrame(share_rows).sort_values("date").reset_index(drop=True)
    return out, shares


def load_norway_fleet_composition(
    *,
    project_root: Path,
    refresh: bool = False,
    session: Optional[requests.Session] = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Load SSB table 07849 private-car fleet by fuel (annual, year-end stock).

    Returns ``(fleet_long, fleet_shares)`` where ``fleet_shares`` has one row
    per year with ``bev_share_fleet`` and ``plugin_share_fleet``.
    """
    cache_dir = Path(project_root) / "data" / "raw" / "norway" / "fleet"
    cache_path = cache_dir / SSB_FLEET_CACHE_NAME
    cache_dir.mkdir(parents=True, exist_ok=True)

    if cache_path.exists() and not refresh:
        text = cache_path.read_text(encoding="utf-8")
    else:
        client = session or requests
        resp = client.get(SSB_FLEET_URL, timeout=120)
        resp.raise_for_status()
        text = resp.text
        cache_path.write_text(text, encoding="utf-8")
        logger.info("Cached SSB fleet composition to %s", cache_path)

    fleet = parse_ssb_fleet_csv(text)
    fleet, shares = enrich_fleet_composition(fleet)
    return fleet, shares


def fleet_to_monthly(shares: pd.DataFrame) -> pd.DataFrame:
    """Step year-end fleet shares onto each month of that calendar year."""
    if shares.empty:
        return pd.DataFrame()

    rows: list[dict] = []
    for rec in shares.to_dict("records"):
        year = pd.Timestamp(rec["date"]).year
        for month in range(1, 13):
            rows.append({**rec, "date": pd.Timestamp(year, month, 1)})
    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


def fleet_road_fuel_panel(
    demand: pd.DataFrame,
    fleet_shares: pd.DataFrame,
    *,
    value_col: str = "value_kbd",
    from_date: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Join road fuel demand with annual fleet BEV share (stepped monthly)."""
    road = road_fuel_series(demand, value_col=value_col)
    if road.empty or fleet_shares.empty:
        return pd.DataFrame()

    monthly_fleet = fleet_to_monthly(fleet_shares)
    panel = road.merge(
        monthly_fleet[["date", "bev_share_fleet", "plugin_share_fleet"]],
        on="date",
        how="inner",
    )
    start = from_date or EV_ANALYSIS_FROM
    panel = panel[panel["date"] >= start].sort_values("date").reset_index(drop=True)
    panel["road_fuel_yoy_pct"] = panel[value_col].pct_change(12) * 100
    panel["bev_share_fleet_yoy_pp"] = (
        panel["bev_share_fleet"] - panel["bev_share_fleet"].shift(12)
    ) * 100
    return panel


def _empty_parse_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "date",
            "product_native",
            "value",
            "source_file",
            "ssb_table",
            "ssb_era",
            "ssb_priority",
        ]
    )
