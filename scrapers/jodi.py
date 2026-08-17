"""
Scraper for the JODI-Oil World Database (annual CSV downloads).

Handles two datasets sharing the same on-disk structure and source page:
  - "secondary" — refined products (LPG, gasoline, diesel, jet, fuel oil…)
  - "primary"   — crude oil and NGLs

Each call to ``download(dataset, year=...)`` retrieves a single annual CSV
from JODI. The historical years use the URL pattern
``.../annual-csv/<dataset>/<YYYY>.csv``; the current year uses the pattern
``.../annual-csv/<dataset>/<dataset>year<YYYY>.csv`` (because that file is
year-to-date and gets refreshed monthly).

Parsing produces a tidy DataFrame ready to be unioned across years by
``processors.jodi``. We deliberately keep parsing per-file (no implicit
multi-year glob here) so callers can stream years in and out of memory.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

from .base import BaseScraper

logger = logging.getLogger(__name__)


# JODI publishes both color codes and special string sentinels in OBS_VALUE.
# We translate them here so the rest of the pipeline can reason about them
# symbolically instead of hard-coding magic strings.
_ASSESSMENT_LABELS = {
    1: "blue",      # final value
    2: "yellow",    # estimate
    3: "white",     # missing / not reported
}

# Mapping for the special string sentinels that JODI uses inside OBS_VALUE.
# Anything not in this dict will be interpreted as a numeric value (or NaN
# if the cast fails — captured as 'invalid' downstream).
# Verified against 2002-2026 secondary CSVs: only '-', '..', 'N/A', 'x'
# appear in the wild. We treat '..' (IEA-style "not available") as
# semantically equivalent to '-'.
_VALUE_STATUS = {
    "-":   "not_reported",     # blank cell — country didn't submit
    "..":  "not_reported",     # JODI/IEA "not available" sentinel
    "x":   "not_applicable",   # column not relevant for this product/flow
    "N/A": "na",               # data unavailable (legacy, mostly pre-2010)
    "n/a": "na",
    "NA":  "na",
    "":    "not_reported",
}

_SUPPORTED_DATASETS = ("secondary", "primary")

# Current-year YTD files are replaced in place on JODI's server each month.
# We HEAD the URL and compare Content-Length / Last-Modified to the local copy
# so routine runs pick up new months without requiring --force.
_MIN_CSV_BYTES = 1000


def _remote_file_metadata(url: str) -> tuple[Optional[int], Optional[datetime]]:
    """Return (content_length, last_modified) from a HEAD request, or (None, None)."""
    try:
        resp = requests.head(url, timeout=60, allow_redirects=True)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning(f"  HEAD failed for {url}: {exc}")
        return None, None

    content_length: Optional[int] = None
    raw_len = resp.headers.get("Content-Length")
    if raw_len and raw_len.isdigit():
        content_length = int(raw_len)

    last_modified: Optional[datetime] = None
    raw_lm = resp.headers.get("Last-Modified")
    if raw_lm:
        try:
            last_modified = parsedate_to_datetime(raw_lm)
            # Normalise to naive local time for comparison with os mtime.
            if last_modified.tzinfo is not None:
                last_modified = last_modified.astimezone().replace(tzinfo=None)
        except (TypeError, ValueError):
            logger.warning(f"  Unparseable Last-Modified header: {raw_lm!r}")

    return content_length, last_modified


def _current_year_cache_is_fresh(url: str, out_path: Path) -> bool:
    """
    True when the on-disk YTD file matches what JODI is serving (skip download).

    Compares remote Content-Length and Last-Modified against the local file.
    If HEAD fails or headers are missing, we keep the cache to avoid blocking
    daily runs on transient network issues.
    """
    remote_len, remote_lm = _remote_file_metadata(url)
    local_stat = out_path.stat()
    local_len = local_stat.st_size
    local_mtime = datetime.fromtimestamp(local_stat.st_mtime)

    if remote_len is not None and remote_len != local_len:
        logger.info(
            f"  Remote size changed ({local_len:,} -> {remote_len:,} bytes); "
            f"will re-download."
        )
        return False

    if remote_lm is not None and remote_lm > local_mtime:
        logger.info(
            f"  Remote newer (server {remote_lm:%Y-%m-%d %H:%M} > "
            f"local {local_mtime:%Y-%m-%d %H:%M}); will re-download."
        )
        return False

    if remote_len is None and remote_lm is None:
        logger.warning(
            f"  Could not verify remote freshness for {out_path.name}; "
            f"using cached copy."
        )
        return True

    logger.info(
        f"  Up to date: {out_path.name} ({local_len:,} bytes, matches remote)"
    )
    return True


class JodiScraper(BaseScraper):
    """
    Country code is a misnomer here — we register JODI as ``country='jodi'``
    so the BaseScraper directory layout (``data/raw/jodi/``) and the
    ``sources.yaml`` lookup both Just Work.
    """

    def __init__(self, data_dir: str = "data"):
        super().__init__(country="jodi", data_dir=data_dir)

    # ------------------------------------------------------------------ #
    # Download
    # ------------------------------------------------------------------ #

    def download(
        self,
        dataset_name: str,
        year: Optional[int] = None,
        force: bool = False,
    ) -> Path:
        """
        Download a single annual JODI CSV.

        Args:
            dataset_name: 'secondary' or 'primary'.
            year:         Calendar year to fetch. Defaults to the current
                          year, which downloads the latest year-to-date file.
            force:        If True, always re-download. For the current calendar
                          year, a HEAD check against JODI compares remote size /
                          Last-Modified to the local file so monthly YTD
                          refreshes are picked up without --force. Historical
                          years still use a simple on-disk cache.

        Returns:
            Path to the downloaded CSV.
        """
        self._validate_dataset(dataset_name)
        ds_cfg = self.get_dataset_config(dataset_name)

        if year is None:
            year = datetime.now().year

        # The current-year file is YTD and lives behind a different URL
        # pattern than the closed historical years.
        is_current_year = year == datetime.now().year
        pattern_key = (
            "current_year_url_pattern" if is_current_year else "historical_url_pattern"
        )
        url = ds_cfg[pattern_key].format(year=year)

        # Layout: data/raw/jodi/<dataset>/<YYYY>.csv
        # We mirror the naming scheme the user already had for "secondary_jodi"
        # but use a cleaner subfolder name going forward.
        out_dir = self.raw_dir / dataset_name
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{year}.csv"

        if (
            not force
            and out_path.exists()
            and out_path.stat().st_size > _MIN_CSV_BYTES
        ):
            if is_current_year:
                if _current_year_cache_is_fresh(url, out_path):
                    return out_path
            else:
                logger.info(f"  Cached: {out_path} ({out_path.stat().st_size:,} bytes)")
                return out_path

        logger.info(f"  Downloading: {url}")
        # JODI serves the CSV as application/octet-stream; we stream to disk
        # to avoid pulling 25-30 MB into memory unnecessarily.
        with requests.get(url, stream=True, timeout=120) as r:
            r.raise_for_status()
            with open(out_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        f.write(chunk)

        size = out_path.stat().st_size
        logger.info(f"  Saved: {out_path} ({size:,} bytes)")
        if size < _MIN_CSV_BYTES:
            # Defensive: JODI returns a tiny HTML 404 page on bad URLs.
            raise RuntimeError(
                f"Downloaded file is suspiciously small ({size} bytes). "
                f"URL may be wrong: {url}"
            )
        return out_path

    # ------------------------------------------------------------------ #
    # Parse
    # ------------------------------------------------------------------ #

    def parse(self, dataset_name: str, raw_path: Path) -> pd.DataFrame:
        """
        Parse a single JODI annual CSV into a tidy DataFrame.

        The output schema:
            date              (datetime64[ns], 1st of month)
            year              (int16)
            month             (int8)
            ref_area          (category, ISO alpha-2 country / aggregate code)
            energy_product    (category, JODI product code)
            flow_breakdown    (category, JODI flow code)
            unit_measure      (category, e.g. KBBL, KBD, KTONS, KL, CONVBBL)
            obs_value         (float64, NaN for any non-numeric cell)
            value_status      (category: 'valid', 'not_reported',
                              'not_applicable', 'na', 'invalid')
            assessment_code   (Int8, 1/2/3)
            assessment_label  (category, blue/yellow/white)
            dataset           (category, 'primary' or 'secondary')
            source_file       (str, original filename)
            updated_at        (datetime64[ns])
        """
        self._validate_dataset(dataset_name)
        raw_path = Path(raw_path)

        logger.info(f"  Parsing: {raw_path.name}")
        # JODI CSVs are well-formed UTF-8 with a header row. We read OBS_VALUE
        # as string up-front so we can classify the special sentinels before
        # coercing to float.
        df = pd.read_csv(
            raw_path,
            dtype={
                "REF_AREA": "string",
                "TIME_PERIOD": "string",
                "ENERGY_PRODUCT": "string",
                "FLOW_BREAKDOWN": "string",
                "UNIT_MEASURE": "string",
                "OBS_VALUE": "string",
                "ASSESSMENT_CODE": "Int8",
            },
            keep_default_na=False,        # JODI uses literal '-', 'x', 'N/A'
            na_values=[],                 # don't auto-NA — we classify ourselves
        )

        # --- Column normalisation ------------------------------------- #
        df.columns = [c.lower() for c in df.columns]

        # --- Date ---------------------------------------------------- #
        # time_period is 'YYYY-MM'. We anchor everything to the 1st of the
        # month so cross-country joins are trivial.
        df["date"] = pd.to_datetime(df["time_period"] + "-01", errors="coerce")
        bad_dates = df["date"].isna().sum()
        if bad_dates:
            logger.warning(f"    {bad_dates} rows had unparseable time_period")
        df["year"] = df["date"].dt.year.astype("Int16")
        df["month"] = df["date"].dt.month.astype("Int8")

        # --- value_status + obs_value -------------------------------- #
        # We strip & normalise once, then classify before numeric coercion.
        raw_val = df["obs_value"].fillna("").str.strip()
        df["value_status"] = raw_val.map(_VALUE_STATUS).fillna("valid")
        # Coerce to float; non-numeric strings (sentinels and stray garbage)
        # become NaN. We then promote 'valid' → 'invalid' for any row whose
        # numeric cast failed despite not matching a known sentinel.
        df["obs_value"] = pd.to_numeric(raw_val, errors="coerce")
        invalid_mask = (df["value_status"] == "valid") & df["obs_value"].isna()
        df.loc[invalid_mask, "value_status"] = "invalid"

        # --- assessment_label ---------------------------------------- #
        df["assessment_label"] = df["assessment_code"].map(_ASSESSMENT_LABELS)

        # --- Provenance ---------------------------------------------- #
        df["dataset"] = dataset_name
        df["source_file"] = raw_path.name
        df["updated_at"] = pd.Timestamp.now()

        # --- Final column order + dtypes ----------------------------- #
        # Categorical conversion is deferred to processors.jodi because
        # categories must be merged across years before being frozen.
        out_cols = [
            "date", "year", "month",
            "ref_area", "energy_product", "flow_breakdown", "unit_measure",
            "obs_value", "value_status",
            "assessment_code", "assessment_label",
            "dataset", "source_file", "updated_at",
        ]
        df = df[out_cols]

        logger.info(
            f"    Parsed {len(df):,} rows | months={df['date'].nunique()} "
            f"| countries={df['ref_area'].nunique()}"
        )
        return df

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _validate_dataset(self, dataset_name: str) -> None:
        if dataset_name not in _SUPPORTED_DATASETS:
            raise ValueError(
                f"Unknown JODI dataset '{dataset_name}'. "
                f"Supported: {_SUPPORTED_DATASETS}"
            )

    @staticmethod
    def latest_published_year() -> int:
        """Convenience helper — JODI's 'latest' file is always the current year."""
        return date.today().year

    def download_history(
        self,
        dataset_name: str,
        start_year: int = 2002,
        end_year: Optional[int] = None,
        force: bool = False,
    ) -> list[Path]:
        """
        Download every annual CSV in [start_year, end_year] for the dataset.

        Used to bootstrap a fresh dataset (e.g. JODI primary, when only the
        current YTD file is present locally). Files already on disk with a
        non-trivial size are skipped unless ``force=True``.

        Returns a list of all paths now on disk (downloaded or cached).
        """
        if end_year is None:
            end_year = self.latest_published_year()
        if start_year > end_year:
            raise ValueError(f"start_year {start_year} > end_year {end_year}")

        paths: list[Path] = []
        for year in range(start_year, end_year + 1):
            try:
                paths.append(self.download(dataset_name, year=year, force=force))
            except Exception as exc:
                # We don't abort the whole sweep on a single bad year; log
                # and continue so partial downloads still leave the DB
                # rebuildable from whatever did succeed.
                logger.warning(f"  download {dataset_name} {year} failed: {exc}")
        return paths
