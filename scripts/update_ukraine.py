"""
update_ukraine.py
─────────────────
Bootstrap or refresh Ukraine SSSU fuel usage and reserves (demand + stocks).

Usage (from country_oil_scraper/):
  python scripts/update_ukraine.py --bootstrap
  python scripts/update_ukraine.py
  python scripts/update_ukraine.py --force
  python scripts/update_ukraine.py --no-download
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scrapers.ukraine_sssu import UkraineSssuScraper  # noqa: E402
import processors.ukraine_sssu_fuel as processor  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_PROCESSED_DIR = DEFAULT_DATA_DIR / "processed" / "ukraine"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Update Ukraine SSSU fuel demand + closing stocks database"
    )
    p.add_argument(
        "--bootstrap",
        action="store_true",
        help="Rebuild parquet from all cached CSV snapshots.",
    )
    p.add_argument(
        "--no-download",
        action="store_true",
        help="Skip SDMX fetch; use cached CSV files only.",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Accepted for CLI compatibility; downloads already refresh by default.",
    )
    p.add_argument("--output-dir", type=Path, default=DEFAULT_PROCESSED_DIR)
    p.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    scraper = UkraineSssuScraper(data_dir=args.data_dir)

    logger.info("=" * 60)
    logger.info("Ukraine SSSU update (fuel used + fuel reserves)")
    logger.info("=" * 60)

    if not args.no_download:
        # Full-history snapshot uses a fixed filename; always refresh so new
        # months (e.g. May 2026) are not blocked by a stale local cache.
        scraper.download(force=True)
    elif not scraper.list_raw_csv_files():
        logger.error(
            "No cached CSV in %s. Run without --no-download.",
            scraper.raw_dir,
        )
        sys.exit(1)

    existing_df = processor.load(args.output_dir)
    rows_before = len(existing_df) if existing_df is not None else 0

    if args.bootstrap or existing_df is None:
        updated_df = processor.build_from_historical(args.data_dir)
    else:
        new_df = scraper.parse()
        updated_df = processor.upsert(existing_df, new_df)

    paths = processor.save(updated_df, args.output_dir)

    rows_after = len(updated_df)
    logger.info("=" * 60)
    logger.info("  Rows before : %s", f"{rows_before:,}")
    logger.info("  Rows after  : %s", f"{rows_after:,}")
    logger.info(
        "  Date range  : %s -> %s",
        updated_df["date"].min(),
        updated_df["date"].max(),
    )
    logger.info("  Metrics     : %s", sorted(updated_df["metric_type"].unique()))
    logger.info("  Products    : %s", updated_df["product_native"].nunique())
    for metric in sorted(updated_df["metric_type"].unique()):
        sub = updated_df[updated_df["metric_type"] == metric]
        logger.info(
            "    %s : %s -> %s (%s rows)",
            metric,
            sub["date"].min(),
            sub["date"].max(),
            f"{len(sub):,}",
        )
    logger.info("  Parquet     : %s", paths["parquet"])
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
