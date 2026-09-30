"""
update_china.py
───────────────
Build / refresh China SCI national consumption parquet from sci_api cache.

Usage (from country_oil_scraper/):
  python scripts/update_china.py --bootstrap
  python scripts/update_china.py
  python scripts/update_china.py --cache-dir path/to/sci_api/data/cache/20260911
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from reference.china import resolve_sci_cache_dir  # noqa: E402
from reference.loaders import load_product_map  # noqa: E402
import processors.china_sci_consumption as processor  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

DEFAULT_PROCESSED_DIR = PROJECT_ROOT / "data" / "processed" / "china"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Update China SCI consumption database from sci_api cache"
    )
    p.add_argument(
        "--bootstrap",
        action="store_true",
        help="Rebuild parquet from SCI cache (ignore existing rows).",
    )
    p.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help="Stamped SCI cache folder (default: sci_api/data/cache via latest.txt).",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Accepted for CLI compatibility; SCI cache is read-only here.",
    )
    p.add_argument("--output-dir", type=Path, default=DEFAULT_PROCESSED_DIR)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    # Drop stale product_map cache so new SCI rows are visible without restart.
    load_product_map.cache_clear()

    cache = (
        Path(args.cache_dir)
        if args.cache_dir is not None
        else resolve_sci_cache_dir()
    )

    logger.info("=" * 60)
    logger.info("China SCI update (national consumption + derived X_OTHKERO)")
    logger.info("  SCI cache  : %s", cache)
    logger.info("=" * 60)

    existing_df = processor.load(args.output_dir)
    rows_before = len(existing_df) if existing_df is not None else 0

    new_df = processor.build_from_sci_cache(cache)
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
    logger.info("  Products    : %s", sorted(updated_df["product_native"].unique()))
    logger.info("  Parquet     : %s", paths["parquet"])
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
