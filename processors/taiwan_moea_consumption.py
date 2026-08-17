"""
Processor for Taiwan MOEA Table 5-04 petroleum product consumption.

  scrapers/taiwan_moea.py  ->  parse raw xlsx
  THIS FILE                ->  upsert + parquet persistence + canonical columns
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Optional

import pandas as pd

from reference.loaders import canonical_category, canonical_subcategory
from reference.taiwan import MOEA_AGENCY_SOURCE
from scrapers.taiwan_moea import CANONICAL_COLUMNS

logger = logging.getLogger(__name__)

_PRODUCT_MAP_SOURCE = MOEA_AGENCY_SOURCE

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

PARQUET_FILENAME = "taiwan_moea_consumption.parquet"
SQLITE_FILENAME = "taiwan_moea_consumption.db"
SQLITE_TABLE = "moea_consumption"


def build_from_historical(raw_path: Path) -> pd.DataFrame:
    """Bootstrap from a single 5-04 workbook (annual imputed + monthly)."""
    from scrapers.taiwan_moea import TaiwanMoeaScraper

    scraper = TaiwanMoeaScraper(data_dir=str(raw_path.parents[2]))
    logger.info("Building Taiwan MOEA DB from %s", raw_path)
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
    logger.info("Upsert: %s replaced, %s appended", f"{rows_replaced:,}", f"{rows_added:,}")
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
        logger.info("Saved SQLite: %s", sqlite_path)
        paths["sqlite"] = sqlite_path

    return paths


def _derive_canonical_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    unknown: list[str] = []
    canon_map: dict[str, Optional[str]] = {}
    cat_map: dict[str, Optional[str]] = {}

    for name in df["product_native"].unique():
        try:
            canon_map[name] = canonical_subcategory(name, source=_PRODUCT_MAP_SOURCE)
            cat_map[name] = canonical_category(name, source=_PRODUCT_MAP_SOURCE)
        except KeyError:
            unknown.append(name)
            canon_map[name] = None
            cat_map[name] = None

    if unknown:
        logger.warning(
            "  %s Taiwan product_native label(s) missing from product_map.csv: %r",
            len(unknown),
            sorted(unknown),
        )

    df["product_canonical"] = df["product_native"].map(canon_map)
    df["category"] = df["product_native"].map(cat_map)
    return df


def _sort_and_clean(df: pd.DataFrame) -> pd.DataFrame:
    df = _derive_canonical_columns(df)
    df = df.sort_values(KEY_COLS + ["value"]).reset_index(drop=True)
    return df[COLUMN_ORDER]
