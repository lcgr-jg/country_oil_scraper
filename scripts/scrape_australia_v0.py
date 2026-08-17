"""
scrape_australia_v0.py
──────────────────────
Phase 1 (learning version): download the latest Australian Petroleum Statistics
Excel file from the energy.gov.au publications page.

This is the flat, line-by-line learning version. The matching notebook is at
notebooks/06_australia_v0_scrape.ipynb. In Phase 2 we'll turn this into a
reusable ``AustraliaAPStatScraper`` class that plugs into the existing
``scrapers.base.BaseScraper`` framework (the same pattern used by
``scrapers/india_ppac.py``).

Strategy
────────
1. Build the publications-page URL dynamically from the current year, with a
   fallback to the previous year for the Jan-1 transition gap.
2. GET the page HTML.
3. Find the FIRST ``<a href="…xlsx">`` on the page. energy.gov.au lists the
   latest monthly extract at the top under "Attachments"; the older yearly
   links on the same page point to OTHER publication pages, not directly to
   xlsx files, so a "first .xlsx link" heuristic is enough.
4. Download the xlsx and verify the bytes are really an xlsx before writing
   to disk (Content-Type as a hint, magic bytes as the gate).
5. Save under the original filename in ``data/raw/australia/``, overwriting
   any previous copy.

Why ``curl_cffi`` instead of ``requests``
─────────────────────────────────────────
energy.gov.au sits behind a WAF that does TLS fingerprinting — it can spot
Python's TLS handshake as non-browser and silently stalls the connection.
``curl_cffi`` performs the TLS handshake byte-for-byte like Chrome, defeating
the WAF. The rest of the codebase still uses plain ``requests``; this script
is the exception.

Run from the project root:

    python scripts/scrape_australia_v0.py
"""

# ── Imports ────────────────────────────────────────────────────────────────
from datetime import datetime           # for the year-based URL discovery
from pathlib import Path                 # cross-platform path arithmetic

from curl_cffi import requests           # requests-compatible client w/ Chrome TLS fingerprint
from bs4 import BeautifulSoup            # HTML parser, same as scrapers/india_ppac.py


# ── Constants ──────────────────────────────────────────────────────────────

# The publications page contains the calendar year. We format it in per-run
# rather than hardcoding "2026" — otherwise the scraper would silently 404
# every January 1st.
PAGE_URL_TEMPLATE = "https://www.energy.gov.au/publications/australian-petroleum-statistics-{year}"

# Used to turn relative hrefs ("/sites/default/files/...") into absolute URLs.
BASE_URL = "https://www.energy.gov.au"

# Which Chrome version's TLS handshake curl_cffi should impersonate. We
# confirmed "chrome131" defeats energy.gov.au's WAF empirically. Newer
# profiles might be rejected if the WAF doesn't expect them yet; older ones
# might also work but are more likely to look suspicious to other modern WAFs.
IMPERSONATE_PROFILE = "chrome131"

# xlsx files are zip archives, so they ALWAYS start with the ZIP local-file
# header magic bytes b"PK\x03\x04". This is the authoritative check that we
# really downloaded an xlsx — content-type headers can lie, magic bytes can't.
XLSX_MAGIC = b"PK\x03\x04"

# Resolve paths relative to THIS script file so the command works whether you
# run it from country_oil_scraper/ or from elsewhere. ``__file__`` is this
# file; ``.resolve().parent.parent`` walks up: scripts/ → country_oil_scraper/.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw" / "australia"


# ── Helper: discover the working publications-page URL ────────────────────

def find_publications_url(today: datetime | None = None) -> tuple[str, "requests.Response"]:
    """
    Try this calendar year's publications page; fall back to last year.

    Returns (url, response) so the caller doesn't have to re-fetch.
    Raises RuntimeError listing what was tried if neither year returns 200.

    Why "current then previous": the publication is monthly. The only edge
    case where the current year's page doesn't exist yet is the Jan-1
    transition (e.g. early Jan 2027, before DCCEEW launches the -2027 page).
    Two candidates cover that. Walking back further is YAGNI.

    ``today`` is a parameter (default datetime.now()) so this is testable:
    ``find_publications_url(today=datetime(2027, 1, 15))`` simulates next
    January's behaviour without changing the system clock.
    """
    today = today or datetime.now()
    candidates = [today.year, today.year - 1]
    last_error = None
    for year in candidates:
        url = PAGE_URL_TEMPLATE.format(year=year)
        print(f"  Trying year={year}: {url}")
        try:
            resp = requests.get(url, timeout=30, impersonate=IMPERSONATE_PROFILE)
            if resp.ok:
                print(f"  → OK ({resp.status_code})")
                return url, resp
            last_error = f"HTTP {resp.status_code}"
            print(f"  → {last_error}, trying next…")
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"
            print(f"  → FAILED ({last_error}), trying next…")
    raise RuntimeError(
        f"No working publications URL found.\n"
        f"  Tried years: {candidates}\n"
        f"  Last error : {last_error}"
    )


# ── 1. Fetch the publications page ─────────────────────────────────────────

