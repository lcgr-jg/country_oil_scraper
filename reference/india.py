"""
India (PPAC) reference helpers — trade, production, and JODI mapping.

PPAC trade workbooks combine product imports and exports on one sheet per
fiscal year. Production workbooks split gasoline/diesel into MS-VI / MS Others
and HSD-VI / HSD Others; we roll those up to the same product keys used in
PT Consumption before comparing to JODI.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from reference.jodi_compare import JodiCompareSeries, sum_natives_series_for_jodi

# Dataset key in metric_types.yaml / product_map.csv (PPAC agency).
PPAC_DATASET_SOURCE = "ppac"
SOURCE_ID = PPAC_DATASET_SOURCE

# Dashboard native-product panel (exclude PPAC total rows duplicated in parquet).
CHART_PRODUCTS = [
    "MS",
    "HSD",
    "ATF",
    "LPG",
    "SKO",
    "Naphtha",
    "FO & LSHS",
    "Bitumen",
    "LDO",
    "Lubricants & Greases",
]

DISPLAY_LABELS: dict[str, str] = {
    "LPG": "LPG",
    "Naphtha": "Naphtha",
    "MS": "Gasoline",
    "ATF": "Jet fuel",
    "SKO": "Kerosene",
    "HSD": "Diesel",
    "LDO": "Light diesel oil",
    "Lubricants & Greases": "Lubricants",
    "FO & LSHS": "Fuel oil",
    "Bitumen": "Bitumen",
}

SEASONALITY_NATIVE_PRODUCTS: tuple[str, ...] = tuple(CHART_PRODUCTS)
SEASONALITY_PANELS_CANONICAL: tuple[str, ...] = (
    "Gasoline",
    "Diesel",
    "Jet fuel",
    "Kerosene",
    "LPG",
    "Naphtha",
    "Fuel oil",
    "Bitumen",
    "Lubes & greases",
    "Others",
)

# Fiscal month keys (header row uses full English names on trade sheets).
TRADE_MONTH_MAP: dict[str, int] = {
    "APRIL": 4,
    "MAY": 5,
    "JUNE": 6,
    "JULY": 7,
    "AUGUST": 8,
    "SEPTEMBER": 9,
    "OCTOBER": 10,
    "NOVEMBER": 11,
    "DECEMBER": 12,
    "JANUARY": 1,
    "FEBRUARY": 2,
    "MARCH": 3,
}

# Production monthwise sheets use three-letter months (same as consumption).
PROD_MONTH_MAP: dict[str, int] = {
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "JULY": 7,
    "AUG": 8,
    "SEP": 9,
    "SEPT": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
}

FISCAL_MONTH_MAP = {
    "APR": 1,
    "MAY": 2,
    "JUN": 3,
    "JUL": 4,
    "AUG": 5,
    "SEP": 6,
    "OCT": 7,
    "NOV": 8,
    "DEC": 9,
    "JAN": 10,
    "FEB": 11,
    "MAR": 12,
}

# PPAC product row -> key aligned with PT Consumption / product_map.csv
_TRADE_PRODUCT_ALIASES: dict[str, str] = {
    "LPG": "LPG",
    "MS": "MS",
    "MS!": "MS",
    "NAPHTHA": "Naphtha",
    "Naphtha": "Naphtha",
    "Naphtha$": "Naphtha",
    "ATF": "ATF",
    "ATF#": "ATF",
    "SKO": "SKO",
    "HSD": "HSD",
    "LOBS/ Lube oil": "Lubricants & Greases",
    "LOBS/ Lube Oil": "Lubricants & Greases",
    "Fuel Oil": "FO & LSHS",
    "Bitumen": "Bitumen",
    "Petcoke": "Petroleum coke",
    "Petcoke / CBFS": "Petroleum coke",
    "Others&": "Others",
    "Others%": "Others",
    "LDO": "LDO",
}

# Production native rows that sum into one consumption key.
_PRODUCTION_AGGREGATE: dict[str, list[str]] = {
    "MS": ["MS-VI", "MS Others", "MS-OTHERS", "MS OTHERS"],
    "HSD": ["HSD-VI", "HSD Others", "HSD-OTHERS", "HSD OTHERS"],
    "FO & LSHS": ["FO", "LSHS"],
    "Naphtha": ["NAPHTHA", "Naphtha"],
    "Lubricants & Greases": ["LUBES", "Lubes", "LUBES/"],
    "Petroleum coke": ["RPC/Petcoke", "RPC/PETCOKE", "Petcoke"],
    "Bitumen": ["BITUMEN", "Bitumen"],
}

PPAC_TO_JODI_CLEAN: dict[str, str] = {
    "LPG": "LPG",
    "MS": "GASOLINE",
    "HSD": "GASDIES",
    "ATF": "JETKERO",
    "Naphtha": "NAPHTHA",
    "FO & LSHS": "RESFUEL",
    "SKO": "KEROSENE_NONJET",
}

ONONSPEC_PPAC: frozenset[str] = frozenset(
    {
        "LDO",
        "Lubricants & Greases",
        "Bitumen",
        "Petroleum coke",
        "Others",
    }
)

# Official-vs-JODI panels (PPAC product_native → JODI energy_product).
JODI_COMPARE_SERIES: dict[str, JodiCompareSeries] = {
    "gasoline": JodiCompareSeries(
        "gasoline", "GASOLINE", "Gasoline", frozenset({"MS"})
    ),
    "diesel": JodiCompareSeries(
        "diesel", "GASDIES", "Diesel", frozenset({"HSD"})
    ),
    "jet_fuel": JodiCompareSeries(
        "jet_fuel", "JETKERO", "Jet fuel", frozenset({"ATF"})
    ),
    "kerosene": JodiCompareSeries(
        "kerosene", "X_OTHKERO", "Kerosene", frozenset({"SKO"})
    ),
    "lpg": JodiCompareSeries("lpg", "LPG", "LPG", frozenset({"LPG"})),
    "naphtha": JodiCompareSeries(
        "naphtha", "NAPHTHA", "Naphtha", frozenset({"Naphtha"})
    ),
    "fuel_oil": JodiCompareSeries(
        "fuel_oil", "RESFUEL", "Fuel oil", frozenset({"FO & LSHS"})
    ),
    "other": JodiCompareSeries(
        "other", "ONONSPEC", "Other products", ONONSPEC_PPAC
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
    "Other products",
)


def ppac_series_for_jodi(
    demand: pd.DataFrame,
    series_key: str,
    *,
    value_col: str = "value_kbd",
) -> pd.DataFrame:
    """Aggregate PPAC natives for one India JODI compare panel."""
    return sum_natives_series_for_jodi(
        demand,
        series_key,
        jodi_compare=JODI_COMPARE_SERIES,
        value_col=value_col,
    )


def seasonality_chart_inputs(
    demand: pd.DataFrame,
    demand_canonical: pd.DataFrame,
    *,
    view: str = "native",
    value_col: str = "value_kbd",
) -> tuple[pd.DataFrame, str, list[str], dict[str, str], str]:
    from reference.dashboard_helpers import default_seasonality_chart_inputs

    return default_seasonality_chart_inputs(
        demand,
        demand_canonical,
        view=view,
        value_col=value_col,
        native_products=SEASONALITY_NATIVE_PRODUCTS,
        display_labels=DISPLAY_LABELS,
        canonical_panels=SEASONALITY_PANELS_CANONICAL,
    )


SKIP_TRADE_SHEETS = frozenset(
    {
        "pt_import_h",
        "sheet1",
        "historical (year-wise)",
    }
)

SKIP_PROD_SHEETS = frozenset({"pt_production_h"})


def normalize_trade_product(label: str) -> str | None:
    """Map a raw trade row label to a consumption-aligned product key."""
    if not label or not str(label).strip():
        return None
    raw = str(label).strip()
    if raw in _TRADE_PRODUCT_ALIASES:
        return _TRADE_PRODUCT_ALIASES[raw]
    # Strip PPAC footnote markers (! # $ % & ^ @ *)
    cleaned = re.sub(r"[!#$%&^@*]+", "", raw).strip()
    if cleaned in _TRADE_PRODUCT_ALIASES:
        return _TRADE_PRODUCT_ALIASES[cleaned]
    upper = cleaned.upper()
    for k, v in _TRADE_PRODUCT_ALIASES.items():
        if k.upper() == upper:
            return v
    return None


def normalize_production_product(label: str) -> str | None:
    """Map production row label to consumption key (before VI/Others rollup)."""
    if not label or not str(label).strip():
        return None
    raw = str(label).strip().upper()
    direct = {
        "LPG": "LPG",
        "ATF": "ATF",
        "SKO": "SKO",
        "LDO": "LDO",
        "OTHERS": "Others",
    }
    if raw in direct:
        return direct[raw]
    if raw.startswith("MS"):
        return "MS"
    if raw.startswith("HSD"):
        return "HSD"
    if raw in ("NAPHTHA",):
        return "Naphtha"
    if raw in ("LUBES",):
        return "Lubricants & Greases"
    if raw in ("FO", "LSHS"):
        return raw  # aggregated to FO & LSHS later
    if "PETCOKE" in raw or raw.startswith("RPC"):
        return "Petroleum coke"
    if raw.startswith("BITUMEN"):
        return "Bitumen"
    return None


def _fiscal_start_year(fiscal_year: str) -> int:
    part = fiscal_year.split("-")[0].strip()
    if len(part) == 4:
        return int(part)
    if len(part) == 2:
        return 2000 + int(part)
    raise ValueError(f"Unrecognized fiscal year: {fiscal_year!r}")


def _extract_fiscal_year_from_sheet(raw: pd.DataFrame, sheet_name: str) -> str:
    for i in range(min(10, len(raw))):
        for c in range(min(6, raw.shape[1])):
            cell = str(raw.iat[i, c]).strip()
            m = re.search(r"April\s*[-–]\s*(\d{2})\b", cell, re.IGNORECASE)
            if m:
                april_year = 2000 + int(m.group(1))
                return f"{april_year}-{str(april_year + 1)[-2:]}"
            m2 = re.search(r"April\s+(\d{4})", cell, re.IGNORECASE)
            if m2:
                start = int(m2.group(1))
                return f"{start}-{str(start + 1)[-2:]}"
            m3 = re.match(r"^(\d{4})\s*[-–]\s*(\d{2})", cell)
            if m3:
                start = int(m3.group(1))
                return f"{start}-{m3.group(2)}"
            m3b = re.search(r"(\d{4})\s*[-–]\s*(\d{2})", cell)
            if m3b and re.search(r"\(P\)|monthwise|production|h-1", cell, re.I):
                start = int(m3b.group(1))
                return f"{start}-{m3b.group(2)}"
            m4 = re.match(r"^(\d{4})\s*[-–]\s*(\d{4})$", cell)
            if m4:
                start = int(m4.group(1))
                return f"{start}-{str(start + 1)[-2:]}"
    m = re.search(r"(\d{4})\s*[-–]\s*(\d{2})", sheet_name)
    if m:
        start = int(m.group(1))
        return f"{start}-{m.group(2)}"
    m2 = re.search(r"(\d{2})\s*[-–]\s*(\d{2})", sheet_name)
    if m2:
        y0 = int(m2.group(1))
        start = 2000 + y0 if y0 < 70 else 1900 + y0
        return f"{start}-{m2.group(2)}"
    raise ValueError(f"Cannot determine fiscal year from sheet '{sheet_name}'")


def _is_monthly_trade_sheet(sheet_name: str, raw: pd.DataFrame) -> bool:
    if sheet_name.lower() in SKIP_TRADE_SHEETS:
        return False
    if re.search(r"pt_import_h", sheet_name, re.I) and "period" in str(
        raw.iloc[4, 0] if raw.shape[0] > 4 else ""
    ).lower():
        return False
    for i in range(min(12, len(raw))):
        row = " ".join(str(raw.iat[i, c]).upper() for c in range(min(14, raw.shape[1])) if pd.notna(raw.iat[i, c]))
        if "APRIL" in row and "MAY" in row:
            return True
    return False


def _parse_trade_sheet(
    raw: pd.DataFrame, sheet_name: str, source_file: str
) -> pd.DataFrame:
    """Parse one monthly trade sheet (imports + exports blocks)."""
    fiscal_year = _extract_fiscal_year_from_sheet(raw, sheet_name)
    fiscal_start = _fiscal_start_year(fiscal_year)

    header_row = None
    for i in range(min(15, len(raw))):
        row = " ".join(
            str(raw.iat[i, c]).upper() for c in range(raw.shape[1]) if pd.notna(raw.iat[i, c])
        )
        if "APRIL" in row and "MAY" in row:
            header_row = i
            break
    if header_row is None:
        raise ValueError(f"No monthly header in trade sheet '{sheet_name}'")

    month_cols = []
    for c in range(1, raw.shape[1]):
        col = str(raw.iat[header_row, c]).strip().upper()
        if col in TRADE_MONTH_MAP:
            month_cols.append((c, col))

    import_start: int | None = None
    import_end: int | None = None
    export_start: int | None = None
    for i in range(header_row + 1, len(raw)):
        label = str(raw.iat[i, 0]).strip().upper() if pd.notna(raw.iat[i, 0]) else ""
        if label == "PRODUCTS" and import_start is None:
            import_start = i + 1
        elif "PRODUCT IMPORT" in label and "TOTAL" not in label:
            import_end = i
        elif (
            export_start is None
            and "TOTAL" not in label
            and label.startswith("PRODUCT EXPORT")
        ):
            export_start = i + 1

    if import_start is None or export_start is None:
        raise ValueError(f"Cannot find import/export blocks in '{sheet_name}'")

    if import_end is None:
        import_end = export_start - 1

    frames: list[pd.DataFrame] = []

    def _block_to_long(start: int, end: int, trade_flow: str) -> None:
        for i in range(start, end):
            label = raw.iat[i, 0]
            product = normalize_trade_product(str(label) if pd.notna(label) else "")
            if product is None:
                continue
            for col_idx, month_name in month_cols:
                val = raw.iat[i, col_idx]
                if pd.isna(val):
                    continue
                try:
                    v = float(val)
                except (TypeError, ValueError):
                    continue
                cal_m = TRADE_MONTH_MAP[month_name]
                cal_y = fiscal_start if cal_m >= 4 else fiscal_start + 1
                frames.append(
                    {
                        "fiscal_year": fiscal_year,
                        "month_name": month_name[:3],
                        "calendar_year": cal_y,
                        "calendar_month": cal_m,
                        "date": date(cal_y, cal_m, 1),
                        "product": product,
                        "trade_flow": trade_flow,
                        "metric_type": "TOTIMPSB" if trade_flow == "imports" else "TOTEXPSB",
                        "value_000mt": v,
                        "is_total_row": False,
                        "source_file": source_file,
                        "sheet_name": sheet_name,
                    }
                )

    _block_to_long(import_start, export_start - 1, "imports")
    export_end = len(raw)
    for i in range(export_start, len(raw)):
        label = str(raw.iat[i, 0]).upper() if pd.notna(raw.iat[i, 0]) else ""
        if "TOTAL" in label and "EXPORT" in label:
            export_end = i
            break
    _block_to_long(export_start, export_end, "exports")

    if not frames:
        raise ValueError(f"No product rows parsed in '{sheet_name}'")
    return pd.DataFrame(frames)


def parse_pt_trade_workbook(path: Path) -> pd.DataFrame:
    """Parse a PPAC combined import/export workbook to long tidy rows."""
    suffix = path.suffix.lower()
    engine = "xlrd" if suffix == ".xls" else "openpyxl"
    xls = pd.ExcelFile(path, engine=engine)
    frames: list[pd.DataFrame] = []
    for sheet_name in xls.sheet_names:
        if sheet_name.lower() in SKIP_TRADE_SHEETS:
            continue
        raw = pd.read_excel(xls, sheet_name=sheet_name, header=None, engine=engine)
        if not _is_monthly_trade_sheet(sheet_name, raw):
            continue
        try:
            frames.append(_parse_trade_sheet(raw, sheet_name, path.name))
        except (ValueError, KeyError) as exc:
            import logging

            logging.getLogger(__name__).warning(
                "Skipping trade sheet %s in %s: %s", sheet_name, path.name, exc
            )
    if not frames:
        raise RuntimeError(f"No monthly trade sheets parsed in {path}")
    out = pd.concat(frames, ignore_index=True)
    out["updated_at"] = datetime.now()
    return out


def _is_monthwise_production_sheet(sheet_name: str, raw: pd.DataFrame) -> bool:
    if sheet_name.lower() in SKIP_PROD_SHEETS:
        return False
    if "monthwise" not in sheet_name.lower():
        return False
    for i in range(min(12, len(raw))):
        row = " ".join(str(raw.iat[i, c]).upper() for c in range(min(8, raw.shape[1])) if pd.notna(raw.iat[i, c]))
        if "PRODUCTS" in row and ("APR" in row or "APRIL" in row):
            return True
    return False


def _parse_production_sheet(
    raw: pd.DataFrame, sheet_name: str, source_file: str
) -> pd.DataFrame:
    fiscal_year = _extract_fiscal_year_from_sheet(raw, sheet_name)
    fiscal_start = _fiscal_start_year(fiscal_year)

    header_row = None
    for i in range(min(15, len(raw))):
        row_vals = [
            str(raw.iat[i, c]).strip().upper()
            for c in range(min(14, raw.shape[1]))
            if pd.notna(raw.iat[i, c])
        ]
        if "PRODUCTS" in row_vals and any(m in row_vals for m in PROD_MONTH_MAP):
            header_row = i
            break
    if header_row is None:
        raise ValueError(f"No header in production sheet '{sheet_name}'")

    month_cols: list[tuple[int, str]] = []
    for c in range(1, raw.shape[1]):
        col = str(raw.iat[header_row, c]).strip().upper()
        key = col[:3] if col.startswith("SEPT") else col
        if key in PROD_MONTH_MAP or col in PROD_MONTH_MAP:
            month_cols.append((c, col))

    data_start = header_row + 1
    data_end = len(raw)
    for i in range(data_start, len(raw)):
        label = str(raw.iat[i, 0]).strip().upper() if pd.notna(raw.iat[i, 0]) else ""
        if label.startswith("TOTAL") or label == "OF WHICH":
            data_end = i
            break

    # Collect native rows then aggregate MS/HSD/FO+LSHS
    native_rows: list[dict] = []
    for i in range(data_start, data_end):
        label = raw.iat[i, 0]
        native = str(label).strip() if pd.notna(label) else ""
        prod_key = normalize_production_product(native)
        if prod_key is None:
            continue
        for col_idx, month_name in month_cols:
            val = raw.iat[i, col_idx]
            if pd.isna(val):
                continue
            try:
                v = float(val)
            except (TypeError, ValueError):
                continue
            mkey = month_name.upper()
            if mkey.startswith("SEPT"):
                mkey = "SEP"
            cal_m = PROD_MONTH_MAP.get(mkey, PROD_MONTH_MAP.get(mkey[:3]))
            if cal_m is None:
                continue
            cal_y = fiscal_start if cal_m >= 4 else fiscal_start + 1
            native_rows.append(
                {
                    "native_product": native,
                    "product": prod_key,
                    "month_name": mkey[:3],
                    "calendar_year": cal_y,
                    "calendar_month": cal_m,
                    "date": date(cal_y, cal_m, 1),
                    "value_000mt": v,
                }
            )

    if not native_rows:
        raise ValueError(f"No production rows in '{sheet_name}'")

    ndf = pd.DataFrame(native_rows)
    # Roll FO + LSHS -> FO & LSHS
    ndf.loc[ndf["product"].isin(["FO", "LSHS"]), "product"] = "FO & LSHS"
    # Sum duplicates (MS-VI + MS Others already map to MS)
    agg = (
        ndf.groupby(
            ["date", "product", "month_name", "calendar_year", "calendar_month"],
            as_index=False,
        )["value_000mt"]
        .sum()
    )
    agg["fiscal_year"] = fiscal_year
    agg["metric_type"] = "REFGROUT"
    agg["is_total_row"] = False
    agg["source_file"] = source_file
    agg["sheet_name"] = sheet_name
    agg["updated_at"] = datetime.now()
    return agg


def parse_pt_production_workbook(path: Path) -> pd.DataFrame:
    """Parse PPAC production historical workbook (monthwise sheets)."""
    suffix = path.suffix.lower()
    engine = "xlrd" if suffix == ".xls" else "openpyxl"
    xls = pd.ExcelFile(path, engine=engine)
    frames: list[pd.DataFrame] = []
    for sheet_name in xls.sheet_names:
        if not _is_monthwise_production_sheet(sheet_name, pd.read_excel(xls, sheet_name=sheet_name, header=None, nrows=12, engine=engine)):
            continue
        raw = pd.read_excel(xls, sheet_name=sheet_name, header=None, engine=engine)
        try:
            frames.append(_parse_production_sheet(raw, sheet_name, path.name))
        except (ValueError, KeyError) as exc:
            import logging

            logging.getLogger(__name__).warning(
                "Skipping production sheet %s in %s: %s", sheet_name, path.name, exc
            )
    if not frames:
        raise RuntimeError(f"No monthwise production sheets in {path}")
    return pd.concat(frames, ignore_index=True)


def upsert_monthly(
    existing: pd.DataFrame | None,
    new: pd.DataFrame,
    key_cols: list[str],
) -> pd.DataFrame:
    """Replace rows matching key_cols in existing with new observations."""
    if existing is None or existing.empty:
        return new.sort_values(key_cols).reset_index(drop=True)
    new_keys = set(map(tuple, new[key_cols].to_numpy()))
    mask = ~existing.apply(lambda r: tuple(r[c] for c in key_cols) in new_keys, axis=1)
    return pd.concat([existing.loc[mask], new], ignore_index=True).sort_values(key_cols)


def load_ppac_trade_from_dirs(
    trade_dir: Path,
    *,
    hist_glob: str = "*IMPORT*TMT*H*.xlsx",
    curr_glob: str = "*import*.xls",
) -> pd.DataFrame:
    """Load historical + current trade workbooks from data/raw/india/trade/."""
    hist_files = sorted(trade_dir.glob(hist_glob))
    curr_files = sorted(trade_dir.glob(curr_glob))
    if not hist_files and not curr_files:
        raise FileNotFoundError(f"No trade files under {trade_dir}")

    df: pd.DataFrame | None = None
    for p in hist_files:
        part = parse_pt_trade_workbook(p)
        df = part if df is None else upsert_monthly(
            df, part, ["date", "product", "trade_flow"]
        )
    for p in curr_files:
        part = parse_pt_trade_workbook(p)
        df = upsert_monthly(df, part, ["date", "product", "trade_flow"])
    return df  # type: ignore[return-value]


def load_ppac_production_from_dir(
    prod_dir: Path,
    *,
    glob: str = "*production*product*H*.xls",
) -> pd.DataFrame:
    files = sorted(prod_dir.glob(glob))
    if not files:
        raise FileNotFoundError(f"No production files under {prod_dir}")
    df: pd.DataFrame | None = None
    for p in files:
        part = parse_pt_production_workbook(p)
        df = part if df is None else upsert_monthly(df, part, ["date", "product"])
    return df  # type: ignore[return-value]


def attach_jodi_product(ppac: pd.DataFrame) -> pd.DataFrame:
    """Add jodi_product column; bucket unmapped small products into ONONSPEC_BASKET."""
    out = ppac.copy()
    out["jodi_product"] = out["product"].map(PPAC_TO_JODI_CLEAN)
    out.loc[out["product"].isin(ONONSPEC_PPAC), "jodi_product"] = "ONONSPEC_BASKET"
    return out


def rollup_to_jodi_products(df: pd.DataFrame, value_col: str = "value_000mt") -> pd.DataFrame:
    """Sum PPAC rows to JODI product codes (incl. ONONSPEC basket)."""
    tmp = attach_jodi_product(df)
    tmp = tmp[~tmp["is_total_row"].fillna(False)]
    tmp = tmp[tmp["jodi_product"].notna()]
    keys = ["date", "jodi_product"]
    if "metric_type" in tmp.columns:
        keys.append("metric_type")
    if "trade_flow" in tmp.columns:
        keys.append("trade_flow")
    return tmp.groupby(keys, as_index=False)[value_col].sum()


def _parse_trade_table_rows(
    table: list[list],
    *,
    month_col: str,
    source_file: str,
    fiscal_year: str,
) -> pd.DataFrame:
    """Parse a pdfplumber/extracted trade table for one month column."""
    if not table:
        raise ValueError("Empty trade table")

    header_row = None
    import_start: int | None = None
    import_end: int | None = None
    export_start: int | None = None
    month_idx = None
    for i, row in enumerate(table):
        if not row or not row[0]:
            continue
        cells = [str(c or "").strip() for c in row]
        label = cells[0].upper()
        if label == "IMPORT/EXPORT" and month_idx is None:
            header_row = i
            for j, c in enumerate(cells[1:], start=1):
                if c.upper() == month_col.upper():
                    month_idx = j
                    break
        elif label == "PRODUCTS" and import_start is None and header_row is not None:
            import_start = i + 1
        elif "PRODUCT IMPORT" in label and "TOTAL" not in label:
            import_end = i
        elif export_start is None and label.startswith("PRODUCT EXPORT"):
            export_start = i + 1

    if month_idx is None or import_start is None or export_start is None:
        raise ValueError(f"Could not locate {month_col} column or trade blocks")

    if import_end is None:
        import_end = export_start - 1
    fiscal_start = _fiscal_start_year(fiscal_year)
    cal_m = TRADE_MONTH_MAP[month_col.upper()]
    cal_y = fiscal_start if cal_m >= 4 else fiscal_start + 1
    target_date = date(cal_y, cal_m, 1)

    frames: list[dict] = []

    def _block(start: int, end: int, trade_flow: str) -> None:
        for i in range(start, end):
            row = table[i]
            if not row:
                continue
            product = normalize_trade_product(str(row[0] or ""))
            if product is None:
                continue
            val = row[month_idx] if month_idx < len(row) else None
            if val is None or str(val).strip() == "":
                continue
            try:
                v = float(str(val).replace(",", ""))
            except ValueError:
                continue
            frames.append(
                {
                    "fiscal_year": fiscal_year,
                    "month_name": month_col[:3],
                    "calendar_year": cal_y,
                    "calendar_month": cal_m,
                    "date": target_date,
                    "product": product,
                    "trade_flow": trade_flow,
                    "metric_type": "TOTIMPSB" if trade_flow == "imports" else "TOTEXPSB",
                    "value_000mt": v,
                    "is_total_row": False,
                    "source_file": source_file,
                    "sheet_name": "pdf",
                }
            )

    _block(import_start, export_start - 1, "imports")
    export_end = len(table)
    for i in range(export_start, len(table)):
        row = table[i]
        if not row or not row[0]:
            continue
        label = str(row[0]).upper()
        if "TOTAL" in label and "EXPORT" in label:
            export_end = i
            break
    _block(export_start, export_end, "exports")

    if not frames:
        raise ValueError("No trade rows parsed from table")
    out = pd.DataFrame(frames)
    out["updated_at"] = datetime.now()
    return out


def parse_pt_trade_pdf(
    path: Path,
    *,
    month_col: str = "APRIL",
    fiscal_year: str = "2026-27",
) -> pd.DataFrame:
    """Parse PPAC flash trade PDF (single-month columns, e.g. April 2026)."""
    try:
        import pdfplumber
    except ImportError as exc:
        raise ImportError("pip install pdfplumber to parse PPAC trade PDFs") from exc

    with pdfplumber.open(path) as doc:
        table = doc.pages[0].extract_table()
    return _parse_trade_table_rows(
        table or [],
        month_col=month_col,
        source_file=path.name,
        fiscal_year=fiscal_year,
    )


def parse_pt_production_pdf(
    path: Path,
    *,
    month_col: str = "APR",
    fiscal_year: str = "2026-27",
) -> pd.DataFrame:
    """Parse PPAC flash production PDF (e.g. April 2026 provisional)."""
    try:
        import pdfplumber
    except ImportError as exc:
        raise ImportError("pip install pdfplumber to parse PPAC production PDFs") from exc

    with pdfplumber.open(path) as doc:
        table = doc.pages[0].extract_table()
    if not table:
        raise ValueError("Empty production table")

    header_row = None
    month_idx = None
    for i, row in enumerate(table):
        if not row or not row[0]:
            continue
        cells = [str(c or "").strip() for c in row]
        if cells[0].upper() == "PRODUCTS":
            header_row = i
            for j, c in enumerate(cells[1:], start=1):
                key = c.upper()
                if key == month_col.upper() or key.startswith(month_col.upper()):
                    month_idx = j
                    break

    if header_row is None or month_idx is None:
        raise ValueError(f"Could not find PRODUCTS / {month_col} in production PDF")

    fiscal_start = _fiscal_start_year(fiscal_year)
    key = month_col.upper()
    cal_m = PROD_MONTH_MAP.get(key, PROD_MONTH_MAP.get(key[:3], TRADE_MONTH_MAP.get(key)))
    if cal_m is None:
        raise ValueError(f"Unknown month column {month_col}")
    cal_y = fiscal_start if cal_m >= 4 else fiscal_start + 1
    target_date = date(cal_y, cal_m, 1)

    native_rows: list[dict] = []
    for row in table[header_row + 1 :]:
        if not row or not row[0]:
            continue
        native = str(row[0]).strip()
        if native.upper().startswith("TOTAL") or native.upper() == "OF WHICH":
            break
        prod_key = normalize_production_product(native)
        if prod_key is None:
            continue
        val = row[month_idx] if month_idx < len(row) else None
        if val is None or str(val).strip() == "":
            continue
        try:
            v = float(str(val).replace(",", ""))
        except ValueError:
            continue
        native_rows.append(
            {
                "native_product": native,
                "product": prod_key,
                "value_000mt": v,
            }
        )

    if not native_rows:
        raise ValueError("No production rows in PDF")

    ndf = pd.DataFrame(native_rows)
    ndf.loc[ndf["product"].isin(["FO", "LSHS"]), "product"] = "FO & LSHS"
    agg = ndf.groupby("product", as_index=False)["value_000mt"].sum()
    agg["date"] = target_date
    agg["fiscal_year"] = fiscal_year
    agg["metric_type"] = "REFGROUT"
    agg["is_total_row"] = False
    agg["source_file"] = path.name
    agg["updated_at"] = datetime.now()
    return agg
