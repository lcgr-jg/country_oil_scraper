"""
reference.poland
────────────────
ARE (Agencja Rynku Energii) — Statistical Information on the Liquid Fuels Market.

Monthly ``Biuletyn_{month}_{year}_*.xls`` workbooks (2024+) from cms.are.waw.pl.
Unit: kt (tys. ton). Refinery products only — crude excluded per project scope.
"""

from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, FrozenSet, Optional

import pandas as pd

ARE_AGENCY_SOURCE = "ARE"
ARE_DATASET_SOURCE = "poland_are_liquid_fuels"
ARE_UNIT_NATIVE = "kt"

COUNTRY_CODE = "PL"
COUNTRY_NAME = "Poland"
SOURCE_ID = ARE_DATASET_SOURCE
JODI_REF_AREA = "PL"
ARE_STOCKS_METRIC = "CLOSTLV"

PUBLICATIONS_PAGE_PL = (
    "https://www.are.waw.pl/pl/badania-statystyczne/wynikowe-informacje-statystyczne"
)
CMS_BASE_URL = "https://cms.are.waw.pl"

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

# Stored product_native values — must match product_map.csv.
PRODUCT_MOTOR_GASOLINE = "Motor gasoline"
PRODUCT_DIESEL = "Diesel oils"
PRODUCT_HEATING_OIL = "Heating oil"
PRODUCT_FUEL_OIL = "Fuel oil"
PRODUCT_LPG = "LPG"

STORED_PRODUCTS: frozenset[str] = frozenset(
    {
        PRODUCT_MOTOR_GASOLINE,
        PRODUCT_DIESEL,
        PRODUCT_HEATING_OIL,
        PRODUCT_FUEL_OIL,
        PRODUCT_LPG,
    }
)

DELIVERY_HEADLINE_NATIVE: frozenset[str] = STORED_PRODUCTS

CHART_PRODUCTS: tuple[str, ...] = (
    PRODUCT_MOTOR_GASOLINE,
    PRODUCT_DIESEL,
    PRODUCT_HEATING_OIL,
    PRODUCT_FUEL_OIL,
    PRODUCT_LPG,
)

DISPLAY_LABELS: dict[str, str] = {
    PRODUCT_MOTOR_GASOLINE: "Gasoline",
    PRODUCT_DIESEL: "Diesel",
    PRODUCT_HEATING_OIL: "Heating oil",
    PRODUCT_FUEL_OIL: "Fuel oil",
    PRODUCT_LPG: "LPG",
}

UNITS_KIND: dict[str, str] = {
    PRODUCT_MOTOR_GASOLINE: "gasoline",
    PRODUCT_DIESEL: "diesel",
    PRODUCT_HEATING_OIL: "diesel",
    PRODUCT_FUEL_OIL: "fuel_oil",
    PRODUCT_LPG: "lpg",
}

SEASONALITY_PANELS_CANONICAL: tuple[str, ...] = (
    "Gasoline",
    "Diesel",
    "Gasoil",
    "Fuel oil",
    "LPG",
)

# product_map Sub-category → chart panel (keep Diesel vs Gasoil distinct).
CANONICAL_SUBCATEGORY_PANEL: dict[str, str] = {
    "Gasoline": "Gasoline",
    "Diesel": "Diesel",
    "Gasoil": "Gasoil",
    "Fuel Oil": "Fuel oil",
    "LPG": "LPG",
}

# JODI-aligned demand rollup for headline canonical charts (GASDIES composite).
JODI_DEMAND_ROLLUP: dict[str, frozenset[str]] = {
    "Gasoline": frozenset({"Gasoline"}),
    "Gas/diesel oil": frozenset({"Diesel", "Gasoil"}),
    "Fuel oil": frozenset({"Fuel Oil"}),
    "LPG": frozenset({"LPG"}),
}

JODI_DEMAND_ROLLUP_ORDER: tuple[str, ...] = (
    "Gasoline",
    "Gas/diesel oil",
    "Fuel oil",
    "LPG",
)


