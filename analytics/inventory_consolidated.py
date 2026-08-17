"""
analytics.inventory_consolidated
────────────────────────────────
Build a long-form national closing-stock table (``CLOSTLV``) rolled up to
``product_canonical``, exportable to CSV for Tableau / PyGWalker, and pivot
into country × month inventory matrices.

Country coverage is driven by ``reference/inventory_sources.csv`` — append a
row there when onboarding a new national source.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Iterable, Literal, Optional, Union

import pandas as pd

from analytics.products import SUBCATEGORY_TO_PRODUCT_KIND
from analytics.units import convert_series

logger = logging.getLogger(__name__)

_ANALYTICS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _ANALYTICS_DIR.parent
_DEFAULT_SOURCES_CSV = _PROJECT_ROOT / "reference" / "inventory_sources.csv"
_DEFAULT_OUTPUT_CSV = (
    _PROJECT_ROOT / "data" / "processed" / "inventory" / "country_stocks_consolidated.csv"
)

# Display units supported by ``convert_value_column``. ``mbbl`` is kb ÷ 1000
# (million barrels); not part of analytics.units because stocks are stored as kb.
DisplayUnit = Literal["kb", "mbbl", "kt", "ML", "kL"]

_MONTH_LABELS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)

# Known Sub-category typos / legacy spellings → canonical product_canonical.
PRODUCT_CANONICAL_ALIASES: dict[str, str] = {
    "Fuel oil": "Fuel Oil",
}


def normalize_product_canonical(series: pd.Series) -> pd.Series:
    """Collapse legacy product_canonical labels before cross-country rollups."""
    out = series.astype("string")
    return out.replace(PRODUCT_CANONICAL_ALIASES)


def load_inventory_sources(
    sources_csv: Optional[Union[str, Path]] = None,
) -> pd.DataFrame:
    """Load ``reference/inventory_sources.csv`` (comment lines ignored)."""
    path = Path(sources_csv) if sources_csv is not None else _DEFAULT_SOURCES_CSV
    df = pd.read_csv(path, comment="#")
    required = {
        "country_key",
        "display_name",
        "parquet_subdir",
        "parquet_filename",
        "metric_type",
        "sort_order",
    }
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"{path} missing columns: {sorted(missing)}")
    return df.sort_values("sort_order", kind="stable").reset_index(drop=True)


def ytd_month_starts(
    year: int,
    *,
    as_of: Optional[date] = None,
) -> list[pd.Timestamp]:
    """Month-start timestamps from January through the YTD cutoff for ``year``."""
    as_of = as_of or date.today()
    if year > as_of.year:
        return []
    last_month = 12 if year < as_of.year else as_of.month
    return [pd.Timestamp(year, month, 1) for month in range(1, last_month + 1)]


def _product_kind_series(product_canonical: pd.Series) -> pd.Series:
    pc = product_canonical.astype("string")
    return pc.map(
        lambda x: SUBCATEGORY_TO_PRODUCT_KIND.get(str(x))
        if pd.notna(x) and str(x) not in ("<NA>", "nan")
        else None
    )


def _values_to_kb(frame: pd.DataFrame, *, source_id: str) -> pd.Series:
    """Convert native stock levels to thousand barrels (kb)."""
    if frame.empty:
        return pd.Series(dtype="float64")

    # Japan METI: tonnes for some products; value is in whole tonnes (÷1000 → kt).
    if source_id == "japan_meti_domestic_sales":
        from reference.japan import UNITS_KIND

        out = pd.Series(index=frame.index, dtype="float64")
        sub = frame.assign(product_kind=frame["product_native"].map(UNITS_KIND))
        for (unit, kind), grp in sub.groupby(["unit", "product_kind"], dropna=False):
            m = grp.index
            if unit == "t":
                out.loc[m] = convert_series(
                    grp["value"] / 1000,
                    "kt",
                    "kb",
                    product_kind=kind,
                    date=grp["date"],
                )
            else:
                out.loc[m] = convert_series(
                    grp["value"],
                    "kL",
                    "kb",
                    product_kind=kind,
                    date=grp["date"],
                )
        return out

    kinds = _product_kind_series(frame["product_canonical"])
    out = pd.Series(index=frame.index, dtype="float64")
    sub = frame.assign(_kind=kinds)
    for (unit, kind), grp in sub.groupby(["unit", "_kind"], dropna=False):
        m = grp.index
        kind_arg = kind if pd.notna(kind) else None
        # kt sources (e.g. UK DESNZ) may tag bundled rows as canonical Others.
        if kind_arg is None and str(unit) in {"kt", "ktoe"}:
            kind_arg = "other"
        out.loc[m] = convert_series(
            grp["value"],
            str(unit),
            "kb",
            product_kind=kind_arg,
            date=grp["date"],
        )
    return out


def _infer_source_id(frame: pd.DataFrame) -> str:
    if "source" not in frame.columns or frame["source"].dropna().empty:
        return ""
    return str(frame["source"].iloc[0])


def _load_country_clostlv(
    source_row: pd.Series,
    *,
    processed_dir: Path,
) -> pd.DataFrame:
    """Read one country parquet and return CLOSTLV rows with ``value_kb``."""
    parquet_path = (
        processed_dir / str(source_row["parquet_subdir"]) / str(source_row["parquet_filename"])
    )
    country_key = str(source_row["country_key"])
    display_name = str(source_row["display_name"])
    metric_type = str(source_row["metric_type"])

    if not parquet_path.exists():
        logger.warning("Missing parquet for %s: %s", country_key, parquet_path)
        return pd.DataFrame()

    df = pd.read_parquet(parquet_path)
    df["date"] = pd.to_datetime(df["date"])

    if "metric_type" not in df.columns:
        logger.warning("%s parquet has no metric_type column — skipped", country_key)
        return pd.DataFrame()

    stocks = df[df["metric_type"].astype(str) == metric_type].copy()
    if stocks.empty:
        return pd.DataFrame()

    if "product_canonical" not in stocks.columns:
        logger.warning("%s parquet has no product_canonical — skipped", country_key)
        return pd.DataFrame()

    stocks = stocks[stocks["product_canonical"].notna()].copy()
    if stocks.empty:
        return pd.DataFrame()

    source_id = _infer_source_id(stocks)
    stocks["value_kb"] = _values_to_kb(stocks, source_id=source_id)

    stocks["country_key"] = country_key
    stocks["country"] = display_name
    stocks["value_native"] = pd.to_numeric(stocks["value"], errors="coerce")
    stocks["unit_native"] = stocks["unit"].astype(str)

    prov = stocks["is_provisional"] if "is_provisional" in stocks.columns else False
    stocks["is_provisional"] = prov

    return stocks


def build_consolidated_inventory(
    *,
    processed_dir: Optional[Union[str, Path]] = None,
    sources_csv: Optional[Union[str, Path]] = None,
    year: Optional[int] = None,
    product_canonical: Optional[Union[str, Iterable[str]]] = None,
) -> pd.DataFrame:
    """
    Long-form national CLOSTLV panel across all registry countries.

    Returns one row per (country, date, product_canonical) after summing
    native sub-rows that map to the same canonical product.
    """
    proc = Path(processed_dir) if processed_dir is not None else _PROJECT_ROOT / "data" / "processed"
    sources = load_inventory_sources(sources_csv)

    parts: list[pd.DataFrame] = []
    for _, row in sources.iterrows():
        part = _load_country_clostlv(row, processed_dir=proc)
        if not part.empty:
            parts.append(part)

    if not parts:
        return _empty_consolidated()

    out = pd.concat(parts, ignore_index=True)
    out["product_canonical"] = normalize_product_canonical(out["product_canonical"])

    if year is not None:
        out = out[out["date"].dt.year == year]

    if product_canonical is not None:
        targets = {
            PRODUCT_CANONICAL_ALIASES.get(t, t)
            for t in (
                {product_canonical}
                if isinstance(product_canonical, str)
                else set(product_canonical)
            )
        }
        out = out[out["product_canonical"].astype(str).isin(targets)]

    grouped = (
        out.groupby(
            ["country_key", "country", "date", "product_canonical"],
            as_index=False,
            dropna=False,
        )
        .agg(
            metric_type=("metric_type", "first"),
            value_native=("value_native", "sum"),
            unit_native=("unit_native", "first"),
            value_kb=("value_kb", "sum"),
            is_provisional=("is_provisional", "max"),
            source=("source", "first"),
        )
    )

    grouped["year"] = grouped["date"].dt.year.astype("int64")
    grouped["month"] = grouped["date"].dt.month.astype("int64")
    grouped["month_label"] = grouped["month"].map(
        lambda m: _MONTH_LABELS[int(m) - 1] if 1 <= int(m) <= 12 else str(m)
    )
    return grouped.sort_values(
        ["country_key", "product_canonical", "date"],
        kind="stable",
        ignore_index=True,
    )


def _empty_consolidated() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "country_key",
            "country",
            "date",
            "product_canonical",
            "metric_type",
            "value_native",
            "unit_native",
            "value_kb",
            "is_provisional",
            "source",
            "year",
            "month",
            "month_label",
        ]
    )


def convert_value_column(
    df: pd.DataFrame,
    target_unit: DisplayUnit,
    *,
    value_kb_col: str = "value_kb",
) -> pd.Series:
    """Convert ``value_kb`` to the requested display unit."""
    kb = pd.to_numeric(df[value_kb_col], errors="coerce")
    if target_unit == "kb":
        return kb
    if target_unit == "mbbl":
        return kb / 1000.0

    kinds = _product_kind_series(df["product_canonical"])
    return convert_series(
        kb,
        "kb",
        target_unit,
        product_kind=kinds,
        date=df["date"],
    )


def add_display_value(
    df: pd.DataFrame,
    target_unit: DisplayUnit,
) -> pd.DataFrame:
    """Return a copy with ``value`` and ``unit`` columns for ``target_unit``."""
    out = df.copy()
    out["value"] = convert_value_column(out, target_unit)
    out["unit"] = target_unit
    return out


def save_consolidated_csv(
    df: pd.DataFrame,
    path: Optional[Union[str, Path]] = None,
    *,
    target_unit: Optional[DisplayUnit] = None,
) -> Path:
    """Write consolidated inventory to CSV (creates parent dirs)."""
    out_path = Path(path) if path is not None else _DEFAULT_OUTPUT_CSV
    out_path.parent.mkdir(parents=True, exist_ok=True)

    to_write = add_display_value(df, target_unit) if target_unit else df.copy()
    if target_unit and "value_kb" in to_write.columns:
        # Keep kb for tools that prefer a fixed cross-country scale.
        cols = [c for c in to_write.columns if c not in ("value", "unit")]
        cols.extend(["value", "unit"])
        to_write = to_write[cols]

    to_write.to_csv(out_path, index=False)
    logger.info("Wrote %s (%d rows)", out_path, len(to_write))
    return out_path


def _append_total_row(
    wide: pd.DataFrame,
    *,
    total_label: str = "Total",
) -> pd.DataFrame:
    """Sum each month column across countries (ignores NaN; all-NaN → NaN)."""
    total = wide.sum(axis=0, min_count=1)
    total.name = total_label
    return pd.concat([wide, total.to_frame().T])


def inventory_levels_table(
    consolidated: pd.DataFrame,
    *,
    product_canonical: str,
    year: int,
    target_unit: DisplayUnit = "mbbl",
    as_of: Optional[date] = None,
    missing_label: Optional[str] = "N/a",
    include_total: bool = False,
    total_label: str = "Total",
    sources_csv: Optional[Union[str, Path]] = None,
) -> pd.DataFrame:
    """
    Country × YTD month pivot for one canonical product.

    Missing cells (country has no stock source or month not yet reported)
    become ``missing_label`` when set, else NaN.

    When ``include_total`` is True, appends a ``total_label`` row summing
    each month across countries (NaN months where no country reported).
    """
    sources = load_inventory_sources(sources_csv)
    countries = sources["display_name"].tolist()
    months = ytd_month_starts(year, as_of=as_of)
    if not months:
        wide = pd.DataFrame(index=countries)
        wide.index.name = "country"
        return wide

    month_labels = [_MONTH_LABELS[m.month - 1] for m in months]

    sub = consolidated[
        consolidated["product_canonical"].astype(str) == product_canonical
    ].copy()
    if sub.empty:
        wide = pd.DataFrame(index=countries, columns=month_labels, dtype="float64")
        wide.index.name = "country"
        if missing_label is not None:
            return wide.fillna(missing_label)
        return wide

    sub["value_display"] = convert_value_column(sub, target_unit)
    sub = sub[sub["date"].isin(months)]

    wide = (
        sub.pivot_table(
            index="country",
            columns="date",
            values="value_display",
            aggfunc="sum",
        )
        .reindex(index=countries, columns=months)
    )
    wide.columns = month_labels
    wide.index.name = "country"

    if target_unit == "mbbl":
        wide = wide.round(3)
    elif target_unit == "kb":
        wide = wide.round(1)
    else:
        wide = wide.round(2)

    if include_total:
        wide = _append_total_row(wide, total_label=total_label)

    if missing_label is not None:
        return wide.where(wide.notna(), missing_label)
    return wide


__all__ = [
    "DisplayUnit",
    "PRODUCT_CANONICAL_ALIASES",
    "load_inventory_sources",
    "normalize_product_canonical",
    "ytd_month_starts",
    "build_consolidated_inventory",
    "convert_value_column",
    "add_display_value",
    "save_consolidated_csv",
    "inventory_levels_table",
]
