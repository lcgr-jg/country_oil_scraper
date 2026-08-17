"""Parquet fingerprints used to decide updated vs unchanged after a poll."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from pipelines.registry import PROJECT_ROOT


@dataclass(frozen=True)
class ParquetFingerprint:
    """Lightweight snapshot of a processed country parquet."""

    path: Path
    exists: bool
    rows: int | None = None
    max_date: str | None = None  # ISO date string when available

    def unchanged_from(self, other: ParquetFingerprint | None) -> bool:
        if other is None or not self.exists or not other.exists:
            return False
        return self.rows == other.rows and self.max_date == other.max_date


def fingerprint_parquet(
    rel_path: str | Path,
    *,
    date_column: str = "date",
    processed_root: Path | None = None,
) -> ParquetFingerprint:
    """Read row count + max(date) from ``data/processed/{rel_path}``."""
    root = processed_root or (PROJECT_ROOT / "data" / "processed")
    path = root / rel_path
    if not path.is_file():
        return ParquetFingerprint(path=path, exists=False)

    # Only pull columns we need — processed files can be wide.
    cols = [date_column]
    try:
        df = pd.read_parquet(path, columns=cols)
    except Exception:
        # Column missing or corrupt — fall back to row count only.
        df = pd.read_parquet(path)
        rows = len(df)
        max_date = None
        if date_column in df.columns:
            max_date = str(pd.to_datetime(df[date_column]).max().date())
        return ParquetFingerprint(path=path, exists=True, rows=rows, max_date=max_date)

    rows = len(df)
    max_date = None
    if date_column in df.columns and rows:
        max_date = str(pd.to_datetime(df[date_column]).max().date())
    return ParquetFingerprint(path=path, exists=True, rows=rows, max_date=max_date)
