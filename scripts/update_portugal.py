"""
update_portugal.py
──────────────────
Bootstrap or refresh Portugal DGEG monthly oil product sales database.

Usage (from country_oil_scraper/):
  python scripts/update_portugal.py
  python scripts/update_portugal.py --bootstrap
  python scripts/update_portugal.py --force
  python scripts/update_portugal.py --no-download
  python scripts/update_portugal.py --local-file data/raw/portugal/dgeg-omn-2026-04_en.xlsx
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scrapers.portugal_dgeg import PortugalDGEGScraper  # noqa: E402
import processors.portugal_dgeg_sales as processor  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_PROCESSED_DIR = DEFAULT_DATA_DIR / "processed" / "portugal"
DEFAULT_RAW_DIR = DEFAULT_DATA_DIR / "raw" / "portugal"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Update Portugal DGEG monthly oil product sales database"
    )
    p.add_argument(
        "--bootstrap",
        action="store_true",
        help="Rebuild parquet from all local DGEG workbooks (since 2006).",
    )
    p.add_argument(
        "--download-history",
        action="store_true",
        help="With --bootstrap, download all historical workbooks from DGEG first.",
    )
    p.add_argument(
        "--no-download",
        action="store_true",
        help="Skip DGEG download; use cached or --local-file.",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Re-download even when a matching local copy exists.",
    )
    p.add_argument(
        "--local-file",
        type=Path,
        default=None,
        help="Parse a specific workbook instead of downloading latest.",
    )
    p.add_argument("--output-dir", type=Path, default=DEFAULT_PROCESSED_DIR)
    p.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    return p.parse_args()


def _resolve_workbook(
    scraper: PortugalDGEGScraper, args: argparse.Namespace
) -> Path:
    if args.local_file is not None:
        path = Path(args.local_file)
        if not path.exists():
            logger.error("Local file not found: %s", path)
            sys.exit(1)
        return path

    if not args.no_download:
        return scraper.download_latest(force=args.force).path

    path = scraper.latest_local_workbook()
    if path is None:
        logger.error(
            "No local workbook under %s. Run without --no-download.",
            scraper.raw_dir,
        )
        sys.exit(1)
    logger.info("Using cached workbook: %s", path.name)
    return path


def main() -> None:
    args = parse_args()
    scraper = PortugalDGEGScraper(data_dir=args.data_dir)

    logger.info("=" * 60)
    logger.info("Portugal DGEG monthly sales update")
    logger.info("=" * 60)

    if args.bootstrap and args.download_history and not args.no_download:
        paths = scraper.download_bootstrap(force=args.force)
        logger.info("Downloaded / cached %d historical workbook(s)", len(paths))

    existing_df = processor.load(args.output_dir)
    rows_before = len(existing_df) if existing_df is not None else 0

    if args.bootstrap or existing_df is None:
        if not scraper.local_workbooks():
            if args.no_download:
                logger.error(
                    "No local workbooks under %s. Run with --download-history.",
                    DEFAULT_RAW_DIR,
                )
                sys.exit(1)
            scraper.download_bootstrap(force=args.force)
        updated_df = processor.build_from_historical(DEFAULT_RAW_DIR)
    else:
        raw_path = _resolve_workbook(scraper, args)
        new_df = scraper.parse("monthly_sales", raw_path)
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
