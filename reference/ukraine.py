"""
reference.ukraine
─────────────────
SSSU (State Statistics Service of Ukraine) — monthly fuel usage and reserves.

Dataflow ``DF_FUEL_USAGE_AND_RESERVES_M`` via SDMX API or Data Bank CSV export.
National ``Ukraine`` rows only; four petroleum products in kt.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import FrozenSet, Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

SSSU_AGENCY_SOURCE = "SSSU"
SSSU_DATASET_SOURCE = "ukraine_sssu_fuel_usage_and_reserves"
SSSU_DEMAND_METRIC = "TOTDEMO"
SSSU_STOCKS_METRIC = "CLOSTLV"
SSSU_UNIT_NATIVE = "kt"

COUNTRY_CODE = "UA"
COUNTRY_NAME = "Ukraine"
SOURCE_ID = SSSU_DATASET_SOURCE
JODI_REF_AREA = "UA"

DATAFLOW_ID = "DF_FUEL_USAGE_AND_RESERVES_M"
DATAFLOW_VERSION = "2.0.0"
DATAFLOW_AGENCY = "SSSU"

SDMX_DATA_URL = (
    "https://stat.gov.ua/sdmx/workspaces/default:integration/registry/sdmx/3.0/"
    f"data/dataflow/{DATAFLOW_AGENCY}/{DATAFLOW_ID}/{DATAFLOW_VERSION}/*"
)
SDMX_CSV_ACCEPT = (
    "application/vnd.sdmx.data+csv;version=2.0.0;"
    "labels=both;timeFormat=original;keys=both"
)

RAW_FILENAME = "fuel_usage_and_reserves_sdmx.csv"
NATIONAL_REGION = "Ukraine"

INDICATOR_DEMAND = "Fuel used"
INDICATOR_STOCKS = "Fuel reserves at the end of the reporting month"

INDICATOR_TO_METRIC: dict[str, str] = {
    INDICATOR_DEMAND: SSSU_DEMAND_METRIC,
    INDICATOR_STOCKS: SSSU_STOCKS_METRIC,
}

PETROLEUM_PRODUCTS: frozenset[str] = frozenset(
    {
        "Motor gasoline",
        "Gas diesel",
        "Liquefied petroleum gases (LPG)",
        "Fuel oil",
    }
)

# SSSU flags that mean no reliable numeric observation — drop the value.
SUPPRESSED_OBS_FLAGS: frozenset[str] = frozenset(
    {
        "Confidential statistical information",
        "Not observed",
    }
)

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

DISPLAY_LABELS: dict[str, str] = {
    "Motor gasoline": "Gasoline",
    "Gas diesel": "Diesel",
    "Liquefied petroleum gases (LPG)": "LPG",
    "Fuel oil": "Fuel oil",
}

CHART_PRODUCTS: tuple[str, ...] = tuple(PETROLEUM_PRODUCTS)

DELIVERY_HEADLINE_NATIVE: frozenset[str] = frozenset(PETROLEUM_PRODUCTS)

UNITS_KIND: dict[str, str] = {
    "Motor gasoline": "gasoline",
    "Gas diesel": "diesel",
    "Liquefied petroleum gases (LPG)": "lpg",
    "Fuel oil": "fuel_oil",
}

SEASONALITY_PANELS_CANONICAL: tuple[str, ...] = (
    "Gasoline",
    "Diesel",
    "LPG",
    "Fuel oil",
)


@dataclass(frozen=True)
class JodiCompareSeries:
    key: str
    jodi_energy_product: str
    panel: str
    natives: FrozenSet[str]


JODI_COMPARE_SERIES: dict[str, JodiCompareSeries] = {
    "gasoline": JodiCompareSeries(
        "gasoline", "GASOLINE", "Gasoline", frozenset({"Motor gasoline"})
    ),
    "diesel": JodiCompareSeries(
        "diesel", "GASDIES", "Diesel", frozenset({"Gas diesel"})
    ),
    "lpg": JodiCompareSeries(
        "lpg", "LPG", "LPG", frozenset({"Liquefied petroleum gases (LPG)"})
    ),
    "fuel_oil": JodiCompareSeries(
        "fuel_oil", "RESFUEL", "Fuel oil", frozenset({"Fuel oil"})
    ),
}

JODI_COMPARE_PANEL_ORDER: tuple[str, ...] = (
    "Gasoline",
    "Diesel",
    "LPG",
    "Fuel oil",
)
JODI_STOCKS_PANEL_ORDER: tuple[str, ...] = JODI_COMPARE_PANEL_ORDER

# Documented reporting break — demand has no national rows in this window.
WAR_DEMAND_GAP_START = pd.Timestamp("2022-02-01")
WAR_DEMAND_GAP_END = pd.Timestamp("2024-12-01")

_TIME_PERIOD_RE = re.compile(r"^(\d{4})-M(\d{2})$")
_SDMX_LABEL_RE = re.compile(r"^[^:]+: (.+)$")

# Wide Data Bank export uses these column names (Explorer CSV).
_WIDE_META_COLS = {
    "Indicator",
    "Region",
    "Fuel type",
    "Unit of measure",
    "Frequency",
    "Scaling",
    "Decimals displayed",
    "Observation flag",
    "Dataset notes",
    "Timeseries notes",
    "Observation notes",
}


def parse_sdmx_label(value: object) -> Optional[str]:
    """Extract human label from SDMX ``code: Label`` cells."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if not text:
        return None
    match = _SDMX_LABEL_RE.match(text)
    return match.group(1) if match else text


