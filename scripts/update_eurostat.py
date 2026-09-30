"""
update_eurostat.py
──────────────────
Fetch Eurostat oil monthly demand (GID_OBS) and/or closing stocks.

Usage (from country_oil_scraper/):
  python scripts/update_eurostat.py --bootstrap
  python scripts/update_eurostat.py --stocks-only
  python scripts/update_eurostat.py --demand-only --geos FR,NL,DE
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from reference.loaders import load_product_map  # noqa: E402
from reference.eurostat_oilm import GEO_CATALOG, SKIP_GEOS  # noqa: E402
import processors.eurostat_oilm as demand_processor  # noqa: E402
import processors.eurostat_oilm_stocks as stocks_processor  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

DEFAULT_PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Update Eurostat oil monthly demand and/or closing stocks"
    )
    p.add_argument(
        "--bootstrap",
        action="store_true",
        help="Full rebuild (always true for Eurostat API pulls).",
    )
    p.add_argument(
        "--geos",
        type=str,
        default=None,
        help="Comma-separated Eurostat geo codes (default: full catalog).",
    )
    p.add_argument("--start", type=str, default=None, help="Start period YYYY-MM")
    p.add_argument(
        "--demand-only",
        action="store_true",
        help="Refresh nrg_cb_oilm GID_OBS only.",
    )
    p.add_argument(
        "--stocks-only",
        action="store_true",
        help="Refresh nrg_stk_oilm closing stocks only.",
    )
    p.add_argument("--output-dir", type=Path, default=DEFAULT_PROCESSED_DIR)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    load_product_map.cache_clear()

    if args.demand_only and args.stocks_only:
        raise SystemExit("Choose at most one of --demand-only / --stocks-only")

    do_demand = not args.stocks_only
    do_stocks = not args.demand_only

    if args.geos:
        geos = [g.strip().upper() for g in args.geos.split(",") if g.strip()]
    else:
        geos = [g for g in GEO_CATALOG if g not in SKIP_GEOS]

    logger.info("=" * 60)
    logger.info("Eurostat update")
    logger.info(
        "  Geos   : %s (%d)",
        ",".join(geos[:8]) + ("..." if len(geos) > 8 else ""),
        len(geos),
    )
    logger.info("  Demand : %s", do_demand)
    logger.info("  Stocks : %s", do_stocks)
    logger.info("=" * 60)

    if do_demand:
        start = args.start or "2008-01"
        df = demand_processor.build_from_eurostat_api(geos=geos, start=start)
        paths = demand_processor.save(df, args.output_dir)
        logger.info(
            "Demand rows=%s geos=%s range=%s->%s master=%s",
            f"{len(df):,}",
            df["geo"].nunique(),
            df["date"].min(),
            df["date"].max(),
            paths.get("master"),
        )

    if do_stocks:
        start = args.start or "2013-01"
        df = stocks_processor.build_stocks_from_eurostat_api(geos=geos, start=start)
        paths = stocks_processor.save_stocks(df, args.output_dir)
        logger.info(
            "Stocks rows=%s geos=%s flows=%s range=%s->%s master=%s",
            f"{len(df):,}",
            df["geo"].nunique(),
            df["stk_flow"].nunique(),
            df["date"].min(),
            df["date"].max(),
            paths.get("master"),
        )

    logger.info("=" * 60)
    logger.info("Eurostat update complete")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
