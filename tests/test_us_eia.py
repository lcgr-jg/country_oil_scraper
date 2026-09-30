"""Tests for US EIA product-supplied connector (weekly sqlite → monthly kb/d)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from reference.loaders import canonical_subcategory, load_product_map
from reference.us import (
    JODI_COMPARE_SERIES,
    PRODUCT_DISTILLATES,
    PRODUCT_GASOLINE,
    PRODUCT_JET_KERO,
    PRODUCT_OTHER_OIL,
    PRODUCT_RESID,
    PRODUCT_TOTAL_OIL,
    SERIES_BY_PRODUCT,
    STORED_NATIVES,
    eia_series_for_jodi,
    resolve_eia_sqlite,
)
import processors.us_eia_product_supplied as processor


@pytest.fixture(scope="module")
def eia_db() -> Path:
    try:
        return resolve_eia_sqlite()
    except FileNotFoundError as exc:
        pytest.skip(str(exc))


@pytest.fixture(scope="module")
def us_df(eia_db: Path) -> pd.DataFrame:
    load_product_map.cache_clear()
    return processor.build_from_eia_sqlite(eia_db)


def test_product_map_has_eia_rows():
    load_product_map.cache_clear()
    pm = load_product_map()
    eia = pm[pm["Source"] == "EIA"]
    assert set(STORED_NATIVES).issubset(set(eia["Product_name"]))


def test_canonical_map():
    load_product_map.cache_clear()
    assert canonical_subcategory(PRODUCT_GASOLINE, source="EIA") == "Gasoline"
    assert canonical_subcategory(PRODUCT_DISTILLATES, source="EIA") == "Diesel"
    assert canonical_subcategory(PRODUCT_JET_KERO, source="EIA") == "Jet Fuel"
    assert canonical_subcategory(PRODUCT_RESID, source="EIA") == "Fuel Oil"
    assert canonical_subcategory(PRODUCT_OTHER_OIL, source="EIA") is None
    assert canonical_subcategory(PRODUCT_TOTAL_OIL, source="EIA") is None


def test_jodi_overlay_products():
    assert JODI_COMPARE_SERIES["diesel"].jodi_energy_product == "GASDIES"
    assert JODI_COMPARE_SERIES["jet_fuel"].jodi_energy_product == "JETKERO"
    assert PRODUCT_DISTILLATES in JODI_COMPARE_SERIES["diesel"].natives


def test_weekly_to_monthly_partial_month_uses_mtd_days():
    # Mid-month Friday: 2024-01-12 → Jan 6–12 (7 covered days). Incomplete Jan.
    # Must divide by 7 (MTD), not 31 — otherwise the rate collapses toward zero.
    weekly = pd.DataFrame(
        {
            "week_end": [pd.Timestamp("2024-01-12")],
            "product_native": [PRODUCT_GASOLINE],
            "value_kbd": [7000.0],
        }
    )
    monthly = processor.weekly_kbd_to_monthly_kbd(weekly)
    jan = monthly[monthly["date"] == pd.Timestamp("2024-01-01")].iloc[0]
    assert jan["value"] == pytest.approx(7000.0, rel=0, abs=1e-6)
    assert bool(jan["is_provisional"]) is True


def test_weekly_to_monthly_splits_across_months():
    # Week ending 2024-02-02 = Jan 27–Feb 2: 5 days Jan + 2 days Feb.
    weekly = pd.DataFrame(
        {
            "week_end": [pd.Timestamp("2024-02-02")],
            "product_native": [PRODUCT_GASOLINE],
            "value_kbd": [1000.0],
        }
    )
    monthly = processor.weekly_kbd_to_monthly_kbd(weekly)
    by_date = monthly.set_index("date")["value"]
    assert by_date[pd.Timestamp("2024-01-01")] == pytest.approx(1000.0)
    assert by_date[pd.Timestamp("2024-02-01")] == pytest.approx(1000.0)


def test_weekly_to_monthly_full_month_divides_by_calendar_days():
    # Cover every day of Jan 2024 with a flat 1000 kbd (weeks ending 5,12,19,26
    # plus spill from Dec 29–31 week and into Feb). Use continuous Fridays so
    # Jan 1–31 are all attributed → divisor is 31.
    fridays = pd.date_range("2023-12-29", "2024-02-02", freq="W-FRI")
    weekly = pd.DataFrame(
        {
            "week_end": fridays,
            "product_native": [PRODUCT_GASOLINE] * len(fridays),
            "value_kbd": [1000.0] * len(fridays),
        }
    )
    monthly = processor.weekly_kbd_to_monthly_kbd(weekly)
    jan = monthly[monthly["date"] == pd.Timestamp("2024-01-01")].iloc[0]
    assert jan["value"] == pytest.approx(1000.0, rel=0, abs=1e-6)
    assert bool(jan["is_provisional"]) is False


def test_build_has_expected_products(us_df: pd.DataFrame):
    assert set(us_df["product_native"]) == set(STORED_NATIVES)
    assert us_df["unit"].eq("kbd").all()
    assert us_df["country"].eq("US").all()
    assert us_df["metric_type"].eq("TOTDEMO").all()


def test_canonical_columns(us_df: pd.DataFrame):
    gas = us_df[us_df["product_native"] == PRODUCT_GASOLINE]
    assert gas["product_canonical"].eq("Gasoline").all()
    other = us_df[us_df["product_native"] == PRODUCT_OTHER_OIL]
    assert other["product_canonical"].isna().all()
    total = us_df[us_df["product_native"] == PRODUCT_TOTAL_OIL]
    assert total["product_canonical"].isna().all()


def test_latest_month_provisional_flag(us_df: pd.DataFrame):
    latest = us_df["date"].max()
    latest_rows = us_df[us_df["date"] == latest]
    # With data through early September, September should be provisional.
    assert latest_rows["is_provisional"].all()
    # Prior complete months should not all be provisional.
    prior = us_df[us_df["date"] < latest]
    assert not prior["is_provisional"].all()


def test_eia_series_for_jodi(us_df: pd.DataFrame):
    panel = eia_series_for_jodi(us_df, "gasoline", value_col="value")
    assert not panel.empty
    native = us_df[us_df["product_native"] == PRODUCT_GASOLINE][["date", "value"]]
    merged = panel.merge(native, on="date", suffixes=("_p", "_n"))
    assert (merged["value_p"] - merged["value_n"]).abs().max() < 1e-9


def test_series_ids_match_catalog():
    assert SERIES_BY_PRODUCT[PRODUCT_GASOLINE] == "WGFUPUS2"
    assert SERIES_BY_PRODUCT[PRODUCT_TOTAL_OIL] == "WRPUPUS2"
