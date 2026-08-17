"""
scrapers/taiwan_moea.py
───────────────────────
MOEA E-STATE-STAT Table 5-04 — petroleum products consumption (by product).
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, NamedTuple, Optional
from urllib.parse import quote, unquote

from curl_cffi import requests

from reference.taiwan import finalize_moea_frame, parse_moea_consumption_workbook

logger = logging.getLogger(__name__)

MOEA_BASE = "https://ea01.moeaea.gov.tw/a0303/02"
MOEA_PAGE_URL = f"{MOEA_BASE}/en/newest/monthly/?tab=Oil"
# Astro SPA loads table/download metadata from this JSON endpoint (not HTML).
MOEA_MONTHLY_API_URL = f"{MOEA_BASE}/api/pages/en/newest/monthly"
IMPERSONATE_PROFILE = "chrome131"
DATASET = "petroleum_consumption"
OIL_TAB_NAME = "Oil"
TABLE_504_MARKER = "5-04"

# Corporate networks may not trust the MOEA TLS chain.
VERIFY_TLS = False

# Fallback for serialized JSON / legacy HTML that still embeds the path.
_XLSX_API_RE = re.compile(
    r"/api/files/(m_5-04[^\"\\]+\.xlsx)",
    re.I,
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


def _filename_from_api_path(api_path: str) -> str:
    """Strip /api/files/ prefix and URL-decoding from an excel path."""
    name = unquote(api_path)
    prefix = "/api/files/"
    if name.lower().startswith(prefix):
        name = name[len(prefix) :]
    return name


def _xlsx_path_from_monthly_json(payload: dict[str, Any]) -> Optional[str]:
    """Pull m_5-04*.xlsx filename from the Oil tab of the monthly API JSON."""
    tabs = payload.get("tabs") or {}
    oil = tabs.get(OIL_TAB_NAME)
    if not isinstance(oil, dict):
        return None

    for item in oil.get("attachment") or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "")
        formats = item.get("formats") or {}
        excel = formats.get("excel") if isinstance(formats, dict) else None
        if not excel:
            continue
        excel_s = str(excel)
        # Prefer the labeled 5-04 row; also accept any m_5-04 path under Oil.
        if TABLE_504_MARKER in title or "m_5-04" in excel_s.lower():
            return _filename_from_api_path(excel_s)
    return None


def discover_consumption_xlsx_path(payload: str | dict[str, Any]) -> str:
    """Return workbook filename for the 5-04 consumption xlsx.

    Accepts the monthly page JSON (dict), its serialized form, or legacy HTML
    that still embeds ``/api/files/m_5-04....xlsx``.
    """
    if isinstance(payload, dict):
        found = _xlsx_path_from_monthly_json(payload)
        if found:
            return found
        raise RuntimeError(
            "Could not find 5-04 petroleum consumption xlsx in MOEA monthly API. "
            "The Oil tab layout may have changed."
        )

    text = payload
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        parsed = None
    if isinstance(parsed, dict):
        found = _xlsx_path_from_monthly_json(parsed)
        if found:
            return found

    m = _XLSX_API_RE.search(text)
    if m:
        return unquote(m.group(1))

    raise RuntimeError(
        "Could not find 5-04 petroleum consumption xlsx link on MOEA page/API. "
        "The portal layout may have changed."
    )


def discover_consumption_download_url(payload: str | dict[str, Any]) -> str:
    filename = discover_consumption_xlsx_path(payload)
    return f"{MOEA_BASE}/api/files/{quote(filename, safe='()_-.~')}"


def _get(url: str) -> requests.Response:
    return requests.get(
        url,
        impersonate=IMPERSONATE_PROFILE,
        timeout=120,
        verify=VERIFY_TLS,
    )


class TaiwanMoeaScraper:
    """Download + parse MOEA monthly energy statistics (Table 5-04)."""

    country = "taiwan"

    def __init__(self, data_dir: str | Path = "data") -> None:
        self.data_dir = Path(data_dir)
        self.raw_dir = self.data_dir / "raw" / "taiwan"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self._legacy_raw_dir = self.data_dir / "raw" / "Taiwan"

    def fetch_page_html(self) -> str:
        """Legacy HTML fetch; downloads no longer embed xlsx links here."""
        resp = _get(MOEA_PAGE_URL)
        resp.raise_for_status()
        return resp.text

    def fetch_monthly_page_json(self) -> dict[str, Any]:
        """Fetch monthly statistics metadata (tabs, attachment download paths)."""
        resp = _get(MOEA_MONTHLY_API_URL)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            raise RuntimeError(
                f"Unexpected MOEA monthly API payload type: {type(data).__name__}"
            )
        return data

    def download(
        self,
        dataset_name: str = DATASET,
        *,
        force: bool = False,
    ) -> Path:
        # Discovery moved off HTML after the Astro redesign (links live in JSON).
        payload = self.fetch_monthly_page_json()
        download_url = discover_consumption_download_url(payload)
        filename = discover_consumption_xlsx_path(payload)
        dest = self.raw_dir / filename

        if dest.exists() and not force:
            logger.info("Using cached %s", dest.name)
            return dest

        logger.info("Downloading %s", download_url)
        resp = _get(download_url)
        resp.raise_for_status()
        content = resp.content
        if content[:2] != b"PK":
            raise RuntimeError(
                f"Expected xlsx zip archive from {download_url}, "
                f"got {len(content)} bytes starting with {content[:8]!r}"
            )

        dest.write_bytes(content)
        logger.info("Saved %s (%d KB)", dest, len(content) // 1024)
        return dest

    def download_refresh(self, *, force: bool = False) -> DownloadResult:
        before = {p.resolve() for p in self.raw_dir.glob("m_5-04*.xlsx")}
        path = self.download(DATASET, force=force)
        fetched = path.resolve() not in before or force
        return DownloadResult(path=path, fetched=fetched)

    def parse(self, dataset_name: str, raw_path: Path) -> "pd.DataFrame":
        import pandas as pd  # noqa: F401 — kept for type checkers / callers

        raw_path = Path(raw_path)
        partial = parse_moea_consumption_workbook(raw_path)
        return finalize_moea_frame(partial, source_file=raw_path.name)

    def latest_local_workbook(self) -> Optional[Path]:
        candidates = list(self.raw_dir.glob("m_5-04*.xlsx"))
        if not candidates and self._legacy_raw_dir.exists():
            candidates = list(self._legacy_raw_dir.glob("m_5-04*.xlsx"))
        if not candidates:
            return None
        return max(candidates, key=lambda p: p.stat().st_mtime)


__all__ = [
    "TaiwanMoeaScraper",
    "DownloadResult",
    "CANONICAL_COLUMNS",
    "DATASET",
    "MOEA_PAGE_URL",
    "MOEA_MONTHLY_API_URL",
    "discover_consumption_download_url",
    "discover_consumption_xlsx_path",
]
