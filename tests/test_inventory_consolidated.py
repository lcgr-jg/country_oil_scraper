"""Tests for analytics.inventory_consolidated."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from analytics.inventory_consolidated import (
    build_consolidated_inventory,
    inventory_levels_table,
    load_inventory_sources,
    normalize_product_canonical,
    save_consolidated_csv,
    ytd_month_starts,
)


def _write_korea_fixture(processed: Path) -> None:
    out_dir = processed / "korea"
    out_dir.mkdir(parents=True)
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01", "2026-02-01", "2026-03-01"]),
            "country": ["KR", "KR", "KR"],
            "country_name": ["Korea (the Republic of)", "Korea (the Republic of)", "Korea (the Republic of)"],
            "source": ["korea_petroleum_stocks"] * 3,
            "metric_type": ["CLOSTLV"] * 3,
            "product_native": ["lpg", "lpg", "lpg"],
            "product": ["lpg", "lpg", "lpg"],
            "value": [1000.0, 1500.0, 1200.0],
            "unit": ["kb", "kb", "kb"],
            "is_provisional": [False] * 3,
            "source_file": ["test.csv"] * 3,
            "updated_at": pd.to_datetime(["2026-06-01"] * 3),
            "product_canonical": ["LPG", "LPG", "LPG"],
            "category": ["LPG", "LPG", "LPG"],
        }
    )
    df.to_parquet(out_dir / "korea_knoc.parquet", index=False)


def _registry_csv(tmp_path: Path) -> Path:
    text = """country_key,display_name,parquet_subdir,parquet_filename,metric_type,sort_order,notes
italy,Italy,italy,italy_mase_consumption.parquet,CLOSTLV,10,
korea,Korea,korea,korea_knoc.parquet,CLOSTLV,30,
"""
    path = tmp_path / "inventory_sources.csv"
    path.write_text(text, encoding="utf-8")
    return path


class TestYtdMonthStarts:
    def test_current_year_truncates_to_as_of(self) -> None:
        months = ytd_month_starts(2026, as_of=date(2026, 5, 15))
        assert len(months) == 5
        assert months[0] == pd.Timestamp("2026-01-01")
        assert months[-1] == pd.Timestamp("2026-05-01")

    def test_past_year_is_full_calendar(self) -> None:
        months = ytd_month_starts(2025, as_of=date(2026, 5, 15))
        assert len(months) == 12


class TestBuildConsolidated:
    def test_korea_lpg_rows_and_missing_country(self, tmp_path: Path) -> None:
        processed = tmp_path / "processed"
        _write_korea_fixture(processed)
        registry = _registry_csv(tmp_path)

        out = build_consolidated_inventory(
            processed_dir=processed,
            sources_csv=registry,
            year=2026,
            product_canonical="LPG",
        )
        assert len(out) == 3
        assert set(out["country"]) == {"Korea"}
        assert out["value_kb"].tolist() == pytest.approx([1000.0, 1500.0, 1200.0], rel=1e-6)


class TestInventoryLevelsTable:
    def test_pivot_with_na_for_missing_country(self, tmp_path: Path) -> None:
        processed = tmp_path / "processed"
        _write_korea_fixture(processed)
        registry = _registry_csv(tmp_path)
        consolidated = build_consolidated_inventory(
            processed_dir=processed,
            sources_csv=registry,
            year=2026,
        )

        table = inventory_levels_table(
            consolidated,
            product_canonical="LPG",
            year=2026,
            target_unit="kb",
            as_of=date(2026, 3, 31),
            missing_label="N/a",
            sources_csv=registry,
        )
        assert list(table.index) == ["Italy", "Korea"]
        assert table.loc["Korea", "Jan"] == pytest.approx(1000.0)
        assert table.loc["Italy", "Jan"] == "N/a"

    def test_include_total_sums_reporting_countries(self, tmp_path: Path) -> None:
        processed = tmp_path / "processed"
        _write_korea_fixture(processed)
        registry = _registry_csv(tmp_path)
        consolidated = build_consolidated_inventory(
            processed_dir=processed,
            sources_csv=registry,
            year=2026,
        )

        table = inventory_levels_table(
            consolidated,
            product_canonical="LPG",
            year=2026,
            target_unit="kb",
            as_of=date(2026, 3, 31),
            include_total=True,
            missing_label=None,
            sources_csv=registry,
        )
        assert list(table.index[-1:]) == ["Total"]
        assert table.loc["Total", "Jan"] == pytest.approx(1000.0)
        assert table.loc["Total", "Feb"] == pytest.approx(1500.0)
        assert table.loc["Total", "Mar"] == pytest.approx(1200.0)

    def test_include_total_false_omits_row(self, tmp_path: Path) -> None:
        processed = tmp_path / "processed"
        _write_korea_fixture(processed)
        registry = _registry_csv(tmp_path)
        consolidated = build_consolidated_inventory(
            processed_dir=processed,
            sources_csv=registry,
            year=2026,
        )
        table = inventory_levels_table(
            consolidated,
            product_canonical="LPG",
            year=2026,
            as_of=date(2026, 3, 31),
            include_total=False,
            sources_csv=registry,
        )
        assert "Total" not in table.index


class TestSaveCsv:
    def test_writes_value_and_unit(self, tmp_path: Path) -> None:
        df = pd.DataFrame(
            {
                "country_key": ["korea"],
                "country": ["Korea"],
                "date": pd.to_datetime(["2026-01-01"]),
                "product_canonical": ["LPG"],
                "metric_type": ["CLOSTLV"],
                "value_native": [1000.0],
                "unit_native": ["kb"],
                "value_kb": [1000.0],
                "is_provisional": [False],
                "source": ["korea_petroleum_stocks"],
                "year": [2026],
                "month": [1],
                "month_label": ["Jan"],
            }
        )
        out = tmp_path / "out.csv"
        save_consolidated_csv(df, out, target_unit="mbbl")
        saved = pd.read_csv(out)
        assert saved.loc[0, "value"] == pytest.approx(1.0)
        assert saved.loc[0, "unit"] == "mbbl"
        assert saved.loc[0, "value_kb"] == pytest.approx(1000.0)


class TestProductCanonicalAliases:
    def test_fuel_oil_alias_collapses(self) -> None:
        s = pd.Series(["Fuel oil", "Fuel Oil", "Diesel"])
        out = normalize_product_canonical(s)
        assert out.tolist() == ["Fuel Oil", "Fuel Oil", "Diesel"]


class TestLoadInventorySources:
    def test_project_registry_loads(self) -> None:
        src = load_inventory_sources()
        assert "korea" in src["country_key"].values
        assert src["sort_order"].is_monotonic_increasing
