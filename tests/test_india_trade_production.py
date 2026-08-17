"""Tests for PPAC India trade/production parsers."""

from pathlib import Path

import pytest

from reference.india import (
    load_ppac_production_from_dir,
    load_ppac_trade_from_dirs,
    parse_pt_trade_workbook,
)

ROOT = Path(__file__).resolve().parents[1]
TRADE_DIR = ROOT / "data/raw/india/trade"
PROD_DIR = ROOT / "data/raw/india/production"

TRADE_CURR = TRADE_DIR / "1779375298_PT_import.xls"
TRADE_HIST = TRADE_DIR / "1751964547_PT_IMPORT_TMT_H.xlsx"
PROD_HIST = PROD_DIR / "1761642701_PT_production_product_H.xls"


@pytest.mark.skipif(not TRADE_CURR.exists(), reason="trade file not in workspace")
def test_trade_current_has_imports_and_exports() -> None:
    df = parse_pt_trade_workbook(TRADE_CURR)
    flows = set(df["trade_flow"])
    assert flows == {"imports", "exports"}
    assert (df["value_000mt"] > 0).any()
    # HSD product import exists in recent FY
    hsd = df[(df["product"] == "HSD") & (df["trade_flow"] == "imports")]
    assert len(hsd) >= 6


@pytest.mark.skipif(not TRADE_HIST.exists(), reason="historical trade not present")
def test_trade_historical_monthly_sheets() -> None:
    import pandas as pd

    df = parse_pt_trade_workbook(TRADE_HIST)
    assert pd.Timestamp(df["date"].min()) <= pd.Timestamp("2015-04-01")
    assert len(df) > 1000


@pytest.mark.skipif(not PROD_HIST.exists(), reason="production file not present")
def test_production_aggregates_ms_hsd() -> None:
    import pandas as pd

    df = load_ppac_production_from_dir(PROD_DIR)
    assert "MS" in set(df["product"])
    assert "HSD" in set(df["product"])
    assert "FO & LSHS" in set(df["product"])
    assert df["metric_type"].eq("REFGROUT").all()


TRADE_PDF = TRADE_DIR / "1779378989_PT_import.pdf"
PROD_PDF = PROD_DIR / "1779779011_PT_POL_production_current.pdf"


@pytest.mark.skipif(not TRADE_PDF.exists(), reason="trade PDF not present")
def test_closing_stocks_summary_since_feb() -> None:
    from analytics.india_inventory import (
        build_closing_stocks_summary,
        build_probe_tables,
    )

    tables = build_probe_tables(ROOT)
    out = build_closing_stocks_summary(tables["jodi_wide"], anchor="2026-02")
    assert "Diesel" in str(out["summary"].index)
    assert out["grand_change_kt"] == -417.0


@pytest.mark.skipif(not TRADE_PDF.exists(), reason="trade PDF not present")
def test_april_implied_inventory_headline() -> None:
    from analytics.india_inventory import build_april_implied_inventory

    out = build_april_implied_inventory(ROOT, period="2026-04")
    h = out["headline"].iloc[0]
    assert h["demand_kt"] > 10000
    assert h["refgrout_kt"] > 10000
    assert out["by_jodi_product"].shape[0] >= 6


@pytest.mark.skipif(
    not (TRADE_HIST.exists() and PROD_HIST.exists()),
    reason="raw india files missing",
)
def test_load_trade_upsert_includes_2026() -> None:
    import pandas as pd

    df = load_ppac_trade_from_dirs(TRADE_DIR)
    assert pd.Timestamp("2026-03-01") in set(pd.to_datetime(df["date"]))
