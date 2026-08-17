"""
scrapers/uk_desnz.py
────────────────────
DESNZ Energy Trends — consolidated oil and oil products ODS workbook.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple
from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup

from reference.uk import (
    CANONICAL_COLUMNS,
    GOVUK_STATISTICS_PAGE,
    finalize_uk_frame,
    keep_parsed_row,
    parse_energy_trends_workbook,
)

logger = logging.getLogger(__name__)

DATASET = "energy_trends"
ODS_MAGIC = b"PK\x03\x04"
_USER_AGENT = "country_oil_scraper/1.0 (DESNZ Energy Trends)"


class DownloadResult(NamedTuple):
    path: Path
    fetched: bool


class UkDesnzScraper:
    """Download + parse DESNZ Energy Trends consolidated ODS."""

    country = "uk"

    def __init__(self, data_dir: str | Path = "data") -> None:
        self.data_dir = Path(data_dir)
        self.raw_dir = self.data_dir / "raw" / "uk"
        self.raw_dir.mkdir(parents=True, exist_ok=True)

    def discover_ods_url(self, page_url: str = GOVUK_STATISTICS_PAGE) -> str:
        """Find the consolidated ODS attachment on the GOV.UK statistics page."""
        resp = requests.get(
            page_url,
            timeout=60,
            headers={"User-Agent": _USER_AGENT},
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        candidates: list[tuple[int, str]] = []
        for link in soup.find_all("a", href=True):
            href = link["href"]
            text = link.get_text(" ", strip=True).lower()
            score = 0
            if href.lower().endswith(".ods"):
                score += 10
            if "oil and oil products tables" in text:
                score += 20
            if "ods" in text:
                score += 5
            if score:
                candidates.append((score, urljoin(page_url, href)))
        if not candidates:
            raise RuntimeError(f"No ODS link found on {page_url}")
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]

    def download(
        self,
        dataset_name: str = DATASET,
        *,
        force: bool = False,
        page_url: str = GOVUK_STATISTICS_PAGE,
    ) -> DownloadResult:
        download_url = self.discover_ods_url(page_url)
        filename = _filename_from_url(download_url)
        dest = self.raw_dir / filename

        if dest.exists() and not force:
            logger.info("Using cached %s", dest.name)
            return DownloadResult(dest, fetched=False)

        logger.info("Downloading %s", download_url)
        resp = requests.get(
            download_url,
            timeout=180,
            headers={"User-Agent": _USER_AGENT},
        )
        resp.raise_for_status()
        content = resp.content
        if not content.startswith(ODS_MAGIC):
            raise RuntimeError(
                f"Expected ODS from {download_url}, got {len(content)} bytes "
                f"starting with {content[:8]!r}"
            )
        dest.write_bytes(content)
        logger.info("Saved %s (%.1f KB)", dest, len(content) / 1024)
        return DownloadResult(dest, fetched=True)

    def latest_local_workbook(self) -> Path | None:
        candidates = sorted(
            self.raw_dir.glob("*.ods"),
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
            raise FileNotFoundError(f"No ODS under {self.raw_dir}")

        partial = parse_energy_trends_workbook(Path(raw_path))
        partial = partial[partial.apply(keep_parsed_row, axis=1)].copy()
        return finalize_uk_frame(
            partial,
            updated_at=updated_at or datetime.now(UTC),
        )


def _filename_from_url(url: str) -> str:
    name = url.rsplit("/", 1)[-1]
    name = name.split("?")[0]
    if not name.lower().endswith(".ods"):
        name = "energy_trends_oil_products.ods"
    return name


__all__ = ["UkDesnzScraper", "DownloadResult", "DATASET", "CANONICAL_COLUMNS"]