@dataclass(frozen=True)
class JodiCompareSeries:
    key: str
    jodi_energy_product: str
    panel: str
    natives: FrozenSet[str]
    mode: str = "reporting"


GASOLINE_JODI_NATIVES: frozenset[str] = frozenset({PRODUCT_MOTOR_GASOLINE})
DIESEL_JODI_NATIVES: frozenset[str] = frozenset({PRODUCT_DIESEL})
GASOIL_JODI_NATIVES: frozenset[str] = frozenset({PRODUCT_HEATING_OIL})
LPG_JODI_NATIVES: frozenset[str] = frozenset({PRODUCT_LPG})
FUEL_OIL_JODI_NATIVES: frozenset[str] = frozenset({PRODUCT_FUEL_OIL})

JODI_COMPARE_SERIES: dict[str, JodiCompareSeries] = {
    "gasoline": JodiCompareSeries(
        "gasoline", "GASOLINE", "Gasoline", GASOLINE_JODI_NATIVES
    ),
    "diesel": JodiCompareSeries(
        "diesel", "GASDIES", "Diesel", DIESEL_JODI_NATIVES
    ),
    "gasoil": JodiCompareSeries(
        "gasoil", "GASDIES", "Gasoil", GASOIL_JODI_NATIVES
    ),
    "lpg": JodiCompareSeries("lpg", "LPG", "LPG", LPG_JODI_NATIVES),
    "fuel_oil": JodiCompareSeries(
        "fuel_oil", "RESFUEL", "Fuel oil", FUEL_OIL_JODI_NATIVES
    ),
}

JODI_COMPARE_PANEL_ORDER: tuple[str, ...] = (
    "Gasoline",
    "Diesel",
    "Gasoil",
    "LPG",
    "Fuel oil",
)

JODI_STOCKS_PANEL_ORDER: tuple[str, ...] = JODI_COMPARE_PANEL_ORDER

_ROMAN_MONTH: dict[str, int] = {
    "I": 1,
    "II": 2,
    "III": 3,
    "IV": 4,
    "V": 5,
    "VI": 6,
    "VII": 7,
    "VIII": 8,
    "IX": 9,
    "X": 10,
    "XI": 11,
    "XII": 12,
}

_POLISH_MONTH_SLUG: dict[str, int] = {
    "styczen": 1,
    "luty": 2,
    "marzec": 3,
    "kwiecien": 4,
    "maj": 5,
    "czerwiec": 6,
    "lipiec": 7,
    "sierpien": 8,
    "wrzesien": 9,
    "pazdziernik": 10,
    "listopad": 11,
    "grudzien": 12,
}

_BIULETYN_PATH_RE = re.compile(
    r"/uploads/Biuletyn_(?P<month>[a-z]+)_(?P<year>\d{4})_[a-f0-9]+\.xls",
    re.I,
)
_ANNUAL_LIQUID_RE = re.compile(
    r"/uploads/Informacja_statystyczna_o_rynku_pal[a-z]*_cieklych[^\"\\]*\.xls",
    re.I,
)

_PRODUCT_PATTERNS: list[tuple[str, str]] = [
    (PRODUCT_MOTOR_GASOLINE, r"motor gasoline"),
    (PRODUCT_DIESEL, r"diesel oils"),
    (PRODUCT_HEATING_OIL, r"heating oil"),
    (PRODUCT_FUEL_OIL, r"fuel oil"),
    (PRODUCT_LPG, r"\blpg\b"),
]

_MISSING_TOKENS = frozenset({"-", "#", ".", "…", "x", "X", "n/a", "N/A", ""})


def _ascii_fold(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text)
    return folded.encode("ascii", "ignore").decode("ascii")


def _normalize_cell(text: Any) -> str:
    if text is None or (isinstance(text, float) and pd.isna(text)):
        return ""
    return re.sub(r"\s+", " ", _ascii_fold(str(text))).strip().lower()


