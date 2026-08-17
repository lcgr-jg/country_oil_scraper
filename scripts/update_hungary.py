"""
update_hungary.py
─────────────────
Bootstrap or refresh Hungary MEKH oil balance (demand + closing stocks).

Usage (from country_oil_scraper/):
  python scripts/update_hungary.py --bootstrap
  python scripts/update_hungary.py
  python scripts/update_hungary.py --force
  python scripts/update_hungary.py --no-download
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scrapers.hungary_mekh import HungaryMekhScraper  # noqa: E402
import processors.hungary_mekh_demand as processor  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_PROCESSED_DIR = DEFAULT_DATA_DIR / "processed" / "hungary"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Update Hungary MEKH demand + closing stocks database"
    )
    p.add_argument(
        "--bootstrap",
        action="store_true",
        help="Rebuild parquet from full OData snapshots.",
    )
    p.add_argument(
        "--no-download",
        action="store_true",
        help="Skip OData fetch; use cached snapshots.",
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
    scraper = HungaryMekhScraper(data_dir=args.data_dir)

    logger.info("=" * 60)
    logger.info("Hungary MEKH update (GID Observed + CSNATTER stocks)")
    logger.info("=" * 60)

    if not args.no_download:
        # Fixed-name OData snapshots; always refresh so new months are not
        # blocked by a stale local cache.
        scraper.download_all(force=True)
    else:
        missing = [
            p
            for p in (scraper.demand_snapshot_path, scraper.stocks_snapshot_path)
            if not p.exists()
        ]
        if missing:
            logger.error(
                "Missing cached snapshot(s): %s. Run without --no-download.",
                ", ".join(p.name for p in missing),
            )
            sys.exit(1)

    existing_df = processor.load(args.output_dir)
    rows_before = len(existing_df) if existing_df is not None else 0

    if args.bootstrap or existing_df is None:
        updated_df = processor.build_from_historical(args.data_dir)
    else:
        new_df = scraper.parse_all()
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
    logger.info(
        "  Provisional : %s rows",
        f"{int(updated_df['is_provisional'].sum()):,}",
    )
    logger.info("  Parquet     : %s", paths["parquet"])
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
