"""Tests for Portugal DGEG monthly sales parser."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pandas as pd
import pytest

from reference.loaders import load_product_map
from reference.portugal import (
    DGEG_UNIT_NATIVE,
    STORED_NATIVES,
    is_dgeg_stored,
    parse_dgeg_sales_workbook,
    workbook_sort_key,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_XLSX = (
    PROJECT_ROOT / "data" / "raw" / "portugal" / "dgeg-omn-2026-04_en.xlsx"
)


@pytest.fixture(scope="module")
def raw_path() -> Path:
    if RAW_XLSX.exists():
        return RAW_XLSX
    pytest.skip(f"Missing fixture: {RAW_XLSX}")


@pytest.fixture(scope="module")
def partial(raw_path: Path) -> pd.DataFrame:
    if not os.access(raw_path, os.R_OK):
        tmp = Path(os.environ["TEMP"]) / "dgeg-omn-2026-04_en.xlsx"
        shutil.copy2(raw_path, tmp)
        return parse_dgeg_sales_workbook(tmp)
    return parse_dgeg_sales_workbook(raw_path)


def test_product_map_has_dgeg_rows():
    pm = load_product_map()
    dgeg = pm[pm["Source"] == "DGEG"]
    assert len(dgeg) >= len(STORED_NATIVES)


def test_parse_row_count(partial: pd.DataFrame):
    assert len(partial) > 80
    assert partial["product_native"].nunique() >= 20


def test_parse_excludes_memo_and_bio(partial: pd.DataFrame):
    natives = set(partial["product_native"])
    assert not any("Memo Fuel" in n for n in natives)
    assert not any("Biodiesel" in n for n in natives)
    assert not any(n.startswith("of which") for n in natives)
    assert all(is_dgeg_stored(n) for n in natives)


def test_date_range(partial: pd.DataFrame):
    assert partial["date"].min() == pd.Timestamp("2026-01-01")
    assert partial["date"].max() == pd.Timestamp("2026-04-01")


def test_scraper_finalize(raw_path: Path):
    from scrapers.portugal_dgeg import PortugalDGEGScraper

    path = raw_path
    if not os.access(raw_path, os.R_OK):
        path = Path(os.environ["TEMP"]) / "dgeg-omn-2026-04_en.xlsx"
        shutil.copy2(raw_path, path)

    df = PortugalDGEGScraper(data_dir=PROJECT_ROOT / "data").parse(
        "monthly_sales", path
    )
    assert df["unit"].eq(DGEG_UNIT_NATIVE).all()
    assert df["country"].eq("PT").all()
    assert df["is_provisional"].all()


def test_processor_build(raw_path: Path, tmp_path: Path):
    from processors import portugal_dgeg_sales as proc

    path = raw_path
    if not os.access(raw_path, os.R_OK):
        path = Path(os.environ["TEMP"]) / "dgeg-omn-2026-04_en.xlsx"
        shutil.copy2(raw_path, path)

    df = proc.build_from_historical(path.parent)
    assert "product_canonical" in df.columns
    assert df["product_canonical"].notna().all()
    paths = proc.save(df, tmp_path)
    assert paths["parquet"].exists()


def test_workbook_sort_key_ranks_by_filename_without_opening():
    """Remote discovery must rank names before the xlsx exists on disk."""
    names = [
        "dgeg-omn-2021-20230731.xlsx",  # date stamp, not month 20
        "dgeg-omn-2025-12_en.xlsx",
        "dgeg-omn-2026-04_en.xlsx",
        "dgeg-omn-2026-05_en.xlsx",
    ]
    ranked = sorted(names, key=lambda n: workbook_sort_key(Path(n)), reverse=True)
    assert ranked[0] == "dgeg-omn-2026-05_en.xlsx"
    assert workbook_sort_key(Path("dgeg-omn-2026-05_en.xlsx"))[0] == 2026
    assert workbook_sort_key(Path("dgeg-omn-2026-05_en.xlsx"))[3] == 5
    # Publication stamp after year must not become month=20
    assert workbook_sort_key(Path("dgeg-omn-2021-20230731.xlsx"))[3] == 0
