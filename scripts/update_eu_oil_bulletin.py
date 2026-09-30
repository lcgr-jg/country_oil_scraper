"""
update_eu_oil_bulletin.py
─────────────────────────
Download and process the European Commission's Weekly Oil Bulletin
(prices with/without taxes, VAT, excise, other taxes).

Usage (from country_oil_scraper/):
  python scripts/update_eu_oil_bulletin.py
  python scripts/update_eu_oil_bulletin.py --force
  python scripts/update_eu_oil_bulletin.py --no-download
  python scripts/update_eu_oil_bulletin.py --local-file data/raw/eu_oil_bulletin/Weekly_Oil_Bulletin_Prices_History_maticni_4web.xlsx
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from reference.loaders import load_product_map  # noqa: E402
import processors.eu_oil_bulletin as processor  # noqa: E402
from scrapers.eu_oil_bulletin import EUOilBulletinScraper  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_PROCESSED_ROOT = DEFAULT_DATA_DIR / "processed"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Update EC Weekly Oil Bulletin prices and taxes"
    )
    p.add_argument(
        "--no-download",
        action="store_true",
        help="Skip download; parse cached history workbook.",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Re-download even when a same-size local copy exists.",
    )
    p.add_argument(
        "--skip-duties",
        action="store_true",
        help="Do not download the standalone duties workbook (history has tax sheets).",
    )
    p.add_argument(
        "--local-file",
        type=Path,
        default=None,
        help="Parse this history workbook instead of downloading.",
    )
    p.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    p.add_argument("--output-dir", type=Path, default=DEFAULT_PROCESSED_ROOT)
    return p.parse_args()


def _resolve_history(
    scraper: EUOilBulletinScraper, args: argparse.Namespace
) -> Path:
    if args.local_file is not None:
        path = Path(args.local_file)
        if not path.exists():
            logger.error("Local file not found: %s", path)
            sys.exit(1)
        return path

    if not args.no_download:
        return scraper.download_history(force=args.force)

    path = scraper.latest_local_history()
    if path is None:
        logger.error(
            "No local history workbook under %s. Run without --no-download.",
            scraper.raw_dir,
        )
        sys.exit(1)
    logger.info("Using cached history: %s", path.name)
    return path


def main() -> None:
    args = parse_args()
    load_product_map.cache_clear()

    scraper = EUOilBulletinScraper(data_dir=args.data_dir)
    history_path = _resolve_history(scraper, args)

    if not args.no_download and not args.skip_duties and args.local_file is None:
        try:
            scraper.download_duties(force=args.force)
        except Exception as exc:  # noqa: BLE001 — duties are optional backup
            logger.warning("Duties workbook download failed (non-fatal): %s", exc)

    logger.info("=" * 60)
    logger.info("EU Oil Bulletin update")
    logger.info("  History: %s", history_path)
    logger.info("=" * 60)

    prices, taxes, consumption = processor.build_from_history(history_path)
    paths = processor.save(prices, taxes, consumption, args.output_dir)

    logger.info(
        "Prices rows=%s geos=%s range=%s→%s → %s",
        f"{len(prices):,}",
        prices["country"].nunique() if not prices.empty else 0,
        prices["date"].min() if not prices.empty else None,
        prices["date"].max() if not prices.empty else None,
        paths.get("prices"),
    )
    logger.info(
        "Taxes rows=%s → %s",
        f"{len(taxes):,}",
        paths.get("taxes"),
    )
    logger.info(
        "Annual consumption rows=%s → %s",
        f"{len(consumption):,}",
        paths.get("consumption"),
    )
    logger.info("=" * 60)
    logger.info("EU Oil Bulletin update complete")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
