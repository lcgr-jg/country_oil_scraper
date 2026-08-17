"""
update_india_pt_consumption.py
──────────────────────────────
End-to-end pipeline for the India PPAC PT Consumption database.

Usage
-----
  # From the project root (country_oil_scraper/):
  python scripts/update_india_pt_consumption.py

  # Bootstrap from the historical .xls (first run or full rebuild):
  python scripts/update_india_pt_consumption.py --bootstrap

  # Skip the live download and only rebuild from a local file:
  python scripts/update_india_pt_consumption.py --local-file data/raw/india/1778131889_PT_Consumption.xlsx

  # Full rebuild from the historical archive:
  python scripts/update_india_pt_consumption.py --bootstrap --historical-file data/raw/india/1777985064_PT_Consumption_English.xls

Schedule
--------
Run monthly (e.g. via Windows Task Scheduler or cron) to keep the DB current:
  cron:  0 6 1 * *  cd /path/to/country_oil_scraper && python scripts/update_india_pt_consumption.py
"""

import argparse
import logging
import sys
from pathlib import Path

# Make sure the project root is on sys.path so we can import scrapers/processors
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scrapers.india_ppac import IndiaPPACScraper          # noqa: E402
import processors.india_pt_consumption as processor        # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_PROCESSED_DIR = DEFAULT_DATA_DIR / "processed" / "india"
DEFAULT_HISTORICAL_FILE = (
    DEFAULT_DATA_DIR / "raw" / "india" / "1777985064_PT_Consumption_English.xls"
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Update India PT Consumption database")
    p.add_argument(
        "--bootstrap",
        action="store_true",
        help="Rebuild the full database from the historical .xls before applying updates.",
    )
    p.add_argument(
        "--historical-file",
        type=Path,
        default=DEFAULT_HISTORICAL_FILE,
        metavar="PATH",
        help=f"Path to the historical .xls bootstrap file (default: {DEFAULT_HISTORICAL_FILE})",
    )
    p.add_argument(
        "--local-file",
        type=Path,
        default=None,
        metavar="PATH",
        help="Use a local Excel file instead of downloading from PPAC.",
    )
    p.add_argument(
        "--no-download",
        action="store_true",
        help="Skip the live PPAC download entirely (useful for offline re-processing).",
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_PROCESSED_DIR,
        metavar="DIR",
        help=f"Directory for output files (default: {DEFAULT_PROCESSED_DIR})",
    )
    p.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        metavar="DIR",
        help="Root data directory passed to IndiaPPACScraper.",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()

    logger.info("=" * 60)
    logger.info("India PT Consumption update pipeline")
    logger.info("=" * 60)

    scraper = IndiaPPACScraper(data_dir=str(args.data_dir))

    # ------------------------------------------------------------------ #
    # 1. Load (or build) existing database
    # ------------------------------------------------------------------ #
    existing_df = processor.load(args.output_dir)
    rows_before = len(existing_df) if existing_df is not None else 0

    if args.bootstrap or existing_df is None:
        if not args.historical_file.exists():
            logger.error(f"Historical file not found: {args.historical_file}")
            logger.error("Download it from PPAC or pass --historical-file PATH")
            sys.exit(1)
        logger.info(f"[Bootstrap] Parsing historical file: {args.historical_file}")
        existing_df = processor.build_from_historical(args.historical_file)
        logger.info(f"[Bootstrap] {len(existing_df)} rows loaded from historical file")

    # ------------------------------------------------------------------ #
    # 2. Get the latest file (download or local)
    # ------------------------------------------------------------------ #
    latest_path: Path | None = None

    if args.local_file is not None:
        if not args.local_file.exists():
            logger.error(f"Local file not found: {args.local_file}")
            sys.exit(1)
        latest_path = args.local_file
        logger.info(f"[Source] Using local file: {latest_path}")
    elif not args.no_download:
        logger.info("[Download] Fetching latest PT Consumption from PPAC…")
        try:
            latest_path = scraper.download("pt_consumption")
            logger.info(f"[Download] Saved to: {latest_path}")
        except Exception as exc:
            logger.warning(f"[Download] Failed: {exc}")
            logger.warning("[Download] Skipping update step — database unchanged since bootstrap.")

    # ------------------------------------------------------------------ #
    # 3. Parse latest file and upsert
    # ------------------------------------------------------------------ #
    if latest_path is not None:
        logger.info(f"[Parse] Parsing: {latest_path.name}")
        new_df = scraper.parse("pt_consumption", latest_path)
        logger.info(f"[Parse] {len(new_df)} rows parsed from latest file")

        updated_df = processor.upsert(existing_df, new_df)
    else:
        updated_df = existing_df

    # ------------------------------------------------------------------ #
    # 4. Save
    # ------------------------------------------------------------------ #
    logger.info(f"[Save] Writing to: {args.output_dir}")
    paths = processor.save(updated_df, args.output_dir)

    # ------------------------------------------------------------------ #
    # 5. Summary
    # ------------------------------------------------------------------ #
    rows_after = len(updated_df)
    rows_added = rows_after - rows_before

    logger.info("=" * 60)
    logger.info("Summary")
    logger.info(f"  Rows before : {rows_before:,}")
    logger.info(f"  Rows after  : {rows_after:,}")
    logger.info(f"  Net change  : {rows_added:+,}")
    logger.info(f"  Date range  : {updated_df['date'].min()}  →  {updated_df['date'].max()}")
    logger.info(f"  Products    : {sorted(updated_df.loc[~updated_df['is_total_row'], 'product'].unique())}")
    logger.info(f"  Parquet     : {paths['parquet']}")
    # The SQLite mirror is opt-in via processor.save(write_sqlite=True).
    # Only log it when present so we don't print "SQLite: None".
    if paths.get("sqlite"):
        logger.info(f"  SQLite      : {paths['sqlite']}")
    logger.info("=" * 60)

    print("\nDone. Quick-access examples:")
    print(f"  import pandas as pd")
    print(f"  df = pd.read_parquet(r'{paths['parquet']}')")
    print(f"  df[df.product == 'HSD'].sort_values('date')")
    if paths.get("sqlite"):
        print()
        print(f"  import sqlite3, pandas as pd")
        print(f"  con = sqlite3.connect(r'{paths['sqlite']}')")
        print(f"  df = pd.read_sql('SELECT * FROM pt_consumption WHERE product = \"HSD\"', con)")


if __name__ == "__main__":
    main()
