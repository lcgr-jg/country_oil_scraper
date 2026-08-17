"""Check which ARE liquid-fuel bulletin URLs return 200."""
from __future__ import annotations

import re
from pathlib import Path

import requests

CMS = "https://cms.are.waw.pl"
PAGE = "https://www.are.waw.pl/pl/badania-statystyczne/wynikowe-informacje-statystyczne"
HTML = Path(__file__).with_name("_are_page.html")
text = HTML.read_text(encoding="utf-8") if HTML.exists() else requests.get(
    PAGE, headers={"User-Agent": "country_oil_scraper/1.0"}, timeout=60
).text

paths = sorted(set(re.findall(r"/uploads/[^\"\\]+?\.xls", text, re.I)))
cands = [
    p
    for p in paths
    if "Biuletyn_" in p
    or re.search(r"/inf_\d{4}_", p, re.I)
    or "rynku_pal" in p.lower()
]
if not cands:
    raise SystemExit("no candidates")

ok: list[str] = []
fail: list[tuple[str, int]] = []
for path in cands:
    resp = requests.head(
        CMS + path,
        headers={"User-Agent": "country_oil_scraper/1.0"},
        timeout=30,
        allow_redirects=True,
    )
    if resp.status_code == 200:
        ok.append(path)
    else:
        fail.append((path, resp.status_code))

print("ok", len(ok), "fail", len(fail))
print("first ok", ok[:2])
print("last ok", ok[-2:])
print("fail examples", fail[:5])
