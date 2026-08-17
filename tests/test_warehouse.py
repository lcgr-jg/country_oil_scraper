"""Tests for the central DuckDB warehouse."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from warehouse.consolidate import (
    consolidate,
    default_warehouse_path,
    ensure_warehouse,
    warehouse_needs_rebuild,
)
from warehouse.registry import get_country, list_countries


@pytest.fixture
def norway_parquet_path() -> Path:
    cfg = get_country("norway")
    if not cfg.parquet_path.exists():
        pytest.skip(f"Norway parquet not found: {cfg.parquet_path}")
    return cfg.parquet_path


def test_countries_registry():
    countries = list_countries()
    assert len(countries) == 14
    assert any(c.country_id == "norway" for c in countries)
    assert any(c.country_id == "thailand" for c in countries)
    assert any(c.country_id == "india" for c in countries)
    norway = get_country("norway")
    assert norway.country_code == "NO"
    assert norway.jodi_ref_area == "NO"
    italy = get_country("italy")
    assert italy.jodi_ref_area == "IT"
    assert italy.reference_module == "reference.italy"


def test_consolidate_norway(tmp_path: Path, norway_parquet_path: Path):
    db_path = tmp_path / "test.duckdb"
    result = consolidate(
        warehouse_path=db_path,
        countries=["norway"],
        include_jodi=False,
        include_kayrros=False,
    )
    assert result == db_path
    assert db_path.exists()

    import duckdb

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        n = con.execute("SELECT COUNT(*) FROM fact_observations").fetchone()[0]
        assert n > 0
        tiers = con.execute(
            "SELECT DISTINCT source_tier FROM fact_observations"
        ).fetchall()
        assert ("official",) in tiers
    finally:
        con.close()


def test_resolve_source_id_eppo_and_ppac():
    from warehouse.country_hooks import load_reference, resolve_source_id

    th = get_country("thailand")
    assert resolve_source_id(th, load_reference(th)) == "eppo_petroleum_sales"
    ind = get_country("india")
    assert resolve_source_id(ind, load_reference(ind)) == "ppac"


def test_consolidate_thailand_has_value_kbd(tmp_path: Path):
    cfg = get_country("thailand")
    if not cfg.parquet_path.exists():
        pytest.skip(f"Thailand parquet not found: {cfg.parquet_path}")

    db_path = tmp_path / "th.duckdb"
    consolidate(
        warehouse_path=db_path,
        countries=["thailand"],
        include_jodi=False,
        include_kayrros=False,
    )

    import duckdb

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        nulls, total = con.execute(
            """
            SELECT
              sum(CASE WHEN value_kbd IS NULL THEN 1 ELSE 0 END),
              count(*)
            FROM fact_observations
            WHERE source_tier = 'official'
            """
        ).fetchone()
        assert total > 0
        assert nulls == 0
        source = con.execute(
            "SELECT DISTINCT source FROM fact_observations WHERE source_tier = 'official'"
        ).fetchone()[0]
        assert source == "eppo_petroleum_sales"
    finally:
        con.close()


def test_warehouse_needs_rebuild_when_missing(tmp_path: Path):
    db_path = tmp_path / "missing.duckdb"
    assert warehouse_needs_rebuild(db_path) is True


def test_ensure_warehouse_skips_when_fresh(tmp_path: Path, norway_parquet_path: Path):
    db_path = tmp_path / "fresh.duckdb"
    consolidate(
        warehouse_path=db_path,
        countries=["norway"],
        include_jodi=False,
        include_kayrros=False,
    )
    assert warehouse_needs_rebuild(db_path, include_jodi=False, include_kayrros=False) is False
    path = ensure_warehouse(
        warehouse_path=db_path,
        countries=["norway"],
        include_jodi=False,
        include_kayrros=False,
    )
    assert path == db_path


def test_ensure_warehouse_rebuilds_when_parquet_newer(
    tmp_path: Path, norway_parquet_path: Path
):
    import os

    db_path = tmp_path / "stale.duckdb"
    consolidate(
        warehouse_path=db_path,
        countries=["norway"],
        include_jodi=False,
        include_kayrros=False,
    )
    # Back-date the warehouse so any on-disk country parquet looks newer.
    os.utime(db_path, (0, 0))
    assert warehouse_needs_rebuild(db_path, include_jodi=False, include_kayrros=False) is True
    ensure_warehouse(
        warehouse_path=db_path,
        countries=["norway"],
        include_jodi=False,
        include_kayrros=False,
    )
    assert warehouse_needs_rebuild(db_path, include_jodi=False, include_kayrros=False) is False


def test_consolidate_india_excludes_total_rows(tmp_path: Path):
    cfg = get_country("india")
    if not cfg.parquet_path.exists():
        pytest.skip(f"India parquet not found: {cfg.parquet_path}")

    db_path = tmp_path / "in.duckdb"
    consolidate(
        warehouse_path=db_path,
        countries=["india"],
        include_jodi=False,
        include_kayrros=False,
    )

    import duckdb

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        totals = con.execute(
            """
            SELECT count(*)
            FROM fact_observations
            WHERE country_code = 'IN'
              AND source_tier = 'official'
              AND product_native IN ('TOTAL', 'All Products total', 'All products total')
            """
        ).fetchone()[0]
        assert totals == 0
        n = con.execute(
            """
            SELECT count(*)
            FROM fact_observations
            WHERE country_code = 'IN' AND source_tier = 'official'
            """
        ).fetchone()[0]
        assert n == 4048
    finally:
        con.close()


def test_seasonality_hooks_polished_countries():
    from warehouse.country_hooks import call_seasonality_chart_inputs, load_reference
    from analytics.core.loader import load_demand_canonical, load_official_demand

    for cid in ("india", "thailand", "australia", "italy"):
        ref = load_reference(get_country(cid))
        assert hasattr(ref, "seasonality_chart_inputs")
        demand = load_official_demand(cid)
        if demand.empty:
            pytest.skip(f"No demand for {cid}")
        canon = load_demand_canonical(cid)
        df, col, products, labels, _suffix = call_seasonality_chart_inputs(
            ref.seasonality_chart_inputs,
            demand,
            canon,
            view="native",
            value_col="value_kbd",
        )
        assert col == "product_native"
        assert products
        assert not df.empty
        assert labels


def test_dashboard_copy_country_specific():
    from analytics.core.dashboard_copy import jodi_compare_caption, seasonality_caption

    assert "X_OTHKERO" in jodi_compare_caption("india")
    assert "J.P." in jodi_compare_caption("thailand")
    assert "calendar year" in seasonality_caption("norway").lower()


def test_resolve_product_labels_audit_mode():
    from reference.dashboard_helpers import resolve_product_labels

    friendly = {"MS": "Gasoline", " HSD": "Diesel"}
    audit = resolve_product_labels(
        ["MS", " HSD"], friendly, use_source_native=True
    )
    assert audit == {"MS": "MS", " HSD": " HSD"}
    display = resolve_product_labels(
        ["MS", " HSD"], friendly, use_source_native=False
    )
    assert display["MS"] == "Gasoline"
    assert display[" HSD"] == "Diesel"


def test_demand_canonical_unique_date_panel():
    from analytics.core.loader import load_demand_canonical

    for cid in ("india", "spain", "japan", "uk", "portugal", "poland", "norway"):
        canon = load_demand_canonical(cid)
        if canon.empty:
            continue
        dup = canon.groupby(["date", "panel"]).size()
        assert dup.max() == 1, f"{cid}: duplicate date+panel rows (max={dup.max()})"


def test_jodi_compare_panels_thailand_india_australia():
    from analytics.core.loader import load_jodi_compare_panels

    for cid in ("thailand", "india", "australia"):
        official, jodi, panels = load_jodi_compare_panels(cid)
        assert len(panels) >= 4, f"{cid}: expected panels, got {panels}"
        assert not official.empty, f"{cid}: official JODI panels empty"
        assert official["value_kbd"].notna().any()
        if not jodi.empty:
            assert jodi["panel"].notna().any()


def test_jodi_loader_has_panel_column(norway_parquet_path: Path):
    from analytics.core.loader import load_jodi_compare_panels

    _official, jodi, panels = load_jodi_compare_panels("norway")
    if jodi.empty:
        pytest.skip("No JODI rows for Norway in warehouse")
    assert "panel" in jodi.columns
    assert len(panels) > 0


def test_product_change_table():
    from analytics.core.metrics import product_change_table

    dates = pd.date_range("2024-01-31", periods=14, freq="ME")
    frame = pd.DataFrame(
        {
            "date": list(dates) + list(dates),
            "product_native": ["A"] * 14 + ["B"] * 14,
            "value_kbd": list(range(100, 114)) + list(range(200, 214)),
        }
    )
    tbl = product_change_table(frame, product_col="product_native")
    assert len(tbl) == 2
    assert "mom_pct" in tbl.columns


def test_snapshot_html_includes_plotly_js():
    import plotly.express as px

    from analytics.reports.html_export import prepare_figure_for_static_export, snapshot_to_html

    df = pd.DataFrame(
        {"date": pd.date_range("2024-01-01", periods=6, freq="ME"), "y": range(6)}
    )
    fig = px.line(df, x="date", y="y")
    prepared = prepare_figure_for_static_export(fig)
    assert prepared.data[0].line.color == "#636efa"
    html = snapshot_to_html(title="Test", figures=[fig], plotlyjs_mode="inline")
    assert "Plotly.newPlot" in html
    assert '"color":"#636efa"' in html or '"color": "#636efa"' in html
    assert "plotly-2.27.0" not in html
    assert len(html) > 100_000


def test_snapshot_html_handles_bar_charts():
    import plotly.express as px

    from analytics.reports.html_export import prepare_figure_for_static_export, snapshot_to_html

    df = pd.DataFrame(
        {
            "country": ["A", "B", "C"],
            "mom_kbd": [10.0, -5.0, 3.0],
            "direction": ["Increase", "Decrease", "Increase"],
        }
    )
    fig = px.bar(
        df,
        x="mom_kbd",
        y="country",
        orientation="h",
        color="direction",
        color_discrete_map={"Increase": "#2ca02c", "Decrease": "#d62728"},
    )
    prepared = prepare_figure_for_static_export(fig)
    assert len(prepared.data) >= 1
    html = snapshot_to_html(title="Bar test", figures=[fig], plotlyjs_mode="inline")
    assert "Plotly.newPlot" in html


def test_call_seasonality_chart_inputs_both_signatures():
    import pandas as pd

    from warehouse.country_hooks import call_seasonality_chart_inputs

    demand = pd.DataFrame(
        {"date": pd.date_range("2024-01-01", periods=3, freq="ME"), "product_native": ["a"] * 3, "value_kbd": [1, 2, 3]}
    )
    canonical = pd.DataFrame(
        {"date": pd.date_range("2024-01-01", periods=3, freq="ME"), "panel": ["Gasoline"] * 3, "value_kbd": [1, 2, 3]}
    )

    def norway_style(d, c, *, view="native", value_col="value_kbd"):
        return d, "product_native", ["a"], {"a": "A"}, view

    def korea_style(view, *, demand, demand_canonical):
        return demand, "product_native", ["a"], {"a": "A"}, view

    call_seasonality_chart_inputs(norway_style, demand, canonical, view="native")
    call_seasonality_chart_inputs(korea_style, demand, canonical, view="native")
    import plotly.express as px

    from analytics.reports.html_export import snapshot_to_html

    df = pd.DataFrame(
        {
            "date": list(pd.date_range("2024-01-01", periods=6, freq="ME")) * 2,
            "y": list(range(6)) * 2,
            "label": ["A"] * 6 + ["B"] * 6,
        }
    )
    fig = px.line(df, x="date", y="y", color="label")
    html = snapshot_to_html(title="Test", figures=[fig])
    assert "#636efa" in html
    assert "#EF553B" in html


def test_headline_total_one_row_per_date_with_mixed_provisional():
    from analytics.core.metrics import headline_total

    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-01", "2024-01-01"]),
            "panel": ["Gasoline", "Diesel"],
            "value_kbd": [100.0, 200.0],
            "is_provisional": [False, True],
        }
    )
    h = headline_total(frame)
    assert len(h) == 1
    assert h.iloc[0]["value_kbd"] == 300.0
    assert bool(h.iloc[0]["is_provisional"]) is True


def test_multi_country_reporting_and_no_duplicate_headline():
    from analytics.core.metrics import headline_total
    from analytics.core.multi_country import (
        aggregate_demand_canonical,
        reporting_metadata,
    )

    db = default_warehouse_path()
    if not db.exists():
        pytest.skip("Warehouse not built")

    ids = ["japan", "korea", "taiwan", "thailand", "india", "australia"]
    meta = reporting_metadata(ids)
    assert meta["balanced_through_label"] == "2026-04"
    assert len(meta["by_country"]) == 6

    agg = aggregate_demand_canonical(ids)
    h = headline_total(agg)
    dup = h.groupby(pd.to_datetime(h["date"]).dt.to_period("M")).size()
    assert dup.max() == 1
    assert pd.to_datetime(h["date"]).max().strftime("%Y-%m") == "2026-04"


def test_multi_country_country_drivers():
    from analytics.core.multi_country import (
        country_driver_table,
        country_total_driver_table,
        top_moving_panels,
    )

    db = default_warehouse_path()
    if not db.exists():
        pytest.skip("Warehouse not built")

    ids = ["japan", "korea", "taiwan", "thailand", "india", "australia"]
    ref = pd.Timestamp("2026-04-01")
    drivers = country_driver_table(ids, ref_date=ref)
    assert not drivers.empty
    assert "share_mom_pct" in drivers.columns
    naphtha = drivers[drivers["panel"] == "Naphtha"]
    assert not naphtha.empty
    korea_row = naphtha[naphtha["country_id"] == "korea"]
    assert float(korea_row["mom_kbd"].iloc[0]) < 0
    assert float(korea_row["share_mom_pct"].iloc[0]) > 50

    totals = country_total_driver_table(ids, ref_date=ref)
    assert len(totals) == 6

    top = top_moving_panels(drivers, n=3)
    assert "Naphtha" in top


def test_regions_config_loads():
    from warehouse.regions import get_region, list_regions

    regions = list_regions()
    assert len(regions) >= 3
    europe = get_region("europe")
    assert "norway" in europe.country_ids
    assert "italy" in europe.country_ids
    asia = get_region("asia_pacific")
    assert "japan" in asia.country_ids
    assert "india" in asia.country_ids


def test_multi_country_aggregate_demand():
    from analytics.core.multi_country import (
        aggregate_demand_canonical,
        aggregate_jodi_compare_panels,
        load_country_bundle,
        multi_country_display_name,
    )

    db = default_warehouse_path()
    if not db.exists():
        pytest.skip("Warehouse not built")

    ids = ["norway", "uk"]
    bundle = load_country_bundle(ids)
    assert not bundle["demand_canonical"].empty
    assert "country_id" in bundle["demand"].columns

    agg = aggregate_demand_canonical(ids)
    assert not agg.empty
    assert agg.groupby(["date", "panel"]).size().max() == 1

    per_country = aggregate_demand_canonical(ids, include_country_column=True)
    assert per_country["country_id"].nunique() == 2

    off, jodi, panels = aggregate_jodi_compare_panels(ids)
    if not off.empty and panels:
        assert set(off["panel"]).issubset(set(panels))

    name = multi_country_display_name(ids)
    assert "Norway" in name
