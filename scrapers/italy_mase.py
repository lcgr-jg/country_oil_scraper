"""
Italy MASE consumi petroliferi scraper.

MASE publishes petroleum consumption via a React SPA backed by a public CMIS
REST API. File links are not in the HTML — list folders via JSON, then download
by opaque document id.

Datasets (see config/sources.yaml):
  - consumi_definitivi     Final annual workbooks (monthly rows within year), 2002–2025
  - consumi_preconsuntivi  Preliminary monthly workbooks (2022+)

Layer split (see ARCHITECTURE.md):
  - This module: download (+ parse in Phase 2) — source-native tidy data
  - reference/italy.py: product name normalization + REPORTING_PRODUCTS
  - processors/italy_* (Phase 2): upsert, parquet, canonical mapping
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import requests

from reference.italy import (
    MASE_METRIC_TYPE,
    MASE_UNIT_NATIVE,
    normalize_mase_group,
    normalize_mase_product_name,
)
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

COUNTRY_CODE = "IT"
COUNTRY_NAME = "Italy"
SOURCE_ID = "mase_consumi_petroliferi"

API_BASE = "https://sisen.mase.gov.it/dgsaie/api/v1"
FOLDER_DEFINITIVI = "/sg_dgsaie/consumi_petroliferi/definitivi/"
FOLDER_PRELIMINARY_TEMPLATE = "/sg_dgsaie/consumi_petroliferi/preconsuntivi/{year}/"

DEFINITIVE_YEAR_START = 2002
DEFINITIVE_YEAR_END = 2025

# Legacy Excel (OLE) and modern xlsx (ZIP) magic bytes.
_XLS_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_XLSX_MAGIC = b"PK\x03\x04"

_DEFINITIVI_RE = re.compile(
    r"^Consumi_Petroliferi_Definitivi_(\d{4})\.(xls|xlsx)$",
    re.IGNORECASE,
)
# Preliminary files usually use Petrolio_; 2024_03 has a Petroliferi_ typo.
_PRELIMINARY_RE = re.compile(
    r"^Consumi_Petroli(?:o|feri)_(\d{4})_(\d{2})\.(xls|xlsx)$",
    re.IGNORECASE,
)

_HEADERS = {"User-Agent": "country_oil_scraper/1.0 (MASE consumi petroliferi)"}

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

# Standalone month headers in definitive workbooks (exclude GEN.FEB cumulative cols).
_STANDALONE_MONTHS: dict[str, int] = {
    "GEN.": 1,
    "FEB.": 2,
    "MAR.": 3,
    "APR.": 4,
    "MAG.": 5,
    "GIU.": 6,
    "LUG.": 7,
    "AGO.": 8,
    "SET.": 9,
    "OTT.": 10,
    "NOV.": 11,
    "DIC.": 12,
}

# Skip parsing below this row label in definitive sheets (footer notes).
_DEFINITIVE_STOP_MARKERS = (
    "CONSUNTIVI AGGIORNATI",
    "(*) RIGUARDA",
    "VAL. CONSUMI",
    "TOTALE  CONSUMI:",
)


def _norm_header(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return re.sub(r"\s+", " ", str(value).strip().upper())


def _parse_year_from_definitive_name(file_name: str) -> int:
    match = _DEFINITIVI_RE.match(file_name)
    if not match:
        raise ValueError(f"Not a definitive MASE filename: {file_name}")
    return int(match.group(1))


def _parse_year_month_from_preliminary_name(file_name: str) -> tuple[int, int]:
    match = _PRELIMINARY_RE.match(file_name)
    if not match:
        raise ValueError(f"Not a preliminary MASE filename: {file_name}")
    return int(match.group(1)), int(match.group(2))


def _select_definitive_sheet(path: Path, year: int) -> str:
    xls = pd.ExcelFile(path)
    for sheet_name in xls.sheet_names:
        preview = pd.read_excel(path, sheet_name=sheet_name, header=None, nrows=8)
        blob = " ".join(str(x) for x in preview.values.flatten()).upper()
        if f"ANNO {year}" in blob:
            return sheet_name
    return xls.sheet_names[-1]


def _find_prodotto_row(df: pd.DataFrame) -> int:
    for i in range(min(15, len(df))):
        if _norm_header(df.iloc[i, 0]) == "PRODOTTO":
            return i
    raise RuntimeError("PRODOTTO header row not found")


def _month_columns(header_row: pd.Series) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for col_idx, label in enumerate(header_row):
        month = _STANDALONE_MONTHS.get(_norm_header(label))
        if month is not None:
            out.append((col_idx, month))
    return out


def _coerce_value(raw: object) -> Optional[float]:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    if isinstance(raw, str) and not raw.strip():
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _finalize_rows(rows: list[dict], *, updated_at: datetime) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=CANONICAL_COLUMNS)
    df = pd.DataFrame(rows)
    df["country"] = COUNTRY_CODE
    df["country_name"] = COUNTRY_NAME
    df["source"] = SOURCE_ID
    df["metric_type"] = MASE_METRIC_TYPE
    df["product"] = df["product_native"]
    df["unit"] = MASE_UNIT_NATIVE
    df["updated_at"] = updated_at
    return df[CANONICAL_COLUMNS].sort_values(
        ["date", "product_native"], ignore_index=True
    )


def parse_definitive_mase(path: Path, *, updated_at: Optional[datetime] = None) -> pd.DataFrame:
    """Parse one definitive annual workbook into long-form monthly rows."""
    path = Path(path)
    updated_at = updated_at or datetime.utcnow()
    year = _parse_year_from_definitive_name(path.name)
    sheet = _select_definitive_sheet(path, year)
    raw = pd.read_excel(path, sheet_name=sheet, header=None)
    header_i = _find_prodotto_row(raw)
    month_cols = _month_columns(raw.iloc[header_i])

    rows: list[dict] = []
    current_group = ""

    for i in range(header_i + 1, len(raw)):
        group_cell = raw.iloc[i, 0]
        sub_cell = raw.iloc[i, 1]
        group_norm = _norm_header(group_cell)

        if group_norm and any(group_norm.startswith(m) for m in _DEFINITIVE_STOP_MARKERS):
            break

        group_label = normalize_mase_group(group_cell)
        if group_label:
            current_group = group_label

        product_native = normalize_mase_product_name(
            group_cell, sub_cell, known_group=current_group
        )
        if not product_native:
            continue

        for col_idx, month in month_cols:
            value = _coerce_value(raw.iloc[i, col_idx])
            if value is None:
                continue
            rows.append(
                {
                    "date": pd.Timestamp(year=year, month=month, day=1),
                    "product_native": product_native,
                    "value": value,
                    "is_provisional": False,
                    "source_file": path.name,
                }
            )

    logger.info(
        f"Parsed definitive {path.name}: {len(rows):,} observations "
        f"({year}, sheet={sheet!r})"
    )
    return _finalize_rows(rows, updated_at=updated_at)


def parse_preliminary_mase(path: Path, *, updated_at: Optional[datetime] = None) -> pd.DataFrame:
    """Parse one preliminary monthly workbook (Italiano sheet, single month)."""
    path = Path(path)
    updated_at = updated_at or datetime.utcnow()
    year, month = _parse_year_month_from_preliminary_name(path.name)
    raw = pd.read_excel(path, sheet_name="Italiano", header=None)

    rows: list[dict] = []
    current_group = ""

    for i in range(len(raw)):
        group_cell = raw.iloc[i, 0]
        sub_cell = raw.iloc[i, 1]
        group_norm = _norm_header(group_cell)

        if group_norm.startswith("FONTE:") or group_norm.startswith("1)"):
            break

        if normalize_mase_group(group_cell):
            current_group = normalize_mase_group(group_cell)

        product_native = normalize_mase_product_name(
            group_cell, sub_cell, known_group=current_group
        )
        if not product_native:
            continue

        value = _coerce_value(raw.iloc[i, 2])
        if value is None:
            continue

        rows.append(
            {
                "date": pd.Timestamp(year=year, month=month, day=1),
                "product_native": product_native,
                "value": value,
                "is_provisional": True,
                "source_file": path.name,
            }
        )

    logger.info(
        f"Parsed preliminary {path.name}: {len(rows):,} observations "
        f"({year}-{month:02d})"
    )
    return _finalize_rows(rows, updated_at=updated_at)


def parse_mase_workbook(path: Path, *, updated_at: Optional[datetime] = None) -> pd.DataFrame:
    """Route to definitive or preliminary parser based on filename."""
    name = Path(path).name
    if _DEFINITIVI_RE.match(name):
        return parse_definitive_mase(path, updated_at=updated_at)
    if _PRELIMINARY_RE.match(name):
        return parse_preliminary_mase(path, updated_at=updated_at)
    raise ValueError(f"Unrecognized MASE workbook filename: {name}")


def parse_definitive_directory(raw_dir: Path, *, updated_at: Optional[datetime] = None) -> pd.DataFrame:
    """Parse all definitive workbooks under ``raw_dir`` and concatenate."""
    paths = sorted(raw_dir.glob("Consumi_Petroliferi_Definitivi_*"))
    if not paths:
        raise FileNotFoundError(f"No definitive workbooks in {raw_dir}")

    frames: list[pd.DataFrame] = []
    for path in paths:
        try:
            frames.append(parse_definitive_mase(path, updated_at=updated_at))
        except PermissionError:
            logger.warning(
                f"Skipping locked file (close in Excel/OneDrive?): {path.name}"
            )
    if not frames:
        raise RuntimeError(f"Could not parse any definitive workbooks in {raw_dir}")
    combined = pd.concat(frames, ignore_index=True)
    return combined.sort_values(["date", "product_native"], ignore_index=True)


def _verify_excel_bytes(body: bytes, file_name: str) -> None:
    """Reject HTML error pages masquerading as spreadsheets."""
    if body.startswith(_XLS_MAGIC) or body.startswith(_XLSX_MAGIC):
        return
    raise RuntimeError(
        f"Download of {file_name} returned {len(body)} bytes that do not look "
        f"like Excel (.xls/.xlsx). First 16 bytes: {body[:16]!r}"
    )


def _parse_definitive_year(file_name: str) -> Optional[int]:
    match = _DEFINITIVI_RE.match(file_name)
    return int(match.group(1)) if match else None


def _find_definitive_docs(
    docs: list[dict[str, Any]],
    *,
    year_start: int = DEFINITIVE_YEAR_START,
    year_end: int = DEFINITIVE_YEAR_END,
) -> list[dict[str, Any]]:
    """Filter CMIS listing to definitive annual files in the year range."""
    matched: list[dict[str, Any]] = []
    for doc in docs:
        year = _parse_definitive_year(str(doc.get("fileName", "")))
        if year is not None and year_start <= year <= year_end:
            matched.append(doc)
    return sorted(matched, key=lambda d: _parse_definitive_year(str(d["fileName"])) or 0)


def _find_latest_preliminary(docs: list[dict[str, Any]]) -> dict[str, Any]:
    """Pick the most recently modified preliminary monthly file."""
    candidates = [
        doc
        for doc in docs
        if _PRELIMINARY_RE.match(str(doc.get("fileName", "")))
    ]
    if not candidates:
        names = [doc.get("fileName") for doc in docs]
        raise RuntimeError(
            "No preliminary monthly files found in folder. "
            f"Listing contained: {names}"
        )
    return max(candidates, key=lambda d: str(d.get("lastModificationDate", "")))


class ItalyMaseScraper(BaseScraper):
    """
    Download MASE petroleum consumption workbooks via the CMIS API.

    Usage::

        scraper = ItalyMaseScraper()
        scraper.download_definitive_history()      # bootstrap 2002–2025
        scraper.download_latest_preliminary()      # latest preconsuntivo month
    """

    def __init__(self, data_dir: str = "data"):
        super().__init__(country="italy", data_dir=data_dir)

    def _list_folder(self, folder_path: str) -> list[dict[str, Any]]:
        url = f"{API_BASE}/cmis/documents"
        resp = requests.get(
            url,
            params={"folder": folder_path},
            headers=_HEADERS,
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list):
            raise RuntimeError(f"Unexpected CMIS listing response: {type(data)!r}")
        return data

    def _download_document(
        self,
        doc: dict[str, Any],
        *,
        force: bool = False,
    ) -> Path:
        file_name = str(doc["fileName"])
        doc_id = str(doc["id"])
        remote_size = int(doc.get("size") or 0)
        out_path = self.raw_dir / file_name

        if not force and out_path.exists() and remote_size > 0:
            local_size = out_path.stat().st_size
            if local_size == remote_size:
                logger.info(
                    f"[{self.country}] Cache hit ({local_size:,} bytes): {file_name}"
                )
                return out_path

        url = f"{API_BASE}/cmis/documents/{doc_id}"
        logger.info(f"[{self.country}] Downloading {file_name} (id={doc_id})")
        resp = requests.get(url, headers=_HEADERS, timeout=120, stream=True)
        resp.raise_for_status()

        chunks: list[bytes] = []
        for chunk in resp.iter_content(8192):
            if chunk:
                chunks.append(chunk)
        body = b"".join(chunks)
        _verify_excel_bytes(body, file_name)

        if remote_size > 0 and len(body) != remote_size:
            logger.warning(
                f"[{self.country}] Size mismatch for {file_name}: "
                f"expected {remote_size:,}, got {len(body):,}"
            )

        out_path.write_bytes(body)
        logger.info(f"[{self.country}] Saved {out_path} ({len(body):,} bytes)")
        return out_path

    def download_definitive_history(
        self,
        *,
        force: bool = False,
        year_start: int = DEFINITIVE_YEAR_START,
        year_end: int = DEFINITIVE_YEAR_END,
    ) -> list[Path]:
        """Download all definitive annual workbooks (bootstrap)."""
        logger.info(
            f"[{self.country}] Listing definitive folder "
            f"({year_start}–{year_end})"
        )
        docs = self._list_folder(FOLDER_DEFINITIVI)
        selected = _find_definitive_docs(
            docs, year_start=year_start, year_end=year_end
        )
        if not selected:
            raise RuntimeError(
                f"No definitive files found for {year_start}–{year_end}"
            )

        paths: list[Path] = []
        for doc in selected:
            paths.append(self._download_document(doc, force=force))
        logger.info(
            f"[{self.country}] Definitive bootstrap complete: "
            f"{len(paths)} files in {self.raw_dir}"
        )
        return paths

    def _list_preliminary_for_latest(self) -> list[dict[str, Any]]:
        """
        List preliminary folder for the current calendar year; fall back to
        previous year if the current folder is empty (early-January gap).
        """
        current_year = datetime.now().year
        for year in (current_year, current_year - 1):
            folder = FOLDER_PRELIMINARY_TEMPLATE.format(year=year)
            docs = self._list_folder(folder)
            if docs:
                logger.info(
                    f"[{self.country}] Preliminary listing: {folder} "
                    f"({len(docs)} files)"
                )
                return docs
        raise RuntimeError(
            f"No preliminary files found for {current_year} or {current_year - 1}"
        )

    def download_latest_preliminary(self, *, force: bool = False) -> Path:
        """Download the most recently published preliminary monthly workbook."""
        docs = self._list_preliminary_for_latest()
        latest = _find_latest_preliminary(docs)
        file_name = latest["fileName"]
        logger.info(
            f"[{self.country}] Latest preliminary: {file_name} "
            f"(modified {latest.get('lastModificationDate', '?')})"
        )
        return self._download_document(latest, force=force)

    def download(
        self,
        dataset_name: str,
        *,
        force: bool = False,
    ) -> Path:
        """
        Download one dataset.

        ``consumi_definitivi`` downloads the latest definitive year only;
        use ``download_definitive_history()`` for the full 2002–2025 bootstrap.
        """
        if dataset_name == "consumi_preconsuntivi":
            return self.download_latest_preliminary(force=force)

        if dataset_name == "consumi_definitivi":
            docs = self._list_folder(FOLDER_DEFINITIVI)
            selected = _find_definitive_docs(docs)
            if not selected:
                raise RuntimeError("No definitive files found")
            latest_doc = selected[-1]
            return self._download_document(latest_doc, force=force)

        raise ValueError(
            f"Unknown dataset '{dataset_name}'. Available: {self.datasets}"
        )

    def parse(self, dataset_name: str, raw_path: Path) -> pd.DataFrame:
        """Parse a local MASE workbook (definitive or preliminary)."""
        self.get_dataset_config(dataset_name)
        return parse_mase_workbook(Path(raw_path))

    def parse_definitive_history(self, raw_dir: Optional[Path] = None) -> pd.DataFrame:
        """Parse all definitive annual files in ``data/raw/italy/``."""
        directory = Path(raw_dir) if raw_dir else self.raw_dir
        return parse_definitive_directory(directory)
