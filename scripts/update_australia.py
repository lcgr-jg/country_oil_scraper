"""
update_australia.py
───────────────────
End-to-end pipeline for the Australia DCCEEW Petroleum Statistics database.

Usage
-----
  # From the project root (country_oil_scraper/):
  python scripts/update_australia.py

  # Force re-download even if a cached xlsx exists:
  python scripts/update_australia.py --force

  # Skip the live download (use a previously-downloaded xlsx):
  python scripts/update_australia.py --no-download

  # Bootstrap from a specific local file (e.g. a saved historical
  # vintage) instead of downloading:
  python scripts/update_australia.py --local-file data/raw/australia/australian_petroleum_statistics_-_data_extract_february_2026.xlsx

Schedule
--------
Run monthly (DCCEEW publishes around the 25th of each month):
  cron:  0 6 28 * *  cd /path/to/country_oil_scraper && python scripts/update_australia.py

Phase status (Phase 2b - 2026-05)
─────────────────────────────────
This is a TODO skeleton. See ``main()`` and the comment blocks below for
the implementation steps. Compare with ``scripts/update_india_pt_consumption.py``
- the structure is nearly identical, only the imports and the "do we
need a separate historical bootstrap?" branch differ (Australia doesn't,
because every monthly xlsx contains the full history).
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Make sure the project root is on sys.path so we can import scrapers/processors.
# This script lives in scripts/, so parents[1] is country_oil_scraper/.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scrapers.australia_apstat import AustraliaAPStatScraper  # noqa: E402
import processors.australia_petroleum_statistics as processor  # noqa: E402


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_PROCESSED_DIR = DEFAULT_DATA_DIR / "processed" / "australia"


def parse_args() -> argparse.Namespace:
    """CLI argument parser. Already wired - no TODOs here."""
    p = argparse.ArgumentParser(
        description="Update the Australia DCCEEW Petroleum Statistics database"
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Force re-download even if a cached xlsx exists in data/raw/australia/.",
    )
    p.add_argument(
        "--no-download",
        action="store_true",
        help="Skip the live download entirely. Will fail unless --local-file is also passed.",
    )
    p.add_argument(
        "--local-file",
        type=Path,
        default=None,
        metavar="PATH",
        help="Use a specific local xlsx instead of downloading.",
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_PROCESSED_DIR,
        metavar="DIR",
        help=f"Directory for output files (default: {DEFAULT_PROCESSED_DIR}).",
    )
    p.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        metavar="DIR",
        help="Root data directory passed to AustraliaAPStatScraper.",
    )
    return p.parse_args()


def main() -> None:
    """
    Pipeline:
      1. Load existing DB (or None on first run).
      2. Acquire the latest xlsx (download via scraper, or --local-file).
      3. Parse it into a tidy DataFrame.
      4. Upsert into the existing DB.
      5. Save parquet (SQLite mirror is opt-in via the processor).
      6. Print a summary + quick-query examples.

    Most of the work is delegated to the scraper and processor modules -
    this function is mostly orchestration + logging.
    """
    args = parse_args()

    logger.info("=" * 60)
    logger.info("Australia DCCEEW Petroleum Statistics update pipeline")
    logger.info("=" * 60)

    # Pass args.data_dir explicitly so a --data-dir override works if the
    # script is ever invoked against a separate data tree (test sandbox,
    # multi-vintage comparisons, etc.).
    scraper = AustraliaAPStatScraper(data_dir=str(args.data_dir))

    # ------------------------------------------------------------------ #
    # 1. Load existing DB
    # ------------------------------------------------------------------ #
    existing_df = processor.load(args.output_dir)
    rows_before = len(existing_df) if existing_df is not None else 0

    # ------------------------------------------------------------------ #
    # 2. Acquire the latest xlsx
    # ------------------------------------------------------------------ #
    latest_path: Path | None = None

    if args.local_file is not None:
        if not args.local_file.exists():
            logger.error(f"Local file not found: {args.local_file}")
            sys.exit(1)
        latest_path = args.local_file
        logger.info(f"[Source] Using local file: {latest_path}")
    elif not args.no_download:
        # The scraper's download() is idempotent: it caches by filename
        # and skips the network call when a same-size local copy exists.
        # --force flips that off so we always re-fetch (useful when DCCEEW
        # silently revises an already-published file).
        logger.info("[Download] Fetching latest xlsx from DCCEEW...")
        try:
            latest_path = scraper.download(
                "petroleum_statistics", force=args.force
            )
            logger.info(f"[Download] Got: {latest_path}")
        except Exception as exc:
            logger.error(f"[Download] Failed: {exc}")
            sys.exit(1)
    else:
        logger.error(
            "Neither --local-file nor a live download is allowed "
            "(--no-download was set). Nothing to do."
        )
        sys.exit(1)

    # ------------------------------------------------------------------ #
    # 3. Parse the xlsx
    # ------------------------------------------------------------------ #
    if latest_path is None:
        logger.error("[Parse] No file to parse. Aborting.")
        sys.exit(1)

    logger.info(f"[Parse] Parsing: {latest_path.name}")
    new_df = scraper.parse("petroleum_statistics", latest_path)
    logger.info(f"[Parse] Got {len(new_df):,} rows")

    # ------------------------------------------------------------------ #
    # 4. Upsert
    # ------------------------------------------------------------------ #
    # processor.upsert handles the existing_df=None edge case (first run)
    # internally, so we don't branch here.
    updated_df = processor.upsert(existing_df, new_df)

    # ------------------------------------------------------------------ #
    # 5. Save
    # ------------------------------------------------------------------ #
    logger.info(f"[Save] Writing to: {args.output_dir}")
    paths = processor.save(updated_df, args.output_dir)

    # ------------------------------------------------------------------ #
    # 6. Summary
    # ------------------------------------------------------------------ #
    if updated_df is None or updated_df.empty:
        logger.warning("Pipeline produced no data. Skipping summary.")
        return

    rows_after = len(updated_df)
    logger.info("=" * 60)
    logger.info("Summary")
    logger.info(f"  Rows before : {rows_before:,}")
    logger.info(f"  Rows after  : {rows_after:,}")
    logger.info(f"  Net change  : {rows_after - rows_before:+,}")
    logger.info(
        f"  Date range  : {updated_df['date'].min()} -> {updated_df['date'].max()}"
    )
    logger.info(f"  Metrics     : {sorted(updated_df['metric_type'].unique())}")
    logger.info(
        f"  Products    : {updated_df['product_native'].nunique()} distinct"
    )
    logger.info(f"  Parquet     : {paths.get('parquet')}")
    # The SQLite mirror is opt-in via processor.save(write_sqlite=True).
    # Only log it when present so we don't print "SQLite: None".
    if paths.get("sqlite"):
        logger.info(f"  SQLite      : {paths.get('sqlite')}")
    logger.info("=" * 60)

    print("\nDone. Quick-access examples:")
    print(f"  import pandas as pd")
    print(f"  df = pd.read_parquet(r'{paths.get('parquet')}')")
    print(
        f"  df[(df.metric_type=='TOTDEMO') & (df.product_native=='Diesel oil: total')]"
    )
    if paths.get("sqlite"):
        print()
        print(f"  import sqlite3, pandas as pd")
        print(f"  con = sqlite3.connect(r'{paths.get('sqlite')}')")
        print(
            f"  df = pd.read_sql(\"SELECT * FROM petroleum_statistics "
            f"WHERE metric_type='TOTDEMO'\", con)"
        )


if __name__ == "__main__":
    main()
