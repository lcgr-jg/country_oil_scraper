"""
analytics.products
──────────────────
Maps source-specific product labels to **density / conversion kinds** used by
``analytics.units`` (e.g. ``\"diesel\"``, ``\"gasoline\"``).

Phase 5c (2026)
---------------
The authoritative product vocabulary lives in ``reference/product_map.csv``.
This module **derives** label→kind maps from that CSV at import time, plus a
small set of explicit overrides where the CSV taxonomy and the units module
diverge (e.g. ethanol blend density).

``infer_product_kind(label, source)`` is the main entry point for notebooks
and ``convert_series`` call sites that still think in native labels.

Relationship to ``product_canonical``
---------------------------------------
Parquet columns ``product_canonical`` / ``category`` come from the CSV
``Sub-category`` / ``Category``.  **Kind** (this module) is a *second*
projection: Sub-category → lowercase key into ``analytics.units.BBL_PER_TONNE``.
``analytics.unified.load_unified`` imports ``SUBCATEGORY_TO_PRODUCT_KIND`` from
here so there is only one Sub-category → kind table.
"""

from __future__ import annotations

import functools
from typing import Optional

import pandas as pd

# --------------------------------------------------------------------------- #
#  Sub-category (product_map) → units.py product_kind
# --------------------------------------------------------------------------- #
# Must stay in sync with BBL_PER_TONNE keys in analytics.units (except None,
# which means "no density-based conversion").

SUBCATEGORY_TO_PRODUCT_KIND: dict[str, Optional[str]] = {
    "Diesel": "diesel",
    "Gasoline": "gasoline",
    "Jet Fuel": "jet",
    "Kerosene": "kerosene",
    "LPG": "lpg",
    "Naphtha": "naphtha",
    "Fuel Oil": "fuel_oil",
    "Gasoil": "diesel",
    "Lubricants / Grease": "lubes",
    "Bitumen": "bitumen",
    "Coke": "fuel_oil",
    "Others": None,
    "Wax": "naphtha",
    "Grease": "lubes",
    "Lubricants": "lubes",
}

# Explicit (Source, Product_name) → kind overrides where the CSV Sub-category
# alone would be wrong or too coarse for unit conversion.
_PRODUCT_KIND_OVERRIDES: dict[tuple[str, str], str] = {
    # CSV tags Ethanol-blended as Gasoline; IEA-style density uses ethanol row.
    #("DCCEEW", "Ethanol-blended fuel"): "ethanol",
    # JODI KEROSENE is a parent aggregate in the CSV; legacy charts still ask
    # for a single kind — keep kerosene density (documented limitation).
    ("JODI", "KEROSENE"): "kerosene",
    ("JODI", "ONONSPEC"): "other",
}

# Keys used by notebooks / config (dataset-style IDs) → Source column in CSV
_SOURCE_KEY_TO_CSV: dict[str, str] = {
    "dceew_petroleum_statistics": "DCCEEW",
    "eppo_petroleum_sales": "EPPO",
    "jodi": "JODI",
    "ppac": "PPAC",
    "mase_consumi_petroliferi": "MASE",
    "korea_petroleum_consumption": "KNOC",
    "japan_meti_domestic_sales": "METI",
    "taiwan_petroleum_consumption": "MOEA",
    "portugal_petroleum_sales": "DGEG",
    "uk_energy_trends_consumption": "DESNZ",
    "uk_energy_trends_stocks": "DESNZ",
}

CANONICAL_KIND_LABEL: dict[str, str] = {
    "diesel": "Diesel",
    "gasoline": "Gasoline",
    "jet": "Jet fuel",
    "kerosene": "Kerosene",
    "lpg": "LPG",
    "naphtha": "Naphtha",
    "fuel_oil": "Fuel oil",
    "crude": "Crude oil",
    "condensate": "Condensate",
    "bitumen": "Bitumen",
    "lubes": "Lubes & greases",
    "ethanol": "Ethanol-blended",
    "other": "Other products",
}


def _row_kind(
    row: pd.Series,
    pm_index: dict[tuple[str, str], pd.Series],
    *,
    csv_source: str,
) -> Optional[str]:
    """Resolve units.py product_kind for one product_map row (recurse parents)."""
    key = (csv_source, str(row["Product_name"]))
    ovr = _PRODUCT_KIND_OVERRIDES.get(key)
    if ovr is not None:
        return ovr

    sub = row["Sub-category"]
    if sub is not None and not pd.isna(sub) and str(sub) != "-":
        return SUBCATEGORY_TO_PRODUCT_KIND.get(str(sub))

    parent = row.get("Parent_product")
    if parent is None or (isinstance(parent, float) and pd.isna(parent)) or str(parent).strip() == "":
        return None
    parent_key = (csv_source, str(parent).strip())
    prow = pm_index.get(parent_key)
    if prow is None:
        return None
    return _row_kind(prow, pm_index, csv_source=csv_source)