def parse_time_period(period: str) -> pd.Timestamp:
    """``2021-M01`` → first day of month."""
    match = _TIME_PERIOD_RE.match(str(period).strip())
    if not match:
        raise ValueError(f"Unrecognised SSSU time period: {period!r}")
    year, month = int(match.group(1)), int(match.group(2))
    return pd.Timestamp(year=year, month=month, day=1)


def is_suppressed_flag(flag: object) -> bool:
    if flag is None or (isinstance(flag, float) and pd.isna(flag)):
        return False
    return str(flag).strip() in SUPPRESSED_OBS_FLAGS


def is_wide_export_csv(path: Path) -> bool:
    """True for Data Bank wide pivot exports (month columns)."""
    with path.open(encoding="utf-8-sig", newline="") as fh:
        header = fh.readline()
    return "Indicator" in header and "Region" in header and "202" in header


def fetch_sdmx_csv(*, session: Optional[requests.Session] = None) -> str:
    """Download full dataflow as SDMX-CSV text."""
    session = session or requests.Session()
    logger.info("Fetching SSSU %s from SDMX API", DATAFLOW_ID)
    response = session.get(
        SDMX_DATA_URL,
        headers={"Accept": SDMX_CSV_ACCEPT},
        timeout=180,
    )
    response.raise_for_status()
    response.encoding = "utf-8"
    return response.text


def save_sdmx_snapshot(text: str, dest: Path) -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    return dest


def _partial_from_long_rows(rows: pd.DataFrame) -> pd.DataFrame:
    """Shared filter + typing for SDMX-long and melted wide rows."""
    if rows.empty:
        return pd.DataFrame(
            columns=["date", "metric_type", "product_native", "value", "observation_flag"]
        )

    work = rows.copy()
    work["indicator"] = work["indicator"].astype(str).str.strip()
    work["region"] = work["region"].astype(str).str.strip()
    work["fuel_type"] = work["fuel_type"].astype(str).str.strip()
    work = work[work["region"] == NATIONAL_REGION]
    work = work[work["fuel_type"].isin(PETROLEUM_PRODUCTS)]
    work = work[work["indicator"].isin(INDICATOR_TO_METRIC)]

    work["metric_type"] = work["indicator"].map(INDICATOR_TO_METRIC)
    work["product_native"] = work["fuel_type"]
    work["date"] = work["time_period"].map(parse_time_period)

    if "observation_flag" not in work.columns:
        work["observation_flag"] = pd.NA

    suppressed = work["observation_flag"].map(is_suppressed_flag)
    work["value"] = pd.to_numeric(work["value"], errors="coerce")
    work.loc[suppressed, "value"] = pd.NA
    work = work.dropna(subset=["value"])
    return work[["date", "metric_type", "product_native", "value"]].copy()


def parse_sdmx_csv_text(text: str) -> pd.DataFrame:
    """Parse SDMX-CSV API response (skip structure header rows)."""
    lines = text.splitlines()
    if len(lines) < 3:
        return _partial_from_long_rows(pd.DataFrame())

    header_names = [part.split(":")[0] for part in lines[0].split(",")]
    raw = pd.read_csv(
        pd.io.common.StringIO("\n".join(lines[2:])),
        header=None,
        names=header_names,
        dtype=str,
        keep_default_na=False,
    )

    obs_flag = (
        raw["OBS_FLAG"].replace("", pd.NA)
        if "OBS_FLAG" in raw.columns
        else pd.Series(pd.NA, index=raw.index)
    )
    rows = pd.DataFrame(
        {
            "indicator": raw["INDICATOR"].map(parse_sdmx_label),
            "region": raw["REGION"].map(parse_sdmx_label),
            "fuel_type": raw["FUEL_TYPE"].map(parse_sdmx_label),
            "time_period": raw["TIME_PERIOD"],
            "value": raw["OBS_VALUE"].replace("", pd.NA),
            "observation_flag": obs_flag,
        }
    )
    return _partial_from_long_rows(rows)


