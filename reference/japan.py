"""
reference.japan
───────────────
METI petroleum statistics (石油統計) — domestic sales and 確報 supply balance.

Publication tiers:
  - 速報 (sokuhō)  : single-month 需給概要 workbook (~M+1); domestic sales only
  - 確報 (kakuhō)  : monthly 製品月表 (~M+2); production / import / sales / export / inventory
  - 年報 (nenpō)   : annual yearbook; domestic sales history only

Native volume unit: **kL** (kilolitres). LPG / grease / paraffin / asphalt
rows in the sokuhō sheet are in **t** (tonnes) — stored as tonnes, converted
via ``product_kind='lpg'`` etc. when building kbd in notebooks.

Headline totals **include naphtha** (industrial + transport overall demand).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd

from reference.loaders import is_primary, load_product_map

METI_AGENCY_SOURCE = "METI"
METI_DATASET_SOURCE = "japan_meti_domestic_sales"
METI_METRIC_TYPE = "TOTDEMO"
METI_UNIT_KL = "kL"
METI_UNIT_TONNES = "t"

# 確報 product blocks: 生産 / 輸入 / 国内向販売 / 輸出 / 在庫 (yearbook = sales only).
METI_KAKUHOU_FLOW_HEADERS: dict[str, tuple[str, ...]] = {
    "INDPROD": ("生産", "Production"),
    "TOTIMPSB": ("輸入", "Import"),
    "TOTDEMO": ("国内向販売", "DomesticSales", "Domestic Sales"),
    "TOTEXPSB": ("輸出", "Export"),
    "CLOSTLV": ("在庫", "Inventory"),
}
METI_SUPPLY_METRIC_TYPES: tuple[str, ...] = tuple(METI_KAKUHOU_FLOW_HEADERS.keys())
# Post–US/Iran baseline for inventory dashboards (month-end Feb 2026 level).
INVENTORY_FOCUS_START = pd.Timestamp(2026, 2, 1)

COUNTRY_CODE = "JP"
COUNTRY_NAME = "Japan"
SOURCE_ID = METI_DATASET_SOURCE

# Regex on section title cells → product_native (must match product_map Product_name)
_SECTION_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"ガソリン|Gasoline", re.I), "gasoline"),
    (re.compile(r"ナフサ|Naphtha", re.I), "naphtha"),
    (re.compile(r"ジェット|Jet\s*Fuel", re.I), "jet_fuel"),
    (re.compile(r"灯油|Kerosene", re.I), "kerosene"),
    (re.compile(r"軽油|Gas\s*Oil", re.I), "gas_oil"),
    (re.compile(r"Ａ重油|Fuel\s*Oil\s*A", re.I), "fuel_oil_a"),
    (re.compile(r"Ｂ[・･]Ｃ重油|B[・･]C|Fuel\s*Oil\s*B", re.I), "fuel_oil_bc"),
    (re.compile(r"潤滑油|Lubricating", re.I), "lubricating_oil"),
    (re.compile(r"アスファルト|Asphalt", re.I), "asphalt"),
    (re.compile(r"グリース|Grease", re.I), "grease"),
    (re.compile(r"パラフィン|Paraffin", re.I), "paraffin_wax"),
    (re.compile(r"液化石油ガス|Liquefied\s*Petroleum|LPG", re.I), "lpg"),
]

# Sokuhō 需給概要 column headers (row 4) → product_native
_SOKUHO_HEADER_TO_NATIVE: dict[str, str] = {
    "ガソリン": "gasoline",
    "ナ フ サ": "naphtha",
    "ナフサ": "naphtha",
    "燃 料 油": "jet_fuel",
    "灯　　油": "kerosene",
    "灯油": "kerosene",
    "軽　　油": "gas_oil",
    "軽油": "gas_oil",
    "Ａ 重 油": "fuel_oil_a",
    "Ａ重油": "fuel_oil_a",
    "Ｂ・Ｃ重油": "fuel_oil_bc",
    "Ｂ・Ｃ重油": "fuel_oil_bc",
    "潤 滑 油": "lubricating_oil",
    "潤滑油": "lubricating_oil",
    "ファルト": "asphalt",
    "アスファルト": "asphalt",
    "グリース": "grease",
    "フ ィ ン": "paraffin_wax",
    "パラフィン": "paraffin_wax",
    "Ｌ Ｐ Ｇ": "lpg",
    "ＬＰＧ": "lpg",
}

_TONNE_PRODUCTS = frozenset({"asphalt", "grease", "paraffin_wax", "lpg"})

# Ｂ・Ｃ重油 — JODI RESFUEL compare (Ａ重油 is gasoil → GASDIES with gas_oil).
FUEL_OIL_HEAVY_NATIVE: frozenset[str] = frozenset({"fuel_oil_bc"})
GASDIES_COMPARE_NATIVE: frozenset[str] = frozenset({"gas_oil", "fuel_oil_a"})
# Back-compat alias used in tests / older imports
FUEL_OIL_NATIVE = FUEL_OIL_HEAVY_NATIVE

# Overall demand headline — includes naphtha (petchem / industrial).
DELIVERY_HEADLINE_NATIVE: frozenset[str] = frozenset(
    {
        "gasoline",
        "naphtha",
        "jet_fuel",
        "kerosene",
        "gas_oil",
        "fuel_oil_a",
        "fuel_oil_bc",
        "lpg",
        "lubricating_oil",
        "asphalt",
        "grease",
        "paraffin_wax",
    }
)

CHART_PRODUCTS: tuple[str, ...] = tuple(DELIVERY_HEADLINE_NATIVE)

SEASONALITY_NATIVE_PRODUCTS: tuple[str, ...] = CHART_PRODUCTS

# Warehouse panel labels from canonical_panel_label (not product_map Sub-category).
# Gasoil rolls into Diesel; Lubricants/Grease/Wax roll into Lubes & greases.
SEASONALITY_PANELS_CANONICAL: tuple[str, ...] = (
    "Gasoline",
    "Naphtha",
    "Jet fuel",
    "Kerosene",
    "Diesel",
    "Fuel oil",
    "LPG",
    "Lubes & greases",
    "Bitumen",
)

DISPLAY_LABELS: dict[str, str] = {
    "gasoline": "Gasoline",
    "naphtha": "Naphtha",
    "jet_fuel": "Jet fuel",
    "kerosene": "Kerosene",
    "gas_oil": "Gas oil (diesel)",
    "fuel_oil_a": "Fuel oil A (gasoil)",
    "fuel_oil_bc": "Fuel oil B·C (heavy)",
    "lpg": "LPG",
    "lubricating_oil": "Lubricating oil",
    "asphalt": "Asphalt",
    "grease": "Grease",
    "paraffin_wax": "Paraffin wax",
}

UNITS_KIND: dict[str, str] = {
    "gasoline": "gasoline",
    "naphtha": "naphtha",
    "kerosene": "kerosene",
    "jet_fuel": "jet",
    "gas_oil": "diesel",
    "fuel_oil_a": "diesel",
    "fuel_oil_bc": "fuel_oil",
    "lpg": "lpg",
    "lubricating_oil": "lubes",
    "asphalt": "bitumen",
    "grease": "lubes",
    "paraffin_wax": "lubes",
}

_KAKUHOU_FILENAME_RE = re.compile(r"se(\d{6})kakji\.xlsx$", re.I)
_YEARBOOK_FILENAME_RE = re.compile(r"h2dhhpe(\d{4})k\.xls(?:x)?$", re.I)
_YEARBOOK_DOMESTIC_SHEET_RE = re.compile(
    r"石油製品.*国内向.*(?:月別)?.*販売"
)
_HEISEI_MONTH_RE = re.compile(
    r"平成\s*(\d+)\s*年\s*[　\s]*(\d{1,2})\s*月"
)
_EN_MONTH_PERIOD_RE = re.compile(
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s*(\d{4})",
    re.I,
)
_EN_MONTH_ONLY_RE = re.compile(
    r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?$",
    re.I,
)
# 年報 col 21 — calendar/fiscal-year totals and quarters (not monthly rows).
_YEARBOOK_EN_AGGREGATE_RE = re.compile(
    r"^(C\.Y\.|F\.Y\.|Q[1-4])\b",
    re.I,
)
_YEARBOOK_QUARTER_RE = re.compile(r"[\d０-９]+[～~][\d０-９]")
_YEARBOOK_YEAR_ONLY_RE = re.compile(r"^[\d０-９]{1,2}年?$")
_EN_MONTH_TO_NUM: dict[str, int] = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

# 年報 product headers (English row preferred; layout shifts by edition).
_YB_COL_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"Gasoline|ガソリン", re.I), "gasoline"),
    (re.compile(r"Naphtha|ナ\s*フ\s*サ|ナフサ", re.I), "naphtha"),
    (re.compile(r"Jet\s*Fuel|ジェット", re.I), "jet_fuel"),
    (re.compile(r"Kerosene|灯\s*油|灯油", re.I), "kerosene"),
    (re.compile(r"Gas\s*Oil|軽\s*油|軽油", re.I), "gas_oil"),
    (re.compile(r"Fuel\s*Oil\s*A|Ａ\s*重\s*油|Ａ重油", re.I), "fuel_oil_a"),
    (re.compile(r"Fuel\s*Oil\s*B|Ｂ[・･]Ｃ", re.I), "fuel_oil_bc"),
    (re.compile(r"Lubricating|潤滑油", re.I), "lubricating_oil"),
    (re.compile(r"Asphalt|アスファルト", re.I), "asphalt"),
    (re.compile(r"Grease|グリース", re.I), "grease"),
    (re.compile(r"Paraffin", re.I), "paraffin_wax"),
    (re.compile(r"^LPG$|液化石油ガス", re.I), "lpg"),
]
_YB_SKIP_COL_RE = re.compile(
    r"Total|計|LNG|液化天然|P・P|B・B|Propane|Division|部門",
    re.I,
)
_KAKUHOU_STOP_TABLE_RE = re.compile(
    r"年・期・月|合計|中東|Middle\s*East|地域・国別|Import\s*of\s*Crude"
)
_REIWA_MONTH_RE = re.compile(
    r"令和\s*(\d+)\s*年\s*[　\s]*(\d{1,2})\s*月"
)
_REIWA_YEAR_MONTH_RE = re.compile(
    r"令和\s*(\d+)\s*年\s*[　\s]*(\d{1,2})\s*(?:月)?\s*$"
)
_MONTH_ONLY_RE = re.compile(r"^[　\s]*([０-９\d]{1,2})\s*月?\s*[　\s]*$")
_SOKUHO_MONTH_RE = re.compile(r"\(?\s*(\d+)\s*年\s*(\d{1,2})\s*月\s*\)?")
_SOKUHO_TITLE_REIWA_MONTH_RE = re.compile(r"[（(]\s*(\d+)\s*年\s*(\d{1,2})\s*月\s*[）)]")
_SOKUHOU_OVERVIEW_SKIP_ROW_RE = re.compile(
    r"月初在庫|前月比|前年同月|End of the Previous|^[RＲ]\.[PＰ]|^[RＲ]\.[SＳ]|"
    r"Notes|注\d|公表予定|今後の",
    re.I,
)
_SOKUHOU_OVERVIEW_SKIP_PRODUCT_RE = re.compile(
    r"^Total$|^燃料油計$|^区|Category|Unit|単",
    re.I,
)
_SOKUHOU_OVERVIEW_FLOW_LABELS: dict[str, tuple[str, ...]] = {
    "INDPROD": ("生産", "Production"),
    "TOTIMPSB": ("輸入", "Import"),
    "TOTDEMO": ("国内向販売", "DomesticSales"),
    "TOTEXPSB": ("輸出", "Export"),
    "CLOSTLV": ("月末在庫", "MonthEndInventories", "Month-EndInventories"),
}
_SOKUHOU_OVERVIEW_PRODUCT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^Gasoline$|ガソリン", re.I), "gasoline"),
    (re.compile(r"^Naphtha$|ナ\s*フ\s*サ|ナフサ", re.I), "naphtha"),
    (re.compile(r"Jet\s*Fuel|^燃\s*料\s*油$", re.I), "jet_fuel"),
    (re.compile(r"Kerosene|灯\s*油|灯油", re.I), "kerosene"),
    (re.compile(r"Gas\s*Oil|軽\s*油|軽油", re.I), "gas_oil"),
    (re.compile(r"Fuel\s*Oil\s*A|Ａ\s*重\s*油|Ａ重油", re.I), "fuel_oil_a"),
    (re.compile(r"Fuel\s*Oil\s*B|Ｂ[・･]Ｃ", re.I), "fuel_oil_bc"),
    (re.compile(r"Lubricating|潤\s*滑\s*油|潤滑油", re.I), "lubricating_oil"),
    (re.compile(r"Asphalt|ファルト|アスファルト", re.I), "asphalt"),
    (re.compile(r"^LPG$|Ｌ\s*Ｐ\s*Ｇ|ＬＰＧ", re.I), "lpg"),
    (re.compile(r"Grease|グリース", re.I), "grease"),
    (re.compile(r"Paraffin|フ\s*ィ\s*ン|パラフィン", re.I), "paraffin_wax"),
]
_SKIP_PERIOD_RE = re.compile(r"[～~]|年度|１～|４～|１０～|１～３")


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
    "naphtha": JodiCompareSeries(
        "naphtha", "NAPHTHA", "Naphtha", frozenset({"naphtha"})
    ),
    "gas_diesel": JodiCompareSeries(
        "gas_diesel",
        "GASDIES",
        "Gas/diesel oil",
        GASDIES_COMPARE_NATIVE,
    ),
    "jet_fuel": JodiCompareSeries(
        "jet_fuel", "JETKERO", "Jet fuel", frozenset({"jet_fuel"})
    ),
    "kerosene": JodiCompareSeries(
        "kerosene", "X_OTHKERO", "Kerosene", frozenset({"kerosene"})
    ),
    "lpg": JodiCompareSeries("lpg", "LPG", "LPG", frozenset({"lpg"})),
    "fuel_oil": JodiCompareSeries(
        "fuel_oil",
        "RESFUEL",
        "Fuel oil",
        FUEL_OIL_HEAVY_NATIVE,
    ),
}

JODI_COMPARE_PANEL_ORDER: tuple[str, ...] = (
    "Gas/diesel oil",
    "Fuel oil",
    "Gasoline",
    "Kerosene",
    "Jet fuel",
    "LPG",
    "Naphtha",
)


def reiwa_to_gregorian_year(reiwa: int) -> int:
    """Calendar year for METI monthly tables (令和7年1月 → 2025-01)."""
    return 2018 + reiwa


def heisei_to_gregorian_year(heisei: int) -> int:
    """Calendar year for 平成 tables (平成29年 → 2017)."""
    return 1988 + heisei


def _parse_month_number(token: str) -> Optional[int]:
    t = token.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    try:
        mo = int(t)
    except ValueError:
        return None
    return mo if 1 <= mo <= 12 else None


def parse_period_label(
    label: object,
    *,
    reiwa_year: Optional[int] = None,
) -> tuple[Optional[pd.Timestamp], Optional[int]]:
    """Parse a 年・期・月 cell; returns (month-start, reiwa_year context)."""
    if label is None or (isinstance(label, float) and pd.isna(label)):
        return None, reiwa_year
    text = str(label).strip()
    if not text or text.lower() == "nan":
        return None, reiwa_year
    if _SKIP_PERIOD_RE.search(text):
        return None, reiwa_year

    m = _REIWA_MONTH_RE.search(text) or _REIWA_YEAR_MONTH_RE.search(text)
    if m:
        ry, mo = int(m.group(1)), int(m.group(2))
        month = _parse_month_number(str(mo))
        if month:
            return pd.Timestamp(reiwa_to_gregorian_year(ry), month, 1), ry

    hm = _HEISEI_MONTH_RE.search(text)
    if hm:
        hy, mo = int(hm.group(1)), int(hm.group(2))
        month = _parse_month_number(str(mo))
        if month:
            return pd.Timestamp(heisei_to_gregorian_year(hy), month, 1), None

    if reiwa_year is not None:
        mo_m = _MONTH_ONLY_RE.match(text)
        if mo_m:
            month = _parse_month_number(mo_m.group(1))
            if month:
                return (
                    pd.Timestamp(reiwa_to_gregorian_year(reiwa_year), month, 1),
                    reiwa_year,
                )

    return None, reiwa_year


def parse_kakuhou_filename(path: Path) -> Optional[pd.Timestamp]:
    """``se202603kakji.xlsx`` → 2026-03-01."""
    m = _KAKUHOU_FILENAME_RE.search(path.name)
    if not m:
        return None
    yyyymm = m.group(1)
    return pd.Timestamp(int(yyyymm[:4]), int(yyyymm[4:6]), 1)


def _match_section_product(cell: object) -> Optional[str]:
    if cell is None or (isinstance(cell, float) and pd.isna(cell)):
        return None
    text = str(cell).strip()
    if not text:
        return None
    for pat, native in _SECTION_PATTERNS:
        if pat.search(text):
            return native
    return None


def _coerce_numeric(val: object) -> Optional[float]:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    if isinstance(val, (int, float)):
        return float(val)
    text = str(val).strip().replace(",", "")
    if not text or text in {"-", "―", "x", "X", "…"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _normalize_kakuhou_header(cell: object) -> str:
    if cell is None or (isinstance(cell, float) and pd.isna(cell)):
        return ""
    return str(cell).strip().replace(" ", "").replace("\u3000", "")


def _kakuhou_flow_columns(
    df: pd.DataFrame, header_row: int, anchor: int
) -> dict[str, int]:
    """Map canonical ``metric_type`` → column index for one 確報 product block."""
    ncols = df.shape[1]
    found: dict[str, int] = {}
    for hr in (header_row, header_row + 1):
        if hr < 0 or hr >= len(df):
            continue
        for c in range(anchor, min(anchor + 14, ncols)):
            norm = _normalize_kakuhou_header(df.iat[hr, c])
            if not norm:
                continue
            for metric_type, labels in METI_KAKUHOU_FLOW_HEADERS.items():
                if metric_type in found:
                    continue
                for label in labels:
                    key = label.replace(" ", "").replace("\u3000", "")
                    if key in norm or norm in key:
                        found[metric_type] = c
                        break
    # Standard METI layout: period col 1, flows 2–6 when headers are sparse.
    if anchor <= 1:
        for metric_type, col in (
            ("INDPROD", 2),
            ("TOTIMPSB", 3),
            ("TOTDEMO", 4),
            ("TOTEXPSB", 5),
            ("CLOSTLV", 6),
        ):
            if metric_type not in found and col < ncols:
                found[metric_type] = col
    if "TOTDEMO" not in found:
        found["TOTDEMO"] = _kakuhou_domestic_sales_col(df, header_row, anchor)
    return found


def _parse_kakuhou_sheet(df: pd.DataFrame, source_file: str) -> list[dict]:
    """Extract monthly supply-balance rows from one 確報 sheet (all flow columns)."""
    rows: list[dict] = []
    ncols = df.shape[1]
    seen_products: set[str] = set()

    for r in range(len(df) - 1):
        for anchor in range(ncols):
            product = _match_section_product(df.iat[r, anchor])
            if product is None or product in seen_products:
                continue
            seen_products.add(product)

            period_col = 1
            header_row = None
            for hr in range(r, min(r + 6, len(df))):
                row_txt = " ".join(
                    str(df.iat[hr, c])
                    for c in range(anchor, min(anchor + 7, ncols))
                )
                if "国内向販売" in row_txt or "Domestic  Sales" in row_txt:
                    header_row = hr
                    break
            if header_row is None:
                continue

            flow_cols = _kakuhou_flow_columns(df, header_row, anchor)
            if not flow_cols or max(flow_cols.values()) >= ncols:
                continue

            data_start = header_row + 1
            reiwa_ctx: Optional[int] = None
            for dr in range(data_start, len(df)):
                period_cell = df.iat[dr, period_col]
                if dr > data_start:
                    row_probe = " ".join(
                        str(df.iat[dr, c])
                        for c in range(min(14, ncols))
                        if pd.notna(df.iat[dr, c])
                    )
                    if _KAKUHOU_STOP_TABLE_RE.search(row_probe):
                        break
                    if _match_section_product(period_cell):
                        break

                period, reiwa_ctx = parse_period_label(
                    period_cell, reiwa_year=reiwa_ctx
                )
                if period is None:
                    if _kakuhou_skip_period_cell(period_cell):
                        continue
                    continue
                unit = METI_UNIT_TONNES if product in _TONNE_PRODUCTS else METI_UNIT_KL
                for metric_type, col in flow_cols.items():
                    val = _coerce_numeric(df.iat[dr, col])
                    if val is None:
                        continue
                    rows.append(
                        {
                            "date": period,
                            "product_native": product,
                            "metric_type": metric_type,
                            "value": val,
                            "unit": unit,
                            "source_file": source_file,
                        }
                    )
    return rows


def parse_meti_kakuhou_workbook(path: Path) -> pd.DataFrame:
    """Parse a 確報 monthly XLSX (製品月表)."""
    path = Path(path)
    xl = pd.ExcelFile(path)
    records: list[dict] = []
    for sheet in xl.sheet_names:
        if sheet.lower() == "sheet1":
            continue
        df = pd.read_excel(path, sheet_name=sheet, header=None)
        records.extend(_parse_kakuhou_sheet(df, path.name))

    if not records:
        return pd.DataFrame(
            columns=[
                "date",
                "product_native",
                "metric_type",
                "value",
                "unit",
                "source_file",
            ]
        )

    out = pd.DataFrame(records)
    file_month = parse_kakuhou_filename(path)
    if file_month is not None:
        # Prefer rows up to the file's survey month when duplicates exist
        out = out[out["date"] <= file_month]

    return (
        out.sort_values(["date", "product_native", "metric_type", "source_file"])
        .drop_duplicates(subset=["date", "product_native", "metric_type"], keep="first")
        .reset_index(drop=True)
    )


def _parse_sokuhou_survey_month(df: pd.DataFrame) -> Optional[pd.Timestamp]:
    for r in range(min(5, len(df))):
        for c in range(min(6, df.shape[1])):
            text = str(df.iat[r, c])
            m = _SOKUHO_MONTH_RE.search(text)
            if m:
                era_year, month = int(m.group(1)), int(m.group(2))
                # Reiwa era in sokuhō title: (8年3月)
                if era_year >= 1:
                    return pd.Timestamp(reiwa_to_gregorian_year(era_year), month, 1)
    return None


def _normalize_sokuhou_header(cell: object) -> Optional[str]:
    if cell is None or (isinstance(cell, float) and pd.isna(cell)):
        return None
    text = str(cell).strip().replace("\u3000", " ").replace(" ", "")
    if "燃料油計" in text or "燃料油计" in text:
        return None
    for key, native in _SOKUHO_HEADER_TO_NATIVE.items():
        k = key.replace("\u3000", " ").replace(" ", "")
        if text == k:
            return native
    return None


def yearbook_edition_year(path: Path) -> Optional[int]:
    """``h2dhhpe2007k.xls`` / ``h2dhhpe2024k.xlsx`` → 2007 / 2024."""
    m = _YEARBOOK_FILENAME_RE.search(Path(path).name)
    return int(m.group(1)) if m else None


def _yearbook_columns_by_product(layout: _YearbookLayout) -> dict[str, int]:
    """One column per product (legacy 年報 sheets repeat product blocks)."""
    out: dict[str, int] = {}
    for col, native in sorted(layout.value_columns.items()):
        if native not in out:
            out[native] = col
    return out


def _score_yearbook_domestic_sheet(
    path: Path,
    sheet_name: str,
    layout: _YearbookLayout,
    edition_year: Optional[int],
) -> int:
    """Count distinct calendar months parsed from a candidate domestic-sales sheet."""
    df = pd.read_excel(path, sheet_name=sheet_name, header=None)
    months: set[tuple[int, int]] = set()
    era_ctx: Optional[tuple[str, int]] = None
    last_gy: Optional[int] = None
    for r in range(layout.data_start, len(df)):
        period, last_gy, era_ctx = _yearbook_row_period(
            df, r, layout, era_ctx=era_ctx, last_gregorian_year=last_gy
        )
        if period is None:
            continue
        if edition_year is not None:
            if period.year < edition_year or period.year > edition_year + 1:
                continue
            if period.year == edition_year + 1 and period.month > 3:
                continue
        months.add((period.year, period.month))
    return len(months)


def _find_yearbook_domestic_sheet(
    sheet_names: list[str],
    *,
    path: Optional[Path] = None,
) -> Optional[str]:
    for name in sheet_names:
        if _YEARBOOK_DOMESTIC_SHEET_RE.search(name):
            return name
    if path is None:
        return None
    edition_year = yearbook_edition_year(path)
    best_score = 0
    best_name: Optional[str] = None
    for name in sheet_names:
        try:
            head = pd.read_excel(path, sheet_name=name, header=None, nrows=25)
        except (ValueError, OSError):
            continue
        if "Gasoline" not in head.to_string():
            continue
        layout = _detect_yearbook_layout(head)
        if layout is None:
            continue
        natives = set(layout.value_columns.values())
        if len(natives) < 10:
            continue
        if len(layout.value_columns) - len(natives) > 3:
            continue
        score = _score_yearbook_domestic_sheet(path, name, layout, edition_year)
        if score > best_score:
            best_score = score
            best_name = name
    return best_name


@dataclass(frozen=True)
class _YearbookLayout:
    data_start: int
    value_columns: dict[int, str]
    era_col: int
    year_col: int
    month_col: int
    en_col: int


def _detect_yearbook_layout(df: pd.DataFrame) -> Optional[_YearbookLayout]:
    """Detect 年報 domestic-sales column map (layout differs pre/post ~2021)."""
    header_row: Optional[int] = None
    value_columns: dict[int, str] = {}
    for r in range(min(12, len(df))):
        row_txt = " ".join(
            str(df.iat[r, c]) for c in range(df.shape[1]) if pd.notna(df.iat[r, c])
        )
        if "Gasoline" in row_txt and "Naphtha" in row_txt:
            header_row = r
            break
    if header_row is None:
        return None

    for r in (header_row, header_row - 1):
        if r < 0:
            continue
        for c in range(df.shape[1]):
            cell = str(df.iat[r, c]).strip() if pd.notna(df.iat[r, c]) else ""
            if not cell or _YB_SKIP_COL_RE.search(cell):
                continue
            for pat, native in _YB_COL_PATTERNS:
                if pat.search(cell) and c not in value_columns:
                    value_columns[c] = native
                    break

    era_col, year_col, month_col = 1, 2, 3
    for r in range(min(8, len(df))):
        for c in range(min(6, df.shape[1])):
            if "年・期・月" in str(df.iat[r, c]):
                era_col, year_col, month_col = c, c + 1, c + 2
                break

    en_col = 21 if df.shape[1] > 21 else df.shape[1] - 1
    return _YearbookLayout(
        data_start=header_row + 1,
        value_columns=value_columns,
        era_col=era_col,
        year_col=year_col,
        month_col=month_col,
        en_col=en_col,
    )


def _kakuhou_skip_period_cell(cell: object) -> bool:
    if cell is None or (isinstance(cell, float) and pd.isna(cell)):
        return True
    text = str(cell).strip()
    if not text or _SKIP_PERIOD_RE.search(text):
        return True
    if _YEARBOOK_QUARTER_RE.search(text):
        return True
    if "年度" in text:
        return True
    if "年" in text and "月" not in text and _MONTH_ONLY_RE.match(text) is None:
        # 確報 uses 令和８年　１ (no 月) for the first month of a Reiwa year block.
        if _REIWA_YEAR_MONTH_RE.search(text):
            return False
        return True
    return False


def _kakuhou_domestic_sales_col(
    df: pd.DataFrame, header_row: int, anchor: int
) -> int:
    for c in range(anchor, min(anchor + 12, df.shape[1])):
        cell = str(df.iat[header_row, c]) if pd.notna(df.iat[header_row, c]) else ""
        norm = cell.replace(" ", "").replace("\u3000", "")
        if "国内向販売" in norm or "DomesticSales" in norm.replace(" ", ""):
            return c
    return 4 if anchor <= 5 else 13


def _yearbook_update_era_context(
    c1: object, c2: object, ctx: Optional[tuple[str, int]]
) -> Optional[tuple[str, int]]:
    s1 = str(c1).strip() if pd.notna(c1) else ""
    s2 = str(c2).strip() if pd.notna(c2) else ""
    if "平成" in s1:
        m = re.search(r"(\d+)", s2)
        if m:
            return ("heisei", int(m.group(1)))
    if "令和" in s1:
        m = re.search(r"(\d+)", s2)
        if m:
            return ("reiwa", int(m.group(1)))
    return ctx


def _parse_yearbook_english_period(
    text: str,
    *,
    last_gregorian_year: Optional[int],
) -> tuple[Optional[pd.Timestamp], Optional[int]]:
    text = text.strip()
    m = _EN_MONTH_PERIOD_RE.search(text)
    if m:
        month = _EN_MONTH_TO_NUM[m.group(1).lower()[:3]]
        year = int(m.group(2))
        return pd.Timestamp(year, month, 1), year
    m2 = _EN_MONTH_ONLY_RE.match(text)
    if m2 and last_gregorian_year is not None:
        month = _EN_MONTH_TO_NUM[m2.group(1).lower()[:3]]
        return pd.Timestamp(last_gregorian_year, month, 1), last_gregorian_year
    return None, last_gregorian_year


def _yearbook_row_period(
    df: pd.DataFrame,
    row: int,
    layout: _YearbookLayout,
    *,
    era_ctx: Optional[tuple[str, int]],
    last_gregorian_year: Optional[int],
) -> tuple[Optional[pd.Timestamp], Optional[int], Optional[tuple[str, int]]]:
    ec, yc, mc = layout.era_col, layout.year_col, layout.month_col
    c1 = df.iat[row, ec] if ec < df.shape[1] else None
    c2 = df.iat[row, yc] if yc < df.shape[1] else None
    c3 = df.iat[row, mc] if mc < df.shape[1] else None
    era_ctx = _yearbook_update_era_context(c1, c2, era_ctx)

    if layout.en_col < df.shape[1] and pd.notna(df.iat[row, layout.en_col]):
        en_label = str(df.iat[row, layout.en_col]).strip()
        if _YEARBOOK_EN_AGGREGATE_RE.match(en_label):
            return None, last_gregorian_year, era_ctx
        ts, gy = _parse_yearbook_english_period(
            en_label, last_gregorian_year=last_gregorian_year
        )
        if ts is not None:
            return ts, gy, era_ctx

    if pd.notna(c2) and "年度" in str(c2):
        return None, last_gregorian_year, era_ctx

    c3s = str(c3).strip() if pd.notna(c3) else ""
    if pd.notna(c2):
        s2 = str(c2).strip().translate(str.maketrans("０１２３４５６７８９", "0123456789"))
        if not c3s and _YEARBOOK_YEAR_ONLY_RE.match(s2):
            return None, last_gregorian_year, era_ctx

    if c3s and (_YEARBOOK_QUARTER_RE.search(c3s) or _SKIP_PERIOD_RE.search(c3s)):
        return None, last_gregorian_year, era_ctx

    if era_ctx is None:
        return None, last_gregorian_year, era_ctx

    era, era_num = era_ctx
    label = " ".join(
        str(x).strip() for x in (c1, c2, c3) if pd.notna(x) and str(x).strip()
    )
    if _SKIP_PERIOD_RE.search(label):
        return None, last_gregorian_year, era_ctx

    if era == "reiwa":
        ts: Optional[pd.Timestamp] = None
        if "月" in label:
            ts, _ = parse_period_label(label, reiwa_year=era_num)
        if ts is None and c3s:
            ts, _ = parse_period_label(c3s, reiwa_year=era_num)
        if ts is not None:
            return ts, ts.year, era_ctx
    elif era == "heisei":
        hm = _HEISEI_MONTH_RE.search(label)
        if hm:
            hy, mo = int(hm.group(1)), int(hm.group(2))
            month = _parse_month_number(str(mo))
            if month:
                ts = pd.Timestamp(heisei_to_gregorian_year(hy), month, 1)
                return ts, ts.year, era_ctx
        if c3s:
            mo_m = _MONTH_ONLY_RE.match(c3s)
            if mo_m:
                month = _parse_month_number(mo_m.group(1))
                if month:
                    ts = pd.Timestamp(heisei_to_gregorian_year(era_num), month, 1)
                    return ts, ts.year, era_ctx

    return None, last_gregorian_year, era_ctx


def parse_meti_yearbook_workbook(path: Path) -> pd.DataFrame:
    """Parse 年報（石油） monthly domestic sales (sheet ２（３）…国内向販売)."""
    path = Path(path)
    xl = pd.ExcelFile(path)
    sheet = _find_yearbook_domestic_sheet(xl.sheet_names, path=path)
    if sheet is None:
        return pd.DataFrame(
            columns=["date", "product_native", "value", "unit", "source_file"]
        )

    df = pd.read_excel(path, sheet_name=sheet, header=None)
    layout = _detect_yearbook_layout(df)
    if layout is None or not layout.value_columns:
        return pd.DataFrame(
            columns=["date", "product_native", "value", "unit", "source_file"]
        )

    records: list[dict] = []
    era_ctx: Optional[tuple[str, int]] = None
    last_gy: Optional[int] = None

    for r in range(layout.data_start, len(df)):
        period, last_gy, era_ctx = _yearbook_row_period(
            df, r, layout, era_ctx=era_ctx, last_gregorian_year=last_gy
        )
        if period is None:
            continue

        for native, col in _yearbook_columns_by_product(layout).items():
            if col >= df.shape[1]:
                continue
            val = _coerce_numeric(df.iat[r, col])
            if val is None:
                continue
            unit = METI_UNIT_TONNES if native in _TONNE_PRODUCTS else METI_UNIT_KL
            records.append(
                {
                    "date": period,
                    "product_native": native,
                    "value": val,
                    "unit": unit,
                    "source_file": path.name,
                }
            )

    if not records:
        return pd.DataFrame(columns=["date", "product_native", "value", "unit", "source_file"])
    out = pd.DataFrame(records)
    return (
        out.sort_values(["date", "product_native"])
        .drop_duplicates(subset=["date", "product_native"], keep="first")
        .reset_index(drop=True)
    )


def _find_sokuhou_overview_sheet(sheet_names: list[str]) -> Optional[str]:
    for name in sheet_names:
        if "Supply and Demand Overview" in name:
            return name
    for name in sheet_names:
        if "需給概要" in name and "付" not in name and "7年度" not in name:
            return name
    for name in sheet_names:
        if "需給概要" in name and "付" not in name:
            return name
    return None


def _parse_sokuhou_overview_survey_month(df: pd.DataFrame) -> Optional[pd.Timestamp]:
    """Survey month from 需給概要 / Supply and Demand Overview title cells."""
    for r in range(min(8, len(df))):
        for c in range(min(8, df.shape[1])):
            cell = df.iat[r, c]
            if cell is None or (isinstance(cell, float) and pd.isna(cell)):
                continue
            text = str(cell).strip()
            m = _EN_MONTH_PERIOD_RE.search(text)
            if m:
                month = _EN_MONTH_TO_NUM[m.group(1).lower()[:3]]
                return pd.Timestamp(int(m.group(2)), month, 1)
            rm = _SOKUHO_TITLE_REIWA_MONTH_RE.search(text)
            if rm:
                ry, mo = int(rm.group(1)), int(rm.group(2))
                if 1 <= mo <= 12:
                    return pd.Timestamp(reiwa_to_gregorian_year(ry), mo, 1)
    return _parse_sokuhou_survey_month(df)


def _sokuhou_overview_product_columns(
    df: pd.DataFrame, header_row: int
) -> dict[int, str]:
    out: dict[int, str] = {}
    for c in range(df.shape[1]):
        cell = df.iat[header_row, c]
        if cell is None or (isinstance(cell, float) and pd.isna(cell)):
            continue
        text = str(cell).strip()
        if _SOKUHOU_OVERVIEW_SKIP_PRODUCT_RE.search(text.replace(" ", "")):
            continue
        for pat, native in _SOKUHOU_OVERVIEW_PRODUCT_PATTERNS:
            if pat.search(text) and c not in out:
                out[c] = native
                break
    return out


def _sokuhou_overview_flow_metric(label_cell: object) -> Optional[str]:
    if label_cell is None or (isinstance(label_cell, float) and pd.isna(label_cell)):
        return None
    norm = str(label_cell).replace(" ", "").replace("\u3000", "")
    if not norm or _SOKUHOU_OVERVIEW_SKIP_ROW_RE.search(norm):
        return None
    for metric_type, keys in _SOKUHOU_OVERVIEW_FLOW_LABELS.items():
        for key in keys:
            if key.replace(" ", "").replace("\u3000", "") in norm:
                return metric_type
    return None


def _sokuhou_overview_unit_for_column(
    df: pd.DataFrame, unit_row: int, col: int, product_native: str
) -> str:
    if unit_row < len(df) and col < df.shape[1]:
        unit_cell = str(df.iat[unit_row, col]).strip().lower()
        if unit_cell in {"t", "ｔ"} or "ton" in unit_cell:
            return METI_UNIT_TONNES
    return METI_UNIT_TONNES if product_native in _TONNE_PRODUCTS else METI_UNIT_KL


def parse_meti_sokuhou_supply_overview(path: Path) -> pd.DataFrame:
    """Parse 速報 需給概要 matrix (production / trade / sales / month-end stocks)."""
    path = Path(path)
    xl = pd.ExcelFile(path)
    sheet = _find_sokuhou_overview_sheet(xl.sheet_names)
    if sheet is None:
        return pd.DataFrame(
            columns=[
                "date",
                "product_native",
                "metric_type",
                "value",
                "unit",
                "source_file",
            ]
        )

    df = pd.read_excel(path, sheet_name=sheet, header=None)
    survey = _parse_sokuhou_overview_survey_month(df)
    if survey is None:
        return pd.DataFrame(
            columns=[
                "date",
                "product_native",
                "metric_type",
                "value",
                "unit",
                "source_file",
            ]
        )

    header_row: Optional[int] = None
    for r in range(min(12, len(df))):
        cols = _sokuhou_overview_product_columns(df, r)
        if "gasoline" in cols.values():
            header_row = r
            break
    if header_row is None:
        return pd.DataFrame(
            columns=[
                "date",
                "product_native",
                "metric_type",
                "value",
                "unit",
                "source_file",
            ]
        )

    product_cols = _sokuhou_overview_product_columns(df, header_row)
    unit_row = header_row + 1 if header_row + 1 < len(df) else header_row

    records: list[dict] = []
    for r in range(header_row + 2, len(df)):
        metric_type = _sokuhou_overview_flow_metric(df.iat[r, 0])
        if metric_type is None:
            continue
        for col, native in product_cols.items():
            if col >= df.shape[1]:
                continue
            val = _coerce_numeric(df.iat[r, col])
            if val is None:
                continue
            records.append(
                {
                    "date": survey,
                    "product_native": native,
                    "metric_type": metric_type,
                    "value": val,
                    "unit": _sokuhou_overview_unit_for_column(
                        df, unit_row, col, native
                    ),
                    "source_file": path.name,
                }
            )

    if not records:
        return pd.DataFrame(
            columns=[
                "date",
                "product_native",
                "metric_type",
                "value",
                "unit",
                "source_file",
            ]
        )
    return pd.DataFrame(records)


def parse_meti_sokuhou_legacy_workbook(path: Path) -> pd.DataFrame:
    """Legacy 速報 parser: domestic-sales row only (older sheet layouts)."""
    path = Path(path)
    xl = pd.ExcelFile(path)
    target = _find_sokuhou_overview_sheet(xl.sheet_names)
    if target is None:
        return pd.DataFrame(columns=["date", "product_native", "value", "unit", "source_file"])

    df = pd.read_excel(path, sheet_name=target, header=None)
    survey = _parse_sokuhou_survey_month(df)
    if survey is None:
        return pd.DataFrame(columns=["date", "product_native", "value", "unit", "source_file"])

    header_row = None
    for r in range(min(15, len(df))):
        row0 = str(df.iat[r, 0]).strip()
        if row0.startswith("区") or "燃料油計" in str(df.iat[r, 3]):
            header_row = r if "燃料油計" in str(df.iat[r, 3]) else r + 1
            break
    if header_row is None:
        header_row = 4

    col_map: dict[int, str] = {}
    for c in range(df.shape[1]):
        native = _normalize_sokuhou_header(df.iat[header_row, c])
        if native:
            col_map[c] = native

    domestic_row = None
    for r in range(len(df)):
        row_text = "".join(str(df.iat[r, c]) for c in range(df.shape[1]))
        row_text = row_text.replace(" ", "").replace("\u3000", "")
        if "国内向販売" in row_text and "前年" not in row_text:
            domestic_row = r
            break
    if domestic_row is None:
        return pd.DataFrame(columns=["date", "product_native", "value", "unit", "source_file"])

    records: list[dict] = []
    for c, native in col_map.items():
        val = _coerce_numeric(df.iat[domestic_row, c])
        if val is None:
            continue
        unit = METI_UNIT_TONNES if native in _TONNE_PRODUCTS else METI_UNIT_KL
        records.append(
            {
                "date": survey,
                "product_native": native,
                "metric_type": METI_METRIC_TYPE,
                "value": val,
                "unit": unit,
                "source_file": path.name,
            }
        )

    if not records:
        return pd.DataFrame(columns=["date", "product_native", "value", "unit", "source_file"])
    return pd.DataFrame(records)


def parse_meti_sokuhou_workbook(path: Path) -> pd.DataFrame:
    """Parse a 速報 workbook (supply overview preferred; legacy domestic-only fallback)."""
    overview = parse_meti_sokuhou_supply_overview(path)
    if not overview.empty:
        return overview
    return parse_meti_sokuhou_legacy_workbook(path)


def _source_tier_for_path(path: Path) -> int:
    """Source tier tag for merge priority (see ``_SOURCE_MERGE_PRIORITY``)."""
    if path.parent.name == "yearbook" or _YEARBOOK_FILENAME_RE.search(path.name):
        return 2
    if path.parent.name == "sokuhou" or path.name.lower().startswith("h2j"):
        return 0
    return 1


# Lower sort-key wins on keep-first: 確報 (1) > 年報 (2) > 速報 (0).
_SOURCE_MERGE_PRIORITY: dict[int, int] = {0: 2, 1: 0, 2: 1}


def discover_yearbook_paths(raw_dir: Path) -> list[Path]:
    """All local 年報 xlsx under ``yearbook/`` or ``raw_dir`` (excludes ``_probe``)."""
    raw_dir = Path(raw_dir)
    found: dict[str, Path] = {}
    candidates: list[Path] = []
    for pattern in ("h2dhhpe*.xlsx", "h2dhhpe*.xls"):
        candidates.extend((raw_dir / "yearbook").glob(pattern))
        candidates.extend(raw_dir.glob(pattern))
    for path in candidates:
        if "_probe" in path.parts:
            continue
        found[path.name] = path.resolve()
    return [found[k] for k in sorted(found)]


def parse_meti_workbook(path: Path, *, is_provisional: bool) -> pd.DataFrame:
    """Dispatch to 年報 / 速報 / 確報 parser based on filename / content."""
    path = Path(path)
    name = path.name.lower()
    if _YEARBOOK_FILENAME_RE.search(name) or path.parent.name == "yearbook":
        df = parse_meti_yearbook_workbook(path)
    elif name.startswith("h2j") or "soku" in name or path.parent.name == "sokuhou":
        df = parse_meti_sokuhou_workbook(path)
    elif _KAKUHOU_FILENAME_RE.search(name) or "kak" in name or path.parent.name == "kakuhou":
        df = parse_meti_kakuhou_workbook(path)
    else:
        # Try sokuhō first (small sheet count), else 確報
        xl = pd.ExcelFile(path)
        if any("需給概要" in s for s in xl.sheet_names):
            df = parse_meti_sokuhou_workbook(path)
        elif _find_yearbook_domestic_sheet(xl.sheet_names):
            df = parse_meti_yearbook_workbook(path)
        else:
            df = parse_meti_kakuhou_workbook(path)

    if df.empty:
        return df
    df = df.copy()
    df["is_provisional"] = is_provisional
    return df


def is_meti_primary(product_native: str) -> bool:
    """True if ``product_native`` is a primary row in ``product_map.csv`` (METI)."""
    try:
        return is_primary(product_native, METI_AGENCY_SOURCE)
    except KeyError:
        return False


def filter_primary_rows(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    mask = df["product_native"].map(is_meti_primary)
    return df.loc[mask].copy()


def parse_meti_paths(paths: list[Path]) -> pd.DataFrame:
    """Parse and stitch multiple workbooks; final rows beat preliminary on duplicate keys."""
    paths = sorted({Path(p) for p in paths}, key=lambda p: (p.name, str(p)))
    if not paths:
        return pd.DataFrame(
            columns=["date", "product_native", "value", "unit", "source_file", "is_provisional"]
        )

    frames: list[pd.DataFrame] = []
    seq = 0
    for p in paths:
        prov = "sokuhou" in p.parts or p.name.lower().startswith("h2j")
        part = parse_meti_workbook(p, is_provisional=prov)
        part["source_tier"] = _source_tier_for_path(p)
        part["_parse_seq"] = range(seq, seq + len(part))
        seq += len(part)
        frames.append(part)

    combined = pd.concat(frames, ignore_index=True)
    combined = filter_primary_rows(combined)
    # 確報 > 年報 > 速報; within one file keep earliest table (first product block).
    combined["_sort_key"] = (
        combined["is_provisional"].astype(int) * 1_000_000_000
        + combined["source_tier"].map(_SOURCE_MERGE_PRIORITY) * 1_000_000
        + combined["_parse_seq"]
    )
    if "metric_type" not in combined.columns:
        combined["metric_type"] = METI_METRIC_TYPE
    else:
        combined["metric_type"] = combined["metric_type"].fillna(METI_METRIC_TYPE)

    combined = combined.sort_values(
        ["date", "product_native", "metric_type", "_sort_key"],
        ascending=[True, True, True, True],
    )
    return (
        combined.drop_duplicates(
            subset=["date", "product_native", "metric_type"], keep="first"
        )
        .drop(columns=["_parse_seq", "_sort_key"], errors="ignore")
        .sort_values(["date", "metric_type", "product_native"], ignore_index=True)
    )


def parse_meti_directory(raw_dir: Path) -> pd.DataFrame:
    raw_dir = Path(raw_dir)
    paths: list[Path] = list(discover_yearbook_paths(raw_dir))
    for sub in ("kakuhou", "sokuhou"):
        d = raw_dir / sub
        if d.is_dir():
            paths.extend(sorted(d.glob("*.xlsx")))
    if not paths:
        raise FileNotFoundError(
            f"No METI .xlsx under {raw_dir} (yearbook, kakuhou, or sokuhou)"
        )
    return parse_meti_paths(paths)


def seasonality_highlight_year(
    df: pd.DataFrame,
    *,
    date_col: str = "date",
    min_months: int = 6,
) -> int:
    """Calendar year to emphasise on seasonality charts.

    Uses the latest year with at least ``min_months`` distinct months so a lone
    速報 month (e.g. only 2026-03) does not draw a one-point '2026' line.
    """
    if df.empty or date_col not in df.columns:
        return pd.Timestamp.today().year
    dates = pd.to_datetime(df[date_col])
    month_counts = (
        pd.DataFrame({"year": dates.dt.year, "month": dates.dt.month})
        .groupby("year")["month"]
        .nunique()
    )
    max_year = int(month_counts.index.max())
    if int(month_counts.get(max_year, 0)) >= min_months:
        return max_year
    complete = month_counts[month_counts >= min_months]
    if len(complete):
        return int(complete.index.max())
    return max_year


def sum_fuel_oil_by_date(
    df: pd.DataFrame,
    *,
    value_col: str = "value",
) -> pd.DataFrame:
    """Sum Ｂ・Ｃ重油 (heavy fuel oil) by date — canonical Fuel oil / JODI RESFUEL."""
    sl = df[df["product_native"].isin(FUEL_OIL_HEAVY_NATIVE)]
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
        return df, "product_native", products, DISPLAY_LABELS, "native products"
    if view == "canonical":
        products = [
            p
            for p in SEASONALITY_PANELS_CANONICAL
            if p in demand_canonical["panel"].values
        ]
        df = demand_canonical[demand_canonical["panel"].isin(products)].copy()
        return df, "panel", products, {p: p for p in products}, "canonical products"
    raise ValueError(f"view must be 'native' or 'canonical', got {view!r}")


def meti_series_for_jodi(
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


def build_demand_canonical(
    demand: pd.DataFrame,
    *,
    value_col: str = "value_kbd",
) -> pd.DataFrame:
    """Roll up METI natives to ``product_canonical`` (from parquet / product_map)."""
    sl = demand[demand["product_canonical"].notna()].copy()
    if sl.empty:
        return pd.DataFrame(
            columns=["date", "product_canonical", value_col, "is_provisional", "panel"]
        )
    out = (
        sl.groupby(["date", "product_canonical", "is_provisional"], as_index=False)[
            value_col
        ]
        .sum()
        .sort_values(["date", "product_canonical"])
    )
    out["panel"] = out["product_canonical"]
    return out


def jodi_compare_energy_products() -> list[str]:
    """Distinct JODI ``energy_product`` codes used in ``JODI_COMPARE_SERIES``."""
    return list(
        dict.fromkeys(spec.jodi_energy_product for spec in JODI_COMPARE_SERIES.values())
    )


def build_meti_jodi_panel_frames(
    demand: pd.DataFrame,
    jodi: pd.DataFrame,
    *,
    value_col: str = "value_kbd",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Long-form METI and JODI frames with aligned ``panel`` labels for §5 charts.

    METI ``gas_oil`` + ``fuel_oil_a`` are summed in the Gas/diesel oil panel vs JODI
    ``GASDIES``.
    """
    meti_parts: list[pd.DataFrame] = []
    jodi_parts: list[pd.DataFrame] = []
    jodi_jp = jodi[
        (jodi["ref_area"] == "JP")
        & (jodi["flow_breakdown"] == "TOTDEMO")
        & (jodi["unit_measure"] == "KBD")
    ].copy()

    for spec in JODI_COMPARE_SERIES.values():
        m = meti_series_for_jodi(demand, spec.key, value_col=value_col)
        if m.empty:
            continue
        m = m.groupby("date", as_index=False)[value_col].sum()
        m["panel"] = spec.panel
        meti_parts.append(m[["date", "panel", value_col]])

        jsl = jodi_jp[jodi_jp["energy_product"] == spec.jodi_energy_product].copy()
        if jsl.empty:
            continue
        jsl["panel"] = spec.panel
        jsl[value_col] = jsl["obs_value"]
        jodi_parts.append(jsl[["date", "panel", value_col]])

    meti_panel = (
        pd.concat(meti_parts, ignore_index=True)
        if meti_parts
        else pd.DataFrame(columns=["date", "panel", value_col])
    )
    jodi_panel = (
        pd.concat(jodi_parts, ignore_index=True)
        if jodi_parts
        else pd.DataFrame(columns=["date", "panel", value_col])
    )
    return meti_panel, jodi_panel


