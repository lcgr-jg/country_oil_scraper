"""
scrapers/ukraine_sssu.py
────────────────────────
SSSU monthly fuel usage and reserves via SDMX API or cached CSV exports.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple, Optional

import pandas as pd
import requests

from reference.ukraine import (
    RAW_FILENAME,
    fetch_sdmx_csv,
    parse_raw_csv,
    save_sdmx_snapshot,
)

logger = logging.getLogger(__name__)

DATASET = "fuel_usage_and_reserves"


class DownloadResult(NamedTuple):
    path: Path
    fetched: bool


class UkraineSssuScraper:
    """Download + parse SSSU fuel usage and reserves."""

    country = "ukraine"

    def __init__(self, data_dir: str | Path = "data") -> None:
        self.data_dir = Path(data_dir)
        self.raw_dir = self.data_dir / "raw" / "ukraine"
        self.raw_dir.mkdir(parents=True, exist_ok=True)

    @property
    def snapshot_path(self) -> Path:
        return self.raw_dir / RAW_FILENAME

    def list_raw_csv_files(self) -> list[Path]:
        """All cached CSV snapshots (SDMX + manual Data Bank exports)."""
        return sorted(self.raw_dir.glob("*.csv"), key=lambda p: p.stat().st_mtime)

    def download(
        self,
        *,
        force: bool = False,
        session: Optional[requests.Session] = None,
    ) -> DownloadResult:
        dest = self.snapshot_path
        if dest.exists() and not force:
            logger.info("Using cached SSSU snapshot: %s", dest.name)
            return DownloadResult(dest, fetched=False)

        text = fetch_sdmx_csv(session=session)
        save_sdmx_snapshot(text, dest)
        logger.info("Saved SSSU snapshot -> %s (%.1f KB)", dest, dest.stat().st_size / 1024)
        return DownloadResult(dest, fetched=True)

    def parse(
        self,
        raw_path: Path | None = None,
        *,
        updated_at: datetime | None = None,
    ) -> pd.DataFrame:
        path = Path(raw_path) if raw_path is not None else self.snapshot_path
        if not path.exists():
            raise FileNotFoundError(f"No SSSU snapshot at {path}")
        return parse_raw_csv(path, updated_at=updated_at)

    def parse_all_cached(self) -> pd.DataFrame:
        """Parse every CSV under ``data/raw/ukraine/`` and dedupe by series key."""
        files = self.list_raw_csv_files()
        if not files:
            raise FileNotFoundError(
                f"No CSV files in {self.raw_dir}. Run download or add a Data Bank export."
            )

        parts: list[pd.DataFrame] = []
        for path in files:
            logger.info("Parsing %s", path.name)
            parts.append(self.parse(path))

        combined = pd.concat(parts, ignore_index=True)
        key_cols = ["date", "country", "source", "metric_type", "product_native"]
        combined = combined.sort_values("updated_at").drop_duplicates(
            subset=key_cols, keep="last"
        )
        return combined.sort_values(
            ["date", "metric_type", "product_native"], ignore_index=True
        )
