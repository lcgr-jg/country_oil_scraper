"""
Country-specific hooks resolved from reference modules + countries.yaml.

New countries should work by YAML entry + reference module; this module
centralises discovery of JODI compare helpers and unit metadata.
"""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd

from analytics.units import convert_series
from warehouse.registry import CountryConfig, import_reference_module


def load_reference(cfg: CountryConfig) -> Any | None:
    if not cfg.reference_module:
        return None
    return import_reference_module(cfg.reference_module)


def resolve_jodi_ref_area(cfg: CountryConfig, ref: Any | None = None) -> str:
    if cfg.jodi_ref_area:
        return cfg.jodi_ref_area
    ref = ref if ref is not None else load_reference(cfg)
    if ref is not None:
        return str(getattr(ref, "JODI_REF_AREA", cfg.country_code))
    return cfg.country_code


def resolve_source_id(cfg: CountryConfig, ref: Any | None = None) -> str:
    """
    Dataset key for ``PRODUCT_KIND_MAP`` and ``fact_observations.source``.

    Reference modules usually expose ``SOURCE_ID``; Thailand (EPPO) and Italy
    (MASE) only define ``*_DATASET_SOURCE`` today — discover those before
    falling back to ``country_id`` (which is not a product_map source key).
    """
    ref = ref if ref is not None else load_reference(cfg)
    if ref is not None:
        sid = getattr(ref, "SOURCE_ID", None)
        if sid:
            return str(sid)
        for name in sorted(dir(ref)):
            if name.endswith("_DATASET_SOURCE"):
                val = getattr(ref, name, None)
                if val:
                    return str(val)
    return cfg.country_id


def resolve_unit_native(cfg: CountryConfig, ref: Any | None = None) -> Optional[str]:
    if cfg.unit_native:
        return cfg.unit_native
    ref = ref if ref is not None else load_reference(cfg)
    if ref is None:
        return None
    if cfg.unit_native_attr:
        return getattr(ref, cfg.unit_native_attr, None)
    for attr in (
        "SSB_UNIT_NATIVE",
        "ARE_UNIT_NATIVE",
        "SSSU_UNIT_NATIVE",
        "KNOC_UNIT_NATIVE",
        "DGEG_UNIT_NATIVE",
        "UK_UNIT_NATIVE",
        "MEKH_UNIT_NATIVE",
        "BAFA_UNIT_NATIVE",
        "MASE_UNIT_NATIVE",
        "CORES_UNIT_NATIVE",
        "MOEA_UNIT_NATIVE",
        "EPPO_UNIT_NATIVE",
        "METI_UNIT_KL",
    ):
        val = getattr(ref, attr, None)
        if val:
            return str(val)
    return None


def resolve_jet_product_native(cfg: CountryConfig, ref: Any | None = None) -> Optional[str]:
    if cfg.jet_product_native:
        return cfg.jet_product_native
    ref = ref if ref is not None else load_reference(cfg)
    if ref is None:
        return None
    for attr in ("PRODUCT_JET_KEROSENE", "JET_PRODUCT_NATIVE"):
        val = getattr(ref, attr, None)
        if val:
            return str(val)
    return None


def resolve_jodi_series_fn(ref: Any | None) -> Any | None:
    if ref is None:
        return None
    if hasattr(ref, "compute_jodi_compare_kt"):
        return ref.compute_jodi_compare_kt
    for name in sorted(dir(ref)):
        if name.endswith("_series_for_jodi"):
            return getattr(ref, name)
    return None


def prepare_values_for_conversion(
    df: pd.DataFrame,
    unit: Any,
) -> tuple[pd.DataFrame, Any]:
    """
    Normalise agency-native units before analytics.units.convert_series.

    Some sources report metric tonnes as ``t``; the converter expects ``kt``.
    """
    out = df.copy()
    if isinstance(unit, pd.Series):
        units = unit.astype(str).str.strip()
        tonne = units.str.lower().isin({"t", "tonne", "tonnes"})
        if tonne.any():
            out.loc[tonne, "value"] = (
                pd.to_numeric(out.loc[tonne, "value"], errors="coerce") / 1000
            )
            units = units.where(~tonne, "kt")
        return out, units

    if str(unit).strip().lower() in {"t", "tonne", "tonnes"}:
        out["value"] = pd.to_numeric(out["value"], errors="coerce") / 1000
        return out, "kt"

    return out, unit


