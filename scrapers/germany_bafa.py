"""
scrapers/germany_bafa.py
────────────────────────
BAFA Amtliche Mineralöldaten — download + parse monthly XLSX/PDF files.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple, Optional

import pandas as pd
import requests

from reference.germany import (
    HISTORY_START,
    MonthFile,
    download_many,
    download_month,
    finalize_bafa_frame,
    list_local_month_files,
    month_grid,
    parse_month_file,
)

logger = logging.getLogger(__name__)

DATASET = "amtliche_mineraloeldaten"


class DownloadResult(NamedTuple):
    path: Path
    fetched: bool
    kind: str
    year: int
    month: int


class GermanyBafaScraper:
    """Download + parse BAFA monthly mineral oil statistics."""

    country = "germany"

    def __init__(self, data_dir: str | Path = "data") -> None:
        self.data_dir = Path(data_dir)
        self.raw_dir = self.data_dir / "raw" / "germany"
        self.raw_dir.mkdir(parents=True, exist_ok=True)

    def download_month(
        self,
        year: int,
        month: int,
        *,
        force: bool = False,
        session: Optional[requests.Session] = None,
    ) -> DownloadResult:
        before = {
            p.resolve()
            for p in self.raw_dir.glob(f"moel_amtliche_daten_{year}_{month:02d}.*")
        }
        mf = download_month(
            year, month, self.raw_dir, session=session, force=force
        )
        fetched = force or mf.path.resolve() not in before or not before
        # If file existed and force=False, download_month returns cache → not fetched.
        if not force and before:
            fetched = False
        return DownloadResult(mf.path, fetched, mf.kind, mf.year, mf.month)

    def download_history(
        self,
        *,
        start: str = HISTORY_START,
        end: Optional[str] = None,
        force: bool = False,
    ) -> list[DownloadResult]:
        end = end or pd.Timestamp.today().strftime("%Y-%m")
        months = month_grid(start, end)
        files = download_many(months, self.raw_dir, force=force)
        return [
            DownloadResult(f.path, True, f.kind, f.year, f.month) for f in files
        ]

    def download_latest(self, *, force: bool = False) -> list[DownloadResult]:
        """Fetch months after the newest local file through today."""
        local = list_local_month_files(self.raw_dir)
        if local:
            last = max((f.year, f.month) for f in local)
            start = (
                pd.Timestamp(year=last[0], month=last[1], day=1)
                + pd.offsets.MonthBegin(1)
            ).strftime("%Y-%m")
        else:
            start = HISTORY_START
        end = pd.Timestamp.today().strftime("%Y-%m")
        if start > end:
            logger.info("Local BAFA files already cover through %s", end)
            return []
        return self.download_history(start=start, end=end, force=force)

    def parse(self, dataset_name: str, raw_path: Path) -> pd.DataFrame:
        if dataset_name != DATASET:
            raise ValueError(f"Unknown dataset {dataset_name!r}; expected {DATASET!r}")
        path = Path(raw_path)
        year, month = _ym_from_path(path)
        kind = "xlsx" if path.suffix.lower() == ".xlsx" else "pdf"
        mf = MonthFile(path, kind, year, month)
        df = parse_month_file(mf)
        return finalize_bafa_frame(df)

    def parse_month(self, year: int, month: int) -> pd.DataFrame:
        mf = download_month(year, month, self.raw_dir, force=False)
        df = parse_month_file(mf)
        return finalize_bafa_frame(df)

    def parse_all_local(self) -> pd.DataFrame:
        files = list_local_month_files(self.raw_dir)
        if not files:
            raise FileNotFoundError(
                f"No BAFA month files under {self.raw_dir}. "
                "Run download_history() first."
            )
        parts: list[pd.DataFrame] = []
        for mf in files:
            try:
                parts.append(parse_month_file(mf))
            except Exception:
                logger.exception("Failed to parse %s", mf.path.name)
                raise
        df = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
        return finalize_bafa_frame(df, updated_at=datetime.now(UTC).replace(tzinfo=None))


def _ym_from_path(path: Path) -> tuple[int, int]:
    from reference.germany import year_month_from_filename

    return year_month_from_filename(path)
