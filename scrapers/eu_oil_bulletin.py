"""
European Commission Weekly Oil Bulletin scraper.

Downloads the historical prices workbook (2005→present, weekly) plus the
duties/taxes workbook from the public Oil Bulletin page, then parses them
into long, source-native DataFrames.

Why page discovery: document UUIDs on energy.ec.europa.eu can change; we
match on stable filename hints and fall back to known URLs.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urljoin

import pandas as pd
import requests

from reference.eu_oil_bulletin import (
    AGENCY_SOURCE,
    DUTIES_FILENAME_HINT,
    FALLBACK_DUTIES_URL,
    FALLBACK_HISTORY_URL,
    GEO_CATALOG,
    HISTORY_FILENAME_HINT,
    HISTORY_SHEET_CONSUMPTION,
    HISTORY_SHEET_EXCISE,
    HISTORY_SHEET_OTHER_TAX,
    HISTORY_SHEET_VAT,
    HISTORY_SHEET_WITH_TAX,
    HISTORY_SHEET_WO_TAX,
    METRIC_CONSUMPTION_ANNUAL,
    METRIC_EXCISE,
    METRIC_FX,
    METRIC_OTHER_TAX,
    METRIC_PRICE_WITH_TAX,
    METRIC_PRICE_WO_TAX,
    METRIC_VAT_RATE,
    PAGE_URL,
    PRODUCT_CODES,
    PRODUCT_UNIT,
    SOURCE_ID,
)
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

XLSX_MAGIC = b"PK\x03\x04"
PRICE_COL_RE = re.compile(
    r"^(?P<geo>[A-Z]{2}|EU|EUR)_price_(?P<tax>with_tax|wo_tax)_(?P<prod>\w+)$"
)
FX_COL_RE = re.compile(r"^(?P<geo>[A-Z]{2}|EU|EUR)_exchange_rate$")
CONSUMPTION_COL_RE = re.compile(
    r"^(?P<geo>[A-Z]{2}|EU|EUR)_consumption_(?P<prod>\w+)$"
)


class EUOilBulletinScraper(BaseScraper):
    """Scraper for EC Weekly Oil Bulletin price and tax workbooks."""

    def __init__(self, data_dir: str | Path = "data"):
        # Country key must match sources.yaml.
        super().__init__(country="eu_oil_bulletin", data_dir=str(data_dir))

    # ------------------------------------------------------------------ #
    # Download
    # ------------------------------------------------------------------ #

    def download(self, dataset_name: str, *, force: bool = False) -> Path:
        """Download one configured dataset (``prices_history`` or ``duties_taxes``)."""
        if dataset_name == "prices_history":
            return self.download_history(force=force)
        if dataset_name == "duties_taxes":
            return self.download_duties(force=force)
        raise ValueError(f"Unknown dataset: {dataset_name}")

    def download_history(self, *, force: bool = False) -> Path:
        url = self._discover_url(HISTORY_FILENAME_HINT) or FALLBACK_HISTORY_URL
        return self._download_xlsx(url, preferred_stem="prices_history", force=force)

    def download_duties(self, *, force: bool = False) -> Path:
        url = self._discover_url(DUTIES_FILENAME_HINT) or FALLBACK_DUTIES_URL
        return self._download_xlsx(url, preferred_stem="duties_taxes", force=force)

    def download_all(self, *, force: bool = False) -> dict[str, Path]:
        return {
            "prices_history": self.download_history(force=force),
            "duties_taxes": self.download_duties(force=force),
        }

    def latest_local_history(self) -> Optional[Path]:
        paths = sorted(
            self.raw_dir.glob("*History*.xlsx"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if paths:
            return paths[0]
        paths = sorted(
            self.raw_dir.glob("prices_history*.xlsx"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return paths[0] if paths else None

    def _discover_url(self, filename_hint: str) -> Optional[str]:
        """Find a document/download link whose filename contains ``filename_hint``."""
        try:
            resp = requests.get(PAGE_URL, timeout=90)
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("Could not fetch Oil Bulletin page: %s", exc)
            return None

        hrefs = re.findall(r'href="([^"]+)"', resp.text)
        hint_l = filename_hint.lower()
        for href in hrefs:
            full = urljoin(PAGE_URL, href)
            decoded = unquote(full).lower()
            if hint_l.lower() in decoded and "document/download" in decoded:
                logger.info("Discovered %s → %s", filename_hint, full)
                return full
        logger.warning("No page link matched hint %r; will use fallback URL", filename_hint)
        return None

    def _download_xlsx(
        self, url: str, *, preferred_stem: str, force: bool
    ) -> Path:
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        # Probe headers first so we can name the file from Content-Disposition.
        # Always stream body — energy.ec.europa.eu serves downloads inline.
        resp = requests.get(url, timeout=180, allow_redirects=True)
        resp.raise_for_status()
        if not resp.content.startswith(XLSX_MAGIC):
            raise ValueError(
                f"Download did not look like an xlsx (magic={resp.content[:4]!r}): {url}"
            )

        fname = self._filename_from_response(resp, preferred_stem)
        out = self.raw_dir / fname
        if out.exists() and not force and out.stat().st_size == len(resp.content):
            logger.info("Cached (same size): %s", out.name)
            return out

        out.write_bytes(resp.content)
        logger.info("Saved %s (%s bytes)", out, f"{len(resp.content):,}")
        return out

    @staticmethod
    def _filename_from_response(resp: requests.Response, preferred_stem: str) -> str:
        cd = resp.headers.get("content-disposition", "")
        m = re.search(r'filename="?([^";]+)"?', cd)
        if m:
            return Path(unquote(m.group(1))).name
        # Fallback: stable local name so re-runs overwrite predictably.
        return f"{preferred_stem}.xlsx"

    # ------------------------------------------------------------------ #
    # Parse
    # ------------------------------------------------------------------ #

    def parse(self, dataset_name: str, raw_path: Path) -> pd.DataFrame:
        """Parse a raw workbook. Prefer ``parse_history`` / ``parse_tax_sheets``."""
        if dataset_name == "prices_history":
            prices, _taxes, _cons = self.parse_history(raw_path)
            return prices
        if dataset_name == "duties_taxes":
            # Duties workbook mirrors tax sheets in the history file; store as taxes.
            return self.parse_duties_workbook(raw_path)
        raise ValueError(f"Unknown dataset: {dataset_name}")

    def parse_history(
        self, raw_path: Path
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """Return (prices_long, taxes_long, annual_consumption_long)."""
        raw_path = Path(raw_path)
        now = datetime.now(tz=UTC)
        source_file = f"eu_oil_bulletin/{raw_path.name}"

        prices_with = self._parse_price_sheet(
            raw_path,
            HISTORY_SHEET_WITH_TAX,
            tax_kind="with_tax",
            metric=METRIC_PRICE_WITH_TAX,
            source_file=source_file,
            updated_at=now,
        )
        prices_wo = self._parse_price_sheet(
            raw_path,
            HISTORY_SHEET_WO_TAX,
            tax_kind="wo_tax",
            metric=METRIC_PRICE_WO_TAX,
            source_file=source_file,
            updated_at=now,
        )
        fx = self._parse_fx_sheet(
            raw_path, HISTORY_SHEET_WITH_TAX, source_file=source_file, updated_at=now
        )
        prices = pd.concat([prices_with, prices_wo, fx], ignore_index=True)

        taxes = pd.concat(
            [
                self._parse_rate_sheet(
                    raw_path,
                    HISTORY_SHEET_VAT,
                    metric=METRIC_VAT_RATE,
                    unit="%",
                    source_file=source_file,
                    updated_at=now,
                ),
                self._parse_rate_sheet(
                    raw_path,
                    HISTORY_SHEET_EXCISE,
                    metric=METRIC_EXCISE,
                    unit="national_currency/unit",
                    source_file=source_file,
                    updated_at=now,
                ),
                self._parse_rate_sheet(
                    raw_path,
                    HISTORY_SHEET_OTHER_TAX,
                    metric=METRIC_OTHER_TAX,
                    unit="national_currency/unit",
                    source_file=source_file,
                    updated_at=now,
                ),
            ],
            ignore_index=True,
        )

        consumption = self._parse_consumption_sheet(
            raw_path, source_file=source_file, updated_at=now
        )
        logger.info(
            "Parsed history: prices=%s taxes=%s consumption=%s",
            f"{len(prices):,}",
            f"{len(taxes):,}",
            f"{len(consumption):,}",
        )
        return prices, taxes, consumption

    def parse_duties_workbook(self, raw_path: Path) -> pd.DataFrame:
        """Best-effort parse of the standalone duties workbook (tax metrics)."""
        raw_path = Path(raw_path)
        xl = pd.ExcelFile(raw_path)
        now = datetime.now(tz=UTC)
        source_file = f"eu_oil_bulletin/{raw_path.name}"
        frames: list[pd.DataFrame] = []
        for sheet in xl.sheet_names:
            low = sheet.lower()
            if "vat" in low:
                frames.append(
                    self._parse_rate_sheet(
                        raw_path,
                        sheet,
                        metric=METRIC_VAT_RATE,
                        unit="%",
                        source_file=source_file,
                        updated_at=now,
                    )
                )
            elif "excise" in low and "component" not in low:
                frames.append(
                    self._parse_rate_sheet(
                        raw_path,
                        sheet,
                        metric=METRIC_EXCISE,
                        unit="national_currency/unit",
                        source_file=source_file,
                        updated_at=now,
                    )
                )
            elif "other" in low and "tax" in low:
                frames.append(
                    self._parse_rate_sheet(
                        raw_path,
                        sheet,
                        metric=METRIC_OTHER_TAX,
                        unit="national_currency/unit",
                        source_file=source_file,
                        updated_at=now,
                    )
                )
        if not frames:
            logger.warning("No recognizable tax sheets in %s", raw_path.name)
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)

    # ------------------------------------------------------------------ #
    # Sheet parsers
    # ------------------------------------------------------------------ #

    def _parse_price_sheet(
        self,
        path: Path,
        sheet: str,
        *,
        tax_kind: str,
        metric: str,
        source_file: str,
        updated_at: datetime,
    ) -> pd.DataFrame:
        raw = pd.read_excel(path, sheet_name=sheet, header=None)
        header = raw.iloc[0].tolist()
        # Data rows start after label + unit rows (rows 1–2).
        body = raw.iloc[3:].copy()
        body = body.rename(columns={0: "date"})
        body["date"] = pd.to_datetime(body["date"], errors="coerce")
        body = body.dropna(subset=["date"])

        records: list[dict] = []
        for col_idx, code in enumerate(header):
            if col_idx == 0 or not isinstance(code, str):
                continue
            m = PRICE_COL_RE.match(code.strip())
            if not m or m.group("tax") != tax_kind:
                continue
            geo = m.group("geo")
            prod = m.group("prod")
            if prod not in PRODUCT_CODES:
                continue
            meta = GEO_CATALOG.get(geo)
            if meta is None:
                continue
            country_id, country_name = meta
            series = pd.to_numeric(body[col_idx], errors="coerce")
            product_native = PRODUCT_CODES[prod]
            unit = PRODUCT_UNIT[prod]
            for dt, val in zip(body["date"], series):
                if pd.isna(val):
                    continue
                records.append(
                    {
                        "date": dt,
                        "country": geo,
                        "country_name": country_name,
                        "country_id": country_id,
                        "source": SOURCE_ID,
                        "metric_type": metric,
                        "product_native": product_native,
                        "product": product_native,
                        "product_code": prod,
                        "value": float(val),
                        "unit": unit,
                        "is_provisional": False,
                        "source_file": source_file,
                        "updated_at": updated_at,
                        "agency": AGENCY_SOURCE,
                    }
                )
        return pd.DataFrame.from_records(records)

    def _parse_fx_sheet(
        self,
        path: Path,
        sheet: str,
        *,
        source_file: str,
        updated_at: datetime,
    ) -> pd.DataFrame:
        """FX columns live next to price blocks (EUR per 1 unit of national currency)."""
        raw = pd.read_excel(path, sheet_name=sheet, header=None)
        header = raw.iloc[0].tolist()
        body = raw.iloc[3:].copy()
        body = body.rename(columns={0: "date"})
        body["date"] = pd.to_datetime(body["date"], errors="coerce")
        body = body.dropna(subset=["date"])

        records: list[dict] = []
        for col_idx, code in enumerate(header):
            if col_idx == 0 or not isinstance(code, str):
                continue
            m = FX_COL_RE.match(code.strip())
            if not m:
                continue
            geo = m.group("geo")
            meta = GEO_CATALOG.get(geo)
            if meta is None or geo in {"EU", "EUR"}:
                continue
            country_id, country_name = meta
            series = pd.to_numeric(body[col_idx], errors="coerce")
            for dt, val in zip(body["date"], series):
                if pd.isna(val):
                    continue
                records.append(
                    {
                        "date": dt,
                        "country": geo,
                        "country_name": country_name,
                        "country_id": country_id,
                        "source": SOURCE_ID,
                        "metric_type": METRIC_FX,
                        "product_native": "exchange_rate",
                        "product": "exchange_rate",
                        "product_code": "fx",
                        "value": float(val),
                        "unit": "EUR_per_national_currency",
                        "is_provisional": False,
                        "source_file": source_file,
                        "updated_at": updated_at,
                        "agency": AGENCY_SOURCE,
                    }
                )
        return pd.DataFrame.from_records(records)

    def _parse_rate_sheet(
        self,
        path: Path,
        sheet: str,
        *,
        metric: str,
        unit: str,
        source_file: str,
        updated_at: datetime,
    ) -> pd.DataFrame:
        """
        Parse VAT / excise / other-tax sheets.

        Layout is irregular: country code appears on the first row of a block,
        then subsequent rows only carry a new effective date + rates. We
        forward-fill the country code.
        """
        raw = pd.read_excel(path, sheet_name=sheet, header=None)
        if raw.empty or raw.shape[1] < 3:
            return pd.DataFrame()

        # Product labels sit on row 2 in the history workbook; units on row 3.
        # Column 0 = country, column 1 = since-date, then one col per product.
        product_row = raw.iloc[2].tolist() if len(raw) > 2 else []
        # Map column index → bulletin product code via fuzzy label match.
        col_products: dict[int, str] = {}
        for idx, label in enumerate(product_row):
            if idx < 2 or not isinstance(label, str):
                continue
            code = self._label_to_product_code(label)
            if code:
                col_products[idx] = code

        if not col_products:
            # Duties workbook variants sometimes put labels on row 3.
            for row_i in range(min(5, len(raw))):
                for idx, label in enumerate(raw.iloc[row_i].tolist()):
                    if idx < 2 or not isinstance(label, str):
                        continue
                    code = self._label_to_product_code(label)
                    if code:
                        col_products[idx] = code
                if col_products:
                    break

        records: list[dict] = []
        current_geo: Optional[str] = None
        for _, row in raw.iterrows():
            c0 = row.iloc[0]
            c1 = row.iloc[1] if len(row) > 1 else None

            geo_candidate = self._normalize_geo_token(c0)
            if geo_candidate:
                current_geo = geo_candidate
                since = pd.to_datetime(c1, errors="coerce")
            else:
                since = pd.to_datetime(c0, errors="coerce")
                if pd.isna(since):
                    since = pd.to_datetime(c1, errors="coerce")

            if current_geo is None or pd.isna(since):
                continue
            meta = GEO_CATALOG.get(current_geo)
            if meta is None or current_geo in {"EU", "EUR"}:
                continue
            country_id, country_name = meta

            for col_idx, prod in col_products.items():
                if col_idx >= len(row):
                    continue
                val = pd.to_numeric(row.iloc[col_idx], errors="coerce")
                if pd.isna(val):
                    continue
                product_native = PRODUCT_CODES[prod]
                records.append(
                    {
                        "date": since,
                        "country": current_geo,
                        "country_name": country_name,
                        "country_id": country_id,
                        "source": SOURCE_ID,
                        "metric_type": metric,
                        "product_native": product_native,
                        "product": product_native,
                        "product_code": prod,
                        "value": float(val),
                        "unit": unit,
                        "is_provisional": False,
                        "source_file": source_file,
                        "updated_at": updated_at,
                        "agency": AGENCY_SOURCE,
                    }
                )
        return pd.DataFrame.from_records(records)

    def _parse_consumption_sheet(
        self, path: Path, *, source_file: str, updated_at: datetime
    ) -> pd.DataFrame:
        """Annual consumption (kt) published inside the history workbook."""
        raw = pd.read_excel(path, sheet_name=HISTORY_SHEET_CONSUMPTION, header=None)
        header = raw.iloc[0].tolist()
        body = raw.iloc[2:].copy()
        body = body.rename(columns={0: "year"})
        body["year"] = pd.to_numeric(body["year"], errors="coerce")
        body = body.dropna(subset=["year"])

        records: list[dict] = []
        for col_idx, code in enumerate(header):
            if col_idx == 0 or not isinstance(code, str):
                continue
            m = CONSUMPTION_COL_RE.match(code.strip())
            if not m:
                continue
            geo = m.group("geo")
            prod_raw = m.group("prod")
            # Bulletin typos: heEUing_oil / heEURing_oil → heating_oil
            prod = prod_raw.replace("heEUing_oil", "heating_oil").replace(
                "heEURing_oil", "heating_oil"
            )
            if prod not in PRODUCT_CODES:
                continue
            meta = GEO_CATALOG.get(geo)
            if meta is None:
                continue
            country_id, country_name = meta
            series = pd.to_numeric(body[col_idx], errors="coerce")
            product_native = PRODUCT_CODES[prod]
            for year, val in zip(body["year"], series):
                if pd.isna(val):
                    continue
                records.append(
                    {
                        "date": pd.Timestamp(int(year), 1, 1),
                        "country": geo,
                        "country_name": country_name,
                        "country_id": country_id,
                        "source": SOURCE_ID,
                        "metric_type": METRIC_CONSUMPTION_ANNUAL,
                        "product_native": product_native,
                        "product": product_native,
                        "product_code": prod,
                        "value": float(val),
                        "unit": "kt",
                        "is_provisional": False,
                        "source_file": source_file,
                        "updated_at": updated_at,
                        "agency": AGENCY_SOURCE,
                    }
                )
        return pd.DataFrame.from_records(records)

    @staticmethod
    def _normalize_geo_token(value: object) -> Optional[str]:
        if not isinstance(value, str):
            return None
        token = value.strip().rstrip("_")
        if re.fullmatch(r"[A-Z]{2}|EU|EUR", token):
            return token
        return None

    @staticmethod
    def _label_to_product_code(label: str) -> Optional[str]:
        low = label.lower()
        if "euro-super" in low or "euro super" in low or "95" in low and "super" in low:
            return "euro95"
        if "gpl" in low or "lpg" in low:
            return "LPG"
        if "chauffage" in low or "heating" in low or "heiz" in low:
            return "heating_oil"
        if "soufre >" in low or "sulphur >" in low or "> 1%" in low:
            return "fuel_oil_2"
        if "fuel oil" in low or "heizöl" in low or "heizol" in low:
            return "fuel_oil_1"
        if (
            "automobile" in low
            or "automotive gas oil" in low
            or "dieselkraftstoff" in low
            or "diesel" in low
        ):
            return "diesel"
        return None
