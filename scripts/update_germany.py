"""
update_germany.py
─────────────────
Bootstrap or refresh Germany BAFA Amtliche Mineralöldaten
(demand + bio blends + closing stocks).

Usage (from country_oil_scraper/):
  python scripts/update_germany.py --bootstrap --download-history
  python scripts/update_germany.py
  python scripts/update_germany.py --force
  python scripts/update_germany.py --no-download
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scrapers.germany_bafa import GermanyBafaScraper  # noqa: E402
import processors.germany_bafa_demand as processor  # noqa: E402
from reference.germany import HISTORY_START, finalize_bafa_frame, parse_month_file  # noqa: E402
from reference.germany import MonthFile, year_month_from_filename  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_PROCESSED_DIR = DEFAULT_DATA_DIR / "processed" / "germany"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Update Germany BAFA demand + bio + stocks database"
    )
    p.add_argument(
        "--bootstrap",
        action="store_true",
        help="Rebuild parquet from all local BAFA month files.",
    )
    p.add_argument(
        "--download-history",
        action="store_true",
        help="With --bootstrap, download HISTORY_START → today first.",
    )
    p.add_argument(
        "--no-download",
        action="store_true",
        help="Skip BAFA download; use cached month files only.",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Re-download even when a matching local copy exists.",
    )
    p.add_argument("--output-dir", type=Path, default=DEFAULT_PROCESSED_DIR)
    p.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    return p.parse_args()


def _parse_paths(paths: list[Path]) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    for path in paths:
        year, month = year_month_from_filename(path)
        kind = "xlsx" if path.suffix.lower() == ".xlsx" else "pdf"
        parts.append(parse_month_file(MonthFile(path, kind, year, month)))
    if not parts:
        return finalize_bafa_frame(pd.DataFrame())
    return finalize_bafa_frame(pd.concat(parts, ignore_index=True))


def main() -> None:
    args = parse_args()
    scraper = GermanyBafaScraper(data_dir=args.data_dir)

    logger.info("=" * 60)
    logger.info("Germany BAFA update (demand + bio + stocks)")
    logger.info("=" * 60)

    existing_df = processor.load(args.output_dir)
    rows_before = len(existing_df) if existing_df is not None else 0

    if args.bootstrap or existing_df is None:
        if args.download_history and not args.no_download:
            scraper.download_history(start=HISTORY_START, force=args.force)
        elif not args.no_download and not list(scraper.raw_dir.glob("moel_amtliche_daten_*.*")):
            scraper.download_history(start=HISTORY_START, force=args.force)
        updated_df = processor.build_from_historical(args.data_dir)
    else:
        if args.no_download:
            # Re-parse any local files newer than parquet max date.
            local = sorted(scraper.raw_dir.glob("moel_amtliche_daten_*.*"))
            last = pd.Timestamp(existing_df["date"].max())
            fresh: list[Path] = []
            for path in local:
                if path.suffix.lower() not in {".xlsx", ".pdf"}:
                    continue
                y, m = year_month_from_filename(path)
                if pd.Timestamp(year=y, month=m, day=1) > last:
                    fresh.append(path)
            if not fresh:
                logger.info("No newer local files than %s", last.strftime("%Y-%m"))
                updated_df = existing_df
            else:
                new_df = _parse_paths(fresh)
                updated_df = processor.upsert(existing_df, new_df)
        else:
            results = scraper.download_latest(force=args.force)
            if not results:
                # Also re-fetch current max month in case BAFA revised it.
                last = pd.Timestamp(existing_df["date"].max())
                results = [
                    scraper.download_month(
                        last.year, last.month, force=True
                    )
                ]
            paths = [r.path for r in results]
            new_df = _parse_paths(paths)
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
