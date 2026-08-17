"""
update_jodi.py
──────────────
End-to-end pipeline for the JODI-Oil World Database (primary & secondary).

Usage
-----
  # From the project root (country_oil_scraper/):

  # First-time bootstrap from your existing local CSVs (no download)
  python scripts/update_jodi.py --bootstrap --no-download

  # Bootstrap then refresh current-year file from JODI
  python scripts/update_jodi.py --bootstrap

  # Routine monthly update (download current year + upsert)
  python scripts/update_jodi.py

  # Only update one of the datasets
  python scripts/update_jodi.py --dataset secondary

  # Force-download a specific year (e.g. backfill 2020)
  python scripts/update_jodi.py --dataset primary --year 2020 --force

  # Opt-in to writing the SQLite mirror (parquet is always written)
  python scripts/update_jodi.py --sqlite

Schedule
--------
JODI refreshes the current year-to-date file monthly (timing varies, often
mid-to-late month). The scraper HEAD-checks the remote YTD file so a daily
job picks up new months without --force:
  cron:  0 6 * * *  cd /path/to/country_oil_scraper && python scripts/update_jodi.py
  Windows Task Scheduler: daily, same command with the project venv python.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

# Project-root onto sys.path so ``scrapers`` and ``processors`` import cleanly
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scrapers.jodi import JodiScraper        # noqa: E402
import processors.jodi as processor          # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_RAW_JODI_DIR = DEFAULT_DATA_DIR / "raw" / "jodi"
DEFAULT_PROCESSED_DIR = DEFAULT_DATA_DIR / "processed" / "jodi"
DEFAULT_COUNTRY_CODES = PROJECT_ROOT / "reference" / "country_codes.xlsx"

DATASETS = ("secondary", "primary")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Update the JODI consolidated DB")
    p.add_argument(
        "--dataset",
        choices=[*DATASETS, "all"],
        default="all",
        help="Which JODI dataset to process (default: all).",
    )
    p.add_argument(
        "--bootstrap",
        action="store_true",
        help="Rebuild the full DB from all local CSVs before applying any update.",
    )
    p.add_argument(
        "--year",
        type=int,
        default=None,
        help="Year to download (default: current calendar year).",
    )
    p.add_argument(
        "--no-download",
        action="store_true",
        help="Skip the live JODI download (useful for offline rebuild).",
    )
    p.add_argument(
        "--download-history",
        action="store_true",
        help="Download every annual CSV from 2002 to the current year that "
             "isn't already on disk. Useful for bootstrapping a dataset where "
             "you only have the YTD file locally (e.g. JODI primary).",
    )
    p.add_argument(
        "--local-file",
        type=Path,
        default=None,
        help="Skip download and use this local CSV as the 'latest' input. "
             "When given, --dataset must be a single dataset.",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Force re-download even if the local file already exists.",
    )
    p.add_argument(
        "--sqlite",
        action="store_true",
        help="Opt in to writing the SQLite mirror. Parquet is always written. "
             "Default is parquet only — the project's notebooks load via "
             "pd.read_parquet and don't need SQLite.",
    )
    p.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help=f"Root data directory (default: {DEFAULT_DATA_DIR})",
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_PROCESSED_DIR,
        help=f"Where to write processed parquet (default: {DEFAULT_PROCESSED_DIR})",
    )
    p.add_argument(
        "--raw-jodi-dir",
        type=Path,
        default=None,
        help=f"Override raw JODI dir (default: <data-dir>/raw/jodi)",
    )
    p.add_argument(
        "--country-codes",
        type=Path,
        default=DEFAULT_COUNTRY_CODES,
        help=f"Path to country_codes.xlsx (default: {DEFAULT_COUNTRY_CODES})",
    )
    return p.parse_args()


def run_one(dataset: str, args: argparse.Namespace) -> None:
    """Process a single dataset (primary or secondary) end-to-end."""
    logger.info("=" * 70)
    logger.info(f"JODI {dataset.upper()} pipeline")
    logger.info("=" * 70)

    raw_jodi_dir = args.raw_jodi_dir or (args.data_dir / "raw" / "jodi")
    scraper = JodiScraper(data_dir=str(args.data_dir))

    # ------------------------------------------------------------------ #
    # 0. Optional: pre-download the entire historical archive
    # ------------------------------------------------------------------ #
    # We do this before bootstrap so build_from_historical can pick up the
    # newly-downloaded files via its normal directory-glob discovery.
    if args.download_history:
        logger.info(f"[History] Downloading JODI {dataset} archive 2002 → current…")
        paths = scraper.download_history(dataset, start_year=2002, force=args.force)
        logger.info(f"[History] {len(paths)} files now on disk for {dataset}")

    # ------------------------------------------------------------------ #
    # 1. Load (or build) existing DB
    # ------------------------------------------------------------------ #
    existing_df = processor.load(args.output_dir, dataset)
    rows_before = len(existing_df) if existing_df is not None else 0

    if args.bootstrap or existing_df is None:
        logger.info(f"[Bootstrap] Building from local CSVs in {raw_jodi_dir}")
        existing_df = processor.build_from_historical(
            raw_jodi_dir=raw_jodi_dir,
            dataset_name=dataset,
            country_codes_path=args.country_codes,
        )
        logger.info(f"[Bootstrap] {len(existing_df):,} rows from local files")

    # ------------------------------------------------------------------ #
    # 2. Get the latest file
    # ------------------------------------------------------------------ #
    latest_path: Path | None = None
    if args.local_file is not None:
        if not args.local_file.exists():
            logger.error(f"Local file not found: {args.local_file}")
            sys.exit(1)
        latest_path = args.local_file
        logger.info(f"[Source] Using local file: {latest_path}")
    elif not args.no_download:
        target_year = args.year or datetime.now().year
        logger.info(f"[Download] Fetching {dataset} year={target_year} from JODI…")
        try:
            latest_path = scraper.download(dataset, year=target_year, force=args.force)
        except Exception as exc:
            # We don't want a one-off network blip to nuke the run — just warn
            # and persist whatever we already have.
            logger.warning(f"[Download] Failed: {exc}")
            logger.warning("[Download] Skipping update; DB unchanged since bootstrap.")

    # ------------------------------------------------------------------ #
    # 3. Parse + upsert
    # ------------------------------------------------------------------ #
    if latest_path is not None:
        new_df = scraper.parse(dataset, latest_path)
        # Run the same enrichment pipeline as the bootstrap to keep schemas aligned
        new_df = processor._enrich_country(new_df, args.country_codes)
        new_df = processor._sort_and_clean(new_df)
        logger.info(f"[Parse] {len(new_df):,} rows from {latest_path.name}")
        file_max = new_df["date"].max()
        target_year = args.year or datetime.now().year
        year_slice = new_df[new_df["date"].dt.year == target_year]
        if not year_slice.empty:
            months = sorted(year_slice["date"].dt.month.unique().tolist())
            logger.info(
                f"[Parse] {target_year} months in file: "
                f"{months[0]:02d}–{months[-1]:02d} (latest {file_max:%Y-%m})"
            )
        updated_df = processor.upsert(existing_df, new_df)
    else:
        updated_df = existing_df

    # ------------------------------------------------------------------ #
    # 4. Save
    # ------------------------------------------------------------------ #
    logger.info(f"[Save] Writing to {args.output_dir}")
    paths = processor.save(
        updated_df,
        args.output_dir,
        dataset_name=dataset,
        write_sqlite=args.sqlite,
    )

    # ------------------------------------------------------------------ #
    # 5. Summary
    # ------------------------------------------------------------------ #
    rows_after = len(updated_df)
    rows_added = rows_after - rows_before
    logger.info("─" * 70)
    logger.info(f"Summary [{dataset}]")
    logger.info(f"  Rows before  : {rows_before:,}")
    logger.info(f"  Rows after   : {rows_after:,}")
    logger.info(f"  Net change   : {rows_added:+,}")
    logger.info(f"  Date range   : {updated_df['date'].min()} → {updated_df['date'].max()}")
    logger.info(f"  Countries    : {updated_df['ref_area'].nunique()}")
    logger.info(f"  Products     : {updated_df['energy_product'].nunique()}")
    logger.info(f"  Parquet      : {paths['parquet']}")
    if "sqlite" in paths:
        logger.info(f"  SQLite       : {paths['sqlite']}")
    logger.info("=" * 70)


def main() -> None:
    args = parse_args()
    datasets = DATASETS if args.dataset == "all" else (args.dataset,)
    if args.local_file is not None and len(datasets) > 1:
        logger.error("--local-file requires --dataset secondary OR --dataset primary")
        sys.exit(2)

    for ds in datasets:
        run_one(ds, args)

    print("\nDone. Quick-access examples:")
    print(f"  import pandas as pd")
    print(f"  df = pd.read_parquet(r'{args.output_dir / 'jodi_secondary.parquet'}')")
    print(f"  df[(df.ref_area == 'IN') & (df.unit_measure == 'KBD')]")
    if args.sqlite:
        print(f"\n  import sqlite3")
        print(f"  con = sqlite3.connect(r'{args.output_dir / 'jodi_secondary.db'}')")
        print(f"  pd.read_sql(\"SELECT * FROM jodi_secondary WHERE ref_area='IN' LIMIT 5\", con)")


if __name__ == "__main__":
    main()
