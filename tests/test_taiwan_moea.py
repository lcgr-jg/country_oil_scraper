"""Tests for Taiwan MOEA Table 5-04 parser."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reference.taiwan import (  # noqa: E402
    DELIVERY_HEADLINE_NATIVE,
    parse_moea_consumption_workbook,
)
from scrapers.taiwan_moea import TaiwanMoeaScraper, discover_consumption_xlsx_path  # noqa: E402

RAW_LEGACY = ROOT / "data" / "raw" / "Taiwan" / "m_5-04石油產品消費(11504)_v113.xlsx"
RAW_LOWER = ROOT / "data" / "raw" / "taiwan"


def _workbook_path() -> Path:
    if RAW_LEGACY.exists():
        return RAW_LEGACY
    matches = list(RAW_LOWER.glob("m_5-04*.xlsx"))
    if matches:
        return max(matches, key=lambda p: p.stat().st_mtime)
    pytest.skip("No Taiwan 5-04 workbook in data/raw/")


class TestTaiwanParser:
    def test_parses_products_and_date_range(self) -> None:
        path = _workbook_path()
        df = parse_moea_consumption_workbook(path)
        assert not df.empty
        assert set(df["product_native"].unique()) == set(DELIVERY_HEADLINE_NATIVE)
        assert df["date"].min() == pd.Timestamp("2007-01-01")
        assert df["date"].max() >= pd.Timestamp("2026-04-01")

    def test_monthly_2025_not_provisional(self) -> None:
        path = _workbook_path()
        df = parse_moea_consumption_workbook(path)
        jan = df[(df["date"] == "2025-01-01") & (df["product_native"] == "gasoline")]
        assert len(jan) == 1
        assert not bool(jan["is_provisional"].iloc[0])

    def test_annual_imputed_is_provisional(self) -> None:
        path = _workbook_path()
        df = parse_moea_consumption_workbook(path)
        old = df[df["date"] == "2010-06-01"]
        assert old["is_provisional"].all()

    def test_scraper_finalize_columns(self) -> None:
        path = _workbook_path()
        scraper = TaiwanMoeaScraper(data_dir=str(ROOT / "data"))
        out = scraper.parse("petroleum_consumption", path)
        assert out["country"].iloc[0] == "TW"
        assert out["unit"].iloc[0] == "ktoe"
        assert out["metric_type"].iloc[0] == "TOTDEMO"


class TestTaiwanDownloadDiscovery:
    def test_discover_from_monthly_api_json(self) -> None:
        # Mirrors /api/pages/en/newest/monthly → tabs.Oil.attachment
        payload = {
            "tabs": {
                "Oil": {
                    "attachment": [
                        {
                            "level": 1,
                            "title": "5-03 Petroleum Products Supply and Transformation",
                            "formats": {
                                "excel": "/api/files/m_5-03石油產品供給與轉變(11505)_v113.xlsx"
                            },
                        },
                        {
                            "level": 1,
                            "title": "5-04 Petroleum Products Consumption",
                            "formats": {
                                "excel": "/api/files/m_5-04石油產品消費(11505)_v113.xlsx"
                            },
                            "names": {
                                "excel": "5-04 Petroleum Products Consumption(202605).xlsx"
                            },
                        },
                    ]
                }
            }
        }
        name = discover_consumption_xlsx_path(payload)
        assert name.startswith("m_5-04")
        assert name.endswith(".xlsx")

    def test_discover_from_legacy_embedded_string(self) -> None:
        # Regex fallback for old HTML / serialized embeds
        html = (
            '"excel":"/api/files/m_5-04石油產品消費(11504)_v113.xlsx",'
            '"names":{"excel":"5-04 Petroleum Products Consumption(202604).xlsx"}'
        )
        assert discover_consumption_xlsx_path(html).endswith(".xlsx")
