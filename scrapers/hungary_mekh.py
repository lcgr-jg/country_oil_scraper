"""
scrapers/hungary_mekh.py
────────────────────────
MEKH monthly oil balance (demand + closing stocks) via OData.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple, Optional

import pandas as pd
import requests

from reference.hungary import (
    CLOSING_STOCK_FLOW,
    DEMAND_RAW_FILENAME,
    GID_OBSERVED_FLOW,
    MEKH_STOCKS_METRIC,
    ODATA_ENTITY_DEMAND,
    ODATA_ENTITY_STOCKS,
    STOCKS_RAW_FILENAME,
    finalize_mekh_frame,
    fetch_closing_stock_rows,
    fetch_gid_observed_rows,
    parse_demand_odata_json,
    parse_demand_odata_records,
    parse_stocks_odata_json,
    parse_stocks_odata_records,
    save_odata_snapshot,
)

logger = logging.getLogger(__name__)

DATASET_DEMAND = "oil_balance_demand"
DATASET_STOCKS = "oil_balance_stocks"


class DownloadResult(NamedTuple):
    path: Path
    fetched: bool


class HungaryMekhScraper:
    """Download + parse MEKH oil balance demand and closing stocks."""

    country = "hungary"

    def __init__(self, data_dir: str | Path = "data") -> None:
        self.data_dir = Path(data_dir)
        self.demand_raw_dir = self.data_dir / "raw" / "hungary" / "demand"
        self.stocks_raw_dir = self.data_dir / "raw" / "hungary" / "stocks"
        self.demand_raw_dir.mkdir(parents=True, exist_ok=True)
        self.stocks_raw_dir.mkdir(parents=True, exist_ok=True)

    @property
    def demand_snapshot_path(self) -> Path:
        return self.demand_raw_dir / DEMAND_RAW_FILENAME

    @property
    def stocks_snapshot_path(self) -> Path:
        return self.stocks_raw_dir / STOCKS_RAW_FILENAME

    def download_demand(
        self,
        *,
        force: bool = False,
        session: Optional[requests.Session] = None,
    ) -> DownloadResult:
        dest = self.demand_snapshot_path
        if dest.exists() and not force:
            logger.info("Using cached MEKH demand snapshot: %s", dest.name)
            return DownloadResult(dest, fetched=False)

        logger.info("Fetching MEKH GID Observed from OData")
        records = fetch_gid_observed_rows(session=session)
        save_odata_snapshot(
            records,
            dest,
            entity=ODATA_ENTITY_DEMAND,
            flow=GID_OBSERVED_FLOW,
        )
        logger.info("Saved %d demand rows -> %s", len(records), dest)
        return DownloadResult(dest, fetched=True)

    def download_stocks(
        self,
        *,
        force: bool = False,
        session: Optional[requests.Session] = None,
    ) -> DownloadResult:
        dest = self.stocks_snapshot_path
        if dest.exists() and not force:
            logger.info("Using cached MEKH stocks snapshot: %s", dest.name)
            return DownloadResult(dest, fetched=False)

        logger.info("Fetching MEKH closing stocks (CSNATTER) from OData")
        records = fetch_closing_stock_rows(session=session)
        save_odata_snapshot(
            records,
            dest,
            entity=ODATA_ENTITY_STOCKS,
            flow=CLOSING_STOCK_FLOW,
        )
        logger.info("Saved %d stock rows -> %s", len(records), dest)
        return DownloadResult(dest, fetched=True)

    def download(
        self,
        dataset_name: str = DATASET_DEMAND,
        *,
        force: bool = False,
        session: Optional[requests.Session] = None,
    ) -> DownloadResult:
        """Download demand only (legacy entry point)."""
        return self.download_demand(force=force, session=session)

    def download_all(
        self,
        *,
        force: bool = False,
        session: Optional[requests.Session] = None,
    ) -> list[DownloadResult]:
        sess = session or requests.Session()
        return [
            self.download_demand(force=force, session=sess),
            self.download_stocks(force=force, session=sess),
        ]

    def parse_demand(
        self,
        raw_path: Path | None = None,
        *,
        updated_at: datetime | None = None,
    ) -> pd.DataFrame:
        path = Path(raw_path) if raw_path is not None else self.demand_snapshot_path
        if not path.exists():
            raise FileNotFoundError(f"No MEKH demand snapshot at {path}")
        partial = parse_demand_odata_json(path)
        ts = updated_at or datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        return finalize_mekh_frame(
            partial,
            updated_at=ts,
            source_file=path.name,
        )

    def parse_stocks(
        self,
        raw_path: Path | None = None,
        *,
        updated_at: datetime | None = None,
    ) -> pd.DataFrame:
        path = Path(raw_path) if raw_path is not None else self.stocks_snapshot_path
        if not path.exists():
            raise FileNotFoundError(f"No MEKH stocks snapshot at {path}")
        partial = parse_stocks_odata_json(path)
        ts = updated_at or datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        return finalize_mekh_frame(
            partial,
            updated_at=ts,
            source_file=path.name,
            metric_type=MEKH_STOCKS_METRIC,
        )

    def parse(
        self,
        dataset_name: str = DATASET_DEMAND,
        raw_path: Path | None = None,
        *,
        updated_at: datetime | None = None,
    ) -> pd.DataFrame:
        if dataset_name == DATASET_STOCKS:
            return self.parse_stocks(raw_path, updated_at=updated_at)
        return self.parse_demand(raw_path, updated_at=updated_at)

    def parse_all(self) -> pd.DataFrame:
        """Demand + stocks in one tidy frame."""
        parts = [self.parse_demand(), self.parse_stocks()]
        return pd.concat(parts, ignore_index=True)

    def parse_demand_records(self, records: list[dict]) -> pd.DataFrame:
        partial = parse_demand_odata_records(records)
        return finalize_mekh_frame(
            partial,
            updated_at=datetime.now(UTC),
            source_file="inline",
        )

    def parse_stocks_records(self, records: list[dict]) -> pd.DataFrame:
        partial = parse_stocks_odata_records(records)
        return finalize_mekh_frame(
            partial,
            updated_at=datetime.now(UTC),
            source_file="inline",
            metric_type=MEKH_STOCKS_METRIC,
        )

    def parse_records(self, records: list[dict]) -> pd.DataFrame:
        """Backward-compatible alias for demand-only tests."""
        return self.parse_demand_records(records)
