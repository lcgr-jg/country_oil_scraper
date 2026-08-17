"""Tests for Japan METI parser and discovery helpers."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from reference.japan import (
    DELIVERY_HEADLINE_NATIVE,
    JODI_COMPARE_SERIES,
    heisei_to_gregorian_year,
    is_meti_primary,
    parse_kakuhou_filename,
    parse_meti_kakuhou_workbook,
    parse_meti_paths,
    parse_meti_sokuhou_workbook,
    parse_meti_yearbook_workbook,
    parse_period_label,
    reiwa_to_gregorian_year,
)
from reference.loaders import canonical_subcategory
from scrapers.japan_meti import (
    discover_kakuhou_links,
    discover_sokuhou_english_link,
    discover_sokuhou_link,
    discover_yearbook_links,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
PROBE = Path(__file__).resolve().parents[1] / "data" / "raw" / "japan" / "_probe"


@pytest.fixture
def kakuhou_path() -> Path:
    p = PROBE / "se202603kakji.xlsx"
    if not p.exists():
        pytest.skip("probe xlsx missing — run scripts/_probe_meti.py once")
    return p


@pytest.fixture
def sokuhou_path() -> Path:
    p = PROBE / "h2j581011j.xlsx"
    if not p.exists():
        pytest.skip("probe sokuhou xlsx missing")
    return p


@pytest.fixture
def sokuhou_english_path() -> Path:
    p = PROBE / "english_h2j581011.xlsx"
    if not p.exists():
        pytest.skip("probe English sokuhou xlsx missing")
    return p


def test_reiwa_year() -> None:
    assert reiwa_to_gregorian_year(7) == 2025
    assert reiwa_to_gregorian_year(8) == 2026


def test_meti_product_map_native_keys() -> None:
    """product_map Product_name must match parser product_native keys."""
    for native in DELIVERY_HEADLINE_NATIVE:
        assert canonical_subcategory(native, "METI") is not None
    assert canonical_subcategory("gas_oil", "METI") == "Diesel"
    assert canonical_subcategory("fuel_oil_a", "METI") == "Gasoil"
    assert canonical_subcategory("fuel_oil_bc", "METI") == "Fuel Oil"
    assert is_meti_primary("gas_oil")
    assert is_meti_primary("fuel_oil_a")
    assert is_meti_primary("fuel_oil_bc")
    assert JODI_COMPARE_SERIES["fuel_oil"].natives == frozenset({"fuel_oil_bc"})
    assert JODI_COMPARE_SERIES["gas_diesel"].natives == frozenset(
        {"gas_oil", "fuel_oil_a"}
    )
    assert JODI_COMPARE_SERIES["gas_diesel"].jodi_energy_product == "GASDIES"


def test_heisei_year() -> None:
    assert heisei_to_gregorian_year(29) == 2017


@pytest.fixture
def yearbook_2023_path() -> Path:
    p = PROBE / "h2dhhpe2023k.xlsx"
    if not p.exists():
        pytest.skip("yearbook probe xlsx missing")
    return p


@pytest.fixture
def yearbook_2021_path() -> Path:
    p = PROBE / "h2dhhpe2021k.xlsx"
    if not p.exists():
        pytest.skip("yearbook 2021 probe xlsx missing")
    return p


def test_parse_period_label_month_only() -> None:
    ts, ry = parse_period_label("　　２　", reiwa_year=7)
    assert ry == 7
    assert ts == pd.Timestamp(2025, 2, 1)


def test_parse_period_label_reiwa8_without_month_char() -> None:
    """確報 first month of a Reiwa year is often 令和８年　１ without 月."""
    ts, ry = parse_period_label("令和８年　１")
    assert ry == 8
    assert ts == pd.Timestamp(2026, 1, 1)
    ts2, ry2 = parse_period_label("　　２　", reiwa_year=ry)
    assert ry2 == 8
    assert ts2 == pd.Timestamp(2026, 2, 1)


def test_parse_kakuhou_filename() -> None:
    assert parse_kakuhou_filename(Path("se202603kakji.xlsx")) == pd.Timestamp(2026, 3, 1)


def test_kakuhou_workbook_products(kakuhou_path: Path) -> None:
    df = parse_meti_kakuhou_workbook(kakuhou_path)
    assert len(df) > 100
    assert "naphtha" in df["product_native"].values
    assert "jet_fuel" in df["product_native"].values
    assert df["unit"].isin(["kL", "t"]).all()
    assert set(df["metric_type"]) == {
        "INDPROD",
        "TOTIMPSB",
        "TOTDEMO",
        "TOTEXPSB",
        "CLOSTLV",
    }


def test_kakuhou_workbook_inventory_gasoline_feb2026(kakuhou_path: Path) -> None:
    df = parse_meti_kakuhou_workbook(kakuhou_path)
    row = df[
        (df["product_native"] == "gasoline")
        & (df["metric_type"] == "CLOSTLV")
        & (df["date"] == "2026-02-01")
    ]
    assert len(row) == 1
    assert row["value"].iloc[0] > 1_000_000


def test_kakuhou_workbook_includes_reiwa8_months(kakuhou_path: Path) -> None:
    """se202603 must emit 2026-01..03 domestic sales, not stop at 2025-12."""
    df = parse_meti_kakuhou_workbook(kakuhou_path)
    gas = df[
        (df["product_native"] == "gasoline") & (df["metric_type"] == "TOTDEMO")
    ].sort_values("date")
    assert gas["date"].max() == pd.Timestamp(2026, 3, 1)
    jan = gas[gas["date"] == "2026-01-01"]
    assert len(jan) == 1
    assert jan["value"].iloc[0] > 1_000_000


def test_sokuhou_workbook(sokuhou_path: Path) -> None:
    df = parse_meti_sokuhou_workbook(sokuhou_path)
    assert set(df["metric_type"]) >= {"TOTDEMO", "CLOSTLV", "INDPROD"}
    demo = df[df["metric_type"] == "TOTDEMO"]
    assert len(demo) >= 9
    assert demo["date"].iloc[0] == pd.Timestamp(2026, 3, 1)
    assert set(demo["product_native"]) <= set(DELIVERY_HEADLINE_NATIVE)


def test_sokuhou_english_april_supply_overview(sokuhou_english_path: Path) -> None:
    df = parse_meti_sokuhou_workbook(sokuhou_english_path)
    assert df["date"].nunique() == 1
    assert df["date"].iloc[0] == pd.Timestamp(2026, 4, 1)
    gas_inv = df[
        (df["product_native"] == "gasoline") & (df["metric_type"] == "CLOSTLV")
    ]
    assert len(gas_inv) == 1
    assert gas_inv["value"].iloc[0] > 1_000_000


def test_discover_sokuhou_english_link() -> None:
    html = '<a href="../sekiyuso/excel/h2j581011e.xlsx">Excel</a>'
    assert discover_sokuhou_english_link(html) == "h2j581011e.xlsx"


def test_stitch_provisional_loses_to_final(
    kakuhou_path: Path, sokuhou_path: Path
) -> None:
    df = parse_meti_paths([sokuhou_path, kakuhou_path])
    dec = df[
        (df["date"] == "2025-12-01")
        & (df["product_native"] == "gasoline")
        & (df["metric_type"] == "TOTDEMO")
    ]
    assert len(dec) == 1
    assert not bool(dec["is_provisional"].iloc[0])


def test_discover_kakuhou_links() -> None:
    html = '<a href="xls/se202501kakji.xlsx">a</a><a href="xls/se202602kakji.xlsx">b</a>'
    links = discover_kakuhou_links(html)
    assert [y for _, y in links] == ["202501", "202602"]


def test_discover_sokuhou_link() -> None:
    html = '<a href="result/xls/h2j581011j.xlsx">x</a>'
    assert discover_sokuhou_link(html) == "h2j581011j.xlsx"


def test_discover_yearbook_links() -> None:
    html = (
        '<a href="xls/h2dhhpe2022k.xlsx">a</a>'
        '<a href="xls/h2dhhpe2024k.xlsx">b</a>'
    )
    links = discover_yearbook_links(html)
    assert [y for _, y in links] == ["2022", "2024"]


def test_yearbook_workbook_monthly(yearbook_2023_path: Path) -> None:
    df = parse_meti_yearbook_workbook(yearbook_2023_path)
    assert len(df) >= 12 * 10
    jan = df[(df["date"] == "2023-01-01") & (df["product_native"] == "gasoline")]
    assert len(jan) == 1
    assert jan["value"].iloc[0] > 1_000_000


def test_yearbook_2021_reiwa_months(yearbook_2021_path: Path) -> None:
    df = parse_meti_yearbook_workbook(yearbook_2021_path)
    dec = df[(df["date"] == "2021-12-01") & (df["product_native"] == "naphtha")]
    assert len(dec) == 1


def test_yearbook_skips_annual_summary_rows(yearbook_2023_path: Path) -> None:
    """CY/FY total rows must not be parsed as single months (e.g. F.Y. 2023 → May)."""
    df = parse_meti_yearbook_workbook(yearbook_2023_path)
    may22 = df[
        (df["date"] == "2022-05-01") & (df["product_native"] == "gasoline")
    ]
    assert len(may22) == 0 or may22["value"].iloc[0] < 10_000_000


def test_yearbook_no_fy_as_month() -> None:
    paths = sorted(PROBE.glob("h2dhhpe20*k.xlsx"))
    if len(paths) < 3:
        pytest.skip("need yearbook probe files")
    df = parse_meti_paths(paths)
    g = df[df["product_native"] == "gasoline"].copy()
    for d in ["2021-04-01", "2022-05-01", "2023-06-01"]:
        row = g[g["date"] == d]
        if len(row):
            assert row["value"].iloc[0] < 10_000_000, f"{d} looks like annual total"


def test_kakuhou_beats_yearbook_on_overlap() -> None:
    """確報 monthly file must win over 年報 for the same calendar month."""
    yb = PROBE / "h2dhhpe2023k.xlsx"
    kak = PROBE / "se202603kakji.xlsx"
    if not yb.exists() or not kak.exists():
        pytest.skip("need yearbook + kakuhou probe files")
    df = parse_meti_paths([yb, kak])
    row = df[
        (df["date"] == "2025-06-01")
        & (df["product_native"] == "gasoline")
        & (df["metric_type"] == "TOTDEMO")
    ]
    assert len(row) == 1
    assert "kakji" in row["source_file"].iloc[0]


def test_yearbook_legacy_xls_2007() -> None:
    p = PROBE.parent / "yearbook" / "h2dhhpe2007k.xls"
    if not p.exists():
        pytest.skip("h2dhhpe2007k.xls not in data/raw/japan/yearbook")
    df = parse_meti_yearbook_workbook(p)
    assert len(df) >= 12 * 10
    jan = df[(df["date"] == "2007-01-01") & (df["product_native"] == "gasoline")]
    assert len(jan) == 1
    assert jan["value"].iloc[0] > 1_000_000


def test_discover_yearbook_includes_xls() -> None:
    from reference.japan import discover_yearbook_paths

    paths = discover_yearbook_paths(PROBE.parent)
    names = {p.name for p in paths}
    if (PROBE.parent / "yearbook" / "h2dhhpe2007k.xls").exists():
        assert "h2dhhpe2007k.xls" in names
    assert any(n.endswith(".xlsx") for n in names)


def test_yearbook_stitch_range() -> None:
    from reference.japan import discover_yearbook_paths

    raw = PROBE.parent
    paths = discover_yearbook_paths(raw)
    if len(paths) < 3:
        pytest.skip("need multiple yearbook files under data/raw/japan/yearbook")
    df = parse_meti_paths(paths)
    assert df["date"].min() <= pd.Timestamp("2007-01-01")
    assert df["date"].max() >= pd.Timestamp("2024-01-01")
    assert df["date"].nunique() >= 60
