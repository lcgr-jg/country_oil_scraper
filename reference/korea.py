"""
reference.korea
───────────────
KNOC/MOTIE 제품별소비 (product-by-product consumption) helpers.

Raw CSVs use Korean headers (pre-2019) or English headers (2019+). The parser
normalizes every product column to snake_case ``product_native`` keys that match
``product_map.csv`` (Source = KNOC).

Native unit: **kbpm** (thousand barrels per calendar month). Convert to kbd via
``analytics.units.convert_series(..., "kbpm", "kbd", date=...)``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal, Optional

import pandas as pd

from reference.loaders import is_primary, load_product_map

KNOC_AGENCY_SOURCE = "KNOC"
KNOC_DATASET_SOURCE = "korea_petroleum_consumption"
KNOC_METRIC_TYPE = "TOTDEMO"
KNOC_UNIT_NATIVE = "kbpm"

KNOC_STOCKS_SOURCE = "korea_petroleum_stocks"
KNOC_STOCKS_METRIC_TYPE = "CLOSTLV"
KNOC_STOCKS_UNIT_NATIVE = "kb"

KoreaDatasetName = Literal["consumption", "stocks"]


@dataclass(frozen=True)
class KoreaDataset:
    """Petronet wide-CSV bundle family (consumption or closing stocks)."""

    name: KoreaDatasetName
    bundle_prefix: str  # filename stem before (YYYYMM-YYYYMM).csv
    metric_type: str
    unit_native: str
    source_id: str
    raw_subdir: str  # "" for consumption; "stocks" under data/raw/korea/
    bootstrap_start: date


CONSUMPTION_DATASET = KoreaDataset(
    name="consumption",
    bundle_prefix="제품별소비",
    metric_type=KNOC_METRIC_TYPE,
    unit_native=KNOC_UNIT_NATIVE,
    source_id=KNOC_DATASET_SOURCE,
    raw_subdir="",
    bootstrap_start=date(1997, 1, 1),
)

STOCKS_DATASET = KoreaDataset(
    name="stocks",
    bundle_prefix="석유제품재고",
    metric_type=KNOC_STOCKS_METRIC_TYPE,
    unit_native=KNOC_STOCKS_UNIT_NATIVE,
    source_id=KNOC_STOCKS_SOURCE,
    raw_subdir="stocks",
    bootstrap_start=date(1991, 1, 1),
)

KOREA_DATASETS: tuple[KoreaDataset, ...] = (CONSUMPTION_DATASET, STOCKS_DATASET)

COUNTRY_CODE = "KR"
COUNTRY_NAME = "Korea (the Republic of)"
SOURCE_ID = KNOC_DATASET_SOURCE

# Raw header (Korean or English) -> normalized product_native (product_map key).
RAW_COLUMN_TO_NATIVE: dict[str, str] = {
    # Korean
    "휘발유": "gasoline",
    "등유": "kerosene",
    "경유": "diesel",
    "경질중유": "light_heavy_oil",
    "중유": "heavy_oil",
    "벙커C유": "bunker_c",
    "납사": "naphtha",
    "용제": "solvent",
    "항공유": "jet_fuel",
    "LPG": "lpg",
    "아스팔트": "asphalt",
    "윤활유": "lubricant",
    "기타제품": "other_products",
    "부생연료유": "byproduct_fuel_oil",
    "바이오연료": "biofuel",
    "합 계": "total",
    "합계": "total",
    # English (2019+)
    "gasoline": "gasoline",
    "kerosene": "kerosene",
    "Via": "diesel",
    "Hard Heavy Oil": "light_heavy_oil",
    "Heavy oil": "heavy_oil",
    "Bunker C Oil": "bunker_c",
    "naphtha": "naphtha",
    "solvent": "solvent",
    "jet fuel": "jet_fuel",
    "asphalt": "asphalt",
    "lubricant": "lubricant",
    "Other Products": "other_products",
    "by-product fuel oil": "byproduct_fuel_oil",
    "biofuel": "biofuel",
    "Total": "total",
}

# Month column labels to ignore when melting.
_MONTH_HEADERS = frozenset(
    {"월", "Month", "month", "제품명", "Product Name", "product name"}
)

FUEL_OIL_NATIVE: frozenset[str] = frozenset(
    {
        "light_heavy_oil",
        "heavy_oil",
        "bunker_c",
        "byproduct_fuel_oil",
    }
)

# End-use headline rows (exclude naphtha and file total).
DELIVERY_HEADLINE_NATIVE: frozenset[str] = frozenset(
    {
        "gasoline",
        "kerosene",
        "diesel",
        "jet_fuel",
        "lpg",
        *FUEL_OIL_NATIVE,
    }
)

CHART_PRODUCTS: tuple[str, ...] = tuple(DELIVERY_HEADLINE_NATIVE)

# Seasonality includes naphtha (petchem); headline totals still exclude it.
SEASONALITY_NATIVE_PRODUCTS: tuple[str, ...] = CHART_PRODUCTS + ("naphtha",)

# One panel per canonical product (fuel-oil components rolled up).
SEASONALITY_PANELS_CANONICAL: tuple[str, ...] = (
    "Diesel",
    "Fuel oil",
    "Gasoline",
    "Jet fuel",
    "Kerosene",
    "LPG",
    "Naphtha",
)

DISPLAY_LABELS: dict[str, str] = {
    "gasoline": "Gasoline",
    "kerosene": "Kerosene",
    "diesel": "Diesel",
    "jet_fuel": "Jet fuel",
    "lpg": "LPG",
    "light_heavy_oil": "Fuel oil — light/heavy",
    "heavy_oil": "Fuel oil — heavy",
    "bunker_c": "Fuel oil — bunker C",
    "byproduct_fuel_oil": "Fuel oil — by-product",
    "naphtha": "Naphtha (petchem)",
}

UNITS_KIND: dict[str, str] = {
    "gasoline": "gasoline",
    "kerosene": "kerosene",
    "diesel": "diesel",
    "jet_fuel": "jet",
    "lpg": "lpg",
    "naphtha": "naphtha",
    "light_heavy_oil": "fuel_oil",
    "heavy_oil": "fuel_oil",
    "bunker_c": "fuel_oil",
    "byproduct_fuel_oil": "fuel_oil",
    "asphalt": "bitumen",
    "lubricant": "lubes",
    "solvent": "other",
    "other_products": "other",
    "biofuel": "other",
}


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
    "kerosene": JodiCompareSeries(
        "kerosene", "X_OTHKERO", "Kerosene", frozenset({"kerosene"})
    ),
    "lpg": JodiCompareSeries("lpg", "LPG", "LPG", frozenset({"lpg"})),
    "naphtha": JodiCompareSeries(
        "naphtha", "NAPHTHA", "Naphtha", frozenset({"naphtha"})
    ),
    "fuel_oil": JodiCompareSeries(
        "fuel_oil",
        "RESFUEL",
        "Fuel oil",
        FUEL_OIL_NATIVE,
    ),
}


def normalize_raw_column(label: object) -> Optional[str]:
    """Map a raw CSV column header to ``product_native``, or None if not a product."""
    if label is None or (isinstance(label, float) and pd.isna(label)):
        return None
    text = str(label).strip()
    if not text or text in _MONTH_HEADERS:
        return None
    return RAW_COLUMN_TO_NATIVE.get(text) or RAW_COLUMN_TO_NATIVE.get(
        text.replace("  ", " ")
    )


def is_knoc_primary(product_native: str) -> bool:
    """True if this normalized product should be stored (not [AGG] total)."""
    if product_native == "total":
        return False
    try:
        return is_primary(product_native, KNOC_AGENCY_SOURCE)
    except KeyError:
        return False


def _korea_product_names() -> frozenset[str]:
    pm = load_product_map()
    mask = pm["Source"] == KNOC_AGENCY_SOURCE
    return frozenset(pm.loc[mask, "Product_name"].astype(str).tolist())


def _parse_two_digit_year(yy: int) -> int:
    """97 -> 1997, 14 -> 2014, 22 -> 2022."""
    return 1900 + yy if yy >= 90 else 2000 + yy


_EN_MONTH_YEAR = re.compile(
    r"^(January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+(\d{4})$",
    re.I,
)
_EN_MONTH_ONLY = re.compile(
    r"^(January|February|March|April|May|June|July|August|September|"
    r"October|November|December)$",
    re.I,
)
_KO_MONTH = re.compile(r"^(\d{2})년\s*(\d{2})월")
_KO_MONTH_ONLY = re.compile(r"^(\d{2})월$")


def _parse_month_cell(
    text: str,
    *,
    carry_year: Optional[int],
) -> tuple[Optional[pd.Timestamp], Optional[int]]:
    """Return (month-start timestamp, year to carry forward)."""
    text = str(text).strip()
    if not text or text.lower() == "nan":
        return None, carry_year

    m = _EN_MONTH_YEAR.match(text)
    if m:
        year = int(m.group(2))
        month = pd.Timestamp(year=year, month=_month_num(m.group(1)), day=1)
        return month, year

    m = _EN_MONTH_ONLY.match(text)
    if m and carry_year is not None:
        month = pd.Timestamp(
            year=carry_year, month=_month_num(m.group(1)), day=1
        )
        return month, carry_year

    m = _KO_MONTH.search(text.replace("\xa0", " "))
    if m:
        year = _parse_two_digit_year(int(m.group(1)))
        month_n = int(m.group(2))
        return pd.Timestamp(year=year, month=month_n, day=1), year

    m = _KO_MONTH_ONLY.match(text.replace("\xa0", " ").strip())
    if m and carry_year is not None:
        month_n = int(m.group(1))
        return pd.Timestamp(year=carry_year, month=month_n, day=1), carry_year

    return None, carry_year


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


def _is_share_row(row: pd.Series, value_cols: list[str]) -> bool:
    """True for percentage share rows (values like '[8.35]')."""
    for col in value_cols:
        val = row[col]
        if pd.isna(val):
            continue
        s = str(val).strip()
        if s.startswith("[") or s.startswith("("):
            return True
    return False


def _read_korea_csv(path: Path) -> pd.DataFrame:
    for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
        try:
            return pd.read_csv(path, encoding=enc)
        except UnicodeDecodeError:
            continue
    return pd.read_csv(path, encoding="utf-8", errors="replace")


def parse_korea_wide_csv(path: Path) -> pd.DataFrame:
    """
    Parse one Petronet wide CSV (consumption or stocks) into long-form rows.

    Columns: date, product_native, value, source_file
    """
    path = Path(path)
    raw = _read_korea_csv(path)
    raw.columns = [str(c).strip() for c in raw.columns]

    month_col = raw.columns[0]
    value_cols: list[str] = []
    col_to_native: dict[str, str] = {}
    for col in raw.columns[1:]:
        native = normalize_raw_column(col)
        if native is not None:
            value_cols.append(col)
            col_to_native[col] = native

    if not value_cols:
        raise ValueError(f"No product columns found in {path.name}")

    rows: list[dict] = []
    carry_year: Optional[int] = None

    for _, row in raw.iterrows():
        if _is_share_row(row, value_cols):
            continue

        month_text = row[month_col]
        if pd.isna(month_text) or str(month_text).strip() == "":
            continue

        date, carry_year = _parse_month_cell(str(month_text), carry_year=carry_year)
        if date is None:
            continue

        for col in value_cols:
            native = col_to_native[col]
            if not is_knoc_primary(native):
                continue
            val = row[col]
            if pd.isna(val):
                continue
            s = str(val).strip().replace(",", "")
            if not s or s.startswith("[") or s == "-":
                continue
            try:
                value = float(s)
            except ValueError:
                continue
            rows.append(
                {
                    "date": date,
                    "product_native": native,
                    "value": value,
                    "source_file": path.name,
                }
            )

    if not rows:
        return pd.DataFrame(columns=["date", "product_native", "value", "source_file"])

    df = pd.DataFrame(rows)
    return df.sort_values(["date", "product_native"], ignore_index=True)


def _filename_range_re(dataset: KoreaDataset) -> re.Pattern[str]:
    prefix = re.escape(dataset.bundle_prefix)
    return re.compile(rf"{prefix}\((\d{{6}})-(\d{{6}})\)\.csv$", re.UNICODE)


def dataset_for_path(path: Path) -> Optional[KoreaDataset]:
    """Return the KNOC dataset matching a bundle filename, if any."""
    for ds in KOREA_DATASETS:
        if _filename_range_re(ds).search(Path(path).name):
            return ds
    return None


def parse_bundle_filename(
    path: Path,
    *,
    dataset: Optional[KoreaDataset] = None,
) -> Optional[tuple[pd.Timestamp, pd.Timestamp]]:
    """Return (start, end) month-stamps from a KNOC bundle filename."""
    path = Path(path)
    candidates = (dataset,) if dataset is not None else KOREA_DATASETS
    for ds in candidates:
        if ds is None:
            continue
        m = _filename_range_re(ds).search(path.name)
        if m:
            start = pd.Timestamp(f"{m.group(1)[:4]}-{m.group(1)[4:6]}-01")
            end = pd.Timestamp(f"{m.group(2)[:4]}-{m.group(2)[4:6]}-01")
            return start, end
    return None


def months_present_in_csv(path: Path) -> pd.DatetimeIndex:
    """Distinct month-start dates parsed from one raw CSV."""
    df = parse_korea_wide_csv(path)
    if df.empty:
        return pd.DatetimeIndex([])
    return pd.DatetimeIndex(df["date"].drop_duplicates().sort_values())


def audit_raw_csv(path: Path) -> dict:
    """
    Compare filename date range vs rows actually parsed.

    Returns keys: path, expected_start, expected_end, actual_start, actual_end,
    month_count, expected_month_count, missing_months, truncated.
    """
    span = parse_bundle_filename(path)
    months = months_present_in_csv(path)
    out: dict = {"path": path.name, "truncated": False}
    if span is not None:
        expected_start, expected_end = span
        out["expected_start"] = expected_start
        out["expected_end"] = expected_end
        expected_idx = pd.period_range(
            expected_start.to_period("M"),
            expected_end.to_period("M"),
            freq="M",
        )
        out["expected_month_count"] = len(expected_idx)
        if len(months):
            have = {pd.Timestamp(m).to_period("M") for m in months}
            missing = [p for p in expected_idx if p not in have]
            out["missing_months"] = [str(p) for p in missing]
            out["truncated"] = len(missing) > 0
    if len(months):
        out["actual_start"] = months.min()
        out["actual_end"] = months.max()
        out["month_count"] = len(months)
    else:
        out["month_count"] = 0
    return out


def find_stitched_gaps(
    df: pd.DataFrame,
    *,
    start: str = "1997-01",
    end: Optional[str] = None,
    metric_type: Optional[str] = None,
) -> list[str]:
    """Return YYYY-MM strings missing from a stitched long-form frame."""
    if df.empty:
        return []
    sl = df
    if metric_type is not None and "metric_type" in df.columns:
        sl = df[df["metric_type"] == metric_type]
        if sl.empty:
            return []
    dates = pd.to_datetime(sl["date"])
    have = {d.to_period("M") for d in dates.drop_duplicates()}
    end_ts = pd.Timestamp(end or dates.max())
    start_ts = pd.Timestamp(start)
    full = pd.period_range(
        start_ts.to_period("M"), end_ts.to_period("M"), freq="M"
    )
    return [str(p) for p in full if p not in have]


def raw_dir_for_dataset(data_dir: Path, dataset: KoreaDataset) -> Path:
    """``data/raw/korea/`` or ``data/raw/korea/stocks/``."""
    base = Path(data_dir) / "raw" / "korea"
    return base / dataset.raw_subdir if dataset.raw_subdir else base


def _bundle_csv_paths(raw_dir: Path, dataset: KoreaDataset) -> list[Path]:
    """KNOC bundle files for one dataset (excludes ad-hoc test CSVs)."""
    return sorted(raw_dir.glob(f"{dataset.bundle_prefix}(*).csv"))


def _stitch_parsed_frames(frames: list[pd.DataFrame]) -> pd.DataFrame:
    if not frames:
        return pd.DataFrame(columns=["date", "product_native", "value", "source_file"])
    combined = pd.concat(frames, ignore_index=True)
    return (
        combined.sort_values(["date", "product_native", "source_file"])
        .drop_duplicates(subset=["date", "product_native"], keep="last")
        .sort_values(["date", "product_native"], ignore_index=True)
    )


def parse_korea_csv_files(
    paths: list[Path],
    *,
    dataset: Optional[KoreaDataset] = None,
) -> pd.DataFrame:
    """Parse one or more bundle CSVs (for incremental updates)."""
    paths = sorted({Path(p) for p in paths})
    if not paths:
        return pd.DataFrame(columns=["date", "product_native", "value", "source_file"])
    if dataset is not None:
        for path in paths:
            got = dataset_for_path(path)
            if got is not None and got.name != dataset.name:
                raise ValueError(
                    f"{path.name} is {got.name}, expected {dataset.name} bundles"
                )
    frames = [parse_korea_wide_csv(p) for p in paths]
    return _stitch_parsed_frames(frames)


def parse_korea_directory(raw_dir: Path, *, dataset: KoreaDataset) -> pd.DataFrame:
    """Parse and stitch all bundle CSV files under ``raw_dir`` (sorted by name)."""
    raw_dir = Path(raw_dir)
    paths = _bundle_csv_paths(raw_dir, dataset)
    if not paths:
        raise FileNotFoundError(
            f"No {dataset.bundle_prefix}(*).csv files in {raw_dir}"
        )
    return parse_korea_csv_files(paths, dataset=dataset)


def parse_korea_consumption_csv(path: Path) -> pd.DataFrame:
    """Alias for :func:`parse_korea_wide_csv` (consumption bundles)."""
    return parse_korea_wide_csv(path)


def sum_fuel_oil_by_date(
    df: pd.DataFrame,
    *,
    value_col: str = "value",
) -> pd.DataFrame:
    """Sum fuel-oil component natives by date (for JODI RESFUEL compare)."""
    sl = df[df["product_native"].isin(FUEL_OIL_NATIVE)]
    if sl.empty:
        return pd.DataFrame(columns=["date", value_col, "is_provisional"])
    out = (
        sl.groupby(["date", "is_provisional"], as_index=False)[value_col]
        .sum()
        .assign(product_native="fuel_oil_composite")
    )
    return out


def seasonality_chart_inputs(
    view: str,
    *,
    demand: pd.DataFrame,
    demand_canonical: pd.DataFrame,
) -> tuple[pd.DataFrame, str, list[str], dict[str, str], str]:
    """Resolve df / product_col / products / labels for ``seasonality_by_year_chart``.

    Parameters
    ----------
    view : ``"native"`` or ``"canonical"``
        * native — headline natives plus **naphtha** (four fuel-oil splits).
        * canonical — rollup ``panel`` incl. **Naphtha** (single Fuel oil panel).

    Returns
    -------
    (df, product_col, products, product_labels, title_suffix)
    """
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


def knoc_series_for_jodi(
    demand: pd.DataFrame,
    series_key: str,
    *,
    value_col: str = "value",
) -> pd.DataFrame:
    """Aggregate KNOC native rows for one JODI compare panel."""
    spec = JODI_COMPARE_SERIES[series_key]
    sl = demand[demand["product_native"].isin(spec.natives)]
    if sl.empty:
        return pd.DataFrame(columns=["date", value_col, "is_provisional"])
    return (
        sl.groupby(["date", "is_provisional"], as_index=False)[value_col]
        .sum()
        .sort_values("date")
    )


__all__ = [
    "KNOC_AGENCY_SOURCE",
    "KNOC_DATASET_SOURCE",
    "KNOC_METRIC_TYPE",
    "KNOC_UNIT_NATIVE",
    "KNOC_STOCKS_SOURCE",
    "KNOC_STOCKS_METRIC_TYPE",
    "KNOC_STOCKS_UNIT_NATIVE",
    "KoreaDataset",
    "KoreaDatasetName",
    "CONSUMPTION_DATASET",
    "STOCKS_DATASET",
    "KOREA_DATASETS",
    "COUNTRY_CODE",
    "COUNTRY_NAME",
    "SOURCE_ID",
    "RAW_COLUMN_TO_NATIVE",
    "FUEL_OIL_NATIVE",
    "DELIVERY_HEADLINE_NATIVE",
    "CHART_PRODUCTS",
    "SEASONALITY_NATIVE_PRODUCTS",
    "SEASONALITY_PANELS_CANONICAL",
    "seasonality_chart_inputs",
    "DISPLAY_LABELS",
    "UNITS_KIND",
    "JODI_COMPARE_SERIES",
    "JodiCompareSeries",
    "normalize_raw_column",
    "is_knoc_primary",
    "parse_korea_wide_csv",
    "parse_korea_consumption_csv",
    "parse_korea_csv_files",
    "parse_korea_directory",
    "parse_bundle_filename",
    "dataset_for_path",
    "raw_dir_for_dataset",
    "audit_raw_csv",
    "find_stitched_gaps",
    "sum_fuel_oil_by_date",
    "knoc_series_for_jodi",
]
