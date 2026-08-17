"""
India PPAC scraper — handles four PPAC datasets:

1. products_wise_consumption  (AJAX-loaded table → fallback to page scrape)
2. state_wise_consumption     (direct Excel download)
3. pmuy_connections           (direct Excel download)
4. pt_consumption             (historical multi-sheet Excel, one sheet per fiscal year)

Key design decisions:
- For direct downloads, we grab the URL from the page HTML each time 
  (not hardcoded) because PPAC updates filenames when they refresh data.
- For the AJAX table, we try the known endpoint pattern first. If that
  fails, we fall back to looking for downloadable Excel links on the page.
- pt_consumption uses a URL-pattern match (PT_Consumption.xlsx) because
  PPAC embeds a Unix timestamp in the filename on every update.
- All downloads get timestamped filenames so we keep a history of snapshots.
"""

import re
import logging
from pathlib import Path
from datetime import datetime, date

import requests
import pandas as pd
from bs4 import BeautifulSoup

from .base import BaseScraper

logger = logging.getLogger(__name__)

# Shared session config
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

BASE_URL = "https://ppac.gov.in"


class IndiaPPACScraper(BaseScraper):
    """
    Scraper for India's Petroleum Planning & Analysis Cell (PPAC).
    
    Usage:
        scraper = IndiaPPACScraper()
        scraper.datasets  # ['products_wise_consumption', 'state_wise_consumption', 'pmuy_connections']
        
        # Download + parse a specific dataset
        df = scraper.run('state_wise_consumption')
        
        # Or step by step
        raw = scraper.download('state_wise_consumption')
        df  = scraper.parse('state_wise_consumption', raw)
    """
    
    # Fiscal month order: 1=APR … 12=MAR
    FISCAL_MONTH_MAP = {
        "APR": 1, "MAY": 2, "JUN": 3, "JUL": 4,
        "AUG": 5, "SEP": 6, "OCT": 7, "NOV": 8,
        "DEC": 9, "JAN": 10, "FEB": 11, "MAR": 12,
    }
    # Calendar month numbers for the same keys
    CALENDAR_MONTH_MAP = {
        "APR": 4, "MAY": 5, "JUN": 6, "JUL": 7,
        "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11,
        "DEC": 12, "JAN": 1, "FEB": 2, "MAR": 3,
    }

    def __init__(self, data_dir: str = "data"):
        super().__init__(country="india", data_dir=data_dir)
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
    
    # ------------------------------------------------------------------ #
    #  DOWNLOAD
    # ------------------------------------------------------------------ #
    
    def download(self, dataset_name: str) -> Path:
        """Route to the appropriate download method."""
        if dataset_name == "pt_consumption":
            return self._download_pt_consumption()

        ds_config = self.get_dataset_config(dataset_name)
        method = ds_config.get("access_method", "direct_download")
        
        if method == "direct_download":
            return self._download_direct(dataset_name, ds_config)
        elif method == "ajax":
            return self._download_ajax_or_fallback(dataset_name, ds_config)
        else:
            raise NotImplementedError(f"Access method '{method}' not implemented")
    
    def _download_direct(self, dataset_name: str, ds_config: dict) -> Path:
        """
        Download an Excel file via direct URL.
        
        Strategy: 
        1. Fetch the page HTML to find the current download link
           (because PPAC changes filenames on update)
        2. Fall back to the hardcoded URL in config if page scrape fails
        """
        page_url = ds_config["page_url"]
        
        # Try to find the live download link from the page
        download_url = self._find_download_link(page_url)
        
        if download_url is None:
            # Fallback to config URL
            download_url = ds_config.get("download_url")
            if download_url is None:
                raise RuntimeError(
                    f"Could not find download link on {page_url} "
                    f"and no fallback URL in config"
                )
            logger.warning(f"  Using fallback URL from config: {download_url}")
        
        # Download the file
        logger.info(f"  Downloading: {download_url}")
        resp = self.session.get(download_url, timeout=30)
        resp.raise_for_status()
        
        # Save with timestamp
        ext = self._guess_extension(download_url, resp)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{dataset_name}_{timestamp}{ext}"
        out_path = self.raw_dir / filename
        
        out_path.write_bytes(resp.content)
        logger.info(f"  Saved: {out_path} ({len(resp.content) / 1024:.1f} KB)")
        return out_path
    
    def _find_download_link(self, page_url: str) -> str | None:
        """
        Scrape the page HTML for .xlsx/.xls/.csv download links.
        Returns the first match as an absolute URL, or None.
        """
        try:
            resp = self.session.get(page_url, timeout=20)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")
            
            # Look for links to Excel/CSV files
            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"]
                if re.search(r"\.(xlsx|xls|csv)$", href, re.IGNORECASE):
                    # Make absolute
                    if href.startswith("http"):
                        return href
                    elif href.startswith("/"):
                        return BASE_URL + href
                    else:
                        return BASE_URL + "/" + href
            
            return None
        except Exception as e:
            logger.warning(f"  Failed to scrape page for download link: {e}")
            return None
    
    def _download_ajax_or_fallback(self, dataset_name: str, ds_config: dict) -> Path:
        """
        For the products-wise consumption page where data is loaded via AJAX.
        
        Strategy:
        1. Try known AJAX endpoint patterns (POST with year/unit params)
        2. If that fails, try to find downloadable Excel links on the page
        3. If that also fails, raise with instructions for manual approach
        
        NOTE: The exact AJAX endpoint needs to be captured from browser 
        DevTools. This is a best-effort implementation. See the notebook 
        for instructions on how to capture the endpoint.
        """
        page_url = ds_config["page_url"]
        
        # -- Attempt 1: Try common AJAX patterns --
        # PPAC sites often use POST endpoints like /api/get-consumption-data
        # or the page itself with form data. We try several patterns.
        ajax_endpoints = [
            f"{BASE_URL}/api/consumption/products-wise",
            f"{BASE_URL}/consumption/get-products-wise-data",
            f"{BASE_URL}/consumption/products-wise",  # POST to same URL
        ]
        
        # Try current fiscal year and previous
        current_year = datetime.now().year
        fiscal_years = [
            f"{current_year-1}-{current_year}",
            f"{current_year}-{current_year+1}",
        ]
        
        for endpoint in ajax_endpoints:
            for fy in fiscal_years:
                try:
                    resp = self.session.post(
                        endpoint,
                        data={"year": fy, "unit": "quantity"},
                        headers={
                            **HEADERS,
                            "X-Requested-With": "XMLHttpRequest",
                        },
                        timeout=15,
                    )
                    if resp.ok and len(resp.text) > 200:
                        # Looks like we got data
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                        filename = f"{dataset_name}_{fy}_{timestamp}.html"
                        out_path = self.raw_dir / filename
                        out_path.write_text(resp.text, encoding="utf-8")
                        logger.info(f"  AJAX success: {endpoint} for {fy}")
                        return out_path
                except Exception:
                    continue
        
        logger.warning("  AJAX attempts failed. Trying page scrape for Excel link...")
        
        # -- Attempt 2: Look for downloadable reports on the page --
        download_url = self._find_download_link(page_url)
        if download_url:
            # Re-route to direct download
            ds_config_copy = {**ds_config, "download_url": download_url}
            return self._download_direct(dataset_name, ds_config_copy)
        
        # -- Attempt 3: Fail with helpful message --
        raise RuntimeError(
            f"Could not fetch data from {page_url}.\n"
            f"The products-wise table loads via AJAX which requires "
            f"capturing the exact endpoint from browser DevTools.\n\n"
            f"To capture it:\n"
            f"  1. Open {page_url} in Chrome\n"
            f"  2. Open DevTools → Network tab → filter by XHR\n"
            f"  3. Select a year from the dropdown and click 'View Data'\n"
            f"  4. Look for the POST request — copy the URL and payload\n"
            f"  5. Update config/sources.yaml with the endpoint\n\n"
            f"Alternatively, register on ppac.gov.in (free) to download "
            f"the historical Excel report directly."
        )
    
    # ------------------------------------------------------------------ #
    #  PARSE
    # ------------------------------------------------------------------ #
    
    def parse(self, dataset_name: str, raw_path: Path) -> pd.DataFrame:
        """Route to the appropriate parser."""
        parsers = {
            "products_wise_consumption": self._parse_products_wise,
            "state_wise_consumption": self._parse_state_wise,
            "pmuy_connections": self._parse_pmuy,
            "pt_consumption": self._parse_pt_consumption,
            "pt_trade": self._parse_pt_trade,
            "pt_production": self._parse_pt_production,
        }
        
        parser = parsers.get(dataset_name)
        if parser is None:
            raise ValueError(f"No parser for '{dataset_name}'")
        
        return parser(raw_path)
    
    def _parse_state_wise(self, raw_path: Path) -> pd.DataFrame:
        """
        Parse the state-wise consumption Excel file.
        
        The Excel typically has multiple sheets (one per fiscal year or 
        one per product). We read all sheets and stack them.
        """
        xls = pd.ExcelFile(raw_path)
        logger.info(f"  Sheets found: {xls.sheet_names}")
        
        frames = []
        for sheet_name in xls.sheet_names:
            try:
                df = pd.read_excel(
                    raw_path, 
                    sheet_name=sheet_name,
                    header=None,  # We'll detect the header row
                )
                
                # Clean: find the header row (usually has 'State' or 'S.No')
                header_row = self._find_header_row(df, ["state", "s.no", "sl"])
                
                if header_row is not None:
                    df.columns = df.iloc[header_row].astype(str).str.strip()
                    df = df.iloc[header_row + 1:].reset_index(drop=True)
                
                # Drop fully empty rows/cols
                df = df.dropna(how="all").dropna(axis=1, how="all")
                
                # Add metadata
                df["sheet_name"] = sheet_name
                df["country"] = "India"
                df["source"] = "PPAC"
                df["dataset"] = "state_wise_consumption"
                
                frames.append(df)
            except Exception as e:
                logger.warning(f"  Failed to parse sheet '{sheet_name}': {e}")
        
        if not frames:
            raise RuntimeError(f"No parseable sheets in {raw_path}")
        
        combined = pd.concat(frames, ignore_index=True)
        return combined
    
    def _parse_pmuy(self, raw_path: Path) -> pd.DataFrame:
        """
        Parse the PMUY connections Excel file.
        Similar structure to state-wise: state rows, OMC columns.
        """
        xls = pd.ExcelFile(raw_path)
        logger.info(f"  Sheets found: {xls.sheet_names}")
        
        frames = []
        for sheet_name in xls.sheet_names:
            try:
                df = pd.read_excel(raw_path, sheet_name=sheet_name, header=None)
                
                header_row = self._find_header_row(
                    df, ["state", "s.no", "sl", "iocl", "bpcl", "hpcl"]
                )
                
                if header_row is not None:
                    df.columns = df.iloc[header_row].astype(str).str.strip()
                    df = df.iloc[header_row + 1:].reset_index(drop=True)
                
                df = df.dropna(how="all").dropna(axis=1, how="all")
                
                df["sheet_name"] = sheet_name
                df["country"] = "India"
                df["source"] = "PPAC"
                df["dataset"] = "pmuy_connections"
                
                frames.append(df)
            except Exception as e:
                logger.warning(f"  Failed to parse sheet '{sheet_name}': {e}")
        
        if not frames:
            raise RuntimeError(f"No parseable sheets in {raw_path}")
        
        return pd.concat(frames, ignore_index=True)
    
    def _parse_products_wise(self, raw_path: Path) -> pd.DataFrame:
        """
        Parse products-wise consumption data.
        Could be HTML (from AJAX) or Excel (from download).
        """
        suffix = raw_path.suffix.lower()
        
        if suffix in (".xlsx", ".xls"):
            return self._parse_products_wise_excel(raw_path)
        elif suffix in (".html", ".htm"):
            return self._parse_products_wise_html(raw_path)
        else:
            raise ValueError(f"Unexpected file type: {suffix}")
    
    def _parse_products_wise_excel(self, raw_path: Path) -> pd.DataFrame:
        """Parse Excel version of products-wise consumption."""
        xls = pd.ExcelFile(raw_path)
        logger.info(f"  Sheets found: {xls.sheet_names}")
        
        frames = []
        for sheet_name in xls.sheet_names:
            try:
                df = pd.read_excel(raw_path, sheet_name=sheet_name, header=None)
                
                header_row = self._find_header_row(
                    df, ["product", "april", "may", "total"]
                )
                
                if header_row is not None:
                    df.columns = df.iloc[header_row].astype(str).str.strip()
                    df = df.iloc[header_row + 1:].reset_index(drop=True)
                
                df = df.dropna(how="all").dropna(axis=1, how="all")
                
                df["sheet_name"] = sheet_name
                df["country"] = "India"
                df["source"] = "PPAC"
                df["dataset"] = "products_wise_consumption"
                
                frames.append(df)
            except Exception as e:
                logger.warning(f"  Failed to parse sheet '{sheet_name}': {e}")
        
        if not frames:
            raise RuntimeError(f"No parseable sheets in {raw_path}")
        
        return pd.concat(frames, ignore_index=True)
    
    def _parse_products_wise_html(self, raw_path: Path) -> pd.DataFrame:
        """Parse HTML table from AJAX response."""
        html = raw_path.read_text(encoding="utf-8")
        
        # Try pandas read_html first
        tables = pd.read_html(html)
        if not tables:
            raise RuntimeError("No tables found in HTML response")
        
        # Take the largest table
        df = max(tables, key=len)
        
        df["country"] = "India"
        df["source"] = "PPAC"
        df["dataset"] = "products_wise_consumption"
        
        return df
    
    def _download_pt_consumption(self) -> Path:
        """
        Download the PT Consumption historical Excel from PPAC.

        Strategy:
        1. Scrape the products-wise page for a link whose href contains
           url_pattern (PT_Consumption.xlsx) — handles timestamp changes.
        2. Fall back to the hardcoded download_url in config.
        """
        ds_config = self.get_dataset_config("pt_consumption")
        page_url = ds_config["page_url"]
        url_pattern = ds_config.get("url_pattern", "PT_Consumption.xlsx")

        download_url = self._find_download_link_by_pattern(page_url, url_pattern)

        if download_url is None:
            download_url = ds_config.get("download_url")
            if download_url is None:
                raise RuntimeError(
                    f"Could not find {url_pattern} on {page_url} "
                    f"and no fallback download_url in config"
                )
            logger.warning(
                f"  PT_Consumption link not found on page; using config fallback: {download_url}"
            )

        logger.info(f"  Downloading pt_consumption: {download_url}")
        resp = self.session.get(download_url, timeout=60)
        resp.raise_for_status()

        ext = self._guess_extension(download_url, resp)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"pt_consumption_{timestamp}{ext}"
        out_path = self.raw_dir / filename
        out_path.write_bytes(resp.content)
        logger.info(f"  Saved: {out_path} ({len(resp.content) / 1024:.1f} KB)")
        return out_path

    def _find_download_link_by_pattern(self, page_url: str, pattern: str) -> str | None:
        """
        Scrape a page for an <a href> that contains `pattern`.
        Returns the first match as an absolute URL, or None.
        """
        try:
            resp = self.session.get(page_url, timeout=20)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"]
                if pattern in href:
                    if href.startswith("http"):
                        return href
                    elif href.startswith("/"):
                        return BASE_URL + href
                    else:
                        return BASE_URL + "/" + href
        except Exception as e:
            logger.warning(f"  Failed to scrape {page_url} for pattern '{pattern}': {e}")
        return None

    def _parse_pt_trade(self, raw_path: Path) -> pd.DataFrame:
        """Parse combined PPAC import/export workbook (see reference.india)."""
        from reference.india import parse_pt_trade_workbook

        return parse_pt_trade_workbook(raw_path)

    def _parse_pt_production(self, raw_path: Path) -> pd.DataFrame:
        """Parse PPAC refinery production monthwise workbook."""
        from reference.india import parse_pt_production_workbook

        return parse_pt_production_workbook(raw_path)

    def _parse_pt_consumption(self, raw_path: Path) -> pd.DataFrame:
        """
        Parse a PT Consumption Excel file (either the multi-sheet historical
        .xls or the single-sheet current .xlsx) into a tidy long-format DataFrame.

        Output columns:
            fiscal_year, fiscal_month, month_name,
            calendar_year, calendar_month, date,
            product, value_000mt, is_total_row,
            source_file, updated_at
        """
        suffix = raw_path.suffix.lower()
        engine = "xlrd" if suffix == ".xls" else "openpyxl"

        xls = pd.ExcelFile(raw_path, engine=engine)
        skip_sheets = {"historical (year-wise)"}
        sheets_to_parse = [s for s in xls.sheet_names if s.lower() not in skip_sheets]
        logger.info(f"  PT Consumption sheets to parse: {sheets_to_parse}")

        frames = []
        for sheet_name in sheets_to_parse:
            try:
                df_sheet = self._parse_pt_sheet(xls, sheet_name, raw_path.name)
                frames.append(df_sheet)
            except Exception as e:
                logger.warning(f"  Skipping sheet '{sheet_name}': {e}")

        if not frames:
            raise RuntimeError(f"No parseable sheets in {raw_path}")

        result = pd.concat(frames, ignore_index=True)
        logger.info(f"  PT Consumption parsed: {len(result)} rows across {len(frames)} sheets")
        return result

    def _parse_pt_sheet(
        self, xls: pd.ExcelFile, sheet_name: str, source_file: str
    ) -> pd.DataFrame:
        """
        Parse one fiscal-year sheet of the PT Consumption Excel.

        Sheet layout (0-indexed rows):
          Row 4:  "Period : April YYYY-March YYYY"  (or "Period : April-YY to March-YY")
          Row 7:  column headers — PRODUCTS | APR | MAY | ... | MAR | TOTAL
          Row 8+: product rows; last data row is "TOTAL"
          After TOTAL: footnote rows (skipped)
        """
        raw = pd.read_excel(xls, sheet_name=sheet_name, header=None)

        # -- Extract fiscal year from the Period cell --
        fiscal_year = self._extract_fiscal_year(raw, sheet_name)

        # -- Find header row (row with PRODUCTS / APR) --
        # require_all=True: "apr" alone would match "april" in the Period title row
        header_row = self._find_header_row(raw, ["products", "apr"], require_all=True)
        if header_row is None:
            raise ValueError(f"Cannot find header row in sheet '{sheet_name}'")

        # Build a working DataFrame from header row onward
        df = raw.iloc[header_row:].copy()
        df.columns = [str(v).strip().upper() for v in df.iloc[0]]
        df = df.iloc[1:].reset_index(drop=True)

        # Keep only rows up to and including the totals row; drop footnotes.
        # Older sheets: "All Products total" / "All products total"
        # Newer sheets: "TOTAL"
        total_mask = df["PRODUCTS"].str.strip().str.upper().isin(
            {"TOTAL", "ALL PRODUCTS TOTAL"}
        )
        if total_mask.any():
            total_idx = total_mask.idxmax()   # first match
            df = df.iloc[: total_idx + 1].copy()

        # Drop fully empty rows
        df = df.dropna(how="all").reset_index(drop=True)

        # Month columns present in this sheet
        month_cols = [m for m in self.FISCAL_MONTH_MAP if m in df.columns]
        if not month_cols:
            raise ValueError(f"No month columns found in sheet '{sheet_name}'")

        # Melt to long format
        id_vars = ["PRODUCTS"]
        df_long = df[id_vars + month_cols].melt(
            id_vars=id_vars, var_name="month_name", value_name="value_000mt"
        )
        df_long.rename(columns={"PRODUCTS": "product"}, inplace=True)

        # Drop rows with no value (incomplete months in current year)
        df_long = df_long.dropna(subset=["value_000mt"]).copy()
        df_long["value_000mt"] = pd.to_numeric(df_long["value_000mt"], errors="coerce")
        df_long = df_long.dropna(subset=["value_000mt"]).copy()

        # Derive time columns
        fiscal_start_year = self._fiscal_start_year(fiscal_year)
        df_long["fiscal_year"] = fiscal_year
        df_long["fiscal_month"] = df_long["month_name"].map(self.FISCAL_MONTH_MAP)
        df_long["calendar_month"] = df_long["month_name"].map(self.CALENDAR_MONTH_MAP)
        df_long["calendar_year"] = df_long["month_name"].apply(
            lambda m: fiscal_start_year if self.CALENDAR_MONTH_MAP[m] >= 4 else fiscal_start_year + 1
        )
        df_long["date"] = df_long.apply(
            lambda r: date(int(r["calendar_year"]), int(r["calendar_month"]), 1), axis=1
        )

        # Metadata — flag the totals row regardless of label variant
        df_long["is_total_row"] = df_long["product"].str.strip().str.upper().isin(
            {"TOTAL", "ALL PRODUCTS TOTAL"}
        )
        df_long["product"] = df_long["product"].str.strip()
        df_long["source_file"] = source_file
        df_long["updated_at"] = datetime.now()

        return df_long[[
            "fiscal_year", "fiscal_month", "month_name",
            "calendar_year", "calendar_month", "date",
            "product", "value_000mt", "is_total_row",
            "source_file", "updated_at",
        ]]

    @staticmethod
    def _extract_fiscal_year(raw: pd.DataFrame, sheet_name: str) -> str:
        """
        Pull fiscal year string (e.g. '2024-25') from the Period cell,
        falling back to the sheet name itself.
        """
        for i in range(min(8, len(raw))):
            cell = str(raw.iloc[i, 0])
            # New style: "April-25 to March-26"
            # "25" is the year April falls in (2025), so FY = "2025-26"
            m = re.search(r"April\s*[-–]\s*(\d{2})\b", cell, re.IGNORECASE)
            if m:
                april_yy = int(m.group(1))          # 25
                april_year = 2000 + april_yy         # 2025
                return f"{april_year}-{str(april_year + 1)[-2:]}"  # "2025-26"
            # Old style: "April 2024-March 2025"
            m2 = re.search(r"April\s+(\d{4})", cell, re.IGNORECASE)
            if m2:
                start = int(m2.group(1))
                return f"{start}-{str(start + 1)[-2:]}"
        return sheet_name  # e.g. "2024-25" — already the fiscal year

    @staticmethod
    def _fiscal_start_year(fiscal_year: str) -> int:
        """Return the calendar year April starts in, e.g. '2024-25' → 2024."""
        part = fiscal_year.split("-")[0].strip()
        return int(part)

    # ------------------------------------------------------------------ #
    #  HELPERS
    # ------------------------------------------------------------------ #
    
    @staticmethod
    def _find_header_row(
        df: pd.DataFrame,
        keywords: list[str],
        max_rows: int = 15,
        require_all: bool = False,
    ) -> int | None:
        """
        Scan the first N rows to find which row looks like a header.
        Returns the row index, or None if not found.

        Why: Indian government Excel files often have title rows,
        merged cells, and notes above the actual data table. We need
        to skip those to find the real column headers.

        Args:
            keywords:    Words to look for (lowercased substring match).
            require_all: If True, ALL keywords must be present in the row.
                         If False (default), ANY single keyword is enough.
                         Use require_all=True when a keyword substring could
                         appear in title rows (e.g. "apr" matching "april").
        """
        check = all if require_all else any
        for i in range(min(max_rows, len(df))):
            row_text = " ".join(
                str(v).lower() for v in df.iloc[i].values if pd.notna(v)
            )
            if check(kw in row_text for kw in keywords):
                return i
        return None
    
    @staticmethod
    def _guess_extension(url: str, resp: requests.Response) -> str:
        """Guess file extension from URL or Content-Type."""
        # From URL
        url_lower = url.lower()
        for ext in [".xlsx", ".xls", ".csv", ".pdf"]:
            if ext in url_lower:
                return ext
        
        # From Content-Type
        ct = resp.headers.get("Content-Type", "").lower()
        if "spreadsheet" in ct or "excel" in ct:
            return ".xlsx"
        elif "csv" in ct:
            return ".csv"
        
        return ".xlsx"  # default assumption for PPAC
