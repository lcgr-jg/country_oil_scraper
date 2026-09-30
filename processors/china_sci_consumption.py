"""
Processor for SCI China national consumption (+ derived non-jet kerosene).

Reads ``sci_api`` parquet caches (no HTML scrape). Emits a country parquet
compatible with the central demand warehouse.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from reference.china import (
    CANONICAL_COLUMNS,
    CONSUMPTION_PRODUCTS,
    COUNTRY_CODE,
    COUNTRY_NAME,
    JET_PRODUCTS,
    PRODUCT_JET_DOMESTIC,
    PRODUCT_KEROSENE,
    PRODUCT_X_OTHKERO,
    SCI_AGENCY_SOURCE,
    SCI_METRIC_TYPE,
    SCI_UNIT_NATIVE,
    SOURCE_ID,
    resolve_sci_cache_dir,
)
from reference.loaders import canonical_category, canonical_subcategory

logger = logging.getLogger(__name__)

_PRODUCT_MAP_SOURCE = SCI_AGENCY_SOURCE

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

PARQUET_FILENAME = "china_sci_consumption.parquet"


def build_from_sci_cache(cache_dir: Path | None = None) -> pd.DataFrame:
    """Build full tidy frame from one SCI stamped cache directory."""
    cache = Path(cache_dir) if cache_dir is not None else resolve_sci_cache_dir()
    cons_path = cache / "consumption_national.parquet"
    jet_path = cache / "kerosene_refueling_national.parquet"
    if not cons_path.exists():
        raise FileNotFoundError(
            f"Missing {cons_path}. Run sci_api/fetch_data.py --history first."
        )
    if not jet_path.exists():
        raise FileNotFoundError(
            f"Missing {jet_path}. Run sci_api/fetch_data.py --history first."
        )

    cons = pd.read_parquet(cons_path)
    jet = pd.read_parquet(jet_path)
    stamp = cache.name
    logger.info(
        "Building China SCI DB from cache %s (cons=%s rows, jet=%s rows)",
        stamp,
        f"{len(cons):,}",
        f"{len(jet):,}",
    )

    frames = [
        _national_to_long(cons, CONSUMPTION_PRODUCTS, stamp),
        _national_to_long(jet, JET_PRODUCTS, stamp),
    ]
    df = pd.concat(frames, ignore_index=True)
    df = _append_x_othkero(df, stamp)
    df = _sort_and_clean(df)
    logger.info(
        "Built %s rows, %s -> %s, products=%s",
        f"{len(df):,}",
        df["date"].min(),
        df["date"].max(),
        df["product_native"].nunique(),
    )
    return df


def build_from_historical(data_dir: Path | None = None) -> pd.DataFrame:
    """Warehouse/pipeline alias — SCI lives outside country_oil_scraper data/."""
    _ = data_dir  # unused; kept for processor API symmetry
    return build_from_sci_cache()


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
    """Replace overlapping keys with the latest SCI snapshot values."""
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


def save(df: pd.DataFrame, output_dir: Path) -> dict[str, Path]:
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
    return {"parquet": parquet_path}


def derive_x_othkero(demand: pd.DataFrame) -> pd.DataFrame:
    """
    Emit ``X_OTHKERO = Kerosene − Jet fuel (domestic)`` (clamped at 0).

    Expects columns ``date``, ``product_native``, ``value``. Returns only the
    derived rows (caller concatenates).
    """
    if demand.empty:
        return demand.iloc[0:0].copy()

    kero = demand.loc[
        demand["product_native"].eq(PRODUCT_KEROSENE), ["date", "value"]
    ].rename(columns={"value": "kero"})
    dom = demand.loc[
        demand["product_native"].eq(PRODUCT_JET_DOMESTIC), ["date", "value"]
    ].rename(columns={"value": "dom"})
    merged = kero.merge(dom, on="date", how="inner")
    if merged.empty:
        logger.warning("derive_x_othkero: no overlapping kerosene/domestic jet months")
        return demand.iloc[0:0].copy()

    other = merged["kero"] - merged["dom"]
    n_neg = int((other < 0).sum())
    if n_neg:
        logger.warning(
            "derive_x_othkero: %s month(s) with Kerosene < domestic jet; clamping to 0",
            n_neg,
        )
    other = other.clip(lower=0)

    template = demand.iloc[0].to_dict()
    rows = []
    now = datetime.now(tz=UTC)
    for date, value in zip(merged["date"], other):
        row = dict(template)
        row.update(
            {
                "date": date,
                "product_native": PRODUCT_X_OTHKERO,
                "product": PRODUCT_X_OTHKERO,
                "value": float(value),
                "is_provisional": False,
                "updated_at": now,
            }
        )
        rows.append(row)
    out = pd.DataFrame(rows)
    logger.info("derive_x_othkero: emitted %s row(s)", f"{len(out):,}")
    return out


def _national_to_long(
    frame: pd.DataFrame,
    products: tuple[str, ...],
    stamp: str,
) -> pd.DataFrame:
    required = {"product", "year", "month", "consumption_kt"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"SCI national frame missing columns: {sorted(missing)}")

    sl = frame[frame["product"].isin(products)].copy()
    if sl.empty:
        return pd.DataFrame(columns=CANONICAL_COLUMNS)

    now = datetime.now(tz=UTC)
    sl["date"] = pd.to_datetime(
        dict(year=sl["year"].astype(int), month=sl["month"].astype(int), day=1)
    )
    out = pd.DataFrame(
        {
            "date": sl["date"],
            "country": COUNTRY_CODE,
            "country_name": COUNTRY_NAME,
            "source": SOURCE_ID,
            "metric_type": SCI_METRIC_TYPE,
            "product_native": sl["product"].astype(str),
            "product": sl["product"].astype(str),
            "value": pd.to_numeric(sl["consumption_kt"], errors="coerce"),
            "unit": SCI_UNIT_NATIVE,
            "is_provisional": False,
            "source_file": f"sci_cache/{stamp}",
            "updated_at": now,
        }
    )
    return out.dropna(subset=["date", "value"])


def _append_x_othkero(df: pd.DataFrame, stamp: str) -> pd.DataFrame:
    derived = derive_x_othkero(df)
    if derived.empty:
        return df
    derived["source_file"] = f"sci_cache/{stamp}+derived"
    return pd.concat([df, derived], ignore_index=True)


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
            unknown.append(str(name))
            canon_map[name] = None
            cat_map[name] = None

    if unknown:
        logger.warning(
            "  %d China product_native label(s) missing from product_map.csv: %s",
            len(unknown),
            sorted(unknown),
        )

    df["product_canonical"] = df["product_native"].map(canon_map)
    df["category"] = df["product_native"].map(cat_map)
    return df