def _parse_numeric(value: Any) -> Optional[float]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if text in _MISSING_TOKENS:
        return None
    try:
        return float(text.replace(",", "").replace(" ", ""))
    except ValueError:
        return None


def _product_from_label(label: Any) -> Optional[str]:
    text = _normalize_cell(label)
    if not text:
        return None
    for product, pattern in _PRODUCT_PATTERNS:
        if re.search(pattern, text):
            return product
    return None


def _period_label_to_date(label: Any) -> Optional[pd.Timestamp]:
    if label is None or (isinstance(label, float) and pd.isna(label)):
        return None
    text = str(label).strip()
    m = re.match(r"^([IVX]+)\s+(\d{4})$", text, re.I)
    if not m:
        return None
    roman = m.group(1).upper()
    month = _ROMAN_MONTH.get(roman)
    if month is None:
        return None
    return pd.Timestamp(year=int(m.group(2)), month=month, day=1)


def publication_date_from_path(path: Path | str) -> Optional[pd.Timestamp]:
    """Infer bulletin month from ``Biuletyn_{month}_{year}_*.xls`` filename."""
    name = Path(path).name
    m = re.match(r"Biuletyn_(?P<month>[a-z]+)_(?P<year>\d{4})", name, re.I)
    if not m:
        return None
    month = _POLISH_MONTH_SLUG.get(m.group("month").lower())
    if month is None:
        return None
    return pd.Timestamp(year=int(m.group("year")), month=month, day=1)


def is_liquid_fuels_bulletin(path: Path | str) -> bool:
    """True when workbook matches ARE liquid-fuels Biuletyn layout."""
    try:
        xl = pd.ExcelFile(path)
    except Exception:
        return False
    joined = " ".join(xl.sheet_names).lower()
    return "tab 1.1" in joined or (
        "czesc i" in joined and any("1.1" in s for s in xl.sheet_names)
    )


def discover_liquid_fuel_paths(html: str) -> list[str]:
    """
    Return CMS-relative paths for liquid-fuels bulletins linked on the ARE page.

    ``inf_*`` paths on the same page are electricity (ISOEE), not liquid fuels.
    """
    paths = sorted(
        set(re.findall(r"/uploads/Biuletyn_[a-z]+_\d{4}_[a-f0-9]+\.xls", html, re.I))
    )
    annual = sorted(
        set(
            re.findall(
                r"/uploads/Informacja_statystyczna_o_rynku_pal[a-z]*_cieklych[^\"\\]*\.xls",
                html,
                re.I,
            )
        )
    )
    return paths + [p for p in annual if p not in paths]


def _find_sheet(sheet_names: list[str], needle: str) -> Optional[str]:
    needle_l = needle.lower()
    for name in sheet_names:
        if needle_l in name.lower():
            return name
    return None


@dataclass(frozen=True)
class _PeriodColumn:
    col_idx: int
    period: pd.Timestamp


def _period_columns(df: pd.DataFrame, header_row: int) -> list[_PeriodColumn]:
    """Read Roman month + year labels from the specification header row."""
    for candidate in (header_row, header_row - 1, header_row - 2):
        if candidate < 0:
            continue
        out: list[_PeriodColumn] = []
        for col in range(1, min(df.shape[1], 8)):
            period = _period_label_to_date(df.iloc[candidate, col])
            if period is not None:
                out.append(_PeriodColumn(col_idx=col, period=period))
        if out:
            return out
    return []


def _table_marker_matches(cell: str, table_marker: str) -> bool:
    """Match ``Table 1.1`` without hitting ``Table 1.10``."""
    num = table_marker.rsplit(" ", 1)[-1]
    return re.search(rf"table\s+{re.escape(num)}(?:\D|$)", cell, re.I) is not None