@functools.lru_cache(maxsize=1)
def _build_product_kind_map() -> dict[str, dict[str, str]]:
    """Build native Product_name → kind for each analytics source key."""
    # Local import so importing analytics.products does not require reference/
    # on sys.path until this function runs (tests may patch).
    from reference.loaders import load_product_map

    pm = load_product_map()
    pm_index: dict[tuple[str, str], pd.Series] = {}
    for _, row in pm.iterrows():
        pm_index[(str(row["Source"]), str(row["Product_name"]))] = row

    out: dict[str, dict[str, str]] = {k: {} for k in _SOURCE_KEY_TO_CSV}

    for src_key, csv_src in _SOURCE_KEY_TO_CSV.items():
        sub = pm[pm["Source"] == csv_src]
        for _, row in sub.iterrows():
            label = str(row["Product_name"])
            kind = _row_kind(row, pm_index, csv_source=csv_src)
            if kind is None:
                continue
            # Last write wins if duplicate labels (should not happen)
            out[src_key][label] = kind
    return out


def _discover_dceew_aggregates(pm: pd.DataFrame) -> dict[str, str]:
    """Kind → DCCEEW native label for the row to use in cross-source totals."""
    dce = pm[pm["Source"] == "DCCEEW"]
    agg: dict[str, str] = {}

    # 1) [AGG] parents: infer kind from first [SUB] child's Sub-category
    for _, row in dce.iterrows():
        det = str(row.get("Product_details") or "")
        if not det.startswith("[AGG]"):
            continue
        pname = str(row["Product_name"])
        children = dce[dce["Parent_product"].astype(str) == pname]
        for _, ch in children.iterrows():
            chd = str(ch.get("Product_details") or "")
            if not chd.startswith("[SUB]"):
                continue
            sub = ch["Sub-category"]
            if sub is None or pd.isna(sub) or str(sub) == "-":
                continue
            k = SUBCATEGORY_TO_PRODUCT_KIND.get(str(sub))
            if k:
                agg[k] = pname
                break

    # 2) Primary totals without [AGG] tag (e.g. Diesel oil: total)
    for _, row in dce.iterrows():
        name = str(row["Product_name"])
        if "total" not in name.lower():
            continue
        sub = row["Sub-category"]
        if sub is None or pd.isna(sub) or str(sub) == "-":
            continue
        k = SUBCATEGORY_TO_PRODUCT_KIND.get(str(sub))
        if k and k not in agg:
            agg[k] = name

    # 3) Single-row families (e.g. Fuel oil)
    for _, row in dce.iterrows():
        det = str(row.get("Product_details") or "")
        if det.startswith(("[AGG]", "[SUB]", "[MIXED]", "[DERIVED]")):
            continue
        sub = row["Sub-category"]
        if sub is None or pd.isna(sub) or str(sub) == "-":
            continue
        k = SUBCATEGORY_TO_PRODUCT_KIND.get(str(sub))
        if k is None:
            continue
        fam = dce[dce["Sub-category"] == sub]
        if len(fam) == 1 and k not in agg:
            agg[k] = str(row["Product_name"])

    return agg


def _discover_jodi_aggregates(pm: pd.DataFrame) -> dict[str, str]:
    """Kind → JODI energy_product code for cross-source comparisons."""
    jo = pm[pm["Source"] == "JODI"]
    out: dict[str, str] = {}
    for _, row in jo.iterrows():
        det = str(row.get("Product_details") or "")
        if "[SUB]" in det or "[DERIVED]" in det:
            continue
        code = str(row["Product_name"])
        if code == "TOTPRODS":
            continue
        sub = row["Sub-category"]
        if sub is None or pd.isna(sub) or str(sub) == "-":
            if code == "KEROSENE":
                out["kerosene"] = "KEROSENE"
            continue
        k = SUBCATEGORY_TO_PRODUCT_KIND.get(str(sub))
        if k:
            out[k] = code
    return out


def _discover_eppo_aggregates(pm: pd.DataFrame) -> dict[str, str]:
    """Kind → EPPO native label for cross-source panels (primary row per kind)."""
    ep = pm[pm["Source"] == "EPPO"]
    out: dict[str, str] = {}
    for _, row in ep.iterrows():
        sub = row["Sub-category"]
        if sub is None or pd.isna(sub) or str(sub) == "-":
            continue
        k = SUBCATEGORY_TO_PRODUCT_KIND.get(str(sub))
        if k is None:
            continue
        label = str(row["Product_name"])
        if k not in out or label < out[k]:
            out[k] = label
    return out


