"""Tests for Petronet download parsing and Korea raw CSV coverage."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reference.korea import (  # noqa: E402
    CONSUMPTION_DATASET,
    JODI_COMPARE_SERIES,
    SEASONALITY_NATIVE_PRODUCTS,
    STOCKS_DATASET,
    _parse_month_cell,
    audit_raw_csv,
    find_stitched_gaps,
    parse_bundle_filename,
    parse_korea_consumption_csv,
    parse_korea_csv_files,
    parse_korea_directory,
    parse_korea_wide_csv,
)
from reference.petronet_knoc import (  # noqa: E402
    DateRange,
    csv_filename,
    html_table_to_wide_csv,
)

FIXTURES = Path(__file__).parent / "fixtures"
RAW = ROOT / "data" / "raw" / "korea"


class TestPetronetHtmlParser:
    def test_html_table_to_csv(self) -> None:
        html = (FIXTURES / "petronet_table_snippet.html").read_text(encoding="utf-8")
        csv_text = html_table_to_wide_csv(html)
        assert "Month,Product Name,gasoline" in csv_text
        assert "24년 01월" in csv_text
        assert "[16.00]" in csv_text

    def test_stocks_html_table_to_csv(self) -> None:
        html = (FIXTURES / "petronet_stocks_table_snippet.html").read_text(
            encoding="utf-8"
        )
        csv_text = html_table_to_wide_csv(html, layout="stocks")
        assert csv_text.startswith("월,제품명,휘발유")
        assert "26년 01월" in csv_text
        assert "5,756" in csv_text or "5756" in csv_text
        assert "평균" not in csv_text

    def test_parsed_months_carry_year(self) -> None:
        html = (FIXTURES / "petronet_table_snippet.html").read_text(encoding="utf-8")
        tmp = ROOT / "data" / "raw" / "korea" / "_test_snippet.csv"
        tmp.write_text(html_table_to_wide_csv(html), encoding="utf-8-sig")
        try:
            df = parse_korea_wide_csv(tmp)
            months = sorted(pd.to_datetime(df["date"]).dt.strftime("%Y-%m").unique())
            assert months == ["2024-01", "2024-02"]
            gas_jan = df[
                (df["date"] == "2024-01-01") & (df["product_native"] == "gasoline")
            ]["value"].iloc[0]
            assert gas_jan == pytest.approx(8008.0)
        finally:
            if tmp.exists():
                tmp.unlink()

    def test_csv_filename(self) -> None:
        dr = DateRange(date(2016, 3, 1), date(2018, 12, 1))
        assert csv_filename(dr) == "제품별소비(201603-201812).csv"

    def test_stocks_csv_filename(self) -> None:
        dr = DateRange(date(2024, 4, 1), date(2026, 4, 1))
        assert (
            csv_filename(dr, bundle_prefix=STOCKS_DATASET.bundle_prefix)
            == "석유제품재고(202404-202604).csv"
        )


class TestKoreaMonthParsing:
    def test_ko_month_only_with_carry(self) -> None:
        ts, year = _parse_month_cell("02월", carry_year=2017)
        assert year == 2017
        assert ts == pd.Timestamp("2017-02-01")

    def test_ko_month_with_year(self) -> None:
        ts, year = _parse_month_cell("16년 01월", carry_year=None)
        assert year == 2016
        assert ts == pd.Timestamp("2016-01-01")


class TestRawCsvCoverage:
    def test_truncated_bundle_detected_on_fixture(self, tmp_path: Path) -> None:
        # Simulates a bad manual export named 2014-2018 but only two months inside.
        path = tmp_path / "제품별소비(201401-201812).csv"
        path.write_text(
            (FIXTURES / "truncated_bundle.csv").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        info = audit_raw_csv(path)
        assert info["truncated"] is True
        assert info["month_count"] < info["expected_month_count"]
        missing = info.get("missing_months") or []
        assert "2016-03" in missing
        assert "2018-12" in missing

    def test_repaired_2014_bundle_if_present(self) -> None:
        path = RAW / "제품별소비(201401-201812).csv"
        if not path.exists():
            pytest.skip("raw bundle not present")
        info = audit_raw_csv(path)
        assert info["truncated"] is False
        assert info["month_count"] == info["expected_month_count"] == 60

    def test_bundle_filename_span(self) -> None:
        path = RAW / "제품별소비(201401-201812).csv"
        if not path.exists():
            path = FIXTURES / "truncated_bundle.csv"
        span = parse_bundle_filename(path.parent / "제품별소비(201401-201812).csv")
        assert span is not None
        assert span[0] == pd.Timestamp("2014-01-01")
        assert span[1] == pd.Timestamp("2018-12-01")


@pytest.mark.integration
class TestPetronetLive:
    def test_jan_2024_gasoline_matches_manual(self) -> None:
        manual = RAW / "제품별소비(202201-202604).csv"
        if not manual.exists():
            pytest.skip("manual bundle not present")
        ref = parse_korea_consumption_csv(manual)
        ref_val = ref[
            (ref["date"] == "2024-01-01") & (ref["product_native"] == "gasoline")
        ]["value"].iloc[0]

        from reference.petronet_knoc import default_session, fetch_table_html, open_menu

        dr = DateRange(date(2024, 1, 1), date(2024, 1, 1))
        session = default_session()
        open_menu(session)
        html = fetch_table_html(session, dr)
        tmp = RAW / "_pytest_live_202401.csv"
        tmp.write_text(html_table_to_wide_csv(html), encoding="utf-8-sig")
        try:
            got = parse_korea_consumption_csv(tmp)
            live_val = got[
                (got["date"] == "2024-01-01") & (got["product_native"] == "gasoline")
            ]["value"].iloc[0]
            assert live_val == pytest.approx(ref_val)
        finally:
            if tmp.exists():
                tmp.unlink()

    def test_stocks_jan_may_2026_matches_manual(self) -> None:
        manual = RAW / "stocks" / "석유제품재고(202605).csv"
        if not manual.exists():
            pytest.skip("manual stocks bundle not present")
        ref = parse_korea_wide_csv(manual)
        ref_feb_gas = ref[
            (ref["date"] == "2026-02-01") & (ref["product_native"] == "gasoline")
        ]["value"].iloc[0]

        from reference.petronet_knoc import (
            STOCKS_PETRONET,
            default_session,
            fetch_table_html,
            open_menu,
        )

        dr = DateRange(date(2026, 1, 1), date(2026, 5, 1))
        session = default_session()
        open_menu(session, menu_ids=STOCKS_PETRONET.menu_ids)
        html = fetch_table_html(session, dr, config=STOCKS_PETRONET)
        csv_text = html_table_to_wide_csv(html, layout="stocks")
        tmp = RAW / "stocks" / "_pytest_live_stocks_202601-202605.csv"
        tmp.write_text(csv_text, encoding="utf-8-sig")
        try:
            got = parse_korea_wide_csv(tmp)
            live_feb_gas = got[
                (got["date"] == "2026-02-01") & (got["product_native"] == "gasoline")
            ]["value"].iloc[0]
            assert live_feb_gas == pytest.approx(ref_feb_gas)
        finally:
            if tmp.exists():
                tmp.unlink()


class TestNaphthaPanels:
    def test_jodi_compare_includes_naphtha(self) -> None:
        assert "naphtha" in JODI_COMPARE_SERIES
        assert JODI_COMPARE_SERIES["naphtha"].jodi_energy_product == "NAPHTHA"

    def test_seasonality_native_includes_naphtha(self) -> None:
        assert "naphtha" in SEASONALITY_NATIVE_PRODUCTS


class TestStocksBundles:
    def test_stocks_directory_parses_if_present(self) -> None:
        stocks_dir = RAW / "stocks"
        bundle = stocks_dir / "석유제품재고(202404-202604).csv"
        if not bundle.exists():
            pytest.skip("stocks bundle not present")
        df = parse_korea_directory(stocks_dir, dataset=STOCKS_DATASET)
        feb = df[
            (df["date"] == "2026-02-01") & (df["product_native"] == "gasoline")
        ]
        assert len(feb) == 1
        assert feb["value"].iloc[0] == pytest.approx(5096.0)


class TestIncrementalParse:
    def test_single_file_matches_directory_subset(self) -> None:
        bundle = RAW / "제품별소비(202201-202604).csv"
        if not bundle.exists():
            pytest.skip("bundle not present")
        full = parse_korea_directory(RAW, dataset=CONSUMPTION_DATASET)
        partial = parse_korea_csv_files([bundle], dataset=CONSUMPTION_DATASET)
        assert len(partial) < len(full)
        merged = full.merge(
            partial,
            on=["date", "product_native"],
            suffixes=("_full", "_partial"),
        )
        assert (merged["value_full"] == merged["value_partial"]).all()


def test_find_stitched_gap_2016_2018() -> None:
    """Sanity: gap list includes Mar 2016 when only Jan-Feb 2016 exist."""
    idx = pd.to_datetime(["2016-01-01", "2016-02-01", "2019-01-01"])
    df = pd.DataFrame(
        {
            "date": list(idx) * 2,
            "product_native": ["gasoline", "diesel"] * 3,
            "value": [1.0] * 6,
        }
    )
    gaps = find_stitched_gaps(df, start="2016-01", end="2019-02")
    assert "2016-03" in gaps
    assert "2018-12" in gaps
    assert "2019-02" in gaps
