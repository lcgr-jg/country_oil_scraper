"""
update_norway.py
────────────────
Bootstrap or refresh Norway SSB monthly petroleum product sales database.

Usage (from country_oil_scraper/):
  python scripts/update_norway.py --bootstrap
  python scripts/update_norway.py
  python scripts/update_norway.py --force
  python scripts/update_norway.py --no-download
  python scripts/update_norway.py --local-file data/raw/norway/Monthly\\ sales....xlsx
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scrapers.norway_ssb import NorwaySsbScraper  # noqa: E402
import processors.norway_ssb_sales as processor  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_PROCESSED_DIR = DEFAULT_DATA_DIR / "processed" / "norway"
DEFAULT_RAW_DIR = DEFAULT_DATA_DIR / "raw" / "norway"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Update Norway SSB monthly petroleum product sales database"
    )
    p.add_argument(
        "--bootstrap",
        action="store_true",
        help="Rebuild parquet from all StatBank eras (1995+).",
    )
    p.add_argument(
        "--no-download",
        action="store_true",
        help="Skip StatBank download; use cached snapshot or --local-file.",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Re-download StatBank snapshot even when cached.",
    )
    p.add_argument(
        "--local-file",
        type=Path,
        default=None,
        help="Parse a Table 3 xlsx export instead of the API snapshot.",
    )
    p.add_argument("--output-dir", type=Path, default=DEFAULT_PROCESSED_DIR)
    p.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    return p.parse_args()


def _resolve_new_data(
    scraper: NorwaySsbScraper, args: argparse.Namespace
) -> "pd.DataFrame":
    import pandas as pd  # noqa: WPS433 — lazy import keeps CLI startup fast

    if args.local_file is not None:
        path = Path(args.local_file)
        if not path.exists():
            logger.error("Local file not found: %s", path)
            sys.exit(1)
        return scraper.parse_workbook(path)

    if not args.no_download:
        scraper.download_current(force=args.force)

    snapshot = scraper.current_snapshot_path
    if not snapshot.exists():
        workbook = scraper.latest_local_workbook()
        if workbook is None:
            logger.error(
                "No cached SSB data under %s. Run without --no-download.",
                scraper.raw_dir,
            )
            sys.exit(1)
        logger.info("Using cached workbook: %s", workbook.name)
        return scraper.parse_workbook(workbook)

    return scraper.parse_current_snapshot(snapshot)


def main() -> None:
    args = parse_args()
    scraper = NorwaySsbScraper(data_dir=args.data_dir)

    logger.info("=" * 60)
    logger.info("Norway SSB update (Table 3 monthly product sales)")
    logger.info("=" * 60)

    existing_df = processor.load(args.output_dir)
    rows_before = len(existing_df) if existing_df is not None else 0

    if args.bootstrap or existing_df is None:
        updated_df = processor.build_from_historical(args.data_dir)
    else:
        new_df = _resolve_new_data(scraper, args)
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
    logger.info("  Products    : %s", updated_df["product_native"].nunique())
    logger.info(
        "  Provisional : %s rows",
        f"{int(updated_df['is_provisional'].sum()):,}",
    )
    logger.info("  Parquet     : %s", paths["parquet"])
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
