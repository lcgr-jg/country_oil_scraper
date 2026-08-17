"""
Thailand EPPO Table 2.3-4 — Sale of Petroleum Products scraper.

Parses two Excel layouts published by EPPO (Energy Policy and Planning Office):
  - Historical monthly wide workbook (T02_03_04-1.xls, 1986–2024)
  - Current snapshot workbook (T02_03_04.xls, Q1 averages + monthly 2025+)

Live files are linked from the petroleum statistics page; EPPO serves legacy
``.xls`` (OLE) workbooks under ``/epposite/images/.../Petroleum/``.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional
from urllib.parse import urljoin

import pandas as pd
import requests

from reference.eppo import (
    EPPO_DATASET_SOURCE,
    EPPO_METRIC_TYPE,
    EPPO_UNIT_NATIVE,
    is_eppo_unified_primary,
    normalize_eppo_product_name,
)
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

COUNTRY_CODE = "TH"
COUNTRY_NAME = "Thailand"
SOURCE_ID = EPPO_DATASET_SOURCE

# Scraper output schema (processor adds product_canonical / category).
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

# Historical wide sheet: (col_index, sub_header, parent_group)
_HIST_PRODUCT_COLS = [
    (1, "TOTAL", "GASOLINE"),
    (2, "REGULAR", "GASOLINE"),
    (3, "PREMIUM", "GASOLINE"),
    (4, "KEROSENE", None),
    (5, "TOTAL", "DIESEL"),
    (6, "HSD", "DIESEL"),
    (7, "LSD", "DIESEL"),
    (8, "JP", None),
    (9, "FUELOIL", None),
    (10, "LPG", None),
    (11, "TOTAL", "COUNTRY"),
]

_MONTHS = [
    "JAN", "FEB", "MAR", "APR", "MAY", "JUN",
    "JUL", "AUG", "SEP", "OCT", "NOV", "DEC",
]
_MONTH_ALIASES: dict[str, int] = {}
for _i, _name in enumerate(_MONTHS, start=1):
    _MONTH_ALIASES[_name] = _i
    _MONTH_ALIASES[_name.title()] = _i
    _MONTH_ALIASES[_name[:3].title()] = _i

# Legacy Excel (OLE compound document) — EPPO serves .xls, not .xlsx.
_XLS_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

_FILE_KIND = Literal["current", "historical"]
_CURRENT_BASENAME = "T02_03_04.xls"
_HISTORICAL_BASENAME = "T02_03_04-1.xls"

_DEFAULT_FALLBACK_URLS: dict[_FILE_KIND, str] = {
    "current": (
        "https://www.eppo.go.th/epposite/images/Energy-Statistics/"
        "energyinformation/Energy_Statistics/Petroleum/T02_03_04.xls"
    ),
    "historical": (
        "https://www.eppo.go.th/epposite/images/Energy-Statistics/"
        "energyinformation/Energy_Statistics/Petroleum/T02_03_04-1.xls"
    ),
}


def discover_table_23_4_urls(page_html: str, page_url: str) -> dict[_FILE_KIND, str]:
    """
    Parse EPPO petroleum page HTML for Table 2.3-4 download hrefs.

    Returns absolute URLs for ``current`` (T02_03_04.xls) and ``historical``
    (T02_03_04-1.xls). Ignores the yearly file (T02_03_04-2.xls).
    """
    out: dict[_FILE_KIND, str] = {}
    for href in re.findall(
        r"""href=["']([^"']*T02_03_04(?:-1)?\.xls)["']""",
        page_html,
        flags=re.IGNORECASE,
    ):
        name = Path(href.split("?")[0]).name.lower()
        abs_url = urljoin(page_url, href)
        if name == _CURRENT_BASENAME.lower():
            out["current"] = abs_url
        elif name == _HISTORICAL_BASENAME.lower():
            out["historical"] = abs_url
    return out


def _resolve_download_url(
    ds_config: dict,
    kind: _FILE_KIND,
    page_html: str,
    page_url: str,
) -> str:
    """Page-discovered URL with sources.yaml / module fallbacks."""
    discovered = discover_table_23_4_urls(page_html, page_url)
    if kind in discovered:
        return discovered[kind]

    yaml_key = f"download_url_{kind}"
    if ds_config.get(yaml_key):
        return str(ds_config[yaml_key])

    fallback = ds_config.get("download_urls", {}).get(kind)
    if fallback:
        return str(fallback)

    return _DEFAULT_FALLBACK_URLS[kind]


def _verify_excel_bytes(body: bytes, url: str) -> None:
    if body.startswith(_XLS_MAGIC):
        return
    raise RuntimeError(
        f"Download from {url} returned {len(body)} bytes that do not look "
        f"like a legacy Excel (.xls) file. First 16 bytes: {body[:16]!r}"
    )


class ThailandEPPOScraper(BaseScraper):
    """
    Parser for EPPO petroleum product sales (Table 2.3-4).

    Usage::

        scraper = ThailandEPPOScraper()
        df = scraper.build_monthly_series(hist_path, curr_path)
    """

    def __init__(self, data_dir: str = "data"):
        super().__init__(country="thailand", data_dir=data_dir)

    def download(
        self,
        dataset_name: str,
        *,
        kind: _FILE_KIND = "current",
        force: bool = False,
    ) -> Path:
        """
        Download Table 2.3-4 workbook from EPPO.

        Args:
            dataset_name: ``petroleum_sales`` (only dataset today).
            kind: ``current`` (rolling snapshot) or ``historical`` (1986–2024).
            force: Re-download even when a local copy exists.
        """
        return self._download_file(dataset_name, kind=kind, force=force)

    def download_historical(
        self,
        dataset_name: str,
        *,
        force: bool = False,
    ) -> Path:
        """Convenience wrapper for the historical monthly workbook."""
        return self.download(dataset_name, kind="historical", force=force)

    def download_both(
        self,
        dataset_name: str,
        *,
        force: bool = False,
    ) -> dict[_FILE_KIND, Path]:
        """Download current + historical workbooks (bootstrap)."""
        return {
            "current": self.download(dataset_name, kind="current", force=force),
            "historical": self.download(
                dataset_name, kind="historical", force=force
            ),
        }

    def _download_file(
        self,
        dataset_name: str,
        *,
        kind: _FILE_KIND,
        force: bool,
    ) -> Path:
        ds_config = self.get_dataset_config(dataset_name)
        page_url = ds_config.get(
            "page_url",
            "https://www.eppo.go.th/index.php/en/en-energystatistics/petroleum-statistic",
        )
        logger.info(f"[{self.country}] Downloading EPPO Table 2.3-4 ({kind})")

        headers = {"User-Agent": "country_oil_scraper/1.0 (EPPO Table 2.3-4)"}
        page_resp = requests.get(page_url, timeout=60, headers=headers)
        page_resp.raise_for_status()

        download_url = _resolve_download_url(
            ds_config, kind, page_resp.text, page_url
        )
        basename = _CURRENT_BASENAME if kind == "current" else _HISTORICAL_BASENAME
        out_path = self.raw_dir / basename

        if not force and out_path.exists() and out_path.stat().st_size > 1000:
            try:
                head = requests.head(
                    download_url, timeout=30, allow_redirects=True, headers=headers
                )
                remote_len = head.headers.get("Content-Length")
                if remote_len and int(remote_len) == out_path.stat().st_size:
                    logger.info(
                        f"  Cached: {out_path} ({out_path.stat().st_size:,} bytes)"
                    )
                    return out_path
            except requests.RequestException:
                logger.info(f"  Using cached copy: {out_path}")

        logger.info(f"  Fetching: {download_url}")
        resp = requests.get(
            download_url, timeout=120, headers=headers, stream=True
        )
        resp.raise_for_status()
        body = resp.content
        _verify_excel_bytes(body, download_url)

        out_path.write_bytes(body)
        logger.info(f"  Saved: {out_path} ({len(body) / 1024:.0f} KB)")
        return out_path

    def parse(self, dataset_name: str, raw_path: Path) -> pd.DataFrame:
        """
        Parse the **current** snapshot workbook (monthly + Q1 2025 imputation).

        For a full historical build, use ``build_monthly_series()`` instead.
        """
        self.get_dataset_config(dataset_name)
        partial = parse_current_eppo(raw_path)
        return _finalize(partial, updated_at=datetime.utcnow())

    def build_monthly_series(
        self,
        historical_path: Path,
        current_path: Path,
    ) -> pd.DataFrame:
        """Parse both workbooks, stitch, and return canonical rows."""
        hist = parse_historical_eppo(historical_path)
        curr = parse_current_eppo(current_path)
        stitched = stitch_monthly(hist, curr)
        return _finalize(stitched, updated_at=datetime.utcnow())


def parse_historical_eppo(path: Path) -> pd.DataFrame:
    """Wide historical sheet → partial long form (date, product_native, value, …)."""
    raw = pd.read_excel(path, sheet_name="T2.3-4M", header=None)
    rows: list[dict] = []
    i = 0
    while i < len(raw):
        year_val = raw.iloc[i, 0]
        if isinstance(year_val, (int, float)) and 1980 < year_val < 2030:
            year = int(year_val)
            data_start = i + 3
            for offset, month in enumerate(_MONTHS):
                r = data_start + offset
                if r >= len(raw):
                    break
                if str(raw.iloc[r, 0]).strip().upper() != month:
                    continue
                for col_idx, sub, parent in _HIST_PRODUCT_COLS:
                    val = raw.iloc[r, col_idx]
                    if pd.isna(val):
                        continue
                    if parent in ("GASOLINE", "DIESEL") and sub == "TOTAL":
                        continue
                    if parent == "COUNTRY":
                        continue
                    native = normalize_eppo_product_name(sub)
                    if not is_eppo_unified_primary(native):
                        continue
                    rows.append(
                        {
                            "date": pd.Timestamp(year=year, month=offset + 1, day=1),
                            "product_native": native,
                            "value": float(val),
                            "is_provisional": False,
                            "source_file": path.name,
                        }
                    )
            i = data_start + len(_MONTHS) + 1
        else:
            i += 1
    if not rows:
        return pd.DataFrame(
            columns=["date", "product_native", "value", "is_provisional", "source_file"]
        )
    return (
        pd.DataFrame(rows)
        .sort_values(["date", "product_native"])
        .reset_index(drop=True)
    )


def _parse_year_cell(cell: object) -> Optional[int]:
    if pd.isna(cell):
        return None
    try:
        year = int(float(cell))
    except (TypeError, ValueError):
        return None
    if 1980 < year < 2035:
        return year
    return None


def _parse_month_cell(cell: object) -> Optional[int]:
    if pd.isna(cell):
        return None
    text = str(cell).strip()
    if not text:
        return None
    return _MONTH_ALIASES.get(text) or _MONTH_ALIASES.get(text[:3].title())


def _find_current_header_rows(raw: pd.DataFrame) -> tuple[int, int, int]:
    """
    Locate the year row, month-name row, and first data row on tab55.

    EPPO labels the month row with ``TYPE`` in column A; the row above carries
    year groupings that apply forward until the next year label.
    """
    for row_idx in range(min(15, len(raw))):
        label = raw.iloc[row_idx, 0]
        if isinstance(label, str) and label.strip().upper() == "TYPE":
            return row_idx - 1, row_idx, row_idx + 1
    raise ValueError(
        "Could not locate the TYPE header row in tab55 — "
        "the current workbook layout may have changed."
    )


def _forward_fill_years(year_row: pd.Series) -> list[Optional[int]]:
    """Carry year labels on the header row forward across blank cells."""
    years: list[Optional[int]] = []
    current: Optional[int] = None
    for cell in year_row:
        parsed = _parse_year_cell(cell)
        if parsed is not None:
            current = parsed
        years.append(current)
    return years


def discover_current_column_layout(
    raw: pd.DataFrame,
) -> tuple[list[tuple[int, int, int]], list[tuple[int, int]], int]:
    """
    Infer monthly and Q1-average columns from tab55 header rows.

    Returns:
        monthly_specs: ``(col_index, year, month)`` for observed monthly cols
        q1_specs: ``(col_index, year)`` for 4-month/Q1 average cols
        data_start_row: first product row below the TYPE header
    """
    year_row_idx, month_row_idx, data_start_row = _find_current_header_rows(raw)
    year_row = raw.iloc[year_row_idx]
    month_row = raw.iloc[month_row_idx]
    years_by_col = _forward_fill_years(year_row)

    monthly_specs: list[tuple[int, int, int]] = []
    q1_specs: list[tuple[int, int]] = []

    for col_idx in range(raw.shape[1]):
        month = _parse_month_cell(month_row.iloc[col_idx])
        if month is not None:
            year = years_by_col[col_idx]
            if year is not None:
                monthly_specs.append((col_idx, year, month))
            continue

        q1_year = _parse_year_cell(month_row.iloc[col_idx])
        if q1_year is None:
            continue
        # Annual totals use the same year on both header rows; Q1 averages do not.
        if _parse_year_cell(year_row.iloc[col_idx]) is not None:
            continue
        q1_specs.append((col_idx, q1_year))

    if not monthly_specs:
        raise ValueError(
            "No monthly columns found in tab55 — check header row layout."
        )

    return monthly_specs, q1_specs, data_start_row


def parse_current_eppo(path: Path) -> pd.DataFrame:
    """Current snapshot → monthly rows incl. Q1 imputation where Jan–Mar missing."""
    raw = pd.read_excel(path, sheet_name="tab55", header=None)
    monthly_specs, q1_specs, data_start_row = discover_current_column_layout(raw)
    monthly_rows = _parse_current_rows(
        raw,
        monthly_specs,
        source_file=path.name,
        provisional=False,
        data_start_row=data_start_row,
    )

    monthly_covered = {(year, month) for _, year, month in monthly_specs}
    monthly_years = {year for _, year, _ in monthly_specs}
    q1_rows: list[dict] = []
    for q1_col, year in q1_specs:
        if year not in monthly_years:
            continue
        missing_q1_months = [
            month
            for month in (1, 2, 3)
            if (year, month) not in monthly_covered
        ]
        if not missing_q1_months:
            continue
        for row_idx in range(data_start_row, len(raw)):
            label = raw.iloc[row_idx, 0]
            if pd.isna(label) or str(label).strip() == "":
                continue
            native = normalize_eppo_product_name(label)
            if not is_eppo_unified_primary(native):
                continue
            val = raw.iloc[row_idx, q1_col]
            if pd.isna(val):
                continue
            for month in missing_q1_months:
                q1_rows.append(
                    {
                        "date": pd.Timestamp(year=year, month=month, day=1),
                        "product_native": native,
                        "value": float(val),
                        "is_provisional": True,
                        "source_file": path.name,
                    }
                )

    all_rows = monthly_rows + q1_rows
    if not all_rows:
        return pd.DataFrame(
            columns=["date", "product_native", "value", "is_provisional", "source_file"]
        )
    return (
        pd.DataFrame(all_rows)
        .sort_values(["date", "product_native"])
        .reset_index(drop=True)
    )


def _parse_current_rows(
    raw: pd.DataFrame,
    col_specs: list[tuple[int, int, int]],
    *,
    source_file: str,
    provisional: bool,
    data_start_row: int,
) -> list[dict]:
    out: list[dict] = []
    for row_idx in range(data_start_row, len(raw)):
        label = raw.iloc[row_idx, 0]
        if pd.isna(label) or str(label).strip() == "":
            continue
        native = normalize_eppo_product_name(label)
        if not is_eppo_unified_primary(native):
            continue
        for col, year, month in col_specs:
            val = raw.iloc[row_idx, col]
            if pd.isna(val):
                continue
            out.append(
                {
                    "date": pd.Timestamp(year=year, month=month, day=1),
                    "product_native": native,
                    "value": float(val),
                    "is_provisional": provisional,
                    "source_file": source_file,
                }
            )
    return out


def stitch_monthly(
    historical: pd.DataFrame,
    current: pd.DataFrame,
) -> pd.DataFrame:
    """
    Combine historical (≤2024-12) with current (≥2025-01).

    On duplicate natural keys, observed rows beat provisional; current file
    beats historical (there should be no month overlap in practice).
    """
    if historical.empty and current.empty:
        return historical

    hist = historical[historical["date"] <= pd.Timestamp("2024-12-01")].copy()
    curr = current[current["date"] >= pd.Timestamp("2025-01-01")].copy()

    combined = pd.concat([hist, curr], ignore_index=True)
    key_cols = ["date", "product_native"]

    # Sort so best row is last per key: provisional first, then observed.
    combined = combined.sort_values(
        key_cols + ["is_provisional"],
        ascending=[True, True, True],
    )
    return (
        combined.drop_duplicates(subset=key_cols, keep="last")
        .sort_values(key_cols)
        .reset_index(drop=True)
    )


def _finalize(partial: pd.DataFrame, *, updated_at: datetime) -> pd.DataFrame:
    """Stamp provenance columns and enforce CANONICAL_COLUMNS order."""
    if partial.empty:
        df = pd.DataFrame(columns=CANONICAL_COLUMNS)
        return df

    df = partial.copy()
    df["country"] = COUNTRY_CODE
    df["country_name"] = COUNTRY_NAME
    df["source"] = SOURCE_ID
    df["metric_type"] = EPPO_METRIC_TYPE
    df["product"] = df["product_native"]
    df["unit"] = EPPO_UNIT_NATIVE
    df["updated_at"] = updated_at
    df["is_provisional"] = df["is_provisional"].astype(bool)

    df = df[CANONICAL_COLUMNS].copy()
    return df.sort_values(
        ["date", "product_native"], ignore_index=True
    )


__all__ = [
    "CANONICAL_COLUMNS",
    "ThailandEPPOScraper",
    "discover_current_column_layout",
    "discover_table_23_4_urls",
    "parse_historical_eppo",
    "parse_current_eppo",
    "stitch_monthly",
]
