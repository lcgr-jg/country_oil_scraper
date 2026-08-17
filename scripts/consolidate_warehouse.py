#!/usr/bin/env python3
"""Rebuild the central DuckDB warehouse from country parquets + JODI + Kayrros."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from warehouse.consolidate import consolidate, default_warehouse_path  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Consolidate country data into DuckDB")
    parser.add_argument(
        "--countries",
        type=str,
        default="",
        help="Comma-separated country ids (default: all enabled in countries.yaml)",
    )
    parser.add_argument(
        "--warehouse",
        type=Path,
        default=None,
        help="Output DuckDB path (default: data/warehouse/oil_demand.duckdb)",
    )
    parser.add_argument("--no-jodi", action="store_true", help="Skip JODI benchmark rows")
    parser.add_argument("--no-kayrros", action="store_true", help="Skip Kayrros satellite rows")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    countries = None
    if args.countries.strip():
        countries = [c.strip().lower() for c in args.countries.split(",") if c.strip()]

    path = consolidate(
        warehouse_path=args.warehouse or default_warehouse_path(),
        countries=countries,
        include_jodi=not args.no_jodi,
        include_kayrros=not args.no_kayrros,
    )
    print(f"Warehouse ready: {path}")


if __name__ == "__main__":
    main()
