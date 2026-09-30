"""
Build Eurostat nrg_stk_oilm closing-stock parquets (master + per-country).

Closing flows only (``STK_CL`` + ``STKCL_*``); openings omitted.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from reference.eurostat_oilm import (
    EUROSTAT_STOCKS_METRIC,
    EUROSTAT_STOCKS_SOURCE,
    EUROSTAT_UNIT_NATIVE,
    GEO_CATALOG,
    MASTER_STOCKS_PARQUET_REL,
    NATIONAL_PRIMARY_IDS,
    SKIP_GEOS,
    SIEC_TO_CANONICAL,
    STORED_STOCK_SIEC,
    fetch_stk_cl_geos,
)
from reference.loaders import canonical_subcategory

logger = logging.getLogger(__name__)

_PRODUCT_MAP_SOURCE = "Eurostat"

COLUMN_ORDER: list[str] = [
    "date",
    "country",
    "country_name",
    "country_id",
    "geo",
    "source",
    "metric_type",
    "product_native",
    "product",
    "siec",
    "stk_flow",
    "stk_flow_label",
    "stock_bucket",
    "value",
    "unit",
    "product_canonical",
    "category",
    "is_provisional",
    "source_file",
    "updated_at",
]


def build_stocks_from_eurostat_api(
    *,
    geos: Optional[list[str]] = None,
    start: str = "2013-01",
) -> pd.DataFrame:
    if geos is None:
        geos = [g for g in GEO_CATALOG if g not in SKIP_GEOS]
    raw = fetch_stk_cl_geos(geos, start=start)
    if raw.empty:
        raise ValueError("Eurostat returned no closing-stock rows")

    raw = raw[raw["siec"].isin(STORED_STOCK_SIEC)].copy()
    raw = raw.dropna(subset=["value_ths_t"])
    now = datetime.now(tz=UTC)
    rows = []
    for geo, sl in raw.groupby("geo"):
        geo = str(geo).upper()
        if geo in SKIP_GEOS or geo not in GEO_CATALOG:
            continue
        country_id, display = GEO_CATALOG[geo]
        part = sl.copy()
        part["country"] = geo
        part["country_name"] = display
        part["country_id"] = country_id
        part["geo"] = geo
        part["source"] = EUROSTAT_STOCKS_SOURCE
        part["metric_type"] = EUROSTAT_STOCKS_METRIC
        # Unique native key so closing splits do not collide in the warehouse.
        part["product_native"] = part["stk_flow"].astype(str) + "|" + part["siec"].astype(str)
        part["product"] = part["siec_label"]
        part["value"] = part["value_ths_t"]
        part["unit"] = EUROSTAT_UNIT_NATIVE
        part["is_provisional"] = False
        part["source_file"] = f"eurostat/nrg_stk_oilm/{geo}"
        part["updated_at"] = now
        canon = []
        for siec in part["siec"].astype(str):
            try:
                sub = canonical_subcategory(siec, source=_PRODUCT_MAP_SOURCE)
            except KeyError:
                sub = None
            if not sub or sub == "-":
                sub = SIEC_TO_CANONICAL.get(siec)
            canon.append(sub)
        part["product_canonical"] = canon
        part["category"] = part["stock_bucket"]
        rows.append(part)

    if not rows:
        raise ValueError("No Eurostat stock rows after geo/product filter")

    df = pd.concat(rows, ignore_index=True)
    df = _sort_and_clean(df)
    logger.info(
        "Built %s Eurostat stock rows, geos=%s, flows=%s, %s -> %s",
        f"{len(df):,}",
        df["geo"].nunique(),
        df["stk_flow"].nunique(),
        df["date"].min(),
        df["date"].max(),
    )
    return df


def _sort_and_clean(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"]).dt.normalize()
    for col in COLUMN_ORDER:
        if col not in out.columns:
            out[col] = None
    out = out[COLUMN_ORDER]
    out = out.dropna(subset=["date", "product_native", "value"])
    return out.sort_values(
        ["country", "date", "stk_flow", "siec"]
    ).reset_index(drop=True)


def save_stocks(df: pd.DataFrame, processed_root: Path) -> dict[str, Path]:
    processed_root = Path(processed_root)
    paths: dict[str, Path] = {}

    master = processed_root / MASTER_STOCKS_PARQUET_REL
    master.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(master, index=False)
    paths["master"] = master
    logger.info("Saved stocks master %s (%s rows)", master, f"{len(df):,}")

    for country_id, sl in df.groupby("country_id"):
        rel = f"{country_id}/{country_id}_eurostat_oilm_stocks.parquet"
        path = processed_root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        sl.to_parquet(path, index=False)
        paths[str(country_id)] = path
        logger.info(
            "Saved stocks %s (%s rows)%s",
            path,
            f"{len(sl):,}",
            " [companion]" if country_id in NATIONAL_PRIMARY_IDS else "",
        )
    return paths
