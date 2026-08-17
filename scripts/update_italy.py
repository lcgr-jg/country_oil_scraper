"""
update_italy.py
───────────────
End-to-end pipeline for Italy MASE petroleum consumption.

Usage (from country_oil_scraper/):
  python scripts/update_italy.py --bootstrap   # definitive 2002–2025 → parquet
  python scripts/update_italy.py               # latest preliminary → upsert
  python scripts/update_italy.py --force
  python scripts/update_italy.py --no-download # parse cached raw files only
  python scripts/update_italy.py --all-preliminaries --no-download  # upsert every local preconsuntivo month

Schedule
--------
Run monthly after MASE publishes preliminary data (typically mid-month):
  python scripts/update_italy.py
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scrapers.italy_mase import ItalyMaseScraper  # noqa: E402
import processors.italy_mase_consumption as processor  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

DATASET = "consumi_definitivi"
PRELIM_DATASET = "consumi_preconsuntivi"
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_PROCESSED_DIR = DEFAULT_DATA_DIR / "processed" / "italy"
DEFAULT_RAW_DIR = DEFAULT_DATA_DIR / "raw" / "italy"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Update Italy MASE petroleum consumption database"
    )
    p.add_argument(
        "--bootstrap",
        action="store_true",
        help="Build full series from definitive workbooks (2002–2025).",
    )
    p.add_argument(
        "--no-download",
        action="store_true",
        help="Skip live download; use cached raw files.",
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
        help="Parse a specific raw workbook instead of downloading.",
    )
    p.add_argument(
        "--all-preliminaries",
        action="store_true",
        help="Upsert every local Consumi_Petrolio_* file (not just the latest).",
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


def _upsert_all_local_preliminaries(
    scraper: ItalyMaseScraper,
    existing_df,
    raw_dir: Path,
):
    """Parse and upsert every cached preconsuntivo workbook in chronological order."""
    files = sorted(raw_dir.glob("Consumi_Petrolio_*.xls*"))
    if not files:
        logger.warning(f"No preliminary files found in {raw_dir}")
        return existing_df
    df = existing_df
    for path in files:
        logger.info(f"Upserting preliminary: {path.name}")
        new_df = scraper.parse(PRELIM_DATASET, path)
        df = processor.upsert(df, new_df)
    return df


def main() -> None:
    args = parse_args()
    scraper = ItalyMaseScraper(data_dir=str(args.data_dir))
    raw_dir = args.data_dir / "raw" / "italy"
    do_download = not args.no_download and args.local_file is None

    logger.info("=" * 60)
    logger.info("Italy MASE consumi petroliferi update")
    logger.info("=" * 60)

    existing_df = processor.load(args.output_dir)
    rows_before = len(existing_df) if existing_df is not None else 0

    if args.bootstrap:
        if do_download:
            scraper.download_definitive_history(force=args.force)
        updated_df = processor.build_from_historical(raw_dir)
        if args.all_preliminaries:
            updated_df = _upsert_all_local_preliminaries(scraper, updated_df, raw_dir)
    elif args.local_file is not None:
        raw_path = args.local_file
        if not raw_path.exists():
            logger.error(f"Local file not found: {raw_path}")
            sys.exit(1)
        dataset = (
            PRELIM_DATASET
            if "Consumi_Petrolio_" in raw_path.name
            else DATASET
        )
        new_df = scraper.parse(dataset, raw_path)
        updated_df = processor.upsert(existing_df, new_df)
    else:
        if existing_df is None:
            logger.error(
                "No existing parquet — run with --bootstrap first "
                "(downloads definitive files by default)."
            )
            sys.exit(1)
        if do_download:
            raw_path = scraper.download_latest_preliminary(force=args.force)
            new_df = scraper.parse(PRELIM_DATASET, raw_path)
            updated_df = processor.upsert(existing_df, new_df)
        elif args.all_preliminaries:
            updated_df = _upsert_all_local_preliminaries(
                scraper, existing_df, raw_dir
            )
        else:
            prelim_files = sorted(raw_dir.glob("Consumi_Petrolio_*.xls*"))
            if not prelim_files:
                logger.error(
                    f"No preliminary files in {raw_dir}. "
                    "Run without --no-download or pass --local-file."
                )
                sys.exit(1)
            raw_path = prelim_files[-1]
            logger.info(f"Using latest local preliminary: {raw_path.name}")
            new_df = scraper.parse(PRELIM_DATASET, raw_path)
            updated_df = processor.upsert(existing_df, new_df)

    paths = processor.save(updated_df, args.output_dir)

    rows_after = len(updated_df)
    logger.info("=" * 60)
    logger.info(f"  Rows before : {rows_before:,}")
    logger.info(f"  Rows after  : {rows_after:,}")
    logger.info(f"  Date range  : {updated_df['date'].min()} -> {updated_df['date'].max()}")
    logger.info(
        f"  Provisional : {int(updated_df['is_provisional'].sum()):,} rows"
    )
    logger.info(
        f"  Products    : {updated_df['product_native'].nunique()} native labels"
    )
    logger.info(f"  Parquet     : {paths['parquet']}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
