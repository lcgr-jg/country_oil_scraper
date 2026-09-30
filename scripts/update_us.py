"""
update_us.py
────────────
Build / refresh US EIA product-supplied parquet from doe_fundamental_dashboard sqlite.

Usage (from country_oil_scraper/):
  python scripts/update_us.py --bootstrap
  python scripts/update_us.py
  python scripts/update_us.py --sqlite path/to/eia_weekly.sqlite
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from reference.loaders import load_product_map  # noqa: E402
from reference.us import resolve_eia_sqlite  # noqa: E402
import processors.us_eia_product_supplied as processor  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

DEFAULT_PROCESSED_DIR = PROJECT_ROOT / "data" / "processed" / "us"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Update US EIA product-supplied database from weekly sqlite"
    )
    p.add_argument(
        "--bootstrap",
        action="store_true",
        help="Rebuild parquet from sqlite (ignore existing rows).",
    )
    p.add_argument(
        "--sqlite",
        type=Path,
        default=None,
        help="Path to eia_weekly.sqlite (default: doe_fundamental_dashboard/data).",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Accepted for CLI compatibility; sqlite is read-only here.",
    )
    p.add_argument("--output-dir", type=Path, default=DEFAULT_PROCESSED_DIR)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    load_product_map.cache_clear()

    db = resolve_eia_sqlite(args.sqlite)

    logger.info("=" * 60)
    logger.info("US EIA update (weekly product supplied → monthly kb/d)")
    logger.info("  SQLite : %s", db)
    logger.info("=" * 60)

    existing_df = processor.load(args.output_dir)
    rows_before = len(existing_df) if existing_df is not None else 0

    new_df = processor.build_from_eia_sqlite(db)
    if args.bootstrap or existing_df is None:
        updated_df = new_df
    else:
        updated_df = processor.upsert(existing_df, new_df)

    paths = processor.save(updated_df, args.output_dir)

    logger.info("=" * 60)
    logger.info("  Rows before : %s", f"{rows_before:,}")
    logger.info("  Rows after  : %s", f"{len(updated_df):,}")
    logger.info(
        "  Date range  : %s -> %s",
        updated_df["date"].min(),
        updated_df["date"].max(),
    )
    logger.info(
        "  Provisional : %s rows",
        f"{int(updated_df['is_provisional'].sum()):,}",
    )
    logger.info("  Products    : %s", sorted(updated_df["product_native"].unique()))
    logger.info("  Parquet     : %s", paths["parquet"])
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
