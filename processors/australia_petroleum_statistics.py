"""
Processor for the Australian Petroleum Statistics database.

This module is the persistence + analytics layer for Australia's data:

  scrapers/australia_apstat.py  ->  parses raw xlsx into a tidy DataFrame
  THIS FILE                     ->  upserts that DataFrame into the local DB
                                    and persists to parquet + sqlite

Mirrors the shape of ``processors.india_pt_consumption`` and
``processors.jodi`` so the project-wide pipeline pattern stays uniform:
``load() -> upsert() -> save()`` for incremental monthly updates,
``build_from_historical()`` for the first-ever build.

Phase status (Phase 2b - 2026-05)
─────────────────────────────────
Skeleton with detailed TODOs for the project owner. Each function has:
  - A docstring explaining WHAT it should do.
  - TODO comments inside the body explaining HOW (pointers to existing
    patterns in india_pt_consumption.py / jodi.py).
  - A ``raise NotImplementedError`` placeholder so callers fail loudly
    if the function is invoked before being filled in.

Recommended order of implementation:
  1. ``build_from_historical``  - shortest, gets the pipeline running
  2. ``load``                   - needed before ``upsert`` is testable
  3. ``upsert``                 - the meaty piece
  4. ``save``                   - the persistence glue
  5. ``compute_apparent_consumption`` - the analytic (TODO 3)
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

# Reference loaders are imported at module level: they cache the CSV/YAML
# read on first call, so importing here is cheap and gives us one place
# to see all reference-data wiring.
from reference.loaders import canonical_category, canonical_subcategory

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
#  Schema contract
# --------------------------------------------------------------------------- #
# We deliberately re-export the canonical column order from the scraper
# module so any consumer (this processor, the dashboard, future cross-source
# joins) reads from ONE source of truth. If we ever rename a column, we
# rename it in australia_apstat.py and every consumer adapts automatically.

from scrapers.australia_apstat import CANONICAL_COLUMNS  # noqa: E402

# Phase 4d (2026-05): the processor extends the scraper's CANONICAL_COLUMNS
# with two cross-source canonical columns. The scraper still owns the raw
# 11-col schema (one row per native observation); the processor adds the
# canonical mapping on top in `_sort_and_clean` -> `_derive_canonical_columns`.
#
# Why extend here rather than in the scraper:
#   - Keeps the scraper a pure parser (1:1 with the source xlsx).
#   - The mapping is data-driven (reference/product_map.csv); editing the
#     CSV and re-running load -> save refreshes the canonical columns
#     without re-scraping.
#   - Matches the India / JODI processors which own canonicalisation too.
#
# See top of reference/product_map.csv for the CSV-column-name <-> parquet-
# column-name rename and the rationale.
COLUMN_ORDER: list[str] = CANONICAL_COLUMNS + [
    "product_canonical",   # Phase 4d: Sub-category from product_map.csv
    "category",            # Phase 4d: Category    from product_map.csv
]

# Source key into product_map.csv for Australia. Stored as a constant so a
# rename or re-tagging happens in one place.
_PRODUCT_MAP_SOURCE = "DCCEEW"

# Natural key for upserts. When DCCEEW republishes the xlsx (every month),
# the same (date, metric_type, product_native) tuple shows up with a new
# value if it's been revised. The upsert replaces the existing row.
#
# `country` and `source` are in the key for future-proofing: once India and
# JODI also write to this canonical schema (Phase 4), one combined table
# can hold all three sources and this key still uniquely identifies one
# observation. Today they're constant ("AU"/"dceew_petroleum_statistics")
# for everything this processor handles - costs nothing to include.
KEY_COLS: list[str] = [
    "date",
    "country",
    "source",
    "metric_type",
    "product_native",
]

# Output filenames. Putting them as constants keeps `save()` and `load()`
# in sync - rename happens in one place.
PARQUET_FILENAME = "australia_petroleum_statistics.parquet"
SQLITE_FILENAME = "australia_petroleum_statistics.db"
SQLITE_TABLE = "petroleum_statistics"


# =========================================================================== #
#  TODO 1.1 — build_from_historical
# =========================================================================== #

def build_from_historical(raw_path: Path) -> pd.DataFrame:
    """
    Build the entire historical Australia DB from a single source xlsx.

    Why this is so simple for Australia
    -----------------------------------
    Unlike India (where the historical bootstrap is a separate xls
    containing fiscal-year sheets), DCCEEW publishes the FULL history
    in EVERY monthly xlsx. So "building from historical" is just
    "parsing one file" - any current xlsx contains 188+ months back to
    Jul 2010.

    Args:
        raw_path: Path to an Australian Petroleum Statistics xlsx
                  (typically the latest one in data/raw/australia/).

    Returns:
        Tidy DataFrame in CANONICAL_COLUMNS order, ready for ``save()``.
    """
    # TODO 1.1
    # ────────
    # 1. Import AustraliaAPStatScraper from scrapers.australia_apstat.
    # 2. Instantiate it (no arguments needed - defaults work).
    # 3. Call scraper.parse("petroleum_statistics", raw_path).
    # 4. Return the resulting DataFrame.
    #
    # Tips:
    # - The returned DataFrame is already in CANONICAL_COLUMNS order
    #   and sorted by (date, metric_type, product_native), so no extra
    #   _sort_and_clean() step is needed.
    # - Compare with processors/india_pt_consumption.py::build_from_historical
    #   for the identical pattern with India.

    # Late import so this processor module remains importable in
    # environments without curl_cffi (download() requires it, but parse()
    # doesn't). The scraper class only gets resolved when this function
    # is actually called.
    from scrapers.australia_apstat import AustraliaAPStatScraper

    scraper = AustraliaAPStatScraper()
    return scraper.parse("petroleum_statistics", raw_path)


# =========================================================================== #
#  TODO 1.2 — load
# =========================================================================== #

def load(output_dir: Path) -> Optional[pd.DataFrame]:
    """
    Load the existing Australia DB from parquet, or return None if absent.

    Why parquet (and not sqlite) is the source of truth for this `load`:
    parquet preserves pandas dtypes exactly (including datetime64[ns]),
    while sqlite stores everything as text. Reading from parquet means
    no type-coercion surprises.

    Args:
        output_dir: Directory where ``australia_petroleum_statistics.parquet``
                    lives. Typically ``data/processed/australia/``.

    Returns:
        DataFrame in CANONICAL_COLUMNS order, or None if no parquet exists
        yet (first-ever run).
    """
    # TODO 1.2
    # ────────
    # 1. Compute parquet path: output_dir / PARQUET_FILENAME.
    # 2. If it doesn't exist:
    #    - Log a friendly INFO message ("No existing DB found — first run?").
    #    - Return None (the caller will trigger build_from_historical).
    # 3. Otherwise:
    #    - df = pd.read_parquet(parquet_path)
    #    - Log how many rows and the date range.
    #    - Return df.
    #
    # Tips:
    # - Compare with processors/india_pt_consumption.py::load for the
    #   same pattern. Same shape, different filename.

    parquet_path = Path(output_dir) / PARQUET_FILENAME
    if not parquet_path.exists():
        logger.info(
            f"No existing DB found at {parquet_path} - first run? "
            f"Caller should bootstrap from raw."
        )
        return None
    df = pd.read_parquet(parquet_path)
    logger.info(
        f"Loaded existing DB: {len(df):,} rows "
        f"({df['date'].min()} -> {df['date'].max()})"
    )
    return df


# =========================================================================== #
#  TODO 1.3 — upsert
# =========================================================================== #

def upsert(
    existing_df: Optional[pd.DataFrame],
    new_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Merge ``new_df`` into ``existing_df``, replacing rows on key collision.

    Semantics: for each natural-key tuple appearing in ``new_df``:
      - If it already exists in ``existing_df``, REPLACE it with the new row.
      - Otherwise APPEND.

    The result is sorted and stable - re-running with the same inputs
    produces a byte-identical parquet on save.

    Why this matters for Australia: DCCEEW frequently revises figures
    for the most recent ~3 months as more refineries/distributors
    report. An upsert on KEY_COLS means re-downloading the next xlsx
    will quietly correct those revisions in-place, without duplicating
    historical rows.

    Args:
        existing_df: Current DB state. May be None (first run) or empty.
        new_df:      Freshly parsed DataFrame from ``scraper.parse()``.

    Returns:
        Merged DataFrame, sorted by (date, metric_type, product_native).
    """
    # TODO 1.3
    # ────────
    # 1. Edge case: if existing_df is None or empty, just return new_df
    #    (sorted by [date, metric_type, product_native], ignore_index=True).
    #
    # 2. Otherwise, do an anti-join + concat:
    #    a. Build a MultiIndex over new_df[KEY_COLS]:
    #          new_keys = pd.MultiIndex.from_frame(new_df[KEY_COLS])
    #    b. Build the same over existing_df[KEY_COLS]:
    #          existing_keys = pd.MultiIndex.from_frame(existing_df[KEY_COLS])
    #    c. Compute a mask of existing rows to KEEP (those whose key is
    #       NOT in new_keys):
    #          keep_mask = ~existing_keys.isin(new_keys)
    #    d. Concatenate: existing_df[keep_mask] + new_df, ignore_index=True.
    #    e. Sort the result.
    #
    # Why MultiIndex + isin (and not df.merge with indicator='left_only')
    # -------------------------------------------------------------------
    # Both approaches work, but MultiIndex + isin is roughly 5-10x faster
    # on large frames and avoids the merge's intermediate copy.
    #
    # Tips:
    # - Compare with processors/jodi.py::upsert for the exact same pattern
    #   - it's the closest reference implementation in the repo (also
    #   uses MultiIndex anti-join).
    # - Logging is helpful: print rows_before / rows_after / net_change
    #   so the user running the script can sanity-check the result.


    # Edge case: first run, no existing DB. Normalise the new frame
    # (column order + sort) and return. Always normalising even in this
    # path means a re-run of the pipeline produces identical bytes on disk.
    if existing_df is None or len(existing_df) == 0:
        return _sort_and_clean(new_df)

    # Build MultiIndexes over both frames' key columns. This is the fast
    # primitive for "is this row's natural key already present in the
    # other frame?". Much faster than pd.merge(..., indicator=True) and
    # avoids the merge's intermediate copy.
    new_keys = pd.MultiIndex.from_frame(new_df[KEY_COLS])
    existing_keys = pd.MultiIndex.from_frame(existing_df[KEY_COLS])

    # Keep only existing rows whose key is NOT in new_df — those are
    # untouched history. Rows whose key IS in new_df get replaced by
    # the corresponding new_df row in the concat below.
    keep_mask = ~existing_keys.isin(new_keys)
    rows_replaced = int((~keep_mask).sum())
    rows_added = len(new_df) - rows_replaced

    combined = pd.concat(
        [existing_df.loc[keep_mask], new_df],
        ignore_index=True,
    )
    logger.info(
        f"  Upsert: {rows_replaced:,} row(s) replaced, "
        f"{rows_added:,} new row(s) appended"
    )
    return _sort_and_clean(combined)