def parse_wide_csv(path: Path) -> pd.DataFrame:
    """Parse Data Bank wide export (one row per series, month columns)."""
    df = pd.read_csv(path, encoding="utf-8-sig")
    date_cols = [c for c in df.columns if c not in _WIDE_META_COLS]

    melted = df.melt(
        id_vars=list(_WIDE_META_COLS & set(df.columns)),
        value_vars=date_cols,
        var_name="time_period",
        value_name="value",
    )
    rows = pd.DataFrame(
        {
            "indicator": melted["Indicator"],
            "region": melted["Region"],
            "fuel_type": melted["Fuel type"],
            "time_period": melted["time_period"],
            "value": melted["value"].replace("", pd.NA),
            "observation_flag": melted.get("Observation flag", pd.NA),
        }
    )
    return _partial_from_long_rows(rows)


def finalize_ukraine_frame(
    partial: pd.DataFrame,
    *,
    updated_at: datetime,
    source_file: str,
) -> pd.DataFrame:
    """Attach country metadata and canonical column order."""
    if partial.empty:
        out = pd.DataFrame(columns=CANONICAL_COLUMNS)
        return out

    out = partial.copy()
    out["country"] = COUNTRY_CODE
    out["country_name"] = COUNTRY_NAME
    out["source"] = SOURCE_ID
    out["product"] = out["product_native"]
    out["unit"] = SSSU_UNIT_NATIVE
    out["is_provisional"] = False
    out["source_file"] = source_file
    out["updated_at"] = updated_at
    return out[CANONICAL_COLUMNS].sort_values(
        ["date", "metric_type", "product_native"], ignore_index=True
    )


def sssu_series_for_jodi(
    df: pd.DataFrame,
    key: str,
    *,
    value_col: str = "value_kbd",
) -> pd.DataFrame:
    """Roll native rows to one monthly series for JODI overlay charts."""
    spec = JODI_COMPARE_SERIES[key]
    sl = df[df["product_native"].isin(spec.natives)]
    if sl.empty:
        return pd.DataFrame(columns=["date", value_col])
    return (
        sl.groupby("date", as_index=False)[value_col]
        .sum()
        .sort_values("date")
    )


def coverage_by_series(df: pd.DataFrame) -> pd.DataFrame:
    """First/last month and month count per metric × product."""
    rows: list[dict[str, object]] = []
    for (metric, product), group in df.groupby(["metric_type", "product_native"]):
        dates = group["date"].sort_values()
        rows.append(
            {
                "metric_type": metric,
                "product_native": product,
                "label": DISPLAY_LABELS.get(product, product),
                "first_month": dates.min(),
                "last_month": dates.max(),
                "n_months": len(group),
            }
        )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    metric_order = {SSSU_DEMAND_METRIC: 0, SSSU_STOCKS_METRIC: 1}
    out["_sort"] = out["metric_type"].map(metric_order)
    return out.sort_values(["_sort", "label"]).drop(columns="_sort").reset_index(drop=True)


def seasonality_chart_inputs(
    demand: pd.DataFrame,
    demand_canonical: pd.DataFrame,
    *,
    view: str,
    value_col: str = "value_kbd",
) -> tuple[pd.DataFrame, str, tuple[str, ...], dict[str, str], str]:
    """Inputs for ``seasonality_by_year_chart`` (native or canonical)."""
    if view == "canonical":
        season_df = demand_canonical.copy()
        product_col = "panel"
        products = tuple(
            p for p in SEASONALITY_PANELS_CANONICAL if p in set(season_df["panel"])
        )
        labels = {p: p for p in products}
        suffix = "canonical"
    else:
        season_df = demand[demand["product_native"].isin(CHART_PRODUCTS)].copy()
        product_col = "product_native"
        products = CHART_PRODUCTS
        labels = DISPLAY_LABELS
        suffix = "native"
    season_df = season_df.rename(columns={value_col: value_col})
    return season_df, product_col, products, labels, suffix


def parse_raw_csv(
    path: Path,
    *,
    updated_at: datetime | None = None,
) -> pd.DataFrame:
    """Parse either wide Data Bank export or SDMX-long snapshot."""
    path = Path(path)
    ts = updated_at or datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    if is_wide_export_csv(path):
        partial = parse_wide_csv(path)
    else:
        partial = parse_sdmx_csv_text(path.read_text(encoding="utf-8-sig"))
    return finalize_ukraine_frame(partial, updated_at=ts, source_file=path.name)
