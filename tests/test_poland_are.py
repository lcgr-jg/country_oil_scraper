"""Tests for Poland ARE liquid fuels Biuletyn parser."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pandas as pd
import pytest

from reference.loaders import load_product_map
from reference.poland import (
    ARE_UNIT_NATIVE,
    STORED_PRODUCTS,
    parse_are_liquid_fuels_workbook,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_XLS = PROJECT_ROOT / "data" / "raw" / "poland" / "are" / "Biuletyn_marzec_2026.xls"


@pytest.fixture(scope="module")
def raw_path() -> Path:
    if RAW_XLS.exists():
        return RAW_XLS
    pytest.skip(f"Missing fixture: {RAW_XLS}")


@pytest.fixture(scope="module")
def parsed(raw_path: Path) -> pd.DataFrame:
    if not os.access(raw_path, os.R_OK):
        tmp = Path(os.environ["TEMP"]) / "Biuletyn_marzec_2026.xls"
        shutil.copy2(raw_path, tmp)
        return parse_are_liquid_fuels_workbook(tmp)
    return parse_are_liquid_fuels_workbook(raw_path)


def test_product_map_has_are_rows():
    pm = load_product_map()
    are = pm[pm["Source"] == "ARE"]
    assert len(are) >= len(STORED_PRODUCTS)


def test_parse_row_count(parsed: pd.DataFrame):
    assert len(parsed) >= 50
    assert parsed["product_native"].nunique() == len(STORED_PRODUCTS)


def test_parse_metrics(parsed: pd.DataFrame):
    metrics = set(parsed["metric_type"])
    assert metrics == {"REFGROUT", "TOTIMPSB", "TOTDEMO", "CLOSTLV"}


def test_parse_products(parsed: pd.DataFrame):
    assert set(parsed["product_native"]) == set(STORED_PRODUCTS)


def test_totdemo_march_2026(parsed: pd.DataFrame):
    gas = parsed[
        (parsed["metric_type"] == "TOTDEMO")
        & (parsed["product_native"] == "Motor gasoline")
        & (parsed["date"] == pd.Timestamp("2026-03-01"))
    ]
    assert len(gas) == 1
    # Close to JODI PL TOTDEMO (~513 kt) for Mar 2026.
    assert 450 <= float(gas.iloc[0]["value"]) <= 550


def test_scraper_finalize(raw_path: Path):
    from scrapers.poland_are import PolandAreScraper

    path = raw_path
    if not os.access(raw_path, os.R_OK):
        path = Path(os.environ["TEMP"]) / "Biuletyn_marzec_2026.xls"
        shutil.copy2(raw_path, path)

    df = PolandAreScraper(data_dir=PROJECT_ROOT / "data").parse("liquid_fuels", path)
    assert df["unit"].eq(ARE_UNIT_NATIVE).all()
    assert df["country"].eq("PL").all()
    assert df["is_provisional"].all()


def test_demand_canonical_panels():
    from reference.poland import build_demand_canonical, build_demand_jodi_rollup

    df = pd.read_parquet(
        PROJECT_ROOT / "data" / "processed" / "poland" / "poland_are_liquid_fuels.parquet"
    )
    demand = df[df["metric_type"] == "TOTDEMO"].copy()
    canon = build_demand_canonical(demand, value_col="value")
    assert set(canon["panel"]) == {"Gasoline", "Diesel", "Gasoil", "Fuel oil", "LPG"}

    jodi = build_demand_jodi_rollup(canon, value_col="value")
    assert set(jodi["panel"]) == {"Gasoline", "Gas/diesel oil", "Fuel oil", "LPG"}
    # GASDIES composite equals Diesel + Gasoil on a sample month.
    sample = pd.Timestamp("2026-03-01")
    diesel = canon.loc[
        (canon["date"] == sample) & (canon["panel"] == "Diesel"), "value"
    ].sum()
    gasoil = canon.loc[
        (canon["date"] == sample) & (canon["panel"] == "Gasoil"), "value"
    ].sum()
    gasdies = jodi.loc[
        (jodi["date"] == sample) & (jodi["panel"] == "Gas/diesel oil"), "value"
    ].iloc[0]
    assert abs(gasdies - (diesel + gasoil)) < 0.01
