"""
update_poland.py
────────────────
Bootstrap or refresh Poland ARE liquid fuels market database.

Usage (from country_oil_scraper/):
  python scripts/update_poland.py
  python scripts/update_poland.py --bootstrap
  python scripts/update_poland.py --bootstrap --download-history
  python scripts/update_poland.py --force
  python scripts/update_poland.py --no-download
  python scripts/update_poland.py --local-file data/raw/poland/are/Biuletyn_marzec_2026.xls
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scrapers.poland_are import PolandAreScraper  # noqa: E402
import processors.poland_are_liquid_fuels as processor  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_PROCESSED_DIR = DEFAULT_DATA_DIR / "processed" / "poland"
DEFAULT_RAW_DIR = DEFAULT_DATA_DIR / "raw" / "poland" / "are"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Update Poland ARE liquid fuels market database"
    )
    p.add_argument(
        "--bootstrap",
        action="store_true",
        help="Rebuild parquet from all local ARE Biuletyn workbooks.",
    )
    p.add_argument(
        "--download-history",
        action="store_true",
        help="With --bootstrap, download all linked Biuletyn files from ARE first.",
    )
    p.add_argument(
        "--no-download",
        action="store_true",
        help="Skip ARE download; use cached or --local-file.",
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
        help="Parse a specific Biuletyn workbook instead of downloading latest.",
    )
    p.add_argument("--output-dir", type=Path, default=DEFAULT_PROCESSED_DIR)
    p.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    return p.parse_args()


def _resolve_bulletin(
    scraper: PolandAreScraper, args: argparse.Namespace
) -> Path:
    if args.local_file is not None:
        path = Path(args.local_file)
        if not path.exists():
            logger.error("Local file not found: %s", path)
            sys.exit(1)
        return path

    if not args.no_download:
        return scraper.download_latest(force=args.force).path

    path = scraper.latest_local_bulletin()
    if path is None:
        logger.error(
            "No local bulletin under %s. Run without --no-download.",
            scraper.raw_dir,
        )
        sys.exit(1)
    logger.info("Using cached bulletin: %s", path.name)
    return path


def main() -> None:
    args = parse_args()
    scraper = PolandAreScraper(data_dir=args.data_dir)

    logger.info("=" * 60)
    logger.info("Poland ARE liquid fuels update")
    logger.info("=" * 60)

    if args.bootstrap and args.download_history and not args.no_download:
        paths = scraper.download_bootstrap(force=args.force)
        logger.info("Downloaded / cached %d bulletin(s)", len(paths))

    existing_df = processor.load(args.output_dir)
    rows_before = len(existing_df) if existing_df is not None else 0

    if args.bootstrap or existing_df is None:
        if not scraper.local_bulletins():
            if args.no_download:
                logger.error(
                    "No local bulletins under %s. Run with --download-history.",
                    DEFAULT_RAW_DIR,
                )
                sys.exit(1)
            scraper.download_bootstrap(force=args.force)
        updated_df = processor.build_from_historical(DEFAULT_RAW_DIR)
    else:
        raw_path = _resolve_bulletin(scraper, args)
        new_df = scraper.parse("liquid_fuels", raw_path)
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
    logger.info("  Metrics     : %s", sorted(updated_df["metric_type"].unique()))
    logger.info(
        "  Provisional : %s rows",
        f"{int(updated_df['is_provisional'].sum()):,}",
    )
    logger.info("  Parquet     : %s", paths["parquet"])
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
