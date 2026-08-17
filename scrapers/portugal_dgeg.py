"""
scrapers/portugal_dgeg.py
─────────────────────────
DGEG Monthly Sales of Oil Products (monthly sales page).
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple
from urllib.parse import urljoin

import pandas as pd
import requests

from reference.portugal import (
    CANONICAL_COLUMNS,
    MONTHLY_SALES_PAGE,
    finalize_dgeg_frame,
    parse_all_workbooks,
    parse_dgeg_sales_workbook,
    workbook_sort_key,
)

logger = logging.getLogger(__name__)

DATASET = "monthly_sales"
BASE_URL = "https://www.dgeg.gov.pt"
_LINK_RE = re.compile(
    r'href=["\']([^"\']+\.(?:xlsx|xls))["\']',
    re.I,
)
_MIN_YEAR = 2006


class DownloadResult(NamedTuple):
    path: Path
    fetched: bool


class PortugalDGEGScraper:
    """Download + parse DGEG monthly oil product sales workbooks."""

    country = "portugal"

    def __init__(self, data_dir: str | Path = "data") -> None:
        self.data_dir = Path(data_dir)
        self.raw_dir = self.data_dir / "raw" / "portugal"
        self.raw_dir.mkdir(parents=True, exist_ok=True)

    def discover_download_links(self) -> list[tuple[str, str]]:
        """Return (filename, absolute_url) pairs from the monthly sales page."""
        headers = {"User-Agent": "country_oil_scraper/1.0 (DGEG statistics)"}
        resp = requests.get(MONTHLY_SALES_PAGE, timeout=60, headers=headers)
        resp.raise_for_status()
        seen: set[str] = set()
        out: list[tuple[str, str]] = []
        for rel in _LINK_RE.findall(resp.text):
            if "/media/" not in rel.lower():
                continue
            url = urljoin(BASE_URL, rel)
            name = Path(rel.split("?")[0]).name
            if name in seen:
                continue
            seen.add(name)
            out.append((name, url))
        return out

    def _download_one(self, url: str, dest: Path, *, force: bool) -> bool:
        headers = {"User-Agent": "country_oil_scraper/1.0 (DGEG statistics)"}
        if dest.exists() and not force:
            return False
        logger.info("Downloading %s -> %s", url, dest.name)
        resp = requests.get(url, timeout=120, headers=headers)
        resp.raise_for_status()
        content = resp.content
        if content[:5].lower().startswith(b"<!doc") or content[:5].lower().startswith(b"<html"):
            raise RuntimeError(f"Expected spreadsheet from {url}, got HTML")
        dest.write_bytes(content)
        return True

    def download_latest(
        self,
        dataset_name: str = DATASET,
        *,
        force: bool = False,
    ) -> DownloadResult:
        """Download the newest yearly workbook linked on the sales page."""
        links = self.discover_download_links()
        if not links:
            raise RuntimeError(f"No spreadsheet links on {MONTHLY_SALES_PAGE}")

        # Prefer dgeg-omn-* names; sort descending by embedded year-month.
        omn = [
            (name, url)
            for name, url in links
            if "dgeg-omn" in name.lower()
        ]
        if omn:
            omn.sort(key=lambda item: workbook_sort_key(Path(item[0])), reverse=True)
            name, url = omn[0]
        else:
            name, url = links[0]

        dest = self.raw_dir / name
        fetched = self._download_one(url, dest, force=force)
        if not fetched and dest.exists():
            logger.info("Using cached %s", dest.name)
        return DownloadResult(dest, fetched=fetched)

    def download_bootstrap(
        self,
        *,
        force: bool = False,
        min_year: int = _MIN_YEAR,
    ) -> list[Path]:
        """Download all historical workbooks linked from the monthly sales page."""
        del min_year  # row filter happens in processor.build_from_historical
        links = self.discover_download_links()
        paths: list[Path] = []
        for name, url in links:
            dest = self.raw_dir / name
            self._download_one(url, dest, force=force)
            if dest.exists():
                paths.append(dest)
        return paths

    def local_workbooks(self) -> list[Path]:
        return sorted(
            list(self.raw_dir.glob("*.xlsx")) + list(self.raw_dir.glob("*.xls")),
            key=workbook_sort_key,
        )

    def latest_local_workbook(self) -> Path | None:
        workbooks = self.local_workbooks()
        if not workbooks:
            return None
        omn = [p for p in workbooks if "dgeg-omn" in p.name.lower()]
        pool = omn or workbooks
        return max(pool, key=workbook_sort_key)

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
            raise FileNotFoundError(f"No DGEG workbook under {self.raw_dir}")
        partial = parse_dgeg_sales_workbook(Path(raw_path))
        return finalize_dgeg_frame(
            partial, updated_at=updated_at or datetime.now(UTC)
        )

    def parse_all(
        self,
        paths: list[Path] | None = None,
        *,
        updated_at: datetime | None = None,
    ) -> pd.DataFrame:
        if paths is None:
            paths = self.local_workbooks()
        if not paths:
            raise FileNotFoundError(f"No DGEG workbooks under {self.raw_dir}")
        partial = parse_all_workbooks(paths)
        return finalize_dgeg_frame(
            partial, updated_at=updated_at or datetime.now(UTC)
        )