# ``find_publications_url`` does the GET internally and returns the URL it
# settled on plus the response, so we don't have to fetch the page twice.
PAGE_URL, resp = find_publications_url()

# ``raise_for_status()`` throws HTTPError on 4xx / 5xx. We keep it as a
# belt-and-braces — ``find_publications_url`` already filters to .ok
# responses, but if its logic ever changes we'd rather fail loudly here than
# silently parse an error page.
resp.raise_for_status()

print(f"[1] {PAGE_URL}  →  HTTP {resp.status_code}, {len(resp.text):,} chars")


# ── 2. Parse the HTML and find the first .xlsx link ───────────────────────

# "lxml" is the fastest BS4 parser (provided by the lxml package in
# requirements.txt). It's overkill for a small page but keeps us consistent
# with the India PPAC scraper.
soup = BeautifulSoup(resp.text, "lxml")

# ``find_all("a", href=True)`` walks the parsed tree once and yields every
# <a> tag that has a non-empty href attribute. The list comprehension then
# filters down to xlsx links only. ``.lower()`` so we match .xlsx / .XLSX /
# .Xlsx etc. — defensive against odd CMS casing on government sites.
xlsx_links = [
    a["href"]
    for a in soup.find_all("a", href=True)
    if a["href"].lower().endswith(".xlsx")
]

if not xlsx_links:
    raise RuntimeError(
        f"No .xlsx links found on {PAGE_URL}. "
        f"Page layout may have changed — open the URL in a browser and update "
        f"the scraping strategy."
    )

# The publications page renders the newest monthly extract first under the
# "Attachments" heading. Older monthly extracts appear lower on the page (the
# current Australia page surfaces the previous month too), but the first
# match is always the latest.
href = xlsx_links[0]

# Build an absolute URL. The href on this page is relative
# ("/sites/default/files/..."); ``requests.get`` needs scheme + host.
url = href if href.startswith("http") else BASE_URL + href

print(f"[2] Found {len(xlsx_links)} xlsx link(s); taking the first → {url}")


# ── 3. Download with verification ─────────────────────────────────────────

# A small curl_cffi quirk: the Response object is NOT a context manager, so
# ``with requests.get(url) as r:`` raises TypeError. We just call .get() and
# read ``r.content`` directly. For our 2-3 MB file that's fine; for very
# large files we'd reach for curl_cffi's stream=True API (different shape
# than requests' streaming).
r = requests.get(url, timeout=120, impersonate=IMPERSONATE_PROFILE)
r.raise_for_status()

# Server-reported content type. Useful as a sanity hint but NOT
# authoritative — some servers mislabel xlsx as text/html, others as
# application/octet-stream. We log it but only fail on the magic bytes.
content_type = r.headers.get("Content-Type", "<unset>").lower()

# We buffer everything because we want to validate the magic bytes BEFORE
# committing to disk. For multi-GB files we'd stream to a temp file and
# validate after; 2-3 MB easily fits in RAM.
body = r.content

# Soft check: warn if the content-type looks nothing like a spreadsheet,
# but don't abort — the magic-bytes check below is the real gate.
spreadsheet_hints = ("spreadsheet", "excel", "openxml", "octet-stream")
if not any(h in content_type for h in spreadsheet_hints):
    print(
        f"[!] Note: server reported Content-Type={content_type!r}, which "
        f"doesn't look spreadsheet-y. Continuing because magic bytes will "
        f"catch any real problem."
    )

# Hard check: an xlsx is a zip, so it must start with "PK\x03\x04". This
# catches the common failure mode where the server returns an HTML error
# page (e.g. maintenance notice) but tags it with a spreadsheet content-type.
if not body.startswith(XLSX_MAGIC):
    raise RuntimeError(
        f"Downloaded {len(body)} bytes from {url} but they don't look like "
        f"an xlsx.\n"
        f"  Content-Type: {content_type}\n"
        f"  First 16 bytes: {body[:16]!r}\n"
        f"Either the URL is wrong or the server returned an error page."
    )

print(
    f"[3] Downloaded {len(body) / 1024:.0f} KB, "
    f"content-type={content_type!r}, magic bytes OK"
)


# ── 4. Save under the original filename ───────────────────────────────────

# ``Path(href).name`` strips the directory portion of the href
# ("/sites/default/files/2026-04/…") and gives us just the filename. We keep
# the original name so it's obvious at a glance which month a file refers to.
filename = Path(href).name

# ``mkdir(parents=True, exist_ok=True)`` creates the directory chain and is a
# no-op if it already exists — saves us a try/except FileExistsError.
RAW_DIR.mkdir(parents=True, exist_ok=True)

out_path = RAW_DIR / filename

# ``write_bytes`` overwrites any previous copy at this path. That's what we
# want in this phase — we always pull the latest, and don't keep snapshots.
# (Phase 2's class version will switch to timestamped names so we can keep
# a history.)
out_path.write_bytes(body)

print(f"[4] Saved → {out_path}")
print(f"    {out_path.stat().st_size / 1024:.0f} KB on disk")
