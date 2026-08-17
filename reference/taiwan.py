"""
reference.taiwan
────────────────
MOEA Energy Administration (Taiwan) Table 5-04 — petroleum products consumption.

Workbook sheet ``按油品別`` (by product) reports monthly consumption in
**ktoe** (千公噸油當量, thousand tonnes of oil equivalent). Years 2007–2024
appear as annual totals only; monthly detail begins 2025. Annual rows are
expanded to twelve flat monthly imputations (``is_provisional=True``) so
headline charts have a continuous series until true monthly history is found.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

from reference.loaders import is_primary, load_product_map

MOEA_AGENCY_SOURCE = "MOEA"
MOEA_DATASET_SOURCE = "taiwan_petroleum_consumption"
MOEA_METRIC_TYPE = "TOTDEMO"
MOEA_UNIT_NATIVE = "ktoe"

COUNTRY_CODE = "TW"
COUNTRY_NAME = "Taiwan"
SOURCE_ID = MOEA_DATASET_SOURCE

# Sheet and column layout (0-based indices on ``按油品別``).
PRODUCTS_SHEET = "按油品別"
SUPPLY_SHEET = "油品供給與轉變"
_HEADER_ROW_ZH = 2
_HEADER_ROW_EN = 3
_DATA_START_ROW = 4
_COL_PERIOD_LABEL = 0
_COL_TOTAL = 1
_COL_PRODUCTS: list[tuple[int, str]] = [
    (2, "lpg"),
    (3, "naphtha"),
    (4, "gasoline"),
    (5, "jet_fuel"),
    (6, "diesel"),
    (7, "fuel_oil"),
    (8, "others"),
]
_COL_GREGORIAN = 9
_COL_GREGORIAN_SUPPLY = 10  # 5-03 adds transformation-input column before Period

# English header row labels -> product_native (fallback if column index shifts).
_EN_HEADER_TO_NATIVE: dict[str, str] = {
    "LPG": "lpg",
    "Naphtha": "naphtha",
    "Motor Gasoline": "gasoline",
    "Jet Fuel": "jet_fuel",
    "Diesel Oil": "diesel",
    "Fuel Oil": "fuel_oil",
    "Others": "others",
}

DELIVERY_HEADLINE_NATIVE: frozenset[str] = frozenset(
    {"lpg", "naphtha", "gasoline", "jet_fuel", "diesel", "fuel_oil", "others"}
)

CHART_PRODUCTS: tuple[str, ...] = tuple(DELIVERY_HEADLINE_NATIVE)

SEASONALITY_NATIVE_PRODUCTS: tuple[str, ...] = CHART_PRODUCTS

SEASONALITY_PANELS_CANONICAL: tuple[str, ...] = (
    "Diesel",
    "Fuel oil",
    "Gasoline",
    "Jet fuel",
    "Kerosene",
    "LPG",
    "Naphtha",
    "Others",
)

DISPLAY_LABELS: dict[str, str] = {
    "lpg": "LPG",
    "naphtha": "Naphtha",
    "gasoline": "Gasoline",
    "jet_fuel": "Jet fuel",
    "diesel": "Diesel",
    "fuel_oil": "Fuel oil",
    "others": "Others",
}

UNITS_KIND: dict[str, str] = {
    "lpg": "lpg",
    "naphtha": "naphtha",
    "gasoline": "gasoline",
    "jet_fuel": "jet",
    "diesel": "diesel",
    "fuel_oil": "fuel_oil",
    "others": "other",
}

_PERIOD_MONTHLY_RE = re.compile(r"^(\d{4})/(\d{2})$")
_PERIOD_ANNUAL_RE = re.compile(r"^(\d{4})$")
_SKIP_LABEL_RE = re.compile(
    r"較|Compared|%|01-\d{2}月|/\d{2}-\d{2}$|/\d{2}-\d{2}",
    re.I,
)


@dataclass(frozen=True)
class JodiCompareSeries:
    key: str
    jodi_energy_product: str
    panel: str
    natives: frozenset[str]


JODI_COMPARE_SERIES: dict[str, JodiCompareSeries] = {
    "gasoline": JodiCompareSeries(
        "gasoline", "GASOLINE", "Gasoline", frozenset({"gasoline"})
    ),
    "diesel": JodiCompareSeries(
        "diesel", "GASDIES", "Diesel", frozenset({"diesel"})
    ),
    "jet_fuel": JodiCompareSeries(
        "jet_fuel", "JETKERO", "Jet fuel", frozenset({"jet_fuel"})
    ),
    "lpg": JodiCompareSeries("lpg", "LPG", "LPG", frozenset({"lpg"})),
    "naphtha": JodiCompareSeries(
        "naphtha", "NAPHTHA", "Naphtha", frozenset({"naphtha"})
    ),
    "fuel_oil": JodiCompareSeries(
        "fuel_oil", "RESFUEL", "Fuel oil", frozenset({"fuel_oil"})
    ),
    "others": JodiCompareSeries(
        "others", "ONONSPEC", "Others", frozenset({"others"})
    ),
}

JODI_COMPARE_PANEL_ORDER: tuple[str, ...] = (
    "Gasoline",
    "Diesel",
    "Jet fuel",
    "LPG",
    "Naphtha",
    "Fuel oil",
    "Others",
)


def is_moea_primary(product_native: str) -> bool:
    if product_native == "total":
        return False
    try:
        return is_primary(product_native, MOEA_AGENCY_SOURCE)
    except KeyError:
        return False


def _parse_period_cell(raw: object) -> tuple[str, Optional[pd.Timestamp], Optional[int]]:
    """Return (kind, date, gregorian_year) where kind is monthly|annual|skip."""
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return "skip", None, None
    text = str(raw).strip()
    if not text or text.lower() == "nan" or text.lower() == "period":
        return "skip", None, None

    m = _PERIOD_MONTHLY_RE.match(text)
    if m:
        year, month = int(m.group(1)), int(m.group(2))
        if not 1 <= month <= 12:
            return "skip", None, None
        return "monthly", pd.Timestamp(year=year, month=month, day=1), year

    m = _PERIOD_ANNUAL_RE.match(text)
    if m:
        return "annual", pd.Timestamp(year=int(m.group(1)), month=1, day=1), int(m.group(1))

    return "skip", None, None


def _should_skip_row(period_label: object, period_greg: object) -> bool:
    for val in (period_label, period_greg):
        if val is None or (isinstance(val, float) and pd.isna(val)):
            continue
        text = str(val).strip()
        if _SKIP_LABEL_RE.search(text):
            return True
    return False


def _annual_years_with_monthly(rows: list[dict]) -> set[int]:
    return {r["year"] for r in rows if r["kind"] == "monthly" and r["year"] is not None}


def parse_moea_consumption_workbook(
    path: Path,
    *,
    sheet_name: str = PRODUCTS_SHEET,
    gregorian_col: int = _COL_GREGORIAN,
) -> pd.DataFrame:
    """
    Parse Table 5-04 product consumption from one MOEA monthly statistics xlsx.

    Returns long-form columns: date, product_native, value, is_provisional.
    """
    path = Path(path)
    raw = pd.read_excel(path, sheet_name=sheet_name, header=None)

    parsed_rows: list[dict] = []
    for i in range(_DATA_START_ROW, len(raw)):
        period_label = raw.iat[i, _COL_PERIOD_LABEL]
        period_greg = raw.iat[i, gregorian_col]
        if _should_skip_row(period_label, period_greg):
            continue

        kind, anchor_date, year = _parse_period_cell(period_greg)
        if kind == "skip" or anchor_date is None:
            continue

        product_values: dict[str, float] = {}
        for col_idx, native in _COL_PRODUCTS:
            val = raw.iat[i, col_idx]
            if val is None or (isinstance(val, float) and pd.isna(val)):
                continue
            try:
                product_values[native] = float(val)
            except (TypeError, ValueError):
                continue

        if not product_values:
            continue

        parsed_rows.append(
            {
                "kind": kind,
                "date": anchor_date,
                "year": year,
                "products": product_values,
            }
        )

    monthly_years = _annual_years_with_monthly(parsed_rows)

    records: list[dict] = []
    for row in parsed_rows:
        if row["kind"] == "monthly":
            is_prov = False
            for product_native, value in row["products"].items():
                if not is_moea_primary(product_native):
                    continue
                records.append(
                    {
                        "date": row["date"],
                        "product_native": product_native,
                        "value": value,
                        "is_provisional": is_prov,
                    }
                )
            continue

        # Annual row — skip when that calendar year already has monthly detail.
        if row["year"] in monthly_years:
            continue

        for product_native, annual_value in row["products"].items():
            if not is_moea_primary(product_native):
                continue
            monthly_value = annual_value / 12.0
            for month in range(1, 13):
                records.append(
                    {
                        "date": pd.Timestamp(year=row["year"], month=month, day=1),
                        "product_native": product_native,
                        "value": monthly_value,
                        "is_provisional": True,
                    }
                )

    if not records:
        return pd.DataFrame(
            columns=["date", "product_native", "value", "is_provisional"]
        )

    out = pd.DataFrame(records)
    out = (
        out.groupby(["date", "product_native", "is_provisional"], as_index=False)["value"]
        .sum()
        .sort_values(["date", "product_native"])
        .reset_index(drop=True)
    )
    return out


def parse_moea_supply_workbook(path: Path) -> pd.DataFrame:
    """Parse Table 5-03 product **supply** (same product cols; Period in col 10)."""
    return parse_moea_consumption_workbook(
        path, sheet_name=SUPPLY_SHEET, gregorian_col=_COL_GREGORIAN_SUPPLY
    )


def finalize_moea_frame(
    partial: pd.DataFrame,
    *,
    source_file: str,
    updated_at: Optional[datetime] = None,
) -> pd.DataFrame:
    """Stamp provenance columns expected by the processor."""
    updated_at = updated_at or datetime.now(timezone.utc).replace(tzinfo=None)
    if partial.empty:
        return partial

    df = partial.copy()
    df["date"] = pd.to_datetime(df["date"])
    df["country"] = COUNTRY_CODE
    df["country_name"] = COUNTRY_NAME
    df["source"] = SOURCE_ID
    df["metric_type"] = MOEA_METRIC_TYPE
    df["product"] = df["product_native"]
    df["unit"] = MOEA_UNIT_NATIVE
    df["source_file"] = source_file
    df["updated_at"] = updated_at
    df["is_provisional"] = df["is_provisional"].astype(bool)

    cols = [
        "date",
        "country",
        "country_name",
        "source",
        "metric_type",
        "product_native",
        "product",
        "value",
        "unit",
        "is_provisional",
        "source_file",
        "updated_at",
    ]
    return df[cols]


def moea_series_for_jodi(
    demand: pd.DataFrame,
    series_key: str,
    *,
    value_col: str = "value",
) -> pd.DataFrame:
    spec = JODI_COMPARE_SERIES[series_key]
    sl = demand[demand["product_native"].isin(spec.natives)]
    if sl.empty:
        return pd.DataFrame(columns=["date", value_col, "is_provisional"])
    return (
        sl.groupby(["date", "is_provisional"], as_index=False)[value_col]
        .sum()
        .sort_values("date")
    )


def seasonality_chart_inputs(
    view: str,
    *,
    demand: pd.DataFrame,
    demand_canonical: pd.DataFrame,
) -> tuple[pd.DataFrame, str, list[str], dict[str, str], str]:
    view = view.strip().lower()
    if view == "native":
        products = list(SEASONALITY_NATIVE_PRODUCTS)
        df = demand[demand["product_native"].isin(products)].copy()
        return (
            df,
            "product_native",
            products,
            DISPLAY_LABELS,
            "native products",
        )
    if view == "canonical":
        products = [
            p
            for p in SEASONALITY_PANELS_CANONICAL
            if p in demand_canonical["panel"].values
        ]
        df = demand_canonical[demand_canonical["panel"].isin(products)].copy()
        labels = {p: p for p in products}
        return (
            df,
            "panel",
            products,
            labels,
            "canonical products",
        )
    raise ValueError(f"view must be 'native' or 'canonical', got {view!r}")


__all__ = [
    "MOEA_AGENCY_SOURCE",
    "MOEA_DATASET_SOURCE",
    "MOEA_METRIC_TYPE",
    "MOEA_UNIT_NATIVE",
    "COUNTRY_CODE",
    "COUNTRY_NAME",
    "SOURCE_ID",
    "PRODUCTS_SHEET",
    "SUPPLY_SHEET",
    "DELIVERY_HEADLINE_NATIVE",
    "CHART_PRODUCTS",
    "SEASONALITY_NATIVE_PRODUCTS",
    "SEASONALITY_PANELS_CANONICAL",
    "DISPLAY_LABELS",
    "UNITS_KIND",
    "JODI_COMPARE_SERIES",
    "JODI_COMPARE_PANEL_ORDER",
    "JodiCompareSeries",
    "is_moea_primary",
    "parse_moea_consumption_workbook",
    "parse_moea_supply_workbook",
    "finalize_moea_frame",
    "moea_series_for_jodi",
    "seasonality_chart_inputs",
]
