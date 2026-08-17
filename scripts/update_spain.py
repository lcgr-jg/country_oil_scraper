"""
update_spain.py
───────────────
Bootstrap or refresh Spain CORES petroleum product consumption database.

Usage (from country_oil_scraper/):
  python scripts/update_spain.py
  python scripts/update_spain.py --bootstrap
  python scripts/update_spain.py --force
  python scripts/update_spain.py --no-download
  python scripts/update_spain.py --local-file data/raw/spain/oil-products-consumption.xlsx
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scrapers.spain_cores import SpainCoresScraper  # noqa: E402
import processors.spain_cores_consumption as processor  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_PROCESSED_DIR = DEFAULT_DATA_DIR / "processed" / "spain"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Update Spain CORES petroleum consumption database"
    )
    p.add_argument(
        "--bootstrap",
        action="store_true",
        help="Rebuild parquet from the latest CORES workbook.",
    )
    p.add_argument(
        "--no-download",
        action="store_true",
        help="Skip CORES download; use cached or --local-file.",
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
        help="Parse a specific workbook instead of downloading.",
    )
    p.add_argument("--output-dir", type=Path, default=DEFAULT_PROCESSED_DIR)
    p.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    return p.parse_args()


def _resolve_workbook(
    scraper: SpainCoresScraper, args: argparse.Namespace
) -> Path:
    if args.local_file is not None:
        path = Path(args.local_file)
        if not path.exists():
            logger.error("Local file not found: %s", path)
            sys.exit(1)
        return path

    if not args.no_download:
        return scraper.download(force=args.force).path

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
    scraper = SpainCoresScraper(data_dir=args.data_dir)

    logger.info("=" * 60)
    logger.info("Spain CORES consumption update")
    logger.info("=" * 60)

    raw_path = _resolve_workbook(scraper, args)
    existing_df = processor.load(args.output_dir)
    rows_before = len(existing_df) if existing_df is not None else 0

    if args.bootstrap or existing_df is None:
        updated_df = processor.build_from_historical(raw_path)
    else:
        new_df = scraper.parse("petroleum_consumption", raw_path)
        updated_df = processor.upsert(existing_df, new_df)

    paths = processor.save(updated_df, args.output_dir)

    rows_after = len(updated_df)
    logger.info("=" * 60)
    logger.info("  Rows before : %s", f"{rows_before:,}")
    logger.info("  Rows after  : %s", f"{rows_after:,}")
    logger.info("  Date range  : %s -> %s", updated_df["date"].min(), updated_df["date"].max())
    logger.info("  Products    : %s", updated_df["product_native"].nunique())
    logger.info("  Parquet     : %s", paths["parquet"])
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
