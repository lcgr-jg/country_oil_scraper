"""
scrapers/japan_meti.py
──────────────────────
METI petroleum statistics — 速報 (preliminary) + 確報 (final) domestic sales.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import NamedTuple, Optional
from urllib.parse import urljoin

import pandas as pd
from curl_cffi import requests

from reference.japan import (
    COUNTRY_CODE,
    COUNTRY_NAME,
    METI_METRIC_TYPE,
    SOURCE_ID,
    parse_kakuhou_filename,
    parse_meti_directory,
    parse_meti_paths,
    parse_meti_workbook,
)

logger = logging.getLogger(__name__)

IMPERSONATE_PROFILE = "chrome131"
METI_BASE = "https://www.meti.go.jp"
KAKUHOU_INDEX = f"{METI_BASE}/statistics/tyo/sekiyuka/index.html"
SOKUHOU_RESULT = f"{METI_BASE}/statistics/tyo/sekiyuso/result.html"
SOKUHOU_ENGLISH_INDEX = f"{METI_BASE}/english/statistics/tyo/sekiyuso/index.html"

_KAKUHOU_LINK_RE = re.compile(r'href=["\'](xls/se(\d{6})kakji\.xlsx)["\']', re.I)
_YEARBOOK_LINK_RE = re.compile(r'href=["\'](xls/h2dhhpe(\d{4})k\.xlsx)["\']', re.I)
_SOKUHOU_XLS_RE = re.compile(
    r'href=["\'](?:\.\./sekiyuso/)?result/xls/(h2j[^"\']+\.xlsx)["\']', re.I
)
_SOKUHOU_ENGLISH_XLS_RE = re.compile(
    r'href=["\'](?:\.\./sekiyuso/)?excel/(h2j[^"\']+\.xlsx)["\']', re.I
)

CANONICAL_COLUMNS: list[str] = [
    "date",
    "country",
    "country_name",
    "source",
    "metric_type",
    "product_native",
    "product",
    "value",
    "unit",
    "is_provisional",
    "source_file",
    "updated_at",
]


class DownloadResult(NamedTuple):
    path: Path
    fetched: bool
    is_provisional: bool


def _get(url: str) -> requests.Response:
    return requests.get(url, impersonate=IMPERSONATE_PROFILE, timeout=120)


def discover_kakuhou_links(html: str) -> list[tuple[str, str]]:
    """Return (filename, yyyymm) sorted ascending."""
    found: dict[str, str] = {}
    for m in _KAKUHOU_LINK_RE.finditer(html):
        fname, yyyymm = m.group(1), m.group(2)
        found[fname] = yyyymm
    return sorted(found.items(), key=lambda x: x[1])


def discover_sokuhou_link(html: str) -> Optional[str]:
    for m in _SOKUHOU_XLS_RE.finditer(html):
        return m.group(1)
    return None


def discover_sokuhou_english_link(html: str) -> Optional[str]:
    """English 速報 index → ``../sekiyuso/excel/h2j….xlsx`` (often ahead of JP result page)."""
    for m in _SOKUHOU_ENGLISH_XLS_RE.finditer(html):
        return m.group(1)
    return None


def discover_yearbook_links(html: str) -> list[tuple[str, str]]:
    """Return (filename, edition_year) sorted ascending."""
    found: dict[str, str] = {}
    for m in _YEARBOOK_LINK_RE.finditer(html):
        fname, year = m.group(1), m.group(2)
        found[Path(fname).name] = year
    return sorted(found.items(), key=lambda x: x[1])


def build_monthly_series(raw_dir: Path, *, updated_at: Optional[datetime] = None) -> pd.DataFrame:
    updated_at = updated_at or datetime.utcnow()
    partial = parse_meti_directory(raw_dir)
    return _finalize(partial, updated_at=updated_at)


def build_monthly_series_from_files(
    paths: list[Path],
    *,
    updated_at: Optional[datetime] = None,
) -> pd.DataFrame:
    updated_at = updated_at or datetime.utcnow()
    partial = parse_meti_paths(paths)
    return _finalize(partial, updated_at=updated_at)


def _finalize(partial: pd.DataFrame, *, updated_at: datetime) -> pd.DataFrame:
    if partial.empty:
        return pd.DataFrame(columns=CANONICAL_COLUMNS)

    df = partial.copy()
    df["country"] = COUNTRY_CODE
    df["country_name"] = COUNTRY_NAME
    df["source"] = SOURCE_ID
    if "metric_type" not in df.columns:
        df["metric_type"] = METI_METRIC_TYPE
    else:
        df["metric_type"] = df["metric_type"].fillna(METI_METRIC_TYPE)
    df["product"] = df["product_native"]
    df["updated_at"] = updated_at
    return df[CANONICAL_COLUMNS].sort_values(
        ["date", "metric_type", "product_native"], ignore_index=True
    )


class JapanMetiScraper:
    country = "japan"

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir)
        self.raw_dir = self.data_dir / "raw" / "japan"
        self.kakuhou_dir = self.raw_dir / "kakuhou"
        self.sokuhou_dir = self.raw_dir / "sokuhou"
        self.yearbook_dir = self.raw_dir / "yearbook"
        self.kakuhou_dir.mkdir(parents=True, exist_ok=True)
        self.sokuhou_dir.mkdir(parents=True, exist_ok=True)
        self.yearbook_dir.mkdir(parents=True, exist_ok=True)

    def build_from_raw(self) -> pd.DataFrame:
        return build_monthly_series(self.raw_dir)

    def _save_if_needed(
        self,
        url: str,
        dest: Path,
        *,
        force: bool,
    ) -> bool:
        if dest.exists() and not force:
            logger.info("  skip (exists): %s", dest.name)
            return False
        logger.info("  download: %s", dest.name)
        r = _get(url)
        r.raise_for_status()
        if r.content[:2] != b"PK":
            raise ValueError(f"Expected xlsx zip at {url}, got {r.content[:8]!r}")
        dest.write_bytes(r.content)
        return True

    def download_kakuhou_index(self, *, force: bool = False) -> list[DownloadResult]:
        r = _get(KAKUHOU_INDEX)
        r.raise_for_status()
        links = discover_kakuhou_links(r.text)
        results: list[DownloadResult] = []
        for rel, _yyyymm in links:
            fname = Path(rel).name
            url = urljoin(KAKUHOU_INDEX, rel)
            dest = self.kakuhou_dir / fname
            fetched = self._save_if_needed(url, dest, force=force)
            results.append(DownloadResult(dest, fetched, False))
        return results

    def download_sokuhou_latest(self, *, force: bool = False) -> list[DownloadResult]:
        """Fetch Japanese + English 速報 workbooks (English often publishes next month first)."""
        results: list[DownloadResult] = []

        r = _get(SOKUHOU_RESULT)
        r.raise_for_status()
        rel = discover_sokuhou_link(r.text)
        if not rel:
            raise RuntimeError("No preliminary xlsx link on sekiyuso/result.html")
        fname = Path(rel).name
        if rel.startswith("http"):
            url = rel
        elif rel.startswith("result/"):
            url = urljoin(f"{METI_BASE}/statistics/tyo/sekiyuso/", rel)
        else:
            url = f"{METI_BASE}/statistics/tyo/sekiyuso/result/xls/{fname}"
        dest = self.sokuhou_dir / fname
        fetched = self._save_if_needed(url, dest, force=force)
        results.append(DownloadResult(dest, fetched, True))

        try:
            en = _get(SOKUHOU_ENGLISH_INDEX)
            en.raise_for_status()
            en_rel = discover_sokuhou_english_link(en.text)
            if en_rel:
                en_fname = Path(en_rel).name
                # Relative ../sekiyuso/excel/… breaks urljoin; use stable path under /english/…
                en_url = (
                    f"{METI_BASE}/english/statistics/tyo/sekiyuso/excel/{en_fname}"
                )
                en_dest = self.sokuhou_dir / en_fname
                en_fetched = self._save_if_needed(en_url, en_dest, force=force)
                results.append(DownloadResult(en_dest, en_fetched, True))
            else:
                logger.warning("No English 速報 xlsx on %s", SOKUHOU_ENGLISH_INDEX)
        except Exception as exc:
            logger.warning("English 速報 download skipped: %s", exc)

        return results

    def download_yearbooks(self, *, force: bool = False) -> list[DownloadResult]:
        r = _get(KAKUHOU_INDEX)
        r.raise_for_status()
        links = discover_yearbook_links(r.text)
        results: list[DownloadResult] = []
        for rel, _year in links:
            fname = Path(rel).name
            url = urljoin(KAKUHOU_INDEX, rel)
            dest = self.yearbook_dir / fname
            try:
                fetched = self._save_if_needed(url, dest, force=force)
            except requests.HTTPError as exc:
                code = exc.response.status_code if exc.response is not None else None
                if code == 404:
                    logger.warning("  skip (404): %s", fname)
                    continue
                raise
            results.append(DownloadResult(dest, fetched, False))
        return results

    def download_bootstrap(self, *, force: bool = False) -> list[DownloadResult]:
        out = self.download_yearbooks(force=force)
        out.extend(self.download_kakuhou_index(force=force))
        out.extend(self.download_sokuhou_latest(force=force))
        return out

    def download_refresh(
        self,
        *,
        lookback_months: int = 6,
        force: bool = False,
    ) -> list[DownloadResult]:
        """Fetch latest 速報 + recent 確報 months."""
        results: list[DownloadResult] = []
        results.extend(self.download_sokuhou_latest(force=force))

        r = _get(KAKUHOU_INDEX)
        r.raise_for_status()
        links = discover_kakuhou_links(r.text)
        for rel, _yyyymm in links[-lookback_months:]:
            fname = Path(rel).name
            url = urljoin(KAKUHOU_INDEX, rel)
            dest = self.kakuhou_dir / fname
            fetched = self._save_if_needed(url, dest, force=force)
            results.append(DownloadResult(dest, fetched, False))
        return results

    def parse(self, raw_path: Path, *, is_provisional: Optional[bool] = None) -> pd.DataFrame:
        raw_path = Path(raw_path)
        if is_provisional is None:
            is_provisional = raw_path.parent.name == "sokuhou" or raw_path.name.lower().startswith(
                "h2j"
            )
        partial = parse_meti_workbook(raw_path, is_provisional=is_provisional)
        return _finalize(partial, updated_at=datetime.utcnow())
