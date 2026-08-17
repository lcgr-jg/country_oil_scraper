"""
analytics.unified
─────────────────
Load national agency parquets together with JODI into one long-form
DataFrame so you can compare **official country statistics** vs **JODI**
on the same ``metric_type`` and ``product_canonical`` keys.

Typical use
-----------
    from analytics.unified import load_unified

    df = load_unified(
        metric="TOTDEMO",
        product_canonical="Diesel",
        countries=["India", "Australia", "United States of America"],
    )
    # df contains PPAC + DCCEEW + JODI rows; filter df["source"] to compare.

Design
------
1. Read each parquet (cached per process).
2. Map columns to a common schema (``product_native`` varies by source).
3. Apply filters. If you omit ``category`` / ``product_canonical``, all
   rows matching the other filters are returned (can be large for JODI).
4. Convert ``value_native`` → ``value_target`` (default unit ``kbd``) via
   ``analytics.units.convert_series``.

Unit quirks
-----------
* **JODI ``KL``**: Treat as **ML** (megalitres) for conversion — not kL.
* **JODI ``KBBL``** → **kb** (thousand barrels). **``CONVBBL``** is left
  unmapped: it does not match ``kb`` numerically in cross-checks, so
  ``value_target`` stays NA unless we add a documented conversion later.
  Prefer **``KBBL``** or **``KBD``** rows for barrel-based comparisons.
* **JODI ``KTONS``** → **kt**; **KBD** → **kbd**.
* **Australia ``Mm3``**: Treated as **million m³** → value × 1e6 then as ``m3``.
* **``%``** and **``days``**: Not convertible to volume; ``value_target`` is NA.

Rows with null ``product_canonical`` (JODI aggregates, etc.) are **included**
when filters allow; density-based conversions may yield NA ``value_target``.
"""

from __future__ import annotations

import functools
import logging
from pathlib import Path
from typing import Iterable, Optional, Union

import pandas as pd

from analytics.products import SUBCATEGORY_TO_PRODUCT_KIND
from analytics.units import convert_series

logger = logging.getLogger(__name__)

_ANALYTICS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _ANALYTICS_DIR.parent
_DEFAULT_PROCESSED_DIR = _PROJECT_ROOT / "data" / "processed"


@functools.lru_cache(maxsize=1)
def _load_australia_parquet(processed_dir: str) -> pd.DataFrame:
    path = Path(processed_dir) / "australia" / "australia_petroleum_statistics.parquet"
    if not path.exists():
        raise FileNotFoundError(f"Australia parquet not found: {path}")
    return pd.read_parquet(path)


@functools.lru_cache(maxsize=1)
def _load_india_parquet(processed_dir: str) -> pd.DataFrame:
    path = Path(processed_dir) / "india" / "india_pt_consumption.parquet"
    if not path.exists():
        raise FileNotFoundError(f"India parquet not found: {path}")
    return pd.read_parquet(path)


@functools.lru_cache(maxsize=1)
def _load_jodi_secondary_parquet(processed_dir: str) -> pd.DataFrame:
    path = Path(processed_dir) / "jodi" / "jodi_secondary.parquet"
    if not path.exists():
        raise FileNotFoundError(f"JODI secondary parquet not found: {path}")
    return pd.read_parquet(path)


def clear_unified_caches() -> None:
    """Invalidate cached parquet reads after regenerating processed data."""
    _load_australia_parquet.cache_clear()
    _load_india_parquet.cache_clear()
    _load_jodi_secondary_parquet.cache_clear()


def _as_list(x: Optional[Union[str, Iterable[str]]]) -> Optional[list[str]]:
    if x is None:
        return None
    if isinstance(x, str):
        return [x]
    return list(x)


def _normalise_unit_for_conversion(
    source: str,
    unit_native: pd.Series,
    value_native: pd.Series,
) -> tuple[pd.Series, pd.Series]:
    """Return (unit_code_for_units_py, value_scaled) for convert_series."""
    u = unit_native.astype(str)
    v = pd.to_numeric(value_native, errors="coerce").astype("float64")
    out_u = u.copy()
    out_v = v.copy()

    if source != "JODI":
        # Australia: Mm3 → million cubic metres → m³ for units.py
        mask_mm3 = u == "Mm3"
        out_u.loc[mask_mm3] = "m3"
        out_v.loc[mask_mm3] = out_v.loc[mask_mm3] * 1_000_000.0
        return out_u, out_v

    # JODI
    mask_kl = u == "KL"
    out_u.loc[mask_kl] = "ML"

    mask_kbbl = u == "KBBL"
    out_u.loc[mask_kbbl] = "kb"
    # CONVBBL is *not* the same numeric scale as KBBL in JODI extracts — do not
    # alias it to kb without a documented factor. Leave as CONVBBL; conversion
    # fails cleanly → NA value_target (use KBBL or KBD rows for comparisons).

    mask_kt = u == "KTONS"
    out_u.loc[mask_kt] = "kt"

    mask_kbd = u == "KBD"
    out_u.loc[mask_kbd] = "kbd"

    return out_u, out_v


