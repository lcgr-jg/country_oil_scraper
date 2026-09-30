"""Tests for China SCI consumption connector (sci_api cache → parquet)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from reference.china import (
    JODI_COMPARE_SERIES,
    PRODUCT_JET_DOMESTIC,
    PRODUCT_JET_TOTAL,
    PRODUCT_KEROSENE,
    PRODUCT_X_OTHKERO,
    STORED_NATIVES,
    resolve_sci_cache_dir,
    sci_series_for_jodi,
)
from reference.loaders import canonical_subcategory, load_product_map
import processors.china_sci_consumption as processor

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def sci_cache() -> Path:
    try:
        return resolve_sci_cache_dir()
    except FileNotFoundError as exc:
        pytest.skip(str(exc))


@pytest.fixture(scope="module")
def china_df(sci_cache: Path) -> pd.DataFrame:
    load_product_map.cache_clear()
    return processor.build_from_sci_cache(sci_cache)


def test_product_map_has_sci_rows():
    load_product_map.cache_clear()
    pm = load_product_map()
    sci = pm[pm["Source"] == "SCI"]
    assert set(STORED_NATIVES).issubset(set(sci["Product_name"]))


def test_canonical_map_excludes_vgo_and_headline_kero():
    load_product_map.cache_clear()
    assert canonical_subcategory("VGO", source="SCI") is None
    assert canonical_subcategory("Kerosene", source="SCI") is None
    assert canonical_subcategory("Jet fuel (domestic)", source="SCI") is None
    assert canonical_subcategory("Jet fuel (total)", source="SCI") == "Jet Fuel"
    assert canonical_subcategory("X_OTHKERO", source="SCI") == "Kerosene"
    assert canonical_subcategory("Gasoline", source="SCI") == "Gasoline"


def test_jodi_overlay_uses_headline_kerosene():
    assert JODI_COMPARE_SERIES["kerosene"].jodi_energy_product == "KEROSENE"
    assert PRODUCT_KEROSENE in JODI_COMPARE_SERIES["kerosene"].natives
    assert PRODUCT_JET_TOTAL not in JODI_COMPARE_SERIES["kerosene"].natives


def test_build_has_expected_products(china_df: pd.DataFrame):
    products = set(china_df["product_native"])
    assert set(STORED_NATIVES) == products
    assert china_df["metric_type"].eq("TOTDEMO").all()
    assert china_df["unit"].eq("kt").all()
    assert china_df["country"].eq("CN").all()


def test_x_othkero_equals_kero_minus_domestic(china_df: pd.DataFrame):
    wide = china_df.pivot_table(
        index="date",
        columns="product_native",
        values="value",
        aggfunc="first",
    )
    expected = (wide[PRODUCT_KEROSENE] - wide[PRODUCT_JET_DOMESTIC]).clip(lower=0)
    got = wide[PRODUCT_X_OTHKERO]
    pd.testing.assert_series_equal(
        got.sort_index(),
        expected.sort_index(),
        check_names=False,
        atol=1e-6,
    )
    assert (got >= -1e-9).all()


def test_jet_total_equals_domestic_plus_intl(china_df: pd.DataFrame):
    wide = china_df.pivot_table(
        index="date",
        columns="product_native",
        values="value",
        aggfunc="first",
    )
    summed = wide[PRODUCT_JET_DOMESTIC] + wide["Jet fuel (international)"]
    pd.testing.assert_series_equal(
        wide[PRODUCT_JET_TOTAL].sort_index(),
        summed.sort_index(),
        check_names=False,
        atol=0.05,
    )


def test_canonical_columns_populated(china_df: pd.DataFrame):
    gas = china_df[china_df["product_native"] == "Gasoline"]
    assert gas["product_canonical"].eq("Gasoline").all()
    kero = china_df[china_df["product_native"] == PRODUCT_KEROSENE]
    assert kero["product_canonical"].isna().all()
    x = china_df[china_df["product_native"] == PRODUCT_X_OTHKERO]
    assert x["product_canonical"].eq("Kerosene").all()
    jet = china_df[china_df["product_native"] == PRODUCT_JET_TOTAL]
    assert jet["product_canonical"].eq("Jet Fuel").all()


def test_sci_series_for_jodi_kerosene(china_df: pd.DataFrame):
    panel = sci_series_for_jodi(china_df, "kerosene", value_col="value")
    assert not panel.empty
    native = china_df[china_df["product_native"] == PRODUCT_KEROSENE][
        ["date", "value"]
    ].sort_values("date")
    merged = panel.merge(native, on="date", suffixes=("_panel", "_native"))
    assert (merged["value_panel"] - merged["value_native"]).abs().max() < 1e-9


def test_upsert_replaces_overlapping_keys(china_df: pd.DataFrame):
    subset = china_df.head(20).copy()
    subset["value"] = subset["value"] + 1.0
    out = processor.upsert(china_df, subset)
    assert len(out) == len(china_df)