def normalize_official_frame(df: pd.DataFrame, cfg: CountryConfig) -> pd.DataFrame:
    """Align heterogeneous country parquets to the warehouse column names."""
    out = df.copy()
    product_col = cfg.product_column or "product_native"
    value_col = cfg.value_column or "value"

    if product_col != "product_native" and product_col in out.columns:
        out["product_native"] = out[product_col].astype(str)
    elif "product_native" not in out.columns and "product" in out.columns:
        out["product_native"] = out["product"].astype(str)

    if value_col != "value" and value_col in out.columns:
        out["value"] = pd.to_numeric(out[value_col], errors="coerce")
    elif "value" not in out.columns:
        for candidate in ("value_000mt", "obs_value"):
            if candidate in out.columns:
                out["value"] = pd.to_numeric(out[candidate], errors="coerce")
                break

    if "metric_type" not in out.columns:
        out["metric_type"] = cfg.demand_metric_type

    if "is_provisional" not in out.columns:
        out["is_provisional"] = False

    return out


def exclude_aggregate_total_rows(df: pd.DataFrame) -> pd.DataFrame:
    """
    Drop headline-total rows kept in country parquets for audit only.

    PPAC (India) sets ``is_total_row=True`` on ``TOTAL`` / ``All Products total``
    lines. Those must not enter demand sums or the warehouse dashboard.
    """
    if "is_total_row" not in df.columns:
        return df
    return df[~df["is_total_row"].fillna(False)].copy()


def build_official_jodi_panels(
    demand: pd.DataFrame,
    cfg: CountryConfig,
    *,
    ref: Any | None = None,
) -> pd.DataFrame:
    """Aggregate official demand to JODI compare panels (kbd)."""
    ref = ref if ref is not None else load_reference(cfg)
    if ref is None:
        return pd.DataFrame(columns=["date", "value_kbd", "panel", "is_provisional"])

    jodi_compare = getattr(ref, "JODI_COMPARE_SERIES", {}) or {}
    series_fn = resolve_jodi_series_fn(ref)
    if not jodi_compare or series_fn is None:
        return pd.DataFrame(columns=["date", "value_kbd", "panel", "is_provisional"])

    frames: list[pd.DataFrame] = []
    for key, spec in jodi_compare.items():
        sl = _call_jodi_series_fn(series_fn, demand, key, spec, ref)
        if sl is None or sl.empty:
            continue
        panel = getattr(spec, "panel", str(key))
        frames.append(sl.assign(panel=panel))

    if not frames:
        return pd.DataFrame(columns=["date", "value_kbd", "panel", "is_provisional"])
    return pd.concat(frames, ignore_index=True)


def _call_jodi_series_fn(
    series_fn: Any,
    demand: pd.DataFrame,
    key: str,
    spec: Any,
    ref: Any,
) -> pd.DataFrame:
    fn_name = getattr(series_fn, "__name__", "")

    if fn_name == "compute_jodi_compare_kt":
        d = demand.copy()
        if "value" not in d.columns and "value_native" in d.columns:
            d["value"] = d["value_native"]
        sl = series_fn(d, key)
        if sl.empty:
            return sl
        kind = getattr(spec, "product_kind", None)
        sl = sl.copy()
        sl["value_kbd"] = convert_series(
            sl["value_kt"],
            "kt",
            "kbd",
            product_kind=kind,
            date=sl["date"],
        )
        return sl[["date", "value_kbd", "is_provisional"]]

    try:
        sl = series_fn(demand, key, value_col="value_kbd")
    except TypeError:
        sl = series_fn(demand, key)
    if sl.empty:
        return sl
    if "value_kbd" not in sl.columns and "value" in sl.columns:
        sl = sl.rename(columns={"value": "value_kbd"})
    keep = [c for c in ("date", "value_kbd", "is_provisional") if c in sl.columns]
    return sl[keep].copy()


def call_seasonality_chart_inputs(
    fn: Any,
    demand: pd.DataFrame,
    demand_canonical: pd.DataFrame,
    *,
    view: str,
    value_col: str = "value_kbd",
) -> tuple[pd.DataFrame, str, list[str], dict[str, str], str]:
    """
    Invoke ``seasonality_chart_inputs`` regardless of parameter order.

    Norway-style: ``(demand, demand_canonical, *, view=...)``
    Korea/Japan-style: ``(view, *, demand=..., demand_canonical=...)``
    """
    import inspect

    params = list(inspect.signature(fn).parameters.keys())
    if params and params[0] == "view":
        return fn(view, demand=demand, demand_canonical=demand_canonical)
    return fn(demand, demand_canonical, view=view, value_col=value_col)
