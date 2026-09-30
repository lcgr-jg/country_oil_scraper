"""
export_iea_jodi_tableau.py
──────────────────────────
Build Phase 2 IEA vs JODI overlap CSVs for Tableau.

Usage (from country_oil_scraper/):
  python scripts/export_iea_jodi_tableau.py
  python scripts/export_iea_jodi_tableau.py --decimal , --sep ;
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from analytics.iea_jodi_overlap import (  # noqa: E402
    DEFAULT_STATS_PATH,
    DEFAULT_TABLEAU_PATH,
    build_overlap_panels,
    build_overlap_stats,
    export_tableau_csv,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Export IEA vs JODI Tableau comparison CSVs")
    p.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / DEFAULT_TABLEAU_PATH,
        help="Primary wide Tableau CSV (iea_value vs jodi_value on same row)",
    )
    p.add_argument(
        "--long-output",
        type=Path,
        default=None,
        help="Optional long-format CSV (default: sibling iea_jodi_tableau_long.csv)",
    )
    p.add_argument(
        "--stats-output",
        type=Path,
        default=PROJECT_ROOT / DEFAULT_STATS_PATH,
        help="Series-level overlap statistics CSV",
    )
    p.add_argument(
        "--decimal",
        default=".",
        choices=[".", ","],
        help="Decimal symbol in the CSV (default '.' for US/UK Excel: 1003.41)",
    )
    p.add_argument(
        "--sep",
        default=",",
        help="Field separator (default ',' — use ';' only when --decimal ',')",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    if args.decimal == "," and args.sep == ",":
        raise SystemExit("Cannot use comma for both --decimal and --sep; use --sep ';'")

    paths = export_tableau_csv(
        PROJECT_ROOT,
        wide_path=args.output,
        long_path=args.long_output,
        stats_path=args.stats_output,
        decimal=args.decimal,
        sep=args.sep,
    )
    combined = build_overlap_panels(PROJECT_ROOT)["combined"]
    stats = build_overlap_stats(combined)
    both = int(combined["has_both"].sum())
    logger.info(
        "Wrote wide Tableau CSV: %s (%s rows, sep=%r decimal=%r)",
        paths["wide"],
        len(combined),
        args.sep,
        args.decimal,
    )
    logger.info("Wrote long Tableau CSV: %s", paths["long"])
    logger.info("Wrote overlap stats: %s (%s series)", paths["stats"], len(stats))
    logger.info("Rows with both sources: %s", both)


if __name__ == "__main__":
    main()
