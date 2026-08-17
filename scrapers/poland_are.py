"""
scrapers/poland_are.py
──────────────────────
ARE Statistical Information on the Liquid Fuels Market (Biuletyn *.xls).
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple, Optional
from urllib.parse import unquote

import pandas as pd
import requests

from reference.poland import (
    CANONICAL_COLUMNS,
    CMS_BASE_URL,
    PUBLICATIONS_PAGE_PL,
    discover_liquid_fuel_paths,
    finalize_are_frame,
    is_liquid_fuels_bulletin,
    parse_are_liquid_fuels_workbook,
    publication_date_from_path,
)

logger = logging.getLogger(__name__)

DATASET = "liquid_fuels"
_XLS_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_FILENAME_RE = re.compile(
    r"Biuletyn_(?P<month>[a-z]+)_(?P<year>\d{4})_[a-f0-9]+\.xls",
    re.I,
)


class DownloadResult(NamedTuple):
    path: Path
    fetched: bool


class PolandAreScraper:
    """Download + parse ARE liquid-fuels monthly bulletins."""

    country = "poland"

    def __init__(self, data_dir: str | Path = "data") -> None:
        self.data_dir = Path(data_dir)
        self.raw_dir = self.data_dir / "raw" / "poland" / "are"
        self.raw_dir.mkdir(parents=True, exist_ok=True)

    def discover_download_links(self) -> list[tuple[str, str]]:
        """Return (filename, absolute_url) for liquid-fuels Biuletyn files."""
        headers = {"User-Agent": "country_oil_scraper/1.0 (ARE liquid fuels)"}
        resp = requests.get(PUBLICATIONS_PAGE_PL, timeout=60, headers=headers)
        resp.raise_for_status()
        rel_paths = discover_liquid_fuel_paths(resp.text)
        out: list[tuple[str, str]] = []
        for rel in rel_paths:
            if not rel.lower().endswith(".xls"):
                continue
            name = unquote(Path(rel).name)
            out.append((name, CMS_BASE_URL + rel))
        return out

    def _download_one(self, url: str, dest: Path, *, force: bool) -> bool:
        headers = {"User-Agent": "country_oil_scraper/1.0 (ARE liquid fuels)"}
        if dest.exists() and not force:
            return False
        logger.info("Downloading %s -> %s", url, dest.name)
        resp = requests.get(url, timeout=180, headers=headers)
        resp.raise_for_status()
        content = resp.content
        if not content.startswith(_XLS_MAGIC):
            raise RuntimeError(f"Expected .xls from {url}, got unexpected payload")
        dest.write_bytes(content)
        if not is_liquid_fuels_bulletin(dest):
            dest.unlink(missing_ok=True)
            raise RuntimeError(f"{dest.name} is not an ARE liquid-fuels Biuletyn")
        return True

    def download_bootstrap(self, *, force: bool = False) -> list[Path]:
        """Download all liquid-fuels Biuletyn files linked from the ARE page."""
        links = self.discover_download_links()
        if not links:
            raise RuntimeError(f"No liquid-fuels links on {PUBLICATIONS_PAGE_PL}")

        saved: list[Path] = []
        skipped_404 = 0
        skipped_other = 0
        for name, url in links:
            dest = self.raw_dir / name
            try:
                fetched = self._download_one(url, dest, force=force)
            except requests.HTTPError as exc:
                if exc.response is not None and exc.response.status_code == 404:
                    skipped_404 += 1
                    logger.warning("Missing on CMS (404): %s", name)
                    continue
                raise
            except RuntimeError as exc:
                skipped_other += 1
                logger.warning("Skipping %s: %s", name, exc)
                continue
            if fetched or dest.exists():
                saved.append(dest)

        logger.info(
            "Bootstrap: %d file(s) cached (%d 404, %d rejected)",
            len(saved),
            skipped_404,
            skipped_other,
        )
        return sorted(saved, key=_bulletin_sort_key)

    def download_latest(self, *, force: bool = False) -> DownloadResult:
        """Download the newest Biuletyn by publication month."""
        local = self.local_bulletins()
        links = self.discover_download_links()
        biuletyn_links = [
            (name, url) for name, url in links if _FILENAME_RE.search(name)
        ]
        if not biuletyn_links:
            raise RuntimeError("No Biuletyn links discovered")

        biuletyn_links.sort(key=lambda item: _bulletin_sort_key(Path(item[0])))
        name, url = biuletyn_links[-1]
        dest = self.raw_dir / name
        fetched = self._download_one(url, dest, force=force)
        if not fetched and dest.exists():
            logger.info("Using cached %s", dest.name)
        elif local and not fetched:
            latest_local = local[-1]
            if _bulletin_sort_key(latest_local) >= _bulletin_sort_key(dest):
                return DownloadResult(latest_local, fetched=False)
        return DownloadResult(dest, fetched=fetched)

    def local_bulletins(self) -> list[Path]:
        paths = sorted(self.raw_dir.glob("Biuletyn_*.xls"), key=_bulletin_sort_key)
        return [p for p in paths if is_liquid_fuels_bulletin(p)]

    def latest_local_bulletin(self) -> Optional[Path]:
        bulletins = self.local_bulletins()
        return bulletins[-1] if bulletins else None

    def parse(self, dataset_name: str, raw_path: Path) -> pd.DataFrame:
        if dataset_name != DATASET:
            raise ValueError(f"Unknown dataset: {dataset_name}")
        native = parse_are_liquid_fuels_workbook(raw_path)
        return self._finalize(native, raw_path)

    def parse_all(self, paths: Optional[list[Path]] = None) -> pd.DataFrame:
        paths = paths or self.local_bulletins()
        if not paths:
            raise FileNotFoundError(f"No bulletins under {self.raw_dir}")
        frames = [self.parse(DATASET, path) for path in paths]
        combined = pd.concat(frames, ignore_index=True)
        return self._dedupe_combined(combined)

    def _finalize(self, df: pd.DataFrame, raw_path: Path) -> pd.DataFrame:
        out = finalize_are_frame(df)
        for col in CANONICAL_COLUMNS:
            if col not in out.columns:
                out[col] = pd.NA
        return out[CANONICAL_COLUMNS]

    def _dedupe_combined(self, df: pd.DataFrame) -> pd.DataFrame:
        key = ["date", "country", "source", "metric_type", "product_native"]
        return (
            df.sort_values(key + ["source_file"])
            .drop_duplicates(subset=key, keep="last")
            .sort_values(["date", "metric_type", "product_native"])
            .reset_index(drop=True)
        )


def _bulletin_sort_key(path: Path) -> tuple[int, int]:
    pub = publication_date_from_path(path)
    if pub is not None:
        return (int(pub.year), int(pub.month))
    m = _FILENAME_RE.search(path.name)
    if m:
        from reference.poland import _POLISH_MONTH_SLUG

        month = _POLISH_MONTH_SLUG.get(m.group("month").lower(), 0)
        return (int(m.group("year")), month)
    return (0, 0)
