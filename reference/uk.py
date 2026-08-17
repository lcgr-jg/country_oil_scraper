"""
reference.uk
────────────
DESNZ Energy Trends — UK oil and oil products (consolidated ODS workbook).

Sheets used:
  * ``3_13`` — deliveries for inland consumption (monthly, thousand tonnes)
  * ``3_11`` — closing stocks (monthly, thousand tonnes; product columns only)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

import pandas as pd

DESNZ_AGENCY_SOURCE = "DESNZ"
UK_CONSUMPTION_SOURCE = "uk_energy_trends_consumption"
UK_STOCKS_SOURCE = "uk_energy_trends_stocks"
UK_CONSUMPTION_METRIC = "TOTDEMO"
UK_STOCKS_METRIC = "CLOSTLV"
UK_UNIT_NATIVE = "kt"

COUNTRY_CODE = "GB"
COUNTRY_NAME = "United Kingdom"

GOVUK_STATISTICS_PAGE = (
    "https://www.gov.uk/government/statistics/"
    "oil-and-oil-products-section-3-energy-trends"
)

CONSUMPTION_SHEET = "3_13"
STOCKS_SHEET = "3_11"

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

# Stable native keys (match product_map.csv Product_name).
CONSUMPTION_PRODUCTS: tuple[str, ...] = (
    "Butane and propane",
    "Other petroleum gases",
    "Naphtha [LDF]",
    "Petrol",
    "Jet fuel",
    "Burning oil",
    "Road diesel",
    "Gas oil",
    "Fuel oil",
    "Lubricating oils",
    "Bitumen",
)

TOTAL_NATIVE = "Total"
DERIVED_OTHERS_NATIVE = "Other products (derived)"

# Internal parse tag (dropped before parquet); disambiguates shared product names.
RECORD_CONSUMPTION = "consumption"
RECORD_STOCKS = "stocks"

STOCK_PRODUCTS: tuple[str, ...] = (
    "Petrol",
    "Diesel",
    "Gas oil",
    "Jet fuel",
    "Burning oil",
    "Other products",
)

# Headline = all stored consumption primaries incl. naphtha + derived Others.
DELIVERY_HEADLINE_NATIVE: frozenset[str] = frozenset(
    CONSUMPTION_PRODUCTS + (DERIVED_OTHERS_NATIVE,)
)

CHART_PRODUCTS: tuple[str, ...] = tuple(CONSUMPTION_PRODUCTS + (DERIVED_OTHERS_NATIVE,))

JODI_REF_AREA = "GB"

LPG_JODI_NATIVES: frozenset[str] = frozenset(
    {"Butane and propane", "Other petroleum gases"}
)

SEASONALITY_PANELS_CANONICAL: tuple[str, ...] = (
    "Gasoline",
    "Diesel",
    "Gasoil",
    "Jet Fuel",
    "Kerosene",
    "LPG",
    "Naphtha",
    "Fuel Oil",
    "Lubricants / Grease",
    "Bitumen",
    "Others",
)

DISPLAY_LABELS: dict[str, str] = {
    "Butane and propane": "LPG — butane & propane",
    "Other petroleum gases": "LPG — other gases",
    "Naphtha [LDF]": "Naphtha",
    "Petrol": "Petrol",
    "Jet fuel": "Jet fuel",
    "Burning oil": "Burning oil (kerosene)",
    "Road diesel": "Road diesel",
    "Gas oil": "Gas oil",
    "Fuel oil": "Fuel oil",
    "Lubricating oils": "Lubricating oils",
    "Bitumen": "Bitumen",
    DERIVED_OTHERS_NATIVE: "Other products (derived)",
}

UNITS_KIND: dict[str, str] = {
    "Butane and propane": "lpg",
    "Other petroleum gases": "lpg",
    "Naphtha [LDF]": "naphtha",
    "Petrol": "gasoline",
    "Jet fuel": "jet",
    "Burning oil": "kerosene",
    "Road diesel": "diesel",
    "Gas oil": "diesel",
    "Fuel oil": "fuel_oil",
    "Lubricating oils": "lubes",
    "Bitumen": "bitumen",
    DERIVED_OTHERS_NATIVE: "other",
}

STOCK_DISPLAY_LABELS: dict[str, str] = {
    "Petrol": "Petrol stocks",
    "Diesel": "Diesel stocks",
    "Gas oil": "Gas oil stocks",
    "Jet fuel": "Jet fuel stocks",
    "Burning oil": "Burning oil stocks",
    "Other products": "Other products stocks",
}

STOCK_UNITS_KIND: dict[str, str] = {
    "Petrol": "gasoline",
    "Diesel": "diesel",
    "Gas oil": "diesel",
    "Jet fuel": "jet",
    "Burning oil": "kerosene",
    "Other products": "other",
}


@dataclass(frozen=True)
class JodiCompareSeries:
    key: str
    jodi_energy_product: str
    panel: str
    natives: frozenset[str]


JODI_COMPARE_SERIES: dict[str, JodiCompareSeries] = {
    "gasoline": JodiCompareSeries(
        "gasoline", "GASOLINE", "Gasoline", frozenset({"Petrol"})
    ),
    "diesel": JodiCompareSeries(
        "diesel", "GASDIES", "Diesel", frozenset({"Road diesel"})
    ),
    "jet_fuel": JodiCompareSeries(
        "jet_fuel", "JETKERO", "Jet fuel", frozenset({"Jet fuel"})
    ),
    "kerosene": JodiCompareSeries(
        "kerosene", "X_OTHKERO", "Kerosene", frozenset({"Burning oil"})
    ),
    "lpg": JodiCompareSeries("lpg", "LPG", "LPG", LPG_JODI_NATIVES),
    "naphtha": JodiCompareSeries(
        "naphtha", "NAPHTHA", "Naphtha", frozenset({"Naphtha [LDF]"})
    ),
    "fuel_oil": JodiCompareSeries(
        "fuel_oil", "RESFUEL", "Fuel oil", frozenset({"Fuel oil"})
    ),
    "others": JodiCompareSeries(
        "others",
        "ONONSPEC",
        "Others",
        frozenset({DERIVED_OTHERS_NATIVE}),
    ),
}

JODI_COMPARE_PANEL_ORDER: tuple[str, ...] = (
    "Gasoline",
    "Diesel",
    "Jet fuel",
    "Kerosene",
    "LPG",
    "Naphtha",
    "Fuel oil",
    "Others",
)

# ET 3.11 stock natives mapped to JODI CLOSTLV panels (subset of demand compare).
DIESEL_STOCK_JODI_NATIVES: frozenset[str] = frozenset({"Diesel", "Gas oil"})

JODI_STOCKS_COMPARE_SERIES: dict[str, JodiCompareSeries] = {
    "gasoline": JodiCompareSeries(
        "gasoline", "GASOLINE", "Gasoline", frozenset({"Petrol"})
    ),
    "diesel": JodiCompareSeries(
        "diesel", "GASDIES", "Diesel", DIESEL_STOCK_JODI_NATIVES
    ),
    "jet_fuel": JodiCompareSeries(
        "jet_fuel", "JETKERO", "Jet fuel", frozenset({"Jet fuel"})
    ),
    "kerosene": JodiCompareSeries(
        "kerosene", "X_OTHKERO", "Kerosene", frozenset({"Burning oil"})
    ),
    "others": JodiCompareSeries(
        "others", "ONONSPEC", "Others", frozenset({"Other products"})
    ),
}

JODI_STOCKS_PANEL_ORDER: tuple[str, ...] = (
    "Gasoline",
    "Diesel",
    "Jet fuel",
    "Kerosene",
    "Others",
)

_NOTE_RE = re.compile(r"\[note\s*\d+\]", re.IGNORECASE)
_PROVISIONAL_RE = re.compile(r"\[provisional\]", re.IGNORECASE)
_MONTH_YEAR_RE = re.compile(
    r"^(January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+(\d{4})",
    re.IGNORECASE,
)
_MONTH_NUM: dict[str, int] = {
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
}


def normalize_label(value: object) -> str:
    """Strip footnote tags and collapse whitespace (ODS headers vary)."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = _NOTE_RE.sub("", str(value))
    return re.sub(r"\s+", " ", text).strip()


