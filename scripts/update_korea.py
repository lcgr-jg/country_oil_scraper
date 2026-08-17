"""
update_korea.py
───────────────
Bootstrap or incrementally refresh Korea KNOC database (consumption + stocks).

Routine runs (default) only download + parse bundles that were actually fetched
from Petronet. Historical bundles are left untouched unless you opt in to a
full reparse.

Usage (from country_oil_scraper/):
  python scripts/update_korea.py
  python scripts/update_korea.py --force
  python scripts/update_korea.py --bootstrap
  python scripts/update_korea.py --reparse-all
  python scripts/update_korea.py --no-download --reparse-all
  python scripts/update_korea.py --repair-gaps
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from reference.korea import (  # noqa: E402
    CONSUMPTION_DATASET,
    STOCKS_DATASET,
    find_stitched_gaps,
)
import processors.korea_knoc as processor  # noqa: E402
from scrapers.korea_knoc import DownloadResult, KoreaKnocScraper  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_PROCESSED_DIR = DEFAULT_DATA_DIR / "processed" / "korea"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Update Korea KNOC petroleum consumption and stocks database"
    )
    p.add_argument(
        "--bootstrap",
        action="store_true",
        help="Download full history (~5y chunks) and rebuild parquet from all bundles.",
    )
    p.add_argument(
        "--reparse-all",
        action="store_true",
        help="Re-parse every local bundle CSV and upsert (no Petronet unless also downloading).",
    )
    p.add_argument(
        "--no-download",
        action="store_true",
        help="Skip Petronet; only parse if --reparse-all is set.",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Re-download even when a matching local bundle exists.",
    )
    p.add_argument(
        "--lookback-months",
        type=int,
        default=24,
        help="Months to fetch on routine refresh (default: 24).",
    )
    p.add_argument(
        "--repair-gaps",
        action="store_true",
        help="Re-download truncated raw bundles only; incremental parse those files.",
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


def _paths_fetched(results: list[DownloadResult]) -> list[Path]:
    return [r.path for r in results if r.fetched]


def main() -> None:
    args = parse_args()
    scraper = KoreaKnocScraper(data_dir=args.data_dir)
    touched: list[Path] = []

    logger.info("=" * 60)
    logger.info("Korea KNOC update (consumption + stocks)")
    logger.info("=" * 60)

    if not args.no_download:
        if args.bootstrap:
            results = scraper.download_bootstrap_all(force=args.force)
            n_fetched = sum(1 for r in results if r.fetched)
            logger.info(
                "Bootstrap download: %d bundle(s), %d fetched from Petronet",
                len(results),
                n_fetched,
            )
        elif args.repair_gaps:
            repaired = scraper.download_repair_truncated_all(force=True)
            touched = _paths_fetched(repaired)
            if not touched:
                logger.info("No truncated raw CSV bundles found.")
            else:
                logger.info("Repaired %d bundle(s).", len(touched))
        else:
            for refresh in scraper.download_refresh_all(
                lookback_months=args.lookback_months,
                force=args.force,
            ):
                if refresh.fetched:
                    touched.append(refresh.path)
            repaired = scraper.download_repair_truncated_all(force=args.force)
            touched.extend(_paths_fetched(repaired))
    else:
        logger.info("Skipping download; using local raw bundles")

    if args.bootstrap or args.reparse_all:
        updated_df = processor.build_from_raw(args.data_dir)
    elif touched:
        existing = processor.load(args.output_dir)
        if existing is None:
            logger.error(
                "No parquet found. Run once with --bootstrap (or place bundles "
                "and use --no-download --reparse-all)."
            )
            sys.exit(1)
        delta_df = processor.build_from_files(touched)
        updated_df = processor.upsert(existing, delta_df)
    else:
        existing = processor.load(args.output_dir)
        if existing is None:
            logger.error("No parquet found. Run with --bootstrap first.")
            sys.exit(1)
        logger.info(
            "No new downloads and no --reparse-all; parquet unchanged."
        )
        updated_df = existing

    paths = processor.save(updated_df, args.output_dir)

    logger.info("=" * 60)
    logger.info("  Rows        : %s", f"{len(updated_df):,}")
    logger.info("  Date range  : %s -> %s", updated_df["date"].min(), updated_df["date"].max())
    logger.info("  Metrics     : %s", ", ".join(sorted(updated_df["metric_type"].unique())))
    logger.info("  Products    : %s", updated_df["product_native"].nunique())
    logger.info("  Parquet     : %s", paths["parquet"])

    for label, ds in (
        ("consumption", CONSUMPTION_DATASET),
        ("stocks", STOCKS_DATASET),
    ):
        sl = updated_df[updated_df["metric_type"] == ds.metric_type]
        if sl.empty:
            continue
        gaps = find_stitched_gaps(
            sl,
            start=ds.bootstrap_start.strftime("%Y-%m"),
            metric_type=ds.metric_type,
        )
        if gaps:
            logger.warning(
                "  %s missing months: %s ... (%d total)",
                label,
                ", ".join(gaps[:6]),
                len(gaps),
            )
            logger.warning("  Run: python scripts/update_korea.py --repair-gaps")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
