"""Tests for Norway SSB petroleum product sales parser."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from reference.loaders import load_product_map
from reference.norway import (
    JODI_COMPARE_SERIES,
    PRODUCT_AUTO_DIESEL_DUTIABLE,
    PRODUCT_HEATING_KERO_COMBINED,
    PRODUCT_JET_KEROSENE,
    PRODUCT_LEGACY_DIESEL,
    PRODUCT_LEGACY_MIDDLE_DISTILLATES,
    PRODUCT_MARINE_GASOIL,
    PRODUCT_MOTOR_GASOLINE,
    SSB_METRIC_TYPE,
    SSB_UNIT_NATIVE,
    STORED_NATIVES,
    drop_superseded_legacy_natives,
    merge_era_tables,
    parse_ev_registrations_csv,
    parse_table3_workbook,
    road_fuel_series,
    ssb_series_for_jodi,
)
from processors.norway_ssb_sales import _sort_and_clean
from scrapers.norway_ssb import NorwaySsbScraper

PROJECT_ROOT = Path(__file__).resolve().parents[1]
XLSX_FIXTURE = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "norway"
    / "Monthly sales of petroleum products and liquid biofuels, by product. Million litres. Preliminary figures.xlsx"
)


@pytest.fixture(scope="module")
def xlsx_parsed() -> pd.DataFrame:
    scraper = NorwaySsbScraper(data_dir=PROJECT_ROOT / "data")
    return _sort_and_clean(scraper.parse_workbook(XLSX_FIXTURE))


def test_product_map_has_ssb_rows():
    pm = load_product_map()
    ssb = pm[pm["Source"] == "SSB"]
    assert len(ssb) == len(STORED_NATIVES)


def test_xlsx_fixture_exists():
    assert XLSX_FIXTURE.exists(), f"missing fixture {XLSX_FIXTURE}"


def test_xlsx_motor_gasoline_may_2026(xlsx_parsed: pd.DataFrame):
    row = xlsx_parsed[
        (xlsx_parsed["product_native"] == PRODUCT_MOTOR_GASOLINE)
        & (xlsx_parsed["date"] == pd.Timestamp("2026-05-01"))
    ]
    assert len(row) == 1
    # Petroleum incl. bio components column (not total deliveries 74).
    assert row.iloc[0]["value"] == pytest.approx(72.0)


def test_jodi_kerosene_uses_x_othkero_not_combined_kero():
    spec = JODI_COMPARE_SERIES["kerosene"]
    assert spec.jodi_energy_product == "X_OTHKERO"
    assert PRODUCT_HEATING_KERO_COMBINED in spec.natives
    assert PRODUCT_JET_KEROSENE not in spec.natives


def test_jodi_kerosene_series_excludes_jet(xlsx_parsed: pd.DataFrame):
    kero = ssb_series_for_jodi(xlsx_parsed, "kerosene")
    jet = ssb_series_for_jodi(xlsx_parsed, "jet_fuel")
    assert not kero.empty
    assert not jet.empty
    assert kero.iloc[0]["value"] != jet.iloc[0]["value"]


def test_merge_prefers_higher_priority_table():
    current = pd.DataFrame(
        [
            {
                "date": pd.Timestamp("2021-06-01"),
                "product_native": PRODUCT_MOTOR_GASOLINE,
                "value": 80.0,
                "source_file": "13585",
                "ssb_table": "13585",
                "ssb_era": "current",
                "ssb_priority": 3,
            }
        ]
    )
    bridge = pd.DataFrame(
        [
            {
                "date": pd.Timestamp("2021-06-01"),
                "product_native": PRODUCT_MOTOR_GASOLINE,
                "value": 70.0,
                "source_file": "11174",
                "ssb_table": "11174",
                "ssb_era": "bridge",
                "ssb_priority": 2,
            }
        ]
    )
    merged = merge_era_tables([bridge, current])
    assert merged.iloc[0]["value"] == pytest.approx(80.0)


def test_finalize_columns(xlsx_parsed: pd.DataFrame):
    assert xlsx_parsed["country"].eq("NO").all()
    assert xlsx_parsed["metric_type"].eq(SSB_METRIC_TYPE).all()
    assert xlsx_parsed["unit"].eq(SSB_UNIT_NATIVE).all()
    assert xlsx_parsed["is_provisional"].all()


_EV_CSV_FIXTURE = """YYYYMM,Total: New,PetrolOnly: New,DieselOnly: New,BEV: New,Non-plugin hybrid: New,Plugin hybrid: New,Total: Used,PetrolOnly: Used,DieselOnly: Used,BEV: Used,Non-plugin hybrid: Used,Plugin hybrid: Used
201101,5000,4500,400,50,30,20,100,80,15,2,2,1
201102,5100,4400,450,100,40,110,110,85,20,3,1,1
201103,5200,4300,400,200,50,250,120,90,25,5,3,2
"""


def test_parse_ev_registrations_csv_shares_and_3m():
    ev = parse_ev_registrations_csv(_EV_CSV_FIXTURE)
    assert len(ev) == 3
    assert ev.iloc[0]["bev_share_new"] == pytest.approx(50 / 5000)
    assert ev.iloc[2]["bev_share_new_3m"] == pytest.approx(
        ev["bev_share_new"].rolling(3, min_periods=1).mean().iloc[2]
    )


def test_merge_drops_legacy_diesel_when_bridge_split_present():
    overlap = pd.Timestamp("2012-06-01")
    bridge = pd.DataFrame(
        [
            {
                "date": overlap,
                "product_native": PRODUCT_AUTO_DIESEL_DUTIABLE,
                "value": 200.0,
                "source_file": "11174",
                "ssb_table": "11174",
                "ssb_era": "bridge",
                "ssb_priority": 2,
            },
            {
                "date": overlap,
                "product_native": PRODUCT_MARINE_GASOIL,
                "value": 50.0,
                "source_file": "11174",
                "ssb_table": "11174",
                "ssb_era": "bridge",
                "ssb_priority": 2,
            },
        ]
    )
    legacy = pd.DataFrame(
        [
            {
                "date": overlap,
                "product_native": PRODUCT_LEGACY_DIESEL,
                "value": 999.0,
                "source_file": "03687",
                "ssb_table": "03687",
                "ssb_era": "legacy",
                "ssb_priority": 1,
            },
            {
                "date": overlap,
                "product_native": PRODUCT_LEGACY_MIDDLE_DISTILLATES,
                "value": 888.0,
                "source_file": "03687",
                "ssb_table": "03687",
                "ssb_era": "legacy",
                "ssb_priority": 1,
            },
        ]
    )
    merged = merge_era_tables([legacy, bridge])
    natives = set(merged.loc[merged["date"] == overlap, "product_native"])
    assert PRODUCT_LEGACY_DIESEL not in natives
    assert PRODUCT_LEGACY_MIDDLE_DISTILLATES not in natives
    assert PRODUCT_AUTO_DIESEL_DUTIABLE in natives
    assert merged.loc[merged["product_native"] == PRODUCT_AUTO_DIESEL_DUTIABLE, "value"].iloc[
        0
    ] == pytest.approx(200.0)


def test_road_fuel_series_sums_gasoline_and_auto_diesel(xlsx_parsed: pd.DataFrame):
    road = road_fuel_series(xlsx_parsed, value_col="value")
    gas = xlsx_parsed[xlsx_parsed["product_native"] == PRODUCT_MOTOR_GASOLINE]
    diesel = xlsx_parsed[
        xlsx_parsed["product_native"].isin(
            {"Auto diesel, dutiable", "Auto diesel, free of duty"}
        )
    ]
    merged = gas.merge(
        diesel.groupby("date", as_index=False)["value"].sum(),
        on="date",
        suffixes=("_gas", "_diesel"),
    )
    sample = merged.iloc[0]
    row = road[road["date"] == sample["date"]]
    assert len(row) == 1
    assert row.iloc[0]["value"] == pytest.approx(sample["value_gas"] + sample["value_diesel"])
