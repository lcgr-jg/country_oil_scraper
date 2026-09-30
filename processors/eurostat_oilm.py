"""
Build Eurostat nrg_cb_oilm GID_OBS demand parquets (master + per-country).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from reference.eurostat_oilm import (
    CANONICAL_COLUMNS,
    EUROSTAT_AGENCY_SOURCE,
    EUROSTAT_METRIC_TYPE,
    EUROSTAT_UNIT_NATIVE,
    GEO_CATALOG,
    MASTER_PARQUET_REL,
    NATIONAL_PRIMARY_IDS,
    SKIP_GEOS,
    SOURCE_ID,
    STORED_SIEC,
    fetch_gid_obs_geos,
)
from reference.loaders import canonical_category, canonical_subcategory

logger = logging.getLogger(__name__)

_PRODUCT_MAP_SOURCE = EUROSTAT_AGENCY_SOURCE

COLUMN_ORDER: list[str] = CANONICAL_COLUMNS + [
    "product_canonical",
    "category",
    "geo",
    "country_id",
]

KEY_COLS: list[str] = [
    "date",
    "country",
    "source",
    "metric_type",
    "product_native",
]


def _derive_canonical_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    natives = out["product_native"].astype(str)
    sub = natives.map(
        lambda p: canonical_subcategory(p, source=_PRODUCT_MAP_SOURCE)
    )
    cat = natives.map(lambda p: canonical_category(p, source=_PRODUCT_MAP_SOURCE))
    out["product_canonical"] = sub.replace({"-": None})
    out["category"] = cat.replace({"-": None})
    # Drop blanks / missing subcategory from canonical sums
    out.loc[out["product_canonical"].isna() | (out["product_canonical"] == ""), "product_canonical"] = None
    out.loc[out["category"].isna() | (out["category"] == ""), "category"] = None
    return out


def build_from_eurostat_api(
    *,
    geos: Optional[list[str]] = None,
    start: str = "2008-01",
) -> pd.DataFrame:
    """Fetch all catalog geos (or a subset) and return warehouse-shaped rows."""
    if geos is None:
        geos = [g for g in GEO_CATALOG if g not in SKIP_GEOS]
    raw = fetch_gid_obs_geos(geos, start=start)
    if raw.empty:
        raise ValueError("Eurostat returned no GID_OBS rows")

    raw = raw[raw["siec"].isin(STORED_SIEC)].copy()
    raw = raw.dropna(subset=["value_ths_t"])
    now = datetime.now(tz=UTC)
    rows = []
    for geo, sl in raw.groupby("geo"):
        geo = str(geo).upper()
        if geo in SKIP_GEOS or geo not in GEO_CATALOG:
            continue
        country_id, display = GEO_CATALOG[geo]
        part = sl.copy()
        part["country"] = geo
        part["country_name"] = display
        part["country_id"] = country_id
        part["geo"] = geo
        part["source"] = SOURCE_ID
        part["metric_type"] = EUROSTAT_METRIC_TYPE
        part["product_native"] = part["siec"]
        part["product"] = part["siec"]
        part["value"] = part["value_ths_t"]
        part["unit"] = EUROSTAT_UNIT_NATIVE
        part["is_provisional"] = False
        part["source_file"] = f"eurostat/{DATASET_TAG}/{geo}"
        part["updated_at"] = now
        rows.append(part)

    if not rows:
        raise ValueError("No Eurostat rows after geo/product filter")

    df = pd.concat(rows, ignore_index=True)
    df = _derive_canonical_columns(df)
    df = _sort_and_clean(df)
    logger.info(
        "Built %s Eurostat rows, geos=%s, %s -> %s",
        f"{len(df):,}",
        df["geo"].nunique(),
        df["date"].min(),
        df["date"].max(),
    )
    return df


DATASET_TAG = "nrg_cb_oilm_gid_obs"


def _sort_and_clean(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"]).dt.normalize()
    for col in COLUMN_ORDER:
        if col not in out.columns:
            out[col] = None
    out = out[COLUMN_ORDER]
    out = out.dropna(subset=["date", "product_native", "value"])
    return out.sort_values(
        ["country", "date", "product_native"]
    ).reset_index(drop=True)


def save(df: pd.DataFrame, processed_root: Path) -> dict[str, Path]:
    """Write master parquet and per-country slices."""
    processed_root = Path(processed_root)
    paths: dict[str, Path] = {}

    master = processed_root / MASTER_PARQUET_REL
    master.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(master, index=False)
    paths["master"] = master
    logger.info("Saved master %s (%s rows)", master, f"{len(df):,}")

    for country_id, sl in df.groupby("country_id"):
        # National-primary countries still get a companion slice for fallback.
        rel = f"{country_id}/{country_id}_eurostat_oilm.parquet"
        path = processed_root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        sl.to_parquet(path, index=False)
        paths[str(country_id)] = path
        logger.info(
            "Saved %s (%s rows)%s",
            path,
            f"{len(sl):,}",
            " [companion]" if country_id in NATIONAL_PRIMARY_IDS else "",
        )
    return paths


def load_master(processed_root: Path) -> Optional[pd.DataFrame]:
    path = Path(processed_root) / MASTER_PARQUET_REL
    if not path.exists():
        return None
    return pd.read_parquet(path)
