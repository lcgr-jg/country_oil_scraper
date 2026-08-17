"""
reference.loaders
─────────────────
Cached read-only access to the project's canonical vocabularies.

Two reference files back this module:

  - ``product_map.csv``    answers "what *product* is this row about?"
                           (Diesel? Gasoline? Kerosene? Jet fuel?)

  - ``metric_types.yaml``  answers "what *kind* of measurement is this row?"
                           (Production? Consumption? Imports? Closing stocks?)

These are orthogonal axes of the same canonical vocabulary. Together they let
any data source — Australia, India, JODI, future Mexico — describe its data
in the same words, which is what makes cross-source queries trivial.

Two source-name vocabularies (heads-up)
---------------------------------------
The two files use *different* keys to identify a "source" by design:

    product_map.csv   Source column      e.g. "DCCEEW", "PPAC", "JODI", "METI"
                                         (agency-level — products travel
                                          across datasets within an agency)

    metric_types.yaml source_mappings:   e.g. "dceew_petroleum_statistics",
                                              "ppac_pt_consumption",
                                              "jodi_primary", "jodi_secondary"
                                         (dataset-level — metrics differ
                                          between JODI primary/secondary)

A processor module already knows both keys for its own source. The product
helpers below take the agency-level key; the metric helpers take the
dataset-level key. Each helper validates its argument against the relevant
file's known sources and raises a clear KeyError with the valid list if a
bad source is passed.

CSV column names vs. Parquet column names (heads-up)
----------------------------------------------------
The CSV taxonomy uses ``Category`` / ``Sub-category``; the parquet
schema uses ``category`` / ``product_canonical``. The rename is
deliberate — see the comment header at the top of ``product_map.csv``
for the full reasoning. In short:

      product_map.csv  ->  parquet column
      Category             category
      Sub-category         product_canonical
      Product_name         <native column, varies per source>
                           - India:     ``product``
                           - Australia: ``product_native`` (also copied to ``product``)
                           - JODI:      ``energy_product``

This module talks about the CSV side. Each processor does the rename
when writing its parquet.

Caching
-------
``load_product_map()`` and ``load_metric_types()`` are wrapped in
``functools.lru_cache(maxsize=1)``. The files are tiny (~kB) so cold-load
cost is sub-millisecond, but the cache prevents repeated disk reads across
hundreds of helper calls in a single pipeline run. If you edit a reference
file at runtime (e.g. in a notebook) and want to pick up the change, call
``load_product_map.cache_clear()`` (same for ``load_metric_types``).

Relationship to ``analytics/products.py``
-----------------------------------------
``analytics/products.py`` has a parallel set of dicts that map native labels
to a lowercase "kind" (e.g. ``"diesel"``, ``"gasoline"``) used by
``analytics/units.py`` for density-based unit conversions. That vocabulary
overlaps with the Sub-category vocabulary returned here, but the two are
kept separate intentionally — see the docstring there for details. Phase 4
final cleanup may unify them; for now both coexist.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Optional

import pandas as pd
import yaml

# --------------------------------------------------------------------------- #
#  Paths
# --------------------------------------------------------------------------- #

REFERENCE_DIR = Path(__file__).parent
PRODUCT_MAP_PATH = REFERENCE_DIR / "product_map.csv"
METRIC_TYPES_PATH = REFERENCE_DIR / "metric_types.yaml"


# --------------------------------------------------------------------------- #
#  Core loaders (cached)
# --------------------------------------------------------------------------- #

@functools.lru_cache(maxsize=1)
def load_product_map() -> pd.DataFrame:
    """
    Read ``reference/product_map.csv`` and return it as a typed DataFrame.

    Columns: Country, Source, Product_name, Category, Sub-category,
             Product_details, Parent_product

    The CSV uses ``#`` as a line-level comment marker so the top of the
    file can document the file's purpose, column meanings, and the
    Product_details [TAG] vocabulary. ``pd.read_csv(comment='#')`` skips
    those lines transparently. Don't use ``#`` inside data values.

    NOTE — CSV vs Parquet column naming:
        The CSV's ``Sub-category`` becomes the parquet column
        ``product_canonical``, and the CSV's ``Category`` becomes the
        parquet column ``category``. The rename happens in each
        processor (see ``processors/india_pt_consumption.py``,
        ``processors/jodi.py``, ``processors/australia_petroleum_statistics.py``).
        Reasoning lives in the comment header at the top of
        ``product_map.csv``.

    Cleanup applied:
      - ``Product_details`` NaN values are replaced with the empty string
        so callers can use ``.startswith()`` without crashing.
      - ``Parent_product`` blanks are left as ``NaN`` because pandas
        auto-coerces ``None`` to ``NaN`` in object columns anyway. Callers
        that want a Python ``None`` should use the ``parent_product()``
        helper below, which normalises NaN -> None at access time.

    Cached: file is re-read only after ``load_product_map.cache_clear()``.
    """
    if not PRODUCT_MAP_PATH.exists():
        raise FileNotFoundError(
            f"product_map.csv not found at {PRODUCT_MAP_PATH}. "
            f"Has the reference/ package been moved or deleted?"
        )

    # comment='#' lets us put a documentation header at the top of the
    # CSV without confusing pandas. See top of product_map.csv.
    df = pd.read_csv(PRODUCT_MAP_PATH, comment="#")

    # Normalise Product_details only: NaN -> "" so .startswith() always works.
    # (Parent_product is left as-is; helpers handle NaN at access time.)
    df["Product_details"] = df["Product_details"].fillna("")

    return df


@functools.lru_cache(maxsize=1)
def load_metric_types() -> dict:
    """
    Read ``reference/metric_types.yaml`` and return it as a parsed dict.

    Top-level structure:
        {
          "canonical": { "INDPROD": {"description": ..., "typical_units": ...}, ...},
          "source_mappings": {
              "dceew_petroleum_statistics": {"Sales of products": "TOTDEMO", ...},
              "ppac_pt_consumption": {...},
              "jodi_primary": {...},
              "jodi_secondary": {...},
          }
        }

    Cached: file is re-read only after ``load_metric_types.cache_clear()``.
    """
    if not METRIC_TYPES_PATH.exists():
        raise FileNotFoundError(
            f"metric_types.yaml not found at {METRIC_TYPES_PATH}."
        )
    with METRIC_TYPES_PATH.open(encoding="utf-8") as fp:
        return yaml.safe_load(fp) or {}


# --------------------------------------------------------------------------- #
#  Enumerations (also cached transitively via the loaders)
# --------------------------------------------------------------------------- #

def product_sources() -> list[str]:
    """Distinct Source values in product_map.csv (agency-level)."""
    return sorted(load_product_map()["Source"].dropna().unique().tolist())


def metric_sources() -> list[str]:
    """Source keys under ``metric_types.yaml`` source_mappings (dataset-level)."""
    return sorted((load_metric_types().get("source_mappings") or {}).keys())


def canonical_metric_codes() -> list[str]:
    """Canonical metric codes defined in ``metric_types.yaml`` (INDPROD, TOTDEMO, ...)."""
    return sorted((load_metric_types().get("canonical") or {}).keys())


# --------------------------------------------------------------------------- #
#  Internal helper
# --------------------------------------------------------------------------- #

def _product_row(native_name: str, source: str) -> pd.Series:
    """
    Find the unique row in product_map.csv for a given (native_name, source).

    Raises:
        KeyError: if ``source`` is unknown, or if no matching row exists.
        ValueError: if there are duplicate rows (shouldn't happen — indicates
                    a data quality issue in product_map.csv).
    """
    df = load_product_map()

    sources = product_sources()
    if source not in sources:
        raise KeyError(
            f"Unknown product source {source!r}. "
            f"Valid sources from product_map.csv: {sources}"
        )

    mask = (df["Source"] == source) & (df["Product_name"] == native_name)
    matches = df[mask]

    if matches.empty:
        # Provide a small preview of valid product names for this source to
        # help the caller debug the mismatch quickly.
        available = df.loc[df["Source"] == source, "Product_name"].tolist()
        preview = available[:10]
        more = f" ...and {len(available) - 10} more" if len(available) > 10 else ""
        raise KeyError(
            f"No product map entry for native_name={native_name!r} "
            f"in source={source!r}. Check reference/product_map.csv. "
            f"Available products for {source}: {preview}{more}"
        )

    if len(matches) > 1:
        raise ValueError(
            f"Duplicate product_map.csv entries for native_name={native_name!r} "
            f"in source={source!r}. This indicates a data quality issue — "
            f"please de-duplicate the file."
        )

    return matches.iloc[0]


# --------------------------------------------------------------------------- #
#  Product convenience helpers
# --------------------------------------------------------------------------- #

def canonical_subcategory(native_name: str, source: str) -> Optional[str]:
    """
    Return the canonical Sub-category for a given native product label.

    Returns ``None`` for rows whose Sub-category is ``-`` (i.e. rows excluded
    from cross-country sums — aggregates, mixed-content rows, sub-products
    whose parent is the primary). Callers wanting to know whether a row
    contributes to canonical sums should use ``is_primary()`` instead.

    Example:
        canonical_subcategory("HSD", source="PPAC") -> "Diesel"
        canonical_subcategory("TOTPRODS", source="JODI") -> None
    """
    row = _product_row(native_name, source)
    value = row["Sub-category"]
    if pd.isna(value) or value == "-":
        return None
    return value


def canonical_category(native_name: str, source: str) -> Optional[str]:
    """Return the canonical Category (e.g. "Distillates", "Gasoline")."""
    row = _product_row(native_name, source)
    value = row["Category"]
    if pd.isna(value) or value == "-":
        return None
    return value


def parent_product(native_name: str, source: str) -> Optional[str]:
    """
    Return the Product_name of this row's parent total, or ``None`` if this
    row has no parent (i.e. it's a primary or an aggregate at the top of its
    own hierarchy).

    Example:
        parent_product("Regular (<95 RON) (ML)", source="DCCEEW")
            -> "Automotive gasoline total (ML)"
    """
    row = _product_row(native_name, source)
    value = row["Parent_product"]
    # pandas auto-coerces blank cells to NaN even when we'd prefer None;
    # normalise here so callers get a clean Python value back.
    if pd.isna(value):
        return None
    return value


def is_primary(native_name: str, source: str) -> bool:
    """
    True if this row contributes to canonical cross-source sums (Sub-category
    is a real bucket, not ``-``).
    """
    return canonical_subcategory(native_name, source) is not None


def _has_tag(native_name: str, source: str, tag: str) -> bool:
    row = _product_row(native_name, source)
    details = row["Product_details"]
    return str(details).startswith(tag)


def is_aggregate(native_name: str, source: str) -> bool:
    """True if Product_details starts with ``[AGG]`` (super-aggregate)."""
    return _has_tag(native_name, source, "[AGG]")


def is_sub(native_name: str, source: str) -> bool:
    """True if Product_details starts with ``[SUB]`` (sub-product of a parent total)."""
    return _has_tag(native_name, source, "[SUB]")


def is_derived(native_name: str, source: str) -> bool:
    """True if Product_details starts with ``[DERIVED]`` (project-derived, e.g. X_OTHKERO)."""
    return _has_tag(native_name, source, "[DERIVED]")


# --------------------------------------------------------------------------- #
#  Metric convenience helpers
# --------------------------------------------------------------------------- #

def canonical_metric(native_label: str, source: str) -> str:
    """
    Return the canonical metric code (e.g. ``TOTDEMO``) for a native metric
    label in the given source's source_mappings block.

    Note the ``source`` here is the *dataset-level* key
    (e.g. ``"dceew_petroleum_statistics"``), not the agency-level key.

    Example:
        canonical_metric("Sales of products",
                         source="dceew_petroleum_statistics") -> "TOTDEMO"

    Raises:
        KeyError: if ``source`` is unknown or ``native_label`` has no mapping.
    """
    mappings = load_metric_types().get("source_mappings") or {}

    if source not in mappings:
        raise KeyError(
            f"Unknown metric source {source!r}. "
            f"Valid sources from metric_types.yaml: {sorted(mappings.keys())}"
        )

    source_block = mappings[source] or {}
    if native_label not in source_block:
        available = list(source_block.keys())
        preview = available[:10]
        more = f" ...and {len(available) - 10} more" if len(available) > 10 else ""
        raise KeyError(
            f"No metric mapping for native_label={native_label!r} "
            f"in source={source!r}. Check reference/metric_types.yaml. "
            f"Available labels: {preview}{more}"
        )

    return source_block[native_label]


def metric_description(code: str) -> str:
    """Return the prose description of a canonical metric code from the YAML."""
    canonical = load_metric_types().get("canonical") or {}
    if code not in canonical:
        raise KeyError(
            f"Unknown canonical metric code {code!r}. "
            f"Valid codes: {sorted(canonical.keys())}"
        )
    entry = canonical[code] or {}
    description = entry.get("description", "") or ""
    # YAML folded scalars introduce trailing newlines and indentation noise.
    return " ".join(str(description).split())


def metric_typical_units(code: str) -> list[str]:
    """Return the list of typical units declared in the YAML for a canonical code."""
    canonical = load_metric_types().get("canonical") or {}
    if code not in canonical:
        raise KeyError(
            f"Unknown canonical metric code {code!r}. "
            f"Valid codes: {sorted(canonical.keys())}"
        )
    entry = canonical[code] or {}
    return list(entry.get("typical_units", []) or [])


__all__ = [
    # Core loaders
    "load_product_map",
    "load_metric_types",
    # Enumerations
    "product_sources",
    "metric_sources",
    "canonical_metric_codes",
    # Product helpers
    "canonical_subcategory",
    "canonical_category",
    "parent_product",
    "is_primary",
    "is_aggregate",
    "is_sub",
    "is_derived",
    # Metric helpers
    "canonical_metric",
    "metric_description",
    "metric_typical_units",
]