def _rows_for_table(df: pd.DataFrame, table_marker: str) -> tuple[int, int]:
    """Return (start_row, end_row) for a table block identified by English title."""
    start: Optional[int] = None
    for i in range(len(df)):
        cell = _normalize_cell(df.iloc[i, 0])
        if _table_marker_matches(cell, table_marker):
            start = i
            break
    if start is None:
        raise ValueError(f"Table marker not found: {table_marker!r}")

    end = len(df)
    for j in range(start + 1, len(df)):
        cell = _normalize_cell(df.iloc[j, 0])
        if (cell.startswith("tablica") or cell.startswith("table ")) and j > start + 3:
            # Avoid treating sub-rows as a new table — require a fresh table number.
            if re.search(r"table\s+\d", cell, re.I):
                end = j
                break
        if "wykres" in cell or "chart" in cell:
            end = j
            break
    return start, end


def _parse_product_rows(
    df: pd.DataFrame,
    *,
    table_marker: str,
    metric_type: str,
    source_file: str,
    updated_at: datetime,
) -> list[dict[str, Any]]:
    start, end = _rows_for_table(df, table_marker)
    block = df.iloc[start:end].reset_index(drop=True)

    header_row: Optional[int] = None
    for i in range(len(block)):
        if "specification" in _normalize_cell(block.iloc[i, 0]):
            header_row = i
            break
    if header_row is None:
        return []

    periods = _period_columns(block, header_row)
    rows: list[dict[str, Any]] = []
    for i in range(header_row + 1, len(block)):
        product = _product_from_label(block.iloc[i, 0])
        if product is None:
            continue
        rows.extend(
            _emit_period_values(
                product=product,
                metric_type=metric_type,
                periods=periods,
                block=block,
                row_idx=i,
                source_file=source_file,
                updated_at=updated_at,
            )
        )
    return rows


_CONSUMPTION_TABLE_PRODUCT: dict[str, str] = {
    "1.4": PRODUCT_MOTOR_GASOLINE,
    "1.5": PRODUCT_DIESEL,
    "1.6": PRODUCT_HEATING_OIL,
    "1.7": PRODUCT_FUEL_OIL,
    "1.8": PRODUCT_LPG,
}


def _product_from_consumption_table(table_marker: str) -> Optional[str]:
    """Map ``Table 1.4`` … ``Table 1.8`` to the single product each table covers."""
    m = re.search(r"table\s+([\d.]+)", table_marker, re.I)
    if m is None:
        return None
    return _CONSUMPTION_TABLE_PRODUCT.get(m.group(1))


def _is_domestic_consumption_row(label: Any) -> bool:
    text = _normalize_cell(label)
    # Bilingual row label: ``Zużycie krajowe / Domestic consumption``.
    return "domestic consumption" in text or text.startswith("zuzycie krajowe")


def _parse_consumption_table(
    df: pd.DataFrame,
    *,
    table_marker: str,
    source_file: str,
    updated_at: datetime,
) -> list[dict[str, Any]]:
    start, end = _rows_for_table(df, table_marker)
    block = df.iloc[start:end].reset_index(drop=True)

    product = _product_from_consumption_table(table_marker)
    if product is None:
        return []

    header_row: Optional[int] = None
    for i in range(len(block)):
        if "specification" in _normalize_cell(block.iloc[i, 0]):
            header_row = i
            break
    if header_row is None:
        return []

    periods = _period_columns(block, header_row)
    for i in range(header_row + 1, len(block)):
        if _is_domestic_consumption_row(block.iloc[i, 0]):
            return _emit_period_values(
                product=product,
                metric_type="TOTDEMO",
                periods=periods,
                block=block,
                row_idx=i,
                source_file=source_file,
                updated_at=updated_at,
            )
    return []