def _adapt_australia(df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime(df["date"]),
            "country": df["country_name"].astype(str),
            "source": "DCCEEW",
            "product_native": df["product_native"].astype(str),
            "product_canonical": df["product_canonical"],
            "category": df["category"],
            "metric_type": df["metric_type"].astype(str),
            "unit_native": df["unit"].astype(str),
            "value_native": pd.to_numeric(df["value"], errors="coerce"),
        }
    )


def _adapt_india(df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime(df["date"]),
            "country": pd.Series("India", index=df.index, dtype="string"),
            "source": "PPAC",
            "product_native": df["product"].astype(str),
            "product_canonical": df["product_canonical"],
            "category": df["category"],
            "metric_type": df["metric_type"].astype(str),
            "unit_native": df["unit_measure"].astype(str),
            "value_native": pd.to_numeric(df["value_000mt"], errors="coerce"),
        }
    )


def _adapt_jodi_secondary(df: pd.DataFrame) -> pd.DataFrame:
    cn = df["country_name"]
    if isinstance(cn.dtype, pd.CategoricalDtype):
        cn = cn.astype("string")
    else:
        cn = cn.astype("string")
    cn = cn.fillna("<no country>")

    return pd.DataFrame(
        {
            "date": pd.to_datetime(df["date"]),
            "country": cn,
            "source": "JODI",
            "product_native": df["energy_product"].astype(str),
            "product_canonical": df["product_canonical"],
            "category": df["category"],
            "metric_type": df["metric_type"].astype(str),
            "unit_native": df["unit_measure"].astype(str),
            "value_native": pd.to_numeric(df["obs_value"], errors="coerce"),
        }
    )


def _product_kind_series(product_canonical: pd.Series) -> pd.Series:
    pc = product_canonical.astype("string")
    return pc.map(
        lambda x: SUBCATEGORY_TO_PRODUCT_KIND.get(str(x))
        if pd.notna(x) and str(x) not in ("<NA>", "nan")
        else None
    )


def _apply_filters(
    df: pd.DataFrame,
    *,
    metric: list[str],
    category: Optional[list[str]],
    product_canonical: Optional[list[str]],
    countries: Optional[list[str]],
    start: Optional[pd.Timestamp],
    end: Optional[pd.Timestamp],
) -> pd.DataFrame:
    out = df[df["metric_type"].isin(metric)]
    if category is not None:
        out = out[out["category"].astype("string").isin(category)]
    if product_canonical is not None:
        out = out[out["product_canonical"].astype("string").isin(product_canonical)]
    if countries is not None:
        out = out[out["country"].isin(countries)]
    if start is not None:
        out = out[out["date"] >= start]
    if end is not None:
        out = out[out["date"] <= end]
    return out


def _convert_block(
    value: pd.Series,
    from_unit: str,
    to_unit: str,
    product_kind: Optional[pd.Series],
    date: pd.Series,
) -> pd.Series:
    if value.empty:
        return value.copy()
    return convert_series(
        value.astype("float64"),
        from_unit,
        to_unit,
        product_kind=product_kind,
        date=date,
    )


def _compute_value_target(df: pd.DataFrame, target_unit: str) -> pd.Series:
    if df.empty:
        return pd.Series(dtype="Float64")

    date_s = pd.to_datetime(df["date"])
    kinds = _product_kind_series(df["product_canonical"])
    out = pd.Series(pd.NA, index=df.index, dtype="Float64")

    # Normalise units row-wise by source (JODI KL→ML, KBBL→kb, …).
    norm_u = pd.Series(index=df.index, dtype=object)
    norm_v = pd.Series(index=df.index, dtype="float64")
    for src in df["source"].unique():
        m_src = df["source"] == src
        uu, vv = _normalise_unit_for_conversion(
            str(src),
            df.loc[m_src, "unit_native"],
            df.loc[m_src, "value_native"],
        )
        norm_u.loc[m_src] = uu
        norm_v.loc[m_src] = vv

    for u in norm_u.dropna().unique():
        m = norm_u == u
        if not m.any():
            continue
        sub_v = norm_v.loc[m]
        sub_d = date_s.loc[m]
        sub_k = kinds.loc[m]
        kind_arg: Optional[Union[str, pd.Series]] = (
            None if sub_k.isna().all() else sub_k
        )
        u_str = str(u)
        if u_str in ("%", "days"):
            continue
        try:
            out.loc[m] = _convert_block(
                sub_v, u_str, target_unit, product_kind=kind_arg, date=sub_d
            ).astype("Float64")
        except (ValueError, TypeError) as e:
            logger.debug("conversion skip unit=%s n=%s: %s", u_str, int(m.sum()), e)
            out.loc[m] = pd.NA

    return out