def build_meti_jodi_clostlv_panel_frames(
    inventories: pd.DataFrame,
    jodi: pd.DataFrame,
    *,
    value_col: str = "value_kb",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Long-form METI and JODI closing-stock frames with aligned ``panel`` labels.

    METI stocks are month-end levels (native kL/t); JODI ``CLOSTLV`` is taken in
    ``KBBL`` (thousand barrels, same numeric scale as METI ``value_kb``).
    """
    meti_parts: list[pd.DataFrame] = []
    jodi_parts: list[pd.DataFrame] = []
    jodi_jp = jodi[
        (jodi["ref_area"] == "JP")
        & (jodi["flow_breakdown"] == "CLOSTLV")
        & (jodi["unit_measure"] == "KBBL")
    ].copy()

    for spec in JODI_COMPARE_SERIES.values():
        m = meti_series_for_jodi(inventories, spec.key, value_col=value_col)
        if m.empty:
            continue
        m = m.groupby("date", as_index=False)[value_col].sum()
        m["panel"] = spec.panel
        meti_parts.append(m[["date", "panel", value_col]])

        jsl = jodi_jp[jodi_jp["energy_product"] == spec.jodi_energy_product].copy()
        if jsl.empty:
            continue
        jsl["panel"] = spec.panel
        jsl[value_col] = jsl["obs_value"]
        jodi_parts.append(jsl[["date", "panel", value_col]])

    meti_panel = (
        pd.concat(meti_parts, ignore_index=True)
        if meti_parts
        else pd.DataFrame(columns=["date", "panel", value_col])
    )
    jodi_panel = (
        pd.concat(jodi_parts, ignore_index=True)
        if jodi_parts
        else pd.DataFrame(columns=["date", "panel", value_col])
    )
    return meti_panel, jodi_panel


def jodi_compare_panels_present(meti_panel: pd.DataFrame) -> list[str]:
    """Panel order for charts, keeping only panels with METI data."""
    have = set(meti_panel["panel"].unique())
    return [p for p in JODI_COMPARE_PANEL_ORDER if p in have]


__all__ = [
    "METI_AGENCY_SOURCE",
    "METI_DATASET_SOURCE",
    "METI_METRIC_TYPE",
    "METI_KAKUHOU_FLOW_HEADERS",
    "METI_SUPPLY_METRIC_TYPES",
    "INVENTORY_FOCUS_START",
    "METI_UNIT_KL",
    "COUNTRY_CODE",
    "COUNTRY_NAME",
    "SOURCE_ID",
    "DELIVERY_HEADLINE_NATIVE",
    "CHART_PRODUCTS",
    "SEASONALITY_NATIVE_PRODUCTS",
    "SEASONALITY_PANELS_CANONICAL",
    "DISPLAY_LABELS",
    "UNITS_KIND",
    "FUEL_OIL_HEAVY_NATIVE",
    "FUEL_OIL_NATIVE",
    "GASDIES_COMPARE_NATIVE",
    "JODI_COMPARE_SERIES",
    "JODI_COMPARE_PANEL_ORDER",
    "JodiCompareSeries",
    "parse_period_label",
    "heisei_to_gregorian_year",
    "parse_kakuhou_filename",
    "parse_meti_yearbook_workbook",
    "parse_meti_kakuhou_workbook",
    "parse_meti_sokuhou_workbook",
    "parse_meti_workbook",
    "parse_meti_paths",
    "parse_meti_directory",
    "discover_yearbook_paths",
    "yearbook_edition_year",
    "seasonality_highlight_year",
    "sum_fuel_oil_by_date",
    "seasonality_chart_inputs",
    "meti_series_for_jodi",
    "build_demand_canonical",
    "jodi_compare_energy_products",
    "build_meti_jodi_panel_frames",
    "build_meti_jodi_clostlv_panel_frames",
    "jodi_compare_panels_present",
]
