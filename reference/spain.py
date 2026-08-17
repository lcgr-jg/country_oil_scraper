"""
reference.spain
───────────────
CORES (Corporación de Reservas Estratégicas) — Petroleum Product Consumption.

Workbook ``oil-products-consumption.xlsx`` (monthly, tonnes) with one sheet per
product family. Published totals and subtotals are tagged ``[AGG]`` in
``product_map.csv`` and excluded from storage; detail lines are stored as
``{Sheet} | {column}`` natives.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd

from datetime import datetime

CORES_AGENCY_SOURCE = "CORES"
CORES_DATASET_SOURCE = "spain_petroleum_consumption"
CORES_METRIC_TYPE = "TOTDEMO"
CORES_UNIT_NATIVE = "t"

COUNTRY_CODE = "ES"
COUNTRY_NAME = "Spain"
SOURCE_ID = CORES_DATASET_SOURCE

CANONICAL_COLUMNS: list[str] = [
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

# Sheets parsed (excludes Start, All).
PRODUCT_SHEETS: tuple[str, ...] = (
    "LPG",
    "Gasoline",
    "Kerosene",
    "Gasoil",
    "Fuel oil",
    "Other products",
)

# Column labels never stored (also tagged [AGG] in product_map).
_EXCLUDED_COLUMN_LABELS: frozenset[str] = frozenset(
    {
        "Total",
        "Subtotal road gasoline",
        "Subtotal road diesel",
    }
)

_MONTH_RE = re.compile(
    r"^(January|February|March|April|May|June|July|August|September|"
    r"October|November|December)$",
    re.I,
)


def product_native(sheet: str, column: str) -> str:
    """Canonical native key: ``Gasoil | Road diesel``."""
    return f"{sheet} | {column.strip()}"


# Stored gasoline / gasoil lines (all subs; excludes sheet totals/subtotals).
GASOLINE_JODI_NATIVES: frozenset[str] = frozenset(
    {
        "Gasoline | Gasoline 97 RON",
        "Gasoline | Gasoline 95 RON",
        "Gasoline | Gasoline 98 RON",
        "Gasoline | Biogasoline",
        "Gasoline | Biogasoline Blend",
        "Gasoline | Aviation gasoline",
        "Gasoline | Other gasoline",
    }
)

GASOIL_JODI_NATIVES: frozenset[str] = frozenset(
    {
        "Gasoil | Road diesel",
        "Gasoil | Biodiesel (B100)",
        "Gasoil | Biodiesel blend (1)",
        "Gasoil | Agricultural diesel",
        "Gasoil | Heating oil",
        "Gasoil | Other gasoil",
    }
)

LPG_JODI_NATIVES: frozenset[str] = frozenset(
    {
        "LPG | Bottled",
        "LPG | Bulk",
        "LPG | Road",
        "LPG | Other LPG",
    }
)

FUEL_OIL_JODI_NATIVES: frozenset[str] = frozenset(
    {
        "Fuel oil | Fuel oil No. 1",
        "Fuel oil | Fuel oil No. 2",
        "Fuel oil | Low-sulphur fuel oil",
        "Fuel oil | Other fuel oil",
    }
)

_STORED_NATIVES: frozenset[str] = (
    GASOLINE_JODI_NATIVES
    | GASOIL_JODI_NATIVES
    | LPG_JODI_NATIVES
    | FUEL_OIL_JODI_NATIVES
    | frozenset({"Kerosene | Jet", "Kerosene | Other kerosene"})
    | frozenset(
        {
            "Other products | Lubricants",
            "Other products | Asphalt products",
            "Other products | Petroleum coke",
            "Other products | Others",
        }
    )
)

def is_cores_stored(native: str) -> bool:
    """True if this native should be written to the processed parquet."""
    return native in _STORED_NATIVES


_OTHER_PRODUCTS_PREFIX = "Other products | "
DELIVERY_HEADLINE_NATIVE: frozenset[str] = frozenset(
    n for n in _STORED_NATIVES if not n.startswith(_OTHER_PRODUCTS_PREFIX)
)

CHART_PRODUCTS: tuple[str, ...] = tuple(sorted(DELIVERY_HEADLINE_NATIVE))

# One panel per sheet family (sum of stored subs) — used for seasonality native view.
SEASONALITY_SHEET_ROLLUPS: dict[str, frozenset[str]] = {
    "LPG": LPG_JODI_NATIVES,
    "Gasoline": GASOLINE_JODI_NATIVES,
    "Gasoil": GASOIL_JODI_NATIVES,
    "Jet fuel": frozenset({"Kerosene | Jet"}),
    "Other kerosene": frozenset({"Kerosene | Other kerosene"}),
    "Fuel oil": FUEL_OIL_JODI_NATIVES,
}
SEASONALITY_NATIVE_PANELS: tuple[str, ...] = tuple(SEASONALITY_SHEET_ROLLUPS.keys())

SEASONALITY_PANELS_CANONICAL: tuple[str, ...] = (
    "Diesel",
    "Fuel oil",
    "Gasoline",
    "Jet fuel",
    "Kerosene",
    "LPG",
    "Lubricants / Grease",
    "Bitumen",
    "Others",
)

DISPLAY_LABELS: dict[str, str] = {
    # LPG
    "LPG | Bottled": "LPG — bottled",
    "LPG | Bulk": "LPG — bulk",
    "LPG | Road": "LPG — road",
    "LPG | Other LPG": "LPG — other",
    # Gasoline
    "Gasoline | Gasoline 97 RON": "Gasoline 97 RON",
    "Gasoline | Gasoline 95 RON": "Gasoline 95 RON",
    "Gasoline | Gasoline 98 RON": "Gasoline 98 RON",
    "Gasoline | Biogasoline": "Biogasoline",
    "Gasoline | Biogasoline Blend": "Biogasoline blend",
    "Gasoline | Aviation gasoline": "Aviation gasoline",
    "Gasoline | Other gasoline": "Other gasoline",
    # Gasoil
    "Gasoil | Road diesel": "Road diesel",
    "Gasoil | Biodiesel (B100)": "Biodiesel (B100)",
    "Gasoil | Biodiesel blend (1)": "Biodiesel blend",
    "Gasoil | Agricultural diesel": "Agricultural diesel",
    "Gasoil | Heating oil": "Heating oil",
    "Gasoil | Other gasoil": "Other gasoil",
    # Kerosene
    "Kerosene | Jet": "Jet",
    "Kerosene | Other kerosene": "Other kerosene",
    # Fuel oil
    "Fuel oil | Fuel oil No. 1": "Fuel oil No. 1",
    "Fuel oil | Fuel oil No. 2": "Fuel oil No. 2",
    "Fuel oil | Low-sulphur fuel oil": "Low-sulphur fuel oil",
    "Fuel oil | Other fuel oil": "Other fuel oil",
    # Other products
    "Other products | Lubricants": "Lubricants",
    "Other products | Asphalt products": "Asphalt",
    "Other products | Petroleum coke": "Petroleum coke",
    "Other products | Others": "Other products",
}

UNITS_KIND: dict[str, str] = {
    "LPG | Bottled": "lpg",
    "LPG | Bulk": "lpg",
    "LPG | Road": "lpg",
    "LPG | Other LPG": "lpg",
    "Gasoline | Gasoline 97 RON": "gasoline",
    "Gasoline | Gasoline 95 RON": "gasoline",
    "Gasoline | Gasoline 98 RON": "gasoline",
    "Gasoline | Biogasoline": "gasoline",
    "Gasoline | Biogasoline Blend": "gasoline",
    "Gasoline | Aviation gasoline": "gasoline",
    "Gasoline | Other gasoline": "gasoline",
    "Gasoil | Road diesel": "diesel",
    "Gasoil | Biodiesel (B100)": "diesel",
    "Gasoil | Biodiesel blend (1)": "diesel",
    "Gasoil | Agricultural diesel": "diesel",
    "Gasoil | Heating oil": "diesel",
    "Gasoil | Other gasoil": "diesel",
    "Kerosene | Jet": "jet",
    "Kerosene | Other kerosene": "kerosene",
    "Fuel oil | Fuel oil No. 1": "fuel_oil",
    "Fuel oil | Fuel oil No. 2": "fuel_oil",
    "Fuel oil | Low-sulphur fuel oil": "fuel_oil",
    "Fuel oil | Other fuel oil": "fuel_oil",
    "Other products | Lubricants": "lubes",
    "Other products | Asphalt products": "bitumen",
    "Other products | Petroleum coke": "other",
    "Other products | Others": "other",
}


@dataclass(frozen=True)
class JodiCompareSeries:
    key: str
    jodi_energy_product: str
    panel: str
    natives: frozenset[str]
    mode: str = "sum"  # sum stored natives for compare


JODI_COMPARE_SERIES: dict[str, JodiCompareSeries] = {
    "gasoline": JodiCompareSeries(
        "gasoline",
        "GASOLINE",
        "Gasoline",
        GASOLINE_JODI_NATIVES,
    ),
    "gasoil": JodiCompareSeries(
        "gasoil",
        "GASDIES",
        "Gasoil / diesel",
        GASOIL_JODI_NATIVES,
    ),
    "jet_fuel": JodiCompareSeries(
        "jet_fuel",
        "JETKERO",
        "Jet fuel",
        frozenset({"Kerosene | Jet"}),
        mode="reporting",
    ),
    "kerosene_other": JodiCompareSeries(
        "kerosene_other",
        "X_OTHKERO",
        "Other kerosene",
        frozenset({"Kerosene | Other kerosene"}),
        mode="reporting",
    ),
    "lpg": JodiCompareSeries("lpg", "LPG", "LPG", LPG_JODI_NATIVES),
    "fuel_oil": JodiCompareSeries(
        "fuel_oil", "RESFUEL", "Fuel oil", FUEL_OIL_JODI_NATIVES
    ),
}

JODI_COMPARE_PANEL_ORDER: tuple[str, ...] = (
    "Gasoline",
    "Gasoil / diesel",
    "Jet fuel",
    "Other kerosene",
    "LPG",
    "Fuel oil",
)


def _month_num(name: str) -> int:
    return {
        "january": 1,
        "february": 2,
        "march": 3,
        "april": 4,
        "may": 5,
        "june": 6,
        "july": 7,
        "august": 8,
        "september": 9,
        "october": 10,
        "november": 11,
        "december": 12,
    }[name.lower()]


def _column_label(raw: object) -> Optional[str]:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    text = str(raw).strip()
    if not text or text.lower() == "nan":
        return None
    return text


def _skip_column(label: str, series: pd.Series) -> bool:
    if label in _EXCLUDED_COLUMN_LABELS:
        return True
    # Trailing biodiesel share column (values in 0–1 range).
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().sum() >= 12:
        med = float(numeric.median())
        if 0 < med < 2 and numeric.max() < 5:
            return True
    return False


def parse_cores_consumption_workbook(path: Path) -> pd.DataFrame:
    """
    Parse CORES oil-products-consumption.xlsx into partial long form.

    Returns columns: date, product_native, value, source_file.
    """
    path = Path(path)
    rows: list[dict] = []

    for sheet in PRODUCT_SHEETS:
        wide = pd.read_excel(path, sheet_name=sheet, header=5)
        if "Year" not in wide.columns and wide.columns[0] != "Year":
            wide = wide.rename(columns={wide.columns[0]: "Year", wide.columns[1]: "Month"})
        year_col, month_col = "Year", "Month"
        product_cols: list[tuple[str, str]] = []
        for col in wide.columns:
            if col in (year_col, month_col):
                continue
            label = _column_label(col)
            if label is None or str(col).startswith("Unnamed"):
                continue
            if _skip_column(label, wide[col]):
                continue
            native = product_native(sheet, label)
            if not is_cores_stored(native):
                continue
            product_cols.append((str(col), native))

        for _, rec in wide.iterrows():
            year_raw, month_raw = rec[year_col], rec[month_col]
            if pd.isna(year_raw) or pd.isna(month_raw):
                continue
            month_text = str(month_raw).strip()
            if month_text.lower() == "total":
                continue
            if not _MONTH_RE.match(month_text):
                continue
            try:
                year = int(float(year_raw))
            except (TypeError, ValueError):
                continue
            if year < 1990 or year > 2035:
                continue
            ts = pd.Timestamp(year=year, month=_month_num(month_text), day=1)

            for col, native in product_cols:
                val = rec[col]
                if pd.isna(val):
                    continue
                try:
                    value = float(val)
                except (TypeError, ValueError):
                    continue
                rows.append(
                    {
                        "date": ts,
                        "product_native": native,
                        "value": value,
                        "source_file": path.name,
                    }
                )

    if not rows:
        return pd.DataFrame(columns=["date", "product_native", "value", "source_file"])
    return pd.DataFrame(rows)


def finalize_cores_frame(
    partial: pd.DataFrame,
    *,
    updated_at: datetime,
    country: str = COUNTRY_CODE,
    country_name: str = COUNTRY_NAME,
    source: str = CORES_DATASET_SOURCE,
    metric_type: str = CORES_METRIC_TYPE,
    unit: str = CORES_UNIT_NATIVE,
) -> pd.DataFrame:
    """Stamp provenance columns (used by scraper and tests)."""
    if partial.empty:
        return pd.DataFrame(columns=CANONICAL_COLUMNS)

    df = partial.copy()
    df["country"] = country
    df["country_name"] = country_name
    df["source"] = source
    df["metric_type"] = metric_type
    df["product"] = df["product_native"]
    df["unit"] = unit
    df["is_provisional"] = False
    df["updated_at"] = updated_at
    return df[CANONICAL_COLUMNS].sort_values(
        ["date", "product_native"], ignore_index=True
    )


def cores_series_for_jodi(
    demand: pd.DataFrame,
    series_key: str,
    *,
    value_col: str = "value",
) -> pd.DataFrame:
    """Aggregate CORES natives for one JODI compare panel."""
    spec = JODI_COMPARE_SERIES[series_key]
    sl = demand[demand["product_native"].isin(spec.natives)]
    if sl.empty:
        return pd.DataFrame(columns=["date", value_col, "is_provisional"])
    return (
        sl.groupby(["date", "is_provisional"], as_index=False)[value_col]
        .sum()
        .sort_values("date")
    )


def seasonality_native_rollup(
    demand: pd.DataFrame,
    *,
    value_col: str = "value_kbd",
) -> pd.DataFrame:
    """Sum subs within each sheet family for readable seasonality panels."""
    parts: list[pd.DataFrame] = []
    for panel, natives in SEASONALITY_SHEET_ROLLUPS.items():
        sl = demand[demand["product_native"].isin(natives)]
        if sl.empty:
            continue
        g = (
            sl.groupby(["date", "is_provisional"], as_index=False)[value_col]
            .sum()
            .assign(product_native=panel)
        )
        parts.append(g)
    if not parts:
        return pd.DataFrame(
            columns=["date", "is_provisional", value_col, "product_native"]
        )
    return pd.concat(parts, ignore_index=True)


def seasonality_chart_inputs(
    demand: pd.DataFrame,
    demand_canonical: pd.DataFrame,
    *,
    view: str = "native",
    value_col: str = "value_kbd",
) -> tuple[pd.DataFrame, str, list[str], dict[str, str], str]:
    view = view.strip().lower()
    if view == "native":
        products = list(SEASONALITY_NATIVE_PANELS)
        df = seasonality_native_rollup(demand, value_col=value_col)
        labels = {p: p for p in products}
        return df, "product_native", products, labels, "sheet rollups"
    if view == "canonical":
        products = [
            p
            for p in SEASONALITY_PANELS_CANONICAL
            if p in demand_canonical["panel"].values
        ]
        df = demand_canonical[demand_canonical["panel"].isin(products)].copy()
        return df, "panel", products, {p: p for p in products}, "canonical products"
    raise ValueError(f"view must be 'native' or 'canonical', got {view!r}")


__all__ = [
    "CANONICAL_COLUMNS",
    "finalize_cores_frame",
    "CORES_AGENCY_SOURCE",
    "CORES_DATASET_SOURCE",
    "CORES_METRIC_TYPE",
    "CORES_UNIT_NATIVE",
    "COUNTRY_CODE",
    "COUNTRY_NAME",
    "SOURCE_ID",
    "PRODUCT_SHEETS",
    "product_native",
    "is_cores_stored",
    "parse_cores_consumption_workbook",
    "DELIVERY_HEADLINE_NATIVE",
    "CHART_PRODUCTS",
    "SEASONALITY_SHEET_ROLLUPS",
    "SEASONALITY_NATIVE_PANELS",
    "seasonality_native_rollup",
    "SEASONALITY_PANELS_CANONICAL",
    "DISPLAY_LABELS",
    "UNITS_KIND",
    "JodiCompareSeries",
    "JODI_COMPARE_SERIES",
    "JODI_COMPARE_PANEL_ORDER",
    "cores_series_for_jodi",
    "seasonality_chart_inputs",
    "GASOLINE_JODI_NATIVES",
    "GASOIL_JODI_NATIVES",
    "LPG_JODI_NATIVES",
    "FUEL_OIL_JODI_NATIVES",
]
