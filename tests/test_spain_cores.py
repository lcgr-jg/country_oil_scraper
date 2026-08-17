"""Tests for Spain CORES petroleum consumption parser."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from reference.spain import (
    CORES_UNIT_NATIVE,
    DELIVERY_HEADLINE_NATIVE,
    GASOLINE_JODI_NATIVES,
    GASOIL_JODI_NATIVES,
    is_cores_stored,
    parse_cores_consumption_workbook,
)
from reference.loaders import load_product_map

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_XLSX = PROJECT_ROOT / "data" / "raw" / "spain" / "oil-products-consumption.xlsx"


@pytest.fixture(scope="module")
def raw_path() -> Path:
    if not RAW_XLSX.exists():
        pytest.skip(f"Missing fixture: {RAW_XLSX}")
    return RAW_XLSX


@pytest.fixture(scope="module")
def partial(raw_path: Path) -> pd.DataFrame:
    return parse_cores_consumption_workbook(raw_path)


def test_product_map_has_cores_rows():
    pm = load_product_map()
    cores = pm[pm["Source"] == "CORES"]
    assert len(cores) >= 27


def test_parse_row_count(partial: pd.DataFrame):
    # ~27 products × ~363 months
    assert len(partial) > 7_500
    assert partial["product_native"].nunique() == 27


def test_parse_excludes_aggregates(partial: pd.DataFrame):
    natives = set(partial["product_native"])
    assert "Gasoline | Total" not in natives
    assert "Gasoil | Subtotal road diesel" not in natives
    assert all(is_cores_stored(n) for n in natives)


def test_gasoline_jodi_includes_aviation_and_bio():
    assert "Gasoline | Aviation gasoline" in GASOLINE_JODI_NATIVES
    assert "Gasoline | Biogasoline" in GASOLINE_JODI_NATIVES


def test_gasoil_jodi_includes_biodiesel_and_heating():
    assert "Gasoil | Biodiesel (B100)" in GASOIL_JODI_NATIVES
    assert "Gasoil | Heating oil" in GASOIL_JODI_NATIVES


def test_date_range(partial: pd.DataFrame):
    assert partial["date"].min() == pd.Timestamp("1996-01-01")
    assert partial["date"].max() >= pd.Timestamp("2026-03-01")


def test_scraper_finalize(raw_path: Path):
    from scrapers.spain_cores import SpainCoresScraper

    df = SpainCoresScraper(data_dir=PROJECT_ROOT / "data").parse(
        "petroleum_consumption", raw_path
    )
    assert df["unit"].eq(CORES_UNIT_NATIVE).all()
    assert df["country"].eq("ES").all()
    assert not df["is_provisional"].any()


def test_processor_build(raw_path: Path, tmp_path: Path):
    from processors import spain_cores_consumption as proc

    df = proc.build_from_historical(raw_path)
    assert "product_canonical" in df.columns
    assert df["product_canonical"].notna().all()
    paths = proc.save(df, tmp_path)
    assert paths["parquet"].exists()
