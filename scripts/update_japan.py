"""
update_japan.py
───────────────
Bootstrap or refresh Japan METI petroleum database (demand + 確報 supply balance).

Routine run: latest 速報 (preliminary) + recent 確報 months.
確報 rows replace 速報 for the same (date, product) on upsert.

Usage (from country_oil_scraper/):
  python scripts/update_japan.py
  python scripts/update_japan.py --force
  python scripts/update_japan.py --bootstrap
  python scripts/update_japan.py --no-download --reparse-all
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scrapers.japan_meti import DownloadResult, JapanMetiScraper  # noqa: E402
import processors.japan_meti_consumption as processor  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_PROCESSED_DIR = DEFAULT_DATA_DIR / "processed" / "japan"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Update Japan METI consumption database")
    p.add_argument(
        "--bootstrap",
        action="store_true",
        help="Download 年報 + all 確報 months + latest 速報; rebuild parquet.",
    )
    p.add_argument(
        "--reparse-all",
        action="store_true",
        help="Re-parse all local xlsx under data/raw/japan/ (no download unless omitted).",
    )
    p.add_argument("--no-download", action="store_true", help="Skip METI downloads.")
    p.add_argument("--force", action="store_true", help="Re-download even if cached.")
    p.add_argument(
        "--lookback-months",
        type=int,
        default=6,
        help="確報 months to fetch on routine refresh (default: 6).",
    )
    p.add_argument("--output-dir", type=Path, default=DEFAULT_PROCESSED_DIR)
    p.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    return p.parse_args()


def _paths_fetched(results: list[DownloadResult]) -> list[Path]:
    return [r.path for r in results if r.fetched]


def main() -> None:
    args = parse_args()
    scraper = JapanMetiScraper(data_dir=args.data_dir)
    raw_dir = scraper.raw_dir
    touched: list[Path] = []

    logger.info("=" * 60)
    logger.info("Japan METI update (demand + 確報 supply balance)")
    logger.info("=" * 60)

    if not args.no_download:
        if args.bootstrap:
            results = scraper.download_bootstrap(force=args.force)
            n = sum(1 for r in results if r.fetched)
            logger.info("Bootstrap: %d files, %d fetched", len(results), n)
            touched = [r.path for r in results]
        else:
            results = scraper.download_refresh(
                lookback_months=args.lookback_months,
                force=args.force,
            )
            touched = _paths_fetched(results)
            logger.info("Refresh: %d file(s) fetched", len(touched))
    else:
        logger.info("Skipping download")

    if args.bootstrap or args.reparse_all:
        updated_df = processor.build_from_raw(raw_dir)
    elif touched:
        existing = processor.load(args.output_dir)
        if existing is None:
            logger.error("No parquet — run --bootstrap first.")
            sys.exit(1)
        updated_df = processor.upsert(
            existing, processor.build_from_files(touched)
        )
    else:
        existing = processor.load(args.output_dir)
        if existing is None:
            logger.error("No parquet — run --bootstrap first.")
            sys.exit(1)
        logger.info("No new downloads; parquet unchanged.")
        updated_df = existing

    paths = processor.save(updated_df, args.output_dir)

    prov = updated_df["is_provisional"].sum() if len(updated_df) else 0
    logger.info("=" * 60)
    logger.info("  Rows          : %s", f"{len(updated_df):,}")
    logger.info("  Date range    : %s -> %s", updated_df["date"].min(), updated_df["date"].max())
    logger.info("  Products      : %s", updated_df["product_native"].nunique())
    if "metric_type" in updated_df.columns:
        for mt, n in updated_df["metric_type"].value_counts().items():
            logger.info("    %-10s : %s", mt, f"{int(n):,}")
    logger.info("  Provisional   : %s rows", f"{int(prov):,}")
    logger.info("  Parquet       : %s", paths["parquet"])
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