def _emit_period_values(
    *,
    product: str,
    metric_type: str,
    periods: list[_PeriodColumn],
    block: pd.DataFrame,
    row_idx: int,
    source_file: str,
    updated_at: datetime,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for pc in periods:
        value = _parse_numeric(block.iloc[row_idx, pc.col_idx])
        if value is None:
            continue
        rows.append(
            {
                "date": pc.period,
                "country": COUNTRY_CODE,
                "country_name": COUNTRY_NAME,
                "source": SOURCE_ID,
                "metric_type": metric_type,
                "product_native": product,
                "product": product,
                "value": value,
                "unit": ARE_UNIT_NATIVE,
                "is_provisional": True,
                "source_file": source_file,
                "updated_at": updated_at,
            }
        )
    return rows


def parse_are_liquid_fuels_workbook(
    path: Path | str,
    *,
    updated_at: Optional[datetime] = None,
) -> pd.DataFrame:
    """Parse one ARE liquid-fuels Biuletyn workbook into a long DataFrame."""
    path = Path(path)
    if updated_at is None:
        updated_at = datetime.now(tz=UTC)

    xl = pd.ExcelFile(path)
    source_file = path.name
    records: list[dict[str, Any]] = []

    prod_sheet = _find_sheet(xl.sheet_names, "tab 1.1")
    if prod_sheet:
        df_prod = pd.read_excel(path, sheet_name=prod_sheet, header=None)
        records.extend(
            _parse_product_rows(
                df_prod,
                table_marker="Table 1.1",
                metric_type="REFGROUT",
                source_file=source_file,
                updated_at=updated_at,
            )
        )
        records.extend(
            _parse_product_rows(
                df_prod,
                table_marker="Table 1.2",
                metric_type="TOTIMPSB",
                source_file=source_file,
                updated_at=updated_at,
            )
        )

    sales_gas_diesel = _find_sheet(xl.sheet_names, "tab 1.4")
    if sales_gas_diesel:
        df_sales = pd.read_excel(path, sheet_name=sales_gas_diesel, header=None)
        records.extend(
            _parse_consumption_table(
                df_sales,
                table_marker="Table 1.4",
                source_file=source_file,
                updated_at=updated_at,
            )
        )
        records.extend(
            _parse_consumption_table(
                df_sales,
                table_marker="Table 1.5",
                source_file=source_file,
                updated_at=updated_at,
            )
        )

    sales_other = _find_sheet(xl.sheet_names, "tab 1.6")
    if sales_other:
        df_other = pd.read_excel(path, sheet_name=sales_other, header=None)
        for marker in ("Table 1.6", "Table 1.7", "Table 1.8"):
            records.extend(
                _parse_consumption_table(
                    df_other,
                    table_marker=marker,
                    source_file=source_file,
                    updated_at=updated_at,
                )
            )

    stocks_sheet = _find_sheet(xl.sheet_names, "tab 1.9")
    if stocks_sheet:
        df_stocks = pd.read_excel(path, sheet_name=stocks_sheet, header=None)
        records.extend(
            _parse_product_rows(
                df_stocks,
                table_marker="Table 1.10",
                metric_type="CLOSTLV",
                source_file=source_file,
                updated_at=updated_at,
            )
        )

    if not records:
        raise ValueError(f"No ARE liquid-fuels rows parsed from {path.name}")

    df = pd.DataFrame(records)
    return finalize_are_frame(df)


def parse_are_liquid_fuels_bytes(
    content: bytes,
    *,
    source_file: str,
    updated_at: Optional[datetime] = None,
) -> pd.DataFrame:
    """Parse workbook bytes (validates CMS payload before persisting)."""
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".xls", delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    try:
        return parse_are_liquid_fuels_workbook(
            tmp_path, updated_at=updated_at
        )
    finally:
        tmp_path.unlink(missing_ok=True)


def finalize_are_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"])
    out["updated_at"] = pd.to_datetime(out["updated_at"], utc=True)
    key = ["date", "metric_type", "product_native", "source_file"]
    out = out.drop_duplicates(subset=key, keep="last")
    return out.sort_values(["date", "metric_type", "product_native"]).reset_index(
        drop=True
    )


def are_series_for_jodi(
    frame: pd.DataFrame,
    series_key: str,
    *,
    value_col: str = "value",
) -> pd.DataFrame:
    """Roll native product rows into one JODI-comparison panel."""
    spec = JODI_COMPARE_SERIES[series_key]
    sl = frame[frame["product_native"].isin(spec.natives)]
    if sl.empty:
        return pd.DataFrame(columns=["date", value_col, "is_provisional"])
    return (
        sl.groupby(["date", "is_provisional"], as_index=False)[value_col]
        .sum()
        .sort_values("date")
    )


def build_demand_canonical(
    demand: pd.DataFrame,
    *,
    value_col: str = "value_kbd",
) -> pd.DataFrame:
    """
    One series per product_map Sub-category (Diesel and Gasoil kept separate).

    Used for seasonality and any chart that needs heating oil visible as Gasoil.
    """
    sl = demand[demand["product_canonical"].notna()].copy()
    if sl.empty:
        return pd.DataFrame(
            columns=["date", "product_canonical", "is_provisional", value_col, "panel"]
        )
    out = sl.groupby(
        ["date", "product_canonical", "is_provisional"], as_index=False
    )[value_col].sum()
    out["panel"] = out["product_canonical"].map(CANONICAL_SUBCATEGORY_PANEL)
    unmapped = out.loc[out["panel"].isna(), "product_canonical"].unique()
    if len(unmapped):
        raise ValueError(f"Unmapped product_canonical values: {sorted(unmapped)}")
    return out.sort_values(["date", "panel"]).reset_index(drop=True)


def build_demand_jodi_rollup(
    demand_canonical: pd.DataFrame,
    *,
    value_col: str = "value_kbd",
) -> pd.DataFrame:
    """
    JODI-aligned TOTDEMO rollup: Diesel + Gasoil → ``Gas/diesel oil`` (GASDIES).
    """
    frames: list[pd.DataFrame] = []
    for panel, subcategories in JODI_DEMAND_ROLLUP.items():
        sl = demand_canonical[
            demand_canonical["product_canonical"].isin(subcategories)
        ]
        if sl.empty:
            continue
        frames.append(
            sl.groupby(["date", "is_provisional"], as_index=False)[value_col]
            .sum()
            .assign(panel=panel)
        )
    if not frames:
        return pd.DataFrame(
            columns=["date", "is_provisional", value_col, "panel"]
        )
    return pd.concat(frames, ignore_index=True).sort_values(["date", "panel"])


def seasonality_chart_inputs(
    demand: pd.DataFrame,
    demand_canonical: pd.DataFrame,
    *,
    view: str = "native",
    value_col: str = "value_kbd",
) -> tuple[pd.DataFrame, str, list[str], dict[str, str], str]:
    view = view.strip().lower()
    if view == "native":
        products = [p for p in CHART_PRODUCTS if p in demand["product_native"].values]
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


def timeliness_vs_jodi(
    are_demand: pd.DataFrame,
    jodi_demand: pd.DataFrame,
) -> pd.DataFrame:
    """
    Latest data month available in ARE vs JODI secondary (PL, TOTDEMO).

    ``lead_months`` = ARE max date minus JODI max date in calendar months
    (positive when ARE extends further).
    """
    rows: list[dict[str, Any]] = []
    for key in JODI_COMPARE_SERIES:
        spec = JODI_COMPARE_SERIES[key]
        are_sl = are_demand[are_demand["product_native"].isin(spec.natives)]
        jodi_sl = jodi_demand[
            jodi_demand["energy_product"] == spec.jodi_energy_product
        ]
        are_max = are_sl["date"].max() if not are_sl.empty else pd.NaT
        jodi_max = jodi_sl["date"].max() if not jodi_sl.empty else pd.NaT
        lead: Optional[int] = None
        if pd.notna(are_max) and pd.notna(jodi_max):
            lead = (are_max.year - jodi_max.year) * 12 + (
                are_max.month - jodi_max.month
            )
        rows.append(
            {
                "panel": spec.panel,
                "jodi_energy_product": spec.jodi_energy_product,
                "are_latest": are_max,
                "jodi_latest": jodi_max,
                "lead_months": lead,
            }
        )
    return pd.DataFrame(rows)
