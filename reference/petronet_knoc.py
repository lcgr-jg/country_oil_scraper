"""
Petronet (KNOC) 제품별소비 download helpers.

The v4 site loads statistics via POST to ``/v4/sub.jsp`` (menu + date range).
Table data can also be fetched as HTML from ``/v4/excel/KDCQ0200_x.jsp`` (despite
the name, the response is an HTML table, not XLSX). We parse that table into the
same wide CSV layout as manual exports.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from io import StringIO
from typing import Iterable, Literal, Optional

import pandas as pd
import requests
from bs4 import BeautifulSoup

PETRONET_BASE = "https://www.petronet.co.kr"
SUB_URL = f"{PETRONET_BASE}/v4/sub.jsp"

# Menu ids for 제품별소비 (product-by-product domestic consumption).
CONSUMPTION_MENU_IDS = {
    "fmuId": "KDDQSTAT",
    "smuId": "KDCQ01",
    "tmuId": "KDCQ0200",
    "fmuOrd": "04",
    "smuOrd": "04_04",
    "tmuOrd": "04_04_01",
    "progId": "KDCQ0200",
}

# 석유제품재고 — petroleum product closing stocks (same product columns).
STOCKS_MENU_IDS = {
    "fmuId": "KDDQSTAT",
    "smuId": "KDPQ02",
    "tmuId": "KDSQ0200",
    "fmuOrd": "04",
    "smuOrd": "04_03",
    "tmuOrd": "04_03_04",
    "progId": "KDSQ0200",
}

MENU_IDS = CONSUMPTION_MENU_IDS  # backward compat

CONSUMPTION_EXCEL_URL = f"{PETRONET_BASE}/v4/excel/KDCQ0200_x.jsp"
STOCKS_EXCEL_URL = f"{PETRONET_BASE}/v4/excel/KDSQ0200_x.jsp"
EXCEL_URL = CONSUMPTION_EXCEL_URL  # backward compat

PROD_CD_LIST = (
    "B000,C000,D000,E000,F000,G000,H000,J000,L000,N000,I000,M000,K000,O000,S000"
)
PROD_CODES: tuple[str, ...] = tuple(PROD_CD_LIST.split(","))

# Stocks page checkboxes use two-char codes (B0), not B000.
STOCKS_PROD_CD_LIST = "B0,C0,D0,E0,F0,G0,H0,I0,J0,K0,L0,M0,N0,O0,S0"
STOCKS_PROD_CODES: tuple[str, ...] = tuple(STOCKS_PROD_CD_LIST.split(","))

TableLayout = Literal["consumption", "stocks"]

# Petronet table header (Korean) -> English CSV column (2019+ manual export style).
KO_HEADER_TO_EN: dict[str, str] = {
    "휘발유": "gasoline",
    "등유": "kerosene",
    "경유": "Via",
    "경질중유": "Hard Heavy Oil",
    "중유": "Heavy oil",
    "벙커C유": "Bunker C Oil",
    "납사": "naphtha",
    "용제": "solvent",
    "항공유": "jet fuel",
    "LPG": "LPG",
    "아스팔트": "asphalt",
    "윤활유": "lubricant",
    "기타제품": "Other Products",
    "부생연료유": "by-product fuel oil",
    "바이오연료": "biofuel",
    "합 계": "Total",
    "합계": "Total",
}

MAX_MONTH_SPAN_DAYS = 1827  # Petronet UI limit (~5 years)
STOCKS_MAX_MONTH_SPAN_DAYS = 730  # Stocks UI limit (~2 years)


@dataclass(frozen=True)
class PetronetDatasetConfig:
    """Petronet menu + form parameters for one KNOC statistic family."""

    name: str
    menu_ids: dict[str, str]
    excel_url: str
    prod_codes: tuple[str, ...]
    table_layout: TableLayout
    bootstrap_max_years: int
    initial_load_file_c: str = ""


CONSUMPTION_PETRONET = PetronetDatasetConfig(
    name="consumption",
    menu_ids=CONSUMPTION_MENU_IDS,
    excel_url=CONSUMPTION_EXCEL_URL,
    prod_codes=PROD_CODES,
    table_layout="consumption",
    bootstrap_max_years=5,
)

STOCKS_PETRONET = PetronetDatasetConfig(
    name="stocks",
    menu_ids=STOCKS_MENU_IDS,
    excel_url=STOCKS_EXCEL_URL,
    prod_codes=STOCKS_PROD_CODES,
    table_layout="stocks",
    bootstrap_max_years=2,
    initial_load_file_c="제품제고(제품별)(intruser1)",
)

PETRONET_CONFIG_BY_NAME: dict[str, PetronetDatasetConfig] = {
    "consumption": CONSUMPTION_PETRONET,
    "stocks": STOCKS_PETRONET,
}


def petronet_config_for(name: str) -> PetronetDatasetConfig:
    try:
        return PETRONET_CONFIG_BY_NAME[name]
    except KeyError as exc:
        raise ValueError(f"Unknown Petronet dataset {name!r}") from exc


@dataclass(frozen=True)
class DateRange:
    start: date  # inclusive, first day of month
    end: date  # inclusive, first day of month

    @property
    def filename_suffix(self) -> str:
        return f"{self.start:%Y%m}-{self.end:%Y%m}"

    def to_form_parts(self) -> dict[str, str]:
        return {
            "by": f"{self.start.year}",
            "bm": f"{self.start.month:02d}",
            "bq": "1",
            "ay": f"{self.end.year}",
            "am": f"{self.end.month:02d}",
            "aq": "1",
        }


def default_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
            "Referer": f"{PETRONET_BASE}/v4/main.jsp",
        }
    )
    return s


def open_menu(
    session: requests.Session,
    *,
    menu_ids: Optional[dict[str, str]] = None,
) -> None:
    """Prime session cookies by loading the stat menu shell."""
    session.post(SUB_URL, data=menu_ids or MENU_IDS, timeout=60)


def _build_parameters(
    from_yyyymm: str,
    to_yyyymm: str,
    prod_codes: tuple[str, ...],
) -> tuple[str, str]:
    pcd = "\\,'".join(prod_codes)
    parameter_c = (
        f"::Bus='1',::FD='{from_yyyymm}',::TD='{to_yyyymm}',::PCD='{pcd}',"
        f":Busisec='1',:FromDate='{from_yyyymm}',:ToDate='{to_yyyymm}'"
    )
    prod_cd = "".join(f",:ProdCD='\\'{c}\\'" for c in prod_codes) + " '"
    parameter = f":Busisec='1',:FromDate='{from_yyyymm}',:ToDate='{to_yyyymm}'" + prod_cd
    return parameter, parameter_c


def fetch_table_html(
    session: requests.Session,
    dr: DateRange,
    *,
    config: Optional[PetronetDatasetConfig] = None,
    menu_ids: Optional[dict[str, str]] = None,
    excel_url: Optional[str] = None,
) -> str:
    """
    Fetch Petronet wide-table HTML for a monthly date range.

    Uses the excel JSP endpoint (HTML table). Falls back to POST search if needed.
    """
    config = config or CONSUMPTION_PETRONET
    menu_ids = menu_ids or config.menu_ids
    excel_url = excel_url or config.excel_url
    prod_cd_list = ",".join(config.prod_codes)
    parts = dr.to_form_parts()
    from_yyyymm = f"{parts['by']}{parts['bm']}"
    to_yyyymm = f"{parts['ay']}{parts['am']}"

    url = (
        f"{excel_url}?term=m"
        f"&by={parts['by']}&bq={parts['bq']}&bm={parts['bm']}"
        f"&ay={parts['ay']}&aq={parts['aq']}&am={parts['am']}"
        f"&ProdCDList={prod_cd_list}"
    )
    r = session.get(url, timeout=120)
    r.raise_for_status()
    if "csvExportTable0" not in r.text:
        r = _post_search(
            session,
            from_yyyymm,
            to_yyyymm,
            parts,
            config=config,
            menu_ids=menu_ids,
        )
        r.raise_for_status()
    return r.text


def _post_search(
    session: requests.Session,
    from_yyyymm: str,
    to_yyyymm: str,
    parts: dict[str, str],
    *,
    config: Optional[PetronetDatasetConfig] = None,
    menu_ids: Optional[dict[str, str]] = None,
) -> requests.Response:
    config = config or CONSUMPTION_PETRONET
    menu_ids = menu_ids or config.menu_ids
    parameter, parameter_c = _build_parameters(from_yyyymm, to_yyyymm, config.prod_codes)
    prod_cd_list = ",".join(config.prod_codes)
    data: list[tuple[str, str]] = [
        *menu_ids.items(),
        ("term", "m"),
        *parts.items(),
        ("Parameter", parameter),
        ("ParameterC", parameter_c),
        ("ProdCDList", prod_cd_list),
        ("InitialLoadFile", ""),
    ]
    if config.initial_load_file_c:
        data.append(("InitialLoadFileC", config.initial_load_file_c))
    for code in config.prod_codes:
        data.append(("ProdCd", code))
    return session.post(SUB_URL, data=data, timeout=120)


def _clean_cell(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ").strip())


def _extract_product_headers(table) -> list[str]:
    headers: list[str] = []
    for th in table.find("thead").find_all("th"):
        label = _clean_cell(th.get_text())
        if label in ("월", "제품명"):
            continue
        headers.append(label)
    if not headers:
        raise ValueError("No product headers in Petronet table")
    return headers


def html_table_to_wide_csv(
    html: str,
    *,
    layout: TableLayout = "consumption",
) -> str:
    """Convert Petronet HTML table to wide CSV text (UTF-8)."""
    if layout == "stocks":
        return _html_table_to_stocks_csv(html)
    return _html_table_to_consumption_csv(html)


def _html_table_to_consumption_csv(html: str) -> str:
    """Consumption table: English headers, volume + share rows per month."""
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", id="csvExportTable0")
    if table is None:
        raise ValueError("csvExportTable0 not found in Petronet response")

    ko_headers = _extract_product_headers(table)
    en_headers = [KO_HEADER_TO_EN.get(h, h) for h in ko_headers]

    rows_out: list[list[str]] = []
    rows_out.append(["Month", "Product Name", *en_headers])

    tbody_rows = table.find("tbody").find_all("tr")
    i = 0
    while i < len(tbody_rows):
        vol_tr = tbody_rows[i]
        i += 1
        if i >= len(tbody_rows):
            break
        share_tr = tbody_rows[i]
        i += 1

        month_td = vol_tr.find("td", class_="title_td") or vol_tr.find("td")
        if month_td is None:
            continue
        month_text = _clean_cell(month_td.get_text())
        rows_out.append([month_text, "", *_row_values(vol_tr, len(ko_headers))])
        rows_out.append(
            ["", "", *_row_values(share_tr, len(ko_headers), shares=True)]
        )

    return _rows_to_csv(rows_out)


def _html_table_to_stocks_csv(html: str) -> str:
    """Stocks table: Korean headers, one level row per month (matches manual export)."""
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", id="csvExportTable0")
    if table is None:
        raise ValueError("csvExportTable0 not found in Petronet response")

    ko_headers = _extract_product_headers(table)
    rows_out: list[list[str]] = [["월", "제품명", *ko_headers]]

    for tr in table.find("tbody").find_all("tr"):
        classes = tr.get("class") or []
        if "result_td" in classes:
            continue
        month_td = tr.find("td", class_="title_td") or tr.find("td")
        if month_td is None:
            continue
        month_text = _clean_cell(month_td.get_text())
        if month_text in ("평균", "합계", "합 계"):
            continue
        rows_out.append([month_text, "", *_row_values(tr, len(ko_headers))])

    return _rows_to_csv(rows_out)


def _rows_to_csv(rows_out: list[list[str]]) -> str:
    buf = StringIO()
    for row in rows_out:
        buf.write(",".join(_csv_escape(c) for c in row))
        buf.write("\n")
    return buf.getvalue()


def _row_values(tr, n_products: int, *, shares: bool = False) -> list[str]:
    tds = [td for td in tr.find_all("td") if "title_td" not in (td.get("class") or [])]
    vals: list[str] = []
    for td in tds[:n_products]:
        text = _clean_cell(td.get_text()).replace(",", "")
        if shares:
            if text in ("-", "- ", ""):
                text = "-"
            elif text.startswith("(") and text.endswith(")"):
                text = f"[{text[1:-1]}]"
        vals.append(text)
    while len(vals) < n_products:
        vals.append("")
    return vals[:n_products]


def _csv_escape(value: str) -> str:
    if "," in value or '"' in value or "\n" in value:
        return '"' + value.replace('"', '""') + '"'
    return value


def csv_filename(dr: DateRange, *, bundle_prefix: str = "제품별소비") -> str:
    return f"{bundle_prefix}({dr.filename_suffix}).csv"


def _add_months(d: date, months: int) -> date:
    y, m = d.year, d.month + months
    while m > 12:
        y += 1
        m -= 12
    while m <= 0:
        y -= 1
        m += 12
    return date(y, m, 1)


def iter_bootstrap_ranges(
    earliest: date,
    latest: date,
    *,
    max_years: int = 5,
) -> Iterable[DateRange]:
    """Yield ~5-year windows covering [earliest, latest] (Petronet limit)."""
    cur_start = earliest.replace(day=1)
    end = latest.replace(day=1)
    span_months = max_years * 12 - 1
    while cur_start <= end:
        chunk_end = _add_months(cur_start, span_months)
        if chunk_end > end:
            chunk_end = end
        yield DateRange(cur_start, chunk_end)
        if chunk_end >= end:
            break
        cur_start = _add_months(chunk_end, 1)


def rolling_refresh_range(
    latest: date,
    *,
    lookback_months: int = 24,
) -> DateRange:
    """Default incremental window: last N months through ``latest``."""
    end = latest.replace(day=1)
    y, m = end.year, end.month - (lookback_months - 1)
    while m <= 0:
        y -= 1
        m += 12
    start = date(y, m, 1)
    return DateRange(start, end)
