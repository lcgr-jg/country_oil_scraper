"""
update_thailand.py
──────────────────
Bootstrap or refresh the Thailand EPPO petroleum sales database.

Usage (from country_oil_scraper/):
  python scripts/update_thailand.py
  python scripts/update_thailand.py --bootstrap
  python scripts/update_thailand.py --force
  python scripts/update_thailand.py --no-download
  python scripts/update_thailand.py --local-file data/raw/thailand/T02_03_04.xls

Schedule
--------
Run monthly after EPPO publishes (same pattern as other country updaters):
  python scripts/update_thailand.py
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scrapers.thailand_eppo import ThailandEPPOScraper  # noqa: E402
import processors.thailand_eppo_sales as processor  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

DATASET = "petroleum_sales"
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_PROCESSED_DIR = DEFAULT_DATA_DIR / "processed" / "thailand"
DEFAULT_RAW_DIR = DEFAULT_DATA_DIR / "raw" / "thailand"
DEFAULT_HISTORICAL = DEFAULT_RAW_DIR / processor.DEFAULT_HISTORICAL
DEFAULT_CURRENT = DEFAULT_RAW_DIR / processor.DEFAULT_CURRENT


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Update Thailand EPPO Table 2.3-4 sales database"
    )
    p.add_argument(
        "--bootstrap",
        action="store_true",
        help="Build full series from historical + current workbooks.",
    )
    p.add_argument(
        "--no-download",
        action="store_true",
        help="Skip the live EPPO download (use cached or --local-file paths).",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Re-download even when a matching local copy exists.",
    )
    p.add_argument(
        "--historical-file",
        type=Path,
        default=DEFAULT_HISTORICAL,
        help=f"Historical workbook (default: {DEFAULT_HISTORICAL.name})",
    )
    p.add_argument(
        "--current-file",
        type=Path,
        default=DEFAULT_CURRENT,
        help=f"Current snapshot workbook (default: {DEFAULT_CURRENT.name})",
    )
    p.add_argument(
        "--local-file",
        type=Path,
        default=None,
        help="Use a specific current workbook instead of downloading.",
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_PROCESSED_DIR,
    )
    p.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
    )
    return p.parse_args()


def _require_file(label: str, path: Path) -> None:
    if not path.exists():
        logger.error(f"{label} file not found: {path}")
        sys.exit(1)


def main() -> None:
    args = parse_args()
    scraper = ThailandEPPOScraper(data_dir=str(args.data_dir))

    historical_path = args.historical_file
    current_path = args.local_file or args.current_file
    do_download = not args.no_download and args.local_file is None

    if do_download:
        if args.bootstrap:
            paths = scraper.download_both(DATASET, force=args.force)
            historical_path = paths["historical"]
            current_path = paths["current"]
        else:
            current_path = scraper.download(DATASET, force=args.force)
    elif args.local_file is None and args.no_download:
        logger.info(
            "[Source] --no-download: using local paths "
            f"(current={current_path.name})"
        )

    logger.info("=" * 60)
    logger.info("Thailand EPPO sales update")
    logger.info("=" * 60)

    existing_df = processor.load(args.output_dir)
    rows_before = len(existing_df) if existing_df is not None else 0

    # Routine refresh: re-parse the current workbook (downloaded or cached).
    refresh_current = not args.bootstrap and (
        args.local_file is not None
        or do_download
        or (args.no_download and existing_df is not None)
    )

    if args.bootstrap or (existing_df is None and not refresh_current):
        _require_file("Historical", historical_path)
        _require_file("Current", current_path)
        existing_df = processor.build_from_historical(
            historical_path, current_path
        )
    elif refresh_current:
        if existing_df is None:
            logger.error(
                "No existing parquet — run with --bootstrap first "
                "(downloads both workbooks from EPPO by default)."
            )
            sys.exit(1)
        _require_file("Current", current_path)
        logger.info(f"Parsing current file: {current_path.name}")
        new_df = scraper.parse(DATASET, current_path)
        hist_part = existing_df[
            existing_df["date"] < pd.Timestamp("2025-01-01")
        ]
        existing_df = processor.upsert(hist_part, new_df)
    elif existing_df is None:
        logger.error(
            "No existing database. Use --bootstrap or pass --local-file."
        )
        sys.exit(1)

    updated_df = existing_df
    paths = processor.save(updated_df, args.output_dir)

    rows_after = len(updated_df)
    logger.info("=" * 60)
    logger.info(f"  Rows before : {rows_before:,}")
    logger.info(f"  Rows after  : {rows_after:,}")
    logger.info(f"  Date range  : {updated_df['date'].min()} -> {updated_df['date'].max()}")
    logger.info(
        f"  Provisional : {int(updated_df['is_provisional'].sum()):,} rows"
    )
    logger.info(f"  Parquet     : {paths['parquet']}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
