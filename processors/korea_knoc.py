"""
Processor for Korea KNOC Petronet statistics (consumption + closing stocks).
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Optional

import pandas as pd

from reference.korea import (
    CONSUMPTION_DATASET,
    KNOC_AGENCY_SOURCE,
    KOREA_DATASETS,
    STOCKS_DATASET,
    raw_dir_for_dataset,
)
from reference.loaders import canonical_category, canonical_subcategory
from scrapers.korea_knoc import (
    CANONICAL_COLUMNS,
    build_all_from_files,
    build_all_from_raw,
)

logger = logging.getLogger(__name__)

_PRODUCT_MAP_SOURCE = KNOC_AGENCY_SOURCE

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

PARQUET_FILENAME = "korea_knoc.parquet"
LEGACY_PARQUET_FILENAME = "korea_knoc_consumption.parquet"
SQLITE_FILENAME = "korea_knoc.db"
SQLITE_TABLE = "knoc"


def build_from_raw(data_dir: Path) -> pd.DataFrame:
    """Rebuild from all local bundle CSVs (consumption + stocks)."""
    data_dir = Path(data_dir)
    logger.info("Full reparse of KNOC bundles under %s/raw/korea/", data_dir)
    df = build_all_from_raw(data_dir)
    return _sort_and_clean(df)


def build_from_files(paths: list[Path]) -> pd.DataFrame:
    """Incremental parse: only the bundle file(s) that changed this run."""
    paths = [Path(p) for p in paths]
    names = ", ".join(p.name for p in paths)
    logger.info("Incremental parse (%d file(s)): %s", len(paths), names)
    df = build_all_from_files(paths)
    return _sort_and_clean(df)


def load(output_dir: Path) -> Optional[pd.DataFrame]:
    output_dir = Path(output_dir)
    parquet_path = output_dir / PARQUET_FILENAME
    legacy_path = output_dir / LEGACY_PARQUET_FILENAME

    if parquet_path.exists():
        df = pd.read_parquet(parquet_path)
    elif legacy_path.exists():
        logger.info(
            "Migrating legacy parquet %s -> %s on next save",
            legacy_path.name,
            PARQUET_FILENAME,
        )
        df = pd.read_parquet(legacy_path)
    else:
        logger.info(f"No existing DB at {parquet_path} — first run? Use --bootstrap.")
        return None

    logger.info(
        f"Loaded {len(df):,} rows ({df['date'].min()} -> {df['date'].max()})"
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
    logger.info(f"Upsert: {rows_replaced:,} replaced, {rows_added:,} appended")
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
        f"Saved parquet: {parquet_path} ({parquet_path.stat().st_size / 1024:.1f} KB)"
    )
    paths: dict[str, Path] = {"parquet": parquet_path}

    legacy_path = output_dir / LEGACY_PARQUET_FILENAME
    if legacy_path.exists() and legacy_path != parquet_path:
        legacy_path.unlink()
        logger.info("Removed legacy parquet %s", legacy_path.name)

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
        ["date", "metric_type", "product_native"], ignore_index=True
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
            f"  {len(unknown)} Korea product_native label(s) missing from "
            f"product_map.csv: {sorted(unknown)!r}"
        )

    df["product_canonical"] = df["product_native"].map(canon_map)
    df["category"] = df["product_native"].map(cat_map)
    return df


__all__ = [
    "PARQUET_FILENAME",
    "build_from_raw",
    "build_from_files",
    "load",
    "upsert",
    "save",
    "CONSUMPTION_DATASET",
    "STOCKS_DATASET",
    "KOREA_DATASETS",
    "raw_dir_for_dataset",
]