def _sort_and_clean(df: pd.DataFrame) -> pd.DataFrame:
    """
    Enforce COLUMN_ORDER, derive canonical product columns, and apply a
    stable sort.

    Stable sort matters because pandas/parquet write order is preserved
    on disk — without this, every re-run of the pipeline would produce
    a parquet with the same data but different row order, generating
    noisy diffs in version control or in downstream change-detection.

    The Phase 4d canonical-column derivation runs FIRST so the new
    columns are filled before the reindex; the step is idempotent so
    re-running on a frame that already has them just refreshes their
    values (useful for picking up edits to product_map.csv without
    re-scraping the xlsx).
    """
    df = _derive_canonical_columns(df)

    # Ensure every canonical column exists (fill missing with NA) before
    # reindexing. This makes the function robust to upstream changes that
    # might add or remove columns.
    for col in COLUMN_ORDER:
        if col not in df.columns:
            df = df.copy()
            df[col] = pd.NA
    df = df[COLUMN_ORDER].copy()
    return df.sort_values(
        ["date", "metric_type", "product_native"],
        ignore_index=True,
    )


def _derive_canonical_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Add `product_canonical` and `category` by looking up `product_native`
    against reference/product_map.csv.

    Behaviour vs India / JODI
    -------------------------
    The India and JODI processors HARD-FAIL on unknown native labels —
    they raise KeyError listing every missing entry. Australia instead
    SOFT-FAILS: unknowns get NaN for the canonical columns and a single
    WARNING is logged listing them.

    Why soft-fail for Australia
    ----------------------------
    DCCEEW's xlsx covers ~42 distinct product labels but only 17 are
    refined petroleum products in scope for cross-source canonicalisation
    (the (ML)-unit subset previously mapped in product_map.csv). The
    other 25 are:
      - Upstream crude / NGL / condensate (out of scope per Phase 4c
        scope decision: project is products, not crude).
      - Natural gas / LNG (different commodity).
      - Aggregate totals ("Total oil imports", "Total stocks COE", ...).
      - Statistical rows ("Percentage indigenous: Total input") used by
        the X_REFINSHARE_INDIG metric, not a product per se.
    Forcing every one of those into product_map.csv as a Category='-'
    placeholder would add 25+ rows of noise with zero information. NaN
    is the correct signal that "this row is not a product in scope" and
    downstream queries already use `df['product_canonical'].notna()` to
    filter.

    Performance: Australia has ~42 unique product_native values, so we
    cache lookups per-unique-value (one loader call per label, then
    .map() across the column).
    """
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
            canon_map[name] = canonical_subcategory(name, source=_PRODUCT_MAP_SOURCE)
            cat_map[name] = canonical_category(name, source=_PRODUCT_MAP_SOURCE)
        except KeyError:
            # Soft-fail: collect rather than raise. Unknown -> NaN below.
            unknown.append(name)
            canon_map[name] = None
            cat_map[name] = None

    if unknown:
        # Single concise WARNING so the gap is visible at run time without
        # spamming the log per row. The list is intentionally not silent
        # because a NEW DCCEEW product (e.g. they add a hydrogen sheet)
        # should be a prompt to update product_map.csv.
        logger.warning(
            f"  [Phase 4d] {len(unknown)} Australia product_native label(s) "
            f"have no entry in reference/product_map.csv; canonical columns "
            f"left as NaN. Labels: {sorted(unknown)!r}. "
            f"This is EXPECTED for out-of-scope rows (crude / LNG / totals); "
            f"add a row to product_map.csv only if you want a new label to "
            f"participate in cross-source canonical sums."
        )

    df["product_canonical"] = df["product_native"].map(canon_map)
    df["category"] = df["product_native"].map(cat_map)
    return df


# =========================================================================== #
#  TODO 1.4 — save
# =========================================================================== #

def save(
    df: pd.DataFrame,
    output_dir: Path,
    write_sqlite: bool = False,
) -> dict[str, Path]:
    """
    Persist the DB to parquet (always). SQLite mirror is opt-in.

    Default is parquet-only — notebooks load via ``pd.read_parquet`` and
    nobody was querying the .db file. Pass ``write_sqlite=True`` to
    re-enable the SQLite mirror when you need ad-hoc SQL access.

      - **Parquet** is the canonical store: columnar, snappy-compressed,
        preserves pandas dtypes exactly, loadable into Snowflake/Spark
        via ``COPY INTO``.
      - **SQLite** (opt-in) is the convenience layer for ad-hoc SQL
        queries and BI tools. Loses some type fidelity (dates become
        strings) but offers ``SELECT * WHERE ...`` ergonomics.

    Args:
        df:           Tidy DataFrame in CANONICAL_COLUMNS order.
        output_dir:   Where to write (created if missing).
        write_sqlite: Opt in to writing the SQLite mirror. Default False.

    Returns:
        Dict with key 'parquet' (always) and 'sqlite' (only when enabled).
    """
    # TODO 1.4
    # ────────
    # 1. Ensure output_dir exists:
    #       output_dir = Path(output_dir)
    #       output_dir.mkdir(parents=True, exist_ok=True)
    #
    # 2. Compute paths:
    #       parquet_path = output_dir / PARQUET_FILENAME
    #       sqlite_path  = output_dir / SQLITE_FILENAME
    #
    # 3. Write parquet:
    #    a. Make a copy: df_pq = df.copy().
    #    b. Ensure date and updated_at are datetime64 (use pd.to_datetime).
    #    c. df_pq.to_parquet(parquet_path, index=False, compression="snappy")
    #    d. Log success + file size in MB.
    #
    # 4. If write_sqlite:
    #    a. Make another copy: df_sql = df.copy().
    #    b. SQLite has no native DATE - convert date and updated_at to
    #       ISO strings: df_sql["date"] = pd.to_datetime(df_sql["date"]).dt.strftime("%Y-%m-%d")
    #    c. Open the connection (use `with sqlite3.connect(sqlite_path) as conn:`).
    #    d. df_sql.to_sql(SQLITE_TABLE, conn, if_exists="replace",
    #                     index=False, chunksize=50_000)
    #    e. Create indexes (these massively speed up dashboard queries):
    #       - (date, metric_type)  for time-series-by-metric
    #       - (product_native)     for product filters
    #       - (date)               for general date range scans
    #       Use:
    #         conn.execute(
    #             f"CREATE INDEX IF NOT EXISTS idx_{SQLITE_TABLE}_date_metric "
    #             f"ON {SQLITE_TABLE} (date, metric_type)"
    #         )
    #    f. Log success.
    #
    # 5. Return dict: {"parquet": parquet_path} or
    #                 {"parquet": parquet_path, "sqlite": sqlite_path}.
    #
    # Tips:
    # - Compare with processors/india_pt_consumption.py::save (closest
    #   match: single-source, monthly cadence).
    # - processors/jodi.py::save has a more sophisticated index strategy
    #   if you want inspiration for additional indexes.


    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = output_dir / PARQUET_FILENAME
    sqlite_path = output_dir / SQLITE_FILENAME

    # --- Parquet -------------------------------------------------------- #
    # Copy first because the SQLite branch below also mutates types — we
    # don't want either branch to leak side effects into the caller's df.
    df_pq = df.copy()
    df_pq["date"] = pd.to_datetime(df_pq["date"])
    df_pq["updated_at"] = pd.to_datetime(df_pq["updated_at"])
    df_pq.to_parquet(parquet_path, index=False, compression="snappy")
    size_mb = parquet_path.stat().st_size / (1024 * 1024)
    logger.info(f"Saved parquet: {parquet_path} ({size_mb:.2f} MB)")

    paths: dict[str, Path] = {"parquet": parquet_path}

    # --- SQLite --------------------------------------------------------- #
    if write_sqlite:
        df_sql = df.copy()
        # SQLite has no native DATE type. Storing as ISO 8601 text is the
        # standard convention — BI tools and pd.read_sql() both interpret
        # it correctly. Without the strftime, pandas would write a binary
        # Timestamp blob that SQL clients can't filter on.
        df_sql["date"] = pd.to_datetime(df_sql["date"]).dt.strftime("%Y-%m-%d")
        df_sql["updated_at"] = pd.to_datetime(df_sql["updated_at"]).astype(str)

        # IMPORTANT: pd.DataFrame.to_sql wants either a SQLAlchemy engine
        # or a sqlite3 Connection — NOT a filesystem path. Passing a path
        # silently does nothing useful in some pandas versions and raises
        # in others. Open the connection in a `with` block so it commits
        # and closes deterministically.
        with sqlite3.connect(sqlite_path) as conn:
            df_sql.to_sql(
                SQLITE_TABLE,
                conn,
                if_exists="replace",
                index=False,
                chunksize=50_000,  # safely under SQLite's 32k-parameter cap
            )
            # Indexes for the queries the dashboard will run most often.
            # CREATE INDEX IF NOT EXISTS is idempotent — safe to re-run.
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{SQLITE_TABLE}_date_metric "
                f"ON {SQLITE_TABLE} (date, metric_type)"
            )
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{SQLITE_TABLE}_product "
                f"ON {SQLITE_TABLE} (product_native)"
            )
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{SQLITE_TABLE}_date "
                f"ON {SQLITE_TABLE} (date)"
            )

        size_mb = sqlite_path.stat().st_size / (1024 * 1024)
        logger.info(f"Saved SQLite: {sqlite_path} ({size_mb:.2f} MB)")
        paths["sqlite"] = sqlite_path

    return paths


# =========================================================================== #
#  TODO 3 — compute_apparent_consumption
# =========================================================================== #

def compute_apparent_consumption(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute apparent consumption as a sanity check against reported sales.

    Definition
    ----------
    For each (date, product_native) combination::

        apparent_consumption = INDPROD + TOTIMPSB - TOTEXPSB - delta_CLOSTLV

    where ``delta_CLOSTLV`` is the month-over-month change in closing
    stock level. Intuitively: how much product flowed into the country's
    market = (what we produced) + (what we imported) - (what we exported)
    - (what we added to stocks).

    This SHOULD approximately equal TOTDEMO (the reported sales/deliveries
    figure). The gap between the two is the "statistical difference" -
    typically a few % for well-instrumented countries like Australia and a
    useful data-quality alarm.

    Args:
        df: Tidy DataFrame in CANONICAL_COLUMNS order (typically
            produced by ``load()``). Must contain INDPROD, TOTIMPSB,
            TOTEXPSB, CLOSTLV, and TOTDEMO rows.

    Returns:
        DataFrame with columns:
            date, product_native, indprod, imports, exports,
            stocks, delta_stocks, apparent_consumption,
            reported_sales, statistical_difference, statdiff_pct
        Sorted by (date, product_native). Months where one of the
        components is missing (e.g. first month has no delta_stocks)
        are dropped.
    """
    # TODO 3
    # ──────
    # This is the most novel TODO. There's no existing pattern in the repo
    # to mirror; you're designing the analytic from scratch. Recommended
    # approach:
    #
    # 1. Pivot the tidy DataFrame to wide format on metric_type:
    #
    #       wide = df.pivot_table(
    #           index=["date", "product_native"],
    #           columns="metric_type",
    #           values="value",
    #           aggfunc="first",   # KEY_COLS is unique, so no real aggregation
    #       ).reset_index()
    #
    #    After this, you have columns: date, product_native, CLOSTLV,
    #    INDPROD, REFGROUT, TOTDEMO, TOTEXPSB, TOTIMPSB, X_STKCOVER, etc.
    #
    # 2. Compute the month-over-month change in stock level. Within each
    #    product_native group, sort by date and take the diff:
    #
    #       wide = wide.sort_values(["product_native", "date"])
    #       wide["delta_CLOSTLV"] = wide.groupby("product_native")["CLOSTLV"].diff()
    #
    #    The first month per product will have NaN for delta_CLOSTLV - that's
    #    expected and gets dropped at step 5.
    #
    # 3. Compute apparent consumption:
    #
    #       wide["apparent_consumption"] = (
    #           wide["INDPROD"].fillna(0)
    #           + wide["TOTIMPSB"].fillna(0)
    #           - wide["TOTEXPSB"].fillna(0)
    #           - wide["delta_CLOSTLV"].fillna(0)
    #       )
    #
    #    The fillna(0) is opinionated: it treats a missing TOTEXPSB (e.g. a
    #    product Australia doesn't export) as 0. If you'd rather propagate
    #    NaN through the computation (so missing -> missing), drop fillna.
    #
    # 4. Compute the statistical difference vs TOTDEMO:
    #
    #       wide["statistical_difference"] = wide["TOTDEMO"] - wide["apparent_consumption"]
    #       wide["statdiff_pct"] = wide["statistical_difference"] / wide["TOTDEMO"] * 100
    #
    # 5. Rename columns to the user-friendly names listed in the docstring,
    #    drop helper rows (where TOTDEMO or apparent_consumption is NaN),
    #    sort, and return.
    #
    # Sanity check (run in a notebook after implementing):
    #   For diesel oil: total in any recent month, the statistical
    #   difference should be small (a few percent at most). If it's
    #   huge, either the math is wrong or there's a unit mismatch
    #   you missed.
    #
    # Tip: this function only makes sense for products that exist in
    # MULTIPLE sheets. Crude oil (Petroleum production only, no sales)
    # will give junk results - your function should either skip such
    # products or document them as expected NaN output.

    # PHASE 4 STOPGAP: the "Sales of products" sheet labels its top-level
    # rows with a ": total" or " total" suffix that doesn't appear in any
    # other sheet ("Diesel oil: total" vs "Diesel oil", etc.). Until
    # reference/products.yaml is populated and the scraper does proper
    # canonicalisation, we hardcode the small alias map below so the
    # apparent-vs-reported comparison works for the major products today.
    # Sub-products like "Diesel oil: premium diesel" are intentionally
    # left alone — they have no supply-side counterpart, so their
    # apparent_consumption stays NaN as expected.
    _DEMAND_ALIASES = {
        "Diesel oil: total": "Diesel oil",
        "Aviation turbine fuel total": "Aviation turbine fuel",
        "Automotive gasoline total": "Automotive gasoline",
        "LPG total": "LPG",
    }
    df = df.copy()
    demand_rows = df["metric_type"] == "TOTDEMO"
    df.loc[demand_rows, "product_native"] = (
        df.loc[demand_rows, "product_native"].replace(_DEMAND_ALIASES)
    )

    # Step 1: pivot the tidy long-form into a wide frame where each
    # metric_type becomes its own column. Pivoting on (date,
    # product_native) is the natural index — date+product_native is the
    # rest of the unique key once country/source are fixed for Australia.
    wide = df.pivot_table(
        index=["date", "product_native"],
        columns="metric_type",
        values="value",
        aggfunc="first",  # KEY_COLS is unique per row, so this is identity
    ).reset_index()

    # Ensure every component column exists even if the input frame is
    # missing some metric_types (e.g. a freshly-cleared DB or partial
    # parse). Missing columns become NaN-filled.
    for c in ("INDPROD", "REFGROUT", "TOTIMPSB", "TOTEXPSB", "CLOSTLV", "TOTDEMO"):
        if c not in wide.columns:
            wide[c] = pd.NA

    # Step 2: month-over-month stock change per product. Sort first so
    # diff() is computed in calendar order. The first month per product
    # always has NaN delta — that's expected (no prior month to subtract).
    wide = wide.sort_values(["product_native", "date"])
    wide["delta_CLOSTLV"] = (
        wide.groupby("product_native")["CLOSTLV"].diff()
    )

    # Step 3: apparent consumption.
    #
    # Domestic supply for a given product is EITHER indigenous primary
    # production (INDPROD - applies to crude oil, condensate, natural gas)
    # OR refinery gross output (REFGROUT - applies to refined products
    # like diesel, gasoline, jet fuel). For any given product in DCCEEW's
    # data only one of these is populated (the other is NaN), so summing
    # both with fillna(0) gives us the right "domestic supply" term without
    # double-counting. Australia produces ~80% of its diesel domestically
    # via refineries — using only INDPROD would understate supply by that
    # much and inflate the statistical difference massively.
    #
    # The fillna(0) is opinionated: a missing TOTEXPSB for a product that
    # Australia doesn't export should contribute 0, not propagate NaN
    # through the whole row.
    wide["domestic_supply"] = (
        wide["INDPROD"].fillna(0) + wide["REFGROUT"].fillna(0)
    )
    wide["apparent_consumption"] = (
        wide["domestic_supply"]
        + wide["TOTIMPSB"].fillna(0)
        - wide["TOTEXPSB"].fillna(0)
        - wide["delta_CLOSTLV"].fillna(0)
    )

    # Step 4: gap vs reported. Statistical-difference is the metric
    # analysts actually care about — small (~few %) gaps are normal,
    # large gaps are a data-quality red flag.
    wide["statistical_difference"] = (
        wide["TOTDEMO"] - wide["apparent_consumption"]
    )

    # Percent gap. Replace zero denominators with NA so the division
    # propagates NA instead of producing inf. (We don't use np.where
    # here because pd.NA in a float column gets coerced to NaN, which
    # is exactly what we want.)
    denom = wide["TOTDEMO"].replace(0, pd.NA)
    wide["statdiff_pct"] = (
        wide["statistical_difference"] / denom * 100
    )

    # Step 5: select + rename to a friendly output schema. We drop rows
    # where BOTH apparent_consumption AND reported_sales are NaN/0 —
    # these are typically the first month per product (no delta_stocks
    # available) AND a product that only exists in one sheet (so the
    # other components are also missing). Such rows have no analytic
    # value.
    result = pd.DataFrame(
        {
            "date": wide["date"].values,
            "product_native": wide["product_native"].values,
            "indprod": wide["INDPROD"].values,
            "refgrout": wide["REFGROUT"].values,
            "domestic_supply": wide["domestic_supply"].values,
            "imports": wide["TOTIMPSB"].values,
            "exports": wide["TOTEXPSB"].values,
            "stocks": wide["CLOSTLV"].values,
            "delta_stocks": wide["delta_CLOSTLV"].values,
            "apparent_consumption": wide["apparent_consumption"].values,
            "reported_sales": wide["TOTDEMO"].values,
            "statistical_difference": wide["statistical_difference"].values,
            "statdiff_pct": wide["statdiff_pct"].values,
        }
    )

    # Drop rows where neither apparent_consumption nor reported_sales is
    # informative (both NA or both 0 means we have no useful signal).
    useless = (
        result[["apparent_consumption", "reported_sales"]]
        .fillna(0)
        .eq(0)
        .all(axis=1)
    )
    result = result.loc[~useless].copy()

    result = result.sort_values(
        ["date", "product_native"], ignore_index=True
    )

    logger.info(
        f"Apparent consumption computed: {len(result):,} "
        f"(date, product) rows; "
        f"{result['product_native'].nunique()} distinct products"
    )
    return result
