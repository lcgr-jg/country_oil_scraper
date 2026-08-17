"""
scrapers/spain_cores.py
───────────────────────
CORES Petroleum Product Consumption (oil-products-consumption.xlsx).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple

import pandas as pd
import requests

from reference.spain import (
    CANONICAL_COLUMNS,
    finalize_cores_frame,
    parse_cores_consumption_workbook,
)

logger = logging.getLogger(__name__)

DATASET = "petroleum_consumption"
DEFAULT_DOWNLOAD_URL = (
    "https://www.cores.es/sites/default/files/archivos/estadisticas/"
    "oil-products-consumption.xlsx"
)
DEFAULT_FILENAME = "oil-products-consumption.xlsx"
XLSX_MAGIC = b"PK\x03\x04"


class DownloadResult(NamedTuple):
    path: Path
    fetched: bool


class SpainCoresScraper:
    """Download + parse CORES monthly petroleum product consumption."""

    country = "spain"

    def __init__(self, data_dir: str | Path = "data") -> None:
        self.data_dir = Path(data_dir)
        self.raw_dir = self.data_dir / "raw" / "spain"
        self.raw_dir.mkdir(parents=True, exist_ok=True)

    def download(
        self,
        dataset_name: str = DATASET,
        *,
        force: bool = False,
        download_url: str = DEFAULT_DOWNLOAD_URL,
    ) -> DownloadResult:
        dest = self.raw_dir / DEFAULT_FILENAME
        headers = {"User-Agent": "country_oil_scraper/1.0 (CORES statistics)"}

        if dest.exists() and not force:
            try:
                head = requests.head(
                    download_url,
                    timeout=30,
                    allow_redirects=True,
                    headers=headers,
                )
                remote_len = head.headers.get("Content-Length")
                if remote_len and int(remote_len) == dest.stat().st_size:
                    logger.info(
                        "Using cached %s (%s bytes)",
                        dest.name,
                        dest.stat().st_size,
                    )
                    return DownloadResult(dest, fetched=False)
            except requests.RequestException:
                logger.info("Using cached copy: %s", dest)

        logger.info("Downloading %s", download_url)
        resp = requests.get(download_url, timeout=120, headers=headers)
        resp.raise_for_status()
        content = resp.content
        if not content.startswith(XLSX_MAGIC):
            raise RuntimeError(
                f"Expected xlsx from {download_url}, got {len(content)} bytes "
                f"starting with {content[:8]!r}"
            )
        dest.write_bytes(content)
        logger.info("Saved %s (%.1f KB)", dest, len(content) / 1024)
        return DownloadResult(dest, fetched=True)

    def latest_local_workbook(self) -> Path | None:
        candidates = sorted(
            self.raw_dir.glob("*.xlsx"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return candidates[0] if candidates else None

    def parse(
        self,
        dataset_name: str = DATASET,
        raw_path: Path | None = None,
        *,
        updated_at: datetime | None = None,
    ) -> pd.DataFrame:
        if raw_path is None:
            raw_path = self.latest_local_workbook()
        if raw_path is None:
            raise FileNotFoundError(f"No xlsx under {self.raw_dir}")
        partial = parse_cores_consumption_workbook(Path(raw_path))
        return finalize_cores_frame(
            partial, updated_at=updated_at or datetime.now(UTC)
        )
