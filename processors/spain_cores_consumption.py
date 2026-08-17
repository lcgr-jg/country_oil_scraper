"""
Processor for CORES petroleum product consumption (Spain).
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Optional

import pandas as pd

from reference.loaders import canonical_category, canonical_subcategory
from reference.spain import CANONICAL_COLUMNS, CORES_AGENCY_SOURCE
from scrapers.spain_cores import SpainCoresScraper

logger = logging.getLogger(__name__)

_PRODUCT_MAP_SOURCE = CORES_AGENCY_SOURCE

COLUMN_ORDER: list[str] = CANONICAL_COLUMNS + [
    "product_canonical",
    "category",
]

KEY_COLS: list[str] = [
    "date",
    "country",
    "source",
    "metric_type",
    "product_native",
]

PARQUET_FILENAME = "spain_cores_consumption.parquet"
SQLITE_FILENAME = "spain_cores_consumption.db"
SQLITE_TABLE = "cores_consumption"


def build_from_historical(raw_path: Path) -> pd.DataFrame:
    """Bootstrap from a single oil-products-consumption.xlsx."""
    raw_path = Path(raw_path)
    data_dir = raw_path.parents[2]
    scraper = SpainCoresScraper(data_dir=data_dir)
    logger.info("Building Spain CORES DB from %s", raw_path)
    df = scraper.parse("petroleum_consumption", raw_path)
    df = _sort_and_clean(df)
    logger.info(
        "Built %s rows, %s -> %s, %s products",
        f"{len(df):,}",
        df["date"].min(),
        df["date"].max(),
        df["product_native"].nunique(),
    )
    return df


def load(output_dir: Path) -> Optional[pd.DataFrame]:
    parquet_path = Path(output_dir) / PARQUET_FILENAME
    if not parquet_path.exists():
        logger.info(
            "No existing DB at %s — first run? Use --bootstrap.",
            parquet_path,
        )
        return None
    df = pd.read_parquet(parquet_path)
    logger.info(
        "Loaded %s rows (%s -> %s)",
        f"{len(df):,}",
        df["date"].min(),
        df["date"].max(),
    )
    return df


def upsert(
    existing_df: Optional[pd.DataFrame],
    new_df: pd.DataFrame,
) -> pd.DataFrame:
    if existing_df is None or len(existing_df) == 0:
        return _sort_and_clean(new_df)

    new_keys = pd.MultiIndex.from_frame(new_df[KEY_COLS])
    existing_keys = pd.MultiIndex.from_frame(existing_df[KEY_COLS])
    keep_mask = ~existing_keys.isin(new_keys)
    rows_replaced = int((~keep_mask).sum())
    rows_added = len(new_df) - rows_replaced

    combined = pd.concat(
        [existing_df.loc[keep_mask], new_df],
        ignore_index=True,
    )
    logger.info(
        "Upsert: %s replaced, %s appended",
        f"{rows_replaced:,}",
        f"{rows_added:,}",
    )
    return _sort_and_clean(combined)


def save(
    df: pd.DataFrame,
    output_dir: Path,
    write_sqlite: bool = False,
) -> dict[str, Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    parquet_path = output_dir / PARQUET_FILENAME
    df_pq = df.copy()
    df_pq["date"] = pd.to_datetime(df_pq["date"])
    df_pq.to_parquet(parquet_path, index=False, compression="snappy")
    logger.info(
        "Saved parquet: %s (%.1f KB)",
        parquet_path,
        parquet_path.stat().st_size / 1024,
    )
    paths: dict[str, Path] = {"parquet": parquet_path}

    if write_sqlite:
        sqlite_path = output_dir / SQLITE_FILENAME
        df_sql = df.copy()
        df_sql["date"] = df_sql["date"].astype(str)
        df_sql["updated_at"] = df_sql["updated_at"].astype(str)
        df_sql["is_provisional"] = df_sql["is_provisional"].astype(int)
        with sqlite3.connect(sqlite_path) as conn:
            df_sql.to_sql(SQLITE_TABLE, conn, if_exists="replace", index=False)
        paths["sqlite"] = sqlite_path

    return paths


def _sort_and_clean(df: pd.DataFrame) -> pd.DataFrame:
    df = _derive_canonical_columns(df)
    for col in COLUMN_ORDER:
        if col not in df.columns:
            df = df.copy()
            df[col] = pd.NA
    return df[COLUMN_ORDER].sort_values(
        ["date", "product_native"], ignore_index=True
    )


def _derive_canonical_columns(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        for col in ("product_canonical", "category"):
            if col not in df.columns:
                df[col] = pd.Series(dtype="object")
        return df

    df = df.copy()
    unknown: list[str] = []
    canon_map: dict[str, Optional[str]] = {}
    cat_map: dict[str, Optional[str]] = {}

    for name in df["product_native"].dropna().unique():
        try:
            canon_map[name] = canonical_subcategory(name, source=_PRODUCT_MAP_SOURCE)
            cat_map[name] = canonical_category(name, source=_PRODUCT_MAP_SOURCE)
        except KeyError:
            unknown.append(name)
            canon_map[name] = None
            cat_map[name] = None

    if unknown:
        logger.warning(
            "  %d Spain product_native label(s) missing from product_map.csv: %s",
            len(unknown),
            sorted(unknown),
        )

    df["product_canonical"] = df["product_native"].map(canon_map)
    df["category"] = df["product_native"].map(cat_map)
    return df
