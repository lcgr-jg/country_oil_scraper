"""
Australia DCCEEW Petroleum Statistics scraper.

Handles one dataset:
- petroleum_statistics : Monthly Excel workbook with 26 sheets covering
                        production, refining, sales (national and by state),
                        imports and exports (volume + value, by country).

Key design notes
────────────────
- energy.gov.au sits behind a WAF that does TLS fingerprinting. Plain
  ``python-requests`` connections silently stall and time out. So this
  scraper uses ``curl_cffi`` — a requests-compatible library that performs
  the TLS handshake byte-for-byte like Chrome. The rest of the codebase
  still uses plain ``requests``; this scraper is the exception. See
  ``notebooks/06_australia_v0_scrape.ipynb`` for the diagnostic backstory.

- The publications-page URL embeds the calendar year (e.g.
  ``.../australian-petroleum-statistics-2026``). The scraper discovers the
  working URL each run (current year first, previous year as fallback)
  rather than hardcoding a year that would silently 404 on January 1st.

- Files are saved with their server-provided filename — which already
  contains the publication month (e.g. ``..._february_2026.xlsx``) — so
  no local timestamping is needed. Re-runs skip the download if a same-
  size local copy already exists. Pass ``force=True`` to override the
  cache (e.g. if you suspect DCCEEW silently revised the file).

- The impersonation profile (``IMPERSONATE_PROFILE`` below) may need to
  be bumped forward if a future Chrome release breaks the current profile
  or the WAF tightens its detection. ``chrome131`` was verified against
  energy.gov.au's WAF on 2026-05.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from curl_cffi import requests
from bs4 import BeautifulSoup
import pandas as pd

from .base import BaseScraper

logger = logging.getLogger(__name__)


# Used to turn relative hrefs ("/sites/default/files/...") into absolute URLs.
BASE_URL = "https://www.energy.gov.au"

# Which Chrome version's TLS handshake to impersonate. Empirically verified
# against energy.gov.au's WAF (see scripts/scrape_australia_v0.py and the
# Phase 1 notebook). Bump if a Chrome release lands that the WAF rejects.
IMPERSONATE_PROFILE = "chrome131"

# An xlsx is a zip archive, so it always starts with the ZIP local-file
# header magic bytes. The authoritative check that we got an xlsx (server
# content-type headers can lie; magic bytes can't).
XLSX_MAGIC = b"PK\x03\x04"


# --------------------------------------------------------------------------- #
#  Parsing constants
# --------------------------------------------------------------------------- #

# Provenance markers stamped onto every parsed row. Keeping them as module
# constants makes the canonical schema visible at a glance and avoids
# magic strings sprinkled through parse().
COUNTRY_CODE = "AU"                       # ISO-3166 alpha-2
COUNTRY_NAME = "Australia"
SOURCE_ID = "dceew_petroleum_statistics"  # dataset id, also used in reference/*.yaml

# The 7 sheets we extract, mapped to JODI-aligned metric codes from
# reference/metric_types.yaml.
#
# Each value is a dict with:
#   "default"   : metric_type code applied to every column in the sheet
#   "overrides" : (optional) per-product-native overrides for columns that
#                 don't semantically match the sheet's default metric type.
#                 Keys are the product name AS IT APPEARS AFTER the unit
#                 is stripped (e.g. "Total input", not "Total input (ML)").
#
# Override examples:
#   - 'Refinery production' contains "Total input" (refinery intake, not
#     output) and "Percentage indigenous: Total input" (a ratio, not output).
#     Tagging them as REFGROUT would muddy any "sum all REFGROUT for diesel"
#     query.
#
# Sheets not listed here are deliberately ignored (price sheets, by-state
# breakdowns, value-not-volume sheets, index/copyright pages). Adding a new
# sheet = adding one entry below.
SHEETS_CONFIG: dict[str, dict] = {
    "Sales of products":         {"default": "TOTDEMO"},     # deliveries observed
    "Petroleum production":      {"default": "INDPROD"},     # upstream production
                                                              # (LNG exports column stays here:
                                                              # it's the volume of gas produced
                                                              # that's destined for LNG export,
                                                              # conceptually still production)
    "Refinery production":       {
        "default": "REFGROUT",                                # refinery gross output
        "overrides": {
            "Total input":                       "REFINOBS",            # refinery intake (input, not output)
            "Percentage indigenous: Total input": "X_REFINSHARE_INDIG",  # ratio, not volume
        },
    },
    "Imports volume":            {"default": "TOTIMPSB"},    # total imports
    "Exports volume":            {"default": "TOTEXPSB"},    # total exports
    "Stock volume by product":   {"default": "CLOSTLV"},     # closing stock level
    "Consumption cover":         {"default": "X_STKCOVER"},  # project-specific (days)
}

# Regex that splits a DCCEEW column header into (product, unit). DCCEEW
# always puts the unit in trailing parentheses, e.g. "Crude oil (ML)" or
# "LPG (days)". The unit may contain spaces ("Crude oil & condensate (ML)").
# Anchored with ^...$ so we never match a stray "(...)" mid-name.
_HEADER_PATTERN = re.compile(r"^(?P<product>.+?)\s*\((?P<unit>[^)]+)\)\s*$")

# Canonical column order for the tidy DataFrame returned by parse(). This is
# the contract every consumer (processors/, scripts/, notebooks/) depends on.
# Phase 4 retrofits India and JODI to produce DataFrames with these same
# columns; cross-country UNION ALL becomes trivial.
CANONICAL_COLUMNS: list[str] = [
    "date",            # 1st of month, datetime64[ns]
    "country",         # ISO-3166 alpha-2
    "country_name",    # human-readable
    "source",          # dataset id (matches reference/*.yaml keys)
    "metric_type",     # JODI-aligned code (TOTDEMO, INDPROD, ...)
    "product_native",  # source's exact label, minus unit suffix
    "product",         # canonical product code; identical to product_native
                       # until reference/products.yaml is populated (Phase 4)
    "value",           # numeric observation; NaN for n.a./n.p.
    "unit",            # extracted from source header ("ML", "Mm3", "days")
    "source_file",     # provenance: filename of the source xlsx
    "updated_at",      # when this row was parsed (not when DCCEEW published)
]


class AustraliaAPStatScraper(BaseScraper):
    """
    Scraper for the Australian Petroleum Statistics monthly publication
    (DCCEEW — Department of Climate Change, Energy, the Environment and Water).

    Usage:
        scraper = AustraliaAPStatScraper()
        scraper.datasets                              # ['petroleum_statistics']
        raw_path = scraper.download('petroleum_statistics')
        # raw_path is a pathlib.Path to the downloaded xlsx in
        # data/raw/australia/

        # Parsing is not yet implemented — Phase 2b will add it.
        # df = scraper.parse('petroleum_statistics', raw_path)  # NotImplementedError
    """

    def __init__(self, data_dir: str = "data"):
        super().__init__(country="australia", data_dir=data_dir)
        # No persistent session: curl_cffi calls are stateless. We don't
        # need cookies or connection pooling for a single monthly file —
        # adding a Session here would just hide the curl_cffi vs requests
        # API differences (curl_cffi has its own Session class with subtly
        # different semantics).

    # ------------------------------------------------------------------ #
    #  Download
    # ------------------------------------------------------------------ #

    def download(self, dataset_name: str, force: bool = False) -> Path:
        """
        Fetch the latest xlsx for the given dataset.

        Strategy:
            1. Discover the live publications-page URL (current year first,
               previous year as fallback — handles the early-January gap).
            2. Parse the page HTML for the first href matching ``url_pattern``
               from sources.yaml (defaults to ``.xlsx``).
            3. Short-circuit if a same-size local copy already exists,
               unless ``force=True``.
            4. Otherwise download via curl_cffi impersonation, verify the
               magic bytes, and save under the server's filename.

        Args:
            dataset_name: Must be one of ``self.datasets`` (currently just
                          ``"petroleum_statistics"``).
            force:        If True, re-download even if a local copy exists.

        Returns:
            Path to the local raw xlsx file.
        """
        ds_config = self.get_dataset_config(dataset_name)
        url_pattern = ds_config.get("url_pattern", ".xlsx")

        logger.info(f"[{self.country}] Downloading: {dataset_name}")

        # -- Step 1: discover the publications page --
        page_url, page_resp = self._find_publications_url(ds_config)
        logger.info(f"  Live page: {page_url}")

        # -- Step 2: find the xlsx link on the page --
        download_url, href = self._find_xlsx_link(
            page_resp.text, page_url, url_pattern
        )

        # -- Step 3: cache hit? --
        # ``Path(href).name`` strips the directory portion of the href
        # and gives us the server filename ("..._february_2026.xlsx"),
        # which already encodes the publication month. So a same-month
        # re-download lands on the same path and we can skip the wire call.
        out_path = self.raw_dir / Path(href).name
        if not force and out_path.exists() and out_path.stat().st_size > 1000:
            logger.info(
                f"  Cached: {out_path} ({out_path.stat().st_size:,} bytes). "
                f"Pass force=True to re-download."
            )
            return out_path

        # -- Step 4: download and verify --
        logger.info(f"  Fetching: {download_url}")
        r = requests.get(
            download_url, timeout=120, impersonate=IMPERSONATE_PROFILE
        )
        r.raise_for_status()
        body = r.content

        # Hard check: must be a zip archive. Catches the failure mode where
        # the server returns an HTML error/maintenance page but tags it with
        # a spreadsheet content-type.
        if not body.startswith(XLSX_MAGIC):
            content_type = r.headers.get("Content-Type", "<unset>")
            raise RuntimeError(
                f"Downloaded {len(body)} bytes from {download_url} but they "
                f"don't look like an xlsx.\n"
                f"  Content-Type : {content_type}\n"
                f"  First 16 bytes: {body[:16]!r}\n"
                f"Either the URL is wrong or the server returned an error page."
            )

        out_path.write_bytes(body)
        logger.info(f"  Saved: {out_path} ({len(body) / 1024:.0f} KB)")
        return out_path

    # ------------------------------------------------------------------ #
    #  Parse
    # ------------------------------------------------------------------ #

    def parse(self, dataset_name: str, raw_path: Path) -> pd.DataFrame:
        """
        Parse the Australian Petroleum Statistics xlsx into a tidy long-form
        DataFrame matching the project's canonical schema (see CANONICAL_COLUMNS).

        Strategy
        --------
        1. Open the xlsx once and reuse the handle across sheets (saves the
           ~150 ms upfront ZIP-extract cost on each `pd.read_excel` call).
        2. For each of the 7 sheets in SHEETS_CONFIG, call _parse_one_sheet()
           which does the wide-to-long melt and unit extraction.
        3. Concatenate the per-sheet long-form frames.
        4. Stamp every row with provenance columns (country, country_name,
           source, source_file, updated_at) and the canonical product column.
        5. Enforce CANONICAL_COLUMNS order and sort by (date, metric_type,
           product_native) for stable diffs across re-runs.

        The output is a tidy DataFrame: one row per (date, metric_type,
        product_native) observation. Cross-country UNION ALL will work once
        the other scrapers are retrofitted to this schema in Phase 4.

        Args:
            dataset_name: Must be ``"petroleum_statistics"`` (the only
                          dataset configured for Australia today).
            raw_path:     Path to the local xlsx produced by ``download()``.

        Returns:
            DataFrame with CANONICAL_COLUMNS, ~22k rows for a recent vintage
            (188 months × ~17 products × 7 metric types — exact count
            depends on how many products each sheet has).
        """
        # Validate the dataset name. Raises ValueError with a helpful list
        # of valid options if the caller passes a typo.
        self.get_dataset_config(dataset_name)

        logger.info(f"[{self.country}] Parsing: {raw_path.name}")

        # Opening pd.ExcelFile once and passing the handle to each read_excel
        # call is materially faster than re-opening the workbook per sheet
        # (the file is a ZIP archive; openpyxl has to re-scan it otherwise).
        xls = pd.ExcelFile(raw_path)

        frames: list[pd.DataFrame] = []
        for sheet_name, sheet_config in SHEETS_CONFIG.items():
            if sheet_name not in xls.sheet_names:
                # DCCEEW occasionally renames sheets between vintages. Don't
                # crash the whole parse for one missing sheet — warn loudly
                # and continue. The user/dashboard will notice a gap in the
                # data and can investigate.
                logger.warning(
                    f"  Sheet not found: {sheet_name!r} "
                    f"(expected default metric_type={sheet_config['default']}). "
                    f"Skipping. Available sheets: {xls.sheet_names}"
                )
                continue
            default = sheet_config["default"]
            overrides = sheet_config.get("overrides", {})
            override_note = (
                f" + {len(overrides)} column override(s)" if overrides else ""
            )
            logger.info(
                f"  Parsing sheet: {sheet_name!r} → {default}{override_note}"
            )
            df = self._parse_one_sheet(xls, sheet_name, sheet_config)
            frames.append(df)

        if not frames:
            raise RuntimeError(
                f"No target sheets were found in {raw_path.name}. "
                f"Expected at least one of: {list(SHEETS_CONFIG)}"
            )

        tidy = pd.concat(frames, ignore_index=True)

        # Stamp provenance + country columns on every row. These are constant
        # for this scraper, so we add them once after the concat (cheaper than
        # adding them inside the per-sheet loop).
        tidy["country"] = COUNTRY_CODE
        tidy["country_name"] = COUNTRY_NAME
        tidy["source"] = SOURCE_ID
        tidy["source_file"] = raw_path.name
        tidy["updated_at"] = pd.Timestamp.now()

        # Canonical `product` column is identical to `product_native` for now.
        # Phase 4 will populate it via reference/products.yaml lookups (e.g.
        # mapping "Diesel oil: total" → "GASOIL_DIESEL"). We keep both columns
        # so that downstream code can already filter on the canonical name
        # once mappings exist, with zero schema migration.
        tidy["product"] = tidy["product_native"]

        # Enforce column order + sort. Stable order means file diffs across
        # re-runs only show actual data changes, not row-shuffling noise.
        tidy = tidy[CANONICAL_COLUMNS].copy()
        tidy = tidy.sort_values(
            ["date", "metric_type", "product_native"], ignore_index=True
        )

        logger.info(
            f"  Tidy DataFrame: {len(tidy):,} rows, "
            f"{tidy['date'].min().strftime('%Y-%m')} → "
            f"{tidy['date'].max().strftime('%Y-%m')}, "
            f"{tidy['metric_type'].nunique()} metric types, "
            f"{tidy['product_native'].nunique()} distinct products"
        )
        return tidy

    @staticmethod
    def _parse_one_sheet(
        xls: pd.ExcelFile,
        sheet_name: str,
        sheet_config: dict,
    ) -> pd.DataFrame:
        """
        Read one DCCEEW sheet and return a long-form DataFrame with columns:
        ``date, product_native, value, unit, metric_type``.

        DCCEEW sheet layout (verified for all 7 target sheets):
            Row 0          - header row. Column 0 = "Month", columns 1+ are
                             product names with units in parentheses
                             (e.g. "Crude oil (ML)", "LPG (days)").
            Rows 1+        - data. Column 0 = first-of-month datetime (pandas
                             parses it automatically). Columns 1+ are numeric
                             values; "n.a." (not available) and "n.p." (not
                             published / suppressed) appear as text and both
                             become NaN after pd.to_numeric coercion.

        sheet_config has shape:
            {"default": "REFGROUT", "overrides": {"Total input": "REFINOBS", ...}}
        Every row gets ``metric_type = sheet_config["default"]`` unless its
        product_native appears in overrides, in which case the override wins.

        Why @staticmethod
            This function depends only on its arguments — no self-state.
            Marking it @staticmethod documents that, and makes it trivially
            unit-testable without instantiating the scraper.

        Why wide-to-long (melt)
            DCCEEW publishes wide-format spreadsheets because they're easier
            for humans to scan. Long format is easier for everything else:
            filtering ("show me all rows where product=Diesel"), joining
            across countries, storing in a relational/columnar database, and
            plotting (most chart libraries expect long input). The melt step
            converts (months × products) wide matrices into one row per
            (month, product) pair.
        """
        # header=0 makes row 0 the column headers and rows 1+ the data.
        wide = pd.read_excel(xls, sheet_name=sheet_name, header=0)

        # First column is the month axis. Renaming it explicitly so the melt
        # below treats it as the identifier (id_vars), not as a value column.
        # Using positional indexing (.columns[0]) rather than the literal
        # string "Month" makes us robust to a future DCCEEW header rename.
        date_col = wide.columns[0]
        wide = wide.rename(columns={date_col: "date"})

        # Wide → long. Every column except "date" becomes one row per (date,
        # column) pair. `var_name` and `value_name` give the new long-form
        # columns their names; defaults would be "variable" and "value".
        long = wide.melt(
            id_vars="date",
            var_name="header_label",   # e.g. "Crude oil (ML)"
            value_name="value_raw",    # may be float, "n.a.", or "n.p."
        )

        # Split the header label into (product_native, unit). The regex is
        # anchored at both ends to prevent matching a stray "(...)" inside
        # a product name (none observed today, but cheap insurance).
        extracted = long["header_label"].str.extract(_HEADER_PATTERN)
        # If the regex doesn't match (e.g. a column header without parens),
        # fall back to the original label and leave unit blank rather than
        # dropping the row — better to have a missing unit than missing data.
        long["product_native"] = extracted["product"].fillna(long["header_label"])
        long["unit"] = extracted["unit"]

        # pd.to_numeric with errors="coerce" turns any non-numeric value into
        # NaN. This is how both "n.a." and "n.p." get coerced. It also
        # silently handles any future typo in the source (e.g. an Excel cell
        # that contains a stray space) without crashing the parse.
        long["value"] = pd.to_numeric(long["value_raw"], errors="coerce")

        # Apply metric_type: start with the sheet's default, then overwrite
        # for any product_natives listed in overrides. Doing the assignment
        # in two steps (rather than .map() with a default) means the override
        # dict only needs to contain the EXCEPTIONS — small and readable.
        default_metric = sheet_config["default"]
        overrides = sheet_config.get("overrides", {})
        long["metric_type"] = default_metric
        for product_native, override_metric in overrides.items():
            mask = long["product_native"] == product_native
            if not mask.any():
                # The override targets a column that doesn't exist in this
                # sheet vintage. Warn loudly because it means our config has
                # drifted from the source — silent skipping would hide bugs.
                logger.warning(
                    f"  Override for product_native={product_native!r} → "
                    f"{override_metric}: no matching column in sheet "
                    f"{sheet_name!r}. Did DCCEEW rename the column?"
                )
                continue
            long.loc[mask, "metric_type"] = override_metric

        # Return only the columns we need. Helper columns (header_label,
        # value_raw) are intermediate scratch — dropping them keeps the
        # concatenated DataFrame in parse() lean.
        return long[["date", "product_native", "value", "unit", "metric_type"]]

    # ------------------------------------------------------------------ #
    #  Helpers
    # ------------------------------------------------------------------ #

    def _find_publications_url(
        self,
        ds_config: dict,
        today: Optional[datetime] = None,
    ) -> tuple[str, "requests.Response"]:
        """
        Discover the working publications-page URL by trying this calendar
        year first and falling back to the previous year.

        Returns ``(url, response)`` so the caller doesn't have to re-fetch.
        Raises RuntimeError listing what was tried if neither year returns 200.

        Why "current then previous": the publication is monthly. The only
        edge case where the current year's page doesn't exist yet is the
        Jan-1 transition (e.g. early Jan 2027 before DCCEEW launches the
        ``-2027`` page). Two candidates cover that; walking further back
        would be YAGNI.

        ``today`` is a parameter (default ``datetime.now()``) so this is
        testable in isolation::

            scraper._find_publications_url(cfg, today=datetime(2027, 1, 15))
        """
        today = today or datetime.now()
        template = ds_config["page_url_template"]
        candidates = [today.year, today.year - 1]
        last_error = None
        for year in candidates:
            url = template.format(year=year)
            logger.info(f"  Trying year={year}: {url}")
            try:
                resp = requests.get(
                    url, timeout=30, impersonate=IMPERSONATE_PROFILE
                )
                if resp.ok:
                    return url, resp
                last_error = f"HTTP {resp.status_code}"
                logger.info(f"  → {last_error}, trying next year")
            except Exception as e:
                last_error = f"{type(e).__name__}: {e}"
                logger.warning(f"  → FAILED ({last_error}), trying next year")
        raise RuntimeError(
            f"No working publications URL found for {self.country}.\n"
            f"  Tried years: {candidates}\n"
            f"  Last error : {last_error}"
        )

    @staticmethod
    def _find_xlsx_link(
        page_html: str,
        page_url: str,
        url_pattern: str = ".xlsx",
    ) -> tuple[str, str]:
        """
        Return ``(absolute_url, href)`` for the first link on the page
        whose href ends with ``url_pattern`` (case-insensitively).

        The DCCEEW publications page lists the newest monthly extract
        first under "Attachments". Older yearly publications appear lower
        on the page but link to OTHER publication pages (not xlsx files),
        so they never end up in this filter — the first xlsx href is
        always the latest month.
        """
        soup = BeautifulSoup(page_html, "lxml")
        pattern_lower = url_pattern.lower()
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            if href.lower().endswith(pattern_lower):
                absolute = href if href.startswith("http") else BASE_URL + href
                return absolute, href
        raise RuntimeError(
            f"No links ending in {url_pattern!r} found on {page_url}. "
            f"Page layout may have changed — open the URL in a browser and "
            f"update the scraping strategy."
        )
