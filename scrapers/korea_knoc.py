"""
scrapers/korea_knoc.py
──────────────────────
Download and parse KNOC/MOTIE Petronet statistics:
  - 제품별소비 (product consumption, TOTDEMO)
  - 석유제품재고 (product closing stocks, CLOSTLV)
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path
from typing import NamedTuple, Optional

import pandas as pd
import requests

from reference.korea import (
    CONSUMPTION_DATASET,
    COUNTRY_CODE,
    COUNTRY_NAME,
    KOREA_DATASETS,
    KoreaDataset,
    STOCKS_DATASET,
    audit_raw_csv,
    dataset_for_path,
    parse_bundle_filename,
    parse_korea_csv_files,
    parse_korea_directory,
    raw_dir_for_dataset,
)
from reference.petronet_knoc import (
    PetronetDatasetConfig,
    DateRange,
    csv_filename,
    default_session,
    fetch_table_html,
    html_table_to_wide_csv,
    iter_bootstrap_ranges,
    open_menu,
    petronet_config_for,
    rolling_refresh_range,
)

logger = logging.getLogger(__name__)

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

DEFAULT_BOOTSTRAP_START = CONSUMPTION_DATASET.bootstrap_start
REFRESH_FLOOR = date(2022, 1, 1)

_PETRONET_CONFIG: dict[str, PetronetDatasetConfig] = {
    "consumption": petronet_config_for("consumption"),
    "stocks": petronet_config_for("stocks"),
}


class DownloadResult(NamedTuple):
    path: Path
    fetched: bool  # True when Petronet was queried and the file was written


def _petronet_for(dataset: KoreaDataset) -> PetronetDatasetConfig:
    return _PETRONET_CONFIG[dataset.name]


def _finalize(
    partial: pd.DataFrame,
    dataset: KoreaDataset,
    *,
    updated_at: datetime,
) -> pd.DataFrame:
    if partial.empty:
        return pd.DataFrame(columns=CANONICAL_COLUMNS)

    df = partial.copy()
    df["country"] = COUNTRY_CODE
    df["country_name"] = COUNTRY_NAME
    df["source"] = dataset.source_id
    df["metric_type"] = dataset.metric_type
    df["product"] = df["product_native"]
    df["unit"] = dataset.unit_native
    df["is_provisional"] = False
    df["updated_at"] = updated_at

    return df[CANONICAL_COLUMNS].sort_values(
        ["date", "metric_type", "product_native"], ignore_index=True
    )


def build_monthly_series(
    raw_dir: Path,
    *,
    dataset: KoreaDataset,
    updated_at: Optional[datetime] = None,
) -> pd.DataFrame:
    """Parse all bundle CSVs under ``raw_dir`` for one dataset."""
    updated_at = updated_at or datetime.utcnow()
    partial = parse_korea_directory(raw_dir, dataset=dataset)
    return _finalize(partial, dataset, updated_at=updated_at)


def build_monthly_series_from_files(
    paths: list[Path],
    *,
    dataset: KoreaDataset,
    updated_at: Optional[datetime] = None,
) -> pd.DataFrame:
    """Parse only the given bundle CSV(s) — used for incremental updates."""
    updated_at = updated_at or datetime.utcnow()
    partial = parse_korea_csv_files(paths, dataset=dataset)
    return _finalize(partial, dataset, updated_at=updated_at)


def build_all_from_raw(
    data_dir: Path,
    *,
    updated_at: Optional[datetime] = None,
) -> pd.DataFrame:
    """Parse consumption + stocks bundles from ``data/raw/korea/``."""
    updated_at = updated_at or datetime.utcnow()
    frames: list[pd.DataFrame] = []
    for dataset in KOREA_DATASETS:
        raw_dir = raw_dir_for_dataset(data_dir, dataset)
        if not raw_dir.exists():
            logger.warning("Raw dir missing for %s: %s", dataset.name, raw_dir)
            continue
        try:
            frames.append(
                build_monthly_series(raw_dir, dataset=dataset, updated_at=updated_at)
            )
        except FileNotFoundError:
            logger.warning("No %s bundles in %s", dataset.name, raw_dir)
    if not frames:
        return pd.DataFrame(columns=CANONICAL_COLUMNS)
    return pd.concat(frames, ignore_index=True).sort_values(
        ["date", "metric_type", "product_native"], ignore_index=True
    )


def build_all_from_files(
    paths: list[Path],
    *,
    updated_at: Optional[datetime] = None,
) -> pd.DataFrame:
    """Incremental parse: group paths by dataset, then concat."""
    updated_at = updated_at or datetime.utcnow()
    by_dataset: dict[str, list[Path]] = {}
    for path in paths:
        ds = dataset_for_path(path)
        if ds is None:
            raise ValueError(f"Not a KNOC bundle filename: {path.name}")
        by_dataset.setdefault(ds.name, []).append(path)

    frames: list[pd.DataFrame] = []
    for dataset in KOREA_DATASETS:
        batch = by_dataset.get(dataset.name)
        if not batch:
            continue
        frames.append(
            build_monthly_series_from_files(
                batch, dataset=dataset, updated_at=updated_at
            )
        )
    if not frames:
        return pd.DataFrame(columns=CANONICAL_COLUMNS)
    return pd.concat(frames, ignore_index=True).sort_values(
        ["date", "metric_type", "product_native"], ignore_index=True
    )


class KoreaKnocScraper:
    """Petronet KNOC scraper (consumption + stocks) + local CSV parse."""

    country = "korea"

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir)
        self.raw_dir = self.data_dir / "raw" / "korea"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        for dataset in KOREA_DATASETS:
            raw_dir_for_dataset(self.data_dir, dataset).mkdir(parents=True, exist_ok=True)

    def raw_dir_for(self, dataset: KoreaDataset) -> Path:
        return raw_dir_for_dataset(self.data_dir, dataset)

    def build_from_raw(self) -> pd.DataFrame:
        logger.info("Building Korea KNOC series from %s", self.data_dir / "raw" / "korea")
        return build_all_from_raw(self.data_dir)

    def download_range(
        self,
        dr: DateRange,
        *,
        dataset: KoreaDataset = CONSUMPTION_DATASET,
        session: Optional[requests.Session] = None,
        force: bool = False,
    ) -> DownloadResult:
        """Download one date window and save as a KNOC bundle CSV."""
        raw_dir = self.raw_dir_for(dataset)
        path = raw_dir / csv_filename(dr, bundle_prefix=dataset.bundle_prefix)
        if path.exists() and not force:
            logger.info("  Cached %s (skip fetch)", path.name)
            return DownloadResult(path, fetched=False)

        config = _petronet_for(dataset)
        session = session or default_session()
        open_menu(session, menu_ids=config.menu_ids)
        logger.info(
            "  Fetching Petronet %s %s -> %s",
            dataset.name,
            dr.start.strftime("%Y-%m"),
            dr.end.strftime("%Y-%m"),
        )
        html = fetch_table_html(session, dr, config=config)
        csv_text = html_table_to_wide_csv(html, layout=config.table_layout)
        path.write_text(csv_text, encoding="utf-8-sig")
        logger.info("  Saved %s (%d bytes)", path.name, path.stat().st_size)
        return DownloadResult(path, fetched=True)

    def download_bootstrap(
        self,
        *,
        dataset: KoreaDataset = CONSUMPTION_DATASET,
        start: Optional[date] = None,
        end: Optional[date] = None,
        force: bool = False,
    ) -> list[DownloadResult]:
        """Download full history in Petronet UI-limited chunks."""
        start = start or dataset.bootstrap_start
        end = end or _default_latest_month()
        config = _petronet_for(dataset)
        session = default_session()
        results: list[DownloadResult] = []
        for dr in iter_bootstrap_ranges(
            start, end, max_years=config.bootstrap_max_years
        ):
            results.append(
                self.download_range(
                    dr, dataset=dataset, session=session, force=force
                )
            )
        return results

    def download_bootstrap_all(
        self,
        *,
        force: bool = False,
    ) -> list[DownloadResult]:
        results: list[DownloadResult] = []
        for dataset in KOREA_DATASETS:
            results.extend(self.download_bootstrap(dataset=dataset, force=force))
        return results

    def download_refresh(
        self,
        *,
        dataset: KoreaDataset = CONSUMPTION_DATASET,
        end: Optional[date] = None,
        lookback_months: int = 24,
        force: bool = False,
    ) -> DownloadResult:
        """
        Download recent history for routine monthly updates.

        Saved as the rolling bundle (e.g. ``제품별소비(202201-YYYYMM).csv``).
        """
        end = end or _default_latest_month()
        dr = rolling_refresh_range(end, lookback_months=lookback_months)
        if dr.start < REFRESH_FLOOR:
            dr = DateRange(REFRESH_FLOOR, dr.end)
        return self.download_range(dr, dataset=dataset, force=force)

    def download_refresh_all(
        self,
        *,
        lookback_months: int = 24,
        force: bool = False,
    ) -> list[DownloadResult]:
        return [
            self.download_refresh(
                dataset=dataset,
                lookback_months=lookback_months,
                force=force,
            )
            for dataset in KOREA_DATASETS
        ]

    def download_repair_truncated(
        self,
        *,
        dataset: KoreaDataset = CONSUMPTION_DATASET,
        force: bool = True,
    ) -> list[DownloadResult]:
        """Re-download bundles whose parsed months do not cover the filename range."""
        config = _petronet_for(dataset)
        session = default_session()
        open_menu(session, menu_ids=config.menu_ids)
        raw_dir = self.raw_dir_for(dataset)
        repaired: list[DownloadResult] = []
        for path in sorted(raw_dir.glob(f"{dataset.bundle_prefix}(*).csv")):
            info = audit_raw_csv(path)
            if not info.get("truncated"):
                continue
            span = parse_bundle_filename(path, dataset=dataset)
            if span is None:
                continue
            start, end = span[0].date(), span[1].date()
            logger.warning(
                "  Truncated %s (%s): %s months parsed, %s expected; re-downloading",
                dataset.name,
                path.name,
                info.get("month_count"),
                info.get("expected_month_count"),
            )
            repaired.append(
                self.download_range(
                    DateRange(start, end),
                    dataset=dataset,
                    session=session,
                    force=force,
                )
            )
        return repaired

    def download_repair_truncated_all(
        self,
        *,
        force: bool = True,
    ) -> list[DownloadResult]:
        repaired: list[DownloadResult] = []
        for dataset in KOREA_DATASETS:
            repaired.extend(
                self.download_repair_truncated(dataset=dataset, force=force)
            )
        return repaired


def _default_latest_month() -> date:
    """Use previous calendar month when day-of-month is early (reporting lag)."""
    today = date.today()
    y, m = today.year, today.month - 1
    if m <= 0:
        y -= 1
        m = 12
    return date(y, m, 1)


__all__ = [
    "CANONICAL_COLUMNS",
    "CONSUMPTION_DATASET",
    "STOCKS_DATASET",
    "DateRange",
    "DownloadResult",
    "KoreaKnocScraper",
    "build_all_from_files",
    "build_all_from_raw",
    "build_monthly_series",
    "build_monthly_series_from_files",
]
