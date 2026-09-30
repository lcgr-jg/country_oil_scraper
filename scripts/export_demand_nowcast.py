"""
export_demand_nowcast.py
────────────────────────
Phase 3 POC: national early prints vs JODI settle (DE/JP/KR/AU × gasoline/gasoil).

Usage (from country_oil_scraper/):
  python scripts/export_demand_nowcast.py
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from analytics.demand_nowcast import (  # noqa: E402
    DEFAULT_LEAD_PATH,
    DEFAULT_TABLEAU_PATH,
    build_lead_summary,
    build_nowcast_long,
    build_nowcast_tracker,
    build_nowcast_wide,
    export_nowcast_csvs,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Export demand nowcast POC CSVs")
    p.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / DEFAULT_TABLEAU_PATH,
        help="Wide Tableau CSV path",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    paths = export_nowcast_csvs(PROJECT_ROOT, wide_path=args.output)
    long = build_nowcast_long(PROJECT_ROOT)
    wide = build_nowcast_tracker(build_nowcast_wide(long))
    lead = build_lead_summary(wide)
    logger.info("Wrote wide: %s (%s rows)", paths["wide"], len(wide))
    logger.info("Wrote long: %s (%s rows)", paths["long"], len(long))
    logger.info("Wrote lead summary: %s (%s series)", paths["lead"], len(lead))
    if not lead.empty:
        logger.info(
            "Lead months by series:\n%s",
            lead[
                ["iso2", "compare_bucket", "lead_months", "official_last", "jodi_last", "median_pct_diff"]
            ].to_string(index=False),
        )


if __name__ == "__main__":
    main()
