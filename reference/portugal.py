"""
reference.portugal
──────────────────
DGEG (Direção-Geral de Energia e Geologia) — Monthly Sales of Oil Products.

Workbooks are one calendar year per file (or multi-year ``.xls`` bundles before
~2006). Units: tonnes. Stored natives use ``{Section} | {Product}`` keys in
English; Portuguese and legacy labels are normalized in ``LABEL_TO_NATIVE``.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

DGEG_AGENCY_SOURCE = "DGEG"
DGEG_DATASET_SOURCE = "portugal_petroleum_sales"
DGEG_METRIC_TYPE = "TOTDEMO"
DGEG_UNIT_NATIVE = "t"

COUNTRY_CODE = "PT"
COUNTRY_NAME = "Portugal"
SOURCE_ID = DGEG_DATASET_SOURCE

MONTHLY_SALES_PAGE = (
    "https://www.dgeg.gov.pt/en/statistics/energy-statistics/"
    "oil-and-related-products/monthly-sales/"
)

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

SECTION_INTERNAL = "Internal Market"
SECTION_MARINE = "Marine Bunkers (e)"
SECTION_AVIATION = "Aviation"

# Section headers in workbooks (normalized matching).
_SECTION_INTERNAL = frozenset({"internal market", "mercado interno"})
_SECTION_MARINE = frozenset(
    {
        "marine bunkers (e)",
        "marine bunkers",
        "mercado de bancas maritimas (e)",
        "mercado de bancas",
        "mercado de bancas maritimas",
    }
)
_SECTION_AVIATION = frozenset(
    {"aviation", "mercado de aviacao", "mercado de aviacao "}
)
_SKIP_SECTIONS = frozenset(
    {
        "memo fuel",
        "biofuels (g)",
        "biofuels (f)",
        "biocombustiveis (g)",
        "biocombustiveis (f)",
        "biocombustiveis",
    }
)

_MONTH_NUM: dict[str, int] = {
    "january": 1,
    "jan": 1,
    "janeiro": 1,
    "february": 2,
    "feb": 2,
    "fevereiro": 2,
    "march": 3,
    "mar": 3,
    "marco": 3,
    "march ": 3,
    "april": 4,
    "apr": 4,
    "abril": 4,
    "may": 5,
    "mai": 5,
    "june": 6,
    "jun": 6,
    "junho": 6,
    "july": 7,
    "jul": 7,
    "julho": 7,
    "august": 8,
    "aug": 8,
    "agosto": 8,
    "september": 9,
    "sep": 9,
    "setembro": 9,
    "october": 10,
    "oct": 10,
    "outubro": 10,
    "november": 11,
    "nov": 11,
    "novembro": 11,
    "december": 12,
    "dec": 12,
    "dezembro": 12,
}

_YEAR_TITLE_RE = re.compile(
    r"(?:Monthly Sales of Oil Products in Portugal|"
    r"Vendas Mensais de (?:Combust[ií]veis|Produtos de Petr[oó]leo)(?: em Portugal)?)"
    r"\s+(\d{4})",
    re.I,
)
_YEAR_SHEET_RE = re.compile(r"^\d{4}$")
_YEAR_FILE_RE = re.compile(r"dgeg-omn-(\d{4})", re.I)

_SKIP_ROW_PREFIXES = (
    "of which",
    "source ",
    "(a)",
    "(b)",
    "(c)",
    "(d)",
    "(e)",
    "(f)",
    "(g)",
    "unidade:",
    "unit:",
)

# Stored primary lines — must match product_map.csv Product_name values.
STORED_NATIVES: frozenset[str] = frozenset(
    {
        f"{SECTION_INTERNAL} | Butane",
        f"{SECTION_INTERNAL} | Propane",
        f"{SECTION_INTERNAL} | LPG Auto",
        f"{SECTION_INTERNAL} | Gasoline ON98 (a)",
        f"{SECTION_INTERNAL} | Gasoline ON95 (b)",
        f"{SECTION_INTERNAL} | Gasoline super additive",
        f"{SECTION_INTERNAL} | Naphtha and Aromatics",
        f"{SECTION_INTERNAL} | Oils (kerosene + fuel)",
        f"{SECTION_INTERNAL} | Road diesel (c)",
        f"{SECTION_INTERNAL} | Coloured diesel for heating purposes",
        f"{SECTION_INTERNAL} | Coloured diesel, except for heating purposes",
        f"{SECTION_INTERNAL} | Coloured diesel (legacy)",
        f"{SECTION_INTERNAL} | Thin low-sulphur fuel oil (<=1%)",
        f"{SECTION_INTERNAL} | Thick low-sulphur fuel oil (<=1%)",
        f"{SECTION_INTERNAL} | Petroleum coke",
        f"{SECTION_INTERNAL} | Lubricants",
        f"{SECTION_INTERNAL} | Asphalt",
        f"{SECTION_INTERNAL} | Paraffins",
        f"{SECTION_INTERNAL} | Solvents",
        f"{SECTION_MARINE} | Diesel (f)",
        f"{SECTION_MARINE} | Coloured diesel",
        f"{SECTION_MARINE} | Marine fuel oil",
        f"{SECTION_MARINE} | Thin fuel oil",
        f"{SECTION_MARINE} | Thick fuel oil",
        f"{SECTION_MARINE} | Lubricants",
        f"{SECTION_AVIATION} | Aviation gasoline",
        f"{SECTION_AVIATION} | Jet fuel",
    }
)


def product_native(section: str, label: str) -> str:
    return f"{section} | {label.strip()}"


def is_dgeg_stored(native: str) -> bool:
    return native in STORED_NATIVES


def _ascii_fold(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text)
    return folded.encode("ascii", "ignore").decode("ascii")


def _normalize_label(text: str) -> str:
    text = _ascii_fold(str(text)).lower().strip()
    text = re.sub(r"\s+", " ", text)
    text = text.rstrip(":")
    return text


def _normalize_section(text: str) -> Optional[str]:
    key = _normalize_label(text)
    if key in _SKIP_SECTIONS:
        return None
    if key in _SECTION_INTERNAL:
        return SECTION_INTERNAL
    if key in _SECTION_MARINE:
        return SECTION_MARINE
    if key in _SECTION_AVIATION:
        return SECTION_AVIATION
    return None


def _is_skip_row(label: str) -> bool:
    key = _normalize_label(label)
    if not key or key == "0":
        return True
    if key in _SKIP_SECTIONS:
        return True
    if key.startswith(_SKIP_ROW_PREFIXES):
        return True
    if key in {"total", "totals"}:
        return True
    # Memo-fuel breakdown rows (already counted in product lines above).
    if key.startswith("fuel for ") or key.startswith("fuel para "):
        return True
    if key.startswith("fuel industria") or key.startswith("fuel ( edp"):
        return True
    if "biodiesel" in key or "bioethanol" in key or "biogasolina" in key:
        return True
    if key in {"propileno", "propylene"}:
        return True
    return False


# (section, normalized_label) -> native product name (without section prefix).
_LABEL_TO_PRODUCT: dict[tuple[str, str], str] = {}
# Fallback when section is unknown (internal-market flat files).
_FLAT_LABEL_TO_PRODUCT: dict[str, str] = {}


def _register(section: str, *labels: str, product: str) -> None:
    for label in labels:
        _LABEL_TO_PRODUCT[(section, _normalize_label(label))] = product


def _register_flat(*labels: str, product: str, section: str = SECTION_INTERNAL) -> None:
    for label in labels:
        key = _normalize_label(label)
        _FLAT_LABEL_TO_PRODUCT[key] = product
        _LABEL_TO_PRODUCT[(section, key)] = product


def _build_label_maps() -> None:
    if _LABEL_TO_PRODUCT:
        return

    _register_flat("Butane", "Butano", product="Butane")
    _register_flat("Propane", "Propano", product="Propane")
    _register_flat("LPG Auto", "Gas. Auto", "Gas Auto", "Gas Auto", product="LPG Auto")

    _register(
        SECTION_INTERNAL,
        "Gasoline ON98 (a)",
        "Gasolina s/ Chumbo 98 (a)",
        "Gas. s/Chumbo  98",
        "Gas. s/chumbo 98",
        product="Gasoline ON98 (a)",
    )
    _register(
        SECTION_INTERNAL,
        "Gasoline ON95 (b)",
        "Gasolina s/ Chumbo 95 (b)",
        "Gas. s/Chumbo  95",
        "Gas. s/chumbo 95",
        product="Gasoline ON95 (b)",
    )
    _register(
        SECTION_INTERNAL,
        "Gas. Super Aditivada",
        "Gasolina super aditivada",
        product="Gasoline super additive",
    )

    _register(
        SECTION_INTERNAL,
        "Naphtha and Aromatics",
        "Nafta Quimica e Aromaticos",
        "Nafta Quimica",
        product="Naphtha and Aromatics",
    )
    _register(
        SECTION_INTERNAL,
        "Materia Prima de Aromaticos",
        "M.Prima de Aromaticos",
        "Res. AV",
        product="Naphtha and Aromatics",
    )

    _register(
        SECTION_INTERNAL,
        "Oils (kerosene + fuel)",
        "Petroleo (Iluminante + carburante)",
        product="Oils (kerosene + fuel)",
    )
    _register(
        SECTION_INTERNAL,
        "Petroleo Iluminante",
        product="Oils (kerosene + fuel)",
    )
    _register(
        SECTION_INTERNAL,
        "Petroleo Carburante",
        product="Oils (kerosene + fuel)",
    )

    _register(
        SECTION_INTERNAL,
        "Road diesel (c)",
        "Gasoleo Rodoviario (c)",
        "Gasoleo",
        product="Road diesel (c)",
    )
    _register(
        SECTION_INTERNAL,
        "Coloured diesel for heating purposes",
        "Gasoleo colorido e marcado destinado a aquecimento",
        product="Coloured diesel for heating purposes",
    )
    _register(
        SECTION_INTERNAL,
        "Coloured diesel, except for heating purposes",
        "Gasoleo colorido e marcado, exceto o destinado a aquecimento",
        product="Coloured diesel, except for heating purposes",
    )
    _register(
        SECTION_INTERNAL,
        "Gasoleo colorido e marcado",
        "Coloured diesel (legacy)",
        product="Coloured diesel (legacy)",
    )

    _register(
        SECTION_INTERNAL,
        "Thin low-sulphur fuel oil (<=1%)",
        "Thin-Fuel-Oil",
        "Thin fuel oil",
        "Fueloleo no3 BTE",
        "Burner's Oil",
        product="Thin low-sulphur fuel oil (<=1%)",
    )
    _register(
        SECTION_INTERNAL,
        "Thick low-sulphur fuel oil (<=1%)",
        "Thick-Fuel-Oil 1%",
        "Thick-Fuel-Oil 1%S",
        "Fueloleo no4 BTE",
        product="Thick low-sulphur fuel oil (<=1%)",
    )
    _register(
        SECTION_INTERNAL,
        "Thick-Fuel-Oil 3,5%",
        "Thick-Fuel-Oil 3.5%S",
        product="Thick low-sulphur fuel oil (<=1%)",
    )

    _register_flat("Petroleum coke", "Coque de Petroleo", product="Petroleum coke")
    _register_flat("Lubricants", "Lubrificantes", product="Lubricants")
    _register_flat("Asphalt", "Asfaltos", product="Asphalt")
    _register_flat("Paraffins", "Parafinas", product="Paraffins")
    _register_flat("Solvents", "Solventes", product="Solvents")

    _register(
        SECTION_MARINE,
        "Diesel (f)",
        "Gasoleo (f)",
        "Gasoleo",
        product="Diesel (f)",
    )
    _register(
        SECTION_MARINE,
        "Coloured diesel",
        "Gasoleo colorido e marcado",
        product="Coloured diesel",
    )
    _register(
        SECTION_MARINE,
        "Marine fuel oil",
        "Fueloleo Naval BTE (com baixo teor de enxofre, <=1%)",
        "Fueloleo Naval ATE (com alto teor de enxofre, >1%)",
        "Thick-Fuel-Oil",
        product="Marine fuel oil",
    )
    _register(
        SECTION_MARINE,
        "Thin-Fuel-Oil",
        "Fueloleo no3 BTE (Thin Fuel Oil)",
        product="Thin fuel oil",
    )
    _register(
        SECTION_MARINE,
        "Thick-Fuel-Oil 3,5%S",
        product="Thick fuel oil",
    )
    _register(
        SECTION_MARINE,
        "Thick-Fuel-Oil 1%S",
        product="Thick fuel oil",
    )
    _register(SECTION_MARINE, "Lubricants", "Lubrificantes", product="Lubricants")

    _register(
        SECTION_AVIATION,
        "Aviation gasoline",
        "Av. Gas.",
        "Gasolina de aviacao",
        product="Aviation gasoline",
    )
    _register(
        SECTION_AVIATION,
        "Jet fuel",
        "Jet",
        "JP1",
        "JP8",
        product="Jet fuel",
    )


_build_label_maps()


def _resolve_native(section: Optional[str], label: str) -> Optional[str]:
    if _is_skip_row(label):
        return None
    key = _normalize_label(label)
    product: Optional[str] = None
    if section is not None:
        product = _LABEL_TO_PRODUCT.get((section, key))
    if product is None:
        product = _FLAT_LABEL_TO_PRODUCT.get(key)
    if product is None:
        return None
    native = product_native(section or SECTION_INTERNAL, product)
    if not is_dgeg_stored(native):
        return None
    return native


def _month_columns(header_row: pd.Series) -> list[tuple[int, int]]:
    """Return (column_index, month_number) pairs from a header row."""
    out: list[tuple[int, int]] = []
    for idx, raw in enumerate(header_row):
        if idx == 0:
            continue
        if raw is None or (isinstance(raw, float) and pd.isna(raw)):
            continue
        text = _normalize_label(str(raw))
        if text in {"total", "totals"}:
            continue
        month = _MONTH_NUM.get(text)
        if month is not None:
            out.append((idx, month))
    return out


def _extract_year_from_title(df: pd.DataFrame) -> Optional[int]:
    for i in range(min(8, len(df))):
        for j in range(min(3, len(df.columns))):
            val = df.iloc[i, j]
            if pd.isna(val):
                continue
            text = str(val)
            m = _YEAR_TITLE_RE.search(text)
            if m:
                for g in m.groups():
                    if g:
                        return int(g)
            folded = _ascii_fold(text)
            m2 = re.search(
                r"vendas mensais de (?:combustiveis|produtos de petroleo) em (\d{4})",
                folded,
                re.I,
            )
            if m2:
                return int(m2.group(1))
    return None


def _extract_year(path: Path, sheet_name: str, df: pd.DataFrame) -> Optional[int]:
    if _YEAR_SHEET_RE.match(str(sheet_name).strip()):
        return int(str(sheet_name).strip())
    from_title = _extract_year_from_title(df)
    if from_title is not None:
        return from_title
    m = _YEAR_FILE_RE.search(path.name)
    if m:
        return int(m.group(1))
    m = re.search(r"(20\d{2}|19\d{2})", path.stem)
    if m:
        return int(m.group(1))
    return None


def _is_provisional_workbook(df: pd.DataFrame) -> bool:
    for i in range(min(8, len(df))):
        for j in range(min(3, len(df.columns))):
            val = df.iloc[i, j]
            if pd.isna(val):
                continue
            text = _normalize_label(str(val))
            if "provisional" in text or "provisorio" in text:
                return True
            if "definitiv" in text:
                return False
    return False


def _find_header_row(df: pd.DataFrame) -> Optional[int]:
    for i in range(min(20, len(df))):
        months = _month_columns(df.iloc[i])
        if len(months) >= 6:
            return i
    return None


def _parse_sheet(
    df: pd.DataFrame,
    *,
    year: int,
    source_file: str,
    is_provisional: bool,
) -> list[dict]:
    header_idx = _find_header_row(df)
    if header_idx is None:
        return []

    month_cols = _month_columns(df.iloc[header_idx])
    if not month_cols:
        return []

    # Old flat workbooks start in internal market before an explicit section row.
    section: Optional[str] = SECTION_INTERNAL
    first_cell = df.iloc[header_idx, 0]
    if pd.notna(first_cell):
        detected = _normalize_section(str(first_cell))
        if detected is not None:
            section = detected

    accum: dict[tuple[pd.Timestamp, str], float] = {}

    for row_idx in range(header_idx + 1, len(df)):
        label_raw = df.iloc[row_idx, 0]
        if pd.isna(label_raw):
            continue
        label = str(label_raw).strip()
        if not label:
            continue

        detected_section = _normalize_section(label)
        if detected_section is not None:
            section = detected_section
            continue
        if _normalize_label(label) in _SKIP_SECTIONS:
            section = None
            continue

        native = _resolve_native(section, label)
        if native is None:
            continue

        for col_idx, month in month_cols:
            val = df.iloc[row_idx, col_idx]
            if pd.isna(val):
                continue
            try:
                value = float(val)
            except (TypeError, ValueError):
                continue
            if value == 0:
                continue
            ts = pd.Timestamp(year=year, month=month, day=1)
            key = (ts, native)
            accum[key] = accum.get(key, 0.0) + value

    return [
        {
            "date": ts,
            "product_native": native,
            "value": value,
            "source_file": source_file,
            "is_provisional": is_provisional,
        }
        for (ts, native), value in accum.items()
    ]


def parse_dgeg_sales_workbook(path: Path) -> pd.DataFrame:
    """Parse one DGEG monthly-sales workbook into partial long form."""
    path = Path(path)
    suffix = path.suffix.lower()
    engine = "xlrd" if suffix == ".xls" else "openpyxl"
    xl = pd.ExcelFile(path, engine=engine)

    rows: list[dict] = []
    for sheet in xl.sheet_names:
        df = pd.read_excel(path, sheet_name=sheet, header=None, engine=engine)
        year = _extract_year(path, sheet, df)
        if year is None or year < 1995 or year > 2035:
            continue
        provisional = _is_provisional_workbook(df)
        rows.extend(
            _parse_sheet(
                df,
                year=year,
                source_file=path.name,
                is_provisional=provisional,
            )
        )

    if not rows:
        return pd.DataFrame(
            columns=["date", "product_native", "value", "source_file", "is_provisional"]
        )
    return pd.DataFrame(rows)


def file_years(path: Path) -> set[int]:
    """Best-effort list of calendar years contained in a workbook."""
    path = Path(path)
    suffix = path.suffix.lower()
    engine = "xlrd" if suffix == ".xls" else "openpyxl"
    years: set[int] = set()
    try:
        xl = pd.ExcelFile(path, engine=engine)
    except Exception:
        return years
    for sheet in xl.sheet_names:
        if _YEAR_SHEET_RE.match(str(sheet).strip()):
            years.add(int(str(sheet).strip()))
            continue
        df = pd.read_excel(path, sheet_name=sheet, header=None, engine=engine)
        y = _extract_year(path, sheet, df)
        if y is not None:
            years.add(y)
    return years


def finalize_dgeg_frame(
    partial: pd.DataFrame,
    *,
    updated_at: datetime,
    country: str = COUNTRY_CODE,
    country_name: str = COUNTRY_NAME,
    source: str = DGEG_DATASET_SOURCE,
    metric_type: str = DGEG_METRIC_TYPE,
    unit: str = DGEG_UNIT_NATIVE,
) -> pd.DataFrame:
    if partial.empty:
        return pd.DataFrame(columns=CANONICAL_COLUMNS)

    df = partial.copy()
    df["country"] = country
    df["country_name"] = country_name
    df["source"] = source
    df["metric_type"] = metric_type
    df["product"] = df["product_native"]
    df["unit"] = unit
    df["updated_at"] = updated_at
    return df[CANONICAL_COLUMNS].sort_values(
        ["date", "product_native"], ignore_index=True
    )


def workbook_sort_key(path: Path) -> tuple:
    """Sort key so later items win in ``parse_all_workbooks`` merges.

    Year/month come from the filename first so remote discovery can rank
    workbooks before they exist on disk (``file_years`` needs an openable file).
    """
    path = Path(path)
    # Filename year (dgeg-omn-YYYY-...) — do not depend on opening the xlsx.
    m_year = _YEAR_FILE_RE.search(path.name)
    if m_year:
        max_year = int(m_year.group(1))
    else:
        years = file_years(path) if path.exists() else set()
        if years:
            max_year = max(years)
        else:
            m = re.search(r"(20\d{2}|19\d{2})", path.stem)
            max_year = int(m.group(1)) if m else 0

    is_omn = 1 if "dgeg-omn" in path.name.lower() else 0
    is_xlsx = 1 if path.suffix.lower() == ".xlsx" else 0
    # Real month token only: -05_en, -12.xlsx — not date stamps like -20230731.
    mm = 0
    m = re.search(r"dgeg-omn-\d{4}-(\d{2})(?:[_./]|$)", path.name, re.I)
    if m:
        month = int(m.group(1))
        if 1 <= month <= 12:
            mm = month
    rev_n = 0
    rev = re.search(r"_v(\d{8})", path.name, re.I)
    if rev:
        rev_n = int(rev.group(1))
    return (max_year, is_omn, is_xlsx, mm, rev_n, path.name)


def parse_all_workbooks(paths: list[Path]) -> pd.DataFrame:
    """
    Parse many yearly workbooks and merge, preferring newer files for overlaps.

    When two files cover the same (date, product_native), the path that sorts
    later by ``workbook_sort_key`` wins.
    """
    ordered = sorted({Path(p) for p in paths}, key=workbook_sort_key)
    merged: dict[tuple[pd.Timestamp, str], dict] = {}

    for path in ordered:
        partial = parse_dgeg_sales_workbook(path)
        for rec in partial.to_dict("records"):
            key = (rec["date"], rec["product_native"])
            merged[key] = rec

    if not merged:
        return pd.DataFrame(
            columns=["date", "product_native", "value", "source_file", "is_provisional"]
        )
    return pd.DataFrame(list(merged.values()))


# JODI compare composites (stored natives only).
GASOLINE_JODI_NATIVES: frozenset[str] = frozenset(
    n
    for n in STORED_NATIVES
    if "Gasoline" in n and n.startswith(SECTION_INTERNAL)
) | frozenset({f"{SECTION_AVIATION} | Aviation gasoline"})

DIESEL_JODI_NATIVES: frozenset[str] = frozenset(
    {
        f"{SECTION_INTERNAL} | Road diesel (c)",
        f"{SECTION_MARINE} | Diesel (f)",
        f"{SECTION_MARINE} | Coloured diesel",
    }
)

GASOIL_JODI_NATIVES: frozenset[str] = frozenset(
    n
    for n in STORED_NATIVES
    if "Coloured diesel" in n and SECTION_INTERNAL in n
) | frozenset({f"{SECTION_INTERNAL} | Coloured diesel (legacy)"})

LPG_JODI_NATIVES: frozenset[str] = frozenset(
    {
        f"{SECTION_INTERNAL} | Butane",
        f"{SECTION_INTERNAL} | Propane",
        f"{SECTION_INTERNAL} | LPG Auto",
    }
)

FUEL_OIL_JODI_NATIVES: frozenset[str] = frozenset(
    n
    for n in STORED_NATIVES
    if "fuel oil" in n.lower() or "Fuel oil" in n or "Thin fuel oil" in n or "Thick fuel oil" in n
)

DELIVERY_HEADLINE_NATIVE: frozenset[str] = STORED_NATIVES

_LEGACY_CHART_SKIP = ("legacy", "super additive", "Thin fuel oil", "Thick fuel oil")
CHART_PRODUCTS: tuple[str, ...] = tuple(
    sorted(
        n
        for n in STORED_NATIVES
        if not any(tag in n for tag in _LEGACY_CHART_SKIP)
    )
)

INTERNAL_NATIVES: frozenset[str] = frozenset(
    n for n in STORED_NATIVES if n.startswith(f"{SECTION_INTERNAL} |")
)
MARINE_NATIVES: frozenset[str] = frozenset(
    n for n in STORED_NATIVES if n.startswith(f"{SECTION_MARINE} |")
)
AVIATION_NATIVES: frozenset[str] = frozenset(
    n for n in STORED_NATIVES if n.startswith(f"{SECTION_AVIATION} |")
)

SEASONALITY_SECTION_ROLLUPS: dict[str, frozenset[str]] = {
    "Internal market": INTERNAL_NATIVES,
    "Marine bunkers": MARINE_NATIVES,
    "Aviation": AVIATION_NATIVES,
}
SEASONALITY_NATIVE_PANELS: tuple[str, ...] = tuple(SEASONALITY_SECTION_ROLLUPS.keys())

SEASONALITY_PANELS_CANONICAL: tuple[str, ...] = (
    "Diesel",
    "Fuel oil",
    "Gasoline",
    "Gasoil",
    "Jet fuel",
    "Kerosene",
    "LPG",
    "Lubricants / Grease",
    "Naphtha",
    "Bitumen",
    "Petcoke",
    "Wax",
    "Others",
)

DISPLAY_LABELS: dict[str, str] = {
    native: native.split(" | ", 1)[1] for native in sorted(STORED_NATIVES)
}

UNITS_KIND: dict[str, str] = {
    f"{SECTION_INTERNAL} | Butane": "lpg",
    f"{SECTION_INTERNAL} | Propane": "lpg",
    f"{SECTION_INTERNAL} | LPG Auto": "lpg",
    f"{SECTION_INTERNAL} | Gasoline ON98 (a)": "gasoline",
    f"{SECTION_INTERNAL} | Gasoline ON95 (b)": "gasoline",
    f"{SECTION_INTERNAL} | Gasoline super additive": "gasoline",
    f"{SECTION_INTERNAL} | Naphtha and Aromatics": "naphtha",
    f"{SECTION_INTERNAL} | Oils (kerosene + fuel)": "kerosene",
    f"{SECTION_INTERNAL} | Road diesel (c)": "diesel",
    f"{SECTION_INTERNAL} | Coloured diesel for heating purposes": "diesel",
    f"{SECTION_INTERNAL} | Coloured diesel, except for heating purposes": "diesel",
    f"{SECTION_INTERNAL} | Coloured diesel (legacy)": "diesel",
    f"{SECTION_INTERNAL} | Thin low-sulphur fuel oil (<=1%)": "fuel_oil",
    f"{SECTION_INTERNAL} | Thick low-sulphur fuel oil (<=1%)": "fuel_oil",
    f"{SECTION_INTERNAL} | Petroleum coke": "other",
    f"{SECTION_INTERNAL} | Lubricants": "lubes",
    f"{SECTION_INTERNAL} | Asphalt": "bitumen",
    f"{SECTION_INTERNAL} | Paraffins": "other",
    f"{SECTION_INTERNAL} | Solvents": "other",
    f"{SECTION_MARINE} | Diesel (f)": "diesel",
    f"{SECTION_MARINE} | Coloured diesel": "diesel",
    f"{SECTION_MARINE} | Marine fuel oil": "fuel_oil",
    f"{SECTION_MARINE} | Thin fuel oil": "fuel_oil",
    f"{SECTION_MARINE} | Thick fuel oil": "fuel_oil",
    f"{SECTION_MARINE} | Lubricants": "lubes",
    f"{SECTION_AVIATION} | Aviation gasoline": "gasoline",
    f"{SECTION_AVIATION} | Jet fuel": "jet",
}


@dataclass(frozen=True)
class JodiCompareSeries:
    key: str
    jodi_energy_product: str
    panel: str
    natives: frozenset[str]
    mode: str = "sum"


JODI_COMPARE_SERIES: dict[str, JodiCompareSeries] = {
    "gasoline": JodiCompareSeries(
        "gasoline",
        "GASOLINE",
        "Gasoline",
        GASOLINE_JODI_NATIVES,
    ),
    "diesel": JodiCompareSeries(
        "diesel",
        "GASDIES",
        "Diesel",
        DIESEL_JODI_NATIVES,
    ),
    "gasoil": JodiCompareSeries(
        "gasoil",
        "GASDIES",
        "Gasoil",
        GASOIL_JODI_NATIVES,
    ),
    "jet_fuel": JodiCompareSeries(
        "jet_fuel",
        "JETKERO",
        "Jet fuel",
        frozenset({f"{SECTION_AVIATION} | Jet fuel"}),
        mode="reporting",
    ),
    "lpg": JodiCompareSeries("lpg", "LPG", "LPG", LPG_JODI_NATIVES),
    "fuel_oil": JodiCompareSeries(
        "fuel_oil",
        "RESFUEL",
        "Fuel oil",
        FUEL_OIL_JODI_NATIVES,
    ),
}

JODI_COMPARE_PANEL_ORDER: tuple[str, ...] = (
    "Gasoline",
    "Diesel",
    "Gasoil",
    "Jet fuel",
    "LPG",
    "Fuel oil",
)


def dgeg_series_for_jodi(
    demand: pd.DataFrame,
    series_key: str,
    *,
    value_col: str = "value",
) -> pd.DataFrame:
    """Aggregate DGEG natives for one JODI compare panel."""
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
    """Sum products within each market segment for seasonality panels."""
    parts: list[pd.DataFrame] = []
    for panel, natives in SEASONALITY_SECTION_ROLLUPS.items():
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
        return df, "product_native", products, labels, "market segments"
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
    "CHART_PRODUCTS",
    "COUNTRY_CODE",
    "COUNTRY_NAME",
    "DELIVERY_HEADLINE_NATIVE",
    "DISPLAY_LABELS",
    "DGEG_AGENCY_SOURCE",
    "DGEG_DATASET_SOURCE",
    "DGEG_METRIC_TYPE",
    "DGEG_UNIT_NATIVE",
    "FUEL_OIL_JODI_NATIVES",
    "GASOLINE_JODI_NATIVES",
    "GASOIL_JODI_NATIVES",
    "DIESEL_JODI_NATIVES",
    "JODI_COMPARE_PANEL_ORDER",
    "JODI_COMPARE_SERIES",
    "JodiCompareSeries",
    "LPG_JODI_NATIVES",
    "MONTHLY_SALES_PAGE",
    "SEASONALITY_NATIVE_PANELS",
    "SEASONALITY_PANELS_CANONICAL",
    "SEASONALITY_SECTION_ROLLUPS",
    "SECTION_AVIATION",
    "SECTION_INTERNAL",
    "SECTION_MARINE",
    "SOURCE_ID",
    "STORED_NATIVES",
    "UNITS_KIND",
    "dgeg_series_for_jodi",
    "file_years",
    "finalize_dgeg_frame",
    "is_dgeg_stored",
    "parse_all_workbooks",
    "parse_dgeg_sales_workbook",
    "product_native",
    "seasonality_chart_inputs",
    "seasonality_native_rollup",
    "workbook_sort_key",
]
