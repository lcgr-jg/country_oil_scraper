"""
Processor for EIA US weekly product supplied → monthly kb/d demand parquet.

Reads ``doe_fundamental_dashboard/data/eia_weekly.sqlite`` (no API calls here).
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

from reference.loaders import canonical_category, canonical_subcategory
from reference.us import (
    CANONICAL_COLUMNS,
    COUNTRY_CODE,
    COUNTRY_NAME,
    EIA_AGENCY_SOURCE,
    EIA_METRIC_TYPE,
    EIA_UNIT_NATIVE,
    SERIES_BY_PRODUCT,
    SOURCE_ID,
    resolve_eia_sqlite,
)

logger = logging.getLogger(__name__)

_PRODUCT_MAP_SOURCE = EIA_AGENCY_SOURCE

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

PARQUET_FILENAME = "us_eia_product_supplied.parquet"


def build_from_eia_sqlite(sqlite_path: Path | None = None) -> pd.DataFrame:
    """Load weekly series and convert to monthly kb/d tidy frame."""
    db = resolve_eia_sqlite(sqlite_path)
    weekly = _load_weekly_long(db)
    if weekly.empty:
        raise ValueError(f"No product-supplied observations in {db}")

    monthly = weekly_kbd_to_monthly_kbd(weekly)
    stamp = db.name
    now = datetime.now(tz=UTC)
    monthly = monthly.assign(
        country=COUNTRY_CODE,
        country_name=COUNTRY_NAME,
        source=SOURCE_ID,
        metric_type=EIA_METRIC_TYPE,
        product=monthly["product_native"],
        unit=EIA_UNIT_NATIVE,
        source_file=f"eia_sqlite/{stamp}",
        updated_at=now,
    )
    df = _sort_and_clean(monthly)
    logger.info(
        "Built %s rows, %s -> %s, products=%s",
        f"{len(df):,}",
        df["date"].min(),
        df["date"].max(),
        df["product_native"].nunique(),
    )
    return df


def build_from_historical(data_dir: Path | None = None) -> pd.DataFrame:
    """Pipeline alias — EIA sqlite lives outside country_oil_scraper data/."""
    _ = data_dir
    return build_from_eia_sqlite()


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


def weekly_kbd_to_monthly_kbd(weekly: pd.DataFrame) -> pd.DataFrame:
    """
    Convert weekly kb/d to calendar-month kb/d.

    For each week-ending Friday with rate ``kbd``:
      attribute ``kbd`` kb to each of the seven days in that week.
    Month rate = sum(day kb in month) / n_days_with_data_in_month.

    Using covered (MTD) days — not calendar days_in_month — keeps an
    unfinished month at a true average rate instead of diluting it toward
    zero. Complete months still divide by the full month length because
    every calendar day has been attributed.

    A month is provisional until a published week covers its last calendar day
    (max week-ending date in the input >= month end).
    """
    required = {"week_end", "product_native", "value_kbd"}
    missing = required - set(weekly.columns)
    if missing:
        raise ValueError(f"weekly frame missing columns: {sorted(missing)}")

    rows: list[dict[str, object]] = []
    max_week = pd.to_datetime(weekly["week_end"]).max()

    for product, sl in weekly.groupby("product_native", sort=False):
        # Accumulate kb per calendar day, then roll to months.
        day_kb: dict[pd.Timestamp, float] = {}
        for week_end, kbd in zip(
            pd.to_datetime(sl["week_end"]),
            pd.to_numeric(sl["value_kbd"], errors="coerce"),
        ):
            if pd.isna(kbd) or pd.isna(week_end):
                continue
            friday = pd.Timestamp(week_end).normalize()
            for offset in range(7):
                day = friday - timedelta(days=6 - offset)
                day_kb[day] = day_kb.get(day, 0.0) + float(kbd)

        if not day_kb:
            continue

        day_index = pd.DatetimeIndex(sorted(day_kb))
        day_values = pd.Series(
            [day_kb[d] for d in day_index], index=day_index, dtype="float64"
        )
        month_periods = day_values.index.to_period("M")
        monthly_kb = day_values.groupby(month_periods).sum()
        # Days that actually received weekly attribution (MTD for open months).
        monthly_days = day_values.groupby(month_periods).size()

        for period, kb_sum in monthly_kb.items():
            month_start = period.to_timestamp()
            n_days = int(monthly_days.loc[period])
            if n_days <= 0:
                continue
            month_end = month_start + pd.offsets.MonthEnd(0)
            # Covered once EIA has published a week that includes month_end.
            is_provisional = bool(max_week < month_end)
            rows.append(
                {
                    "date": month_start.normalize(),
                    "product_native": product,
                    "value": float(kb_sum) / float(n_days),
                    "is_provisional": is_provisional,
                }
            )

    out = pd.DataFrame(rows)
    if out.empty:
        return pd.DataFrame(
            columns=["date", "product_native", "value", "is_provisional"]
        )
    return out.sort_values(["date", "product_native"], ignore_index=True)


def _load_weekly_long(db_path: Path) -> pd.DataFrame:
    series_to_product = {sid: prod for prod, sid in SERIES_BY_PRODUCT.items()}
    placeholders = ",".join("?" * len(series_to_product))
    sql = f"""
        SELECT series_id, period, value
        FROM observations
        WHERE series_id IN ({placeholders})
        ORDER BY series_id, period
    """
    with sqlite3.connect(str(db_path)) as con:
        raw = pd.read_sql_query(sql, con, params=list(series_to_product))

    if raw.empty:
        return pd.DataFrame(columns=["week_end", "product_native", "value_kbd"])

    raw["product_native"] = raw["series_id"].map(series_to_product)
    raw["week_end"] = pd.to_datetime(raw["period"])
    raw["value_kbd"] = pd.to_numeric(raw["value"], errors="coerce")
    out = raw.dropna(subset=["product_native", "week_end", "value_kbd"])[
        ["week_end", "product_native", "value_kbd"]
    ]
    logger.info(
        "Loaded %s weekly rows from %s (%s products, %s -> %s)",
        f"{len(out):,}",
        db_path.name,
        out["product_native"].nunique(),
        out["week_end"].min().date(),
        out["week_end"].max().date(),
    )
    return out


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
            "  %d US product_native label(s) missing from product_map.csv: %s",
            len(unknown),
            sorted(unknown),
        )

    df["product_canonical"] = df["product_native"].map(canon_map)
    df["category"] = df["product_native"].map(cat_map)
    return df
