"""Eurostat oilm connector smoke tests."""

from __future__ import annotations

import pandas as pd
import pytest

from reference.eurostat_oilm import (
    GEO_CATALOG,
    JODI_COMPARE_SERIES,
    NATIONAL_PRIMARY_IDS,
    SIEC_GAS_DIESEL_OIL,
    SIEC_MOTOR_GASOLINE,
    SOURCE_ID,
    STOCK_BUCKET_LABELS,
    country_id_to_geo,
    eurostat_only_catalog,
    seasonality_chart_inputs,
    stock_bucket_for_flow,
)
from warehouse.consolidate import _assign_freshness_tiers


def test_geo_catalog_covers_nationals_and_neighbours():
    assert country_id_to_geo("germany") == "DE"
    assert country_id_to_geo("greece") == "EL"
    assert country_id_to_geo("turkiye") == "TR"
    assert "france" not in NATIONAL_PRIMARY_IDS
    assert "germany" in NATIONAL_PRIMARY_IDS
    assert len(eurostat_only_catalog()) >= 20


def test_jodi_compare_uses_headline_siec():
    assert SIEC_MOTOR_GASOLINE in JODI_COMPARE_SERIES["gasoline"].natives
    assert SIEC_GAS_DIESEL_OIL in JODI_COMPARE_SERIES["diesel"].natives


def test_freshness_tiers_prefer_newer_eurostat():
    nat = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-04-01", "2026-05-01"]),
            "source": ["bafa", "bafa"],
            "source_tier": ["official", "official"],
            "value_kbd": [1.0, 1.0],
        }
    )
    euro = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-04-01", "2026-05-01", "2026-06-01"]),
            "source": [SOURCE_ID, SOURCE_ID, SOURCE_ID],
            "source_tier": ["benchmark", "benchmark", "benchmark"],
            "value_kbd": [1.0, 1.0, 1.0],
        }
    )
    n, e = _assign_freshness_tiers(nat, euro)
    assert e["source_tier"].iloc[0] == "official"
    assert n["source_tier"].iloc[0] == "benchmark"


def test_freshness_tiers_tie_keeps_national():
    dates = pd.to_datetime(["2026-05-01"])
    nat = pd.DataFrame(
        {"date": dates, "source": ["bafa"], "source_tier": ["official"], "value_kbd": [1.0]}
    )
    euro = pd.DataFrame(
        {
            "date": dates,
            "source": [SOURCE_ID],
            "source_tier": ["benchmark"],
            "value_kbd": [1.0],
        }
    )
    n, e = _assign_freshness_tiers(nat, euro)
    assert n["source_tier"].iloc[0] == "official"
    assert e["source_tier"].iloc[0] == "benchmark"


def test_seasonality_signature():
    demand = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=3, freq="ME"),
            "product_native": [SIEC_MOTOR_GASOLINE] * 3,
            "value_kbd": [100.0, 110.0, 105.0],
        }
    )
    canon = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=3, freq="ME"),
            "panel": ["Gasoline"] * 3,
            "value_kbd": [100.0, 110.0, 105.0],
        }
    )
    df, col, products, labels, suffix = seasonality_chart_inputs(
        demand, canon, view="native"
    )
    assert col == "product_native"
    assert SIEC_MOTOR_GASOLINE in products
    assert not df.empty


@pytest.mark.integration
def test_countries_yaml_has_eurostat_primary():
    from warehouse.registry import get_country, list_countries

    fr = get_country("france")
    assert fr.official_source_label == "Eurostat"
    assert fr.country_code == "FR"
    enabled = {c.country_id for c in list_countries(enabled_only=True)}
    assert "netherlands" in enabled
    assert "serbia" in enabled
    assert len(enabled) >= 40


@pytest.mark.integration
def test_eurostat_compare_panels_germany():
    from analytics.core.comparisons import build_eurostat_comparison_figure
    from analytics.core.loader import load_eurostat_compare_panels
    from warehouse.consolidate import default_warehouse_path

    if not default_warehouse_path().exists():
        pytest.skip("Warehouse not built")

    national, euro, panels, label = load_eurostat_compare_panels("germany")
    assert not national.empty
    assert not euro.empty
    assert panels
    assert label == "BAFA"
    fig = build_eurostat_comparison_figure(
        national, euro, panels, label_national=label, title="test"
    )
    assert fig is not None

    # Eurostat-only: no national companion
    nat_fr, euro_fr, panels_fr, _ = load_eurostat_compare_panels("france")
    assert nat_fr.empty
    assert not euro_fr.empty or panels_fr == []


def test_stock_bucket_mapping_covers_spr_commercial_abroad():
    assert stock_bucket_for_flow("STK_CL") == "closing_headline"
    assert stock_bucket_for_flow("STKCL_EUE") == "emergency_spr"
    assert stock_bucket_for_flow("STKCL_EUE_NAT_CSE") == "emergency_spr"
    assert stock_bucket_for_flow("STKCL_NAT") == "national_territory"
    assert stock_bucket_for_flow("STKCL_NAT_OTH") == "national_territory"
    assert stock_bucket_for_flow("STKCL_ABR_OA") == "held_abroad"
    assert stock_bucket_for_flow("STKCL_C_OTH_OA") == "held_for_others"
    assert stock_bucket_for_flow("STKCL_BA") == "bonded_areas"
    assert stock_bucket_for_flow("STKCL_MCL") == "major_consumers"
    assert stock_bucket_for_flow("STKCL_PF") == "pipeline_vessels"
    assert stock_bucket_for_flow("STKCL_KFD") == "known_foreign_destination"
    assert "emergency_spr" in STOCK_BUCKET_LABELS
    assert "held_abroad" in STOCK_BUCKET_LABELS