def _discover_ppac_aggregates(pm: pd.DataFrame) -> dict[str, str]:
    """Kind → PPAC product label (primary row per kind for India totals)."""
    pp = pm[pm["Source"] == "PPAC"]
    out: dict[str, str] = {}
    for _, row in pp.iterrows():
        det = str(row.get("Product_details") or "")
        if det.startswith("[AGG]"):
            continue
        sub = row["Sub-category"]
        if sub is None or pd.isna(sub) or str(sub) == "-":
            continue
        k = SUBCATEGORY_TO_PRODUCT_KIND.get(str(sub))
        if k is None:
            continue
        # Deterministic: lexicographically first native label per kind
        label = str(row["Product_name"])
        if k not in out or label < out[k]:
            out[k] = label
    return out


def _discover_mase_aggregates(pm: pd.DataFrame) -> dict[str, str]:
    """Kind → MASE native headline row (Italy-vs-JODI compare)."""
    from reference.italy import REPORTING_PRODUCTS

    return dict(REPORTING_PRODUCTS)


@functools.lru_cache(maxsize=1)
def _build_canonical_aggregate_labels() -> dict[str, dict[str, str]]:
    from reference.loaders import load_product_map

    pm = load_product_map()
    return {
        "dceew_petroleum_statistics": _discover_dceew_aggregates(pm),
        "eppo_petroleum_sales": _discover_eppo_aggregates(pm),
        "jodi": _discover_jodi_aggregates(pm),
        "ppac": _discover_ppac_aggregates(pm),
        "mase_consumi_petroliferi": _discover_mase_aggregates(pm),
    }


# Public dicts — built once per process (refresh kernel after editing CSV).
PRODUCT_KIND_MAP: dict[str, dict[str, str]] = _build_product_kind_map()
CANONICAL_AGGREGATE_LABELS: dict[str, dict[str, str]] = _build_canonical_aggregate_labels()

# Back-compat aliases (historical names in notebooks)
DCCEEW_LABEL_TO_KIND: dict[str, str] = PRODUCT_KIND_MAP["dceew_petroleum_statistics"]
JODI_LABEL_TO_KIND: dict[str, str] = PRODUCT_KIND_MAP["jodi"]
PPAC_LABEL_TO_KIND: dict[str, str] = PRODUCT_KIND_MAP.get("ppac", {})
EPPO_LABEL_TO_KIND: dict[str, str] = PRODUCT_KIND_MAP.get("eppo_petroleum_sales", {})


def clear_products_caches() -> None:
    """Call after editing ``product_map.csv`` at runtime (e.g. in a notebook)."""
    from reference.loaders import load_product_map

    load_product_map.cache_clear()
    _build_product_kind_map.cache_clear()
    _build_canonical_aggregate_labels.cache_clear()
    global PRODUCT_KIND_MAP, CANONICAL_AGGREGATE_LABELS
    global DCCEEW_LABEL_TO_KIND, JODI_LABEL_TO_KIND, PPAC_LABEL_TO_KIND, EPPO_LABEL_TO_KIND
    PRODUCT_KIND_MAP = _build_product_kind_map()
    CANONICAL_AGGREGATE_LABELS = _build_canonical_aggregate_labels()
    DCCEEW_LABEL_TO_KIND = PRODUCT_KIND_MAP["dceew_petroleum_statistics"]
    JODI_LABEL_TO_KIND = PRODUCT_KIND_MAP["jodi"]
    PPAC_LABEL_TO_KIND = PRODUCT_KIND_MAP.get("ppac", {})
    EPPO_LABEL_TO_KIND = PRODUCT_KIND_MAP.get("eppo_petroleum_sales", {})


def infer_product_kind(label: str, source: str) -> str:
    """Return the units.py **product_kind** for a native label and source key.

    ``source`` must be one of:     ``dceew_petroleum_statistics``, ``eppo_petroleum_sales``, ``jodi``,
    ``ppac`` (matching ``PRODUCT_KIND_MAP`` / ``config`` conventions).

    Raises KeyError if unmapped — same contract as pre-Phase-5c.
    """
    if source not in PRODUCT_KIND_MAP:
        raise KeyError(
            f"Unknown source={source!r}. "
            f"Known sources: {sorted(PRODUCT_KIND_MAP)}."
        )
    mapping = PRODUCT_KIND_MAP[source]
    if label not in mapping:
        raise KeyError(
            f"No product_kind for label={label!r} in source={source!r}. "
            f"Add a row to reference/product_map.csv or an entry in "
            f"analytics/products.py::_PRODUCT_KIND_OVERRIDES."
        )
    return mapping[label]


__all__ = [
    "SUBCATEGORY_TO_PRODUCT_KIND",
    "infer_product_kind",
    "PRODUCT_KIND_MAP",
    "CANONICAL_KIND_LABEL",
    "CANONICAL_AGGREGATE_LABELS",
    "DCCEEW_LABEL_TO_KIND",
    "JODI_LABEL_TO_KIND",
    "PPAC_LABEL_TO_KIND",
    "EPPO_LABEL_TO_KIND",
    "clear_products_caches",
]