def parse_numeric(value: object) -> Optional[float]:
    """Parse UK table cells; ``[x]`` and blanks become None."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = str(value).strip()
    if text in ("", "-", "[x]", "x", "nan"):
        return None
    text = text.replace(",", "")
    try:
        return float(text)
    except ValueError:
        return None


def parse_month_cell(label: object) -> tuple[Optional[pd.Timestamp], bool]:
    """``January 1998`` or ``March 2026 [provisional]`` → month-start + flag."""
    if label is None or (isinstance(label, float) and pd.isna(label)):
        return None, False
    text = str(label).strip()
    is_provisional = bool(_PROVISIONAL_RE.search(text))
    text = _PROVISIONAL_RE.sub("", text).strip()
    match = _MONTH_YEAR_RE.match(text)
    if not match:
        return None, False
    month = _MONTH_NUM[match.group(1).lower()]
    year = int(match.group(2))
    return pd.Timestamp(year=year, month=month, day=1), is_provisional


def _find_header_row(raw: pd.DataFrame) -> int:
    for idx, row in raw.iterrows():
        first = normalize_label(row.iloc[0])
        if first.lower() == "column1":
            return int(idx)
    raise ValueError("Could not find header row (Column1)")


def _read_sheet(raw_path: Path, sheet_name: str) -> pd.DataFrame:
    return pd.read_excel(raw_path, sheet_name=sheet_name, engine="odf", header=None)


def parse_consumption_sheet(
    raw_path: Path,
    *,
    source_file: str | None = None,
) -> pd.DataFrame:
    """Parse ET 3.13 to long form (products + official total)."""
    raw = _read_sheet(raw_path, CONSUMPTION_SHEET)
    header_idx = _find_header_row(raw)
    header = raw.iloc[header_idx]
    source_file = source_file or Path(raw_path).name

    col_map: dict[int, str] = {}
    for col_idx, cell in header.items():
        label = normalize_label(cell)
        if not label or label.lower() == "column1":
            continue
        col_map[int(col_idx)] = label

    rows: list[dict[str, object]] = []
    for row_idx in range(header_idx + 1, len(raw)):
        row = raw.iloc[row_idx]
        date, is_provisional = parse_month_cell(row.iloc[0])
        if date is None:
            continue
        for col_idx, product_native in col_map.items():
            value = parse_numeric(row.iloc[col_idx])
            if value is None:
                continue
            rows.append(
                {
                    "date": date,
                    "product_native": product_native,
                    "value": value,
                    "is_provisional": is_provisional,
                    "source_file": source_file,
                    "_record_kind": RECORD_CONSUMPTION,
                }
            )

    if not rows:
        return pd.DataFrame(
            columns=[
                "date",
                "product_native",
                "value",
                "is_provisional",
                "source_file",
                "_record_kind",
            ]
        )
    return pd.DataFrame(rows)


def append_derived_others(consumption: pd.DataFrame) -> pd.DataFrame:
    """
    Add ``Other products (derived)`` = Total − sum(11 product columns).

    Table 3.13 Note 1: the gap is aviation spirit, white spirits, petcoke,
    wax, and miscellaneous products not broken out in the product columns.
    """
    if consumption.empty:
        return consumption

    totals = consumption[consumption["product_native"] == TOTAL_NATIVE].copy()
    if totals.empty:
        return consumption

    products = consumption[
        consumption["product_native"].isin(CONSUMPTION_PRODUCTS)
    ].copy()
    if products.empty:
        return consumption

    sum_by_month = (
        products.groupby(
            ["date", "is_provisional", "source_file"],
            as_index=False,
            sort=False,
        )["value"]
        .sum()
        .rename(columns={"value": "product_sum"})
    )
    merged = totals.merge(
        sum_by_month,
        on=["date", "is_provisional", "source_file"],
        how="inner",
    )
    derived = merged.copy()
    derived["product_native"] = DERIVED_OTHERS_NATIVE
    derived["value"] = derived["value"] - derived["product_sum"]
    derived["_record_kind"] = RECORD_CONSUMPTION
    derived = derived.drop(columns=["product_sum"])

    without_total = consumption[consumption["product_native"] != TOTAL_NATIVE]
    return pd.concat([without_total, derived], ignore_index=True)


def parse_stocks_sheet(
    raw_path: Path,
    *,
    source_file: str | None = None,
) -> pd.DataFrame:
    """Parse ET 3.11 product-stock columns (excludes crude / aggregate cols)."""
    raw = _read_sheet(raw_path, STOCKS_SHEET)
    header_idx = _find_header_row(raw)
    header = raw.iloc[header_idx]
    source_file = source_file or Path(raw_path).name
    allowed = frozenset(STOCK_PRODUCTS)

    col_map: dict[int, str] = {}
    for col_idx, cell in header.items():
        label = normalize_label(cell)
        if label in allowed:
            col_map[int(col_idx)] = label

    rows: list[dict[str, object]] = []
    for row_idx in range(header_idx + 1, len(raw)):
        row = raw.iloc[row_idx]
        date, is_provisional = parse_month_cell(row.iloc[0])
        if date is None:
            continue
        for col_idx, product_native in col_map.items():
            value = parse_numeric(row.iloc[col_idx])
            if value is None:
                continue
            rows.append(
                {
                    "date": date,
                    "product_native": product_native,
                    "value": value,
                    "is_provisional": is_provisional,
                    "source_file": source_file,
                    "_record_kind": RECORD_STOCKS,
                }
            )

    if not rows:
        return pd.DataFrame(
            columns=[
                "date",
                "product_native",
                "value",
                "is_provisional",
                "source_file",
                "_record_kind",
            ]
        )
    return pd.DataFrame(rows)


def parse_energy_trends_workbook(raw_path: Path) -> pd.DataFrame:
    """Parse consumption (with derived Others) and product stocks from one ODS."""
    raw_path = Path(raw_path)
    consumption = append_derived_others(parse_consumption_sheet(raw_path))
    stocks = parse_stocks_sheet(raw_path)
    return pd.concat([consumption, stocks], ignore_index=True)


def finalize_uk_frame(
    partial: pd.DataFrame,
    *,
    updated_at: datetime | None = None,
) -> pd.DataFrame:
    """Attach country / source / metric metadata for the unified parquet."""
    if partial.empty:
        for col in CANONICAL_COLUMNS:
            if col not in partial.columns:
                partial[col] = pd.Series(dtype="object")
        return partial[CANONICAL_COLUMNS]

    df = partial.copy()
    # ET 3.11 shares names with 3.13 (Petrol, Jet fuel, …) — use sheet tag, not name.
    if "_record_kind" in df.columns:
        stock_mask = df["_record_kind"] == RECORD_STOCKS
    else:
        stock_mask = df["product_native"].isin(STOCK_PRODUCTS)
    df["country"] = COUNTRY_CODE
    df["country_name"] = COUNTRY_NAME
    df["source"] = UK_STOCKS_SOURCE
    df.loc[~stock_mask, "source"] = UK_CONSUMPTION_SOURCE
    df["metric_type"] = UK_STOCKS_METRIC
    df.loc[~stock_mask, "metric_type"] = UK_CONSUMPTION_METRIC
    df["product"] = df["product_native"]
    df["unit"] = UK_UNIT_NATIVE
    df["updated_at"] = updated_at or datetime.now(UTC)
    return df[CANONICAL_COLUMNS]


def is_uk_stored(native: str) -> bool:
    """True if this native label appears in stored consumption or stock rows."""
    return native in DELIVERY_HEADLINE_NATIVE or native in STOCK_PRODUCTS


def keep_parsed_row(row: pd.Series) -> bool:
    """Row-level store filter (handles shared consumption/stock product names)."""
    kind = row.get("_record_kind")
    native = row["product_native"]
    if kind == RECORD_CONSUMPTION:
        return native in DELIVERY_HEADLINE_NATIVE
    if kind == RECORD_STOCKS:
        return native in STOCK_PRODUCTS
    return is_uk_stored(str(native))


def uk_series_for_jodi(
    demand: pd.DataFrame,
    series_key: str,
    *,
    value_col: str = "value",
) -> pd.DataFrame:
    """Aggregate DESNZ natives for one JODI compare panel."""
    spec = JODI_COMPARE_SERIES[series_key]
    sl = demand[demand["product_native"].isin(spec.natives)]
    if sl.empty:
        return pd.DataFrame(columns=["date", value_col, "is_provisional"])
    return (
        sl.groupby(["date", "is_provisional"], as_index=False)[value_col]
        .sum()
        .sort_values("date")
    )


def uk_stocks_series_for_jodi(
    stocks: pd.DataFrame,
    series_key: str,
    *,
    value_col: str = "value_kb",
) -> pd.DataFrame:
    """Aggregate ET 3.11 stock natives for one JODI CLOSTLV panel."""
    spec = JODI_STOCKS_COMPARE_SERIES[series_key]
    sl = stocks[stocks["product_native"].isin(spec.natives)]
    if sl.empty:
        return pd.DataFrame(columns=["date", value_col, "is_provisional"])
    return (
        sl.groupby(["date", "is_provisional"], as_index=False)[value_col]
        .sum()
        .sort_values("date")
    )


def seasonality_chart_inputs(
    demand: pd.DataFrame,
    demand_canonical: pd.DataFrame,
    *,
    view: str = "native",
    value_col: str = "value_kbd",
) -> tuple[pd.DataFrame, str, list[str], dict[str, str], str]:
    view = view.strip().lower()
    if view == "native":
        products = list(CHART_PRODUCTS)
        df = demand[demand["product_native"].isin(products)].copy()
        labels = {p: DISPLAY_LABELS.get(p, p) for p in products}
        return df, "product_native", products, labels, "native products"
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
    "DESNZ_AGENCY_SOURCE",
    "UK_CONSUMPTION_SOURCE",
    "UK_STOCKS_SOURCE",
    "GOVUK_STATISTICS_PAGE",
    "CONSUMPTION_SHEET",
    "STOCKS_SHEET",
    "CANONICAL_COLUMNS",
    "CONSUMPTION_PRODUCTS",
    "STOCK_PRODUCTS",
    "TOTAL_NATIVE",
    "DERIVED_OTHERS_NATIVE",
    "DELIVERY_HEADLINE_NATIVE",
    "CHART_PRODUCTS",
    "JODI_REF_AREA",
    "DISPLAY_LABELS",
    "UNITS_KIND",
    "STOCK_DISPLAY_LABELS",
    "STOCK_UNITS_KIND",
    "SEASONALITY_PANELS_CANONICAL",
    "JODI_COMPARE_SERIES",
    "JODI_COMPARE_PANEL_ORDER",
    "DIESEL_STOCK_JODI_NATIVES",
    "JODI_STOCKS_COMPARE_SERIES",
    "JODI_STOCKS_PANEL_ORDER",
    "uk_series_for_jodi",
    "uk_stocks_series_for_jodi",
    "seasonality_chart_inputs",
    "normalize_label",
    "parse_consumption_sheet",
    "parse_stocks_sheet",
    "append_derived_others",
    "parse_energy_trends_workbook",
    "finalize_uk_frame",
    "is_uk_stored",
    "keep_parsed_row",
    "RECORD_CONSUMPTION",
    "RECORD_STOCKS",
]
