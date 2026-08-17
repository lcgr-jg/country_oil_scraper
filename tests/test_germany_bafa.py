"""Tests for Germany BAFA Mineralöldaten parsers (offline fixtures)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from reference.germany import (
    BAFA_AGENCY_SOURCE,
    BAFA_BIO_METRIC,
    BAFA_DEMAND_METRIC,
    BAFA_STOCKS_METRIC,
    MonthFile,
    normalize_product_native,
    parse_month_file,
    year_month_from_filename,
)
from reference.loaders import load_product_map
from scrapers.germany_bafa import GermanyBafaScraper

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROBE_DIR = PROJECT_ROOT / "data" / "raw" / "germany" / "probe"

XLSX_2020_06 = PROBE_DIR / "moel_amtliche_daten_2020_06.xlsx"
PDF_2025_08 = PROBE_DIR / "moel_amtliche_daten_2025_08.pdf"
PDF_2026_04 = PROBE_DIR / "moel_amtliche_daten_2026_04.pdf"


def _require(path: Path) -> Path:
    if not path.exists():
        pytest.skip(f"Fixture missing: {path}")
    return path


def test_product_map_has_bafa_rows():
    pm = load_product_map()
    bafa = pm[pm["Source"] == BAFA_AGENCY_SOURCE]
    assert len(bafa) >= 20
    assert "Dieselkraftstoff" in set(bafa["Product_name"])
    assert "Ottokraftstoff" in set(bafa["Product_name"])


def test_normalize_aliases():
    assert (
        normalize_product_native("Flugturb.Kraftst.,schwer und andere Leuchtöle")
        == "Flugturb.Kraftst.,schwer"
    )
    assert normalize_product_native("Biodiesel (FAME), HVO, BTL und andere") == (
        "Biodiesel (FAME), HVO, BTL"
    )


def test_year_month_from_filename():
    assert year_month_from_filename(Path("moel_amtliche_daten_2026_04.pdf")) == (
        2026,
        4,
    )
    assert year_month_from_filename(Path("moel_amtliche_daten_2020_06.xlsx")) == (
        2020,
        6,
    )


def test_parse_xlsx_2020_06_has_demand_stocks_bio():
    path = _require(XLSX_2020_06)
    df = parse_month_file(MonthFile(path, "xlsx", 2020, 6))
    metrics = set(df["metric_type"])
    assert metrics == {BAFA_DEMAND_METRIC, BAFA_STOCKS_METRIC, BAFA_BIO_METRIC}

    diesel = df[
        (df["metric_type"] == BAFA_DEMAND_METRIC)
        & (df["product_native"] == "Dieselkraftstoff")
    ]
    assert len(diesel) == 1
    assert diesel.iloc[0]["value"] == pytest.approx(2812365.0)

    bio = df[df["metric_type"] == BAFA_BIO_METRIC]
    assert "Bioethanol" in set(bio["product_native"])
    assert "Biodiesel (FAME), HVO, BTL" in set(bio["product_native"])


def test_parse_pdf_2025_08_hvo_fame_split():
    path = _require(PDF_2025_08)
    df = parse_month_file(MonthFile(path, "pdf", 2025, 8))
    bio = df[df["metric_type"] == BAFA_BIO_METRIC].set_index("product_native")["value"]
    assert "davon HVO" in bio.index
    assert "davon FAME" in bio.index
    assert bio["davon HVO"] == pytest.approx(9140.0)
    assert bio["davon FAME"] == pytest.approx(169781.0)

    diesel = df[
        (df["metric_type"] == BAFA_DEMAND_METRIC)
        & (df["product_native"] == "Dieselkraftstoff")
    ]
    assert diesel.iloc[0]["value"] == pytest.approx(2814181.0)


def test_parse_pdf_2026_04_available():
    path = _require(PDF_2026_04)
    df = parse_month_file(MonthFile(path, "pdf", 2026, 4))
    assert not df.empty
    assert BAFA_DEMAND_METRIC in set(df["metric_type"])
    diesel = df[
        (df["metric_type"] == BAFA_DEMAND_METRIC)
        & (df["product_native"] == "Dieselkraftstoff")
    ]
    assert len(diesel) == 1
    assert diesel.iloc[0]["value"] > 0


def test_scraper_parse_finalizes_columns():
    path = _require(XLSX_2020_06)
    scraper = GermanyBafaScraper(data_dir=PROJECT_ROOT / "data")
    df = scraper.parse("amtliche_mineraloeldaten", path)
    for col in (
        "date",
        "country",
        "source",
        "metric_type",
        "product_native",
        "value",
        "unit",
        "is_provisional",
    ):
        assert col in df.columns
    assert df["country"].iloc[0] == "DE"
    assert (df["date"] == pd.Timestamp("2020-06-01")).all()
