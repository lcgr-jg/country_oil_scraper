"""
Processor for India PPAC PT Consumption data.

Responsibilities:
- Build the historical database from the multi-sheet .xls bootstrap file
- Upsert fresh data downloaded by IndiaPPACScraper
- Persist to Parquet (Snowflake-ready) and SQLite (opt-in)

Primary dimension is calendar date so the data aligns with other countries.
Fiscal year is retained as an informational column only.

Phase 4b additions (2026-05) — see reference/loaders.py:
    The output schema now carries four canonical columns derived from
    reference/product_map.csv and reference/metric_types.yaml:

        product_canonical : Sub-category (e.g. HSD -> "Diesel")
        category          : Category    (e.g. HSD -> "Distillates")
        metric_type       : Hardcoded "TOTDEMO" (PPAC is consumption-only)
        unit_measure      : Hardcoded "kt" (PPAC publishes thousand tonnes)

    These are FULLY ADDITIVE — every pre-existing column (notably the
    `product` and `value_000mt` columns relied on by notebooks) is kept
    untouched. Rows whose native `product` is an aggregate / total
    ("All Products total", "TOTAL", ...) get `product_canonical=None`
    and `category=None`, so they are naturally excluded from
    cross-source sums but still queryable via `is_total_row=True`.
"""

import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

# Reference loaders are imported at module level: they cache the CSV/YAML
# read on first call, so importing here is cheap and gives us a single
# place to see all reference-data wiring.
from reference.loaders import canonical_category, canonical_subcategory

logger = logging.getLogger(__name__)

# Source key used when querying product_map.csv. Matches the value in the
# CSV's "Source" column. Keeping it as a constant means there's one place
# to change if PPAC is ever re-tagged or replaced.
_PRODUCT_MAP_SOURCE = "PPAC"

# All PPAC rows describe consumption / deliveries to the domestic market,
# so the canonical metric is fixed. See metric_types.yaml > source_mappings
# > ppac_pt_consumption for the rationale.
_METRIC_TYPE_DEFAULT = "TOTDEMO"

# Native unit of every PPAC value column. The actual numeric column is
# still called `value_000mt` (preserved for backwards compatibility with
# existing notebooks); `unit_measure` is added so cross-source queries
# can treat the value generically.
_UNIT_MEASURE_DEFAULT = "kt"

# Canonical column order — date-first so cross-country joins are natural.
# The 4 canonical columns sit between `product` (native) and
# `value_000mt` (native value) so the schema reads:
#   [time]  [product, canonical, category]  [metric, unit, value]  [meta]
COLUMN_ORDER = [
    "date",
    "calendar_year",
    "calendar_month",
    "month_name",
    "product",             # native (PPAC label, e.g. "HSD")
    "product_canonical",   # Phase 4b: Sub-category from product_map.csv
    "category",            # Phase 4b: Category    from product_map.csv
    "metric_type",         # Phase 4b: always "TOTDEMO" for PPAC
    "unit_measure",        # Phase 4b: always "kt"      for PPAC
    "value_000mt",         # native value (kept for backwards compat)
    "is_total_row",
    "fiscal_year",
    "fiscal_month",
    "source_file",
    "updated_at",
]

# Natural key that uniquely identifies one observation
_KEY_COLS = ["date", "product"]


def build_from_historical(historical_path: Path) -> pd.DataFrame:
    """
    Parse every fiscal-year sheet from the large historical .xls file and
    return a single tidy DataFrame sorted by calendar date.

    Skips the 'Historical (year-wise)' summary sheet automatically
    (that logic lives in IndiaPPACScraper._parse_pt_consumption).

    Args:
        historical_path: Path to the .xls or .xlsx bootstrap file.

    Returns:
        Tidy DataFrame with all historical monthly observations.
    """
    # Late import so this module stays importable even if scrapers/ isn't on
    # sys.path at module load time (e.g. when called from the script).
    import importlib, sys
    if "scrapers.india_ppac" in sys.modules:
        IndiaPPACScraper = sys.modules["scrapers.india_ppac"].IndiaPPACScraper
    else:
        mod = importlib.import_module("scrapers.india_ppac")
        IndiaPPACScraper = mod.IndiaPPACScraper

    # data_dir is two levels up from the raw file: raw/india/<file> → data/
    data_dir = historical_path.parents[2]
    scraper = IndiaPPACScraper(data_dir=str(data_dir))

    logger.info(f"Building historical DB from: {historical_path}")
    df = scraper.parse("pt_consumption", historical_path)
    df = _sort_and_clean(df)
    logger.info(f"Historical DB built: {len(df)} rows, {df['date'].nunique()} distinct months")
    return df


