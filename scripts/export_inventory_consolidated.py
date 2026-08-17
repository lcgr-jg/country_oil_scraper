"""
export_inventory_consolidated.py
────────────────────────────────
Refresh the team-facing national closing-stock CSV from processed parquets.

Usage (from country_oil_scraper/):
  python scripts/export_inventory_consolidated.py
  python scripts/export_inventory_consolidated.py --year 2026 --unit mbbl
  python scripts/export_inventory_consolidated.py --output data/processed/inventory/custom.csv
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from analytics.inventory_consolidated import (  # noqa: E402
    build_consolidated_inventory,
    save_consolidated_csv,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

DEFAULT_PROCESSED = PROJECT_ROOT / "data" / "processed"
DEFAULT_OUTPUT = (
    PROJECT_ROOT / "data" / "processed" / "inventory" / "country_stocks_consolidated.csv"
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Export national CLOSTLV inventory to consolidated CSV"
    )
    p.add_argument(
        "--processed-dir",
        type=Path,
        default=DEFAULT_PROCESSED,
        help="Root data/processed directory",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Output CSV path",
    )
    p.add_argument(
        "--year",
        type=int,
        default=None,
        help="Optional calendar-year filter (default: all history)",
    )
    p.add_argument(
        "--unit",
        choices=("kb", "mbbl", "kt", "ML", "kL"),
        default="mbbl",
        help="Display unit written as value/unit columns (value_kb always kept)",
    )
    p.add_argument(
        "--sources-csv",
        type=Path,
        default=PROJECT_ROOT / "reference" / "inventory_sources.csv",
        help="Country registry CSV",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    df = build_consolidated_inventory(
        processed_dir=args.processed_dir,
        sources_csv=args.sources_csv,
        year=args.year,
    )
    if df.empty:
        logger.warning("No CLOSTLV rows found — CSV will have headers only")
    else:
        logger.info(
            "Built consolidated panel: %d rows, %s → %s",
            len(df),
            df["date"].min().date(),
            df["date"].max().date(),
        )
    path = save_consolidated_csv(df, args.output, target_unit=args.unit)
    print(path)


if __name__ == "__main__":
    main()
