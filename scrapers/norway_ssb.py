"""
scrapers/norway_ssb.py
────────────────────────
SSB monthly petroleum product sales (StatBank Table 3 / table 13585).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple, Optional

import pandas as pd

from reference.norway import (
    TABLE_CURRENT,
    TABLE_ERAS,
    fetch_era_table,
    finalize_ssb_frame,
    merge_era_tables,
    parse_table3_workbook,
)

logger = logging.getLogger(__name__)

DATASET = "monthly_product_sales"
CURRENT_SNAPSHOT = f"ssb_{TABLE_CURRENT}_monthly_products.csv"


class DownloadResult(NamedTuple):
    path: Path
    fetched: bool


class NorwaySsbScraper:
    """Download + parse SSB monthly petroleum product sales."""

    country = "norway"

    def __init__(self, data_dir: str | Path = "data") -> None:
        self.data_dir = Path(data_dir)
        self.raw_dir = self.data_dir / "raw" / "norway"
        self.raw_dir.mkdir(parents=True, exist_ok=True)

    @property
    def current_snapshot_path(self) -> Path:
        return self.raw_dir / CURRENT_SNAPSHOT

    def download_current(self, *, force: bool = False) -> DownloadResult:
        """
        Refresh the live StatBank table (13585) into a cached CSV snapshot.

        Fetches product-by-product and writes one combined CSV under
        ``data/raw/norway/``.
        """
        dest = self.current_snapshot_path
        if dest.exists() and not force:
            logger.info("Using cached SSB snapshot: %s", dest.name)
            return DownloadResult(dest, fetched=False)

        era = next(e for e in TABLE_ERAS if e.table_id == TABLE_CURRENT)
        logger.info("Downloading SSB table %s (%s)", era.table_id, era.label)
        df = fetch_era_table(era)
        if df.empty:
            raise RuntimeError(f"SSB table {era.table_id} returned no rows")

        dest.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(dest, index=False)
        logger.info("Saved %s rows -> %s", f"{len(df):,}", dest.name)
        return DownloadResult(dest, fetched=True)

    def parse_current_snapshot(self, path: Optional[Path] = None) -> pd.DataFrame:
        path = Path(path or self.current_snapshot_path)
        if not path.exists():
            raise FileNotFoundError(f"Missing SSB snapshot: {path}")
        df = pd.read_csv(path, parse_dates=["date"])
        return finalize_ssb_frame(df)

    def parse_workbook(self, path: Path) -> pd.DataFrame:
        """Parse a Table 3 xlsx page export."""
        df = parse_table3_workbook(Path(path))
        return finalize_ssb_frame(df)

    def bootstrap_historical(self) -> pd.DataFrame:
        """Fetch and stitch all configured StatBank eras (1995+)."""
        parts: list[pd.DataFrame] = []
        for era in TABLE_ERAS:
            logger.info(
                "Fetching SSB table %s (%s) — %d products",
                era.table_id,
                era.label,
                len(era.product_codes),
            )
            part = fetch_era_table(era)
            logger.info(
                "  %s: %s rows, %s -> %s",
                era.table_id,
                f"{len(part):,}",
                part["date"].min() if not part.empty else None,
                part["date"].max() if not part.empty else None,
            )
            parts.append(part)
        merged = merge_era_tables(parts)
        return finalize_ssb_frame(merged)

    def parse(self, raw_path: Path) -> pd.DataFrame:
        """Parse one raw file (.csv snapshot or .xlsx export)."""
        raw_path = Path(raw_path)
        suffix = raw_path.suffix.lower()
        if suffix == ".csv":
            df = pd.read_csv(raw_path, parse_dates=["date"])
            if "ssb_table" not in df.columns:
                raise ValueError(f"Unexpected CSV layout: {raw_path.name}")
            return finalize_ssb_frame(df)
        if suffix in {".xlsx", ".xls"}:
            return self.parse_workbook(raw_path)
        raise ValueError(f"Unsupported raw file type: {raw_path}")

    def latest_local_workbook(self) -> Optional[Path]:
        candidates = sorted(
            self.raw_dir.glob("*.xlsx"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return candidates[0] if candidates else None