def upsert(existing_df: pd.DataFrame, new_df: pd.DataFrame) -> pd.DataFrame:
    """
    Merge new observations into the existing database.

    For each (date, product) key that appears in new_df:
      - If it already exists in existing_df, replace with new value.
      - If it is new, append it.

    This means a fresh PPAC download will update provisional figures for the
    current fiscal year while leaving older years untouched.

    Args:
        existing_df: Current state of the database.
        new_df:      Freshly parsed DataFrame (one or more fiscal-year sheets).

    Returns:
        Updated DataFrame sorted by date then product.
    """
    if existing_df is None or existing_df.empty:
        return _sort_and_clean(new_df)

    # Drop rows from existing that are superseded by new data
    key_set = set(zip(new_df["date"], new_df["product"]))
    mask_keep = ~existing_df.apply(
        lambda r: (r["date"], r["product"]) in key_set, axis=1
    )
    combined = pd.concat([existing_df[mask_keep], new_df], ignore_index=True)
    return _sort_and_clean(combined)


def save(
    df: pd.DataFrame,
    output_dir: Path,
    write_sqlite: bool = False,
) -> dict[str, Path]:
    """
    Persist the database. Parquet is always written; SQLite is opt-in.

    Default is parquet-only — notebooks load via ``pd.read_parquet`` and
    nobody was querying the .db file. Pass ``write_sqlite=True`` to
    re-enable the SQLite mirror when you need ad-hoc SQL access.

    1. Parquet — ``india_pt_consumption.parquet`` (always)
       Columnar, compressed, directly loadable into Snowflake via COPY INTO.

    2. SQLite  — ``india_pt_consumption.db`` (only if ``write_sqlite=True``)
       Table ``pt_consumption``, indexed on (date, product). Use with
       pandas, sqlite3, or any SQL client.

    Args:
        df:           The full tidy DataFrame to save.
        output_dir:   Directory to write files into (created if absent).
        write_sqlite: Opt in to writing the SQLite mirror. Default False.

    Returns:
        Dict with key 'parquet' (always) and 'sqlite' (only when enabled).
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    parquet_path = output_dir / "india_pt_consumption.parquet"

    # -- Parquet --
    # Convert date → datetime so pyarrow / Snowflake handle it cleanly
    df_pq = df.copy()
    df_pq["date"] = pd.to_datetime(df_pq["date"])
    df_pq.to_parquet(parquet_path, index=False, compression="snappy")
    logger.info(f"Saved parquet: {parquet_path} ({parquet_path.stat().st_size / 1024:.1f} KB)")

    paths: dict[str, Path] = {"parquet": parquet_path}

    # -- SQLite --
    if write_sqlite:
        sqlite_path = output_dir / "india_pt_consumption.db"
        df_sql = df.copy()
        df_sql["date"] = df_sql["date"].astype(str)          # SQLite has no native DATE
        df_sql["updated_at"] = df_sql["updated_at"].astype(str)
        df_sql["is_total_row"] = df_sql["is_total_row"].astype(int)  # SQLite booleans as 0/1

        with sqlite3.connect(sqlite_path) as conn:
            df_sql.to_sql("pt_consumption", conn, if_exists="replace", index=False)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_date_product "
                "ON pt_consumption (date, product)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_date "
                "ON pt_consumption (date)"
            )
        logger.info(f"Saved SQLite: {sqlite_path}")
        paths["sqlite"] = sqlite_path

    return paths


def load(output_dir: Path) -> Optional[pd.DataFrame]:
    """
    Load the existing database from parquet, or return None if it doesn't exist.

    Args:
        output_dir: Directory where ``india_pt_consumption.parquet`` lives.

    Returns:
        DataFrame or None if no database exists yet.
    """
    parquet_path = Path(output_dir) / "india_pt_consumption.parquet"
    if not parquet_path.exists():
        logger.info("No existing database found — will build from scratch.")
        return None

    df = pd.read_parquet(parquet_path)
    # Normalise date back to Python date objects for consistency with parser output
    df["date"] = pd.to_datetime(df["date"]).dt.date
    logger.info(f"Loaded existing DB: {len(df)} rows from {parquet_path}")
    return df


# --------------------------------------------------------------------------- #
#  Internal helpers
# --------------------------------------------------------------------------- #

def _sort_and_clean(df: pd.DataFrame) -> pd.DataFrame:
    """Enforce column order, types, derive canonical columns, and sort by date.

    The canonical-column step (Phase 4b) is idempotent: running it on a
    DataFrame that already has `product_canonical` / `category` / etc.
    simply overwrites them with freshly looked-up values, so a change to
    product_map.csv can be propagated by re-running load -> _sort_and_clean
    -> save without re-scraping.
    """
    df = _derive_canonical_columns(df)

    # Ensure all expected columns exist (fill missing with NaN). This runs
    # AFTER _derive_canonical_columns so the new columns are guaranteed
    # to exist before the reindex.
    for col in COLUMN_ORDER:
        if col not in df.columns:
            df[col] = None

    df = df[COLUMN_ORDER].copy()

    # Types
    df["calendar_year"] = pd.to_numeric(df["calendar_year"], errors="coerce").astype("Int64")
    df["calendar_month"] = pd.to_numeric(df["calendar_month"], errors="coerce").astype("Int64")
    df["fiscal_month"] = pd.to_numeric(df["fiscal_month"], errors="coerce").astype("Int64")
    df["value_000mt"] = pd.to_numeric(df["value_000mt"], errors="coerce")
    df["is_total_row"] = df["is_total_row"].astype(bool)

    # Primary sort: calendar date, then product (alphabetical within a month)
    df = df.sort_values(["date", "product"], ignore_index=True)
    return df


def _derive_canonical_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Add the 4 Phase-4b canonical columns by looking up `product`
    against reference/product_map.csv.

    Behaviour:
    - `product_canonical` and `category` come from the Sub-category /
      Category columns of product_map.csv, looked up by (native_name,
      source=PPAC). Aggregate rows (tagged `-,-` in the CSV) yield None
      for both, which is the intended exclusion signal for cross-source
      sums.
    - `metric_type` and `unit_measure` are constants because PPAC has no
      per-row variation (consumption only, kt only).
    - Unknown native labels raise KeyError from the loader. We surface
      that as a descriptive error rather than silently writing None, so a
      typo in the CSV or a new PPAC product gets caught immediately.
    """
    if df.empty:
        # Nothing to derive; just make sure the columns exist so the
        # reindex in _sort_and_clean has something to align to.
        for col in ("product_canonical", "category", "metric_type", "unit_measure"):
            if col not in df.columns:
                df[col] = pd.Series(dtype="object")
        return df

    # Cache lookups per unique product to avoid hammering the loader once
    # per row. PPAC has ~15 distinct labels so this turns 4.4k lookups
    # into 15.
    unique_products = df["product"].dropna().unique()
    canon_map: dict[str, Optional[str]] = {}
    cat_map: dict[str, Optional[str]] = {}
    unknown: list[str] = []
    for name in unique_products:
        try:
            canon_map[name] = canonical_subcategory(name, source=_PRODUCT_MAP_SOURCE)
            cat_map[name] = canonical_category(name, source=_PRODUCT_MAP_SOURCE)
        except KeyError:
            # Collect all unknowns first so the error message lists them
            # all at once instead of failing on the first one.
            unknown.append(name)

    if unknown:
        raise KeyError(
            f"PPAC products missing from reference/product_map.csv: {unknown!r}. "
            "Add them (use Category='-', Sub-category='-' if they are totals "
            "or aggregates) and re-run."
        )

    df = df.copy()
    df["product_canonical"] = df["product"].map(canon_map)
    df["category"] = df["product"].map(cat_map)
    df["metric_type"] = _METRIC_TYPE_DEFAULT
    df["unit_measure"] = _UNIT_MEASURE_DEFAULT
    return df