def load_unified(
    *,
    metric: Union[str, Iterable[str]] = "TOTDEMO",
    category: Optional[Union[str, Iterable[str]]] = None,
    product_canonical: Optional[Union[str, Iterable[str]]] = None,
    countries: Optional[Iterable[str]] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    sources: Optional[Iterable[str]] = None,
    target_unit: str = "kbd",
    processed_dir: Optional[Union[str, Path]] = None,
) -> pd.DataFrame:
    """
    Load DCCEEW (Australia), PPAC (India), and JODI secondary in one frame.

    Use this to compare **national official statistics** vs **JODI** for the
    same country, metric, and canonical product — group or filter by
    ``source``.

    Parameters
    ----------
    metric
        Canonical metric code(s), e.g. ``\"TOTDEMO\"``.
    category, product_canonical
        Optional filters. If both omitted, all rows matching ``metric`` (and
        other filters) are returned.
    countries
        Country names as in parquets: ``\"Australia\"``, ``\"India\"``,
        ``\"United States of America\"``, …
    start, end
        Inclusive bounds; any input accepted by ``pd.to_datetime``.
    sources
        Subset of ``{\"DCCEEW\", \"PPAC\", \"JODI\"}``. Default: all three.
    target_unit
        Default ``\"kbd\"``. Rows that cannot be converted get NA in
        ``value_target``.
    processed_dir
        Root ``data/processed`` directory (default: under ``country_oil_scraper``).

    Returns
    -------
    DataFrame with:
        date, country, source, product_native, product_canonical, category,
        metric_type, unit_native, value_native, unit_target, value_target
    """
    proc_dir = Path(processed_dir) if processed_dir is not None else _DEFAULT_PROCESSED_DIR
    proc_key = str(proc_dir.resolve())

    metric_list = _as_list(metric)
    if not metric_list:
        raise ValueError("metric must be non-empty")

    src_set = (
        {"DCCEEW", "PPAC", "JODI"}
        if sources is None
        else {str(s) for s in sources}
    )
    allowed = {"DCCEEW", "PPAC", "JODI"}
    if bad := src_set - allowed:
        raise ValueError(f"Unknown sources {bad!r}. Allowed: {allowed}")

    t_start = pd.to_datetime(start) if start is not None else None
    t_end = pd.to_datetime(end) if end is not None else None

    cat_list = _as_list(category)
    pc_list = _as_list(product_canonical)
    country_list = list(countries) if countries is not None else None

    frames: list[pd.DataFrame] = []
    if "DCCEEW" in src_set:
        au = _adapt_australia(_load_australia_parquet(proc_key))
        frames.append(
            _apply_filters(
                au,
                metric=metric_list,
                category=cat_list,
                product_canonical=pc_list,
                countries=country_list,
                start=t_start,
                end=t_end,
            )
        )
    if "PPAC" in src_set:
        ind = _adapt_india(_load_india_parquet(proc_key))
        frames.append(
            _apply_filters(
                ind,
                metric=metric_list,
                category=cat_list,
                product_canonical=pc_list,
                countries=country_list,
                start=t_start,
                end=t_end,
            )
        )
    if "JODI" in src_set:
        jo = _adapt_jodi_secondary(_load_jodi_secondary_parquet(proc_key))
        frames.append(
            _apply_filters(
                jo,
                metric=metric_list,
                category=cat_list,
                product_canonical=pc_list,
                countries=country_list,
                start=t_start,
                end=t_end,
            )
        )

    cols = [
        "date",
        "country",
        "source",
        "product_native",
        "product_canonical",
        "category",
        "metric_type",
        "unit_native",
        "value_native",
        "unit_target",
        "value_target",
    ]
    if not frames:
        return pd.DataFrame(columns=cols)

    combined = pd.concat(frames, ignore_index=True)
    combined["unit_target"] = target_unit
    combined["value_target"] = _compute_value_target(combined, target_unit)

    return combined.sort_values(
        ["date", "country", "source", "metric_type", "product_native"],
        ignore_index=True,
    )


__all__ = ["load_unified", "clear_unified_caches"]
