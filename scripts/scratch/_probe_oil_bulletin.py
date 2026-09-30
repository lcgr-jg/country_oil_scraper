"""Probe EU Oil Bulletin page + historical workbook structure."""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urljoin

import pandas as pd
import requests

PAGE = "https://energy.ec.europa.eu/data-and-analysis/weekly-oil-bulletin_en"
OUT = Path("data/raw/eu_oil_bulletin")
OUT.mkdir(parents=True, exist_ok=True)

r = requests.get(PAGE, timeout=90)
r.raise_for_status()
html = r.text
print("page status", r.status_code, "bytes", len(html))

# Collect download-ish links
hrefs = re.findall(r'href="([^"]+)"', html)
cands = []
for h in hrefs:
    low = h.lower()
    if "xlsx" in low or "document/download" in low or "oil_bulletin" in low or "oil-bulletin" in low:
        cands.append(urljoin(PAGE, h))

print("candidate links:")
for c in sorted(set(cands)):
    print(" ", c)

# Prefer history workbook
history = [c for c in set(cands) if "history" in c.lower() or "maticni" in c.lower() or "2005" in c.lower()]
print("history candidates:", history)

# Fallback known UUID from older newsroom post
FALLBACK = (
    "https://energy.ec.europa.eu/document/download/"
    "906e60ca-8b6a-44e7-8589-652854d2fd3f_en"
    "?filename=Weekly_Oil_Bulletin_Prices_History_maticni_4web.xlsx"
)

url = history[0] if history else FALLBACK
print("downloading:", url)
resp = requests.get(url, timeout=180, allow_redirects=True)
print("dl status", resp.status_code, "ctype", resp.headers.get("content-type"), "len", len(resp.content))
print("content starts", resp.content[:8])

# Try to get filename from content-disposition
cd = resp.headers.get("content-disposition", "")
print("content-disposition", cd)
fname = "Weekly_Oil_Bulletin_Prices_History.xlsx"
m = re.search(r'filename="?([^";]+)"?', cd)
if m:
    fname = m.group(1)
path = OUT / fname
path.write_bytes(resp.content)
print("saved", path, path.stat().st_size)

xl = pd.ExcelFile(path)
print("sheets:", xl.sheet_names)
for sheet in xl.sheet_names[:12]:
    df = pd.read_excel(path, sheet_name=sheet, header=None)
    print("\n===", sheet, "shape", df.shape, "===")
    print(df.head(12).to_string())
