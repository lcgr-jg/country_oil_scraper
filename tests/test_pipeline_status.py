"""Tests for parquet fingerprint + status classification (no network)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from pipelines.fingerprint import fingerprint_parquet
from pipelines.registry import get_pipeline


def test_norway_and_germany_have_parquet_paths():
    assert get_pipeline("norway").parquet_rel_path
    assert get_pipeline("germany").parquet_rel_path
    assert get_pipeline("jodi").parquet_rel_path is None


def test_fingerprint_unchanged(tmp_path: Path):
    path = tmp_path / "demo.parquet"
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-01", "2024-02-01"]),
            "value": [1.0, 2.0],
        }
    )
    df.to_parquet(path)

    a = fingerprint_parquet(path.name, processed_root=tmp_path)
    b = fingerprint_parquet(path.name, processed_root=tmp_path)
    assert a.exists and b.exists
    assert a.rows == 2
    assert a.max_date == "2024-02-01"
    assert b.unchanged_from(a)


def test_fingerprint_detects_new_month(tmp_path: Path):
    path = tmp_path / "demo.parquet"
    pd.DataFrame(
        {"date": pd.to_datetime(["2024-01-01"]), "value": [1.0]}
    ).to_parquet(path)
    before = fingerprint_parquet(path.name, processed_root=tmp_path)

    pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-01", "2024-02-01"]),
            "value": [1.0, 2.0],
        }
    ).to_parquet(path)
    after = fingerprint_parquet(path.name, processed_root=tmp_path)

    assert not after.unchanged_from(before)
    assert after.max_date == "2024-02-01"
    assert after.rows == 2
