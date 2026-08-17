"""
reference.hungary
─────────────────
MEKH (Hungarian Energy and Public Utility Regulatory Authority) — monthly
oil balance and closing stocks via public OData.

Demand: ``HaviOlajMerleg`` flow ``GDINCTRO`` (Gross inland deliveries, Observed).
Stocks: ``HaviOlajKeszlet`` flow ``CSNATTER`` (Closing stock — national territory).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, FrozenSet, Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

MEKH_AGENCY_SOURCE = "MEKH"
MEKH_DATASET_SOURCE = "hungary_mekh_oil_balance"
MEKH_METRIC_TYPE = "TOTDEMO"
MEKH_STOCKS_METRIC = "CLOSTLV"
MEKH_UNIT_NATIVE = "kt"

COUNTRY_CODE = "HU"
COUNTRY_NAME = "Hungary"
SOURCE_ID = MEKH_DATASET_SOURCE
JODI_REF_AREA = "HU"

ODATA_BASE = "https://stattab.mekh.hu/odata/v4/public"
ODATA_ENTITY_DEMAND = "HaviOlajMerleg"
ODATA_ENTITY_STOCKS = "HaviOlajKeszlet"
GID_OBSERVED_FLOW = "GDINCTRO"
CLOSING_STOCK_FLOW = "CSNATTER"
ODATA_PAGE_SIZE = 5000

DEMAND_RAW_FILENAME = "gid_observed_odata.json"
STOCKS_RAW_FILENAME = "closing_stock_odata.json"

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

PRODUCT_CODE_TO_NATIVE: dict[str, str] = {
    "NGL": "Natural gas liquids",
    "NGL2": "Natural gas liquids",
    "LPG": "LPG",
    "NAPHTHA": "Naphtha",
    "MOTORGAS": "Total motor gasoline",
    "JETKERO": "Kerosene type jet fuel",
    "GASDIES": "Total gas/diesel oil",
    "RESFUEL": "Fuel oil",
    "REFINGAS": "Refinery gas",
    "PETCOKE": "Petroleum coke",
    "OPRODS": "Other products",
}

_COMPONENT_TO_PARENT: dict[str, str] = {
    "NONBIOGASO": "MOTORGAS",
    "BIOGASOL": "MOTORGAS",
    "NONBIOJETK": "JETKERO",
    "BIOJETKERO": "JETKERO",
    "NONBIODIES": "GASDIES",
    "BIODIESEL": "GASDIES",
    "HIGHSULF": "RESFUEL",
    "LOWSULF": "RESFUEL",
}

STORED_NATIVES: tuple[str, ...] = tuple(sorted(set(PRODUCT_CODE_TO_NATIVE.values())))

DELIVERY_HEADLINE_NATIVE: frozenset[str] = frozenset(
    n for n in STORED_NATIVES if n != "Refinery gas"
)

CHART_PRODUCTS: tuple[str, ...] = tuple(
    p for p in STORED_NATIVES if p != "Refinery gas"
)

DISPLAY_LABELS: dict[str, str] = {
    "Natural gas liquids": "NGL",
    "LPG": "LPG",
    "Naphtha": "Naphtha",
    "Total motor gasoline": "Gasoline",
    "Kerosene type jet fuel": "Jet fuel",
    "Total gas/diesel oil": "Diesel",
    "Fuel oil": "Fuel oil",
    "Refinery gas": "Refinery gas",
    "Petroleum coke": "Petcoke",
    "Other products": "Others",
}

UNITS_KIND: dict[str, str] = {
    "Natural gas liquids": "lpg",
    "LPG": "lpg",
    "Naphtha": "naphtha",
    "Total motor gasoline": "gasoline",
    "Kerosene type jet fuel": "jet",
    "Total gas/diesel oil": "diesel",
    "Fuel oil": "fuel_oil",
    "Refinery gas": "other",
    "Petroleum coke": "other",
    "Other products": "other",
}

SEASONALITY_PANELS_CANONICAL: tuple[str, ...] = (
    "Gasoline",
    "Diesel",
    "Jet Fuel",
    "LPG",
    "Naphtha",
    "Fuel Oil",
    "Petcoke",
    "Others",
)


@dataclass(frozen=True)
class JodiCompareSeries:
    key: str
    jodi_energy_product: str
    panel: str
    natives: FrozenSet[str]
    mode: str = "reporting"


GASOLINE_JODI_NATIVES: frozenset[str] = frozenset({"Total motor gasoline"})
DIESEL_JODI_NATIVES: frozenset[str] = frozenset({"Total gas/diesel oil"})
JET_JODI_NATIVES: frozenset[str] = frozenset({"Kerosene type jet fuel"})
LPG_JODI_NATIVES: frozenset[str] = frozenset({"Natural gas liquids", "LPG"})
NAPHTHA_JODI_NATIVES: frozenset[str] = frozenset({"Naphtha"})
FUEL_OIL_JODI_NATIVES: frozenset[str] = frozenset({"Fuel oil"})
OTHERS_JODI_NATIVES: frozenset[str] = frozenset({"Petroleum coke", "Other products"})

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
    "others": JodiCompareSeries(
        "others", "ONONSPEC", "Others", OTHERS_JODI_NATIVES
    ),
}

JODI_COMPARE_PANEL_ORDER: tuple[str, ...] = (
    "Gasoline",
    "Diesel",
    "Jet fuel",
    "LPG",
    "Naphtha",
    "Fuel oil",
    "Others",
)

JODI_STOCKS_COMPARE_SERIES: dict[str, JodiCompareSeries] = JODI_COMPARE_SERIES
JODI_STOCKS_PANEL_ORDER: tuple[str, ...] = JODI_COMPARE_PANEL_ORDER


def _parent_code(product_code: str) -> Optional[str]:
    if product_code in PRODUCT_CODE_TO_NATIVE:
        return product_code
    return _COMPONENT_TO_PARENT.get(product_code)


def fetch_odata_rows(
    entity: str,
    *,
    flow_filter: str,
    session: Optional[requests.Session] = None,
) -> list[dict[str, Any]]:
    """Paginated OData fetch (MEKH caps pages at 5000 without nextLink)."""
    session = session or requests.Session()
    headers = {"Accept": "application/json;odata.metadata=none"}
    url = f"{ODATA_BASE}/{entity}"
    params: dict[str, str] | None = {
        "$filter": flow_filter,
        "$select": "date,dimension_1,dimension_2,value_1",
        "$top": str(ODATA_PAGE_SIZE),
        "$skip": "0",
    }
    out: list[dict[str, Any]] = []
    page = 0
    while True:
        page += 1
        resp = session.get(url, params=params, headers=headers, timeout=120)
        resp.raise_for_status()
        chunk = resp.json().get("value", [])
        if not chunk:
            break
        out.extend(chunk)
        logger.info(
            "MEKH OData %s page %d: +%d rows (total %d)",
            entity,
            page,
            len(chunk),
            len(out),
        )
        if len(chunk) < ODATA_PAGE_SIZE:
            break
        assert params is not None
        params["$skip"] = str(len(out))
    return out


def fetch_gid_observed_rows(
    *,
    session: Optional[requests.Session] = None,
) -> list[dict[str, Any]]:
    return fetch_odata_rows(
        ODATA_ENTITY_DEMAND,
        flow_filter=f"startswith(dimension_1,'{GID_OBSERVED_FLOW}')",
        session=session,
    )


def fetch_closing_stock_rows(
    *,
    session: Optional[requests.Session] = None,
) -> list[dict[str, Any]]:
    # ``eq`` filter fails on this OData endpoint; ``startswith`` is exact here.
    return fetch_odata_rows(
        ODATA_ENTITY_STOCKS,
        flow_filter=f"startswith(dimension_1,'{CLOSING_STOCK_FLOW}')",
        session=session,
    )


def _rollup_to_natives(
    raw: pd.DataFrame,
    *,
    expected_flow: str,
) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame(columns=["date", "product_native", "value"])

    if not raw["dimension_1"].eq(expected_flow).all():
        bad = raw.loc[~raw["dimension_1"].eq(expected_flow), "dimension_1"].unique()
        raise ValueError(f"Unexpected MEKH flow codes: {bad!r}")

    raw = raw.copy()
    raw["parent_code"] = raw["dimension_2"].map(_parent_code)
    unknown = sorted(raw.loc[raw["parent_code"].isna(), "dimension_2"].unique())
    if unknown:
        logger.warning("Ignoring unknown MEKH product codes: %s", unknown)
    raw = raw.dropna(subset=["parent_code", "value_1"])
    if raw.empty:
        return pd.DataFrame(columns=["date", "product_native", "value"])

    rolled = (
        raw.groupby(["date", "parent_code"], as_index=False)["value_1"]
        .sum()
        .rename(columns={"value_1": "value"})
    )
    rolled["product_native"] = rolled["parent_code"].map(PRODUCT_CODE_TO_NATIVE)
    rolled = (
        rolled.groupby(["date", "product_native"], as_index=False)["value"]
        .sum()
    )
    rolled["date"] = pd.to_datetime(rolled["date"])
    return rolled[["date", "product_native", "value"]].sort_values(
        ["date", "product_native"], ignore_index=True
    )


def parse_demand_odata_records(records: list[dict[str, Any]]) -> pd.DataFrame:
    if not records:
        return pd.DataFrame(columns=["date", "product_native", "value"])
    return _rollup_to_natives(pd.DataFrame(records), expected_flow=GID_OBSERVED_FLOW)


def parse_stocks_odata_records(records: list[dict[str, Any]]) -> pd.DataFrame:
    if not records:
        return pd.DataFrame(columns=["date", "product_native", "value"])
    return _rollup_to_natives(pd.DataFrame(records), expected_flow=CLOSING_STOCK_FLOW)


def parse_odata_records(records: list[dict[str, Any]]) -> pd.DataFrame:
    """Backward-compatible alias for demand parsing."""
    return parse_demand_odata_records(records)


def parse_odata_json(raw_path: Path) -> pd.DataFrame:
    return parse_demand_odata_json(raw_path)


def parse_demand_odata_json(raw_path: Path) -> pd.DataFrame:
    records = _load_snapshot_records(raw_path)
    return parse_demand_odata_records(records)


def parse_stocks_odata_json(raw_path: Path) -> pd.DataFrame:
    records = _load_snapshot_records(raw_path)
    return parse_stocks_odata_records(records)


def finalize_mekh_frame(
    partial: pd.DataFrame,
    *,
    updated_at: datetime,
    source_file: str,
    country: str = COUNTRY_CODE,
    country_name: str = COUNTRY_NAME,
    source: str = MEKH_DATASET_SOURCE,
    metric_type: str = MEKH_METRIC_TYPE,
    unit: str = MEKH_UNIT_NATIVE,
) -> pd.DataFrame:
    if partial.empty:
        return pd.DataFrame(columns=CANONICAL_COLUMNS)

    df = partial.copy()
    latest = df["date"].max()
    df["country"] = country
    df["country_name"] = country_name
    df["source"] = source
    df["metric_type"] = metric_type
    df["product"] = df["product_native"]
    df["unit"] = unit
    df["is_provisional"] = df["date"].eq(latest)
    df["source_file"] = source_file
    df["updated_at"] = updated_at
    return df[CANONICAL_COLUMNS].sort_values(
        ["date", "product_native"], ignore_index=True
    )


def save_odata_snapshot(
    records: list[dict[str, Any]],
    dest: Path,
    *,
    entity: str,
    flow: str,
    downloaded_at: Optional[datetime] = None,
) -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "entity": entity,
        "flow": flow,
        "downloaded_at": (downloaded_at or datetime.now(UTC)).isoformat(),
        "records": records,
    }
    dest.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return dest


def _load_snapshot_records(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    records = payload.get("records", payload)
    if not isinstance(records, list):
        raise ValueError(f"Expected list of OData rows in {path}")
    return records


def load_odata_snapshot(path: Path) -> list[dict[str, Any]]:
    return _load_snapshot_records(path)


def mekh_series_for_jodi(
    frame: pd.DataFrame,
    series_key: str,
    *,
    value_col: str = "value",
) -> pd.DataFrame:
    spec = JODI_COMPARE_SERIES[series_key]
    sl = frame[frame["product_native"].isin(spec.natives)]
    if sl.empty:
        return pd.DataFrame(columns=["date", value_col, "is_provisional"])
    return (
        sl.groupby(["date", "is_provisional"], as_index=False)[value_col]
        .sum()
        .sort_values("date")
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
