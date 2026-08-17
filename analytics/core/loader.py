"""Query helpers for the central DuckDB warehouse."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

import duckdb
import pandas as pd

from warehouse.consolidate import canonical_panel_label, default_warehouse_path
from warehouse.country_hooks import build_official_jodi_panels, load_reference
from warehouse.registry import get_country, list_countries

SourceTier = Literal["official", "benchmark", "satellite", "all"]


def connect(warehouse_path: Optional[Path] = None) -> duckdb.DuckDBPyConnection:
    path = Path(warehouse_path or default_warehouse_path())
    if not path.exists():
        raise FileNotFoundError(
            f"Warehouse not found at {path}. Run: python scripts/consolidate_warehouse.py"
        )
    return duckdb.connect(str(path), read_only=True)


def load_observations(
    country_id: str,
    *,
    source_tier: SourceTier = "all",
    metric_type: str = "TOTDEMO",
    warehouse_path: Optional[Path] = None,
) -> pd.DataFrame:
    cfg = get_country(country_id)
    con = connect(warehouse_path)
    try:
        sql = """
            SELECT *
            FROM fact_observations
            WHERE country_code = ?
              AND metric_type = ?
        """
        params: list[object] = [cfg.country_code, metric_type]
        if source_tier != "all":
            sql += " AND source_tier = ?"
            params.append(source_tier)
        sql += " ORDER BY date, source, product_native"
        df = con.execute(sql, params).df()
    finally:
        con.close()

    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    return df


def load_official_demand(
    country_id: str,
    *,
    warehouse_path: Optional[Path] = None,
) -> pd.DataFrame:
    return load_observations(
        country_id, source_tier="official", warehouse_path=warehouse_path
    )


def load_demand_canonical(
    country_id: str,
    *,
    warehouse_path: Optional[Path] = None,
) -> pd.DataFrame:
    """Official demand aggregated to canonical product panels (kbd)."""
    demand = load_official_demand(country_id, warehouse_path=warehouse_path)
    if demand.empty:
        return demand

    sl = demand[demand["product_canonical"].notna()].copy()
    if sl.empty:
        return sl

    # Map sub-category labels (Diesel, Gasoil, …) to kind-level panels (Gasoline,
    # Diesel, …). Several canonical names can share one panel — sum after mapping.
    sl["panel"] = sl["product_canonical"].map(canonical_panel_label)
    out = (
        sl.groupby(["date", "panel", "is_provisional"], as_index=False)["value_kbd"]
        .sum()
        .sort_values("date")
    )
    return out


def load_jodi_compare_panels(
    country_id: str,
    *,
    warehouse_path: Optional[Path] = None,
) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """
    Return (official_panels, jodi_panels, panel_order) for cross-source charts.
    """
    cfg = get_country(country_id)
    ref = load_reference(cfg)
    demand = load_official_demand(country_id, warehouse_path=warehouse_path)
    jodi = load_observations(
        country_id, source_tier="benchmark", warehouse_path=warehouse_path
    )

    official = build_official_jodi_panels(demand, cfg, ref=ref)
    panel_order = list(getattr(ref, "JODI_COMPARE_PANEL_ORDER", ())) if ref else []

    jodi_panels = jodi[jodi["compare_panel"].notna()].copy()
    jodi_panels = jodi_panels.rename(columns={"compare_panel": "panel"})

    present = set(official.get("panel", pd.Series(dtype=str)).tolist()) | set(
        jodi_panels.get("panel", pd.Series(dtype=str)).tolist()
    )
    if panel_order:
        panels = [p for p in panel_order if p in present]
    else:
        panels = sorted(present)

    return official, jodi_panels, panels


def load_kayrros_series(
    country_id: str,
    product_canonical: str = "Jet fuel",
    *,
    warehouse_path: Optional[Path] = None,
) -> pd.DataFrame:
    obs = load_observations(
        country_id, source_tier="satellite", warehouse_path=warehouse_path
    )
    if obs.empty:
        return obs
    sl = obs[obs["product_canonical"] == product_canonical].copy()
    return sl.sort_values("date")


def list_enabled_country_ids() -> list[str]:
    return [c.country_id for c in list_countries(enabled_only=True)]


def warehouse_status(warehouse_path: Optional[Path] = None) -> dict[str, object]:
    path = Path(warehouse_path or default_warehouse_path())
    if not path.exists():
        return {"exists": False, "path": str(path)}
    con = connect(path)
    try:
        n = con.execute("SELECT COUNT(*) FROM fact_observations").fetchone()[0]
        countries = con.execute(
            "SELECT DISTINCT country_code, country_name FROM fact_observations ORDER BY 1"
        ).df()
        sources = con.execute(
            "SELECT source_tier, COUNT(*) AS n FROM fact_observations GROUP BY 1"
        ).df()
        date_range = con.execute(
            "SELECT MIN(date) AS min_date, MAX(date) AS max_date FROM fact_observations"
        ).df()
    finally:
        con.close()
    return {
        "exists": True,
        "path": str(path),
        "rows": int(n),
        "countries": countries.to_dict("records"),
        "sources": sources.to_dict("records"),
        "date_range": date_range.to_dict("records")[0] if len(date_range) else {},
    }
