"""
Build the central DuckDB warehouse from country parquets, JODI, and Kayrros.

Each enabled country in config/countries.yaml is loaded independently so new
countries can be added without changing this module.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable, Optional

import duckdb
import pandas as pd

from analytics.products import CANONICAL_KIND_LABEL, PRODUCT_KIND_MAP, SUBCATEGORY_TO_PRODUCT_KIND
from analytics.units import convert_series
from warehouse.country_hooks import (
    load_reference,
    normalize_official_frame,
    exclude_aggregate_total_rows,
    prepare_values_for_conversion,
    resolve_jodi_ref_area,
    resolve_source_id,
    resolve_unit_native,
)
from warehouse.kayrros_loader import load_kayrros_observations
from warehouse.registry import (
    CountryConfig,
    kayrros_db_path,
    list_countries,
    project_root,
)

logger = logging.getLogger(__name__)

_OBS_COLUMNS = [
    "country_code",
    "country_name",
    "scope_type",
    "date",
    "source",
    "source_tier",
    "metric_type",
    "product_native",
    "product_canonical",
    "category",
    "compare_panel",
    "value_native",
    "unit_native",
    "value_kbd",
    "is_provisional",
    "ingested_at",
]


def default_warehouse_path(root: Optional[Path] = None) -> Path:
    root = root or project_root()
    return root / "data" / "warehouse" / "oil_demand.duckdb"


def warehouse_needs_rebuild(
    warehouse_path: Optional[Path] = None,
    *,
    include_jodi: bool = True,
    include_kayrros: bool = True,
) -> bool:
    """True when the DuckDB file is missing or older than any consolidation input."""
    warehouse_path = Path(warehouse_path or default_warehouse_path())
    if not warehouse_path.exists():
        return True

    wh_mtime = warehouse_path.stat().st_mtime
    for cfg in list_countries(enabled_only=True):
        parquet_path = cfg.parquet_path
        if parquet_path.exists() and parquet_path.stat().st_mtime > wh_mtime:
            logger.info(
                "Warehouse stale: %s is newer than %s",
                parquet_path.name,
                warehouse_path.name,
            )
            return True

    if include_jodi:
        jodi_path = project_root() / "data" / "processed" / "jodi" / "jodi_secondary.parquet"
        if jodi_path.exists() and jodi_path.stat().st_mtime > wh_mtime:
            logger.info(
                "Warehouse stale: %s is newer than %s",
                jodi_path.name,
                warehouse_path.name,
            )
            return True

    if include_kayrros:
        kay_path = kayrros_db_path()
        if kay_path.exists() and kay_path.stat().st_mtime > wh_mtime:
            logger.info(
                "Warehouse stale: %s is newer than %s",
                kay_path.name,
                warehouse_path.name,
            )
            return True

    return False


def ensure_warehouse(
    *,
    warehouse_path: Optional[Path] = None,
    countries: Optional[Iterable[str]] = None,
    include_jodi: bool = True,
    include_kayrros: bool = True,
    force: bool = False,
) -> Path:
    """Rebuild the warehouse when missing or stale; otherwise return the existing path."""
    warehouse_path = Path(warehouse_path or default_warehouse_path())
    if force or warehouse_needs_rebuild(
        warehouse_path,
        include_jodi=include_jodi,
        include_kayrros=include_kayrros,
    ):
        return consolidate(
            warehouse_path=warehouse_path,
            countries=countries,
            include_jodi=include_jodi,
            include_kayrros=include_kayrros,
        )

    logger.info("Warehouse up to date: %s", warehouse_path)
    return warehouse_path


def consolidate(
    *,
    warehouse_path: Optional[Path] = None,
    countries: Optional[Iterable[str]] = None,
    include_jodi: bool = True,
    include_kayrros: bool = True,
) -> Path:
    """Rebuild fact tables in the DuckDB warehouse."""
    warehouse_path = Path(warehouse_path or default_warehouse_path())
    warehouse_path.parent.mkdir(parents=True, exist_ok=True)

    enabled = list_countries(enabled_only=True)
    if countries is not None:
        wanted = {c.strip().lower() for c in countries}
        enabled = [c for c in enabled if c.country_id in wanted]

    ingested_at = datetime.now(tz=UTC)
    obs_frames: list[pd.DataFrame] = []

    for cfg in enabled:
        official = _load_official_parquet(cfg, ingested_at)
        if not official.empty:
            obs_frames.append(official)
        if include_kayrros and cfg.kayrros_enabled:
            kay = load_kayrros_observations(
                cfg.country_code,
                cfg.display_name,
                cfg.kayrros_products,
            )
            if not kay.empty:
                obs_frames.append(kay)

    if include_jodi:
        jodi = _load_jodi_for_countries(enabled, ingested_at)
        if not jodi.empty:
            obs_frames.append(jodi)

    observations = (
        pd.concat(obs_frames, ignore_index=True)
        if obs_frames
        else pd.DataFrame(columns=_OBS_COLUMNS)
    )

    schema_path = project_root() / "warehouse" / "schema.sql"
    con = duckdb.connect(str(warehouse_path))
    try:
        con.execute(schema_path.read_text(encoding="utf-8"))
        con.execute("DELETE FROM fact_observations")
        con.execute("DELETE FROM fact_revisions")
        con.execute("DELETE FROM fact_divergences")
        if not observations.empty:
            con.register("_obs", observations)
            con.execute("INSERT INTO fact_observations SELECT * FROM _obs")
            con.unregister("_obs")
        logger.info(
            "Warehouse written: %s (%s observation rows, %s countries)",
            warehouse_path,
            f"{len(observations):,}",
            len(enabled),
        )
    finally:
        con.close()

    return warehouse_path


def _load_official_parquet(cfg: CountryConfig, ingested_at: datetime) -> pd.DataFrame:
    path = cfg.parquet_path
    if not path.exists():
        logger.warning(
            "Parquet missing for %s (%s) — run update script first",
            cfg.country_id,
            path,
        )
        return pd.DataFrame(columns=_OBS_COLUMNS)

    ref = load_reference(cfg)
    df = pd.read_parquet(path)
    df["date"] = pd.to_datetime(df["date"])
    df = normalize_official_frame(df, cfg)
    before = len(df)
    df = exclude_aggregate_total_rows(df)
    if before > len(df):
        logger.info(
            "Excluded %d aggregate total rows for %s",
            before - len(df),
            cfg.country_id,
        )
    df = df[df["metric_type"] == cfg.demand_metric_type].copy()
    if df.empty:
        return pd.DataFrame(columns=_OBS_COLUMNS)

    unit_native = resolve_unit_native(cfg, ref)
    if unit_native is None and "unit" in df.columns and df["unit"].notna().any():
        unit_series = df["unit"].astype(str)
    else:
        unit_series = unit_native

    units_kind = getattr(ref, "UNITS_KIND", None) if ref is not None else None
    if units_kind is not None:
        product_kind = df["product_native"].map(units_kind)
    elif ref is not None:
        source_id = resolve_source_id(cfg, ref)
        mapping = PRODUCT_KIND_MAP.get(source_id, {})
        product_kind = df["product_native"].map(lambda x: mapping.get(x))
    else:
        product_kind = None

    source_id = resolve_source_id(cfg, ref) if ref is not None else cfg.country_id
    country_code = getattr(ref, "COUNTRY_CODE", cfg.country_code) if ref is not None else cfg.country_code
    country_name = cfg.display_name

    prep, prep_unit = prepare_values_for_conversion(df, unit_series)

    df["value_kbd"] = convert_series(
        prep["value"],
        prep_unit,
        "kbd",
        product_kind=product_kind,
        date=prep["date"],
    )

    compare_panel = _official_compare_panels(df, ref)

    out = pd.DataFrame(
        {
            "country_code": country_code,
            "country_name": country_name,
            "scope_type": "country",
            "date": df["date"].dt.normalize(),
            "source": source_id,
            "source_tier": "official",
            "metric_type": df["metric_type"],
            "product_native": df["product_native"].astype(str),
            "product_canonical": df.get("product_canonical"),
            "category": df.get("category"),
            "compare_panel": compare_panel,
            "value_native": pd.to_numeric(df["value"], errors="coerce"),
            "unit_native": unit_series if isinstance(unit_series, str) else df.get("unit"),
            "value_kbd": df["value_kbd"],
            "is_provisional": df.get("is_provisional", False),
            "ingested_at": ingested_at,
        }
    )
    return out.dropna(subset=["date"])


def _official_compare_panels(df: pd.DataFrame, ref: object | None) -> pd.Series:
    """Map official rows to JODI compare panel labels where configured."""
    if ref is None:
        return df.get("product_canonical")
    jodi_series = getattr(ref, "JODI_COMPARE_SERIES", None)
    if not jodi_series:
        return df.get("product_canonical")

    native_to_panel: dict[str, str] = {}
    for spec in jodi_series.values():
        natives = getattr(spec, "natives", None)
        if not natives:
            continue
        for native in natives:
            native_to_panel[str(native)] = spec.panel

    if not native_to_panel:
        return df.get("product_canonical")
    return df["product_native"].map(native_to_panel)


def _load_jodi_for_countries(
    countries: list[CountryConfig],
    ingested_at: datetime,
) -> pd.DataFrame:
    jodi_path = project_root() / "data" / "processed" / "jodi" / "jodi_secondary.parquet"
    if not jodi_path.exists():
        logger.warning("JODI secondary parquet missing — skipping benchmark rows")
        return pd.DataFrame(columns=_OBS_COLUMNS)

    ref_areas = {resolve_jodi_ref_area(c) for c in countries}
    ref_to_country = {resolve_jodi_ref_area(c): c for c in countries}

    jodi = pd.read_parquet(jodi_path)
    jodi["date"] = pd.to_datetime(jodi["date"])
    jodi = jodi[
        (jodi["ref_area"].isin(ref_areas))
        & (jodi["flow_breakdown"] == "TOTDEMO")
        & (jodi["unit_measure"] == "KBD")
    ].copy()
    if jodi.empty:
        return pd.DataFrame(columns=_OBS_COLUMNS)

    panel_lookup: dict[str, dict[str, str]] = {}
    for cfg in countries:
        ref = load_reference(cfg)
        if ref is None:
            continue
        jodi_series = getattr(ref, "JODI_COMPARE_SERIES", None)
        if not jodi_series:
            continue
        ref_area = resolve_jodi_ref_area(cfg, ref)
        panel_lookup[ref_area] = {
            spec.jodi_energy_product: spec.panel for spec in jodi_series.values()
        }

    jodi_codes = {code for m in panel_lookup.values() for code in m}
    jodi = jodi[jodi["energy_product"].isin(jodi_codes)].copy()
    if jodi.empty:
        return pd.DataFrame(columns=_OBS_COLUMNS)

    def _panel(row: pd.Series) -> Optional[str]:
        mapping = panel_lookup.get(str(row["ref_area"]), {})
        return mapping.get(str(row["energy_product"]))

    jodi["compare_panel"] = jodi.apply(_panel, axis=1)

    rows: list[pd.DataFrame] = []
    for ref_area, cfg in ref_to_country.items():
        sl = jodi[jodi["ref_area"] == ref_area].copy()
        if sl.empty:
            continue
        rows.append(
            pd.DataFrame(
                {
                    "country_code": cfg.country_code,
                    "country_name": cfg.display_name,
                    "scope_type": "country",
                    "date": sl["date"].dt.normalize(),
                    "source": "JODI",
                    "source_tier": "benchmark",
                    "metric_type": "TOTDEMO",
                    "product_native": sl["energy_product"].astype(str),
                    "product_canonical": sl.get("product_canonical"),
                    "category": sl.get("category"),
                    "compare_panel": sl["compare_panel"],
                    "value_native": pd.to_numeric(sl["obs_value"], errors="coerce"),
                    "unit_native": "KBD",
                    "value_kbd": pd.to_numeric(sl["obs_value"], errors="coerce"),
                    "is_provisional": False,
                    "ingested_at": ingested_at,
                }
            )
        )

    if not rows:
        return pd.DataFrame(columns=_OBS_COLUMNS)
    return pd.concat(rows, ignore_index=True)


def canonical_panel_label(product_canonical: str) -> str:
    kind = SUBCATEGORY_TO_PRODUCT_KIND.get(product_canonical, "")
    return CANONICAL_KIND_LABEL.get(kind, product_canonical)
