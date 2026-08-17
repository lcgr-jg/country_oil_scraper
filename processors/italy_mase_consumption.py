"""
Processor for Italy MASE consumi petroliferi.

  scrapers/italy_mase.py       ->  parse raw workbooks
  THIS FILE                    ->  upsert + parquet + canonical columns
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Optional

import pandas as pd

from reference.italy import MASE_AGENCY_SOURCE
from reference.loaders import canonical_category, canonical_subcategory
from scrapers.italy_mase import CANONICAL_COLUMNS

logger = logging.getLogger(__name__)

_PRODUCT_MAP_SOURCE = MASE_AGENCY_SOURCE

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

PARQUET_FILENAME = "italy_mase_consumption.parquet"
SQLITE_FILENAME = "italy_mase_consumption.db"
SQLITE_TABLE = "mase_consumption"

# Definitive history ends here; preliminary rows may extend beyond.
DEFINITIVE_CUTOFF = pd.Timestamp("2025-12-01")


def build_from_historical(raw_dir: Path) -> pd.DataFrame:
    """
    Bootstrap from all definitive annual workbooks (2002–2025).

    Each file contributes one calendar year of monthly rows.
    """
    from scrapers.italy_mase import parse_definitive_directory

    raw_dir = Path(raw_dir)
    logger.info(f"Building Italy MASE DB from definitive files in {raw_dir}")
    df = parse_definitive_directory(raw_dir)
    return _sort_and_clean(df)


def load(output_dir: Path) -> Optional[pd.DataFrame]:
    """Load existing parquet or None on first run."""
    parquet_path = Path(output_dir) / PARQUET_FILENAME
    if not parquet_path.exists():
        logger.info(
            f"No existing DB at {parquet_path} — first run? Use --bootstrap."
        )
        return None
    df = pd.read_parquet(parquet_path)
    logger.info(
        f"Loaded {len(df):,} rows ({df['date'].min()} -> {df['date'].max()})"
    )
    return df


def upsert(
    existing_df: Optional[pd.DataFrame],
    new_df: pd.DataFrame,
    *,
    prefer_definitive: bool = True,
) -> pd.DataFrame:
    """
    Merge ``new_df`` into ``existing_df`` on KEY_COLS.

    When ``prefer_definitive`` is True, existing definitive rows
    (``is_provisional=False``) are kept over provisional rows for the same key.
    """
    if existing_df is None or len(existing_df) == 0:
        return _sort_and_clean(new_df)

    new_df = new_df.copy()
    existing_df = existing_df.copy()

    if prefer_definitive and len(new_df) > 0:
        provisional_new = new_df[new_df["is_provisional"]]
        if len(provisional_new) > 0:
            # Drop existing provisional rows that overlap definitive history years.
            mask_definitive_years = existing_df["date"] <= DEFINITIVE_CUTOFF
            existing_df = existing_df.loc[
                ~(existing_df["is_provisional"] & mask_definitive_years)
            ]

    new_keys = pd.MultiIndex.from_frame(new_df[KEY_COLS])
    existing_keys = pd.MultiIndex.from_frame(existing_df[KEY_COLS])

    if prefer_definitive and len(new_df) > 0:
        # Do not replace definitive rows with provisional updates.
        definitive_existing = existing_df[~existing_df["is_provisional"]]
        definitive_keys = pd.MultiIndex.from_frame(definitive_existing[KEY_COLS])
        provisional_new = new_df[new_df["is_provisional"]]
        if len(provisional_new) > 0:
            overlap = provisional_new[
                pd.MultiIndex.from_frame(provisional_new[KEY_COLS]).isin(definitive_keys)
            ]
            if len(overlap) > 0:
                drop_keys = pd.MultiIndex.from_frame(overlap[KEY_COLS])
                new_df = new_df.loc[
                    ~pd.MultiIndex.from_frame(new_df[KEY_COLS]).isin(drop_keys)
                ]

    new_keys = pd.MultiIndex.from_frame(new_df[KEY_COLS])
    keep_mask = ~existing_keys.isin(new_keys)
    rows_replaced = int((~keep_mask).sum())
    rows_added = len(new_df) - rows_replaced

    combined = pd.concat(
        [existing_df.loc[keep_mask], new_df],
        ignore_index=True,
    )
    logger.info(
        f"Upsert: {rows_replaced:,} replaced, {rows_added:,} appended"
    )
    return _sort_and_clean(combined)


def save(
    df: pd.DataFrame,
    output_dir: Path,
    write_sqlite: bool = False,
) -> dict[str, Path]:
    """Write parquet (always) and optional SQLite mirror."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    parquet_path = output_dir / PARQUET_FILENAME
    df_pq = df.copy()
    df_pq["date"] = pd.to_datetime(df_pq["date"])
    df_pq.to_parquet(parquet_path, index=False, compression="snappy")
    logger.info(
        f"Saved parquet: {parquet_path} "
        f"({parquet_path.stat().st_size / 1024:.1f} KB)"
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
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_date_product "
                f"ON {SQLITE_TABLE} (date, product_native)"
            )
        logger.info(f"Saved SQLite: {sqlite_path}")
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
    """Soft-fail canonical mapping (Australia pattern)."""
    if df.empty:
        for col in ("product_canonical", "category"):
            if col not in df.columns:
                df[col] = pd.Series(dtype="object")
        return df

    df = df.copy()
    unique_products = df["product_native"].dropna().unique()
    canon_map: dict[str, Optional[str]] = {}
    cat_map: dict[str, Optional[str]] = {}
    unknown: list[str] = []

    for name in unique_products:
        try:
            canon_map[name] = canonical_subcategory(
                name, source=_PRODUCT_MAP_SOURCE
            )
            cat_map[name] = canonical_category(
                name, source=_PRODUCT_MAP_SOURCE
            )
        except KeyError:
            unknown.append(name)
            canon_map[name] = None
            cat_map[name] = None

    if unknown:
        logger.warning(
            f"  {len(unknown)} Italy product_native label(s) missing from "
            f"product_map.csv; canonical columns left as NaN: "
            f"{sorted(unknown)!r}"
        )

    df["product_canonical"] = df["product_native"].map(canon_map)
    df["category"] = df["product_native"].map(cat_map)
    return df
